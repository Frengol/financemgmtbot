import os
from pathlib import Path
from unittest.mock import patch

import pytest


if (os.environ.get("LIVE_DB_SMOKE") or "").strip().lower() != "true":
    pytest.skip("LIVE_DB_SMOKE not enabled.", allow_module_level=True)


env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


required_vars = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_SECRET_TOKEN",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
]
missing_vars = [var for var in required_vars if not os.environ.get(var)]
if missing_vars:
    pytest.skip(f"LIVE_DB_SMOKE missing required env vars: {', '.join(missing_vars)}", allow_module_level=True)


from admin_runtime import auth as admin_auth  # noqa: E402
import main  # noqa: E402


@pytest.mark.asyncio
async def test_live_db_smoke_reads_transactions_through_admin_route():
    async with main.app.test_client() as client:
        with patch.object(admin_auth, "ALLOW_LOCAL_DEV_AUTH", True):
            response = await client.get(
                "/api/admin/gastos?date_from=2000-01-01&date_to=2100-01-01",
                headers={"Origin": "http://127.0.0.1:5173"},
            )

    assert response.status_code == 200
    payload = await response.get_json()
    assert payload["status"] == "ok"
    assert isinstance(payload.get("transactions"), list)
