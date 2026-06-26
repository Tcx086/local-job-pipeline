import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from job_pipeline.database import connect, mark_missing_inactive, upsert_job
from job_pipeline.freshness import calculate_age_days, freshness_label


class FreshnessTests(unittest.TestCase):
    def test_posted_at_used_for_age_when_present(self):
        ref = datetime(2026, 6, 25, tzinfo=timezone.utc)
        self.assertEqual(calculate_age_days("2026-06-20", "2026-06-24", ref), 5)
        self.assertEqual(freshness_label("2026-06-20", "2026-06-24", ref), "new_this_week")

    def test_first_seen_used_when_posted_missing(self):
        ref = datetime(2026, 6, 25, tzinfo=timezone.utc)
        self.assertEqual(calculate_age_days("", "2026-06-10", ref), 15)
        self.assertEqual(freshness_label("", "2026-06-10", ref), "recent")

    def test_second_fetch_updates_last_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job = {
                    "source": "greenhouse",
                    "source_job_id": "1",
                    "title": "Market Data Analyst",
                    "company": "Wealthsimple",
                    "location": "Toronto, ON",
                    "country": "Canada",
                    "description": "Python SQL market data.",
                    "score": 80,
                }
                first, is_new = upsert_job(conn, job)
                second, is_new_again = upsert_job(conn, job)
                self.assertTrue(is_new)
                self.assertFalse(is_new_again)
                self.assertEqual(first["first_seen_at"], second["first_seen_at"])
                self.assertGreaterEqual(second["last_seen_at"], first["last_seen_at"])
            finally:
                conn.close()

    def test_missing_job_marked_inactive_after_n_misses(self):
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
                mark_missing_inactive(conn, set(), inactive_after_misses=2)
                row = conn.execute("SELECT is_active, missing_count FROM jobs WHERE canonical_job_id=?", (job["canonical_job_id"],)).fetchone()
                self.assertEqual(row["is_active"], 1)
                mark_missing_inactive(conn, set(), inactive_after_misses=2)
                row = conn.execute("SELECT is_active, missing_count FROM jobs WHERE canonical_job_id=?", (job["canonical_job_id"],)).fetchone()
                self.assertEqual(row["is_active"], 0)
                self.assertEqual(row["missing_count"], 2)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()