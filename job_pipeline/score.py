from __future__ import annotations

import re
from typing import Any

from .filter_policy import apply_filter_policy
from .utils import normalize_text_escapes


SCORE_BANDS = [
    (85, 100, "Must apply"),
    (70, 84, "Strong apply"),
    (55, 69, "Maybe apply"),
    (35, 54, "Review manually"),
    (25, 34, "Low priority"),
    (0, 24, "Skip"),
]

ROLE_CATEGORY_TERMS = {
    "data": ["data analyst", "data operations", "market data", "investment data", "portfolio analytics", "data engineer", "data quality", "reference data"],
    "risk": ["risk analyst", "risk operations", "model risk", "credit risk", "operational risk"],
    "trading_ops": ["trading operations", "trading support", "trade support", "market operations", "securities operations", "middle office", "settlements", "reconciliation"],
    "api": ["api integration", "api support", "technical operations", "implementation analyst", "platform support", "application support"],
    "capital_markets": ["capital markets", "business analyst", "treasury", "investment analyst", "onboarding"],
    "crypto_ops": ["crypto operations", "exchange operations", "liquidity operations", "digital assets"],
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
]

TITLE_REVIEW_TERMS = [
    "operations",
    "support",
    "data",
    "risk",
    "api",
    "implementation",
    "reconciliation",
    "reporting",
]

SKILL_KEYWORDS = [
    "python",
    "sql",
    "excel",
    "pandas",
    "api integration",
    "rest api",
    "data pipeline",
    "market data",
    "crypto market data",
    "order book",
    "risk control",
    "trading system",
    "backtesting",
    "automation",
    "dashboard",
    "reporting",
    "data cleaning",
    "etl",
    "reconciliation",
    "financial markets",
    "derivatives",
    "capital markets",
    "credit risk",
    "operational risk",
    "business analysis",
    "customer-facing",
    "mandarin",
    "english",
    *BACK_OFFICE_TERMS,
]

INDUSTRY_KEYWORDS = [
    "fintech",
    "crypto",
    "digital assets",
    "exchange",
    "capital markets",
    "bank",
    "banking",
    "brokerage",
    "asset management",
    "market data",
    "treasury",
    "middle office",
    "settlements",
]

NEGATIVE_RULES = [
    (r"\b(senior|sr\.?|staff|principal|lead)\b", 30, "senior_or_lead_level"),
    (r"\b(5\+|6\+|7\+|8\+|9\+|10\+|5|6|7|8|9|10|five|six|seven|eight|nine|ten)\s*(years|yrs)\b", 25, "high_years_required"),
    (r"\bph\.?d\b|\bdoctorate\b", 30, "phd_required"),
    (r"\b(citizenship|citizen|permanent resident|pr only|security clearance)\b", 40, "work_authorization_restricted"),
    (r"\blow latency\b[^.]{0,120}c\+\+|\bhft\b[^.]{0,120}c\+\+", 25, "low_latency_cpp"),
    (r"\bcommission[- ]only\b|\bunpaid\b", 30, "commission_or_unpaid"),
]

QUANT_RE = re.compile(r"\b(quant research|quantitative researcher|quant trader)\b", re.I)
OPS_ESCAPE_RE = re.compile(r"\b(data|operations|support|api|risk|market data)\b", re.I)


def _job_text(job: dict[str, Any], *, include_company: bool = False) -> str:
    parts = [job.get("title", "")]
    if include_company:
        parts.append(job.get("company", ""))
    parts.append(job.get("description", ""))
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


def score_role_fit(job: dict[str, Any]) -> tuple[int, list[str]]:
    title = str(job.get("title") or "")
    description = str(job.get("description") or "")
    text = normalize_text_escapes(f"{title} {description}")
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
    if any(term in lower_text for term in ["crypto", "fintech", "digital assets"]) and any(word in lower_text for word in ["operations", "data", "risk", "api", "support"]):
        score += 3
    return min(score, 30), matched


def score_skill_match(job: dict[str, Any]) -> tuple[int, list[str]]:
    text = _job_text(job)
    matched = _keyword_matches(text, SKILL_KEYWORDS)
    score = len(matched) * 3
    back_office_matches = _keyword_matches(text, BACK_OFFICE_TERMS)
    if back_office_matches:
        score += min(6, len(back_office_matches) * 2)
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
    return min(5, len(matched) * 2), matched


def collect_red_flags(job: dict[str, Any]) -> tuple[int, list[str]]:
    text = _job_text(job).lower()
    title_text = normalize_text_escapes(str(job.get("title") or "")).lower()
    penalty = 0
    flags: list[str] = []
    for pattern, points, flag in NEGATIVE_RULES:
        if re.search(pattern, text):
            penalty += points
            flags.append(flag)
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
        if enriched.get("filter_reason"):
            enriched["reason_to_apply"] = f"Filtered: {enriched['filter_reason']}"
    else:
        enriched["recommendation"] = recommendation_for_score(int(enriched.get("score") or 0))
        enriched["score_band"] = score_band(int(enriched.get("score") or 0))
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
