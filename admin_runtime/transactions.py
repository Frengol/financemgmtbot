from typing import Any

from postgrest.exceptions import APIError
from quart import request

from api_responses import with_request_id
from config import logger, mascarar_segredos, supabase
from test_support import auth_test_mode_enabled, list_seeded_transactions

from .audit import _build_field_summary, registrar_auditoria_admin
from .auth import autenticar_admin_request
from .common import _json_error, _json_success
from .payloads import _normalize_transaction_payload


def listar_gastos_admin():
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        date_from = (request.args.get("date_from") or "").strip()
        date_to = (request.args.get("date_to") or "").strip()

        if auth_test_mode_enabled():
            return _json_success({"transactions": list_seeded_transactions(date_from, date_to)}, 200)

        query = supabase.table("gastos").select("id, data, natureza, categoria, descricao, valor, conta, metodo_pagamento").order("data", desc=True)
        if date_from:
            query = query.gte("data", date_from)
        if date_to:
            query = query.lte("data", date_to)

        response = query.execute()
        return _json_success({"transactions": getattr(response, "data", [])}, 200)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_list_transactions_failed", "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to load transactions right now.", 503, code="ADMIN_DATA_LOAD_FAILED", retryable=True)
    except Exception as exc:
        logger.error(with_request_id({"event": "admin_list_transactions_unexpected", "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to load transactions right now.", 503, code="ADMIN_DATA_LOAD_FAILED", retryable=True)


def criar_gasto_admin(payload: dict[str, Any] | None):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    payload, payload_error = _normalize_transaction_payload(payload)
    if payload_error:
        return payload_error

    try:
        response = supabase.table("gastos").insert(payload).execute()
        inserted = response.data[0] if getattr(response, "data", None) else payload
        transaction_id = inserted.get("id")
        registrar_auditoria_admin(actor, "create_transaction", "gastos", str(transaction_id or "unknown"), _build_field_summary(payload))
        return _json_success({"transaction": inserted}, 201)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_create_transaction_failed", "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to create the transaction right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)


def atualizar_gasto_admin(gasto_id: str, payload: dict[str, Any] | None):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    payload, payload_error = _normalize_transaction_payload(payload)
    if payload_error:
        return payload_error

    try:
        existing = supabase.table("gastos").select("id").eq("id", gasto_id).execute()
        if not existing.data:
            return _json_error("Transaction not found.", 404)

        response = supabase.table("gastos").update(payload).eq("id", gasto_id).execute()
        updated = response.data[0] if getattr(response, "data", None) else {"id": gasto_id, **payload}
        registrar_auditoria_admin(actor, "update_transaction", "gastos", gasto_id, _build_field_summary(payload))
        return _json_success({"transaction": updated}, 200)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_update_transaction_failed", "id": gasto_id, "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to update the transaction right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)


def deletar_gasto_admin(gasto_id: str):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        existing = supabase.table("gastos").select("id").eq("id", gasto_id).execute()
        if not existing.data:
            return _json_error("Transaction not found.", 404)

        supabase.table("gastos").delete().eq("id", gasto_id).execute()
        registrar_auditoria_admin(actor, "delete_transaction", "gastos", gasto_id)
        return _json_success({"id": gasto_id}, 200)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_delete_transaction_failed", "id": gasto_id, "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to delete the transaction right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)
