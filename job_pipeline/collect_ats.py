from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .collect_ashby import collect_ashby_board
from .collect_company_pages import collect_company_page_links
from .collect_greenhouse import collect_greenhouse_board
from .collect_lever import collect_lever_board
from .normalize import normalize_jobs
from .utils import CONFIG_DIR, RAW_DIR, load_yaml, setup_logging, write_csv, write_json

LOGGER = setup_logging(__name__)


def load_ats_config(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or CONFIG_DIR / "ats_sources.yaml") or {}


def collect_public_ats_jobs(config: dict[str, Any] | None = None, source: str = "all") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = config or load_ats_config()
    settings = config.get("settings", {})
    timeout = int(settings.get("timeout_seconds", 20))
    retries = int(settings.get("max_retries", 2))
    sleep_seconds = float(settings.get("sleep_seconds", 1.5))
    user_agent = settings.get("user_agent") or "job-pipeline-local/2.0"
    rows: list[dict[str, Any]] = []
    manual_pages = collect_company_page_links(config.get("company_pages", []))

    def should_run(name: str) -> bool:
        return source in {"all", name}

    if should_run("greenhouse"):
        for item in config.get("greenhouse", []) or []:
            try:
                rows.extend(
                    collect_greenhouse_board(
                        company_name=item.get("company_name") or item.get("board_token"),
                        board_token=item.get("board_token"),
                        country_focus=item.get("country_focus") or [],
                        tags=item.get("tags") or [],
                        timeout=timeout,
                        retries=retries,
                        user_agent=user_agent,
                    )
                )
            except Exception:
                LOGGER.exception("Greenhouse collection failed for %s", item)
            time.sleep(sleep_seconds)

    if should_run("lever"):
        for item in config.get("lever", []) or []:
            try:
                rows.extend(
                    collect_lever_board(
                        company_name=item.get("company_name") or item.get("lever_slug"),
                        lever_slug=item.get("lever_slug"),
                        country_focus=item.get("country_focus") or [],
                        tags=item.get("tags") or [],
                        timeout=timeout,
                        retries=retries,
                        user_agent=user_agent,
                    )
                )
            except Exception:
                LOGGER.exception("Lever collection failed for %s", item)
            time.sleep(sleep_seconds)

    if should_run("ashby"):
        for item in config.get("ashby", []) or []:
            try:
                rows.extend(
                    collect_ashby_board(
                        company_name=item.get("company_name") or item.get("ashby_board"),
                        ashby_board=item.get("ashby_board"),
                        country_focus=item.get("country_focus") or [],
                        tags=item.get("tags") or [],
                        timeout=timeout,
                        retries=retries,
                        user_agent=user_agent,
                    )
                )
            except Exception:
                LOGGER.exception("Ashby collection failed for %s", item)
            time.sleep(sleep_seconds)

    return rows, manual_pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect public ATS jobs from Greenhouse, Lever, and Ashby.")
    parser.add_argument("--source", choices=["all", "greenhouse", "lever", "ashby"], default="all")
    parser.add_argument("--out-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)

    rows, manual_pages = collect_public_ats_jobs(source=args.source)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_json = args.out_dir / f"ats_{args.source}_{stamp}.json"
    normalized_csv = args.out_dir / f"ats_{args.source}_{stamp}_normalized.csv"
    write_json(raw_json, {"jobs": rows, "manual_company_pages": manual_pages})
    normalized = normalize_jobs(rows)
    write_csv(normalized_csv, normalized)
    print(json.dumps({"jobs": len(rows), "manual_company_pages": len(manual_pages), "raw_json": str(raw_json), "normalized_csv": str(normalized_csv)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())