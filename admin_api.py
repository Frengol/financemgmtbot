from datetime import datetime
from typing import Any
import unicodedata

from postgrest.exceptions import APIError
from quart import jsonify, request

from config import ADMIN_EMAILS, ADMIN_USER_IDS, ALLOW_LOCAL_DEV_AUTH, FRONTEND_ALLOWED_ORIGINS, logger, mascarar_segredos, supabase
from db_repository import gravar_lote_no_banco
from utils import CATEGORIA_MAP, inferir_natureza

AUDIT_TABLE = "auditoria_admin"


def _build_field_summary(payload: dict[str, Any] | None):
    if not isinstance(payload, dict):
        return {"contains_sensitive_values": False, "fields": [], "field_count": 0}

    fields = sorted(payload.keys())
    return {
        "contains_sensitive_values": False,
        "fields": fields,
        "field_count": len(fields),
    }


def _json_error(message: str, status_code: int):
    response = jsonify({"status": "error", "message": message})
    response.status_code = status_code
    return response


def _json_success(payload: dict[str, Any], status_code: int = 200):
    response = jsonify({"status": "ok", **payload})
    response.status_code = status_code
    return response


def _extract_user_fields(user: Any):
    if user is None:
        return None, None

    if isinstance(user, dict):
        return user.get("id"), user.get("email")

    return getattr(user, "id", None), getattr(user, "email", None)


def _normalize_lookup(value: str):
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().lower()


def autenticar_admin_request():
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    origin = request.headers.get("Origin", "")
    remote_addr = request.remote_addr or ""
    is_loopback = remote_addr in {"127.0.0.1", "::1", "localhost"}
    is_allowed_origin = origin in FRONTEND_ALLOWED_ORIGINS if origin else False

    if ALLOW_LOCAL_DEV_AUTH and token == "" and (is_allowed_origin or is_loopback):
        return {"id": "local-dev", "email": "local-dev@localhost"}, None

    if not token:
        return None, _json_error("Missing bearer token.", 401)

    try:
        auth_response = supabase.auth.get_user(token)
    except Exception as exc:
        logger.warning({"event": "admin_auth_failed", "error": mascarar_segredos(str(exc))})
        return None, _json_error("Invalid or expired session.", 401)

    user = getattr(auth_response, "user", None) if auth_response is not None else None
    user_id, email = _extract_user_fields(user)
    if not user_id:
        return None, _json_error("Unable to resolve the authenticated user.", 401)

    normalized_email = email.lower() if isinstance(email, str) else None
    if ADMIN_USER_IDS and user_id not in ADMIN_USER_IDS:
        return None, _json_error("Authenticated user is not allowed to access this admin route.", 403)
    if ADMIN_EMAILS and normalized_email not in ADMIN_EMAILS:
        return None, _json_error("Authenticated user is not allowed to access this admin route.", 403)

    return {"id": user_id, "email": normalized_email}, None


def _normalize_transaction_payload(payload: dict[str, Any] | None):
    if not isinstance(payload, dict):
        return None, _json_error("Invalid transaction payload.", 400)

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

    raw_description = str(payload.get("descricao") or "").strip()
    if not raw_description:
        return None, _json_error("Transaction description is required.", 400)

    raw_category = str(payload.get("categoria") or "").strip()
    category_lookup = _normalize_lookup(raw_category)
    category_aliases = {
        _normalize_lookup(category_key): category_key
        for category_key in CATEGORIA_MAP
    }
    canonical_category_key = category_aliases.get(category_lookup)
    if not canonical_category_key:
        return None, _json_error("Transaction category is invalid.", 400)

    normalized_nature, normalized_category = inferir_natureza(canonical_category_key)
    normalized_payment_method = str(payload.get("metodo_pagamento") or "Outros").strip() or "Outros"
    normalized_account = str(payload.get("conta") or "Nao Informada").strip() or "Nao Informada"

    return {
        "data": normalized_date,
        "valor": normalized_value,
        "natureza": normalized_nature,
        "categoria": normalized_category,
        "descricao": raw_description[:250],
        "metodo_pagamento": normalized_payment_method[:120],
        "conta": normalized_account[:120],
    }, None


def registrar_auditoria_admin(actor: dict[str, str | None], action: str, target_table: str, target_id: str, metadata: dict[str, Any] | None = None):
    payload = {
        "actor_user_id": actor.get("id"),
        "actor_email": actor.get("email"),
        "action": action,
        "target_table": target_table,
        "target_id": target_id,
        "metadata": metadata or {},
    }

    try:
        supabase.table(AUDIT_TABLE).insert(payload).execute()
    except APIError as exc:
        logger.warning({
            "event": "admin_audit_insert_failed",
            "action": action,
            "target_table": target_table,
            "target_id": target_id,
            "error": mascarar_segredos(str(exc)),
        })
    except Exception as exc:
        logger.warning({
            "event": "admin_audit_unexpected_failure",
            "action": action,
            "target_table": target_table,
            "target_id": target_id,
            "error": mascarar_segredos(str(exc)),
        })


def listar_gastos_admin():
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        query = supabase.table("gastos").select("id, data, natureza, categoria, descricao, valor, conta, metodo_pagamento").order("data", desc=True)
        date_from = (request.args.get("date_from") or "").strip()
        date_to = (request.args.get("date_to") or "").strip()

        if date_from:
          query = query.gte("data", date_from)
        if date_to:
          query = query.lte("data", date_to)

        response = query.execute()
        return _json_success({"transactions": getattr(response, "data", [])}, 200)
    except APIError as exc:
        logger.error({"event": "admin_list_transactions_failed", "error": mascarar_segredos(str(exc))})
        return _json_error("Unable to load transactions right now.", 500)


def listar_cache_admin():
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        response = supabase.table("cache_aprovacao").select("id, payload, created_at").order("created_at", desc=True).execute()
        return _json_success({"items": getattr(response, "data", [])}, 200)
    except APIError as exc:
        logger.error({"event": "admin_list_pending_receipts_failed", "error": mascarar_segredos(str(exc))})
        return _json_error("Unable to load pending receipts right now.", 500)


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
        logger.error({"event": "admin_create_transaction_failed", "error": mascarar_segredos(str(exc))})
        return _json_error("Unable to create the transaction right now.", 500)


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
        logger.error({"event": "admin_update_transaction_failed", "id": gasto_id, "error": mascarar_segredos(str(exc))})
        return _json_error("Unable to update the transaction right now.", 500)


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
        logger.error({"event": "admin_delete_transaction_failed", "id": gasto_id, "error": mascarar_segredos(str(exc))})
        return _json_error("Unable to delete the transaction right now.", 500)


def aprovar_cache_admin(cache_id: str):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        response = supabase.table("cache_aprovacao").select("payload").eq("id", cache_id).execute()
        if not response.data:
            return _json_error("Pending receipt not found.", 404)

        payload = response.data[0]["payload"]
        linhas, total = gravar_lote_no_banco(payload)
        supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()

        registrar_auditoria_admin(
            actor,
            "approve_pending_receipt",
            "cache_aprovacao",
            cache_id,
            {"lines": linhas, "total": total, "contains_sensitive_values": False},
        )

        return _json_success({"id": cache_id, "linhas": linhas, "total": total}, 200)
    except APIError as exc:
        logger.error({"event": "admin_approve_pending_failed", "id": cache_id, "error": mascarar_segredos(str(exc))})
        return _json_error("Unable to approve the pending receipt right now.", 500)
    except Exception as exc:
        logger.error({"event": "admin_approve_pending_unexpected", "id": cache_id, "error": mascarar_segredos(str(exc))})
        return _json_error("Unable to approve the pending receipt right now.", 500)


def rejeitar_cache_admin(cache_id: str):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        response = supabase.table("cache_aprovacao").select("id").eq("id", cache_id).execute()
        if not response.data:
            return _json_error("Pending receipt not found.", 404)

        supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()
        registrar_auditoria_admin(actor, "reject_pending_receipt", "cache_aprovacao", cache_id)
        return _json_success({"id": cache_id}, 200)
    except APIError as exc:
        logger.error({"event": "admin_reject_pending_failed", "id": cache_id, "error": mascarar_segredos(str(exc))})
        return _json_error("Unable to reject the pending receipt right now.", 500)
