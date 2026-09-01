import json
import os
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
    "TELEGRAM_TASKS_PROJECT": "financemgmtbot",
    "TELEGRAM_TASKS_LOCATION": "southamerica-east1",
    "TELEGRAM_TASKS_QUEUE": "telegram-updates",
    "TELEGRAM_WORKER_URL": "https://worker.example.run.app",
    "TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT": "telegram-task-invoker@financemgmtbot.iam.gserviceaccount.com",
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

import db_repository
import ai_service
import handlers
import main
import security
import telegram_service
import telegram_tasks
import telegram_update_ledger
from admin_runtime import approvals as admin_approvals
from web_app import webhook_routes, worker_routes


@pytest.fixture
def telegram_client():
    client = AsyncMock()
    telegram_service.http_client = client
    yield client
    telegram_service.http_client = None


class TestTaskProducer:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "update",
        [[], {"update_id": True}, {"update_id": 1, "message": {"text": "x" * 75_000}}],
    )
    async def test_rejects_unqueueable_payloads(self, update):
        with pytest.raises(telegram_tasks.InvalidTelegramUpdate):
            await telegram_tasks.enqueue_telegram_update(update, client=MagicMock())

    @pytest.mark.asyncio
    async def test_missing_queue_configuration_fails_closed(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_TASKS_PROJECT", raising=False)
        with pytest.raises(RuntimeError, match="TELEGRAM_TASKS_PROJECT"):
            await telegram_tasks.enqueue_telegram_update({"update_id": 1}, client=MagicMock())

    def test_lazy_client_requires_dependency_and_caches_created_client(self):
        with patch.object(telegram_tasks, "_client", None), patch.object(telegram_tasks, "tasks_v2", None), pytest.raises(
            RuntimeError, match="not installed"
        ):
            telegram_tasks._get_client()

        created = MagicMock()
        provider = MagicMock()
        provider.CloudTasksAsyncClient.return_value = created
        with patch.object(telegram_tasks, "_client", None), patch.object(telegram_tasks, "tasks_v2", provider):
            assert telegram_tasks._get_client() is created
            assert telegram_tasks._get_client() is created
        provider.CloudTasksAsyncClient.assert_called_once()

    @pytest.mark.asyncio
    async def test_named_oidc_task_contains_only_the_update(self):
        client = MagicMock()
        client.create_task = AsyncMock()
        client.queue_path.return_value = (
            "projects/financemgmtbot/locations/southamerica-east1/queues/telegram-updates"
        )
        client.task_path.return_value = (
            "projects/financemgmtbot/locations/southamerica-east1/queues/telegram-updates/tasks/stable"
        )
        client.create_task.return_value = MagicMock(name="created-task")
        update = {"update_id": 611390353, "message": {"chat": {"id": 123}, "text": "teste"}}

        result = await telegram_tasks.enqueue_telegram_update(update, client=client)

        request = client.create_task.await_args.kwargs["request"]
        task = request["task"]
        assert request["parent"].endswith("/queues/telegram-updates")
        assert task["name"].startswith(f"{request['parent']}/tasks/telegram-")
        assert json.loads(task["http_request"]["body"].decode("utf-8")) == update
        assert task["http_request"]["url"] == "https://worker.example.run.app/internal/tasks/telegram-update"
        assert task["http_request"]["oidc_token"] == {
            "service_account_email": "telegram-task-invoker@financemgmtbot.iam.gserviceaccount.com",
            "audience": "https://worker.example.run.app",
        }
        assert result.created is True

    @pytest.mark.asyncio
    async def test_existing_named_task_is_an_idempotent_enqueue_success(self):
        from google.api_core.exceptions import AlreadyExists

        client = MagicMock()
        client.create_task = AsyncMock()
        client.queue_path.return_value = "queue"
        client.create_task.side_effect = AlreadyExists("duplicate")

        result = await telegram_tasks.enqueue_telegram_update(
            {"update_id": 42, "message": {"chat": {"id": 1}, "text": "x"}},
            client=client,
        )

        assert result.created is False
        assert result.duplicate is True

    @pytest.mark.asyncio
    async def test_rejects_update_without_integer_update_id(self):
        with pytest.raises(telegram_tasks.InvalidTelegramUpdate):
            await telegram_tasks.enqueue_telegram_update({"message": {}}, client=AsyncMock())


class _StrictGetClient:
    """Reproduz a assinatura real do httpx.AsyncClient.get (sem kwarg json)."""

    def __init__(self):
        self.get_calls = []

    async def get(self, url, *, params=None, timeout=None):
        self.get_calls.append((url, params))
        if "/getFile" in url:
            return httpx.Response(
                200,
                json={"ok": True, "result": {"file_path": "voice/file_223.oga"}},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(200, content=b"ogg-bytes", request=httpx.Request("GET", url))


class TestTelegramServiceHttp:
    @pytest.mark.asyncio
    async def test_baixar_arquivo_telegram_usa_get_sem_json(self):
        client = _StrictGetClient()
        with patch.object(telegram_service, "http_client", client):
            content = await telegram_service.baixar_arquivo_telegram("FILE_ID")

        assert content == b"ogg-bytes"
        assert client.get_calls[0][1] == {"file_id": "FILE_ID"}

    @pytest.mark.asyncio
    async def test_media_download_retries_one_timeout_then_confirms(self):
        client = AsyncMock()
        client.get.side_effect = [
            httpx.Response(
                200,
                json={"ok": True, "result": {"file_path": "voice/file.oga"}},
                request=httpx.Request("GET", "https://api.telegram.org"),
            ),
            httpx.ReadTimeout("download timeout"),
            httpx.Response(200, content=b"bytes", request=httpx.Request("GET", "https://api.telegram.org/file")),
        ]
        stages = AsyncMock()
        with patch.object(telegram_service, "http_client", client):
            result = await telegram_service.baixar_arquivo_telegram(
                "FILE_ID", stage_callback=stages, progress_message_id=77
            )

        assert result == b"bytes"
        assert client.get.await_count == 3
        assert client.get.await_args_list[1].kwargs["timeout"] == telegram_service.TELEGRAM_MEDIA_DOWNLOAD_TIMEOUT
        assert [call.args[0] for call in stages.await_args_list] == [
            "media_get_file", "media_download", "media_download"
        ]

    @pytest.mark.asyncio
    async def test_get_file_retries_one_network_timeout(self):
        client = AsyncMock()
        client.get.side_effect = [
            httpx.ReadTimeout("metadata timeout"),
            httpx.Response(
                200,
                json={"ok": True, "result": {"file_path": "voice/file.oga"}},
                request=httpx.Request("GET", "https://api.telegram.org"),
            ),
            httpx.Response(200, content=b"bytes", request=httpx.Request("GET", "https://api.telegram.org/file")),
        ]
        with patch.object(telegram_service, "http_client", client), patch("telegram_service.asyncio.sleep", AsyncMock()):
            assert await telegram_service.baixar_arquivo_telegram("FILE_ID") == b"bytes"

        assert client.get.await_count == 3

    @pytest.mark.asyncio
    async def test_get_file_rate_limit_is_not_retried_internally(self):
        client = AsyncMock()
        client.get.return_value = httpx.Response(
            429,
            json={"ok": False, "error_code": 429, "description": "Too Many Requests"},
            request=httpx.Request("GET", "https://api.telegram.org"),
        )
        with patch.object(telegram_service, "http_client", client):
            with pytest.raises(telegram_service.TelegramRetryableError):
                await telegram_service.baixar_arquivo_telegram("FILE_ID")

        assert client.get.await_count == 1


class TestWebhookEnqueue:
    @pytest.mark.asyncio
    async def test_acknowledges_only_after_enqueue_confirmation(self):
        async with main.app.test_client() as client:
            with patch.object(webhook_routes, "enqueue_telegram_update", AsyncMock()) as enqueue:
                response = await client.post(
                    "/",
                    json={"update_id": 9001, "message": {"chat": {"id": 1}, "text": "hi"}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": webhook_routes.SECRET_TOKEN},
                )

        assert response.status_code == 200
        enqueue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enqueue_failure_returns_503_for_telegram_retry(self):
        async with main.app.test_client() as client:
            with patch.object(
                webhook_routes,
                "enqueue_telegram_update",
                AsyncMock(side_effect=RuntimeError("provider detail must not leak")),
            ):
                response = await client.post(
                    "/",
                    json={"update_id": 9002, "message": {"chat": {"id": 1}, "text": "hi"}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": webhook_routes.SECRET_TOKEN},
                )

        assert response.status_code == 503
        assert "provider detail" not in await response.get_data(as_text=True)


class TestLedger:
    @pytest.mark.asyncio
    async def test_invalid_claim_response_is_rejected(self):
        rpc = MagicMock()
        rpc.execute.return_value = MagicMock(data=[])
        supabase = MagicMock()
        supabase.rpc.return_value = rpc
        with patch.object(
            telegram_update_ledger.asyncio,
            "to_thread",
            AsyncMock(side_effect=lambda operation: operation()),
        ), pytest.raises(RuntimeError, match="invalid response"):
            await telegram_update_ledger.claim_update(42, "lease-invalid", client=supabase)

    @pytest.mark.asyncio
    async def test_claim_uses_atomic_rpc_and_preserves_completed(self):
        rpc = MagicMock()
        rpc.execute.return_value = MagicMock(
            data=[{"claimed": False, "status": "completed", "attempt_count": 2, "progress_message_id": 99}]
        )
        supabase = MagicMock()
        supabase.rpc.return_value = rpc

        with patch.object(
            telegram_update_ledger.asyncio,
            "to_thread",
            AsyncMock(side_effect=lambda operation: operation()),
        ):
            result = await telegram_update_ledger.claim_update(42, "lease-a", client=supabase)

        supabase.rpc.assert_called_once_with(
            "claim_webhook_update",
            {"p_update_id": 42, "p_lease_owner": "lease-a", "p_lease_seconds": 180},
        )
        assert result.claimed is False
        assert result.status == "completed"
        assert result.progress_message_id == 99

    @pytest.mark.asyncio
    async def test_expired_lease_is_reclaimed_by_database_result(self):
        rpc = MagicMock()
        rpc.execute.return_value = MagicMock(
            data=[{"claimed": True, "status": "processing", "attempt_count": 3, "progress_message_id": 77}]
        )
        supabase = MagicMock()
        supabase.rpc.return_value = rpc

        with patch.object(
            telegram_update_ledger.asyncio,
            "to_thread",
            AsyncMock(side_effect=lambda operation: operation()),
        ):
            result = await telegram_update_ledger.claim_update(42, "lease-b", client=supabase)

        assert result.claimed is True
        assert result.attempt_count == 3

    @pytest.mark.asyncio
    async def test_rejected_state_transition_raises(self):
        rpc = MagicMock()
        rpc.execute.return_value = MagicMock(data=False)
        supabase = MagicMock()
        supabase.rpc.return_value = rpc

        with patch.object(telegram_update_ledger, "supabase", supabase), patch.object(
            telegram_update_ledger.asyncio,
            "to_thread",
            AsyncMock(side_effect=lambda operation: operation()),
        ), pytest.raises(RuntimeError, match="Ledger transition rejected"):
            await telegram_update_ledger.mark_completed(42, "lease-c")

    @pytest.mark.asyncio
    async def test_all_state_transitions_accept_atomic_rpc_success(self):
        rpc = MagicMock()
        rpc.execute.return_value = MagicMock(data=True)
        supabase = MagicMock()
        supabase.rpc.return_value = rpc
        with patch.object(telegram_update_ledger, "supabase", supabase), patch.object(
            telegram_update_ledger.asyncio,
            "to_thread",
            AsyncMock(side_effect=lambda operation: operation()),
        ):
            await telegram_update_ledger.update_stage(42, "lease-d", "ocr", progress_message_id=8)
            await telegram_update_ledger.mark_completed(42, "lease-d")
            await telegram_update_ledger.mark_failed(42, "lease-d", stage="llm", error_code="x" * 100)
            await telegram_update_ledger.mark_terminal_failed(42, "lease-d", stage="delivery", error_code="bad")

        assert [call.args[0] for call in supabase.rpc.call_args_list] == [
            "update_webhook_stage",
            "complete_webhook_update",
            "fail_webhook_update",
            "terminal_fail_webhook_update",
        ]
        assert len(supabase.rpc.call_args_list[2].args[1]["p_error_code"]) == 80


class TestFinancialEffects:
    def test_pending_summary_marker_is_encrypted_and_updated(self):
        table = MagicMock()
        response = MagicMock(data=[{"id": "pending-1"}])
        table.update.return_value.eq.return_value.execute.return_value = response
        with patch.object(security.supabase, "table", return_value=table):
            security.mark_pending_summary_sent("pending-1", {"itens": []})

        update_payload = table.update.call_args.args[0]
        assert "payload_ciphertext" in update_payload
        assert security.decrypt_pending_payload(update_payload["payload_ciphertext"])["_approval_summary_sent"] is True

    def test_pending_summary_marker_requires_persistence_confirmation(self):
        table = MagicMock()
        table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=None)
        with patch.object(security.supabase, "table", return_value=table):
            with pytest.raises(RuntimeError, match="delivery marker"):
                security.mark_pending_summary_sent("pending-1", {"itens": []})

    def test_installments_use_stable_effect_keys_and_conflict_safe_upsert(self):
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[])
        supabase = MagicMock()
        supabase.table.return_value = table
        payload = {
            "data": "2026-08-15",
            "valor_total": 90,
            "parcelas": 3,
            "categoria": "Transporte",
            "descricao": "Revisão",
            "metodo_pagamento": "Cartão de Crédito",
            "conta": "Conta",
        }

        with patch.object(db_repository, "supabase", supabase):
            records = db_repository.inserir_no_banco(payload, source_update_id=700)

        inserted = table.upsert.call_args.args[0]
        assert [row["source_record_key"] for row in inserted] == [
            "installment:0001",
            "installment:0002",
            "installment:0003",
        ]
        assert all(row["source_update_id"] == 700 for row in inserted)
        assert table.upsert.call_args.kwargs == {
            "on_conflict": "source_update_id,source_record_key",
            "ignore_duplicates": True,
        }
        assert records == inserted

    def test_pending_receipt_id_is_stable_for_replay(self):
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "inserted"}])
        supabase = MagicMock()
        supabase.table.return_value = table
        payload = {"itens": [], "metodo_pagamento": "Pix", "conta": "Conta"}

        with patch.object(security, "supabase", supabase):
            first = security.store_pending_item(payload, source_update_id=701)
            second = security.store_pending_item(payload, source_update_id=701)

        assert first["id"] == second["id"]
        inserted = table.upsert.call_args.args[0]
        assert inserted["source_update_id"] == 701
        assert table.upsert.call_args.kwargs == {
            "on_conflict": "source_update_id",
            "ignore_duplicates": True,
        }

    def test_loads_canonical_financial_records_by_source_update(self):
        records = [{"id": 1, "descricao": "Persistido", "source_record_key": "receipt:0001"}]
        table = MagicMock()
        table.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=records)
        supabase = MagicMock()
        supabase.table.return_value = table

        with patch.object(db_repository, "supabase", supabase):
            result = db_repository.load_records_by_source_update_id(701)

        assert result == records
        table.select.return_value.eq.assert_called_once_with("source_update_id", 701)
        table.select.return_value.eq.return_value.order.assert_called_once_with("source_record_key")

    def test_source_lookups_fail_closed_for_missing_or_malformed_results(self):
        assert db_repository.load_records_by_source_update_id(None) == []
        assert security.load_pending_item_by_source_update_id(None) is None

        transaction_table = MagicMock()
        transaction_table.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=None)
        pending_table = MagicMock()
        pending_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=["bad"])
        supabase = MagicMock()
        supabase.table.side_effect = lambda name: pending_table if name == "cache_aprovacao" else transaction_table

        with patch.object(db_repository, "supabase", supabase), patch.object(security, "supabase", supabase):
            assert db_repository.load_records_by_source_update_id(701) == []
            assert security.load_pending_item_by_source_update_id(701) is None

    def test_pending_lookup_hydrates_the_canonical_payload(self):
        payload = {"itens": [], "metodo_pagamento": "Pix", "conta": "Conta"}
        table = MagicMock()
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{
            "id": "pending-701",
            "kind": "receipt_batch",
            "payload_ciphertext": security.encrypt_pending_payload(payload),
            "payload_key_version": security.PENDING_KEY_VERSION,
            "preview_json": {"summary": "Cupom pendente"},
            "source_update_id": 701,
        }])
        supabase = MagicMock()
        supabase.table.return_value = table

        with patch.object(security, "supabase", supabase):
            result = security.load_pending_item_by_source_update_id(701)

        assert result["payload"] == payload
        assert result["source_update_id"] == 701

    def test_pending_conflict_fails_closed_when_winner_cannot_be_loaded(self):
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[])
        table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        supabase = MagicMock()
        supabase.table.return_value = table

        with patch.object(security, "supabase", supabase), pytest.raises(
            RuntimeError, match="conflict winner is unavailable"
        ):
            security.store_pending_item({"itens": []}, source_update_id=701)

    def test_pending_conflict_returns_the_first_persisted_payload(self):
        first_payload = {"itens": [{"nome": "A", "valor_bruto": 10}], "metodo_pagamento": "Pix", "conta": "Conta"}
        retry_payload = {"itens": [{"nome": "B", "valor_bruto": 99}], "metodo_pagamento": "Pix", "conta": "Conta"}
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[])
        table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "id": f"tu_{security.hash_text('701')[:20]}",
                "kind": "receipt_batch",
                "payload_ciphertext": security.encrypt_pending_payload(first_payload),
                "payload_key_version": security.PENDING_KEY_VERSION,
                "preview_json": security.build_pending_preview("receipt_batch", first_payload),
                "created_at": "2026-08-15T10:00:00",
                "expires_at": "2099-08-15T10:00:00",
                "origin_chat_id": "1",
                "origin_user_id": "2",
                "source_update_id": 701,
                "payload": {},
            }]
        )
        supabase = MagicMock()
        supabase.table.return_value = table

        with patch.object(security, "supabase", supabase):
            result = security.store_pending_item(
                retry_payload,
                source_update_id=701,
                origin_chat_id=1,
                origin_user_id=2,
            )

        assert result["payload"] == first_payload
        assert result["preview"]["itens"] == ["A"]

    @pytest.mark.asyncio
    async def test_replay_resumes_persisted_pending_payload_before_calling_ai(self):
        first_payload = {
            "itens": [{"nome": "Persistido", "valor_bruto": 10, "desconto_item": 0, "categoria": "Mercado"}],
            "metodo_pagamento": "Pix",
            "conta": "Conta",
            "desconto_global": 0,
        }
        pending = {"id": "pending-1", "kind": "receipt_batch", "payload": first_payload}
        delivery = AsyncMock()

        with patch.object(handlers, "load_pending_item_by_source_update_id", return_value=pending), patch.object(
            handlers, "load_records_by_source_update_id", return_value=[]
        ), patch.object(handlers, "processar_texto_com_llm", AsyncMock()) as llm, patch.object(
            handlers, "_deliver_final_message", delivery
        ):
            await handlers.processar_update_assincrono(
                {"update_id": 701, "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "retry"}},
                source_update_id=701,
            )

        llm.assert_not_awaited()
        assert "Mercado" in delivery.await_args.args[2]
        assert "R$ 10.00" in delivery.await_args.args[2]
        assert delivery.await_args.args[3]["inline_keyboard"][0][0]["callback_data"] == "aprovar_pending-1"

    @pytest.mark.asyncio
    async def test_replay_resumes_persisted_financial_records_before_calling_ai(self):
        records = [{
            "data": "2026-08-15",
            "valor": 10.0,
            "categoria": "Mercado",
            "descricao": "Persistido",
            "metodo_pagamento": "Pix",
            "conta": "Conta",
        }]
        delivery = AsyncMock()

        with patch.object(handlers, "load_records_by_source_update_id", return_value=records) as load_records, patch.object(
            handlers, "load_pending_item_by_source_update_id"
        ) as load_pending, patch.object(handlers, "processar_texto_com_llm", AsyncMock()) as llm, patch.object(
            handlers, "_deliver_final_message", delivery
        ):
            await handlers.processar_update_assincrono(
                {"update_id": 701, "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "retry"}},
                source_update_id=701,
            )

        llm.assert_not_awaited()
        load_pending.assert_not_called()
        load_records.assert_called_once_with(701, 1)
        assert "Mercado" in delivery.await_args.args[2]
        assert "R$ 10.00" in delivery.await_args.args[2]

    def test_pending_conflict_falls_back_to_canonical_source_lookup(self):
        winner_payload = {"itens": [{"nome": "A", "valor_bruto": 10}], "metodo_pagamento": "Pix", "conta": "Conta"}
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[])
        table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "legacy-random-id",
                "kind": "receipt_batch",
                "payload_ciphertext": security.encrypt_pending_payload(winner_payload),
                "payload_key_version": security.PENDING_KEY_VERSION,
                "preview_json": security.build_pending_preview("receipt_batch", winner_payload),
                "created_at": "2026-08-15T10:00:00",
                "expires_at": "2099-08-15T10:00:00",
                "origin_chat_id": "1",
                "origin_user_id": "2",
                "source_update_id": 701,
                "payload": {},
            }]
        )
        supabase = MagicMock()
        supabase.table.return_value = table

        with patch.object(security, "supabase", supabase):
            result = security.store_pending_item(
                {"itens": []},
                source_update_id=701,
                origin_chat_id=1,
                origin_user_id=2,
            )

        assert result["payload"] == winner_payload
        assert result["id"] == "legacy-random-id"
        table.select.return_value.eq.assert_called_once_with("source_update_id", 701)

    def test_pending_conflict_origin_guard_rejects_cross_chat_winner(self):
        winner_payload = {"itens": [], "metodo_pagamento": "Pix", "conta": "Conta"}
        winner = {
            "id": "legacy-random-id",
            "kind": "receipt_batch",
            "payload_ciphertext": security.encrypt_pending_payload(winner_payload),
            "payload_key_version": security.PENDING_KEY_VERSION,
            "preview_json": security.build_pending_preview("receipt_batch", winner_payload),
            "created_at": "2026-08-15T10:00:00",
            "expires_at": "2099-08-15T10:00:00",
            "origin_chat_id": "2",
            "origin_user_id": "2",
            "source_update_id": 701,
            "payload": {},
        }
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[])
        table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[winner])
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[winner])
        supabase = MagicMock()
        supabase.table.return_value = table

        with patch.object(security, "supabase", supabase), pytest.raises(
            RuntimeError, match="another chat"
        ):
            security.store_pending_item(
                {"itens": []},
                source_update_id=701,
                origin_chat_id=1,
                origin_user_id=2,
            )

    def test_load_records_by_source_update_id_filters_by_origin_chat(self):
        records = [{"id": 1, "descricao": "Persistido", "source_record_key": "receipt:0001"}]
        table = MagicMock()
        table.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=records)
        supabase = MagicMock()
        supabase.table.return_value = table

        with patch.object(db_repository, "supabase", supabase):
            result = db_repository.load_records_by_source_update_id(701, origin_chat_id=5)

        assert result == records
        table.select.return_value.eq.assert_called_once_with("source_update_id", 701)
        table.select.return_value.eq.return_value.eq.assert_called_once_with("source_origin_chat_id", 5)
        table.select.return_value.eq.return_value.eq.return_value.order.assert_called_once_with("source_record_key")

    @pytest.mark.asyncio
    async def test_resume_rejects_pending_from_another_chat(self):
        pending = {
            "id": "pending-1",
            "kind": "receipt_batch",
            "payload": {"itens": []},
            "origin_chat_id": "2",
            "origin_user_id": "2",
        }
        delivery = AsyncMock()

        with patch.object(handlers, "load_pending_item_by_source_update_id", return_value=pending), patch.object(
            handlers, "load_records_by_source_update_id", return_value=[]
        ), patch.object(handlers, "_deliver_final_message", delivery):
            resumed = await handlers._resume_existing_effect(
                chat_id=1,
                source_update_id=701,
                progress_message_id=None,
                origin_user_id=2,
            )

        assert resumed is False
        delivery.assert_not_awaited()

    def test_installments_carry_origin_chat_id(self):
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[])
        supabase = MagicMock()
        supabase.table.return_value = table
        payload = {
            "data": "2026-08-15",
            "valor_total": 90,
            "parcelas": 3,
            "categoria": "Transporte",
            "descricao": "Revisão",
            "metodo_pagamento": "Cartão de Crédito",
            "conta": "Conta",
        }

        with patch.object(db_repository, "supabase", supabase):
            records = db_repository.inserir_no_banco(payload, source_update_id=700, origin_chat_id=5)

        assert all(row["source_origin_chat_id"] == 5 for row in records)

    @pytest.mark.asyncio
    async def test_processing_failure_does_not_send_orphan_failure_notice(self):
        delivery = AsyncMock()
        logmock = MagicMock()
        with patch.object(handlers, "load_records_by_source_update_id", return_value=[]), patch.object(
            handlers, "load_pending_item_by_source_update_id", return_value=None
        ), patch.object(handlers, "processar_texto_com_llm", AsyncMock(side_effect=RuntimeError("boom"))), patch.object(
            handlers, "enviar_mensagem_telegram", delivery
        ), patch.object(handlers, "logger", logmock):
            with pytest.raises(RuntimeError):
                await handlers.processar_update_assincrono(
                    {"update_id": 701, "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "oi"}},
                    source_update_id=701,
                )

        delivery.assert_not_awaited()
        assert logmock.error.call_args.args[0]["update_id"] == 701

    @pytest.mark.asyncio
    async def test_processing_failure_is_silent_on_first_attempt(self):
        delivery = AsyncMock()
        with patch.object(handlers, "load_records_by_source_update_id", return_value=[]), patch.object(
            handlers, "load_pending_item_by_source_update_id", return_value=None
        ), patch.object(handlers, "processar_texto_com_llm", AsyncMock(side_effect=RuntimeError("boom"))), patch.object(
            handlers, "enviar_mensagem_telegram", delivery
        ):
            with pytest.raises(RuntimeError):
                await handlers.processar_update_assincrono(
                    {"update_id": 702, "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "oi"}},
                    source_update_id=702,
                )

        delivery.assert_not_awaited()

    def test_reliability_migration_binds_financial_origin(self):
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase"
            / "migrations"
            / "20260815_telegram_update_reliability.sql"
        )
        content = migration.read_text(encoding="utf-8")
        assert "source_origin_chat_id bigint" in content

    @pytest.mark.asyncio
    async def test_telegram_approval_uses_original_pending_source_identity(self):
        pending = {
            "id": "pending-1",
            "kind": "receipt_batch",
            "payload": {"itens": [], "metodo_pagamento": "Pix", "conta": "Conta"},
            "source_update_id": 701,
        }
        saved = MagicMock(return_value=(0, 0.0, []))

        with patch.object(handlers, "responder_callback_telegram", AsyncMock()), patch.object(
            handlers, "load_pending_item", return_value=pending
        ), patch.object(handlers, "pending_item_expired", return_value=False), patch.object(
            handlers, "matches_pending_origin", return_value=True
        ), patch.object(handlers, "gravar_lote_no_banco_com_registros", saved), patch.object(
            handlers, "remover_teclado_mensagem_telegram", AsyncMock()
        ) as remove_keyboard, patch.object(handlers, "enviar_mensagem_telegram", AsyncMock()) as send_summary, patch.object(
            handlers, "editar_mensagem_telegram", AsyncMock()
        ) as edit_text, patch.object(handlers, "delete_pending_item"):
            await handlers.processar_update_assincrono(
                {
                    "update_id": 999,
                    "callback_query": {
                        "id": "cb",
                        "data": "aprovar_pending-1",
                        "from": {"id": 2},
                        "message": {"chat": {"id": 1}, "message_id": 3},
                    },
                },
                source_update_id=999,
            )

        assert saved.call_args.kwargs["source_update_id"] == 701
        remove_keyboard.assert_awaited_once_with(1, 3)
        send_summary.assert_awaited_once()
        edit_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_telegram_approval_keeps_pending_when_summary_delivery_fails(self):
        pending = {
            "id": "pending-1",
            "kind": "receipt_batch",
            "payload": {"itens": [], "metodo_pagamento": "Pix", "conta": "Conta"},
            "source_update_id": 701,
        }
        delete_pending = MagicMock()
        with patch.object(handlers, "responder_callback_telegram", AsyncMock()), patch.object(
            handlers, "load_pending_item", return_value=pending
        ), patch.object(handlers, "pending_item_expired", return_value=False), patch.object(
            handlers, "matches_pending_origin", return_value=True
        ), patch.object(handlers, "gravar_lote_no_banco_com_registros", return_value=(1, 10.0, [])), patch.object(
            handlers, "remover_teclado_mensagem_telegram", AsyncMock()
        ), patch.object(
            handlers, "enviar_mensagem_telegram", AsyncMock(side_effect=RuntimeError("telegram unavailable"))
        ), patch.object(handlers, "delete_pending_item", delete_pending):
            with pytest.raises(RuntimeError):
                await handlers.processar_update_assincrono(
                    {
                        "update_id": 999,
                        "callback_query": {
                            "id": "cb",
                            "data": "aprovar_pending-1",
                            "from": {"id": 2},
                            "message": {"chat": {"id": 1}, "message_id": 3},
                        },
                    }
                )

        delete_pending.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_approval_retry_with_delivery_marker_does_not_resend_summary(self):
        pending = {
            "id": "pending-1",
            "kind": "receipt_batch",
            "payload": {
                "itens": [],
                "metodo_pagamento": "Pix",
                "conta": "Conta",
                "_approval_summary_sent": True,
            },
            "source_update_id": 701,
        }
        with patch.object(handlers, "responder_callback_telegram", AsyncMock()), patch.object(
            handlers, "load_pending_item", return_value=pending
        ), patch.object(handlers, "pending_item_expired", return_value=False), patch.object(
            handlers, "matches_pending_origin", return_value=True
        ), patch.object(handlers, "gravar_lote_no_banco_com_registros", return_value=(1, 10.0, [])), patch.object(
            handlers, "remover_teclado_mensagem_telegram", AsyncMock()
        ), patch.object(handlers, "enviar_mensagem_telegram", AsyncMock()) as send_summary, patch.object(
            handlers, "delete_pending_item"
        ):
            await handlers.processar_update_assincrono(
                {
                    "update_id": 999,
                    "callback_query": {
                        "id": "cb",
                        "data": "aprovar_pending-1",
                        "from": {"id": 2},
                        "message": {"chat": {"id": 1}, "message_id": 3},
                    },
                }
            )

        send_summary.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_admin_approval_uses_original_pending_source_identity(self):
        pending = {
            "id": "pending-1",
            "kind": "receipt_batch",
            "payload": {"itens": []},
            "source_update_id": 701,
        }
        saved = MagicMock(return_value=(1, 10.0))

        async with main.app.test_request_context("/api/admin/cache-aprovacao/pending-1/approve", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=({"id": "admin"}, None)), patch.object(
                admin_approvals, "load_pending_item", return_value=pending
            ), patch.object(admin_approvals, "pending_item_expired", return_value=False), patch.object(
                admin_approvals, "gravar_lote_no_banco", saved
            ), patch.object(admin_approvals, "delete_pending_item"), patch.object(
                admin_approvals, "registrar_auditoria_admin"
            ):
                response = admin_approvals.aprovar_cache_admin("pending-1")

        assert response.status_code == 200
        assert saved.call_args.kwargs["source_update_id"] == 701


class TestWorkerRoute:
    @pytest.mark.asyncio
    async def test_rejects_missing_task_headers_and_invalid_content(self):
        app = worker_routes.create_worker_app_for_test()
        async with app.test_client() as client:
            missing_headers = await client.post("/internal/tasks/telegram-update", json={"update_id": 1})
            wrong_content = await client.post(
                "/internal/tasks/telegram-update",
                data="text",
                headers={"X-CloudTasks-TaskName": "task", "X-CloudTasks-QueueName": "queue"},
            )
            invalid_update = await client.post(
                "/internal/tasks/telegram-update",
                json={"update_id": True},
                headers={"X-CloudTasks-TaskName": "task", "X-CloudTasks-QueueName": "queue"},
            )
            with patch.object(worker_routes, "MAX_WORKER_BODY_BYTES", -1):
                too_large = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 1},
                    headers={"X-CloudTasks-TaskName": "task", "X-CloudTasks-QueueName": "queue"},
                )

        assert [missing_headers.status_code, wrong_content.status_code, invalid_update.status_code, too_large.status_code] == [
            403,
            415,
            400,
            413,
        ]

    @pytest.mark.asyncio
    async def test_ledger_claim_failure_returns_retryable_response(self):
        app = worker_routes.create_worker_app_for_test()
        async with app.test_client() as client:
            with patch.object(
                worker_routes,
                "claim_update",
                AsyncMock(side_effect=RuntimeError("database detail must stay private")),
            ):
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 43, "message": {"chat": {"id": 1}, "text": "x"}},
                    headers={"X-CloudTasks-TaskName": "task-43", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 503
        assert "database detail" not in await response.get_data(as_text=True)

    @pytest.mark.asyncio
    async def test_worker_never_requests_orphan_failure_notice(self):
        app = worker_routes.create_worker_app_for_test()
        retry_claim = telegram_update_ledger.UpdateClaim(True, "processing", 3, None)
        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=retry_claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock()
            ) as retry_processor, patch.object(worker_routes, "mark_completed", AsyncMock()):
                retry_response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 45, "message": {"chat": {"id": 1}, "text": "x"}},
                    headers={"X-CloudTasks-TaskName": "task-45", "X-CloudTasks-QueueName": "telegram-updates"},
                )
            first_claim = telegram_update_ledger.UpdateClaim(True, "processing", 1, None)
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=first_claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock()
            ) as first_processor, patch.object(worker_routes, "mark_completed", AsyncMock()):
                first_response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 46, "message": {"chat": {"id": 1}, "text": "x"}},
                    headers={"X-CloudTasks-TaskName": "task-46", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert retry_response.status_code == 200
        assert first_response.status_code == 200
        assert "notify_failure" not in retry_processor.await_args.kwargs
        assert "notify_failure" not in first_processor.await_args.kwargs

    @pytest.mark.asyncio
    async def test_completed_update_does_not_run_handler_again(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(False, "completed", 2, None)
        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock()
            ) as processor:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 44, "message": {"chat": {"id": 1}, "text": "x"}},
                    headers={"X-CloudTasks-TaskName": "task-44", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 200
        processor.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_terminal_update_does_not_run_handler_again(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(False, "terminal_failed", 1, None)
        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock()
            ) as processor:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 440, "message": {}},
                    headers={"X-CloudTasks-TaskName": "task-440", "X-CloudTasks-QueueName": "telegram-updates"},
                )
        assert response.status_code == 200
        processor.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_records_stage_and_completion(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(True, "processing", 1, 70)

        async def process(*args, **kwargs):
            await kwargs["stage_callback"]("ocr_completed", 71)

        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock(side_effect=process)
            ), patch.object(worker_routes, "update_stage", AsyncMock()) as stage, patch.object(
                worker_routes, "mark_completed", AsyncMock()
            ) as completed:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 441, "message": {}},
                    headers={"X-CloudTasks-TaskName": "task-441", "X-CloudTasks-QueueName": "telegram-updates"},
                )
        assert response.status_code == 200
        stage.assert_awaited_once()
        completed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_active_lease_returns_503_so_cloud_tasks_retries(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(False, "processing", 1, None)
        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)):
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 45, "message": {"chat": {"id": 1}, "text": "x"}},
                    headers={"X-CloudTasks-TaskName": "task-45", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_failure_is_recorded_and_retried(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(True, "processing", 1, None)
        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock(side_effect=RuntimeError("secret receipt"))
            ), patch.object(worker_routes, "mark_failed", AsyncMock()) as failed:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 46, "message": {"chat": {"id": 1}, "text": "x"}},
                    headers={"X-CloudTasks-TaskName": "task-46", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 503
        failed.assert_awaited_once()
        assert failed.await_args.kwargs["error_code"] == "RuntimeError"
        assert "secret receipt" not in json.dumps(failed.await_args.kwargs)

    @pytest.mark.asyncio
    async def test_ocr_retry_keeps_progress_message_silent(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(True, "processing", 1, None)

        async def fail_ocr(*args, **kwargs):
            await kwargs["stage_callback"]("ocr", 91)
            raise ai_service.AIProviderRetryableError("provider unavailable", error_code="503")

        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock(side_effect=fail_ocr)
            ), patch.object(worker_routes, "update_stage", AsyncMock()), patch.object(
                worker_routes, "mark_failed", AsyncMock()
            ) as failed, patch.object(
                worker_routes, "editar_mensagem_telegram", AsyncMock()
            ) as edit:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 461, "message": {"chat": {"id": 1}, "photo": [{"file_id": "x"}]}},
                    headers={"X-CloudTasks-TaskName": "task-461", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 503
        failed.assert_awaited_once()
        edit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_final_ocr_failure_edits_existing_progress_and_stops_retry(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(True, "processing", 3, 91)

        async def fail_ocr(*args, **kwargs):
            await kwargs["stage_callback"]("ocr", 91)
            raise ai_service.AIProviderRetryableError("provider unavailable", error_code="503")

        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock(side_effect=fail_ocr)
            ), patch.object(worker_routes, "update_stage", AsyncMock()), patch.object(
                worker_routes, "mark_terminal_failed", AsyncMock()
            ) as terminal, patch.object(
                worker_routes, "editar_mensagem_telegram", AsyncMock()
            ) as edit:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 462, "message": {"chat": {"id": 1}, "photo": [{"file_id": "x"}]}},
                    headers={"X-CloudTasks-TaskName": "task-462", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 200
        edit.assert_awaited_once_with(1, 91, worker_routes.OCR_TERMINAL_MESSAGE)
        terminal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_permanent_ocr_failure_edits_existing_progress_and_stops_retry(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(True, "processing", 1, 92)

        async def fail_ocr(*args, **kwargs):
            await kwargs["stage_callback"]("ocr", 92)
            raise ai_service.AIProviderPermanentError("invalid image", error_code="400")

        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock(side_effect=fail_ocr)
            ), patch.object(worker_routes, "update_stage", AsyncMock()), patch.object(
                worker_routes, "mark_terminal_failed", AsyncMock()
            ) as terminal, patch.object(
                worker_routes, "editar_mensagem_telegram", AsyncMock()
            ) as edit:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 463, "message": {"chat": {"id": 1}, "photo": [{"file_id": "x"}]}},
                    headers={"X-CloudTasks-TaskName": "task-463", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 200
        edit.assert_awaited_once_with(1, 92, worker_routes.OCR_TERMINAL_MESSAGE)
        terminal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_permanent_ocr_notice_delivery_failure_keeps_task_retryable(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(True, "processing", 1, 93)

        async def fail_ocr(*args, **kwargs):
            await kwargs["stage_callback"]("ocr", 93)
            raise ai_service.AIProviderPermanentError("bad image", error_code="400")

        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock(side_effect=fail_ocr)
            ), patch.object(worker_routes, "update_stage", AsyncMock()), patch.object(
                worker_routes,
                "editar_mensagem_telegram",
                AsyncMock(side_effect=telegram_service.TelegramRetryableError("temporary")),
            ), patch.object(worker_routes, "mark_failed", AsyncMock()) as failed, patch.object(
                worker_routes, "mark_terminal_failed", AsyncMock()
            ) as terminal:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 464, "message": {"chat": {"id": 1}, "photo": [{"file_id": "x"}]}},
                    headers={"X-CloudTasks-TaskName": "task-464", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 503
        failed.assert_awaited_once()
        assert failed.await_args.kwargs["stage"] == "telegram_delivery"
        terminal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_permanent_telegram_failure_is_terminal(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(True, "processing", 1, None)
        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes,
                "processar_update_assincrono",
                AsyncMock(side_effect=telegram_service.TelegramPermanentError("chat blocked")),
            ), patch.object(worker_routes, "mark_terminal_failed", AsyncMock()) as terminal:
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 47, "message": {"chat": {"id": 1}, "text": "x"}},
                    headers={"X-CloudTasks-TaskName": "task-47", "X-CloudTasks-QueueName": "telegram-updates"},
                )

        assert response.status_code == 200
        terminal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_terminal_transition_failure_is_retried(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(True, "processing", 1, None)
        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes,
                "processar_update_assincrono",
                AsyncMock(side_effect=telegram_service.TelegramPermanentError("blocked")),
            ), patch.object(worker_routes, "mark_terminal_failed", AsyncMock(side_effect=RuntimeError("db"))):
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 48, "message": {}},
                    headers={"X-CloudTasks-TaskName": "task-48", "X-CloudTasks-QueueName": "telegram-updates"},
                )
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_retryable_transition_failure_still_returns_503(self):
        app = worker_routes.create_worker_app_for_test()
        claim = telegram_update_ledger.UpdateClaim(True, "processing", 1, None)
        async with app.test_client() as client:
            with patch.object(worker_routes, "claim_update", AsyncMock(return_value=claim)), patch.object(
                worker_routes, "processar_update_assincrono", AsyncMock(side_effect=RuntimeError("work"))
            ), patch.object(worker_routes, "mark_failed", AsyncMock(side_effect=RuntimeError("db"))):
                response = await client.post(
                    "/internal/tasks/telegram-update",
                    json={"update_id": 49, "message": {}},
                    headers={"X-CloudTasks-TaskName": "task-49", "X-CloudTasks-QueueName": "telegram-updates"},
                )
        assert response.status_code == 503


class TestTelegramDelivery:
    def test_split_prefers_newline_boundary(self):
        chunks = telegram_service._split_message("a" * 4090 + "\n" + "b" * 20)
        assert chunks == ["a" * 4090, "b" * 20]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code,expected_error", [(500, telegram_service.TelegramRetryableError), (400, telegram_service.TelegramPermanentError)])
    async def test_invalid_json_response_is_classified(self, telegram_client, status_code, expected_error):
        telegram_client.post.return_value = httpx.Response(
            status_code,
            content=b"not-json",
            request=httpx.Request("POST", "https://api.telegram.org"),
        )
        with pytest.raises(expected_error):
            await telegram_service.enviar_mensagem_telegram(1, "teste")

    @pytest.mark.asyncio
    async def test_message_not_modified_is_idempotent_success(self, telegram_client):
        telegram_client.post.return_value = httpx.Response(
            400,
            json={"ok": False, "error_code": 400, "description": "Bad Request: message is not modified"},
            request=httpx.Request("POST", "https://api.telegram.org"),
        )
        assert await telegram_service.editar_mensagem_telegram(1, 2, "igual") == {}

    @pytest.mark.asyncio
    async def test_ok_false_raises_even_with_http_200(self, telegram_client):
        telegram_client.post.return_value = httpx.Response(
            200,
            json={"ok": False, "error_code": 429, "description": "Too Many Requests"},
            request=httpx.Request("POST", "https://api.telegram.org"),
        )

        with pytest.raises(telegram_service.TelegramRetryableError):
            await telegram_service.enviar_mensagem_telegram(1, "teste")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [500, 503])
    async def test_server_errors_are_retryable(self, telegram_client, status_code):
        telegram_client.post.return_value = httpx.Response(
            status_code,
            json={"ok": False, "error_code": status_code, "description": "provider unavailable"},
            request=httpx.Request("POST", "https://api.telegram.org"),
        )

        with pytest.raises(telegram_service.TelegramRetryableError):
            await telegram_service.enviar_mensagem_telegram(1, "teste")

    @pytest.mark.asyncio
    async def test_non_format_400_is_permanent(self, telegram_client):
        telegram_client.post.return_value = httpx.Response(
            400,
            json={"ok": False, "error_code": 400, "description": "chat not found"},
            request=httpx.Request("POST", "https://api.telegram.org"),
        )

        with pytest.raises(telegram_service.TelegramPermanentError):
            await telegram_service.enviar_mensagem_telegram(1, "teste")

    @pytest.mark.asyncio
    async def test_timeout_is_retryable(self, telegram_client):
        telegram_client.post.side_effect = httpx.ReadTimeout("timed out")

        with pytest.raises(telegram_service.TelegramRetryableError):
            await telegram_service.enviar_mensagem_telegram(1, "teste")

    @pytest.mark.asyncio
    async def test_invalid_markdown_retries_as_plain_text(self, telegram_client):
        telegram_client.post.side_effect = [
            httpx.Response(
                400,
                json={"ok": False, "error_code": 400, "description": "can't parse entities"},
                request=httpx.Request("POST", "https://api.telegram.org"),
            ),
            httpx.Response(
                200,
                json={"ok": True, "result": {"message_id": 7}},
                request=httpx.Request("POST", "https://api.telegram.org"),
            ),
        ]

        result = await telegram_service.enviar_mensagem_telegram(1, "dinâmico_[quebrado")

        assert result["message_id"] == 7
        assert telegram_client.post.await_count == 2
        assert "parse_mode" not in telegram_client.post.await_args_list[1].kwargs["json"]

    @pytest.mark.asyncio
    async def test_long_messages_are_split_under_telegram_limit(self, telegram_client):
        telegram_client.post.return_value = httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 8}},
            request=httpx.Request("POST", "https://api.telegram.org"),
        )

        await telegram_service.enviar_mensagem_telegram(1, "a" * 8200)

        assert telegram_client.post.await_count == 3
        assert all(len(call.kwargs["json"]["text"]) <= 4096 for call in telegram_client.post.await_args_list)

    @pytest.mark.asyncio
    async def test_long_edit_sends_remaining_chunks_and_keyboard_on_last(self, telegram_client):
        telegram_client.post.return_value = httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 9}},
            request=httpx.Request("POST", "https://api.telegram.org"),
        )
        markup = {"inline_keyboard": [[{"text": "ok", "callback_data": "ok"}]]}

        await telegram_service.editar_mensagem_telegram(1, 2, "z" * 5000, markup)

        assert telegram_client.post.await_count == 2
        assert "reply_markup" not in telegram_client.post.await_args_list[0].kwargs["json"]
        assert telegram_client.post.await_args_list[1].kwargs["json"]["reply_markup"] == markup

    @pytest.mark.asyncio
    async def test_callback_answer_is_best_effort(self, telegram_client):
        telegram_client.post.side_effect = httpx.ReadTimeout("late callback")
        assert await telegram_service.responder_callback_telegram("cb") == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code,expected_error", [(503, telegram_service.TelegramRetryableError), (404, telegram_service.TelegramPermanentError)])
    async def test_file_download_status_is_classified(self, telegram_client, status_code, expected_error):
        telegram_client.get.side_effect = [
            httpx.Response(
                200,
                json={"ok": True, "result": {"file_path": "files/test"}},
                request=httpx.Request("GET", "https://api.telegram.org"),
            ),
            httpx.Response(status_code, request=httpx.Request("GET", "https://api.telegram.org/file")),
        ]
        with pytest.raises(expected_error):
            await telegram_service.baixar_arquivo_telegram("file")

    @pytest.mark.asyncio
    async def test_file_download_timeout_is_retryable(self, telegram_client):
        telegram_client.get.side_effect = [
            httpx.Response(
                200,
                json={"ok": True, "result": {"file_path": "files/test"}},
                request=httpx.Request("GET", "https://api.telegram.org"),
            ),
            httpx.ReadTimeout("download timeout"),
            httpx.ReadTimeout("download timeout"),
        ]
        with pytest.raises(telegram_service.TelegramRetryableError):
            await telegram_service.baixar_arquivo_telegram("file")
