from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .config_loader import load_public_config
from .database import DEFAULT_DB, get_jobs, replace_campaign_items
from .score import score_band
from .utils import CONFIG_DIR, PROJECT_ROOT, REPORTS_DIR, TEMPLATES_DIR, list_to_cell, load_yaml, now_utc_iso, today_yyyymmdd, write_csv

APPLICATION_CAMPAIGN_CONFIG = CONFIG_DIR / "application_campaign.local.yaml"
RESUME_PROFILE_PATHS_CONFIG = CONFIG_DIR / "resume_profile_paths.local.yaml"

EFFORTS = ["deep_tailor", "standard_tailor", "quick_apply", "hold", "skip"]
ACTIONABLE_EFFORTS = ["deep_tailor", "standard_tailor", "quick_apply"]
EFFORT_PRIORITY = {effort: idx for idx, effort in enumerate(EFFORTS)}
FRESHNESS_PRIORITY = {"new_today": 0, "new_this_week": 1, "recent": 2, "unknown": 3, "old": 4}
COUNTRY_PRIORITY = {"Remote": 99}
DEFAULT_PROFILE = "general_data"

ROLE_CATEGORY_PROFILE = {
    "data": "general_data",
    "risk": "finance_operations",
    "trading_ops": "operations",
    "crypto_ops": "operations",
    "api": "technical_support",
    "capital_markets": "finance_operations",
}

SEVERE_RED_FLAGS = {
    "senior_title",
    "senior_or_lead_level",
    "high_years_required",
    "five_plus_years",
    "manager_title",
    "local_presence_required",
    "local_presence_required_without_sponsorship",
    "citizenship_only",
    "work_authorization_restricted",
    "sponsorship_not_available",
}

SKIP_RED_FLAGS = {
    "commission_or_unpaid",
    "commission_only",
    "unpaid_internship",
    "security_clearance",
    "phd_research_role",
}

SKIP_PATTERNS = [
    (re.compile(r"\bcommission[- ]only\b|\b100%\s+commission\b", re.I), "commission-only role"),
    (re.compile(r"\bunpaid\b|\bvolunteer internship\b", re.I), "unpaid role"),
    (re.compile(r"\b(active|government|secret|top secret)?\s*security clearance\b", re.I), "security clearance required"),
    (re.compile(r"\b(requires?|required|must have)\b.{0,80}\b(ph\.?d|doctorate)\b|\b(ph\.?d|doctorate)\b.{0,80}\b(requires?|required|must have)\b", re.I), "PhD required"),
    (re.compile(r"\b(sales development representative|business development representative|account executive|cold calling)\b", re.I), "pure sales role"),
]

PENALTY_REASON_LABELS = {
    "senior_title": "senior title",
    "senior_or_lead_level": "senior/lead level",
    "manager_title": "manager/director title",
    "three_plus_years": "3+ years requirement",
    "five_plus_years": "5+ years requirement",
    "high_years_required": "high-years requirement",
    "local_presence_required": "local presence required",
    "local_presence_required_without_sponsorship": "local presence without sponsorship",
    "citizenship_only": "citizenship-only wording",
    "work_authorization_restricted": "work authorization restriction",
    "sponsorship_not_available": "no sponsorship",
    "masters_required": "master's required",
    "masters_preferred": "master's preferred",
    "cpp_required": "C++ required",
    "low_latency_cpp": "low-latency C++",
    "pure_quant_track": "pure quant track",
    "no_description": "missing description",
}

SHORT_EFFORT_LABELS = {
    "deep_tailor": "deep",
    "standard_tailor": "standard",
    "quick_apply": "quick",
    "hold": "hold",
    "skip": "skip",
}

SHORT_REASON_LABELS = {
    "senior_title": "senior",
    "senior_or_lead_level": "senior/lead/staff",
    "manager_title": "manager",
    "three_plus_years": "3+ yrs",
    "five_plus_years": "5+ yrs",
    "high_years_required": "high yrs",
    "local_presence_required": "local required",
    "local_presence_required_without_sponsorship": "local/no sponsorship",
    "citizenship_only": "citizenship",
    "work_authorization_restricted": "work auth",
    "sponsorship_not_available": "no sponsorship",
    "masters_required": "master req",
    "masters_preferred": "master pref",
    "cpp_required": "C++",
    "low_latency_cpp": "low-latency C++",
    "pure_quant_track": "pure quant",
    "no_description": "no desc",
}

SEVERE_KEYWORD_REASON_LABELS = {"lead", "senior", "staff", "principal"}
SENIOR_KEYWORD_RED_FLAGS = {"senior_title", "senior_or_lead_level"}
BASE_RED_FLAG_PENALTIES = {
    "senior_or_lead_level": 30,
    "high_years_required": 25,
    "phd_required": 30,
    "work_authorization_restricted": 40,
    "low_latency_cpp": 25,
    "commission_or_unpaid": 30,
    "no_description": 3,
    "local_presence_required_without_sponsorship": 20,
    "pure_quant_track": 20,
}

CAMPAIGN_FIELDS = [
    "campaign_date",
    "campaign_priority",
    "application_effort",
    "campaign_status",
    "score",
    "score_band",
    "title",
    "company",
    "country",
    "location",
    "freshness_label",
    "resume_profile",
    "estimated_minutes",
    "auto_generate_resume",
    "allow_manual_generate_resume",
    "auto_generate_answer_pack",
    "allow_manual_generate_answer_pack",
    "should_generate_resume",
    "should_generate_answer_pack",
    "profile_resume_path",
    "tailored_resume_path",
    "answer_pack_path",
    "apply_url",
    "job_url",
    "campaign_reason",
    "red_flags",
    "matched_keywords",
    "canonical_job_id",
]

DEFAULT_CONFIG = {
    "campaign": {
        "daily_targets": {"deep_tailor": 5, "standard_tailor": 12, "quick_apply": 25, "hold": 0},
        "estimated_minutes": {"deep_tailor": 25, "standard_tailor": 10, "quick_apply": 4, "hold": 0, "skip": 0},
        "score_thresholds": {"deep_tailor": 70, "standard_tailor": 55, "quick_apply": 35, "hold": 25},
        "company_priority": {"tier_1": [], "crypto_fintech_priority": []},
        "max_per_company_per_day": 3,
        "max_same_title_per_day": 5,
        "exclude_if_already_applied": True,
        "exclude_if_status": ["applied", "interview", "rejected", "skipped", "archived"],
        "auto_generate_resume": {"deep_tailor": False, "standard_tailor": False, "quick_apply": False, "hold": False, "skip": False},
        "allow_manual_generate_resume": {"deep_tailor": True, "standard_tailor": True, "quick_apply": False, "hold": False, "skip": False},
        "auto_generate_answer_pack": {"deep_tailor": False, "standard_tailor": False, "quick_apply": False, "hold": False, "skip": False},
        "allow_manual_generate_answer_pack": {"deep_tailor": True, "standard_tailor": True, "quick_apply": False, "hold": False, "skip": False},
        "quick_apply_requires_existing_profile_resume": True,
    },
    "resume_profiles": {
        "general_data": {"keywords": ["data analyst", "reporting", "sql", "python", "spreadsheet"]},
        "business_operations": {"keywords": ["business operations", "process", "workflow", "stakeholder"]},
        "sales_operations": {"keywords": ["sales operations", "crm", "pipeline", "revenue operations"]},
        "technical_support": {"keywords": ["technical support", "api", "troubleshooting", "customer support"]},
        "finance_operations": {"keywords": ["finance operations", "risk", "reconciliation", "reporting"]},
        "operations": {"keywords": ["operations", "coordination", "process improvement", "reconciliation"]},
    },
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_campaign_config(path: Path = APPLICATION_CAMPAIGN_CONFIG) -> dict[str, Any]:
    if path == APPLICATION_CAMPAIGN_CONFIG:
        data = load_public_config("application_campaign") or {}
        return _deep_merge(DEFAULT_CONFIG, data if isinstance(data, dict) else {})
    if not path.exists():
        return DEFAULT_CONFIG
    data = load_yaml(path) or {}
    return _deep_merge(DEFAULT_CONFIG, data if isinstance(data, dict) else {})


def load_resume_profile_paths(path: Path = RESUME_PROFILE_PATHS_CONFIG) -> dict[str, Any]:
    if path == RESUME_PROFILE_PATHS_CONFIG:
        data = load_public_config("resume_profile_paths") or {}
        return data if isinstance(data, dict) else {"profiles": {}}
    if not path.exists():
        return {"profiles": {}}
    data = load_yaml(path) or {}
    return data if isinstance(data, dict) else {"profiles": {}}


def _campaign_settings(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("campaign") if isinstance(config.get("campaign"), dict) else {}


def _score(job: dict[str, Any]) -> int:
    try:
        return int(job.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                import json

                parsed = json.loads(text)
                return parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                pass
        return [part.strip() for part in re.split(r";|,", text) if part.strip()]
    return [value]


def _job_text(job: dict[str, Any]) -> str:
    parts = [
        job.get("title"),
        job.get("company"),
        job.get("location"),
        job.get("country"),
        job.get("role_category"),
        job.get("description"),
        " ".join(str(item) for item in _as_list(job.get("matched_keywords"))),
        " ".join(str(item) for item in _as_list(job.get("red_flags"))),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _red_flags(job: dict[str, Any]) -> set[str]:
    return {str(flag).strip().lower() for flag in _as_list(job.get("red_flags")) if str(flag).strip()}


def _hard_skip(job: dict[str, Any]) -> bool:
    return bool(job.get("hard_skip")) or str(job.get("recommendation") or "").strip().lower() == "hard skip"


def _has_skip_disqualifier(job: dict[str, Any]) -> tuple[bool, str]:
    flags = _red_flags(job)
    matched_flags = sorted(flags & SKIP_RED_FLAGS)
    if matched_flags:
        return True, ", ".join(matched_flags)
    text = _job_text(job)
    for pattern, reason in SKIP_PATTERNS:
        if pattern.search(text):
            return True, reason
    return False, ""


def _soft_penalty_lookup(job: dict[str, Any]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for item in _as_list(job.get("soft_penalties")):
        if not isinstance(item, dict):
            continue
        rule = str(item.get("rule") or "").strip().lower()
        if not rule:
            continue
        try:
            penalty = int(item.get("applied_penalty", item.get("penalty") or 0) or 0)
        except (TypeError, ValueError):
            penalty = 0
        if penalty:
            lookup[rule] = penalty
    return lookup


def _penalty_label(rule_id: str) -> str:
    return PENALTY_REASON_LABELS.get(rule_id, rule_id.replace("_", " "))


def _flag_reason(flag: str, penalties: dict[str, int]) -> str:
    penalty = penalties.get(flag)
    label = _penalty_label(flag)
    return f"{label} -{penalty}" if penalty else label


def _short_effort_label(effort: str) -> str:
    return SHORT_EFFORT_LABELS.get(effort, effort.replace("_tailor", "").replace("_apply", ""))


def _short_reason_label(rule_id: str) -> str:
    return SHORT_REASON_LABELS.get(rule_id, _penalty_label(rule_id))


def _short_flag_reason(flag: str, penalties: dict[str, int]) -> str:
    penalty = penalties.get(flag)
    if penalty is None:
        penalty = BASE_RED_FLAG_PENALTIES.get(flag)
    label = _short_reason_label(flag)
    return f"{label} -{abs(penalty)}" if penalty else label


def _short_keyword_reason(keyword: str) -> str:
    normalized = keyword.lower().rstrip(".")
    return "senior" if normalized == "sr" else normalized


def _unique_reasons(reasons: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for reason in reasons:
        text = str(reason or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _short_free_text_reason(reason: Any) -> str:
    text = str(reason or "").strip().rstrip(".")
    if not text:
        return "hard skip"
    lower = text.lower()
    if "life sciences" in lower or "biotech" in lower:
        return "life sci mismatch"
    return text


def _compact_reason_groups(reasons: list[str]) -> list[str]:
    unique = _unique_reasons(reasons)
    keyword_items: list[tuple[str, str]] = []
    for reason in unique:
        match = re.fullmatch(r"(lead|senior|staff|principal)( -\d+)?", reason)
        if match:
            keyword_items.append((match.group(1), match.group(2) or ""))
    if len(keyword_items) < 2:
        return unique

    suffixes = {suffix for _, suffix in keyword_items}
    grouped_suffix = next(iter(suffixes)) if len(suffixes) == 1 else ""
    grouped_keywords = "/".join(keyword for keyword, _ in keyword_items) + grouped_suffix
    compacted: list[str] = []
    inserted = False
    for reason in unique:
        if re.fullmatch(r"(lead|senior|staff|principal)( -\d+)?", reason):
            if not inserted:
                compacted.append(grouped_keywords)
                inserted = True
            continue
        compacted.append(reason)
    return compacted


def _format_campaign_reason(score: int, effort: str, reasons: list[str]) -> str:
    reason_text = "; ".join(_compact_reason_groups(reasons))
    base = f"{score} -> {_short_effort_label(effort)}"
    return f"{base}: {reason_text}" if reason_text else base


def _campaign_penalty_reasons(job: dict[str, Any]) -> list[str]:
    penalties = _soft_penalty_lookup(job)
    red_flags = _red_flags(job)
    reasons = []
    for rule in sorted(penalties):
        if rule in SENIOR_KEYWORD_RED_FLAGS:
            continue
        if rule == "five_plus_years" and "high_years_required" in red_flags:
            continue
        reasons.append(_short_flag_reason(rule, penalties))
    for flag in sorted(red_flags):
        if flag in penalties or flag in SENIOR_KEYWORD_RED_FLAGS:
            continue
        if flag == "five_plus_years" and "high_years_required" in red_flags:
            continue
        reasons.append(_short_flag_reason(flag, penalties))
    return _unique_reasons(reasons)


def _severe_red_flag_reasons(job: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    penalties = _soft_penalty_lookup(job)
    red_flags = _red_flags(job)
    for flag in sorted((red_flags & SEVERE_RED_FLAGS) - SENIOR_KEYWORD_RED_FLAGS):
        if flag == "five_plus_years" and "high_years_required" in red_flags:
            continue
        reasons.append(_short_flag_reason(flag, penalties))

    keyword_penalty = BASE_RED_FLAG_PENALTIES["senior_or_lead_level"] if "senior_or_lead_level" in red_flags else penalties.get("senior_title")
    title_text = str(job.get("title") or "")
    for match in re.finditer(r"\b(senior|sr\.?|staff|principal|lead)\b", title_text, flags=re.I):
        label = _short_keyword_reason(match.group(0))
        reason = f"{label} -{keyword_penalty}" if keyword_penalty else label
        if reason not in reasons:
            reasons.append(reason)

    text = _job_text(job)
    for match in re.finditer(r"\b(senior|sr\.?|staff|principal|lead)\b", text, flags=re.I):
        label = _short_keyword_reason(match.group(0))
        reason = f"{label} -{keyword_penalty}" if keyword_penalty else label
        if reason not in reasons:
            reasons.append(reason)
    for pattern, label in [
        (r"\b(citizenship required|citizens only|must be a citizen)\b", "citizenship"),
        (r"\b(must already be based|currently based)\b.{0,100}\b(singapore|hong kong)\b", "local required"),
    ]:
        match = re.search(pattern, text, flags=re.I)
        if match:
            reasons.append(label)
    return _unique_reasons(reasons)


def _has_severe_red_flag(job: dict[str, Any]) -> bool:
    return bool(_severe_red_flag_reasons(job))


def _norm_company(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _priority_companies(config: dict[str, Any]) -> list[str]:
    priority = _campaign_settings(config).get("company_priority") or {}
    names: list[str] = []
    if isinstance(priority, dict):
        for values in priority.values():
            names.extend(str(value) for value in _as_list(values))
    return [name for name in names if name.strip()]


def is_priority_company(company: Any, config: dict[str, Any] | None = None) -> bool:
    config = config or load_campaign_config()
    company_norm = _norm_company(company)
    if not company_norm:
        return False
    company_tokens = set(company_norm.split())
    for name in _priority_companies(config):
        target = _norm_company(name)
        if not target:
            continue
        if len(target) <= 3:
            if target in company_tokens:
                return True
            continue
        if target in company_norm or company_norm in target:
            return True
    return False


def classify_application_effort(job: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    return classify_campaign_job(job, config)["application_effort"]


def classify_campaign_job(job: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_campaign_config()
    campaign = _campaign_settings(config)
    thresholds = campaign.get("score_thresholds") or {}
    score = _score(job)
    if _hard_skip(job):
        reason = _short_free_text_reason(job.get("filter_reason") or "hard skip")
        return {"application_effort": "skip", "campaign_reason": _format_campaign_reason(score, "skip", [reason])}
    disqualified, disqualifier = _has_skip_disqualifier(job)
    if disqualified:
        return {"application_effort": "skip", "campaign_reason": _format_campaign_reason(score, "skip", [disqualifier])}
    if score >= int(thresholds.get("deep_tailor") or 70):
        effort = "deep_tailor"
    elif score >= int(thresholds.get("standard_tailor") or 55):
        effort = "standard_tailor"
    elif score >= int(thresholds.get("quick_apply") or 35):
        effort = "quick_apply"
    elif score >= int(thresholds.get("hold") or 25):
        effort = "hold"
    else:
        effort = "skip"

    reasons = list(_campaign_penalty_reasons(job))
    severe_reasons = _severe_red_flag_reasons(job)
    reasons.extend(severe_reasons)
    if effort == "deep_tailor" and severe_reasons:
        effort = "standard_tailor"
    if effort == "standard_tailor" and is_priority_company(job.get("company") or job.get("canonical_company"), config):
        if severe_reasons:
            reasons.append("priority blocked")
        else:
            effort = "deep_tailor"
            reasons.append("priority")
    return {"application_effort": effort, "campaign_reason": _format_campaign_reason(score, effort, reasons)}


def choose_resume_profile(job: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    config = config or load_campaign_config()
    role_category = str(job.get("role_category") or "").strip().lower()
    if role_category in ROLE_CATEGORY_PROFILE:
        return ROLE_CATEGORY_PROFILE[role_category]

    profiles = config.get("resume_profiles") or {}
    text = _job_text(job)
    best_profile = DEFAULT_PROFILE
    best_score = 0
    for profile, payload in profiles.items():
        keywords = _as_list((payload or {}).get("keywords") if isinstance(payload, dict) else [])
        matched = sum(1 for keyword in keywords if str(keyword).lower() in text)
        if matched > best_score:
            best_profile = str(profile)
            best_score = matched
    return best_profile


def _configured_profile_paths(resume_profile: str, profile_paths: dict[str, Any]) -> dict[str, str]:
    profiles = profile_paths.get("profiles") if isinstance(profile_paths.get("profiles"), dict) else {}
    payload = profiles.get(resume_profile) if isinstance(profiles, dict) else {}
    return {key: str(value or "") for key, value in (payload or {}).items()} if isinstance(payload, dict) else {}


def _resolve_project_path(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else PROJECT_ROOT / path


def profile_resume_path(resume_profile: str, profile_paths: dict[str, Any] | None = None) -> str:
    profile_paths = profile_paths or load_resume_profile_paths()
    configured = _configured_profile_paths(resume_profile, profile_paths)
    for key in ["pdf", "docx"]:
        value = configured.get(key, "")
        if value and _resolve_project_path(value).exists():
            return value
    return configured.get("pdf") or configured.get("docx") or ""


def profile_resume_exists(path_text: str) -> bool:
    return bool(path_text and _resolve_project_path(path_text).exists())


def profile_resume_source_path(resume_profile: str, profile_paths: dict[str, Any] | None = None) -> str:
    profile_paths = profile_paths or load_resume_profile_paths()
    configured = _configured_profile_paths(resume_profile, profile_paths)
    value = configured.get("source") or configured.get("yaml")
    if not value and resume_profile:
        local_source = TEMPLATES_DIR / "resume_profiles" / f"{resume_profile}.local.yaml"
        example_source = TEMPLATES_DIR / "resume_profiles" / f"{resume_profile}.example.yaml"
        value = str(local_source if local_source.exists() else example_source)
    if not value:
        return ""
    resolved = Path(value)
    return str(resolved if resolved.is_absolute() else PROJECT_ROOT / resolved)


def profile_resume_source_exists(resume_profile: str, profile_paths: dict[str, Any] | None = None) -> bool:
    source = profile_resume_source_path(resume_profile, profile_paths)
    return bool(source and Path(source).exists())


def _bool_setting(settings: dict[str, Any], key: str, effort: str, fallback_key: str | None = None) -> bool:
    values = settings.get(key) if isinstance(settings.get(key), dict) else {}
    if not values and fallback_key:
        values = settings.get(fallback_key) if isinstance(settings.get(fallback_key), dict) else {}
    return bool(values.get(effort)) if isinstance(values, dict) else False


def build_campaign_row(
    job: dict[str, Any],
    *,
    campaign_date: str,
    config: dict[str, Any] | None = None,
    profile_paths: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_campaign_config()
    profile_paths = profile_paths or load_resume_profile_paths()
    settings = _campaign_settings(config)
    effort_info = classify_campaign_job(job, config)
    effort = effort_info["application_effort"]
    resume_profile = choose_resume_profile(job, config)
    profile_path = profile_resume_path(resume_profile, profile_paths) if effort in {"deep_tailor", "standard_tailor", "quick_apply"} else ""
    estimated_minutes = int((settings.get("estimated_minutes") or {}).get(effort) or 0)
    score = _score(job)
    hard_skip = _hard_skip(job) or effort == "skip"
    status = "queued"
    if effort == "hold":
        status = "moved_to_hold"
    elif effort == "skip":
        status = "skipped"
    auto_generate_resume = _bool_setting(settings, "auto_generate_resume", effort, fallback_key="resume_generation")
    allow_manual_generate_resume = _bool_setting(settings, "allow_manual_generate_resume", effort, fallback_key="resume_generation")
    auto_generate_answer_pack = _bool_setting(settings, "auto_generate_answer_pack", effort, fallback_key="answer_pack_generation")
    allow_manual_generate_answer_pack = _bool_setting(settings, "allow_manual_generate_answer_pack", effort, fallback_key="answer_pack_generation")

    return {
        "campaign_date": campaign_date,
        "canonical_job_id": job.get("canonical_job_id") or job.get("job_id") or "",
        "application_effort": effort,
        "campaign_priority": 0,
        "campaign_reason": effort_info["campaign_reason"],
        "resume_profile": resume_profile,
        "profile_resume_path": profile_path,
        "tailored_resume_path": "",
        "answer_pack_path": "",
        "estimated_minutes": estimated_minutes,
        "auto_generate_resume": auto_generate_resume,
        "allow_manual_generate_resume": allow_manual_generate_resume,
        "auto_generate_answer_pack": auto_generate_answer_pack,
        "allow_manual_generate_answer_pack": allow_manual_generate_answer_pack,
        "should_generate_resume": auto_generate_resume,
        "should_generate_answer_pack": auto_generate_answer_pack,
        "campaign_status": status,
        "selected_at": now_utc_iso(),
        "completed_at": "",
        "notes": "",
        "score": score,
        "score_band": str(job.get("score_band") or score_band(score, hard_skip=hard_skip)),
        "recommendation": job.get("recommendation") or "",
        "title": job.get("title") or "",
        "company": job.get("company") or job.get("canonical_company") or "",
        "canonical_company": job.get("canonical_company") or job.get("company") or "",
        "country": job.get("country") or job.get("detected_country") or "",
        "location": job.get("location") or "",
        "remote_type": job.get("remote_type") or "",
        "role_category": job.get("role_category") or "",
        "seniority": job.get("seniority") or "",
        "job_url": job.get("job_url") or "",
        "apply_url": job.get("application_apply_url") or job.get("apply_url") or job.get("job_url") or "",
        "description": job.get("description") or "",
        "posted_at": job.get("posted_at") or job.get("date_posted") or "",
        "first_seen_at": job.get("first_seen_at") or "",
        "last_seen_at": job.get("last_seen_at") or "",
        "freshness_label": job.get("freshness_label") or "unknown",
        "is_new_since_last_run": job.get("is_new_since_last_run") or 0,
        "matched_keywords": _as_list(job.get("matched_keywords")),
        "missing_keywords": _as_list(job.get("missing_keywords")),
        "red_flags": sorted(_red_flags(job)),
        "hard_skip": hard_skip,
        "reason_to_apply": job.get("reason_to_apply") or "",
        "scheduler_resume_draft_path": job.get("scheduler_resume_draft_path") or job.get("resume_file_generated") or "",
        "resume_file_generated": job.get("resume_file_generated") or "",
        "current_status": job.get("status") or "new",
    }


def campaign_sort_key(row: dict[str, Any], config: dict[str, Any] | None = None) -> tuple[Any, ...]:
    config = config or load_campaign_config()
    return (
        EFFORT_PRIORITY.get(str(row.get("application_effort") or ""), 99),
        -int(row.get("score") or 0),
        FRESHNESS_PRIORITY.get(str(row.get("freshness_label") or "unknown"), 9),
        0 if is_priority_company(row.get("company"), config) else 1,
        COUNTRY_PRIORITY.get(str(row.get("country") or ""), 9),
        len(_as_list(row.get("red_flags"))),
        str(row.get("company") or ""),
        str(row.get("title") or ""),
    )


def _same_title_key(row: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(row.get("title") or "").lower()).strip()


def _company_key(row: dict[str, Any]) -> str:
    return _norm_company(row.get("canonical_company") or row.get("company"))


def _country_allowed(job: dict[str, Any], countries: list[str] | None) -> bool:
    if not countries:
        return True
    country = str(job.get("country") or job.get("detected_country") or "")
    return country in set(countries)


def build_daily_campaign(
    jobs: list[dict[str, Any]],
    *,
    campaign_date: str | None = None,
    config: dict[str, Any] | None = None,
    profile_paths: dict[str, Any] | None = None,
    countries: list[str] | None = None,
    deep: int | None = None,
    standard: int | None = None,
    quick: int | None = None,
) -> dict[str, Any]:
    config = config or load_campaign_config()
    profile_paths = profile_paths or load_resume_profile_paths()
    campaign_date = campaign_date or today_yyyymmdd()
    settings = _campaign_settings(config)
    targets = dict(settings.get("daily_targets") or {})
    if deep is not None:
        targets["deep_tailor"] = deep
    if standard is not None:
        targets["standard_tailor"] = standard
    if quick is not None:
        targets["quick_apply"] = quick
    excluded_statuses = {str(status).lower() for status in _as_list(settings.get("exclude_if_status"))}
    exclude_already = bool(settings.get("exclude_if_already_applied", True))

    candidates: list[dict[str, Any]] = []
    already_applied: list[dict[str, Any]] = []
    for job in jobs:
        if int(job.get("is_active", 1) or 0) != 1:
            continue
        if not _country_allowed(job, countries):
            continue
        current_status = str(job.get("status") or "new").lower()
        row = build_campaign_row(job, campaign_date=campaign_date, config=config, profile_paths=profile_paths)
        if exclude_already and current_status in excluded_statuses:
            row["campaign_status"] = current_status
            already_applied.append(row)
            continue
        candidates.append(row)

    candidates.sort(key=lambda row: campaign_sort_key(row, config))
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    selected_by_effort = Counter()
    selected_by_company = Counter()
    selected_by_title = Counter()
    max_per_company = int(settings.get("max_per_company_per_day") or 3)
    max_same_title = int(settings.get("max_same_title_per_day") or 5)

    for effort in ACTIONABLE_EFFORTS:
        effort_target = int(targets.get(effort) or 0)
        for row in [candidate for candidate in candidates if candidate["application_effort"] == effort]:
            if selected_by_effort[effort] >= effort_target:
                row["campaign_status"] = "deferred"
                deferred.append(row)
                continue
            company_key = _company_key(row)
            title_key = _same_title_key(row)
            if company_key and selected_by_company[company_key] >= max_per_company:
                row["campaign_status"] = "deferred"
                deferred.append(row)
                continue
            if title_key and selected_by_title[title_key] >= max_same_title:
                row["campaign_status"] = "deferred"
                deferred.append(row)
                continue
            selected.append(row)
            selected_by_effort[effort] += 1
            if company_key:
                selected_by_company[company_key] += 1
            if title_key:
                selected_by_title[title_key] += 1

    hold_rows = [row for row in candidates if row["application_effort"] == "hold"]
    skip_rows = [row for row in candidates if row["application_effort"] == "skip"]
    today_campaign = selected + hold_rows + skip_rows
    for priority, row in enumerate(today_campaign, start=1):
        row["campaign_priority"] = priority
    for priority, row in enumerate(already_applied, start=1):
        row["campaign_priority"] = priority
    for priority, row in enumerate(deferred, start=1):
        row["campaign_priority"] = priority
    return {
        "campaign_date": campaign_date,
        "today_campaign": today_campaign,
        "selected": selected,
        "hold": hold_rows,
        "skip": skip_rows,
        "already_applied": already_applied,
        "deferred": deferred,
        "summary": summarize_campaign(today_campaign, already_applied=already_applied, deferred=deferred),
    }


def summarize_campaign(
    rows: list[dict[str, Any]],
    *,
    already_applied: list[dict[str, Any]] | None = None,
    deferred: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    counts = Counter(str(row.get("application_effort") or "") for row in rows)
    queued_rows = [row for row in rows if row.get("campaign_status") == "queued"]
    return {
        "total_items": len(rows),
        "deep_tailor": counts.get("deep_tailor", 0),
        "standard_tailor": counts.get("standard_tailor", 0),
        "quick_apply": counts.get("quick_apply", 0),
        "hold": counts.get("hold", 0),
        "skip": counts.get("skip", 0),
        "estimated_total_minutes": sum(int(row.get("estimated_minutes") or 0) for row in queued_rows),
        "already_applied_excluded": len(already_applied or []),
        "deferred": len(deferred or []),
    }


def _export_row(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["matched_keywords"] = list_to_cell(row.get("matched_keywords"))
    output["missing_keywords"] = list_to_cell(row.get("missing_keywords"))
    output["red_flags"] = list_to_cell(row.get("red_flags"))
    for flag in ["auto_generate_resume", "allow_manual_generate_resume", "auto_generate_answer_pack", "allow_manual_generate_answer_pack", "should_generate_resume", "should_generate_answer_pack"]:
        output[flag] = int(bool(row.get(flag)))
    return output


def _format_sheet(worksheet: Any, rows: list[dict[str, Any]], fields: list[str]) -> None:
    worksheet.freeze_panes = "A2"
    for idx, column in enumerate(fields, start=1):
        values = [len(str(column))] + [len(str(row.get(column, ""))) for row in rows[:200]]
        worksheet.column_dimensions[worksheet.cell(row=1, column=idx).column_letter].width = min(max(values) + 2, 60)


def _aggregate(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        bucket = grouped.setdefault(key, {field: key, "count": 0, "estimated_minutes": 0, "avg_score": 0})
        bucket["count"] += 1
        bucket["estimated_minutes"] += int(row.get("estimated_minutes") or 0)
        bucket["avg_score"] += int(row.get("score") or 0)
    for bucket in grouped.values():
        bucket["avg_score"] = round(bucket["avg_score"] / max(1, bucket["count"]), 1)
    return sorted(grouped.values(), key=lambda item: (-int(item["count"]), str(item.get(field) or "")))


def write_campaign_excel(path: Path, result: dict[str, Any]) -> bool:
    try:
        import pandas as pd  # type: ignore
    except ModuleNotFoundError:
        return False
    rows = [_export_row(row) for row in result["today_campaign"]]
    already = [_export_row(row) for row in result["already_applied"]]
    sheets = [
        ("Today Campaign", rows, CAMPAIGN_FIELDS),
        ("Deep Tailor", [row for row in rows if row["application_effort"] == "deep_tailor"], CAMPAIGN_FIELDS),
        ("Standard Tailor", [row for row in rows if row["application_effort"] == "standard_tailor"], CAMPAIGN_FIELDS),
        ("Quick Apply", [row for row in rows if row["application_effort"] == "quick_apply"], CAMPAIGN_FIELDS),
        ("Hold", [row for row in rows if row["application_effort"] == "hold"], CAMPAIGN_FIELDS),
        ("Skip", [row for row in rows if row["application_effort"] == "skip"], CAMPAIGN_FIELDS),
        ("Already Applied", already, CAMPAIGN_FIELDS),
        ("By Resume Profile", _aggregate(rows, "resume_profile"), None),
        ("By Country", _aggregate(rows, "country"), None),
        ("By Company", _aggregate(rows, "company"), None),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, sheet_rows, fields in sheets:
            data = pd.DataFrame(sheet_rows, columns=fields) if fields else pd.DataFrame(sheet_rows)
            data.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            _format_sheet(writer.sheets[sheet_name[:31]], sheet_rows, list(data.columns))
    return True


def write_campaign_markdown(path: Path, result: dict[str, Any]) -> None:
    rows = result["today_campaign"]
    summary = result["summary"]
    lines = [f"# Application Campaign - {result['campaign_date']}", ""]
    lines.append("## Summary")
    for key in ["deep_tailor", "standard_tailor", "quick_apply", "hold", "skip", "estimated_total_minutes", "already_applied_excluded", "deferred"]:
        lines.append(f"- {key}: {summary.get(key, 0)}")
    lines.append("")
    for effort, title in [
        ("deep_tailor", "Deep Tailor"),
        ("standard_tailor", "Standard Tailor"),
        ("quick_apply", "Quick Apply"),
        ("hold", "Hold"),
        ("skip", "Skip"),
    ]:
        lines.append(f"## {title}")
        effort_rows = [row for row in rows if row.get("application_effort") == effort]
        if not effort_rows:
            lines.append("No items.")
            lines.append("")
            continue
        for row in effort_rows:
            lines.append(f"- [{row.get('score')}] {row.get('company')} - {row.get('title')} ({row.get('country')})")
            lines.append(f"  - Resume profile: {row.get('resume_profile')} | Minutes: {row.get('estimated_minutes')}")
            lines.append(f"  - Reason: {row.get('campaign_reason')}")
            if row.get("apply_url"):
                lines.append(f"  - Apply URL: {row.get('apply_url')}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_campaign_reports(result: dict[str, Any], output_dir: Path = REPORTS_DIR) -> dict[str, str]:
    date_part = str(result["campaign_date"])
    rows = [_export_row(row) for row in result["today_campaign"]]
    csv_path = output_dir / f"application_campaign_{date_part}.csv"
    xlsx_path = output_dir / f"application_campaign_{date_part}.xlsx"
    md_path = output_dir / f"application_campaign_{date_part}.md"
    write_csv(csv_path, rows, CAMPAIGN_FIELDS)
    xlsx_created = write_campaign_excel(xlsx_path, result)
    write_campaign_markdown(md_path, result)
    return {"csv": str(csv_path), "xlsx": str(xlsx_path) if xlsx_created else "", "markdown": str(md_path)}


def format_summary(result: dict[str, Any], paths: dict[str, str] | None = None) -> str:
    summary = result["summary"]
    lines = [f"Application campaign {result['campaign_date']}"]
    for key in ["deep_tailor", "standard_tailor", "quick_apply", "hold", "skip"]:
        lines.append(f"- {key}: {summary.get(key, 0)}")
    lines.append(f"- estimated_total_minutes: {summary.get('estimated_total_minutes', 0)}")
    lines.append(f"- already_applied_excluded: {summary.get('already_applied_excluded', 0)}")
    lines.append(f"- deferred: {summary.get('deferred', 0)}")
    if paths:
        for key, value in paths.items():
            if value:
                lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _clean_date(value: str | None) -> str:
    if not value:
        return today_yyyymmdd()
    digits = re.sub(r"\D+", "", value)
    if len(digits) != 8:
        raise argparse.ArgumentTypeError("date must be YYYYMMDD or YYYY-MM-DD")
    return digits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an application campaign queue from SQLite.")
    parser.add_argument("--today", action="store_true", help="Use today's local date.")
    parser.add_argument("--date", default=None, help="Campaign date as YYYYMMDD.")
    parser.add_argument("--deep", type=int, default=None, help="Deep tailor quota.")
    parser.add_argument("--standard", type=int, default=None, help="Standard tailor quota.")
    parser.add_argument("--quick", type=int, default=None, help="Quick apply quota.")
    parser.add_argument("--country", action="append", default=None, help="Filter to a country. Repeat for multiple.")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing campaign rows or reports.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    campaign_date = _clean_date(None if args.today and not args.date else args.date)
    jobs = get_jobs(args.db, include_inactive=False)
    result = build_daily_campaign(
        jobs,
        campaign_date=campaign_date,
        countries=args.country,
        deep=args.deep,
        standard=args.standard,
        quick=args.quick,
    )
    paths: dict[str, str] = {}
    if not args.dry_run:
        replace_campaign_items(args.db, result["campaign_date"], result["today_campaign"])
        paths = write_campaign_reports(result)
    print(format_summary(result, paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
