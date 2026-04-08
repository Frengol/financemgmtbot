import secrets
from typing import Any

from quart import g, has_request_context, jsonify


def current_request_id() -> str:
    if has_request_context():
        request_id = getattr(g, "request_id", None)
        if request_id:
            return request_id

        request_id = f"req_{secrets.token_hex(8)}"
        g.request_id = request_id
        return request_id

    return f"req_{secrets.token_hex(8)}"


def attach_request_id(response):
    response.headers.setdefault("X-Request-ID", current_request_id())
    return response


def json_success(payload: dict[str, Any], status_code: int = 200):
    response = jsonify({"status": "ok", **payload})
    response.status_code = status_code
    return attach_request_id(response)


def json_error(
    message: str,
    status_code: int,
    *,
    code: str = "UNKNOWN_ERROR",
    detail: str | None = None,
    retryable: bool | None = None,
    retry_after_seconds: int | None = None,
):
    payload: dict[str, Any] = {
        "status": "error",
        "message": message,
        "code": code,
        "requestId": current_request_id(),
    }
    if detail is not None:
        payload["detail"] = detail
    if retryable is not None:
        payload["retryable"] = retryable
    if retry_after_seconds is not None:
        payload["retryAfterSeconds"] = retry_after_seconds

    response = jsonify(payload)
    response.status_code = status_code
    response.headers["X-Request-ID"] = payload["requestId"]
    if retry_after_seconds is not None:
        response.headers["Retry-After"] = str(retry_after_seconds)
    return response


def with_request_id(fields: dict[str, Any] | None = None, **extra: Any):
    payload = dict(fields or {})
    payload.update(extra)
    payload.setdefault("request_id", current_request_id())
    return payload
