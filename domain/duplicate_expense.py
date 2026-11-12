"""Deterministic rules for the repeated-expense warning (no IO)."""

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from domain.finance import build_installment_records

DUPLICATE_EXPENSE_KIND = "duplicate_expense"
DUPLICATE_DECISIONS = ("save", "skip", "expired")
SKIP_ACTION = "dupskip"
SAVE_ACTION = "dupsave"
GENERIC_TEXT_KEYS = frozenset({"", "nao informada", "sem descricao"})

DUPLICATE_PROMPT = "Este gasto já está registrado. É outro gasto?"
DUPLICATE_SKIPPED_MESSAGE = "Gasto não salvo. O registro anterior foi mantido."
DUPLICATE_EXPIRED_MESSAGE = (
    "Confirmação expirada. Nenhum novo gasto foi salvo; envie o gasto novamente se necessário."
)
DUPLICATE_INVALID_MESSAGE = (
    "Não foi possível processar esta confirmação. Envie o gasto novamente se necessário."
)

_TRANSACTION_TEXT_FIELDS = ("categoria", "descricao", "metodo_pagamento", "conta")
_MATCHED_FIELDS = ("id", "data", "valor", "conta", "descricao")


@dataclass(frozen=True)
class DuplicateCandidate:
    transaction: dict[str, Any]
    record: dict[str, Any]
    key: tuple[str, int, str, str]


@dataclass(frozen=True)
class DuplicatePayload:
    transaction: dict[str, Any]
    matched_record: dict[str, Any]


def normalize_match_text(value: Any) -> str:
    """Casefold, strip accents, trim and collapse spaces; punctuation is kept.

    NFD (not NFKD) so only combining marks go away: fullwidth letters, ligatures and
    similar compatibility characters stay distinct, as the rule allows accents only.
    """
    if not isinstance(value, str):
        return ""
    decomposed = unicodedata.normalize("NFD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_marks.split())


def amount_cents(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _date_key(value: Any) -> str | None:
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def build_match_key(date: Any, value: Any, account: Any, description: Any):
    day = _date_key(date)
    cents = amount_cents(value)
    account_key = normalize_match_text(account)
    description_key = normalize_match_text(description)
    if day is None or cents is None or cents <= 0:
        return None
    if account_key in GENERIC_TEXT_KEYS or description_key in GENERIC_TEXT_KEYS:
        return None
    return day, cents, account_key, description_key


def prepare_duplicate_candidate(dados_reg: Any, *, fallback_date: datetime) -> DuplicateCandidate | None:
    """Freeze a single positive expense, or return None when the check does not apply."""
    if not isinstance(dados_reg, dict) or not dados_reg:
        return None
    records = build_installment_records(dados_reg, fallback_date=fallback_date)
    if len(records) != 1:
        return None
    record = records[0]
    if record["natureza"] == "Receita":
        return None
    key = build_match_key(record["data"], record["valor"], record["conta"], record["descricao"])
    if key is None:
        return None
    transaction = {**dados_reg, "data": record["data"], "valor_total": record["valor"], "parcelas": 1}
    return DuplicateCandidate(transaction=transaction, record=record, key=key)


def _id_sort_key(row: dict[str, Any]):
    row_id = row.get("id")
    if isinstance(row_id, int) and not isinstance(row_id, bool):
        return (0, row_id, "")
    return (1, 0, str(row_id))


def pick_first_match(candidate: DuplicateCandidate, rows: Any) -> dict[str, Any] | None:
    """Return the persisted expense with the lowest id that matches the candidate key."""
    matches = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("natureza") == "Receita":
            continue
        key = build_match_key(row.get("data"), row.get("valor"), row.get("conta"), row.get("descricao"))
        if key == candidate.key:
            matches.append(row)
    return min(matches, key=_id_sort_key) if matches else None


def snapshot_matched_record(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in _MATCHED_FIELDS}


def parse_duplicate_payload(payload: Any) -> DuplicatePayload | None:
    """Validate a decrypted duplicate payload; None means fail closed."""
    if not isinstance(payload, dict):
        return None
    transaction = payload.get("transaction")
    matched = payload.get("matched_record")
    if not isinstance(transaction, dict) or not isinstance(matched, dict):
        return None
    if not _valid_date(transaction.get("data")):
        return None
    cents = amount_cents(transaction.get("valor_total"))
    if cents is None or cents <= 0 or transaction.get("parcelas") != 1:
        return None
    if not all(isinstance(transaction.get(field), str) for field in _TRANSACTION_TEXT_FIELDS):
        return None
    if matched.get("id") is None or any(matched.get(field) is None for field in _MATCHED_FIELDS):
        return None
    return DuplicatePayload(transaction=transaction, matched_record=matched)


def escape_markdown(value: Any) -> str:
    text = str(value if value is not None else "")
    for char in ("\\", "_", "*", "`", "["):
        text = text.replace(char, f"\\{char}")
    return text


def _describe(date: Any, value: Any, account: Any, description: Any) -> str:
    try:
        amount = f"R$ {float(value):,.2f}"
    except (TypeError, ValueError):
        amount = "R$ ?"
    return (
        f"🗓️ {escape_markdown(date)} | 💰 {amount}\n"
        f"🏦 {escape_markdown(account)}\n"
        f"📝 {escape_markdown(description)}"
    )


def format_duplicate_confirmation(payload: DuplicatePayload) -> str:
    previous = payload.matched_record
    proposed = payload.transaction
    return (
        "⚠️ **Possível gasto repetido**\n\n"
        "**Anterior**\n"
        f"{_describe(previous['data'], previous['valor'], previous['conta'], previous['descricao'])}\n\n"
        "**Proposto**\n"
        f"{_describe(proposed['data'], proposed['valor_total'], proposed['conta'], proposed['descricao'])}\n\n"
        f"{DUPLICATE_PROMPT}"
    )


def duplicate_keyboard(cache_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "Já registrei — não salvar", "callback_data": f"{SKIP_ACTION}_{cache_id}"}],
            [{"text": "É outro — salvar", "callback_data": f"{SAVE_ACTION}_{cache_id}"}],
        ]
    }


def format_saved_expense(record: dict[str, Any]) -> str:
    return (
        f"✅ **Salvo!**\n💰 R$ {float(record['valor']):,.2f} | 📊 {escape_markdown(record['natureza'])}\n"
        f"📂 Categoria: {escape_markdown(record['categoria'])}\n"
        f"🗓️ Data: {escape_markdown(record['data'])}\n"
        f"🏦 {escape_markdown(record['conta'])} ({escape_markdown(record['metodo_pagamento'])})\n"
        f"📝 {escape_markdown(record['descricao'])}"
    )
