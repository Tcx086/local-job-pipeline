import unittest

from job_pipeline.normalize import normalize_job
from job_pipeline.score import score_job
from job_pipeline.utils import normalize_text_escapes


class ScoreTests(unittest.TestCase):
    def test_strong_market_data_role_scores_high(self):
        job = normalize_job(
            {
                "title": "Market Data Analyst",
                "company": "Wealthsimple",
                "location": "Toronto, ON",
                "country": "Canada",
                "description": (
                    "Use Python, SQL, Excel, market data, reporting, data cleaning, "
                    "API integration, and dashboard workflows to support fintech operations."
                ),
            }
        )

        scored = score_job(job)

        self.assertGreaterEqual(scored["score"], 70)
        self.assertIn(scored["recommendation"], {"Strong apply", "Must apply"})
        self.assertIn("market data", scored["matched_keywords"])

    def test_senior_quant_cpp_role_is_filtered_down(self):
        job = normalize_job(
            {
                "title": "Senior Quant Trader - Low Latency C++",
                "company": "Example Trading",
                "location": "Singapore",
                "country": "Singapore",
                "description": (
                    "Requires PhD, 7+ years required, low latency C++ HFT experience, "
                    "advanced probability, and pure quant research track."
                ),
            }
        )

        scored = score_job(job)

        self.assertLess(scored["score"], 55)
        self.assertEqual(scored["recommendation"], "Hard skip")
        self.assertIn("low_latency_cpp", scored["red_flags"])
        self.assertIn("phd_required", scored["red_flags"])

    def test_senior_mentions_in_description_are_penalized(self):
        job = normalize_job(
            {
                "title": "Data Analyst",
                "company": "Example",
                "location": "Toronto, ON",
                "country": "Canada",
                "description": "Build SQL dashboards and present insights to senior leadership.",
            }
        )

        scored = score_job(job)

        self.assertIn("senior_or_lead_level", scored["red_flags"])
        self.assertLess(scored["score"], 55)


    def test_year_range_requirement_is_penalized(self):
        job = normalize_job(
            {
                "title": "Data Analyst",
                "company": "Sun Life",
                "location": "Toronto, ON",
                "country": "Canada",
                "description": (
                    "Use Python, SQL, market data, reporting, ETL and dashboard workflows. "
                    "The ideal candidate brings 3-5 years of data analytics experience."
                ),
            }
        )

        scored = score_job(job)

        self.assertLess(scored["score"], 70)
        self.assertIn("high_years_required", scored["red_flags"])
        self.assertIn("five_plus_years", scored["red_flags"])

    def test_escaped_seven_plus_years_is_hard_skip(self):
        job = normalize_job(
            {
                "title": "Calypso Support Analyst",
                "company": "Luxoft",
                "location": "Toronto, ON",
                "country": "Canada",
                "description": (
                    "Support Calypso production workflows, market data, settlements, and reporting. "
                    "7\\+ years of Capital Markets and Calypso experience preferred."
                ),
            }
        )

        scored = score_job(job)

        self.assertTrue(scored["hard_skip"])
        self.assertEqual(scored["recommendation"], "Hard skip")
        self.assertEqual(scored["score"], 0)
        self.assertIn("high_years_required", scored["red_flags"])
        self.assertIn("seven_plus_years", scored["filter_rule_ids"])

    def test_normalize_text_escapes_for_markdown_punctuation(self):
        self.assertEqual(normalize_text_escapes(r"7\+ years and Front\-to\-Back P\&L"), "7+ years and Front-to-Back P&L")


if __name__ == "__main__":
    unittest.main()
