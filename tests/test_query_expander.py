import unittest

from job_pipeline.query_expander import build_search_config, describe_search_plan, expand_queries, get_search_mode, rotate_query_location_pairs


class QueryExpanderTests(unittest.TestCase):
    def test_strict_uses_base_titles(self):
        queries = expand_queries("strict")
        self.assertIn("Trading Operations Analyst", queries)
        self.assertNotIn("Trading Operations Analyst fintech", queries)

    def test_broad_adds_industry_modifiers_and_locations(self):
        queries = expand_queries("broad", max_queries=500)
        self.assertIn("Market Data Analyst fintech", queries)
        config = build_search_config("normal", no_rotation=True)
        self.assertIn("Canada", config["countries"])
        self.assertNotIn("United States", config["countries"])

    def test_mode_defaults(self):
        mode = get_search_mode("backfill")
        self.assertEqual(mode["days_back"], 90)
        self.assertEqual(mode["results_wanted_per_query"], 100)
        self.assertEqual(get_search_mode("normal")["min_score_report"], 35)

    def test_max_query_location_pairs_limits_plan_size(self):
        config = build_search_config("normal", max_query_location_pairs=30, no_rotation=True)
        plan = describe_search_plan(config, mode="normal")
        self.assertLessEqual(plan["total_query_location_pairs"], 30)

    def test_query_rotation_is_stable_for_date(self):
        pairs = [("Canada", f"query {idx}", "Toronto") for idx in range(100)]
        first = rotate_query_location_pairs(pairs, mode="normal", rotation_date="2026-06-25", limit=10)
        second = rotate_query_location_pairs(pairs, mode="normal", rotation_date="2026-06-25", limit=10)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 10)


if __name__ == "__main__":
    unittest.main()
