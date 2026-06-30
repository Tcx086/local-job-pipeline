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
    _application_workspace_path,
    _campaign_resume_path,
    _campaign_df_with_application_bucket,
    _filter_campaign_bucket,
    _cover_letter_copy_text,
    _cover_letter_path,
    _generate_answer_pack_for_campaign,
    _generate_cover_letter_for_campaign,
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
                {"canonical_job_id": "queued", "campaign_status": "queued", "application_status": "new", "applied_at": ""},
                {"canonical_job_id": "campaign_applied", "campaign_status": "applied", "application_status": "new", "applied_at": ""},
                {"canonical_job_id": "application_applied", "campaign_status": "queued", "application_status": "applied", "applied_at": ""},
                {"canonical_job_id": "effort_skip", "campaign_status": "queued", "application_status": "new", "applied_at": "", "application_effort": "skip"},
                {"canonical_job_id": "hard_skip", "campaign_status": "queued", "application_status": "new", "applied_at": "", "hard_skip": True},
                {"canonical_job_id": "deferred", "campaign_status": "deferred", "application_status": "new", "applied_at": ""},
            ]
        )
        bucketed = _campaign_df_with_application_bucket(df)

        self.assertEqual(_filter_campaign_bucket(bucketed, "Actionable")["canonical_job_id"].tolist(), ["queued"])
        self.assertEqual(_filter_campaign_bucket(bucketed, "Not applied")["canonical_job_id"].tolist(), ["queued"])
        self.assertEqual(
            _filter_campaign_bucket(bucketed, "Skipped")["canonical_job_id"].tolist(),
            ["effort_skip", "hard_skip", "deferred"],
        )
        self.assertEqual(
            _filter_campaign_bucket(bucketed, "Applied")["canonical_job_id"].tolist(),
            ["campaign_applied", "application_applied"],
        )

    def test_profile_resume_rows_report_ready_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_path = root / "data_market_data.yaml"
            docx_path = root / "data_market_data.docx"
            pdf_path = root / "data_market_data.pdf"
            source_path.write_text("profile: data_market_data", encoding="utf-8")
            docx_path.write_text("docx", encoding="utf-8")
            pdf_path.write_text("pdf", encoding="utf-8")

            rows = _profile_resume_rows(
                {
                    "profiles": {
                        "data_market_data": {
                            "source": str(source_path),
                            "docx": str(docx_path),
                            "pdf": str(pdf_path),
                        }
                    }
                }
            )

        self.assertEqual(rows[0]["profile"], "data_market_data")
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
                {"canonical_job_id": "pdf", "campaign_date": "20260626", "score": 70, "resume_pdf_path": "generated/resume.pdf", "tailored_resume_path": ""},
            ]
        )

        result = _tailored_resume_rows(df)

        self.assertEqual(result["canonical_job_id"].tolist(), ["pdf", "new", "old"])

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

    def test_campaign_manual_cover_letter_generation_requires_allow_flag(self):
        row = {"canonical_job_id": "job1", "campaign_date": "20260625", "allow_manual_generate_cover_letter": False}
        with patch("job_pipeline.dashboard.generate_cover_letter", side_effect=AssertionError("cover letter generated")) as generate_cover_letter:
            self.assertEqual(_generate_cover_letter_for_campaign(row), "")
        self.assertEqual(generate_cover_letter.call_count, 0)

    def test_cover_letter_copy_text_prefers_body(self):
        self.assertEqual(
            _cover_letter_copy_text({"cover_letter_body": "Dear Hiring Team,\nBody only", "cover_letter_markdown": "# Cover Letter\nMarkdown"}),
            "Dear Hiring Team,\nBody only",
        )
        self.assertEqual(_cover_letter_copy_text({"cover_letter_markdown": "# Cover Letter\nMarkdown"}), "# Cover Letter\nMarkdown")

    def test_application_workspace_path_prefers_direct_then_payload_paths(self):
        self.assertEqual(
            _application_workspace_path(
                {"application_workspace_path": "generated/direct"},
                {"paths": {"workspace": "generated/from_payload"}},
            ),
            "generated/direct",
        )
        self.assertEqual(_application_workspace_path({}, {"paths": {"workspace": "generated/from_payload"}}), "generated/from_payload")

    def test_cover_letter_path_prefers_formal_pdf(self):
        cover = {"paths": {"formal_pdf": "generated/cover_letter.pdf", "body_txt": "generated/body.txt", "markdown": "generated/review.md"}}
        self.assertEqual(_cover_letter_path(cover), "generated/cover_letter.pdf")

    def test_campaign_resume_path_prefers_generated_pdf(self):
        self.assertEqual(
            _campaign_resume_path({"resume_pdf_path": "generated/resume.pdf", "tailored_resume_path": "legacy/resume.pdf"}),
            "generated/resume.pdf",
        )

    def test_campaign_answer_pack_generation_persists_workspace_path(self):
        row = {"canonical_job_id": "job1", "campaign_date": "20260625", "allow_manual_generate_answer_pack": True, "resume_pdf_path": "generated/resume.pdf"}
        pack = {"paths": {"workspace": "generated/20260625/company/role__job1", "markdown": "generated/20260625/company/role__job1/answer_pack.md"}}
        with patch("job_pipeline.dashboard.get_job_detail", return_value={"canonical_job_id": "job1"}), \
            patch("job_pipeline.dashboard.generate_answer_pack", return_value=pack), \
            patch("job_pipeline.dashboard.update_campaign_item_files") as update_files:
            self.assertEqual(_generate_answer_pack_for_campaign(row), "generated/20260625/company/role__job1/answer_pack.md")

        self.assertEqual(update_files.call_args.args[:2], ("20260625", "job1"))
        self.assertEqual(update_files.call_args.kwargs["answer_pack_path"], "generated/20260625/company/role__job1/answer_pack.md")
        self.assertEqual(update_files.call_args.kwargs["application_workspace_path"], "generated/20260625/company/role__job1")

    def test_campaign_cover_letter_generation_persists_workspace_paths(self):
        row = {"canonical_job_id": "job1", "campaign_date": "20260625", "allow_manual_generate_cover_letter": True, "resume_pdf_path": "generated/resume.pdf"}
        cover = {
            "paths": {
                "workspace": "generated/20260625/company/role__job1",
                "formal_pdf": "generated/20260625/company/role__job1/cover_letter.pdf",
                "body_txt": "generated/20260625/company/role__job1/cover_letter_body.txt",
                "markdown": "generated/20260625/company/role__job1/review/cover_letter_review.md",
            }
        }
        with patch("job_pipeline.dashboard._cover_letter_generation_enabled", return_value=True), \
            patch("job_pipeline.dashboard.get_job_detail", return_value={"canonical_job_id": "job1"}), \
            patch("job_pipeline.dashboard.generate_cover_letter", return_value=cover), \
            patch("job_pipeline.dashboard.update_campaign_item_files") as update_files:
            self.assertEqual(_generate_cover_letter_for_campaign(row), "generated/20260625/company/role__job1/cover_letter.pdf")

        self.assertEqual(update_files.call_args.args[:2], ("20260625", "job1"))
        self.assertEqual(update_files.call_args.kwargs["cover_letter_path"], "generated/20260625/company/role__job1/cover_letter.pdf")
        self.assertEqual(update_files.call_args.kwargs["application_workspace_path"], "generated/20260625/company/role__job1")
        self.assertEqual(update_files.call_args.kwargs["cover_letter_pdf_path"], "generated/20260625/company/role__job1/cover_letter.pdf")
        self.assertEqual(update_files.call_args.kwargs["cover_letter_body_path"], "generated/20260625/company/role__job1/cover_letter_body.txt")

if __name__ == "__main__":
    unittest.main()
