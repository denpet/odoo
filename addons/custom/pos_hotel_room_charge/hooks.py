import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Create the room-charge accounting setup for every company that has a chart of accounts."""
    for company in env["res.company"].search([("chart_template", "!=", False)]):
        env["pos.payment.method"]._room_charge_setup_company(company)
