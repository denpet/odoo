from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Databases installed in one run with their chart (e.g. production) never got the
    Charge to Room method, because the chart was loaded after the post_init_hook ran."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env["res.company"].search([("chart_template", "!=", False)]):
        env["pos.payment.method"]._room_charge_setup_company(company)
