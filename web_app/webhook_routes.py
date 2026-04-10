from quart import jsonify, request

from api_responses import with_request_id
from config import SECRET_TOKEN, logger, mascarar_segredos
from handlers import processar_update_assincrono
from security import MAX_WEBHOOK_BODY_BYTES

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

        limited = rate_limited("telegram_webhook", request.remote_addr or "unknown", limit=120, window_seconds=60)
        if limited:
            return limited

        try:
            request_body = await request.get_json()
            logger.info(with_request_id({"event": "webhook_received_raw", "module": "main"}))
            await processar_update_assincrono(request_body)
            return jsonify({"status": "ok"}), 200
        except Exception as exc:
            logger.error(with_request_id({"event": "webhook_processing_error", "error": mascarar_segredos(str(exc))}))
            return _json_error("Internal processing error.", 500)
