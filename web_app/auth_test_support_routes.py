from urllib.parse import urlencode

from quart import redirect, request

from admin_runtime.common import _json_error, _json_success
from test_support import capture_magic_link, consume_magic_link, peek_magic_link, reset_auth_test_state, seed_transactions

from .http import (
    auth_redirect_config_error,
    default_frontend_auth_callback_url,
    sanitize_frontend_redirect_target,
    test_support_request_allowed,
)


def register_test_support_routes(app):
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
            email = (request.args.get("email") or "").strip().lower()
            payload = peek_magic_link(email)
            if not payload:
                return _json_error("Magic link not found.", 404)
            return _json_success({"magicLink": payload}, 200)

        payload = await request.get_json(silent=True) or {}
        email = (payload.get("email") or "").strip().lower() if isinstance(payload, dict) else ""
        user_id = None
        if isinstance(payload, dict):
            user_id = (payload.get("userId") or "").strip() or None
        if not email:
            return _json_error("Email is required.", 400)

        try:
            callback_url = sanitize_frontend_redirect_target(payload.get("redirectTo") if isinstance(payload, dict) else None)
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
