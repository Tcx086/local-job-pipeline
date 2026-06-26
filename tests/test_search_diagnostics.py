import unittest

from job_pipeline.search_diagnostics import build_coverage_rows


class SearchDiagnosticsTests(unittest.TestCase):
    def test_build_coverage_funnel_counts(self):
        raw = [
            {"source": "linkedin", "country": "Canada", "search_term_used": "Market Data Analyst", "location": "Toronto"},
            {"source": "linkedin", "country": "Canada", "search_term_used": "Market Data Analyst", "location": "Toronto"},
        ]
        normalized = [dict(item) for item in raw]
        scored = [
            {**raw[0], "score": 80, "hard_skip": False},
            {**raw[1], "score": 20, "hard_skip": True},
        ]
        deduped = [scored[0]]
        reported = [scored[0]]
        duplicates = [{**scored[1], "duplicate_of_job_id": "abc"}]

        rows = build_coverage_rows(
            run_id="run1",
            run_started_at="start",
            run_finished_at="finish",
            mode="normal",
            raw_jobs=raw,
            normalized_jobs=normalized,
            scored_jobs=scored,
            deduped_jobs=deduped,
            reported_jobs=reported,
            duplicate_jobs=duplicates,
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["raw_count"], 2)
        self.assertEqual(row["deduped_count"], 1)
        self.assertEqual(row["report_count"], 1)
        self.assertEqual(row["skipped_by_filter_count"], 1)
        self.assertEqual(row["merged_by_dedupe_count"], 1)
        self.assertEqual(row["high_score_count_70"], 1)

    def test_zero_result_query_attempt_creates_coverage_row(self):
        rows = build_coverage_rows(
            run_id="run1",
            run_started_at="start",
            run_finished_at="finish",
            mode="normal",
            raw_jobs=[],
            normalized_jobs=[],
            scored_jobs=[],
            deduped_jobs=[],
            reported_jobs=[],
            query_attempts=[
                {
                    "run_id": "run1",
                    "source": "linkedin",
                    "country": "Canada",
                    "query": "No Match Analyst",
                    "location": "Toronto",
                    "raw_count": 0,
                    "success": True,
                    "error_message": "",
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["country"], "Canada")
        self.assertEqual(row["source"], "linkedin")
        self.assertEqual(row["query"], "No Match Analyst")
        self.assertEqual(row["location"], "Toronto")
        self.assertEqual(row["raw_count"], 0)
        self.assertEqual(row["error_count"], 0)

    def test_query_attempt_location_is_used_for_job_funnel_overlay(self):
        raw = [
            {
                "source": "linkedin",
                "country": "Canada",
                "search_term_used": "Market Data Analyst",
                "search_location_used": "Toronto",
                "location": "Toronto, ON",
            }
        ]
        rows = build_coverage_rows(
            run_id="run1",
            run_started_at="start",
            run_finished_at="finish",
            mode="normal",
            raw_jobs=raw,
            normalized_jobs=raw,
            scored_jobs=[{**raw[0], "score": 72, "hard_skip": False}],
            deduped_jobs=raw,
            reported_jobs=raw,
            query_attempts=[
                {
                    "run_id": "run1",
                    "source": "linkedin",
                    "country": "Canada",
                    "query": "Market Data Analyst",
                    "location": "Toronto",
                    "raw_count": 1,
                    "success": True,
                    "error_message": "",
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["location"], "Toronto")
        self.assertEqual(row["raw_count"], 1)
        self.assertEqual(row["normalized_count"], 1)
        self.assertEqual(row["scored_count"], 1)
        self.assertEqual(row["high_score_count_70"], 1)

if __name__ == "__main__":
    unittest.main()
