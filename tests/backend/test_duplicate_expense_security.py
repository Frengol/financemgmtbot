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

import security


class TestDuplicatePendingStorage:
    def test_preview_is_generic_and_has_no_financial_values(self):
        payload = {"transaction": {"descricao": "Segredo", "valor_total": 9.99}}
        preview = security.build_pending_preview("duplicate_expense", payload)
        assert preview == {"summary": "Confirmação pendente"}

    def test_store_persists_encrypted_payload_with_stable_id_and_ttl_from_creation(self):
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "x"}])
        supabase = MagicMock()
        supabase.table.return_value = table
        payload = {"transaction": {"descricao": "Segredo"}, "matched_record": {"id": 1}}
        with patch.object(security, "supabase", supabase):
            first = security.store_pending_item(
                payload, kind="duplicate_expense", origin_chat_id=1, origin_user_id=2, source_update_id=77
            )
            second = security.store_pending_item(
                payload, kind="duplicate_expense", origin_chat_id=1, origin_user_id=2, source_update_id=77
            )
        row = table.upsert.call_args.args[0]
        assert first["id"] == second["id"] == row["id"]
        assert row["kind"] == "duplicate_expense"
        assert "Segredo" not in str(row)
        assert row["preview_json"] == {"summary": "Confirmação pendente"}
        assert table.upsert.call_args.kwargs == {"on_conflict": "source_update_id", "ignore_duplicates": True}
        assert "duplicate_decision" not in row

    def test_conflict_winner_exposes_its_decision(self):
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[])
        winner = {
            "id": "tu_1",
            "kind": "duplicate_expense",
            "preview_json": {"summary": "Confirmação pendente"},
            "origin_chat_id": "1",
            "source_update_id": 77,
            "duplicate_decision": "skip",
            "payload_ciphertext": None,
            "payload": {},
        }
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[winner])
        supabase = MagicMock()
        supabase.table.return_value = table
        with patch.object(security, "supabase", supabase):
            stored = security.store_pending_item(
                {"transaction": {}}, kind="duplicate_expense", origin_chat_id=1, origin_user_id=2, source_update_id=77
            )
        assert stored["duplicate_decision"] == "skip"
        assert stored["origin_user_id"] is None or isinstance(stored["origin_user_id"], str)

    def test_empty_response_without_a_persisted_row_is_not_durable(self):
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[])
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        supabase = MagicMock()
        supabase.table.return_value = table
        with patch.object(security, "supabase", supabase):
            with pytest.raises(RuntimeError):
                security.store_pending_item(
                    {"transaction": {}}, kind="duplicate_expense", origin_chat_id=1, origin_user_id=2, source_update_id=78
                )

    def test_empty_response_but_row_is_readable_back_counts_as_persisted(self):
        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=None)
        row = {"id": "tu_x", "kind": "duplicate_expense", "preview_json": {}, "origin_chat_id": "1",
               "origin_user_id": "2", "source_update_id": 79, "duplicate_decision": None,
               "payload_ciphertext": None, "payload": {}}
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[row])
        supabase = MagicMock()
        supabase.table.return_value = table
        with patch.object(security, "supabase", supabase):
            stored = security.store_pending_item(
                {"transaction": {}}, kind="duplicate_expense", origin_chat_id=1, origin_user_id=2, source_update_id=79
            )
        assert stored["id"] == "tu_x"

    def test_select_fields_include_the_decision_marker(self):
        assert "duplicate_decision" in security.PENDING_SELECT_FIELDS


class TestExactOrigin:
    def test_requires_exact_chat_and_user(self):
        item = {"origin_chat_id": "10", "origin_user_id": "20"}
        assert security.matches_pending_origin_exact(item, 10, 20)
        assert not security.matches_pending_origin_exact(item, 11, 20)
        assert not security.matches_pending_origin_exact(item, 10, 21)
        assert not security.matches_pending_origin_exact(item, 10, None)
        assert not security.matches_pending_origin_exact(item, None, 20)

    @pytest.mark.parametrize("item", [None, {}, {"origin_chat_id": "10"}, {"origin_user_id": "20"}, {"origin_chat_id": "", "origin_user_id": "20"}])
    def test_missing_binding_fails_closed(self, item):
        assert not security.matches_pending_origin_exact(item, 10, 20)


class TestDecisionRpc:
    def _supabase(self, data):
        supabase = MagicMock()
        supabase.rpc.return_value.execute.return_value = MagicMock(data=data)
        return supabase

    @pytest.mark.parametrize("data,expected", [("save", "save"), ("skip", "skip"), ("expired", "expired"), (["skip"], "skip")])
    def test_returns_canonical_decision(self, data, expected):
        supabase = self._supabase(data)
        with patch.object(security, "supabase", supabase):
            assert security.decide_duplicate_expense("tu_1", 10, 20, "save") == expected
        supabase.rpc.assert_called_once_with(
            "decide_duplicate_expense",
            {"p_id": "tu_1", "p_chat_id": "10", "p_user_id": "20", "p_decision": "save"},
        )

    @pytest.mark.parametrize("data", [None, [], "", "other", [None], 5])
    def test_unknown_or_missing_result_is_none(self, data):
        with patch.object(security, "supabase", self._supabase(data)):
            assert security.decide_duplicate_expense("tu_1", 10, 20, "skip") is None

    def test_invalid_decision_never_reaches_the_database(self):
        supabase = self._supabase("save")
        with patch.object(security, "supabase", supabase):
            with pytest.raises(ValueError):
                security.decide_duplicate_expense("tu_1", 10, 20, "expired")
        supabase.rpc.assert_not_called()

    def test_binding_is_mandatory(self):
        supabase = self._supabase("save")
        with patch.object(security, "supabase", supabase):
            assert security.decide_duplicate_expense("tu_1", None, 20, "save") is None
            assert security.decide_duplicate_expense("tu_1", 10, None, "save") is None
        supabase.rpc.assert_not_called()


class TestClearSnapshot:
    def test_clears_ciphertext_only_for_decided_duplicate_rows(self):
        table = MagicMock()
        chain = table.update.return_value.eq.return_value.eq.return_value.not_.is_.return_value
        chain.execute.return_value = MagicMock(data=[{"id": "tu_1"}])
        supabase = MagicMock()
        supabase.table.return_value = table
        with patch.object(security, "supabase", supabase):
            security.clear_duplicate_snapshot("tu_1")
        update = table.update.call_args.args[0]
        assert update["payload_ciphertext"] is None
        assert update["payload"] == {}
        assert update["preview_json"] == {"summary": "Confirmação concluída"}
        table.update.return_value.eq.assert_called_once_with("id", "tu_1")
        table.update.return_value.eq.return_value.eq.assert_called_once_with("kind", "duplicate_expense")
        table.update.return_value.eq.return_value.eq.return_value.not_.is_.assert_called_once_with("duplicate_decision", "null")

    def test_requires_confirmation_of_persistence(self):
        table = MagicMock()
        chain = table.update.return_value.eq.return_value.eq.return_value.not_.is_.return_value
        chain.execute.return_value = MagicMock(data=[])
        supabase = MagicMock()
        supabase.table.return_value = table
        with patch.object(security, "supabase", supabase):
            with pytest.raises(RuntimeError, match="snapshot"):
                security.clear_duplicate_snapshot("tu_1")


class TestHydrateClearedMarker:
    def test_cleared_marker_has_no_payload(self):
        row = {
            "id": "tu_1",
            "kind": "duplicate_expense",
            "payload_ciphertext": None,
            "payload": {},
            "preview_json": {"summary": "Confirmação concluída"},
            "duplicate_decision": "skip",
        }
        hydrated = security._hydrate_pending_item(row, "tu_1")
        assert hydrated["kind"] == "duplicate_expense"
        assert hydrated["duplicate_decision"] == "skip"
        assert hydrated["payload"] == {}


class TestDuplicateDeadline:
    def test_duplicate_rows_store_timezone_aware_utc_instants_with_24h_ttl(self):
        from datetime import datetime, timedelta

        table = MagicMock()
        table.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "x"}])
        supabase = MagicMock()
        supabase.table.return_value = table
        with patch.object(security, "supabase", supabase):
            security.store_pending_item({"a": 1}, kind="duplicate_expense", origin_chat_id=1, origin_user_id=2, source_update_id=5)
        row = table.upsert.call_args.args[0]
        created = datetime.fromisoformat(row["created_at"])
        expires = datetime.fromisoformat(row["expires_at"])
        assert created.utcoffset() == timedelta(0)
        assert expires - created == timedelta(hours=24)

    def test_expiry_check_uses_real_instants_and_fails_closed(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        assert not security.duplicate_item_expired({"expires_at": (now + timedelta(minutes=1)).isoformat()})
        assert security.duplicate_item_expired({"expires_at": (now - timedelta(minutes=1)).isoformat()})
        assert security.duplicate_item_expired({"expires_at": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")})
        assert security.duplicate_item_expired({"expires_at": None})
        assert security.duplicate_item_expired({"expires_at": "garbage"})
        assert security.duplicate_item_expired(None)
        naive_future = (now + timedelta(hours=1)).replace(tzinfo=None).isoformat()
        assert not security.duplicate_item_expired({"expires_at": naive_future})
