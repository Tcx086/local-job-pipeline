from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .search_scope import SearchScopeError, load_search_scope, search_scope_to_search_config
from .utils import CONFIG_DIR, load_yaml, stable_id, today_yyyymmdd

EXPANDED_QUERIES_PATH = CONFIG_DIR / "expanded_queries.yaml"
SEARCH_MODES_PATH = CONFIG_DIR / "search_modes.yaml"

MODE_NAMES = {"strict", "normal", "broad", "backfill"}
COUNTRY_LABELS = {
    "canada": "Canada",
    "united_states": "United States",
}
DEFAULT_SOURCE_SITES = ["indeed", "linkedin", "google", "glassdoor", "zip_recruiter"]
DEFAULT_REPORTING_CONFIG = {
    "always_include_top_n": 20,
    "dashboard_default_min_score": 35,
    "markdown_min_score": 35,
    "resume_generation_min_score": "use mode config",
}
DEFAULT_ROTATION_CONFIG = {
    "enabled": True,
    "daily_query_location_pairs": {"normal": 80, "broad": 120, "backfill": 160},
    "strategy": "stable_hash_by_date",
}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        cleaned = " ".join(str(item or "").split())
        marker = cleaned.lower()
        if not cleaned or marker in seen:
            continue
        seen.add(marker)
        output.append(cleaned)
    return output


def _search_modes_doc(path: Path = SEARCH_MODES_PATH) -> dict[str, Any]:
    data = load_yaml(path) or {}
    return data if isinstance(data, dict) else {}


def load_search_modes(path: Path = SEARCH_MODES_PATH) -> dict[str, Any]:
    data = _search_modes_doc(path)
    modes = data.get("modes") if isinstance(data, dict) else {}
    return modes if isinstance(modes, dict) else {}


def load_reporting_config(path: Path = SEARCH_MODES_PATH) -> dict[str, Any]:
    data = _search_modes_doc(path)
    reporting = data.get("reporting") if isinstance(data, dict) else {}
    output = dict(DEFAULT_REPORTING_CONFIG)
    if isinstance(reporting, dict):
        output.update(reporting)
    output["always_include_top_n"] = int(output.get("always_include_top_n") or 20)
    output["dashboard_default_min_score"] = int(output.get("dashboard_default_min_score") or 35)
    output["markdown_min_score"] = int(output.get("markdown_min_score") or 35)
    return output


def load_rotation_config(path: Path = SEARCH_MODES_PATH) -> dict[str, Any]:
    data = _search_modes_doc(path)
    rotation = data.get("rotation") if isinstance(data, dict) else {}
    output = dict(DEFAULT_ROTATION_CONFIG)
    output["daily_query_location_pairs"] = dict(DEFAULT_ROTATION_CONFIG["daily_query_location_pairs"])
    if isinstance(rotation, dict):
        for key, value in rotation.items():
            if key == "daily_query_location_pairs" and isinstance(value, dict):
                output[key].update(value)
            else:
                output[key] = value
    output["enabled"] = bool(output.get("enabled", True))
    output["daily_query_location_pairs"] = {
        str(key): int(value) for key, value in (output.get("daily_query_location_pairs") or {}).items()
    }
    return output


def get_search_mode(mode: str = "normal", path: Path = SEARCH_MODES_PATH) -> dict[str, Any]:
    normalized = str(mode or "normal").lower()
    modes = load_search_modes(path)
    if normalized not in modes:
        raise ValueError(f"Unknown search mode: {mode}. Expected one of {sorted(modes or MODE_NAMES)}")
    payload = dict(modes[normalized] or {})
    payload["name"] = normalized
    payload["days_back"] = int(payload.get("days_back") or 30)
    payload["min_score_report"] = int(payload.get("min_score_report") or 55)
    payload["generate_resume_min_score"] = int(payload.get("generate_resume_min_score") or 70)
    payload["results_wanted_per_query"] = int(payload.get("results_wanted_per_query") or 25)
    payload["include_maybe"] = bool(payload.get("include_maybe", True))
    payload["hard_skip_only"] = bool(payload.get("hard_skip_only", True))
    return payload


def load_expanded_queries(path: Path = EXPANDED_QUERIES_PATH) -> dict[str, Any]:
    data = load_yaml(path) or {}
    return data if isinstance(data, dict) else {}


def _base_titles(config: dict[str, Any], query_family: str | None = None) -> list[str]:
    families = config.get("role_families") or {}
    if query_family:
        family = families.get(query_family)
        if not isinstance(family, dict):
            raise ValueError(f"Unknown query family: {query_family}. Expected one of {sorted(families)}")
        return _dedupe([str(item) for item in family.get("base_titles") or []])
    titles: list[str] = []
    for family in families.values():
        if isinstance(family, dict):
            titles.extend(str(item) for item in family.get("base_titles") or [])
    return _dedupe(titles)


def _mode_modifiers(config: dict[str, Any], mode: str) -> list[str]:
    if mode == "strict":
        return []
    if mode == "normal":
        return _dedupe([str(item) for item in config.get("selected_industry_modifiers") or []])
    return _dedupe([str(item) for item in config.get("industry_modifiers") or []])


def expand_queries(
    mode: str = "normal",
    *,
    config: dict[str, Any] | None = None,
    max_queries: int | None = None,
    query_family: str | None = None,
) -> list[str]:
    """Build role-family queries for a search mode without mutating config."""
    mode = str(mode or "normal").lower()
    if mode not in MODE_NAMES:
        raise ValueError(f"Unknown search mode: {mode}")
    config = config or load_expanded_queries()
    bases = _base_titles(config, query_family=query_family)
    modifiers = _mode_modifiers(config, mode)
    queries: list[str] = list(bases)

    if mode in {"normal", "broad", "backfill"}:
        for title in bases:
            for modifier in modifiers:
                marker = modifier.lower()
                if marker in title.lower():
                    continue
                queries.append(f"{title} {modifier}")

    if mode == "backfill" and not query_family:
        queries.extend(str(item) for item in config.get("generic_backfill_terms") or [])
        for item in config.get("generic_backfill_terms") or []:
            for modifier in modifiers[:8]:
                queries.append(f"{item} {modifier}")

    deduped = _dedupe(queries)
    return deduped[:max_queries] if max_queries else deduped


def location_groups(config: dict[str, Any] | None = None) -> dict[str, list[str]]:
    config = config or load_expanded_queries()
    groups: dict[str, list[str]] = {}
    for key, values in (config.get("location_groups") or {}).items():
        groups[COUNTRY_LABELS.get(str(key), str(key))] = _dedupe([str(item) for item in values or []])
    return groups


def _source_site_list(source_sites: list[str] | str | None) -> list[str]:
    if source_sites is None:
        return list(DEFAULT_SOURCE_SITES)
    if isinstance(source_sites, str):
        source_sites = [item.strip() for item in source_sites.split(",")]
    return _dedupe([str(item).strip().lower() for item in source_sites if str(item).strip()]) or list(DEFAULT_SOURCE_SITES)


def _country_filter(countries: list[str] | str | None) -> set[str] | None:
    if not countries:
        return None
    if isinstance(countries, str):
        countries = [countries]
    normalized = {COUNTRY_LABELS.get(str(item).strip().lower().replace(" ", "_"), str(item).strip()) for item in countries if str(item).strip()}
    return normalized or None


def _pairs_from_config(config: dict[str, Any]) -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    for country, payload in (config.get("countries") or {}).items():
        exact_pairs = payload.get("query_location_pairs") or []
        if exact_pairs:
            for item in exact_pairs:
                if isinstance(item, dict):
                    pairs.append((str(country), str(item.get("query") or ""), str(item.get("location") or "")))
            continue
        for query in payload.get("search_terms") or []:
            for location in payload.get("locations") or []:
                pairs.append((str(country), str(query), str(location)))
    return pairs


def _config_from_pairs(base_config: dict[str, Any], pairs: list[tuple[str, str, str]]) -> dict[str, Any]:
    countries: dict[str, dict[str, Any]] = {}
    for country, query, location in pairs:
        payload = countries.setdefault(country, {"search_terms": [], "locations": [], "query_location_pairs": []})
        if query not in payload["search_terms"]:
            payload["search_terms"].append(query)
        if location not in payload["locations"]:
            payload["locations"].append(location)
        payload["query_location_pairs"].append({"query": query, "location": location})
    return {"settings": dict(base_config.get("settings") or {}), "countries": countries}


def _date_value(value: str | date | None = None) -> date:
    if isinstance(value, date):
        return value
    if value:
        cleaned = str(value)
        for fmt in ["%Y-%m-%d", "%Y%m%d"]:
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                pass
    return datetime.strptime(today_yyyymmdd(), "%Y%m%d").date()


def rotate_query_location_pairs(pairs: list[tuple[str, str, str]], *, mode: str, rotation_date: str | date | None = None, limit: int | None = None) -> list[tuple[str, str, str]]:
    if not limit or limit <= 0 or len(pairs) <= limit:
        return list(pairs)
    ordered = sorted(pairs, key=lambda item: stable_id(item[0], item[1], item[2]))
    day = _date_value(rotation_date)
    offset = (day.toordinal() * limit) % len(ordered)
    return [ordered[(offset + idx) % len(ordered)] for idx in range(limit)]


def apply_pair_limit(config: dict[str, Any], max_query_location_pairs: int | None) -> dict[str, Any]:
    pairs = _pairs_from_config(config)
    if max_query_location_pairs and max_query_location_pairs > 0:
        pairs = pairs[:max_query_location_pairs]
    return _config_from_pairs(config, pairs)


def build_search_config(
    mode: str = "normal",
    *,
    expanded_config: dict[str, Any] | None = None,
    modes_path: Path = SEARCH_MODES_PATH,
    max_queries: int | None = None,
    max_locations: int | None = None,
    max_query_location_pairs: int | None = None,
    query_family: str | None = None,
    country: list[str] | str | None = None,
    source_sites: list[str] | str | None = None,
    no_rotation: bool = False,
    rotation_date: str | date | None = None,
) -> dict[str, Any]:
    if expanded_config is None:
        try:
            scope = load_search_scope()
            return search_scope_to_search_config(
                scope,
                mode=mode,
                max_queries=max_queries,
                max_locations=max_locations,
                max_query_location_pairs=max_query_location_pairs,
                country=country,
                source_sites=source_sites,
            )
        except FileNotFoundError:
            pass
        except SearchScopeError:
            raise

    settings = get_search_mode(mode, modes_path)
    expanded_config = expanded_config or load_expanded_queries()
    query_limit = max_queries if max_queries is not None else int(settings.get("max_queries_per_country") or 0) or None
    queries = expand_queries(settings["name"], config=expanded_config, max_queries=query_limit, query_family=query_family)
    groups = location_groups(expanded_config)
    allowed_countries = _country_filter(country)
    countries: dict[str, dict[str, Any]] = {}
    for country_name, locations in groups.items():
        if allowed_countries and country_name not in allowed_countries:
            continue
        selected_locations = locations[:max_locations] if max_locations and max_locations > 0 else locations
        countries[country_name] = {
            "locations": selected_locations,
            "search_terms": queries,
        }
    base_config = {
        "settings": {
            "hours_old": settings["days_back"] * 24,
            "results_wanted": settings["results_wanted_per_query"],
            "sleep_seconds": 4,
            "verbose": 1,
            "linkedin_fetch_description": False,
            "site_name": _source_site_list(source_sites),
        },
        "countries": countries,
    }

    pairs = _pairs_from_config(base_config)
    rotation = load_rotation_config(modes_path)
    if not no_rotation and rotation.get("enabled") and mode in rotation.get("daily_query_location_pairs", {}):
        pairs = rotate_query_location_pairs(
            pairs,
            mode=mode,
            rotation_date=rotation_date,
            limit=int(rotation["daily_query_location_pairs"].get(mode) or 0),
        )
    if max_query_location_pairs and max_query_location_pairs > 0:
        pairs = pairs[:max_query_location_pairs]
    return _config_from_pairs(base_config, pairs)


def describe_search_plan(config: dict[str, Any], *, mode: str = "normal") -> dict[str, Any]:
    settings = config.get("settings") or {}
    source_sites = _source_site_list(settings.get("site_name"))
    countries = config.get("countries") or {}
    pairs_by_country = {}
    for country, payload in countries.items():
        exact_pairs = payload.get("query_location_pairs") or []
        if exact_pairs:
            pairs_by_country[country] = len(exact_pairs)
        else:
            pairs_by_country[country] = len(payload.get("search_terms") or []) * len(payload.get("locations") or [])
    total_pairs = sum(pairs_by_country.values())
    sleep_seconds = float(settings.get("sleep_seconds") or 0)
    return {
        "mode": mode,
        "countries": list(countries.keys()),
        "queries": {country: len(payload.get("search_terms") or []) for country, payload in countries.items()},
        "locations": {country: len(payload.get("locations") or []) for country, payload in countries.items()},
        "query_location_pairs": pairs_by_country,
        "total_query_location_pairs": total_pairs,
        "source_sites": source_sites,
        "estimated_external_calls": total_pairs * len(source_sites),
        "sleep_seconds_per_pair": sleep_seconds,
        "estimated_sleep_seconds": round(total_pairs * sleep_seconds, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview expanded job-search queries.")
    parser.add_argument("--mode", choices=sorted(MODE_NAMES), default="normal")
    parser.add_argument("--max", type=int, default=0, help="Preview at most N queries.")
    parser.add_argument("--query-family", default=None)
    args = parser.parse_args(argv)
    settings = get_search_mode(args.mode)
    queries = expand_queries(
        args.mode,
        max_queries=args.max or int(settings.get("max_queries_per_country") or 0) or None,
        query_family=args.query_family,
    )
    print(json.dumps({"mode": args.mode, "count": len(queries), "queries": queries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
