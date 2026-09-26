from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from .database import DEFAULT_DB, connect, update_application
from .utils import CONFIG_DIR, PROJECT_ROOT, load_yaml, now_utc_iso, slugify
from .workspace import ApplicationWorkspace, PathRegistry

MUSE_CONFIG_PATH = CONFIG_DIR / "muse_integration.yaml"

DEFAULT_MUSE_CONFIG: dict[str, Any] = {
    "muse": {
        "queue_dir": "generated/muse_queue",
        "approved_application_statuses": ["apply_today"],
        "require_apply_url": True,
        "require_resume_pdf": True,
        "facts_path": "local_resources/muse/muse_facts.yaml",
        "allowed_actions": [
            "open_official_application_url",
            "fill_application_fields_from_manifest",
            "upload_manifest_artifacts",
            "submit_when_no_stop_condition_is_triggered",
            "write_submission_result",
        ],
        "stop_conditions": [
            "salary_question_without_posted_range",
            "sponsorship_or_work_authorization_ambiguity",
            "legal_or_background_attestation_not_preapproved",
            "demographic_question_without_preapproved_answer",
            "new_written_response_over_300_characters",
            "missing_or_conflicting_candidate_fact",
            "unexpected_required_document",
            "payment_or_purchase_request",
            "software_install_or_unknown_code_execution_request",
            "captcha_or_identity_verification_outside_normal_ats_flow",
            "application_url_redirects_to_unverified_domain",
        ],
        "result_filename": "result.json",
    }
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_muse_config(path: Path = MUSE_CONFIG_PATH) -> dict[str, Any]:
    loaded = load_yaml(path) if path.exists() else {}
    data = loaded if isinstance(loaded, dict) else {}
    return _deep_merge(DEFAULT_MUSE_CONFIG, data)


def _resolve_project_path(value: str | Path | None, project_root: Path = PROJECT_ROOT) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else project_root / path


def load_private_facts(config: dict[str, Any], project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    muse = config.get("muse") if isinstance(config.get("muse"), dict) else {}
    path = _resolve_project_path(muse.get("facts_path"), project_root)
    if not path or not path.exists():
        return {}
    loaded = load_yaml(path)
    return loaded if isinstance(loaded, dict) else {}


def _approved_rows(
    db_path: Path,
    statuses: list[str],
    job_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"a.status IN ({placeholders})")
            params.extend(statuses)
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            clauses.append(f"j.canonical_job_id IN ({placeholders})")
            params.extend(job_ids)
        where = " AND ".join(clauses) if clauses else "1=1"
        rows = conn.execute(
            f"""
            SELECT
                j.*,
                a.status AS application_status,
                a.applied_at AS application_applied_at,
                a.resume_used AS application_resume_used,
                a.cover_letter_used AS application_cover_letter_used,
                a.apply_url AS application_apply_url,
                a.notes AS application_notes,
                a.next_action AS application_next_action,
                a.next_action_date AS application_next_action_date,
                a.application_workspace_path AS application_workspace_path_db,
                a.resume_pdf_path AS application_resume_pdf_path,
                a.resume_docx_path AS application_resume_docx_path,
                a.cover_letter_pdf_path AS application_cover_letter_pdf_path,
                a.cover_letter_docx_path AS application_cover_letter_docx_path,
                a.cover_letter_body_path AS application_cover_letter_body_path,
                a.answer_pack_path AS application_answer_pack_path,
                a.job_description_path AS application_job_description_path
            FROM applications a
            JOIN jobs j ON j.canonical_job_id = a.canonical_job_id
            WHERE {where}
            ORDER BY COALESCE(j.score, 0) DESC, j.company, j.title
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _first_existing(
    candidates: list[str | Path | None],
    *,
    project_root: Path,
    workspace_root: Path | None = None,
) -> Path | None:
    for value in candidates:
        if not value:
            continue
        path = Path(str(value))
        variants = [path] if path.is_absolute() else [project_root / path]
        if workspace_root is not None and not path.is_absolute():
            variants.append(workspace_root / path)
        for variant in variants:
            if variant.exists() and variant.is_file():
                return variant
    return None


def _copy_artifact(source: Path | None, target: Path) -> str:
    if source is None:
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target.as_posix()


def _workspace_for_row(row: dict[str, Any], paths: PathRegistry) -> ApplicationWorkspace:
    return ApplicationWorkspace.from_job(row, paths=paths)


def _artifact_sources(row: dict[str, Any], workspace: ApplicationWorkspace) -> dict[str, Path | None]:
    root = workspace.paths.project_root
    ws_root = workspace.root
    return {
        "resume_pdf": _first_existing(
            [
                row.get("application_resume_pdf_path"),
                row.get("application_resume_used"),
                row.get("latest_resume_pdf_path"),
                row.get("tailored_resume_path"),
                row.get("profile_resume_path"),
                workspace.resume_pdf_path(),
            ],
            project_root=root,
            workspace_root=ws_root,
        ),
        "resume_docx": _first_existing(
            [row.get("application_resume_docx_path"), workspace.resume_docx_path()],
            project_root=root,
            workspace_root=ws_root,
        ),
        "cover_letter_pdf": _first_existing(
            [
                row.get("application_cover_letter_pdf_path"),
                row.get("latest_cover_letter_pdf_path"),
                row.get("cover_letter_path"),
                workspace.cover_letter_pdf_path(),
            ],
            project_root=root,
            workspace_root=ws_root,
        ),
        "cover_letter_docx": _first_existing(
            [row.get("application_cover_letter_docx_path"), workspace.cover_letter_docx_path()],
            project_root=root,
            workspace_root=ws_root,
        ),
        "cover_letter_body": _first_existing(
            [row.get("application_cover_letter_body_path"), workspace.cover_letter_body_txt_path()],
            project_root=root,
            workspace_root=ws_root,
        ),
        "answer_pack": _first_existing(
            [row.get("application_answer_pack_path"), row.get("latest_answer_pack_path"), workspace.answer_pack_md_path()],
            project_root=root,
            workspace_root=ws_root,
        ),
        "job_description": _first_existing(
            [row.get("application_job_description_path"), workspace.job_description_path()],
            project_root=root,
            workspace_root=ws_root,
        ),
    }


def _official_url(row: dict[str, Any]) -> str:
    for key in ["application_apply_url", "apply_url", "job_url"]:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _safe_bundle_name(row: dict[str, Any]) -> str:
    company = slugify(str(row.get("company") or row.get("canonical_company") or "company"), 50)
    title = slugify(str(row.get("title") or "role"), 60)
    job_id = slugify(str(row.get("canonical_job_id") or "job"), 60)
    return f"{company}__{title}__{job_id}"


def build_manifest(
    row: dict[str, Any],
    *,
    config: dict[str, Any],
    private_facts: dict[str, Any],
    artifact_paths: dict[str, str],
    result_relative_path: str,
) -> dict[str, Any]:
    muse = config.get("muse") if isinstance(config.get("muse"), dict) else {}
    return {
        "schema_version": 1,
        "queue_status": "READY_TO_APPLY",
        "exported_at": now_utc_iso(),
        "canonical_job_id": row.get("canonical_job_id") or "",
        "job": {
            "company": row.get("company") or row.get("canonical_company") or "",
            "title": row.get("title") or "",
            "location": row.get("location") or "",
            "country": row.get("country") or "",
            "remote_type": row.get("remote_type") or "",
            "official_application_url": _official_url(row),
            "source": row.get("source") or "",
            "posted_at": row.get("posted_at") or "",
            "last_seen_at": row.get("last_seen_at") or "",
        },
        "decision": {
            "application_status": row.get("application_status") or "",
            "application_effort": row.get("application_effort") or "",
            "resume_profile": row.get("resume_profile") or "",
            "score": row.get("score") or 0,
            "recommendation": row.get("recommendation") or "",
            "reason_to_apply": row.get("reason_to_apply") or "",
            "red_flags": row.get("red_flags") or "",
        },
        "artifacts": artifact_paths,
        "candidate": private_facts,
        "execution_policy": {
            "role": "browser_application_executor",
            "discovery_allowed": False,
            "rescoring_allowed": False,
            "resume_rewriting_allowed": False,
            "candidate_fact_inference_allowed": False,
            "allowed_actions": list(muse.get("allowed_actions") or []),
            "stop_conditions": list(muse.get("stop_conditions") or []),
            "instruction": (
                "Use only the official application URL, manifest facts, and listed artifacts. "
                "Do not search for a replacement posting, invent candidate facts, or rewrite application materials. "
                "If a stop condition is triggered, stop before submission and record BLOCKED."
            ),
        },
        "result_contract": {
            "write_json_to": result_relative_path,
            "allowed_outcomes": ["SUBMITTED", "BLOCKED", "SKIPPED"],
            "required_fields": ["outcome", "canonical_job_id", "timestamp", "notes"],
            "submitted_optional_fields": [
                "confirmation_number",
                "confirmation_text",
                "final_url",
            ],
            "blocked_optional_fields": [
                "blocking_question",
                "blocking_reason",
                "screenshot_path",
            ],
        },
    }


def export_ready_queue(
    *,
    db_path: Path = DEFAULT_DB,
    output_dir: Path | None = None,
    statuses: list[str] | None = None,
    job_ids: list[str] | None = None,
    config_path: Path = MUSE_CONFIG_PATH,
) -> dict[str, Any]:
    config = load_muse_config(config_path)
    muse = config.get("muse") if isinstance(config.get("muse"), dict) else {}
    statuses = statuses or list(muse.get("approved_application_statuses") or ["apply_today"])
    paths = PathRegistry.from_project_root()
    queue_dir = output_dir or _resolve_project_path(muse.get("queue_dir"), paths.project_root) or paths.resolve_generated("muse_queue")
    queue_dir.mkdir(parents=True, exist_ok=True)
    private_facts = load_private_facts(config, paths.project_root)

    exported: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    rows = _approved_rows(db_path, statuses, job_ids)

    for row in rows:
        workspace = _workspace_for_row(row, paths)
        sources = _artifact_sources(row, workspace)
        url = _official_url(row)
        blockers: list[str] = []
        if bool(muse.get("require_apply_url", True)) and not url:
            blockers.append("missing application URL")
        if bool(muse.get("require_resume_pdf", True)) and sources.get("resume_pdf") is None:
            blockers.append("missing resume PDF")
        if not private_facts:
            blockers.append("missing private Muse facts file")

        if blockers:
            blocked.append(
                {
                    "canonical_job_id": row.get("canonical_job_id") or "",
                    "company": row.get("company") or "",
                    "title": row.get("title") or "",
                    "blockers": blockers,
                }
            )
            continue

        bundle = queue_dir / _safe_bundle_name(row)
        artifact_dir = bundle / "artifacts"
        bundle.mkdir(parents=True, exist_ok=True)

        artifact_paths: dict[str, str] = {}
        copy_specs = {
            "resume_pdf": "resume.pdf",
            "resume_docx": "resume.docx",
            "cover_letter_pdf": "cover_letter.pdf",
            "cover_letter_docx": "cover_letter.docx",
            "cover_letter_body": "cover_letter_body.txt",
            "answer_pack": "answer_pack.md",
            "job_description": "job_description.md",
        }
        for key, filename in copy_specs.items():
            copied = _copy_artifact(sources.get(key), artifact_dir / filename)
            if copied:
                artifact_paths[key] = (Path("artifacts") / filename).as_posix()

        if "job_description" not in artifact_paths and str(row.get("description") or "").strip():
            path = artifact_dir / "job_description.md"
            path.write_text(str(row.get("description")).strip() + "\n", encoding="utf-8")
            artifact_paths["job_description"] = (Path("artifacts") / "job_description.md").as_posix()

        result_filename = str(muse.get("result_filename") or "result.json")
        manifest = build_manifest(
            row,
            config=config,
            private_facts=private_facts,
            artifact_paths=artifact_paths,
            result_relative_path=result_filename,
        )
        manifest_path = bundle / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        exported.append(
            {
                "canonical_job_id": row.get("canonical_job_id") or "",
                "company": row.get("company") or "",
                "title": row.get("title") or "",
                "bundle": bundle.as_posix(),
                "manifest": manifest_path.as_posix(),
            }
        )

    summary = {
        "exported_at": now_utc_iso(),
        "statuses": statuses,
        "requested_job_ids": job_ids or [],
        "exported_count": len(exported),
        "blocked_count": len(blocked),
        "exported": exported,
        "blocked": blocked,
    }
    (queue_dir / "_queue_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def record_result(
    canonical_job_id: str,
    outcome: str,
    *,
    db_path: Path = DEFAULT_DB,
    confirmation_number: str = "",
    confirmation_text: str = "",
    notes: str = "",
    next_action: str = "",
    next_action_date: str = "",
) -> None:
    normalized = outcome.strip().upper()
    if normalized == "SUBMITTED":
        update_application(
            canonical_job_id,
            status="applied",
            applied_at=now_utc_iso(),
            confirmation_number=confirmation_number,
            confirmation_snippet=confirmation_text,
            notes=notes,
            next_action=next_action,
            next_action_date=next_action_date,
            db_path=db_path,
        )
        return
    if normalized == "BLOCKED":
        update_application(
            canonical_job_id,
            status="apply_today",
            notes=notes,
            next_action=next_action or "Resolve Muse blocker before submission",
            next_action_date=next_action_date,
            db_path=db_path,
        )
        return
    if normalized == "SKIPPED":
        update_application(
            canonical_job_id,
            status="skipped",
            notes=notes,
            next_action=next_action,
            next_action_date=next_action_date,
            db_path=db_path,
        )
        return
    raise ValueError(f"Unsupported Muse outcome: {outcome}")


def import_result_file(path: Path, *, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Muse result must be a JSON object")
    job_id = str(data.get("canonical_job_id") or "").strip()
    outcome = str(data.get("outcome") or "").strip()
    if not job_id or not outcome:
        raise ValueError("Muse result requires canonical_job_id and outcome")
    record_result(
        job_id,
        outcome,
        db_path=db_path,
        confirmation_number=str(data.get("confirmation_number") or ""),
        confirmation_text=str(data.get("confirmation_text") or ""),
        notes=str(data.get("notes") or data.get("blocking_reason") or ""),
        next_action=str(data.get("next_action") or ""),
        next_action_date=str(data.get("next_action_date") or ""),
    )
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export approved job applications to a Muse browser-execution queue.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export approved applications into Muse queue bundles.")
    export_parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    export_parser.add_argument("--output", type=Path, default=None)
    export_parser.add_argument("--config", type=Path, default=MUSE_CONFIG_PATH)
    export_parser.add_argument("--status", action="append", dest="statuses")
    export_parser.add_argument("--job-id", action="append", dest="job_ids")
    export_parser.add_argument("--json", action="store_true")

    result_parser = subparsers.add_parser("import-result", help="Import a Muse result.json into the local application tracker.")
    result_parser.add_argument("result_file", type=Path)
    result_parser.add_argument("--db", type=Path, default=DEFAULT_DB)

    args = parser.parse_args(argv)

    if args.command == "export":
        summary = export_ready_queue(
            db_path=args.db,
            output_dir=args.output,
            statuses=args.statuses,
            job_ids=args.job_ids,
            config_path=args.config,
        )
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(f"Exported {summary['exported_count']} Muse bundle(s); blocked {summary['blocked_count']}.")
            for item in summary["exported"]:
                print(f"READY | {item['company']} | {item['title']} | {item['manifest']}")
            for item in summary["blocked"]:
                print(f"BLOCKED | {item['company']} | {item['title']} | {', '.join(item['blockers'])}")
        return 0

    if args.command == "import-result":
        data = import_result_file(args.result_file, db_path=args.db)
        print(f"Imported Muse result: {data.get('canonical_job_id')} -> {data.get('outcome')}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
