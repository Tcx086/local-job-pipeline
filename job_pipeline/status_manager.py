from __future__ import annotations

import argparse
from pathlib import Path

from .database import DEFAULT_DB, get_job_detail, update_application

ALLOWED_STATUSES = {"new", "reviewed", "apply_today", "applied", "interview", "rejected", "archived", "skipped"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update application status in the local SQLite tracker.")
    parser.add_argument("--set-status", dest="canonical_job_id", required=True)
    parser.add_argument("status", choices=sorted(ALLOWED_STATUSES))
    parser.add_argument("--resume", default="")
    parser.add_argument("--cover-letter", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--apply-url", default="")
    parser.add_argument("--confirmation-number", default="")
    parser.add_argument("--confirmation-snippet", default="")
    parser.add_argument("--next-action", default="")
    parser.add_argument("--next-action-date", default="")
    parser.add_argument("--applied-at", default="")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    update_application(
        args.canonical_job_id,
        status=args.status,
        resume_used=args.resume,
        cover_letter_used=args.cover_letter,
        notes=args.notes,
        apply_url=args.apply_url,
        confirmation_number=args.confirmation_number,
        confirmation_snippet=args.confirmation_snippet,
        next_action=args.next_action,
        next_action_date=args.next_action_date,
        applied_at=args.applied_at,
        db_path=args.db,
    )
    detail = get_job_detail(args.canonical_job_id, args.db)
    title = detail.get("title") if detail else args.canonical_job_id
    print(f"Updated {title} -> {args.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())