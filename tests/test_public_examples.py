import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from job_pipeline import setup_wizard
from job_pipeline.config_loader import PUBLIC_CONFIGS
from job_pipeline.utils import PROJECT_ROOT, load_yaml


class PublicExampleTests(unittest.TestCase):
    def test_setup_wizard_dry_run_prints_plan_without_writing(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = setup_wizard.main(["--dry-run"])

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("Dry run", output)
        self.assertIn("search_scope", output)

    def test_public_example_configs_parse(self):
        example_paths = [spec.example_path for spec in PUBLIC_CONFIGS.values()]
        example_paths.extend(sorted((PROJECT_ROOT / "templates" / "resume_profiles").glob("*.example.yaml")))

        for path in example_paths:
            with self.subTest(path=path):
                self.assertTrue(path.exists())
                self.assertIsNotNone(load_yaml(path))

    def test_public_docs_and_examples_do_not_contain_original_private_strings(self):
        private_terms = [
            "Xiang" + "yun",
            "Ch" + "en",
            "job" + "_apply",
            "PG" + "WP",
            "E" + ":" + "\\",
        ]
        paths: list[Path] = []
        for folder in ["config", "docs", "templates"]:
            paths.extend(path for path in (PROJECT_ROOT / folder).rglob("*") if path.is_file())
        paths.extend([PROJECT_ROOT / "README.md", PROJECT_ROOT / ".env.example", PROJECT_ROOT / "LICENSE"])

        for path in paths:
            if path.suffix.lower() in {".docx", ".pdf", ".zip"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for term in private_terms:
                with self.subTest(path=path, term=term):
                    self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
