import unittest

from job_pipeline.filter_policy import apply_filter_policy


class FilterPolicyTests(unittest.TestCase):
    def test_hard_skip_for_unpaid_internship(self):
        job = {
            "title": "Unpaid Internship",
            "description": "This is an unpaid internship supporting operations.",
            "score": 70,
        }
        result = apply_filter_policy(job)
        self.assertTrue(result["hard_skip"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["recommendation"], "Hard skip")

    def test_soft_penalty_preserves_job(self):
        job = {
            "title": "Senior Risk Analyst",
            "description": "Requires 3+ years risk reporting experience.",
            "score": 75,
            "score_breakdown": {"penalty": 0},
        }
        result = apply_filter_policy(job)
        self.assertFalse(result["hard_skip"])
        self.assertLess(result["score"], 75)
        self.assertIn("senior_title", result["red_flags"])

    def test_manager_mentions_in_description_do_not_create_manager_title_flag(self):
        job = {
            "title": "Business Systems Analyst",
            "description": "Reporting to the Manager, this role builds SQL dashboards.",
            "score": 70,
            "score_breakdown": {"penalty": 0},
        }
        result = apply_filter_policy(job)

        self.assertFalse(result["hard_skip"])


    def test_mandarin_is_not_penalized(self):
        job = {
            "title": "Market Data Analyst",
            "description": "Mandarin preferred for client communication.",
            "score": 70,
        }
        result = apply_filter_policy(job)
        self.assertEqual(result["score"], 70)
        self.assertFalse(result["hard_skip"])

    def test_escaped_seven_plus_years_is_hard_skip(self):
        job = {
            "title": "Calypso Support Analyst",
            "description": "7\\+ years of Capital Markets and Calypso experience preferred.",
            "score": 90,
            "score_breakdown": {"penalty": 0},
        }
        result = apply_filter_policy(job)

        self.assertTrue(result["hard_skip"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["recommendation"], "Hard skip")
        self.assertIn("seven_plus_years", result["filter_rule_ids"])


if __name__ == "__main__":
    unittest.main()
