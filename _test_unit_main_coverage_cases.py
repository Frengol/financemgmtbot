from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

import main
from web_app import auth_compat, http as web_http, webhook_routes


class TestMainHelperCoverage:
    def test_extract_user_fields_supports_multiple_shapes(self):
        assert main._extract_user_fields(None) == (None, None)
        assert main._extract_user_fields({"id": "user-1", "email": "admin@example.com"}) == ("user-1", "admin@example.com")
        assert main._extract_user_fields(SimpleNamespace(id="user-2", email="admin2@example.com")) == ("user-2", "admin2@example.com")
        assert main._extract_user_fields(SimpleNamespace(user=SimpleNamespace(id="user-3", email="nested@example.com"))) == ("user-3", "nested@example.com")

    @pytest.mark.asyncio
    async def test_request_scheme_and_public_url_helpers_cover_forwarded_and_loopback_branches(self):
        async with main.app.test_request_context("/auth/callback", headers={"Forwarded": 'for=1.1.1.1;proto="https"'}):
            assert main._browser_cors_enabled() is True
            with patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"http://localhost:5173"})):
                assert main._origin_allowed("http://localhost:5173") is True
            assert main._request_effective_scheme() == "https"
            assert main._request_is_effectively_secure() is True

        async with main.app.test_request_context("/auth/callback", headers={"X-Forwarded-Proto": "https,http"}):
            assert main._request_effective_scheme() == "https"

        async with main.app.test_request_context("/plain"):
            assert main._browser_cors_enabled() is False
            with patch.object(web_http, "FRONTEND_PUBLIC_URL", ""), patch.object(web_http, "is_loopback_request", return_value=True):
                assert main._default_frontend_public_url() == "http://localhost:5173/"
                assert main._default_frontend_auth_callback_url().endswith("/auth/callback")

    @pytest.mark.asyncio
    async def test_redirect_sanitization_and_test_support_helpers_cover_invalid_and_loopback_paths(self):
        async with main.app.test_request_context("/auth/callback"):
            with patch.object(web_http, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"):
                assert main._sanitize_frontend_redirect_target("") == "https://admin.example.com/app/auth/callback"
                assert main._sanitize_frontend_redirect_target("https://admin.example.com/app/historico") == "https://admin.example.com/app/historico"
                assert main._sanitize_frontend_redirect_target("https://evil.example.com") == "https://admin.example.com/app/auth/callback"
                assert main._sanitize_frontend_app_redirect_target("") == "https://admin.example.com/app/"
                assert main._sanitize_frontend_app_redirect_target("https://evil.example.com") == "https://admin.example.com/app/"
                assert main._build_callback_url("https://admin.example.com/app/auth/callback", mode="canonical") == "https://admin.example.com/app/auth/callback"

            with patch.object(web_http, "FRONTEND_PUBLIC_URL", ""), patch.object(web_http, "is_loopback_request", return_value=True):
                assert main._sanitize_frontend_redirect_target("http://localhost:3000/app") == "http://localhost:3000/app"

        async with main.app.test_request_context("/__test__/auth/reset"):
            with patch.object(web_http, "auth_test_mode_enabled", return_value=False):
                assert main._test_support_request_allowed() is False
            with patch.object(web_http, "auth_test_mode_enabled", return_value=True), patch.object(main.request, "remote_addr", "127.0.0.1"):
                assert main._test_support_request_allowed() is True

    @pytest.mark.asyncio
    async def test_main_helper_branches_cover_runtime_errors_allowed_identities_and_loopback_overrides(self):
        async with main.app.test_request_context("/auth/callback", headers={"Forwarded": 'for=1.1.1.1;proto=""', "X-Forwarded-Proto": "https"}):
            assert main._request_effective_scheme() == "https"

        async with main.app.test_request_context("/auth/callback"):
            with patch.object(web_http, "FRONTEND_PUBLIC_URL", ""), patch.object(web_http, "is_loopback_request", return_value=False):
                with pytest.raises(RuntimeError):
                    main._default_frontend_public_url()

            with patch.object(web_http, "FRONTEND_PUBLIC_URL", ""), patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://preview.example.com"})), patch.object(web_http, "is_loopback_request", return_value=True):
                assert main._sanitize_frontend_app_redirect_target("http://localhost:3000/app") == "http://localhost:3000/app"

            assert main._build_login_redirect_target("https://admin.example.com/app/") == "https://admin.example.com/app/login"
            assert main._build_login_redirect_target("https://admin.example.com/app/", reason="expired", request_id="req_123") == "https://admin.example.com/app/login?reason=expired&requestId=req_123"

    @pytest.mark.asyncio
    async def test_main_runtime_helpers_cover_startup_shutdown_and_harden_response(self):
        init_http_client = AsyncMock()
        close_http_client = AsyncMock()
        with patch.object(main, "init_http_client", init_http_client), patch.object(main, "close_http_client", close_http_client):
            await main.startup()
            await main.shutdown()
        init_http_client.assert_awaited_once()
        close_http_client.assert_awaited_once()

        async with main.app.test_request_context("/api/admin/gastos", headers={"Origin": "https://admin.example.com"}):
            with patch.object(web_http, "FRONTEND_ALLOWED_ORIGINS", frozenset({"https://admin.example.com"})):
                response = await main.harden_response(main.Response("ok"))
            assert response.headers["Access-Control-Allow-Origin"] == "https://admin.example.com"
            assert response.headers["Access-Control-Allow-Headers"] == "Authorization, Content-Type"
            assert response.headers["Cache-Control"] == "no-store, private"

        async with main.app.test_request_context("/plain"):
            response = await main.harden_response(main.Response("ok"))
            assert "Access-Control-Allow-Origin" not in response.headers

    @pytest.mark.asyncio
    async def test_removed_legacy_auth_routes_and_test_support_cover_error_paths(self):
        async with main.app.test_client() as client:
            assert (await client.get("/auth/session")).status_code == 404
            assert (await client.post("/auth/logout")).status_code == 404

            with patch.object(auth_compat, "test_support_request_allowed", return_value=False):
                assert (await client.post("/__test__/auth/reset")).status_code == 404
                assert (await client.post("/__test__/auth/transactions", json={"transactions": []})).status_code == 404
                assert (await client.get("/__test__/auth/magic-link?email=admin@example.com")).status_code == 404
                assert (await client.options("/__test__/auth/magic-link")).status_code == 204

            with patch.object(auth_compat, "test_support_request_allowed", return_value=True):
                invalid_transactions = await client.post("/__test__/auth/transactions", json={"transactions": {"bad": "payload"}})
                assert invalid_transactions.status_code == 400

                missing_link = await client.get("/__test__/auth/magic-link?email=missing@example.com")
                assert missing_link.status_code == 404

                created_link = await client.post("/__test__/auth/magic-link", json={"email": "admin@example.com"})
                assert created_link.status_code == 200

                peeked_link = await client.get("/__test__/auth/magic-link?email=admin@example.com")
                assert peeked_link.status_code == 200

                assert (await client.options("/__test__/auth/reset")).status_code == 204
                assert (await client.options("/__test__/auth/transactions")).status_code == 204
                assert (await client.options("/__test__/auth/verify")).status_code == 204

            with patch.object(auth_compat, "test_support_request_allowed", return_value=False):
                verify_disabled = await client.get("/__test__/auth/verify?token_hash=missing")
                assert verify_disabled.status_code == 404

    @pytest.mark.asyncio
    async def test_main_routes_cover_rate_limits_and_test_support_paths(self):
        async with main.app.test_client() as client:
            callback_limited = lambda *args, **kwargs: main._json_error("Slow down.", 429, code="RATE_LIMITED")
            with patch.object(auth_compat, "rate_limited", side_effect=callback_limited):
                callback_resp = await client.get("/auth/callback")
                assert callback_resp.status_code == 429

            with patch.object(web_http, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"), patch.object(auth_compat, "build_frontend_callback_relay_target", side_effect=RuntimeError("missing frontend")):
                relay_error = await client.get("/auth/callback")
                assert relay_error.status_code == 500
                assert (await relay_error.get_json())["code"] == "AUTH_CONFIGURATION_INVALID"

            with patch.object(web_http, "allow_request", return_value=True):
                assert main._rate_limited("auth_callback", "127.0.0.1", limit=1, window_seconds=60) is None

            with patch.object(auth_compat, "test_support_request_allowed", return_value=True):
                seeded = await client.post("/__test__/auth/transactions", json={"transactions": [{"id": "tx-1", "data": "2026-04-01"}]})
                assert seeded.status_code == 200

                verify_expired = await client.get("/__test__/auth/verify?redirect_to=https://admin.example.com/app/auth/callback&token_hash=missing")
                assert verify_expired.status_code == 302
                assert "otp_expired" in verify_expired.headers["Location"]

                with patch.object(auth_compat, "sanitize_frontend_redirect_target", side_effect=RuntimeError("bad redirect")):
                    magic_link_error = await client.post("/__test__/auth/magic-link", json={"email": "admin@example.com"})
                    assert magic_link_error.status_code == 500
                    assert (await magic_link_error.get_json())["code"] == "AUTH_CONFIGURATION_INVALID"

            webhook_limited = lambda *args, **kwargs: main._json_error("Too many webhook requests.", 429, code="RATE_LIMITED")
            with patch.object(webhook_routes, "rate_limited", side_effect=webhook_limited):
                webhook_resp = await client.post("/", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": webhook_routes.SECRET_TOKEN})
                assert webhook_resp.status_code == 429

    @pytest.mark.asyncio
    async def test_auth_routes_cover_fragment_bridge_invalid_callbacks_and_options(self):
        async with main.app.test_client() as client:
            with patch.object(web_http, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"):
                fragment_resp = await client.get("/auth/callback")
                assert fragment_resp.status_code == 200
                fragment_html = await fragment_resp.get_data(as_text=True)
                assert "Finalizing secure sign-in" in fragment_html
                assert "fetch(" not in fragment_html

                relay_resp = await client.get("/auth/callback?next=https://admin.example.com/app/")
                assert relay_resp.status_code == 302
                relay_target = urlparse(relay_resp.headers["Location"])
                assert relay_target.path == "/app/auth/callback"
                assert parse_qs(relay_target.query) == {"next": ["https://admin.example.com/app/"]}

                invalid_post = await client.post("/auth/callback", json={"redirectTo": "https://admin.example.com/app/"})
                assert invalid_post.status_code == 405

                options_resp = await client.options("/auth/callback")
                assert options_resp.status_code == 204

                admin_me_options = await client.options("/api/admin/me")
                assert admin_me_options.status_code == 204

                gastos_options = await client.options("/api/admin/gastos")
                assert gastos_options.status_code == 204

                cache_options = await client.options("/api/admin/cache-aprovacao")
                assert cache_options.status_code == 204

                approve_options = await client.options("/api/admin/cache-aprovacao/cache-1/approve")
                assert approve_options.status_code == 204

                reject_options = await client.options("/api/admin/cache-aprovacao/cache-1/reject")
                assert reject_options.status_code == 204

    @pytest.mark.asyncio
    async def test_http_helpers_cover_scheme_loopback_and_same_origin_app_redirect(self):
        async with main.app.test_request_context("http://127.0.0.1/plain"):
            assert main._is_loopback_request() is True
            assert main._request_effective_scheme() == "http"

        async with main.app.test_request_context("/auth/callback"):
            with patch.object(web_http, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"):
                assert main._sanitize_frontend_app_redirect_target("https://admin.example.com/app/historico") == "https://admin.example.com/app/historico"

        async with main.app.test_request_context("/auth/callback"):
            with patch.object(web_http, "allow_request", return_value=False):
                limited_response = main._rate_limited("auth_callback", "127.0.0.1", limit=1, window_seconds=60)
            assert limited_response is not None
            assert limited_response.status_code == 429

    @pytest.mark.asyncio
    async def test_auth_callback_covers_relay_and_test_support_success_paths(self):
        async with main.app.test_client() as client:
            with patch.object(web_http, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"):
                relayed = await client.get("/auth/callback?token_hash=token-1&type=magiclink&next=https://admin.example.com/app/")
                assert relayed.status_code == 302
                relay_target = urlparse(relayed.headers["Location"])
                assert relay_target.path == "/app/auth/callback"
                assert parse_qs(relay_target.query) == {
                    "token_hash": ["token-1"],
                    "type": ["magiclink"],
                    "next": ["https://admin.example.com/app/"],
                }

            with patch.object(auth_compat, "test_support_request_allowed", return_value=True), patch.object(web_http, "FRONTEND_PUBLIC_URL", "https://admin.example.com/app/"):
                reset_resp = await client.post("/__test__/auth/reset")
                assert reset_resp.status_code == 200

                link_resp = await client.post("/__test__/auth/magic-link", json={"email": "admin@example.com", "userId": "user-1", "redirectTo": "https://admin.example.com/app/"})
                assert link_resp.status_code == 200
                link_payload = await link_resp.get_json()
                assert link_payload["magicLink"]["user_id"] == "user-1"
                assert "token_hash=" in link_payload["magicLink"]["link"]
