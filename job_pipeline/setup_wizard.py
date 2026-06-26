from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from .config_loader import PUBLIC_CONFIGS, PublicConfigSpec
from .search_scope import ALLOWED_SITES, normalize_sites, validate_search_scope
from .utils import load_yaml


CREATE_ORDER = [
    "search_scope",
    "application_campaign",
    "apply_profile",
    "resume_profile_paths",
    "scoring_rules",
    "master_resume",
]


def _load_example(spec: PublicConfigSpec) -> dict[str, Any]:
    data = load_yaml(spec.example_path) if spec.example_path.exists() else {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml  # type: ignore

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{text}{suffix}: ").strip()
    return answer or default


def _prompt_list(text: str, default: list[str]) -> list[str]:
    value = _prompt(text, ", ".join(default))
    return [item.strip() for item in value.split(",") if item.strip()]


def _prompt_int(text: str, default: int) -> int:
    while True:
        value = _prompt(text, str(default))
        try:
            parsed = int(value)
        except ValueError:
            print("Please enter a whole number.")
            continue
        if parsed < 0:
            print("Please enter zero or a positive number.")
            continue
        return parsed


def _prompt_yes_no(text: str, default: bool = False) -> bool:
    default_text = "y" if default else "n"
    value = _prompt(text, default_text).lower()
    return value in {"y", "yes", "true", "1"}


def _search_scope_answers(example: dict[str, Any]) -> dict[str, Any]:
    search = example.get("search") if isinstance(example.get("search"), dict) else {}
    countries = example.get("countries") if isinstance(example.get("countries"), dict) else {}
    default_country_names = [name for name, payload in countries.items() if isinstance(payload, dict) and payload.get("enabled", True)]
    target_countries = _prompt_list("Target countries", default_country_names or ["Canada"])
    sites = normalize_sites(_prompt_list("Preferred job boards", search.get("sites") or ["linkedin", "indeed", "google"]))
    min_score = _prompt_int("Minimum score threshold", int((example.get("filters") or {}).get("min_score") or 35))

    output = dict(example)
    output["search"] = dict(search)
    output["search"]["sites"] = sites
    configured_countries: dict[str, dict[str, Any]] = {}
    for country in target_countries:
        existing = countries.get(country) if isinstance(countries.get(country), dict) else {}
        default_locations = existing.get("locations") or [f"Remote, {country}"]
        default_terms = existing.get("search_terms") or ["Data Analyst"]
        configured_countries[country] = {
            "enabled": True,
            "locations": _prompt_list(f"Locations for {country}", list(default_locations)),
            "search_terms": _prompt_list(f"Role keywords for {country}", list(default_terms)),
        }
    for country, payload in countries.items():
        if country not in configured_countries and isinstance(payload, dict):
            disabled = dict(payload)
            disabled["enabled"] = False
            configured_countries[str(country)] = disabled
    output["countries"] = configured_countries
    output["filters"] = dict(example.get("filters") or {})
    output["filters"]["min_score"] = min_score
    validate_search_scope(output)
    return output


def _campaign_answers(example: dict[str, Any]) -> dict[str, Any]:
    output = dict(example)
    campaign = dict(output.get("campaign") or {})
    targets = dict(campaign.get("daily_targets") or {})
    targets["deep_tailor"] = _prompt_int("Daily deep-tailor quota", int(targets.get("deep_tailor") or 2))
    targets["standard_tailor"] = _prompt_int("Daily standard-tailor quota", int(targets.get("standard_tailor") or 5))
    targets["quick_apply"] = _prompt_int("Daily quick-apply review quota", int(targets.get("quick_apply") or 10))
    campaign["daily_targets"] = targets
    tailoring_enabled = _prompt_yes_no("Enable manual resume tailoring workflow", False)
    allow = {"deep_tailor": tailoring_enabled, "standard_tailor": tailoring_enabled, "quick_apply": False, "hold": False, "skip": False}
    campaign["allow_manual_generate_resume"] = allow
    campaign["allow_manual_generate_answer_pack"] = allow
    output["campaign"] = campaign
    return output


def _resume_path_answers(example: dict[str, Any]) -> dict[str, Any]:
    output = dict(example)
    profiles = output.get("profiles") if isinstance(output.get("profiles"), dict) else {}
    for profile, payload in profiles.items():
        if not isinstance(payload, dict):
            continue
        pdf = _prompt(f"PDF resume path for {profile} (optional)", str(payload.get("pdf") or ""))
        docx = _prompt(f"DOCX resume path for {profile} (optional)", str(payload.get("docx") or ""))
        payload["pdf"] = pdf
        payload["docx"] = docx
    output["profiles"] = profiles
    return output


def planned_files() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name in CREATE_ORDER:
        spec = PUBLIC_CONFIGS[name]
        rows.append(
            {
                "name": name,
                "local_path": str(spec.local_path),
                "example_path": str(spec.example_path),
                "action": "overwrite" if spec.local_path.exists() else "create",
            }
        )
    return rows


def initialize(*, force: bool = False, dry_run: bool = False) -> list[Path]:
    created: list[Path] = []
    if dry_run:
        print("Dry run: no files will be written.")
        print(json.dumps(planned_files(), indent=2))
        return created

    for name in CREATE_ORDER:
        spec = PUBLIC_CONFIGS[name]
        if spec.local_path.exists() and not force:
            print(f"Keeping existing local config: {spec.local_path}")
            continue
        if not spec.example_path.exists():
            print(f"Skipping {spec.local_path}; example is missing: {spec.example_path}")
            continue

        if name == "search_scope":
            data = _search_scope_answers(_load_example(spec))
            _write_yaml(spec.local_path, data)
        elif name == "application_campaign":
            data = _campaign_answers(_load_example(spec))
            _write_yaml(spec.local_path, data)
        elif name == "resume_profile_paths":
            data = _resume_path_answers(_load_example(spec))
            _write_yaml(spec.local_path, data)
        else:
            spec.local_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(spec.example_path, spec.local_path)
        created.append(spec.local_path)
        print(f"Created {spec.local_path}")
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize local, non-sensitive job-pipeline config files.")
    parser.add_argument("--init", action="store_true", help="Create local config files from public examples.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing local config files.")
    parser.add_argument("--dry-run", action="store_true", help="Print the files that would be created without writing anything.")
    args = parser.parse_args(argv)

    if args.dry_run:
        initialize(force=args.force, dry_run=True)
        return 0
    if not args.init:
        parser.print_help()
        return 0
    initialize(force=args.force, dry_run=False)
    print("Setup complete. Review config/search_scope.yaml before running a real search.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
