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
    "TELEGRAM_TASKS_PROJECT": "financemgmtbot",
    "TELEGRAM_TASKS_LOCATION": "southamerica-east1",
    "TELEGRAM_TASKS_QUEUE": "telegram-updates",
    "TELEGRAM_WORKER_URL": "https://worker.example.run.app",
    "TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT": "telegram-task-invoker@financemgmtbot.iam.gserviceaccount.com",
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)

for dependency_patch in [
    patch("supabase.create_client", return_value=MagicMock()),
    patch("groq.AsyncGroq", return_value=MagicMock()),
    patch("openai.AsyncOpenAI", return_value=MagicMock()),
    patch("google.genai.Client", return_value=MagicMock()),
]:
    dependency_patch.start()

import main
from admin_runtime import approvals as admin_approvals


def _rows():
    return [
        {"id": "r1", "kind": "receipt_batch", "preview_json": {"summary": "Cupom pendente"}, "created_at": "t", "expires_at": "e", "payload": None},
        {"id": "d1", "kind": "duplicate_expense", "preview_json": {"summary": "Confirmação pendente"}, "created_at": "t", "expires_at": "e", "payload": None},
        {"id": "u1", "kind": "mystery", "preview_json": {}, "created_at": "t", "expires_at": "e", "payload": None},
        {"id": "x1", "kind": None, "preview_json": {}, "created_at": "t", "expires_at": "e", "payload": {"ids": [1]}},
    ]


@pytest.mark.asyncio
async def test_list_hides_duplicate_and_unknown_kinds():
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.order.return_value.execute.return_value = MagicMock(data=_rows())
    async with main.app.test_request_context("/api/admin/cache-aprovacao"):
        with patch.object(admin_approvals, "autenticar_admin_request", return_value=({"id": "a"}, None)), patch.object(
            admin_approvals, "supabase", supabase
        ):
            response = admin_approvals.listar_cache_admin()
    body = await response.get_json()
    assert [item["id"] for item in body["items"]] == ["r1", "x1"]
    assert "duplicate" not in str(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["duplicate_expense", "mystery"])
@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize("expired", [False, True])
async def test_approve_and_reject_are_409_without_effects(kind, action, expired):
    item = {"id": "d1", "kind": kind, "payload": {"ids": [1]}, "source_update_id": 5}
    delete = MagicMock()
    save = MagicMock()
    audit = MagicMock()
    handler = admin_approvals.aprovar_cache_admin if action == "approve" else admin_approvals.rejeitar_cache_admin
    async with main.app.test_request_context(f"/api/admin/cache-aprovacao/d1/{action}", method="POST"):
        with patch.object(admin_approvals, "autenticar_admin_request", return_value=({"id": "a"}, None)), patch.object(
            admin_approvals, "load_pending_item", return_value=item
        ), patch.object(admin_approvals, "pending_item_expired", return_value=expired), patch.object(
            admin_approvals, "delete_pending_item", delete
        ), patch.object(admin_approvals, "gravar_lote_no_banco", save), patch.object(
            admin_approvals, "registrar_auditoria_admin", audit
        ), patch.object(admin_approvals, "supabase", MagicMock()) as supabase:
            response = handler("d1")
    assert response.status_code == 409
    delete.assert_not_called()
    save.assert_not_called()
    audit.assert_not_called()
    supabase.table.assert_not_called()


@pytest.mark.asyncio
async def test_missing_item_keeps_404_on_reject():
    async with main.app.test_request_context("/api/admin/cache-aprovacao/zz/reject", method="POST"):
        with patch.object(admin_approvals, "autenticar_admin_request", return_value=({"id": "a"}, None)), patch.object(
            admin_approvals, "load_pending_item", return_value=None
        ):
            response = admin_approvals.rejeitar_cache_admin("zz")
    assert response.status_code == 404
