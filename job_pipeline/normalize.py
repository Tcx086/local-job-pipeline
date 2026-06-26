from __future__ import annotations

import re
from typing import Any

from .utils import normalize_space, stable_id, strip_html


COUNTRY_PATTERNS = {
    "Canada": [
        "canada",
        "toronto",
        "montreal",
        "vancouver",
        "ontario",
        "quebec",
        "british columbia",
    ],
    "United States": [
        "united states",
        "usa",
        "u.s.",
        "new york",
        "california",
        "remote, united states",
    ],
}

SENIORITY_PATTERNS = [
    ("intern", r"\b(intern|internship|co-op|coop)\b"),
    ("new grad", r"\b(new grad|graduate|early career|campus)\b"),
    ("entry", r"\b(entry level|junior|jr\.?)\b"),
    ("senior", r"\b(senior|sr\.?|staff|principal|lead)\b"),
    ("manager", r"\b(manager|head of|director)\b"),
    ("associate", r"\b(associate)\b"),
    ("analyst", r"\b(analyst)\b"),
]


def normalize_company(value: Any) -> str:
    text = normalize_space(value).lower()
    text = re.sub(r"\b(inc|inc\.|ltd|ltd\.|limited|corp|corp\.|corporation|co\.?)\b", "", text)
    return normalize_space(text)


def normalize_title(value: Any) -> str:
    text = normalize_space(value).lower()
    text = re.sub(r"[^a-z0-9+#/ ]+", " ", text)
    return normalize_space(text)


def normalize_location(value: Any) -> str:
    text = normalize_space(value)
    text = re.sub(r"\s*,\s*", ", ", text)
    return text


def detect_country(location: Any, country: Any = "", description: Any = "") -> str:
    explicit = normalize_space(country)
    if explicit in COUNTRY_PATTERNS:
        return explicit
    haystack = f"{location} {country} {description}".lower()
    if "remote" in haystack and not any(token in haystack for tokens in COUNTRY_PATTERNS.values() for token in tokens):
        return "Remote"
    for country_name, tokens in COUNTRY_PATTERNS.items():
        if any(token in haystack for token in tokens):
            return country_name
    return explicit or ""


def detect_seniority(title: Any, description: Any = "") -> str:
    title_text = str(title or "").lower()
    for label, pattern in SENIORITY_PATTERNS:
        if re.search(pattern, title_text):
            return label
    if not title_text.strip():
        description_text = str(description or "").lower()
        for label, pattern in SENIORITY_PATTERNS:
            if re.search(pattern, description_text):
                return label
    return "unspecified"


def normalize_salary(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_job(job: dict[str, Any]) -> dict[str, Any]:
    title = normalize_space(job.get("title"))
    company = normalize_space(job.get("company"))
    location = normalize_location(job.get("location"))
    description = strip_html(job.get("description"))
    job_url = normalize_space(job.get("job_url"))
    apply_url = normalize_space(job.get("apply_url")) or job_url
    normalized = dict(job)
    normalized.update(
        {
            "title": title,
            "company": company,
            "location": location,
            "job_url": job_url,
            "apply_url": apply_url,
            "description": description,
            "normalized_title": normalize_title(title),
            "normalized_company": normalize_company(company),
            "normalized_location": normalize_location(location).lower(),
            "salary_min": normalize_salary(job.get("salary_min")),
            "salary_max": normalize_salary(job.get("salary_max")),
            "detected_country": detect_country(location, job.get("country"), description),
            "seniority": detect_seniority(title, description),
        }
    )
    if not normalized.get("job_id"):
        normalized["job_id"] = stable_id(
            normalized.get("source"),
            normalized.get("title"),
            normalized.get("company"),
            normalized.get("location"),
            normalized.get("job_url"),
        )
    return normalized


def normalize_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_job(job) for job in jobs]
