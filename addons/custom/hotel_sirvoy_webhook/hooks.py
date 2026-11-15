import secrets

TOKEN_PARAM = "hotel_sirvoy_webhook.token"


def post_init_hook(env):
    """Generate the secret that Sirvoy must send as ?token=... (kept if already set)."""
    params = env["ir.config_parameter"].sudo()
    if not params.get_param(TOKEN_PARAM):
        params.set_param(TOKEN_PARAM, secrets.token_urlsafe(32))
