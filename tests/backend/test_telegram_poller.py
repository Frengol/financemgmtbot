import asyncio
import contextvars
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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

import ai_service
import config
import telegram_poller
import telegram_service
import telegram_update_processor as processor
from telegram_service import TelegramPermanentError, TelegramRetryableError


REPO_ROOT = Path(__file__).resolve().parents[2]
DONE = processor.UpdateResult(processor.UpdateOutcome.DONE)


def retry(code="PROCESSING_FAILED"):
    return processor.UpdateResult(processor.UpdateOutcome.RETRY, code)


def update(update_id):
    return {"update_id": update_id, "message": {"chat": {"id": 1}, "from": {"id": 7}, "text": "x"}}


def events(caplog, name):
    return [record.msg for record in caplog.records if isinstance(record.msg, dict) and record.msg.get("event") == name]


class FakeTelegram:
    """Scripted Bot API: each batch is a list of updates or an exception; stops when exhausted."""

    def __init__(self, batches=(), *, webhook_infos=None, trace=None):
        self.stop_event = asyncio.Event()
        self.batches = list(batches)
        self.webhook_infos = list(webhook_infos or [{"url": ""}])
        self.offsets = []
        self.trace = trace

    async def get_webhook_info(self):
        item = self.webhook_infos.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def get_updates(self, offset):
        self.offsets.append(offset)
        if self.trace is not None:
            self.trace.append("get")
        if not self.batches:
            self.stop_event.set()
            return []
        item = self.batches.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class ScriptedProcessor:
    def __init__(self, *results, trace=None):
        self.results = list(results)
        self.seen = []
        self.trace = trace

    async def __call__(self, incoming):
        self.seen.append(incoming["update_id"])
        if self.trace is not None:
            self.trace.append("proc")
        item = self.results.pop(0) if self.results else DONE
        if isinstance(item, BaseException):
            raise item
        return item


async def run(fake, process_update, *, max_attempts=8, stop_on_wait=False, heartbeat=None):
    waits = []

    async def wait_or_stop(seconds):
        waits.append(seconds)
        return stop_on_wait

    exit_code = await telegram_poller.run_poller(
        get_updates=fake.get_updates,
        get_webhook_info=fake.get_webhook_info,
        process_update=process_update,
        stop_event=fake.stop_event,
        max_attempts=max_attempts,
        wait_or_stop=wait_or_stop,
        heartbeat=heartbeat or MagicMock(),
    )
    return exit_code, waits


@pytest.fixture
def restore_http_loggers():
    saved = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


class TestRetryDelay:
    def test_delay_starts_at_five_seconds_doubles_and_caps_at_two_minutes(self):
        assert [telegram_poller.retry_delay(attempt) for attempt in range(1, 9)] == [5, 10, 20, 40, 80, 120, 120, 120]

    @pytest.mark.asyncio
    async def test_default_wait_returns_early_only_when_stopping(self):
        stop_event = asyncio.Event()

        assert await telegram_poller.wait_for_stop(stop_event, 0.01) is False
        stop_event.set()
        assert await telegram_poller.wait_for_stop(stop_event, 60) is True


class TestHeartbeat:
    def test_missing_heartbeat_is_unhealthy(self, tmp_path):
        assert telegram_poller.check_heartbeat(tmp_path / "missing") == 1

    def test_fresh_heartbeat_is_healthy_and_stale_one_is_not(self, tmp_path):
        path = tmp_path / "telegram-poller.heartbeat"
        telegram_poller.write_heartbeat(path)

        assert telegram_poller.check_heartbeat(path) == 0
        stale = time.time() - telegram_poller.HEARTBEAT_MAX_AGE_SECONDS - 1
        os.utime(path, (stale, stale))
        assert telegram_poller.check_heartbeat(path) == 1

    def test_write_heartbeat_refreshes_existing_file(self, tmp_path):
        path = tmp_path / "telegram-poller.heartbeat"
        telegram_poller.write_heartbeat(path)
        os.utime(path, (0, 0))

        telegram_poller.write_heartbeat(path)

        assert time.time() - path.stat().st_mtime < 5

    def test_heartbeat_lives_in_tmp(self):
        assert telegram_poller.HEARTBEAT_PATH == Path("/tmp/telegram-poller.heartbeat")
        assert telegram_poller.HEARTBEAT_MAX_AGE_SECONDS == 300


class TestStartup:
    @pytest.mark.asyncio
    async def test_active_webhook_blocks_polling(self, caplog):
        fake = FakeTelegram([[update(10)]], webhook_infos=[{"url": "https://example.com/hook"}])
        process = ScriptedProcessor()

        exit_code, _ = await run(fake, process)

        assert exit_code == 1
        assert fake.offsets == []
        assert process.seen == []
        assert events(caplog, "telegram_poller_webhook_active")

    @pytest.mark.asyncio
    async def test_rejected_webhook_check_exits(self, caplog):
        fake = FakeTelegram(webhook_infos=[TelegramPermanentError("unauthorized", status_code=401)])

        exit_code, _ = await run(fake, ScriptedProcessor())

        assert exit_code == 1
        assert events(caplog, "telegram_poller_startup_rejected")[0]["status_code"] == 401

    @pytest.mark.asyncio
    async def test_transient_webhook_check_failure_is_retried(self):
        fake = FakeTelegram(webhook_infos=[TelegramRetryableError("later"), {"url": ""}])

        exit_code, waits = await run(fake, ScriptedProcessor())

        assert exit_code == 0
        assert waits == [5]
        assert fake.offsets == [None]

    @pytest.mark.asyncio
    async def test_stop_while_waiting_for_startup_retry_exits_cleanly(self):
        fake = FakeTelegram(webhook_infos=[TelegramRetryableError("later")])

        exit_code, waits = await run(fake, ScriptedProcessor(), stop_on_wait=True)

        assert (exit_code, waits, fake.offsets) == (0, [5], [])


class TestDefaultWaitAndStartupStop:
    @pytest.mark.asyncio
    async def test_default_wait_ends_immediately_once_stop_is_requested(self):
        fake = FakeTelegram(webhook_infos=[TelegramRetryableError("later")])
        fake.stop_event.set()

        exit_code = await asyncio.wait_for(
            telegram_poller.run_poller(
                get_updates=fake.get_updates,
                get_webhook_info=fake.get_webhook_info,
                process_update=ScriptedProcessor(),
                stop_event=fake.stop_event,
                max_attempts=8,
                heartbeat=MagicMock(),
            ),
            timeout=5,
        )

        assert exit_code == 0
        assert fake.offsets == []

    @pytest.mark.asyncio
    async def test_stop_during_startup_check_exits_cleanly(self):
        fake = FakeTelegram()

        async def blocking_webhook_info():
            await asyncio.Event().wait()

        fake.get_webhook_info = blocking_webhook_info
        asyncio.get_running_loop().call_later(0.01, fake.stop_event.set)

        exit_code, _ = await asyncio.wait_for(run(fake, ScriptedProcessor()), timeout=5)

        assert exit_code == 0
        assert fake.offsets == []


class TestPollingLoop:
    @pytest.mark.asyncio
    async def test_updates_are_processed_in_order_and_confirmed_after_done(self):
        fake = FakeTelegram([[update(10), update(11)]])
        process = ScriptedProcessor(DONE, DONE)

        exit_code, waits = await run(fake, process)

        assert exit_code == 0
        assert waits == []
        assert process.seen == [10, 11]
        assert fake.offsets == [None, 12]

    @pytest.mark.asyncio
    async def test_retry_repeats_the_same_update_with_growing_waits(self):
        fake = FakeTelegram([[update(10), update(11)]])
        process = ScriptedProcessor(retry("LEASE_ACTIVE"), retry(), DONE, DONE)

        exit_code, waits = await run(fake, process)

        assert exit_code == 0
        assert process.seen == [10, 10, 10, 11]
        assert waits == [5, 10]
        assert fake.offsets == [None, 12]

    @pytest.mark.asyncio
    async def test_exhausted_retries_are_logged_and_skipped(self, caplog):
        fake = FakeTelegram([[update(10)]])
        process = ScriptedProcessor(retry(), retry(), retry("LEDGER_UNAVAILABLE"))

        exit_code, waits = await run(fake, process, max_attempts=3)

        assert exit_code == 0
        assert process.seen == [10, 10, 10]
        assert waits == [5, 10]
        assert fake.offsets == [None, 11]
        [exhausted] = events(caplog, "telegram_update_retry_exhausted")
        assert exhausted == {
            "event": "telegram_update_retry_exhausted",
            "update_id": 10,
            "attempts": 3,
            "last_code": "LEDGER_UNAVAILABLE",
        }

    @pytest.mark.asyncio
    async def test_stop_during_retry_wait_leaves_update_unconfirmed(self):
        fake = FakeTelegram([[update(10)]])
        process = ScriptedProcessor(retry())

        exit_code, waits = await run(fake, process, stop_on_wait=True)

        assert exit_code == 0
        assert process.seen == [10]
        assert waits == [5]
        assert fake.offsets == [None]

    @pytest.mark.asyncio
    async def test_processor_crash_is_retried(self, caplog):
        fake = FakeTelegram([[update(10)]])
        process = ScriptedProcessor(KeyError("private detail"), DONE)

        exit_code, waits = await run(fake, process)

        assert (exit_code, waits, process.seen) == (0, [5], [10, 10])
        [crash] = events(caplog, "telegram_poller_process_error")
        assert crash["error_code"] == "KeyError"
        assert "private detail" not in caplog.text

    @pytest.mark.asyncio
    async def test_update_without_id_is_skipped(self, caplog):
        fake = FakeTelegram([[{"message": {}}, update(11)]])
        process = ScriptedProcessor(DONE)

        exit_code, _ = await run(fake, process)

        assert exit_code == 0
        assert process.seen == [11]
        assert fake.offsets == [None, 12]
        assert events(caplog, "telegram_poller_invalid_update")

    @pytest.mark.asyncio
    async def test_transient_fetch_failures_back_off_and_reset(self, caplog):
        fake = FakeTelegram(
            [
                TelegramRetryableError("down"),
                RuntimeError("unexpected"),
                [update(10)],
                TelegramRetryableError("down again"),
            ]
        )

        exit_code, waits = await run(fake, ScriptedProcessor(DONE))

        assert exit_code == 0
        assert waits == [5, 10, 5]
        assert fake.offsets == [None, None, None, 11, 11]
        assert [entry["error_code"] for entry in events(caplog, "telegram_poller_fetch_failed")] == [
            "TelegramRetryableError",
            "RuntimeError",
            "TelegramRetryableError",
        ]

    @pytest.mark.asyncio
    async def test_stop_during_fetch_backoff_exits_cleanly(self):
        fake = FakeTelegram([TelegramRetryableError("down")])

        exit_code, waits = await run(fake, ScriptedProcessor(), stop_on_wait=True)

        assert (exit_code, waits, fake.offsets) == (0, [5], [None])

    @pytest.mark.asyncio
    async def test_conflict_exits_with_failure(self, caplog):
        fake = FakeTelegram([TelegramPermanentError("conflict", status_code=409)])

        exit_code, _ = await run(fake, ScriptedProcessor())

        assert exit_code == 1
        assert events(caplog, "telegram_poller_conflict")

    @pytest.mark.asyncio
    async def test_other_rejection_exits_with_failure(self, caplog):
        fake = FakeTelegram([TelegramPermanentError("unauthorized", status_code=401)])

        exit_code, _ = await run(fake, ScriptedProcessor())

        assert exit_code == 1
        assert events(caplog, "telegram_poller_rejected")[0]["status_code"] == 401

    @pytest.mark.asyncio
    async def test_stop_during_long_poll_cancels_the_request(self):
        fake = FakeTelegram()
        cancelled = asyncio.Event()

        async def blocking_get_updates(offset):
            fake.offsets.append(offset)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        fake.get_updates = blocking_get_updates
        asyncio.get_running_loop().call_later(0.01, fake.stop_event.set)

        exit_code, _ = await asyncio.wait_for(run(fake, ScriptedProcessor()), timeout=5)

        assert exit_code == 0
        assert cancelled.is_set()

    @pytest.mark.asyncio
    async def test_stop_during_processing_finishes_the_update_then_exits(self):
        fake = FakeTelegram([[update(10), update(11)]])
        finished = []

        async def slow_process(incoming):
            fake.stop_event.set()
            await asyncio.sleep(0.01)
            finished.append(incoming["update_id"])
            return DONE

        exit_code, _ = await run(fake, slow_process)

        assert exit_code == 0
        assert finished == [10]
        assert fake.offsets == [None]

    @pytest.mark.asyncio
    async def test_heartbeat_is_written_around_every_fetch_and_attempt(self):
        trace = []
        fake = FakeTelegram([[update(10)]], trace=trace)
        process = ScriptedProcessor(retry(), DONE, trace=trace)

        await run(fake, process, heartbeat=lambda: trace.append("hb"))

        assert trace == ["hb", "get", "hb", "proc", "hb", "proc", "hb", "hb", "get"]

    @pytest.mark.asyncio
    async def test_processing_context_does_not_leak_into_the_loop(self):
        marker = contextvars.ContextVar("marker", default=None)
        seen_by_fetch = []
        fake = FakeTelegram([[update(10)], []])
        original_get_updates = fake.get_updates

        async def get_updates(offset):
            seen_by_fetch.append(marker.get())
            return await original_get_updates(offset)

        async def process(incoming):
            marker.set(incoming["update_id"])
            return DONE

        fake.get_updates = get_updates
        await run(fake, process)

        assert seen_by_fetch == [None, None, None]


def raise_error(error):
    raise error


def telegram_transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestTelegramServicePolling:
    @pytest.mark.asyncio
    async def test_get_updates_uses_long_polling_with_a_longer_read_timeout(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"ok": True, "result": [update(10)]})

        telegram_service.http_client = telegram_transport(handler)
        try:
            assert await telegram_service.obter_updates_telegram(10) == [update(10)]
            await telegram_service.obter_updates_telegram(None)
        finally:
            await telegram_service.close_http_client()

        first, second = seen
        assert first.method == "POST"
        assert first.url.path.endswith("/getUpdates")
        assert json.loads(first.content) == {
            "offset": 10,
            "timeout": 50,
            "allowed_updates": ["message", "callback_query"],
        }
        assert "offset" not in json.loads(second.content)
        assert first.extensions["timeout"]["read"] > 50

    @pytest.mark.asyncio
    async def test_get_updates_rejects_a_non_list_result(self):
        telegram_service.http_client = telegram_transport(
            lambda request: httpx.Response(200, json={"ok": True, "result": {"not": "a list"}})
        )
        try:
            with pytest.raises(TelegramRetryableError):
                await telegram_service.obter_updates_telegram(None)
        finally:
            await telegram_service.close_http_client()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "error_type"),
        [(409, TelegramPermanentError), (401, TelegramPermanentError), (502, TelegramRetryableError), (429, TelegramRetryableError)],
    )
    async def test_errors_carry_the_http_status(self, status, error_type):
        telegram_service.http_client = telegram_transport(
            lambda request: httpx.Response(status, json={"ok": False, "error_code": status, "description": "x"})
        )
        try:
            with pytest.raises(error_type) as error:
                await telegram_service.obter_updates_telegram(None)
        finally:
            await telegram_service.close_http_client()

        assert error.value.status_code == status

    def test_legacy_mock_responses_also_carry_the_status(self):
        response = MagicMock(status_code=409)
        response.json.return_value = {"ok": False, "error_code": 409}

        with pytest.raises(TelegramPermanentError) as error:
            telegram_service._parse_response(response)

        assert error.value.status_code == 409

    def test_network_errors_have_no_status(self):
        assert TelegramRetryableError("down", internal_retryable=True).status_code is None

    @pytest.mark.asyncio
    async def test_webhook_info_returns_the_result_object(self):
        telegram_service.http_client = telegram_transport(
            lambda request: httpx.Response(200, json={"ok": True, "result": {"url": "", "pending_update_count": 0}})
        )
        try:
            assert await telegram_service.obter_info_webhook_telegram() == {"url": "", "pending_update_count": 0}
        finally:
            await telegram_service.close_http_client()


class TestTokenNeverLogged:
    def test_http_client_loggers_are_quieted(self, restore_http_loggers):
        logging.getLogger("httpx").setLevel(logging.NOTSET)
        logging.getLogger("httpcore").setLevel(logging.DEBUG)

        telegram_poller.quiet_http_loggers()

        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
        assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING

    @pytest.mark.asyncio
    async def test_poller_logs_never_contain_the_bot_token(self, caplog, restore_http_loggers):
        token = config.TELEGRAM_TOKEN
        requested_urls = []
        stop_event = asyncio.Event()
        responses = iter(
            [
                lambda url: httpx.Response(200, json={"ok": True, "result": {"url": ""}}),
                lambda url: raise_error(httpx.ConnectError(f"cannot reach {url}")),
                lambda url: raise_error(RuntimeError(f"unexpected failure for {url}")),
                lambda url: httpx.Response(500, json={"ok": False, "description": f"echo {url}"}),
                lambda url: httpx.Response(200, json={"ok": True, "result": []}),
            ]
        )

        def handler(request):
            requested_urls.append(str(request.url))
            respond = next(responses, None)
            if respond is None:
                stop_event.set()
                return httpx.Response(200, json={"ok": True, "result": []})
            return respond(request.url)

        async def no_wait(seconds):
            return False

        telegram_poller.quiet_http_loggers()
        telegram_service.http_client = telegram_transport(handler)
        try:
            with caplog.at_level(logging.DEBUG):
                exit_code = await telegram_poller.run_poller(
                    get_updates=telegram_service.obter_updates_telegram,
                    get_webhook_info=telegram_service.obter_info_webhook_telegram,
                    process_update=ScriptedProcessor(),
                    stop_event=stop_event,
                    max_attempts=2,
                    wait_or_stop=no_wait,
                    heartbeat=MagicMock(),
                )
        finally:
            await telegram_service.close_http_client()

        assert exit_code == 0
        assert any(token in url for url in requested_urls)
        assert len(events(caplog, "telegram_poller_fetch_failed")) == 3
        formatter = logging.Formatter("%(name)s %(message)s")
        rendered = "\n".join(formatter.format(record) + repr(record.__dict__) for record in caplog.records)
        assert token not in rendered


class TestCommandLine:
    def test_check_reports_heartbeat_health(self, tmp_path):
        path = tmp_path / "telegram-poller.heartbeat"
        with patch.object(telegram_poller, "HEARTBEAT_PATH", path):
            assert telegram_poller.cli(["--check"]) == 1
            telegram_poller.write_heartbeat(path)
            assert telegram_poller.cli(["--check"]) == 0

    def test_unknown_arguments_are_rejected(self, capsys):
        assert telegram_poller.cli(["--verbose"]) == 2
        assert "usage" in capsys.readouterr().err

    def test_without_arguments_runs_the_poller(self):
        with patch.object(telegram_poller, "main", AsyncMock(return_value=0)) as main:
            assert telegram_poller.cli([]) == 0
        main.assert_awaited_once()

    def test_importing_the_module_does_not_load_config(self):
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); import telegram_poller; "
            "print('config' in sys.modules, 'telegram_service' in sys.modules)"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-c", code, str(REPO_ROOT)],
            capture_output=True,
            text=True,
            env={"PATH": os.environ.get("PATH", "")},
            timeout=30,
            check=True,
        )

        assert completed.stdout.strip() == "False False"


class TestMain:
    @pytest.mark.asyncio
    async def test_main_refuses_other_components(self, caplog):
        with patch.object(config, "APP_COMPONENT", "api"):
            assert await telegram_poller.main() == 1
        assert events(caplog, "telegram_poller_wrong_component")

    @pytest.mark.asyncio
    async def test_main_wires_clients_signals_and_processor(self, restore_http_loggers):
        captured = {}
        processed = AsyncMock(return_value=DONE)

        async def fake_run_poller(**kwargs):
            captured.update(kwargs)
            assert await kwargs["process_update"](update(10)) == DONE
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(kwargs["stop_event"].wait(), timeout=5)
            return 0

        previous_handler = signal.signal(signal.SIGTERM, lambda *args: None)
        try:
            with patch.object(config, "APP_COMPONENT", "telegram-poller"), patch.object(
                config, "TELEGRAM_POLL_MAX_ATTEMPTS", 5
            ), patch.object(telegram_service, "init_http_client", AsyncMock()) as init_client, patch.object(
                telegram_service, "close_http_client", AsyncMock()
            ) as close_client, patch.object(ai_service, "close_ai_clients", AsyncMock()) as close_ai, patch.object(
                processor, "process_telegram_update", processed
            ), patch.object(
                telegram_poller, "run_poller", fake_run_poller
            ):
                assert await telegram_poller.main() == 0
        finally:
            signal.signal(signal.SIGTERM, previous_handler)

        assert captured["max_attempts"] == 5
        assert captured["get_updates"] is telegram_service.obter_updates_telegram
        assert captured["get_webhook_info"] is telegram_service.obter_info_webhook_telegram
        assert isinstance(processed.await_args.args[1], processor.ProcessorDeps)
        init_client.assert_awaited_once()
        close_client.assert_awaited_once()
        close_ai.assert_awaited_once()
        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING

    @pytest.mark.asyncio
    async def test_main_closes_clients_when_the_poller_crashes(self, restore_http_loggers):
        with patch.object(config, "APP_COMPONENT", "telegram-poller"), patch.object(
            telegram_service, "init_http_client", AsyncMock()
        ), patch.object(telegram_service, "close_http_client", AsyncMock()) as close_client, patch.object(
            ai_service, "close_ai_clients", AsyncMock()
        ) as close_ai, patch.object(
            telegram_poller, "run_poller", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            with pytest.raises(RuntimeError):
                await telegram_poller.main()

        close_client.assert_awaited_once()
        close_ai.assert_awaited_once()
