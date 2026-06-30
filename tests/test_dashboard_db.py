import sqlite3
import tempfile
import unittest
from pathlib import Path

from job_pipeline.database import connect, get_job_detail, update_application, upsert_job


class DashboardDbTests(unittest.TestCase):
    def test_status_update_writes_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(
                    conn,
                    {
                        "source": "greenhouse",
                        "source_job_id": "1",
                        "title": "Market Data Analyst",
                        "company": "Wealthsimple",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "description": "Python SQL market data.",
                    },
                )
            finally:
                conn.close()
            update_application(job["canonical_job_id"], status="applied", resume_used="resume.md", notes="submitted", db_path=db)
            detail = get_job_detail(job["canonical_job_id"], db)
            self.assertEqual(detail["status"], "applied")
            self.assertEqual(detail["resume_used"], "resume.md")
            self.assertEqual(detail["notes"], "submitted")

    def test_apply_assist_fields_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(
                    conn,
                    {
                        "source": "ashby",
                        "source_job_id": "phase3",
                        "title": "Risk Data Analyst",
                        "company": "Example Fintech",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "apply_url": "https://example.com/apply",
                        "description": "Python SQL risk controls market data.",
                    },
                )
            finally:
                conn.close()
            update_application(
                job["canonical_job_id"],
                status="applied",
                applied_at="2026-06-25T12:00:00+00:00",
                resume_used="resume.docx",
                apply_url="https://example.com/apply",
                confirmation_number="ABC123",
                confirmation_snippet="Thank you for applying.",
                db_path=db,
            )
            detail = get_job_detail(job["canonical_job_id"], db)
            self.assertEqual(detail["status"], "applied")
            self.assertEqual(detail["application_apply_url"], "https://example.com/apply")
            self.assertEqual(detail["confirmation_number"], "ABC123")
            self.assertEqual(detail["confirmation_snippet"], "Thank you for applying.")


    def test_role_family_and_fit_category_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(
                    conn,
                    {
                        "source": "test",
                        "source_job_id": "role-family-fit",
                        "title": "Fraud Analyst",
                        "company": "Example Fintech",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "description": "Fraud transaction monitoring SQL reporting.",
                        "score": 82,
                        "role_family": "risk_fraud_compliance",
                        "fit_category": "core_fit",
                    },
                )
            finally:
                conn.close()
            detail = get_job_detail(job["canonical_job_id"], db)
            self.assertEqual(detail["role_family"], "risk_fraud_compliance")
            self.assertEqual(detail["fit_category"], "core_fit")
    def test_job_detail_reads_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(
                    conn,
                    {
                        "source": "lever",
                        "source_job_id": "abc",
                        "title": "API Support Analyst",
                        "company": "OKX",
                        "location": "Singapore",
                        "country": "Singapore",
                        "description": "REST API support JSON troubleshooting.",
                    },
                    raw_json_path="raw.json",
                )
            finally:
                conn.close()
            detail = get_job_detail(job["canonical_job_id"], db)
            self.assertEqual(detail["title"], "API Support Analyst")
            self.assertEqual(len(detail["snapshots"]), 1)
            self.assertEqual(detail["snapshots"][0]["raw_json_path"], "raw.json")



    def test_workspace_columns_are_added_to_old_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            raw = sqlite3.connect(db)
            try:
                raw.executescript(
                    """
                    CREATE TABLE jobs (id INTEGER PRIMARY KEY, canonical_job_id TEXT UNIQUE, source TEXT, source_job_id TEXT, job_url TEXT, apply_url TEXT, canonical_company TEXT, normalized_title TEXT);
                    CREATE TABLE applications (id INTEGER PRIMARY KEY, canonical_job_id TEXT UNIQUE, status TEXT);
                    CREATE TABLE campaign_items (id INTEGER PRIMARY KEY, campaign_date TEXT, canonical_job_id TEXT, application_effort TEXT, campaign_status TEXT, UNIQUE(campaign_date, canonical_job_id));
                    """
                )
                raw.commit()
            finally:
                raw.close()

            conn = connect(db)
            try:
                job_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
                application_columns = {row[1] for row in conn.execute("PRAGMA table_info(applications)").fetchall()}
                campaign_columns = {row[1] for row in conn.execute("PRAGMA table_info(campaign_items)").fetchall()}
            finally:
                conn.close()

        self.assertIn("application_workspace_path", application_columns)
        self.assertIn("resume_pdf_path", application_columns)
        self.assertIn("cover_letter_pdf_path", application_columns)
        self.assertIn("application_workspace_path", campaign_columns)
        self.assertIn("resume_pdf_path", campaign_columns)
        self.assertIn("application_workspace_path", job_columns)
        self.assertIn("latest_resume_pdf_path", job_columns)

    def test_application_formal_paths_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(
                    conn,
                    {
                        "source": "test",
                        "source_job_id": "workspace-paths",
                        "title": "QA Analyst",
                        "company": "Example Co",
                        "description": "Quality documentation checks.",
                    },
                )
            finally:
                conn.close()
            update_application(
                job["canonical_job_id"],
                status="applied",
                resume_used="legacy-resume.pdf",
                cover_letter_used="legacy-cover.pdf",
                application_workspace_path="generated/20260630/example/qa__job",
                resume_pdf_path="generated/20260630/example/qa__job/resume.pdf",
                resume_docx_path="generated/20260630/example/qa__job/resume.docx",
                cover_letter_pdf_path="generated/20260630/example/qa__job/cover.pdf",
                cover_letter_docx_path="generated/20260630/example/qa__job/cover.docx",
                cover_letter_body_path="generated/20260630/example/qa__job/cover_letter_body.txt",
                answer_pack_path="generated/20260630/example/qa__job/answer_pack.md",
                job_description_path="generated/20260630/example/qa__job/source/job_description.md",
                db_path=db,
            )
            detail = get_job_detail(job["canonical_job_id"], db)

        self.assertEqual(detail["resume_used"], "legacy-resume.pdf")
        self.assertEqual(detail["application_workspace_path"], "generated/20260630/example/qa__job")
        self.assertEqual(detail["resume_pdf_path"], "generated/20260630/example/qa__job/resume.pdf")
        self.assertEqual(detail["cover_letter_pdf_path"], "generated/20260630/example/qa__job/cover.pdf")
        self.assertEqual(detail["answer_pack_path"], "generated/20260630/example/qa__job/answer_pack.md")
if __name__ == "__main__":
    unittest.main()
