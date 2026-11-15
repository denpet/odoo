from odoo import fields, models


class HotelFolio(models.Model):
    _inherit = "hotel.folio"

    sirvoy_booking_id = fields.Char("Sirvoy Booking", index="btree_not_null", readonly=True, copy=False)
    sirvoy_room_key = fields.Char(
        readonly=True, copy=False, help="Sirvoy room id and arrival date this folio was created for."
    )
    sirvoy_event_id = fields.Many2one("sirvoy.webhook.event", "Sirvoy Event", readonly=True, copy=False)

    _sirvoy_booking_room_uniq = models.Constraint(
        "UNIQUE(sirvoy_booking_id, sirvoy_room_key)",
        "A folio already exists for this Sirvoy booking room.",
    )
