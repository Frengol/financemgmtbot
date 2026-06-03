from unittest.mock import MagicMock, patch

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
import pytest

import security


class TestSecurityCoverage:
    def test_key_hash_and_timestamp_helpers_cover_configured_invalid_and_optional_values(self):
        valid_key = Fernet.generate_key().decode("utf-8")
        with patch.dict("os.environ", {"DATA_ENCRYPTION_KEY": valid_key}, clear=False):
            assert security._fernet_key() == valid_key.encode("utf-8")

        with patch.dict("os.environ", {"DATA_ENCRYPTION_KEY": "invalid-key"}, clear=False), \
             patch.object(security.logger, "warning") as warning_mock:
            derived = security._fernet_key()
        assert derived != b"invalid-key"
        warning_mock.assert_called_once()

        assert security.hash_optional(None) is None
        assert security.hash_optional("") is None
        assert security.hash_optional("value") == security.hash_text("value")
        assert security._parse_timestamp(None) is None
        parsed_zulu = security._parse_timestamp("2026-04-05T12:00:00Z")
        assert parsed_zulu is not None
        assert parsed_zulu.tzinfo is None
        aware = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc).isoformat()
        parsed_aware = security._parse_timestamp(aware)
        assert parsed_aware is not None
        assert parsed_aware.tzinfo is None

    def test_sanitize_plain_text_escapes_null_bytes_and_truncates(self):
        value = "  <script>alert(1)</script>\x00resto  "
        sanitized = security.sanitize_plain_text(value, 20, "fallback")
        assert sanitized == "&lt;script&gt;alert("

    def test_build_pending_preview_for_delete_confirmation_counts_records(self):
        preview = security.build_pending_preview("delete_confirmation", {"ids": ["1", "2", "3"]})
        assert preview == {"summary": "Exclusão pendente", "records_count": 3}

    def test_load_pending_item_decrypts_ciphertext_and_builds_preview(self):
        payload = {
            "metodo_pagamento": "Pix",
            "conta": "Nubank",
            "desconto_global": 1.5,
            "itens": [
                {"nome": "Cafe", "valor_bruto": 12.0, "desconto_item": 0.0, "categoria": "Mercado"},
                {"nome": "Pao", "valor_bruto": 8.0, "desconto_item": 1.0, "categoria": "Mercado"},
            ],
        }
        encrypted_payload = security.encrypt_pending_payload(payload)
        mock_cache = MagicMock()
        mock_cache.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "CIPHER-1",
                "kind": "receipt_batch",
                "payload_ciphertext": encrypted_payload,
                "payload_key_version": security.PENDING_KEY_VERSION,
                "preview_json": None,
                "created_at": "2026-04-03T10:00:00",
                "expires_at": "2099-04-03T12:00:00",
                "origin_chat_id": "123",
                "origin_user_id": "456",
                "payload": {},
            }]
        )

        with patch.object(security.supabase, "table", return_value=mock_cache):
            item = security.load_pending_item("CIPHER-1")

        assert item["payload"]["conta"] == "Nubank"
        assert item["preview_json"]["summary"] == "Cupom pendente"
        assert item["preview_json"]["total_estimado"] == 17.5

    def test_load_pending_item_handles_invalid_ciphertext_and_matches_origin(self):
        mock_cache = MagicMock()
        mock_cache.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "BROKEN-1",
                "kind": "receipt_batch",
                "payload_ciphertext": "invalid-token",
                "payload_key_version": security.PENDING_KEY_VERSION,
                "preview_json": None,
                "created_at": "2026-04-03T10:00:00",
                "expires_at": "2099-04-03T12:00:00",
                "origin_chat_id": "chat-1",
                "origin_user_id": "user-1",
                "payload": {},
            }]
        )

        with patch.object(security.supabase, "table", return_value=mock_cache):
            item = security.load_pending_item("BROKEN-1")

        assert item["payload"] is None
        assert security.matches_pending_origin(item, "chat-1", "user-1") is True
        assert security.matches_pending_origin(item, "chat-2", "user-1") is False
        assert security.matches_pending_origin(item, "chat-1", "user-2") is False

    def test_pending_item_expired_and_rate_limit(self):
        expired_item = {"expires_at": "2000-01-01T00:00:00"}
        valid_item = {"expires_at": "2099-01-01T00:00:00"}

        assert security.pending_item_expired(None) is True
        assert security.pending_item_expired(expired_item) is True
        assert security.pending_item_expired(valid_item) is False

        with patch.dict(security._RATE_LIMIT_BUCKETS, {}, clear=True):
            assert security.allow_request("auth", "127.0.0.1", limit=2, window_seconds=60) is True
            assert security.allow_request("auth", "127.0.0.1", limit=2, window_seconds=60) is True
            assert security.allow_request("auth", "127.0.0.1", limit=2, window_seconds=60) is False

    def test_pending_helpers_cover_plain_payload_fallback_and_origin_variants(self):
        cache_table = MagicMock()
        cache_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "cache-plain-1",
                "kind": None,
                "payload_ciphertext": None,
                "payload_key_version": None,
                "preview_json": None,
                "created_at": "2026-04-03T10:00:00",
                "expires_at": None,
                "origin_chat_id": "10",
                "origin_user_id": "20",
                "payload": {"ids": ["tx-1"]},
            }]
        )

        with patch.object(security.supabase, "table", return_value=cache_table):
            item = security.load_pending_item("cache-plain-1")

        assert item["kind"] == "delete_confirmation"
        assert item["payload"] == {"ids": ["tx-1"]}
        assert item["preview_json"]["records_count"] == 1
        assert security.pending_item_expired({"expires_at": None}) is False
        assert security.matches_pending_origin(None, "10", "20") is False
        assert security.matches_pending_origin(item, "11", "20") is False
        assert security.matches_pending_origin(item, "10", "21") is False
        assert security.detect_pending_kind({"itens": []}) == "receipt_batch"

    def test_build_pending_preview_handles_invalid_items_and_global_discount(self):
        preview = security.build_pending_preview("receipt_batch", {
            "metodo_pagamento": None,
            "conta": None,
            "desconto_global": "bad",
            "itens": [
                {"nome": None, "valor_bruto": "5.5", "desconto_item": "1.5"},
                {"nome": "Inválido", "valor_bruto": "oops", "desconto_item": 0},
                "invalid",
            ],
        })

        assert preview["itens"][0] == "Item"
        assert preview["total_estimado"] == 4.0
