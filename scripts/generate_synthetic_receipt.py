#!/usr/bin/env python3
"""Generate the local synthetic receipt used by the isolated Gemini smoke test."""

import argparse
import io
from pathlib import Path


RECEIPT_LINES = (
    "TESTE - SEM VALOR FISCAL",
    "CUPOM FICTICIO PARA VALIDACAO",
    "",
    "1 ARROZ                         24,90",
    "2 LEITE 2 x 5,49                10,98",
    "  DESCONTO ITEM                 -1,00",
    "3 CAFE                          15,79",
    "  DESCONTO ITEM                 -2,30",
    "4 BANANA 0,750 kg x 6,80         5,10",
    "",
    "SUBTOTAL                        56,77",
    "DESCONTO GLOBAL                 -1,47",
    "TOTAL                            52,00",
    "PAGAMENTO: PIX                  52,00",
    "",
    "TESTE - SEM VALOR FISCAL",
)


def render_synthetic_receipt() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (920, 900), color=255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=24)
    y = 35
    for line in RECEIPT_LINES:
        draw.text((35, y), line, fill=0, font=font)
        y += 47
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=95, optimize=False, progressive=False)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Destination JPEG path.")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(render_synthetic_receipt())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
