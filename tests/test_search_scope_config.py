import tempfile
import unittest
from pathlib import Path

from job_pipeline.search_scope import SearchScopeError, load_search_scope, search_scope_to_search_config, validate_search_scope
from job_pipeline.utils import CONFIG_DIR


class SearchScopeConfigTests(unittest.TestCase):
    def test_example_search_scope_loads(self):
        scope = load_search_scope(CONFIG_DIR / "search_scope.example.yaml")
        config = search_scope_to_search_config(scope)

        self.assertIn("Canada", config["countries"])
        self.assertEqual(config["settings"]["site_name"], ["linkedin", "indeed", "google"])
        self.assertGreater(config["settings"]["results_wanted"], 0)

    def test_missing_local_falls_back_to_example(self):
        scope = load_search_scope()
        config = search_scope_to_search_config(scope, max_query_location_pairs=2)

        self.assertLessEqual(sum(len(payload["query_location_pairs"]) for payload in config["countries"].values()), 2)

    def test_invalid_site_is_rejected(self):
        scope = load_search_scope(CONFIG_DIR / "search_scope.example.yaml")
        scope["search"]["sites"] = ["linkedin", "not_a_board"]

        with self.assertRaises(SearchScopeError):
            validate_search_scope(scope)

    def test_enabled_country_requires_location_and_term(self):
        scope = {
            "search": {"hours_old": 24, "results_wanted": 5, "sleep_seconds": 1, "sites": ["indeed"]},
            "countries": {"Exampleland": {"enabled": True, "locations": [], "search_terms": ["Analyst"]}},
        }

        with self.assertRaises(SearchScopeError):
            validate_search_scope(scope)

    def test_custom_scope_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "search_scope.yaml"
            path.write_text(
                """
search:
  hours_old: 12
  results_wanted: 3
  sleep_seconds: 1
  sites: [indeed]
countries:
  Exampleland:
    enabled: true
    locations: [Remote]
    search_terms: [Operations Analyst]
""",
                encoding="utf-8",
            )
            scope = load_search_scope(path)

        self.assertIn("Exampleland", scope["countries"])


if __name__ == "__main__":
    unittest.main()
