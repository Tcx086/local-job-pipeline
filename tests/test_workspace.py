import tempfile
import unittest
from pathlib import Path

from job_pipeline.workspace import ApplicationWorkspace, PathRegistry


class PathRegistryTests(unittest.TestCase):
    def test_default_paths_are_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = PathRegistry.from_project_root(root)
            self.assertEqual(paths.resources_dir, root / "resources")
            self.assertEqual(paths.generated_dir, root / "generated")
            self.assertEqual(paths.data_dir, root / "data")
            self.assertEqual(paths.db_path, root / "data" / "db" / "job_pipeline.sqlite")

    def test_effective_db_path_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "data" / "job_pipeline.sqlite"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("", encoding="utf-8")
            paths = PathRegistry.from_project_root(root)
            self.assertEqual(paths.effective_db_path(), legacy)

    def test_resolve_generated_and_resource_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "config" / "common_answers.yaml"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("legacy: true", encoding="utf-8")
            paths = PathRegistry.from_project_root(root)
            self.assertEqual(paths.resolve_generated("20260630"), root / "generated" / "20260630")
            self.assertEqual(paths.resource_path("common_answers"), root / "resources" / "common_answers")
            self.assertEqual(paths.existing_resource_path("common_answers", legacy=legacy), legacy)


class ApplicationWorkspaceTests(unittest.TestCase):
    def test_workspace_paths_follow_application_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = PathRegistry.from_project_root(root)
            workspace = ApplicationWorkspace.from_job(
                {
                    "canonical_job_id": "Job:ABC/123",
                    "company": "Bombardier",
                    "title": "Analyst Quality Assurance",
                    "country": "Canada",
                    "role_category": "quality_assurance",
                    "role_family": "quality_assurance",
                },
                paths=paths,
                date="20260630",
            )

            expected_root = root / "generated" / "20260630" / "bombardier" / "analyst_quality_assurance__job_abc_123"
            self.assertEqual(workspace.root, expected_root)
            self.assertEqual(workspace.canonical_job_id, "Job:ABC/123")
            self.assertEqual(workspace.job_slug, "job_abc_123")
            self.assertNotIn("generated/applications", workspace.root.as_posix())
            self.assertEqual(workspace.resume_pdf_path().parent, workspace.root)
            self.assertEqual(workspace.cover_letter_pdf_path().parent, workspace.root)
            self.assertEqual(workspace.answer_pack_md_path().parent, workspace.root)
            self.assertEqual(workspace.notes_path().parent, workspace.root)
            self.assertEqual(workspace.job_description_path().parent.name, "source")
            self.assertEqual(workspace.resume_review_md_path().parent.name, "review")
            self.assertEqual(workspace.submission_record_path().parent.name, "application")
            self.assertFalse(workspace.root.exists())

            workspace.ensure_dirs()
            self.assertTrue(workspace.root.exists())
            self.assertTrue(workspace.source_dir.exists())
            self.assertTrue(workspace.review_dir.exists())
            self.assertTrue(workspace.application_dir.exists())
            manifest = workspace.write_manifest()
            self.assertTrue(workspace.manifest_path.exists())
            self.assertEqual(manifest["canonical_job_id"], "Job:ABC/123")
            self.assertEqual(manifest["job_slug"], "job_abc_123")
            self.assertEqual(workspace.read_manifest(), manifest)


if __name__ == "__main__":
    unittest.main()
