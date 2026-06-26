from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .utils import CONFIG_DIR, load_yaml, normalize_text_escapes

FILTER_POLICY_PATH = CONFIG_DIR / "filter_policy.yaml"
OPS_ESCAPE_RE = re.compile(r"\b(data|operations|support|api|risk|market data|analyst)\b", re.I)
FINTECH_ESCAPE_RE = re.compile(r"\b(fintech|crypto|digital assets|analyst|operations|data|api)\b", re.I)
CORE_RULE_OVERLAPS = {
    "senior_title": {"senior_or_lead_level"},
    "five_plus_years": {"high_years_required"},
    "low_latency_cpp": {"low_latency_cpp"},
    "pure_quant_researcher_trader": {"pure_quant_track"},
}


def load_filter_policy(path: Path = FILTER_POLICY_PATH) -> dict[str, Any]:
    data = load_yaml(path) or {}
    return data if isinstance(data, dict) else {}


def _job_text(job: dict[str, Any]) -> str:
    fields = [
        job.get("title"),
        job.get("company"),
        job.get("location"),
        job.get("country"),
        job.get("description"),
    ]
    return normalize_text_escapes(" ".join(str(field or "") for field in fields)).lower()


def _red_flag_set(job: dict[str, Any]) -> set[str]:
    return {str(flag).strip() for flag in job.get("red_flags") or [] if str(flag).strip()}


def _soft_rule_already_counted(rule_id: str, job: dict[str, Any]) -> bool:
    overlaps = CORE_RULE_OVERLAPS.get(rule_id) or set()
    return bool(overlaps & _red_flag_set(job))


def _matches(pattern: Any, text: str) -> bool:
    if not pattern:
        return False
    return bool(re.search(str(pattern), text, flags=re.I))


def _skip_soft_rule(rule_id: str, text: str, job: dict[str, Any]) -> bool:
    country = str(job.get("detected_country") or job.get("country") or "").lower()
    if rule_id == "sponsorship_not_available" and "canada" in country:
        if "pgwp" in text or "open work permit" in text or "open work authorization" in text:
            return True
    if rule_id == "pure_sales_bd" and FINTECH_ESCAPE_RE.search(text):
        return True
    if rule_id == "pure_quant_researcher_trader" and OPS_ESCAPE_RE.search(text):
        return True
    return False


def apply_filter_policy(
    job: dict[str, Any],
    *,
    base_score: int | None = None,
    policy: dict[str, Any] | None = None,
    adjust_score: bool = True,
) -> dict[str, Any]:
    """Annotate a scored job with hard-skip and soft-penalty policy fields."""
    policy = policy or load_filter_policy()
    text = _job_text(job)
    title_text = normalize_text_escapes(str(job.get("title") or "")).lower()
    hard_reasons: list[str] = []
    hard_rule_ids: list[str] = []
    for rule in policy.get("hard_skip_rules") or []:
        if not isinstance(rule, dict):
            continue
        if _matches(rule.get("pattern"), text):
            hard_rule_ids.append(str(rule.get("id") or "hard_skip"))
            hard_reasons.append(str(rule.get("reason") or rule.get("id") or "Hard skip"))

    soft_penalties: list[dict[str, Any]] = []
    red_flags = list(job.get("red_flags") or [])
    for rule in policy.get("soft_penalty_rules") or []:
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id") or "soft_penalty")
        match_text = title_text if rule_id in {"senior_title", "manager_title"} else text
        if not _matches(rule.get("pattern"), match_text) or _skip_soft_rule(rule_id, text, job):
            continue
        penalty = int(rule.get("penalty") or 0)
        applied_penalty = 0 if _soft_rule_already_counted(rule_id, {**job, "red_flags": red_flags}) else penalty
        soft_penalties.append({"rule": rule_id, "penalty": penalty, "applied_penalty": applied_penalty})
        red_flag = str(rule.get("red_flag") or rule_id)
        if red_flag:
            red_flags.append(red_flag)

    score = int(base_score if base_score is not None else job.get("score") or 0)
    policy_penalty = sum(int(item.get("applied_penalty", item.get("penalty") or 0) or 0) for item in soft_penalties)
    adjusted_score = max(0, score - policy_penalty) if adjust_score else score
    hard_skip = bool(hard_reasons)
    if hard_skip:
        adjusted_score = 0

    output = dict(job)
    output["hard_skip"] = hard_skip
    output["soft_penalties"] = soft_penalties
    output["red_flags"] = sorted(set(str(flag) for flag in red_flags if str(flag).strip()))
    output["filter_reason"] = "; ".join(hard_reasons) if hard_reasons else "; ".join(
        f"{item['rule']} -{item.get('applied_penalty', item['penalty'])}"
        for item in soft_penalties
        if int(item.get("applied_penalty", item.get("penalty") or 0) or 0) > 0
    )
    output["filter_rule_ids"] = hard_rule_ids + [str(item["rule"]) for item in soft_penalties]
    output["score"] = adjusted_score
    if hard_skip:
        output["recommendation"] = "Hard skip"
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate one job JSON payload against filter policy.")
    parser.add_argument("job_json", help="JSON object with title/description fields.")
    args = parser.parse_args(argv)
    job = json.loads(args.job_json)
    print(json.dumps(apply_filter_policy(job), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
