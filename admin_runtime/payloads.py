from datetime import datetime
from typing import Any
import unicodedata

from security import sanitize_plain_text
from utils import CATEGORIA_MAP, inferir_natureza

from .common import _json_error

ALLOWED_TRANSACTION_FIELDS = {
    "data",
    "valor",
    "categoria",
    "descricao",
    "metodo_pagamento",
    "conta",
    "natureza",
}


def _normalize_lookup(value: str):
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().lower()


def _normalize_transaction_payload(payload: dict[str, Any] | None):
    if not isinstance(payload, dict):
        return None, _json_error("Invalid transaction payload.", 400)

    extra_fields = sorted(set(payload.keys()) - ALLOWED_TRANSACTION_FIELDS)
    if extra_fields:
        return None, _json_error("Unexpected transaction fields provided.", 400)

    raw_date = str(payload.get("data") or "").strip()
    try:
        normalized_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None, _json_error("Transaction date must be in YYYY-MM-DD format.", 400)

    try:
        normalized_value = round(float(payload.get("valor")), 2)
    except (TypeError, ValueError):
        return None, _json_error("Transaction value must be numeric.", 400)

    if normalized_value < 0:
        return None, _json_error("Transaction value must be zero or positive.", 400)

    raw_description = sanitize_plain_text(payload.get("descricao"), 250)
    if not raw_description:
        return None, _json_error("Transaction description is required.", 400)

    raw_category = str(payload.get("categoria") or "").strip()
    category_lookup = _normalize_lookup(raw_category)
    category_aliases = {_normalize_lookup(category_key): category_key for category_key in CATEGORIA_MAP}
    canonical_category_key = category_aliases.get(category_lookup)
    if not canonical_category_key:
        return None, _json_error("Transaction category is invalid.", 400)

    normalized_nature, normalized_category = inferir_natureza(canonical_category_key)
    normalized_payment_method = sanitize_plain_text(payload.get("metodo_pagamento"), 120, "Outros") or "Outros"
    normalized_account = sanitize_plain_text(payload.get("conta"), 120, "Nao Informada") or "Nao Informada"

    return {
        "data": normalized_date,
        "valor": normalized_value,
        "natureza": normalized_nature,
        "categoria": normalized_category,
        "descricao": raw_description,
        "metodo_pagamento": normalized_payment_method,
        "conta": normalized_account,
    }, None
