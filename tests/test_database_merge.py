import tempfile
import unittest
from pathlib import Path

from job_pipeline.database import connect, get_job_detail, upsert_job


class DatabaseMergeTests(unittest.TestCase):
    def _job(self, source_id: str, *, score=None, **extra):
        job = {
            "source": "greenhouse",
            "source_job_id": source_id,
            "title": "Market Data Analyst",
            "company": "Example Fintech",
            "location": "Toronto, ON",
            "country": "Canada",
            "description": "SQL Python reporting for market data operations.",
        }
        if score is not None:
            job["score"] = score
        job.update(extra)
        return job

    def test_lower_incoming_score_refreshes_scoring_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                first, is_new = upsert_job(
                    conn,
                    self._job(
                        "score-refresh-lower",
                        score=94,
                        recommendation="Must apply",
                        role_family="financial_data_analysis",
                        fit_category="core_fit",
                        matched_keywords=["sql", "market data"],
                        missing_keywords=[],
                        red_flags=[],
                        reason_to_apply="Strong market data analyst fit.",
                        hard_skip=False,
                        soft_penalties=[],
                        filter_reason="",
                        scheduler_resume_draft_path="drafts/high.md",
                    ),
                )
                second, is_new_again = upsert_job(
                    conn,
                    self._job(
                        "score-refresh-lower",
                        score=12,
                        recommendation="Hard skip",
                        role_family="unknown",
                        fit_category="skip",
                        matched_keywords=[],
                        missing_keywords=["finance fit"],
                        red_flags=["biotech_industry_mismatch"],
                        reason_to_apply="Skip: biotech mismatch.",
                        hard_skip=True,
                        soft_penalties=["industry_mismatch"],
                        filter_reason="biotech/life sciences mismatch",
                        resume_file_generated="drafts/skip.md",
                    ),
                )
            finally:
                conn.close()

            detail = get_job_detail(first["canonical_job_id"], db)
            self.assertTrue(is_new)
            self.assertFalse(is_new_again)
            self.assertEqual(second["canonical_job_id"], first["canonical_job_id"])
            self.assertEqual(detail["score"], 12)
            self.assertEqual(detail["recommendation"], "Hard skip")
            self.assertEqual(detail["role_family"], "unknown")
            self.assertEqual(detail["fit_category"], "skip")
            self.assertTrue(detail["hard_skip"])
            self.assertEqual(detail["filter_reason"], "biotech/life sciences mismatch")
            self.assertIn("biotech_industry_mismatch", detail["red_flags"])
            self.assertEqual(detail["scheduler_resume_draft_path"], "drafts/skip.md")

    def test_higher_incoming_score_still_refreshes_scoring_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                first, _ = upsert_job(
                    conn,
                    self._job(
                        "score-refresh-higher",
                        score=42,
                        recommendation="Review manually",
                        role_family="financial_data_analysis",
                        fit_category="stretch_fit",
                        matched_keywords=["reporting"],
                        red_flags=["missing_sql"],
                        reason_to_apply="Partial analyst fit.",
                        hard_skip=False,
                        soft_penalties=["missing_key_skill"],
                        filter_reason="",
                    ),
                )
                upsert_job(
                    conn,
                    self._job(
                        "score-refresh-higher",
                        score=88,
                        recommendation="Strong apply",
                        role_family="technical_operations",
                        fit_category="core_fit",
                        matched_keywords=["api", "sql", "troubleshooting"],
                        red_flags=[],
                        reason_to_apply="Strong API support analyst fit.",
                        hard_skip=False,
                        soft_penalties=[],
                        filter_reason="",
                    ),
                )
            finally:
                conn.close()

            detail = get_job_detail(first["canonical_job_id"], db)
            self.assertEqual(detail["score"], 88)
            self.assertEqual(detail["recommendation"], "Strong apply")
            self.assertEqual(detail["role_family"], "technical_operations")
            self.assertEqual(detail["fit_category"], "core_fit")
            self.assertFalse(detail["hard_skip"])
            self.assertEqual(detail["red_flags"], [])

    def test_unscored_incoming_row_preserves_existing_scoring_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                first, _ = upsert_job(
                    conn,
                    self._job(
                        "score-refresh-unscored",
                        score=76,
                        recommendation="Strong apply",
                        role_family="risk_fraud_compliance",
                        fit_category="core_fit",
                        matched_keywords=["fraud", "sql"],
                        red_flags=[],
                        reason_to_apply="Strong fraud analyst fit.",
                        hard_skip=False,
                        filter_reason="",
                    ),
                )
                upsert_job(
                    conn,
                    self._job(
                        "score-refresh-unscored",
                        description="Fresh source row without a scoring pass yet.",
                    ),
                )
            finally:
                conn.close()

            detail = get_job_detail(first["canonical_job_id"], db)
            self.assertEqual(detail["score"], 76)
            self.assertEqual(detail["recommendation"], "Strong apply")
            self.assertEqual(detail["role_family"], "risk_fraud_compliance")
            self.assertEqual(detail["fit_category"], "core_fit")
            self.assertFalse(detail["hard_skip"])


if __name__ == "__main__":
    unittest.main()