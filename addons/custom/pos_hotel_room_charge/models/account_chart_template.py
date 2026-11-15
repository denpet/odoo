from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _load(self, template_code, company, install_demo, force_create=True):
        """Set up Charge to Room once a company gets its chart of accounts.

        On a fresh database the chart is loaded only after every module of the install run,
        so the post_init_hook finds no chart yet and has to rely on this.
        """
        res = super()._load(template_code, company, install_demo, force_create=force_create)
        self.env["pos.payment.method"].sudo()._room_charge_setup_company(company)
        return res
