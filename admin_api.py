from typing import Any

from postgrest.exceptions import APIError
from quart import jsonify, request

from config import ADMIN_EMAILS, ADMIN_USER_IDS, logger, mascarar_segredos, supabase
from db_repository import gravar_lote_no_banco

AUDIT_TABLE = "auditoria_admin"


def _json_error(message: str, status_code: int):
    return jsonify({"status": "error", "message": message}), status_code


def _extract_user_fields(user: Any):
    if user is None:
        return None, None

    if isinstance(user, dict):
        return user.get("id"), user.get("email")

    return getattr(user, "id", None), getattr(user, "email", None)


def autenticar_admin_request():
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
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
        return jsonify({"status": "ok", "id": gasto_id}), 200
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
            {"linhas": linhas, "total": total},
        )

        return jsonify({"status": "ok", "id": cache_id, "linhas": linhas, "total": total}), 200
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
        return jsonify({"status": "ok", "id": cache_id}), 200
    except APIError as exc:
        logger.error({"event": "admin_reject_pending_failed", "id": cache_id, "error": mascarar_segredos(str(exc))})
        return _json_error("Unable to reject the pending receipt right now.", 500)
