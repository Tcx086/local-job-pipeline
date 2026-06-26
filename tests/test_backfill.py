import unittest

from job_pipeline.backfill import hours_old_from_days


class BackfillTests(unittest.TestCase):
    def test_hours_old_from_days(self):
        self.assertEqual(hours_old_from_days(30), 720)
        self.assertEqual(hours_old_from_days(90), 2160)

    def test_hours_old_rejects_invalid_days(self):
        with self.assertRaises(ValueError):
            hours_old_from_days(0)


if __name__ == "__main__":
    unittest.main()
