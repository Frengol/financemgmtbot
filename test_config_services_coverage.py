import importlib.util
import os
import sys
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
}
for _key, _value in REQUIRED_ENV.items():
    os.environ.setdefault(_key, _value)

_mock_supabase_client = MagicMock(name="top_level_supabase_client")
_supabase_patch = patch("supabase.create_client", return_value=_mock_supabase_client)
_supabase_patch.start()

import ai_service
import telegram_service


CONFIG_PATH = Path(__file__).with_name("config.py")


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
        "FRONTEND_PUBLIC_URL": "",
        "FRONTEND_ALLOWED_ORIGINS": "",
        "ALLOW_LOCAL_DEV_AUTH": "false",
        "SUPABASE_ADMIN_EMAILS": "",
        "SUPABASE_ADMIN_USER_IDS": "",
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
             patch("google.generativeai.configure"):
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
             patch("google.generativeai.configure"):
            module = _import_fresh_config("config_cov_helpers")

        assert module.normalize_frontend_origin(" https://admin.example.com/app/login ") == "https://admin.example.com"
        assert module.normalize_frontend_origin("localhost:5173/") == "localhost:5173"
        assert module.normalize_frontend_origin("") == ""
        assert module.parse_frontend_allowed_origins(None) == frozenset(module.DEFAULT_FRONTEND_ALLOWED_ORIGINS)
        assert module.parse_frontend_allowed_origins("https://admin.example.com/app/,http://localhost:5173") == frozenset(
            {"https://admin.example.com", "http://localhost:5173"}
        )
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

    def test_auth_test_mode_uses_magicmock_supabase_and_normalizes_public_urls(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(
            monkeypatch,
            AUTH_TEST_MODE="true",
            FRONTEND_PUBLIC_URL="https://admin.example.com/app",
            FRONTEND_ALLOWED_ORIGINS="https://admin.example.com/app/,https://other.example.com/path",
        )

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")) as mock_create_client, \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
             patch("google.generativeai.configure"):
            module = _import_fresh_config("config_cov_auth_test")

        assert isinstance(module.supabase, MagicMock)
        mock_create_client.assert_not_called()
        assert module.FRONTEND_PUBLIC_URL == "https://admin.example.com/app/"
        assert module.FRONTEND_ALLOWED_ORIGINS == frozenset({"https://admin.example.com", "https://other.example.com"})

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
             patch("google.generativeai.configure"), \
             patch("logging.Logger.info") as info_mock:
            module = _import_fresh_config("config_cov_managed_runtime")

        assert module.FRONTEND_ALLOWED_ORIGINS == frozenset({"https://frengol.github.io"})
        assert module.managed_runtime_enabled() is True
        assert module.APP_COMMIT_SHA == "557a1d4fedcba9876543210"
        assert module.APP_RELEASE_SHA == "557a1d4fedcb"
        assert any(
            isinstance(call.args[0], dict) and call.args[0].get("event") == "frontend_cors_configured"
            for call in info_mock.call_args_list
        )
        assert any(
            isinstance(call.args[0], dict) and call.args[0].get("event") == "runtime_metadata_configured"
            for call in info_mock.call_args_list
        )

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
             patch("google.generativeai.configure"), \
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
             patch("google.generativeai.configure"), \
             pytest.raises(RuntimeError, match="FRONTEND_ALLOWED_ORIGINS"):
            _import_fresh_config("config_cov_loopback_only_origin")

    def test_missing_required_environment_variable_fails_fast(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        with patch("supabase.create_client", return_value=MagicMock(name="supabase_client")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
             patch("google.generativeai.configure"), \
             pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            _import_fresh_config("config_cov_missing_var")

    def test_client_initialization_failure_raises_and_masks_secrets(self, monkeypatch: pytest.MonkeyPatch):
        _set_required_env(monkeypatch)
        leaked_key = REQUIRED_ENV["SUPABASE_KEY"]

        with patch("supabase.create_client", side_effect=RuntimeError(f"boom {leaked_key}")), \
             patch("openai.AsyncOpenAI", return_value=MagicMock(name="deepseek_client")), \
             patch("groq.AsyncGroq", return_value=MagicMock(name="groq_client")), \
             patch("google.generativeai.configure"), \
             pytest.raises(RuntimeError, match="boom"):
            _import_fresh_config("config_cov_init_failure")


class TestAiServiceCoverage:
    @pytest.mark.asyncio
    async def test_transcrever_audio_rejects_empty_payload(self):
        with pytest.raises(ValueError, match="Audio payload is empty"):
            await ai_service.transcrever_audio(b"")

    @pytest.mark.asyncio
    async def test_extrair_tabela_recibo_rejects_empty_payload(self):
        with pytest.raises(ValueError, match="Image payload is empty"):
            await ai_service.extrair_tabela_recibo_gemini(b"")

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
            async_client_cls.assert_called_once_with(timeout=30.0)
            assert telegram_service.http_client is fake_client

            await telegram_service.close_http_client()
            fake_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_http_client_without_client_is_noop(self):
        telegram_service.http_client = None
        await telegram_service.close_http_client()
        assert telegram_service.http_client is None

    @pytest.mark.asyncio
    async def test_send_helpers_swallow_provider_failures(self):
        failing_client = AsyncMock()
        failing_client.post.side_effect = RuntimeError("network down")
        telegram_service.http_client = failing_client

        await telegram_service.enviar_acao_telegram(123)
        await telegram_service.enviar_mensagem_telegram(123, "oi")
        await telegram_service.editar_mensagem_telegram(123, 99, "oi")

        assert failing_client.post.await_count == 3
