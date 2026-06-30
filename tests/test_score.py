import unittest

from job_pipeline.normalize import normalize_job
from job_pipeline.score import score_job
from job_pipeline.utils import normalize_text_escapes


class ScoreTests(unittest.TestCase):
    def _score(self, payload):
        return score_job(normalize_job(payload))

    def test_strong_market_data_role_scores_high_without_crypto(self):
        scored = self._score(
            {
                "title": "Market Data Analyst",
                "company": "Wealthsimple",
                "location": "Toronto, ON",
                "country": "Canada",
                "description": (
                    "Use Python, SQL, Excel, market data, reporting, data validation, "
                    "dashboard workflows, and data quality checks to support fintech operations."
                ),
            }
        )

        self.assertGreaterEqual(scored["score"], 70)
        self.assertIn(scored["recommendation"], {"Strong apply", "Must apply"})
        self.assertEqual(scored["role_family"], "financial_data_analysis")
        self.assertIn(scored["fit_category"], {"core_fit", "adjacent_fit"})
        self.assertIn("market data", scored["matched_keywords"])

    def test_fraud_transaction_monitoring_scores_high_without_crypto(self):
        scored = self._score(
            {
                "title": "Fraud Analyst, Transaction Monitoring",
                "company": "Payments Co",
                "location": "Toronto, ON",
                "country": "Canada",
                "description": "Review fraud alerts, AML and KYC cases, SQL reporting, Excel queues, sanctions checks, controls, and payments risk patterns. 1+ years preferred.",
            }
        )

        self.assertGreaterEqual(scored["score"], 70)
        self.assertFalse(scored["hard_skip"])
        self.assertEqual(scored["role_family"], "risk_fraud_compliance")
        self.assertIn(scored["fit_category"], {"core_fit", "adjacent_fit"})
        self.assertIn("transaction monitoring", scored["matched_keywords"])

    def test_api_support_scores_high_without_crypto(self):
        scored = self._score(
            {
                "title": "API Support Analyst",
                "company": "Platform Co",
                "location": "Singapore",
                "country": "Singapore",
                "description": "Support REST API clients, troubleshoot JSON data issues, implementation workflows, integration tickets, dashboards, SQL reporting, and platform support.",
            }
        )

        self.assertGreaterEqual(scored["score"], 70)
        self.assertFalse(scored["hard_skip"])
        self.assertEqual(scored["role_family"], "technical_operations")
        self.assertIn(scored["fit_category"], {"core_fit", "adjacent_fit"})

    def test_digital_assets_research_still_scores_high(self):
        scored = self._score(
            {
                "title": "Digital Assets Research Analyst",
                "company": "Digital Asset Manager",
                "location": "Hong Kong",
                "country": "Hong Kong",
                "description": "Research blockchain, DeFi, Web3, tokenomics, on-chain data, wallets, smart contracts, market intelligence, SQL, Python, and dashboards.",
            }
        )

        self.assertGreaterEqual(scored["score"], 70)
        self.assertEqual(scored["role_family"], "digital_assets_research")
        self.assertEqual(scored["fit_category"], "core_fit")

    def test_senior_quant_cpp_role_is_filtered_down(self):
        scored = self._score(
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

        self.assertLess(scored["score"], 55)
        self.assertEqual(scored["recommendation"], "Hard skip")
        self.assertEqual(scored["fit_category"], "skip")
        self.assertIn("low_latency_cpp", scored["red_flags"])
        self.assertIn("phd_required", scored["red_flags"])

    def test_senior_stakeholders_do_not_create_senior_title_flag(self):
        scored = self._score(
            {
                "title": "Data Analyst",
                "company": "Example",
                "location": "Toronto, ON",
                "country": "Canada",
                "description": "Build SQL dashboards and present insights to senior stakeholders and senior leadership. 1-2 years experience preferred.",
            }
        )

        self.assertFalse(scored["hard_skip"])
        self.assertNotIn("senior_or_lead_level", scored["red_flags"])

    def test_year_range_requirement_is_penalized(self):
        scored = self._score(
            {
                "title": "Senior Data Analyst",
                "company": "Sun Life",
                "location": "Toronto, ON",
                "country": "Canada",
                "description": (
                    "Use Python, SQL, market data, reporting, ETL and dashboard workflows. "
                    "The ideal candidate brings 5+ years of data analytics experience."
                ),
            }
        )

        self.assertLess(scored["score"], 70)
        self.assertIn("high_years_required", scored["red_flags"])
        self.assertIn("five_plus_years", scored["red_flags"])

    def test_escaped_seven_plus_years_is_hard_skip(self):
        scored = self._score(
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

        self.assertTrue(scored["hard_skip"])
        self.assertEqual(scored["recommendation"], "Hard skip")
        self.assertEqual(scored["score"], 0)
        self.assertIn("high_years_required", scored["red_flags"])
        self.assertIn("seven_plus_years", scored["filter_rule_ids"])

    def test_normalize_text_escapes_for_markdown_punctuation(self):
        self.assertEqual(normalize_text_escapes(r"7\+ years and Front\-to\-Back P\&L"), "7+ years and Front-to-Back P&L")


if __name__ == "__main__":
    unittest.main()
