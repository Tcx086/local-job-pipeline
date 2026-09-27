from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import (
    DEFAULT_DB,
    JOB_COLUMNS,
    connect,
    prepare_job_for_db,
    update_application,
)
from .freshness import enrich_freshness
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

HISTORY_SOURCE = "gmail_history"


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


def _requisition_id(item: dict[str, Any]) -> str:
    for key in ("requisition_id", "req_id", "source_job_id", "job_id"):
        value = normalize_space(item.get(key))
        if value:
            return value
    return ""


def _canonical_history_job_id(item: dict[str, Any]) -> str:
    """Strict canonical identity for Gmail historical applications.

    Priority:
      1. explicit ``canonical_job_id`` on the record;
      2. requisition_id / req_id / source_job_id / job_id when present;
      3. company + title + location + applied_at.

    Different application dates are always different applications.
    Never uses the search pipeline's fuzzy dedupe.
    """
    explicit = normalize_space(item.get("canonical_job_id"))
    if explicit:
        return explicit
    company = normalize_space(item.get("company"))
    title = normalize_space(item.get("title"))
    req_id = _requisition_id(item)
    if req_id:
        return "history_req_" + stable_id(company, req_id)[:24]
    location = normalize_space(item.get("location"))
    applied_at = normalize_space(item.get("applied_at"))
    return "history_" + stable_id(company, title, location, applied_at)[:24]


def _job_payload(item: dict[str, Any]) -> dict[str, Any]:
    company = normalize_space(item.get("company"))
    title = normalize_space(item.get("title"))
    if not company or not title:
        raise ValueError("Each history record requires company and title")
    return {
        "canonical_job_id": _canonical_history_job_id(item),
        "source": HISTORY_SOURCE,
        "source_job_id": _requisition_id(item) or _canonical_history_job_id(item),
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


def _strict_upsert_history_job(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a history job matched ONLY by exact canonical_job_id.

    Deliberately does not call find_existing_job / jobs_are_same: Gmail
    history records must never be fuzzy-merged with each other or with
    search-collected jobs.
    """
    now = now_utc_iso()
    incoming = prepare_job_for_db(payload, now=now)
    canonical_id = incoming["canonical_job_id"]
    existing_row = conn.execute(
        "SELECT * FROM jobs WHERE canonical_job_id = ?", (canonical_id,)
    ).fetchone()
    if existing_row:
        incoming["first_seen_at"] = existing_row["first_seen_at"] or now
        incoming["created_at"] = existing_row["created_at"] or now
        incoming["is_new_since_last_run"] = 0
    else:
        incoming["first_seen_at"] = incoming.get("first_seen_at") or now
        incoming["created_at"] = now
        incoming["is_new_since_last_run"] = 1
    incoming["last_seen_at"] = now
    incoming["updated_at"] = now
    incoming["missing_count"] = 0
    incoming = enrich_freshness(incoming)
    for json_field in ["matched_keywords", "missing_keywords", "red_flags", "soft_penalties", "all_sources", "all_source_urls"]:
        incoming[json_field] = _json_cell(incoming.get(json_field) or [])
    incoming["hard_skip"] = int(bool(incoming.get("hard_skip")))
    values = {column: incoming.get(column, "") for column in JOB_COLUMNS}
    placeholders = ", ".join([":" + column for column in JOB_COLUMNS])
    assignments = ", ".join([f"{column}=excluded.{column}" for column in JOB_COLUMNS if column != "canonical_job_id"])
    conn.execute(
        f"""
        INSERT INTO jobs ({', '.join(JOB_COLUMNS)})
        VALUES ({placeholders})
        ON CONFLICT(canonical_job_id) DO UPDATE SET {assignments}
        """,
        values,
    )
    conn.execute(
        """
        INSERT INTO job_snapshots (canonical_job_id, collected_at, source, raw_json_path, description_hash, score, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            now,
            incoming.get("source"),
            "",
            incoming.get("description_hash"),
            incoming.get("score"),
            0,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM jobs WHERE canonical_job_id = ?", (canonical_id,)).fetchone()
    return dict(row)


def _json_cell(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _collision_key_sort(record: dict[str, Any]) -> tuple[str, str, int]:
    # Latest status_updated_at wins; then latest applied_at; then file order.
    return (
        normalize_space(record["item"].get("status_updated_at")),
        normalize_space(record["item"].get("applied_at")),
        record["index"],
    )


def _build_plan(data: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate every record, group by strict canonical ID, resolve collisions.

    Pure function: touches no database, so dry-run results are exact.
    """
    parsed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, raw in enumerate(data.get("applications") or []):
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
        parsed.append(
            {
                "index": index,
                "item": raw,
                "status": status,
                "canonical_job_id": payload["canonical_job_id"],
                "payload": payload,
            }
        )

    groups: dict[str, list[dict[str, Any]]] = {}
    for record in parsed:
        groups.setdefault(record["canonical_job_id"], []).append(record)

    resolved: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []
    for canonical_id, group in groups.items():
        if len(group) == 1:
            resolved.append({**group[0], "merged_from": 1, "collision": False})
            continue
        ordered = sorted(group, key=_collision_key_sort)
        winner = ordered[-1]
        detail = {
            "canonical_job_id": canonical_id,
            "record_count": len(group),
            "statuses": sorted({record["status"] for record in group}),
            "winner_status": winner["status"],
            "records": [
                {
                    "company": normalize_space(record["item"].get("company")),
                    "title": normalize_space(record["item"].get("title")),
                    "applied_at": normalize_space(record["item"].get("applied_at")),
                    "status": record["status"],
                    "status_updated_at": normalize_space(record["item"].get("status_updated_at")),
                    "is_winner": record is winner,
                }
                for record in ordered
            ],
        }
        collisions.append(detail)
        merged_notes = " || ".join(
            note for note in (_evidence_note(record["item"]) for record in ordered) if note
        )
        resolved.append(
            {
                **winner,
                "merged_from": len(group),
                "collision": True,
                "merged_evidence_note": merged_notes,
            }
        )

    resolved.sort(key=lambda record: record["index"])
    return {
        "raw_record_count": len(data.get("applications") or []),
        "unique_record_count": len(resolved),
        "collision_count": len(collisions),
        "skipped_count": len(skipped),
        "collisions": collisions,
        "resolved": resolved,
        "skipped": skipped,
    }


def backup_db(db_path: Path = DEFAULT_DB) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = db_path.parent / f"{db_path.stem}.backup-{timestamp}.sqlite"
    shutil.copy2(db_path, destination)
    return destination


def delete_history_owned(db_path: Path = DEFAULT_DB) -> int:
    """Delete ONLY jobs/applications created by the gmail_history importer.

    Regular ATS/search jobs (any other source) are left untouched.
    """
    conn = connect(db_path)
    try:
        ids = [row[0] for row in conn.execute("SELECT canonical_job_id FROM jobs WHERE source = ?", (HISTORY_SOURCE,))]
        for canonical_id in ids:
            conn.execute("DELETE FROM job_snapshots WHERE canonical_job_id = ?", (canonical_id,))
            conn.execute("DELETE FROM applications WHERE canonical_job_id = ?", (canonical_id,))
            conn.execute("DELETE FROM jobs WHERE canonical_job_id = ?", (canonical_id,))
        conn.commit()
        return len(ids)
    finally:
        conn.close()


def import_history(
    path: Path = DEFAULT_HISTORY_PATH,
    *,
    db_path: Path = DEFAULT_DB,
    dry_run: bool = False,
    replace_history: bool = False,
) -> dict[str, Any]:
    data = load_history(path)
    plan = _build_plan(data)

    if dry_run:
        return {
            "imported_at": now_utc_iso(),
            "source_file": str(path),
            "dry_run": True,
            "raw_record_count": plan["raw_record_count"],
            "unique_record_count": plan["unique_record_count"],
            "collision_count": plan["collision_count"],
            "skipped_count": plan["skipped_count"],
            "collisions": plan["collisions"],
            # Back-compat aliases.
            "imported_count": plan["unique_record_count"],
            "imported": [
                {
                    "company": record["payload"]["company"],
                    "title": record["payload"]["title"],
                    "status": record["status"],
                    "canonical_job_id": record["canonical_job_id"],
                }
                for record in plan["resolved"]
            ],
            "skipped": plan["skipped"],
        }

    backup_path: Path | None = None
    deleted_count = 0
    if replace_history:
        backup_path = backup_db(db_path)
        deleted_count = delete_history_owned(db_path)

    conn = connect(db_path)
    imported: list[dict[str, Any]] = []
    try:
        for record in plan["resolved"]:
            raw = record["item"]
            status = record["status"]
            payload = record["payload"]
            _strict_upsert_history_job(conn, payload)
            job_id = payload["canonical_job_id"]
            notes = record.get("merged_evidence_note") or _evidence_note(raw)
            update_application(
                job_id,
                status=status,
                applied_at=normalize_space(raw.get("applied_at")),
                apply_url=normalize_space(raw.get("apply_url")),
                confirmation_number=normalize_space(raw.get("confirmation_number")),
                confirmation_snippet=normalize_space(raw.get("confirmation_snippet")),
                notes=notes,
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
        "dry_run": False,
        "replace_history": replace_history,
        "backup_path": str(backup_path) if backup_path else "",
        "deleted_history_jobs": deleted_count,
        "raw_record_count": plan["raw_record_count"],
        "unique_record_count": plan["unique_record_count"],
        "collision_count": plan["collision_count"],
        "skipped_count": plan["skipped_count"],
        "collisions": plan["collisions"],
        # Back-compat aliases.
        "imported_count": plan["unique_record_count"],
        "imported": imported,
        "skipped": plan["skipped"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import private application history reconstructed from Gmail.")
    parser.add_argument("--file", type=Path, default=DEFAULT_HISTORY_PATH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace-history",
        action="store_true",
        help="Backup the DB, delete jobs/applications previously created by the gmail_history "
        "importer, then rebuild history with the strict canonical-ID rules.",
    )
    args = parser.parse_args(argv)

    summary = import_history(args.file, db_path=args.db, dry_run=args.dry_run, replace_history=args.replace_history)
    print(f"History import: raw={summary['raw_record_count']} "
          f"unique={summary['unique_record_count']} "
          f"collisions={summary['collision_count']} "
          f"skipped={summary['skipped_count']} "
          f"dry_run={summary['dry_run']}")
    if summary.get("backup_path"):
        print(f"Backup: {summary['backup_path']}")
    if summary.get("deleted_history_jobs"):
        print(f"Deleted history-owned jobs: {summary['deleted_history_jobs']}")
    for collision in summary["collisions"]:
        print(f"COLLISION | {collision['canonical_job_id']} | {collision['record_count']} records "
              f"| statuses={','.join(collision['statuses'])} | winner={collision['winner_status']}")
        for record in collision["records"]:
            marker = "WINNER" if record["is_winner"] else "merged"
            print(f"    - {marker} | {record['company']} | {record['title']} | "
                  f"{record['applied_at']} | {record['status']} | updated={record['status_updated_at']}")
    if not args.dry_run:
        for row in summary["imported"]:
            print(f"{row['status'].upper()} | {row['company']} | {row['title']} | {row['canonical_job_id']}")
    for row in summary["skipped"]:
        print(f"SKIPPED | {row.get('company', '')} | {row.get('title', '')} | {row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
