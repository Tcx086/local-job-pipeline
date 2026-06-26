from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from .query_expander import build_search_config, expand_queries, get_search_mode
from .source_health import load_source_registry
from .utils import CONFIG_DIR, REPORTS_DIR, load_yaml, now_utc_iso, today_yyyymmdd, write_csv

MANUAL_SEARCH_FIELDS = [
    "source_name",
    "country",
    "query",
    "location",
    "search_url",
    "generated_at",
    "last_checked_at",
    "notes",
]


def build_search_url(source_name: str, query: str, location: str = "", country: str = "", careers_url: str = "") -> str:
    source = source_name.strip().lower()
    q = quote_plus(query)
    loc = quote_plus(location or country)
    if source == "linkedin":
        return f"https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}"
    if source == "indeed":
        return f"https://www.indeed.com/jobs?q={q}&l={loc}"
    if source == "google":
        return f"https://www.google.com/search?q={quote_plus(f'{query} jobs {location or country}')}"
    if source == "efinancialcareers":
        return f"https://www.efinancialcareers.com/search-jobs?keywords={q}&location={loc}"
    if source == "cfa institute career center":
        return f"https://careers.cfainstitute.org/jobs/?keywords={q}&location={loc}"
    if source == "canada job bank":
        return f"https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring={q}&locationstring={loc}"
    if source == "jobsdb hong kong":
        return f"https://hk.jobsdb.com/jobs?keywords={q}&location={loc}"
    if source == "mycareersfuture singapore":
        return f"https://www.mycareersfuture.gov.sg/search?search={q}&sortBy=new_posting_date&page=0"
    if source == "cryptojobslist":
        return f"https://cryptojobslist.com/jobs?query={q}"
    if source == "web3 career":
        return f"https://web3.career/jobs?query={q}"
    if source == "remote3":
        return f"https://remote3.co/search?query={q}"
    if source == "company careers":
        return careers_url
    return f"https://www.google.com/search?q={quote_plus(f'{source_name} {query} jobs {location or country}')}"


def _source_country_allowed(source_name: str, country: str) -> bool:
    source = source_name.lower()
    if "canada job bank" in source:
        return country == "Canada"
    if "jobsdb" in source:
        return country == "Hong Kong"
    if "mycareersfuture" in source:
        return country == "Singapore"
    return True


def _manual_sources(registry: dict[str, Any] | None = None) -> list[str]:
    registry = registry or load_source_registry()
    sources = ["LinkedIn", "Indeed", "Google"]
    for group in (registry.get("sources") or {}).values():
        if not isinstance(group, dict) or not group.get("enabled", True):
            continue
        for item in group.get("sources") or []:
            if isinstance(item, dict):
                mode = str(item.get("mode") or "")
                if "manual" in mode or "public_page" in mode or "rss" in mode:
                    sources.append(str(item.get("name") or ""))
    seen: set[str] = set()
    result: list[str] = []
    for source in sources:
        marker = source.lower()
        if source and marker not in seen:
            seen.add(marker)
            result.append(source)
    return result


def _company_page_rows(generated_at: str) -> list[dict[str, Any]]:
    config = load_yaml(CONFIG_DIR / "ats_sources.yaml") or {}
    rows: list[dict[str, Any]] = []
    for item in config.get("company_pages") or []:
        countries = item.get("country_focus") or [""]
        for country in countries:
            rows.append(
                {
                    "source_name": "Company Careers",
                    "country": country,
                    "query": str(item.get("company_name") or ""),
                    "location": country,
                    "search_url": build_search_url(
                        "Company Careers",
                        str(item.get("company_name") or ""),
                        str(country or ""),
                        str(country or ""),
                        careers_url=str(item.get("careers_url") or ""),
                    ),
                    "generated_at": generated_at,
                    "last_checked_at": "",
                    "notes": "Manual company career page check only; no login/captcha bypass.",
                }
            )
    return rows


def generate_manual_search_urls(
    *,
    mode: str = "normal",
    registry: dict[str, Any] | None = None,
    include_company_pages: bool = True,
    search_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    settings = get_search_mode(mode)
    limit = int(settings.get("manual_url_query_limit") or 20)
    search_config = search_config or build_search_config(mode)
    fallback_queries = expand_queries(mode, max_queries=limit)
    sources = _manual_sources(registry)
    generated_at = now_utc_iso()
    rows: list[dict[str, Any]] = []
    for country, payload in (search_config.get("countries") or {}).items():
        exact_pairs = payload.get("query_location_pairs") or []
        pair_values = [
            (str(pair.get("query") or ""), str(pair.get("location") or country))
            for pair in exact_pairs
            if isinstance(pair, dict)
        ]
        if not pair_values:
            locations = payload.get("locations") or [country]
            queries = payload.get("search_terms") or fallback_queries
            pair_values = [(str(query), str(location)) for query in queries for location in locations]
        for source_name in sources:
            if not _source_country_allowed(source_name, country):
                continue
            for query, location in pair_values:
                rows.append(
                    {
                        "source_name": source_name,
                        "country": country,
                        "query": query,
                        "location": location,
                        "search_url": build_search_url(source_name, query, location, country),
                        "generated_at": generated_at,
                        "last_checked_at": "",
                        "notes": "Manual search URL; open and review manually.",
                    }
                )
    if include_company_pages:
        rows.extend(_company_page_rows(generated_at))
    return rows


def write_manual_search_urls(rows: list[dict[str, Any]], *, report_date: str | None = None) -> dict[str, str]:
    date_part = report_date or today_yyyymmdd()
    path = REPORTS_DIR / f"manual_search_urls_{date_part}.csv"
    write_csv(path, rows, MANUAL_SEARCH_FIELDS)
    return {"csv": str(path)}


def generate_and_save_manual_urls(*, mode: str = "normal", db_path: Path | None = None) -> dict[str, Any]:
    rows = generate_manual_search_urls(mode=mode)
    paths = write_manual_search_urls(rows)
    if db_path is not None:
        from .database import upsert_manual_search_urls

        upsert_manual_search_urls(db_path, rows)
    return {"rows": rows, "paths": paths}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate manual job-search URLs.")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--mode", choices=["strict", "normal", "broad", "backfill"], default="normal")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.generate:
        result = generate_and_save_manual_urls(mode=args.mode, db_path=args.db)
        print(json.dumps({"count": len(result["rows"]), "paths": result["paths"]}, ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
