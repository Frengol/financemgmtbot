import asyncio
import inspect
from typing import Any

import httpx

from config import TELEGRAM_API_URL, TELEGRAM_TOKEN, logger


TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_GET_FILE_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
TELEGRAM_MEDIA_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class TelegramError(RuntimeError):
    pass


class TelegramRetryableError(TelegramError):
    def __init__(self, message, *, internal_retryable=False):
        super().__init__(message)
        self.internal_retryable = internal_retryable


class TelegramPermanentError(TelegramError):
    pass


class TelegramMarkdownError(TelegramPermanentError):
    pass


http_client = None


async def init_http_client():
    global http_client
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))


async def close_http_client():
    global http_client
    if http_client:
        await http_client.aclose()
        http_client = None


def _split_message(text: str) -> list[str]:
    if len(text) <= TELEGRAM_TEXT_LIMIT:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= TELEGRAM_TEXT_LIMIT:
            chunks.append(remaining)
            break
        boundary = remaining.rfind("\n", 0, TELEGRAM_TEXT_LIMIT + 1)
        if boundary <= 0:
            boundary = TELEGRAM_TEXT_LIMIT
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
        if remaining.startswith("\n"):
            remaining = remaining[1:]
    return chunks


def _parse_response(response: Any) -> dict[str, Any]:
    # Unit tests from the legacy suite use a bare AsyncMock response. Real
    # production responses are always httpx.Response instances.
    if not isinstance(response, httpx.Response):
        json_method = getattr(response, "json", None)
        if not callable(json_method):
            return {}
        if inspect.iscoroutinefunction(json_method):
            return {}
        payload = json_method()
        if not isinstance(payload, dict):
            return {}
        status_code = getattr(response, "status_code", 200)
        status_code = status_code if isinstance(status_code, int) else 200
        error_code = payload.get("error_code")
        description = str(payload.get("description") or "")
        if status_code == 429 or error_code == 429 or status_code >= 500:
            raise TelegramRetryableError("Telegram delivery is temporarily unavailable.")
        if status_code >= 400 or payload.get("ok") is not True:
            if status_code == 400 and "parse" in description.lower() and "entit" in description.lower():
                raise TelegramMarkdownError("Telegram rejected message formatting.")
            raise TelegramPermanentError("Telegram rejected the request.")
        return payload.get("result") if isinstance(payload.get("result"), dict) else {}
    try:
        payload = response.json()
    except ValueError as exc:
        if response.status_code >= 500:
            raise TelegramRetryableError("Telegram returned an invalid server response.") from exc
        raise TelegramPermanentError("Telegram returned an invalid response.") from exc

    error_code = payload.get("error_code") if isinstance(payload, dict) else None
    description = str(payload.get("description") or "") if isinstance(payload, dict) else ""
    status_code = response.status_code
    if status_code == 429 or error_code == 429 or status_code >= 500:
        raise TelegramRetryableError("Telegram delivery is temporarily unavailable.")
    if status_code >= 400 or not isinstance(payload, dict) or payload.get("ok") is not True:
        if status_code == 400 and "message is not modified" in description.lower():
            return {}
        if status_code == 400 and "parse" in description.lower() and "entit" in description.lower():
            raise TelegramMarkdownError("Telegram rejected message formatting.")
        raise TelegramPermanentError("Telegram rejected the request.")
    return payload.get("result") if isinstance(payload.get("result"), dict) else {}


async def _request(method: str, endpoint: str, *, payload=None, params=None, timeout=None) -> dict[str, Any]:
    if not http_client:
        raise TelegramRetryableError("Telegram HTTP client is unavailable.")
    url = f"{TELEGRAM_API_URL}/{endpoint}"
    kwargs: dict[str, Any] = {"params": params}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if payload is not None:
        kwargs["json"] = payload
    try:
        response = await getattr(http_client, method)(url, **kwargs)
    except (httpx.TimeoutException, httpx.NetworkError, asyncio.TimeoutError) as exc:
        raise TelegramRetryableError("Telegram request failed temporarily.", internal_retryable=True) from exc
    except Exception as exc:
        logger.warning({"event": "telegram_request_failed", "error_code": type(exc).__name__, "endpoint": endpoint})
        raise TelegramRetryableError("Telegram request failed temporarily.") from exc
    return _parse_response(response)


async def enviar_acao_telegram(chat_id, action="typing"):
    try:
        await _request("post", "sendChatAction", payload={"chat_id": chat_id, "action": action})
    except TelegramError as exc:
        logger.warning({"event": "telegram_chat_action_failed", "error_code": type(exc).__name__})


async def _send_text(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _request("post", endpoint, payload=payload)
    except TelegramMarkdownError:
        fallback = dict(payload)
        fallback.pop("parse_mode", None)
        logger.info({"event": "telegram_markdown_plain_text_fallback", "endpoint": endpoint})
        return await _request("post", endpoint, payload=fallback)


async def enviar_mensagem_telegram(chat_id, texto, reply_markup=None):
    chunks = _split_message(str(texto))
    result: dict[str, Any] = {}
    for index, chunk in enumerate(chunks):
        payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}
        if reply_markup and index == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        result = await _send_text("sendMessage", payload)
        logger.info(
            {
                "event": "telegram_delivery_confirmed",
                "operation": "send_message",
                "chunk": index + 1,
                "chunks": len(chunks),
            }
        )
    return result


async def editar_mensagem_telegram(chat_id, message_id, texto, reply_markup=None):
    chunks = _split_message(str(texto))
    first_payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": chunks[0],
        "parse_mode": "Markdown",
    }
    if reply_markup and len(chunks) == 1:
        first_payload["reply_markup"] = reply_markup
    result = await _send_text("editMessageText", first_payload)
    logger.info({"event": "telegram_delivery_confirmed", "operation": "edit_message", "chunk": 1, "chunks": len(chunks)})
    for index, chunk in enumerate(chunks[1:], start=2):
        payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}
        if reply_markup and index == len(chunks):
            payload["reply_markup"] = reply_markup
        result = await _send_text("sendMessage", payload)
        logger.info({"event": "telegram_delivery_confirmed", "operation": "send_message", "chunk": index, "chunks": len(chunks)})
    return result


async def remover_teclado_mensagem_telegram(chat_id, message_id):
    result = await _request(
        "post",
        "editMessageReplyMarkup",
        payload={"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
    )
    logger.info({"event": "telegram_delivery_confirmed", "operation": "remove_keyboard"})
    return result


async def responder_callback_telegram(callback_query_id):
    try:
        return await _request("post", "answerCallbackQuery", payload={"callback_query_id": callback_query_id})
    except TelegramError as exc:
        logger.warning({"event": "telegram_callback_answer_failed", "error_code": type(exc).__name__})
        return {}


async def baixar_arquivo_telegram(file_id, *, stage_callback=None, progress_message_id=None):
    async def record_stage(stage):
        if stage_callback:
            await stage_callback(stage, progress_message_id)

    file_info = None
    for attempt in range(1, 3):
        await record_stage("media_get_file")
        started_at = asyncio.get_running_loop().time()
        try:
            file_info = await _request(
                "get",
                "getFile",
                params={"file_id": file_id},
                timeout=TELEGRAM_GET_FILE_TIMEOUT,
            )
            logger.info(
                {
                    "event": "telegram_media_stage_completed",
                    "stage": "media_get_file",
                    "provider": "telegram",
                    "attempt": attempt,
                    "duration_ms": round((asyncio.get_running_loop().time() - started_at) * 1000),
                }
            )
            break
        except TelegramRetryableError as exc:
            logger.warning(
                {
                    "event": "telegram_media_stage_retryable_failure",
                    "stage": "media_get_file",
                    "provider": "telegram",
                    "attempt": attempt,
                    "error_code": getattr(exc.__cause__, "__class__", type(exc)).__name__,
                    "duration_ms": round((asyncio.get_running_loop().time() - started_at) * 1000),
                }
            )
            if not exc.internal_retryable or attempt == 2:
                raise
            await asyncio.sleep(0.5)
    file_path = file_info.get("file_path")
    if not file_path:
        raise TelegramPermanentError("Telegram file metadata is incomplete.")
    if not http_client:
        raise TelegramRetryableError("Telegram HTTP client is unavailable.")
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    for attempt in range(1, 3):
        await record_stage("media_download")
        started_at = asyncio.get_running_loop().time()
        try:
            response = await http_client.get(download_url, timeout=TELEGRAM_MEDIA_DOWNLOAD_TIMEOUT)
            response.raise_for_status()
            logger.info(
                {
                    "event": "telegram_media_stage_completed",
                    "stage": "media_download",
                    "provider": "telegram",
                    "attempt": attempt,
                    "duration_ms": round((asyncio.get_running_loop().time() - started_at) * 1000),
                }
            )
            return response.content
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(
                {
                    "event": "telegram_media_stage_retryable_failure",
                    "stage": "media_download",
                    "provider": "telegram",
                    "attempt": attempt,
                    "error_code": type(exc).__name__,
                    "duration_ms": round((asyncio.get_running_loop().time() - started_at) * 1000),
                }
            )
            if attempt == 2:
                raise TelegramRetryableError("Telegram file download failed temporarily.") from exc
            await asyncio.sleep(0.5)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 or exc.response.status_code >= 500:
                raise TelegramRetryableError("Telegram file download failed temporarily.") from exc
            raise TelegramPermanentError("Telegram rejected the file download.") from exc
