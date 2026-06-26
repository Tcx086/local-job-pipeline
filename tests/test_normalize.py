import unittest

from job_pipeline.normalize import normalize_job


class NormalizeJobTests(unittest.TestCase):
    def test_seniority_uses_title_before_description_reporting_lines(self):
        job = normalize_job(
            {
                "title": "Business Systems Analyst",
                "company": "Example",
                "location": "Toronto, ON",
                "description": "Reporting to the Manager, this role supports dashboard delivery.",
            }
        )



    def test_apply_url_falls_back_to_job_url(self):
        job = normalize_job(
            {
                "source": "linkedin",
                "title": "Operations Analyst",
                "company": "Example",
                "location": "Toronto, Ontario, Canada",
                "job_url": "https://www.linkedin.com/jobs/view/4431478042",
                "apply_url": None,
            }
        )

        self.assertEqual(job["apply_url"], "https://www.linkedin.com/jobs/view/4431478042")


if __name__ == "__main__":
    unittest.main()