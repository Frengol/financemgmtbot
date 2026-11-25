import os
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

CORRECTED = {
    "metodo_pagamento": "Pix",
    "conta": "Nubank",
    "desconto_global": 0.0,
    "itens": [
        {"nome": "Arroz", "valor_bruto": 30.0, "desconto_item": 0.0, "categoria": "Mercado"},
        {"nome": "Cerveja", "valor_bruto": 12.0, "desconto_item": 0.0, "categoria": "Bebidas Alcoólicas"},
    ],
}


def _item(**overrides):
    base = {
        "id": "tu_1",
        "kind": "receipt_batch",
        "payload": CORRECTED,
        "source_update_id": 701,
        "payload_revision": 1,
        "approval_claimed_revision": 1,
        "expires_at": "2026-11-24T10:00:00",
    }
    base.update(overrides)
    return base


class Mocks:
    def __init__(self, item, claim=("claimed", 1), discard="discarded"):
        self.load = MagicMock(return_value=item)
        self.claim = MagicMock(return_value=claim)
        self.discard = MagicMock(return_value=discard)
        self.save = MagicMock(return_value=(2, 42.0))
        self.delete = MagicMock()
        self.audit = MagicMock()

    def patches(self):
        return [
            patch.object(admin_approvals, "autenticar_admin_request", return_value=({"id": "admin"}, None)),
            patch.object(admin_approvals, "load_pending_item", self.load),
            patch.object(admin_approvals, "claim_receipt_approval_admin", self.claim),
            patch.object(admin_approvals, "discard_receipt_pending_admin", self.discard),
            patch.object(admin_approvals, "gravar_lote_no_banco", self.save),
            patch.object(admin_approvals, "delete_pending_item", self.delete),
            patch.object(admin_approvals, "registrar_auditoria_admin", self.audit),
        ]


@pytest.fixture
def run():
    active = []

    async def _run(mocks, action):
        handler = admin_approvals.aprovar_cache_admin if action == "approve" else admin_approvals.rejeitar_cache_admin
        async with main.app.test_request_context(f"/api/admin/cache-aprovacao/tu_1/{action}", method="POST"):
            patches = mocks.patches()
            for p in patches:
                p.start()
                active.append(p)
            return handler("tu_1")

    yield _run
    for p in reversed(active):
        p.stop()


class TestAdminApprove:
    @pytest.mark.asyncio
    async def test_approves_the_corrected_draft_after_claiming(self, run):
        mocks = Mocks(_item())
        response = await run(mocks, "approve")
        assert response.status_code == 200
        mocks.claim.assert_called_once_with("tu_1")
        assert mocks.save.call_args.args[0] == CORRECTED
        assert mocks.save.call_args.kwargs["source_update_id"] == 701
        mocks.delete.assert_called_once_with("tu_1")
        mocks.audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_approval_already_started_elsewhere_completes_idempotently(self, run):
        mocks = Mocks(_item(), claim=("already_claimed", 1))
        response = await run(mocks, "approve")
        assert response.status_code == 200
        mocks.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_expired_is_410_and_discarded_without_saving(self, run):
        mocks = Mocks(_item(approval_claimed_revision=None), claim=("expired", None))
        response = await run(mocks, "approve")
        assert response.status_code == 410
        mocks.discard.assert_called_once_with("tu_1")
        mocks.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_unavailable_claim_is_404(self, run):
        mocks = Mocks(_item(), claim=("unavailable", None))
        response = await run(mocks, "approve")
        assert response.status_code == 404
        mocks.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_item_removed_after_claim_is_404(self, run):
        mocks = Mocks(_item())
        mocks.load.side_effect = [_item(), None]
        response = await run(mocks, "approve")
        assert response.status_code == 404
        mocks.save.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "reloaded",
        [_item(payload_revision=2, approval_claimed_revision=2), _item(approval_claimed_revision=None), _item(payload="bad")],
        ids=["other-revision", "not-claimed", "bad-payload"],
    )
    async def test_inconsistent_claim_fails_closed(self, run, reloaded):
        mocks = Mocks(_item())
        mocks.load.side_effect = [_item(), reloaded]
        response = await run(mocks, "approve")
        assert response.status_code == 409
        mocks.save.assert_not_called()
        mocks.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_receipt_without_source_identity_is_refused(self, run):
        mocks = Mocks(_item(source_update_id=None))
        response = await run(mocks, "approve")
        assert response.status_code == 409
        mocks.claim.assert_not_called()
        mocks.save.assert_not_called()


class TestAdminReject:
    @pytest.mark.asyncio
    async def test_reject_discards_unclaimed_receipt(self, run):
        mocks = Mocks(_item(approval_claimed_revision=None))
        response = await run(mocks, "reject")
        assert response.status_code == 200
        mocks.discard.assert_called_once_with("tu_1")
        mocks.delete.assert_not_called()
        mocks.audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_during_approval_is_409(self, run):
        mocks = Mocks(_item(), discard="claimed")
        response = await run(mocks, "reject")
        assert response.status_code == 409
        mocks.audit.assert_not_called()

    @pytest.mark.asyncio
    async def test_reject_of_vanished_receipt_is_404(self, run):
        mocks = Mocks(_item(), discard="unavailable")
        response = await run(mocks, "reject")
        assert response.status_code == 404
        mocks.audit.assert_not_called()
