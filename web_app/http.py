import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
        or request.path.startswith("/auth")
        or (auth_test_mode_enabled() and request.path.startswith("/__test__/auth"))
    )


def origin_allowed(origin: str):
    return origin in FRONTEND_ALLOWED_ORIGINS or "*" in FRONTEND_ALLOWED_ORIGINS


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


def sanitize_frontend_app_redirect_target(candidate: str | None):
    default_target = default_frontend_public_url()
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


def build_callback_url(frontend_redirect: str, *, mode: str):
    return frontend_redirect


def build_frontend_callback_relay_target():
    query_string = request.query_string.decode("utf-8", errors="ignore").strip()
    redirect_to = default_frontend_auth_callback_url()
    if not query_string:
        return build_callback_url(redirect_to, mode="canonical")

    parsed = urlsplit(build_callback_url(redirect_to, mode="canonical"))
    incoming_pairs = parse_qsl(query_string, keep_blank_values=True)
    incoming_keys = {key for key, _value in incoming_pairs}
    preserved_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in incoming_keys
    ]
    merged_query = urlencode([*preserved_pairs, *incoming_pairs])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, merged_query, parsed.fragment))


def build_login_redirect_target(redirect_to: str, *, reason: str | None = None, request_id: str | None = None):
    login_url = f"{redirect_to.rstrip('/')}/login"
    params = {}
    if reason:
        params["reason"] = reason
    if request_id:
        params["requestId"] = request_id
    if not params:
        return login_url
    return f"{login_url}?{urlencode(params)}"


def test_support_request_allowed():
    if not auth_test_mode_enabled():
        return False
    remote_addr = (request.remote_addr or "").strip()
    return remote_addr in {"127.0.0.1", "::1", "localhost"} or remote_addr.startswith("127.") or remote_addr.startswith("::ffff:127.")


def build_fragment_bridge_html(redirect_to: str):
    serialized_redirect = json.dumps(redirect_to)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta http-equiv="Cache-Control" content="no-store">
    <meta name="referrer" content="no-referrer">
    <title>Finance Copilot Auth</title>
  </head>
  <body>
    <p>Finalizing secure sign-in...</p>
    <script>
      (async function () {{
        const redirectTo = new URL({serialized_redirect});
        if (window.location.search) {{
          const sourceSearch = new URLSearchParams(window.location.search);
          sourceSearch.forEach((value, key) => {{
            redirectTo.searchParams.set(key, value);
          }});
        }}
        if (window.location.hash) {{
          redirectTo.hash = window.location.hash;
        }}
        history.replaceState(null, '', window.location.pathname + window.location.search);
        window.location.replace(redirectTo.toString());
      }})();
    </script>
  </body>
</html>"""


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
    if origin and browser_cors_enabled() and origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"

    if browser_cors_enabled():
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"

    return response
