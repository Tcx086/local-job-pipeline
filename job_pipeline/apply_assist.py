from __future__ import annotations

from pathlib import Path
from typing import Any

from .application_answers import generate_answer_pack
from .database import DEFAULT_DB, get_job_detail, update_application
from .profile_export import export_profile
from .utils import DATA_DIR, now_utc_iso

APPLY_ASSIST_DIR = DATA_DIR / "apply_assist"
ALLOWED_APPLY_STATUSES = {"applied", "skipped", "interview", "reviewed", "apply_today"}


def generate_answer_pack_for_job(
    canonical_job_id: str,
    *,
    db_path: Path = DEFAULT_DB,
    output_dir: Path = APPLY_ASSIST_DIR,
) -> dict[str, Any]:
    job = get_job_detail(canonical_job_id, db_path)
    if not job:
        raise ValueError(f"Unknown canonical_job_id: {canonical_job_id}")
    return generate_answer_pack(
        job,
        generated_resume_file=str(job.get("resume_used") or job.get("tailored_resume_path") or job.get("profile_resume_path") or job.get("scheduler_resume_draft_path") or job.get("resume_file_generated") or ""),
        output_dir=output_dir,
    )


def mark_application_status(
    canonical_job_id: str,
    status: str,
    *,
    db_path: Path = DEFAULT_DB,
    resume_used: str = "",
    apply_url: str = "",
    notes: str = "",
    confirmation_number: str = "",
    confirmation_snippet: str = "",
    next_action: str = "",
) -> None:
    if status not in ALLOWED_APPLY_STATUSES:
        raise ValueError(f"Unsupported apply assist status: {status}")
    applied_at = now_utc_iso() if status == "applied" else ""
    update_application(
        canonical_job_id,
        status=status,
        applied_at=applied_at,
        resume_used=resume_used,
        apply_url=apply_url,
        notes=notes,
        confirmation_number=confirmation_number,
        confirmation_snippet=confirmation_snippet,
        next_action=next_action,
        db_path=db_path,
    )


def build_profile_export(*, output_dir: Path = APPLY_ASSIST_DIR) -> dict[str, Any]:
    return export_profile(output_dir=output_dir)
