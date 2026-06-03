#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate backend line and branch coverage thresholds.")
    parser.add_argument("coverage_xml", help="Path to coverage XML report.")
    parser.add_argument("--min-lines", type=float, default=90.0, help="Minimum line coverage percentage.")
    parser.add_argument("--min-branches", type=float, default=90.0, help="Minimum branch coverage percentage.")
    return parser.parse_args()


def _to_percent(raw: str | None) -> float:
    if raw is None:
        raise ValueError("coverage report is missing a required rate attribute")
    return round(float(raw) * 100, 2)


def main() -> int:
    args = _parse_args()
    coverage_path = Path(args.coverage_xml)
    if not coverage_path.exists():
        print(f"coverage report not found: {coverage_path}", file=sys.stderr)
        return 1

    root = ET.parse(coverage_path).getroot()
    lines = _to_percent(root.attrib.get("line-rate"))
    branches = _to_percent(root.attrib.get("branch-rate"))

    print(f"Backend coverage: lines={lines:.2f}% branches={branches:.2f}%")

    failures: list[str] = []
    if lines < args.min_lines:
        failures.append(f"lines {lines:.2f}% < {args.min_lines:.2f}%")
    if branches < args.min_branches:
        failures.append(f"branches {branches:.2f}% < {args.min_branches:.2f}%")

    if failures:
        print("Backend coverage threshold check failed: " + "; ".join(failures), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
