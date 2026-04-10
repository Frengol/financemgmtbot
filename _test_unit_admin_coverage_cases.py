from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from postgrest.exceptions import APIError

import main
import admin_runtime as admin_api
from admin_runtime import audit as admin_audit
from admin_runtime import approvals as admin_approvals
from admin_runtime import auth as admin_auth
from admin_runtime import transactions as admin_transactions


class TestAdminApiHelperCoverage:
    def test_field_summary_and_user_lookup_helpers(self):
        assert admin_api._build_field_summary(None) == {
            "contains_sensitive_values": False,
            "fields": [],
            "field_count": 0,
        }
        assert admin_api._build_field_summary({"b": 2, "a": 1}) == {
            "contains_sensitive_values": False,
            "fields": ["a", "b"],
            "field_count": 2,
        }
        assert admin_api._extract_user_fields(None) == (None, None)
        assert admin_api._extract_user_fields({"id": "user-1", "email": "admin@example.com"}) == ("user-1", "admin@example.com")
        assert admin_api._extract_user_fields(SimpleNamespace(id="user-2", email="admin2@example.com")) == ("user-2", "admin2@example.com")
        assert admin_api._extract_user_fields(SimpleNamespace(user=SimpleNamespace(id="user-3", email="nested@example.com"))) == ("user-3", "nested@example.com")
        assert admin_api._normalize_lookup(" Diversão Ágil ") == "diversao agil"

    @pytest.mark.asyncio
    async def test_normalize_transaction_payload_covers_validation_errors(self):
        async with main.app.test_request_context("/api/admin/gastos", method="POST"):
            payload, error = admin_api._normalize_transaction_payload(None)
            assert payload is None
            assert error.status_code == 400

            _, extra_fields_error = admin_api._normalize_transaction_payload({"data": "2026-04-01", "valor": 1, "categoria": "Mercado", "descricao": "Compra", "extra": True})
            assert extra_fields_error.status_code == 400

            _, invalid_date_error = admin_api._normalize_transaction_payload({"data": "04/01/2026", "valor": 1, "categoria": "Mercado", "descricao": "Compra"})
            assert invalid_date_error.status_code == 400

            _, invalid_value_error = admin_api._normalize_transaction_payload({"data": "2026-04-01", "valor": "abc", "categoria": "Mercado", "descricao": "Compra"})
            assert invalid_value_error.status_code == 400

            _, negative_value_error = admin_api._normalize_transaction_payload({"data": "2026-04-01", "valor": -1, "categoria": "Mercado", "descricao": "Compra"})
            assert negative_value_error.status_code == 400

            _, missing_description_error = admin_api._normalize_transaction_payload({"data": "2026-04-01", "valor": 1, "categoria": "Mercado", "descricao": ""})
            assert missing_description_error.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_auth_helpers_cover_bearer_lookup_authorization_and_current_admin_branches(self):
        response = MagicMock()
        response.user = {"id": "user-1", "email": "admin@example.com"}
        admin_auth.supabase.auth.get_user = MagicMock(return_value=response)

        with patch.object(admin_auth, "_lookup_admin_user", return_value={"user_id": "user-1", "email": "admin@example.com"}), \
             patch.object(admin_auth, "ADMIN_USER_IDS", frozenset()), \
             patch.object(admin_auth, "ADMIN_EMAILS", frozenset({"admin@example.com"})):
            async with main.app.test_request_context("/api/admin/me", headers={"Authorization": "Bearer header.payload.signature"}):
                actor, error = admin_api.autenticar_admin_request()
        assert error is None
        assert actor == {"id": "user-1", "email": "admin@example.com"}

        malformed_logs = []
        with patch.object(admin_auth, "auth_test_mode_enabled", return_value=True), \
             patch.object(admin_auth, "resolve_test_access_token", return_value=None), \
             patch.object(admin_auth.logger, "warning", side_effect=lambda payload: malformed_logs.append(payload)):
            async with main.app.test_request_context("/api/admin/me", headers={"Authorization": "Bearer auth-test-invalid"}):
                actor, error = admin_api.autenticar_admin_request()
        assert actor is None
        assert error.status_code == 401
        assert (await error.get_json())["code"] == "AUTH_SESSION_INVALID"
        assert malformed_logs[-1]["event"] == "admin_bearer_auth_failed"

        async with main.app.test_request_context("/api/admin/me"):
            auth_error = admin_api._json_error("denied", 403, code="AUTH_ACCESS_DENIED")
            with patch.object(admin_auth, "autenticar_admin_request", return_value=(None, auth_error)):
                current = admin_api.obter_admin_atual()
        assert current.status_code == 403

        async with main.app.test_request_context("/api/admin/me"):
            with patch.object(admin_auth, "autenticar_admin_request", return_value=({"id": "user-1", "email": "admin@example.com"}, None)):
                current = admin_api.obter_admin_atual()
        assert current.status_code == 200
        assert (await current.get_json())["user"]["id"] == "user-1"

    @pytest.mark.asyncio
    async def test_autenticar_admin_request_covers_local_dev_bypass_and_access_denied(self):
        async with main.app.test_request_context("/api/admin/gastos", headers={"Origin": "http://localhost:5173"}):
            with patch.object(admin_auth, "ALLOW_LOCAL_DEV_AUTH", True), patch.object(admin_auth, "FRONTEND_ALLOWED_ORIGINS", frozenset({"http://localhost:5173"})):
                actor, error = admin_api.autenticar_admin_request()
                assert error is None
                assert actor["id"] == "local-dev"

        response = MagicMock()
        response.user = {"id": "wrong", "email": "wrong@example.com"}
        admin_auth.supabase.auth.get_user = MagicMock(return_value=response)
        async with main.app.test_request_context("/api/admin/gastos", headers={"Authorization": "Bearer header.payload.signature"}):
            with patch.object(admin_auth, "_lookup_admin_user", return_value={"user_id": "wrong", "email": "wrong@example.com"}), \
                 patch.object(admin_auth, "ADMIN_USER_IDS", frozenset({"expected"})), \
                 patch.object(admin_auth, "ADMIN_EMAILS", frozenset({"admin@example.com"})):
                actor, error = admin_api.autenticar_admin_request()
                assert actor is None
                assert error.status_code == 403

    @pytest.mark.asyncio
    async def test_registrar_auditoria_admin_and_listar_cache_cover_failure_paths(self):
        audit_table = MagicMock()
        audit_table.insert.return_value.execute.side_effect = APIError({"message": "audit fail", "code": "500", "details": "", "hint": ""})

        with patch.object(admin_audit, "supabase", MagicMock(table=MagicMock(return_value=audit_table))):
            admin_api.registrar_auditoria_admin({"id": "u1", "email": "admin@example.com"}, "create", "gastos", "tx-1", {})

        audit_table.insert.return_value.execute.side_effect = RuntimeError("audit boom")
        with patch.object(admin_audit, "supabase", MagicMock(table=MagicMock(return_value=audit_table))):
            admin_api.registrar_auditoria_admin({"id": "u1", "email": "admin@example.com"}, "create", "gastos", "tx-1", {})

        failing_table = MagicMock()
        failing_table.select.return_value.order.return_value.execute.side_effect = RuntimeError("boom")
        supabase_mock = MagicMock(table=MagicMock(return_value=failing_table))

        async with main.app.test_request_context("/api/admin/cache-aprovacao"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=({"id": "u1", "email": "admin@example.com"}, None)), \
                 patch.object(admin_approvals, "supabase", supabase_mock):
                response = admin_api.listar_cache_admin()

        assert response.status_code == 503
        payload = await response.get_json()
        assert payload["code"] == "ADMIN_DATA_LOAD_FAILED"

    @pytest.mark.asyncio
    async def test_admin_mutation_helpers_return_auth_errors_early(self):
        actor = {"id": "u1", "email": "admin@example.com"}

        async with main.app.test_request_context("/api/admin/cache-aprovacao"):
            auth_error = admin_api._json_error("denied", 403, code="AUTH_ACCESS_DENIED")
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(None, auth_error)):
                listar_cache_resp = admin_api.listar_cache_admin()
        assert listar_cache_resp.status_code == 403

        async with main.app.test_request_context("/api/admin/gastos/tx-1", method="PATCH"):
            auth_error = admin_api._json_error("denied", 403, code="AUTH_ACCESS_DENIED")
            with patch.object(admin_transactions, "autenticar_admin_request", return_value=(None, auth_error)):
                update_resp = admin_api.atualizar_gasto_admin("tx-1", {"bad": "payload"})
        assert update_resp.status_code == 403

        with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)):
            async with main.app.test_request_context("/api/admin/gastos/tx-1", method="PATCH"):
                invalid_payload = admin_api.atualizar_gasto_admin("tx-1", None)
        assert invalid_payload.status_code == 400

    @pytest.mark.asyncio
    async def test_listar_gastos_admin_applies_optional_date_filters_independently(self):
        actor = {"id": "u1", "email": "admin@example.com"}
        query = MagicMock()
        query.gte.return_value = query
        query.lte.return_value = query
        query.execute.return_value = MagicMock(data=[])
        gastos = MagicMock()
        gastos.select.return_value.order.return_value = query

        with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(return_value=gastos))):
            async with main.app.test_request_context("/api/admin/gastos?date_from=2026-04-01"):
                only_from = admin_api.listar_gastos_admin()
            async with main.app.test_request_context("/api/admin/gastos?date_to=2026-04-30"):
                only_to = admin_api.listar_gastos_admin()

        assert only_from.status_code == 200
        assert only_to.status_code == 200
        assert query.gte.called
        assert query.lte.called

    @pytest.mark.asyncio
    async def test_admin_auth_helpers_cover_bearer_parsing_lookup_and_authorization_edges(self):
        long_token = "a" * (admin_auth.MAX_BEARER_TOKEN_CHARS + 1)

        async with main.app.test_request_context("/api/admin/me"):
            assert admin_auth._extract_bearer_token() is None

        async with main.app.test_request_context("/api/admin/me", headers={"Authorization": "   "}):
            assert admin_auth._extract_bearer_token() is None

        async with main.app.test_request_context("/api/admin/me", headers={"Authorization": "Bearer"}):
            assert admin_auth._extract_bearer_token() is None

        async with main.app.test_request_context("/api/admin/me", headers={"Authorization": "Basic token"}):
            assert admin_auth._extract_bearer_token() is None

        async with main.app.test_request_context("/api/admin/me", headers={"Authorization": f"Bearer {long_token}"}):
            assert admin_auth._extract_bearer_token() is None

        async with main.app.test_request_context("/api/admin/me", headers={"Authorization": "Bearer header.payload.signature"}):
            assert admin_auth._extract_bearer_token() == "header.payload.signature"

        with patch.object(admin_auth, "auth_test_mode_enabled", return_value=True):
            assert admin_auth._lookup_admin_user("user-1") == {"user_id": "user-1", "email": None}

        query = MagicMock()
        query.limit.return_value.execute.return_value = MagicMock(data=[])
        table = MagicMock()
        table.select.return_value.eq.return_value = query
        with patch.object(admin_auth, "auth_test_mode_enabled", return_value=False), \
             patch.object(admin_auth, "supabase", MagicMock(table=MagicMock(return_value=table))):
            assert admin_auth._lookup_admin_user("user-1") is None

        query.limit.return_value.execute.return_value = MagicMock(data=["bad-row"])
        with patch.object(admin_auth, "auth_test_mode_enabled", return_value=False), \
             patch.object(admin_auth, "supabase", MagicMock(table=MagicMock(return_value=table))):
            assert admin_auth._lookup_admin_user("user-1") is None

        async with main.app.test_request_context("/api/admin/me"):
            with patch.object(admin_auth, "_lookup_admin_user", return_value=None):
                actor, error = admin_auth._authorize_admin_identity("user-1", "admin@example.com")
        assert actor is None
        assert error.status_code == 403

        async with main.app.test_request_context("/api/admin/me"):
            with patch.object(admin_auth, "_lookup_admin_user", return_value={"user_id": "user-1", "email": "admin@example.com"}), \
                 patch.object(admin_auth, "ADMIN_USER_IDS", frozenset()), \
                 patch.object(admin_auth, "ADMIN_EMAILS", frozenset()):
                actor, error = admin_auth._authorize_admin_identity("user-1", None)
        assert error is None
        assert actor == {"id": "user-1", "email": "admin@example.com"}

    @pytest.mark.asyncio
    async def test_autenticar_admin_request_covers_test_mode_success_and_denied_without_bearer(self):
        async with main.app.test_request_context("/api/admin/me", headers={"Authorization": "Bearer auth-test-valid"}):
            with patch.object(admin_auth, "auth_test_mode_enabled", return_value=True), \
                 patch.object(admin_auth, "resolve_test_access_token", return_value={"id": "user-1", "email": "admin@example.com"}), \
                 patch.object(admin_auth, "_authorize_admin_identity", return_value=({"id": "user-1", "email": "admin@example.com"}, None)) as authorize_identity:
                actor, error = admin_auth.autenticar_admin_request()
        assert error is None
        assert actor["id"] == "user-1"
        authorize_identity.assert_called_once_with("user-1", "admin@example.com")

        async with main.app.test_request_context("/api/admin/me", headers={"Origin": "https://admin.example.com"}):
            with patch.object(admin_auth, "ALLOW_LOCAL_DEV_AUTH", False), \
                 patch.object(admin_auth, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://admin.example.com"})):
                actor, error = admin_auth.autenticar_admin_request()
        assert actor is None
        assert error.status_code == 401

    @pytest.mark.asyncio
    async def test_transactions_runtime_covers_test_mode_fallbacks_and_api_errors(self):
        actor = {"id": "u1", "email": "admin@example.com"}

        with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_transactions, "auth_test_mode_enabled", return_value=True), \
             patch.object(admin_transactions, "list_seeded_transactions", return_value=[{"id": "seed-1"}]):
            async with main.app.test_request_context("/api/admin/gastos?date_from=2026-04-01&date_to=2026-04-30"):
                seeded_response = admin_transactions.listar_gastos_admin()
        assert seeded_response.status_code == 200
        assert (await seeded_response.get_json())["transactions"] == [{"id": "seed-1"}]

        query = MagicMock()
        query.execute.side_effect = RuntimeError("boom")
        gastos = MagicMock()
        gastos.select.return_value.order.return_value = query
        with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_transactions, "auth_test_mode_enabled", return_value=False), \
             patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(return_value=gastos))):
            async with main.app.test_request_context("/api/admin/gastos"):
                list_error = admin_transactions.listar_gastos_admin()
        assert list_error.status_code == 503

        payload = {"data": "2026-04-01", "valor": 10, "categoria": "Mercado", "descricao": "Compra"}
        insert_table = MagicMock()
        insert_table.insert.return_value.execute.return_value = MagicMock(data=[])
        async with main.app.test_request_context("/api/admin/gastos", method="POST"):
            with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_transactions, "_normalize_transaction_payload", return_value=(payload, None)), \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(return_value=insert_table))), \
                 patch.object(admin_transactions, "registrar_auditoria_admin") as registrar:
                created = admin_transactions.criar_gasto_admin(payload)
        assert created.status_code == 201
        assert (await created.get_json())["transaction"] == payload
        registrar.assert_called_once()

        insert_table.insert.return_value.execute.side_effect = APIError({"message": "create fail", "code": "500", "details": "", "hint": ""})
        async with main.app.test_request_context("/api/admin/gastos", method="POST"):
            with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_transactions, "_normalize_transaction_payload", return_value=(payload, None)), \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(return_value=insert_table))):
                create_error = admin_transactions.criar_gasto_admin(payload)
        assert create_error.status_code == 503

        existing_query = MagicMock()
        existing_query.execute.return_value = MagicMock(data=[{"id": "tx-1"}])
        update_query = MagicMock()
        update_query.execute.return_value = MagicMock(data=[])
        gastos_table = MagicMock()
        gastos_table.select.return_value.eq.return_value = existing_query
        gastos_table.update.return_value.eq.return_value = update_query
        async with main.app.test_request_context("/api/admin/gastos/tx-1", method="PATCH"):
            with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_transactions, "_normalize_transaction_payload", return_value=(payload, None)), \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(return_value=gastos_table))), \
                 patch.object(admin_transactions, "registrar_auditoria_admin"):
                updated = admin_transactions.atualizar_gasto_admin("tx-1", payload)
        assert updated.status_code == 200
        assert (await updated.get_json())["transaction"] == {"id": "tx-1", **payload}

        existing_query.execute.return_value = MagicMock(data=[])
        async with main.app.test_request_context("/api/admin/gastos/tx-1", method="PATCH"):
            with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_transactions, "_normalize_transaction_payload", return_value=(payload, None)), \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(return_value=gastos_table))):
                not_found = admin_transactions.atualizar_gasto_admin("tx-1", payload)
        assert not_found.status_code == 404

        existing_query.execute.return_value = MagicMock(data=[{"id": "tx-1"}])
        update_query.execute.side_effect = APIError({"message": "update fail", "code": "500", "details": "", "hint": ""})
        async with main.app.test_request_context("/api/admin/gastos/tx-1", method="PATCH"):
            with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_transactions, "_normalize_transaction_payload", return_value=(payload, None)), \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(return_value=gastos_table))):
                update_error = admin_transactions.atualizar_gasto_admin("tx-1", payload)
        assert update_error.status_code == 503

        delete_existing_query = MagicMock()
        delete_existing_query.execute.return_value = MagicMock(data=[])
        delete_chain = MagicMock()
        delete_chain.eq.return_value.execute.return_value = MagicMock(data=[])
        delete_table = MagicMock()
        delete_table.select.return_value.eq.return_value = delete_existing_query
        delete_table.delete.return_value = delete_chain
        async with main.app.test_request_context("/api/admin/gastos/tx-1", method="DELETE"):
            with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(return_value=delete_table))):
                delete_not_found = admin_transactions.deletar_gasto_admin("tx-1")
        assert delete_not_found.status_code == 404

        delete_existing_query.execute.return_value = MagicMock(data=[{"id": "tx-1"}])
        delete_chain.eq.return_value.execute.side_effect = APIError({"message": "delete fail", "code": "500", "details": "", "hint": ""})
        async with main.app.test_request_context("/api/admin/gastos/tx-1", method="DELETE"):
            with patch.object(admin_transactions, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(return_value=delete_table))):
                delete_error = admin_transactions.deletar_gasto_admin("tx-1")
        assert delete_error.status_code == 503

    @pytest.mark.asyncio
    async def test_approvals_runtime_covers_success_paths_and_failure_branches(self):
        actor = {"id": "u1", "email": "admin@example.com"}
        async with main.app.test_request_context("/api/admin/cache-aprovacao", method="POST"):
            auth_error = admin_api._json_error("denied", 403, code="AUTH_ACCESS_DENIED")

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/approve", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(None, auth_error)):
                assert admin_approvals.aprovar_cache_admin("cache-1").status_code == 403
        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/reject", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(None, auth_error)):
                assert admin_approvals.rejeitar_cache_admin("cache-1").status_code == 403

        select_query = MagicMock()
        select_query.order.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "id": "cache-1",
                    "kind": None,
                    "preview_json": None,
                    "created_at": "2026-04-01T00:00:00",
                    "expires_at": "2026-04-02T00:00:00",
                    "payload": {"ids": ["tx-1", "tx-2"]},
                },
                {
                    "id": "cache-2",
                    "kind": "receipt_batch",
                    "preview_json": {"summary": "cached"},
                    "created_at": "2026-04-01T00:00:00",
                    "expires_at": "2026-04-02T00:00:00",
                    "payload": {"itens": []},
                },
            ]
        )
        cache_table = MagicMock()
        cache_table.select.return_value = select_query
        async with main.app.test_request_context("/api/admin/cache-aprovacao"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "supabase", MagicMock(table=MagicMock(return_value=cache_table))), \
                 patch.object(admin_approvals, "build_pending_preview", return_value={"summary": "built"}) as build_preview:
                listed = admin_approvals.listar_cache_admin()
        assert listed.status_code == 200
        listed_payload = await listed.get_json()
        assert listed_payload["items"][0]["kind"] == "delete_confirmation"
        assert listed_payload["items"][0]["preview"] == {"summary": "built"}
        assert listed_payload["items"][1]["preview"] == {"summary": "cached"}
        build_preview.assert_called_once()

        cache_table.select.return_value.order.return_value.execute.side_effect = APIError({"message": "list fail", "code": "500", "details": "", "hint": ""})
        async with main.app.test_request_context("/api/admin/cache-aprovacao"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "supabase", MagicMock(table=MagicMock(return_value=cache_table))):
                list_error = admin_approvals.listar_cache_admin()
        assert list_error.status_code == 503

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/approve", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value=None):
                missing = admin_approvals.aprovar_cache_admin("cache-1")
        assert missing.status_code == 404

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/approve", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value={"id": "cache-1", "payload": {}}), \
                 patch.object(admin_approvals, "pending_item_expired", return_value=True), \
                 patch.object(admin_approvals, "delete_pending_item") as delete_pending:
                expired = admin_approvals.aprovar_cache_admin("cache-1")
        assert expired.status_code == 410
        delete_pending.assert_called_once_with("cache-1")

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/approve", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value={"id": "cache-1", "payload": "bad"}), \
                 patch.object(admin_approvals, "pending_item_expired", return_value=False):
                unavailable = admin_approvals.aprovar_cache_admin("cache-1")
        assert unavailable.status_code == 500

        delete_query = MagicMock()
        delete_query.in_.return_value.execute.return_value = MagicMock(data=[])
        gastos_table = MagicMock()
        gastos_table.delete.return_value = delete_query
        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/approve", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value={"id": "cache-1", "kind": "delete_confirmation", "payload": {"ids": ["tx-1", "tx-2"]}}), \
                 patch.object(admin_approvals, "pending_item_expired", return_value=False), \
                 patch.object(admin_approvals, "supabase", MagicMock(table=MagicMock(return_value=gastos_table))), \
                 patch.object(admin_approvals, "delete_pending_item") as delete_pending, \
                 patch.object(admin_approvals, "registrar_auditoria_admin") as registrar:
                approved_delete = admin_approvals.aprovar_cache_admin("cache-1")
        assert approved_delete.status_code == 200
        assert (await approved_delete.get_json())["deleted_records"] == 2
        delete_pending.assert_called_once_with("cache-1")
        registrar.assert_called_once()

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/approve", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value={"id": "cache-1", "kind": "receipt_batch", "payload": {"itens": []}}), \
                 patch.object(admin_approvals, "pending_item_expired", return_value=False), \
                 patch.object(admin_approvals, "gravar_lote_no_banco", return_value=(3, 45.5)), \
                 patch.object(admin_approvals, "delete_pending_item") as delete_pending, \
                 patch.object(admin_approvals, "registrar_auditoria_admin") as registrar:
                approved_receipt = admin_approvals.aprovar_cache_admin("cache-1")
        assert approved_receipt.status_code == 200
        assert (await approved_receipt.get_json())["linhas"] == 3
        delete_pending.assert_called_once_with("cache-1")
        registrar.assert_called_once()

        delete_query.in_.return_value.execute.side_effect = APIError({"message": "approve fail", "code": "500", "details": "", "hint": ""})
        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/approve", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value={"id": "cache-1", "kind": "delete_confirmation", "payload": {"ids": ["tx-1"]}}), \
                 patch.object(admin_approvals, "pending_item_expired", return_value=False), \
                 patch.object(admin_approvals, "supabase", MagicMock(table=MagicMock(return_value=gastos_table))):
                approve_error = admin_approvals.aprovar_cache_admin("cache-1")
        assert approve_error.status_code == 503

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/approve", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value={"id": "cache-1", "kind": "receipt_batch", "payload": {"itens": []}}), \
                 patch.object(admin_approvals, "pending_item_expired", return_value=False), \
                 patch.object(admin_approvals, "gravar_lote_no_banco", side_effect=RuntimeError("boom")):
                approve_unexpected = admin_approvals.aprovar_cache_admin("cache-1")
        assert approve_unexpected.status_code == 503

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/reject", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value=None):
                reject_missing = admin_approvals.rejeitar_cache_admin("cache-1")
        assert reject_missing.status_code == 404

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/reject", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value={"id": "cache-1"}), \
                 patch.object(admin_approvals, "delete_pending_item") as delete_pending, \
                 patch.object(admin_approvals, "registrar_auditoria_admin") as registrar:
                rejected = admin_approvals.rejeitar_cache_admin("cache-1")
        assert rejected.status_code == 200
        delete_pending.assert_called_once_with("cache-1")
        registrar.assert_called_once()

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/reject", method="POST"):
            with patch.object(admin_approvals, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_approvals, "load_pending_item", return_value={"id": "cache-1"}), \
                 patch.object(admin_approvals, "delete_pending_item", side_effect=APIError({"message": "reject fail", "code": "500", "details": "", "hint": ""})):
                reject_error = admin_approvals.rejeitar_cache_admin("cache-1")
        assert reject_error.status_code == 503
