from __future__ import annotations

from pathlib import Path
from typing import Any

from .config_loader import load_public_config, load_path_with_fallback
from .utils import CONFIG_DIR, load_yaml, stable_id


SEARCH_SCOPE_LOCAL = CONFIG_DIR / "search_scope.yaml"
SEARCH_SCOPE_EXAMPLE = CONFIG_DIR / "search_scope.example.yaml"
ALLOWED_SITES = {"indeed", "linkedin", "google", "glassdoor", "zip_recruiter"}


class SearchScopeError(ValueError):
    pass


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _clean_strings(value: Any) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in _as_list(value):
        cleaned = " ".join(str(item or "").split())
        marker = cleaned.lower()
        if cleaned and marker not in seen:
            seen.add(marker)
            output.append(cleaned)
    return output


def _positive_int(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SearchScopeError(f"{field} must be a positive integer.") from exc
    if number <= 0:
        raise SearchScopeError(f"{field} must be positive.")
    return number


def _positive_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SearchScopeError(f"{field} must be a positive number.") from exc
    if number <= 0:
        raise SearchScopeError(f"{field} must be positive.")
    return number


def normalize_sites(value: Any) -> list[str]:
    sites = [site.lower().replace("-", "_") for site in _clean_strings(value)]
    invalid = sorted(site for site in sites if site not in ALLOWED_SITES)
    if invalid:
        raise SearchScopeError(
            "Invalid search site(s): "
            + ", ".join(invalid)
            + f". Expected one or more of: {', '.join(sorted(ALLOWED_SITES))}."
        )
    return sites


def load_search_scope(path: Path | None = None) -> dict[str, Any]:
    if path is not None:
        data = load_yaml(path)
    else:
        data = load_public_config("search_scope", required=True)
    if not isinstance(data, dict):
        raise SearchScopeError("Search scope config must be a YAML mapping.")
    validate_search_scope(data)
    return data


def load_search_scope_optional(path: Path = SEARCH_SCOPE_LOCAL) -> dict[str, Any]:
    data = load_path_with_fallback(path, required=True)
    if not isinstance(data, dict):
        raise SearchScopeError("Search scope config must be a YAML mapping.")
    validate_search_scope(data)
    return data


def enabled_countries(scope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    countries = scope.get("countries") if isinstance(scope.get("countries"), dict) else {}
    enabled: dict[str, dict[str, Any]] = {}
    for name, payload in countries.items():
        if not isinstance(payload, dict):
            continue
        if payload.get("enabled", True):
            enabled[str(name)] = payload
    return enabled


def validate_search_scope(scope: dict[str, Any]) -> None:
    search = scope.get("search") if isinstance(scope.get("search"), dict) else {}
    _positive_int(search.get("results_wanted", 10), "search.results_wanted")
    _positive_float(search.get("sleep_seconds", 4), "search.sleep_seconds")
    _positive_int(search.get("hours_old", 24), "search.hours_old")
    normalize_sites(search.get("sites") or ["linkedin", "indeed", "google"])

    countries = enabled_countries(scope)
    if not countries:
        raise SearchScopeError("At least one country must be enabled in config/search_scope.yaml.")
    for country, payload in countries.items():
        locations = _clean_strings(payload.get("locations"))
        terms = _clean_strings(payload.get("search_terms"))
        if not locations:
            raise SearchScopeError(f"Enabled country {country!r} must include at least one location.")
        if not terms:
            raise SearchScopeError(f"Enabled country {country!r} must include at least one search term.")


def _country_filter(countries: list[str] | str | None) -> set[str] | None:
    values = {item.lower() for item in _clean_strings(countries)}
    return values or None


def _pairs_from_countries(countries: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    for country, payload in countries.items():
        for query in _clean_strings(payload.get("search_terms")):
            for location in _clean_strings(payload.get("locations")):
                pairs.append((country, query, location))
    return pairs


def _config_from_pairs(settings: dict[str, Any], filters: dict[str, Any], pairs: list[tuple[str, str, str]]) -> dict[str, Any]:
    countries: dict[str, dict[str, Any]] = {}
    for country, query, location in pairs:
        payload = countries.setdefault(country, {"search_terms": [], "locations": [], "query_location_pairs": []})
        if query not in payload["search_terms"]:
            payload["search_terms"].append(query)
        if location not in payload["locations"]:
            payload["locations"].append(location)
        payload["query_location_pairs"].append({"query": query, "location": location})
    return {"settings": settings, "countries": countries, "filters": filters}


def rotate_scope_pairs(pairs: list[tuple[str, str, str]], *, rotation_date: str, limit: int | None) -> list[tuple[str, str, str]]:
    if not limit or limit <= 0 or len(pairs) <= limit:
        return pairs
    ordered = sorted(pairs, key=lambda item: stable_id(item[0], item[1], item[2]))
    offset = int(stable_id(rotation_date, len(ordered)), 16) % len(ordered)
    return [ordered[(offset + idx) % len(ordered)] for idx in range(limit)]


def search_scope_to_search_config(
    scope: dict[str, Any],
    *,
    mode: str | None = None,
    max_queries: int | None = None,
    max_locations: int | None = None,
    max_query_location_pairs: int | None = None,
    country: list[str] | str | None = None,
    source_sites: list[str] | str | None = None,
) -> dict[str, Any]:
    validate_search_scope(scope)
    search = scope.get("search") if isinstance(scope.get("search"), dict) else {}
    sites = normalize_sites(source_sites or search.get("sites") or ["linkedin", "indeed", "google"])
    allowed = _country_filter(country)
    countries: dict[str, dict[str, Any]] = {}
    for country_name, payload in enabled_countries(scope).items():
        if allowed and country_name.lower() not in allowed:
            continue
        locations = _clean_strings(payload.get("locations"))
        terms = _clean_strings(payload.get("search_terms"))
        if max_locations and max_locations > 0:
            locations = locations[:max_locations]
        if max_queries and max_queries > 0:
            terms = terms[:max_queries]
        countries[country_name] = {"locations": locations, "search_terms": terms}
    if not countries:
        raise SearchScopeError("No enabled countries match the requested --country filter.")

    settings = {
        "hours_old": _positive_int(search.get("hours_old", 24), "search.hours_old"),
        "results_wanted": _positive_int(search.get("results_wanted", 10), "search.results_wanted"),
        "sleep_seconds": _positive_float(search.get("sleep_seconds", 4), "search.sleep_seconds"),
        "mode": mode or search.get("mode") or "normal",
        "verbose": int(search.get("verbose", 1) or 1),
        "linkedin_fetch_description": bool(search.get("linkedin_fetch_description", False)),
        "site_name": sites,
    }
    filters = scope.get("filters") if isinstance(scope.get("filters"), dict) else {}
    pairs = _pairs_from_countries(countries)
    if max_query_location_pairs and max_query_location_pairs > 0:
        pairs = pairs[:max_query_location_pairs]
    return _config_from_pairs(settings, filters, pairs)
