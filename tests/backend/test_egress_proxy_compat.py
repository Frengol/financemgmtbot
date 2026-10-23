"""Every outbound client must honor HTTPS_PROXY (the VPS egress goes through an allowlisting proxy).

A local fake proxy records the CONNECT target and refuses it, so no request leaves the machine.
"""

import base64
import os
import socketserver
import threading
from unittest.mock import MagicMock, patch

import pytest


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

import telegram_service

# Other test modules replace the public client names with mocks for the whole session,
# so the real classes are taken from the modules that define them.
from google.genai.client import Client as RealGeminiClient
from groq._client import AsyncGroq as RealAsyncGroq
from openai._client import AsyncOpenAI as RealAsyncOpenAI
from receipt_ocr_contract import GEMINI_PRIMARY_MODEL, build_generate_content_config
from supabase._sync.client import create_client as real_create_supabase_client


SYNTHETIC_SUPABASE_HOST = "abcdefghijklmnopqrst.supabase.co"


def _synthetic_jwt():
    # supabase-py only checks the three-segment JWT shape. Built at runtime so no token-shaped
    # literal sits in the repository for secret scanners to flag.
    def segment(text):
        return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

    return ".".join(segment(part) for part in ("synthetic-header", "synthetic-payload", "synthetic-signature"))


SYNTHETIC_JWT = _synthetic_jwt()


class _RefusingConnectProxy(socketserver.StreamRequestHandler):
    def handle(self):
        request_line = self.rfile.readline(4096).decode("latin-1").strip()
        while self.rfile.readline(4096) not in (b"\r\n", b"\n", b""):
            pass
        self.server.requests.append(request_line)
        self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")


@pytest.fixture
def refusing_proxy(monkeypatch):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _RefusingConnectProxy)
    server.daemon_threads = True
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy_url = f"http://127.0.0.1:{server.server_address[1]}"
    for name in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", proxy_url)
    monkeypatch.setenv("https_proxy", proxy_url)
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def connect_targets(server):
    return [line.split()[1] for line in server.requests if line.startswith("CONNECT ")]


def test_real_client_classes_are_used():
    for client in (RealGeminiClient, RealAsyncGroq, RealAsyncOpenAI, real_create_supabase_client):
        assert not isinstance(client, MagicMock)


@pytest.mark.asyncio
async def test_telegram_client_uses_the_proxy(refusing_proxy):
    await telegram_service.init_http_client()
    try:
        with pytest.raises(telegram_service.TelegramRetryableError):
            await telegram_service.obter_info_webhook_telegram()
    finally:
        await telegram_service.close_http_client()

    assert connect_targets(refusing_proxy) == ["api.telegram.org:443"]


def test_supabase_client_uses_the_proxy(refusing_proxy):
    client = real_create_supabase_client(f"https://{SYNTHETIC_SUPABASE_HOST}", SYNTHETIC_JWT)

    with pytest.raises(Exception):
        client.table("gastos").select("valor").execute()

    assert connect_targets(refusing_proxy) == [f"{SYNTHETIC_SUPABASE_HOST}:443"]


@pytest.mark.asyncio
async def test_deepseek_client_uses_the_proxy(refusing_proxy):
    client = RealAsyncOpenAI(api_key="synthetic", base_url="https://api.deepseek.com", max_retries=0)
    try:
        with pytest.raises(Exception):
            await client.chat.completions.create(model="deepseek-chat", messages=[{"role": "user", "content": "x"}])
    finally:
        await client.close()

    assert connect_targets(refusing_proxy) == ["api.deepseek.com:443"]


@pytest.mark.asyncio
async def test_groq_client_uses_the_proxy(refusing_proxy):
    client = RealAsyncGroq(api_key="synthetic", max_retries=0)
    try:
        with pytest.raises(Exception):
            await client.chat.completions.create(model="whisper", messages=[{"role": "user", "content": "x"}])
    finally:
        await client.close()

    assert connect_targets(refusing_proxy) == ["api.groq.com:443"]


@pytest.mark.asyncio
async def test_gemini_client_uses_the_proxy_with_production_call_options(refusing_proxy):
    client = RealGeminiClient(api_key="synthetic")
    try:
        with pytest.raises(Exception):
            await client.aio.models.generate_content(
                model=GEMINI_PRIMARY_MODEL,
                contents="x",
                config=build_generate_content_config(5),
            )
    finally:
        await client.aio.aclose()

    assert connect_targets(refusing_proxy) == ["generativelanguage.googleapis.com:443"]
