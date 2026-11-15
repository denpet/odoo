import hmac
import json
import logging

from odoo import SUPERUSER_ID, http
from odoo.http import request

from ..hooks import TOKEN_PARAM

_logger = logging.getLogger(__name__)


class SirvoyWebhook(http.Controller):
    @http.route(
        "/api/sirvoy",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
        save_session=False,
    )
    def sirvoy_webhook(self, token=None, **kwargs):
        # Sirvoy health check: a periodic GET that must answer 200.
        if request.httprequest.method == "GET":
            return self._text("OK")

        env = request.env(user=SUPERUSER_ID)
        expected = env["ir.config_parameter"].get_param(TOKEN_PARAM)
        if not expected or not token or not hmac.compare_digest(token, expected):
            _logger.warning("Sirvoy webhook: rejected call with a missing or wrong token")
            return self._text("Forbidden", 403)

        try:
            payload = json.loads(request.httprequest.get_data(as_text=True))
            if not isinstance(payload, dict):
                raise ValueError("payload is not a JSON object")
        except ValueError as e:
            _logger.warning("Sirvoy webhook: invalid JSON: %s", e)
            return self._text("Invalid JSON", 400)

        # Always answer 200 once the payload is stored: Sirvoy removes webhooks that keep
        # failing, and data problems (e.g. unknown room) are fixed in Odoo and reprocessed.
        event = env["sirvoy.webhook.event"].create_from_payload(payload)
        event._run()
        return self._text("OK")

    def _text(self, body, status=200):
        return request.make_response(body, headers=[("Content-Type", "text/plain")], status=status)
