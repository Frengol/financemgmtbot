import json
import re
from typing import Any

from quart import request

from api_responses import current_request_id, json_error, json_success, with_request_id
from config import APP_COMMIT_SHA, APP_RELEASE_SHA, K_REVISION, K_SERVICE, logger, normalize_frontend_origin
from web_app.http import origin_allowed, rate_limited


SAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")
SAFE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9/_-]{0,160}$")
MAX_TELEMETRY_BODY_BYTES = 4096
ALLOWED_TELEMETRY_FIELDS = frozenset(
    {
        "event",
        "phase",
        "clientEventId",
        "releaseId",
        "pagePath",
        "apiOrigin",
        "online",
        "httpStatus",
        "errorCode",
        "diagnostic",
        "requestId",
        "corsSuspected",
    }
)


def _json_error(message: str, status_code: int, *, code: str, detail: str | None = None):
    return json_error(message, status_code, code=code, detail=detail)


def _validate_safe_token(value: Any, *, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise ValueError(f"missing_{field_name}")
        return None

    candidate = str(value).strip()
    if not SAFE_TOKEN_PATTERN.fullmatch(candidate):
        raise ValueError(f"invalid_{field_name}")
    return candidate


def _validate_page_path(value: Any):
    if value in (None, ""):
        return None
    candidate = str(value).strip()
    if not SAFE_PATH_PATTERN.fullmatch(candidate):
        raise ValueError("invalid_page_path")
    return candidate


def _validate_api_origin(value: Any):
    if value in (None, ""):
        return None
    normalized = normalize_frontend_origin(str(value))
    if not normalized.startswith(("http://", "https://")):
        raise ValueError("invalid_api_origin")
    return normalized


def _validate_http_status(value: Any):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("invalid_http_status")
    try:
        candidate = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_http_status") from exc
    if candidate < 0 or candidate > 599:
        raise ValueError("invalid_http_status")
    return candidate


def _validate_boolean(value: Any, *, field_name: str):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"invalid_{field_name}")


async def _parse_client_telemetry_payload():
    raw_bytes = await request.get_data(cache=True)
    if len(raw_bytes) > MAX_TELEMETRY_BODY_BYTES:
        raise ValueError("payload_too_large")

    payload = await request.get_json(silent=True)
    if payload is None:
        raw_text = raw_bytes.decode("utf-8", errors="ignore").strip()
        if not raw_text:
            raise ValueError("missing_payload")
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid_json") from exc

    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    return payload


def _normalize_client_telemetry_payload(payload: dict[str, Any]):
    unexpected_fields = sorted(set(payload) - ALLOWED_TELEMETRY_FIELDS)
    if unexpected_fields:
        raise ValueError("unexpected_fields")

    return {
        "event": _validate_safe_token(payload.get("event"), field_name="event", required=True),
        "phase": _validate_safe_token(payload.get("phase"), field_name="phase", required=True),
        "clientEventId": _validate_safe_token(payload.get("clientEventId"), field_name="client_event_id", required=True),
        "releaseId": _validate_safe_token(payload.get("releaseId"), field_name="release_id"),
        "pagePath": _validate_page_path(payload.get("pagePath")),
        "apiOrigin": _validate_api_origin(payload.get("apiOrigin")),
        "online": _validate_boolean(payload.get("online"), field_name="online"),
        "httpStatus": _validate_http_status(payload.get("httpStatus")),
        "errorCode": _validate_safe_token(payload.get("errorCode"), field_name="error_code"),
        "diagnostic": _validate_safe_token(payload.get("diagnostic"), field_name="diagnostic"),
        "requestId": _validate_safe_token(payload.get("requestId"), field_name="request_id"),
        "corsSuspected": _validate_boolean(payload.get("corsSuspected"), field_name="cors_suspected"),
    }


def register_observability_routes(app):
    @app.route("/api/meta/runtime", methods=["GET", "OPTIONS"])
    async def runtime_meta():
        if request.method == "OPTIONS":
            return "", 204
        return json_success(
            {
                "requestId": current_request_id(),
                "commitSha": APP_COMMIT_SHA or None,
                "releaseSha": APP_RELEASE_SHA or None,
                "service": K_SERVICE or None,
                "revision": K_REVISION or None,
            }
        )

    @app.route("/api/client-telemetry", methods=["POST", "OPTIONS"])
    async def client_telemetry():
        if request.method == "OPTIONS":
            return "", 204

        origin = normalize_frontend_origin(request.headers.get("Origin") or "")
        if not origin or not origin_allowed(origin):
            return _json_error(
                "Client telemetry origin is not allowed.",
                403,
                code="CLIENT_TELEMETRY_ORIGIN_DENIED",
                detail="origin_not_allowed",
            )

        remote_addr = (request.remote_addr or "").strip() or "unknown"
        rate_limited_response = rate_limited(
            "client-telemetry",
            f"{origin}:{remote_addr}",
            limit=60,
            window_seconds=60,
            code="CLIENT_TELEMETRY_RATE_LIMITED",
            message="Too many telemetry events. Try again later.",
        )
        if rate_limited_response is not None:
            return rate_limited_response

        try:
            payload = await _parse_client_telemetry_payload()
            normalized_payload = _normalize_client_telemetry_payload(payload)
        except ValueError as exc:
            return _json_error(
                "Client telemetry payload is invalid.",
                400,
                code="CLIENT_TELEMETRY_INVALID",
                detail=str(exc),
            )

        logger.info(
            with_request_id(
                {
                    "event": "browser_client_telemetry",
                    "origin": origin,
                    "client_event_id": normalized_payload["clientEventId"],
                    "release_id": normalized_payload["releaseId"],
                    "phase": normalized_payload["phase"],
                    "frontend_event": normalized_payload["event"],
                    "page_path": normalized_payload["pagePath"],
                    "api_origin": normalized_payload["apiOrigin"],
                    "online": normalized_payload["online"],
                    "http_status": normalized_payload["httpStatus"],
                    "error_code": normalized_payload["errorCode"],
                    "diagnostic": normalized_payload["diagnostic"],
                    "backend_request_id": normalized_payload["requestId"],
                    "cors_suspected": normalized_payload["corsSuspected"],
                    "commit_sha": APP_COMMIT_SHA or None,
                    "service": K_SERVICE or None,
                    "revision": K_REVISION or None,
                }
            )
        )
        return json_success({"accepted": True}, 202)
