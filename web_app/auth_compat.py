from urllib.parse import urlencode

from quart import Response, redirect, request

from admin_runtime.common import _json_error, _json_success
from security import sanitize_plain_text
from test_support import auth_test_mode_enabled, capture_magic_link, consume_magic_link, peek_magic_link, reset_auth_test_state, seed_transactions

from .http import (
    auth_redirect_config_error,
    build_callback_url,
    build_fragment_bridge_html,
    build_frontend_callback_relay_target,
    default_frontend_auth_callback_url,
    rate_limited,
    sanitize_frontend_redirect_target,
    test_support_request_allowed,
)


def register_auth_compat_routes(app):
    @app.route("/auth/callback", methods=["GET", "OPTIONS"])
    async def auth_callback():
        if request.method == "OPTIONS":
            return "", 204

        limited = rate_limited("auth_callback", request.remote_addr or "unknown", limit=12, window_seconds=300)
        if limited:
            return limited

        try:
            redirect_to = build_frontend_callback_relay_target()
        except RuntimeError as exc:
            return auth_redirect_config_error(exc)

        if request.query_string:
            return redirect(redirect_to)
        return Response(build_fragment_bridge_html(redirect_to), mimetype="text/html")

    @app.route("/__test__/auth/reset", methods=["POST", "OPTIONS"])
    async def auth_test_reset():
        if request.method == "OPTIONS":
            return "", 204
        if not test_support_request_allowed():
            return _json_error("Not found.", 404)

        reset_auth_test_state()
        return _json_success({"reset": True}, 200)

    @app.route("/__test__/auth/transactions", methods=["POST", "OPTIONS"])
    async def auth_test_transactions():
        if request.method == "OPTIONS":
            return "", 204
        if not test_support_request_allowed():
            return _json_error("Not found.", 404)

        payload = await request.get_json(silent=True) or {}
        transactions = payload.get("transactions") if isinstance(payload, dict) else None
        if transactions is not None and not isinstance(transactions, list):
            return _json_error("Transactions payload must be a list.", 400)

        seeded = seed_transactions(transactions if isinstance(transactions, list) else [])
        return _json_success({"transactions": seeded}, 200)

    @app.route("/__test__/auth/magic-link", methods=["GET", "POST", "OPTIONS"])
    async def auth_test_magic_link():
        if request.method == "OPTIONS":
            return "", 204
        if not test_support_request_allowed():
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
            redirect_to = sanitize_frontend_redirect_target(payload.get("redirectTo"))
            callback_url = build_callback_url(redirect_to, mode="local_override")
        except RuntimeError as exc:
            return auth_redirect_config_error(exc)

        magic_link = capture_magic_link(
            email=email,
            callback_url=callback_url,
            user_id=user_id,
            verify_base_url=request.url_root.rstrip("/"),
        )
        return _json_success({"magicLink": magic_link}, 200)

    @app.route("/__test__/auth/verify", methods=["GET", "OPTIONS"])
    async def auth_test_verify():
        if request.method == "OPTIONS":
            return "", 204
        if not test_support_request_allowed():
            return _json_error("Not found.", 404)

        redirect_to = (request.args.get("redirect_to") or "").strip() or default_frontend_auth_callback_url()
        token_hash = (request.args.get("token_hash") or "").strip()
        magic_link = consume_magic_link(token_hash)

        if not magic_link:
            error_fragment = "error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired"
            return redirect(f"{redirect_to}#{error_fragment}")

        fragment = urlencode(
            {
                "access_token": str(magic_link.get("access_token") or ""),
                "refresh_token": str(magic_link.get("refresh_token") or ""),
                "type": "magiclink",
                "auth_test_user_id": str(magic_link.get("user_id") or ""),
                "auth_test_email": str(magic_link.get("email") or ""),
            }
        )
        return redirect(f"{redirect_to}#{fragment}")
