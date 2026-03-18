import os
import logging
import traceback
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

REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_SECRET_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"]
for var in REQUIRED_VARS:
    if not os.environ.get(var):
        logger.critical({"event": "startup_failed", "reason": f"Missing variable {var}"})
        raise RuntimeError(f"AppSec Fatal Error: Variável de ambiente {var} não configurada.")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

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
