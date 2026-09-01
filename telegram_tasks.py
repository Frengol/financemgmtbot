import hashlib
import json
import os
from dataclasses import dataclass

from google.api_core.exceptions import AlreadyExists
from google.protobuf import duration_pb2

try:
    from google.cloud import tasks_v2
except ImportError:  # Allows injected clients in local tests before dependencies are installed.
    tasks_v2 = None

from config import logger


MAX_TASK_BODY_BYTES = 75_000
TASK_DISPATCH_DEADLINE_SECONDS = 220


class InvalidTelegramUpdate(ValueError):
    pass


@dataclass(frozen=True)
class EnqueueResult:
    task_name: str
    created: bool
    duplicate: bool


_client = None


def _required_setting(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required Cloud Tasks setting: {name}")
    return value


def _task_id(update_id: int) -> str:
    digest = hashlib.sha256(str(update_id).encode("ascii")).hexdigest()
    return f"telegram-{digest}"


def _serialize_update(update: object) -> tuple[int, bytes]:
    if not isinstance(update, dict):
        raise InvalidTelegramUpdate("Telegram update must be a JSON object.")
    update_id = update.get("update_id")
    if isinstance(update_id, bool) or not isinstance(update_id, int):
        raise InvalidTelegramUpdate("Telegram update_id must be an integer.")
    body = json.dumps(update, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(body) > MAX_TASK_BODY_BYTES:
        raise InvalidTelegramUpdate("Telegram update exceeds the Cloud Tasks payload limit.")
    return update_id, body


def _get_client():
    global _client
    if _client is None:
        if tasks_v2 is None:
            raise RuntimeError("google-cloud-tasks is not installed.")
        _client = tasks_v2.CloudTasksAsyncClient()
    return _client


async def enqueue_telegram_update(update: object, *, client=None) -> EnqueueResult:
    update_id, body = _serialize_update(update)
    project = _required_setting("TELEGRAM_TASKS_PROJECT")
    location = _required_setting("TELEGRAM_TASKS_LOCATION")
    queue = _required_setting("TELEGRAM_TASKS_QUEUE")
    worker_url = _required_setting("TELEGRAM_WORKER_URL").rstrip("/")
    invoker_service_account = _required_setting("TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT")
    tasks_client = client or _get_client()
    parent = tasks_client.queue_path(project, location, queue)
    task_name = f"{parent}/tasks/{_task_id(update_id)}"
    deadline = duration_pb2.Duration(seconds=TASK_DISPATCH_DEADLINE_SECONDS)
    task = {
        "name": task_name,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST if tasks_v2 is not None else 1,
            "url": f"{worker_url}/internal/tasks/telegram-update",
            "headers": {"Content-Type": "application/json"},
            "body": body,
            "oidc_token": {
                "service_account_email": invoker_service_account,
                "audience": worker_url,
            },
        },
        "dispatch_deadline": deadline,
    }
    try:
        await tasks_client.create_task(request={"parent": parent, "task": task})
    except AlreadyExists:
        logger.info({"event": "telegram_task_duplicate", "update_id": update_id})
        return EnqueueResult(task_name=task_name, created=False, duplicate=True)

    logger.info({"event": "telegram_task_enqueued", "update_id": update_id})
    return EnqueueResult(task_name=task_name, created=True, duplicate=False)
