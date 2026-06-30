import unittest

from job_pipeline.query_expander import (
    build_search_config,
    describe_search_plan,
    expand_queries,
    expand_query_specs,
    get_search_mode,
    load_role_families,
    rotate_query_location_pairs,
)


class QueryExpanderTests(unittest.TestCase):
    def test_role_families_load_from_config(self):
        config = load_role_families()
        self.assertIn("digital_assets_research", config["families"])
        self.assertIn("financial_data_analysis", config["families"])
        self.assertIn("risk_fraud_compliance", config["families"])

    def test_strict_uses_strongest_role_families(self):
        specs = expand_query_specs("strict")
        queries = [item["query"] for item in specs]
        families = {item["role_family"] for item in specs}
        self.assertIn("Digital Assets Analyst", queries)
        self.assertIn("Market Data Analyst", queries)
        self.assertIn("Fraud Analyst", queries)
        self.assertNotIn("Technical Operations Analyst", queries)
        self.assertEqual(families, {"digital_assets_research", "financial_data_analysis", "risk_fraud_compliance"})

    def test_normal_generates_enabled_family_terms_with_metadata(self):
        specs = expand_query_specs("normal", max_queries=200)
        families = {item["role_family"] for item in specs}
        self.assertIn("technical_operations", families)
        self.assertIn("banking_operations", families)
        self.assertIn("Market Data Analyst fintech", [item["query"] for item in specs])

    def test_broad_adds_ai_data_governance_and_locations(self):
        queries = expand_queries("broad", max_queries=500)
        self.assertIn("AI Governance Analyst", queries)
        config = build_search_config("normal", no_rotation=True)
        self.assertIn("Canada", config["countries"])
        self.assertIn("Singapore", config["countries"])
        self.assertIn("Hong Kong", config["countries"])

    def test_mode_defaults(self):
        mode = get_search_mode("backfill")
        self.assertEqual(mode["days_back"], 90)
        self.assertEqual(mode["results_wanted_per_query"], 100)
        self.assertEqual(get_search_mode("normal")["min_score_report"], 35)

    def test_max_query_location_pairs_limits_plan_size(self):
        config = build_search_config("normal", max_query_location_pairs=30, no_rotation=True)
        plan = describe_search_plan(config, mode="normal")
        self.assertLessEqual(plan["total_query_location_pairs"], 30)
        self.assertIn("role_family_query_location_pairs", plan)

    def test_query_rotation_is_stable_for_date(self):
        pairs = [("Canada", f"query {idx}", "Toronto") for idx in range(100)]
        first = rotate_query_location_pairs(pairs, mode="normal", rotation_date="2026-06-25", limit=10)
        second = rotate_query_location_pairs(pairs, mode="normal", rotation_date="2026-06-25", limit=10)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 10)


if __name__ == "__main__":
    unittest.main()
