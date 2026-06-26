import tempfile
import unittest
from pathlib import Path

from job_pipeline.report import prepare_report_rows, write_top_jobs_markdown
from job_pipeline.score import score_band


class ScoreBandReportTests(unittest.TestCase):
    def test_score_46_is_review_manually_band(self):
        self.assertEqual(score_band(46), "Review manually")
        rows = prepare_report_rows([
            {
                "job_id": "job1",
                "score": 46,
                "title": "Report Solution Analyst",
                "company": "Example",
                "location": "Toronto",
                "country": "Canada",
            }
        ])
        self.assertEqual(rows[0]["score_band"], "Review manually")

    def test_markdown_includes_top_review_candidates_below_55(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "top_jobs.md"
            rows = prepare_report_rows([
                {
                    "job_id": "job1",
                    "score": 46,
                    "recommendation": "Review manually",
                    "title": "Report Solution Analyst",
                    "company": "Example",
                    "location": "Toronto",
                    "country": "Canada",
                    "is_active": 1,
                }
            ])
            write_top_jobs_markdown(
                path,
                rows,
                min_score_report=55,
                markdown_min_score=55,
                always_include_top_n=20,
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("Top Review Candidates", text)
            self.assertIn("Report Solution Analyst", text)
            self.assertIn("No apply-grade roles, but review candidates exist.", text)


if __name__ == "__main__":
    unittest.main()
