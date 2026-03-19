import os
import logging
import traceback
import sys
from pathlib import Path
from urllib.parse import urlsplit
from pythonjsonlogger import jsonlogger
from supabase import create_client, Client
from openai import AsyncOpenAI
from groq import AsyncGroq
import google.generativeai as genai

logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(message)s %(module)s')
logHandler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)


DEFAULT_FRONTEND_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def load_local_env():
    if "pytest" in sys.modules:
        return

    env_path = Path(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_local_env()


def normalize_frontend_origin(origin: str):
    normalized = (origin or "").strip()
    if not normalized:
        return ""

    parsed = urlsplit(normalized)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"

    return normalized.rstrip("/")


def parse_frontend_allowed_origins(raw_origins: str | None):
    source = raw_origins or ",".join(DEFAULT_FRONTEND_ALLOWED_ORIGINS)
    return frozenset(
        normalized
        for normalized in (normalize_frontend_origin(origin) for origin in source.split(","))
        if normalized
    )

REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_SECRET_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"]
for var in REQUIRED_VARS:
    if not os.environ.get(var):
        logger.critical({"event": "startup_failed", "reason": f"Missing variable {var}"})
        raise RuntimeError(f"AppSec Fatal Error: Variável de ambiente {var} não configurada.")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
ADMIN_EMAILS = frozenset(
    email.strip().lower()
    for email in (os.environ.get("SUPABASE_ADMIN_EMAILS") or "").split(",")
    if email.strip()
)
ADMIN_USER_IDS = frozenset(
    user_id.strip()
    for user_id in (os.environ.get("SUPABASE_ADMIN_USER_IDS") or "").split(",")
    if user_id.strip()
)
FRONTEND_ALLOWED_ORIGINS = parse_frontend_allowed_origins(os.environ.get("FRONTEND_ALLOWED_ORIGINS"))
ALLOW_LOCAL_DEV_AUTH = (os.environ.get("ALLOW_LOCAL_DEV_AUTH") or "").strip().lower() == "true"

def mascarar_segredos(texto):
    if not isinstance(texto, str): return texto
    for var_name in REQUIRED_VARS:
        val = os.environ.get(var_name)
        if val and len(val) > 4:
            texto = texto.replace(val, f"[MASKED_{var_name}]")
    return texto

try:
    supa_url = os.environ.get("SUPABASE_URL") or ""
    supa_key = os.environ.get("SUPABASE_KEY") or ""
    supabase: Client = create_client(supa_url, supa_key)
    groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY") or "")
    deepseek_client = AsyncOpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY") or "", base_url="https://api.deepseek.com")
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY") or "")
    logger.info({"event": "clients_initialized", "status": "success"})
except Exception:
    logger.critical({"event": "init_error", "error": mascarar_segredos(traceback.format_exc())})
    raise
