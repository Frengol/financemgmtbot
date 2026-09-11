import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import receipt_ocr_contract
from scripts import evaluate_gemini_receipt_models as evaluation


def test_shared_ocr_contract_keeps_models_prompt_and_safe_http_configuration():
    assert receipt_ocr_contract.GEMINI_OCR_MODELS == (
        ("gemini-3.5-flash", 60),
        ("gemini-3.5-flash-lite", 45),
    )
    assert "Desconto Global:" in receipt_ocr_contract.RECEIPT_OCR_PROMPT
    assert "Pagamento:" in receipt_ocr_contract.RECEIPT_OCR_PROMPT

    config = receipt_ocr_contract.build_generate_content_config(45)
    assert config.thinking_config.thinking_level == "MINIMAL"
    assert config.http_options.timeout == 45_000
    assert config.http_options.retry_options.attempts == 1

    with pytest.raises(ValueError, match="positive"):
        receipt_ocr_contract.build_generate_content_config(0)


def test_parse_and_compare_exact_receipt_result():
    text = """
    Arroz | 24.90 | 0.00
    Leite | 10.98 | 1.00
    Café | 15.79 | 2.30
    Banana | 5.10 | 0.00
    Desconto Global: 1.47
    Pagamento: Pix
    """

    parsed = evaluation.parse_receipt_text(text)
    assert parsed == evaluation.EXPECTED_RECEIPT
    assert evaluation.compare_receipt(parsed) == []


def test_parser_ignores_markdown_separator_and_comparison_ignores_item_order():
    text = """
    | Nome do Produto | Valor Bruto | Desconto do Item |
    | --- | --- | --- |
    | Banana | 5.10 | 0.00 |
    | Café | 15.79 | 2.30 |
    | Leite | 10.98 | 1.00 |
    | Arroz | 24.90 | 0.00 |
    Desconto Global: 1.47
    Pagamento: PIX
    """

    assert evaluation.compare_receipt(evaluation.parse_receipt_text(text)) == []


def test_compare_reports_sanitized_field_paths_without_ocr_contents():
    parsed = dict(evaluation.EXPECTED_RECEIPT)
    parsed["global_discount_cents"] = 0

    differences = evaluation.compare_receipt(parsed)

    assert differences == ["global_discount_cents"]
    assert "Arroz" not in json.dumps(differences)


class _Response:
    text = """
    Arroz | 24.90 | 0.00
    Leite | 10.98 | 1.00
    Café | 15.79 | 2.30
    Banana | 5.10 | 0.00
    Desconto Global: 1.47
    Pagamento: Pix
    """


class _Models:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return _Response()


class _Client:
    def __init__(self, failure=None):
        self.aio = type("Aio", (), {"models": _Models(failure)})()


@pytest.mark.asyncio
async def test_evaluator_calls_only_lite_once_with_shared_prompt_and_configuration():
    client = _Client()

    results = await evaluation.evaluate_lite_model(client, b"same-image")

    assert len(results) == 1
    assert results[0]["model"] == "gemini-3.5-flash-lite"
    assert results[0]["duration_ms"] >= 0
    assert results[0]["status"] == "matched"
    assert results[0]["differences"] == []
    calls = client.aio.models.calls
    assert len(calls) == 1
    assert calls[0]["model"] == "gemini-3.5-flash-lite"
    assert calls[0]["contents"][0].inline_data.data == b"same-image"
    assert calls[0]["contents"][1] == receipt_ocr_contract.RECEIPT_OCR_PROMPT
    assert calls[0]["config"].http_options.timeout == 45_000
    assert calls[0]["config"].http_options.retry_options.attempts == 1


@pytest.mark.asyncio
async def test_evaluator_reports_the_single_lite_provider_failure():
    client = _Client(RuntimeError("provider payload must not be reported"))

    results = await evaluation.evaluate_lite_model(client, b"same-image")

    assert len(client.aio.models.calls) == 1
    assert len(results) == 1
    assert results[0]["model"] == "gemini-3.5-flash-lite"
    assert results[0]["status"] == "incomplete"
    assert results[0]["error_code"] == "RuntimeError"
    assert results[0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_main_preserves_sanitized_report_when_client_close_fails(monkeypatch, tmp_path, capsys):
    image_path = tmp_path / "synthetic.jpg"
    image_path.write_bytes(b"synthetic-image")

    async def close_fails():
        raise RuntimeError("close failure")

    client = SimpleNamespace(aio=SimpleNamespace(aclose=close_fails), close=lambda: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(evaluation.genai, "Client", lambda **_: client)
    monkeypatch.setattr(
        evaluation,
        "evaluate_lite_model",
        AsyncMock(return_value=[{"model": "gemini-3.5-flash-lite", "duration_ms": 1, "status": "matched", "differences": []}]),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate_gemini_receipt_models", "--confirm-free-tier", "--image", str(image_path)],
    )

    assert await evaluation._main() == 0
    assert json.loads(capsys.readouterr().out) == [
        {"model": "gemini-3.5-flash-lite", "duration_ms": 1, "status": "matched", "differences": []}
    ]
