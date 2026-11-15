from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestRoomCharge(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref("hotel.group_hotel_manager") | cls.env.ref("sales_team.group_sale_manager")
        cls.config = cls.basic_config
        cls.room_pm = cls.env["pos.payment.method"]._room_charge_setup_company(cls.env.company)
        cls.clearing = cls.room_pm.outstanding_account_id
        cls.vat = cls.env["account.tax"].create({
            "name": "VAT 12%", "amount": 12, "amount_type": "percent", "type_tax_use": "sale",
        })
        cls.beer = cls.create_product("Beer", cls.categ_basic, 100.0, tax_ids=cls.vat.ids)
        now = fields.Datetime.now()
        cls.folio = cls.env["hotel.folio"].create({
            "partner_id": cls.customer.id,
            "checkin_date": now - timedelta(hours=2),
            "checkout_date": now + timedelta(days=1),
        })

    def _order(self, qty, payments, folio=None):
        folio = folio or self.folio
        total = 112.0 * qty
        return self.create_ui_order_data(
            [(self.beer, qty)],
            pos_order_ui_args={"room_charge_folio_ref": folio.id, "room_charge_label": "Room X"},
            payments=payments if payments is not None else [(self.room_pm, total)],
        )

    def _balance(self, account):
        lines = self.env["account.move.line"].search([("account_id", "=", account.id), ("parent_state", "=", "posted")])
        return sum(lines.mapped("balance"))

    def test_setup_is_consistent(self):
        self.assertIn(self.room_pm, self.config.payment_method_ids)
        self.assertEqual(self.room_pm.room_charge_product_id.property_account_income_id, self.clearing)
        self.assertFalse(self.room_pm.room_charge_product_id.taxes_id)
        # idempotent
        self.assertEqual(self.env["pos.payment.method"]._room_charge_setup_company(self.env.company), self.room_pm)

    def test_charge_to_room_full_cycle(self):
        self.open_new_session()
        self.env["pos.order"].sync_from_ui([self._order(2, None)])
        order = self.pos_session.order_ids
        self.assertEqual(order.hotel_folio_id, self.folio)
        self.assertEqual(order.partner_id, self.customer)

        line = self.folio.service_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.pos_order_id, order)
        self.assertEqual(line.product_uom_qty, 2)
        self.assertAlmostEqual(line.price_unit, 112.0)
        self.assertFalse(line.tax_ids)
        self.assertIn("Beer", line.name)

        # POS books revenue + VAT, debit goes to the Guest Ledger clearing account
        self.pos_session.action_pos_session_validate()
        self.assertEqual(self.pos_session.state, "closed")
        self.assertAlmostEqual(self._balance(self.clearing), 224.0)

        # Folio invoice moves it off the clearing account -> nothing booked twice
        self.folio.action_confirm()
        invoice = self.folio.order_id._create_invoices()
        invoice.action_post()
        self.assertAlmostEqual(invoice.amount_total, 224.0)
        self.assertAlmostEqual(invoice.amount_tax, 0.0)
        self.assertAlmostEqual(self._balance(self.clearing), 0.0)

    def test_new_pos_gets_room_charge(self):
        config = self.env["pos.config"].create({"name": "New Bar"})
        self.assertIn(self.room_pm, config.payment_method_ids)

    def test_mixed_payment_rejected(self):
        self.open_new_session()
        data = self._order(1, [(self.room_pm, 50.0), (self.cash_pm1, 62.0)])
        with self.assertRaises(UserError):
            self.env["pos.order"].sync_from_ui([data])

    def test_checked_out_folio_rejected(self):
        now = fields.Datetime.now()
        old = self.env["hotel.folio"].create({
            "partner_id": self.customer.id,
            "checkin_date": now - timedelta(days=3),
            "checkout_date": now - timedelta(days=1),
        })
        self.assertNotIn(old.id, [f["id"] for f in self.env["hotel.folio"].get_room_charge_folios()])
        self.open_new_session()
        with self.assertRaises(UserError):
            self.env["pos.order"].sync_from_ui([self._order(1, None, folio=old)])

    def test_refund_adds_negative_line(self):
        self.open_new_session()
        self.env["pos.order"].sync_from_ui([self._order(1, None)])
        refund = self._order(-1, [(self.room_pm, -112.0)])
        self.env["pos.order"].sync_from_ui([refund])
        self.assertAlmostEqual(sum(self.folio.service_line_ids.mapped("price_subtotal")), 0.0)

    def test_order_without_room_payment_ignores_folio(self):
        self.open_new_session()
        self.env["pos.order"].sync_from_ui([self._order(1, [(self.cash_pm1, 112.0)])])
        order = self.pos_session.order_ids
        self.assertFalse(order.hotel_folio_id)
        self.assertFalse(self.folio.service_line_ids)
