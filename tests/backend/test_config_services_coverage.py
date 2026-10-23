import base64
import contextlib
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": "FAKE_TELEGRAM_TOKEN",
    "TELEGRAM_SECRET_TOKEN": "FAKE_SECRET_TOKEN",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_KEY": "FAKE_SUPABASE_KEY_1234567890",
    "DEEPSEEK_API_KEY": "FAKE_DEEPSEEK_KEY_1234567890",
    "GROQ_API_KEY": "FAKE_GROQ_KEY_1234567890",
    "GEMINI_API_KEY": "FAKE_GEMINI_KEY_1234567890",
    "DATA_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"0" * 32).decode("ascii"),
    "TELEGRAM_TASKS_PROJECT": "financemgmtbot",
    "TELEGRAM_TASKS_LOCATION": "southamerica-east1",
    "TELEGRAM_TASKS_QUEUE": "telegram-updates",
    "TELEGRAM_WORKER_URL": "https://worker.example.run.app",
    "TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT": "telegram-task-invoker@financemgmtbot.iam.gserviceaccount.com",
}
for _key, _value in REQUIRED_ENV.items():
    os.environ.setdefault(_key, _value)

_mock_supabase_client = MagicMock(name="top_level_supabase_client")
_supabase_patch = patch("supabase.create_client", return_value=_mock_supabase_client)
_supabase_patch.start()

import ai_service
import telegram_service


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.py"


def _import_fresh_config(module_name: str):
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _set_required_env(monkeypatch: pytest.MonkeyPatch, **overrides: str):
    optional_defaults = {
        "AUTH_TEST_MODE": "false",
        "AUTH_TEST_DATA_SOURCE": "",
        "FRONTEND_PUBLIC_URL": "",
        "FRONTEND_ALLOWED_ORIGINS": "",
        "ALLOW_LOCAL_DEV_AUTH": "false",
        "SUPABASE_GASTOS_TABLE": "",
        "SUPABASE_ADMIN_EMAILS": "",
        "SUPABASE_ADMIN_USER_IDS": "",
        "GEMINI_OCR_FALLBACK_ENABLED": "false",
        "TELEGRAM_ALLOWED_USER_IDS": "",
        "APP_RUNTIME": "",
        "TELEGRAM_DELIVERY_MODE": "",
        "TELEGRAM_POLL_MAX_ATTEMPTS": "",
    }
    merged = {**REQUIRED_ENV, **optional_defaults, **overrides}
    for key in REQUIRED_ENV:
        monkeypatch.setenv(key, merged[key])
    for key, value in optional_defaults.items():
        monkeypatch.setenv(key, merged[key])
    for key, value in overrides.items():
        if key not in REQUIRED_ENV and key not in optional_defaults:
            monkeypatch.setenv(key, value)


class TestConfigCoverage:
    def test_worker_runtime_does_not_require_frontend_or_api_only_secrets(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(
            monkeypatch,
            APP_COMPONENT="telegram-worker",
            K_SERVICE="financemgmtbot-worker",
            FRONTEND_PUBLIC_URL="",
            FRONTEND_ALLOWED_ORIGINS="",
        )
        monkeypatch.delenv("TELEGRAM_SECRET_TOKEN", raising=False)

        pytest_module = sys.modules.pop("pytest", None)
        try:
            with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
                 patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
                 patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
                 patch("google.genai.Client"):
                module = _import_fresh_config("config_cov_worker_component")
        finally:
            if pytest_module is not None:
                sys.modules["pytest"] = pytest_module

        assert module.APP_COMPONENT == "telegram-worker"
        assert module.GEMINI_OCR_FALLBACK_ENABLED is False
        assert "TELEGRAM_SECRET_TOKEN" not in module.REQUIRED_VARS
        assert "DATA_ENCRYPTION_KEY" in module.REQUIRED_VARS

    def test_gemini_ocr_fallback_requires_explicit_enablement(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(
            monkeypatch,
            APP_COMPONENT="telegram-worker",
            GEMINI_OCR_FALLBACK_ENABLED="true",
        )
        pytest_module = sys.modules.pop("pytest", None)
        try:
            with patch("supabase.create_client", return_value=MagicMock()), patch("openai.AsyncOpenAI"), patch(
                "groq.AsyncGroq"
            ), patch("google.genai.Client"):
                module = _import_fresh_config("config_cov_gemini_fallback")
        finally:
            if pytest_module is not None:
                sys.modules["pytest"] = pytest_module

        assert module.GEMINI_OCR_FALLBACK_ENABLED is True

    def test_api_runtime_does_not_initialize_ai_clients(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(
            monkeypatch,
            APP_COMPONENT="api",
            TELEGRAM_TASKS_PROJECT="financemgmtbot",
            TELEGRAM_TASKS_LOCATION="southamerica-east1",
            TELEGRAM_TASKS_QUEUE="telegram-updates",
            TELEGRAM_WORKER_URL="https://worker.example.run.app",
            TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT="invoker@financemgmtbot.iam.gserviceaccount.com",
        )
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        pytest_module = sys.modules.pop("pytest", None)
        try:
            with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
                 patch("openai.AsyncOpenAI") as deepseek, \
                 patch("groq.AsyncGroq") as groq, \
                 patch("google.genai.Client") as gemini:
                module = _import_fresh_config("config_cov_api_component")
        finally:
            if pytest_module is not None:
                sys.modules["pytest"] = pytest_module

        assert module.APP_COMPONENT == "api"
        assert "DATA_ENCRYPTION_KEY" in module.REQUIRED_VARS
        assert module.deepseek_client is None
        deepseek.assert_not_called()
        groq.assert_not_called()
        gemini.assert_not_called()

    def test_load_local_env_reads_dotenv_when_pytest_module_is_temporarily_absent(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        _set_required_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "\n".join(
                [
                    "# comment",
                    "FRONTEND_ALLOWED_ORIGINS=https://admin.example.com/app/,https://admin2.example.com",
                    "EXTRA_FLAG='enabled'",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.delenv("EXTRA_FLAG", raising=False)
        monkeypatch.delenv("FRONTEND_ALLOWED_ORIGINS", raising=False)

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
                 patch("google.genai.Client"):
            module = _import_fresh_config("config_cov_env")

        pytest_module = sys.modules.pop("pytest", None)
        try:
            module.load_local_env()
        finally:
            if pytest_module is not None:
                sys.modules["pytest"] = pytest_module

        assert os.environ["EXTRA_FLAG"] == "enabled"
        assert os.environ["FRONTEND_ALLOWED_ORIGINS"] == "https://admin.example.com/app/,https://admin2.example.com"

    def test_normalization_helpers_cover_defaults_and_invalid_values(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch)

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
                 patch("google.genai.Client"):
            module = _import_fresh_config("config_cov_helpers")

        assert module.normalize_frontend_origin(" https://admin.example.com/app/login ") == "https://admin.example.com"
        assert module.normalize_frontend_origin("localhost:5173/") == "localhost:5173"
        assert module.normalize_frontend_origin("") == ""
        assert module.parse_frontend_allowed_origins(None) == frozenset(module.DEFAULT_FRONTEND_ALLOWED_ORIGINS)
        assert module.parse_frontend_allowed_origins("https://admin.example.com/app/,http://localhost:5173") == frozenset(
            {"https://admin.example.com", "http://localhost:5173"}
        )
        assert module.TRANSACTIONS_TABLE == "gastos"
        assert module.resolve_frontend_allowed_origins(
            "",
            "https://frengol.github.io/financemgmtbot/",
        ) == frozenset({"https://frengol.github.io"})
        assert module.resolve_frontend_allowed_origins(
            "",
            "http://localhost:5173/",
        ) == frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})
        assert module.is_loopback_origin("http://localhost:5173") is True
        assert module.is_loopback_origin("https://frengol.github.io") is False
        assert module.normalize_public_url("https://admin.example.com/app", trailing_slash=True) == "https://admin.example.com/app/"
        assert module.normalize_public_url("nota-url") == ""
        assert module.mascarar_segredos(REQUIRED_ENV["SUPABASE_KEY"]) == "[MASKED_SUPABASE_KEY]"

    def test_allow_local_dev_auth_defaults_true_for_unmanaged_local_runtime(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch, ALLOW_LOCAL_DEV_AUTH="", AUTH_TEST_MODE="false")

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
                 patch("google.genai.Client"):
            module = _import_fresh_config("config_cov_local_dev_auth_default")

        assert module.managed_runtime_enabled() is False
        assert module.ALLOW_LOCAL_DEV_AUTH is True

    def test_allow_local_dev_auth_stays_disabled_by_default_in_auth_test_mode(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch, ALLOW_LOCAL_DEV_AUTH="", AUTH_TEST_MODE="true", AUTH_TEST_DATA_SOURCE="database")

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
                 patch("google.genai.Client"):
            module = _import_fresh_config("config_cov_local_dev_auth_auth_test")

        assert module.AUTH_TEST_MODE is True
        assert module.ALLOW_LOCAL_DEV_AUTH is False

    def test_auth_test_mode_uses_magicmock_supabase_and_normalizes_public_urls(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(
            monkeypatch,
            AUTH_TEST_MODE="true",
            AUTH_TEST_DATA_SOURCE="seeded",
            FRONTEND_PUBLIC_URL="https://admin.example.com/app",
            FRONTEND_ALLOWED_ORIGINS="https://admin.example.com/app/,https://other.example.com/path",
        )

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")) as mock_create_client, \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
                 patch("google.genai.Client"):
            module = _import_fresh_config("config_cov_auth_test")

        assert isinstance(module.supabase, MagicMock)
        mock_create_client.assert_not_called()
        assert module.FRONTEND_PUBLIC_URL == "https://admin.example.com/app/"
        assert module.FRONTEND_ALLOWED_ORIGINS == frozenset({"https://admin.example.com", "https://other.example.com"})

    def test_auth_test_database_mode_uses_real_supabase_and_defaults_to_gastos_qa(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(
            monkeypatch,
            AUTH_TEST_MODE="true",
            AUTH_TEST_DATA_SOURCE="database",
        )

        real_supabase_client = SimpleNamespace(name="real_supabase_client")
        pytest_module = sys.modules.pop("pytest", None)
        try:
            with patch("supabase.create_client", return_value=real_supabase_client) as mock_create_client, \
                 patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
                 patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
                 patch("google.genai.Client"):
                module = _import_fresh_config("config_cov_auth_test_database")
        finally:
            if pytest_module is not None:
                sys.modules["pytest"] = pytest_module

        assert module.supabase is real_supabase_client
        mock_create_client.assert_called_once()
        assert module.TRANSACTIONS_TABLE == "gastos_qa"

    def test_managed_runtime_requires_public_frontend_origin_and_logs_resolution(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(
            monkeypatch,
            K_SERVICE="financemgmtbot-git",
            K_REVISION="rev-1",
            APP_COMMIT_SHA="557a1d4fedcba9876543210",
            APP_RELEASE_SHA="557a1d4fedcb",
            FRONTEND_PUBLIC_URL="https://frengol.github.io/financemgmtbot/",
            FRONTEND_ALLOWED_ORIGINS="",
        )

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
             patch("google.genai.Client"), \
             patch("logging.Logger.info") as info_mock:
            module = _import_fresh_config("config_cov_managed_runtime")

        assert module.FRONTEND_ALLOWED_ORIGINS == frozenset({"https://frengol.github.io"})
        assert module.managed_runtime_enabled() is True
        assert module.APP_COMMIT_SHA == "557a1d4fedcba9876543210"
        assert module.APP_RELEASE_SHA == "557a1d4fedcb"
        assert module.TRANSACTIONS_TABLE == "gastos"
        assert any(
            isinstance(call.args[0], dict) and call.args[0].get("event") == "frontend_cors_configured"
            for call in info_mock.call_args_list
        )
        assert any(
            isinstance(call.args[0], dict) and call.args[0].get("event") == "runtime_metadata_configured"
            for call in info_mock.call_args_list
        )
        assert any(
            isinstance(call.args[0], dict) and call.args[0].get("event") == "database_tables_configured"
            for call in info_mock.call_args_list
        )

    def test_local_runtime_defaults_transactions_table_to_gastos_qa_outside_pytest(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch)

        pytest_module = sys.modules.pop("pytest", None)
        try:
            with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
                 patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
                 patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
                 patch("google.genai.Client"):
                module = _import_fresh_config("config_cov_local_tables")
        finally:
            if pytest_module is not None:
                sys.modules["pytest"] = pytest_module

        assert module.TRANSACTIONS_TABLE == "gastos_qa"

    def test_transactions_table_can_be_overridden_explicitly(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch, SUPABASE_GASTOS_TABLE="gastos_custom")

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
                 patch("google.genai.Client"):
            module = _import_fresh_config("config_cov_table_override")

        assert module.TRANSACTIONS_TABLE == "gastos_custom"

    def test_managed_runtime_fails_fast_without_public_frontend_origin(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(
            monkeypatch,
            K_SERVICE="financemgmtbot-git",
            K_REVISION="rev-1",
            FRONTEND_PUBLIC_URL="",
            FRONTEND_ALLOWED_ORIGINS="",
        )

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
             patch("google.genai.Client"), \
             patch("logging.Logger.critical") as critical_mock, \
             pytest.raises(RuntimeError, match="FRONTEND_PUBLIC_URL"):
            _import_fresh_config("config_cov_missing_public_origin")

        assert any(
            isinstance(call.args[0], dict) and call.args[0].get("event") == "frontend_cors_configuration_invalid"
            for call in critical_mock.call_args_list
        )

    def test_managed_runtime_fails_fast_with_loopback_only_origin(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(
            monkeypatch,
            K_SERVICE="financemgmtbot-git",
            K_REVISION="rev-1",
            FRONTEND_PUBLIC_URL="http://localhost:5173/",
            FRONTEND_ALLOWED_ORIGINS="http://localhost:5173",
        )

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
             patch("google.genai.Client"), \
             pytest.raises(RuntimeError, match="FRONTEND_ALLOWED_ORIGINS"):
            _import_fresh_config("config_cov_loopback_only_origin")

    def test_missing_required_environment_variable_fails_fast(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
             patch("google.genai.Client"), \
             pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            _import_fresh_config("config_cov_missing_var")

    def test_client_initialization_failure_raises_and_masks_secrets(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch)
        leaked_key = REQUIRED_ENV["SUPABASE_KEY"]

        with patch("supabase.create_client", side_effect=RuntimeError(f"boom {leaked_key}")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
             patch("google.genai.Client"), \
             pytest.raises(RuntimeError, match="boom"):
            _import_fresh_config("config_cov_init_failure")


class TestAiServiceCoverage:
    @pytest.mark.asyncio
    async def test_transcrever_audio_rejects_empty_payload(self):
        with pytest.raises(ValueError, match="Audio payload is empty"):
            await ai_service.transcrever_audio(b"")

    @pytest.mark.asyncio
    async def test_extrair_tabela_recibo_rejects_empty_payload(self):
        with pytest.raises(ai_service.AIProviderPermanentError) as raised:
            await ai_service.extrair_tabela_recibo_gemini(b"")

        assert raised.value.error_code == "invalid_image"

    @pytest.mark.asyncio
    async def test_transcrever_audio_removes_temporary_file_when_provider_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        fake_path = tmp_path / "audio.ogg"

        class FakeTempFile:
            name = str(fake_path)

            def write(self, data: bytes):
                fake_path.write_bytes(data)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        create_mock = AsyncMock(side_effect=RuntimeError("transcription failed"))
        monkeypatch.setattr(ai_service.tempfile, "NamedTemporaryFile", lambda **kwargs: FakeTempFile())
        monkeypatch.setattr(ai_service.groq_client.audio.transcriptions, "create", create_mock)

        with pytest.raises(RuntimeError, match="transcription failed"):
            await ai_service.transcrever_audio(b"audio")

        assert not fake_path.exists()

    @pytest.mark.asyncio
    async def test_processar_texto_com_llm_returns_empty_object_when_provider_content_is_missing(self, monkeypatch: pytest.MonkeyPatch):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        )
        create_mock = AsyncMock(return_value=response)
        monkeypatch.setattr(ai_service.deepseek_client.chat.completions, "create", create_mock)

        result = await ai_service.processar_texto_com_llm("oi")

        assert result == {}


class TestTelegramServiceCoverage:
    @pytest.mark.asyncio
    async def test_init_and_close_http_client_manage_client_lifecycle(self):
        fake_client = AsyncMock()
        with patch("telegram_service.httpx.AsyncClient", return_value=fake_client) as async_client_cls:
            telegram_service.http_client = None
            await telegram_service.init_http_client()
            timeout = async_client_cls.call_args.kwargs["timeout"]
            assert timeout.connect == 10.0
            assert timeout.read == 30.0
            assert telegram_service.http_client is fake_client

            await telegram_service.close_http_client()
            fake_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_http_client_without_client_is_noop(self):
        telegram_service.http_client = None
        await telegram_service.close_http_client()
        assert telegram_service.http_client is None

    @pytest.mark.asyncio
    async def test_only_best_effort_action_swallows_provider_failures(self):
        failing_client = AsyncMock()
        failing_client.post.side_effect = RuntimeError("network down")
        telegram_service.http_client = failing_client

        await telegram_service.enviar_acao_telegram(123)
        with pytest.raises(telegram_service.TelegramRetryableError):
            await telegram_service.enviar_mensagem_telegram(123, "oi")
        with pytest.raises(telegram_service.TelegramRetryableError):
            await telegram_service.editar_mensagem_telegram(123, 99, "oi")

        assert failing_client.post.await_count == 3


def _load_fresh_config(module_name: str):
    # Without pytest in sys.modules, config.load_local_env() reads ./.env; an empty
    # working directory keeps these imports independent of the developer's .env.
    pytest_module = sys.modules.pop("pytest", None)
    try:
        with tempfile.TemporaryDirectory() as empty_dir, contextlib.chdir(empty_dir), patch(
            "supabase.create_client", return_value=MagicMock()
        ), patch("openai.AsyncOpenAI"), patch("groq.AsyncGroq"), patch("google.genai.Client"):
            return _import_fresh_config(module_name)
    finally:
        if pytest_module is not None:
            sys.modules["pytest"] = pytest_module


def _logged_events(caplog: pytest.LogCaptureFixture):
    return [record.msg.get("event") for record in caplog.records if isinstance(record.msg, dict)]


class TestTelegramSenderAllowlistConfig:
    @pytest.mark.parametrize(("raw", "expected"), [(None, None), ("", None), ("   ", None)])
    def test_absent_allowlist_disables_the_filter(self, raw, expected):
        import config

        assert config.parse_telegram_allowed_user_ids(raw) is expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("123", frozenset({123})), (" 1 , 22 ", frozenset({1, 22})), ("5,5", frozenset({5}))],
    )
    def test_allowlist_accepts_positive_numeric_ids(self, raw, expected):
        import config

        assert config.parse_telegram_allowed_user_ids(raw) == expected

    @pytest.mark.parametrize("raw", ["abc", "12,x", "-1", "0", "1.5", "12,,34", "12,", "+5", "١٢"])
    def test_malformed_allowlist_is_rejected_without_echoing_it(self, raw):
        import config

        with pytest.raises(RuntimeError) as error:
            config.parse_telegram_allowed_user_ids(raw)

        assert "TELEGRAM_ALLOWED_USER_IDS" in str(error.value)
        assert raw.strip(",") not in str(error.value)

    def test_worker_without_allowlist_warns_once(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
        _set_required_env(monkeypatch, APP_COMPONENT="telegram-worker")

        with caplog.at_level("WARNING"):
            module = _load_fresh_config("config_cov_worker_without_allowlist")

        assert module.TELEGRAM_ALLOWED_USER_IDS is None
        assert _logged_events(caplog).count("telegram_sender_allowlist_disabled") == 1

    def test_worker_with_allowlist_parses_it_without_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        _set_required_env(monkeypatch, APP_COMPONENT="telegram-worker", TELEGRAM_ALLOWED_USER_IDS="7,8")

        with caplog.at_level("WARNING"):
            module = _load_fresh_config("config_cov_worker_with_allowlist")

        assert module.TELEGRAM_ALLOWED_USER_IDS == frozenset({7, 8})
        assert "telegram_sender_allowlist_disabled" not in _logged_events(caplog)

    def test_api_without_allowlist_does_not_warn(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
        _set_required_env(monkeypatch, APP_COMPONENT="api")

        with caplog.at_level("WARNING"):
            _load_fresh_config("config_cov_api_without_allowlist")

        assert "telegram_sender_allowlist_disabled" not in _logged_events(caplog)

    def test_malformed_allowlist_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch, APP_COMPONENT="telegram-worker", TELEGRAM_ALLOWED_USER_IDS="12,abc")

        with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USER_IDS"):
            _load_fresh_config("config_cov_malformed_allowlist")


class TestExplicitProductionRuntimeConfig:
    @staticmethod
    def _without_cloud_run_markers(monkeypatch: pytest.MonkeyPatch):
        for key in ("K_SERVICE", "K_REVISION", "K_CONFIGURATION"):
            monkeypatch.delenv(key, raising=False)

    def test_production_runtime_applies_managed_defaults_without_cloud_run(self, monkeypatch: pytest.MonkeyPatch):
        self._without_cloud_run_markers(monkeypatch)
        _set_required_env(
            monkeypatch,
            APP_COMPONENT="api",
            APP_RUNTIME=" Production ",
            ALLOW_LOCAL_DEV_AUTH="",
            FRONTEND_PUBLIC_URL="https://painel.example.com/",
            FRONTEND_ALLOWED_ORIGINS="https://painel.example.com",
        )

        module = _load_fresh_config("config_cov_production_runtime")

        assert module.APP_RUNTIME == "production"
        assert module.managed_runtime_enabled() is True
        assert module.TRANSACTIONS_TABLE == "gastos"
        assert module.ALLOW_LOCAL_DEV_AUTH is False

    def test_production_runtime_enforces_frontend_cors_configuration(self, monkeypatch: pytest.MonkeyPatch):
        self._without_cloud_run_markers(monkeypatch)
        _set_required_env(monkeypatch, APP_COMPONENT="api", APP_RUNTIME="production")

        with pytest.raises(RuntimeError, match="FRONTEND_PUBLIC_URL"):
            _load_fresh_config("config_cov_production_runtime_without_cors")

    def test_absent_runtime_keeps_local_defaults(self, monkeypatch: pytest.MonkeyPatch):
        self._without_cloud_run_markers(monkeypatch)
        _set_required_env(monkeypatch, APP_COMPONENT="api", ALLOW_LOCAL_DEV_AUTH="")

        module = _load_fresh_config("config_cov_unset_runtime")

        assert module.APP_RUNTIME == ""
        assert module.managed_runtime_enabled() is False
        assert module.TRANSACTIONS_TABLE == "gastos_qa"
        assert module.ALLOW_LOCAL_DEV_AUTH is True

    def test_unknown_runtime_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch, APP_COMPONENT="api", APP_RUNTIME="prod")

        with pytest.raises(RuntimeError, match="APP_RUNTIME"):
            _load_fresh_config("config_cov_unknown_runtime")


class TestTelegramDeliveryModeConfig:
    WEBHOOK_ONLY_VARS = (
        "TELEGRAM_SECRET_TOKEN",
        "TELEGRAM_TASKS_PROJECT",
        "TELEGRAM_TASKS_LOCATION",
        "TELEGRAM_TASKS_QUEUE",
        "TELEGRAM_WORKER_URL",
        "TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT",
    )

    def _polling_api_env(self, monkeypatch: pytest.MonkeyPatch, **overrides: str):
        _set_required_env(
            monkeypatch,
            **{
                "APP_COMPONENT": "api",
                "TELEGRAM_DELIVERY_MODE": " Polling ",
                "APP_RUNTIME": "production",
                "FRONTEND_PUBLIC_URL": "https://painel.example.com/",
                "FRONTEND_ALLOWED_ORIGINS": "https://painel.example.com",
                **overrides,
            },
        )
        for key in (*self.WEBHOOK_ONLY_VARS, "TELEGRAM_BOT_TOKEN", "K_SERVICE", "K_REVISION", "K_CONFIGURATION"):
            monkeypatch.delenv(key, raising=False)

    def test_polling_api_requires_only_database_secrets(self, monkeypatch: pytest.MonkeyPatch):
        self._polling_api_env(monkeypatch)

        module = _load_fresh_config("config_cov_polling_api")

        assert module.TELEGRAM_DELIVERY_MODE == "polling"
        assert module.REQUIRED_VARS == ["SUPABASE_URL", "SUPABASE_KEY", "DATA_ENCRYPTION_KEY"]
        masked = module.mascarar_segredos(f"{REQUIRED_ENV['SUPABASE_KEY']} {REQUIRED_ENV['DATA_ENCRYPTION_KEY']}")
        assert REQUIRED_ENV["SUPABASE_KEY"] not in masked
        assert REQUIRED_ENV["DATA_ENCRYPTION_KEY"] not in masked

    def test_polling_api_without_production_runtime_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch):
        # Without it the VPS host would be treated as local and ALLOW_LOCAL_DEV_AUTH would default to true.
        self._polling_api_env(monkeypatch, APP_RUNTIME="")

        with pytest.raises(RuntimeError, match="APP_RUNTIME"):
            _load_fresh_config("config_cov_polling_api_without_runtime")

    def test_polling_api_inside_cloud_run_still_requires_the_explicit_marker(self, monkeypatch: pytest.MonkeyPatch):
        self._polling_api_env(monkeypatch, APP_RUNTIME="")
        monkeypatch.setenv("K_SERVICE", "financemgmtbot-git")

        with pytest.raises(RuntimeError, match="APP_RUNTIME"):
            _load_fresh_config("config_cov_polling_api_cloud_run_without_runtime")

    def test_webhook_api_without_runtime_marker_still_starts(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch, APP_COMPONENT="api", TELEGRAM_DELIVERY_MODE="webhook", APP_RUNTIME="")

        module = _load_fresh_config("config_cov_webhook_api_without_runtime")

        assert module.APP_RUNTIME == ""
        assert module.TELEGRAM_DELIVERY_MODE == "webhook"

    def test_default_delivery_mode_keeps_webhook_requirements(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch, APP_COMPONENT="api")

        module = _load_fresh_config("config_cov_webhook_api")

        assert module.TELEGRAM_DELIVERY_MODE == "webhook"
        assert set(self.WEBHOOK_ONLY_VARS) <= set(module.REQUIRED_VARS)

    def test_webhook_api_still_fails_without_its_secret(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch, APP_COMPONENT="api", TELEGRAM_DELIVERY_MODE="webhook")
        monkeypatch.delenv("TELEGRAM_SECRET_TOKEN", raising=False)

        with pytest.raises(RuntimeError, match="TELEGRAM_SECRET_TOKEN"):
            _load_fresh_config("config_cov_webhook_api_without_secret")

    def test_unknown_delivery_mode_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch, APP_COMPONENT="api", TELEGRAM_DELIVERY_MODE="pull")

        with pytest.raises(RuntimeError, match="TELEGRAM_DELIVERY_MODE"):
            _load_fresh_config("config_cov_unknown_delivery_mode")


class TestTelegramPollerConfig:
    def _poller_env(self, monkeypatch: pytest.MonkeyPatch, **overrides: str):
        _set_required_env(
            monkeypatch,
            **{
                "APP_COMPONENT": "telegram-poller",
                "TELEGRAM_ALLOWED_USER_IDS": "7",
                "APP_RUNTIME": "production",
                **overrides,
            },
        )
        for key in (*TestTelegramDeliveryModeConfig.WEBHOOK_ONLY_VARS, "K_SERVICE", "K_REVISION", "K_CONFIGURATION"):
            monkeypatch.delenv(key, raising=False)

    def test_poller_in_production_writes_to_the_real_transactions_table(self, monkeypatch: pytest.MonkeyPatch):
        self._poller_env(monkeypatch)

        assert _load_fresh_config("config_cov_poller_production_table").TRANSACTIONS_TABLE == "gastos"

    def test_poller_without_runtime_or_explicit_table_fails_instead_of_using_the_qa_table(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        self._poller_env(monkeypatch, APP_RUNTIME="", SUPABASE_GASTOS_TABLE="")

        with pytest.raises(RuntimeError, match="APP_RUNTIME"):
            _load_fresh_config("config_cov_poller_implicit_qa_table")

    def test_poller_with_explicit_table_runs_without_runtime_marker(self, monkeypatch: pytest.MonkeyPatch):
        self._poller_env(monkeypatch, APP_RUNTIME="", SUPABASE_GASTOS_TABLE="gastos_qa")

        module = _load_fresh_config("config_cov_poller_explicit_qa_table")

        assert module.TRANSACTIONS_TABLE == "gastos_qa"

    def test_poller_requires_worker_secrets_and_allowlist_but_no_webhook_secret(self, monkeypatch: pytest.MonkeyPatch):
        self._poller_env(monkeypatch)

        with patch("supabase.create_client", return_value=MagicMock()):
            module = _load_fresh_config("config_cov_poller")

        assert module.APP_COMPONENT == "telegram-poller"
        assert module.REQUIRED_VARS == [
            "TELEGRAM_BOT_TOKEN",
            "SUPABASE_URL",
            "SUPABASE_KEY",
            "DEEPSEEK_API_KEY",
            "GROQ_API_KEY",
            "GEMINI_API_KEY",
            "DATA_ENCRYPTION_KEY",
            "TELEGRAM_ALLOWED_USER_IDS",
        ]
        assert module.TELEGRAM_ALLOWED_USER_IDS == frozenset({7})
        assert module.TELEGRAM_POLL_MAX_ATTEMPTS == 8

    def test_poller_initializes_ai_clients(self, monkeypatch: pytest.MonkeyPatch):
        self._poller_env(monkeypatch)
        pytest_module = sys.modules.pop("pytest", None)
        try:
            with tempfile.TemporaryDirectory() as empty_dir, contextlib.chdir(empty_dir), patch(
                "supabase.create_client", return_value=MagicMock()
            ), patch("openai.AsyncOpenAI") as deepseek, patch("groq.AsyncGroq") as groq, patch(
                "google.genai.Client"
            ) as gemini:
                module = _import_fresh_config("config_cov_poller_ai_clients")
        finally:
            if pytest_module is not None:
                sys.modules["pytest"] = pytest_module

        assert module.deepseek_client is deepseek.return_value
        groq.assert_called_once()
        gemini.assert_called_once()

    @pytest.mark.parametrize("raw_ids", ["", "   "])
    def test_poller_without_allowlist_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch, raw_ids):
        self._poller_env(monkeypatch, TELEGRAM_ALLOWED_USER_IDS=raw_ids)

        with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USER_IDS"):
            _load_fresh_config("config_cov_poller_without_allowlist")

    def test_poller_max_attempts_accepts_positive_integer(self, monkeypatch: pytest.MonkeyPatch):
        self._poller_env(monkeypatch, TELEGRAM_POLL_MAX_ATTEMPTS=" 3 ")

        assert _load_fresh_config("config_cov_poller_attempts").TELEGRAM_POLL_MAX_ATTEMPTS == 3

    @pytest.mark.parametrize("raw_attempts", ["0", "-1", "abc", "2.5", "٣"])
    def test_poller_invalid_max_attempts_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch, raw_attempts):
        self._poller_env(monkeypatch, TELEGRAM_POLL_MAX_ATTEMPTS=raw_attempts)

        with pytest.raises(RuntimeError, match="TELEGRAM_POLL_MAX_ATTEMPTS"):
            _load_fresh_config("config_cov_poller_invalid_attempts")
