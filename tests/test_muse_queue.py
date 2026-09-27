import json
from pathlib import Path

from job_pipeline.database import connect, update_application, upsert_job
from job_pipeline.muse_queue import export_ready_queue, import_result_file


def _seed_job(db_path: Path, resume_pdf: Path | None, apply_url: str = "https://example.com/apply") -> str:
    conn = connect(db_path)
    try:
        row, _ = upsert_job(
            conn,
            {
                "canonical_job_id": "job_muse_test_1",
                "source": "greenhouse",
                "source_job_id": "123",
                "title": "Trading Operations Associate",
                "company": "Example Markets",
                "location": "Toronto, ON",
                "country": "Canada",
                "role_category": "trading_ops",
                "role_family": "trading_operations",
                "job_url": apply_url,
                "apply_url": apply_url,
                "description": "Test description",
                "score": 82,
                "recommendation": "apply",
                "is_active": 1,
            },
        )
        job_id = row["canonical_job_id"]
    finally:
        conn.close()

    update_application(
        job_id,
        status="apply_today",
        apply_url=apply_url,
        resume_pdf_path=str(resume_pdf) if resume_pdf else "",
        db_path=db_path,
    )
    return job_id


def _write_config(path: Path, facts_path: Path) -> None:
    path.write_text(
        f"""
muse:
  queue_dir: generated/muse_queue
  approved_application_statuses:
    - apply_today
  require_apply_url: true
  require_resume_pdf: true
  facts_path: "{facts_path.as_posix()}"
  allowed_actions:
    - open_official_application_url
    - fill_application_fields_from_manifest
  stop_conditions:
    - sponsorship_or_work_authorization_ambiguity
  result_filename: result.json
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_export_ready_queue_builds_self_contained_bundle(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n% fake test pdf\n")
    facts = tmp_path / "facts.yaml"
    facts.write_text(
        """
facts:
  full_name: Example Candidate
  canada_work_authorization:
    status: Open Work Permit
preapproved_answers:
  hybrid_2_days: true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = tmp_path / "muse.yaml"
    _write_config(config, facts)

    job_id = _seed_job(db_path, resume)
    queue = tmp_path / "queue"

    summary = export_ready_queue(
        db_path=db_path,
        output_dir=queue,
        config_path=config,
    )

    assert summary["exported_count"] == 1
    assert summary["blocked_count"] == 0
    item = summary["exported"][0]
    assert item["canonical_job_id"] == job_id

    manifest_path = Path(item["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["queue_status"] == "READY_TO_APPLY"
    assert manifest["job"]["official_application_url"] == "https://example.com/apply"
    assert manifest["candidate"]["facts"]["full_name"] == "Example Candidate"
    assert manifest["execution_policy"]["discovery_allowed"] is False
    assert manifest["execution_policy"]["resume_rewriting_allowed"] is False
    assert manifest["artifacts"]["resume_pdf"] == "artifacts/resume.pdf"
    assert (manifest_path.parent / "artifacts" / "resume.pdf").exists()


def test_export_blocks_missing_required_resume(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    facts = tmp_path / "facts.yaml"
    facts.write_text("facts:\n  full_name: Example Candidate\n", encoding="utf-8")
    config = tmp_path / "muse.yaml"
    _write_config(config, facts)

    _seed_job(db_path, None)
    summary = export_ready_queue(
        db_path=db_path,
        output_dir=tmp_path / "queue",
        config_path=config,
    )

    assert summary["exported_count"] == 0
    assert summary["blocked_count"] == 1
    assert "missing resume PDF" in summary["blocked"][0]["blockers"]


def test_import_submitted_result_marks_application_applied(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n")
    job_id = _seed_job(db_path, resume)

    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "outcome": "SUBMITTED",
                "canonical_job_id": job_id,
                "timestamp": "2026-09-26T18:00:00Z",
                "notes": "Submitted through official ATS.",
                "confirmation_number": "ABC123",
                "confirmation_text": "Thank you for applying",
            }
        ),
        encoding="utf-8",
    )

    import_result_file(result_path, db_path=db_path)

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, confirmation_number, confirmation_snippet FROM applications WHERE canonical_job_id = ?",
            (job_id,),
        ).fetchone()
        assert row["status"] == "applied"
        assert row["confirmation_number"] == "ABC123"
        assert row["confirmation_snippet"] == "Thank you for applying"
    finally:
        conn.close()
