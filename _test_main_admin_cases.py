import os
import json
from contextlib import ExitStack, contextmanager
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock, patch

import pytest
from quart import Quart

import config
import main
import security
import test_support
from admin_runtime import approvals as admin_approvals
from admin_runtime import auth as admin_auth
from admin_runtime import transactions as admin_transactions
from web_app import auth_test_support_routes, http as web_http, observability_routes


class TestAdminRoutes:
    @contextmanager
    def _authorized_admin(self, *, email: str = "admin@example.com", user_id: str = "user-1", bearer_token: str = "header.payload.signature"):
        auth_response = MagicMock()
        auth_response.user = {"id": user_id, "email": email}

        with ExitStack() as stack:
            stack.enter_context(patch.object(admin_auth.supabase.auth, "get_user", MagicMock(return_value=auth_response)))
            stack.enter_context(patch.object(admin_auth, "_lookup_admin_user", return_value={"user_id": user_id, "email": email}))
            stack.enter_context(patch.object(admin_auth, "ADMIN_EMAILS", frozenset({email})))
            stack.enter_context(patch.object(admin_auth, "ADMIN_USER_IDS", frozenset({user_id})))
            stack.enter_context(patch.object(admin_auth, "auth_test_mode_enabled", return_value=False))
            stack.enter_context(patch.object(admin_transactions, "auth_test_seeded_mode_enabled", return_value=False))
            yield {"Authorization": f"Bearer {bearer_token}"}

    @pytest.mark.asyncio
    async def test_auth_test_verify_redirects_to_frontend_callback_with_tokens_and_bearer_data_loads(self):
        seeded_transactions = [
            {
                "id": "tx-auth-1",
                "data": "2026-04-04",
                "natureza": "Essencial",
                "categoria": "Mercado",
                "descricao": "Mercado autenticado",
                "valor": 42.5,
                "conta": "Nubank",
                "metodo_pagamento": "Pix",
            }
        ]

        with patch.dict(os.environ, {"AUTH_TEST_MODE": "true"}, clear=False):
            test_support.seed_transactions(seeded_transactions)
            temp_app = Quart(__name__)
            auth_test_support_routes.register_test_support_routes(temp_app)

            async with temp_app.test_client() as client:
                with patch.object(web_http, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"), \
                     patch.object(auth_test_support_routes, "test_support_request_allowed", return_value=True), \
                     patch.object(admin_auth, "auth_test_mode_enabled", return_value=True), \
                     patch.object(admin_transactions, "auth_test_seeded_mode_enabled", return_value=True):
                    magic_link_resp = await client.post(
                        "/__test__/auth/magic-link",
                        json={"email": "admin@example.com", "redirectTo": "https://admin.example.com/app/auth/callback"},
                    )
                    assert magic_link_resp.status_code == 200
                    magic_link_payload = await magic_link_resp.get_json()
                    verify_target = urlsplit(magic_link_payload["magicLink"]["link"])
                    verify_resp = await client.get(f"{verify_target.path}?{verify_target.query}")

                    assert verify_resp.status_code == 302
                    redirect_target = urlsplit(verify_resp.headers["Location"])
                    assert redirect_target.path == "/app/auth/callback"
                    fragment = parse_qs(redirect_target.fragment)
                    assert fragment["access_token"][0].count(".") == 2

                    bearer_token = fragment["access_token"][0]
            async with main.app.test_client() as client:
                with patch.object(admin_auth, "auth_test_mode_enabled", return_value=True), \
                     patch.object(admin_transactions, "auth_test_seeded_mode_enabled", return_value=True):
                    transactions_resp = await client.get(
                        "/api/admin/gastos?date_from=2026-04-01&date_to=2026-04-30",
                        headers={"Authorization": f"Bearer {bearer_token}"},
                    )

        assert transactions_resp.status_code == 200
        transactions_payload = await transactions_resp.get_json()
        assert transactions_payload["transactions"] == seeded_transactions

    @pytest.mark.asyncio
    async def test_productive_auth_routes_are_removed_from_runtime(self):
        async with main.app.test_client() as client:
            assert (await client.post("/auth/magic-link", json={"email": "admin@example.com"})).status_code == 404
            assert (await client.get("/auth/callback")).status_code == 404
            assert (await client.get("/auth/callback?token_hash=fakehash&type=magiclink")).status_code == 404
            assert (await client.post("/auth/callback", json={"access_token": "token"})).status_code == 404
            assert (await client.get("/auth/session")).status_code == 404
            assert (await client.post("/auth/logout")).status_code == 404

    @pytest.mark.asyncio
    async def test_admin_delete_requires_bearer_auth(self):
        async with main.app.test_client() as client:
            resp = await client.delete("/api/admin/gastos/tx-1")

        assert resp.status_code == 401
        payload = await resp.get_json()
        assert payload["message"] == "Invalid or expired session."
        assert payload["code"] == "AUTH_SESSION_INVALID"

    @pytest.mark.asyncio
    async def test_admin_list_transactions_accepts_valid_bearer_without_cookie_session(self):
        mock_gastos = MagicMock()
        mock_gastos.select.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{"id": "tx-1", "descricao": "Mercado Bearer"}]
        )

        def table_switch(name):
            if name == "gastos":
                return mock_gastos
            return MagicMock()

        async with main.app.test_client() as client:
            with self._authorized_admin() as headers, \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))):
                resp = await client.get("/api/admin/gastos", headers=headers)

        assert resp.status_code == 200
        payload = await resp.get_json()
        assert payload["transactions"] == [{"id": "tx-1", "descricao": "Mercado Bearer"}]

    @pytest.mark.asyncio
    async def test_admin_create_transaction_with_valid_bearer_does_not_require_csrf(self):
        mock_gastos = MagicMock()
        mock_gastos.insert.return_value.execute.return_value = MagicMock(data=[{
            "id": "tx-99",
            "data": "2026-03-19",
            "valor": 99.9,
            "natureza": "Essencial",
            "categoria": "Mercado",
            "descricao": "Compra bearer",
            "metodo_pagamento": "Pix",
            "conta": "Nubank",
        }])

        def table_switch(name):
            if name == "gastos":
                return mock_gastos
            if name == "auditoria_admin":
                return MagicMock()
            return MagicMock()

        async with main.app.test_client() as client:
            with self._authorized_admin() as headers, \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))), \
                 patch.object(admin_approvals, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))):
                resp = await client.post(
                    "/api/admin/gastos",
                    headers=headers,
                    json={
                        "data": "2026-03-19",
                        "valor": 99.9,
                        "categoria": "Mercado",
                        "descricao": "Compra bearer",
                        "metodo_pagamento": "Pix",
                        "conta": "Nubank",
                    },
                )

        assert resp.status_code == 201
        payload = await resp.get_json()
        assert payload["transaction"]["id"] == "tx-99"

    @pytest.mark.asyncio
    async def test_admin_routes_reject_malformed_bearer_tokens_with_short_detail(self):
        malformed_get_user = MagicMock(
            side_effect=Exception("invalid JWT: unable to parse or verify signature, token is malformed: token contains an invalid number of segments")
        )
        log_calls = []

        async with main.app.test_client() as client:
            with patch.object(admin_auth.logger, "warning", side_effect=lambda payload: log_calls.append(payload)), \
                 patch.object(admin_auth.supabase.auth, "get_user", malformed_get_user), \
                 patch.object(admin_auth, "auth_test_mode_enabled", return_value=False):
                resp = await client.get("/api/admin/gastos", headers={"Authorization": "Bearer not-a-jwt"})

        assert resp.status_code == 401
        payload = await resp.get_json()
        assert payload["code"] == "AUTH_SESSION_TOKEN_MALFORMED"
        assert payload["detail"] == "bearer_malformed"
        assert log_calls[-1]["event"] == "admin_bearer_auth_failed"

    @pytest.mark.asyncio
    async def test_admin_me_accepts_long_valid_bearer_without_truncating_it(self):
        long_segment = "a" * 180
        long_bearer = f"{long_segment}.{long_segment}.{long_segment}"
        auth_response = MagicMock()
        auth_response.user = {"id": "user-1", "email": "admin@example.com"}
        get_user = MagicMock(return_value=auth_response)

        async with main.app.test_client() as client:
            with self._authorized_admin(bearer_token=long_bearer) as headers, \
                 patch.object(admin_auth.supabase.auth, "get_user", get_user):
                resp = await client.get("/api/admin/me", headers=headers)

        assert resp.status_code == 200
        get_user.assert_called_once_with(long_bearer)

    @pytest.mark.asyncio
    async def test_admin_routes_reject_bearer_tokens_for_blocked_identities(self):
        blocked_user = MagicMock(return_value=MagicMock(user={"id": "user-1", "email": "blocked@example.com"}))

        async with main.app.test_client() as client:
            with patch.object(admin_auth, "_lookup_admin_user", return_value={"user_id": "user-1", "email": "blocked@example.com"}), \
                 patch.object(admin_auth, "ADMIN_EMAILS", frozenset({"admin@example.com"})), \
                 patch.object(admin_auth, "ADMIN_USER_IDS", frozenset({"user-1"})), \
                 patch.object(admin_auth, "auth_test_mode_enabled", return_value=False), \
                 patch.object(admin_auth.supabase.auth, "get_user", blocked_user):
                resp = await client.get("/api/admin/me", headers={"Authorization": "Bearer header.payload.signature"})

        assert resp.status_code == 403
        assert (await resp.get_json())["code"] == "AUTH_ACCESS_DENIED"

    @pytest.mark.asyncio
    async def test_admin_preflight_allows_authorization_header(self):
        async with main.app.test_client() as client:
            with patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://frengol.github.io"})):
                resp = await client.options(
                    "/api/admin/gastos",
                    headers={
                        "Origin": "https://frengol.github.io",
                        "Access-Control-Request-Method": "GET",
                        "Access-Control-Request-Headers": "authorization, x-client-request-id",
                    },
                )

        assert resp.status_code == 204
        assert resp.headers["Access-Control-Allow-Headers"] == "Authorization, Content-Type, X-Client-Request-ID"

    @pytest.mark.asyncio
    async def test_admin_me_reads_success_response_with_allowed_origin(self):
        async with main.app.test_client() as client:
            with self._authorized_admin() as headers, \
                 patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://frengol.github.io"})):
                resp = await client.get(
                    "/api/admin/me",
                    headers={
                        **headers,
                        "Origin": "https://frengol.github.io",
                        "X-Client-Request-ID": "reqc_front_1",
                    },
                )

        assert resp.status_code == 200
        assert resp.headers["Access-Control-Allow-Origin"] == "https://frengol.github.io"
        assert resp.headers["Access-Control-Expose-Headers"] == "X-Request-ID, X-Client-Request-ID"
        assert resp.headers["X-Client-Request-ID"] == "reqc_front_1"

    @pytest.mark.asyncio
    async def test_admin_me_omits_cors_header_for_disallowed_origin(self):
        async with main.app.test_client() as client:
            with self._authorized_admin() as headers, \
                 patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://frengol.github.io"})):
                resp = await client.get(
                    "/api/admin/me",
                    headers={
                        **headers,
                        "Origin": "https://evil.example.com",
                    },
                )

        assert resp.status_code == 200
        assert "Access-Control-Allow-Origin" not in resp.headers

    @pytest.mark.asyncio
    async def test_runtime_meta_reports_public_runtime_version_metadata(self):
        async with main.app.test_client() as client:
            with patch.object(observability_routes, "APP_COMMIT_SHA", "557a1d4fedcba9876543210"), \
                 patch.object(observability_routes, "APP_RELEASE_SHA", "557a1d4fedcb"), \
                 patch.object(observability_routes, "K_SERVICE", "financemgmtbot-git"), \
                 patch.object(observability_routes, "K_REVISION", "financemgmtbot-git-00042-abc"), \
                 patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://frengol.github.io"})):
                resp = await client.get(
                    "/api/meta/runtime",
                    headers={"Origin": "https://frengol.github.io"},
                )

        assert resp.status_code == 200
        payload = await resp.get_json()
        assert payload["status"] == "ok"
        assert payload["commitSha"] == "557a1d4fedcba9876543210"
        assert payload["releaseSha"] == "557a1d4fedcb"
        assert payload["service"] == "financemgmtbot-git"
        assert payload["revision"] == "financemgmtbot-git-00042-abc"
        assert payload["requestId"].startswith("req_")
        assert resp.headers["Access-Control-Allow-Origin"] == "https://frengol.github.io"

    @pytest.mark.asyncio
    async def test_client_telemetry_accepts_valid_payload_and_logs_structured_event(self):
        logged_events = []

        async with main.app.test_client() as client:
            with patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://frengol.github.io"})), \
                 patch.object(observability_routes.logger, "info", side_effect=lambda payload: logged_events.append(payload)):
                resp = await client.post(
                    "/api/client-telemetry",
                    headers={
                        "Origin": "https://frengol.github.io",
                        "Content-Type": "text/plain;charset=UTF-8",
                    },
                    data=json.dumps({
                        "event": "auth_callback_failed",
                        "phase": "callback_admin_validation",
                        "clientEventId": "cli_123456789abc",
                        "clientRequestId": "reqc_front_1",
                        "releaseId": "557a1d4fedcb",
                        "pagePath": "/financemgmtbot/auth/callback",
                        "apiOrigin": "https://financemgmtbot-git-606617355477.southamerica-east1.run.app",
                        "online": True,
                        "httpStatus": 200,
                        "errorCode": "NETWORK_ERROR",
                        "diagnostic": "frontend_transport_failed",
                        "requestId": "req_backend_1",
                        "corsSuspected": True,
                    }),
                )

        assert resp.status_code == 202
        assert resp.headers["Access-Control-Allow-Origin"] == "https://frengol.github.io"
        payload = await resp.get_json()
        assert payload["status"] == "ok"
        assert logged_events[-1]["event"] == "browser_client_telemetry"
        assert logged_events[-1]["client_event_id"] == "cli_123456789abc"
        assert logged_events[-1]["client_request_id"] == "reqc_front_1"
        assert logged_events[-1]["release_id"] == "557a1d4fedcb"
        assert logged_events[-1]["request_id"].startswith("req_")

    @pytest.mark.asyncio
    async def test_client_telemetry_rejects_unexpected_fields_and_disallowed_origins(self):
        async with main.app.test_client() as client:
            with patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://frengol.github.io"})):
                invalid_resp = await client.post(
                    "/api/client-telemetry",
                    headers={
                        "Origin": "https://frengol.github.io",
                        "Content-Type": "text/plain;charset=UTF-8",
                    },
                    data=json.dumps({
                        "event": "auth_callback_failed",
                        "phase": "callback_admin_validation",
                        "clientEventId": "cli_123456789abc",
                        "unexpected": "field",
                    }),
                )
                blocked_origin_resp = await client.post(
                    "/api/client-telemetry",
                    headers={
                        "Origin": "https://evil.example.com",
                        "Content-Type": "text/plain;charset=UTF-8",
                    },
                    data=json.dumps({
                        "event": "auth_callback_failed",
                        "phase": "callback_admin_validation",
                        "clientEventId": "cli_123456789abc",
                    }),
                )

        assert invalid_resp.status_code == 400
        invalid_payload = await invalid_resp.get_json()
        assert invalid_payload["code"] == "CLIENT_TELEMETRY_INVALID"
        assert blocked_origin_resp.status_code == 403
        assert "Access-Control-Allow-Origin" not in blocked_origin_resp.headers

    @pytest.mark.asyncio
    async def test_admin_write_and_pending_routes_stay_bearer_only(self):
        mock_gastos = MagicMock()
        mock_gastos.insert.return_value.execute.return_value = MagicMock(data=[{
            "id": "tx-1",
            "data": "2026-03-19",
            "valor": 10.5,
            "natureza": "Essencial",
            "categoria": "Mercado",
            "descricao": "Compra",
            "metodo_pagamento": "Pix",
            "conta": "Nubank",
        }])
        mock_gastos.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "tx-1"}])
        mock_gastos.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "tx-1", "descricao": "Atualizado"}])
        mock_gastos.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        mock_cache = MagicMock()
        mock_cache.select.return_value.order.return_value.execute.return_value = MagicMock(data=[{
            "id": "cache-1",
            "kind": "receipt_batch",
            "created_at": "2026-04-03T10:00:00",
            "expires_at": "2099-04-03T10:00:00",
            "preview_json": {"summary": "Cupom pendente"},
            "payload": {},
        }])
        mock_cache.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
            "id": "cache-2",
            "kind": "receipt_batch",
            "expires_at": "2099-04-03T23:59:59",
            "payload": {
                "metodo_pagamento": "Pix",
                "conta": "Nubank",
                "itens": [{"nome": "Cafe", "valor_bruto": 12, "desconto_item": 0}],
            },
            "payload_ciphertext": None,
        }])
        mock_cache.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_audit = MagicMock()
        mock_audit.insert.return_value.execute.return_value = MagicMock()

        def table_switch(name):
            if name == "gastos":
                return mock_gastos
            if name == "cache_aprovacao":
                return mock_cache
            if name == "auditoria_admin":
                return mock_audit
            return MagicMock()

        async with main.app.test_client() as client:
            with self._authorized_admin() as headers, \
                 patch.object(admin_transactions, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))), \
                 patch.object(admin_approvals, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))), \
                 patch.object(security, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))):
                create_resp = await client.post(
                    "/api/admin/gastos",
                    headers=headers,
                    json={
                        "data": "2026-03-19",
                        "valor": 10.5,
                        "categoria": "Mercado",
                        "descricao": "Compra",
                        "metodo_pagamento": "Pix",
                        "conta": "Nubank",
                    },
                )
                update_resp = await client.patch(
                    "/api/admin/gastos/tx-1",
                    headers=headers,
                    json={
                        "data": "2026-03-19",
                        "valor": 10.5,
                        "categoria": "Mercado",
                        "descricao": "Atualizado",
                        "metodo_pagamento": "Pix",
                        "conta": "Nubank",
                    },
                )
                delete_resp = await client.delete("/api/admin/gastos/tx-1", headers=headers)
                pending_resp = await client.get("/api/admin/cache-aprovacao", headers=headers)
                approve_resp = await client.post("/api/admin/cache-aprovacao/cache-2/approve", headers=headers)
                reject_resp = await client.post("/api/admin/cache-aprovacao/cache-2/reject", headers=headers)

        assert create_resp.status_code == 201
        assert update_resp.status_code == 200
        assert delete_resp.status_code == 200
        assert pending_resp.status_code == 200
        assert approve_resp.status_code == 200
        assert reject_resp.status_code == 200


class TestAdminValidationCoverage:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload, expected_message",
        [
            (
                {
                    "data": "2026-03-19",
                    "valor": 9.9,
                    "categoria": "Mercado",
                    "descricao": "Compra",
                    "metodo_pagamento": "Pix",
                    "conta": "Nubank",
                    "extra": "field",
                },
                "Unexpected transaction fields provided.",
            ),
            (
                {
                    "data": "03/19/2026",
                    "valor": 9.9,
                    "categoria": "Mercado",
                    "descricao": "Compra",
                    "metodo_pagamento": "Pix",
                    "conta": "Nubank",
                },
                "Transaction date must be in YYYY-MM-DD format.",
            ),
        ],
    )
    async def test_normalize_transaction_payload_rejects_invalid_inputs(self, payload, expected_message):
        auth_response = MagicMock()
        auth_response.user = {"id": "user-1", "email": "admin@example.com"}

        async with main.app.test_client() as client:
            with patch.object(admin_auth, "_lookup_admin_user", return_value={"user_id": "user-1", "email": "admin@example.com"}), \
                 patch.object(admin_auth, "ADMIN_EMAILS", frozenset({"admin@example.com"})), \
                 patch.object(admin_auth, "ADMIN_USER_IDS", frozenset({"user-1"})), \
                 patch.object(admin_auth, "auth_test_mode_enabled", return_value=False), \
                 patch.object(admin_transactions, "auth_test_seeded_mode_enabled", return_value=False), \
                 patch.object(admin_auth.supabase.auth, "get_user", MagicMock(return_value=auth_response)):
                resp = await client.post(
                    "/api/admin/gastos",
                    headers={"Authorization": "Bearer header.payload.signature"},
                    json=payload,
                )

        assert resp.status_code == 400
        assert (await resp.get_json())["message"] == expected_message

    @pytest.mark.asyncio
    async def test_listar_cache_admin_builds_preview_from_legacy_delete_payload(self):
        auth_response = MagicMock()
        auth_response.user = {"id": "user-1", "email": "admin@example.com"}

        mock_cache = MagicMock()
        mock_cache.select.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "DEL-1",
                "kind": None,
                "created_at": "2026-04-03T10:00:00",
                "expires_at": "2099-04-03T10:00:00",
                "preview_json": None,
                "payload": {"ids": ["1", "2"]},
            }]
        )

        def table_switch(name):
            if name == "cache_aprovacao":
                return mock_cache
            return MagicMock()

        async with main.app.test_client() as client:
            with patch.object(admin_auth, "_lookup_admin_user", return_value={"user_id": "user-1", "email": "admin@example.com"}), \
                 patch.object(admin_auth, "ADMIN_EMAILS", frozenset({"admin@example.com"})), \
                 patch.object(admin_auth, "ADMIN_USER_IDS", frozenset({"user-1"})), \
                 patch.object(admin_auth, "auth_test_mode_enabled", return_value=False), \
                 patch.object(admin_auth.supabase.auth, "get_user", MagicMock(return_value=auth_response)), \
                 patch.object(admin_approvals, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))):
                response = await client.get("/api/admin/cache-aprovacao", headers={"Authorization": "Bearer header.payload.signature"})

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["items"][0]["kind"] == "delete_confirmation"
        assert payload["items"][0]["preview"]["records_count"] == 2


class TestObservabilityCoverage:
    def test_observability_validation_helpers_cover_optional_and_invalid_inputs(self):
        assert observability_routes._validate_safe_token(None, field_name="event") is None
        with pytest.raises(ValueError, match="missing_event"):
            observability_routes._validate_safe_token(None, field_name="event", required=True)
        with pytest.raises(ValueError, match="invalid_event"):
            observability_routes._validate_safe_token("bad value with spaces", field_name="event", required=True)

        assert observability_routes._validate_page_path(None) is None
        with pytest.raises(ValueError, match="invalid_page_path"):
            observability_routes._validate_page_path("/financemgmtbot/auth/callback?token=secret")

        assert observability_routes._validate_api_origin(None) is None
        with pytest.raises(ValueError, match="invalid_api_origin"):
            observability_routes._validate_api_origin("nota-url")

        assert observability_routes._validate_http_status(None) is None
        with pytest.raises(ValueError, match="invalid_http_status"):
            observability_routes._validate_http_status(True)
        with pytest.raises(ValueError, match="invalid_http_status"):
            observability_routes._validate_http_status("oops")
        with pytest.raises(ValueError, match="invalid_http_status"):
            observability_routes._validate_http_status(700)

        assert observability_routes._validate_boolean(None, field_name="online") is None
        assert observability_routes._validate_boolean(True, field_name="online") is True
        with pytest.raises(ValueError, match="invalid_online"):
            observability_routes._validate_boolean("yes", field_name="online")

    def test_normalize_client_telemetry_payload_rejects_unexpected_fields(self):
        with pytest.raises(ValueError, match="unexpected_fields"):
            observability_routes._normalize_client_telemetry_payload({
                "event": "auth_callback_failed",
                "phase": "callback_admin_validation",
                "clientEventId": "cli_123456789abc",
                "extra": "field",
            })

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "data, expected_detail",
        [
            ("", "missing_payload"),
            ("{", "invalid_json"),
            ("[]", "invalid_payload"),
            ("x" * 5000, "payload_too_large"),
        ],
    )
    async def test_client_telemetry_invalid_payload_branches_return_short_details(self, data, expected_detail):
        async with main.app.test_client() as client:
            with patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://frengol.github.io"})):
                resp = await client.post(
                    "/api/client-telemetry",
                    headers={
                        "Origin": "https://frengol.github.io",
                        "Content-Type": "text/plain;charset=UTF-8",
                    },
                    data=data,
                )

        assert resp.status_code == 400
        payload = await resp.get_json()
        assert payload["detail"] == expected_detail

    @pytest.mark.asyncio
    async def test_observability_options_and_rate_limit_branches(self):
        async with main.app.test_client() as client:
            with patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://frengol.github.io"})), \
                 patch.object(
                     observability_routes,
                     "rate_limited",
                     side_effect=lambda *args, **kwargs: ("rate_limited", 429),
                 ):
                runtime_options = await client.options(
                    "/api/meta/runtime",
                    headers={"Origin": "https://frengol.github.io"},
                )
                telemetry_options = await client.options(
                    "/api/client-telemetry",
                    headers={"Origin": "https://frengol.github.io"},
                )
                rate_limited_resp = await client.post(
                    "/api/client-telemetry",
                    headers={
                        "Origin": "https://frengol.github.io",
                        "Content-Type": "text/plain;charset=UTF-8",
                    },
                    data=json.dumps({
                        "event": "auth_callback_failed",
                        "phase": "callback_admin_validation",
                        "clientEventId": "cli_123456789abc",
                    }),
                )

        assert runtime_options.status_code == 204
        assert telemetry_options.status_code == 204
        assert rate_limited_resp.status_code == 429
        assert await rate_limited_resp.get_data(as_text=True) == "rate_limited"
