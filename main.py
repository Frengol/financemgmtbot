import os

from quart import Quart, Response, request

from admin_runtime.common import _extract_user_fields
from config import SECRET_TOKEN
from telegram_service import close_http_client, init_http_client
from web_app.admin_routes import register_admin_routes
from web_app.auth_compat import register_auth_compat_routes
from web_app.http import (
    _json_error,
    auth_redirect_config_error as _auth_redirect_config_error,
    browser_cors_enabled as _browser_cors_enabled,
    build_callback_url as _build_callback_url,
    build_fragment_bridge_html as _build_fragment_bridge_html,
    build_frontend_callback_relay_target as _build_frontend_callback_relay_target,
    build_login_redirect_target as _build_login_redirect_target,
    default_frontend_auth_callback_url as _default_frontend_auth_callback_url,
    default_frontend_public_url as _default_frontend_public_url,
    harden_response,
    is_loopback_request as _is_loopback_request,
    origin_allowed as _origin_allowed,
    rate_limited as _rate_limited,
    request_effective_scheme as _request_effective_scheme,
    request_is_effectively_secure as _request_is_effectively_secure,
    sanitize_frontend_app_redirect_target as _sanitize_frontend_app_redirect_target,
    sanitize_frontend_redirect_target as _sanitize_frontend_redirect_target,
    test_support_request_allowed as _test_support_request_allowed,
)
from web_app.webhook_routes import register_webhook_routes

app = Quart(__name__)


@app.before_serving
async def startup():
    await init_http_client()


@app.after_serving
async def shutdown():
    await close_http_client()


app.after_request(harden_response)
register_auth_compat_routes(app)
register_admin_routes(app)
register_webhook_routes(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
