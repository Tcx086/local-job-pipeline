from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from .utils import CONFIG_DIR, REPORTS_DIR, load_yaml, now_utc_iso, read_csv, today_yyyymmdd, write_csv

SOURCE_REGISTRY_PATH = CONFIG_DIR / "source_registry.yaml"
SOURCE_HEALTH_FIELDS = [
    "run_id",
    "source",
    "enabled",
    "last_run_at",
    "last_success_at",
    "last_error_at",
    "last_error_message",
    "raw_count_last_run",
    "normalized_count_last_run",
    "average_latency_ms",
    "consecutive_failures",
    "status",
]


def load_source_registry(path: Path = SOURCE_REGISTRY_PATH) -> dict[str, Any]:
    data = load_yaml(path) or {}
    return data if isinstance(data, dict) else {}


def _registry_enabled_sources(registry: dict[str, Any]) -> dict[str, bool]:
    sources: dict[str, bool] = {}
    for key, payload in (registry.get("sources") or {}).items():
        if not isinstance(payload, dict):
            continue
        enabled = bool(payload.get("enabled", True))
        if key == "jobspy":
            for platform in payload.get("platforms") or []:
                sources[str(platform)] = enabled
        elif payload.get("sources"):
            for item in payload.get("sources") or []:
                if isinstance(item, dict):
                    sources[str(item.get("name") or key)] = enabled
        else:
            sources[str(key)] = enabled
    return sources


def build_source_health_rows(
    coverage_rows: list[dict[str, Any]],
    *,
    run_id: str,
    registry: dict[str, Any] | None = None,
    previous_rows: list[dict[str, Any]] | None = None,
    last_run_at: str | None = None,
) -> list[dict[str, Any]]:
    registry = registry or load_source_registry()
    enabled = _registry_enabled_sources(registry)
    last_run_at = last_run_at or now_utc_iso()
    previous_failures = {
        str(row.get("source")): int(row.get("consecutive_failures") or 0)
        for row in previous_rows or []
    }
    totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"raw": 0, "normalized": 0, "errors": 0, "messages": []})
    for row in coverage_rows:
        source = str(row.get("source") or "unknown")
        totals[source]["raw"] += int(row.get("raw_count") or 0)
        totals[source]["normalized"] += int(row.get("normalized_count") or 0)
        totals[source]["errors"] += int(row.get("error_count") or 0)
        if row.get("error_message"):
            totals[source]["messages"].append(str(row.get("error_message")))

    for source in enabled:
        totals[source] = totals[source]

    rows: list[dict[str, Any]] = []
    for source, metrics in sorted(totals.items()):
        is_enabled = enabled.get(source, True)
        errors = int(metrics["errors"])
        raw_count = int(metrics["raw"])
        normalized_count = int(metrics["normalized"])
        consecutive_failures = previous_failures.get(source, 0)
        if not is_enabled:
            status = "disabled"
        elif errors > 0 and raw_count == 0:
            status = "failing"
            consecutive_failures += 1
        elif errors > 0 or raw_count == 0:
            status = "degraded"
            consecutive_failures = consecutive_failures + 1 if raw_count == 0 else 0
        else:
            status = "healthy"
            consecutive_failures = 0
        rows.append(
            {
                "run_id": run_id,
                "source": source,
                "enabled": int(is_enabled),
                "last_run_at": last_run_at,
                "last_success_at": last_run_at if status in {"healthy", "degraded"} and raw_count > 0 else "",
                "last_error_at": last_run_at if errors else "",
                "last_error_message": "; ".join(metrics["messages"][:3]),
                "raw_count_last_run": raw_count,
                "normalized_count_last_run": normalized_count,
                "average_latency_ms": "",
                "consecutive_failures": consecutive_failures,
                "status": status,
            }
        )
    return rows


def write_source_health_report(rows: list[dict[str, Any]], *, report_date: str | None = None) -> dict[str, str]:
    date_part = report_date or today_yyyymmdd()
    path = REPORTS_DIR / f"source_health_{date_part}.csv"
    write_csv(path, rows, SOURCE_HEALTH_FIELDS)
    return {"csv": str(path)}


def record_source_health(rows: list[dict[str, Any]], *, db_path: Path | None = None, report_date: str | None = None) -> dict[str, str]:
    paths = write_source_health_report(rows, report_date=report_date)
    if db_path is not None:
        from .database import save_source_health

        save_source_health(db_path, rows)
    return paths


def latest_source_health_csv(report_dir: Path = REPORTS_DIR) -> Path | None:
    files = sorted(report_dir.glob("source_health_*.csv"))
    return files[-1] if files else None


def load_latest_source_health(report_dir: Path = REPORTS_DIR) -> list[dict[str, str]]:
    path = latest_source_health_csv(report_dir)
    return read_csv(path) if path else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect source health.")
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args(argv)
    if args.latest:
        rows = load_latest_source_health()
        if not rows:
            print("No source health report found.")
            return 1
        for row in rows:
            print(
                f"{row.get('source')}: {row.get('status')} "
                f"raw={row.get('raw_count_last_run')} normalized={row.get('normalized_count_last_run')} "
                f"errors={row.get('last_error_message') or '-'}"
            )
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
