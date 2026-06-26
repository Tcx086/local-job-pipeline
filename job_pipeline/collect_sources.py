from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .collect_jobspy import collect_jobs
from .query_expander import build_search_config, get_search_mode
from .search_url_builder import generate_manual_search_urls


@dataclass
class CollectionResult:
    jobs: list[dict[str, Any]]
    manual_pages: list[dict[str, Any]]
    manual_search_urls: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    query_attempts: list[dict[str, Any]]


def _failed_attempts_to_errors(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for attempt in attempts:
        if bool(attempt.get("success")):
            continue
        errors.append(
            {
                "country": attempt.get("country") or "unknown",
                "source": attempt.get("source") or "jobspy",
                "query": attempt.get("query") or "unknown",
                "location": attempt.get("location") or "unknown",
                "error_message": attempt.get("error_message") or "unknown collection error",
            }
        )
    return errors


def collect_jobspy_from_config(
    config: dict[str, Any],
    *,
    hours_old: int | None = None,
    results_wanted: int | None = None,
    run_id: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    settings = config.get("settings", {})
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    query_attempts: list[dict[str, Any]] = []

    def collect_one(country: str, query: str, location: str) -> None:
        try:
            collected, attempts = collect_jobs(
                search_terms=[query],
                locations=[location],
                country=country,
                hours_old=hours_old or int(settings.get("hours_old", 24)),
                results_wanted=results_wanted or int(settings.get("results_wanted", 10)),
                site_name=settings.get("site_name"),
                sleep_seconds=float(settings.get("sleep_seconds", 4)),
                linkedin_fetch_description=bool(settings.get("linkedin_fetch_description", False)),
                verbose=int(settings.get("verbose", 1)),
                run_id=run_id,
                return_attempts=True,
            )
            rows.extend(collected)
            query_attempts.extend(attempts)
            errors.extend(_failed_attempts_to_errors(attempts))
        except Exception as exc:  # noqa: BLE001 - collectors must remain fault tolerant
            site_names = settings.get("site_name") or ["jobspy"]
            if isinstance(site_names, str):
                site_names = [site_names]
            for source in site_names:
                attempt = {
                    "run_id": run_id,
                    "source": source,
                    "country": country,
                    "query": query,
                    "location": location,
                    "raw_count": 0,
                    "success": False,
                    "error_message": str(exc),
                }
                query_attempts.append(attempt)
                errors.extend(_failed_attempts_to_errors([attempt]))

    for country, payload in config.get("countries", {}).items():
        exact_pairs = payload.get("query_location_pairs") or []
        if exact_pairs:
            for pair in exact_pairs:
                collect_one(country, str(pair.get("query") or ""), str(pair.get("location") or ""))
            continue
        for query in payload.get("search_terms", []) or ["configured_search_terms"]:
            for location in payload.get("locations", []) or ["configured_locations"]:
                collect_one(country, str(query), str(location))
    return rows, errors, query_attempts


def collect_sources(
    *,
    mode: str = "normal",
    hours_old: int | None = None,
    results_wanted: int | None = None,
    include_ats: bool = True,
    ats_source: str = "all",
    run_id: str = "",
    max_queries: int | None = None,
    max_locations: int | None = None,
    max_query_location_pairs: int | None = None,
    query_family: str | None = None,
    country: list[str] | str | None = None,
    source_sites: list[str] | str | None = None,
    no_rotation: bool = False,
) -> CollectionResult:
    mode_settings = get_search_mode(mode)
    search_config = build_search_config(
        mode,
        max_queries=max_queries,
        max_locations=max_locations,
        max_query_location_pairs=max_query_location_pairs,
        query_family=query_family,
        country=country,
        source_sites=source_sites,
        no_rotation=no_rotation,
    )
    config_settings = search_config.get("settings") or {}
    jobspy_rows, errors, query_attempts = collect_jobspy_from_config(
        search_config,
        hours_old=hours_old if hours_old is not None else int(config_settings.get("hours_old") or mode_settings["days_back"] * 24),
        results_wanted=results_wanted if results_wanted is not None else int(config_settings.get("results_wanted") or mode_settings["results_wanted_per_query"]),
        run_id=run_id,
    )
    ats_rows: list[dict[str, Any]] = []
    manual_pages: list[dict[str, Any]] = []
    if include_ats:
        try:
            from .collect_ats import collect_public_ats_jobs, load_ats_config

            ats_rows, manual_pages = collect_public_ats_jobs(load_ats_config(), source=ats_source)
        except Exception as exc:  # noqa: BLE001
            errors.append({"country": "unknown", "source": "ats", "query": ats_source, "location": "all_active", "error_message": str(exc)})
    manual_search_urls = generate_manual_search_urls(mode=mode, search_config=search_config)
    return CollectionResult(
        jobs=jobspy_rows + ats_rows,
        manual_pages=manual_pages,
        manual_search_urls=manual_search_urls,
        errors=errors,
        query_attempts=query_attempts,
    )
