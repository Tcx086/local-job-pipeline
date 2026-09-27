#!/usr/bin/env python3
"""PDF-level assertions for generated resumes.

Extracts text from a rendered resume PDF and checks forbidden / required
strings. Prints PASS/FAIL and exits non-zero on any violation.

Usage:
    python scripts/assert_resume_pdf.py <pdf_path>
        [--forbidden "a,b,c"] [--required "x,y,z"]

Defaults encode the Alpaca V2 assertion contract. On FAIL, the caller must
NOT report the resume as complete.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pypdf import PdfReader

DEFAULT_FORBIDDEN = [
    "Targeted fit:",
    "Targeted Skills",
    "Crypto Trading Execution & Monitoring",
    "Spanish",
    "PL-300",
]
DEFAULT_REQUIRED = [
    "Historical Live Perpetual Futures Execution",
    "Microstructure Discovery Factory",
    "Lomidance",
    "CCC Motors",
    "Sep 2021 - Apr 2025",
    "French - Beginner",
]


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def normalize(text: str) -> str:
    """Collapse all whitespace so line-wrap in extracted PDF text can't split phrases."""
    return " ".join(text.split())


def check(text: str, forbidden: list[str], required: list[str]) -> list[str]:
    flat = normalize(text)
    errors: list[str] = []
    for s in forbidden:
        if normalize(s) in flat:
            errors.append(f"FORBIDDEN string present: {s!r}")
    for s in required:
        if normalize(s) not in flat:
            errors.append(f"REQUIRED string missing: {s!r}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Assert rendered resume PDF text.")
    ap.add_argument("pdf_path", help="Path to the rendered PDF.")
    ap.add_argument("--forbidden", default=",".join(DEFAULT_FORBIDDEN),
                    help="Comma-separated forbidden strings.")
    ap.add_argument("--required", default=",".join(DEFAULT_REQUIRED),
                    help="Comma-separated required strings.")
    args = ap.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"ASSERTION FAIL: PDF not found: {pdf_path}")
        return 1

    text = extract_text(pdf_path)
    forbidden = [s for s in args.forbidden.split(",") if s]
    required = [s for s in args.required.split(",") if s]
    errors = check(text, forbidden, required)
    if errors:
        print("ASSERTION FAIL:")
        for e in errors:
            print(f" - {e}")
        return 1
    print("ASSERTION PASS: all forbidden strings absent; all required strings present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
