from pathlib import Path

from job_pipeline.database import connect
from job_pipeline.history_import import import_history


def test_history_import_dry_run(tmp_path: Path):
    history = tmp_path / "history.yaml"
    history.write_text(
        """
version: 1
applications:
  - company: Example Markets
    title: Trading Operations Associate
    location: Toronto, ON
    country: Canada
    status: applied
    applied_at: 2026-09-26
    source: gmail
    evidence:
      - message_id: msg-1
        subject: Application received
        date: 2026-09-26
""".strip()
        + "\n",
        encoding="utf-8",
    )
    summary = import_history(history, db_path=tmp_path / "jobs.sqlite", dry_run=True)
    assert summary["imported_count"] == 1
    assert summary["skipped_count"] == 0
    assert summary["imported"][0]["status"] == "applied"


def test_history_import_writes_job_and_application(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    history = tmp_path / "history.yaml"
    history.write_text(
        """
version: 1
applications:
  - company: AP Example
    title: Execution Trader
    location: Toronto, ON
    country: Canada
    status: rejected
    applied_at: 2026-07-24
    status_updated_at: 2026-08-18
    recruiter: Recruiter Name
    confirmation_snippet: We will not be proceeding with your application.
    notes: Screening completed before rejection.
    evidence:
      - message_id: msg-reject
        thread_id: thread-1
        subject: Re: Execution Trader
        date: 2026-08-18
""".strip()
        + "\n",
        encoding="utf-8",
    )

    summary = import_history(history, db_path=db_path)
    assert summary["imported_count"] == 1
    job_id = summary["imported"][0]["canonical_job_id"]

    conn = connect(db_path)
    try:
        job = conn.execute(
            "SELECT company, title, source FROM jobs WHERE canonical_job_id = ?",
            (job_id,),
        ).fetchone()
        app = conn.execute(
            "SELECT status, applied_at, rejection_date, confirmation_snippet, notes "
            "FROM applications WHERE canonical_job_id = ?",
            (job_id,),
        ).fetchone()
        assert job["company"] == "AP Example"
        assert job["title"] == "Execution Trader"
        assert job["source"] == "gmail_history"
        assert app["status"] == "rejected"
        assert app["applied_at"] == "2026-07-24"
        assert app["rejection_date"] == "2026-08-18"
        assert "will not be proceeding" in app["confirmation_snippet"].lower()
        assert "Gmail evidence" in app["notes"]
    finally:
        conn.close()


def test_history_import_skips_unsupported_status(tmp_path: Path):
    history = tmp_path / "history.yaml"
    history.write_text(
        """
version: 1
applications:
  - company: Example
    title: Analyst
    status: maybe
""".strip()
        + "\n",
        encoding="utf-8",
    )
    summary = import_history(history, db_path=tmp_path / "jobs.sqlite")
    assert summary["imported_count"] == 0
    assert summary["skipped_count"] == 1
