from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .database import DEFAULT_DB, get_jobs, get_manual_search_urls, get_search_coverage_rows
from .query_expander import MODE_NAMES, get_search_mode
from .report import REPORT_FIELDS, prepare_report_rows
from .utils import REPORTS_DIR, today_yyyymmdd


def hours_old_from_days(days_back: int) -> int:
    if days_back <= 0:
        raise ValueError("days_back must be positive")
    return days_back * 24


def _write_backfill_xlsx(path: Path, sheets: list[tuple[str, list[dict[str, Any]], list[str] | None]]) -> bool:
    try:
        import pandas as pd  # type: ignore
    except ModuleNotFoundError:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, rows, fields in sheets:
            df = pd.DataFrame(rows, columns=fields) if fields else pd.DataFrame(rows)
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            worksheet = writer.sheets[sheet_name[:31]]
            worksheet.freeze_panes = "A2"
            for idx, column in enumerate(df.columns, start=1):
                max_len = max([len(str(column))] + [len(str(row.get(column, ""))) for row in rows[:200]])
                worksheet.column_dimensions[worksheet.cell(row=1, column=idx).column_letter].width = min(max_len + 2, 60)
    return True


def generate_backfill_report(*, db_path: Path = DEFAULT_DB, report_date: str | None = None) -> dict[str, str]:
    date_part = report_date or today_yyyymmdd()
    rows = prepare_report_rows(get_jobs(db_path, include_inactive=True))
    active = [row for row in rows if int(row.get("is_active") or 0) == 1]
    sheets = [
        ("Backfill Top Jobs", [row for row in active if int(row.get("score") or 0) >= 70 and not row.get("hard_skip")], REPORT_FIELDS),
        ("Backfill All Jobs", rows, REPORT_FIELDS),
        ("New To Database", [row for row in rows if int(row.get("is_new_since_last_run") or 0) == 1], REPORT_FIELDS),
        ("Active Old Jobs", [row for row in active if str(row.get("freshness_label") or "") in {"recent", "old", "unknown"}], REPORT_FIELDS),
        ("Source Coverage", get_search_coverage_rows(db_path), None),
        ("Query Coverage", get_search_coverage_rows(db_path), None),
        ("Manual Check URLs", get_manual_search_urls(db_path), None),
    ]
    path = REPORTS_DIR / f"backfill_{date_part}.xlsx"
    created = _write_backfill_xlsx(path, sheets)
    return {"xlsx": str(path) if created else ""}


def run_backfill(
    *,
    days_back: int = 30,
    mode: str = "broad",
    db_path: Path = DEFAULT_DB,
    use_sample: bool = False,
    include_ats: bool = True,
    make_docx: bool = True,
) -> dict[str, Any]:
    settings = get_search_mode(mode)
    from .scheduler import run_once

    summary = run_once(
        use_sample=use_sample,
        mode=mode,
        hours_old=hours_old_from_days(days_back),
        results_wanted=int(settings["results_wanted_per_query"]),
        resume_score_threshold=int(settings["generate_resume_min_score"]),
        make_docx=make_docx,
        db_path=db_path,
        include_ats=include_ats,
        mark_missing=False,
    )
    summary["days_back"] = days_back
    summary["backfill_report"] = generate_backfill_report(db_path=db_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill active public jobs into SQLite.")
    parser.add_argument("--days-back", type=int, default=30)
    parser.add_argument("--mode", choices=sorted(MODE_NAMES), default="broad")
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--no-ats", action="store_true")
    parser.add_argument("--no-docx", action="store_true")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    summary = run_backfill(
        days_back=args.days_back,
        mode=args.mode,
        db_path=args.db,
        use_sample=args.sample,
        include_ats=not args.no_ats,
        make_docx=not args.no_docx,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
