import tempfile
import unittest
from pathlib import Path

from job_pipeline.dedupe import dedupe_jobs, merge_jobs
from job_pipeline.normalize import normalize_jobs


class DedupeTests(unittest.TestCase):
    def test_duplicate_url_and_fingerprint_are_not_returned_as_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite"
            jobs = normalize_jobs(
                [
                    {
                        "job_id": "job_1",
                        "source": "indeed",
                        "title": "Market Data Analyst",
                        "company": "RBC",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "job_url": "https://example.com/job-1",
                        "description": "Python SQL market data reporting.",
                    },
                    {
                        "job_id": "job_2",
                        "source": "linkedin",
                        "title": "Market Data Analyst",
                        "company": "RBC Inc.",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "job_url": "https://example.com/job-1",
                        "description": "Python SQL market data reporting.",
                    },
                ]
            )

            new_jobs, duplicates = dedupe_jobs(jobs, db_path=db_path)

            self.assertEqual(len(new_jobs), 1)
            self.assertEqual(len(duplicates), 1)
            self.assertEqual(duplicates[0]["duplicate_of_job_id"], "job_1")

    def test_merge_jobs_ignores_nan_urls(self):
        merged = merge_jobs(
            {
                "source": "linkedin",
                "title": "Market Data Analyst",
                "company": "RBC",
                "location": "Toronto, ON",
                "job_url": float("nan"),
                "apply_url": "https://example.com/apply",
                "all_source_urls": [float("nan"), "https://example.com/job"],
            },
            {
                "source": "indeed",
                "title": "Market Data Analyst",
                "company": "RBC",
                "location": "Toronto, ON",
                "job_url": "nan",
                "apply_url": "",
            },
        )

        self.assertEqual(
            merged["all_source_urls"],
            ["https://example.com/apply", "https://example.com/job"],
        )


if __name__ == "__main__":
    unittest.main()
