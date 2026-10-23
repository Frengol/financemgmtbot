import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from quart import Quart


TEST_ENV = {
    "TELEGRAM_BOT_TOKEN": "FAKE_TELEGRAM_TOKEN",
    "TELEGRAM_SECRET_TOKEN": "FAKE_SECRET",
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_KEY": "FAKE_SUPABASE_KEY_1234567890",
    "DEEPSEEK_API_KEY": "FAKE_DEEPSEEK_KEY_1234567890",
    "GROQ_API_KEY": "FAKE_GROQ_KEY_1234567890",
    "GEMINI_API_KEY": "FAKE_GEMINI_KEY_1234567890",
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)

_dependency_patches = [
    patch("supabase.create_client", return_value=MagicMock()),
    patch("groq.AsyncGroq", return_value=MagicMock()),
    patch("openai.AsyncOpenAI", return_value=MagicMock()),
    patch("google.genai.Client", return_value=MagicMock()),
]
for dependency_patch in _dependency_patches:
    dependency_patch.start()

import main


IGNORED_METHODS = {"HEAD", "OPTIONS"}
WEBHOOK_RULE = ("/", frozenset({"POST"}))


def rules(app):
    return {
        (rule.rule, frozenset(set(rule.methods or ()) - IGNORED_METHODS))
        for rule in app.url_map.iter_rules()
        if rule.endpoint != "static"
    }


def routes_for(component, delivery_mode, auth_test_mode=False):
    app = Quart(f"routing-{component}-{delivery_mode}")
    main.register_component_routes(
        app,
        component=component,
        delivery_mode=delivery_mode,
        auth_test_mode=auth_test_mode,
    )
    return rules(app)


class TestComponentRouting:
    def test_polling_api_serves_everything_except_the_webhook(self):
        webhook_routes = routes_for("api", "webhook")
        polling_routes = routes_for("api", "polling")

        assert WEBHOOK_RULE in webhook_routes
        assert polling_routes == webhook_routes - {WEBHOOK_RULE}

    def test_polling_api_does_not_import_the_webhook_or_task_queue(self):
        with patch.dict(sys.modules, {"web_app.webhook_routes": None}):
            routes_for("api", "polling")
            with pytest.raises(ImportError):
                routes_for("api", "webhook")

    def test_worker_component_only_serves_the_task_route(self):
        assert routes_for("telegram-worker", "webhook") == {
            ("/internal/tasks/telegram-update", frozenset({"POST"}))
        }

    def test_auth_test_mode_adds_test_support_routes(self):
        assert routes_for("api", "webhook", auth_test_mode=True) > routes_for("api", "webhook")

    def test_module_app_uses_configured_component(self):
        assert WEBHOOK_RULE in rules(main.app)

    def test_poller_component_is_never_served_by_the_http_app(self):
        with pytest.raises(RuntimeError, match="python -m telegram_poller"):
            routes_for("telegram-poller", "webhook")


class TestAiClientShutdown:
    @pytest.mark.asyncio
    async def test_close_ai_clients_awaits_async_gemini_close(self):
        import ai_service

        gemini = MagicMock()
        gemini.aio.aclose = AsyncMock()
        with patch("config.gemini_client", gemini):
            await ai_service.close_ai_clients()

        gemini.aio.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_ai_clients_accepts_sync_close_and_missing_client(self):
        import ai_service

        gemini = MagicMock()
        gemini.aio.aclose = MagicMock(return_value=None)
        with patch("config.gemini_client", gemini):
            await ai_service.close_ai_clients()
        with patch("config.gemini_client", None):
            await ai_service.close_ai_clients()

        gemini.aio.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_shutdown_delegates_to_ai_service(self):
        import ai_service

        with patch.object(ai_service, "close_ai_clients", AsyncMock()) as close:
            await main.close_ai_clients()

        close.assert_awaited_once()
