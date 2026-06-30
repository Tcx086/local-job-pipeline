import json
import tempfile
import unittest
from pathlib import Path

from job_pipeline.application_answers import generate_answer_pack
from job_pipeline.cover_letter import generate_cover_letter
from job_pipeline.profile_export import export_profile

MASTER_PROFILE = """
name: Test Candidate
location: City, Country
contacts:
  email: test@example.com
headline: Example analyst candidate
summary:
  - Analyst with Python SQL reporting experience.
skills:
  technical:
    - Python
    - SQL
projects:
  example_project:
    title: Example Project
    type: Project
    dates: 2026
    bullets:
      - Built Python SQL reporting for sample workflows.
experience:
  - title: Example Analyst
    company: Example Company
    location: City, Country
    dates: 2026
    bullets:
      - Supported reporting and documentation checks.
"""

class ApplyAssistTests(unittest.TestCase):
    def test_answer_pack_uses_job_and_resume_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            master = out / "master_profile.yaml"
            master.write_text(MASTER_PROFILE, encoding="utf-8")
            job = {
                "canonical_job_id": "job123",
                "title": "Market Data Analyst",
                "company": "Example Fintech",
                "country": "Canada",
                "role_category": "data",
                "apply_url": "https://example.com/apply",
                "description": "Python SQL market data API reporting and risk controls.",
            }
            pack = generate_answer_pack(job, generated_resume_file="resume.docx", output_dir=out, master_resume_path=master)
            md = Path(pack["paths"]["markdown"])
            js = Path(pack["paths"]["json"])
            self.assertTrue(md.exists())
            self.assertTrue(js.exists())
            self.assertIn("Example Fintech", md.read_text(encoding="utf-8"))
            self.assertIn("ANSWER MANUALLY", md.read_text(encoding="utf-8"))
            self.assertIn("python", " ".join(pack["top_keywords_to_mention"]).lower())
            self.assertIn("work_authorization", pack["answers"])

    def test_cover_letter_apply_assist_output_uses_human_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            master = out / "master_profile.yaml"
            master.write_text(MASTER_PROFILE, encoding="utf-8")
            job = {
                "canonical_job_id": "job_cover",
                "title": "Market Data Analyst",
                "company": "Example Fintech",
                "country": "Canada",
                "role_category": "data",
                "apply_url": "https://example.com/apply",
                "description": "Python SQL market data reporting and documentation.",
            }
            cover = generate_cover_letter(job, generated_resume_file="resume.pdf", output_dir=out, master_resume_path=master, make_docx=False, make_pdf=False)
            md = Path(cover["paths"]["markdown"])
            js = Path(cover["paths"]["json"])
            self.assertTrue(md.exists())
            self.assertTrue(js.exists())
            self.assertIn("Manual review required", md.read_text(encoding="utf-8"))
            self.assertTrue(cover["manual_review_required"])

    def test_profile_export_excludes_highly_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = export_profile(output_dir=out)
            payload = json.loads(Path(result["paths"]["json"]).read_text(encoding="utf-8"))
            text = Path(result["paths"]["markdown"]).read_text(encoding="utf-8").lower()
            self.assertIn("profile", payload)
            self.assertIn("standard_answers", payload)
            self.assertIn("skills", payload)
            self.assertNotIn("passport", text)
            self.assertNotIn("banking info", text)
            self.assertNotIn("exact dob", text)


if __name__ == "__main__":
    unittest.main()
