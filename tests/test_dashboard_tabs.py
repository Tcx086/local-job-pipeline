import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from job_pipeline.dashboard import (
    APPLY_ASSIST_DEFAULT_MIN_SCORE,
    DASHBOARD_DEFAULT_MIN_SCORE,
    DASHBOARD_TAB_LABELS,
    get_job_merge_events,
    get_manual_search_urls,
    get_search_coverage_rows,
    get_source_health_rows,
    mark_manual_search_checked,
    _applied_jobs_df,
    _campaign_df_with_application_bucket,
    _filter_campaign_bucket,
    _generate_answer_pack_for_campaign,
    _generate_tailored_resume_for_campaign,
    _profile_resume_rows,
    _tailored_resume_rows,
)


class DashboardTabsTests(unittest.TestCase):
    def test_phase4_pages_are_registered_in_main_tabs(self):
        for label in ["Search Coverage", "Source Health", "Manual Search", "Dedupe Audit"]:
            self.assertIn(label, DASHBOARD_TAB_LABELS)

    def test_score_defaults_keep_review_and_apply_assist_separate(self):
        self.assertEqual(DASHBOARD_DEFAULT_MIN_SCORE, 35)
        self.assertEqual(APPLY_ASSIST_DEFAULT_MIN_SCORE, 70)

    def test_phase4_diagnostic_imports_are_resilient(self):
        for func in [
            get_search_coverage_rows,
            get_source_health_rows,
            get_manual_search_urls,
            mark_manual_search_checked,
            get_job_merge_events,
        ]:
            self.assertTrue(callable(func))

    def test_application_tracker_filters_to_applied_lifecycle(self):
        df = pd.DataFrame(
            [
                {"canonical_job_id": "new", "status": "new", "applied_at": ""},
                {"canonical_job_id": "applied", "status": "applied", "applied_at": ""},
                {"canonical_job_id": "interview", "status": "interview", "applied_at": ""},
                {"canonical_job_id": "dated", "status": "new", "applied_at": "2026-06-25"},
            ]
        )

        result = _applied_jobs_df(df)

        self.assertEqual(result["canonical_job_id"].tolist(), ["applied", "interview", "dated"])

    def test_campaign_bucket_separates_applied_skipped_and_actionable(self):
        df = pd.DataFrame(
            [
                {"canonical_job_id": "queued", "campaign_status": "queued", "application_effort": "deep_tailor", "application_status": "new", "applied_at": "", "hard_skip": False},
                {"canonical_job_id": "campaign_applied", "campaign_status": "applied", "application_effort": "deep_tailor", "application_status": "new", "applied_at": "", "hard_skip": False},
                {"canonical_job_id": "application_applied", "campaign_status": "queued", "application_effort": "deep_tailor", "application_status": "applied", "applied_at": "", "hard_skip": False},
                {"canonical_job_id": "skipped", "campaign_status": "skipped", "application_effort": "skip", "application_status": "new", "applied_at": "", "hard_skip": True},
            ]
        )
        bucketed = _campaign_df_with_application_bucket(df)

        self.assertEqual(_filter_campaign_bucket(bucketed, "Actionable")["canonical_job_id"].tolist(), ["queued"])
        self.assertEqual(_filter_campaign_bucket(bucketed, "Not applied")["canonical_job_id"].tolist(), ["queued"])
        self.assertEqual(_filter_campaign_bucket(bucketed, "Skipped")["canonical_job_id"].tolist(), ["skipped"])
        self.assertEqual(
            _filter_campaign_bucket(bucketed, "Applied")["canonical_job_id"].tolist(),
            ["campaign_applied", "application_applied"],
        )

    def test_profile_resume_rows_report_ready_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_path = root / "general_data.yaml"
            docx_path = root / "general_data.docx"
            pdf_path = root / "general_data.pdf"
            source_path.write_text("profile: general_data", encoding="utf-8")
            docx_path.write_text("docx", encoding="utf-8")
            pdf_path.write_text("pdf", encoding="utf-8")

            rows = _profile_resume_rows(
                {
                    "profiles": {
                        "general_data": {
                            "source": str(source_path),
                            "docx": str(docx_path),
                            "pdf": str(pdf_path),
                        }
                    }
                }
            )

        self.assertEqual(rows[0]["profile"], "general_data")
        self.assertTrue(rows[0]["ready"])
        self.assertTrue(rows[0]["source_exists"])
        self.assertTrue(rows[0]["docx_exists"])
        self.assertTrue(rows[0]["pdf_exists"])

    def test_tailored_resume_rows_filters_empty_paths(self):
        df = pd.DataFrame(
            [
                {"canonical_job_id": "empty", "campaign_date": "20260625", "score": 99, "tailored_resume_path": ""},
                {"canonical_job_id": "none", "campaign_date": "20260625", "score": 98, "tailored_resume_path": None},
                {"canonical_job_id": "old", "campaign_date": "20260624", "score": 100, "tailored_resume_path": "data/resumes/old.pdf"},
                {"canonical_job_id": "new", "campaign_date": "20260625", "score": 80, "tailored_resume_path": "data/resumes/new.pdf"},
            ]
        )

        result = _tailored_resume_rows(df)

        self.assertEqual(result["canonical_job_id"].tolist(), ["new", "old"])

    def test_campaign_manual_resume_generation_requires_allow_flag(self):
        row = {"canonical_job_id": "job1", "campaign_date": "20260625", "allow_manual_generate_resume": False}
        with patch("job_pipeline.dashboard.generate_resume", side_effect=AssertionError("resume generated")) as generate_resume:
            self.assertEqual(_generate_tailored_resume_for_campaign(row), "")
        self.assertEqual(generate_resume.call_count, 0)

    def test_campaign_manual_answer_pack_generation_requires_allow_flag(self):
        row = {"canonical_job_id": "job1", "campaign_date": "20260625", "allow_manual_generate_answer_pack": False}
        with patch("job_pipeline.dashboard.generate_answer_pack", side_effect=AssertionError("answer pack generated")) as generate_answer_pack:
            self.assertEqual(_generate_answer_pack_for_campaign(row), "")
        self.assertEqual(generate_answer_pack.call_count, 0)


if __name__ == "__main__":
    unittest.main()
