import asyncio
import secrets
import time

from quart import Quart, jsonify, request

from config import logger
from handlers import processar_update_assincrono
from telegram_service import TelegramPermanentError
from telegram_update_ledger import claim_update, mark_completed, mark_failed, mark_terminal_failed, update_stage


WORKER_PROCESSING_BUDGET_SECONDS = 150
MAX_WORKER_BODY_BYTES = 75_000


def register_worker_routes(app):
    @app.post("/internal/tasks/telegram-update")
    async def telegram_update_task():
        started_at = time.monotonic()
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

        stage = "processing"
        try:
            async def record_stage(next_stage, progress_message_id=None):
                nonlocal stage
                stage = next_stage
                await update_stage(
                    update_id,
                    lease_owner,
                    next_stage,
                    progress_message_id=progress_message_id,
                )

            async with asyncio.timeout(WORKER_PROCESSING_BUDGET_SECONDS):
                await processar_update_assincrono(
                    update,
                    source_update_id=update_id,
                    progress_message_id=claim.progress_message_id,
                    stage_callback=record_stage,
                )
            await mark_completed(update_id, lease_owner)
        except TelegramPermanentError as exc:
            try:
                await mark_terminal_failed(
                    update_id,
                    lease_owner,
                    stage=stage,
                    error_code=type(exc).__name__,
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
            logger.error(
                {
                    "event": "telegram_update_terminal_failure",
                    "update_id": update_id,
                    "attempt": claim.attempt_count,
                    "stage": stage,
                    "error_code": type(exc).__name__,
                    "duration_ms": round((time.monotonic() - started_at) * 1000),
                }
            )
            return jsonify({"status": "ok"}), 200
        except Exception as exc:
            try:
                await mark_failed(
                    update_id,
                    lease_owner,
                    stage=stage,
                    error_code=type(exc).__name__,
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
                    "error_code": type(exc).__name__,
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
