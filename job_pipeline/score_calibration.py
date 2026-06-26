from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from .score import SCORE_BANDS, score_band
from .utils import REPORTS_DIR, list_to_cell, today_yyyymmdd, write_csv

CALIBRATION_FIELDS = ["section", "metric", "value", "details"]
BREAKDOWN_FIELDS = [
    "role_fit",
    "skill_match",
    "location_fit",
    "seniority_fit",
    "visa_work_authorization_fit",
    "industry_fit",
    "penalty",
]


def _score(row: dict[str, Any]) -> int:
    return int(row.get("score") or 0)


def _hard_skip(row: dict[str, Any]) -> bool:
    return bool(row.get("hard_skip")) or str(row.get("recommendation") or "").lower() == "hard skip"


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [part.strip() for part in text.split(";") if part.strip()]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item)]
    return [str(value)]


def _breakdown(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("score_breakdown") or {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


def score_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    distribution = {label: 0 for _, _, label in SCORE_BANDS}
    distribution["Hard skip"] = 0
    for row in rows:
        label = score_band(_score(row), hard_skip=_hard_skip(row))
        distribution[label] = distribution.get(label, 0) + 1
    return distribution


def top_jobs(rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    return sorted([row for row in rows if not _hard_skip(row)], key=lambda row: _score(row), reverse=True)[:limit]


def build_calibration_rows(rows: list[dict[str, Any]], *, top_n: int = 20) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    distribution = score_distribution(rows)
    output.append({"section": "summary", "metric": "total_scored_jobs", "value": len(rows), "details": ""})
    for _, _, label in SCORE_BANDS:
        output.append({"section": "score_distribution", "metric": label, "value": distribution.get(label, 0), "details": ""})
    output.append({"section": "score_distribution", "metric": "Hard skip", "value": distribution.get("Hard skip", 0), "details": ""})

    red_flags = Counter(flag for row in rows for flag in _list(row.get("red_flags")))
    filter_reasons = Counter(reason.strip() for row in rows for reason in str(row.get("filter_reason") or "").split(";") if reason.strip())
    penalties = Counter()
    for row in rows:
        breakdown = _breakdown(row)
        if int(breakdown.get("penalty") or 0) > 0:
            penalties["score_breakdown.penalty"] += int(breakdown.get("penalty") or 0)
    for reason, count in (red_flags + filter_reasons + penalties).most_common(20):
        output.append({"section": "loss_reasons", "metric": reason, "value": count, "details": ""})

    for field in BREAKDOWN_FIELDS:
        values = []
        for row in rows:
            breakdown = _breakdown(row)
            if field in breakdown and breakdown.get(field) not in (None, ""):
                values.append(float(breakdown.get(field) or 0))
        output.append({"section": "average_breakdown", "metric": field, "value": round(mean(values), 2) if values else "", "details": ""})

    for idx, row in enumerate(top_jobs(rows, top_n), start=1):
        output.append(
            {
                "section": "top_jobs",
                "metric": str(idx),
                "value": _score(row),
                "details": f"{row.get('company')} | {row.get('title')} | {row.get('location')} | {row.get('recommendation')}",
            }
        )

    manual_review = [row for row in rows if not _hard_skip(row) and 35 <= _score(row) <= 54]
    for idx, row in enumerate(sorted(manual_review, key=lambda item: _score(item), reverse=True)[:10], start=1):
        output.append(
            {
                "section": "manual_review_examples",
                "metric": str(idx),
                "value": _score(row),
                "details": f"{row.get('company')} | {row.get('title')} | flags={list_to_cell(row.get('red_flags'))}",
            }
        )
    return output


def write_score_calibration_markdown(path: Path, rows: list[dict[str, Any]], *, top_n: int = 20) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    distribution = score_distribution(rows)
    top = top_jobs(rows, top_n)
    red_flags = Counter(flag for row in rows for flag in _list(row.get("red_flags")))
    filter_reasons = Counter(reason.strip() for row in rows for reason in str(row.get("filter_reason") or "").split(";") if reason.strip())
    lines = ["# Score Calibration", ""]
    lines.append(f"- Total scored jobs: {len(rows)}")
    lines.append("")
    lines.append("## Score Distribution")
    for _, _, label in SCORE_BANDS:
        lines.append(f"- {label}: {distribution.get(label, 0)}")
    lines.append(f"- Hard skip: {distribution.get('Hard skip', 0)}")
    lines.append("")
    lines.append("## Top 20 Jobs By Score")
    for idx, row in enumerate(top, start=1):
        lines.append(f"{idx}. {row.get('score')} - {row.get('company')} - {row.get('title')} ({row.get('recommendation')})")
    if not top:
        lines.append("No non-hard-skipped jobs scored in this run.")
    lines.append("")
    lines.append("## Top Reasons Jobs Lose Points")
    combined = red_flags + filter_reasons
    for reason, count in combined.most_common(15):
        lines.append(f"- {reason}: {count}")
    if not combined:
        lines.append("- none detected")
    lines.append("")
    lines.append("## Average Score Breakdown")
    for item in build_calibration_rows(rows, top_n=0):
        if item["section"] == "average_breakdown":
            lines.append(f"- {item['metric']}: {item['value']}")
    lines.append("")
    lines.append("## Manual Review Examples 35-54")
    examples = [row for row in rows if not _hard_skip(row) and 35 <= _score(row) <= 54]
    for idx, row in enumerate(sorted(examples, key=lambda item: _score(item), reverse=True)[:10], start=1):
        lines.append(f"{idx}. {row.get('score')} - {row.get('company')} - {row.get('title')} | {row.get('location')}")
    if not examples:
        lines.append("No 35-54 manual review examples in this run.")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def record_score_calibration(rows: list[dict[str, Any]], *, report_date: str | None = None, top_n: int = 20) -> dict[str, str]:
    date_part = report_date or today_yyyymmdd()
    csv_path = REPORTS_DIR / f"score_calibration_{date_part}.csv"
    md_path = REPORTS_DIR / f"score_calibration_{date_part}.md"
    write_csv(csv_path, build_calibration_rows(rows, top_n=top_n), CALIBRATION_FIELDS)
    write_score_calibration_markdown(md_path, rows, top_n=top_n)
    return {"csv": str(csv_path), "markdown": str(md_path)}
