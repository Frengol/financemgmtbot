from postgrest.exceptions import APIError
from quart import request

from api_responses import with_request_id
from config import ADMIN_EMAILS, ADMIN_USER_IDS, ALLOW_LOCAL_DEV_AUTH, FRONTEND_ALLOWED_ORIGINS, logger, mascarar_segredos, supabase
from test_support import auth_test_mode_enabled, resolve_test_access_token

from .common import MAX_BEARER_TOKEN_CHARS, _extract_user_fields, _json_error, _json_success


def _extract_bearer_token():
    authorization = request.headers.get("Authorization")
    if authorization is None:
        return None

    raw_header = str(authorization).replace("\x00", "").strip()
    if not raw_header:
        return None

    parts = raw_header.split(None, 1)
    if len(parts) != 2:
        return None

    scheme, token = parts
    normalized_token = token.strip()
    if scheme.lower() != "bearer" or not normalized_token:
        return None
    if len(normalized_token) > MAX_BEARER_TOKEN_CHARS:
        return None
    return normalized_token


def _is_malformed_bearer_error(error_text: str):
    normalized = (error_text or "").lower()
    return (
        "invalid number of segments" in normalized
        or "token is malformed" in normalized
        or "jwt malformed" in normalized
    )


def _lookup_admin_user(user_id: str | None):
    if not user_id:
        return None

    if auth_test_mode_enabled():
        return {"user_id": user_id, "email": None}

    response = (
        supabase
        .table("admin_users")
        .select("user_id, email")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None)
    if not isinstance(rows, list) or not rows:
        return None
    admin_user = rows[0]
    return admin_user if isinstance(admin_user, dict) else None


def _authorize_admin_identity(user_id: str | None, email: str | None):
    try:
        admin_user = _lookup_admin_user(user_id)
    except APIError as exc:
        logger.warning(with_request_id({"event": "admin_authorization_lookup_failed", "error": mascarar_segredos(str(exc))}))
        return None, _json_error(
            "Unable to validate admin access right now.",
            503,
            code="AUTH_ACCESS_CHECK_FAILED",
            retryable=True,
        )
    except Exception as exc:
        logger.warning(with_request_id({"event": "admin_authorization_lookup_unexpected", "error": mascarar_segredos(str(exc))}))
        return None, _json_error(
            "Unable to validate admin access right now.",
            503,
            code="AUTH_ACCESS_CHECK_FAILED",
            retryable=True,
        )

    if not admin_user:
        return None, _json_error(
            "Authenticated user is not allowed to access this admin route.",
            403,
            code="AUTH_ACCESS_DENIED",
        )

    normalized_email = email.lower() if isinstance(email, str) else None
    admin_email = admin_user.get("email")
    normalized_admin_email = admin_email.lower() if isinstance(admin_email, str) else None
    effective_email = normalized_email or normalized_admin_email

    if ADMIN_USER_IDS and user_id not in ADMIN_USER_IDS:
        return None, _json_error("Authenticated user is not allowed to access this admin route.", 403, code="AUTH_ACCESS_DENIED")
    if ADMIN_EMAILS and effective_email not in ADMIN_EMAILS:
        return None, _json_error("Authenticated user is not allowed to access this admin route.", 403, code="AUTH_ACCESS_DENIED")

    return {"id": user_id, "email": effective_email}, None


def autenticar_admin_request():
    origin = request.headers.get("Origin", "")
    remote_addr = request.remote_addr or ""
    is_loopback = remote_addr in {"127.0.0.1", "::1", "localhost"}
    is_allowed_origin = origin in FRONTEND_ALLOWED_ORIGINS if origin else False
    bearer_token = _extract_bearer_token()

    if bearer_token:
        try:
            if auth_test_mode_enabled():
                auth_user = resolve_test_access_token(bearer_token)
                if not auth_user:
                    raise ValueError("Invalid test bearer token.")
                user_id, email = _extract_user_fields(auth_user)
            else:
                auth_response = supabase.auth.get_user(bearer_token)
                user_id, email = _extract_user_fields(getattr(auth_response, "user", auth_response))
        except Exception as exc:
            error_text = mascarar_segredos(str(exc))
            logger.warning(with_request_id({"event": "admin_bearer_auth_failed", "error": error_text}))
            if _is_malformed_bearer_error(error_text):
                return None, _json_error(
                    "Invalid or expired session.",
                    401,
                    code="AUTH_SESSION_TOKEN_MALFORMED",
                    detail="bearer_malformed",
                )
            return None, _json_error("Invalid or expired session.", 401, code="AUTH_SESSION_INVALID")

        return _authorize_admin_identity(user_id, email)

    if ALLOW_LOCAL_DEV_AUTH and (is_allowed_origin or is_loopback):
        return {"id": "local-dev", "email": "local-dev@localhost"}, None

    return None, _json_error("Invalid or expired session.", 401, code="AUTH_SESSION_INVALID")


def obter_admin_atual():
    actor, auth_error = autenticar_admin_request()
    if auth_error:
        return auth_error

    return _json_success(
        {
            "authenticated": True,
            "authorized": True,
            "user": actor,
        },
        200,
    )
