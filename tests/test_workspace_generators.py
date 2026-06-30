import json
import tempfile
import unittest
from pathlib import Path

from job_pipeline.application_answers import generate_answer_pack, load_answer_pack
from job_pipeline.cover_letter import generate_cover_letter
from job_pipeline.resources import load_candidate_master, load_common_answers, load_cover_letter_human_templates
from job_pipeline.resume_tailor import generate_resume
from job_pipeline.workspace import PathRegistry


MASTER_RESUME = """
name: Test Candidate
location: Toronto, ON
contacts:
  email: test@example.com
headline: Operations data analyst
summary:
  - Analyst with Python SQL reporting experience.
skills:
  technical:
    - Python
    - SQL
projects:
  - name: Operations Reporting
    type: Project
    dates: 2025
    bullets:
      - Built Python SQL reporting for reconciliation workflows.
experience:
  - title: Operations Analyst
    company: Example Bank
    location: Toronto
    dates: 2024-2025
    bullets:
      - Supported reporting and data quality controls.
"""


class ResourceLoaderTests(unittest.TestCase):
    def test_resources_path_wins_and_legacy_fallback_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resource = root / "resources" / "templates" / "answer_packs" / "common_answers.yaml"
            legacy = root / "config" / "common_answers.yaml"
            resource.parent.mkdir(parents=True)
            legacy.parent.mkdir(parents=True)
            resource.write_text("questions:\n  why_role:\n    template: resource answer\n", encoding="utf-8")
            legacy.write_text("questions:\n  why_role:\n    template: legacy answer\n", encoding="utf-8")
            paths = PathRegistry.from_project_root(root)

            self.assertEqual(load_common_answers(paths)["questions"]["why_role"]["template"], "resource answer")
            resource.unlink()
            self.assertEqual(load_common_answers(paths)["questions"]["why_role"]["template"], "legacy answer")

    def test_optional_templates_missing_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_cover_letter_human_templates(PathRegistry.from_project_root(Path(tmp))), {})

    def test_missing_candidate_master_has_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, "Candidate master profile not found"):
                load_candidate_master(PathRegistry.from_project_root(Path(tmp)))


class WorkspaceGeneratorTests(unittest.TestCase):
    def test_generators_share_application_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = PathRegistry.from_project_root(root)
            master = root / "master_resume.yaml"
            common = root / "common_answers.yaml"
            profile = root / "apply_profile.yaml"
            policy = root / "sensitive_policy.yaml"
            master.write_text(MASTER_RESUME, encoding="utf-8")
            common.write_text("questions: {}\n", encoding="utf-8")
            profile.write_text("{}\n", encoding="utf-8")
            policy.write_text("warning: Sensitive fields must be answered manually.\n", encoding="utf-8")
            job = {
                "canonical_job_id": "Job:ABC/123",
                "company": "Bombardier",
                "title": "Analyst Quality Assurance",
                "country": "Canada",
                "role_category": "quality_assurance",
                "role_family": "quality_assurance",
                "description": "Quality documentation data checks with Python SQL.",
                "score": 88,
            }

            resume = generate_resume(
                master_resume_path=master,
                job=job,
                keyword_info={"top_keywords": ["python", "sql", "quality"]},
                output_dir=None,
                path_registry=paths,
                workspace_date="20260630",
                make_docx=False,
                make_pdf=False,
            )
            cover = generate_cover_letter(
                job,
                generated_resume_file=resume["pdf"],
                output_dir=None,
                master_resume_path=master,
                common_answers_path=common,
                path_registry=paths,
                workspace_date="20260630",
                make_docx=False,
                make_pdf=False,
            )
            pack = generate_answer_pack(
                job,
                generated_resume_file=resume["pdf"],
                output_dir=None,
                master_resume_path=master,
                apply_profile_path=profile,
                common_answers_path=common,
                sensitive_policy_path=policy,
                path_registry=paths,
                workspace_date="20260630",
            )

            workspace = root / "generated" / "20260630" / "bombardier" / "analyst_quality_assurance__job_abc_123"
            self.assertEqual(Path(resume["workspace"]), workspace)
            self.assertEqual(Path(cover["paths"]["workspace"]), workspace)
            self.assertEqual(Path(pack["paths"]["workspace"]), workspace)
            self.assertEqual(Path(cover["paths"]["body_txt"]).parent, workspace)
            self.assertEqual(Path(pack["paths"]["markdown"]).parent, workspace)
            self.assertEqual(Path(resume["source_json"]).parent, workspace / "source")
            self.assertEqual(Path(cover["paths"]["source_json"]).parent, workspace / "source")
            self.assertEqual(Path(pack["paths"]["json"]).parent, workspace / "source")
            self.assertEqual(Path(cover["paths"]["review_markdown"]).parent, workspace / "review")
            self.assertEqual(Path(resume["markdown_review"]).parent, workspace / "review")
            resume_source = json.loads(Path(resume["source_json"]).read_text(encoding="utf-8"))
            cover_source = json.loads(Path(cover["paths"]["source_json"]).read_text(encoding="utf-8"))
            pack_source = json.loads(Path(pack["paths"]["json"]).read_text(encoding="utf-8"))
            self.assertEqual(resume_source["metadata"]["canonical_job_id"], "Job:ABC/123")
            self.assertEqual(cover_source["metadata"]["canonical_job_id"], "Job:ABC/123")
            self.assertEqual(pack_source["metadata"]["canonical_job_id"], "Job:ABC/123")
            for value in [*resume.values(), *cover["paths"].values(), *pack["paths"].values()]:
                self.assertNotIn("data/resumes", str(value).replace("\\", "/"))
                self.assertNotIn("data/cover_letters", str(value).replace("\\", "/"))
                self.assertNotIn("data/apply_assist", str(value).replace("\\", "/"))
                self.assertNotIn("generated/applications", str(value).replace("\\", "/"))

            loaded_pack = load_answer_pack("Job:ABC/123")
            self.assertIsNone(loaded_pack)


if __name__ == "__main__":
    unittest.main()
