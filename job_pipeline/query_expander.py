from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .utils import CONFIG_DIR, load_yaml, stable_id, today_yyyymmdd

EXPANDED_QUERIES_PATH = CONFIG_DIR / "expanded_queries.yaml"
ROLE_FAMILIES_PATH = CONFIG_DIR / "role_families.yaml"
SEARCH_MODES_PATH = CONFIG_DIR / "search_modes.yaml"

MODE_NAMES = {"strict", "normal", "broad", "backfill"}
COUNTRY_LABELS = {
    "canada": "Canada",
    "singapore": "Singapore",
    "hong_kong": "Hong Kong",
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
DEFAULT_ROLE_FAMILY_SETTINGS = {
    "enabled_families": [],
    "mode_families": {
        "strict": ["digital_assets_research", "financial_data_analysis", "risk_fraud_compliance"],
        "normal": ["digital_assets_research", "financial_data_analysis", "risk_fraud_compliance", "technical_operations", "banking_operations"],
        "broad": ["digital_assets_research", "financial_data_analysis", "risk_fraud_compliance", "technical_operations", "banking_operations", "ai_data_governance"],
        "backfill": ["digital_assets_research", "financial_data_analysis", "risk_fraud_compliance", "technical_operations", "banking_operations", "ai_data_governance"],
    },
    "max_terms_per_family": {"strict": 8, "normal": 9, "broad": 11, "backfill": 11},
    "max_role_families_per_run": {"strict": 3, "normal": 5, "broad": 6, "backfill": 6},
}

QueryPair = tuple[str, str, str, str]


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


def load_role_families(path: Path = ROLE_FAMILIES_PATH) -> dict[str, Any]:
    data = load_yaml(path) or {}
    return data if isinstance(data, dict) else {}


def _role_family_settings(role_config: dict[str, Any]) -> dict[str, Any]:
    settings = dict(DEFAULT_ROLE_FAMILY_SETTINGS)
    settings["mode_families"] = dict(DEFAULT_ROLE_FAMILY_SETTINGS["mode_families"])
    settings["max_terms_per_family"] = dict(DEFAULT_ROLE_FAMILY_SETTINGS["max_terms_per_family"])
    settings["max_role_families_per_run"] = dict(DEFAULT_ROLE_FAMILY_SETTINGS["max_role_families_per_run"])
    overlay = role_config.get("settings") if isinstance(role_config.get("settings"), dict) else {}
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            settings[key].update(value)
        else:
            settings[key] = value
    return settings


def _family_payloads(role_config: dict[str, Any]) -> dict[str, Any]:
    families = role_config.get("families") if isinstance(role_config.get("families"), dict) else {}
    return families if isinstance(families, dict) else {}


def _family_terms(payload: dict[str, Any], *, max_terms: int | None = None) -> list[str]:
    terms = payload.get("search_terms") or payload.get("base_titles") or []
    output = _dedupe([str(item) for item in terms])
    return output[:max_terms] if max_terms and max_terms > 0 else output


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


def _selected_role_families(
    mode: str,
    *,
    role_config: dict[str, Any],
    legacy_config: dict[str, Any],
    query_family: str | None = None,
) -> tuple[list[str], bool]:
    families = _family_payloads(role_config)
    legacy_families = legacy_config.get("role_families") if isinstance(legacy_config.get("role_families"), dict) else {}
    if query_family:
        if query_family in families:
            return [query_family], False
        if query_family in legacy_families:
            return [query_family], True
        expected = sorted(set(families) | set(legacy_families))
        raise ValueError(f"Unknown query family: {query_family}. Expected one of {expected}")
    if not families:
        return list(legacy_families), True

    settings = _role_family_settings(role_config)
    enabled = [str(item) for item in settings.get("enabled_families") or families.keys()]
    mode_families = [str(item) for item in (settings.get("mode_families") or {}).get(mode, enabled)]
    selected = [family for family in mode_families if family in families and family in enabled]
    max_families = int((settings.get("max_role_families_per_run") or {}).get(mode) or 0)
    return (selected[:max_families] if max_families > 0 else selected), False


def _dedupe_specs(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    output: list[dict[str, str]] = []
    for item in items:
        query = " ".join(str(item.get("query") or "").split())
        marker = query.lower()
        if not query or marker in seen:
            continue
        seen.add(marker)
        output.append({"query": query, "role_family": str(item.get("role_family") or "")})
    return output


def expand_query_specs(
    mode: str = "normal",
    *,
    config: dict[str, Any] | None = None,
    role_config: dict[str, Any] | None = None,
    max_queries: int | None = None,
    query_family: str | None = None,
) -> list[dict[str, str]]:
    """Build search queries with role-family metadata while preserving bounded modes."""
    mode = str(mode or "normal").lower()
    if mode not in MODE_NAMES:
        raise ValueError(f"Unknown search mode: {mode}")
    config = config or load_expanded_queries()
    role_config = role_config or load_role_families()
    selected_families, use_legacy = _selected_role_families(
        mode,
        role_config=role_config,
        legacy_config=config,
        query_family=query_family,
    )
    modifiers = _mode_modifiers(config, mode)
    specs: list[dict[str, str]] = []

    if use_legacy:
        bases = _base_titles(config, query_family=query_family)
        base_specs = [{"query": title, "role_family": query_family or ""} for title in bases]
    else:
        settings = _role_family_settings(role_config)
        max_terms = int((settings.get("max_terms_per_family") or {}).get(mode) or 0)
        families = _family_payloads(role_config)
        base_specs = []
        for family in selected_families:
            for term in _family_terms(families.get(family) or {}, max_terms=max_terms):
                base_specs.append({"query": term, "role_family": family})

    specs.extend(base_specs)
    if mode in {"normal", "broad", "backfill"}:
        for modifier in modifiers:
            marker = modifier.lower()
            for item in base_specs:
                query = item["query"]
                if marker in query.lower():
                    continue
                specs.append({"query": f"{query} {modifier}", "role_family": item.get("role_family", "")})

    if mode == "backfill" and not query_family:
        generic_terms = [str(item) for item in config.get("generic_backfill_terms") or []]
        specs.extend({"query": item, "role_family": role_family_for_query(item, role_config=role_config, config=config)} for item in generic_terms)
        for item in generic_terms:
            for modifier in modifiers[:8]:
                specs.append(
                    {
                        "query": f"{item} {modifier}",
                        "role_family": role_family_for_query(item, role_config=role_config, config=config),
                    }
                )

    deduped = _dedupe_specs(specs)
    return deduped[:max_queries] if max_queries else deduped


def expand_queries(
    mode: str = "normal",
    *,
    config: dict[str, Any] | None = None,
    role_config: dict[str, Any] | None = None,
    max_queries: int | None = None,
    query_family: str | None = None,
) -> list[str]:
    """Build role-family queries for a search mode without mutating config."""
    return [
        item["query"]
        for item in expand_query_specs(
            mode,
            config=config,
            role_config=role_config,
            max_queries=max_queries,
            query_family=query_family,
        )
    ]


def role_family_for_query(
    query: str,
    *,
    role_config: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    query_text = " ".join(str(query or "").lower().split())
    if not query_text:
        return ""
    role_config = role_config or load_role_families()
    config = config or load_expanded_queries()
    for family, payload in _family_payloads(role_config).items():
        for term in _family_terms(payload):
            marker = term.lower()
            if query_text == marker or query_text.startswith(f"{marker} "):
                return str(family)
    for family, payload in (config.get("role_families") or {}).items():
        if not isinstance(payload, dict):
            continue
        for term in _family_terms(payload):
            marker = term.lower()
            if query_text == marker or query_text.startswith(f"{marker} "):
                return str(family)
    return ""


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


def _pairs_from_config(config: dict[str, Any]) -> list[QueryPair]:
    pairs: list[QueryPair] = []
    for country, payload in (config.get("countries") or {}).items():
        exact_pairs = payload.get("query_location_pairs") or []
        if exact_pairs:
            for item in exact_pairs:
                if isinstance(item, dict):
                    pairs.append(
                        (
                            str(country),
                            str(item.get("query") or ""),
                            str(item.get("location") or ""),
                            str(item.get("role_family") or ""),
                        )
                    )
            continue
        for query in payload.get("search_terms") or []:
            for location in payload.get("locations") or []:
                pairs.append((str(country), str(query), str(location), role_family_for_query(str(query))))
    return pairs


def _config_from_pairs(base_config: dict[str, Any], pairs: list[QueryPair]) -> dict[str, Any]:
    countries: dict[str, dict[str, Any]] = {}
    for country, query, location, role_family in pairs:
        payload = countries.setdefault(country, {"search_terms": [], "locations": [], "query_location_pairs": []})
        if query not in payload["search_terms"]:
            payload["search_terms"].append(query)
        if location not in payload["locations"]:
            payload["locations"].append(location)
        pair = {"query": query, "location": location}
        if role_family:
            pair["role_family"] = role_family
        payload["query_location_pairs"].append(pair)
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


def rotate_query_location_pairs(pairs: list[QueryPair], *, mode: str, rotation_date: str | date | None = None, limit: int | None = None) -> list[QueryPair]:
    if not limit or limit <= 0 or len(pairs) <= limit:
        return list(pairs)
    ordered = sorted(pairs, key=lambda item: stable_id(*item))
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
    settings = get_search_mode(mode, modes_path)
    expanded_config = expanded_config or load_expanded_queries()
    query_limit = max_queries if max_queries is not None else int(settings.get("max_queries_per_country") or 0) or None
    query_specs = expand_query_specs(settings["name"], config=expanded_config, max_queries=query_limit, query_family=query_family)
    queries = [item["query"] for item in query_specs]
    groups = location_groups(expanded_config)
    allowed_countries = _country_filter(country)
    countries: dict[str, dict[str, Any]] = {}
    pairs: list[QueryPair] = []
    for country_name, locations in groups.items():
        if allowed_countries and country_name not in allowed_countries:
            continue
        selected_locations = locations[:max_locations] if max_locations and max_locations > 0 else locations
        countries[country_name] = {
            "locations": selected_locations,
            "search_terms": queries,
        }
        for item in query_specs:
            for location in selected_locations:
                pairs.append((country_name, item["query"], location, item.get("role_family") or ""))
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
    role_families_by_country = {}
    role_family_counts: Counter[str] = Counter()
    for country, payload in countries.items():
        exact_pairs = payload.get("query_location_pairs") or []
        if exact_pairs:
            pairs_by_country[country] = len(exact_pairs)
            families = Counter(
                str(pair.get("role_family") or role_family_for_query(str(pair.get("query") or "")) or "unknown")
                for pair in exact_pairs
                if isinstance(pair, dict)
            )
        else:
            pairs_by_country[country] = len(payload.get("search_terms") or []) * len(payload.get("locations") or [])
            families = Counter()
            for query in payload.get("search_terms") or []:
                family = role_family_for_query(str(query)) or "unknown"
                families[family] += len(payload.get("locations") or [])
        role_families_by_country[country] = dict(sorted(families.items()))
        role_family_counts.update(families)
    total_pairs = sum(pairs_by_country.values())
    sleep_seconds = float(settings.get("sleep_seconds") or 0)
    return {
        "mode": mode,
        "countries": list(countries.keys()),
        "queries": {country: len(payload.get("search_terms") or []) for country, payload in countries.items()},
        "locations": {country: len(payload.get("locations") or []) for country, payload in countries.items()},
        "query_location_pairs": pairs_by_country,
        "role_families": role_families_by_country,
        "role_family_query_location_pairs": dict(sorted(role_family_counts.items())),
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
    specs = expand_query_specs(
        args.mode,
        max_queries=args.max or int(settings.get("max_queries_per_country") or 0) or None,
        query_family=args.query_family,
    )
    print(json.dumps({"mode": args.mode, "count": len(specs), "queries": specs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
