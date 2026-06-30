import unittest
from pathlib import Path

from job_pipeline.resources import load_candidate_master, load_role_profile
from job_pipeline.resume_tailor import render_markdown_resume
from job_pipeline.workspace import PathRegistry


class PublicExampleResourceTests(unittest.TestCase):
    def test_missing_local_candidate_profile_has_setup_error(self):
        paths = PathRegistry.from_project_root(Path(__file__).resolve().parents[1])
        with self.assertRaisesRegex(FileNotFoundError, "Copy resources/candidate/master_profile.example.yaml"):
            load_candidate_master(paths)

    def test_candidate_example_loads_only_when_explicitly_allowed(self):
        paths = PathRegistry.from_project_root(Path(__file__).resolve().parents[1])
        master = load_candidate_master(paths, allow_example=True)
        self.assertEqual(master["name"], "Candidate Name")
        self.assertEqual(master["contact"]["email"], "candidate@example.com")

    def test_role_profile_examples_are_usable_resume_sources(self):
        paths = PathRegistry.from_project_root(Path(__file__).resolve().parents[1])
        profile = load_role_profile("risk_operations", paths)
        markdown = render_markdown_resume(
            profile,
            {"company": "Example Company", "title": "Example Risk Role", "role_category": "risk", "score": 80},
            {"top_keywords": ["risk", "reporting", "python"]},
        )
        self.assertIn("Candidate Name", markdown)
        self.assertIn("Example Risk Control Review Project", markdown)


if __name__ == "__main__":
    unittest.main()