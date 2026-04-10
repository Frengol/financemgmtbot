import os
import secrets
import json
import base64
import time
from threading import Lock
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit


_STATE_LOCK = Lock()
_MAGIC_LINKS_BY_TOKEN: dict[str, dict[str, str | bool]] = {}
_MAGIC_LINKS_BY_EMAIL: dict[str, list[dict[str, str | bool]]] = {}
_SEEDED_TRANSACTIONS: list[dict[str, object]] = []
_ACCESS_TOKENS: dict[str, dict[str, str | None]] = {}


def auth_test_mode_enabled():
    return (os.environ.get("AUTH_TEST_MODE") or "").strip().lower() == "true"


def reset_auth_test_state():
    with _STATE_LOCK:
        _MAGIC_LINKS_BY_TOKEN.clear()
        _MAGIC_LINKS_BY_EMAIL.clear()
        _SEEDED_TRANSACTIONS.clear()
        _ACCESS_TOKENS.clear()


def _normalize_email(email: str | None):
    return (email or "").strip().lower()


def _build_magic_link_verify_url(verify_base_url: str, callback_url: str, token_hash: str):
    parsed_callback = urlsplit(verify_base_url.strip())
    verify_base = urlunsplit((parsed_callback.scheme, parsed_callback.netloc, "/__test__/auth/verify", "", ""))
    return (
        f"{verify_base}?token_hash={quote(token_hash, safe='')}"
        f"&redirect_to={quote_plus(callback_url)}"
    )


def _base64url_encode(payload: dict[str, object]):
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _build_test_access_token(*, user_id: str, email: str):
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": "https://auth.test.local",
        "sub": user_id,
        "aud": "authenticated",
        "exp": now + (60 * 60),
        "iat": now,
        "email": email,
        "role": "authenticated",
        "aal": "aal1",
        "session_id": f"session-{secrets.token_urlsafe(8)}",
    }
    return f"{_base64url_encode(header)}.{_base64url_encode(payload)}.test-signature"


def capture_magic_link(
    *,
    email: str,
    callback_url: str,
    verify_base_url: str,
    user_id: str | None = None,
):
    normalized_email = _normalize_email(email)
    token_hash = secrets.token_urlsafe(18)
    effective_user_id = (user_id or f"auth-test-{token_hash[:8]}").strip()
    access_token = _build_test_access_token(user_id=effective_user_id, email=normalized_email)
    refresh_token = f"auth-test-refresh-{secrets.token_urlsafe(18)}"
    payload = {
        "email": normalized_email,
        "user_id": effective_user_id,
        "token_hash": token_hash,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "callback_url": callback_url,
        "link": _build_magic_link_verify_url(verify_base_url, callback_url, token_hash),
    }

    with _STATE_LOCK:
        _MAGIC_LINKS_BY_TOKEN[token_hash] = payload
        _MAGIC_LINKS_BY_EMAIL.setdefault(normalized_email, []).append(payload)
        _ACCESS_TOKENS[access_token] = {
            "id": str(payload["user_id"]),
            "email": normalized_email,
        }

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


def resolve_test_access_token(access_token: str):
    normalized_token = (access_token or "").strip()
    if not normalized_token:
        return None
    with _STATE_LOCK:
        payload = _ACCESS_TOKENS.get(normalized_token)
        return dict(payload) if payload else None


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
