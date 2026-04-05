import os
import secrets
from threading import Lock
from urllib.parse import quote


_STATE_LOCK = Lock()
_MAGIC_LINKS_BY_TOKEN: dict[str, dict[str, str | bool]] = {}
_MAGIC_LINKS_BY_EMAIL: dict[str, list[dict[str, str | bool]]] = {}
_SEEDED_TRANSACTIONS: list[dict[str, object]] = []
_SESSIONS_BY_HASH: dict[str, dict[str, str | None]] = {}


def auth_test_mode_enabled():
    return (os.environ.get("AUTH_TEST_MODE") or "").strip().lower() == "true"


def reset_auth_test_state():
    with _STATE_LOCK:
        _MAGIC_LINKS_BY_TOKEN.clear()
        _MAGIC_LINKS_BY_EMAIL.clear()
        _SEEDED_TRANSACTIONS.clear()
        _SESSIONS_BY_HASH.clear()


def _normalize_email(email: str | None):
    return (email or "").strip().lower()


def _build_magic_link(callback_url: str, token_hash: str):
    separator = "&" if "?" in callback_url else "?"
    return f"{callback_url}{separator}token_hash={quote(token_hash, safe='')}&type=magiclink"


def capture_magic_link(
    *,
    email: str,
    callback_url: str,
    user_id: str | None = None,
):
    normalized_email = _normalize_email(email)
    token_hash = secrets.token_urlsafe(18)
    payload = {
        "email": normalized_email,
        "user_id": (user_id or f"auth-test-{token_hash[:8]}").strip(),
        "token_hash": token_hash,
        "link": _build_magic_link(callback_url, token_hash),
    }

    with _STATE_LOCK:
        _MAGIC_LINKS_BY_TOKEN[token_hash] = payload
        _MAGIC_LINKS_BY_EMAIL.setdefault(normalized_email, []).append(payload)

    return dict(payload)


def peek_magic_link(email: str):
    normalized_email = _normalize_email(email)
    with _STATE_LOCK:
        links = _MAGIC_LINKS_BY_EMAIL.get(normalized_email) or []
        if not links:
            return None
        return dict(links[-1])


def consume_magic_link(token_hash: str):
    with _STATE_LOCK:
        payload = _MAGIC_LINKS_BY_TOKEN.pop(token_hash, None)
        if not payload:
            return None

        email = str(payload.get("email") or "")
        links = _MAGIC_LINKS_BY_EMAIL.get(email) or []
        _MAGIC_LINKS_BY_EMAIL[email] = [item for item in links if item.get("token_hash") != token_hash]
        if not _MAGIC_LINKS_BY_EMAIL[email]:
            _MAGIC_LINKS_BY_EMAIL.pop(email, None)
        return dict(payload)


def seed_transactions(transactions: list[dict[str, object]] | None):
    with _STATE_LOCK:
        _SEEDED_TRANSACTIONS.clear()
        for item in transactions or []:
            _SEEDED_TRANSACTIONS.append(dict(item))
    return list_seeded_transactions()


def list_seeded_transactions(date_from: str | None = None, date_to: str | None = None):
    with _STATE_LOCK:
        items = [dict(item) for item in _SEEDED_TRANSACTIONS]

    filtered = []
    for item in items:
        transaction_date = str(item.get("data") or "")
        if date_from and transaction_date and transaction_date < date_from:
            continue
        if date_to and transaction_date and transaction_date > date_to:
            continue
        filtered.append(item)

    filtered.sort(key=lambda item: str(item.get("data") or ""), reverse=True)
    return filtered


def store_admin_session(
    *,
    session_id_hash: str,
    user_id: str,
    email: str | None,
    created_at: str,
    last_seen_at: str,
    expires_at: str,
    revoked_at: str | None = None,
):
    payload = {
        "session_id_hash": session_id_hash,
        "user_id": user_id,
        "email": _normalize_email(email),
        "created_at": created_at,
        "last_seen_at": last_seen_at,
        "expires_at": expires_at,
        "revoked_at": revoked_at,
    }
    with _STATE_LOCK:
        _SESSIONS_BY_HASH[session_id_hash] = payload
    return dict(payload)


def load_admin_session(session_id_hash: str):
    with _STATE_LOCK:
        payload = _SESSIONS_BY_HASH.get(session_id_hash)
        return dict(payload) if payload else None


def update_admin_session(session_id_hash: str, *, last_seen_at: str, expires_at: str):
    with _STATE_LOCK:
        payload = _SESSIONS_BY_HASH.get(session_id_hash)
        if not payload:
            return None
        payload["last_seen_at"] = last_seen_at
        payload["expires_at"] = expires_at
        return dict(payload)


def revoke_admin_session(session_id_hash: str, *, revoked_at: str, expires_at: str):
    with _STATE_LOCK:
        payload = _SESSIONS_BY_HASH.get(session_id_hash)
        if not payload:
            return None
        payload["revoked_at"] = revoked_at
        payload["expires_at"] = expires_at
        return dict(payload)
