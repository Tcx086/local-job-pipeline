import unittest
from unittest.mock import patch

from job_pipeline.collect_jobspy import collect_jobs


class CollectJobSpyAttemptTests(unittest.TestCase):
    def test_zero_result_scrape_records_successful_attempt_per_source(self):
        def scrape_jobs(**kwargs):
            return []

        with patch("job_pipeline.collect_jobspy._import_jobspy", return_value=scrape_jobs):
            rows, attempts = collect_jobs(
                search_terms=["No Match Analyst"],
                locations=["Toronto"],
                country="Canada",
                site_name=["linkedin", "indeed"],
                sleep_seconds=0,
                run_id="run1",
                return_attempts=True,
            )

        self.assertEqual(rows, [])
        self.assertEqual(len(attempts), 2)
        for attempt in attempts:
            self.assertEqual(attempt["run_id"], "run1")
            self.assertEqual(attempt["country"], "Canada")
            self.assertEqual(attempt["query"], "No Match Analyst")
            self.assertEqual(attempt["location"], "Toronto")
            self.assertEqual(attempt["raw_count"], 0)
            self.assertTrue(attempt["success"])
            self.assertEqual(attempt["error_message"], "")
        self.assertEqual({attempt["source"] for attempt in attempts}, {"linkedin", "indeed"})

    def test_successful_scrape_records_source_counts_and_search_location(self):
        def scrape_jobs(**kwargs):
            return [
                {
                    "site": "linkedin",
                    "id": "job1",
                    "title": "Market Data Analyst",
                    "company": "Example",
                    "location": "Toronto, ON",
                    "country": "Canada",
                    "job_url": "https://example.com/job1",
                    "job_url_direct": None,
                    "description": "SQL Python market data",
                }
            ]

        with patch("job_pipeline.collect_jobspy._import_jobspy", return_value=scrape_jobs):
            rows, attempts = collect_jobs(
                search_terms=["Market Data Analyst"],
                locations=["Toronto"],
                country="Canada",
                site_name=["linkedin", "indeed"],
                sleep_seconds=0,
                run_id="run1",
                return_attempts=True,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["location"], "Toronto, ON")
        self.assertEqual(rows[0]["search_location_used"], "Toronto")
        self.assertEqual(rows[0]["apply_url"], "https://example.com/job1")
        counts = {attempt["source"]: attempt["raw_count"] for attempt in attempts}
        self.assertEqual(counts, {"linkedin": 1, "indeed": 0})

if __name__ == "__main__":
    unittest.main()
