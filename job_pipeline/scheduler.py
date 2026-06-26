from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .collect_sources import collect_jobspy_from_config, collect_sources
from .company_registry import load_company_registry
from .database import (
    DEFAULT_DB,
    connect,
    get_source_health_rows,
    record_job_merge_events,
    update_application,
    upsert_companies,
    upsert_jobs,
    upsert_manual_search_urls,
)
from .dedupe import dedupe_current_jobs
from .keyword_extract import extract_keywords
from .normalize import normalize_jobs
from .config_loader import resolve_public_config_path
from .query_expander import MODE_NAMES, build_search_config, describe_search_plan, get_search_mode, load_reporting_config
from .report import generate_reports
from .resume_tailor import generate_resume
from .score import score_jobs
from .score_calibration import record_score_calibration
from .search_diagnostics import build_coverage_rows, record_search_coverage
from .search_url_builder import write_manual_search_urls
from .source_health import build_source_health_rows, record_source_health
from .utils import CONFIG_DIR, RAW_DIR, TEMPLATES_DIR, ensure_dirs, flatten_text, load_yaml, setup_logging, today_yyyymmdd, write_csv, write_json

LOGGER = setup_logging(__name__)


def sample_jobs() -> list[dict[str, Any]]:
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return [
        {
            "job_id": "sample_linkedin_example_analytics_data",
            "source_job_id": "sample_linkedin_example_analytics_data",
            "source": "linkedin",
            "title": "Market Data Analyst",
            "company": "Example Analytics Co",
            "location": "Toronto, ON",
            "country": "Canada",
            "date_posted": today_yyyymmdd(),
            "posted_at": today_yyyymmdd(),
            "job_type": "fulltime",
            "salary_min": "",
            "salary_max": "",
            "job_url": "https://example.com/example-analytics-data-linkedin",
            "apply_url": "https://example.com/example-analytics-data-linkedin/apply",
            "description": "Analyze market data, support reporting, build SQL and Python data pipelines, reconcile data quality issues, and work with product and operations teams.",
            "search_term_used": "Market Data Analyst",
            "collected_at": collected_at,
        },
        {
            "job_id": "sample_greenhouse_example_analytics_data",
            "source_job_id": "12345",
            "source": "greenhouse",
            "title": "Market Data Analyst",
            "company": "Example Analytics Co",
            "location": "Toronto, ON",
            "country": "Canada",
            "date_posted": today_yyyymmdd(),
            "posted_at": today_yyyymmdd(),
            "job_type": "fulltime",
            "salary_min": "",
            "salary_max": "",
            "job_url": "https://boards.greenhouse.io/example/jobs/12345",
            "apply_url": "https://boards.greenhouse.io/example/jobs/12345",
            "description": "Analyze market data, support reporting, build SQL and Python data pipelines, reconcile data quality issues, and work with product and operations teams.",
            "ats_company_token": "example",
            "collected_at": collected_at,
        },
        {
            "job_id": "sample_okx_api_ops",
            "source_job_id": "sample_okx_api_ops",
            "source": "sample",
            "title": "API Support Analyst",
            "company": "Example Support Systems",
            "location": "Remote, United States",
            "country": "United States",
            "date_posted": today_yyyymmdd(),
            "posted_at": today_yyyymmdd(),
            "job_type": "fulltime",
            "salary_min": "",
            "salary_max": "",
            "job_url": "https://example.com/api-support",
            "apply_url": "https://example.com/api-support/apply",
            "description": "Provide technical operations support for REST API clients, JSON data issues, crypto market data, dashboards, incident review, and customer-facing troubleshooting.",
            "search_term_used": "API Support Analyst",
            "collected_at": collected_at,
        },
        {
            "job_id": "sample_bank_risk_ops",
            "source_job_id": "sample_bank_risk_ops",
            "source": "sample",
            "title": "Risk Operations Analyst",
            "company": "Example Finance Ops",
            "location": "Remote, Canada",
            "country": "Canada",
            "date_posted": today_yyyymmdd(),
            "posted_at": today_yyyymmdd(),
            "job_type": "fulltime",
            "salary_min": "",
            "salary_max": "",
            "job_url": "https://example.com/risk-ops",
            "apply_url": "https://example.com/risk-ops/apply",
            "description": "Support operational risk reporting, credit risk data checks, Excel tracking, reconciliation, data cleaning, and cross-functional business analysis.",
            "search_term_used": "Risk Operations Analyst",
            "collected_at": collected_at,
        },
        {
            "job_id": "sample_bad_quant_cpp",
            "source_job_id": "sample_bad_quant_cpp",
            "source": "sample",
            "title": "Senior Quant Trader - Low Latency C++",
            "company": "Example Trading",
            "location": "Remote, United States",
            "country": "United States",
            "date_posted": today_yyyymmdd(),
            "posted_at": today_yyyymmdd(),
            "job_type": "fulltime",
            "salary_min": "",
            "salary_max": "",
            "job_url": "https://example.com/senior-quant-cpp",
            "apply_url": "https://example.com/senior-quant-cpp/apply",
            "description": "Requires PhD, 7+ years required, low latency C++ HFT experience, advanced probability, and pure quant research track.",
            "search_term_used": "Quant Trader",
            "collected_at": collected_at,
        },
    ]


def load_search_config(mode: str | None = None) -> dict[str, Any]:
    return build_search_config(mode or "normal")


def collect_from_config(config: dict[str, Any], hours_old: int | None = None, results_wanted: int | None = None) -> list[dict[str, Any]]:
    rows, errors, _query_attempts = collect_jobspy_from_config(config, hours_old=hours_old, results_wanted=results_wanted)
    if errors:
        LOGGER.warning("JobSpy collection errors: %s", json.dumps(errors, ensure_ascii=False))
    return rows


def enrich_for_resume_and_report(jobs: list[dict[str, Any]], *, master_resume_path: Path, resume_score_threshold: int = 70, make_docx: bool = True, generate_resumes: bool = False) -> list[dict[str, Any]]:
    master_resume = load_yaml(master_resume_path)
    master_text = flatten_text(master_resume)
    enriched: list[dict[str, Any]] = []
    for job in jobs:
        keyword_info = extract_keywords(str(job.get("description") or ""), master_text)
        row = dict(job)
        row["top_keywords"] = keyword_info["top_keywords"]
        row["missing_keywords"] = keyword_info["missing_keywords_from_master_resume"]
        row["suggested_resume_focus"] = keyword_info["suggested_resume_focus"]
        row["scheduler_resume_draft_path"] = row.get("scheduler_resume_draft_path") or row.get("resume_file_generated", "")
        row["resume_file_generated"] = row.get("resume_file_generated", "")
        if generate_resumes and not row.get("hard_skip") and int(row.get("score") or 0) >= resume_score_threshold:
            paths = generate_resume(master_resume_path=master_resume_path, job=row, keyword_info=keyword_info, make_docx=make_docx)
            draft_path = paths.get("pdf") or paths.get("docx") or paths.get("markdown", "")
            row["scheduler_resume_draft_path"] = draft_path
            row["resume_file_generated"] = draft_path
            if paths.get("pdf"):
                row["resume_pdf_generated"] = paths["pdf"]
            if paths.get("docx"):
                row["resume_docx_generated"] = paths["docx"]
            if paths.get("markdown"):
                row["resume_markdown_generated"] = paths["markdown"]
        enriched.append(row)
    return enriched


def initialize_company_registry(db_path: Path = DEFAULT_DB) -> None:
    conn = connect(db_path)
    try:
        upsert_companies(conn, load_company_registry())
    finally:
        conn.close()


def _reported_jobs(jobs: list[dict[str, Any]], min_score_report: int) -> list[dict[str, Any]]:
    return [job for job in jobs if not job.get("hard_skip") and int(job.get("score") or 0) >= min_score_report]


def run_once(
    *,
    use_sample: bool = False,
    mode: str = "normal",
    hours_old: int | None = None,
    results_wanted: int | None = None,
    resume_score_threshold: int | None = None,
    make_docx: bool = True,
    generate_resumes: bool = False,
    db_path: Path = DEFAULT_DB,
    include_ats: bool = True,
    ats_source: str = "all",
    mark_missing: bool = True,
    max_queries: int | None = None,
    max_locations: int | None = None,
    max_query_location_pairs: int | None = None,
    query_family: str | None = None,
    country: list[str] | str | None = None,
    source_sites: list[str] | str | None = None,
    no_rotation: bool = False,
) -> dict[str, Any]:
    ensure_dirs()
    initialize_company_registry(db_path)
    mode_settings = get_search_mode(mode)
    planned_search_config = build_search_config(
        mode,
        max_queries=max_queries,
        max_locations=max_locations,
        max_query_location_pairs=max_query_location_pairs,
        query_family=query_family,
        country=country,
        source_sites=source_sites,
        no_rotation=no_rotation,
    )
    config_settings = planned_search_config.get("settings") or {}
    hours_old = hours_old if hours_old is not None else int(config_settings.get("hours_old") or mode_settings["days_back"] * 24)
    results_wanted = results_wanted if results_wanted is not None else int(config_settings.get("results_wanted") or mode_settings["results_wanted_per_query"])
    resume_score_threshold = resume_score_threshold if resume_score_threshold is not None else mode_settings["generate_resume_min_score"]
    min_score_report = int(mode_settings["min_score_report"])
    run_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{mode}_{run_stamp}"
    manual_pages: list[dict[str, Any]] = []
    manual_search_urls: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    query_attempts: list[dict[str, Any]] = []

    if use_sample:
        raw_jobs = sample_jobs()
    else:
        result = collect_sources(
            mode=mode,
            hours_old=hours_old,
            results_wanted=results_wanted,
            include_ats=include_ats,
            ats_source=ats_source,
            run_id=run_id,
            max_queries=max_queries,
            max_locations=max_locations,
            max_query_location_pairs=max_query_location_pairs,
            query_family=query_family,
            country=country,
            source_sites=source_sites,
            no_rotation=no_rotation,
        )
        raw_jobs = result.jobs
        manual_pages = result.manual_pages
        manual_search_urls = result.manual_search_urls
        errors = result.errors
        query_attempts = result.query_attempts
    if manual_search_urls:
        upsert_manual_search_urls(db_path, manual_search_urls)
    manual_url_paths = write_manual_search_urls(manual_search_urls) if manual_search_urls else {"csv": ""}

    raw_csv = RAW_DIR / f"jobs_raw_{run_stamp}.csv"
    raw_json = RAW_DIR / f"jobs_raw_{run_stamp}.json"
    write_csv(raw_csv, raw_jobs)
    write_json(
        raw_json,
        {
            "run_id": run_id,
            "mode": mode,
            "jobs": raw_jobs,
            "manual_company_pages": manual_pages,
            "manual_search_urls": manual_search_urls,
            "errors": errors,
            "query_attempts": query_attempts,
        },
    )

    normalized = normalize_jobs(raw_jobs)
    scored = score_jobs(normalized)
    unique_current, duplicates, merge_events = dedupe_current_jobs(scored, run_id=run_id, return_events=True)
    final_jobs = enrich_for_resume_and_report(
        unique_current,
        master_resume_path=resolve_public_config_path("master_resume"),
        resume_score_threshold=resume_score_threshold,
        make_docx=make_docx,
        generate_resumes=generate_resumes,
    )
    upserted_rows, new_rows = upsert_jobs(db_path, final_jobs, raw_json_path=str(raw_json), mark_missing=mark_missing)
    record_job_merge_events(db_path, merge_events)

    run_finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report_visible_jobs = _reported_jobs(upserted_rows, min_score_report)
    coverage_rows = build_coverage_rows(
        run_id=run_id,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        mode=mode,
        raw_jobs=raw_jobs,
        normalized_jobs=normalized,
        scored_jobs=scored,
        deduped_jobs=unique_current,
        reported_jobs=report_visible_jobs,
        duplicate_jobs=duplicates,
        errors=errors,
        query_attempts=query_attempts,
    )
    coverage_paths = record_search_coverage(coverage_rows, db_path=db_path)
    previous_source_health_rows = get_source_health_rows(db_path)
    source_health_rows = build_source_health_rows(
        coverage_rows,
        run_id=run_id,
        previous_rows=previous_source_health_rows,
        last_run_at=run_finished_at,
    )
    source_health_paths = record_source_health(source_health_rows, db_path=db_path)
    reporting = load_reporting_config()
    score_calibration_paths = record_score_calibration(scored, top_n=int(reporting.get("always_include_top_n") or 20))
    reports = generate_reports(upserted_rows, db_path=db_path, min_score_report=min_score_report)
    summary = {
        "run_id": run_id,
        "mode": mode,
        "hours_old": hours_old,
        "results_wanted": results_wanted,
        "min_score_report": min_score_report,
        "resume_score_threshold": resume_score_threshold,
        "generate_resumes": generate_resumes,
        "raw_jobs": len(raw_jobs),
        "normalized_jobs": len(normalized),
        "scored_jobs": len(scored),
        "current_unique_jobs": len(unique_current),
        "current_duplicates": len(duplicates),
        "reported_jobs": len(report_visible_jobs),
        "new_canonical_jobs": len(new_rows),
        "manual_company_pages": len(manual_pages),
        "manual_search_urls": len(manual_search_urls),
        "database": str(db_path),
        "reports": reports,
        "search_coverage": coverage_paths,
        "source_health": source_health_paths,
        "manual_search_url_report": manual_url_paths,
        "score_calibration": score_calibration_paths,
        "raw_csv": str(raw_csv),
        "raw_json": str(raw_json),
    }
    LOGGER.info("Run summary: %s", json.dumps(summary, ensure_ascii=False))
    return summary


def seconds_until(clock_time: str) -> float:
    hour, minute = [int(part) for part in clock_time.split(":", 1)]
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_daily(clock_time: str, **kwargs: Any) -> None:
    while True:
        wait_seconds = seconds_until(clock_time)
        LOGGER.info("Next run scheduled at %s in %.1f minutes", clock_time, wait_seconds / 60)
        time.sleep(wait_seconds)
        try:
            run_once(**kwargs)
        except Exception:
            LOGGER.exception("Scheduled run failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local job pipeline scheduler.")
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--run-once", action="store_true", help="Run one collection/scoring/report cycle.")
    mode_group.add_argument("--daily", action="store_true", help="Run once per day at --time.")
    mode_group.add_argument("--mark-status", nargs=2, metavar=("CANONICAL_JOB_ID", "STATUS"), help="Update application status in SQLite.")
    parser.add_argument("--mode", choices=sorted(MODE_NAMES), default="normal")
    parser.add_argument("--time", default="08:30", help="Daily run time in HH:MM local time.")
    parser.add_argument("--sample", action="store_true", help="Use local sample jobs instead of scraping.")
    parser.add_argument("--hours-old", type=int, default=None)
    parser.add_argument("--results-wanted", type=int, default=None)
    parser.add_argument("--resume-score", type=int, default=None)
    parser.add_argument("--generate-resumes", action="store_true", help="Opt in to scheduler resume draft generation; disabled by default.")
    parser.add_argument("--no-docx", action="store_true", help="Skip DOCX output when resume generation is explicitly enabled.")
    parser.add_argument("--no-ats", action="store_true", help="Skip ATS collectors.")
    parser.add_argument("--ats-source", choices=["all", "greenhouse", "lever", "ashby"], default="all")
    parser.add_argument("--no-mark-missing", action="store_true", help="Do not mark missing jobs inactive after this run.")
    parser.add_argument("--max-queries", type=int, default=None)
    parser.add_argument("--max-locations", type=int, default=None)
    parser.add_argument("--max-query-location-pairs", type=int, default=None)
    parser.add_argument("--query-family", default=None)
    parser.add_argument("--country", action="append", default=None)
    parser.add_argument("--source-sites", default=None, help="Comma-separated JobSpy source sites, e.g. linkedin,indeed.")
    parser.add_argument("--dry-run-plan", action="store_true", help="Print bounded search plan without external requests.")
    parser.add_argument("--no-rotation", action="store_true", help="Disable daily query/location rotation for this run.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    if args.mark_status:
        update_application(args.mark_status[0], status=args.mark_status[1], db_path=args.db)
        print(f"Updated {args.mark_status[0]} -> {args.mark_status[1]}")
        return 0

    kwargs = {
        "use_sample": args.sample,
        "mode": args.mode,
        "hours_old": args.hours_old,
        "results_wanted": args.results_wanted,
        "resume_score_threshold": args.resume_score,
        "make_docx": not args.no_docx,
        "generate_resumes": args.generate_resumes,
        "include_ats": not args.no_ats,
        "ats_source": args.ats_source,
        "mark_missing": not args.no_mark_missing,
        "db_path": args.db,
        "max_queries": args.max_queries,
        "max_locations": args.max_locations,
        "max_query_location_pairs": args.max_query_location_pairs,
        "query_family": args.query_family,
        "country": args.country,
        "source_sites": args.source_sites,
        "no_rotation": args.no_rotation,
    }
    if args.dry_run_plan:
        try:
            search_config = build_search_config(
                args.mode,
                max_queries=args.max_queries,
                max_locations=args.max_locations,
                max_query_location_pairs=args.max_query_location_pairs,
                query_family=args.query_family,
                country=args.country,
                source_sites=args.source_sites,
                no_rotation=args.no_rotation,
            )
            print(json.dumps(describe_search_plan(search_config, mode=args.mode), ensure_ascii=False, indent=2))
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    if args.run_once:
        try:
            summary = run_once(**kwargs)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    run_daily(args.time, **kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
