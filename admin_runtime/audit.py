from typing import Any

from postgrest.exceptions import APIError

from config import logger, mascarar_segredos, supabase

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
