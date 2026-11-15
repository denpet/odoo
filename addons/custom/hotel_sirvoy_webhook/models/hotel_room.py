from odoo import fields, models


class HotelRoom(models.Model):
    _inherit = "hotel.room"

    sirvoy_room_name = fields.Char(
        "Sirvoy Room Name",
        index="btree_not_null",
        help="Room name/number exactly as in Sirvoy. Leave empty if the Odoo room name "
        "is the same as in Sirvoy.",
    )
