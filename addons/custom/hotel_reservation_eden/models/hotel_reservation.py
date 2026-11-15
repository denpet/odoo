from odoo import api, models
from odoo.exceptions import ValidationError


class HotelReservation(models.Model):
    _inherit = "hotel.reservation"

    @api.constrains("reservation_line", "adults", "children")
    def _check_reservation_rooms(self):
        # Without any line, upstream reports "Room Capacity Exceeded"
        # (capacity 0), which hides the real problem: no room was chosen.
        # Duplicates are skipped because copy() does not copy the lines.
        if not self.env.context.get("duplicate"):
            for reservation in self:
                if not reservation.reservation_line:
                    raise ValidationError(
                        self.env._(
                            "Please add at least one room on the "
                            "Reservation Line tab (choose a Room Type, "
                            "then the Room)."
                        )
                    )
        return super()._check_reservation_rooms()


class HotelReservationLine(models.Model):
    _inherit = "hotel.reservation.line"

    @api.onchange("categ_id")
    def on_change_categ(self):
        # Upstream raises when booking dates are missing. This onchange also
        # fires when a new line is created (categ_id still empty), so the
        # raise aborted opening the line dialog and the Room Type field was
        # never shown. Only act once a type is chosen, and warn instead.
        if not self.categ_id:
            return
        if not self.line_id.checkin or not self.line_id.checkout:
            return {
                "warning": {
                    "title": self.env._("Booking dates missing"),
                    "message": self.env._(
                        "Before choosing a room, select the Booking Date "
                        "(check-in and check-out) on the reservation form, "
                        "so only available rooms are offered."
                    ),
                }
            }
        return super().on_change_categ()
