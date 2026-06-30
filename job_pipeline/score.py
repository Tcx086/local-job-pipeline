from __future__ import annotations

import re
from typing import Any

from .filter_policy import apply_filter_policy
from .query_expander import role_family_for_query
from .utils import normalize_text_escapes


SCORE_BANDS = [
    (85, 100, "Must apply"),
    (70, 84, "Strong apply"),
    (55, 69, "Maybe apply"),
    (35, 54, "Review manually"),
    (25, 34, "Low priority"),
    (0, 24, "Skip"),
]

DATA_REPORTING_KEYWORDS = [
    "sql",
    "python",
    "excel",
    "dashboard",
    "reporting",
    "data quality",
    "data validation",
    "data cleanup",
    "data cleaning",
    "analytics",
    "visualization",
    "business intelligence",
    "bi analyst",
]

FINANCE_MARKET_DATA_KEYWORDS = [
    "market data",
    "investment data",
    "capital markets",
    "treasury",
    "portfolio",
    "financial reporting",
    "securities",
    "brokerage",
    "trade support",
    "middle office",
    "settlements",
    "reconciliation",
]

RISK_FRAUD_COMPLIANCE_KEYWORDS = [
    "fraud",
    "aml",
    "kyc",
    "financial crime",
    "transaction monitoring",
    "risk operations",
    "controls",
    "compliance",
    "investigations",
    "sanctions",
    "payments risk",
    "trust and safety",
]

TECHNICAL_OPERATIONS_KEYWORDS = [
    "api",
    "rest api",
    "integration",
    "implementation",
    "application support",
    "platform support",
    "technical operations",
    "client integration",
    "troubleshooting",
    "workflow automation",
    "technical business analyst",
]

DIGITAL_ASSETS_KEYWORDS = [
    "digital assets",
    "blockchain",
    "crypto",
    "defi",
    "web3",
    "tokenomics",
    "on-chain",
    "on chain",
    "wallet",
    "smart contract",
    "chainalysis",
]

AI_DATA_GOVERNANCE_KEYWORDS = [
    "data governance",
    "regulatory reporting",
    "model risk",
    "ai governance",
    "process improvement",
    "automation analyst",
    "business process",
    "data quality",
    "workflow automation",
]

ROLE_CATEGORY_TERMS = {
    "data": [
        "data analyst",
        "data operations",
        "market data",
        "investment data",
        "financial data",
        "portfolio analytics",
        "data quality",
        "reference data",
        "reporting analyst",
        "business intelligence",
    ],
    "risk": [
        "risk analyst",
        "risk operations",
        "model risk",
        "credit risk",
        "operational risk",
        "fraud analyst",
        "aml analyst",
        "kyc analyst",
        "transaction monitoring",
        "financial crime",
        "compliance analyst",
        "payments risk",
    ],
    "trading_ops": [
        "trading operations",
        "trading support",
        "trade support",
        "market operations",
        "payments operations",
        "securities operations",
        "middle office",
        "settlements",
        "reconciliation",
        "brokerage operations",
        "investment operations",
    ],
    "api": [
        "api integration",
        "api support",
        "technical operations",
        "implementation analyst",
        "platform operations",
        "platform support",
        "application support",
        "client integration",
        "solutions analyst",
        "product support",
    ],
    "capital_markets": [
        "capital markets",
        "business analyst",
        "strategy analyst",
        "treasury",
        "investment analyst",
        "onboarding",
        "product analyst",
    ],
    "crypto_ops": [
        "crypto operations",
        "exchange operations",
        "digital assets",
        "blockchain analytics",
        "crypto research",
        "web3 research",
        "on-chain data",
        "tokenomics",
    ],
    "ai_governance": AI_DATA_GOVERNANCE_KEYWORDS,
}

ROLE_TERMS = sorted({term for terms in ROLE_CATEGORY_TERMS.values() for term in terms})

BACK_OFFICE_TERMS = [
    "reconciliation",
    "reporting",
    "trade support",
    "middle office",
    "settlements",
    "onboarding",
    "implementation",
    "platform support",
    "application support",
    "data quality",
    "reference data",
    "payments operations",
]

TITLE_REVIEW_TERMS = [
    "operations",
    "support",
    "data",
    "risk",
    "fraud",
    "compliance",
    "api",
    "implementation",
    "reconciliation",
    "reporting",
    "analyst",
]

SKILL_KEYWORDS = sorted(
    set(
        [
            "pandas",
            "data pipeline",
            "order book",
            "risk control",
            "trading system",
            "backtesting",
            "automation",
            "etl",
            "financial markets",
            "derivatives",
            "business analysis",
            "case review",
            "pattern detection",
            "customer-facing",
            "mandarin",
            "english",
            *BACK_OFFICE_TERMS,
            *DATA_REPORTING_KEYWORDS,
            *FINANCE_MARKET_DATA_KEYWORDS,
            *RISK_FRAUD_COMPLIANCE_KEYWORDS,
            *TECHNICAL_OPERATIONS_KEYWORDS,
            *DIGITAL_ASSETS_KEYWORDS,
            *AI_DATA_GOVERNANCE_KEYWORDS,
        ]
    )
)

INDUSTRY_KEYWORDS = sorted(
    set(
        [
            "fintech",
            "exchange",
            "bank",
            "banking",
            "asset management",
            "wealth management",
            "payments",
            *FINANCE_MARKET_DATA_KEYWORDS,
            *RISK_FRAUD_COMPLIANCE_KEYWORDS,
            *DIGITAL_ASSETS_KEYWORDS,
        ]
    )
)

ROLE_FAMILY_TERMS = {
    "digital_assets_research": DIGITAL_ASSETS_KEYWORDS + ["market intelligence", "research analyst", "blockchain analytics"],
    "financial_data_analysis": DATA_REPORTING_KEYWORDS + FINANCE_MARKET_DATA_KEYWORDS + ["research analyst", "product analyst", "business analyst", "strategy analyst"],
    "risk_fraud_compliance": RISK_FRAUD_COMPLIANCE_KEYWORDS,
    "technical_operations": TECHNICAL_OPERATIONS_KEYWORDS,
    "banking_operations": ["operations analyst", "payments operations", "treasury", "trade support", "reconciliation", "brokerage", "securities", "middle office", "client operations"],
    "ai_data_governance": AI_DATA_GOVERNANCE_KEYWORDS,
}

NEGATIVE_RULES = [
    (r"\b(senior|sr\.?|staff|principal|lead)\b", 30, "senior_or_lead_level"),
    (r"\b(5\+|6\+|7\+|8\+|9\+|10\+|5|6|7|8|9|10|five|six|seven|eight|nine|ten)\s*(years|yrs)\b", 25, "high_years_required"),
    (r"\bph\.?d\b|\bdoctorate\b", 30, "phd_required"),
    (r"\b(citizenship|citizen|permanent resident|pr only|security clearance)\b", 40, "work_authorization_restricted"),
    (r"\blow latency\b[^.]{0,120}c\+\+|\bhft\b[^.]{0,120}c\+\+", 25, "low_latency_cpp"),
    (r"\bcommission[- ]only\b|\bunpaid\b", 30, "commission_or_unpaid"),
]

QUANT_RE = re.compile(r"\b(quant research|quantitative researcher|quant trader)\b", re.I)
OPS_ESCAPE_RE = re.compile(r"\b(data|operations|support|api|risk|market data|analyst)\b", re.I)
SENIOR_ENGINEERING_TITLE_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead)\b[^\n]{0,90}\b(software|backend|frontend|full stack|infrastructure|platform|systems|c\+\+)?\s*engineer\b|"
    r"\b(staff|principal|lead)\s+[^\n]{0,60}engineer\b",
    re.I,
)


def _job_text(job: dict[str, Any], *, include_company: bool = False) -> str:
    parts = [job.get("title", "")]
    if include_company:
        parts.append(job.get("company", ""))
    parts.append(job.get("description", ""))
    parts.append(job.get("search_term_used", ""))
    return normalize_text_escapes(" ".join(str(part or "") for part in parts))


def _keyword_matches(text: str, keywords: list[str]) -> list[str]:
    haystack = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in haystack]


def score_band(score: int, *, hard_skip: bool = False) -> str:
    if hard_skip:
        return "Hard skip"
    value = max(0, min(100, int(score or 0)))
    for low, high, label in SCORE_BANDS:
        if low <= value <= high:
            return label
    return "Skip"


def infer_role_category(job: dict[str, Any]) -> str:
    text = _job_text(job).lower()
    best_category = "general"
    best_count = 0
    for category, terms in ROLE_CATEGORY_TERMS.items():
        count = sum(1 for term in terms if term in text)
        if count > best_count:
            best_category = category
            best_count = count
    return best_category


def infer_role_family(job: dict[str, Any]) -> str:
    configured = str(job.get("role_family") or "").strip()
    if configured:
        return configured
    from_query = role_family_for_query(str(job.get("search_term_used") or job.get("query") or ""))
    if from_query:
        return from_query
    text = _job_text(job).lower()
    best_family = ""
    best_count = 0
    for family, terms in ROLE_FAMILY_TERMS.items():
        count = sum(1 for term in terms if term.lower() in text)
        if count > best_count:
            best_family = family
            best_count = count
    return best_family


def score_role_fit(job: dict[str, Any]) -> tuple[int, list[str]]:
    title = str(job.get("title") or "")
    text = _job_text(job)
    lower_title = title.lower()
    lower_text = text.lower()
    matched = _keyword_matches(text, ROLE_TERMS)
    title_matches = _keyword_matches(title, ROLE_TERMS)
    score = min(30, len(matched) * 4 + len(title_matches) * 8)
    if "analyst" in lower_title and score < 18:
        score += 8
    if any(word in lower_title for word in TITLE_REVIEW_TERMS):
        score += 6
    if any(term in lower_text for term in BACK_OFFICE_TERMS):
        score += 4
    if _keyword_matches(text, RISK_FRAUD_COMPLIANCE_KEYWORDS) and "analyst" in lower_title:
        score += 6
    if _keyword_matches(text, TECHNICAL_OPERATIONS_KEYWORDS) and any(word in lower_title for word in ["analyst", "support", "operations"]):
        score += 5
    if _keyword_matches(text, FINANCE_MARKET_DATA_KEYWORDS) and _keyword_matches(text, DATA_REPORTING_KEYWORDS):
        score += 5
    return min(score, 30), matched


def score_skill_match(job: dict[str, Any]) -> tuple[int, list[str]]:
    text = _job_text(job)
    matched = _keyword_matches(text, SKILL_KEYWORDS)
    score = len(matched) * 3
    back_office_matches = _keyword_matches(text, BACK_OFFICE_TERMS)
    if back_office_matches:
        score += min(6, len(back_office_matches) * 2)
    if _keyword_matches(text, DATA_REPORTING_KEYWORDS) and _keyword_matches(text, FINANCE_MARKET_DATA_KEYWORDS + RISK_FRAUD_COMPLIANCE_KEYWORDS + TECHNICAL_OPERATIONS_KEYWORDS):
        score += 5
    return min(25, score), sorted(set(matched))


def score_location(job: dict[str, Any]) -> int:
    country = str(job.get("detected_country") or job.get("country") or "")
    location = str(job.get("location") or "").lower()
    description = normalize_text_escapes(job.get("description") or "").lower()
    if country in {"Canada", "Singapore", "Hong Kong"}:
        return 15
    if country == "Remote" and any(token in description for token in ["canada", "singapore", "hong kong"]):
        return 12
    if "remote" in location or "remote" in description:
        return 8
    return 3


def score_seniority(job: dict[str, Any]) -> int:
    seniority = str(job.get("seniority") or "").lower()
    title = str(job.get("title") or "").lower()
    if seniority in {"intern", "new grad", "entry", "associate", "analyst"}:
        return 15
    if "junior" in title or "analyst" in title:
        return 14
    if seniority == "manager":
        return 4
    if seniority == "senior":
        return 2
    return 10


def score_visa_fit(job: dict[str, Any]) -> int:
    text = _job_text(job).lower()
    restricted = ["citizenship", "citizen", "permanent resident", "pr only", "security clearance"]
    if any(token in text for token in restricted):
        return 0
    if "visa sponsorship" in text or "sponsorship available" in text:
        return 10
    if "must already be based in singapore" in text or "must already be based in hong kong" in text:
        return 3
    return 8


def score_industry(job: dict[str, Any]) -> tuple[int, list[str]]:
    text = _job_text(job, include_company=True)
    matched = _keyword_matches(text, INDUSTRY_KEYWORDS)
    base = min(6, len(matched) * 2)
    digital_bonus = min(4, len(_keyword_matches(text, DIGITAL_ASSETS_KEYWORDS)))
    return min(8, base + digital_bonus), matched


def collect_red_flags(job: dict[str, Any]) -> tuple[int, list[str]]:
    text = _job_text(job).lower()
    title_text = normalize_text_escapes(str(job.get("title") or "")).lower()
    penalty = 0
    flags: list[str] = []
    for pattern, points, flag in NEGATIVE_RULES:
        target_text = title_text if flag == "senior_or_lead_level" else text
        if re.search(pattern, target_text):
            penalty += points
            flags.append(flag)
    if SENIOR_ENGINEERING_TITLE_RE.search(title_text):
        penalty += 50
        flags.append("senior_engineering_title")
    if QUANT_RE.search(text) and not OPS_ESCAPE_RE.search(text):
        penalty += 20
        flags.append("pure_quant_track")
    if not str(job.get("description") or "").strip():
        penalty += 3
        flags.append("no_description")
    if "must already be based in singapore" in text or "must already be based in hong kong" in text:
        if "visa sponsorship" not in text and "sponsorship available" not in text:
            penalty += 20
            flags.append("local_presence_required_without_sponsorship")
    return penalty, sorted(set(flags))


def recommendation_for_score(score: int) -> str:
    return score_band(score)


def classify_fit_category(job: dict[str, Any]) -> str:
    score = int(job.get("score") or 0)
    hard_skip = bool(job.get("hard_skip")) or str(job.get("recommendation") or "").lower() == "hard skip"
    if hard_skip or score < 25:
        return "skip"
    text = _job_text(job).lower()
    family = infer_role_family(job)
    flags = {str(flag) for flag in job.get("red_flags") or []}
    digital = bool(_keyword_matches(text, DIGITAL_ASSETS_KEYWORDS))
    dataish = bool(_keyword_matches(text, DATA_REPORTING_KEYWORDS) or any(word in text for word in ["research", "operations", "analytics"]))
    core_families = {"digital_assets_research", "financial_data_analysis", "risk_fraud_compliance", "technical_operations", "banking_operations"}
    adjacent_families = core_families | {"ai_data_governance"}
    severe_experience = flags & {"high_years_required", "five_plus_years", "senior_title", "senior_or_lead_level", "senior_engineering_title"}

    if severe_experience:
        return "stretch_fit" if score >= 25 else "skip"
    if digital and dataish and score >= 70:
        return "core_fit"
    if family in core_families and score >= 70:
        return "core_fit"
    if family in adjacent_families and score >= 55:
        return "adjacent_fit"
    if score >= 55 and (dataish or "analyst" in text):
        return "adjacent_fit"
    return "stretch_fit"


def score_job(job: dict[str, Any]) -> dict[str, Any]:
    role_score, role_matches = score_role_fit(job)
    skill_score, skill_matches = score_skill_match(job)
    location_score = score_location(job)
    seniority_score = score_seniority(job)
    visa_score = score_visa_fit(job)
    industry_score, industry_matches = score_industry(job)
    penalty, red_flags = collect_red_flags(job)

    raw_score = role_score + skill_score + location_score + seniority_score + visa_score + industry_score - penalty
    final_score = max(0, min(100, int(round(raw_score))))
    matched_keywords = sorted(set(role_matches + skill_matches + industry_matches))
    reason = build_reason(job, matched_keywords, red_flags)

    enriched = dict(job)
    enriched.update(
        {
            "score": final_score,
            "recommendation": recommendation_for_score(final_score),
            "score_band": score_band(final_score),
            "role_category": infer_role_category(job),
            "role_family": infer_role_family(job),
            "matched_keywords": matched_keywords,
            "red_flags": red_flags,
            "reason_to_apply": reason,
            "score_breakdown": {
                "role_fit": role_score,
                "skill_match": skill_score,
                "location_fit": location_score,
                "seniority_fit": seniority_score,
                "visa_work_authorization_fit": visa_score,
                "industry_fit": industry_score,
                "penalty": penalty,
            },
        }
    )
    enriched = apply_filter_policy(enriched)
    if enriched.get("hard_skip"):
        enriched["score_band"] = "Hard skip"
        enriched["fit_category"] = "skip"
    else:
        enriched["recommendation"] = recommendation_for_score(int(enriched.get("score") or 0))
        enriched["score_band"] = score_band(int(enriched.get("score") or 0))
        enriched["fit_category"] = classify_fit_category(enriched)
    if not enriched.get("role_family"):
        enriched["role_family"] = infer_role_family(enriched)
    return enriched


def build_reason(job: dict[str, Any], matched_keywords: list[str], red_flags: list[str]) -> str:
    title = job.get("title") or "This role"
    if red_flags:
        return f"{title} has useful overlap ({', '.join(matched_keywords[:6])}) but needs review: {', '.join(red_flags)}."
    if matched_keywords:
        return f"{title} matches target keywords: {', '.join(matched_keywords[:8])}."
    return f"{title} has limited keyword evidence; review manually before applying."


def score_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [score_job(job) for job in jobs]
