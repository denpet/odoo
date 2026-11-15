import copy
import json
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from ..hooks import TOKEN_PARAM


@tagged("post_install", "-at_install")
class TestSirvoyWebhook(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.env["ir.config_parameter"].sudo().set_param(TOKEN_PARAM, "s3cret")
        cls.vat = cls.env["account.tax"].create({
            "name": "Test VAT 12%", "amount": 12, "amount_type": "percent", "type_tax_use": "sale",
            "price_include_override": "tax_excluded",
        })
        cls.company.account_sale_tax_id = cls.vat
        room_type = cls.env["hotel.room.type"].create({"name": "Sirvoy Test Type"})

        def room(name, **kw):
            return cls.env["hotel.room"].create({
                "name": name, "room_categ_id": room_type.id, "capacity": 2, "list_price": 999.0,
                "taxes_id": [(6, 0, cls.vat.ids)], **kw,
            })

        cls.room_101 = room("S-101", sirvoy_room_name="101")
        cls.room_102 = room("102")
        today = fields.Date.context_today(cls.env["res.users"])
        cls.arrival, cls.departure = today, today + timedelta(days=3)
        cls.payload = {
            "version": "2.0",
            "generatedAt": "2026-11-15T12:11:53.639+00:00",
            "event": "modified",
            "propertyId": 1,
            "bookingId": 4711,
            "arrivalDate": str(cls.arrival),
            "departureDate": str(cls.departure),
            "cancelled": False,
            "bookingIsCheckedIn": True,
            "bookingIsCheckedOut": False,
            "guest": {"firstName": "Jane", "lastName": "Doe", "email": "jane@example.com", "phone": "+63 900"},
            "rooms": [
                {"RoomTypeName": "Double", "RoomName": "101", "RoomId": 11, "arrivalDate": str(cls.arrival),
                 "departureDate": str(cls.departure), "adults": 2, "quantity": 3, "price": 1500,
                 "roomTotal": 4500, "guestName": ""},
            ],
            "additionalItems": [
                {"description": "Breakfast", "specificDate": None, "quantity": 2, "price": 350, "itemTotal": 700},
            ],
            "currency": cls.currency.name,
            "totalPrice": 5200,
            "totalSurcharges": 100,
            "totalPriceIncludingSurcharges": 5300,
        }

    def _post(self, payload, token="s3cret"):
        url = "/api/sirvoy" + (f"?token={token}" if token else "")
        return self.url_open(url, data=json.dumps(payload), headers={"Content-Type": "application/json"})

    def _payload(self, **changes):
        payload = copy.deepcopy(self.payload)
        payload.update(changes)
        return payload

    def _folios(self, booking="4711"):
        return self.env["hotel.folio"].search([("sirvoy_booking_id", "=", booking)])

    def test_health_check_get(self):
        res = self.url_open("/api/sirvoy")
        self.assertEqual(res.status_code, 200)

    def test_wrong_token_rejected(self):
        self.assertEqual(self._post(self.payload, token="nope").status_code, 403)
        self.assertEqual(self._post(self.payload, token=None).status_code, 403)
        self.assertFalse(self._folios())

    def test_invalid_json(self):
        res = self.url_open("/api/sirvoy?token=s3cret", data="not json")
        self.assertEqual(res.status_code, 400)

    def test_check_in_creates_customer_and_folio(self):
        res = self._post(self.payload)
        self.assertEqual(res.status_code, 200)
        folio = self._folios()
        self.assertEqual(len(folio), 1)
        self.assertEqual(folio.partner_id.name, "Jane Doe #101")
        self.assertEqual(folio.partner_id.email, "jane@example.com")
        self.assertIn(folio.state, ("draft", "sent"))
        self.assertLessEqual(folio.checkin_date, fields.Datetime.now())

        line = folio.room_line_ids
        self.assertEqual(line.product_id, self.room_101.product_id)
        self.assertEqual(line.product_uom_qty, 3)
        self.assertAlmostEqual(line.price_unit, 1500)
        self.assertTrue(line.tax_ids.price_include)
        self.assertAlmostEqual(line.price_total, 4500)
        self.assertAlmostEqual(line.price_tax, 482.14, places=2)
        self.assertEqual(line.checkout_date.date(), self.departure)

        self.assertEqual(len(folio.service_line_ids), 2)  # breakfast + surcharges
        self.assertAlmostEqual(folio.amount_total, 5300)
        self.assertEqual(self.room_101.status, "occupied")

        event = folio.sirvoy_event_id
        self.assertEqual(event.state, "done")

    def test_repeated_callback_is_idempotent(self):
        self._post(self.payload)
        self._post(self._payload(generatedAt="2026-11-15T13:00:00+00:00"))
        self.assertEqual(len(self._folios()), 1)
        last = self.env["sirvoy.webhook.event"].search([("booking_id", "=", "4711")], limit=1)
        self.assertEqual(last.state, "ignored")

    def test_not_checked_in_or_cancelled_ignored(self):
        self._post(self._payload(bookingIsCheckedIn=False, event="new"))
        self._post(self._payload(cancelled=True))
        self.assertFalse(self._folios())
        events = self.env["sirvoy.webhook.event"].search([("booking_id", "=", "4711")])
        self.assertEqual(set(events.mapped("state")), {"ignored"})

    def test_multi_room_one_folio_per_room(self):
        rooms = self.payload["rooms"] + [{
            "RoomName": "102", "RoomId": 12, "arrivalDate": str(self.arrival),
            "departureDate": str(self.arrival + timedelta(days=1)), "quantity": 1, "price": 1000,
            "roomTotal": 1000, "guestName": "John Roe",
        }]
        self._post(self._payload(rooms=rooms))
        folios = self._folios()
        self.assertEqual(sorted(folios.partner_id.mapped("name")), ["Jane Doe #101", "John Roe #102"])
        folio_102 = folios.filtered(lambda f: f.room_line_ids.product_id == self.room_102.product_id)
        self.assertAlmostEqual(folio_102.amount_total, 1000)
        self.assertFalse(folio_102.service_line_ids)  # extras only on the first folio
        self.assertAlmostEqual(sum(folios.mapped("amount_total")), 6300)

    def test_uneven_total_kept_exact(self):
        rooms = copy.deepcopy(self.payload["rooms"])
        rooms[0]["roomTotal"] = 4000  # 1333.33 x 3 != 4000
        self._post(self._payload(rooms=rooms, additionalItems=[], totalSurcharges=0))
        folio = self._folios()
        self.assertAlmostEqual(folio.amount_total, 4000)

    def test_unknown_room_logged_and_reprocessable(self):
        rooms = copy.deepcopy(self.payload["rooms"])
        rooms[0]["RoomName"] = "999"
        res = self._post(self._payload(rooms=rooms))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(self._folios())
        self.assertFalse(self.env["res.partner"].search([("name", "=", "Jane Doe #999")]))
        event = self.env["sirvoy.webhook.event"].search([("booking_id", "=", "4711")], limit=1)
        self.assertEqual(event.state, "error")
        self.assertIn("999", event.message)

        self.room_102.sirvoy_room_name = "999"
        event.action_reprocess()
        self.assertEqual(event.state, "done")
        self.assertEqual(event.folio_ids.partner_id.name, "Jane Doe #999")
