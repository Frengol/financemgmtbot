from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from quart import Quart, Response

import main
from admin_runtime.common import _extract_user_fields
from web_app import auth_test_support_routes, http as web_http, webhook_routes


class TestMainHelperCoverage:
    def test_extract_user_fields_supports_multiple_shapes(self):
        assert _extract_user_fields(None) == (None, None)
        assert _extract_user_fields({"id": "user-1", "email": "admin@example.com"}) == ("user-1", "admin@example.com")
        assert _extract_user_fields(SimpleNamespace(id="user-2", email="admin2@example.com")) == ("user-2", "admin2@example.com")
        assert _extract_user_fields(SimpleNamespace(user=SimpleNamespace(id="user-3", email="nested@example.com"))) == ("user-3", "nested@example.com")

    @pytest.mark.asyncio
    async def test_http_helpers_cover_forwarded_loopback_and_redirect_sanitization(self):
        async with main.app.test_request_context("/api/admin/me", headers={"Forwarded": 'for=1.1.1.1;proto="https"', "Origin": "http://localhost:5173"}):
            assert web_http.browser_cors_enabled() is True
            with patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"http://localhost:5173"})):
                assert web_http.origin_allowed("http://localhost:5173") is True
            assert web_http.request_effective_scheme() == "https"
            assert web_http.request_is_effectively_secure() is True

        async with main.app.test_request_context("/api/admin/me", headers={"Forwarded": 'for=1.1.1.1;proto=""', "X-Forwarded-Proto": "https"}):
            assert web_http.request_effective_scheme() == "https"

        async with main.app.test_request_context("/api/admin/me", headers={"Forwarded": 'for=1.1.1.1;host="admin.example.com"'}):
            assert web_http.request_effective_scheme() == "http"

        async with main.app.test_request_context("/plain", headers={"X-Forwarded-Proto": "https,http"}):
            assert web_http.browser_cors_enabled() is False
            assert web_http.request_effective_scheme() == "https"

        async with main.app.test_request_context("/__test__/auth/reset"):
            with patch.object(web_http, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"):
                assert web_http.default_frontend_auth_callback_url() == "https://admin.example.com/app/auth/callback"
                assert web_http.sanitize_frontend_redirect_target("") == "https://admin.example.com/app/auth/callback"
                assert web_http.sanitize_frontend_redirect_target("https://admin.example.com/app/historico") == "https://admin.example.com/app/historico"
                assert web_http.sanitize_frontend_redirect_target("https://evil.example.com") == "https://admin.example.com/app/auth/callback"
                assert web_http.sanitize_frontend_redirect_target("javascript:alert('x')") == "https://admin.example.com/app/auth/callback"

            with patch.object(web_http, "FRONTEND_PUBLIC_URL", ""), patch.object(web_http, "is_loopback_request", return_value=True):
                assert web_http.default_frontend_public_url() == "http://localhost:5173/"
                assert web_http.sanitize_frontend_redirect_target("http://localhost:3000/auth/callback") == "http://localhost:3000/auth/callback"

        async with main.app.test_request_context("http://127.0.0.1/plain"):
            assert web_http.is_loopback_request() is True
            assert web_http.request_effective_scheme() == "http"

        async with main.app.test_request_context("/plain"):
            with patch.object(web_http, "FRONTEND_PUBLIC_URL", ""), patch.object(web_http, "is_loopback_request", return_value=False):
                with pytest.raises(RuntimeError):
                    web_http.default_frontend_public_url()

    @pytest.mark.asyncio
    async def test_main_runtime_helpers_cover_startup_shutdown_harden_response_and_rate_limit(self):
        init_http_client = AsyncMock()
        close_http_client = AsyncMock()
        with patch.object(main, "init_http_client", init_http_client), patch.object(main, "close_http_client", close_http_client):
            await main.startup()
            await main.shutdown()
        init_http_client.assert_awaited_once()
        close_http_client.assert_awaited_once()

        logged_events = []
        async with main.app.test_request_context(
            "/api/admin/gastos",
            headers={
                "Origin": "https://admin.example.com",
                "X-Client-Request-ID": "reqc_test_1",
            },
        ):
            with patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://admin.example.com"})), \
                 patch.object(web_http.logger, "info", side_effect=lambda payload: logged_events.append(payload)):
                response = await main.harden_response(Response("ok"))
            assert response.headers["Access-Control-Allow-Origin"] == "https://admin.example.com"
            assert response.headers["Access-Control-Allow-Headers"] == "Authorization, Content-Type, X-Client-Request-ID"
            assert response.headers["Access-Control-Expose-Headers"] == "X-Request-ID, X-Client-Request-ID"
            assert response.headers["Cache-Control"] == "no-store, private"
            assert response.headers["X-Client-Request-ID"] == "reqc_test_1"
            assert logged_events[-1]["event"] == "browser_admin_request_cors"
            assert logged_events[-1]["client_request_id"] == "reqc_test_1"
            assert logged_events[-1]["access_control_allow_origin_set"] is True

        async with main.app.test_request_context("/plain"):
            response = await main.harden_response(Response("ok"))
            assert "Access-Control-Allow-Origin" not in response.headers

        with patch.object(web_http, "allow_request", return_value=True):
            assert web_http.rate_limited("auth_callback", "127.0.0.1", limit=1, window_seconds=60) is None

        async with main.app.test_request_context("/api/admin/me"):
            with patch.object(web_http, "allow_request", return_value=False):
                limited_response = web_http.rate_limited("auth_callback", "127.0.0.1", limit=1, window_seconds=60)
            assert limited_response is not None
            assert limited_response.status_code == 429

    @pytest.mark.asyncio
    async def test_removed_legacy_auth_routes_and_test_support_registration_contract(self):
        async with main.app.test_client() as client:
            assert (await client.get("/auth/session")).status_code == 404
            assert (await client.post("/auth/logout")).status_code == 404
            assert (await client.get("/auth/callback")).status_code == 404
            assert (await client.post("/__test__/auth/reset")).status_code == 404
            assert (await client.get("/__test__/auth/magic-link?email=admin@example.com")).status_code == 404

        temp_app = Quart(__name__)
        auth_test_support_routes.register_test_support_routes(temp_app)

        async with temp_app.test_client() as client:
            with patch.object(auth_test_support_routes, "test_support_request_allowed", return_value=False):
                assert (await client.post("/__test__/auth/reset")).status_code == 404
                assert (await client.post("/__test__/auth/transactions", json={"transactions": []})).status_code == 404
                assert (await client.get("/__test__/auth/magic-link?email=admin@example.com")).status_code == 404
                assert (await client.get("/__test__/auth/verify?token_hash=missing")).status_code == 404
                assert (await client.options("/__test__/auth/magic-link")).status_code == 204

            with patch.object(auth_test_support_routes, "test_support_request_allowed", return_value=True):
                invalid_transactions = await client.post("/__test__/auth/transactions", json={"transactions": {"bad": "payload"}})
                assert invalid_transactions.status_code == 400

                missing_link = await client.get("/__test__/auth/magic-link?email=missing@example.com")
                assert missing_link.status_code == 404

                missing_email = await client.post("/__test__/auth/magic-link", json={})
                assert missing_email.status_code == 400

                invalid_magic_link_payload = await client.post("/__test__/auth/magic-link", json=[{"email": "admin@example.com"}])
                assert invalid_magic_link_payload.status_code == 400

                created_link = await client.post("/__test__/auth/magic-link", json={"email": "admin@example.com"})
                assert created_link.status_code == 200

                peeked_link = await client.get("/__test__/auth/magic-link?email=admin@example.com")
                assert peeked_link.status_code == 200

                assert (await client.options("/__test__/auth/reset")).status_code == 204
                assert (await client.options("/__test__/auth/transactions")).status_code == 204
                assert (await client.options("/__test__/auth/verify")).status_code == 204

    @pytest.mark.asyncio
    async def test_test_support_routes_cover_error_paths_and_success_branches(self):
        temp_app = Quart(__name__)
        auth_test_support_routes.register_test_support_routes(temp_app)

        async with temp_app.test_client() as client:
            with patch.object(auth_test_support_routes, "test_support_request_allowed", return_value=True):
                seeded = await client.post("/__test__/auth/transactions", json={"transactions": [{"id": "tx-1", "data": "2026-04-01"}]})
                assert seeded.status_code == 200

                verify_expired = await client.get("/__test__/auth/verify?redirect_to=https://admin.example.com/app/auth/callback&token_hash=missing")
                assert verify_expired.status_code == 302
                assert "otp_expired" in verify_expired.headers["Location"]

                with patch.object(auth_test_support_routes, "sanitize_frontend_redirect_target", side_effect=RuntimeError("bad redirect")):
                    magic_link_error = await client.post("/__test__/auth/magic-link", json={"email": "admin@example.com"})
                    assert magic_link_error.status_code == 500
                    assert (await magic_link_error.get_json())["code"] == "AUTH_CONFIGURATION_INVALID"

                reset_resp = await client.post("/__test__/auth/reset")
                assert reset_resp.status_code == 200

                link_resp = await client.post("/__test__/auth/magic-link", json={"email": "admin@example.com", "userId": "user-1", "redirectTo": "https://admin.example.com/app/auth/callback"})
                assert link_resp.status_code == 200
                link_payload = await link_resp.get_json()
                assert link_payload["magicLink"]["user_id"] == "user-1"
                assert "token_hash=" in link_payload["magicLink"]["link"]

            with patch.object(web_http, "auth_test_mode_enabled", return_value=False):
                async with temp_app.test_request_context("/__test__/auth/reset"):
                    assert web_http.test_support_request_allowed() is False
            with patch.object(web_http, "auth_test_mode_enabled", return_value=True):
                async with temp_app.test_request_context("/__test__/auth/reset"):
                    current_request = web_http.request._get_current_object()
                    current_request.remote_addr = "127.0.0.1"
                    assert web_http.test_support_request_allowed() is True

    @pytest.mark.asyncio
    async def test_admin_preflight_and_webhook_rate_limit_still_work(self):
        async with main.app.test_client() as client:
            admin_me_options = await client.options("/api/admin/me")
            gastos_options = await client.options("/api/admin/gastos")
            cache_options = await client.options("/api/admin/cache-aprovacao")
            approve_options = await client.options("/api/admin/cache-aprovacao/cache-1/approve")
            reject_options = await client.options("/api/admin/cache-aprovacao/cache-1/reject")

            assert admin_me_options.status_code == 204
            assert gastos_options.status_code == 204
            assert cache_options.status_code == 204
            assert approve_options.status_code == 204
            assert reject_options.status_code == 204

            webhook_limited = lambda *args, **kwargs: web_http._json_error("Too many webhook requests.", 429, code="RATE_LIMITED")
            with patch.object(webhook_routes, "rate_limited", side_effect=webhook_limited):
                webhook_resp = await client.post("/", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": webhook_routes.SECRET_TOKEN})
                assert webhook_resp.status_code == 429
