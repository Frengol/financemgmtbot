import asyncio
import secrets
import time

from quart import Quart, jsonify, request

from ai_service import AIProviderPermanentError, AIProviderRetryableError
from config import logger
from handlers import processar_update_assincrono
from telegram_service import TelegramPermanentError, TelegramRetryableError, editar_mensagem_telegram
from telegram_correlation import bind_telegram_update, with_error_reference
from telegram_update_ledger import (
    OCRRoundLimitReached,
    claim_update,
    mark_completed,
    mark_failed,
    mark_terminal_failed,
    prepare_terminal_failure,
    reserve_ocr_round,
    reset_ocr_rounds,
    update_stage,
)


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
MAX_WORKER_BODY_BYTES = 75_000


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


async def _edit_terminal_progress(update, progress_message_id, terminal_reason):
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


async def _finish_terminal_notice(update_id, lease_owner, update, progress_message_id, reason, error_code):
    try:
        delivery_confirmed = await _edit_terminal_progress(update, progress_message_id, reason)
    except TelegramRetryableError as exc:
        await mark_failed(
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
        return 503, "TERMINAL_NOTICE_RETRY"
    except TelegramPermanentError as exc:
        await mark_terminal_failed(
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
        return 200, "TERMINAL_NOTICE_UNDELIVERABLE"
    except Exception as exc:
        await mark_failed(
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
        return 503, "TERMINAL_NOTICE_RETRY"

    await mark_terminal_failed(
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
    return 200, "TERMINAL_FAILURE"


def register_worker_routes(app):
    @app.post("/internal/tasks/telegram-update")
    async def telegram_update_task():
        started_at = time.monotonic()
        total_deadline = started_at + WORKER_TOTAL_BUDGET_SECONDS
        processing_deadline = total_deadline - WORKER_FINALIZATION_RESERVE_SECONDS
        task_name = (request.headers.get("X-CloudTasks-TaskName") or "").strip()
        queue_name = (request.headers.get("X-CloudTasks-QueueName") or "").strip()
        if not task_name or not queue_name:
            return jsonify({"status": "error", "code": "TASK_HEADERS_REQUIRED"}), 403
        if request.mimetype != "application/json":
            return jsonify({"status": "error", "code": "JSON_REQUIRED"}), 415
        if (request.content_length or 0) > MAX_WORKER_BODY_BYTES:
            return jsonify({"status": "error", "code": "TASK_TOO_LARGE"}), 413

        update = await request.get_json(silent=True)
        update_id = update.get("update_id") if isinstance(update, dict) else None
        if isinstance(update_id, bool) or not isinstance(update_id, int):
            return jsonify({"status": "error", "code": "INVALID_UPDATE"}), 400
        bind_telegram_update(update_id)

        lease_owner = secrets.token_hex(16)
        try:
            claim = await claim_update(update_id, lease_owner)
        except Exception as exc:
            logger.error(
                {
                    "event": "telegram_ledger_claim_failed",
                    "update_id": update_id,
                    "error_code": type(exc).__name__,
                }
            )
            return jsonify({"status": "retry", "code": "LEDGER_UNAVAILABLE"}), 503
        if not claim.claimed:
            if claim.status in {"completed", "terminal_failed"}:
                logger.info({"event": "telegram_update_already_final", "update_id": update_id, "status": claim.status})
                return jsonify({"status": "ok"}), 200
            logger.info({"event": "telegram_update_lease_active", "update_id": update_id})
            return jsonify({"status": "retry", "code": "LEASE_ACTIVE"}), 503

        if claim.terminal_reason:
            try:
                async with asyncio.timeout_at(total_deadline):
                    status_code, response_code = await _finish_terminal_notice(
                        update_id,
                        lease_owner,
                        update,
                        claim.progress_message_id,
                        claim.terminal_reason,
                        claim.error_code or claim.terminal_reason,
                    )
            except Exception as exc:
                logger.error(
                    {
                        "event": "telegram_ledger_transition_failed",
                        "update_id": update_id,
                        "target_status": "terminal_failed",
                        "error_code": type(exc).__name__,
                    }
                )
                return jsonify({"status": "retry", "code": "LEDGER_UNAVAILABLE"}), 503
            status = "ok" if status_code == 200 else "retry"
            return jsonify({"status": status, "code": response_code}), status_code

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
            await update_stage(
                update_id,
                lease_owner,
                next_stage,
                progress_message_id=progress_message_id,
            )

        async def reserve_round():
            nonlocal current_ocr_round
            current_ocr_round = await reserve_ocr_round(update_id, lease_owner)
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
            await reset_ocr_rounds(update_id, lease_owner)
            current_ocr_round = 0

        async def finish_prepared_terminal(reason, error_code):
            async with asyncio.timeout_at(total_deadline):
                await prepare_terminal_failure(
                    update_id,
                    lease_owner,
                    reason=reason,
                    error_code=error_code,
                )
                return await _finish_terminal_notice(
                    update_id,
                    lease_owner,
                    update,
                    current_progress_message_id,
                    reason,
                    error_code,
                )

        try:
            async with asyncio.timeout_at(processing_deadline):
                await processar_update_assincrono(
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
                await mark_completed(update_id, lease_owner)
        except AIProviderPermanentError as exc:
            try:
                status_code, response_code = await finish_prepared_terminal("ocr_rejected", _error_code(exc))
            except Exception as transition_exc:
                logger.error(
                    {
                        "event": "telegram_ledger_transition_failed",
                        "update_id": update_id,
                        "target_status": "terminal_delivery_pending",
                        "error_code": type(transition_exc).__name__,
                    }
                )
                return jsonify({"status": "retry", "code": "LEDGER_UNAVAILABLE"}), 503
            status = "ok" if status_code == 200 else "retry"
            return jsonify({"status": status, "code": response_code}), status_code
        except TelegramPermanentError as exc:
            try:
                async with asyncio.timeout_at(total_deadline):
                    await prepare_terminal_failure(
                        update_id,
                        lease_owner,
                        reason="telegram_delivery_permanent",
                        error_code=_error_code(exc),
                    )
                    await mark_terminal_failed(
                        update_id,
                        lease_owner,
                        stage="telegram_delivery",
                        error_code=_error_code(exc),
                        delivery_confirmed=False,
                    )
            except Exception as transition_exc:
                logger.error(
                    {
                        "event": "telegram_ledger_transition_failed",
                        "update_id": update_id,
                        "target_status": "terminal_failed",
                        "error_code": type(transition_exc).__name__,
                    }
                )
                return jsonify({"status": "retry", "code": "LEDGER_UNAVAILABLE"}), 503
            logger.warning(
                {
                    "event": "telegram_update_terminal_failure",
                    "update_id": update_id,
                    "terminal_reason": "telegram_delivery_permanent",
                    "delivery_confirmed": False,
                    "error_code": _error_code(exc),
                }
            )
            return jsonify({"status": "ok", "code": "TERMINAL_FAILURE"}), 200
        except Exception as exc:
            terminal_ocr_failure = isinstance(exc, OCRRoundLimitReached) or (
                isinstance(exc, AIProviderRetryableError)
                and stage == "ocr"
                and current_ocr_round >= OCR_MAX_ROUNDS
            )
            if terminal_ocr_failure:
                try:
                    status_code, response_code = await finish_prepared_terminal("ocr_unavailable", _error_code(exc))
                except Exception as transition_exc:
                    logger.error(
                        {
                            "event": "telegram_ledger_transition_failed",
                            "update_id": update_id,
                            "target_status": "terminal_delivery_pending",
                            "error_code": type(transition_exc).__name__,
                        }
                    )
                    return jsonify({"status": "retry", "code": "LEDGER_UNAVAILABLE"}), 503
                status = "ok" if status_code == 200 else "retry"
                return jsonify({"status": status, "code": response_code}), status_code
            try:
                async with asyncio.timeout_at(total_deadline):
                    await mark_failed(
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
            return jsonify({"status": "retry", "code": "PROCESSING_FAILED"}), 503

        logger.info(
            {
                "event": "telegram_update_completed",
                "update_id": update_id,
                "attempt": claim.attempt_count,
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            }
        )
        return jsonify({"status": "ok"}), 200


def create_worker_app_for_test():
    app = Quart("telegram-worker-test")
    register_worker_routes(app)
    return app
