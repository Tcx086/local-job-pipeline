import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from job_pipeline import scheduler


class SchedulerPlanTests(unittest.TestCase):
    def test_dry_run_plan_does_not_collect(self):
        with patch("job_pipeline.scheduler.collect_sources", side_effect=AssertionError("collector called")):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = scheduler.main([
                    "--run-once",
                    "--mode",
                    "normal",
                    "--dry-run-plan",
                    "--max-query-location-pairs",
                    "30",
                    "--source-sites",
                    "linkedin,indeed",
                ])
        self.assertEqual(code, 0)
        plan = json.loads(buffer.getvalue())
        self.assertLessEqual(plan["total_query_location_pairs"], 30)
        self.assertEqual(plan["source_sites"], ["linkedin", "indeed"])
        self.assertEqual(plan["estimated_external_calls"], plan["total_query_location_pairs"] * 2)

    def test_scheduler_does_not_generate_resumes_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            resume = Path(tmp) / "master_resume.yaml"
            resume.write_text("profile:\n  name: Test\nskills:\n  - Python\n", encoding="utf-8")
            jobs = [
                {"job_id": "high", "score": 95, "title": "Resume Role", "company": "B", "description": "Python SQL"},
            ]
            with patch("job_pipeline.scheduler.generate_resume", return_value={"pdf": "resume.pdf", "markdown": "resume.md"}) as generate_resume:
                enriched = scheduler.enrich_for_resume_and_report(
                    jobs,
                    master_resume_path=resume,
                    resume_score_threshold=65,
                    make_docx=False,
                )
        self.assertEqual(generate_resume.call_count, 0)
        self.assertEqual(enriched[0].get("scheduler_resume_draft_path"), "")
        self.assertEqual(enriched[0].get("resume_file_generated"), "")

    def test_generate_resumes_opt_in_uses_resume_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            resume = Path(tmp) / "master_resume.yaml"
            resume.write_text("profile:\n  name: Test\nskills:\n  - Python\n", encoding="utf-8")
            jobs = [
                {"job_id": "low", "score": 64, "title": "Review Role", "company": "A", "description": "Python SQL"},
                {"job_id": "high", "score": 65, "title": "Resume Role", "company": "B", "description": "Python SQL"},
            ]
            with patch("job_pipeline.scheduler.generate_resume", return_value={"pdf": "resume.pdf", "markdown": "resume.md"}) as generate_resume:
                enriched = scheduler.enrich_for_resume_and_report(
                    jobs,
                    master_resume_path=resume,
                    resume_score_threshold=65,
                    make_docx=False,
                    generate_resumes=True,
                )
        self.assertEqual(generate_resume.call_count, 1)
        self.assertEqual(enriched[0].get("scheduler_resume_draft_path"), "")
        self.assertEqual(enriched[1].get("scheduler_resume_draft_path"), "resume.pdf")
        self.assertEqual(enriched[1].get("resume_file_generated"), "resume.pdf")

    def test_run_once_default_does_not_call_resume_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            with patch("job_pipeline.scheduler.generate_resume", side_effect=AssertionError("resume generated")) as generate_resume:
                summary = scheduler.run_once(
                    use_sample=True,
                    mode="normal",
                    results_wanted=1,
                    make_docx=False,
                    include_ats=False,
                    mark_missing=False,
                    db_path=db,
                )
        self.assertFalse(summary["generate_resumes"])
        self.assertEqual(generate_resume.call_count, 0)

    def test_generate_resumes_cli_flag_is_passed_to_run_once(self):
        with patch("job_pipeline.scheduler.run_once", return_value={"ok": True}) as run_once:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = scheduler.main(["--run-once", "--mode", "normal", "--generate-resumes", "--no-docx"])
        self.assertEqual(code, 0)
        self.assertTrue(run_once.call_args.kwargs["generate_resumes"])
        self.assertFalse(run_once.call_args.kwargs["make_docx"])


if __name__ == "__main__":
    unittest.main()
