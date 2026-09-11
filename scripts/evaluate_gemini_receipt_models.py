#!/usr/bin/env python3
"""One-shot Gemini receipt smoke test without bootstrapping the bot services."""

import argparse
import asyncio
import json
import os
import time
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from google import genai
from google.genai import types

from receipt_ocr_contract import GEMINI_FALLBACK_MODEL, GEMINI_OCR_MODELS, RECEIPT_OCR_PROMPT, build_generate_content_config


EXPECTED_RECEIPT = {
    "items": (
        ("arroz", 2490, 0),
        ("leite", 1098, 100),
        ("cafe", 1579, 230),
        ("banana", 510, 0),
    ),
    "global_discount_cents": 147,
    "payment": "pix",
}


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return " ".join("".join(char for char in normalized if not unicodedata.combining(char)).split())


def _cents(value: str) -> int:
    normalized = value.strip().replace("R$", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    else:
        normalized = normalized.replace(",", ".")
    try:
        return int((Decimal(normalized) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError("invalid monetary field") from exc


def parse_receipt_text(text: str) -> dict:
    items = []
    global_discount_cents = None
    payment = None
    for raw_line in text.splitlines():
        line = raw_line.strip().strip("| ")
        if not line:
            continue
        if line.casefold().startswith("desconto global:"):
            global_discount_cents = _cents(line.split(":", 1)[1])
            continue
        if line.casefold().startswith("pagamento:"):
            payment = _normalized(line.split(":", 1)[1])
            continue
        columns = [column.strip() for column in line.split("|")]
        if len(columns) != 3 or "valor bruto" in line.casefold():
            continue
        if all(not column.replace("-", "").replace(":", "").strip() for column in columns):
            continue
        items.append((_normalized(columns[0]), _cents(columns[1]), _cents(columns[2])))
    if global_discount_cents is None or payment is None:
        raise ValueError("missing receipt summary fields")
    return {
        "items": tuple(items),
        "global_discount_cents": global_discount_cents,
        "payment": payment,
    }


def compare_receipt(actual: dict) -> list[str]:
    differences = []
    if tuple(sorted(actual.get("items", ()))) != tuple(sorted(EXPECTED_RECEIPT["items"])):
        differences.append("items")
    if actual.get("global_discount_cents") != EXPECTED_RECEIPT["global_discount_cents"]:
        differences.append("global_discount_cents")
    if actual.get("payment") != EXPECTED_RECEIPT["payment"]:
        differences.append("payment")
    return differences


async def evaluate_lite_model(client, image_bytes: bytes) -> list[dict]:
    timeout_seconds = dict(GEMINI_OCR_MODELS)[GEMINI_FALLBACK_MODEL]
    started_at = time.monotonic()
    try:
        async with asyncio.timeout(timeout_seconds):
            response = await client.aio.models.generate_content(
                model=GEMINI_FALLBACK_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    RECEIPT_OCR_PROMPT,
                ],
                config=build_generate_content_config(timeout_seconds),
            )
        differences = compare_receipt(parse_receipt_text(response.text or ""))
        return [{
            "model": GEMINI_FALLBACK_MODEL,
            "duration_ms": round((time.monotonic() - started_at) * 1000),
            "status": "matched" if not differences else "mismatch",
            "differences": differences,
        }]
    except Exception as exc:
        return [{
            "model": GEMINI_FALLBACK_MODEL,
            "duration_ms": round((time.monotonic() - started_at) * 1000),
            "status": "incomplete",
            "error_code": type(exc).__name__,
        }]


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-free-tier",
        action="store_true",
        help="Attest that the key project/tier and current quota were checked in Google AI Studio.",
    )
    parser.add_argument("--image", required=True, help="Path to the local JPEG synthetic receipt.")
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    if not args.confirm_free_tier:
        raise SystemExit("Refusing provider calls until --confirm-free-tier is supplied after checking AI Studio.")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set.")

    try:
        image_bytes = Path(args.image).read_bytes()
    except OSError as exc:
        raise SystemExit("Synthetic receipt image is unavailable.") from exc
    if not image_bytes:
        raise SystemExit("Synthetic receipt image is empty.")

    client = genai.Client(api_key=api_key)
    try:
        results = await evaluate_lite_model(client, image_bytes)
    finally:
        try:
            await client.aio.aclose()
            client.close()
        except Exception:
            pass
    print(json.dumps(results, ensure_ascii=False, separators=(",", ":")))
    return 0 if len(results) == 1 and results[0]["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
