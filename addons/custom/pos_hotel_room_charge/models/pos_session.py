from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _get_closed_orders(self):
        orders = super()._get_closed_orders()
        if self.env.context.get("room_charge_exclude_folio_orders"):
            orders = orders.filtered(lambda o: not o.room_charge_vat_on_folio)
        return orders

    def _accumulate_amounts(self, data):
        """Leave room charges out of the session entry: no revenue, VAT or payment is booked
        by the POS. The folio invoice books revenue and VAT when the guest checks out.
        Stock moves are still valued by the session (they are collected separately)."""
        return super(PosSession, self.with_context(room_charge_exclude_folio_orders=True))._accumulate_amounts(data)

    def _validate_session(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        res = super()._validate_session(balancing_account, amount_to_balance, bank_payment_method_diffs)
        # A session with only room charges has an empty entry, which Odoo deletes without
        # marking the orders done.
        for session in self.filtered(lambda s: s.state == "closed"):
            session.sudo().order_ids.filtered(
                lambda o: o.state == "paid" and o.room_charge_vat_on_folio
            ).write({"state": "done"})
        return res
