import base64
import hashlib
import html
import json
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from config import logger, supabase
from domain.duplicate_expense import DUPLICATE_DECISIONS, DUPLICATE_EXPENSE_KIND
from utils import get_brasilia_time

PENDING_TTL_HOURS = 24
PENDING_KEY_VERSION = "v1"
MAX_WEBHOOK_BODY_BYTES = int(os.environ.get("MAX_WEBHOOK_BODY_BYTES") or 75_000)
MAX_TELEGRAM_IMAGE_BYTES = int(os.environ.get("MAX_TELEGRAM_IMAGE_BYTES") or 8_000_000)
MAX_TELEGRAM_AUDIO_BYTES = int(os.environ.get("MAX_TELEGRAM_AUDIO_BYTES") or 12_000_000)

_RATE_LIMIT_BUCKETS: dict[tuple[str, str], list[float]] = defaultdict(list)
PENDING_SELECT_FIELDS = (
    "id, kind, payload_ciphertext, payload_key_version, preview_json, created_at, expires_at, "
    "origin_chat_id, origin_user_id, source_update_id, duplicate_decision, payload, "
    "payload_revision, approval_claimed_revision"
)
RECEIPT_CLAIM_STATUSES = frozenset({"claimed", "already_claimed", "stale", "expired", "unavailable"})
RECEIPT_DISCARD_STATUSES = frozenset({"discarded", "claimed", "unavailable"})
LEGACY_PENDING_KINDS = frozenset({"receipt_batch", "delete_confirmation"})
DUPLICATE_CLEARED_PREVIEW = {"summary": "Confirmação concluída"}

def _derive_secret(label: str):
    seed = "|".join(
        [
            label,
            os.environ.get("SUPABASE_KEY") or "",
            os.environ.get("TELEGRAM_SECRET_TOKEN") or "",
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _fernet_key():
    configured = (os.environ.get("DATA_ENCRYPTION_KEY") or "").strip()
    if configured:
        try:
            Fernet(configured.encode("utf-8"))
            return configured.encode("utf-8")
        except Exception:
            logger.warning({"event": "security_invalid_data_encryption_key", "message": "Falling back to derived key."})

    return base64.urlsafe_b64encode(_derive_secret("data-encryption"))


FERNET = Fernet(_fernet_key())


def sanitize_plain_text(value: Any, max_length: int, default: str = ""):
    raw = str(value if value is not None else default).strip()
    if not raw:
        raw = default
    return html.escape(raw.replace("\x00", ""), quote=False)[:max_length]


def hash_text(value: str):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_optional(value: str | None):
    if not value:
        return None
    return hash_text(value)


def _parse_timestamp(value: str | None):
    if not value:
        return None

    candidate = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def encrypt_pending_payload(payload: dict[str, Any]):
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return FERNET.encrypt(serialized.encode("utf-8")).decode("utf-8")


def decrypt_pending_payload(payload_ciphertext: str):
    decoded = FERNET.decrypt(payload_ciphertext.encode("utf-8"))
    return json.loads(decoded.decode("utf-8"))


def detect_pending_kind(payload: dict[str, Any] | None):
    if isinstance(payload, dict) and isinstance(payload.get("ids"), list):
        return "delete_confirmation"
    return "receipt_batch"


def generate_pending_id():
    return secrets.token_urlsafe(12)


def build_pending_preview(kind: str, payload: dict[str, Any] | None):
    payload = payload if isinstance(payload, dict) else {}
    if kind == DUPLICATE_EXPENSE_KIND:
        return {"summary": "Confirmação pendente"}
    if kind == "delete_confirmation":
        ids = payload.get("ids") or []
        return {
            "summary": "Exclusão pendente",
            "records_count": len(ids),
        }

    items = payload.get("itens") if isinstance(payload.get("itens"), list) else []
    preview_items = [
        sanitize_plain_text(item.get("nome") if isinstance(item, dict) else "", 80, "Item")
        for item in items[:3]
    ]
    total = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            bruto = float(item.get("valor_bruto") or 0.0)
            desconto = float(item.get("desconto_item") or 0.0)
        except (TypeError, ValueError):
            continue
        total += max(0.0, bruto - desconto)

    try:
        total -= float(payload.get("desconto_global") or 0.0)
    except (TypeError, ValueError):
        pass

    return {
        "summary": "Cupom pendente",
        "metodo_pagamento": sanitize_plain_text(payload.get("metodo_pagamento"), 120, "Nao Informado"),
        "conta": sanitize_plain_text(payload.get("conta"), 120, "Nao Informada"),
        "itens": preview_items,
        "itens_count": len(items),
        "total_estimado": round(max(total, 0.0), 2),
    }


def store_pending_item(
    payload: dict[str, Any],
    *,
    kind: str | None = None,
    cache_id: str | None = None,
    origin_chat_id: int | str | None = None,
    origin_user_id: int | str | None = None,
    source_update_id: int | None = None,
):
    resolved_kind = kind or detect_pending_kind(payload)
    stable_id = f"tu_{hash_text(str(source_update_id))[:20]}" if source_update_id is not None else None
    record_id = cache_id or stable_id or generate_pending_id()
    # Duplicate confirmations are decided by the database against now(), so they
    # need real instants; legacy kinds keep their historical local-time values.
    now = datetime.now(timezone.utc) if resolved_kind == DUPLICATE_EXPENSE_KIND else get_brasilia_time()
    expires_at = now + timedelta(hours=PENDING_TTL_HOURS)
    preview = build_pending_preview(resolved_kind, payload)
    insert_payload = {
        "id": record_id,
        "kind": resolved_kind,
        "payload": {},
        "payload_ciphertext": encrypt_pending_payload(payload),
        "payload_key_version": PENDING_KEY_VERSION,
        "preview_json": preview,
        "origin_chat_id": str(origin_chat_id) if origin_chat_id is not None else None,
        "origin_user_id": str(origin_user_id) if origin_user_id is not None else None,
        "source_update_id": source_update_id,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    table = supabase.table("cache_aprovacao")
    if source_update_id is None:
        table.insert(insert_payload).execute()
    else:
        response = table.upsert(
            insert_payload,
            on_conflict="source_update_id",
            ignore_duplicates=True,
        ).execute()
        if not isinstance(getattr(response, "data", None), list) or not response.data:
            persisted = load_pending_item_by_source_update_id(source_update_id)
            if not persisted:
                raise RuntimeError("Pending item conflict winner is unavailable.")
            if origin_chat_id is not None and str(persisted.get("origin_chat_id") or "") != str(origin_chat_id):
                raise RuntimeError("Pending conflict winner belongs to another chat.")
            return {
                "id": persisted["id"],
                "kind": persisted["kind"],
                "preview": persisted["preview_json"],
                "expires_at": persisted.get("expires_at"),
                "payload": persisted.get("payload"),
                "source_update_id": persisted.get("source_update_id"),
                "origin_user_id": persisted.get("origin_user_id"),
                "duplicate_decision": persisted.get("duplicate_decision"),
                "payload_revision": persisted.get("payload_revision"),
            }
    return {
        "id": record_id,
        "kind": resolved_kind,
        "preview": preview,
        "expires_at": expires_at.isoformat(),
        "payload": payload,
        "source_update_id": source_update_id,
    }


def _hydrate_pending_item(item: dict[str, Any], cache_id: str):
    payload = None
    ciphertext = item.get("payload_ciphertext")
    if ciphertext:
        try:
            payload = decrypt_pending_payload(ciphertext)
        except InvalidToken:
            logger.warning({"event": "pending_payload_invalid_token", "cache_id": cache_id})
            payload = None
    elif isinstance(item.get("payload"), dict):
        payload = item.get("payload")

    kind = item.get("kind") or detect_pending_kind(payload)
    preview = item.get("preview_json") if isinstance(item.get("preview_json"), dict) else build_pending_preview(kind, payload)
    return {
        **item,
        "kind": kind,
        "payload": payload,
        "preview_json": preview,
    }


def load_pending_item(cache_id: str):
    response = (
        supabase
        .table("cache_aprovacao")
        .select(PENDING_SELECT_FIELDS)
        .eq("id", cache_id)
        .execute()
    )
    if not getattr(response, "data", None):
        return None

    return _hydrate_pending_item(response.data[0], cache_id)


def load_pending_item_by_source_update_id(source_update_id: int | None):
    if source_update_id is None:
        return None
    response = (
        supabase
        .table("cache_aprovacao")
        .select(PENDING_SELECT_FIELDS)
        .eq("source_update_id", source_update_id)
        .limit(1)
        .execute()
    )
    data = getattr(response, "data", None)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    return _hydrate_pending_item(data[0], str(data[0].get("id") or "unknown"))


def pending_item_expired(item: dict[str, Any] | None):
    if not item:
        return True
    expires_at = _parse_timestamp(item.get("expires_at"))
    if not expires_at:
        return False
    return expires_at <= get_brasilia_time()


def duplicate_item_expired(item: dict[str, Any] | None):
    """Deadline check for duplicate confirmations; a missing or unreadable deadline counts as expired."""
    raw = item.get("expires_at") if item else None
    if not isinstance(raw, str):
        return True
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= datetime.now(timezone.utc)


def delete_pending_item(cache_id: str):
    supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()


def mark_pending_summary_sent(cache_id: str, payload: dict[str, Any]):
    marked_payload = dict(payload)
    marked_payload["_approval_summary_sent"] = True
    response = (
        supabase
        .table("cache_aprovacao")
        .update({"payload_ciphertext": encrypt_pending_payload(marked_payload)})
        .eq("id", cache_id)
        .execute()
    )
    if getattr(response, "data", None) is None:
        raise RuntimeError("Pending approval delivery marker was not persisted.")


def matches_pending_origin(item: dict[str, Any] | None, chat_id: int | str | None, user_id: int | str | None):
    if not item:
        return False
    expected_chat = str(item.get("origin_chat_id") or "").strip()
    expected_user = str(item.get("origin_user_id") or "").strip()
    current_chat = str(chat_id) if chat_id is not None else ""
    current_user = str(user_id) if user_id is not None else ""

    if expected_chat and expected_chat != current_chat:
        return False
    if expected_user and current_user and expected_user != current_user:
        return False
    return True


def matches_pending_origin_exact(item: dict[str, Any] | None, chat_id: int | str | None, user_id: int | str | None):
    """Strict binding: the stored chat and user must both exist and equal the caller's."""
    if not item or chat_id is None or user_id is None:
        return False
    expected_chat = str(item.get("origin_chat_id") or "").strip()
    expected_user = str(item.get("origin_user_id") or "").strip()
    return bool(expected_chat) and bool(expected_user) and expected_chat == str(chat_id) and expected_user == str(user_id)


def decide_duplicate_expense(cache_id: str, chat_id: int | str | None, user_id: int | str | None, decision: str):
    """Atomically record the first valid decision in the database; returns the canonical one.

    The database function re-checks kind, chat, user and deadline, and a decision
    requested after the deadline is stored as ``expired``.
    """
    if decision not in ("save", "skip"):
        raise ValueError("Unsupported duplicate decision.")
    if chat_id is None or user_id is None:
        return None
    response = supabase.rpc(
        "decide_duplicate_expense",
        {"p_id": cache_id, "p_chat_id": str(chat_id), "p_user_id": str(user_id), "p_decision": decision},
    ).execute()
    data = getattr(response, "data", None)
    if isinstance(data, list):
        data = data[0] if len(data) == 1 else None
    return data if data in DUPLICATE_DECISIONS else None


def clear_duplicate_snapshot(cache_id: str):
    """Drop the encrypted snapshot of a decided duplicate confirmation, keeping the marker row."""
    response = (
        supabase
        .table("cache_aprovacao")
        .update(
            {
                "payload_ciphertext": None,
                "payload": {},
                "preview_json": DUPLICATE_CLEARED_PREVIEW,
            }
        )
        .eq("id", cache_id)
        .eq("kind", DUPLICATE_EXPENSE_KIND)
        .not_.is_("duplicate_decision", "null")
        .execute()
    )
    if not getattr(response, "data", None):
        raise RuntimeError("Duplicate confirmation snapshot was not cleared.")


def _non_negative_int(value: Any):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def pending_revision(item: dict[str, Any] | None):
    """Stored payload revision of a pending receipt; None when absent or malformed."""
    return _non_negative_int(item.get("payload_revision")) if isinstance(item, dict) else None


def receipt_pending_expired_strict(item: dict[str, Any] | None):
    """Deadline check for receipt edits and claims; a missing or unreadable deadline counts as expired."""
    raw = item.get("expires_at") if isinstance(item, dict) else None
    if not isinstance(raw, str) or not raw:
        return True
    try:
        expires_at = _parse_timestamp(raw)
    except ValueError:
        return True
    return expires_at <= get_brasilia_time()


def _receipt_rpc_clock():
    # Receipt deadlines are stored with the Brasilia wall clock (see store_pending_item),
    # so the database compares them with the same clock instead of its own now().
    return get_brasilia_time().isoformat()


def _single_rpc_value(data: Any):
    if isinstance(data, list):
        return data[0] if len(data) == 1 else None
    return data


def edit_receipt_pending(
    cache_id: str,
    chat_id: int | str | None,
    user_id: int | str | None,
    expected_revision: int,
    payload: dict[str, Any],
):
    """Atomically replace the encrypted payload of a bound, open receipt at ``expected_revision``.

    The database re-checks kind, chat, user, deadline, revision and that no approval
    started, and never renews the deadline. Returns the new revision or None.
    """
    if chat_id is None or user_id is None or _non_negative_int(expected_revision) is None:
        return None
    response = supabase.rpc(
        "edit_receipt_pending",
        {
            "p_id": cache_id,
            "p_chat_id": str(chat_id),
            "p_user_id": str(user_id),
            "p_expected_revision": expected_revision,
            "p_ciphertext": encrypt_pending_payload(payload),
            "p_preview": build_pending_preview("receipt_batch", payload),
            "p_now": _receipt_rpc_clock(),
        },
    ).execute()
    revision = _non_negative_int(_single_rpc_value(getattr(response, "data", None)))
    return revision if revision else None


def _parse_claim(data: Any):
    row = _single_rpc_value(data)
    if not isinstance(row, dict) or row.get("claim_status") not in RECEIPT_CLAIM_STATUSES:
        return "unavailable", None
    status = row["claim_status"]
    if status in ("expired", "unavailable"):
        return status, None
    revision = _non_negative_int(row.get("claim_revision"))
    return (status, revision) if revision is not None else ("unavailable", None)


def claim_receipt_approval(cache_id: str, chat_id: int | str | None, user_id: int | str | None, revision: int):
    """Lock the approval of a bound receipt at ``revision``; returns (status, revision)."""
    if chat_id is None or user_id is None or _non_negative_int(revision) is None:
        return "unavailable", None
    response = supabase.rpc(
        "claim_receipt_approval",
        {
            "p_id": cache_id,
            "p_chat_id": str(chat_id),
            "p_user_id": str(user_id),
            "p_revision": revision,
            "p_now": _receipt_rpc_clock(),
        },
    ).execute()
    return _parse_claim(getattr(response, "data", None))


def claim_receipt_approval_admin(cache_id: str):
    """Lock the approval of the current revision for the authenticated admin panel."""
    response = supabase.rpc("claim_receipt_approval_admin", {"p_id": cache_id, "p_now": _receipt_rpc_clock()}).execute()
    return _parse_claim(getattr(response, "data", None))


def _parse_discard(data: Any):
    status = _single_rpc_value(data)
    return status if status in RECEIPT_DISCARD_STATUSES else "unavailable"


def discard_receipt_pending(cache_id: str, chat_id: int | str | None, user_id: int | str | None):
    """Delete a bound receipt unless its approval started: discarded, claimed or unavailable."""
    if chat_id is None or user_id is None:
        return "unavailable"
    response = supabase.rpc(
        "discard_receipt_pending",
        {"p_id": cache_id, "p_chat_id": str(chat_id), "p_user_id": str(user_id)},
    ).execute()
    return _parse_discard(getattr(response, "data", None))


def discard_receipt_pending_admin(cache_id: str):
    response = supabase.rpc("discard_receipt_pending_admin", {"p_id": cache_id}).execute()
    return _parse_discard(getattr(response, "data", None))


def allow_request(scope: str, key: str, *, limit: int, window_seconds: int):
    now = time.monotonic()
    bucket_key = (scope, key or "anonymous")
    bucket = [timestamp for timestamp in _RATE_LIMIT_BUCKETS[bucket_key] if now - timestamp < window_seconds]
    if len(bucket) >= limit:
        _RATE_LIMIT_BUCKETS[bucket_key] = bucket
        return False
    bucket.append(now)
    _RATE_LIMIT_BUCKETS[bucket_key] = bucket
    return True
