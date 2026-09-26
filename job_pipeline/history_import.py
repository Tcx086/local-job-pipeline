from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .database import DEFAULT_DB, connect, get_job_detail, update_application, upsert_job
from .utils import load_yaml, normalize_space, now_utc_iso, stable_id

DEFAULT_HISTORY_PATH = Path("local_resources/history/application_history.yaml")

ALLOWED_HISTORY_STATUSES = {
    "applied",
    "interview",
    "rejected",
    "archived",
    "offer",
    "unknown",
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def load_history(path: Path = DEFAULT_HISTORY_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Application history file not found: {path}")
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ValueError("Application history must be a YAML mapping")
    applications = data.get("applications")
    if not isinstance(applications, list):
        raise ValueError("Application history must contain an applications list")
    return data


def _evidence_note(item: dict[str, Any]) -> str:
    parts: list[str] = []
    recruiter = normalize_space(item.get("recruiter"))
    if recruiter:
        parts.append(f"Recruiter: {recruiter}")
    notes = normalize_space(item.get("notes"))
    if notes:
        parts.append(notes)
    evidence = _as_list(item.get("evidence"))
    ids = []
    for row in evidence:
        if not isinstance(row, dict):
            continue
        message_id = normalize_space(row.get("message_id"))
        thread_id = normalize_space(row.get("thread_id"))
        subject = normalize_space(row.get("subject"))
        date = normalize_space(row.get("date"))
        marker = " / ".join(value for value in [date, subject, message_id or thread_id] if value)
        if marker:
            ids.append(marker)
    if ids:
        parts.append("Gmail evidence: " + " | ".join(ids[:8]))
    return " || ".join(parts)


def _canonical_history_job_id(item: dict[str, Any]) -> str:
    company = normalize_space(item.get("company"))
    title = normalize_space(item.get("title"))
    location = normalize_space(item.get("location"))
    applied_at = normalize_space(item.get("applied_at"))
    return "history_" + stable_id(company, title, location, applied_at)[:24]


def _job_payload(item: dict[str, Any]) -> dict[str, Any]:
    company = normalize_space(item.get("company"))
    title = normalize_space(item.get("title"))
    if not company or not title:
        raise ValueError("Each history record requires company and title")
    return {
        "canonical_job_id": normalize_space(item.get("canonical_job_id")) or _canonical_history_job_id(item),
        "source": "gmail_history",
        "source_job_id": _canonical_history_job_id(item),
        "title": title,
        "company": company,
        "location": normalize_space(item.get("location")),
        "country": normalize_space(item.get("country")) or "Canada",
        "job_url": normalize_space(item.get("job_url")),
        "apply_url": normalize_space(item.get("apply_url")),
        "description": "Historical application record reconstructed from Gmail evidence.",
        "posted_at": "",
        "is_active": 0,
        "score": 0,
        "recommendation": "history_only",
        "reason_to_apply": "",
        "matched_keywords": [],
        "missing_keywords": [],
        "red_flags": [],
    }


def import_history(
    path: Path = DEFAULT_HISTORY_PATH,
    *,
    db_path: Path = DEFAULT_DB,
    dry_run: bool = False,
) -> dict[str, Any]:
    data = load_history(path)
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    conn = connect(db_path)
    try:
        for raw in data.get("applications") or []:
            if not isinstance(raw, dict):
                skipped.append({"reason": "record is not a mapping"})
                continue
            status = normalize_space(raw.get("status")).lower() or "unknown"
            if status not in ALLOWED_HISTORY_STATUSES:
                skipped.append(
                    {
                        "company": raw.get("company") or "",
                        "title": raw.get("title") or "",
                        "reason": f"unsupported status: {status}",
                    }
                )
                continue
            try:
                payload = _job_payload(raw)
            except ValueError as exc:
                skipped.append(
                    {
                        "company": raw.get("company") or "",
                        "title": raw.get("title") or "",
                        "reason": str(exc),
                    }
                )
                continue

            if dry_run:
                imported.append(
                    {
                        "company": payload["company"],
                        "title": payload["title"],
                        "status": status,
                        "canonical_job_id": payload["canonical_job_id"],
                    }
                )
                continue

            job, _ = upsert_job(conn, payload)
            job_id = job["canonical_job_id"]
            update_application(
                job_id,
                status=status,
                applied_at=normalize_space(raw.get("applied_at")),
                apply_url=normalize_space(raw.get("apply_url")),
                confirmation_number=normalize_space(raw.get("confirmation_number")),
                confirmation_snippet=normalize_space(raw.get("confirmation_snippet")),
                notes=_evidence_note(raw),
                next_action=normalize_space(raw.get("next_action")),
                next_action_date=normalize_space(raw.get("next_action_date")),
                rejection_date=normalize_space(raw.get("status_updated_at")) if status == "rejected" else "",
                company_response=normalize_space(raw.get("confirmation_snippet")),
                db_path=db_path,
            )
            imported.append(
                {
                    "company": payload["company"],
                    "title": payload["title"],
                    "status": status,
                    "canonical_job_id": job_id,
                }
            )
    finally:
        conn.close()

    return {
        "imported_at": now_utc_iso(),
        "source_file": str(path),
        "dry_run": dry_run,
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "imported": imported,
        "skipped": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import private application history reconstructed from Gmail.")
    parser.add_argument("--file", type=Path, default=DEFAULT_HISTORY_PATH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    summary = import_history(args.file, db_path=args.db, dry_run=args.dry_run)
    print(
        f"History import: {summary['imported_count']} imported, "
        f"{summary['skipped_count']} skipped, dry_run={summary['dry_run']}"
    )
    for row in summary["imported"]:
        print(f"{row['status'].upper()} | {row['company']} | {row['title']} | {row['canonical_job_id']}")
    for row in summary["skipped"]:
        print(f"SKIPPED | {row.get('company', '')} | {row.get('title', '')} | {row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
