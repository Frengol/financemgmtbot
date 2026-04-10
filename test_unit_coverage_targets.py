import os
from unittest.mock import MagicMock, patch

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

import admin_runtime  # noqa: F401
import handlers  # noqa: F401
import main  # noqa: F401
import security  # noqa: F401
from _test_unit_admin_coverage_cases import TestAdminApiHelperCoverage
from _test_unit_main_coverage_cases import TestMainHelperCoverage
