from postgrest.exceptions import APIError

from api_responses import with_request_id
from config import logger, mascarar_segredos, supabase
from db_repository import gravar_lote_no_banco
from security import build_pending_preview, delete_pending_item, load_pending_item, pending_item_expired

from .audit import registrar_auditoria_admin
from .auth import autenticar_admin_request
from .common import _json_error, _json_success


def listar_cache_admin():
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        response = (
            supabase
            .table("cache_aprovacao")
            .select("id, kind, preview_json, created_at, expires_at, payload")
            .order("created_at", desc=True)
            .execute()
        )

        items = []
        for item in getattr(response, "data", []):
            kind = item.get("kind") or ("delete_confirmation" if isinstance(item.get("payload"), dict) and isinstance(item["payload"].get("ids"), list) else "receipt_batch")
            preview = item.get("preview_json") if isinstance(item.get("preview_json"), dict) else build_pending_preview(kind, item.get("payload"))
            items.append({
                "id": item.get("id"),
                "kind": kind,
                "created_at": item.get("created_at"),
                "expires_at": item.get("expires_at"),
                "preview": preview,
            })
        return _json_success({"items": items}, 200)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_list_pending_receipts_failed", "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to load pending receipts right now.", 503, code="ADMIN_DATA_LOAD_FAILED", retryable=True)
    except Exception as exc:
        logger.error(with_request_id({"event": "admin_list_pending_receipts_unexpected", "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to load pending receipts right now.", 503, code="ADMIN_DATA_LOAD_FAILED", retryable=True)


def aprovar_cache_admin(cache_id: str):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        item = load_pending_item(cache_id)
        if not item:
            return _json_error("Pending receipt not found.", 404)
        if pending_item_expired(item):
            delete_pending_item(cache_id)
            return _json_error("Pending item expired.", 410)

        payload = item.get("payload")
        if not isinstance(payload, dict):
            return _json_error("Pending item payload unavailable.", 500)

        if item.get("kind") == "delete_confirmation":
            ids = payload.get("ids") if isinstance(payload.get("ids"), list) else []
            supabase.table("gastos").delete().in_("id", ids).execute()
            delete_pending_item(cache_id)
            registrar_auditoria_admin(
                actor,
                "approve_pending_delete",
                "cache_aprovacao",
                cache_id,
                {"records_count": len(ids), "contains_sensitive_values": False},
            )
            return _json_success({"id": cache_id, "deleted_records": len(ids)}, 200)

        linhas, total = gravar_lote_no_banco(payload)
        delete_pending_item(cache_id)
        registrar_auditoria_admin(
            actor,
            "approve_pending_receipt",
            "cache_aprovacao",
            cache_id,
            {"lines": linhas, "total": total, "contains_sensitive_values": False},
        )
        return _json_success({"id": cache_id, "linhas": linhas, "total": total}, 200)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_approve_pending_failed", "id": cache_id, "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to approve the pending receipt right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)
    except Exception as exc:
        logger.error(with_request_id({"event": "admin_approve_pending_unexpected", "id": cache_id, "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to approve the pending receipt right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)


def rejeitar_cache_admin(cache_id: str):
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    try:
        item = load_pending_item(cache_id)
        if not item:
            return _json_error("Pending receipt not found.", 404)

        delete_pending_item(cache_id)
        registrar_auditoria_admin(actor, "reject_pending_receipt", "cache_aprovacao", cache_id)
        return _json_success({"id": cache_id}, 200)
    except APIError as exc:
        logger.error(with_request_id({"event": "admin_reject_pending_failed", "id": cache_id, "error": mascarar_segredos(str(exc))}))
        return _json_error("Unable to reject the pending receipt right now.", 503, code="ADMIN_ACTION_FAILED", retryable=True)
