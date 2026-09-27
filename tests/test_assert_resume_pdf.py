"""Regression tests for scripts/assert_resume_pdf.py.

The assertion script must be self-contained on a clean checkout: it may only
rely on declared dependencies (PyMuPDF / fitz). These tests build a tiny PDF
with fitz, extract its text through the script, and verify the
required/forbidden checks behave as expected.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

import fitz


def _load_script():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "assert_resume_pdf.py"
    spec = importlib.util.spec_from_file_location("assert_resume_pdf", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = _load_script()


def _make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        doc.save(path)
    finally:
        doc.close()


class AssertResumePdfTests(unittest.TestCase):
    def _extract(self, text: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "sample.pdf"
            _make_pdf(pdf, text)
            return SCRIPT.extract_text(pdf)

    def test_extract_text_reads_rendered_page(self):
        text = self._extract("Microstructure Discovery Factory")
        self.assertIn("Microstructure Discovery Factory", SCRIPT.normalize(text))

    def test_required_and_forbidden_checks(self):
        text = self._extract("Lomidance\nPython SQL reporting")
        # required present, forbidden absent -> clean
        self.assertEqual(SCRIPT.check(text, forbidden=["Spanish"], required=["Lomidance"]), [])
        # required missing -> error
        errors = SCRIPT.check(text, forbidden=[], required=["CCC Motors"])
        self.assertEqual(len(errors), 1)
        self.assertIn("REQUIRED string missing", errors[0])
        # forbidden present -> error
        errors = SCRIPT.check(text, forbidden=["Lomidance"], required=[])
        self.assertEqual(len(errors), 1)
        self.assertIn("FORBIDDEN string present", errors[0])

    def test_line_wrap_cannot_split_phrases(self):
        # whitespace normalization must survive PDF line wrapping
        self.assertEqual(
            SCRIPT.check("Sep 2021\n- Apr 2025", forbidden=[], required=["Sep 2021 - Apr 2025"]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
