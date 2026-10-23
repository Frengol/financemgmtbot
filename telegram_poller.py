"""Telegram long-polling component (APP_COMPONENT=telegram-poller).

Start with `python -m telegram_poller`; `python -m telegram_poller --check` is the
container healthcheck. Module scope stays stdlib-only so the healthcheck never
imports config, which requires every secret and builds the provider clients.
"""

import asyncio
import contextlib
import logging
import signal
import sys
import time
from pathlib import Path


HEARTBEAT_PATH = Path("/tmp/telegram-poller.heartbeat")
HEARTBEAT_MAX_AGE_SECONDS = 300
RETRY_INITIAL_DELAY_SECONDS = 5
RETRY_MAX_DELAY_SECONDS = 120
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
USAGE = "usage: python -m telegram_poller [--check]"


class _Stopped(Exception):
    pass


def retry_delay(attempt):
    return min(RETRY_INITIAL_DELAY_SECONDS * 2 ** (attempt - 1), RETRY_MAX_DELAY_SECONDS)


def write_heartbeat(path=None):
    (path or HEARTBEAT_PATH).touch()


def check_heartbeat(path=None):
    try:
        age = time.time() - (path or HEARTBEAT_PATH).stat().st_mtime
    except OSError:
        return EXIT_FAILURE
    return EXIT_OK if age < HEARTBEAT_MAX_AGE_SECONDS else EXIT_FAILURE


def quiet_http_loggers():
    # httpx logs every request URL at INFO, and Bot API URLs embed the bot token.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


async def wait_for_stop(stop_event, seconds):
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return False
    return True


async def _unless_stopped(stop_event, call):
    request = asyncio.ensure_future(call())
    stopper = asyncio.ensure_future(stop_event.wait())
    try:
        await asyncio.wait({request, stopper}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopper.cancel()
    if request.done():
        return request.result()
    request.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await request
    raise _Stopped


async def run_poller(
    *,
    get_updates,
    get_webhook_info,
    process_update,
    stop_event,
    max_attempts,
    wait_or_stop=None,
    heartbeat=write_heartbeat,
):
    """Read updates with getUpdates and process them one at a time, in order.

    The offset only moves past an update once processing reports DONE (or the
    retries run out), so an interrupted update is redelivered after a restart;
    the ledger makes that redelivery idempotent.
    """
    from config import logger
    from telegram_service import TelegramPermanentError
    from telegram_update_processor import UpdateOutcome, UpdateResult, extract_update_id

    if wait_or_stop is None:

        async def wait_or_stop(seconds):
            return await wait_for_stop(stop_event, seconds)

    startup_failures = 0
    while True:
        try:
            webhook_info = await _unless_stopped(stop_event, get_webhook_info)
            break
        except _Stopped:
            return EXIT_OK
        except TelegramPermanentError as exc:
            logger.critical({"event": "telegram_poller_startup_rejected", "status_code": exc.status_code})
            return EXIT_FAILURE
        except Exception as exc:
            startup_failures += 1
            logger.warning({"event": "telegram_poller_startup_check_failed", "error_code": type(exc).__name__})
            if await wait_or_stop(retry_delay(startup_failures)):
                return EXIT_OK
    if (webhook_info or {}).get("url"):
        # getUpdates and webhooks are mutually exclusive; never remove a webhook from here.
        logger.critical({"event": "telegram_poller_webhook_active"})
        return EXIT_FAILURE

    logger.info({"event": "telegram_poller_started", "max_attempts": max_attempts})

    async def process_with_retries(update, update_id):
        attempt = 0
        while True:
            attempt += 1
            heartbeat()
            try:
                # A task runs in a copy of the context, so per-update log correlation stays inside it.
                result = await asyncio.ensure_future(process_update(update))
            except Exception as exc:
                logger.error(
                    {"event": "telegram_poller_process_error", "update_id": update_id, "error_code": type(exc).__name__}
                )
                result = UpdateResult(UpdateOutcome.RETRY, "PROCESSOR_ERROR")
            if result.outcome is UpdateOutcome.DONE:
                return True
            if attempt >= max_attempts:
                logger.error(
                    {
                        "event": "telegram_update_retry_exhausted",
                        "update_id": update_id,
                        "attempts": attempt,
                        "last_code": result.code,
                    }
                )
                return True
            delay = retry_delay(attempt)
            logger.warning(
                {
                    "event": "telegram_update_retry_scheduled",
                    "update_id": update_id,
                    "attempt": attempt,
                    "code": result.code,
                    "delay_seconds": delay,
                }
            )
            if await wait_or_stop(delay):
                return False

    offset = None
    fetch_failures = 0
    while not stop_event.is_set():
        heartbeat()
        try:
            updates = await _unless_stopped(stop_event, lambda: get_updates(offset))
        except _Stopped:
            break
        except TelegramPermanentError as exc:
            event = "telegram_poller_conflict" if exc.status_code == 409 else "telegram_poller_rejected"
            logger.critical({"event": event, "status_code": exc.status_code})
            return EXIT_FAILURE
        except Exception as exc:
            fetch_failures += 1
            logger.warning(
                {
                    "event": "telegram_poller_fetch_failed",
                    "error_code": type(exc).__name__,
                    "consecutive_failures": fetch_failures,
                }
            )
            if await wait_or_stop(retry_delay(fetch_failures)):
                break
            continue
        fetch_failures = 0

        for update in updates:
            update_id = extract_update_id(update)
            if update_id is None:
                logger.error({"event": "telegram_poller_invalid_update"})
                continue
            if not await process_with_retries(update, update_id):
                return EXIT_OK
            offset = update_id + 1
            heartbeat()
            if stop_event.is_set():
                break

    logger.info({"event": "telegram_poller_stopped"})
    return EXIT_OK


async def main():
    import config

    if config.APP_COMPONENT != "telegram-poller":
        config.logger.critical({"event": "telegram_poller_wrong_component"})
        return EXIT_FAILURE

    from ai_service import close_ai_clients
    from telegram_service import close_http_client, init_http_client, obter_info_webhook_telegram, obter_updates_telegram
    from telegram_update_processor import default_deps, process_telegram_update

    quiet_http_loggers()
    deps = default_deps()

    async def process_update(update):
        return await process_telegram_update(update, deps)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    stop_signals = (signal.SIGTERM, signal.SIGINT)
    for stop_signal in stop_signals:
        loop.add_signal_handler(stop_signal, stop_event.set)
    try:
        await init_http_client()
        return await run_poller(
            get_updates=obter_updates_telegram,
            get_webhook_info=obter_info_webhook_telegram,
            process_update=process_update,
            stop_event=stop_event,
            max_attempts=config.TELEGRAM_POLL_MAX_ATTEMPTS,
        )
    finally:
        for stop_signal in stop_signals:
            loop.remove_signal_handler(stop_signal)
        await close_http_client()
        await close_ai_clients()


def cli(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ["--check"]:
        return check_heartbeat()
    if args:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    return asyncio.run(main())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(cli())
