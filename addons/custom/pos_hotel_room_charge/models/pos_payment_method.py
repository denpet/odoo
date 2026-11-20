from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    is_room_charge = fields.Boolean(
        "Charge to Room",
        help="Orders paid with this method are added to a checked-in guest's hotel folio "
        "and billed at checkout.",
    )
    room_charge_product_id = fields.Many2one(
        "product.product",
        "Room Charge Product",
        domain=[("type", "=", "service")],
        help="Service product used for the folio lines. Each line keeps the VAT and income "
        "account of the product sold in the POS, so revenue and VAT are booked once, by the "
        "folio invoice at checkout.",
    )

    @api.constrains("is_room_charge", "room_charge_product_id", "journal_id", "outstanding_account_id")
    def _check_room_charge_config(self):
        for method in self.filtered("is_room_charge"):
            if method.type != "bank":
                raise ValidationError(self.env._("A Charge to Room method needs a Bank journal."))
            if method.split_transactions:
                raise ValidationError(self.env._("A Charge to Room method can't split transactions."))
            product = method.room_charge_product_id
            if not product:
                raise ValidationError(self.env._("Set a Room Charge Product on %s.", method.name))
            if product.type != "service":
                raise ValidationError(
                    self.env._("Room Charge Product %s must be a service, so the folio doesn't "
                               "deliver the items a second time.", product.display_name)
                )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["is_room_charge"]

    @api.model
    def _room_charge_setup_company(self, company):
        """Create clearing account, journal, product and payment method for one company.

        Idempotent: returns the existing method if the company already has one.
        """
        self = self.with_company(company)
        existing = self.search([("is_room_charge", "=", True), ("company_id", "=", company.id)], limit=1)
        if existing:
            return existing

        Account = self.env["account.account"]
        base = company.transfer_account_id  # a current-asset account; number the new one next to it
        code = base.code if base and base.code and base.code.isdigit() else "101400"
        code_num = int(code)
        while Account.search_count([("code", "=", str(code_num)), ("company_ids", "in", company.id)]):
            code_num += 1
        clearing = Account.create({
            "name": "Guest Ledger (Room Charges)",
            "code": str(code_num),
            "account_type": "asset_current",
            "reconcile": True,
            "company_ids": [(6, 0, company.ids)],
        })

        journal_code = "ROOM"
        Journal = self.env["account.journal"]
        while Journal.search_count([("code", "=", journal_code), ("company_id", "=", company.id)]):
            journal_code = journal_code[:4] + "X"
        journal = Journal.create({
            "name": "Room Charges",
            "code": journal_code,
            "type": "bank",
            "company_id": company.id,
        })

        product = self.env["product.product"].create({
            "name": "Restaurant / POS Room Charge",
            "type": "service",
            "sale_ok": True,
            "purchase_ok": False,
            "list_price": 0.0,
            "taxes_id": [(5, 0, 0)],
            "invoice_policy": "order",
            "company_id": company.id,
        })
        product.with_company(company).property_account_income_id = clearing

        method = self.create({
            "name": "Charge to Room",
            "journal_id": journal.id,
            "outstanding_account_id": clearing.id,
            "is_room_charge": True,
            "room_charge_product_id": product.id,
            "company_id": company.id,
        })

        configs = self.env["pos.config"].search([("company_id", "=", company.id)])
        for config in configs:
            if config.current_session_id:
                continue  # can't change payment methods while a session is open
            config.payment_method_ids = [(4, method.id)]
        return method
