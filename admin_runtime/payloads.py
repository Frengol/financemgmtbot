from typing import Any

from domain.finance import (
    DomainValidationError,
    normalize_lookup,
    parse_month_date,
    normalize_recurring_expense_payload,
    normalize_transaction_payload,
)

from .common import _json_error


def _normalize_lookup(value: str):
    return normalize_lookup(value)


def _normalize_transaction_payload(payload: dict[str, Any] | None):
    try:
        return normalize_transaction_payload(payload), None
    except DomainValidationError as exc:
        return None, _json_error(str(exc), 400)


def _parse_month_date(raw: str | None, field_name: str):
    try:
        return parse_month_date(raw, field_name), None
    except DomainValidationError as exc:
        return None, _json_error(str(exc), 400)


def _normalize_recurring_expense_payload(payload: dict[str, Any] | None):
    try:
        return normalize_recurring_expense_payload(payload), None
    except DomainValidationError as exc:
        return None, _json_error(str(exc), 400)
