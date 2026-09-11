import hashlib
import logging

from quart import g, has_request_context


_CORRELATION_NAMESPACE = b"financemgmtbot:telegram-update:v1:"
_REFERENCE_MARKER = "\n\nReferência: TG-"


def correlation_id_for_update(update_id: int) -> str:
    if isinstance(update_id, bool) or not isinstance(update_id, int):
        raise ValueError("Telegram update_id must be an integer.")
    digest = hashlib.sha256(_CORRELATION_NAMESPACE + str(update_id).encode("ascii")).hexdigest()[:16]
    return f"TG-{digest.upper()}"


def bind_telegram_update(update_id: int) -> str:
    correlation_id = correlation_id_for_update(update_id)
    if has_request_context():
        g.telegram_correlation_id = correlation_id
    return correlation_id


def current_correlation_id() -> str | None:
    if not has_request_context():
        return None
    value = getattr(g, "telegram_correlation_id", None)
    return value if isinstance(value, str) and value.startswith("TG-") else None


def correlation_fields(update_id: int | None = None) -> dict[str, str]:
    correlation_id = correlation_id_for_update(update_id) if update_id is not None else current_correlation_id()
    return {"correlation_id": correlation_id} if correlation_id else {}


def with_error_reference(text: str, *, update_id: int | None = None) -> str:
    message = str(text)
    if _REFERENCE_MARKER in message:
        return message
    correlation_id = correlation_fields(update_id).get("correlation_id")
    return f"{message}\n\nReferência: {correlation_id}" if correlation_id else message


class TelegramCorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        correlation_id = current_correlation_id()
        if correlation_id and not getattr(record, "correlation_id", None):
            record.correlation_id = correlation_id
        return True
