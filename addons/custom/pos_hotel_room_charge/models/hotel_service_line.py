from odoo import fields, models


class HotelServiceLine(models.Model):
    _inherit = "hotel.service.line"

    pos_order_id = fields.Many2one(
        "pos.order",
        "POS Order",
        readonly=True,
        index="btree_not_null",
        ondelete="restrict",
        help="Point of Sale order that was charged to the room with this line.",
    )
