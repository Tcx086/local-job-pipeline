import unittest

from job_pipeline.dedupe import dedupe_current_jobs, jobs_are_same
from job_pipeline.normalize import normalize_jobs
from job_pipeline.score import score_jobs


class CompanyDedupeTests(unittest.TestCase):
    def test_same_company_same_role_linkedin_greenhouse_merge(self):
        jobs = score_jobs(
            normalize_jobs(
                [
                    {
                        "source": "linkedin",
                        "source_job_id": "li-1",
                        "title": "Market Data Analyst",
                        "company": "Wealthsimple",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "job_url": "https://linkedin.example/jobs/1",
                        "description": "Python SQL market data reporting reconciliation operations.",
                    },
                    {
                        "source": "greenhouse",
                        "source_job_id": "gh-1",
                        "title": "Market Data Analyst",
                        "company": "Wealthsimple Inc.",
                        "location": "Toronto, ON",
                        "country": "Canada",
                        "job_url": "https://boards.greenhouse.io/wealthsimple/jobs/1",
                        "description": "Python SQL market data reporting reconciliation operations.",
                    },
                ]
            )
        )
        unique, duplicates = dedupe_current_jobs(jobs)
        self.assertEqual(len(unique), 1)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(unique[0]["source"], "greenhouse")

    def test_same_company_slight_title_difference_merge(self):
        left = {
            "source": "indeed",
            "title": "API Support Analyst",
            "company": "OKX",
            "location": "Singapore",
            "description": "REST API support JSON market data troubleshooting dashboard.",
        }
        right = {
            "source": "lever",
            "title": "API Technical Support Analyst",
            "company": "OKX Ltd",
            "location": "Singapore",
            "description": "REST API support JSON market data troubleshooting dashboard.",
        }
        self.assertTrue(jobs_are_same(left, right))

    def test_different_company_same_title_not_merge(self):
        left = {
            "source": "indeed",
            "title": "Risk Analyst",
            "company": "DBS",
            "location": "Hong Kong",
            "description": "Risk reporting credit risk data checks.",
        }
        right = {
            "source": "greenhouse",
            "title": "Risk Analyst",
            "company": "RBC",
            "location": "Hong Kong",
            "description": "Risk reporting credit risk data checks.",
        }
        self.assertFalse(jobs_are_same(left, right))


if __name__ == "__main__":
    unittest.main()