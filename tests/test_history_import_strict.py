from pathlib import Path

import yaml

from job_pipeline.database import connect
from job_pipeline.history_import import import_history


def _write_history(path: Path, applications: list[dict]) -> Path:
    history = path / "history.yaml"
    history.write_text(
        yaml.safe_dump({"version": 1, "applications": applications}, allow_unicode=True),
        encoding="utf-8",
    )
    return history


def _base_record(**overrides) -> dict:
    record = {
        "company": "TD Bank",
        "title": "Canadian Commercial Banking Associate",
        "location": "Toronto, ON",
        "country": "Canada",
        "status": "applied",
        "applied_at": "2026-05-01",
        "source": "gmail",
        "evidence": [{"message_id": "msg-1", "subject": "Applied", "date": "2026-05-01"}],
    }
    record.update(overrides)
    return record


def _count_applications(db_path: Path, company: str, title: str) -> int:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE source = 'gmail_history' AND company = ? AND title = ?",
            (company, title),
        ).fetchone()
        return int(row["n"])
    finally:
        conn.close()


def test_same_company_title_different_dates_are_not_merged(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    history = _write_history(
        tmp_path,
        [
            _base_record(applied_at="2026-05-01", evidence=[{"message_id": "m1"}]),
            _base_record(applied_at="2026-06-15", evidence=[{"message_id": "m2"}]),
        ],
    )
    summary = import_history(history, db_path=db_path)
    assert summary["raw_record_count"] == 2
    assert summary["unique_record_count"] == 2
    assert summary["collision_count"] == 0
    assert _count_applications(db_path, "TD Bank", "Canadian Commercial Banking Associate") == 2


def test_td_same_title_three_dates_three_records(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    history = _write_history(
        tmp_path,
        [
            _base_record(applied_at="2026-04-10", evidence=[{"message_id": "m1"}]),
            _base_record(applied_at="2026-05-22", evidence=[{"message_id": "m2"}]),
            _base_record(applied_at="2026-07-30", evidence=[{"message_id": "m3"}]),
        ],
    )
    summary = import_history(history, db_path=db_path)
    assert summary["raw_record_count"] == 3
    assert summary["unique_record_count"] == 3
    assert summary["collision_count"] == 0
    assert _count_applications(db_path, "TD Bank", "Canadian Commercial Banking Associate") == 3


def test_same_company_title_date_different_req_ids_are_not_merged(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    history = _write_history(
        tmp_path,
        [
            _base_record(requisition_id="REQ-1001", evidence=[{"message_id": "m1"}]),
            _base_record(requisition_id="REQ-2002", evidence=[{"message_id": "m2"}]),
        ],
    )
    summary = import_history(history, db_path=db_path)
    assert summary["raw_record_count"] == 2
    assert summary["unique_record_count"] == 2
    assert summary["collision_count"] == 0
    assert _count_applications(db_path, "TD Bank", "Canadian Commercial Banking Associate") == 2
    ids = {
        row["canonical_job_id"]
        for row in summary["imported"]
    }
    assert all(canonical_id.startswith("history_req_") for canonical_id in ids)
    assert len(ids) == 2


def test_exact_canonical_id_merges_into_one(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    history = _write_history(
        tmp_path,
        [
            _base_record(applied_at="2026-05-01", evidence=[{"message_id": "m1"}]),
            _base_record(applied_at="2026-05-01", evidence=[{"message_id": "m2"}]),
        ],
    )
    summary = import_history(history, db_path=db_path)
    assert summary["raw_record_count"] == 2
    assert summary["unique_record_count"] == 1
    assert summary["collision_count"] == 1
    assert _count_applications(db_path, "TD Bank", "Canadian Commercial Banking Associate") == 1
    # Evidence from both colliding records is preserved, not silently dropped.
    conn = connect(db_path)
    try:
        app = conn.execute(
            "SELECT notes FROM applications WHERE canonical_job_id = ?",
            (summary["imported"][0]["canonical_job_id"],),
        ).fetchone()
        assert "m1" in app["notes"] and "m2" in app["notes"]
    finally:
        conn.close()


def test_collision_latest_status_updated_at_wins_and_is_reported(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    history = _write_history(
        tmp_path,
        [
            _base_record(
                status="applied",
                status_updated_at="2026-05-02",
                evidence=[{"message_id": "m-applied"}],
            ),
            _base_record(
                status="rejected",
                status_updated_at="2026-06-10",
                evidence=[{"message_id": "m-rejected"}],
            ),
        ],
    )
    summary = import_history(history, db_path=db_path)
    assert summary["raw_record_count"] == 2
    assert summary["unique_record_count"] == 1
    assert summary["collision_count"] == 1
    collision = summary["collisions"][0]
    assert collision["record_count"] == 2
    assert collision["winner_status"] == "rejected"
    assert len(collision["records"]) == 2
    winners = [record for record in collision["records"] if record["is_winner"]]
    assert len(winners) == 1
    assert winners[0]["status"] == "rejected"
    # Winner's status is the one written to the DB.
    conn = connect(db_path)
    try:
        app = conn.execute(
            "SELECT status FROM applications WHERE canonical_job_id = ?",
            (summary["imported"][0]["canonical_job_id"],),
        ).fetchone()
        assert app["status"] == "rejected"
    finally:
        conn.close()


def test_dry_run_reports_exact_final_counts(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    history = _write_history(
        tmp_path,
        [
            _base_record(applied_at="2026-05-01"),
            _base_record(applied_at="2026-05-01"),  # exact collision
            _base_record(applied_at="2026-06-15"),
            {"company": "Nope", "status": "maybe"},  # skipped: unsupported status + missing title
        ],
    )
    summary = import_history(history, db_path=db_path, dry_run=True)
    assert summary["raw_record_count"] == 4
    assert summary["unique_record_count"] == 2
    assert summary["collision_count"] == 1
    assert summary["skipped_count"] == 1
    collision = summary["collisions"][0]
    assert {record["status"] for record in collision["records"]} == {"applied"}
    # Dry-run must not touch the database.
    assert not db_path.exists()


def test_replace_history_only_removes_history_owned_jobs(tmp_path: Path):
    from job_pipeline.database import upsert_job

    db_path = tmp_path / "jobs.sqlite"
    # A regular search/ATS job that must survive replace-history.
    search_job = {
        "canonical_job_id": "search-job-1",
        "source": "company_careers",
        "source_job_id": "REQ-9",
        "title": "Data Analyst",
        "company": "Some Bank",
        "location": "Toronto, ON",
    }
    conn = connect(db_path)
    try:
        upsert_job(conn, search_job)
    finally:
        conn.close()

    history = _write_history(tmp_path, [_base_record()])
    import_history(history, db_path=db_path)
    assert _count_applications(db_path, "TD Bank", "Canadian Commercial Banking Associate") == 1

    summary = import_history(history, db_path=db_path, replace_history=True)
    assert summary["deleted_history_jobs"] == 1
    assert summary["unique_record_count"] == 1
    assert _count_applications(db_path, "TD Bank", "Canadian Commercial Banking Associate") == 1

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT canonical_job_id FROM jobs WHERE canonical_job_id = 'search-job-1'"
        ).fetchone()
        assert row is not None, "replace-history must not delete regular search jobs"
    finally:
        conn.close()
