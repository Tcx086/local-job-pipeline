from __future__ import annotations

from typing import Any

from ..utils import write_json
from .application_workspace import ApplicationWorkspace


JOB_SNAPSHOT_FIELDS = [
    "canonical_job_id",
    "source",
    "source_job_id",
    "title",
    "company",
    "canonical_company",
    "location",
    "country",
    "remote_type",
    "role_category",
    "role_family",
    "fit_category",
    "seniority",
    "job_url",
    "apply_url",
    "posted_at",
    "first_seen_at",
    "last_seen_at",
]

SCORING_FIELDS = [
    "score",
    "recommendation",
    "matched_keywords",
    "missing_keywords",
    "red_flags",
    "reason_to_apply",
    "application_effort",
    "resume_profile",
]


def write_workspace_source_files(
    workspace: ApplicationWorkspace,
    job: dict[str, Any],
    scoring_snapshot: dict[str, Any] | None = None,
) -> None:
    workspace.ensure_dirs()
    description = str(job.get("description") or "").strip()
    if description:
        workspace.job_description_path().write_text(description + "\n", encoding="utf-8")
    job_snapshot = {field: job.get(field, "") for field in JOB_SNAPSHOT_FIELDS if job.get(field) not in (None, "", [])}
    write_json(workspace.job_snapshot_path(), job_snapshot)
    scoring = scoring_snapshot or {field: job.get(field) for field in SCORING_FIELDS if job.get(field) not in (None, "", [])}
    if scoring:
        write_json(workspace.scoring_snapshot_path(), scoring)
