from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
from typing import Any

from .utils import CONFIG_DIR, load_yaml, normalize_space

ATS_TYPES = {"greenhouse", "lever", "ashby", "workday", "oracle", "successfactors", "manual_url", "unknown"}


@dataclass
class CompanyRecord:
    display_name: str
    canonical_company: str
    region_focus: list[str]
    industry_tags: list[str]
    ats_type: str = "unknown"
    ats_token: str = ""
    careers_url: str = ""
    priority: int = 3
    notes: str = ""


def canonical_company_name(name: Any) -> str:
    text = normalize_space(name).lower()
    replacements = {
        "coinbase canada": "coinbase",
        "stripe canada": "stripe",
        "capital one canada": "capital one",
        "morningstar canada": "morningstar",
    }
    text = replacements.get(text, text)
    for suffix in [" inc", " ltd", " limited", " corp", " corporation", " canada"]:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return normalize_space(text)


def _merge_record(records: dict[str, CompanyRecord], record: CompanyRecord) -> None:
    existing = records.get(record.canonical_company)
    if not existing:
        records[record.canonical_company] = record
        return
    existing.region_focus = sorted(set(existing.region_focus + record.region_focus))
    existing.industry_tags = sorted(set(existing.industry_tags + record.industry_tags))
    if existing.ats_type == "unknown" and record.ats_type != "unknown":
        existing.ats_type = record.ats_type
        existing.ats_token = record.ats_token
    if not existing.careers_url and record.careers_url:
        existing.careers_url = record.careers_url
    existing.priority = min(existing.priority, record.priority)
    if record.notes and record.notes not in existing.notes:
        existing.notes = (existing.notes + " | " + record.notes).strip(" |")


def load_company_registry(
    company_sources_path=None,
    ats_sources_path=None,
) -> list[dict[str, Any]]:
    company_sources_path = company_sources_path or CONFIG_DIR / "company_sources.yaml"
    ats_sources_path = ats_sources_path or CONFIG_DIR / "ats_sources.yaml"
    company_sources = load_yaml(company_sources_path) or {}
    ats_sources = load_yaml(ats_sources_path) or {}
    records: dict[str, CompanyRecord] = {}

    for region, companies in company_sources.items():
        for company in companies or []:
            name = normalize_space(company)
            _merge_record(
                records,
                CompanyRecord(
                    display_name=name,
                    canonical_company=canonical_company_name(name),
                    region_focus=[region],
                    industry_tags=[],
                    ats_type="unknown",
                    priority=3,
                ),
            )

    for item in ats_sources.get("greenhouse", []) or []:
        token = item.get("board_token") or ""
        name = item.get("company_name") or token
        _merge_record(
            records,
            CompanyRecord(
                display_name=name,
                canonical_company=canonical_company_name(name),
                region_focus=item.get("country_focus") or [],
                industry_tags=item.get("tags") or [],
                ats_type="greenhouse",
                ats_token=token,
                priority=1,
                notes=item.get("notes") or "",
            ),
        )

    for item in ats_sources.get("lever", []) or []:
        token = item.get("lever_slug") or ""
        name = item.get("company_name") or token
        _merge_record(
            records,
            CompanyRecord(
                display_name=name,
                canonical_company=canonical_company_name(name),
                region_focus=item.get("country_focus") or [],
                industry_tags=item.get("tags") or [],
                ats_type="lever",
                ats_token=token,
                priority=1,
                notes=item.get("notes") or "",
            ),
        )

    for item in ats_sources.get("ashby", []) or []:
        token = item.get("ashby_board") or ""
        name = item.get("company_name") or token
        _merge_record(
            records,
            CompanyRecord(
                display_name=name,
                canonical_company=canonical_company_name(name),
                region_focus=item.get("country_focus") or [],
                industry_tags=item.get("tags") or [],
                ats_type="ashby",
                ats_token=token,
                priority=2,
                notes=item.get("notes") or "",
            ),
        )

    for item in ats_sources.get("company_pages", []) or []:
        name = item.get("company_name") or item.get("careers_url") or ""
        adapter_type = item.get("adapter_type") or "manual_url"
        if adapter_type not in ATS_TYPES:
            adapter_type = "manual_url"
        _merge_record(
            records,
            CompanyRecord(
                display_name=name,
                canonical_company=canonical_company_name(name),
                region_focus=item.get("country_focus") or [],
                industry_tags=item.get("tags") or [],
                ats_type=adapter_type,
                ats_token=item.get("ats_token") or "",
                careers_url=item.get("careers_url") or "",
                priority=2,
                notes=item.get("notes") or "manual check only",
            ),
        )

    return [asdict(record) for record in sorted(records.values(), key=lambda row: (row.priority, row.display_name.lower()))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Print merged target company registry.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = load_company_registry()
    if args.json:
        import json

        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{row['display_name']} | {row['ats_type']} | {row['ats_token']} | {', '.join(row['region_focus'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())