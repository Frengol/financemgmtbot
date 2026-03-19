import os
from quart import Quart, request, jsonify
from admin_api import aprovar_cache_admin, deletar_gasto_admin, rejeitar_cache_admin
from config import FRONTEND_ALLOWED_ORIGINS, SECRET_TOKEN, logger, mascarar_segredos
from telegram_service import init_http_client, close_http_client
from handlers import processar_update_assincrono

app = Quart(__name__)

@app.before_serving
async def startup():
    await init_http_client()
    
@app.after_serving
async def shutdown():
    await close_http_client()


@app.after_request
async def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin and (origin in FRONTEND_ALLOWED_ORIGINS or "*" in FRONTEND_ALLOWED_ORIGINS):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Vary"] = "Origin"
    return response

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
        logger.error({"event": "webhook_processing_error", "error": mascarar_segredos(str(e))})
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/admin/gastos/<gasto_id>", methods=["DELETE", "OPTIONS"])
async def admin_delete_gasto(gasto_id):
    if request.method == "OPTIONS":
        return "", 204
    return deletar_gasto_admin(gasto_id)


@app.route("/api/admin/cache-aprovacao/<cache_id>/approve", methods=["POST", "OPTIONS"])
async def admin_approve_cache(cache_id):
    if request.method == "OPTIONS":
        return "", 204
    return aprovar_cache_admin(cache_id)


@app.route("/api/admin/cache-aprovacao/<cache_id>/reject", methods=["POST", "OPTIONS"])
async def admin_reject_cache(cache_id):
    if request.method == "OPTIONS":
        return "", 204
    return rejeitar_cache_admin(cache_id)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
