import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from config import logger, mascarar_segredos, supabase
from test_support import auth_test_mode_enabled, load_admin_session, revoke_admin_session as revoke_test_admin_session, store_admin_session, update_admin_session
from utils import get_brasilia_time

SESSION_COOKIE_NAME = "fm_admin_session"
CSRF_COOKIE_NAME = "fm_csrf"
SESSION_IDLE_HOURS = 8
SESSION_ABSOLUTE_HOURS = 24
PENDING_TTL_HOURS = 24
PENDING_KEY_VERSION = "v1"
MAX_WEBHOOK_BODY_BYTES = int(os.environ.get("MAX_WEBHOOK_BODY_BYTES") or 262_144)
MAX_TELEGRAM_IMAGE_BYTES = int(os.environ.get("MAX_TELEGRAM_IMAGE_BYTES") or 8_000_000)
MAX_TELEGRAM_AUDIO_BYTES = int(os.environ.get("MAX_TELEGRAM_AUDIO_BYTES") or 12_000_000)

_RATE_LIMIT_BUCKETS: dict[tuple[str, str], list[float]] = defaultdict(list)


def _derive_secret(label: str):
    seed = "|".join(
        [
            label,
            os.environ.get("APP_SESSION_SECRET") or "",
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
SESSION_SECRET = _derive_secret("session-secret")
CSRF_SECRET = _derive_secret("csrf-secret")


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


def generate_session_token():
    return secrets.token_urlsafe(32)


def hash_session_token(session_token: str):
    return hash_text(session_token)


def build_csrf_token(session_token: str):
    return hmac.new(CSRF_SECRET, session_token.encode("utf-8"), hashlib.sha256).hexdigest()


def validate_csrf_token(session_token: str, provided_token: str | None):
    if not provided_token:
        return False
    expected = build_csrf_token(session_token)
    return hmac.compare_digest(expected, provided_token)


def _parse_timestamp(value: str | None):
    if not value:
        return None

    candidate = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def create_admin_session(user_id: str, email: str | None, user_agent: str | None, ip_address: str | None):
    session_token = generate_session_token()
    now = get_brasilia_time()
    expires_at = now + timedelta(hours=SESSION_IDLE_HOURS)
    session_id_hash = hash_session_token(session_token)
    if auth_test_mode_enabled():
        store_admin_session(
            session_id_hash=session_id_hash,
            user_id=user_id,
            email=(email or "").lower() or None,
            created_at=now.isoformat(),
            last_seen_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )
    else:
        payload = {
            "session_id_hash": session_id_hash,
            "user_id": user_id,
            "email": (email or "").lower() or None,
            "created_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "revoked_at": None,
            "user_agent_hash": hash_optional(user_agent),
            "ip_hash": hash_optional(ip_address),
        }
        supabase.table("admin_web_sessions").insert(payload).execute()
    return {
        "token": session_token,
        "csrf_token": build_csrf_token(session_token),
        "expires_at": expires_at.isoformat(),
    }


def resolve_admin_session(session_token: str | None):
    if not session_token:
        return None

    session_id_hash = hash_session_token(session_token)
    if auth_test_mode_enabled():
        session_row = load_admin_session(session_id_hash)
        if not session_row:
            return None
    else:
        response = (
            supabase
            .table("admin_web_sessions")
            .select("session_id_hash, user_id, email, created_at, last_seen_at, expires_at, revoked_at")
            .eq("session_id_hash", session_id_hash)
            .execute()
        )
        if not getattr(response, "data", None):
            return None

        session_row = response.data[0]
    now = get_brasilia_time()
    created_at = _parse_timestamp(session_row.get("created_at")) or now
    expires_at = _parse_timestamp(session_row.get("expires_at")) or created_at
    revoked_at = _parse_timestamp(session_row.get("revoked_at"))
    absolute_expiry = created_at + timedelta(hours=SESSION_ABSOLUTE_HOURS)

    if revoked_at is not None or expires_at <= now or absolute_expiry <= now:
        return None

    refreshed_expiry = min(now + timedelta(hours=SESSION_IDLE_HOURS), absolute_expiry)
    try:
        if auth_test_mode_enabled():
            update_admin_session(
                session_id_hash,
                last_seen_at=now.isoformat(),
                expires_at=refreshed_expiry.isoformat(),
            )
        else:
            (
                supabase
                .table("admin_web_sessions")
                .update({"last_seen_at": now.isoformat(), "expires_at": refreshed_expiry.isoformat()})
                .eq("session_id_hash", session_id_hash)
                .execute()
            )
    except Exception as exc:
        logger.warning({"event": "admin_session_refresh_failed", "error": mascarar_segredos(str(exc))})

    return {
        "user_id": session_row.get("user_id"),
        "email": session_row.get("email"),
        "expires_at": refreshed_expiry.isoformat(),
        "csrf_token": build_csrf_token(session_token),
    }


def revoke_admin_session(session_token: str | None):
    if not session_token:
        return

    now = get_brasilia_time().isoformat()
    session_id_hash = hash_session_token(session_token)
    if auth_test_mode_enabled():
        revoke_test_admin_session(session_id_hash, revoked_at=now, expires_at=now)
        return

    (
        supabase
        .table("admin_web_sessions")
        .update({"revoked_at": now, "expires_at": now})
        .eq("session_id_hash", session_id_hash)
        .execute()
    )


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
):
    resolved_kind = kind or detect_pending_kind(payload)
    record_id = cache_id or generate_pending_id()
    now = get_brasilia_time()
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
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    supabase.table("cache_aprovacao").insert(insert_payload).execute()
    return {"id": record_id, "kind": resolved_kind, "preview": preview, "expires_at": expires_at.isoformat()}


def load_pending_item(cache_id: str):
    response = (
        supabase
        .table("cache_aprovacao")
        .select("id, kind, payload_ciphertext, payload_key_version, preview_json, created_at, expires_at, origin_chat_id, origin_user_id, payload")
        .eq("id", cache_id)
        .execute()
    )
    if not getattr(response, "data", None):
        return None

    item = response.data[0]
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


def pending_item_expired(item: dict[str, Any] | None):
    if not item:
        return True
    expires_at = _parse_timestamp(item.get("expires_at"))
    if not expires_at:
        return False
    return expires_at <= get_brasilia_time()


def delete_pending_item(cache_id: str):
    supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()


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
