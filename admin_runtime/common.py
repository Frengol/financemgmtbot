from typing import Any

from api_responses import json_error, json_success

MAX_BEARER_TOKEN_CHARS = 8192


def _json_error(message: str, status_code: int, *, code: str = "UNKNOWN_ERROR", detail: str | None = None, retryable: bool | None = None, retry_after_seconds: int | None = None):
    return json_error(
        message,
        status_code,
        code=code,
        detail=detail,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )


def _json_success(payload: dict[str, Any], status_code: int = 200):
    return json_success(payload, status_code)


def _extract_user_fields(user: Any):
    if user is None:
        return None, None

    if isinstance(user, dict):
        return user.get("id"), user.get("email")

    attributes = getattr(user, "__dict__", {})
    user_id = attributes.get("id")
    email = attributes.get("email")
    if user_id is not None or email is not None:
        return user_id, email

    nested_user = attributes.get("user")
    if nested_user is not None and nested_user is not user:
        return _extract_user_fields(nested_user)

    return getattr(user, "id", None), getattr(user, "email", None)
