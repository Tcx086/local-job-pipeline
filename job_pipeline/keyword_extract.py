from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .score import SKILL_KEYWORDS


TOOLS = [
    "python",
    "sql",
    "excel",
    "pandas",
    "numpy",
    "power bi",
    "tableau",
    "jira",
    "confluence",
    "rest api",
    "json",
    "csv",
    "git",
]

FINANCIAL_PRODUCTS = [
    "equities",
    "fixed income",
    "derivatives",
    "options",
    "futures",
    "fx",
    "crypto",
    "digital assets",
    "order book",
    "market data",
    "treasury",
    "credit risk",
]

RESPONSIBILITIES = [
    "reconciliation",
    "reporting",
    "data cleaning",
    "data pipeline",
    "stakeholder communication",
    "trade support",
    "incident management",
    "risk control",
    "automation",
    "dashboard",
    "requirements gathering",
    "api integration",
]

ATS_KEYWORDS = sorted(set(SKILL_KEYWORDS + TOOLS + FINANCIAL_PRODUCTS + RESPONSIBILITIES))
STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "you",
    "our",
    "are",
    "will",
    "from",
    "this",
    "that",
    "have",
    "work",
    "team",
    "role",
    "job",
    "your",
    "into",
    "within",
    "about",
}


def _find_keywords(text: str, keywords: list[str]) -> list[str]:
    lower = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lower]


def repeated_terms(text: str, limit: int = 20) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#]{2,}", text.lower())
    counts = Counter(word for word in words if word not in STOPWORDS)
    phrases = re.findall(r"\b[a-zA-Z][a-zA-Z0-9+#]+(?:\s+[a-zA-Z][a-zA-Z0-9+#]+){1,2}\b", text.lower())
    phrase_counts = Counter(phrase for phrase in phrases if not any(part in STOPWORDS for part in phrase.split()))
    combined = counts + phrase_counts
    return [term for term, _ in combined.most_common(limit)]


def context_keywords(text: str, marker: str) -> list[str]:
    pattern = re.compile(rf"(.{{0,120}}{re.escape(marker)}.{{0,220}})", re.I | re.S)
    snippets = " ".join(match.group(1) for match in pattern.finditer(text))
    return _find_keywords(snippets, ATS_KEYWORDS)


def extract_keywords(description: str, master_resume_text: str = "") -> dict[str, Any]:
    text = description or ""
    master_lower = master_resume_text.lower()
    required = sorted(set(context_keywords(text, "required") + context_keywords(text, "must have")))
    preferred = sorted(set(context_keywords(text, "preferred") + context_keywords(text, "nice to have")))
    tools = _find_keywords(text, TOOLS)
    financial_products = _find_keywords(text, FINANCIAL_PRODUCTS)
    responsibilities = _find_keywords(text, RESPONSIBILITIES)
    ats_keywords = _find_keywords(text, ATS_KEYWORDS)
    repeated = repeated_terms(text)

    resume_relevant = sorted(set(required + preferred + tools + financial_products + responsibilities + ats_keywords))
    top_keywords = sorted(set(resume_relevant + repeated[:10]))
    missing = [keyword for keyword in resume_relevant if keyword.lower() not in master_lower]
    focus = suggest_resume_focus(top_keywords)
    return {
        "required_skills": required,
        "preferred_skills": preferred,
        "tools": tools,
        "financial_products": financial_products,
        "responsibilities": responsibilities,
        "repeated_keywords": repeated,
        "ats_keywords": ats_keywords,
        "top_keywords": top_keywords[:30],
        "missing_keywords_from_master_resume": missing[:20],
        "suggested_resume_focus": focus,
    }


def suggest_resume_focus(keywords: list[str]) -> str:
    lower = " ".join(keywords).lower()
    if any(token in lower for token in ["api", "technical operations", "implementation"]):
        return "API / Technical Operations"
    if any(token in lower for token in ["risk", "credit risk", "operational risk"]):
        return "Risk Analyst / Risk Operations"
    if any(token in lower for token in ["trading", "trade support", "market data", "reconciliation"]):
        return "Trading Operations / Market Data"
    if any(token in lower for token in ["crypto", "digital assets", "exchange"]):
        return "FinTech / Crypto Data Analyst"
    if any(token in lower for token in ["capital markets", "business analysis", "treasury"]):
        return "Capital Markets / Business Analyst"
    return "FinTech / Crypto Data Analyst"


