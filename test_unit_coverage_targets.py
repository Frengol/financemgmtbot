import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import InvalidToken
from postgrest.exceptions import APIError
for _key, _value in {
    "TELEGRAM_BOT_TOKEN": "FAKE_TELEGRAM_TOKEN",
    "TELEGRAM_SECRET_TOKEN": "FAKE_SECRET_TOKEN",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_KEY": "FAKE_SUPABASE_KEY_1234567890",
    "DEEPSEEK_API_KEY": "FAKE_DEEPSEEK_KEY_1234567890",
    "GROQ_API_KEY": "FAKE_GROQ_KEY_1234567890",
    "GEMINI_API_KEY": "FAKE_GEMINI_KEY_1234567890",
}.items():
    os.environ.setdefault(_key, _value)

_mock_supabase_client = MagicMock(name="top_level_supabase_client")
_supabase_patch = patch("supabase.create_client", return_value=_mock_supabase_client)
_supabase_patch.start()

import admin_api
import handlers
import main
import security


class TestMainHelperCoverage:
    def test_extract_user_fields_supports_multiple_shapes(self):
        assert main._extract_user_fields(None) == (None, None)
        assert main._extract_user_fields({"id": "user-1", "email": "admin@example.com"}) == ("user-1", "admin@example.com")

        user_object = SimpleNamespace(id="user-2", email="admin2@example.com")
        assert main._extract_user_fields(user_object) == ("user-2", "admin2@example.com")

        nested = SimpleNamespace(user=SimpleNamespace(id="user-3", email="nested@example.com"))
        assert main._extract_user_fields(nested) == ("user-3", "nested@example.com")

        session = SimpleNamespace(session=SimpleNamespace(user=SimpleNamespace(id="user-4", email="session@example.com")))
        assert main._extract_user_fields(session) == ("user-4", "session@example.com")

    @pytest.mark.asyncio
    async def test_request_scheme_and_public_url_helpers_cover_forwarded_and_loopback_branches(self):
        async with main.app.test_request_context(
            "/auth/session",
            headers={"Forwarded": 'for=1.1.1.1;proto="https"'},
        ):
            assert main._browser_cors_enabled() is True
            assert main._origin_allowed("http://localhost:5173") in {True, False}
            assert main._request_effective_scheme() == "https"
            assert main._request_is_effectively_secure() is True

        async with main.app.test_request_context(
            "/auth/session",
            headers={"X-Forwarded-Proto": "https,http"},
        ):
            assert main._request_effective_scheme() == "https"

        async with main.app.test_request_context("/plain"):
            assert main._browser_cors_enabled() is False
            assert main._is_loopback_request() is True
            with patch.object(main, "FRONTEND_PUBLIC_URL", ""), patch.object(main, "AUTH_CALLBACK_PUBLIC_URL", ""):
                assert main._default_frontend_public_url() == "http://localhost:5173/"
                assert main._default_auth_callback_public_url().endswith("/auth/callback")

    @pytest.mark.asyncio
    async def test_redirect_sanitization_and_test_support_helpers_cover_invalid_and_loopback_paths(self):
        async with main.app.test_request_context("/auth/magic-link"):
            with patch.object(main, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"):
                assert main._sanitize_frontend_redirect_target("") == "https://admin.example.com/app/"
                assert main._sanitize_frontend_redirect_target("https://admin.example.com/app/historico") == "https://admin.example.com/app/historico"
                assert main._sanitize_frontend_redirect_target("https://evil.example.com") == "https://admin.example.com/app/"

            with patch.object(main, "FRONTEND_PUBLIC_URL", ""), patch.object(main, "_is_loopback_request", return_value=True):
                assert main._sanitize_frontend_redirect_target("http://localhost:3000/app") == "http://localhost:3000/app"

        async with main.app.test_request_context("/__test__/auth/reset"):
            with patch.object(main, "auth_test_mode_enabled", return_value=False):
                assert main._test_support_request_allowed() is False
            with patch.object(main, "auth_test_mode_enabled", return_value=True), patch.object(main.request, "remote_addr", "127.0.0.1"):
                assert main._test_support_request_allowed() is True

    @pytest.mark.asyncio
    async def test_auth_session_and_test_support_routes_cover_error_paths(self):
        async with main.app.test_client() as client:
            session_resp = await client.get("/auth/session")
            assert session_resp.status_code == 200
            assert (await session_resp.get_json())["authenticated"] is False

            with patch("security.resolve_admin_session", side_effect=RuntimeError("boom")):
                client.set_cookie("localhost", security.SESSION_COOKIE_NAME, "opaque")
                failed_resp = await client.get("/auth/session")
                assert failed_resp.status_code == 200
                assert (await failed_resp.get_json())["authenticated"] is False

            with patch.object(main, "_test_support_request_allowed", return_value=False):
                assert (await client.post("/__test__/auth/reset")).status_code == 404
                assert (await client.post("/__test__/auth/transactions", json={"transactions": []})).status_code == 404
                assert (await client.get("/__test__/auth/magic-link?email=admin@example.com")).status_code == 404

            with patch.object(main, "_test_support_request_allowed", return_value=True):
                invalid_transactions = await client.post("/__test__/auth/transactions", json={"transactions": {"bad": "payload"}})
                assert invalid_transactions.status_code == 400

                missing_link = await client.get("/__test__/auth/magic-link?email=missing@example.com")
                assert missing_link.status_code == 404

    @pytest.mark.asyncio
    async def test_rate_limited_helper_returns_retry_metadata(self):
        async with main.app.test_request_context("/auth/magic-link"):
            with patch.object(main, "allow_request", return_value=False):
                response = main._rate_limited(
                    "auth_magic_link",
                    "127.0.0.1:admin@example.com",
                    limit=5,
                    window_seconds=120,
                    code="AUTH_MAGIC_LINK_RATE_LIMIT",
                    message="Too many login requests. Try again later.",
                )

        assert response.status_code == 429
        payload = await response.get_json()
        assert payload["code"] == "AUTH_MAGIC_LINK_RATE_LIMIT"
        assert payload["retryable"] is True
        assert payload["retryAfterSeconds"] == 120

    @pytest.mark.asyncio
    async def test_auth_routes_cover_fragment_bridge_invalid_callbacks_and_options(self):
        async with main.app.test_client() as client:
            with patch.object(main, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"), \
                 patch.object(main, "AUTH_CALLBACK_PUBLIC_URL", "https://api.example.com/auth/callback"):
                fragment_resp = await client.get("/auth/callback?next=https://admin.example.com/app/")
                assert fragment_resp.status_code == 200
                assert "Finalizing secure sign-in" in (await fragment_resp.get_data(as_text=True))

                invalid_post = await client.post("/auth/callback", json={"redirectTo": "https://admin.example.com/app/"})
                assert invalid_post.status_code == 400
                assert (await invalid_post.get_json())["code"] == "AUTH_SESSION_INVALID"

                options_resp = await client.options("/auth/callback")
                assert options_resp.status_code == 204

                session_options = await client.options("/auth/session")
                assert session_options.status_code == 204

                logout_options = await client.options("/auth/logout")
                assert logout_options.status_code == 204

                gastos_options = await client.options("/api/admin/gastos")
                assert gastos_options.status_code == 204

                cache_options = await client.options("/api/admin/cache-aprovacao")
                assert cache_options.status_code == 204

    @pytest.mark.asyncio
    async def test_auth_callback_covers_verify_failure_access_denied_and_test_support_success_paths(self):
        async with main.app.test_client() as client:
            with patch.object(main, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"), \
                 patch.object(main, "AUTH_CALLBACK_PUBLIC_URL", "https://api.example.com/auth/callback"), \
                 patch.object(main, "ADMIN_EMAILS", frozenset({"admin@example.com"})), \
                 patch.object(main, "ADMIN_USER_IDS", frozenset({"user-1"})), \
                 patch.object(main.supabase.auth, "verify_otp", return_value={"id": "blocked", "email": "blocked@example.com"}):
                denied = await client.get(
                    "/auth/callback?token_hash=token-1&type=magiclink&next=https://admin.example.com/app/"
                )
                assert denied.status_code == 302
                assert denied.headers["Location"].endswith("/login?reason=unauthorized")

            with patch.object(main, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"), \
                 patch.object(main, "AUTH_CALLBACK_PUBLIC_URL", "https://api.example.com/auth/callback"), \
                 patch.object(main.supabase.auth, "verify_otp", side_effect=RuntimeError("verify failed")):
                failed = await client.get(
                    "/auth/callback?token_hash=token-1&type=magiclink&next=https://admin.example.com/app/"
                )
                assert failed.status_code == 302
                assert failed.headers["Location"].endswith("/login")

            with patch.object(main, "_test_support_request_allowed", return_value=True), \
                 patch.object(main, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"), \
                 patch.object(main, "AUTH_CALLBACK_PUBLIC_URL", "https://api.example.com/auth/callback"):
                reset_resp = await client.post("/__test__/auth/reset")
                assert reset_resp.status_code == 200
                assert (await reset_resp.get_json())["reset"] is True

                link_resp = await client.post(
                    "/__test__/auth/magic-link",
                    json={
                        "email": "admin@example.com",
                        "userId": "user-1",
                        "redirectTo": "https://admin.example.com/app/",
                    },
                )
                assert link_resp.status_code == 200
                link_payload = await link_resp.get_json()
                assert link_payload["magicLink"]["user_id"] == "user-1"
                assert "token_hash=" in link_payload["magicLink"]["link"]

            with patch.object(main, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"), \
                 patch.object(main, "AUTH_CALLBACK_PUBLIC_URL", "https://api.example.com/auth/callback"), \
                 patch.object(main.supabase.auth, "get_user", side_effect=RuntimeError("expired")):
                invalid_user = await client.post(
                    "/auth/callback",
                    json={"access_token": "expired-token", "redirectTo": "https://admin.example.com/app/"},
                )
                assert invalid_user.status_code == 401
                assert (await invalid_user.get_json())["code"] == "AUTH_SESSION_INVALID"

            with patch.object(main, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"), \
                 patch.object(main, "AUTH_CALLBACK_PUBLIC_URL", "https://api.example.com/auth/callback"), \
                 patch.object(main.supabase.auth, "get_user", return_value=SimpleNamespace(user=SimpleNamespace(id="blocked", email="blocked@example.com"))), \
                 patch.object(main, "ADMIN_EMAILS", frozenset({"admin@example.com"})):
                forbidden = await client.post(
                    "/auth/callback",
                    json={"access_token": "valid-token", "redirectTo": "https://admin.example.com/app/"},
                )
                assert forbidden.status_code == 403
                assert (await forbidden.get_json())["code"] == "AUTH_ACCESS_DENIED"


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

            _, invalid_category_error = admin_api._normalize_transaction_payload({"data": "2026-04-01", "valor": 1, "categoria": "Inexistente", "descricao": "Compra"})
            assert invalid_category_error.status_code == 400

    @pytest.mark.asyncio
    async def test_autenticar_admin_request_covers_local_dev_bypass_and_access_denied(self):
        async with main.app.test_request_context("/api/admin/gastos", headers={"Origin": "http://localhost:5173"}):
            with patch.object(admin_api, "ALLOW_LOCAL_DEV_AUTH", True), patch.object(admin_api, "FRONTEND_ALLOWED_ORIGINS", frozenset({"http://localhost:5173"})):
                actor, error = admin_api.autenticar_admin_request()
                assert error is None
                assert actor["id"] == "local-dev"

        async with main.app.test_request_context("/api/admin/gastos", headers={"Cookie": f"{security.SESSION_COOKIE_NAME}=opaque"}):
            with patch.object(admin_api, "resolve_admin_session", return_value={"user_id": "wrong", "email": "wrong@example.com"}), \
                 patch.object(admin_api, "ADMIN_USER_IDS", frozenset({"expected"})), \
                 patch.object(admin_api, "ADMIN_EMAILS", frozenset({"admin@example.com"})):
                actor, error = admin_api.autenticar_admin_request()
                assert actor is None
                assert error.status_code == 403

    @pytest.mark.asyncio
    async def test_registrar_auditoria_admin_and_listar_cache_cover_failure_paths(self):
        audit_table = MagicMock()
        audit_table.insert.return_value.execute.side_effect = APIError({"message": "audit fail", "code": "500", "details": "", "hint": ""})

        with patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=audit_table))):
            admin_api.registrar_auditoria_admin({"id": "u1", "email": "admin@example.com"}, "create", "gastos", "tx-1", {})

        audit_table.insert.return_value.execute.side_effect = RuntimeError("audit boom")
        with patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=audit_table))):
            admin_api.registrar_auditoria_admin({"id": "u1", "email": "admin@example.com"}, "create", "gastos", "tx-1", {})

        failing_table = MagicMock()
        failing_table.select.return_value.order.return_value.execute.side_effect = RuntimeError("boom")
        supabase_mock = MagicMock(table=MagicMock(return_value=failing_table))

        async with main.app.test_request_context("/api/admin/cache-aprovacao"):
            with patch.object(admin_api, "autenticar_admin_request", return_value=({"id": "u1", "email": "admin@example.com"}, None)), \
                 patch.object(admin_api, "supabase", supabase_mock):
                response = admin_api.listar_cache_admin()

        assert response.status_code == 503
        payload = await response.get_json()
        assert payload["code"] == "ADMIN_DATA_LOAD_FAILED"

    @pytest.mark.asyncio
    async def test_list_and_mutation_routes_cover_api_errors_and_not_found_paths(self):
        actor = {"id": "u1", "email": "admin@example.com"}
        api_error = APIError({"message": "db fail", "code": "500", "details": "", "hint": ""})
        valid_payload = {
            "data": "2026-04-01",
            "valor": 10,
            "categoria": "Mercado",
            "descricao": "Compra de teste",
            "metodo_pagamento": "Pix",
            "conta": "Nubank",
        }

        failing_query = MagicMock()
        failing_query.order.return_value.execute.side_effect = api_error
        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "auth_test_mode_enabled", return_value=False), \
             patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=failing_query))):
            async with main.app.test_request_context("/api/admin/gastos"):
                list_resp = admin_api.listar_gastos_admin()
        assert list_resp.status_code == 503
        assert (await list_resp.get_json())["code"] == "ADMIN_DATA_LOAD_FAILED"

        create_table = MagicMock()
        create_table.insert.return_value.execute.side_effect = api_error
        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=create_table))):
            async with main.app.test_request_context("/api/admin/gastos", method="POST"):
                create_resp = admin_api.criar_gasto_admin(valid_payload)
        assert create_resp.status_code == 503
        assert (await create_resp.get_json())["code"] == "ADMIN_ACTION_FAILED"

        missing_table = MagicMock()
        missing_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=missing_table))):
            async with main.app.test_request_context("/api/admin/gastos/tx-404", method="PATCH"):
                update_missing = admin_api.atualizar_gasto_admin("tx-404", valid_payload)
        assert update_missing.status_code == 404

        update_table = MagicMock()
        update_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "tx-1"}])
        update_table.update.return_value.eq.return_value.execute.side_effect = api_error
        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=update_table))):
            async with main.app.test_request_context("/api/admin/gastos/tx-1", method="PATCH"):
                update_error = admin_api.atualizar_gasto_admin("tx-1", valid_payload)
        assert update_error.status_code == 503

        delete_missing_table = MagicMock()
        delete_missing_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=delete_missing_table))):
            async with main.app.test_request_context("/api/admin/gastos/tx-404", method="DELETE"):
                delete_missing = admin_api.deletar_gasto_admin("tx-404")
        assert delete_missing.status_code == 404

        delete_table = MagicMock()
        delete_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "tx-1"}])
        delete_table.delete.return_value.eq.return_value.execute.side_effect = api_error
        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=delete_table))):
            async with main.app.test_request_context("/api/admin/gastos/tx-1", method="DELETE"):
                delete_error = admin_api.deletar_gasto_admin("tx-1")
        assert delete_error.status_code == 503

    @pytest.mark.asyncio
    async def test_pending_actions_cover_missing_expired_invalid_payload_and_error_paths(self):
        actor = {"id": "u1", "email": "admin@example.com"}
        api_error = APIError({"message": "db fail", "code": "500", "details": "", "hint": ""})

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-1/approve", method="POST"):
            with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_api, "load_pending_item", return_value=None):
                missing = admin_api.aprovar_cache_admin("cache-1")
        assert missing.status_code == 404

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-2/approve", method="POST"):
            with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_api, "load_pending_item", return_value={"payload": {}, "kind": "receipt_batch"}), \
                 patch.object(admin_api, "pending_item_expired", return_value=True), \
                 patch.object(admin_api, "delete_pending_item") as delete_pending:
                expired = admin_api.aprovar_cache_admin("cache-2")
        assert expired.status_code == 410
        delete_pending.assert_called_once_with("cache-2")

        async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-3/approve", method="POST"):
            with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
                 patch.object(admin_api, "load_pending_item", return_value={"payload": None, "kind": "receipt_batch"}), \
                 patch.object(admin_api, "pending_item_expired", return_value=False):
                invalid_payload = admin_api.aprovar_cache_admin("cache-3")
        assert invalid_payload.status_code == 500

        delete_confirmation_table = MagicMock()
        delete_confirmation_table.delete.return_value.in_.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "load_pending_item", return_value={"payload": {"ids": ["tx-1", "tx-2"]}, "kind": "delete_confirmation"}), \
             patch.object(admin_api, "pending_item_expired", return_value=False), \
             patch.object(admin_api, "delete_pending_item") as delete_pending, \
             patch.object(admin_api, "registrar_auditoria_admin") as audit_mock, \
             patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=delete_confirmation_table))):
            async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-4/approve", method="POST"):
                delete_approved = admin_api.aprovar_cache_admin("cache-4")
        assert delete_approved.status_code == 200
        delete_pending.assert_called_once_with("cache-4")
        audit_mock.assert_called_once()

        failing_delete_table = MagicMock()
        failing_delete_table.delete.return_value.in_.return_value.execute.side_effect = api_error
        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "load_pending_item", return_value={"payload": {"ids": ["tx-1"]}, "kind": "delete_confirmation"}), \
             patch.object(admin_api, "pending_item_expired", return_value=False), \
             patch.object(admin_api, "supabase", MagicMock(table=MagicMock(return_value=failing_delete_table))):
            async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-5/approve", method="POST"):
                delete_failure = admin_api.aprovar_cache_admin("cache-5")
        assert delete_failure.status_code == 503

        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "load_pending_item", return_value={"payload": {"itens": []}, "kind": "receipt_batch"}), \
             patch.object(admin_api, "pending_item_expired", return_value=False), \
             patch.object(admin_api, "gravar_lote_no_banco", side_effect=RuntimeError("boom")):
            async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-6/approve", method="POST"):
                approval_failure = admin_api.aprovar_cache_admin("cache-6")
        assert approval_failure.status_code == 503

        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "load_pending_item", return_value=None):
            async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-7/reject", method="POST"):
                reject_missing = admin_api.rejeitar_cache_admin("cache-7")
        assert reject_missing.status_code == 404

        with patch.object(admin_api, "autenticar_admin_request", return_value=(actor, None)), \
             patch.object(admin_api, "load_pending_item", return_value={"payload": {}, "kind": "receipt_batch"}), \
             patch.object(admin_api, "delete_pending_item", side_effect=api_error):
            async with main.app.test_request_context("/api/admin/cache-aprovacao/cache-8/reject", method="POST"):
                reject_failure = admin_api.rejeitar_cache_admin("cache-8")
        assert reject_failure.status_code == 503


class TestHandlersAndSecurityCoverage:
    def test_normalization_helpers_cover_invalid_inputs(self):
        assert handlers._safe_float("bad", 1.5) == 1.5
        assert handlers._safe_int("bad", 7) == 7
        assert handlers._normalize_dados_lote(None)["itens"] == []
        normalized_lote = handlers._normalize_dados_lote(
            {
                "metodo_pagamento": None,
                "conta": None,
                "desconto_global": "x",
                "itens": [
                    {"nome": None, "valor_bruto": "9.5", "desconto_item": "1.5", "categoria": None},
                    "invalid",
                ],
            }
        )
        assert normalized_lote["metodo_pagamento"] == "Outros"
        assert normalized_lote["conta"] == "Nao Informada"
        assert normalized_lote["desconto_global"] == 0.0
        assert normalized_lote["itens"][0]["categoria"] == "Outros"
        assert handlers._normalize_dados_registro(None) == {}

    @pytest.mark.asyncio
    async def test_processar_update_covers_invalid_media_and_callback_rejections(self):
        http_client = AsyncMock()
        message_sender = AsyncMock()
        edit_sender = AsyncMock()

        with patch.object(handlers.telegram_service, "http_client", http_client), \
             patch.object(handlers, "enviar_mensagem_telegram", message_sender), \
             patch.object(handlers, "editar_mensagem_telegram", edit_sender), \
             patch.object(handlers, "baixar_arquivo_telegram", AsyncMock(return_value=b"")), \
             patch.object(handlers, "processar_texto_com_llm", AsyncMock()):
            await handlers.processar_update_assincrono(
                {
                    "update_id": 999,
                    "message": {
                        "chat": {"id": 1},
                        "from": {"id": 2},
                        "photo": [{"file_id": "photo"}],
                    },
                }
            )

        assert message_sender.await_args_list[-1].args[1] == "⚠️ A imagem enviada é inválida ou excede o tamanho suportado."

        http_client.reset_mock()
        message_sender.reset_mock()
        edit_sender.reset_mock()
        with patch.object(handlers.telegram_service, "http_client", http_client), \
             patch.object(handlers, "editar_mensagem_telegram", edit_sender), \
             patch.object(handlers, "load_pending_item", return_value={"kind": "delete_confirmation", "payload": {}, "origin_chat_id": "1", "origin_user_id": "2", "expires_at": "2999-01-01T00:00:00"}), \
             patch.object(handlers, "pending_item_expired", return_value=False), \
             patch.object(handlers, "matches_pending_origin", return_value=True), \
             patch.object(handlers, "delete_pending_item") as delete_pending_item:
            await handlers.processar_update_assincrono(
                {
                    "callback_query": {
                        "id": "cb-1",
                        "data": "aprovar_cache",
                        "from": {"id": 2},
                        "message": {"chat": {"id": 1}, "message_id": 10},
                    }
                }
            )

        edit_sender.assert_awaited_with(1, 10, "❌ Tipo de pendência inválido para aprovação.")
        delete_pending_item.assert_not_called()

        edit_sender.reset_mock()
        with patch.object(handlers.telegram_service, "http_client", http_client), \
             patch.object(handlers, "editar_mensagem_telegram", edit_sender), \
             patch.object(handlers, "load_pending_item", return_value={"kind": "receipt_batch", "payload": {}, "origin_chat_id": "1", "origin_user_id": "2", "expires_at": "2999-01-01T00:00:00"}), \
             patch.object(handlers, "pending_item_expired", return_value=False), \
             patch.object(handlers, "matches_pending_origin", return_value=False):
            await handlers.processar_update_assincrono(
                {
                    "callback_query": {
                        "id": "cb-2",
                        "data": "aprovar_cache",
                        "from": {"id": 99},
                        "message": {"chat": {"id": 1}, "message_id": 11},
                    }
                }
            )

        edit_sender.assert_awaited_with(1, 11, "❌ Operação não autorizada para esta conversa.")

    @pytest.mark.asyncio
    async def test_processar_update_covers_edit_delete_and_cancel_callback_actions(self):
        edit_sender = AsyncMock()
        http_client = AsyncMock()
        cache_item = {
            "kind": "receipt_batch",
            "payload": {"itens": []},
            "origin_chat_id": "1",
            "origin_user_id": "2",
            "expires_at": "2999-01-01T00:00:00",
        }

        with patch.object(handlers.telegram_service, "http_client", http_client), \
             patch.object(handlers, "editar_mensagem_telegram", edit_sender), \
             patch.object(handlers, "load_pending_item", return_value=cache_item), \
             patch.object(handlers, "pending_item_expired", return_value=False), \
             patch.object(handlers, "matches_pending_origin", return_value=True), \
             patch.object(handlers, "gerar_texto_edicao", return_value="linha 1"), \
             patch.object(handlers, "delete_pending_item") as delete_pending:
            await handlers.processar_update_assincrono(
                {
                    "callback_query": {
                        "id": "cb-edit",
                        "data": "editar_cache-1",
                        "from": {"id": 2},
                        "message": {"chat": {"id": 1}, "message_id": 12},
                    }
                }
            )

        edit_sender.assert_awaited_with(1, 12, "📝 **MODO EDIÇÃO**\nCopie, altere as categorias/valores e envie:\n\n`linha 1`")
        delete_pending.assert_called_once_with("cache-1")

        delete_table = MagicMock()
        delete_table.delete.return_value.in_.return_value.execute.return_value = MagicMock(data=[])
        edit_sender.reset_mock()
        with patch.object(handlers.telegram_service, "http_client", http_client), \
             patch.object(handlers, "editar_mensagem_telegram", edit_sender), \
             patch.object(handlers, "load_pending_item", return_value={**cache_item, "kind": "delete_confirmation", "payload": {"ids": ["tx-1", "tx-2"]}}), \
             patch.object(handlers, "pending_item_expired", return_value=False), \
             patch.object(handlers, "matches_pending_origin", return_value=True), \
             patch.object(handlers, "delete_pending_item") as delete_pending, \
             patch.object(handlers, "supabase", MagicMock(table=MagicMock(return_value=delete_table))):
            await handlers.processar_update_assincrono(
                {
                    "callback_query": {
                        "id": "cb-del",
                        "data": "confirmdel_cache-2",
                        "from": {"id": 2},
                        "message": {"chat": {"id": 1}, "message_id": 13},
                    }
                }
            )

        edit_sender.assert_awaited_with(1, 13, "🗑️ **Exclusão Efetuada!** (2 registros apagados).")
        delete_pending.assert_called_once_with("cache-2")

        edit_sender.reset_mock()
        with patch.object(handlers.telegram_service, "http_client", http_client), \
             patch.object(handlers, "editar_mensagem_telegram", edit_sender), \
             patch.object(handlers, "load_pending_item", return_value=cache_item), \
             patch.object(handlers, "pending_item_expired", return_value=False), \
             patch.object(handlers, "matches_pending_origin", return_value=True), \
             patch.object(handlers, "delete_pending_item") as delete_pending:
            await handlers.processar_update_assincrono(
                {
                    "callback_query": {
                        "id": "cb-cancel",
                        "data": "cancelar_cache-3",
                        "from": {"id": 2},
                        "message": {"chat": {"id": 1}, "message_id": 14},
                    }
                }
            )

        edit_sender.assert_awaited_with(1, 14, "❌ **Operação Cancelada.** A base de dados não foi alterada.")
        delete_pending.assert_called_once_with("cache-3")

    @pytest.mark.asyncio
    async def test_processar_update_covers_callback_without_cache_id_and_invalid_voice(self):
        http_client = AsyncMock()
        edit_sender = AsyncMock()
        message_sender = AsyncMock()

        with patch.object(handlers.telegram_service, "http_client", http_client), \
             patch.object(handlers, "editar_mensagem_telegram", edit_sender), \
             patch.object(handlers, "enviar_mensagem_telegram", message_sender):
            await handlers.processar_update_assincrono(
                {
                    "callback_query": {
                        "id": "cb-no-cache",
                        "data": "aprovar",
                        "from": {"id": 2},
                        "message": {"chat": {"id": 1}, "message_id": 15},
                    }
                }
            )

        http_client.post.assert_awaited_once()
        edit_sender.assert_not_awaited()

        message_sender.reset_mock()
        with patch.object(handlers.telegram_service, "http_client", None), \
             patch.object(handlers, "enviar_mensagem_telegram", message_sender), \
             patch.object(handlers, "enviar_acao_telegram", AsyncMock()), \
             patch.object(
                 handlers,
                 "baixar_arquivo_telegram",
                 AsyncMock(return_value=b"x" * (handlers.MAX_TELEGRAM_AUDIO_BYTES + 1)),
             ):
            await handlers.processar_update_assincrono(
                {
                    "message": {
                        "chat": {"id": 1},
                        "from": {"id": 2},
                        "voice": {"file_id": "voice-1"},
                    }
                }
            )

        assert message_sender.await_args_list[-1].args[1] == "⚠️ O áudio enviado é inválido ou excede o tamanho suportado."

    @pytest.mark.asyncio
    async def test_processar_update_covers_consultar_variants(self):
        message_sender = AsyncMock()
        consultar_mock = MagicMock(return_value=(123.45, 7))
        inferencia_mock = MagicMock(return_value=("Essencial", "Mercado"))
        casos = [
            (
                {"mes": "ab", "ano": "2026", "tipo_transacao": "saida"},
                "📊 **Total de Gastos (Saídas):** R$ 123.45",
                "🎛️ Filtros: ab/2026",
                "🗂️ Busca Global",
            ),
            (
                {"ano": "2026", "tipo_transacao": "entrada"},
                "📊 **Total de Ganhos (Entradas):** R$ 123.45",
                "🎛️ Filtros: 2026",
                "🗂️ Busca Global",
            ),
            (
                {"categoria": "Mercado"},
                "📊 **Total:** R$ 123.45",
                "🎛️ Filtros: Nenhum",
                "🗂️ Categoria: Mercado (Essencial)",
            ),
            (
                {"natureza": "qualquer"},
                "📊 **Total:** R$ 123.45",
                "🎛️ Filtros: Nenhum",
                "🗂️ Natureza: Todas",
            ),
        ]

        with patch.object(handlers, "enviar_acao_telegram", AsyncMock()), \
             patch.object(handlers, "enviar_mensagem_telegram", message_sender), \
             patch.object(handlers, "consultar_no_banco", consultar_mock), \
             patch.object(handlers, "inferir_natureza", inferencia_mock):
            for filtros, total_txt, filtro_txt, detalhe_txt in casos:
                message_sender.reset_mock()
                with patch.object(
                    handlers,
                    "processar_texto_com_llm",
                    AsyncMock(return_value={"intencao": "consultar", "filtros_pesquisa": filtros}),
                ):
                    await handlers.processar_update_assincrono(
                        {
                            "message": {
                                "chat": {"id": 1},
                                "from": {"id": 2},
                                "text": "consultar",
                            }
                        }
                    )

                resposta = message_sender.await_args_list[-1].args[1]
                assert total_txt in resposta
                assert filtro_txt in resposta
                assert detalhe_txt in resposta

    @pytest.mark.asyncio
    async def test_processar_update_covers_excluir_variants_and_safe_failure_message(self):
        iniciar_fluxo = AsyncMock()
        message_sender = AsyncMock()

        with patch.object(handlers, "enviar_acao_telegram", AsyncMock()), \
             patch.object(handlers, "iniciar_fluxo_exclusao", iniciar_fluxo), \
             patch.object(
                 handlers,
                 "processar_texto_com_llm",
                 AsyncMock(return_value={"intencao": "excluir", "filtros_exclusao": {"descricao": "uber"}}),
             ):
            await handlers.processar_update_assincrono(
                {
                    "message": {
                        "chat": {"id": 1},
                        "text": "excluir",
                    }
                }
            )
            await handlers.processar_update_assincrono(
                {
                    "message": {
                        "chat": {"id": 1},
                        "from": {"id": 99},
                        "text": "excluir",
                    }
                }
            )

        assert iniciar_fluxo.await_args_list[0].args == (1, {"descricao": "uber"})
        assert iniciar_fluxo.await_args_list[1].args == (1, {"descricao": "uber"})
        assert iniciar_fluxo.await_args_list[1].kwargs == {"origin_user_id": 99}

        with patch.object(handlers, "enviar_acao_telegram", AsyncMock()), \
             patch.object(handlers, "enviar_mensagem_telegram", message_sender), \
             patch.object(
                 handlers,
                 "processar_texto_com_llm",
                 AsyncMock(return_value={"intencao": "desconhecida"}),
             ):
            await handlers.processar_update_assincrono(
                {
                    "message": {
                        "chat": {"id": 1},
                        "from": {"id": 2},
                        "text": "quebrar",
                    }
                }
            )

        assert message_sender.await_args_list[-1].args[1].startswith("❌ *Falha Sistémica*")

    def test_security_helpers_cover_session_and_pending_branches(self):
        assert security.hash_optional(None) is None
        assert security.validate_csrf_token("opaque", None) is False
        parsed = security._parse_timestamp("2026-04-05T10:00:00+00:00")
        assert parsed is not None
        assert parsed.tzinfo is None
        assert security.resolve_admin_session(None) is None
        assert security.pending_item_expired(None) is True
        assert security.matches_pending_origin({"origin_chat_id": "1", "origin_user_id": "2"}, 9, 2) is False
        assert security.matches_pending_origin({"origin_chat_id": "1", "origin_user_id": "2"}, 1, 9) is False
        assert security.matches_pending_origin({"origin_chat_id": "1", "origin_user_id": "2"}, 1, None) is True

    def test_security_storage_and_loading_cover_empty_and_non_test_paths(self):
        supabase_table = MagicMock()
        supabase_table.insert.return_value.execute.return_value = MagicMock(data=[])
        supabase_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        with patch.object(security, "auth_test_mode_enabled", return_value=False), \
             patch.object(security, "supabase", MagicMock(table=MagicMock(return_value=supabase_table))):
            session = security.create_admin_session("user-1", "admin@example.com", "agent", "127.0.0.1")
            assert session["token"]
            assert session["csrf_token"]

            security.revoke_admin_session(None)
            assert security.load_pending_item("missing") is None

    def test_security_non_test_mode_helpers_cover_remaining_branches(self):
        now = datetime(2026, 4, 5, 10, 0, 0)
        session_table = MagicMock()
        session_table.insert.return_value.execute.return_value = MagicMock(data=[])
        session_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
            "session_id_hash": "hash",
            "user_id": "u1",
            "email": "admin@example.com",
            "created_at": "2026-04-05T08:00:00",
            "last_seen_at": "2026-04-05T08:00:00",
            "expires_at": "2026-04-05T18:00:00",
            "revoked_at": None,
        }])
        session_table.update.return_value.eq.return_value.execute.side_effect = RuntimeError("update failed")
        supabase_mock = MagicMock(table=MagicMock(return_value=session_table))

        with patch.object(security, "auth_test_mode_enabled", return_value=False), \
             patch.object(security, "supabase", supabase_mock), \
             patch.object(security, "get_brasilia_time", return_value=now):
            created = security.create_admin_session("u1", "admin@example.com", "agent", "127.0.0.1")
            resolved = security.resolve_admin_session(created["token"])
            session_table.update.return_value.eq.return_value.execute.side_effect = None
            session_table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            security.revoke_admin_session(created["token"])

        assert created["csrf_token"]
        assert resolved["user_id"] == "u1"
        assert session_table.insert.called
        assert session_table.update.called

        missing_table = MagicMock()
        missing_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(security, "auth_test_mode_enabled", return_value=False), \
             patch.object(security, "supabase", MagicMock(table=MagicMock(return_value=missing_table))):
            assert security.resolve_admin_session("missing-token") is None

        expired_table = MagicMock()
        expired_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
            "session_id_hash": "hash",
            "user_id": "u1",
            "email": "admin@example.com",
            "created_at": "2026-04-04T08:00:00",
            "last_seen_at": "2026-04-04T08:00:00",
            "expires_at": "2026-04-05T08:00:00",
            "revoked_at": "2026-04-05T08:30:00",
        }])
        with patch.object(security, "auth_test_mode_enabled", return_value=False), \
             patch.object(security, "supabase", MagicMock(table=MagicMock(return_value=expired_table))), \
             patch.object(security, "get_brasilia_time", return_value=now):
            assert security.resolve_admin_session("expired-token") is None

        cache_table = MagicMock()
        cache_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
            "id": "cache-1",
            "kind": None,
            "payload_ciphertext": "bad-token",
            "payload_key_version": "v1",
            "preview_json": None,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "origin_chat_id": "10",
            "origin_user_id": "20",
            "payload": None,
        }])
        with patch.object(security, "supabase", MagicMock(table=MagicMock(return_value=cache_table))), \
             patch.object(security, "decrypt_pending_payload", side_effect=InvalidToken()):
            invalid_cipher = security.load_pending_item("cache-1")
        assert invalid_cipher["payload"] is None
        assert invalid_cipher["preview_json"]["summary"] == "Cupom pendente"

        legacy_cache_table = MagicMock()
        legacy_cache_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
            "id": "cache-2",
            "kind": None,
            "payload_ciphertext": None,
            "payload_key_version": None,
            "preview_json": None,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "origin_chat_id": "10",
            "origin_user_id": "20",
            "payload": {"ids": ["tx-1"]},
        }])
        with patch.object(security, "supabase", MagicMock(table=MagicMock(return_value=legacy_cache_table))):
            legacy_item = security.load_pending_item("cache-2")
        assert legacy_item["payload"] == {"ids": ["tx-1"]}
        assert legacy_item["kind"] == "delete_confirmation"

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
        assert security.pending_item_expired({"expires_at": None}) is False
        assert security.matches_pending_origin(None, 1, 2) is False
        assert security.matches_pending_origin({"origin_chat_id": "11", "origin_user_id": "20"}, 10, 20) is False
        assert security.matches_pending_origin({"origin_chat_id": "10", "origin_user_id": "21"}, 10, 20) is False

    def test_security_key_and_test_mode_branches_cover_configured_and_invalid_values(self):
        valid_key = security.Fernet.generate_key().decode("utf-8")
        with patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": valid_key}, clear=False):
            assert security._fernet_key() == valid_key.encode("utf-8")

        with patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": "invalid-key"}, clear=False), \
             patch.object(security.logger, "warning") as warning_mock:
            derived = security._fernet_key()
        assert derived != b"invalid-key"
        warning_mock.assert_called_once()

        with patch.object(security, "auth_test_mode_enabled", return_value=True), \
             patch.object(security, "load_admin_session", return_value=None):
            assert security.resolve_admin_session("opaque") is None

        with patch.object(security, "auth_test_mode_enabled", return_value=True), \
             patch.object(security, "revoke_test_admin_session") as revoke_test_session:
            security.revoke_admin_session("opaque")
        revoke_test_session.assert_called_once()
