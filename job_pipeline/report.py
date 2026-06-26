from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .database import (
    DEFAULT_DB,
    get_applications,
    get_companies,
    get_job_merge_events,
    get_jobs,
    get_manual_search_urls,
    get_search_coverage_rows,
    get_source_health_rows,
)
from .query_expander import load_reporting_config
from .score import score_band
from .utils import REPORTS_DIR, list_to_cell, today_yyyymmdd, write_csv

REPORT_FIELDS = [
    "canonical_job_id", "score", "score_band", "recommendation", "freshness_label", "is_new_since_last_run",
    "title", "company", "location", "country", "source", "search_term_used", "posted_at", "first_seen_at", "last_seen_at",
    "is_active", "job_url", "apply_url", "role_category", "seniority", "matched_keywords",
    "missing_keywords", "red_flags", "hard_skip", "soft_penalties", "filter_reason", "all_sources",
    "reason_to_apply", "scheduler_resume_draft_path", "resume_file_generated", "status", "next_action",
]

FRESHNESS_PRIORITY = {"new_today": 0, "new_this_week": 1, "recent": 2, "unknown": 3, "old": 4}
COUNTRY_PRIORITY = {"Remote": 99}


def _status(job: dict[str, Any]) -> str:
    return str(job.get("status") or "new")


def _score(row: dict[str, Any]) -> int:
    return int(row.get("score") or 0)


def _hard_skip(row: dict[str, Any]) -> bool:
    return bool(row.get("hard_skip")) or str(row.get("recommendation") or "").lower() == "hard skip"


def _band(row: dict[str, Any]) -> str:
    return str(row.get("score_band") or score_band(_score(row), hard_skip=_hard_skip(row)))


def prepare_report_rows(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in jobs:
        hard_skip = _hard_skip(job)
        row = {
            "canonical_job_id": job.get("canonical_job_id") or job.get("job_id"),
            "score": job.get("score"),
            "score_band": score_band(int(job.get("score") or 0), hard_skip=hard_skip),
            "recommendation": job.get("recommendation") or score_band(int(job.get("score") or 0), hard_skip=hard_skip),
            "freshness_label": job.get("freshness_label", "unknown"),
            "is_new_since_last_run": job.get("is_new_since_last_run", 0),
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "country": job.get("detected_country") or job.get("country"),
            "source": job.get("source"),
            "search_term_used": job.get("search_term_used", ""),
            "posted_at": job.get("posted_at") or job.get("date_posted"),
            "first_seen_at": job.get("first_seen_at"),
            "last_seen_at": job.get("last_seen_at"),
            "is_active": job.get("is_active", 1),
            "job_url": job.get("job_url"),
            "apply_url": job.get("apply_url"),
            "role_category": job.get("role_category"),
            "seniority": job.get("seniority"),
            "matched_keywords": list_to_cell(job.get("matched_keywords")),
            "missing_keywords": list_to_cell(job.get("missing_keywords")),
            "red_flags": list_to_cell(job.get("red_flags")),
            "hard_skip": int(hard_skip),
            "soft_penalties": list_to_cell([f"{item.get('rule')}:-{item.get('penalty')}" for item in job.get("soft_penalties") or []]) if isinstance(job.get("soft_penalties"), list) else str(job.get("soft_penalties") or ""),
            "filter_reason": job.get("filter_reason", ""),
            "all_sources": list_to_cell(job.get("all_sources")),
            "reason_to_apply": job.get("reason_to_apply"),
            "scheduler_resume_draft_path": job.get("scheduler_resume_draft_path") or job.get("resume_file_generated", ""),
            "resume_file_generated": job.get("resume_file_generated", ""),
            "status": _status(job),
            "next_action": job.get("next_action", ""),
        }
        rows.append(row)
    rows.sort(key=sort_key)
    return rows


def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(_hard_skip(row)),
        -int(row.get("is_new_since_last_run") or 0),
        -_score(row),
        FRESHNESS_PRIORITY.get(str(row.get("freshness_label") or "unknown"), 9),
        COUNTRY_PRIORITY.get(str(row.get("country") or ""), 9),
        str(row.get("company") or ""),
    )


def _format_sheet(worksheet: Any, rows: list[dict[str, Any]], fields: list[str]) -> None:
    worksheet.freeze_panes = "A2"
    for idx, column in enumerate(fields, start=1):
        max_len = max([len(str(column))] + [len(str(row.get(column, ""))) for row in rows[:200]])
        worksheet.column_dimensions[worksheet.cell(row=1, column=idx).column_letter].width = min(max_len + 2, 60)


def _df(rows: list[dict[str, Any]], fields: list[str] | None = None):
    import pandas as pd  # type: ignore

    return pd.DataFrame(rows, columns=fields) if fields else pd.DataFrame(rows)


def _new_this_week(row: dict[str, Any]) -> bool:
    return str(row.get("freshness_label") or "") in {"new_today", "new_this_week"} or int(row.get("is_new_since_last_run") or 0) == 1


def _active_old(row: dict[str, Any]) -> bool:
    return int(row.get("is_active") or 0) == 1 and str(row.get("freshness_label") or "") in {"recent", "old", "unknown"}


def _top_review_candidates(rows: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    return sorted([row for row in rows if not _hard_skip(row)], key=lambda row: _score(row), reverse=True)[:top_n]


def _sheet_rows(rows: list[dict[str, Any]], db_path: Path, min_score_report: int, top_n: int) -> list[tuple[str, list[dict[str, Any]], list[str] | None]]:
    return [
        ("Top Review Candidates", _top_review_candidates(rows, top_n), REPORT_FIELDS),
        ("Must Apply 85-100", [r for r in rows if not _hard_skip(r) and _score(r) >= 85], REPORT_FIELDS),
        ("Strong Apply 70-84", [r for r in rows if not _hard_skip(r) and 70 <= _score(r) < 85], REPORT_FIELDS),
        ("Maybe Apply 55-69", [r for r in rows if not _hard_skip(r) and 55 <= _score(r) < 70], REPORT_FIELDS),
        ("Review Manually 35-54", [r for r in rows if not _hard_skip(r) and 35 <= _score(r) < 55], REPORT_FIELDS),
        ("Low Priority 25-34", [r for r in rows if not _hard_skip(r) and 25 <= _score(r) < 35], REPORT_FIELDS),
        ("Skip 0-24", [r for r in rows if not _hard_skip(r) and _score(r) < 25], REPORT_FIELDS),
        ("Visible Score Threshold", [r for r in rows if not _hard_skip(r) and _score(r) >= min_score_report], REPORT_FIELDS),
        ("All Jobs", rows, REPORT_FIELDS),
        ("Hard Skipped", [r for r in rows if _hard_skip(r)], REPORT_FIELDS),
        ("New Today", [r for r in rows if r.get("freshness_label") == "new_today" or int(r.get("is_new_since_last_run") or 0) == 1], REPORT_FIELDS),
        ("New This Week", [r for r in rows if _new_this_week(r)], REPORT_FIELDS),
        ("Backfill Active Jobs", [r for r in rows if _active_old(r)], REPORT_FIELDS),
        *[(country, [r for r in rows if r.get("country") == country], REPORT_FIELDS) for country in sorted({str(r.get("country") or "Unknown") for r in rows})],
        ("Search Coverage", get_search_coverage_rows(db_path), None),
        ("Source Health", get_source_health_rows(db_path), None),
        ("Dedupe Audit", get_job_merge_events(db_path), None),
        ("Manual Search URLs", get_manual_search_urls(db_path), None),
        ("Applied Tracker", get_applications(db_path), None),
        ("Company Tracker", get_companies(db_path), None),
    ]


def write_excel(path: Path, rows: list[dict[str, Any]], *, db_path: Path = DEFAULT_DB, min_score_report: int = 70, top_n: int = 20) -> bool:
    try:
        import pandas as pd  # type: ignore  # noqa: F401
    except ModuleNotFoundError:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, sheet_rows, fields in _sheet_rows(rows, db_path, min_score_report, top_n):
            data = _df(sheet_rows, fields)
            data.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            _format_sheet(writer.sheets[sheet_name[:31]], sheet_rows, list(data.columns))
    return True


def _append_job(lines: list[str], idx: int, row: dict[str, Any]) -> None:
    lines.append(f"## {idx}. {row.get('title')} - {row.get('company')} ({row.get('score')})")
    lines.append(f"- Band: {_band(row)} | Recommendation: {row.get('recommendation')} | Freshness: {row.get('freshness_label')}")
    lines.append(f"- Location: {row.get('location')} | {row.get('country')} | Source: {row.get('source')}")
    lines.append(f"- Posted: {row.get('posted_at') or 'unknown'} | First seen: {row.get('first_seen_at') or 'unknown'}")
    lines.append(f"- Role category: {row.get('role_category')}")
    lines.append(f"- Matched keywords: {row.get('matched_keywords')}")
    if row.get("missing_keywords"):
        lines.append(f"- Missing keywords to review: {row.get('missing_keywords')}")
    if row.get("red_flags"):
        lines.append(f"- Red flags: {row.get('red_flags')}")
    lines.append(f"- Why apply: {row.get('reason_to_apply')}")
    if row.get("scheduler_resume_draft_path") or row.get("resume_file_generated"):
        resume_path = str(row.get("scheduler_resume_draft_path") or row.get("resume_file_generated") or "")
        label = "Resume PDF" if resume_path.lower().endswith(".pdf") else "Resume draft"
        lines.append(f"- {label}: {resume_path}")
    if row.get("apply_url"):
        lines.append(f"- Apply URL: {row.get('apply_url')}")
    elif row.get("job_url"):
        lines.append(f"- Job URL: {row.get('job_url')}")
    lines.append("")


def write_top_jobs_markdown(path: Path, rows: list[dict[str, Any]], *, limit: int = 30, min_score_report: int = 35, markdown_min_score: int = 35, always_include_top_n: int = 20) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    active_rows = [row for row in rows if int(row.get("is_active") or 0) == 1]
    hard_skipped = [row for row in rows if _hard_skip(row)]
    non_hard = [row for row in rows if not _hard_skip(row)]
    apply_grade = [row for row in non_hard if _score(row) >= 55]
    visible = [row for row in non_hard if _score(row) >= markdown_min_score]
    top_review = _top_review_candidates(non_hard, always_include_top_n)
    lines = ["# Daily Top Jobs", ""]
    lines.append("## Pool Summary")
    lines.append(f"- All Jobs: {len(rows)}")
    lines.append(f"- Active Jobs: {len(active_rows)}")
    lines.append(f"- Must apply 85-100: {sum(1 for row in non_hard if _score(row) >= 85)}")
    lines.append(f"- Strong apply 70-84: {sum(1 for row in non_hard if 70 <= _score(row) < 85)}")
    lines.append(f"- Maybe apply 55-69: {sum(1 for row in non_hard if 55 <= _score(row) < 70)}")
    lines.append(f"- Review manually 35-54: {sum(1 for row in non_hard if 35 <= _score(row) < 55)}")
    lines.append(f"- Low priority 25-34: {sum(1 for row in non_hard if 25 <= _score(row) < 35)}")
    lines.append(f"- Skip 0-24: {sum(1 for row in non_hard if _score(row) < 25)}")
    lines.append(f"- Hard Skipped: {len(hard_skipped)}")
    lines.append(f"- Visible report threshold: {min_score_report}")
    if not apply_grade and top_review:
        lines.append("- No apply-grade roles, but review candidates exist.")
    lines.append("- Note: resume drafts are generated only at the mode resume threshold, not by the report visibility threshold.")
    lines.append("")

    lines.append("# Top Review Candidates")
    if not top_review:
        lines.append("No non-hard-skipped jobs were found. Check Search Coverage and Hard Skipped sheets.")
    for idx, row in enumerate(top_review[:always_include_top_n], start=1):
        _append_job(lines, idx, row)

    if visible:
        lines.append("# Visible Candidates By Threshold")
        for idx, row in enumerate(visible[:limit], start=1):
            _append_job(lines, idx, row)
    elif non_hard:
        lines.append("# Visible Candidates By Threshold")
        lines.append("No jobs met the Markdown threshold; Top Review Candidates above still shows the highest scoring roles.")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_dashboard_export(path: Path, jobs: list[dict[str, Any]], db_path: Path = DEFAULT_DB, min_score_report: int = 70, top_n: int = 20) -> bool:
    rows = prepare_report_rows(jobs)
    return write_excel(path, rows, db_path=db_path, min_score_report=min_score_report, top_n=top_n)


def generate_reports(jobs: list[dict[str, Any]], report_date: str | None = None, db_path: Path = DEFAULT_DB, min_score_report: int = 70) -> dict[str, str]:
    date_part = report_date or today_yyyymmdd()
    reporting = load_reporting_config()
    top_n = int(reporting.get("always_include_top_n") or 20)
    markdown_min_score = int(reporting.get("markdown_min_score") or min_score_report)
    rows = prepare_report_rows(jobs)
    csv_path = REPORTS_DIR / f"daily_jobs_{date_part}.csv"
    xlsx_path = REPORTS_DIR / f"daily_jobs_{date_part}.xlsx"
    md_path = REPORTS_DIR / f"top_jobs_{date_part}.md"
    dashboard_path = REPORTS_DIR / f"daily_dashboard_export_{date_part}.xlsx"
    write_csv(csv_path, rows, REPORT_FIELDS)
    xlsx_created = write_excel(xlsx_path, rows, db_path=db_path, min_score_report=min_score_report, top_n=top_n)
    dashboard_created = write_dashboard_export(dashboard_path, jobs, db_path=db_path, min_score_report=min_score_report, top_n=top_n)
    write_top_jobs_markdown(
        md_path,
        rows,
        min_score_report=min_score_report,
        markdown_min_score=markdown_min_score,
        always_include_top_n=top_n,
    )
    return {
        "csv": str(csv_path),
        "xlsx": str(xlsx_path) if xlsx_created else "",
        "markdown": str(md_path),
        "dashboard_export": str(dashboard_path) if dashboard_created else "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate local job reports from SQLite.")
    parser.add_argument("--today", action="store_true")
    parser.add_argument("--min-score-report", type=int, default=70)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    jobs = get_jobs(args.db, include_inactive=True)
    paths = generate_reports(jobs, report_date=today_yyyymmdd() if args.today else None, db_path=args.db, min_score_report=args.min_score_report)
    for key, value in paths.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
