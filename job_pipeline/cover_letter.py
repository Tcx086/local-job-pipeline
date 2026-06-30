from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .database import DEFAULT_DB, get_job_detail
from .keyword_extract import extract_keywords
from .resources import (
    load_candidate_master,
    load_common_answers,
    load_cover_letter_configurable_templates as load_resource_cover_letter_templates,
    load_cover_letter_human_templates as load_resource_cover_letter_human_templates,
)
from .resume_tailor import write_docx_from_markdown, write_pdf_from_docx, write_pdf_from_markdown
from .utils import CONFIG_DIR, DATA_DIR, TEMPLATES_DIR, flatten_text, load_yaml, now_utc_iso, slugify, today_yyyymmdd, write_json
from .workspace import ApplicationWorkspace, PathRegistry
from .workspace.artifacts import write_workspace_source_files

COVER_LETTER_DIR = DATA_DIR / "cover_letters"
MASTER_RESUME_PATH = TEMPLATES_DIR / "master_resume.yaml"
COMMON_ANSWERS_PATH = CONFIG_DIR / "common_answers.yaml"
COVER_LETTER_TEMPLATE_PATH = CONFIG_DIR / "cover_letter_templates.yaml"
COVER_LETTER_HUMAN_TEMPLATE_PATH = CONFIG_DIR / "cover_letter_human_templates.yaml"
BUILTIN_TEMPLATE_ID = "builtin_safe"
DISABLED_EFFORTS = {"quick_apply", "hold", "skip"}
SENSITIVE_TERMS = {
    "passport",
    "bank account",
    "banking info",
    "financial account",
    "exact dob",
    "date of birth",
    "birth date",
    "eeo",
    "disability",
    "veteran",
    "government id",
    "social security",
    "ssn",
    "sin number",
    "health data",
    "medical record",
    "medical condition",
    "medical history",
    "race",
    "ethnicity",
    "gender",
}
DEFAULT_NON_CORE_SKILL_LABELS = {
    "english",
    "english language",
    "mandarin",
    "mandarin chinese",
    "chinese",
    "cantonese",
    "spanish",
    "french",
    "japanese",
    "korean",
}
PAST_TENSE_BULLET_STARTERS = {
    "applied",
    "assisted",
    "built",
    "communicated",
    "conducted",
    "coordinated",
    "created",
    "designed",
    "developed",
    "documented",
    "explored",
    "improved",
    "integrated",
    "maintained",
    "managed",
    "organized",
    "prepared",
    "processed",
    "reviewed",
    "resolved",
    "supported",
    "translated",
    "used",
}
GENERIC_COMPANY_REASON_PATTERNS = [
    re.compile(r"\boperating at (?:the )?highest level\b", re.I),
    re.compile(r"\bwe (?:are|'re) (?:a )?global leader\b", re.I),
    re.compile(r"\bglobal leader\b", re.I),
    re.compile(r"\bjoin our team\b", re.I),
    re.compile(r"\bwe are proud to\b", re.I),
]
HUMAN_TEMPLATE_PRIORITY = [
    "quality_assurance",
    "client_finance",
    "data_market_data",
    "risk_operations",
    "trading_operations",
    "api_technical_operations",
]
HUMAN_TEMPLATE_EVIDENCE_TERMS = {
    "quality_assurance": [
        "quality assurance",
        "quality control",
        "documentation",
        "documentation accuracy",
        "process tracking",
        "process accuracy",
        "data accuracy",
        "data quality",
        "quality checks",
        "testing",
        "validation",
        "human validation",
        "reporting",
        "record tracking",
        "records",
        "communication",
        "follow-up",
        "resolved inconsistencies",
    ],
    "data_market_data": [
        "data analysis",
        "data quality",
        "market data",
        "reporting",
        "decision support",
        "python",
        "sql",
        "excel",
        "data cleaning",
        "monitoring",
    ],
    "risk_operations": [
        "risk",
        "risk-management",
        "controls",
        "reconciliation",
        "data validation",
        "reporting",
        "documentation",
        "operational follow-up",
    ],
    "trading_operations": [
        "market data",
        "exchange",
        "trade",
        "trading",
        "operational checks",
        "monitoring",
        "reconciliation",
        "reporting",
        "execution simulation",
    ],
    "api_technical_operations": [
        "api",
        "rest api",
        "json",
        "technical troubleshooting",
        "debugging",
        "documentation",
        "communication",
        "workflow automation",
    ],
    "client_finance": [
        "budget",
        "financial",
        "financing",
        "reporting",
        "data accuracy",
        "documentation",
        "follow-up",
        "transaction",
        "variance",
    ],
}
QA_CONTEXT_BLOCKED_TERMS = {
    "finance",
    "financial",
    "financing",
    "lender",
    "cash-handling",
    "cash handling",
    "payment",
    "sales targets",
    "dealership",
    "deal completion",
    "investment",
    "trading",
    "crypto",
    "digital asset",
    "market data",
    "capital markets",
    "practical finance",
    "quantitative trading",
}
EVIDENCE_TERM_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "into",
    "this",
    "that",
    "role",
    "team",
    "work",
    "using",
    "across",
    "support",
}

def cover_letter_paths(
    canonical_job_id: str,
    company: str = "",
    title: str = "",
    output_dir: Path = COVER_LETTER_DIR,
) -> dict[str, Path]:
    company_slug = slugify(company or "company", 60)
    role_slug = slugify(title or "role", 55)
    job_slug = slugify(canonical_job_id or "job", 24)
    target_dir = output_dir / company_slug / today_yyyymmdd() / f"{role_slug}_{job_slug}"
    return {
        "directory": target_dir,
        "markdown": target_dir / "cover_letter.md",
        "json": target_dir / "cover_letter.json",
        "docx": target_dir / "cover_letter.docx",
        "pdf": target_dir / "cover_letter.pdf",
        "formal_docx": target_dir / "cover_letter.docx",
        "formal_pdf": target_dir / "cover_letter.pdf",
    }


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = load_yaml(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_cover_letter_templates(path: Path | None = None) -> dict[str, Any]:
    data = load_resource_cover_letter_templates() if path is None else _load_config(path)
    if not isinstance(data.get("templates"), dict):
        return {}
    return data


def load_cover_letter_human_templates(path: Path | None = None) -> dict[str, Any]:
    data = load_resource_cover_letter_human_templates() if path is None else _load_config(path)
    if not isinstance(data.get("templates_v2"), dict):
        return {}
    return data

def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        items: list[dict[str, Any]] = []
        for key, item in value.items():
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("id", str(key))
            row.setdefault("name", row.get("title") or str(key).replace("_", " ").title())
            items.append(row)
        return items
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _contains_sensitive(value: Any) -> bool:
    lower = flatten_text(value).lower()
    return any(term in lower for term in SENSITIVE_TERMS)


def _dedupe(items: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = _clean_text(item)
        marker = cleaned.lower()
        if not cleaned or marker in seen or _contains_sensitive(cleaned):
            continue
        seen.add(marker)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _keyword_candidates(keyword_info: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    for bucket in [
        "required_skills",
        "preferred_skills",
        "tools",
        "financial_products",
        "responsibilities",
        "ats_keywords",
        "top_keywords",
        "repeated_keywords",
    ]:
        ordered.extend(str(item) for item in keyword_info.get(bucket) or [])
    return _dedupe(ordered, 30)


def _supported_keywords(keyword_info: dict[str, Any], master_text: str) -> tuple[list[str], list[str]]:
    master_lower = master_text.lower()
    missing = _dedupe([str(item) for item in keyword_info.get("missing_keywords_from_master_resume") or []], 20)
    missing_lower = {item.lower() for item in missing}
    supported = [
        keyword
        for keyword in _keyword_candidates(keyword_info)
        if keyword.lower() not in missing_lower and keyword.lower() in master_lower and not _contains_sensitive(keyword)
    ]
    return _dedupe(supported, 12), missing


def _score_text(value: Any, keywords: list[str]) -> int:
    lower = flatten_text(value).lower()
    return sum(1 for keyword in keywords if keyword and keyword.lower() in lower)


def _rank_items(items: list[Any], keywords: list[str], limit: int) -> list[Any]:
    safe_items = [item for item in items if not _contains_sensitive(item)]
    ranked = sorted(safe_items, key=lambda item: _score_text(item, keywords), reverse=True)
    return ranked[:limit]


def _skills_from_master(master: dict[str, Any]) -> list[str]:
    skills: list[str] = []
    values = master.get("skills") or {}
    if isinstance(values, dict):
        for group_values in values.values():
            skills.extend(str(item) for item in _as_list(group_values))
    else:
        skills.extend(str(item) for item in _as_list(values))
    return _dedupe(skills, 300)


def _selected_summary(master: dict[str, Any], keywords: list[str]) -> str:
    summaries = [str(item) for item in _as_list(master.get("summary")) if str(item).strip()]
    ranked = _rank_items(summaries, keywords, 1)
    if ranked:
        return _clean_text(ranked[0])
    return _clean_text(summaries[0]) if summaries else ""


def _best_bullet(item: dict[str, Any], keywords: list[str], preferred_terms: list[str] | None = None) -> str:
    bullets = [str(bullet) for bullet in _as_list(item.get("bullets")) if str(bullet).strip()]
    ranking_terms = _dedupe([*keywords, *(preferred_terms or [])], 40)
    ranked = _rank_items(bullets, ranking_terms, 1)
    return _clean_text(ranked[0]) if ranked else ""


def _selected_evidence(
    master: dict[str, Any],
    keywords: list[str],
    blocked_terms: set[str] | None = None,
    preferred_terms: list[str] | None = None,
    non_core_skill_labels: set[str] | None = None,
) -> dict[str, Any]:
    blocked_terms = blocked_terms or set()
    preferred_terms = preferred_terms or []
    non_core_skill_labels = non_core_skill_labels or set()
    evidence_items: list[dict[str, Any]] = []
    for source_type, items in [
        ("project", _dict_items(master.get("projects"))),
        ("experience", _dict_items(master.get("experience"))),
    ]:
        for item in items:
            bullet = _best_bullet(item, keywords, preferred_terms)
            if not bullet or _contains_sensitive(bullet) or _contains_blocked(bullet, blocked_terms):
                continue
            evidence_items.append(
                {
                    "source_type": source_type,
                    "title": _clean_text(item.get("name") or item.get("title") or ""),
                    "organization": _clean_text(item.get("company") or item.get("type") or ""),
                    "dates": _clean_text(item.get("dates") or ""),
                    "bullet": bullet,
                    "score": (_score_text(item, keywords) * 3) + _score_text(item, preferred_terms),
                }
            )
    evidence_items = sorted(evidence_items, key=lambda item: int(item.get("score") or 0), reverse=True)[:2]
    for item in evidence_items:
        item.pop("score", None)

    core_master_skills = [
        skill
        for skill in _skills_from_master(master)
        if not _contains_blocked(skill, blocked_terms) and not _is_non_core_skill_label(skill, non_core_skill_labels)
    ]
    skills = _rank_items(core_master_skills, keywords, 6)
    skills = _dedupe([str(skill) for skill in skills], 6)
    if len(skills) < 4:
        fallback_skills = _dedupe(core_master_skills, 6)
        skills = _dedupe([*skills, *fallback_skills], 6)

    return {
        "summary_angle": _selected_summary(master, keywords),
        "projects_or_experience": evidence_items[:2],
        "skills": skills[:6],
    }


def _evidence_sentence(evidence: dict[str, Any]) -> str:
    title = _clean_text(evidence.get("title"))
    organization = _clean_text(evidence.get("organization"))
    bullet = _clean_text(evidence.get("bullet"))
    if title and organization:
        return f"In {title} ({organization}), my work included: {bullet}"
    if title:
        return f"In {title}, my work included: {bullet}"
    return bullet


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "TODO: Review manually."


def _global_rules(config: dict[str, Any]) -> dict[str, Any]:
    rules = config.get("global_rules") if isinstance(config.get("global_rules"), dict) else {}
    return rules if isinstance(rules, dict) else {}


def _template_todos(config: dict[str, Any]) -> list[str]:
    rules = _global_rules(config)
    todos = [str(item) for item in _as_list(rules.get("always_include_todos")) if str(item).strip()]
    return todos or [
        "Review every factual claim against the master resume and job description before use.",
        "Replace TODOs before submitting.",
    ]


def _prohibited_terms(config: dict[str, Any]) -> set[str]:
    rules = _global_rules(config)
    terms = set(SENSITIVE_TERMS)
    for key in ["never_claim", "sensitive_exclusions"]:
        for item in _as_list(rules.get(key)):
            text = _clean_text(item).lower()
            if text:
                terms.add(text)
    return terms


def _non_core_skill_labels(config: dict[str, Any]) -> set[str]:
    rules = _global_rules(config)
    labels = set(DEFAULT_NON_CORE_SKILL_LABELS)
    for source in [rules, config]:
        for key in ["blocked_skill_labels", "non_core_skill_labels"]:
            for item in _as_list(source.get(key) if isinstance(source, dict) else None):
                cleaned = _clean_text(item).lower()
                if cleaned:
                    labels.add(cleaned)
    return labels


def _is_non_core_skill_label(value: Any, labels: set[str]) -> bool:
    text = _clean_text(value).lower()
    if not text:
        return False
    base = re.split(r"\s+[-(]\s*", text, maxsplit=1)[0].strip()
    return text in labels or base in labels


def _contains_blocked(value: Any, blocked_terms: set[str]) -> bool:
    lower = flatten_text(value).lower()
    return any(term and term in lower for term in blocked_terms)


def _safe_config_phrase(value: Any, blocked_terms: set[str]) -> str:
    text = _clean_text(value)
    if not text or _contains_sensitive(text) or _contains_blocked(text, blocked_terms):
        return ""
    return text


def _overlay_focus_fallback(overlay: dict[str, Any], fallback: dict[str, Any], blocked_terms: set[str]) -> str:
    for source in [overlay, fallback]:
        for key in ["jd_focus_fallback", "positioning"]:
            phrase = _safe_config_phrase(source.get(key), blocked_terms)
            if phrase:
                return phrase
    return ""


def _overlay_positioning(overlay: dict[str, Any], fallback: dict[str, Any], blocked_terms: set[str]) -> str:
    for source in [overlay, fallback]:
        phrase = _safe_config_phrase(source.get("positioning"), blocked_terms)
        if phrase:
            return phrase
    return ""


def _overlay_supported_skill_labels(overlay: dict[str, Any], master_text: str, blocked_terms: set[str]) -> list[str]:
    master_lower = master_text.lower()
    labels: list[str] = []
    for label in _as_list(overlay.get("safe_skill_groups")):
        cleaned = _safe_config_phrase(label, blocked_terms)
        if cleaned and cleaned.lower() in master_lower:
            labels.append(cleaned)
    return _dedupe(labels, 6)


def _overlay_preferred_terms(overlay: dict[str, Any], blocked_terms: set[str]) -> list[str]:
    terms: list[str] = []
    for item in _as_list(overlay.get("preferred_evidence")):
        cleaned = _safe_config_phrase(item, blocked_terms)
        if not cleaned:
            continue
        terms.append(cleaned)
        normalized = cleaned.replace("-", " ")
        if normalized != cleaned:
            terms.append(normalized)
        for part in re.split(r"[/,;]|\bor\b|\band\b", normalized, flags=re.IGNORECASE):
            part = _safe_config_phrase(part, blocked_terms)
            if part:
                terms.append(part)
    return _dedupe(terms, 24)

def _effort_from_job(job: dict[str, Any]) -> str:
    for key in ["application_effort", "campaign_effort", "effort"]:
        effort = str(job.get(key) or "").strip()
        if effort:
            return effort
    return ""


def _template_enabled_for_effort(template: dict[str, Any], effort: str) -> bool:
    enabled = {str(item) for item in _as_list(template.get("enabled_for_efforts"))}
    return bool(effort and effort in enabled)


def _valid_full_template(template: Any) -> bool:
    return isinstance(template, dict) and isinstance(template.get("paragraphs"), list) and bool(template.get("paragraphs"))


def _select_template(config: dict[str, Any], job: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    templates = config.get("templates") if isinstance(config.get("templates"), dict) else {}
    effort = _effort_from_job(job)
    effort_template = {
        "deep_tailor": "full_deep_tailor",
        "standard_tailor": "full_standard_tailor",
    }.get(effort)
    if effort_template:
        template = templates.get(effort_template)
        if _valid_full_template(template) and _template_enabled_for_effort(template, effort):
            return effort_template, template, effort
        return BUILTIN_TEMPLATE_ID, {}, effort
    if effort in DISABLED_EFFORTS:
        for template_id, template in templates.items():
            if str(template_id).startswith("full_") and _valid_full_template(template) and _template_enabled_for_effort(template, effort):
                return str(template_id), template, effort
        return BUILTIN_TEMPLATE_ID, {}, effort
    template = templates.get("full_standard_tailor")
    if _valid_full_template(template):
        return "full_standard_tailor", template, "fallback"
    return BUILTIN_TEMPLATE_ID, {}, effort or "fallback"

def _explicit_generation_enabled(config: dict[str, Any], effort: str) -> bool:
    if effort not in DISABLED_EFFORTS:
        return True
    templates = config.get("templates") if isinstance(config.get("templates"), dict) else {}
    for template_id, template in templates.items():
        if str(template_id).startswith("full_") and _valid_full_template(template) and _template_enabled_for_effort(template, effort):
            return True
    return False


def cover_letter_generation_enabled(job: dict[str, Any], template_path: Path | None = None) -> bool:
    return _explicit_generation_enabled(load_cover_letter_templates(template_path), _effort_from_job(job))


def _ensure_generation_enabled(config: dict[str, Any], job: dict[str, Any]) -> None:
    effort = _effort_from_job(job)
    if not _explicit_generation_enabled(config, effort):
        raise ValueError(f"Cover letter generation is disabled for application_effort={effort}.")

def _normalized_profile(value: Any) -> str:
    return str(value or "").strip().lower()


def _role_overlay_matches(job: dict[str, Any], overlay_id: str) -> bool:
    role_family = _normalized_profile(job.get("role_family") or job.get("fit_category")).replace("-", "_").replace(" ", "_")
    text = " ".join(str(job.get(key) or "") for key in ["title", "description", "role_category", "role_family"]).lower()
    if overlay_id in role_family:
        return True
    patterns = {
        "quality_assurance": [
            "quality assurance",
            "qa analyst",
            "quality analyst",
            "quality control",
            "non-conformance",
            "nonconformance",
            "audit documentation",
            "continuous improvement",
            "manufacturing quality",
        ],
        "client_finance": ["client finance", "budget", "variance", "billing", "project financial", "project finance"],
        "revenue_operations": ["revenue operations", "revops", "revenue ops", "sales operations", "crm", "pipeline reporting"],
    }
    return any(pattern in text for pattern in patterns.get(overlay_id, []))


def _select_overlay(config: dict[str, Any], job: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    role_overlays = config.get("role_family_overlays") if isinstance(config.get("role_family_overlays"), dict) else {}
    for overlay_id in ["quality_assurance", "client_finance", "revenue_operations"]:
        overlay = role_overlays.get(overlay_id)
        if isinstance(overlay, dict) and _role_overlay_matches(job, overlay_id):
            return overlay_id, overlay
    profile_overlays = config.get("profile_overlays") if isinstance(config.get("profile_overlays"), dict) else {}
    profile = _normalized_profile(job.get("resume_profile") or job.get("profile"))
    if profile in profile_overlays and isinstance(profile_overlays.get(profile), dict):
        return profile, profile_overlays[profile]
    fallback = config.get("fallback") if isinstance(config.get("fallback"), dict) else {}
    return "fallback", fallback if isinstance(fallback, dict) else {}



def _normalized_template_key(value: Any) -> str:
    return _normalized_profile(value).replace("-", "_").replace(" ", "_")


def _job_search_text(job: dict[str, Any]) -> str:
    return " ".join(
        str(job.get(key) or "")
        for key in ["title", "description", "role_category", "role_family", "fit_category", "resume_profile", "profile"]
    ).lower()


def _human_templates(config: dict[str, Any]) -> dict[str, Any]:
    templates = config.get("templates_v2") if isinstance(config.get("templates_v2"), dict) else {}
    return templates if isinstance(templates, dict) else {}


def _valid_human_template(template: Any) -> bool:
    return isinstance(template, dict) and isinstance(template.get("body"), dict)


def _human_enabled_values(template: dict[str, Any], key: str) -> list[str]:
    enabled_for = template.get("enabled_for") if isinstance(template.get("enabled_for"), dict) else {}
    return [_clean_text(item).lower() for item in _as_list(enabled_for.get(key)) if _clean_text(item)]


def _human_template_matches(job: dict[str, Any], template_id: str, template: dict[str, Any]) -> bool:
    profile = _normalized_template_key(job.get("resume_profile") or job.get("profile"))
    role_values = {
        _normalized_template_key(job.get("role_family") or job.get("fit_category")),
        _normalized_template_key(job.get("role_category")),
    }
    title = str(job.get("title") or "").lower()

    for expected in _human_enabled_values(template, "resume_profile"):
        if profile and profile == _normalized_template_key(expected):
            return True
    for expected in _human_enabled_values(template, "role_family"):
        if _normalized_template_key(expected) in role_values:
            return True
    for expected in _human_enabled_values(template, "title_contains"):
        if expected and expected in title:
            return True

    if template_id in {"quality_assurance", "client_finance"}:
        return _role_overlay_matches(job, template_id)
    return False


def _select_human_template(config: dict[str, Any], job: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    templates = _human_templates(config)
    ordered_ids = [*HUMAN_TEMPLATE_PRIORITY, *(template_id for template_id in templates if template_id not in HUMAN_TEMPLATE_PRIORITY)]
    for template_id in ordered_ids:
        template = templates.get(template_id)
        if _valid_human_template(template) and _human_template_matches(job, str(template_id), template):
            return str(template_id), template
    return "", {}


def _qa_allows_financial_terms(job: dict[str, Any]) -> bool:
    text = _job_search_text(job)
    financial = r"(?:financial|finance|financing|banking|investment|trading|crypto|market data|capital markets)"
    qa = r"(?:qa|quality assurance|quality analyst|quality control|financial qa)"
    return bool(
        re.search(financial + r"\W+(?:\w+\W+){0,10}?" + qa, text)
        or re.search(qa + r"\W+(?:\w+\W+){0,10}?" + financial, text)
    )


def _human_blocked_terms(template_id: str, template: dict[str, Any], job: dict[str, Any], blocked_terms: set[str]) -> set[str]:
    terms = set(blocked_terms)
    for item in _as_list(template.get("blocked_phrases")):
        cleaned = _clean_text(item).lower()
        if cleaned:
            terms.add(cleaned)
    if template_id == "quality_assurance" and not _qa_allows_financial_terms(job):
        terms.update(QA_CONTEXT_BLOCKED_TERMS)
    return terms


def _human_evidence_terms(
    template_id: str,
    template: dict[str, Any],
    overlay: dict[str, Any],
    keywords: list[str],
    preferred_terms: list[str],
    blocked_terms: set[str],
) -> list[str]:
    terms: list[str] = [*keywords, *preferred_terms, *HUMAN_TEMPLATE_EVIDENCE_TERMS.get(template_id, [])]
    body = template.get("body") if isinstance(template.get("body"), dict) else {}
    for text in body.values():
        terms.extend(re.findall(r"[a-zA-Z][a-zA-Z0-9+#-]*(?:\s+[a-zA-Z][a-zA-Z0-9+#-]*){0,2}", str(text or "")))
    for key in ["preferred_evidence", "safe_skill_groups"]:
        terms.extend(str(item) for item in _as_list(overlay.get(key)))
    return _dedupe([term for term in terms if not _contains_blocked(term, blocked_terms)], 80)


def _evidence_term_parts(term: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9+#-]{2,}", term.lower())
        if word not in EVIDENCE_TERM_STOPWORDS
    ]


def _evidence_match_score(text: str, terms: list[str]) -> int:
    lower = text.lower()
    score = 0
    for term in terms:
        cleaned = _clean_text(term).lower()
        if not cleaned:
            continue
        if cleaned in lower:
            score += 4 if " " in cleaned else 2
        for word in _evidence_term_parts(cleaned):
            if word in lower:
                score += 1
    return score


def _selected_human_evidence(master: dict[str, Any], terms: list[str], blocked_terms: set[str], limit: int = 2) -> list[dict[str, Any]]:
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    index = 0
    for source_type, items in [
        ("project", _dict_items(master.get("projects"))),
        ("experience", _dict_items(master.get("experience"))),
    ]:
        for item in items:
            for bullet_value in _as_list(item.get("bullets")):
                bullet = _clean_text(bullet_value)
                if not bullet:
                    continue
                source_text = " ".join(
                    [
                        _clean_text(item.get("name") or item.get("title") or ""),
                        _clean_text(item.get("company") or item.get("type") or ""),
                        bullet,
                    ]
                )
                if _contains_sensitive(source_text) or _contains_blocked(source_text, blocked_terms):
                    continue
                score = _evidence_match_score(source_text, terms)
                if score <= 0:
                    continue
                ranked.append(
                    (
                        score,
                        index,
                        {
                            "source_type": source_type,
                            "title": _clean_text(item.get("name") or item.get("title") or ""),
                            "organization": _clean_text(item.get("company") or item.get("type") or ""),
                            "dates": _clean_text(item.get("dates") or ""),
                            "bullet": bullet,
                            "match_score": score,
                        },
                    )
                )
                index += 1
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, _, record in ranked:
        marker = str(record.get("bullet") or "").lower()
        if marker in seen:
            continue
        seen.add(marker)
        selected.append(record)
        if len(selected) >= limit:
            break
    return selected


def _human_evidence_clause(evidence: dict[str, Any]) -> str:
    text = _lower_first(str(evidence.get("bullet") or ""))
    text = re.sub(r"^worked on\s+", "", text, flags=re.I)
    return _clean_text(text).rstrip(".")


def _human_template_values(job: dict[str, Any], template: dict[str, Any], evidence_points: list[dict[str, Any]]) -> dict[str, str]:
    body = template.get("body") if isinstance(template.get("body"), dict) else {}
    evidence_key = "evidence_double" if len(evidence_points) > 1 else "evidence_single"
    evidence_1 = _human_evidence_clause(evidence_points[0]) if evidence_points else ""
    if evidence_1 and re.search(r"\bincludes\s+\{evidence_1\}", str(body.get(evidence_key) or ""), re.I):
        evidence_1 = f"work where I {evidence_1}"
    values = {
        "company": _clean_text(job.get("company")) or "the company",
        "title": _clean_text(job.get("title")) or "this role",
        "evidence_1": evidence_1,
        "evidence_2": _human_evidence_clause(evidence_points[1]) if len(evidence_points) > 1 else "",
    }
    return values


def _render_human_template_body(*, template: dict[str, Any], values: dict[str, str], master: dict[str, Any]) -> str:
    body = template.get("body") if isinstance(template.get("body"), dict) else {}
    evidence_key = "evidence_double" if values.get("evidence_2") else "evidence_single"
    learning = _safe_format(body.get("learning"), values)
    closing = _safe_format(body.get("closing"), values)
    paragraphs = [
        _safe_format(body.get("opening"), values),
        _safe_format(body.get(evidence_key), values),
        _clean_text(f"{learning} {closing}"),
    ]
    name = _clean_text(master.get("name"))
    lines = ["Dear Hiring Team,", ""]
    for paragraph in paragraphs:
        if paragraph:
            lines.extend([paragraph, ""])
    lines.extend(["Thank you for your time and consideration.", "", "Sincerely,"])
    if name:
        lines.append(name)
    return "\n".join(lines).strip() + "\n"


def _mark_human_insufficient_evidence(payload: dict[str, Any]) -> None:
    payload["cover_letter_body"] = ""
    payload["cover_letter_markdown"] = "Manual review required: insufficient evidence.\n"
    payload["manual_review_required"] = True
    payload["manual_review_reason"] = "insufficient evidence"
    payload["reason"] = "insufficient evidence"
    payload["generation_status"] = "manual_review_required"
    payload["formal_generation_skipped"] = True
    payload["todo"] = []

def _join_phrase(items: list[str]) -> str:
    clean = _dedupe(items, 8)
    if not clean:
        return "TODO: Add evidence-backed skills from the master resume."
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f", and {clean[-1]}"


def _lower_first(value: str) -> str:
    text = _clean_text(value).rstrip(".")
    if not text:
        return ""
    return text[0].lower() + text[1:]


def _evidence_clause(evidence: dict[str, Any]) -> str:
    return _lower_first(str(evidence.get("bullet") or ""))


def _evidence_action_sentence(evidence: dict[str, Any]) -> str:
    bullet = _clean_text(evidence.get("bullet")).rstrip(".")
    if not bullet:
        return "TODO: Add one evidence-backed example from the master resume"
    first_word = re.split(r"\s+", bullet, maxsplit=1)[0].lower()
    if first_word in PAST_TENSE_BULLET_STARTERS or first_word.endswith("ed"):
        return f"I {_lower_first(bullet)}"
    return f"My relevant experience includes {_lower_first(bullet)}"


def _split_sentences(text: str) -> list[str]:
    return [_clean_text(item) for item in re.split(r"(?<=[.!?])\s+", str(text or "")) if _clean_text(item)]


def _dedupe_punctuation(text: str) -> str:
    cleaned = _clean_text(text)
    cleaned = re.sub(r"([.!?]){2,}", r"\1", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return cleaned


def _is_generic_company_reason(sentence: str, policy: dict[str, Any]) -> bool:
    patterns = list(GENERIC_COMPANY_REASON_PATTERNS)
    for phrase in _as_list(policy.get("generic_slogan_phrases")):
        cleaned = _clean_text(phrase)
        if cleaned:
            patterns.append(re.compile(re.escape(cleaned), re.I))
    return any(pattern.search(sentence) for pattern in patterns)


def _company_reason_from_jd(job: dict[str, Any], config: dict[str, Any], blocked_terms: set[str]) -> str:
    policy = config.get("company_reason_policy") if isinstance(config.get("company_reason_policy"), dict) else {}
    todo = str(policy.get("todo_text") or "TODO: Add one specific reason for this company after reviewing the posting.")
    company = str(job.get("company") or "").strip().lower()
    for sentence in _split_sentences(str(job.get("description") or "")):
        sentence = _dedupe_punctuation(sentence)
        lower = sentence.lower()
        if _contains_sensitive(sentence) or _contains_blocked(sentence, blocked_terms):
            continue
        if _is_generic_company_reason(sentence, policy):
            continue
        has_company = bool(company and company in lower)
        has_team_context = "our " in lower and any(token in lower for token in ["team", "platform", "product", "client", "customer", "mission"])
        if has_company or has_team_context:
            clipped = _dedupe_punctuation(sentence[:180].rstrip(" ,;:.!?"))
            if clipped:
                return _dedupe_punctuation(f"The job description notes that {clipped}.")
    return todo


def _safe_format(template_text: Any, values: dict[str, str]) -> str:
    try:
        return str(template_text or "").format_map(_SafeFormatDict(values))
    except (KeyError, ValueError):
        return "TODO: Review this section manually."


def _limit_words(text: str, max_words: int) -> str:
    words = text.split()
    if not max_words or len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


def _template_values(
    *,
    master: dict[str, Any],
    job: dict[str, Any],
    payload: dict[str, Any],
    config: dict[str, Any],
    overlay: dict[str, Any],
    blocked_terms: set[str],
    non_core_skill_labels: set[str],
) -> dict[str, str]:
    evidence = payload.get("selected_evidence") or {}
    evidence_points = [item for item in evidence.get("projects_or_experience") or [] if isinstance(item, dict)]
    fallback = config.get("fallback") if isinstance(config.get("fallback"), dict) else {}
    master_text = flatten_text(master)
    skills = _dedupe(
        [
            str(skill)
            for skill in evidence.get("skills") or []
            if not _contains_blocked(skill, blocked_terms) and not _is_non_core_skill_label(skill, non_core_skill_labels)
        ],
        6,
    )
    overlay_skills = [
        skill
        for skill in _overlay_supported_skill_labels(overlay, master_text, blocked_terms)
        if not _is_non_core_skill_label(skill, non_core_skill_labels)
    ]
    if overlay_skills:
        skills = _dedupe([*overlay_skills, *skills], 6)
    keywords = _dedupe(
        [
            str(keyword)
            for keyword in payload.get("top_keywords_to_reflect") or []
            if not _contains_blocked(keyword, blocked_terms) and not _is_non_core_skill_label(keyword, non_core_skill_labels)
        ],
        6,
    )
    sparse_evidence = "TODO: Add one evidence-backed example from the master resume"
    first_evidence = _evidence_action_sentence(evidence_points[0]) if evidence_points else sparse_evidence
    second_evidence = _evidence_action_sentence(evidence_points[1]) if len(evidence_points) > 1 else sparse_evidence
    jd_focus = _join_phrase(keywords[:3]) if len(keywords) >= 2 else ""
    if not jd_focus:
        jd_focus = _overlay_focus_fallback(overlay, fallback, blocked_terms)
    if not jd_focus:
        jd_focus = _join_phrase(keywords[:3]) if keywords else "the responsibilities described in the posting"
    skill_phrase = _join_phrase(skills) if skills else "TODO: Add evidence-backed skills from the master resume"
    return {
        "company": _clean_text(job.get("company")) or "the company",
        "title": _clean_text(job.get("title")) or "this role",
        "candidate_name": _clean_text(master.get("name")),
        "jd_focus_phrase": jd_focus,
        "matched_skill_phrase": skill_phrase,
        "skill_list_sentence": skill_phrase,
        "positioning_phrase": _overlay_positioning(overlay, fallback, blocked_terms) or "data-driven operations and structured problem-solving",
        "evidence_sentence_1": first_evidence,
        "evidence_sentence_2": second_evidence,
        "evidence_short_phrase": first_evidence,
        "company_reason_sentence": _company_reason_from_jd(job, config, blocked_terms),
        "recruiter_name_or_team": "Hiring Team",
    }


def _render_review_markdown(company: str, title: str, body: str) -> str:
    lines = [
        f"# Cover Letter - {company} - {title}",
        "",
        "> Manual review required before use. This draft is local-only and may contain TODOs for factual review.",
        "",
        body.strip(),
    ]
    return "\n".join(lines).strip() + "\n"


def _render_template_body(*, config: dict[str, Any], template: dict[str, Any], values: dict[str, str]) -> str:
    rules = _global_rules(config)
    lines = [
        str(rules.get("default_greeting") or "Dear Hiring Team,"),
        "",
    ]
    for paragraph in template.get("paragraphs") or []:
        lines.extend([_safe_format(paragraph, values), ""])
    closing = _safe_format(template.get("closing") or "Thank you for your time and consideration.", values)
    if closing:
        lines.extend([closing, ""])
    signoff = str(rules.get("default_signoff") or "Sincerely,")
    lines.append(signoff)
    if values.get("candidate_name"):
        lines.append(values["candidate_name"])
    return "\n".join(lines).strip() + "\n"


def _render_template_markdown(
    *,
    payload: dict[str, Any],
    master: dict[str, Any],
    config: dict[str, Any],
    template: dict[str, Any],
    values: dict[str, str],
) -> str:
    return _render_review_markdown(values["company"], values["title"], _render_template_body(config=config, template=template, values=values))


def _render_short_intro(config: dict[str, Any], effort: str, values: dict[str, str]) -> str:
    templates = config.get("templates") if isinstance(config.get("templates"), dict) else {}
    template = templates.get("short_intro") if isinstance(templates.get("short_intro"), dict) else {}
    enabled_effort = "standard_tailor" if effort == "fallback" else effort
    if not template or (enabled_effort and not _template_enabled_for_effort(template, enabled_effort)):
        return ""
    rules = _global_rules(config)
    text = _safe_format(template.get("text"), values)
    return _limit_words(text, int(rules.get("max_short_intro_words") or template.get("target_words") or 90))


def _render_cover_letter_body(payload: dict[str, Any], master: dict[str, Any]) -> str:
    meta = payload.get("metadata") or {}
    evidence = payload.get("selected_evidence") or {}
    company = _clean_text(meta.get("company")) or "the company"
    title = _clean_text(meta.get("title")) or "this role"
    name = _clean_text(master.get("name"))
    skills = _dedupe([str(skill) for skill in evidence.get("skills") or []], 6)
    summary = _clean_text(evidence.get("summary_angle"))
    evidence_points = [item for item in evidence.get("projects_or_experience") or [] if isinstance(item, dict)]

    first = f"I am writing to apply for the {title} role at {company}."
    if summary:
        first += f" {summary}"
    first += " TODO: Add one company-specific reason that is directly supported by the posting before sending."

    if evidence_points:
        second = " ".join(_evidence_sentence(item) for item in evidence_points[:2])
    else:
        second = "My closest relevant background is summarized in the local master resume; please review and add one evidence-backed example before sending."

    keyword_phrase = ", ".join(payload.get("top_keywords_to_reflect") or [])
    skill_phrase = ", ".join(skills[:6])
    if keyword_phrase and skill_phrase:
        third = (
            f"I would be glad to bring my experience with {skill_phrase} to responsibilities involving {keyword_phrase}. "
            "Where a requirement is only partially matched, I would frame it as an area I am interested in applying my existing experience toward."
        )
    elif skill_phrase:
        third = f"I would be glad to bring my experience with {skill_phrase} to this role while learning the team-specific systems and expectations."
    else:
        third = "I would be glad to discuss how my existing experience can support the responsibilities described in the posting."

    lines = [
        "Dear Hiring Team,",
        "",
        first,
        "",
        second,
        "",
        third,
        "",
        "Thank you for your time and consideration.",
    ]
    if name:
        lines.extend(["", "Sincerely,", name])
    return "\n".join(lines).strip() + "\n"


def _render_cover_letter_markdown(payload: dict[str, Any], master: dict[str, Any]) -> str:
    meta = payload.get("metadata") or {}
    company = _clean_text(meta.get("company")) or "the company"
    title = _clean_text(meta.get("title")) or "this role"
    return _render_review_markdown(company, title, _render_cover_letter_body(payload, master))


def generate_cover_letter(
    job: dict[str, Any],
    *,
    generated_resume_file: str = "",
    output_dir: Path | None = None,
    master_resume_path: Path | None = None,
    common_answers_path: Path | None = None,
    template_path: Path | None = None,
    human_template_path: Path | None = None,
    make_docx: bool = True,
    make_pdf: bool = True,
    path_registry: PathRegistry | None = None,
    workspace_date: str | None = None,
) -> dict[str, Any]:
    registry = path_registry or PathRegistry.from_project_root()
    master = _load_config(master_resume_path) if master_resume_path is not None else load_candidate_master(registry)
    _ = _load_config(common_answers_path) if common_answers_path is not None else load_common_answers(registry)
    template_config = load_cover_letter_templates(template_path)
    human_template_config = load_cover_letter_human_templates(human_template_path)
    _ensure_generation_enabled(template_config, job)
    blocked_terms = _prohibited_terms(template_config)
    non_core_skill_labels = _non_core_skill_labels(template_config)
    resume_text = flatten_text(master)
    keyword_info = extract_keywords(str(job.get("description") or ""), resume_text)
    keywords, missing = _supported_keywords(keyword_info, resume_text)
    keywords = [keyword for keyword in keywords if not _contains_blocked(keyword, blocked_terms)]
    keywords = [keyword for keyword in keywords if not _is_non_core_skill_label(keyword, non_core_skill_labels)]
    missing = [keyword for keyword in missing if not _contains_sensitive(keyword) and not _contains_blocked(keyword, blocked_terms)]
    missing = [keyword for keyword in missing if not _is_non_core_skill_label(keyword, non_core_skill_labels)]
    template_id, selected_template, effort_used = _select_template(template_config, job) if template_config else (BUILTIN_TEMPLATE_ID, {}, _effort_from_job(job) or "fallback")
    overlay_id, overlay = _select_overlay(template_config, job) if template_config else ("fallback", {})
    human_template_id, human_template = _select_human_template(human_template_config, job) if human_template_config else ("", {})
    preferred_terms = _overlay_preferred_terms(overlay, blocked_terms)
    human_blocked_terms = _human_blocked_terms(human_template_id, human_template, job, blocked_terms) if human_template_id else blocked_terms
    selection_blocked_terms = human_blocked_terms if human_template_id else blocked_terms
    evidence = _selected_evidence(
        master,
        keywords,
        blocked_terms=selection_blocked_terms,
        preferred_terms=preferred_terms,
        non_core_skill_labels=non_core_skill_labels,
    )
    if human_template_id:
        human_terms = _human_evidence_terms(human_template_id, human_template, overlay, keywords, preferred_terms, human_blocked_terms)
        human_evidence = _selected_human_evidence(master, human_terms, human_blocked_terms)
        evidence = dict(evidence)
        evidence["projects_or_experience"] = human_evidence
    canonical_job_id = str(job.get("canonical_job_id") or job.get("job_id") or slugify(job.get("company"), 40))
    score_part = str(job.get("score") or "").strip()
    path_title = f"{job.get('title')}_{score_part}" if score_part else str(job.get("title") or "")
    workspace: ApplicationWorkspace | None = None
    if output_dir is None:
        workspace = ApplicationWorkspace.from_job(job, paths=registry, date=workspace_date)
        write_workspace_source_files(workspace, job)
        paths = {
            "directory": workspace.root,
            "markdown": workspace.cover_letter_review_md_path(),
            "json": workspace.cover_letter_source_json_path(),
            "docx": workspace.cover_letter_docx_path(),
            "pdf": workspace.cover_letter_pdf_path(),
            "formal_docx": workspace.cover_letter_docx_path(),
            "formal_pdf": workspace.cover_letter_pdf_path(),
            "body_txt": workspace.cover_letter_body_txt_path(),
            "workspace": workspace.root,
            "manifest": workspace.manifest_path,
        }
    else:
        paths = cover_letter_paths(canonical_job_id, str(job.get("company") or ""), path_title, output_dir)
    active_template_id = f"human:{human_template_id}" if human_template_id else template_id
    payload: dict[str, Any] = {
        "metadata": {
            "canonical_job_id": canonical_job_id,
            "company": job.get("company", ""),
            "title": job.get("title", ""),
            "country": job.get("country", ""),
            "role_category": job.get("role_category", ""),
            "apply_url": job.get("application_apply_url") or job.get("apply_url") or job.get("job_url") or "",
            "generated_resume_file": generated_resume_file
            or job.get("resume_used")
            or job.get("tailored_resume_path")
            or job.get("profile_resume_path")
            or job.get("scheduler_resume_draft_path")
            or job.get("resume_file_generated")
            or "",
            "created_at": now_utc_iso(),
        },
        "cover_letter_markdown": "",
        "cover_letter_body": "",
        "short_intro": "",
        "selected_evidence": evidence,
        "top_keywords_to_reflect": keywords[:6],
        "missing_keywords_not_claimed": missing,
        "unsupported_keywords_not_claimed": missing,
        "non_core_skill_labels": sorted(non_core_skill_labels),
        "manual_review_required": False if human_template_id else True,
        "template_id": active_template_id,
        "human_template_id": human_template_id,
        "overlay_id": overlay_id,
        "effort_used": effort_used,
        "prohibited_claims_checked": True,
        "manual_review_reason": "",
        "generation_status": "generated" if human_template_id else "manual_review_required",
        "formal_generation_skipped": False,
        "todo": [] if human_template_id else (_template_todos(template_config) if template_config else [
            "Review and replace the company-specific reason TODO with a fact supported by the posting or remove it.",
            "Review every factual claim against the master resume and job description before use.",
            "Do not add private personal details, financial details, or unsupported eligibility claims.",
        ]),
        "paths": {key: str(value) for key, value in paths.items()},
    }
    if human_template_id:
        evidence_points = [item for item in (payload.get("selected_evidence") or {}).get("projects_or_experience") or [] if isinstance(item, dict)]
        if not evidence_points:
            _mark_human_insufficient_evidence(payload)
        else:
            human_values = _human_template_values(job, human_template, evidence_points)
            payload["cover_letter_body"] = _render_human_template_body(template=human_template, values=human_values, master=master)
            payload["cover_letter_markdown"] = payload["cover_letter_body"]
            payload["short_intro"] = ""
            payload["manual_review_required"] = False
            payload["manual_review_reason"] = ""
            payload["generation_status"] = "generated"
            payload["formal_generation_skipped"] = False
    elif selected_template:
        template_values = _template_values(
            master=master,
            job=job,
            payload=payload,
            config=template_config,
            overlay=overlay,
            blocked_terms=blocked_terms,
            non_core_skill_labels=non_core_skill_labels,
        )
        payload["cover_letter_body"] = _render_template_body(config=template_config, template=selected_template, values=template_values)
        payload["cover_letter_markdown"] = _render_template_markdown(
            payload=payload,
            master=master,
            config=template_config,
            template=selected_template,
            values=template_values,
        )
        payload["short_intro"] = _render_short_intro(template_config, effort_used, template_values)
    else:
        payload["cover_letter_body"] = _render_cover_letter_body(payload, master)
        payload["cover_letter_markdown"] = _render_cover_letter_markdown(payload, master)
    target_dir = paths["directory"]
    target_dir.mkdir(parents=True, exist_ok=True)

    docx_created = False
    pdf_renderer = ""
    formal_body = payload["cover_letter_body"]
    if workspace is not None:
        paths["body_txt"].write_text(formal_body, encoding="utf-8")
        review_markdown = _render_review_markdown(
            _clean_text(job.get("company")) or "the company",
            _clean_text(job.get("title")) or "this role",
            formal_body,
        )
        paths["markdown"].write_text(review_markdown, encoding="utf-8")
    else:
        paths["markdown"].write_text(payload["cover_letter_markdown"], encoding="utf-8")

    skip_formal_generation = bool(payload.get("formal_generation_skipped")) or not formal_body.strip()
    if not skip_formal_generation and make_docx:
        docx_created = write_docx_from_markdown(formal_body, paths["formal_docx"])
    if not skip_formal_generation and make_pdf and docx_created:
        pdf_renderer = write_pdf_from_docx(paths["formal_docx"], paths["formal_pdf"], fallback_markdown=formal_body)
    elif not skip_formal_generation and make_pdf and write_pdf_from_markdown(formal_body, paths["formal_pdf"]):
        pdf_renderer = "markdown_fallback"
    payload["renderers"] = {
        "docx": "python-docx" if docx_created else "",
        "pdf": pdf_renderer,
    }
    payload_paths = {
        "markdown": str(paths["markdown"]),
        "review_markdown": str(paths["markdown"]),
        "json": str(paths["json"]),
        "source_json": str(paths["json"]),
        "docx": str(paths["formal_docx"]) if not skip_formal_generation and paths["formal_docx"].exists() else "",
        "pdf": str(paths["formal_pdf"]) if not skip_formal_generation and paths["formal_pdf"].exists() else "",
        "formal_docx": str(paths["formal_docx"]) if not skip_formal_generation and paths["formal_docx"].exists() else "",
        "formal_pdf": str(paths["formal_pdf"]) if not skip_formal_generation and paths["formal_pdf"].exists() else "",
        "directory": str(paths["directory"]),
    }
    if workspace is not None:
        payload_paths["body_txt"] = str(paths["body_txt"])
        payload_paths["workspace"] = str(paths["workspace"])
        payload_paths["manifest"] = str(paths["manifest"])
        payload["manifest"] = workspace.write_manifest({"manual_review_required": bool(payload.get("manual_review_required"))})
    payload["paths"] = payload_paths
    write_json(paths["json"], payload)
    return payload


def _read_cover_letter(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def load_cover_letter(canonical_job_id: str, output_dir: Path | None = None) -> dict[str, Any] | None:
    if output_dir is None:
        generated_dir = PathRegistry.from_project_root().generated_dir
        if generated_dir.exists():
            matches = sorted(
                generated_dir.rglob("source/cover_letter_source.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in matches:
                payload = _read_cover_letter(path)
                meta = payload.get("metadata") if isinstance(payload, dict) else {}
                if str((meta or {}).get("canonical_job_id") or "") == str(canonical_job_id):
                    payload.setdefault("paths", {})
                    payload["paths"].setdefault("json", str(path))
                    payload["paths"].setdefault("source_json", str(path))
                    payload["paths"].setdefault("review_markdown", str(path.parents[1] / "review" / "cover_letter_review.md"))
                    payload["paths"].setdefault("body_txt", str(path.parents[1] / "cover_letter_body.txt"))
                    return payload
        output_dir = COVER_LETTER_DIR
    if not output_dir.exists():
        return None
    matches: list[tuple[float, dict[str, Any]]] = []
    for path in output_dir.rglob("cover_letter.json"):
        payload = _read_cover_letter(path)
        meta = payload.get("metadata") if isinstance(payload, dict) else {}
        if str((meta or {}).get("canonical_job_id") or "") != str(canonical_job_id):
            continue
        payload.setdefault("paths", {})
        payload["paths"].setdefault("json", str(path))
        payload["paths"].setdefault("markdown", str(path.with_suffix(".md")))
        matches.append((path.stat().st_mtime, payload))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a local manual-review cover letter for one job.")
    parser.add_argument("--job-id", required=True, help="canonical_job_id from the SQLite jobs table")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-docx", action="store_true")
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args(argv)
    job = get_job_detail(args.job_id, args.db)
    if not job:
        raise SystemExit(f"Unknown canonical_job_id: {args.job_id}")
    payload = generate_cover_letter(
        job,
        generated_resume_file=str(job.get("resume_used") or job.get("tailored_resume_path") or job.get("profile_resume_path") or job.get("scheduler_resume_draft_path") or job.get("resume_file_generated") or ""),
        output_dir=args.out,
        make_docx=not args.no_docx,
        make_pdf=not args.no_pdf,
    )
    paths = payload.get("paths") or {}
    for key in ["workspace", "body_txt", "formal_pdf", "formal_docx", "review_markdown", "source_json"]:
        print(f"{key}: {paths.get(key) or 'not created'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
