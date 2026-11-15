from odoo import api, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    @api.model_create_multi
    def create(self, vals_list):
        """Offer Charge to Room on every new POS of a company that has it."""
        configs = super().create(vals_list)
        Method = self.env["pos.payment.method"].sudo()
        for config in configs:
            methods = Method.search([("is_room_charge", "=", True), ("company_id", "=", config.company_id.id)])
            if methods - config.payment_method_ids:
                config.payment_method_ids = [(4, m.id) for m in methods]
        return configs
