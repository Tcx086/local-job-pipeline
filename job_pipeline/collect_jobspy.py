from __future__ import annotations

import argparse
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .utils import STANDARD_FIELDS, normalize_space, now_utc_iso, stable_id, strip_html, write_csv


DEFAULT_SITES = ["indeed", "linkedin", "google", "glassdoor", "zip_recruiter"]
INDEED_COUNTRY_MAP = {
    "Canada": "Canada",
    "Singapore": "Singapore",
    "Hong Kong": "Hong Kong",
}


def _import_jobspy():
    try:
        from jobspy import scrape_jobs  # type: ignore

        return scrape_jobs
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "python-jobspy is not installed. Install requirements first: "
            "python -m pip install -r requirements.txt"
        ) from exc


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _row_get(row: Any, *names: str, default: Any = "") -> Any:
    for name in names:
        if isinstance(row, dict) and name in row:
            value = row.get(name)
            if _present(value):
                return value
        if hasattr(row, name):
            value = getattr(row, name)
            if _present(value):
                return value
    return default


def _dataframe_to_records(df: Any) -> list[dict[str, Any]]:
    if hasattr(df, "to_dict"):
        return list(df.to_dict(orient="records"))
    if isinstance(df, list):
        return df
    return []


def _site_list(site_name: list[str] | str | None) -> list[str]:
    if site_name is None:
        return list(DEFAULT_SITES)
    if isinstance(site_name, str):
        return [site_name]
    return [str(item) for item in site_name if str(item)]


def _source_name(value: Any) -> str:
    return normalize_space(value or "unknown").lower() or "unknown"


def _query_attempt(
    *,
    run_id: str,
    source: str,
    country: str,
    query: str,
    location: str,
    raw_count: int,
    success: bool,
    error_message: str = "",
    role_family: str = "",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "source": source,
        "country": country,
        "query": query,
        "location": location,
        "role_family": role_family,
        "raw_count": int(raw_count),
        "success": bool(success),
        "error_message": error_message,
    }


def standardize_jobspy_row(
    row: dict[str, Any],
    *,
    search_term: str,
    requested_country: str,
    collected_at: str,
    role_family: str = "",
) -> dict[str, Any]:
    source = _row_get(row, "site", "source")
    title = _row_get(row, "title")
    company = _row_get(row, "company")
    location = _row_get(row, "location")
    country = _row_get(row, "country", default=requested_country) or requested_country
    job_url = _row_get(row, "job_url", "url")
    apply_url = _row_get(row, "job_url_direct", "direct_url", "apply_url", default=job_url)
    description = strip_html(_row_get(row, "description"))
    job_id = _row_get(row, "id", "job_id") or stable_id(source, title, company, location, job_url)
    return {
        "job_id": str(job_id),
        "source": source,
        "title": title,
        "company": company,
        "location": location,
        "country": country,
        "date_posted": str(_row_get(row, "date_posted") or ""),
        "job_type": _row_get(row, "job_type"),
        "salary_min": _row_get(row, "min_amount", "salary_min"),
        "salary_max": _row_get(row, "max_amount", "salary_max"),
        "job_url": job_url,
        "apply_url": apply_url,
        "description": description,
        "search_term_used": search_term,
        "role_family": role_family,
        "collected_at": collected_at,
    }


def collect_jobs(
    *,
    search_terms: list[str],
    locations: list[str],
    country: str,
    hours_old: int = 24,
    results_wanted: int = 25,
    site_name: list[str] | str | None = None,
    sleep_seconds: float = 3.0,
    linkedin_fetch_description: bool = False,
    verbose: int = 1,
    run_id: str = "",
    role_family: str = "",
    return_attempts: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect public jobs through JobSpy without proxy/login bypass behavior."""
    scrape_jobs = _import_jobspy()
    sites = _site_list(site_name)
    collected_at = now_utc_iso()
    output: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []

    for term in search_terms:
        for location in locations:
            kwargs = {
                "site_name": sites,
                "search_term": term,
                "google_search_term": f"{term} jobs near {location} posted in the last {hours_old} hours",
                "location": location,
                "results_wanted": results_wanted,
                "hours_old": hours_old,
                "country_indeed": INDEED_COUNTRY_MAP.get(country, country),
                "linkedin_fetch_description": linkedin_fetch_description,
                "description_format": "markdown",
                "verbose": verbose,
            }
            try:
                jobs_df = scrape_jobs(**kwargs)
            except Exception as exc:
                if not return_attempts:
                    raise
                for site in sites:
                    attempts.append(
                        _query_attempt(
                            run_id=run_id,
                            source=site,
                            country=country,
                            query=term,
                            location=location,
                            role_family=role_family,
                            raw_count=0,
                            success=False,
                            error_message=str(exc),
                        )
                    )
                if sleep_seconds:
                    time.sleep(sleep_seconds)
                continue

            records = _dataframe_to_records(jobs_df)
            counts_by_source: dict[str, int] = defaultdict(int)
            source_labels = {_source_name(site): site for site in sites}
            for row in records:
                standardized = standardize_jobspy_row(
                    row,
                    search_term=term,
                    requested_country=country,
                    collected_at=collected_at,
                    role_family=role_family,
                )
                standardized["search_location_used"] = location
                output.append(standardized)
                source = _source_name(standardized.get("source"))
                counts_by_source[source] += 1
                source_labels.setdefault(source, str(standardized.get("source") or source))

            if return_attempts:
                for source in sorted(source_labels):
                    attempts.append(
                        _query_attempt(
                            run_id=run_id,
                            source=source_labels[source],
                            country=country,
                            query=term,
                            location=location,
                            role_family=role_family,
                            raw_count=counts_by_source.get(source, 0),
                            success=True,
                        )
                    )
            if sleep_seconds:
                time.sleep(sleep_seconds)
    if return_attempts:
        return output, attempts
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect jobs with python-jobspy.")
    parser.add_argument("--term", action="append", required=True, help="Search term; repeatable.")
    parser.add_argument("--location", action="append", required=True, help="Location; repeatable.")
    parser.add_argument("--country", required=True, choices=["Canada", "Singapore", "Hong Kong"])
    parser.add_argument("--hours-old", type=int, default=24)
    parser.add_argument("--results-wanted", type=int, default=25)
    parser.add_argument("--out", type=Path, default=Path("data/raw/jobspy_jobs.csv"))
    args = parser.parse_args()

    rows = collect_jobs(
        search_terms=args.term,
        locations=args.location,
        country=args.country,
        hours_old=args.hours_old,
        results_wanted=args.results_wanted,
    )
    write_csv(args.out, rows, STANDARD_FIELDS)
    print(f"Wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
