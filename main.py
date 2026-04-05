import json
import os
from urllib.parse import quote, urlencode, urlsplit

from quart import Quart, Response, jsonify, redirect, request

from api_responses import attach_request_id, current_request_id, json_error, json_success, with_request_id
from admin_api import (
    aprovar_cache_admin,
    atualizar_gasto_admin,
    criar_gasto_admin,
    deletar_gasto_admin,
    listar_cache_admin,
    listar_gastos_admin,
    rejeitar_cache_admin,
)
from config import ADMIN_EMAILS, ADMIN_USER_IDS, AUTH_CALLBACK_PUBLIC_URL, FRONTEND_ALLOWED_ORIGINS, FRONTEND_PUBLIC_URL, SECRET_TOKEN, logger, mascarar_segredos, normalize_frontend_origin, supabase
from handlers import processar_update_assincrono
from security import (
    AdminSessionStorageUnavailableError,
    CSRF_COOKIE_NAME,
    MAX_WEBHOOK_BODY_BYTES,
    SESSION_ABSOLUTE_HOURS,
    SESSION_COOKIE_NAME,
    allow_request,
    create_admin_session,
    revoke_admin_session,
    sanitize_plain_text,
)
from telegram_service import close_http_client, init_http_client
from test_support import auth_test_mode_enabled, capture_magic_link, consume_magic_link, peek_magic_link, reset_auth_test_state, seed_transactions

app = Quart(__name__)


def _json_error(message: str, status_code: int, *, code: str = "UNKNOWN_ERROR", retryable: bool | None = None, retry_after_seconds: int | None = None):
    return json_error(
        message,
        status_code,
        code=code,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )


def _json_success(payload: dict[str, object], status_code: int = 200):
    return json_success(payload, status_code)


def _extract_user_fields(user):
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

    session = attributes.get("session")
    if session is not None and session is not user:
        session_user = getattr(session, "__dict__", {}).get("user")
        if session_user is not None:
            return _extract_user_fields(session_user)

    return None, None


def _browser_cors_enabled():
    return request.path.startswith("/api/admin") or request.path.startswith("/auth")


def _origin_allowed(origin: str):
    return origin in FRONTEND_ALLOWED_ORIGINS or "*" in FRONTEND_ALLOWED_ORIGINS


def _is_loopback_url(url: str):
    parsed = urlsplit((url or "").strip())
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _is_loopback_request():
    return _is_loopback_url(request.url_root)


def _request_effective_scheme():
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


def _request_is_effectively_secure():
    return _request_effective_scheme() == "https"


def _default_frontend_public_url():
    if FRONTEND_PUBLIC_URL:
        return FRONTEND_PUBLIC_URL
    if _is_loopback_request():
        return "http://localhost:5173/"
    raise RuntimeError("Missing FRONTEND_PUBLIC_URL for public auth redirects.")


def _default_auth_callback_public_url():
    if AUTH_CALLBACK_PUBLIC_URL:
        return AUTH_CALLBACK_PUBLIC_URL
    if _is_loopback_request():
        return request.url_root.rstrip("/") + "/auth/callback"
    raise RuntimeError("Missing AUTH_CALLBACK_PUBLIC_URL for public auth redirects.")


def _auth_redirect_config_error(exc: Exception):
    logger.error(with_request_id({"event": "auth_redirect_configuration_invalid", "error": mascarar_segredos(str(exc))}))
    return _json_error("Auth redirect configuration is invalid.", 500, code="AUTH_CONFIGURATION_INVALID")


def _set_session_cookies(response, session_token: str, csrf_token: str):
    secure_cookie = _request_is_effectively_secure()
    cookie_settings = {
        "max_age": SESSION_ABSOLUTE_HOURS * 60 * 60,
        "secure": secure_cookie,
        "samesite": "None" if secure_cookie else "Lax",
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE_NAME, session_token, httponly=True, **cookie_settings)
    response.set_cookie(CSRF_COOKIE_NAME, csrf_token, httponly=False, **cookie_settings)
    return response


def _clear_session_cookies(response):
    secure_cookie = _request_is_effectively_secure()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=secure_cookie, samesite="None" if secure_cookie else "Lax")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=secure_cookie, samesite="None" if secure_cookie else "Lax")
    return response


def _is_allowed_admin_identity(email: str | None, user_id: str | None):
    normalized_email = email.lower() if isinstance(email, str) else None
    if ADMIN_USER_IDS and user_id not in ADMIN_USER_IDS:
        return False
    if ADMIN_EMAILS and normalized_email not in ADMIN_EMAILS:
        return False
    return True


def _is_magic_link_email_allowed(email: str | None):
    normalized_email = email.lower() if isinstance(email, str) else None
    if ADMIN_EMAILS and normalized_email not in ADMIN_EMAILS:
        return False
    return True


def _sanitize_frontend_redirect_target(candidate: str | None):
    default_target = _default_frontend_public_url()
    raw_value = (candidate or "").strip()
    if not raw_value:
        return default_target

    parsed = urlsplit(raw_value)
    if parsed.scheme in {"http", "https"}:
        if normalize_frontend_origin(raw_value) == normalize_frontend_origin(default_target):
            return raw_value
        if not FRONTEND_PUBLIC_URL and _is_loopback_request() and _is_loopback_url(raw_value):
            return raw_value

    return default_target


def _build_callback_url(frontend_redirect: str):
    callback_base = _default_auth_callback_public_url()
    return f"{callback_base}?next={quote(frontend_redirect, safe='')}"


def _build_login_redirect_target(redirect_to: str, *, reason: str | None = None, request_id: str | None = None):
    login_url = f"{redirect_to.rstrip('/')}/login"
    params = {}
    if reason:
        params["reason"] = reason
    if request_id:
        params["requestId"] = request_id
    if not params:
        return login_url
    return f"{login_url}?{urlencode(params)}"


def _log_auth_session_storage_unavailable(exc: AdminSessionStorageUnavailableError):
    request_id = current_request_id()
    log_payload = {
        "event": "auth_session_storage_unavailable",
        "storage": "admin_web_sessions",
        "request_id": request_id,
    }
    if exc.upstream_code:
        log_payload["upstream_code"] = exc.upstream_code
    logger.error(with_request_id(log_payload))
    return request_id


def _test_support_request_allowed():
    if not auth_test_mode_enabled():
        return False
    remote_addr = (request.remote_addr or "").strip()
    return remote_addr in {"127.0.0.1", "::1", "localhost"} or remote_addr.startswith("127.") or remote_addr.startswith("::ffff:127.")


def _build_fragment_bridge_html(redirect_to: str):
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
        const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
        const accessToken = params.get('access_token');
        const refreshToken = params.get('refresh_token');
        const redirectTo = {serialized_redirect};

        if (!accessToken) {{
          window.location.replace(redirectTo);
          return;
        }}

        const response = await fetch(window.location.pathname + window.location.search, {{
          method: 'POST',
          credentials: 'include',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            access_token: accessToken,
            refresh_token: refreshToken,
            redirectTo
          }})
        }});

        const payload = await response.json().catch(() => ({{ redirectTo }}));
        const buildLoginUrl = function (reason, requestId) {{
          const loginUrl = new URL('login', redirectTo);
          if (reason) {{
            loginUrl.searchParams.set('reason', reason);
          }}
          if (requestId) {{
            loginUrl.searchParams.set('requestId', requestId);
          }}
          return loginUrl.toString();
        }};

        if (!response.ok) {{
          history.replaceState(null, '', window.location.pathname + window.location.search);
          if (payload.code === 'AUTH_ACCESS_DENIED') {{
            window.location.replace(buildLoginUrl('unauthorized'));
            return;
          }}
          if (payload.code === 'AUTH_SESSION_STORAGE_UNAVAILABLE') {{
            window.location.replace(buildLoginUrl('auth_unavailable', payload.requestId));
            return;
          }}
          window.location.replace(buildLoginUrl('auth_unavailable', payload.requestId));
          return;
        }}

        const nextUrl = payload.redirectTo || redirectTo;
        history.replaceState(null, '', window.location.pathname + window.location.search);
        window.location.replace(nextUrl);
      }})().catch(function () {{
        window.location.replace(new URL('login', {serialized_redirect}).toString());
      }});
    </script>
  </body>
</html>"""


def _rate_limited(
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


@app.before_serving
async def startup():
    await init_http_client()


@app.after_serving
async def shutdown():
    await close_http_client()


@app.after_request
async def harden_response(response):
    attach_request_id(response)
    origin = request.headers.get("Origin")
    if origin and _browser_cors_enabled() and _origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRF-Token"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"

    if _browser_cors_enabled():
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"

    return response


@app.route("/auth/magic-link", methods=["POST", "OPTIONS"])
async def auth_magic_link():
    if request.method == "OPTIONS":
        return "", 204

    payload = await request.get_json(silent=True) or {}
    email = sanitize_plain_text(payload.get("email"), 160).lower()
    try:
        redirect_to = _sanitize_frontend_redirect_target(payload.get("redirectTo"))
        callback_url = _build_callback_url(redirect_to)
    except RuntimeError as exc:
        return _auth_redirect_config_error(exc)
    remote_addr = request.remote_addr or "unknown"

    rate_limited = _rate_limited("auth_magic_link", f"{remote_addr}:{email}", limit=5, window_seconds=300)
    if rate_limited:
        return rate_limited

    if email and "@" in email and _is_magic_link_email_allowed(email):
        try:
            if auth_test_mode_enabled():
                capture_magic_link(email=email, callback_url=callback_url)
            else:
                supabase.auth.sign_in_with_otp({
                    "email": email,
                    "options": {
                        "email_redirect_to": callback_url,
                    },
                })
        except Exception as exc:
            sanitized_error = mascarar_segredos(str(exc))
            logger.warning(with_request_id({"event": "auth_magic_link_send_failed", "error": sanitized_error}))
            if "email rate limit exceeded" in sanitized_error.lower():
                return _json_error(
                    "Too many login requests. Try again later.",
                    429,
                    code="AUTH_MAGIC_LINK_RATE_LIMIT",
                    retryable=True,
                    retry_after_seconds=300,
                )
            return _json_error(
                "Unable to send the magic link right now.",
                503,
                code="AUTH_MAGIC_LINK_SEND_FAILED",
                retryable=True,
            )

    return _json_success({"message": "If the e-mail is authorized, a magic link will be sent shortly."}, 200)


@app.route("/auth/callback", methods=["GET", "POST", "OPTIONS"])
async def auth_callback():
    if request.method == "OPTIONS":
        return "", 204

    remote_addr = request.remote_addr or "unknown"
    rate_limited = _rate_limited("auth_callback", remote_addr, limit=12, window_seconds=300)
    if rate_limited:
        return rate_limited

    if request.method == "GET":
        try:
            redirect_to = _sanitize_frontend_redirect_target(request.args.get("next"))
        except RuntimeError as exc:
            return _auth_redirect_config_error(exc)
        token_hash = (request.args.get("token_hash") or "").strip()
        otp_type = (request.args.get("type") or "").strip()
        if not token_hash or not otp_type:
            return Response(_build_fragment_bridge_html(redirect_to), mimetype="text/html")

        try:
            auth_payload = consume_magic_link(token_hash) if auth_test_mode_enabled() else None
            if auth_payload:
                user_id = str(auth_payload.get("user_id") or "").strip()
                email = str(auth_payload.get("email") or "").strip().lower()
            else:
                auth_response = supabase.auth.verify_otp({"token_hash": token_hash, "type": otp_type})
                user_id, email = _extract_user_fields(auth_response)
            if not user_id or not _is_allowed_admin_identity(email, user_id):
                return redirect(_build_login_redirect_target(redirect_to, reason="unauthorized"))

            session = create_admin_session(user_id, email, request.headers.get("User-Agent"), request.remote_addr)
            response = redirect(redirect_to)
            return _set_session_cookies(response, session["token"], session["csrf_token"])
        except AdminSessionStorageUnavailableError as exc:
            request_id = _log_auth_session_storage_unavailable(exc)
            return redirect(_build_login_redirect_target(redirect_to, reason="auth_unavailable", request_id=request_id))
        except Exception as exc:
            logger.warning(with_request_id({"event": "auth_callback_verify_failed", "error": mascarar_segredos(str(exc))}))
            return redirect(_build_login_redirect_target(redirect_to))

    payload = await request.get_json(silent=True) or {}
    access_token = str(payload.get("access_token") or "").strip()
    try:
        redirect_to = _sanitize_frontend_redirect_target(payload.get("redirectTo") or request.args.get("next"))
    except RuntimeError as exc:
        return _auth_redirect_config_error(exc)
    if not access_token:
        return _json_error("Missing access token.", 400, code="AUTH_SESSION_INVALID")

    try:
        auth_response = supabase.auth.get_user(access_token)
    except Exception as exc:
        logger.warning(with_request_id({"event": "auth_callback_get_user_failed", "error": mascarar_segredos(str(exc))}))
        return _json_error("Invalid or expired upstream session.", 401, code="AUTH_SESSION_INVALID")

    user_id, email = _extract_user_fields(getattr(auth_response, "user", auth_response))
    if not user_id or not _is_allowed_admin_identity(email, user_id):
        return _json_error("Authenticated user is not allowed to access this admin route.", 403, code="AUTH_ACCESS_DENIED")

    try:
        session = create_admin_session(user_id, email, request.headers.get("User-Agent"), request.remote_addr)
    except AdminSessionStorageUnavailableError as exc:
        _log_auth_session_storage_unavailable(exc)
        return _json_error(
            "Login is temporarily unavailable. Try again later.",
            503,
            code="AUTH_SESSION_STORAGE_UNAVAILABLE",
            retryable=True,
        )
    response = _json_success({"redirectTo": redirect_to, "csrfToken": session["csrf_token"]}, 200)
    return _set_session_cookies(response, session["token"], session["csrf_token"])


@app.route("/__test__/auth/reset", methods=["POST"])
async def auth_test_reset():
    if not _test_support_request_allowed():
        return _json_error("Not found.", 404)

    reset_auth_test_state()
    return _json_success({"reset": True}, 200)


@app.route("/__test__/auth/transactions", methods=["POST"])
async def auth_test_transactions():
    if not _test_support_request_allowed():
        return _json_error("Not found.", 404)

    payload = await request.get_json(silent=True) or {}
    transactions = payload.get("transactions") if isinstance(payload, dict) else None
    if transactions is not None and not isinstance(transactions, list):
        return _json_error("Transactions payload must be a list.", 400)

    seeded = seed_transactions(transactions if isinstance(transactions, list) else [])
    return _json_success({"transactions": seeded}, 200)


@app.route("/__test__/auth/magic-link", methods=["GET", "POST"])
async def auth_test_magic_link():
    if not _test_support_request_allowed():
        return _json_error("Not found.", 404)

    if request.method == "GET":
        email = sanitize_plain_text(request.args.get("email"), 160).lower()
        payload = peek_magic_link(email)
        if not payload:
            return _json_error("Magic link not found.", 404)
        return _json_success({"magicLink": payload}, 200)

    payload = await request.get_json(silent=True) or {}
    email = sanitize_plain_text(payload.get("email"), 160).lower()
    user_id = sanitize_plain_text(payload.get("userId"), 120) or None
    try:
        redirect_to = _sanitize_frontend_redirect_target(payload.get("redirectTo"))
        callback_url = _build_callback_url(redirect_to)
    except RuntimeError as exc:
        return _auth_redirect_config_error(exc)

    magic_link = capture_magic_link(email=email, callback_url=callback_url, user_id=user_id)
    return _json_success({"magicLink": magic_link}, 200)


@app.route("/auth/session", methods=["GET", "OPTIONS"])
async def auth_session():
    if request.method == "OPTIONS":
        return "", 204

    from security import resolve_admin_session

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return _json_success({"authenticated": False}, 200)

    try:
        session = resolve_admin_session(session_token)
    except Exception as exc:
        logger.warning(with_request_id({"event": "auth_session_lookup_failed", "error": mascarar_segredos(str(exc))}))
        session = None

    if not session:
        return _json_success({"authenticated": False}, 200)

    return _json_success(
        {
            "authenticated": True,
            "user": {
                "id": session.get("user_id"),
                "email": session.get("email"),
            },
            "csrfToken": session.get("csrf_token"),
            "expiresAt": session.get("expires_at"),
        },
        200,
    )


@app.route("/auth/logout", methods=["POST", "OPTIONS"])
async def auth_logout():
    if request.method == "OPTIONS":
        return "", 204

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    try:
        revoke_admin_session(session_token)
    except Exception as exc:
        logger.warning(with_request_id({"event": "auth_logout_revoke_failed", "error": mascarar_segredos(str(exc))}))

    response = _json_success({"loggedOut": True}, 200)
    return _clear_session_cookies(response)


@app.route("/", methods=["POST"])
async def telegram_webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
        return jsonify({"error": "Unauthorized"}), 403

    if request.mimetype != "application/json":
        return _json_error("Webhook requests must be JSON.", 415)

    content_length = request.content_length or 0
    if content_length > MAX_WEBHOOK_BODY_BYTES:
        return _json_error("Webhook payload too large.", 413)

    rate_limited = _rate_limited("telegram_webhook", request.remote_addr or "unknown", limit=120, window_seconds=60)
    if rate_limited:
        return rate_limited

    try:
        request_body = await request.get_json()
        logger.info(with_request_id({"event": "webhook_received_raw", "module": "main"}))

        await processar_update_assincrono(request_body)

        return jsonify({"status": "ok"}), 200
    except Exception as exc:
        logger.error(with_request_id({"event": "webhook_processing_error", "error": mascarar_segredos(str(exc))}))
        return _json_error("Internal processing error.", 500)


@app.route("/api/admin/gastos", methods=["GET", "POST", "OPTIONS"])
async def admin_gastos():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "GET":
        return listar_gastos_admin()
    payload = await request.get_json(silent=True)
    return criar_gasto_admin(payload)


@app.route("/api/admin/gastos/<gasto_id>", methods=["DELETE", "PATCH", "OPTIONS"])
async def admin_manage_gasto(gasto_id):
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "PATCH":
        payload = await request.get_json(silent=True)
        return atualizar_gasto_admin(gasto_id, payload)
    return deletar_gasto_admin(gasto_id)


@app.route("/api/admin/cache-aprovacao", methods=["GET", "OPTIONS"])
async def admin_list_cache():
    if request.method == "OPTIONS":
        return "", 204
    return listar_cache_admin()


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
