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
        cls.vat_account = cls.tax_received_account
        cls.vat = cls.env["account.tax"].create({
            "name": "VAT 12%", "amount": 12, "amount_type": "percent", "type_tax_use": "sale",
            "invoice_repartition_line_ids": [
                (0, 0, {"repartition_type": "base"}),
                (0, 0, {"repartition_type": "tax", "account_id": cls.vat_account.id}),
            ],
            "refund_repartition_line_ids": [
                (0, 0, {"repartition_type": "base"}),
                (0, 0, {"repartition_type": "tax", "account_id": cls.vat_account.id}),
            ],
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
        self.assertEqual(self.room_pm.room_charge_product_id.type, "service")
        # idempotent
        self.assertEqual(self.env["pos.payment.method"]._room_charge_setup_company(self.env.company), self.room_pm)

    def test_charge_to_room_full_cycle(self):
        income = self.beer._get_product_accounts()["income"]
        vat_account = self.vat_account
        self.open_new_session()
        self.env["pos.order"].sync_from_ui([self._order(2, None)])
        order = self.pos_session.order_ids
        self.assertEqual(order.hotel_folio_id, self.folio)
        self.assertEqual(order.partner_id, self.customer)
        self.assertTrue(order.room_charge_vat_on_folio)

        line = self.folio.service_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.pos_order_id, order)
        self.assertEqual(line.product_uom_qty, 2)
        self.assertAlmostEqual(line.price_unit, 100.0)
        self.assertEqual(line.tax_ids, self.vat)
        self.assertAlmostEqual(line.price_total, 224.0)
        self.assertIn("Beer", line.name)

        # The POS books nothing for a room charge: no revenue, no VAT, no payment
        income_before, vat_before = self._balance(income), self._balance(vat_account)
        self.pos_session.action_pos_session_validate()
        self.assertEqual(self.pos_session.state, "closed")
        self.assertFalse(self.pos_session.move_id)
        self.assertEqual(order.state, "done")
        self.assertAlmostEqual(self._balance(self.clearing), 0.0)
        self.assertAlmostEqual(self._balance(income), income_before)
        self.assertAlmostEqual(self._balance(vat_account), vat_before)

        # The folio invoice books revenue on the product's income account and the VAT
        self.folio.action_confirm()
        invoice = self.folio.order_id._create_invoices()
        invoice.action_post()
        self.assertAlmostEqual(invoice.amount_total, 224.0)
        self.assertAlmostEqual(invoice.amount_tax, 24.0)
        self.assertEqual(invoice.invoice_line_ids.account_id, income)
        self.assertAlmostEqual(self._balance(income), income_before - 200.0)
        self.assertAlmostEqual(self._balance(vat_account), vat_before - 24.0)

    def test_session_books_only_other_orders(self):
        income = self.beer._get_product_accounts()["income"]
        income_before = self._balance(income)
        self.open_new_session()
        self.env["pos.order"].sync_from_ui([
            self._order(1, None),
            self._order(1, [(self.cash_pm1, 112.0)]),
        ])
        self.pos_session.action_pos_session_validate()
        self.assertEqual(self.pos_session.state, "closed")
        self.assertEqual(set(self.pos_session.order_ids.mapped("state")), {"done"})
        self.assertAlmostEqual(self._balance(income), income_before - 100.0)
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
