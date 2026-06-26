import unittest

from job_pipeline.keyword_extract import extract_keywords


class KeywordExtractTests(unittest.TestCase):
    def test_extracts_top_keywords_and_missing_master_terms(self):
        description = (
            "Required: Python, SQL, REST API, market data, reconciliation, and Excel. "
            "Preferred: Tableau and derivatives knowledge. The analyst will build reporting workflows."
        )
        master_resume_text = "Python SQL Excel market data reporting"

        result = extract_keywords(description, master_resume_text)

        self.assertIn("python", result["top_keywords"])
        self.assertIn("rest api", result["top_keywords"])
        self.assertIn("tableau", result["missing_keywords_from_master_resume"])
        self.assertNotIn("python", result["missing_keywords_from_master_resume"])


if __name__ == "__main__":
    unittest.main()

