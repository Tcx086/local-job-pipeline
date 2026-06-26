from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from .utils import REPORTS_DIR, normalize_space, read_csv, today_yyyymmdd, write_csv

COVERAGE_FIELDS = [
    "run_id",
    "run_started_at",
    "run_finished_at",
    "mode",
    "country",
    "source",
    "query",
    "location",
    "raw_count",
    "normalized_count",
    "deduped_count",
    "scored_count",
    "report_count",
    "skipped_by_filter_count",
    "merged_by_dedupe_count",
    "average_score",
    "high_score_count_70",
    "must_apply_count_85",
    "error_count",
    "error_message",
]

COUNT_FIELDS = [
    "raw_count",
    "normalized_count",
    "deduped_count",
    "scored_count",
    "report_count",
    "skipped_by_filter_count",
    "merged_by_dedupe_count",
    "high_score_count_70",
    "must_apply_count_85",
    "error_count",
]


def _key(job: dict[str, Any]) -> tuple[str, str, str, str]:
    country = normalize_space(job.get("detected_country") or job.get("country") or "unknown") or "unknown"
    source = normalize_space(job.get("source") or "unknown") or "unknown"
    query = normalize_space(job.get("search_term_used") or job.get("ats_company_token") or job.get("query") or "active_public_postings")
    location = normalize_space(job.get("search_location_used") or job.get("location") or "all_active")
    return country, source, query or "unknown", location or "unknown"


def _attempt_key(attempt: dict[str, Any]) -> tuple[str, str, str, str]:
    country = normalize_space(attempt.get("country") or "unknown") or "unknown"
    source = normalize_space(attempt.get("source") or "unknown") or "unknown"
    query = normalize_space(attempt.get("query") or "unknown") or "unknown"
    location = normalize_space(attempt.get("location") or "unknown") or "unknown"
    return country, source, query, location


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "success"}


def _inc(row: dict[str, Any], field: str, amount: int = 1) -> None:
    row[field] = int(row.get(field) or 0) + amount


def _base_row(
    *,
    run_id: str,
    run_started_at: str,
    run_finished_at: str,
    mode: str,
    key: tuple[str, str, str, str],
) -> dict[str, Any]:
    country, source, query, location = key
    row = {
        "run_id": run_id,
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "mode": mode,
        "country": country,
        "source": source,
        "query": query,
        "location": location,
        "average_score": "",
        "error_message": "",
    }
    for field in COUNT_FIELDS:
        row[field] = 0
    return row


def build_coverage_rows(
    *,
    run_id: str,
    run_started_at: str,
    run_finished_at: str,
    mode: str,
    raw_jobs: list[dict[str, Any]],
    normalized_jobs: list[dict[str, Any]],
    scored_jobs: list[dict[str, Any]],
    deduped_jobs: list[dict[str, Any]],
    reported_jobs: list[dict[str, Any]],
    duplicate_jobs: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    query_attempts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    score_buckets: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    attempt_keys: set[tuple[str, str, str, str]] = set()
    recorded_attempt_errors: dict[tuple[tuple[str, str, str, str], str], int] = defaultdict(int)

    def row_for_key(key: tuple[str, str, str, str]) -> dict[str, Any]:
        if key not in rows:
            rows[key] = _base_row(
                run_id=run_id,
                run_started_at=run_started_at,
                run_finished_at=run_finished_at,
                mode=mode,
                key=key,
            )
        return rows[key]

    def row_for(job: dict[str, Any]) -> dict[str, Any]:
        return row_for_key(_key(job))

    for attempt in query_attempts or []:
        key = _attempt_key(attempt)
        attempt_keys.add(key)
        row = row_for_key(key)
        _inc(row, "raw_count", int(attempt.get("raw_count") or 0))
        if not _truthy(attempt.get("success")):
            _inc(row, "error_count")
            message = normalize_space(attempt.get("error_message") or "")
            if message:
                existing = normalize_space(row.get("error_message"))
                row["error_message"] = f"{existing}; {message}".strip("; ") if existing else message
                recorded_attempt_errors[(key, message)] += 1

    for job in raw_jobs:
        key = _key(job)
        if key not in attempt_keys:
            _inc(row_for_key(key), "raw_count")
    for job in normalized_jobs:
        _inc(row_for(job), "normalized_count")
    for job in scored_jobs:
        row = row_for(job)
        _inc(row, "scored_count")
        score = int(job.get("score") or 0)
        score_buckets[_key(job)].append(score)
        if bool(job.get("hard_skip")):
            _inc(row, "skipped_by_filter_count")
        if score >= 70:
            _inc(row, "high_score_count_70")
        if score >= 85:
            _inc(row, "must_apply_count_85")
    for job in deduped_jobs:
        _inc(row_for(job), "deduped_count")
    for job in reported_jobs:
        _inc(row_for(job), "report_count")
    for job in duplicate_jobs or []:
        _inc(row_for(job), "merged_by_dedupe_count")
    for error in errors or []:
        key = _key(error)
        message = normalize_space(error.get("error_message") or error.get("message") or "")
        marker = (key, message)
        if recorded_attempt_errors.get(marker, 0) > 0:
            recorded_attempt_errors[marker] -= 1
            continue
        row = row_for_key(key)
        _inc(row, "error_count")
        if message:
            existing = normalize_space(row.get("error_message"))
            row["error_message"] = f"{existing}; {message}".strip("; ") if existing else message

    for key, scores in score_buckets.items():
        if scores:
            rows[key]["average_score"] = round(mean(scores), 1)

    return sorted(rows.values(), key=lambda row: (row["country"], row["source"], row["query"], row["location"]))


def _write_xlsx(path: Path, rows: list[dict[str, Any]]) -> bool:
    try:
        import pandas as pd  # type: ignore
    except ModuleNotFoundError:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=COVERAGE_FIELDS)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Search Coverage", index=False)
        worksheet = writer.sheets["Search Coverage"]
        worksheet.freeze_panes = "A2"
        for idx, column in enumerate(COVERAGE_FIELDS, start=1):
            max_len = max([len(column)] + [len(str(row.get(column, ""))) for row in rows[:200]])
            worksheet.column_dimensions[worksheet.cell(row=1, column=idx).column_letter].width = min(max_len + 2, 60)
    return True


def _sum(rows: list[dict[str, Any]], field: str) -> int:
    return sum(int(row.get(field) or 0) for row in rows)


def write_markdown_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    source_totals: dict[str, int] = defaultdict(int)
    high_by_source: dict[str, int] = defaultdict(int)
    high_by_query: dict[str, int] = defaultdict(int)
    for row in rows:
        source = str(row.get("source") or "unknown")
        query = str(row.get("query") or "unknown")
        source_totals[source] += int(row.get("raw_count") or 0)
        high_by_source[source] += int(row.get("high_score_count_70") or 0)
        high_by_query[query] += int(row.get("high_score_count_70") or 0)

    zero_sources = [source for source, total in sorted(source_totals.items()) if total == 0]
    zero_queries = sorted({str(row.get("query")) for row in rows if int(row.get("raw_count") or 0) == 0})
    zero_locations = sorted({str(row.get("location")) for row in rows if int(row.get("raw_count") or 0) == 0})
    error_sources = sorted({str(row.get("source")) for row in rows if int(row.get("error_count") or 0) > 0})
    merged = _sum(rows, "merged_by_dedupe_count")
    deduped = _sum(rows, "deduped_count")
    scored = _sum(rows, "scored_count")
    report_count = _sum(rows, "report_count")
    high70 = _sum(rows, "high_score_count_70")
    must85 = _sum(rows, "must_apply_count_85")

    lines = ["# Search Coverage", ""]
    lines.append("## Funnel Totals")
    for label, field in [
        ("Raw", "raw_count"),
        ("Normalized", "normalized_count"),
        ("Deduped", "deduped_count"),
        ("Scored", "scored_count"),
        ("Reported", "report_count"),
        ("Hard skipped", "skipped_by_filter_count"),
        ("Merged by dedupe", "merged_by_dedupe_count"),
        ("Score >= 70", "high_score_count_70"),
        ("Score >= 85", "must_apply_count_85"),
    ]:
        lines.append(f"- {label}: {_sum(rows, field)}")
    lines.append("")
    lines.append("## Diagnostic Answers")
    lines.append(f"- Sources returning no raw jobs: {', '.join(zero_sources) if zero_sources else 'none detected'}")
    lines.append(f"- Zero-result queries: {', '.join(zero_queries[:30]) if zero_queries else 'none detected'}")
    lines.append(f"- Zero-result locations: {', '.join(zero_locations[:30]) if zero_locations else 'none detected'}")
    dedupe_ratio = (merged / max(1, deduped + merged)) * 100
    lines.append(f"- Dedupe merge ratio: {dedupe_ratio:.1f}% ({merged} merged, {deduped} kept)")
    lines.append(f"- Score threshold view: {high70} jobs are >= 70, {must85} jobs are >= 85, {scored} jobs were scored.")
    lines.append(f"- Report visibility: report_count={report_count}; All Jobs should be checked before assuming only top jobs exist.")
    top_sources = sorted(high_by_source.items(), key=lambda item: item[1], reverse=True)[:10]
    top_queries = sorted(high_by_query.items(), key=lambda item: item[1], reverse=True)[:10]
    lines.append(f"- Top high-score sources: {', '.join(f'{k} ({v})' for k, v in top_sources if v) or 'none yet'}")
    lines.append(f"- Top high-score queries: {', '.join(f'{k} ({v})' for k, v in top_queries if v) or 'none yet'}")
    lines.append(f"- Error sources: {', '.join(error_sources) if error_sources else 'none detected'}")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_coverage_reports(rows: list[dict[str, Any]], *, report_date: str | None = None) -> dict[str, str]:
    date_part = report_date or today_yyyymmdd()
    csv_path = REPORTS_DIR / f"search_coverage_{date_part}.csv"
    xlsx_path = REPORTS_DIR / f"search_coverage_{date_part}.xlsx"
    md_path = REPORTS_DIR / f"search_coverage_{date_part}.md"
    write_csv(csv_path, rows, COVERAGE_FIELDS)
    xlsx_created = _write_xlsx(xlsx_path, rows)
    write_markdown_summary(md_path, rows)
    return {
        "csv": str(csv_path),
        "xlsx": str(xlsx_path) if xlsx_created else "",
        "markdown": str(md_path),
    }


def record_search_coverage(rows: list[dict[str, Any]], *, db_path: Path | None = None, report_date: str | None = None) -> dict[str, str]:
    paths = write_coverage_reports(rows, report_date=report_date)
    if db_path is not None:
        from .database import save_search_coverage

        save_search_coverage(db_path, rows)
    return paths


def latest_coverage_csv(report_dir: Path = REPORTS_DIR) -> Path | None:
    files = sorted(report_dir.glob("search_coverage_*.csv"))
    return files[-1] if files else None


def load_latest_coverage(report_dir: Path = REPORTS_DIR) -> list[dict[str, str]]:
    path = latest_coverage_csv(report_dir)
    return read_csv(path) if path else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect search coverage diagnostics.")
    parser.add_argument("--latest", action="store_true", help="Print latest Search Coverage markdown report.")
    args = parser.parse_args(argv)
    if args.latest:
        files = sorted(REPORTS_DIR.glob("search_coverage_*.md"))
        if not files:
            print("No search coverage report found.")
            return 1
        print(files[-1].read_text(encoding="utf-8"))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
