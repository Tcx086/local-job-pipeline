import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_pipeline.campaign import build_campaign_row, build_daily_campaign, classify_application_effort
from job_pipeline.dashboard import DASHBOARD_TAB_LABELS, _generate_tailored_resume_for_campaign
from job_pipeline.database import connect, get_campaign_items, get_job_detail, replace_campaign_items, save_campaign_items, update_campaign_item_files, update_campaign_item_status, upsert_job


def _job(idx: int, *, score: int, company: str = "Example Fintech", title: str = "Market Data Analyst", **extra):
    row = {
        "canonical_job_id": f"job_{idx}",
        "source": "test",
        "source_job_id": f"src_{idx}",
        "title": title,
        "company": company,
        "canonical_company": company.lower().replace(" ", "_"),
        "location": "Toronto, ON",
        "country": "Canada",
        "description": "Python SQL market data reporting operations.",
        "score": score,
        "matched_keywords": ["python", "sql", "market data"],
        "red_flags": [],
        "role_family": "financial_data_analysis",
        "fit_category": "adjacent_fit",
        "is_active": 1,
        "status": "new",
    }
    row.update(extra)
    return row


class CampaignTests(unittest.TestCase):
    def test_score_bands_route_to_application_effort(self):
        self.assertEqual(classify_application_effort(_job(1, score=70)), "deep_tailor")
        self.assertEqual(classify_application_effort(_job(2, score=55)), "standard_tailor")
        self.assertEqual(classify_application_effort(_job(3, score=35)), "quick_apply")
        self.assertEqual(classify_application_effort(_job(4, score=25)), "hold")

    def test_hard_skip_routes_to_skip(self):
        self.assertEqual(classify_application_effort(_job(5, score=95, hard_skip=True)), "skip")

    def test_severe_red_flags_cannot_deep_tailor_even_with_high_score(self):
        senior = _job(55, score=95, title="Senior Data Analyst", red_flags=["senior_title"])
        self.assertEqual(classify_application_effort(senior), "standard_tailor")

        high_years = _job(56, score=95, title="Data Analyst", red_flags=["five_plus_years"])
        self.assertEqual(classify_application_effort(high_years), "standard_tailor")

    def test_priority_company_can_promote_but_not_over_severe_red_flag(self):
        promoted = _job(6, score=60, company="RBC")
        self.assertEqual(classify_application_effort(promoted), "deep_tailor")

        senior = _job(7, score=60, company="RBC", title="Senior Market Data Analyst", red_flags=["senior_title"])
        self.assertEqual(classify_application_effort(senior), "standard_tailor")

    def test_daily_campaign_respects_max_per_company_per_day(self):
        jobs = [_job(i, score=90, company="RBC", title=f"Market Data Analyst {i}") for i in range(5)]
        result = build_daily_campaign(jobs, campaign_date="20260625", deep=5, standard=0, quick=0)
        selected_rbc = [row for row in result["selected"] if row["company"] == "RBC"]
        self.assertEqual(len(selected_rbc), 3)

    def test_daily_campaign_respects_effort_quotas(self):
        jobs = []
        jobs.extend(_job(i, score=80, company=f"DeepCo{i}", title=f"Deep Analyst {i}") for i in range(10))
        jobs.extend(_job(20 + i, score=60, company=f"StdCo{i}", title=f"Standard Analyst {i}") for i in range(10))
        jobs.extend(_job(40 + i, score=40, company=f"QuickCo{i}", title=f"Quick Analyst {i}") for i in range(10))
        result = build_daily_campaign(jobs, campaign_date="20260625", deep=2, standard=3, quick=4)
        counts = {effort: sum(1 for row in result["selected"] if row["application_effort"] == effort) for effort in ["deep_tailor", "standard_tailor", "quick_apply"]}
        self.assertEqual(counts, {"deep_tailor": 2, "standard_tailor": 3, "quick_apply": 4})

    def test_campaign_row_stores_score_snapshot(self):
        row = build_campaign_row(_job(49, score=42), campaign_date="20260625")

        self.assertEqual(row["campaign_score"], 42)
        self.assertEqual(row["score"], 42)
        self.assertEqual(row["campaign_score_band"], row["score_band"])
        self.assertIn("score 42", row["campaign_reason"])

    def test_generation_flags_follow_effort(self):
        quick = build_campaign_row(_job(50, score=40), campaign_date="20260625")
        self.assertFalse(quick["auto_generate_resume"])
        self.assertFalse(quick["allow_manual_generate_resume"])
        self.assertFalse(quick["auto_generate_answer_pack"])
        self.assertFalse(quick["allow_manual_generate_answer_pack"])
        self.assertFalse(quick["auto_generate_cover_letter"])
        self.assertFalse(quick["allow_manual_generate_cover_letter"])

        deep = build_campaign_row(_job(51, score=80), campaign_date="20260625")
        self.assertFalse(deep["auto_generate_resume"])
        self.assertFalse(deep["auto_generate_cover_letter"])
        self.assertTrue(deep["allow_manual_generate_resume"])
        self.assertTrue(deep["allow_manual_generate_answer_pack"])
        self.assertTrue(deep["allow_manual_generate_cover_letter"])

        standard = build_campaign_row(_job(52, score=60), campaign_date="20260625")
        self.assertTrue(standard["allow_manual_generate_resume"])
        self.assertTrue(standard["allow_manual_generate_answer_pack"])
        self.assertTrue(standard["allow_manual_generate_cover_letter"])

    def test_mark_applied_syncs_applications_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(
                    conn,
                    {
                        "source": "test",
                        "source_job_id": "applied-sync",
                        "title": "Market Data Analyst",
                        "company": "Example Fintech",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "apply_url": "https://example.com/apply",
                        "description": "Python SQL market data reporting.",
                        "score": 80,
                    },
                )
            finally:
                conn.close()

            row = build_campaign_row(job, campaign_date="20260625")
            row["cover_letter_path"] = "data/cover_letters/example.md"
            save_campaign_items(db, [row])
            update_campaign_item_status("20260625", job["canonical_job_id"], "applied", notes="submitted", db_path=db)

            detail = get_job_detail(job["canonical_job_id"], db)
            self.assertEqual(detail["status"], "applied")
            self.assertEqual(detail["notes"], "submitted")
            self.assertEqual(detail["application_apply_url"], "https://example.com/apply")
            self.assertEqual(detail["cover_letter_used"], "data/cover_letters/example.md")


    def test_mark_applied_does_not_fallback_to_scheduler_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(
                    conn,
                    {
                        "source": "test",
                        "source_job_id": "scheduler-draft",
                        "title": "Market Data Analyst",
                        "company": "Example Fintech",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "apply_url": "https://example.com/apply",
                        "description": "Python SQL market data reporting.",
                        "score": 80,
                        "scheduler_resume_draft_path": "data/resumes/scheduler.pdf",
                        "resume_file_generated": "data/resumes/legacy.pdf",
                    },
                )
            finally:
                conn.close()

            row = build_campaign_row(job, campaign_date="20260625")
            row["profile_resume_path"] = ""
            row["tailored_resume_path"] = ""
            save_campaign_items(db, [row])
            update_campaign_item_status("20260625", job["canonical_job_id"], "applied", notes="submitted", db_path=db)

            detail = get_job_detail(job["canonical_job_id"], db)
            self.assertEqual(detail["status"], "applied")
            self.assertEqual(detail["resume_used"], "")

    def test_update_campaign_item_files_can_persist_cover_letter_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(conn, _job(66, score=80))
            finally:
                conn.close()
            row = build_campaign_row(job, campaign_date="20260625")
            save_campaign_items(db, [row])
            update_campaign_item_files(
                "20260625",
                row["canonical_job_id"],
                cover_letter_path="data/cover_letters/job_66/cover_letter.md",
                db_path=db,
            )
            rows = get_campaign_items(db, campaign_date="20260625")

        self.assertEqual(rows[0]["cover_letter_path"], "data/cover_letters/job_66/cover_letter.md")


    def test_update_campaign_item_files_stores_workspace_and_formal_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(conn, _job(68, score=80))
            finally:
                conn.close()
            row = build_campaign_row(job, campaign_date="20260625")
            save_campaign_items(db, [row])
            update_campaign_item_files(
                "20260625",
                row["canonical_job_id"],
                application_workspace_path="generated/20260625/example/analyst__job68",
                resume_pdf_path="generated/20260625/example/analyst__job68/resume.pdf",
                cover_letter_pdf_path="generated/20260625/example/analyst__job68/cover.pdf",
                cover_letter_body_path="generated/20260625/example/analyst__job68/cover_letter_body.txt",
                answer_pack_path="generated/20260625/example/analyst__job68/answer_pack.md",
                db_path=db,
            )
            rows = get_campaign_items(db, campaign_date="20260625")
            detail = get_job_detail(job["canonical_job_id"], db)

        self.assertEqual(rows[0]["application_workspace_path"], "generated/20260625/example/analyst__job68")
        self.assertEqual(rows[0]["resume_pdf_path"], "generated/20260625/example/analyst__job68/resume.pdf")
        self.assertEqual(rows[0]["cover_letter_pdf_path"], "generated/20260625/example/analyst__job68/cover.pdf")
        self.assertEqual(rows[0]["cover_letter_body_path"], "generated/20260625/example/analyst__job68/cover_letter_body.txt")
        self.assertEqual(rows[0]["answer_pack_path"], "generated/20260625/example/analyst__job68/answer_pack.md")
        self.assertEqual(detail["application_workspace_path"], "generated/20260625/example/analyst__job68")
        self.assertEqual(detail["resume_pdf_path"], "generated/20260625/example/analyst__job68/resume.pdf")
        self.assertEqual(detail["cover_letter_pdf_path"], "generated/20260625/example/analyst__job68/cover.pdf")
    def test_update_campaign_item_files_migrates_legacy_cover_letter_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(conn, _job(67, score=80))
            finally:
                conn.close()

            conn = sqlite3.connect(db)
            try:
                conn.execute("DROP TABLE campaign_items")
                conn.execute(
                    """
                    CREATE TABLE campaign_items (
                        id INTEGER PRIMARY KEY,
                        campaign_date TEXT,
                        canonical_job_id TEXT,
                        application_effort TEXT,
                        campaign_status TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO campaign_items (campaign_date, canonical_job_id, application_effort, campaign_status)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("20260625", job["canonical_job_id"], "deep_tailor", "queued"),
                )
                conn.commit()
            finally:
                conn.close()

            update_campaign_item_files(
                "20260625",
                job["canonical_job_id"],
                cover_letter_path="data/cover_letters/job_67/cover_letter.md",
                db_path=db,
            )
            conn = connect(db)
            try:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(campaign_items)").fetchall()}
                saved = conn.execute(
                    "SELECT cover_letter_path FROM campaign_items WHERE canonical_job_id = ?",
                    (job["canonical_job_id"],),
                ).fetchone()
            finally:
                conn.close()

        self.assertIn("cover_letter_path", columns)
        self.assertEqual(saved["cover_letter_path"], "data/cover_letters/job_67/cover_letter.md")

    def test_campaign_tailored_generation_uses_selected_resume_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(
                    conn,
                    {
                        "source": "test",
                        "source_job_id": "risk-profile",
                        "title": "Risk Operations Analyst",
                        "company": "Example Fintech",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "description": "Risk operations controls reporting Python SQL.",
                        "score": 80,
                        "role_category": "risk",
                    },
                )
            finally:
                conn.close()

            row = build_campaign_row(job, campaign_date="20260625")
            row["resume_profile"] = "risk_operations"
            row["allow_manual_generate_resume"] = True
            with patch("job_pipeline.dashboard.DEFAULT_DB", db), patch("job_pipeline.dashboard.generate_resume", return_value={"pdf": "tailored.pdf"}) as generate_resume:
                result = _generate_tailored_resume_for_campaign(row)

        self.assertEqual(result, "tailored.pdf")
        self.assertEqual(generate_resume.call_args.kwargs["master_resume_path"].name, "risk_operations.example.yaml")

    def test_campaign_items_mark_stale_when_job_score_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(conn, _job(68, score=42))
            finally:
                conn.close()

            save_campaign_items(db, [build_campaign_row(job, campaign_date="20260625")])

            conn = connect(db)
            try:
                upsert_job(conn, _job(68, score=100))
            finally:
                conn.close()

            rows = get_campaign_items(db, campaign_date="20260625")

        self.assertEqual(rows[0]["campaign_score"], 42)
        self.assertEqual(rows[0]["current_score"], 100)
        self.assertTrue(rows[0]["campaign_stale"])

    def test_campaign_items_fall_back_to_joined_role_family_and_fit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            conn = connect(db)
            try:
                job, _ = upsert_job(
                    conn,
                    _job(69, score=60, role_family="risk_fraud_compliance", fit_category="core_fit"),
                )
            finally:
                conn.close()

            save_campaign_items(db, [build_campaign_row(job, campaign_date="20260625")])
            rows = get_campaign_items(db, campaign_date="20260625")

        self.assertEqual(rows[0]["role_family"], "risk_fraud_compliance")
        self.assertEqual(rows[0]["fit_category"], "core_fit")

    def test_replace_campaign_items_prunes_stale_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            first = build_campaign_row(_job(70, score=80), campaign_date="20260625")
            stale = build_campaign_row(_job(71, score=60), campaign_date="20260625")
            save_campaign_items(db, [first, stale])
            replace_campaign_items(db, "20260625", [first])
            conn = connect(db)
            try:
                rows = conn.execute("SELECT canonical_job_id FROM campaign_items WHERE campaign_date = ? ORDER BY canonical_job_id", ("20260625",)).fetchall()
            finally:
                conn.close()
            self.assertEqual([row["canonical_job_id"] for row in rows], [first["canonical_job_id"]])


    def test_save_campaign_items_refreshes_snapshot_on_conflict_and_preserves_manual_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jobs.sqlite"
            first = build_campaign_row(_job(79, score=42), campaign_date="20260625")
            refreshed = build_campaign_row(_job(79, score=100), campaign_date="20260625")
            save_campaign_items(db, [first])
            update_campaign_item_status("20260625", first["canonical_job_id"], "applied", notes="submitted", db_path=db)
            save_campaign_items(db, [refreshed])
            conn = connect(db)
            try:
                stored = conn.execute(
                    """
                    SELECT campaign_status, campaign_score, campaign_reason
                    FROM campaign_items
                    WHERE campaign_date = ? AND canonical_job_id = ?
                    """,
                    ("20260625", first["canonical_job_id"]),
                ).fetchone()
            finally:
                conn.close()

        self.assertEqual(stored["campaign_status"], "applied")
        self.assertEqual(stored["campaign_score"], 100)
        self.assertIn("score 100", stored["campaign_reason"])

    def test_adjacent_role_can_enter_quick_apply(self):
        row = build_campaign_row(_job(80, score=40, fit_category="adjacent_fit", role_family="technical_operations"), campaign_date="20260625")
        self.assertEqual(row["application_effort"], "quick_apply")
        self.assertEqual(row["role_family"], "technical_operations")
        self.assertEqual(row["fit_category"], "adjacent_fit")

    def test_skipped_rows_remain_out_of_selected_actionable_campaign(self):
        jobs = [
            _job(81, score=80, title="Fraud Analyst"),
            _job(82, score=0, title="Staff Software Engineer", hard_skip=True, fit_category="skip"),
        ]
        result = build_daily_campaign(jobs, campaign_date="20260625", deep=2, standard=2, quick=2)
        self.assertEqual([row["canonical_job_id"] for row in result["selected"]], ["job_81"])
        self.assertEqual([row["canonical_job_id"] for row in result["skip"]], ["job_82"])

    def test_role_family_appears_in_campaign_row(self):
        row = build_campaign_row(_job(83, score=60, role_family="risk_fraud_compliance", fit_category="adjacent_fit"), campaign_date="20260625")
        self.assertEqual(row["role_family"], "risk_fraud_compliance")
        self.assertEqual(row["fit_category"], "adjacent_fit")

    def test_dashboard_tab_labels_include_application_campaign(self):
        self.assertIn("Application Campaign", DASHBOARD_TAB_LABELS)


if __name__ == "__main__":
    unittest.main()
