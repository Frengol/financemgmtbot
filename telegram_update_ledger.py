import asyncio
from dataclasses import dataclass

from config import supabase


LEASE_SECONDS = 300
TERMINAL_REASONS = frozenset({"ocr_unavailable", "ocr_rejected", "telegram_delivery_permanent"})


class OCRRoundLimitReached(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateClaim:
    claimed: bool
    status: str
    attempt_count: int
    progress_message_id: int | None
    ocr_round_count: int = 0
    terminal_reason: str | None = None
    error_code: str | None = None


def _first_row(response):
    data = getattr(response, "data", None)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise RuntimeError("Ledger RPC returned an invalid response.")
    return data[0]


def _require_transition(response):
    data = getattr(response, "data", None)
    accepted = data is True or data == [True]
    if not accepted:
        raise RuntimeError("Ledger transition rejected.")


async def claim_update(update_id: int, lease_owner: str, *, client=None) -> UpdateClaim:
    db = client or supabase
    response = await asyncio.to_thread(
        lambda: db.rpc(
            "claim_webhook_update_v2",
            {
                "p_update_id": update_id,
                "p_lease_owner": lease_owner,
                "p_lease_seconds": LEASE_SECONDS,
            },
        ).execute()
    )
    row = _first_row(response)
    return UpdateClaim(
        claimed=bool(row.get("claimed")),
        status=str(row.get("status") or "unknown"),
        attempt_count=int(row.get("attempt_count") or 0),
        progress_message_id=int(row["progress_message_id"]) if row.get("progress_message_id") is not None else None,
        ocr_round_count=int(row.get("ocr_round_count") or 0),
        terminal_reason=str(row["terminal_reason"]) if row.get("terminal_reason") is not None else None,
        error_code=str(row["error_code"]) if row.get("error_code") is not None else None,
    )


async def update_stage(update_id: int, lease_owner: str, stage: str, *, progress_message_id: int | None = None):
    response = await asyncio.to_thread(
        lambda: supabase.rpc(
            "update_webhook_stage_v2",
            {
                "p_update_id": update_id,
                "p_lease_owner": lease_owner,
                "p_stage": stage,
                "p_progress_message_id": progress_message_id,
            },
        ).execute()
    )
    _require_transition(response)


async def mark_completed(update_id: int, lease_owner: str):
    response = await asyncio.to_thread(
        lambda: supabase.rpc(
            "complete_webhook_update_v2",
            {"p_update_id": update_id, "p_lease_owner": lease_owner},
        ).execute()
    )
    _require_transition(response)


async def mark_failed(update_id: int, lease_owner: str, *, stage: str, error_code: str):
    response = await asyncio.to_thread(
        lambda: supabase.rpc(
            "fail_webhook_update_v2",
            {
                "p_update_id": update_id,
                "p_lease_owner": lease_owner,
                "p_stage": stage,
                "p_error_code": error_code[:80],
            },
        ).execute()
    )
    _require_transition(response)


async def reserve_ocr_round(update_id: int, lease_owner: str) -> int:
    response = await asyncio.to_thread(
        lambda: supabase.rpc(
            "reserve_webhook_ocr_round_v2",
            {"p_update_id": update_id, "p_lease_owner": lease_owner},
        ).execute()
    )
    row = _first_row(response)
    round_count = int(row.get("ocr_round_count") or 0)
    if not bool(row.get("reserved")):
        if round_count >= 3:
            raise OCRRoundLimitReached("OCR round limit reached.")
        raise RuntimeError("OCR round reservation rejected.")
    return round_count


async def reset_ocr_rounds(update_id: int, lease_owner: str):
    response = await asyncio.to_thread(
        lambda: supabase.rpc(
            "reset_webhook_ocr_rounds_v2",
            {"p_update_id": update_id, "p_lease_owner": lease_owner},
        ).execute()
    )
    _require_transition(response)


async def prepare_terminal_failure(
    update_id: int,
    lease_owner: str,
    *,
    reason: str,
    error_code: str,
):
    if reason not in TERMINAL_REASONS:
        raise ValueError("Unsupported terminal reason.")
    response = await asyncio.to_thread(
        lambda: supabase.rpc(
            "prepare_webhook_terminal_failure_v2",
            {
                "p_update_id": update_id,
                "p_lease_owner": lease_owner,
                "p_terminal_reason": reason,
                "p_error_code": error_code[:80],
            },
        ).execute()
    )
    _require_transition(response)


async def mark_terminal_failed(
    update_id: int,
    lease_owner: str,
    *,
    stage: str,
    error_code: str,
    delivery_confirmed: bool,
):
    response = await asyncio.to_thread(
        lambda: supabase.rpc(
            "terminal_fail_webhook_update_v2",
            {
                "p_update_id": update_id,
                "p_lease_owner": lease_owner,
                "p_stage": stage,
                "p_error_code": error_code[:80],
                "p_delivery_confirmed": delivery_confirmed,
            },
        ).execute()
    )
    _require_transition(response)
