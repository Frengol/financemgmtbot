import asyncio
import enum
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable

from ai_service import AIProviderPermanentError, AIProviderRetryableError
from config import logger
from telegram_correlation import bind_telegram_update, with_error_reference
from telegram_service import TelegramPermanentError, TelegramRetryableError
from telegram_update_ledger import OCRRoundLimitReached


WORKER_TOTAL_BUDGET_SECONDS = 200
WORKER_FINALIZATION_RESERVE_SECONDS = 20
WORKER_PROCESSING_BUDGET_SECONDS = WORKER_TOTAL_BUDGET_SECONDS - WORKER_FINALIZATION_RESERVE_SECONDS
OCR_MAX_ROUNDS = 3
OCR_TERMINAL_MESSAGE = (
    "⚠️ *O serviço de leitura está temporariamente indisponível.*\n"
    "Não foi possível concluir este envio. Tente novamente mais tarde."
)
OCR_REJECTED_MESSAGE = (
    "❌ *Não foi possível interpretar este cupom.*\n"
    "Verifique a imagem e envie novamente quando quiser tentar de novo."
)


class UpdateOutcome(enum.Enum):
    DONE = "done"
    RETRY = "retry"


@dataclass(frozen=True)
class UpdateResult:
    outcome: UpdateOutcome
    code: str | None = None


@dataclass(frozen=True)
class ProcessorDeps:
    claim_update: Callable[..., Any]
    update_stage: Callable[..., Any]
    mark_completed: Callable[..., Any]
    mark_failed: Callable[..., Any]
    mark_terminal_failed: Callable[..., Any]
    prepare_terminal_failure: Callable[..., Any]
    reserve_ocr_round: Callable[..., Any]
    reset_ocr_rounds: Callable[..., Any]
    processar_update_assincrono: Callable[..., Any]
    editar_mensagem_telegram: Callable[..., Any]
    allowed_user_ids: frozenset[int] | None = None


def default_deps():
    import config
    import handlers
    import telegram_service
    import telegram_update_ledger

    return ProcessorDeps(
        claim_update=telegram_update_ledger.claim_update,
        update_stage=telegram_update_ledger.update_stage,
        mark_completed=telegram_update_ledger.mark_completed,
        mark_failed=telegram_update_ledger.mark_failed,
        mark_terminal_failed=telegram_update_ledger.mark_terminal_failed,
        prepare_terminal_failure=telegram_update_ledger.prepare_terminal_failure,
        reserve_ocr_round=telegram_update_ledger.reserve_ocr_round,
        reset_ocr_rounds=telegram_update_ledger.reset_ocr_rounds,
        processar_update_assincrono=handlers.processar_update_assincrono,
        editar_mensagem_telegram=telegram_service.editar_mensagem_telegram,
        allowed_user_ids=config.TELEGRAM_ALLOWED_USER_IDS,
    )


DONE = UpdateResult(UpdateOutcome.DONE)
# Per-process key: rejected senders can be grouped within one run, but the
# reference cannot be reversed by hashing every possible Telegram user id.
_SENDER_REFERENCE_KEY = secrets.token_bytes(32)


def extract_update_id(update):
    update_id = update.get("update_id") if isinstance(update, dict) else None
    if isinstance(update_id, bool) or not isinstance(update_id, int):
        return None
    return update_id


def _sender_user_id(update):
    # handlers.processar_update_assincrono takes the callback branch whenever the key is present,
    # so the sender must come from the same payload; never fall through to another one.
    for kind in ("callback_query", "message"):
        if kind in update:
            payload = update[kind]
            sender = payload.get("from") if isinstance(payload, dict) else None
            sender_id = sender.get("id") if isinstance(sender, dict) else None
            return sender_id if type(sender_id) is int else None
    return None


def sender_reference(user_id):
    if user_id is None:
        return None
    digest = hmac.new(_SENDER_REFERENCE_KEY, str(user_id).encode("ascii"), hashlib.sha256)
    return digest.hexdigest()[:12]


def _error_code(exc):
    value = getattr(exc, "error_code", None)
    if isinstance(value, (str, int)) and str(value).strip():
        return str(value).strip()[:80]
    return type(exc).__name__[:80]


def _terminal_message(reason):
    if reason == "ocr_unavailable":
        return OCR_TERMINAL_MESSAGE
    if reason == "ocr_rejected":
        return OCR_REJECTED_MESSAGE
    return None


def _terminal_destination(update, progress_message_id):
    if progress_message_id is None:
        return None
    message = update.get("message") if isinstance(update, dict) else None
    chat = message.get("chat") if isinstance(message, dict) else None
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    if chat_id is None:
        return None
    return chat_id, progress_message_id


async def edit_terminal_progress(update, progress_message_id, terminal_reason, *, editar_mensagem_telegram):
    message = _terminal_message(terminal_reason)
    destination = _terminal_destination(update, progress_message_id)
    if message is None or destination is None:
        return False
    chat_id, message_id = destination
    await editar_mensagem_telegram(
        chat_id,
        message_id,
        with_error_reference(message, update_id=update.get("update_id")),
    )
    return True


async def finish_terminal_notice(deps, update_id, lease_owner, update, progress_message_id, reason, error_code):
    try:
        delivery_confirmed = await edit_terminal_progress(
            update,
            progress_message_id,
            reason,
            editar_mensagem_telegram=deps.editar_mensagem_telegram,
        )
    except TelegramRetryableError as exc:
        await deps.mark_failed(
            update_id,
            lease_owner,
            stage="telegram_delivery",
            error_code="terminal_notice_retryable",
        )
        logger.warning(
            {
                "event": "telegram_terminal_notice_retryable",
                "update_id": update_id,
                "terminal_reason": reason,
                "error_code": type(exc).__name__,
            }
        )
        return UpdateResult(UpdateOutcome.RETRY, "TERMINAL_NOTICE_RETRY")
    except TelegramPermanentError as exc:
        await deps.mark_terminal_failed(
            update_id,
            lease_owner,
            stage="telegram_delivery",
            error_code="terminal_notice_permanent",
            delivery_confirmed=False,
        )
        logger.warning(
            {
                "event": "telegram_terminal_notice_unconfirmed",
                "update_id": update_id,
                "terminal_reason": reason,
                "error_code": type(exc).__name__,
            }
        )
        return UpdateResult(UpdateOutcome.DONE, "TERMINAL_NOTICE_UNDELIVERABLE")
    except Exception as exc:
        await deps.mark_failed(
            update_id,
            lease_owner,
            stage="telegram_delivery",
            error_code="terminal_notice_error",
        )
        logger.error(
            {
                "event": "telegram_terminal_notice_failed",
                "update_id": update_id,
                "terminal_reason": reason,
                "error_code": type(exc).__name__,
            }
        )
        return UpdateResult(UpdateOutcome.RETRY, "TERMINAL_NOTICE_RETRY")

    await deps.mark_terminal_failed(
        update_id,
        lease_owner,
        stage="telegram_delivery",
        error_code=error_code,
        delivery_confirmed=delivery_confirmed,
    )
    logger.info(
        {
            "event": "telegram_update_terminal_failure",
            "update_id": update_id,
            "terminal_reason": reason,
            "delivery_confirmed": delivery_confirmed,
            "error_code": error_code,
        }
    )
    return UpdateResult(UpdateOutcome.DONE, "TERMINAL_FAILURE")


def _ledger_unavailable(update_id, target_status, exc):
    logger.error(
        {
            "event": "telegram_ledger_transition_failed",
            "update_id": update_id,
            "target_status": target_status,
            "error_code": type(exc).__name__,
        }
    )
    return UpdateResult(UpdateOutcome.RETRY, "LEDGER_UNAVAILABLE")


async def process_telegram_update(update, deps: ProcessorDeps) -> UpdateResult:
    """Process one validated Telegram update through the idempotency ledger.

    Shared by the Cloud Tasks worker route and the long-polling component, so
    both delivery modes keep identical ledger transitions and logs.
    """
    started_at = time.monotonic()
    total_deadline = started_at + WORKER_TOTAL_BUDGET_SECONDS
    processing_deadline = total_deadline - WORKER_FINALIZATION_RESERVE_SECONDS
    update_id = update["update_id"]
    bind_telegram_update(update_id)

    if deps.allowed_user_ids is not None:
        sender_id = _sender_user_id(update)
        if sender_id not in deps.allowed_user_ids:
            # Dropped before the ledger: strangers cause no reply, AI call or database write.
            logger.warning(
                {
                    "event": "telegram_update_sender_rejected",
                    "update_id": update_id,
                    "sender_ref": sender_reference(sender_id),
                }
            )
            return DONE

    lease_owner = secrets.token_hex(16)
    try:
        claim = await deps.claim_update(update_id, lease_owner)
    except Exception as exc:
        logger.error(
            {
                "event": "telegram_ledger_claim_failed",
                "update_id": update_id,
                "error_code": type(exc).__name__,
            }
        )
        return UpdateResult(UpdateOutcome.RETRY, "LEDGER_UNAVAILABLE")
    if not claim.claimed:
        if claim.status in {"completed", "terminal_failed"}:
            logger.info({"event": "telegram_update_already_final", "update_id": update_id, "status": claim.status})
            return DONE
        logger.info({"event": "telegram_update_lease_active", "update_id": update_id})
        return UpdateResult(UpdateOutcome.RETRY, "LEASE_ACTIVE")

    if claim.terminal_reason:
        try:
            async with asyncio.timeout_at(total_deadline):
                return await finish_terminal_notice(
                    deps,
                    update_id,
                    lease_owner,
                    update,
                    claim.progress_message_id,
                    claim.terminal_reason,
                    claim.error_code or claim.terminal_reason,
                )
        except Exception as exc:
            return _ledger_unavailable(update_id, "terminal_failed", exc)

    stage = "processing"
    current_progress_message_id = claim.progress_message_id
    current_ocr_round = claim.ocr_round_count
    stage_started_at = time.monotonic()

    async def record_stage(next_stage, progress_message_id=None):
        nonlocal stage, stage_started_at, current_progress_message_id
        now = time.monotonic()
        logger.info(
            {
                "event": "telegram_update_stage",
                "update_id": update_id,
                "attempt": claim.attempt_count,
                "stage": next_stage,
                "duration_ms": round((now - stage_started_at) * 1000),
            }
        )
        stage = next_stage
        stage_started_at = now
        if progress_message_id is not None:
            current_progress_message_id = progress_message_id
        await deps.update_stage(
            update_id,
            lease_owner,
            next_stage,
            progress_message_id=progress_message_id,
        )

    async def reserve_round():
        nonlocal current_ocr_round
        current_ocr_round = await deps.reserve_ocr_round(update_id, lease_owner)
        logger.info(
            {
                "event": "telegram_ocr_round_reserved",
                "update_id": update_id,
                "attempt": claim.attempt_count,
                "ocr_round": current_ocr_round,
            }
        )
        return current_ocr_round

    async def confirm_ocr_success():
        nonlocal current_ocr_round
        await deps.reset_ocr_rounds(update_id, lease_owner)
        current_ocr_round = 0

    async def finish_prepared_terminal(reason, error_code):
        async with asyncio.timeout_at(total_deadline):
            await deps.prepare_terminal_failure(
                update_id,
                lease_owner,
                reason=reason,
                error_code=error_code,
            )
            return await finish_terminal_notice(
                deps,
                update_id,
                lease_owner,
                update,
                current_progress_message_id,
                reason,
                error_code,
            )

    try:
        async with asyncio.timeout_at(processing_deadline):
            await deps.processar_update_assincrono(
                update,
                source_update_id=update_id,
                progress_message_id=current_progress_message_id,
                stage_callback=record_stage,
                worker_attempt=claim.attempt_count,
                ocr_round_callback=reserve_round,
                ocr_success_callback=confirm_ocr_success,
                processing_deadline_monotonic=processing_deadline,
            )
        async with asyncio.timeout_at(total_deadline):
            await deps.mark_completed(update_id, lease_owner)
    except AIProviderPermanentError as exc:
        try:
            return await finish_prepared_terminal("ocr_rejected", _error_code(exc))
        except Exception as transition_exc:
            return _ledger_unavailable(update_id, "terminal_delivery_pending", transition_exc)
    except TelegramPermanentError as exc:
        try:
            async with asyncio.timeout_at(total_deadline):
                await deps.prepare_terminal_failure(
                    update_id,
                    lease_owner,
                    reason="telegram_delivery_permanent",
                    error_code=_error_code(exc),
                )
                await deps.mark_terminal_failed(
                    update_id,
                    lease_owner,
                    stage="telegram_delivery",
                    error_code=_error_code(exc),
                    delivery_confirmed=False,
                )
        except Exception as transition_exc:
            return _ledger_unavailable(update_id, "terminal_failed", transition_exc)
        logger.warning(
            {
                "event": "telegram_update_terminal_failure",
                "update_id": update_id,
                "terminal_reason": "telegram_delivery_permanent",
                "delivery_confirmed": False,
                "error_code": _error_code(exc),
            }
        )
        return UpdateResult(UpdateOutcome.DONE, "TERMINAL_FAILURE")
    except Exception as exc:
        terminal_ocr_failure = isinstance(exc, OCRRoundLimitReached) or (
            isinstance(exc, AIProviderRetryableError)
            and stage == "ocr"
            and current_ocr_round >= OCR_MAX_ROUNDS
        )
        if terminal_ocr_failure:
            try:
                return await finish_prepared_terminal("ocr_unavailable", _error_code(exc))
            except Exception as transition_exc:
                return _ledger_unavailable(update_id, "terminal_delivery_pending", transition_exc)
        try:
            async with asyncio.timeout_at(total_deadline):
                await deps.mark_failed(
                    update_id,
                    lease_owner,
                    stage=stage,
                    error_code=_error_code(exc),
                )
        except Exception as transition_exc:
            logger.error(
                {
                    "event": "telegram_ledger_transition_failed",
                    "update_id": update_id,
                    "target_status": "retryable_failed",
                    "error_code": type(transition_exc).__name__,
                }
            )
        logger.error(
            {
                "event": "telegram_update_retryable_failure",
                "update_id": update_id,
                "attempt": claim.attempt_count,
                "stage": stage,
                "error_code": _error_code(exc),
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            }
        )
        return UpdateResult(UpdateOutcome.RETRY, "PROCESSING_FAILED")

    logger.info(
        {
            "event": "telegram_update_completed",
            "update_id": update_id,
            "attempt": claim.attempt_count,
            "duration_ms": round((time.monotonic() - started_at) * 1000),
        }
    )
    return DONE
