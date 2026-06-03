import hmac

from quart import request

from admin_runtime.common import _json_error
from admin_runtime.recurring_expenses import _executar_geracao_recorrente
from api_responses import with_request_id
from config import RECURRING_EXPENSES_CRON_SECRET, logger
from security import MAX_WEBHOOK_BODY_BYTES
from web_app.http import rate_limited

CRON_ACTOR = {"id": "system-cron", "email": "cron@system.local"}
CRON_RATE_LIMIT = 5
CRON_RATE_WINDOW_SECONDS = 60
MAX_CRON_BODY_BYTES = min(MAX_WEBHOOK_BODY_BYTES, 4096)


def _validate_cron_secret(provided: str | None):
    if not RECURRING_EXPENSES_CRON_SECRET:
        logger.error(with_request_id({
            "event": "cron_secret_not_configured",
            "endpoint": "recurring-expenses",
        }))
        return _json_error("Cron endpoint not configured.", 503, code="CRON_NOT_CONFIGURED")

    if not provided or not hmac.compare_digest(provided, RECURRING_EXPENSES_CRON_SECRET):
        logger.warning(with_request_id({
            "event": "cron_secret_invalid",
            "endpoint": "recurring-expenses",
        }))
        return _json_error("Invalid cron credentials.", 401, code="CRON_AUTH_FAILED")

    return None


def register_cron_routes(app):
    @app.route("/api/cron/recurring-expenses", methods=["POST"])
    async def cron_recurring_expenses():
        provided_secret = request.headers.get("X-Cron-Secret")
        auth_error = _validate_cron_secret(provided_secret)
        if auth_error:
            return auth_error

        limited = rate_limited(
            "cron-recurring-expenses",
            request.remote_addr or "unknown",
            limit=CRON_RATE_LIMIT,
            window_seconds=CRON_RATE_WINDOW_SECONDS,
            code="CRON_RATE_LIMITED",
            message="Too many cron requests. Try again later.",
        )
        if limited is not None:
            return limited

        content_length = request.content_length or 0
        if content_length > MAX_CRON_BODY_BYTES:
            return _json_error("Cron payload too large.", 413, code="CRON_PAYLOAD_TOO_LARGE")
        if not content_length:
            raw_body = await request.get_data(cache=True)
            if len(raw_body) > MAX_CRON_BODY_BYTES:
                return _json_error("Cron payload too large.", 413, code="CRON_PAYLOAD_TOO_LARGE")

        payload = await request.get_json(silent=True) or {}
        data_referencia = payload.get("data_referencia")
        return _executar_geracao_recorrente(
            data_referencia,
            CRON_ACTOR,
            action_label="generate_recurring_expenses_cron",
        )
