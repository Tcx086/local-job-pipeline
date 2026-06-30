import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from job_pipeline.database import connect, get_job_detail
from job_pipeline.migrations.migrate_artifacts import main as migrate_main
from job_pipeline.migrations.migrate_artifacts import migrate_artifacts
from job_pipeline.workspace import ApplicationWorkspace, PathRegistry


class ArtifactMigrationTests(unittest.TestCase):
    def test_migrate_legacy_job_artifacts_to_generated_workspace(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            resume = root / "data" / "resumes" / "legacy_resume.pdf"
            cover = root / "data" / "cover_letters" / "legacy_cover.md"
            answer = root / "data" / "apply_assist" / "job1" / "answer_pack.md"
            for path, text in [(resume, "resume"), (cover, "cover"), (answer, "answer")]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            db_path = root / "data" / "db" / "job_pipeline.sqlite"
            conn = connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        canonical_job_id, source, source_job_id, title, company, description, score,
                        scheduler_resume_draft_path, cover_letter_path, answer_pack_path, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "job1",
                        "test",
                        "source1",
                        "QA Analyst",
                        "Acme",
                        "Role description",
                        90,
                        "data/resumes/legacy_resume.pdf",
                        "data/cover_letters/legacy_cover.md",
                        "data/apply_assist/job1/answer_pack.md",
                        "2026-06-25T00:00:00Z",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            summary = migrate_artifacts(db_path, project_root=root, dry_run=False)
            registry = PathRegistry.from_project_root(root)
            workspace = ApplicationWorkspace.from_job(
                {"canonical_job_id": "job1", "title": "QA Analyst", "company": "Acme"},
                paths=registry,
                date="20260625",
            )

            self.assertEqual(summary.scanned_records, 1)
            self.assertEqual(summary.records_with_artifacts, 1)
            self.assertEqual(summary.copied_files, 3)
            self.assertTrue(workspace.resume_pdf_path().exists())
            self.assertTrue(workspace.cover_letter_review_md_path().exists())
            self.assertTrue(workspace.answer_pack_md_path().exists())
            self.assertTrue(workspace.manifest_path.exists())

            detail = get_job_detail("job1", db_path)
            self.assertEqual(detail["application_workspace_path"], str(workspace.root))
            self.assertEqual(detail["resume_pdf_path"], str(workspace.resume_pdf_path()))
            self.assertEqual(detail["cover_letter_path"], str(workspace.cover_letter_review_md_path()))
            self.assertEqual(detail["answer_pack_path"], str(workspace.answer_pack_md_path()))

    def test_migrate_artifacts_dry_run_does_not_write_files_or_db(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            resume = root / "data" / "resumes" / "legacy_resume.pdf"
            resume.parent.mkdir(parents=True, exist_ok=True)
            resume.write_text("resume", encoding="utf-8")
            db_path = root / "data" / "db" / "job_pipeline.sqlite"
            conn = connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        canonical_job_id, source, source_job_id, title, company, description, score,
                        scheduler_resume_draft_path, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("job1", "test", "source1", "QA Analyst", "Acme", "Role description", 90, "data/resumes/legacy_resume.pdf", "2026-06-25T00:00:00Z"),
                )
                conn.commit()
            finally:
                conn.close()

            summary = migrate_artifacts(db_path, project_root=root, dry_run=True)
            workspace = ApplicationWorkspace.from_job(
                {"canonical_job_id": "job1", "title": "QA Analyst", "company": "Acme"},
                paths=PathRegistry.from_project_root(root),
                date="20260625",
            )

            self.assertTrue(summary.dry_run)
            self.assertEqual(summary.copied_files, 1)
            self.assertFalse(workspace.resume_pdf_path().exists())
            detail = get_job_detail("job1", db_path)
            self.assertEqual(detail["resume_pdf_path"], "")

    def test_cli_defaults_to_dry_run_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            resume = root / "data" / "resumes" / "legacy_resume.pdf"
            resume.parent.mkdir(parents=True, exist_ok=True)
            resume.write_text("resume", encoding="utf-8")
            db_path = root / "data" / "db" / "job_pipeline.sqlite"
            conn = connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        canonical_job_id, source, source_job_id, title, company, description, score,
                        scheduler_resume_draft_path, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("job1", "test", "source1", "QA Analyst", "Acme", "Role description", 90, "data/resumes/legacy_resume.pdf", "2026-06-25T00:00:00Z"),
                )
                conn.commit()
            finally:
                conn.close()

            output = StringIO()
            with patch("sys.argv", ["migrate_artifacts", "--db", str(db_path), "--project-root", str(root), "--json"]), redirect_stdout(output):
                self.assertEqual(migrate_main(), 0)
            payload = json.loads(output.getvalue())
            workspace = ApplicationWorkspace.from_job(
                {"canonical_job_id": "job1", "title": "QA Analyst", "company": "Acme"},
                paths=PathRegistry.from_project_root(root),
                date="20260625",
            )

            self.assertTrue(payload["dry_run"])
            self.assertIn("No --apply supplied", payload["message"])
            self.assertFalse(workspace.resume_pdf_path().exists())
            detail = get_job_detail("job1", db_path)
            self.assertEqual(detail["resume_pdf_path"], "")

    def test_cli_rejects_dry_run_and_apply_together(self):
        with patch("sys.argv", ["migrate_artifacts", "--dry-run", "--apply"]), patch("sys.stderr", StringIO()):
            with self.assertRaises(SystemExit) as exc:
                migrate_main()
        self.assertEqual(exc.exception.code, 2)

if __name__ == "__main__":
    unittest.main()
