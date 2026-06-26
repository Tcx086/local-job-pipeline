import tempfile
import unittest
from pathlib import Path

import fitz
from docx import Document

from job_pipeline.campaign import profile_resume_path
from job_pipeline.resume_tailor import HUMAN_DOCX_RENDERER, PDF_RENDERER_DOCX, generate_profile_resumes, generate_resume


MASTER_RESUME = """
name: Test Candidate
location: Toronto, ON
contacts:
  email: test@example.com
headline: Operations data analyst
summary:
  - Analyst with Python SQL reporting experience.
skills:
  technical:
    - Python
    - SQL
    - Reconciliation
projects:
  - name: Operations Reporting
    type: Project
    dates: 2025
    bullets:
      - Built Python SQL reporting for reconciliation workflows.
experience:
  - title: Operations Analyst
    company: Example Bank
    location: Toronto
    dates: 2024-2025
    bullets:
      - Supported trade support reporting and data quality controls.
education:
  - degree: MSc Finance
    school: Example University
    date: 2024
languages:
  - English
"""


def _docx_text(path: Path) -> str:
    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


class ResumeTailorTests(unittest.TestCase):
    def test_generate_resume_writes_company_date_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master_resume.yaml"
            master.write_text(MASTER_RESUME, encoding="utf-8")
            paths = generate_resume(
                master_resume_path=master,
                job={
                    "canonical_job_id": "job-123",
                    "company": "Luxoft",
                    "title": "Calypso Support Analyst",
                    "score": 98,
                    "role_category": "trading_ops",
                },
                keyword_info={
                    "top_keywords": ["python", "sql", "reconciliation"],
                    "missing_keywords_from_master_resume": ["calypso_vendor_term"],
                },
                output_dir=root / "resumes",
                output_date="20260625",
                make_docx=False,
            )
            pdf_path = Path(paths["pdf"])
            markdown_path = Path(paths["markdown"])
            self.assertTrue(pdf_path.exists())
            self.assertEqual(pdf_path.suffix, ".pdf")
            self.assertEqual(pdf_path.parent.name, "20260625")
            self.assertEqual(pdf_path.parent.parent.name, "luxoft")
            with fitz.open(pdf_path) as doc:
                self.assertGreaterEqual(doc.page_count, 1)
            self.assertNotIn("calypso_vendor_term", markdown_path.read_text(encoding="utf-8"))

    def test_learning_backlog_and_do_not_use_keywords_are_filtered(self):
        unsafe_master = """
name: Test Candidate
summary:
  - Analyst with Python reporting experience and forbidden_ledger exposure.
skills:
  technical:
    - Python
    - forbidden_ledger
    - unsafe_platform
projects:
  - name: Reporting Project
    bullets:
      - Built Python reporting workflows.
      - Used forbidden_ledger for production reconciliation.
      - Supported unsafe_platform migration.
experience:
  - title: Analyst
    company: Example
    bullets:
      - Maintained Python reports.
      - Owned forbidden_ledger controls.
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "profile.yaml"
            master.write_text(unsafe_master, encoding="utf-8")
            paths = generate_resume(
                master_resume_path=master,
                job={"canonical_job_id": "job-unsafe", "company": "Example", "title": "Analyst", "score": 80},
                keyword_info={
                    "top_keywords": ["python", "forbidden_ledger", "unsafe_platform"],
                    "keyword_evidence": {
                        "evidence_backed": ["python"],
                        "learning_backlog": ["forbidden_ledger"],
                        "do_not_use": ["unsafe_platform"],
                    },
                },
                output_dir=root / "resumes",
                output_date="20260625",
                make_docx=False,
                make_pdf=False,
            )
            markdown = Path(paths["markdown"]).read_text(encoding="utf-8").lower()
        self.assertIn("python", markdown)
        self.assertNotIn("forbidden_ledger", markdown)
        self.assertNotIn("unsafe_platform", markdown)

    def test_profile_export_uses_docx_template_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = generate_profile_resumes(output_dir=root)

            self.assertGreaterEqual(len(results), 5)
            profile_paths = {
                "profiles": {
                    result["profile"]: {
                        "source": result["source"],
                        "docx": result["docx"],
                        "pdf": result["pdf"],
                    }
                    for result in results
                }
            }
            for result in results:
                docx_path = Path(result["docx"])
                pdf_path = Path(result["pdf"])
                self.assertEqual(result["docx_renderer"], HUMAN_DOCX_RENDERER)
                self.assertEqual(result["pdf_renderer"], PDF_RENDERER_DOCX)
                self.assertTrue(docx_path.exists())
                self.assertTrue(pdf_path.exists())
                resolved_profile = profile_resume_path(result["profile"], profile_paths)
                self.assertTrue(Path(resolved_profile).exists())

                docx_text = _docx_text(docx_path)
                self.assertNotIn("Targeted fit:", docx_text)
                self.assertNotIn("TARGETED SKILLS", docx_text)
                self.assertIn("Programming & Data", docx_text)
                self.assertGreater(len(docx_text), 50)
                self.assertNotIn("linkedin.comin", docx_text)
                self.assertNotIn("\ufffd", docx_text)
                self.assertNotIn("\ufffd", docx_text)

                with fitz.open(pdf_path) as pdf_doc:
                    pdf_text = "\n".join(page.get_text() for page in pdf_doc)
                    self.assertLessEqual(pdf_doc.page_count, 2)
                self.assertNotIn("Targeted fit:", pdf_text)
                self.assertNotIn("TARGETED SKILLS", pdf_text)
                self.assertNotIn("linkedin.comin", pdf_text)
                self.assertNotIn("\ufffd", pdf_text)
                self.assertNotIn("\ufffd", pdf_text)


if __name__ == "__main__":
    unittest.main()
