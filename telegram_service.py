import httpx
from config import TELEGRAM_API_URL, TELEGRAM_TOKEN, logger, mascarar_segredos

http_client = None

async def init_http_client():
    global http_client
    http_client = httpx.AsyncClient(timeout=30.0)

async def close_http_client():
    global http_client
    if http_client:
        await http_client.aclose()

async def enviar_acao_telegram(chat_id, action="typing"):
    if not http_client: return
    try:
        url = f"{TELEGRAM_API_URL}/sendChatAction"
        await http_client.post(url, json={"chat_id": chat_id, "action": action})
    except Exception as e:
        logger.error({"event": "telegram_chat_action_fail", "error": mascarar_segredos(str(e))})

async def enviar_mensagem_telegram(chat_id, texto, reply_markup=None):
    if not http_client: return
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        await http_client.post(url, json=payload)
    except Exception as e:
        logger.error({"event": "telegram_send_fail", "error": mascarar_segredos(str(e))})

async def editar_mensagem_telegram(chat_id, message_id, texto, reply_markup=None):
    if not http_client: return
    try:
        url = f"{TELEGRAM_API_URL}/editMessageText"
        payload = {"chat_id": chat_id, "message_id": message_id, "text": texto, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        await http_client.post(url, json=payload)
    except Exception as e:
        logger.error({"event": "telegram_edit_fail", "error": mascarar_segredos(str(e))})

async def baixar_arquivo_telegram(file_id):
    if not http_client: return None
    url_info = f"{TELEGRAM_API_URL}/getFile?file_id={file_id}"
    resp = (await http_client.get(url_info)).json()
    if not resp.get("ok"): return None
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{resp['result']['file_path']}"
    return (await http_client.get(download_url)).content
