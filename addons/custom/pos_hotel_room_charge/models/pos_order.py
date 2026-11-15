from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero, float_round


class PosOrder(models.Model):
    _inherit = "pos.order"

    # Set by the POS frontend. Plain integer because the POS does not load hotel.folio.
    room_charge_folio_ref = fields.Integer(copy=False)
    room_charge_label = fields.Char("Charged To", copy=False, readonly=True)
    hotel_folio_id = fields.Many2one(
        "hotel.folio",
        "Hotel Folio",
        compute="_compute_hotel_folio_id",
        store=True,
        readonly=True,
        index="btree_not_null",
    )

    @api.depends("room_charge_folio_ref")
    def _compute_hotel_folio_id(self):
        Folio = self.env["hotel.folio"].sudo()
        for order in self:
            ref = order.room_charge_folio_ref
            order.hotel_folio_id = Folio.browse(ref).exists() if ref else False

    def _room_charge_payments(self):
        return self.payment_ids.filtered(lambda p: p.payment_method_id.is_room_charge)

    def _room_charge_validate(self):
        """Raise if a room-charge order can't be accepted. Runs before the order is marked paid."""
        self.ensure_one()
        payments = self._room_charge_payments()
        if not payments:
            if self.room_charge_folio_ref or self.room_charge_label:
                self.write({"room_charge_folio_ref": 0, "room_charge_label": False})
            return
        if self.payment_ids - payments:
            raise UserError(self.env._("Charge to Room must be the only payment on order %s.", self.name))
        if self.to_invoice:
            raise UserError(
                self.env._("Order %s is charged to a room; it is invoiced with the folio, "
                           "not from the POS.", self.name)
            )
        folio = self.hotel_folio_id
        if not folio:
            raise UserError(self.env._("Select the guest's room for order %s.", self.name))
        if self._room_charge_already_posted():
            return
        folio._room_charge_check_eligible()
        if folio.sudo().currency_id != self.currency_id:
            raise UserError(self.env._("The folio and the POS use different currencies."))

    def _room_charge_already_posted(self):
        return bool(self.env["hotel.service.line"].sudo().search_count([("pos_order_id", "=", self.id)]))

    def _process_saved_order(self, draft):
        if not draft and self.state != "cancel":
            self._room_charge_validate()
        res = super()._process_saved_order(draft)
        if self.state in ("paid", "done"):
            self._room_charge_post_to_folio()
        return res

    def _room_charge_line_vals(self, line, product):
        """Itemised folio line, tax included, using the no-tax clearing product."""
        name = line.full_product_name or line.product_id.display_name
        if line.customer_note:
            name = f"{name} ({line.customer_note})"
        name = f"{name} [{self.pos_reference or self.name}]"
        qty = line.qty
        total = line.price_subtotal_incl
        digits = self.env["decimal.precision"].precision_get("Product Price")
        price = float_round(total / qty, precision_digits=digits)
        if float_compare(self.currency_id.round(price * qty), total, precision_rounding=self.currency_id.rounding):
            # Unit price can't be expressed exactly: keep the amount right, show qty in the text.
            name = f"{qty:g} x {name}"
            sign = 1 if qty > 0 else -1
            qty, price = sign, total * sign
        return {
            "product_id": product.id,
            "name": name,
            "product_uom_qty": qty,
            "price_unit": price,
            "tax_ids": [Command.clear()],
        }

    def _room_charge_post_to_folio(self):
        for order in self:
            payments = order._room_charge_payments()
            if not payments or order._room_charge_already_posted():
                continue
            folio = order.hotel_folio_id.sudo()
            product = payments[0].payment_method_id.room_charge_product_id
            sol_vals = []
            for line in order.lines:
                if float_is_zero(line.qty, precision_digits=6) or line.currency_id.is_zero(line.price_subtotal_incl):
                    continue
                sol_vals.append({**order._room_charge_line_vals(line, product), "order_id": folio.order_id.id})
            if not sol_vals:
                continue
            sols = self.env["sale.order.line"].sudo().create(sol_vals)
            self.env["hotel.service.line"].sudo().create([
                {
                    "folio_id": folio.id,
                    "service_line_id": sol.id,
                    "pos_order_id": order.id,
                    "ser_checkin_date": order.date_order,
                    "ser_checkout_date": order.date_order,
                }
                for sol in sols
            ])
            vals = {"room_charge_label": order.room_charge_label or folio._room_charge_label()}
            if not order.partner_id:
                vals["partner_id"] = folio.partner_id.id
            order.write(vals)
            folio.order_id.message_post(
                body=self.env._(
                    "POS order %(order)s charged to this folio: %(amount)s",
                    order=order.pos_reference or order.name,
                    amount=order.currency_id.format(order.amount_total),
                )
            )
