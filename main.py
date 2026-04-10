import os

from quart import Quart

from config import AUTH_TEST_MODE
from telegram_service import close_http_client, init_http_client
from web_app.auth_test_support_routes import register_test_support_routes
from web_app.admin_routes import register_admin_routes
from web_app.http import harden_response
from web_app.webhook_routes import register_webhook_routes

app = Quart(__name__)


@app.before_serving
async def startup():
    await init_http_client()


@app.after_serving
async def shutdown():
    await close_http_client()


app.after_request(harden_response)
register_admin_routes(app)
register_webhook_routes(app)
if AUTH_TEST_MODE:
    register_test_support_routes(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
