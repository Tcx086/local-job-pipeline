import unittest

from job_pipeline.source_health import build_source_health_rows


class SourceHealthTests(unittest.TestCase):
    def test_consecutive_failures_accumulates_from_previous_rows(self):
        rows = build_source_health_rows(
            [
                {
                    "source": "linkedin",
                    "raw_count": 0,
                    "normalized_count": 0,
                    "error_count": 1,
                    "error_message": "temporary upstream error",
                }
            ],
            run_id="run2",
            registry={"sources": {"jobspy": {"enabled": True, "platforms": ["linkedin"]}}},
            previous_rows=[{"source": "linkedin", "consecutive_failures": 2}],
            last_run_at="finish",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "failing")
        self.assertEqual(rows[0]["consecutive_failures"], 3)
        self.assertEqual(rows[0]["last_error_message"], "temporary upstream error")


if __name__ == "__main__":
    unittest.main()
