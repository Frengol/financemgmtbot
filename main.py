import os
from quart import Quart, request, jsonify
from config import SECRET_TOKEN, logger
from telegram_service import init_http_client, close_http_client
from handlers import processar_update_assincrono

app = Quart(__name__)

@app.before_serving
async def startup():
    await init_http_client()
    
@app.after_serving
async def shutdown():
    await close_http_client()

@app.route("/", methods=["POST"])
async def telegram_webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        request_body = await request.get_json()
        logger.info({"event": "webhook_received_raw", "module": "main"})
        
        await processar_update_assincrono(request_body)
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error({"event": "webhook_processing_error", "error": str(e)})
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))