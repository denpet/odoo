from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class HotelFolio(models.Model):
    _inherit = "hotel.folio"

    pos_order_ids = fields.One2many(
        "pos.order", "hotel_folio_id", "POS Room Charges", readonly=True
    )
    pos_order_count = fields.Integer(compute="_compute_pos_order_count")

    def _compute_pos_order_count(self):
        for folio in self:
            folio.pos_order_count = len(folio.pos_order_ids)

    @api.model
    def _room_charge_domain(self):
        """Folios that can receive room charges: open and checked in right now."""
        now = fields.Datetime.now()
        return [
            ("state", "in", ("draft", "sent", "sale")),
            ("checkin_date", "<=", now),
            ("checkout_date", ">=", now),
        ]

    def _room_charge_label(self):
        self.ensure_one()
        rooms = ", ".join(self.room_line_ids.mapped("product_id.name")) or "-"
        return f"Room {rooms} - {self.partner_id.name} - {self.display_name}"

    @api.model
    def get_room_charge_folios(self, company_id=False):
        """Called by the POS: list folios a cashier may charge to."""
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(self.env._("Only Point of Sale users can list room charges."))
        domain = self._room_charge_domain()
        if company_id:
            domain.append(("company_id", "=", company_id))
        folios = self.sudo().search(domain, order="checkin_date, id")
        return [
            {
                "id": folio.id,
                "label": folio._room_charge_label(),
                "guest": folio.partner_id.name,
                "rooms": folio.room_line_ids.mapped("product_id.name"),
                "folio": folio.display_name,
            }
            for folio in folios
        ]

    def _room_charge_check_eligible(self):
        self.ensure_one()
        if not self.sudo().filtered_domain(self._room_charge_domain()):
            raise UserError(
                self.env._(
                    "Folio %s can't receive room charges: it must be open (not cancelled) "
                    "and the guest must be checked in today.",
                    self.sudo().display_name,
                )
            )

    def action_view_pos_room_charges(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("POS Room Charges"),
            "res_model": "pos.order",
            "view_mode": "list,form",
            "domain": [("hotel_folio_id", "=", self.id)],
        }
