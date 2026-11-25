import os
from datetime import datetime
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

import security

NOW = datetime(2026, 11, 23, 10, 0, 0)
PAYLOAD = {
    "metodo_pagamento": "Pix",
    "conta": "Nubank",
    "desconto_global": 0.0,
    "itens": [{"nome": "Cerveja Secreta", "valor_bruto": 9.0, "desconto_item": 0.0, "categoria": "Bebidas Alcoólicas"}],
}


def _rpc(data):
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=data)
    return client


@pytest.fixture(autouse=True)
def fixed_clock():
    with patch.object(security, "get_brasilia_time", lambda: NOW):
        yield


class TestSelectAndHelpers:
    def test_select_reads_revision_and_claim(self):
        assert "payload_revision" in security.PENDING_SELECT_FIELDS
        assert "approval_claimed_revision" in security.PENDING_SELECT_FIELDS

    @pytest.mark.parametrize(
        "value,expected",
        [(0, 0), (7, 7), (None, None), (-1, None), (True, None), ("1", None), (1.0, None)],
    )
    def test_pending_revision_is_strict(self, value, expected):
        assert security.pending_revision({"payload_revision": value}) == expected

    def test_pending_revision_of_missing_item_is_none(self):
        assert security.pending_revision(None) is None
        assert security.pending_revision({}) is None

    @pytest.mark.parametrize(
        "expires_at,expired",
        [
            ("2026-11-23T10:00:01", False),
            ("2026-11-23T10:00:00", True),
            ("2026-11-23T09:00:00", True),
            (None, True),
            ("", True),
            ("not a date", True),
            (123, True),
        ],
    )
    def test_strict_expiry_counts_missing_or_unreadable_as_expired(self, expires_at, expired):
        assert security.receipt_pending_expired_strict({"expires_at": expires_at}) is expired
        assert security.receipt_pending_expired_strict(None) is True

    def test_legacy_expiry_keeps_lenient_missing_deadline(self):
        assert security.pending_item_expired({"expires_at": None}) is False


class TestEditRpc:
    def test_sends_encrypted_payload_preview_and_application_clock(self):
        client = _rpc(3)
        with patch.object(security, "supabase", client):
            assert security.edit_receipt_pending("tu_1", 1, 2, 2, PAYLOAD) == 3
        name, params = client.rpc.call_args.args
        assert name == "edit_receipt_pending"
        assert params["p_id"] == "tu_1" and params["p_chat_id"] == "1" and params["p_user_id"] == "2"
        assert params["p_expected_revision"] == 2
        assert params["p_now"] == NOW.isoformat()
        assert "Cerveja Secreta" not in params["p_ciphertext"]
        assert security.decrypt_pending_payload(params["p_ciphertext"]) == PAYLOAD
        assert params["p_preview"] == security.build_pending_preview("receipt_batch", PAYLOAD)

    @pytest.mark.parametrize("data,expected", [(None, None), ([], None), ([4], 4), (True, None), ("4", None), (0, None)])
    def test_result_is_strictly_parsed(self, data, expected):
        with patch.object(security, "supabase", _rpc(data)):
            assert security.edit_receipt_pending("tu_1", 1, 2, 0, PAYLOAD) == expected

    @pytest.mark.parametrize("chat,user,rev", [(None, 2, 0), (1, None, 0), (1, 2, None), (1, 2, -1), (1, 2, True)])
    def test_missing_binding_or_revision_never_calls_the_database(self, chat, user, rev):
        client = _rpc(1)
        with patch.object(security, "supabase", client):
            assert security.edit_receipt_pending("tu_1", chat, user, rev, PAYLOAD) is None
        client.rpc.assert_not_called()


class TestClaimRpc:
    @pytest.mark.parametrize(
        "data,expected",
        [
            ([{"claim_status": "claimed", "claim_revision": 2}], ("claimed", 2)),
            ([{"claim_status": "already_claimed", "claim_revision": 1}], ("already_claimed", 1)),
            ([{"claim_status": "stale", "claim_revision": 5}], ("stale", 5)),
            ([{"claim_status": "expired", "claim_revision": None}], ("expired", None)),
            ([{"claim_status": "unavailable", "claim_revision": None}], ("unavailable", None)),
            ({"claim_status": "claimed", "claim_revision": 0}, ("claimed", 0)),
            ([{"claim_status": "claimed", "claim_revision": None}], ("unavailable", None)),
            ([{"claim_status": "claimed", "claim_revision": True}], ("unavailable", None)),
            ([{"claim_status": "bogus", "claim_revision": 1}], ("unavailable", None)),
            ([], ("unavailable", None)),
            (None, ("unavailable", None)),
            ("claimed", ("unavailable", None)),
        ],
        ids=repr,
    )
    def test_statuses_are_strictly_parsed(self, data, expected):
        client = _rpc(data)
        with patch.object(security, "supabase", client):
            assert security.claim_receipt_approval("tu_1", 1, 2, 2) == expected
        name, params = client.rpc.call_args.args
        assert name == "claim_receipt_approval"
        assert params == {"p_id": "tu_1", "p_chat_id": "1", "p_user_id": "2", "p_revision": 2, "p_now": NOW.isoformat()}

    def test_missing_binding_never_claims(self):
        client = _rpc([{"claim_status": "claimed", "claim_revision": 0}])
        with patch.object(security, "supabase", client):
            assert security.claim_receipt_approval("tu_1", 1, None, 0) == ("unavailable", None)
        client.rpc.assert_not_called()

    def test_admin_claim_has_no_binding(self):
        client = _rpc([{"claim_status": "claimed", "claim_revision": 4}])
        with patch.object(security, "supabase", client):
            assert security.claim_receipt_approval_admin("tu_1") == ("claimed", 4)
        assert client.rpc.call_args.args == ("claim_receipt_approval_admin", {"p_id": "tu_1", "p_now": NOW.isoformat()})


class TestDiscardRpc:
    @pytest.mark.parametrize(
        "data,expected",
        [("discarded", "discarded"), ("claimed", "claimed"), (["discarded"], "discarded"), ("x", "unavailable"), (None, "unavailable")],
    )
    def test_statuses(self, data, expected):
        client = _rpc(data)
        with patch.object(security, "supabase", client):
            assert security.discard_receipt_pending("tu_1", 1, 2) == expected
        assert client.rpc.call_args.args == ("discard_receipt_pending", {"p_id": "tu_1", "p_chat_id": "1", "p_user_id": "2"})

    def test_missing_binding_never_discards(self):
        client = _rpc("discarded")
        with patch.object(security, "supabase", client):
            assert security.discard_receipt_pending("tu_1", None, 2) == "unavailable"
        client.rpc.assert_not_called()

    def test_admin_variant(self):
        client = _rpc("claimed")
        with patch.object(security, "supabase", client):
            assert security.discard_receipt_pending_admin("tu_1") == "claimed"
        assert client.rpc.call_args.args == ("discard_receipt_pending_admin", {"p_id": "tu_1"})
