import os

from quart import Quart

from config import APP_COMPONENT, AUTH_TEST_MODE, TELEGRAM_DELIVERY_MODE
from web_app.http import harden_response

app = Quart(__name__)


async def init_http_client():
    from telegram_service import init_http_client as initialize

    await initialize()


async def close_http_client():
    from telegram_service import close_http_client as close

    await close()


async def close_ai_clients():
    from ai_service import close_ai_clients as close

    await close()


@app.before_serving
async def startup():
    if APP_COMPONENT == "telegram-worker":
        await init_http_client()


@app.after_serving
async def shutdown():
    if APP_COMPONENT == "telegram-worker":
        await close_http_client()
        await close_ai_clients()


def register_component_routes(app, *, component, delivery_mode, auth_test_mode):
    if component == "telegram-poller":
        raise RuntimeError("AppSec Fatal Error: o telegram-poller não serve HTTP; use python -m telegram_poller.")
    if component == "telegram-worker":
        from web_app.worker_routes import register_worker_routes

        register_worker_routes(app)
        return

    from web_app.admin_routes import register_admin_routes
    from web_app.auth_test_support_routes import register_test_support_routes
    from web_app.cron_routes import register_cron_routes
    from web_app.observability_routes import register_observability_routes

    register_admin_routes(app)
    register_cron_routes(app)
    register_observability_routes(app)
    if delivery_mode == "webhook":
        from web_app.webhook_routes import register_webhook_routes

        register_webhook_routes(app)
    if auth_test_mode:
        register_test_support_routes(app)


app.after_request(harden_response)
register_component_routes(
    app,
    component=APP_COMPONENT,
    delivery_mode=TELEGRAM_DELIVERY_MODE,
    auth_test_mode=AUTH_TEST_MODE,
)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
