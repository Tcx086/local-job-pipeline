import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from job_pipeline.cover_letter import (
    BUILTIN_TEMPLATE_ID,
    COVER_LETTER_TEMPLATE_PATH,
    COVER_LETTER_HUMAN_TEMPLATE_PATH,
    cover_letter_generation_enabled,
    generate_cover_letter,
    load_cover_letter,
    load_cover_letter_templates,
    load_cover_letter_human_templates,
)


MASTER_FIXTURE = {
    "name": "Sample Candidate",
    "summary": [
        "Data analyst with experience in Python, SQL, Excel, market data reporting, risk controls, API workflows, and operational documentation."
    ],
    "skills": {
        "data": ["Python", "SQL", "Excel", "pandas", "market data", "reporting", "data quality", "data validation"],
        "operations": ["risk controls", "reconciliation", "workflow automation", "operational controls", "documentation", "process tracking", "communication"],
        "technical": ["REST API", "JSON", "exchange APIs", "technical troubleshooting", "client communication"],
        "business": ["capital markets", "financial analysis", "business analysis", "budget tracking", "variance analysis", "data analysis"],
        "languages": ["English", "Mandarin Chinese"],
    },
    "projects": [
        {
            "name": "Market Data Reporting Project",
            "type": "Portfolio project",
            "dates": "2025",
            "bullets": [
                "Built Python and SQL reporting checks for market data quality review."
            ],
        },
        {
            "name": "Risk Controls Validation Project",
            "type": "Portfolio project",
            "dates": "2025",
            "bullets": [
                "Created Excel and Python checks for risk controls, reconciliation, and data validation."
            ],
        },
        {
            "name": "Exchange API Monitoring Project",
            "type": "Portfolio project",
            "dates": "2025",
            "bullets": [
                "Used REST API, JSON, and exchange APIs to document market data monitoring workflows."
            ],
        },
        {
            "name": "Capital Markets Reporting Project",
            "type": "Portfolio project",
            "dates": "2025",
            "bullets": [
                "Prepared Excel reporting and financial analysis outputs for capital markets business analysis."
            ],
        },
    ],
    "experience": [
        {
            "title": "Operations Assistant",
            "company": "Example Operations",
            "dates": "2024",
            "bullets": [
                "Maintained structured Excel tracking systems for documentation workflow, data quality checks, process tracking, and operational follow-up."
            ],
        }
    ],
}


SENSITIVE_BODY_TERMS = [
    "passport",
    "government id",
    "ssn",
    "sin number",
    "bank account",
    "exact dob",
    "date of birth",
    "health data",
    "medical record",
    "medical condition",
    "banking info",
    "financial account",
    "disability",
    "veteran",
    "race",
    "ethnicity",
    "gender",
    "eeo",
    "work authorization",
    "sponsorship",
    "citizenship",
    "permanent residency",
    "cfa",
    "frm",
    "cpa",
    "master's degree",
    "years of experience",
    "team leadership",
    "managed direct reports",
    "revenue growth",
    "cost savings",
]


GOLDEN_CASES = [
    {
        "case_id": "data_market_data_deep",
        "resume_profile": "data_market_data",
        "application_effort": "deep_tailor",
        "title": "Market Data Analyst",
        "description": "Python SQL market data reporting data quality documentation. Preferred Tableau.",
        "expected_template": "human:data_market_data",
        "expected_overlay": "data_market_data",
        "expected_manual_review": False,
    },
    {
        "case_id": "risk_operations_standard",
        "resume_profile": "risk_operations",
        "application_effort": "standard_tailor",
        "title": "Risk Operations Analyst",
        "description": "Excel SQL Python risk controls reconciliation data validation reporting. Preferred Tableau.",
        "expected_template": "human:risk_operations",
        "expected_overlay": "risk_operations",
        "expected_manual_review": False,
    },
    {
        "case_id": "trading_operations_deep",
        "resume_profile": "trading_operations",
        "application_effort": "deep_tailor",
        "title": "Trading Operations Analyst",
        "description": "Python exchange APIs market data reconciliation operational controls reporting. Preferred Tableau.",
        "expected_template": "human:trading_operations",
        "expected_overlay": "trading_operations",
        "expected_manual_review": False,
    },
    {
        "case_id": "api_technical_operations_standard",
        "resume_profile": "api_technical_operations",
        "application_effort": "standard_tailor",
        "title": "API Technical Operations Analyst",
        "description": "REST API JSON Python SQL technical troubleshooting documentation client communication. Preferred Tableau.",
        "expected_template": "human:api_technical_operations",
        "expected_overlay": "api_technical_operations",
        "expected_manual_review": False,
    },
    {
        "case_id": "capital_markets_business_standard",
        "resume_profile": "capital_markets_business",
        "application_effort": "standard_tailor",
        "title": "Capital Markets Business Analyst",
        "description": "Excel SQL Python capital markets financial analysis reporting business analysis. Preferred Tableau.",
        "expected_template": "full_standard_tailor",
        "expected_overlay": "capital_markets_business",
        "expected_manual_review": True,
    },
    {
        "case_id": "client_finance_overlay",
        "resume_profile": "data_market_data",
        "application_effort": "standard_tailor",
        "role_family": "client_finance",
        "title": "Client Finance Analyst",
        "description": "Excel reporting budget tracking variance analysis data analysis communication. Preferred Tableau.",
        "expected_template": "human:client_finance",
        "expected_overlay": "client_finance",
        "expected_manual_review": False,
    },
    {
        "case_id": "revenue_operations_overlay",
        "resume_profile": "data_market_data",
        "application_effort": "standard_tailor",
        "role_family": "revenue_operations",
        "title": "Revenue Operations Analyst",
        "description": "SQL Python reporting workflow automation business analysis communication. Preferred Tableau.",
        "expected_template": "human:data_market_data",
        "expected_overlay": "revenue_operations",
        "expected_manual_review": False,
    },
    {
        "case_id": "fallback_unknown_role",
        "resume_profile": "unknown_profile",
        "application_effort": "standard_tailor",
        "role_family": "unknown_role",
        "title": "Operations Analyst",
        "description": "Python SQL reporting documentation workflow automation. Preferred Tableau.",
        "expected_template": "full_standard_tailor",
        "expected_overlay": "fallback",
        "expected_manual_review": True,
    },
]


class CoverLetterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.master_path = self.root / "master_resume.json"
        self.common_path = self.root / "common_answers.json"
        self.master_path.write_text(json.dumps(MASTER_FIXTURE), encoding="utf-8")
        self.common_path.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, case: dict | None = None, **extra) -> dict:
        values = dict(case or {})
        values.update(extra)
        case_id = values.get("case_id") or values.get("application_effort") or "fallback"
        job = {
            "canonical_job_id": f"job_{case_id}",
            "title": values.get("title") or "Market Data Analyst",
            "company": values.get("company") or "Example Fintech",
            "country": "Canada",
            "role_category": values.get("role_category") or "data",
            "role_family": values.get("role_family") or "",
            "resume_profile": values.get("resume_profile") or "data_market_data",
            "application_effort": values.get("application_effort") or "standard_tailor",
            "apply_url": "https://example.test/apply",
            "score": 82,
            "description": values.get("description") or "Python SQL market data reporting and documentation. Preferred Tableau.",
        }
        return job

    def _generate(self, job: dict, **kwargs):
        return generate_cover_letter(
            job,
            generated_resume_file="resume.pdf",
            output_dir=self.root / "cover_letters",
            master_resume_path=self.master_path,
            common_answers_path=self.common_path,
            make_docx=False,
            make_pdf=False,
            **kwargs,
        )

    def test_template_config_loads_required_sections(self):
        config = load_cover_letter_templates(COVER_LETTER_TEMPLATE_PATH)
        self.assertIn("global_rules", config)
        self.assertIn("templates", config)
        self.assertIn("full_deep_tailor", config["templates"])
        self.assertIn("full_standard_tailor", config["templates"])
        self.assertIn("short_intro", config["templates"])
        self.assertIn("recruiter_message", config["templates"])
        self.assertIn("follow_up_message", config["templates"])
        self.assertIn("profile_overlays", config)
        self.assertIn("client_finance", config.get("role_family_overlays", {}))
        self.assertIn("revenue_operations", config.get("role_family_overlays", {}))
        self.assertIn("quality_assurance", config.get("role_family_overlays", {}))
        self.assertIn("fallback", config)

    def test_human_template_config_loads_required_roles(self):
        config = load_cover_letter_human_templates(COVER_LETTER_HUMAN_TEMPLATE_PATH)
        templates = config.get("templates_v2", {})
        for role in [
            "quality_assurance",
            "data_market_data",
            "risk_operations",
            "trading_operations",
            "api_technical_operations",
            "client_finance",
        ]:
            self.assertIn(role, templates)
            self.assertIn("body", templates[role])

    def test_generated_body_templates_do_not_contain_prohibited_claim_text(self):
        config = load_cover_letter_templates(COVER_LETTER_TEMPLATE_PATH)
        templates = config.get("templates", {})
        body_parts = []
        for template in templates.values():
            body_parts.extend(str(item) for item in template.get("paragraphs") or [])
            body_parts.append(str(template.get("text") or ""))
            body_parts.append(str(template.get("closing") or ""))
        body = "\n".join(body_parts).lower()
        for term in SENSITIVE_BODY_TERMS:
            self.assertNotIn(term, body)

    def test_deep_tailor_uses_full_deep_tailor(self):
        payload = self._generate(self._job(application_effort="deep_tailor"), human_template_path=self.root / "missing_human_templates.yaml")
        self.assertEqual(payload["template_id"], "full_deep_tailor")
        self.assertEqual(payload["effort_used"], "deep_tailor")
        self.assertIn("would welcome the opportunity", payload["cover_letter_markdown"])

    def test_standard_tailor_uses_full_standard_tailor(self):
        payload = self._generate(self._job(application_effort="standard_tailor"), human_template_path=self.root / "missing_human_templates.yaml")
        self.assertEqual(payload["template_id"], "full_standard_tailor")
        self.assertEqual(payload["effort_used"], "standard_tailor")
        self.assertIn("would appreciate the opportunity", payload["cover_letter_markdown"])

    def test_missing_template_falls_back_safely(self):
        payload = self._generate(
            self._job(case_id="missing_template", application_effort="deep_tailor"),
            template_path=self.root / "does_not_exist.yaml",
            human_template_path=self.root / "missing_human_templates.yaml",
        )
        self.assertEqual(payload["template_id"], BUILTIN_TEMPLATE_ID)
        self.assertTrue(payload["manual_review_required"])
        self.assertIn("Manual review required", payload["cover_letter_markdown"])
        self.assertIn("TODO", payload["cover_letter_markdown"])

    def test_malformed_template_config_falls_back_safely(self):
        malformed = self.root / "malformed_cover_letter_templates.yaml"
        malformed.write_text("templates: [\n", encoding="utf-8")
        payload = self._generate(
            self._job(case_id="malformed_template", application_effort="standard_tailor"),
            template_path=malformed,
            human_template_path=self.root / "missing_human_templates.yaml",
        )
        self.assertEqual(payload["template_id"], BUILTIN_TEMPLATE_ID)
        self.assertTrue(payload["manual_review_required"])
        self.assertIn("Manual review required", payload["cover_letter_markdown"])

    def test_client_finance_overlay_selected_from_role_family_title_or_jd(self):
        payload = self._generate(
            self._job(
                case_id="client_finance",
                title="Project Finance Analyst",
                role_family="finance",
                description="Budget tracking, variance analysis, billing support, and project finance reporting. Preferred Tableau.",
            )
        )
        self.assertEqual(payload["overlay_id"], "client_finance")
        self.assertEqual(payload["template_id"], "human:client_finance")

    def test_golden_fake_jobs_create_safe_markdown_and_json(self):
        for case in GOLDEN_CASES:
            with self.subTest(case=case["case_id"]):
                payload = self._generate(self._job(case))
                md_path = Path(payload["paths"]["markdown"])
                json_path = Path(payload["paths"]["json"])
                saved = json.loads(json_path.read_text(encoding="utf-8"))
                generated_body = (saved["cover_letter_markdown"] + "\n" + str(saved.get("short_intro") or "")).lower()

                self.assertTrue(md_path.exists())
                self.assertTrue(json_path.exists())
                self.assertEqual(saved["template_id"], case["expected_template"])
                self.assertEqual(saved["overlay_id"], case["expected_overlay"])
                self.assertEqual(saved["effort_used"], case["application_effort"])
                self.assertEqual(saved["manual_review_required"], case["expected_manual_review"])
                self.assertIn("unsupported_keywords_not_claimed", saved)
                self.assertIn("prohibited_claims_checked", saved)
                self.assertTrue(saved["prohibited_claims_checked"])
                self.assertIn("tableau", [item.lower() for item in saved["unsupported_keywords_not_claimed"]])
                self.assertNotIn("tableau", generated_body)
                if case["expected_manual_review"]:
                    self.assertIn("todo: add one specific reason", generated_body)
                    self.assertIn("manual review required", generated_body)
                else:
                    self.assertEqual(saved.get("todo"), [])
                    self.assertNotIn("todo", generated_body)
                    self.assertNotIn("manual review required", generated_body)
                    self.assertNotIn("# cover letter", generated_body)
                for term in SENSITIVE_BODY_TERMS:
                    self.assertNotIn(term, generated_body)

    def test_overlay_fallback_affects_sparse_jd_focus(self):
        payload = self._generate(
            self._job(
                case_id="risk_sparse",
                resume_profile="risk_operations",
                application_effort="deep_tailor",
                title="Risk Operations Analyst",
                description="Open role.",
            )
        )
        self.assertEqual(payload["overlay_id"], "risk_operations")
        self.assertIn("risk awareness, documentation, reporting, and operational follow-through", payload["cover_letter_body"])

    def test_healthcare_and_banking_industry_words_are_allowed(self):
        master = deepcopy(MASTER_FIXTURE)
        master["skills"] = dict(master["skills"])
        master["skills"]["industry"] = ["healthcare analytics", "banking operations", "Python", "reporting"]
        master["projects"] = [
            {
                "name": "Industry Reporting Project",
                "type": "Portfolio project",
                "dates": "2025",
                "bullets": ["Built Python reporting checks for healthcare and banking operations workflows."],
            },
            *master["projects"],
        ]
        self.master_path.write_text(json.dumps(master), encoding="utf-8")
        payload = self._generate(
            self._job(
                case_id="healthcare_banking",
                title="Healthcare Banking Operations Analyst",
                description="Healthcare banking reporting role with Python workflow documentation.",
            )
        )
        body = payload["cover_letter_body"].lower()
        self.assertIn("healthcare", body)
        self.assertIn("banking", body)

    def test_sensitive_personal_phrases_are_still_blocked(self):
        payload = self._generate(
            self._job(
                case_id="sensitive_precise_phrases",
                description="Python SQL reporting. Do not include health data, medical record, medical condition, banking info, financial account, or bank account details.",
            )
        )
        body = (payload["cover_letter_body"] + "\n" + payload.get("short_intro", "")).lower()
        for term in ["health data", "medical record", "medical condition", "banking info", "financial account", "bank account"]:
            self.assertNotIn(term, body)

    def test_sensitive_eligibility_phrases_are_still_blocked(self):
        payload = self._generate(
            self._job(
                case_id="sensitive_eligibility_phrases",
                description=(
                    "Example Fintech notes that visa sponsorship is not available "
                    "and work authorization must be confirmed."
                ),
            )
        )
        generated = (
            payload["cover_letter_body"]
            + "\n"
            + payload["cover_letter_markdown"]
            + "\n"
            + payload.get("short_intro", "")
        ).lower()
        for term in ["work authorization", "sponsorship", "visa sponsorship", "employer sponsorship"]:
            self.assertNotIn(term, generated)


    def test_cover_letter_body_excludes_markdown_review_header(self):
        payload = self._generate(self._job(case_id="body_copy", application_effort="standard_tailor"))
        body = payload["cover_letter_body"]
        self.assertTrue(body.startswith("Dear Hiring Team,"))
        self.assertNotIn("# Cover Letter", body)
        self.assertNotIn("Manual review required", body)
        self.assertNotIn("# Cover Letter", payload["cover_letter_markdown"])
        self.assertNotIn("Manual review required", payload["cover_letter_markdown"])
        self.assertNotIn("TODO", payload["cover_letter_markdown"])
        self.assertFalse(payload["manual_review_required"])

    def test_quality_assurance_overlay_selected_from_role_family_title_or_jd(self):
        cases = [
            self._job(case_id="qa_role_family", role_family="quality_assurance", title="Operations Analyst", description="Excel reporting and documentation."),
            self._job(case_id="qa_title", title="QA Analyst", description="Excel reporting and documentation."),
            self._job(case_id="qa_jd", title="Operations Analyst", description="Manufacturing quality work involving quality control, non-conformance tracking, audit documentation, and continuous improvement."),
        ]
        for job in cases:
            with self.subTest(job=job["canonical_job_id"]):
                payload = self._generate(job)
                self.assertEqual(payload["overlay_id"], "quality_assurance")

    def test_bombardier_quality_assurance_body_uses_qa_language_without_english_skill(self):
        payload = self._generate(
            self._job(
                case_id="bombardier_quality_assurance",
                company="Bombardier",
                title="Analyst, Quality Assurance",
                resume_profile="capital_markets_business",
                description=(
                    "Working at Bombardier means operating at the highest level. "
                    "This role supports quality assurance, quality control, audit documentation, "
                    "data accuracy, non-conformance follow-up, continuous improvement, Excel reporting, "
                    "and English communication."
                ),
            )
        )
        generated = (payload["cover_letter_body"] + "\n" + payload.get("short_intro", "")).lower()
        skills = [skill.lower() for skill in payload["selected_evidence"]["skills"]]

        self.assertEqual(payload["overlay_id"], "quality_assurance")
        self.assertIn("quality assurance", generated)
        self.assertIn("process follow-through", generated)
        self.assertNotIn("practical finance", generated)
        self.assertNotIn("english", skills)
        self.assertNotRegex(payload["cover_letter_body"], r"\bEnglish\b")

    def test_company_reason_avoids_generic_slogan_and_duplicate_period(self):
        slogan_payload = self._generate(
            self._job(
                case_id="slogan_reason",
                company="Bombardier",
                title="Analyst, Quality Assurance",
                description="Working at Bombardier means operating at the highest level. We are a global leader. Join our team.",
            )
        )
        body = slogan_payload["cover_letter_body"]
        self.assertNotIn("TODO", body)
        self.assertNotIn("The job description notes that", body)
        self.assertNotIn("highest level", body.lower())
        self.assertNotIn("global leader", body.lower())
        self.assertNotIn("..", body)

        concrete_payload = self._generate(
            self._job(
                case_id="concrete_reason",
                company="Bombardier",
                title="Analyst, Quality Assurance",
                description="Bombardier supports quality documentation and continuous improvement.",
            )
        )
        concrete_body = concrete_payload["cover_letter_body"]
        self.assertNotIn("The job description notes that", concrete_body)
        self.assertNotIn("TODO", concrete_body)
        self.assertNotIn("..", concrete_body)

    def test_evidence_sentence_does_not_prefix_worked_on_to_past_tense_bullet(self):
        payload = self._generate(
            self._job(
                case_id="evidence_grammar",
                title="Analyst, Quality Assurance",
                description="Quality assurance process tracking, documentation workflow, structured Excel tracking, reporting, and data quality checks.",
            )
        )
        generated = (payload["cover_letter_body"] + "\n" + payload.get("short_intro", "")).lower()
        for fragment in ["worked on maintained", "worked on built", "worked on created", "worked on prepared", "worked on used"]:
            self.assertNotIn(fragment, generated)
        self.assertRegex(payload["cover_letter_body"], r"I (maintained|built|created|prepared|used)\b")

    def test_formal_docx_and_pdf_exports_use_clean_body_not_review_markdown(self):
        try:
            from docx import Document  # type: ignore
            import fitz  # type: ignore
        except ModuleNotFoundError as exc:
            self.skipTest(f"optional document dependency missing: {exc.name}")

        payload = generate_cover_letter(
            self._job(
                case_id="formal_exports",
                company="Bombardier",
                title="Analyst, Quality Assurance",
                description="Bombardier supports quality documentation and continuous improvement.",
            ),
            generated_resume_file="resume.pdf",
            output_dir=self.root / "cover_letters",
            master_resume_path=self.master_path,
            common_answers_path=self.common_path,
            make_docx=True,
            make_pdf=True,
        )
        docx_path = Path(payload["paths"]["formal_docx"])
        pdf_path = Path(payload["paths"]["formal_pdf"])
        markdown = Path(payload["paths"]["markdown"]).read_text(encoding="utf-8")
        docx_text = "\n".join(paragraph.text for paragraph in Document(str(docx_path)).paragraphs)
        with fitz.open(pdf_path) as pdf_doc:
            pdf_text = "\n".join(page.get_text() for page in pdf_doc)

        self.assertTrue(docx_path.exists())
        self.assertTrue(pdf_path.exists())
        self.assertNotIn("Manual review required", markdown)
        self.assertNotIn("# Cover Letter", markdown)
        self.assertNotIn("TODO", markdown)
        for source_text in [payload["cover_letter_body"], docx_text, pdf_text]:
            self.assertIn("Dear Hiring Team", source_text)
            self.assertNotIn("# Cover Letter", source_text)
            self.assertNotIn("Manual review required", source_text)

    def test_insufficient_evidence_skips_formal_exports_with_reason(self):
        empty_master = self.root / "empty_master_resume.json"
        empty_master.write_text(json.dumps({"name": "Sample Candidate", "skills": {}, "projects": [], "experience": []}), encoding="utf-8")
        payload = generate_cover_letter(
            self._job(
                case_id="insufficient_evidence",
                title="Market Data Analyst",
                resume_profile="data_market_data",
                description="Python SQL market data reporting.",
            ),
            generated_resume_file="resume.pdf",
            output_dir=self.root / "cover_letters",
            master_resume_path=empty_master,
            common_answers_path=self.common_path,
            make_docx=True,
            make_pdf=True,
        )

        self.assertTrue(payload["manual_review_required"])
        self.assertEqual(payload["manual_review_reason"], "insufficient evidence")
        self.assertEqual(payload["reason"], "insufficient evidence")
        self.assertEqual(payload["cover_letter_body"], "")
        self.assertEqual(payload["paths"]["formal_docx"], "")
        self.assertEqual(payload["paths"]["formal_pdf"], "")
        self.assertEqual(payload["renderers"], {"docx": "", "pdf": ""})

    def test_generated_text_avoids_sensitive_terms_and_missing_keywords(self):
        payload = self._generate(
            self._job(
                application_effort="deep_tailor",
                description="Python SQL market data reporting. Preferred Tableau. Do not include passport, bank account, exact DOB, EEO, disability, or veteran details.",
            )
        )
        generated = (payload["cover_letter_markdown"] + "\n" + payload.get("short_intro", "")).lower()
        for term in ["passport", "bank account", "exact dob", "eeo", "disability", "veteran"]:
            self.assertNotIn(term, generated)
        self.assertIn("tableau", [item.lower() for item in payload["unsupported_keywords_not_claimed"]])
        self.assertNotIn("tableau", generated)
        self.assertTrue(payload["prohibited_claims_checked"])

    def test_disabled_efforts_require_explicit_template_enablement(self):
        job = self._job(case_id="quick_apply", application_effort="quick_apply")
        self.assertFalse(cover_letter_generation_enabled(job))
        with self.assertRaises(ValueError):
            self._generate(job)

    def test_json_contains_template_and_overlay_ids(self):
        payload = self._generate(self._job(application_effort="standard_tailor"), human_template_path=self.root / "missing_human_templates.yaml")
        self.assertIn("template_id", payload)
        self.assertIn("overlay_id", payload)
        self.assertIn("effort_used", payload)
        self.assertEqual(payload["overlay_id"], "data_market_data")

    def test_generate_cover_letter_creates_clean_human_markdown_and_json(self):
        job = self._job(
            case_id="job123",
            description="Python SQL market data reporting. Preferred Tableau. Do not include passport, bank account, exact DOB, EEO, disability, or veteran details.",
        )
        job["canonical_job_id"] = "job123"
        payload = self._generate(job)

        md_path = Path(payload["paths"]["markdown"])
        json_path = Path(payload["paths"]["json"])
        markdown = md_path.read_text(encoding="utf-8")
        serialized = json.dumps(payload).lower()
        self.assertTrue(md_path.exists())
        self.assertTrue(json_path.exists())
        self.assertIn("Example Fintech", markdown)
        self.assertIn("Market Data Analyst", markdown)
        self.assertNotIn("Manual review required", markdown)
        self.assertNotIn("# Cover Letter", markdown)
        self.assertNotIn("TODO", markdown)
        self.assertFalse(payload["manual_review_required"])
        self.assertIn("tableau", [item.lower() for item in payload["missing_keywords_not_claimed"]])
        self.assertNotIn("tableau", payload["cover_letter_markdown"].lower())
        for term in ["passport", "bank account", "exact dob", "eeo", "disability", "veteran"]:
            self.assertNotIn(term, serialized)
        loaded = load_cover_letter("job123", output_dir=self.root / "cover_letters")
        self.assertIsNotNone(loaded)
        self.assertEqual((loaded or {})["metadata"]["canonical_job_id"], "job123")

    def test_generator_does_not_mutate_job_input(self):
        job = self._job(application_effort="standard_tailor")
        original = deepcopy(job)
        self._generate(job)
        self.assertEqual(job, original)


if __name__ == "__main__":
    unittest.main()
