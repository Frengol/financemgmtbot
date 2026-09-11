import logging

import pytest
from quart import Quart

import telegram_correlation


def test_correlation_id_is_stable_and_does_not_expose_update_id():
    first = telegram_correlation.correlation_id_for_update(611390412)
    repeated = telegram_correlation.correlation_id_for_update(611390412)
    other = telegram_correlation.correlation_id_for_update(611390413)

    assert first == repeated
    assert first != other
    assert first.startswith("TG-")
    assert len(first) == 19
    assert first[3:].isalnum()
    assert "611390412" not in first

    with pytest.raises(ValueError, match="integer"):
        telegram_correlation.correlation_id_for_update(True)


def test_binding_outside_request_context_returns_id_without_leaking_context():
    expected = telegram_correlation.correlation_id_for_update(654)

    assert telegram_correlation.bind_telegram_update(654) == expected
    assert telegram_correlation.current_correlation_id() is None


def test_error_reference_is_appended_once():
    original = "❌ Não foi possível concluir."
    referenced = telegram_correlation.with_error_reference(original, update_id=123)

    assert referenced == f"{original}\n\nReferência: {telegram_correlation.correlation_id_for_update(123)}"
    assert telegram_correlation.with_error_reference(referenced, update_id=123) == referenced


@pytest.mark.asyncio
async def test_request_context_is_isolated_and_logging_filter_injects_reference():
    app = Quart("correlation-test")
    filter_ = telegram_correlation.TelegramCorrelationFilter()

    assert telegram_correlation.current_correlation_id() is None
    async with app.test_request_context("/"):
        expected = telegram_correlation.bind_telegram_update(321)
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
        assert filter_.filter(record) is True
        assert record.correlation_id == expected

    assert telegram_correlation.current_correlation_id() is None


@pytest.mark.asyncio
async def test_logging_filter_preserves_explicit_reference():
    app = Quart("correlation-explicit-test")
    filter_ = telegram_correlation.TelegramCorrelationFilter()

    async with app.test_request_context("/"):
        telegram_correlation.bind_telegram_update(111)
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
        record.correlation_id = "TG-EXPLICIT"

        assert filter_.filter(record) is True
        assert record.correlation_id == "TG-EXPLICIT"
