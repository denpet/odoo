import json
import logging
import zlib
from datetime import date, datetime, time

import pytz

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_TZ = "Asia/Manila"
CHECKOUT_TIME = time(12, 0)  # folio check-out on the departure date
CHECKIN_TIME = time(14, 0)  # used only when the check-in arrives outside the stay dates


class SirvoyWebhookEvent(models.Model):
    """One booking callback received from Sirvoy (kept for audit and reprocessing)."""

    _name = "sirvoy.webhook.event"
    _description = "Sirvoy Webhook Event"
    _order = "id desc"
    _rec_name = "booking_id"

    booking_id = fields.Char("Sirvoy Booking", index=True, readonly=True)
    event = fields.Char(readonly=True, help="Sirvoy event: new, modified, ...")
    generated_at = fields.Char("Generated At (Sirvoy)", readonly=True)
    guest_name = fields.Char(readonly=True)
    checked_in = fields.Boolean(readonly=True)
    cancelled = fields.Boolean(readonly=True)
    state = fields.Selection(
        [("new", "Received"), ("done", "Folio created"), ("ignored", "Ignored"), ("error", "Error")],
        default="new",
        required=True,
        readonly=True,
        index=True,
    )
    message = fields.Text(readonly=True)
    payload = fields.Text(readonly=True)
    folio_ids = fields.One2many("hotel.folio", "sirvoy_event_id", "Created Folios", readonly=True)

    @api.model
    def create_from_payload(self, payload):
        return self.create(
            {
                "booking_id": str(payload.get("bookingId") or ""),
                "event": payload.get("event"),
                "generated_at": payload.get("generatedAt"),
                "guest_name": self._sirvoy_guest_name(payload, {}),
                "checked_in": bool(payload.get("bookingIsCheckedIn")),
                "cancelled": bool(payload.get("cancelled")),
                "payload": json.dumps(payload, indent=2, ensure_ascii=False),
            }
        )

    def _run(self):
        """Process each event in its own savepoint; failures are stored on the event."""
        for event in self:
            try:
                with self.env.cr.savepoint():
                    state, message = event._process()
                event.write({"state": state, "message": message})
            except UserError as e:
                _logger.warning("Sirvoy webhook: booking %s not processed: %s", event.booking_id, e)
                event.write({"state": "error", "message": str(e)})
            except Exception as e:  # noqa: BLE001 - every failure must end up on the event
                _logger.exception("Sirvoy webhook: booking %s failed", event.booking_id)
                event.write({"state": "error", "message": str(e)})

    def action_reprocess(self):
        self._run()
        return True

    # ------------------------------------------------------------------ processing

    def _process(self):
        """Create guest + open folio per room when the booking is checked in.

        Returns (state, message). Raises UserError on data problems (nothing is created then).
        """
        self.ensure_one()
        data = json.loads(self.payload)
        booking_id = str(data.get("bookingId") or "")
        if not booking_id:
            raise UserError(self.env._("The payload has no bookingId."))
        if data.get("cancelled"):
            return "ignored", self.env._("Booking is cancelled.")
        if not data.get("bookingIsCheckedIn"):
            return "ignored", self.env._("Booking is not checked in.")
        if data.get("bookingIsCheckedOut"):
            return "ignored", self.env._("Booking is already checked out.")
        rooms = data.get("rooms") or []
        if not rooms:
            raise UserError(self.env._("Checked-in booking %s has no rooms.", booking_id))

        company = self.env.company
        currency = company.currency_id
        if data.get("currency") and data["currency"] != currency.name:
            raise UserError(
                self.env._(
                    "Booking %(booking)s is in %(sirvoy)s but the company currency is %(odoo)s.",
                    booking=booking_id,
                    sirvoy=data["currency"],
                    odoo=currency.name,
                )
            )

        # Serialise concurrent callbacks for the same booking (Sirvoy may send several).
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [zlib.crc32(f"sirvoy:{booking_id}".encode())])
        Folio = self.env["hotel.folio"]
        booking_folios = Folio.search([("sirvoy_booking_id", "=", booking_id)])

        created = Folio
        for room in rooms:
            key = self._sirvoy_room_key(room)
            if booking_folios.filtered(lambda f, key=key: f.sirvoy_room_key == key):
                continue
            # Booking-level extras and surcharges go on the booking's first folio.
            with_extras = not booking_folios and not created
            created |= self._create_folio(data, room, key, company, with_extras)

        if not created:
            return "ignored", self.env._("Folios already exist: %s", ", ".join(booking_folios.mapped("display_name")))
        return "done", self.env._("Created %s", ", ".join(created.mapped("display_name")))

    @api.model
    def _sirvoy_room_key(self, room):
        return f"{room.get('RoomId') or room.get('RoomName')}/{room.get('arrivalDate') or ''}"

    @api.model
    def _sirvoy_guest_name(self, data, room):
        guest = data.get("guest")
        guest = guest if isinstance(guest, dict) else {}
        name = str(room.get("guestName") or "").strip()
        if not name:
            name = " ".join(filter(None, [(guest.get("firstName") or "").strip(),
                                          (guest.get("lastName") or "").strip()]))
        return name or (guest.get("businessName") or "").strip() or f"Sirvoy {data.get('bookingId')}"

    def _find_room(self, room_name):
        Room = self.env["hotel.room"]
        room = Room.search([("sirvoy_room_name", "=", room_name)], limit=1)
        if not room:
            room = Room.search([("name", "=", room_name), ("sirvoy_room_name", "=", False)], limit=1)
        if not room:
            raise UserError(
                self.env._(
                    "No hotel room matches Sirvoy room '%s'. Name the Odoo room the same, or set "
                    "'Sirvoy Room Name' on it, then reprocess this event.",
                    room_name,
                )
            )
        return room

    def _stay_datetimes(self, arrival, departure, company):
        """Folio check-in/out as naive UTC: now (if within the stay) -> departure 12:00 local."""
        tz = pytz.timezone(company.partner_id.tz or self.env.user.tz or DEFAULT_TZ)

        def to_utc(day, at):
            return tz.localize(datetime.combine(day, at)).astimezone(pytz.utc).replace(tzinfo=None)

        now = fields.Datetime.now()
        local_today = pytz.utc.localize(now).astimezone(tz).date()
        checkout = to_utc(departure, CHECKOUT_TIME)
        if arrival <= local_today and now < checkout:
            checkin = now.replace(microsecond=0)
        else:
            checkin = to_utc(arrival, CHECKIN_TIME)
        return checkin, checkout

    @api.model
    def _split_amount(self, qty, total, currency):
        """(qty, unit price) whose product is exactly ``total``; else (1, total)."""
        if qty and qty > 0:
            unit = currency.round(total / qty)
            if currency.is_zero(unit * qty - total):
                return qty, unit
        return 1, currency.round(total)

    @api.model
    def _float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _sirvoy_product(self, code, name, company):
        Product = self.env["product.product"].with_company(company)
        product = Product.search([("default_code", "=", code), ("company_id", "in", (company.id, False))], limit=1)
        if not product:
            product = Product.create(
                {
                    "name": name,
                    "default_code": code,
                    "type": "service",
                    "sale_ok": True,
                    "purchase_ok": False,
                    "invoice_policy": "order",
                    "company_id": company.id,
                    "taxes_id": [Command.set(company.account_sale_tax_id.ids)],
                }
            )
        return product

    def _line_taxes(self, product, company):
        taxes = product.with_company(company).taxes_id.filtered(lambda t: t.company_id == company)
        return self.env["account.tax"]._sirvoy_tax_included(taxes)

    def _create_folio(self, data, room, key, company, with_extras):
        booking_id = str(data["bookingId"])
        currency = company.currency_id
        room_name = str(room.get("RoomName") or "").strip()
        if not room_name:
            raise UserError(self.env._("A room of booking %s has no RoomName.", booking_id))
        hotel_room = self._find_room(room_name)

        try:
            arrival = date.fromisoformat(room.get("arrivalDate") or data["arrivalDate"])
            departure = date.fromisoformat(room.get("departureDate") or data["departureDate"])
        except (KeyError, TypeError, ValueError) as e:
            raise UserError(self.env._("Invalid arrival/departure date in booking %s.", booking_id)) from e
        nights = (departure - arrival).days
        if nights <= 0:
            raise UserError(self.env._("Room %(room)s of booking %(booking)s has no nights.",
                                       room=room_name, booking=booking_id))
        checkin, checkout = self._stay_datetimes(arrival, departure, company)

        guest = data.get("guest") or {}
        partner = self.env["res.partner"].create(
            {
                "name": f"{self._sirvoy_guest_name(data, room)} #{room_name}",
                "email": guest.get("email") or False,
                "phone": guest.get("phone") or False,
                "ref": f"Sirvoy {booking_id}",
                "customer_rank": 1,
                "company_id": False,
            }
        )

        room_total = room.get("roomTotal")
        if room_total is None:
            room_total = self._float(room.get("price")) * self._float(room.get("quantity"), 1.0)
        qty, unit = self._split_amount(nights, self._float(room_total), currency)
        room_product = hotel_room.product_id
        room_lines = [
            Command.create(
                {
                    "product_id": room_product.id,
                    "name": self.env._("%(room)s, %(nights)s night(s), Sirvoy booking %(booking)s",
                                       room=hotel_room.name, nights=nights, booking=booking_id),
                    "checkin_date": checkin,
                    "checkout_date": checkout,
                    "product_uom_qty": qty,
                    "price_unit": unit,
                    "tax_ids": [Command.set(self._line_taxes(room_product, company).ids)],
                }
            )
        ]

        service_lines = []
        if with_extras:
            extra = self._sirvoy_product("SIRVOY-EXTRA", "Sirvoy Additional Item", company)
            for item in data.get("additionalItems") or []:
                item_qty = self._float(item.get("quantity"), 1.0)
                total = item.get("itemTotal")
                total = self._float(total) if total is not None else self._float(item.get("price")) * item_qty
                if currency.is_zero(total):
                    continue
                qty_i, unit_i = self._split_amount(item_qty, total, currency)
                label = item.get("description") or extra.name
                if item.get("specificDate"):
                    label = f"{label} ({item['specificDate']})"
                service_lines.append(self._service_line(extra, label, qty_i, unit_i, checkin, checkout, company))
            surcharges = self._float(data.get("totalSurcharges"))
            if not currency.is_zero(surcharges):
                surcharge = self._sirvoy_product("SIRVOY-SURCHARGE", "Sirvoy Surcharges", company)
                service_lines.append(
                    self._service_line(surcharge, surcharge.name, 1, currency.round(surcharges), checkin, checkout, company)
                )

        folio = self.env["hotel.folio"].create(
            {
                "partner_id": partner.id,
                "company_id": company.id,
                "date_order": checkin,
                "checkin_date": checkin,
                "checkout_date": checkout,
                "duration": nights,
                "sirvoy_booking_id": booking_id,
                "sirvoy_room_key": key,
                "sirvoy_event_id": self.id,
                "room_line_ids": room_lines,
                "service_line_ids": service_lines,
            }
        )
        if folio.currency_id != currency:
            raise UserError(self.env._("The folio pricelist currency %(folio)s differs from %(company)s.",
                                       folio=folio.currency_id.name, company=currency.name))
        hotel_room.write({"status": "occupied", "isroom": False})
        return folio

    def _service_line(self, product, label, qty, unit, checkin, checkout, company):
        return Command.create(
            {
                "product_id": product.id,
                "name": label,
                "product_uom_qty": qty,
                "price_unit": unit,
                "ser_checkin_date": checkin,
                "ser_checkout_date": checkout,
                "tax_ids": [Command.set(self._line_taxes(product, company).ids)],
            }
        )
