from quart import jsonify, request

from api_responses import with_request_id
from config import SECRET_TOKEN, logger
from security import MAX_WEBHOOK_BODY_BYTES
from telegram_tasks import InvalidTelegramUpdate, enqueue_telegram_update

from .http import _json_error, rate_limited


def register_webhook_routes(app):
    @app.route("/", methods=["POST"])
    async def telegram_webhook():
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
            return jsonify({"error": "Unauthorized"}), 403

        if request.mimetype != "application/json":
            return _json_error("Webhook requests must be JSON.", 415)

        content_length = request.content_length or 0
        if content_length > MAX_WEBHOOK_BODY_BYTES:
            return _json_error("Webhook payload too large.", 413)
        if not content_length:
            raw_body = await request.get_data(cache=True)
            if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
                return _json_error("Webhook payload too large.", 413)

        limited = rate_limited("telegram_webhook", request.remote_addr or "unknown", limit=120, window_seconds=60)
        if limited:
            return limited

        try:
            request_body = await request.get_json()
            logger.info(with_request_id({"event": "webhook_received_raw", "module": "main"}))
            await enqueue_telegram_update(request_body)
            return jsonify({"status": "ok"}), 200
        except InvalidTelegramUpdate:
            return _json_error("Invalid Telegram update.", 400, code="INVALID_TELEGRAM_UPDATE")
        except Exception as exc:
            logger.error(with_request_id({"event": "telegram_task_enqueue_failed", "error_code": type(exc).__name__}))
            return _json_error("Update queue unavailable.", 503, code="QUEUE_UNAVAILABLE", retryable=True)
