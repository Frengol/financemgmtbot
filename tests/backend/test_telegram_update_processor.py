import os
from unittest.mock import AsyncMock, MagicMock, patch

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

import handlers
import telegram_service
import telegram_update_ledger
import telegram_update_processor as processor
from ai_service import AIProviderPermanentError, AIProviderRetryableError
from telegram_service import TelegramPermanentError, TelegramRetryableError
from telegram_update_ledger import OCRRoundLimitReached, UpdateClaim


DONE = processor.UpdateOutcome.DONE
RETRY = processor.UpdateOutcome.RETRY
MESSAGE_UPDATE = {"update_id": 900, "message": {"chat": {"id": 1}, "from": {"id": 7}, "text": "x"}}


def make_deps(**overrides):
    values = {
        "claim_update": AsyncMock(return_value=UpdateClaim(True, "processing", 1, None)),
        "update_stage": AsyncMock(),
        "mark_completed": AsyncMock(),
        "mark_failed": AsyncMock(),
        "mark_terminal_failed": AsyncMock(),
        "prepare_terminal_failure": AsyncMock(),
        "reserve_ocr_round": AsyncMock(return_value=1),
        "reset_ocr_rounds": AsyncMock(),
        "processar_update_assincrono": AsyncMock(),
        "editar_mensagem_telegram": AsyncMock(),
    }
    values.update(overrides)
    return processor.ProcessorDeps(**values)


def result(outcome, code=None):
    return processor.UpdateResult(outcome, code)


class TestUpdateIdExtraction:
    @pytest.mark.parametrize(
        ("update", "expected"),
        [
            ({"update_id": 5}, 5),
            ({"update_id": True}, None),
            ({"update_id": "5"}, None),
            ({}, None),
            (["update_id", 5], None),
            (None, None),
        ],
    )
    def test_only_plain_integer_update_ids_are_accepted(self, update, expected):
        assert processor.extract_update_id(update) == expected


class TestDefaultDeps:
    def test_default_deps_use_real_collaborators(self):
        deps = processor.default_deps()

        assert deps.claim_update is telegram_update_ledger.claim_update
        assert deps.mark_completed is telegram_update_ledger.mark_completed
        assert deps.processar_update_assincrono is handlers.processar_update_assincrono
        assert deps.editar_mensagem_telegram is telegram_service.editar_mensagem_telegram


class TestClaimOutcomes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["completed", "terminal_failed"])
    async def test_already_final_update_is_done_without_processing(self, status):
        deps = make_deps(claim_update=AsyncMock(return_value=UpdateClaim(False, status, 2, None)))

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(DONE)
        deps.processar_update_assincrono.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_active_lease_is_retried(self):
        deps = make_deps(claim_update=AsyncMock(return_value=UpdateClaim(False, "processing", 1, None)))

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(RETRY, "LEASE_ACTIVE")
        deps.processar_update_assincrono.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claim_failure_is_retried_as_ledger_unavailable(self):
        deps = make_deps(claim_update=AsyncMock(side_effect=RuntimeError("private database detail")))

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(RETRY, "LEDGER_UNAVAILABLE")


class TestTerminalNoticeOutcomes:
    @staticmethod
    def _terminal_claim():
        return UpdateClaim(True, "processing", 2, 55, terminal_reason="ocr_unavailable", error_code="ocr_down")

    @pytest.mark.asyncio
    async def test_delivered_terminal_notice_is_done(self):
        deps = make_deps(claim_update=AsyncMock(return_value=self._terminal_claim()))

        outcome = await processor.process_telegram_update(MESSAGE_UPDATE, deps)

        assert outcome == result(DONE, "TERMINAL_FAILURE")
        deps.editar_mensagem_telegram.assert_awaited_once()
        assert deps.mark_terminal_failed.await_args.kwargs["delivery_confirmed"] is True
        deps.processar_update_assincrono.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (TelegramRetryableError("later"), result(RETRY, "TERMINAL_NOTICE_RETRY")),
            (TelegramPermanentError("gone"), result(DONE, "TERMINAL_NOTICE_UNDELIVERABLE")),
            (RuntimeError("unexpected"), result(RETRY, "TERMINAL_NOTICE_RETRY")),
        ],
    )
    async def test_terminal_notice_delivery_errors_map_to_outcomes(self, error, expected):
        deps = make_deps(
            claim_update=AsyncMock(return_value=self._terminal_claim()),
            editar_mensagem_telegram=AsyncMock(side_effect=error),
        )

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == expected

    @pytest.mark.asyncio
    async def test_terminal_notice_ledger_failure_is_retried(self):
        deps = make_deps(
            claim_update=AsyncMock(return_value=self._terminal_claim()),
            mark_terminal_failed=AsyncMock(side_effect=RuntimeError("ledger down")),
        )

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(RETRY, "LEDGER_UNAVAILABLE")


class TestProcessingOutcomes:
    @pytest.mark.asyncio
    async def test_successful_processing_is_done_and_marks_completed(self):
        deps = make_deps()

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(DONE)

        kwargs = deps.processar_update_assincrono.await_args.kwargs
        assert kwargs["source_update_id"] == 900
        assert kwargs["worker_attempt"] == 1
        deps.mark_completed.assert_awaited_once()
        assert deps.mark_completed.await_args.args[0] == 900

    @pytest.mark.asyncio
    async def test_processing_callbacks_reach_the_ledger(self):
        async def run_callbacks(update, **kwargs):
            await kwargs["stage_callback"]("ocr", progress_message_id=77)
            assert await kwargs["ocr_round_callback"]() == 2
            await kwargs["ocr_success_callback"]()

        deps = make_deps(
            processar_update_assincrono=AsyncMock(side_effect=run_callbacks),
            reserve_ocr_round=AsyncMock(return_value=2),
        )

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(DONE)
        assert deps.update_stage.await_args.args[2] == "ocr"
        assert deps.update_stage.await_args.kwargs == {"progress_message_id": 77}
        deps.reset_ocr_rounds.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_permanent_ai_failure_becomes_rejected_terminal_notice(self):
        deps = make_deps(
            claim_update=AsyncMock(return_value=UpdateClaim(True, "processing", 1, 55)),
            processar_update_assincrono=AsyncMock(
                side_effect=AIProviderPermanentError("bad receipt", error_code="ocr_invalid")
            ),
        )

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(DONE, "TERMINAL_FAILURE")
        assert deps.prepare_terminal_failure.await_args.kwargs["reason"] == "ocr_rejected"

    @pytest.mark.asyncio
    async def test_permanent_ai_failure_with_ledger_error_is_retried(self):
        deps = make_deps(
            processar_update_assincrono=AsyncMock(
                side_effect=AIProviderPermanentError("bad receipt", error_code="ocr_invalid")
            ),
            prepare_terminal_failure=AsyncMock(side_effect=RuntimeError("ledger down")),
        )

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(RETRY, "LEDGER_UNAVAILABLE")

    @pytest.mark.asyncio
    async def test_permanent_telegram_failure_is_terminal(self):
        deps = make_deps(processar_update_assincrono=AsyncMock(side_effect=TelegramPermanentError("blocked")))

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(DONE, "TERMINAL_FAILURE")
        assert deps.prepare_terminal_failure.await_args.kwargs["reason"] == "telegram_delivery_permanent"
        assert deps.mark_terminal_failed.await_args.kwargs["delivery_confirmed"] is False

    @pytest.mark.asyncio
    async def test_permanent_telegram_failure_with_ledger_error_is_retried(self):
        deps = make_deps(
            processar_update_assincrono=AsyncMock(side_effect=TelegramPermanentError("blocked")),
            mark_terminal_failed=AsyncMock(side_effect=RuntimeError("ledger down")),
        )

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(RETRY, "LEDGER_UNAVAILABLE")

    @pytest.mark.asyncio
    async def test_ocr_round_limit_becomes_unavailable_terminal_notice(self):
        deps = make_deps(processar_update_assincrono=AsyncMock(side_effect=OCRRoundLimitReached("limit")))

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(DONE, "TERMINAL_FAILURE")
        assert deps.prepare_terminal_failure.await_args.kwargs["reason"] == "ocr_unavailable"

    @pytest.mark.asyncio
    async def test_retryable_ocr_failure_on_last_round_is_terminal(self):
        async def fail_on_last_round(update, **kwargs):
            await kwargs["stage_callback"]("ocr")
            await kwargs["ocr_round_callback"]()
            raise AIProviderRetryableError("ocr down", error_code="ocr_timeout")

        deps = make_deps(
            processar_update_assincrono=AsyncMock(side_effect=fail_on_last_round),
            reserve_ocr_round=AsyncMock(return_value=processor.OCR_MAX_ROUNDS),
        )

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(DONE, "TERMINAL_FAILURE")
        assert deps.prepare_terminal_failure.await_args.kwargs["reason"] == "ocr_unavailable"

    @pytest.mark.asyncio
    async def test_ocr_terminal_notice_with_ledger_error_is_retried(self):
        deps = make_deps(
            processar_update_assincrono=AsyncMock(side_effect=OCRRoundLimitReached("limit")),
            prepare_terminal_failure=AsyncMock(side_effect=RuntimeError("ledger down")),
        )

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(RETRY, "LEDGER_UNAVAILABLE")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mark_failed_error", [None, RuntimeError("ledger down")])
    async def test_generic_failure_is_retried_even_when_marking_fails(self, mark_failed_error):
        deps = make_deps(
            processar_update_assincrono=AsyncMock(side_effect=ValueError("boom")),
            mark_failed=AsyncMock(side_effect=mark_failed_error),
        )

        assert await processor.process_telegram_update(MESSAGE_UPDATE, deps) == result(RETRY, "PROCESSING_FAILED")
        assert deps.mark_failed.await_args.kwargs == {"stage": "processing", "error_code": "ValueError"}


def logged(caplog, event):
    return [record.msg for record in caplog.records if isinstance(record.msg, dict) and record.msg.get("event") == event]


STRANGER_ID = 987654321
ALLOWED_ID = 7


def message_from(user_id, text="segredo financeiro 123,45"):
    return {"update_id": 901, "message": {"chat": {"id": 1}, "from": {"id": user_id}, "text": text}}


def callback_from(user_id):
    return {
        "update_id": 902,
        "callback_query": {"id": "cb", "from": {"id": user_id}, "data": "aprovar_x", "message": {"chat": {"id": 1}}},
    }


class TestSenderAllowlist:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "update",
        [
            message_from(STRANGER_ID),
            callback_from(STRANGER_ID),
            {"update_id": 903, "message": {"chat": {"id": 1}, "text": "sem remetente"}},
            {"update_id": 904, "edited_message": {"chat": {"id": 1}, "from": {"id": ALLOWED_ID}, "text": "x"}},
            {"update_id": 905, "message": {"chat": {"id": 1}, "from": {"id": True}, "text": "x"}},
            {"update_id": 906, "message": {"chat": {"id": 1}, "from": "7", "text": "x"}},
            # The handler takes the callback branch whenever the key exists, so that is the
            # sender that must be checked, never a listed `message.from` riding along.
            {
                "update_id": 907,
                "callback_query": "x",
                "message": {"chat": {"id": 1}, "from": {"id": ALLOWED_ID}, "text": "x"},
            },
            {
                "update_id": 908,
                "callback_query": {"id": "cb", "from": {"id": STRANGER_ID}, "data": "aprovar_x"},
                "message": {"chat": {"id": 1}, "from": {"id": ALLOWED_ID}, "text": "x"},
            },
        ],
    )
    async def test_unlisted_or_missing_sender_is_done_before_any_effect(self, update):
        deps = make_deps(allowed_user_ids=frozenset({ALLOWED_ID, 1}))

        assert await processor.process_telegram_update(update, deps) == result(DONE)

        deps.claim_update.assert_not_awaited()
        deps.processar_update_assincrono.assert_not_awaited()
        deps.editar_mensagem_telegram.assert_not_awaited()
        deps.mark_completed.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("update", [message_from(ALLOWED_ID), callback_from(ALLOWED_ID)])
    async def test_listed_sender_is_processed(self, update):
        deps = make_deps(allowed_user_ids=frozenset({ALLOWED_ID}))

        assert await processor.process_telegram_update(update, deps) == result(DONE)

        deps.claim_update.assert_awaited_once()
        deps.processar_update_assincrono.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disabled_allowlist_keeps_current_behavior(self):
        deps = make_deps()

        assert deps.allowed_user_ids is None
        assert await processor.process_telegram_update(message_from(STRANGER_ID), deps) == result(DONE)
        deps.processar_update_assincrono.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejection_log_has_no_content_or_raw_sender_id(self, caplog):
        deps = make_deps(allowed_user_ids=frozenset({ALLOWED_ID}))

        with caplog.at_level("INFO"):
            await processor.process_telegram_update(message_from(STRANGER_ID), deps)

        [entry] = logged(caplog, "telegram_update_sender_rejected")
        assert entry["update_id"] == 901
        assert len(entry["sender_ref"]) == 12
        serialized = repr([record.msg for record in caplog.records]) + caplog.text
        assert str(STRANGER_ID) not in serialized
        assert "segredo financeiro" not in serialized

    def test_sender_reference_is_stable_and_keyed(self):
        first = processor.sender_reference(STRANGER_ID)

        assert first == processor.sender_reference(STRANGER_ID)
        assert first != processor.sender_reference(STRANGER_ID + 1)
        assert first != processor.hashlib.sha256(str(STRANGER_ID).encode()).hexdigest()[:12]
        assert processor.sender_reference(None) is None

    def test_default_deps_use_configured_allowlist(self):
        with patch("config.TELEGRAM_ALLOWED_USER_IDS", frozenset({ALLOWED_ID})):
            assert processor.default_deps().allowed_user_ids == frozenset({ALLOWED_ID})


class TestWorkerRouteAllowlist:
    @pytest.mark.asyncio
    async def test_worker_route_acknowledges_stranger_without_touching_the_ledger(self):
        from web_app import worker_routes

        app = worker_routes.create_worker_app_for_test()
        async with app.test_client() as client:
            with patch.object(worker_routes, "TELEGRAM_ALLOWED_USER_IDS", frozenset({ALLOWED_ID})), patch.object(
                worker_routes, "claim_update", AsyncMock()
            ) as claim:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json=message_from(STRANGER_ID),
                    headers={"X-CloudTasks-TaskName": "task-901", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 200
        assert await response.get_json() == {"status": "ok"}
        claim.assert_not_awaited()
