from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..database import DEFAULT_DB, connect
from ..workspace import ApplicationWorkspace, PathRegistry
from ..workspace.artifacts import write_workspace_source_files


@dataclass
class ArtifactMigrationSummary:
    dry_run: bool = False
    scanned_records: int = 0
    records_with_artifacts: int = 0
    copied_files: int = 0
    existing_targets: int = 0
    missing_sources: int = 0
    db_updates: int = 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _date_hint(row: dict[str, Any]) -> str | None:
    for key in ["campaign_date", "applied_at", "updated_at", "created_at", "first_seen_at", "last_seen_at"]:
        text = "".join(ch for ch in _text(row.get(key)) if ch.isdigit())
        if len(text) >= 8:
            return text[:8]
    return None


def _resolve_source(project_root: Path, path_text: Any) -> Path | None:
    text = _text(path_text)
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = project_root / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    return resolved if resolved.exists() and resolved.is_file() else None


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _copy_file(source: Path | None, target: Path, summary: ArtifactMigrationSummary, dry_run: bool) -> bool:
    if source is None:
        summary.missing_sources += 1
        return False
    if target.exists() or _same_path(source, target):
        summary.existing_targets += 1
        return True
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    summary.copied_files += 1
    return True


def _migrate_resume(source: Path | None, workspace: ApplicationWorkspace, summary: ArtifactMigrationSummary, dry_run: bool) -> dict[str, str]:
    if source is None:
        summary.missing_sources += 1
        return {}
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        target = workspace.resume_pdf_path()
        return {"resume_pdf_path": str(target), "tailored_resume_path": str(target)} if _copy_file(source, target, summary, dry_run) else {}
    if suffix == ".docx":
        target = workspace.resume_docx_path()
        return {"resume_docx_path": str(target), "tailored_resume_path": str(target)} if _copy_file(source, target, summary, dry_run) else {}
    target = workspace.resume_review_md_path()
    return {"tailored_resume_path": str(target)} if _copy_file(source, target, summary, dry_run) else {}


def _migrate_cover(source: Path | None, workspace: ApplicationWorkspace, summary: ArtifactMigrationSummary, dry_run: bool) -> dict[str, str]:
    if source is None:
        summary.missing_sources += 1
        return {}
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        target = workspace.cover_letter_pdf_path()
        return {"cover_letter_pdf_path": str(target), "cover_letter_path": str(target)} if _copy_file(source, target, summary, dry_run) else {}
    if suffix == ".docx":
        target = workspace.cover_letter_docx_path()
        return {"cover_letter_docx_path": str(target), "cover_letter_path": str(target)} if _copy_file(source, target, summary, dry_run) else {}
    if suffix == ".txt":
        target = workspace.cover_letter_body_txt_path()
        return {"cover_letter_body_path": str(target), "cover_letter_path": str(target)} if _copy_file(source, target, summary, dry_run) else {}
    target = workspace.cover_letter_review_md_path()
    return {"cover_letter_path": str(target)} if _copy_file(source, target, summary, dry_run) else {}


def _migrate_answer(source: Path | None, workspace: ApplicationWorkspace, summary: ArtifactMigrationSummary, dry_run: bool) -> dict[str, str]:
    if source is None:
        summary.missing_sources += 1
        return {}
    suffix = source.suffix.lower()
    target = workspace.answer_pack_json_path() if suffix == ".json" else workspace.answer_pack_md_path()
    if not _copy_file(source, target, summary, dry_run):
        return {}
    return {"answer_pack_path": str(target)} if target.suffix.lower() == ".md" else {}


def _table_columns(conn: Any, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _update_table(conn: Any, table: str, key_fields: dict[str, Any], updates: dict[str, str], dry_run: bool) -> int:
    columns = _table_columns(conn, table)
    clean = {key: value for key, value in updates.items() if key in columns and _text(value)}
    if not clean:
        return 0
    if dry_run:
        return 1
    params = {**clean, **key_fields}
    assignments = ", ".join(f"{key} = :{key}" for key in clean)
    where = " AND ".join(f"{key} = :{key}" for key in key_fields)
    conn.execute(f"UPDATE {table} SET {assignments} WHERE {where}", params)
    return 1


def _workspace_for(row: dict[str, Any], registry: PathRegistry) -> ApplicationWorkspace:
    return ApplicationWorkspace.from_job(row, paths=registry, date=_date_hint(row))


def _prepare_workspace(workspace: ApplicationWorkspace, row: dict[str, Any], dry_run: bool) -> None:
    if dry_run:
        return
    write_workspace_source_files(workspace, row)
    workspace.write_manifest()


def _migrate_record(
    *,
    row: dict[str, Any],
    registry: PathRegistry,
    summary: ArtifactMigrationSummary,
    dry_run: bool,
    resume_source: Any = "",
    cover_source: Any = "",
    answer_source: Any = "",
) -> dict[str, str]:
    summary.scanned_records += 1
    workspace = _workspace_for(row, registry)
    updates: dict[str, str] = {"application_workspace_path": str(workspace.root)}
    before = summary.copied_files + summary.existing_targets
    resume_text = _text(resume_source)
    cover_text = _text(cover_source)
    answer_text = _text(answer_source)
    resume = _resolve_source(registry.project_root, resume_text)
    cover = _resolve_source(registry.project_root, cover_text)
    answer = _resolve_source(registry.project_root, answer_text)
    if resume_text and not resume:
        summary.missing_sources += 1
    elif resume:
        updates.update(_migrate_resume(resume, workspace, summary, dry_run))
    if cover_text and not cover:
        summary.missing_sources += 1
    elif cover:
        updates.update(_migrate_cover(cover, workspace, summary, dry_run))
    if answer_text and not answer:
        summary.missing_sources += 1
    elif answer:
        updates.update(_migrate_answer(answer, workspace, summary, dry_run))
    if summary.copied_files + summary.existing_targets == before:
        updates.pop("application_workspace_path", None)
    if updates:
        summary.records_with_artifacts += 1
        _prepare_workspace(workspace, row, dry_run)
    return updates


def migrate_artifacts(
    db_path: Path = DEFAULT_DB,
    *,
    project_root: Path | None = None,
    dry_run: bool = True,
) -> ArtifactMigrationSummary:
    registry = PathRegistry.from_project_root(project_root)
    summary = ArtifactMigrationSummary(dry_run=dry_run)
    conn = connect(db_path)
    try:
        job_rows = [dict(row) for row in conn.execute("SELECT * FROM jobs").fetchall()]
        for row in job_rows:
            updates = _migrate_record(
                row=row,
                registry=registry,
                summary=summary,
                dry_run=dry_run,
                resume_source=_first_text(row.get("resume_pdf_path"), row.get("tailored_resume_path"), row.get("scheduler_resume_draft_path"), row.get("resume_file_generated")),
                cover_source=_first_text(row.get("cover_letter_pdf_path"), row.get("cover_letter_path")),
                answer_source=_first_text(row.get("answer_pack_path"), row.get("latest_answer_pack_path")),
            )
            job_updates = {
                "application_workspace_path": updates.get("application_workspace_path", ""),
                "tailored_resume_path": updates.get("tailored_resume_path", ""),
                "cover_letter_path": updates.get("cover_letter_path", ""),
                "answer_pack_path": updates.get("answer_pack_path", ""),
                "latest_resume_pdf_path": updates.get("resume_pdf_path", ""),
                "latest_cover_letter_pdf_path": updates.get("cover_letter_pdf_path", ""),
                "latest_answer_pack_path": updates.get("answer_pack_path", ""),
            }
            summary.db_updates += _update_table(conn, "jobs", {"canonical_job_id": row.get("canonical_job_id")}, job_updates, dry_run)

        application_rows = [dict(row) for row in conn.execute("SELECT a.*, j.title, j.company, j.canonical_company, j.description, j.country, j.role_category, j.role_family FROM applications a LEFT JOIN jobs j ON j.canonical_job_id = a.canonical_job_id").fetchall()]
        for row in application_rows:
            updates = _migrate_record(
                row=row,
                registry=registry,
                summary=summary,
                dry_run=dry_run,
                resume_source=_first_text(row.get("resume_pdf_path"), row.get("resume_docx_path"), row.get("resume_used")),
                cover_source=_first_text(row.get("cover_letter_pdf_path"), row.get("cover_letter_docx_path"), row.get("cover_letter_body_path"), row.get("cover_letter_used")),
                answer_source=row.get("answer_pack_path"),
            )
            summary.db_updates += _update_table(conn, "applications", {"canonical_job_id": row.get("canonical_job_id")}, updates, dry_run)

        campaign_rows = [dict(row) for row in conn.execute("SELECT ci.*, j.title, j.company, j.canonical_company, j.description, j.country, j.role_category, j.role_family FROM campaign_items ci LEFT JOIN jobs j ON j.canonical_job_id = ci.canonical_job_id").fetchall()]
        for row in campaign_rows:
            updates = _migrate_record(
                row=row,
                registry=registry,
                summary=summary,
                dry_run=dry_run,
                resume_source=_first_text(row.get("resume_pdf_path"), row.get("tailored_resume_path"), row.get("profile_resume_path")),
                cover_source=_first_text(row.get("cover_letter_pdf_path"), row.get("cover_letter_body_path"), row.get("cover_letter_path")),
                answer_source=row.get("answer_pack_path"),
            )
            summary.db_updates += _update_table(
                conn,
                "campaign_items",
                {"campaign_date": row.get("campaign_date"), "canonical_job_id": row.get("canonical_job_id")},
                updates,
                dry_run,
            )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy legacy application artifacts into generated application workspaces.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Run without copying files or updating the DB. This is the default unless --apply is supplied.")
    parser.add_argument("--apply", action="store_true", help="Copy files and update DB paths. Required for writes.")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")
    defaulted_to_dry_run = not args.dry_run and not args.apply
    dry_run = not args.apply
    summary = migrate_artifacts(args.db, project_root=args.project_root, dry_run=dry_run)
    message = "No --apply supplied; running dry-run. Pass --apply to copy files and update the DB."
    payload = asdict(summary)
    if defaulted_to_dry_run:
        payload["message"] = message
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if defaulted_to_dry_run:
            print(message)
        mode = "Dry run" if summary.dry_run else "Applied"
        print(
            f"{mode}: scanned={summary.scanned_records} records_with_artifacts={summary.records_with_artifacts} "
            f"copied={summary.copied_files} existing={summary.existing_targets} missing_sources={summary.missing_sources} "
            f"db_updates={summary.db_updates}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
