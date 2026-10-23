from quart import Quart, jsonify, request

from config import TELEGRAM_ALLOWED_USER_IDS
from handlers import processar_update_assincrono
from telegram_service import editar_mensagem_telegram
from telegram_update_ledger import (
    claim_update,
    mark_completed,
    mark_failed,
    mark_terminal_failed,
    prepare_terminal_failure,
    reserve_ocr_round,
    reset_ocr_rounds,
    update_stage,
)
from telegram_update_processor import (
    OCR_MAX_ROUNDS,
    OCR_REJECTED_MESSAGE,
    OCR_TERMINAL_MESSAGE,
    WORKER_FINALIZATION_RESERVE_SECONDS,
    WORKER_PROCESSING_BUDGET_SECONDS,
    WORKER_TOTAL_BUDGET_SECONDS,
    ProcessorDeps,
    UpdateOutcome,
    edit_terminal_progress,
    extract_update_id,
    process_telegram_update,
)


MAX_WORKER_BODY_BYTES = 75_000


def _deps():
    # Resolved from this module's globals on every request so the route keeps
    # the same patch points it had before processing moved to the processor.
    return ProcessorDeps(
        claim_update=claim_update,
        update_stage=update_stage,
        mark_completed=mark_completed,
        mark_failed=mark_failed,
        mark_terminal_failed=mark_terminal_failed,
        prepare_terminal_failure=prepare_terminal_failure,
        reserve_ocr_round=reserve_ocr_round,
        reset_ocr_rounds=reset_ocr_rounds,
        processar_update_assincrono=processar_update_assincrono,
        editar_mensagem_telegram=editar_mensagem_telegram,
        allowed_user_ids=TELEGRAM_ALLOWED_USER_IDS,
    )


async def _edit_terminal_progress(update, progress_message_id, terminal_reason):
    return await edit_terminal_progress(
        update,
        progress_message_id,
        terminal_reason,
        editar_mensagem_telegram=editar_mensagem_telegram,
    )


def _result_response(result):
    done = result.outcome is UpdateOutcome.DONE
    body = {"status": "ok" if done else "retry"}
    if result.code:
        body["code"] = result.code
    return jsonify(body), 200 if done else 503


def register_worker_routes(app):
    @app.post("/internal/tasks/telegram-update")
    async def telegram_update_task():
        task_name = (request.headers.get("X-CloudTasks-TaskName") or "").strip()
        queue_name = (request.headers.get("X-CloudTasks-QueueName") or "").strip()
        if not task_name or not queue_name:
            return jsonify({"status": "error", "code": "TASK_HEADERS_REQUIRED"}), 403
        if request.mimetype != "application/json":
            return jsonify({"status": "error", "code": "JSON_REQUIRED"}), 415
        if (request.content_length or 0) > MAX_WORKER_BODY_BYTES:
            return jsonify({"status": "error", "code": "TASK_TOO_LARGE"}), 413

        update = await request.get_json(silent=True)
        if extract_update_id(update) is None:
            return jsonify({"status": "error", "code": "INVALID_UPDATE"}), 400

        return _result_response(await process_telegram_update(update, _deps()))


def create_worker_app_for_test():
    app = Quart("telegram-worker-test")
    register_worker_routes(app)
    return app
