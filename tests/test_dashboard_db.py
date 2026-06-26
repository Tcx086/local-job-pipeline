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


if __name__ == "__main__":
    unittest.main()