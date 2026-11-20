from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    room_charge_account_id = fields.Many2one(
        "account.account",
        "Room Charge Income Account",
        readonly=True,
        copy=False,
        help="Income account of the POS product charged to the room. The folio invoice books "
        "the line there instead of on the generic room-charge product's account.",
    )

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        if self.room_charge_account_id and res.get("display_type", "product") == "product":
            res["account_id"] = self.room_charge_account_id.id
        return res
