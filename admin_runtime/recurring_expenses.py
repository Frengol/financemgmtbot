from datetime import datetime
from typing import Any

from postgrest.exceptions import APIError

from api_responses import with_request_id
from config import TRANSACTIONS_TABLE, logger, mascarar_segredos, supabase
from domain.finance import build_recurring_transaction_for_reference, compute_recurring_transaction_date

from .audit import _build_field_summary, registrar_auditoria_admin
from .auth import autenticar_admin_request
from .common import _json_error, _json_success
from .payloads import _normalize_recurring_expense_payload

RECURRING_EXPENSES_TABLE = "despesas_recorrentes"
RECURRING_EXPENSE_SELECT_FIELDS = (
    "id,nome,valor,mes_inicio,mes_fim,dia_mes,natureza,categoria,"
    "metodo_pagamento,conta,ativo,created_at,updated_at"
)
RECURRING_EXPENSE_GENERATION_FIELDS = (
    "id,nome,valor,mes_inicio,mes_fim,dia_mes,natureza,categoria,"
    "metodo_pagamento,conta,ativo"
)


def _compute_gasto_date(year: int, month: int, day: int) -> str:
    return compute_recurring_transaction_date(year, month, day)


def _is_unique_violation(exc: APIError):
    return getattr(exc, "code", "") == "23505"


def listar_despesas_recorrentes():
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        query = supabase.table(RECURRING_EXPENSES_TABLE).select(RECURRING_EXPENSE_SELECT_FIELDS).order("nome", desc=False)
        response = query.execute()
        return _json_success({"items": getattr(response, "data", [])}, 200)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_list_recurring_expenses_failed", "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to load recurring expenses right now.", 503, code="ADMIN_DATA_LOAD_FAILED", retryable=True)
    except Exception as exc:
        logger.error(with_request_id({"event": "admin_list_recurring_expenses_unexpected", "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to load recurring expenses right now.", 503, code="ADMIN_DATA_LOAD_FAILED", retryable=True)


def criar_despesa_recorrente(payload: dict[str, Any] | None):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    payload, payload_error = _normalize_recurring_expense_payload(payload)
    if payload_error:
        return payload_error

    try:
        response = supabase.table(RECURRING_EXPENSES_TABLE).insert(payload).execute()
        inserted = response.data[0] if getattr(response, "data", None) else payload
        expense_id = inserted.get("id")
        registrar_auditoria_admin(actor, "create_recurring_expense", RECURRING_EXPENSES_TABLE, str(expense_id or "unknown"), _build_field_summary(payload))
        return _json_success({"recurring_expense": inserted}, 201)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_create_recurring_expense_failed", "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to create the recurring expense right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)


def atualizar_despesa_recorrente(expense_id: str, payload: dict[str, Any] | None):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    payload, payload_error = _normalize_recurring_expense_payload(payload)
    if payload_error:
        return payload_error

    try:
        existing = supabase.table(RECURRING_EXPENSES_TABLE).select("id").eq("id", expense_id).execute()
        if not existing.data:
            return _json_error("Recurring expense not found.", 404)

        response = supabase.table(RECURRING_EXPENSES_TABLE).update(payload).eq("id", expense_id).execute()
        updated = response.data[0] if getattr(response, "data", None) else {"id": expense_id, **payload}
        registrar_auditoria_admin(actor, "update_recurring_expense", RECURRING_EXPENSES_TABLE, expense_id, _build_field_summary(payload))
        return _json_success({"recurring_expense": updated}, 200)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_update_recurring_expense_failed", "id": expense_id, "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to update the recurring expense right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)


def deletar_despesa_recorrente(expense_id: str):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        existing = supabase.table(RECURRING_EXPENSES_TABLE).select("id").eq("id", expense_id).execute()
        if not existing.data:
            return _json_error("Recurring expense not found.", 404)

        supabase.table(RECURRING_EXPENSES_TABLE).delete().eq("id", expense_id).execute()
        registrar_auditoria_admin(actor, "delete_recurring_expense", RECURRING_EXPENSES_TABLE, expense_id)
        return _json_success({"id": expense_id}, 200)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_delete_recurring_expense_failed", "id": expense_id, "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to delete the recurring expense right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)


def _executar_geracao_recorrente(data_referencia: str | None, actor: dict, action_label: str = "generate_recurring_expenses"):
    if not data_referencia:
        from utils import get_brasilia_time
        data_referencia = get_brasilia_time().strftime("%Y-%m-%d")

    try:
        ref_date = datetime.strptime(data_referencia, "%Y-%m-%d")
    except ValueError:
        return _json_error("data_referencia must be in YYYY-MM-DD format.", 400)

    ref_month_start = f"{ref_date.year}-{ref_date.month:02d}-01"

    try:
        query = (
            supabase.table(RECURRING_EXPENSES_TABLE)
            .select(RECURRING_EXPENSE_GENERATION_FIELDS)
            .eq("ativo", True)
            .lte("mes_inicio", ref_month_start)
        )
        response = query.execute()
        recorrentes = getattr(response, "data", [])
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_generate_recurring_failed", "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to generate recurring expenses right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)

    generated = 0
    for rec in recorrentes:
        gasto = build_recurring_transaction_for_reference(rec, data_referencia)
        if gasto is None:
            continue

        try:
            supabase.table(TRANSACTIONS_TABLE).insert(gasto).execute()
            generated += 1
        except APIError as exc:
            if _is_unique_violation(exc):
                continue
            logger.error(with_request_id({
                "event": "admin_generate_recurring_insert_failed",
                "recurring_id": rec.get("id"),
                "error": mascarar_segredos(str(exc)),
            }))
            continue

    registrar_auditoria_admin(actor, action_label, TRANSACTIONS_TABLE, "batch", {"generated": generated, "reference_date": data_referencia})
    return _json_success({"generated": generated, "reference_date": data_referencia}, 200)
