import re
from urllib.parse import urlsplit

from quart import Response, request

from api_responses import attach_request_id, json_error, with_request_id
from config import FRONTEND_ALLOWED_ORIGINS, FRONTEND_PUBLIC_URL, logger, mascarar_segredos, normalize_frontend_origin
from security import allow_request
from test_support import auth_test_mode_enabled


def _json_error(message: str, status_code: int, *, code: str = "UNKNOWN_ERROR", detail: str | None = None, retryable: bool | None = None, retry_after_seconds: int | None = None):
    return json_error(
        message,
        status_code,
        code=code,
        detail=detail,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )


def browser_cors_enabled():
    return (
        request.path.startswith("/api/admin")
        or request.path.startswith("/api/meta/")
        or request.path.startswith("/api/client-telemetry")
        or (auth_test_mode_enabled() and request.path.startswith("/__test__/auth"))
    )


def origin_allowed(origin: str):
    return origin in FRONTEND_ALLOWED_ORIGINS or "*" in FRONTEND_ALLOWED_ORIGINS


SAFE_CLIENT_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")


def sanitize_client_request_id(value: str | None):
    candidate = (value or "").strip()
    if not candidate:
        return None
    if not SAFE_CLIENT_REQUEST_ID_PATTERN.fullmatch(candidate):
        return None
    return candidate


def is_loopback_url(url: str):
    parsed = urlsplit((url or "").strip())
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def is_loopback_request():
    return is_loopback_url(request.url_root)


def request_effective_scheme():
    forwarded = (request.headers.get("Forwarded") or "").strip()
    if forwarded:
        first_hop = forwarded.split(",", 1)[0]
        for part in first_hop.split(";"):
            key, _, value = part.partition("=")
            if key.strip().lower() == "proto":
                candidate = value.strip().strip('"').lower()
                if candidate:
                    return candidate

    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto

    return request.scheme


def request_is_effectively_secure():
    return request_effective_scheme() == "https"


def default_frontend_public_url():
    if FRONTEND_PUBLIC_URL:
        return FRONTEND_PUBLIC_URL
    if is_loopback_request():
        return "http://localhost:5173/"
    raise RuntimeError("Missing FRONTEND_PUBLIC_URL for public auth redirects.")


def default_frontend_auth_callback_url():
    return f"{default_frontend_public_url().rstrip('/')}/auth/callback"


def auth_redirect_config_error(exc: Exception):
    logger.error(with_request_id({"event": "auth_redirect_configuration_invalid", "error": mascarar_segredos(str(exc))}))
    return _json_error("Auth redirect configuration is invalid.", 500, code="AUTH_CONFIGURATION_INVALID")


def sanitize_frontend_redirect_target(candidate: str | None):
    default_target = default_frontend_auth_callback_url()
    raw_value = (candidate or "").strip()
    if not raw_value:
        return default_target

    parsed = urlsplit(raw_value)
    if parsed.scheme in {"http", "https"}:
        if normalize_frontend_origin(raw_value) == normalize_frontend_origin(default_target):
            return raw_value
        if not FRONTEND_PUBLIC_URL and is_loopback_request() and is_loopback_url(raw_value):
            return raw_value

    return default_target


def test_support_request_allowed():
    if not auth_test_mode_enabled():
        return False
    remote_addr = (request.remote_addr or "").strip()
    return remote_addr in {"127.0.0.1", "::1", "localhost"} or remote_addr.startswith("127.") or remote_addr.startswith("::ffff:127.")


def rate_limited(
    scope: str,
    key: str,
    *,
    limit: int,
    window_seconds: int,
    code: str = "RATE_LIMITED",
    message: str = "Too many requests. Try again later.",
):
    if allow_request(scope, key, limit=limit, window_seconds=window_seconds):
        return None
    return _json_error(
        message,
        429,
        code=code,
        retryable=True,
        retry_after_seconds=window_seconds,
    )


async def harden_response(response: Response):
    attach_request_id(response)
    origin = request.headers.get("Origin")
    cors_enabled = browser_cors_enabled()
    origin_ok = bool(origin and origin_allowed(origin))
    client_request_id = sanitize_client_request_id(request.headers.get("X-Client-Request-ID"))

    if origin and cors_enabled and origin_ok:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Client-Request-ID"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = "X-Request-ID, X-Client-Request-ID"
        response.headers["Vary"] = "Origin"

    if client_request_id:
        response.headers["X-Client-Request-ID"] = client_request_id

    if cors_enabled:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"

    if request.path.startswith("/api/admin/") or request.path == "/api/admin/me":
        logger.info(
            with_request_id(
                {
                    "event": "browser_admin_request_cors",
                    "path": request.path,
                    "method": request.method,
                    "origin": origin or None,
                    "origin_allowed": origin_ok,
                    "browser_cors_enabled": cors_enabled,
                    "client_request_id": client_request_id,
                    "response_status": response.status_code,
                    "access_control_allow_origin_set": bool(response.headers.get("Access-Control-Allow-Origin")),
                }
            )
        )

    return response
