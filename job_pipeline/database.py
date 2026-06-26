from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .dedupe import canonicalize_job, description_hash, job_fingerprint, jobs_are_same, source_rank
from .freshness import enrich_freshness, iso_or_blank
from .utils import DATA_DIR, list_to_cell, now_utc_iso, normalize_space, stable_id

DEFAULT_DB = DATA_DIR / "job_pipeline.sqlite"

JOB_COLUMNS = [
    "canonical_job_id", "source", "source_job_id", "ats_company_token", "title", "normalized_title",
    "company", "canonical_company", "location", "country", "remote_type", "role_category", "seniority",
    "job_url", "apply_url", "description", "description_hash", "salary_min", "salary_max", "currency",
    "posted_at", "first_seen_at", "last_seen_at", "is_active", "score", "recommendation",
    "matched_keywords", "missing_keywords", "red_flags", "reason_to_apply", "resume_file_generated", "scheduler_resume_draft_path",
    "search_term_used", "hard_skip", "soft_penalties", "filter_reason", "all_sources", "all_source_urls",
    "freshness_label", "age_days", "is_new_since_last_run", "missing_count", "created_at", "updated_at",
]


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY,
            canonical_job_id TEXT UNIQUE,
            source TEXT,
            source_job_id TEXT,
            ats_company_token TEXT,
            title TEXT,
            normalized_title TEXT,
            company TEXT,
            canonical_company TEXT,
            location TEXT,
            country TEXT,
            remote_type TEXT,
            role_category TEXT,
            seniority TEXT,
            job_url TEXT,
            apply_url TEXT,
            description TEXT,
            description_hash TEXT,
            salary_min REAL,
            salary_max REAL,
            currency TEXT,
            posted_at TEXT,
            first_seen_at TEXT,
            last_seen_at TEXT,
            is_active INTEGER,
            score INTEGER,
            recommendation TEXT,
            matched_keywords TEXT,
            missing_keywords TEXT,
            red_flags TEXT,
            reason_to_apply TEXT,
            resume_file_generated TEXT,
            scheduler_resume_draft_path TEXT,
            search_term_used TEXT,
            hard_skip INTEGER DEFAULT 0,
            soft_penalties TEXT,
            filter_reason TEXT,
            all_sources TEXT,
            all_source_urls TEXT,
            freshness_label TEXT,
            age_days INTEGER,
            is_new_since_last_run INTEGER,
            missing_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS job_snapshots (
            id INTEGER PRIMARY KEY,
            canonical_job_id TEXT,
            collected_at TEXT,
            source TEXT,
            raw_json_path TEXT,
            description_hash TEXT,
            score INTEGER,
            is_active INTEGER
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY,
            canonical_job_id TEXT UNIQUE,
            status TEXT,
            status_updated_at TEXT,
            applied_at TEXT,
            resume_used TEXT,
            cover_letter_used TEXT,
            account_used TEXT,
            apply_url TEXT,
            confirmation_number TEXT,
            confirmation_snippet TEXT,
            notes TEXT,
            next_action TEXT,
            next_action_date TEXT,
            interview_date TEXT,
            rejection_date TEXT,
            company_response TEXT
        );

        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY,
            canonical_company TEXT UNIQUE,
            display_name TEXT,
            region_focus TEXT,
            industry_tags TEXT,
            ats_type TEXT,
            ats_token TEXT,
            careers_url TEXT,
            priority INTEGER,
            last_checked_at TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS search_coverage (
            id INTEGER PRIMARY KEY,
            run_id TEXT,
            run_started_at TEXT,
            run_finished_at TEXT,
            mode TEXT,
            country TEXT,
            source TEXT,
            query TEXT,
            location TEXT,
            raw_count INTEGER,
            normalized_count INTEGER,
            deduped_count INTEGER,
            scored_count INTEGER,
            report_count INTEGER,
            skipped_by_filter_count INTEGER,
            merged_by_dedupe_count INTEGER,
            average_score REAL,
            high_score_count_70 INTEGER,
            must_apply_count_85 INTEGER,
            error_count INTEGER,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS source_health (
            id INTEGER PRIMARY KEY,
            run_id TEXT,
            source TEXT,
            enabled INTEGER,
            last_run_at TEXT,
            last_success_at TEXT,
            last_error_at TEXT,
            last_error_message TEXT,
            raw_count_last_run INTEGER,
            normalized_count_last_run INTEGER,
            average_latency_ms REAL,
            consecutive_failures INTEGER,
            status TEXT
        );

        CREATE TABLE IF NOT EXISTS manual_search_urls (
            id INTEGER PRIMARY KEY,
            source_name TEXT,
            country TEXT,
            query TEXT,
            location TEXT,
            search_url TEXT,
            generated_at TEXT,
            last_checked_at TEXT,
            notes TEXT,
            UNIQUE(source_name, country, query, location, search_url)
        );

        CREATE TABLE IF NOT EXISTS campaign_items (
            id INTEGER PRIMARY KEY,
            campaign_date TEXT,
            canonical_job_id TEXT,
            application_effort TEXT,
            campaign_priority INTEGER,
            campaign_reason TEXT,
            resume_profile TEXT,
            profile_resume_path TEXT,
            tailored_resume_path TEXT,
            answer_pack_path TEXT,
            estimated_minutes INTEGER,
            auto_generate_resume INTEGER DEFAULT 0,
            allow_manual_generate_resume INTEGER DEFAULT 0,
            auto_generate_answer_pack INTEGER DEFAULT 0,
            allow_manual_generate_answer_pack INTEGER DEFAULT 0,
            should_generate_resume INTEGER DEFAULT 0,
            should_generate_answer_pack INTEGER DEFAULT 0,
            campaign_status TEXT,
            selected_at TEXT,
            completed_at TEXT,
            notes TEXT,
            UNIQUE(campaign_date, canonical_job_id)
        );
        CREATE TABLE IF NOT EXISTS job_merge_events (
            id INTEGER PRIMARY KEY,
            run_id TEXT,
            incoming_source TEXT,
            incoming_title TEXT,
            incoming_company TEXT,
            incoming_location TEXT,
            incoming_url TEXT,
            merged_into_canonical_job_id TEXT,
            existing_title TEXT,
            existing_company TEXT,
            existing_location TEXT,
            reason TEXT,
            title_similarity REAL,
            company_similarity REAL,
            location_similarity REAL,
            description_similarity REAL,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_source_id ON jobs(source, source_job_id);
        CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(job_url);
        CREATE INDEX IF NOT EXISTS idx_jobs_apply_url ON jobs(apply_url);
        CREATE INDEX IF NOT EXISTS idx_jobs_company_title ON jobs(canonical_company, normalized_title);
        CREATE INDEX IF NOT EXISTS idx_snapshots_job ON job_snapshots(canonical_job_id);
        CREATE INDEX IF NOT EXISTS idx_search_coverage_run ON search_coverage(run_id);
        CREATE INDEX IF NOT EXISTS idx_source_health_run ON source_health(run_id);
        CREATE INDEX IF NOT EXISTS idx_manual_search_country ON manual_search_urls(country, source_name);
        CREATE INDEX IF NOT EXISTS idx_campaign_items_date ON campaign_items(campaign_date, application_effort, campaign_status);
        CREATE INDEX IF NOT EXISTS idx_campaign_items_job ON campaign_items(canonical_job_id);
        CREATE INDEX IF NOT EXISTS idx_merge_events_run ON job_merge_events(run_id);
        """
    )
    _ensure_job_columns(conn)
    _ensure_application_columns(conn)
    _ensure_campaign_item_columns(conn)
    conn.commit()


APPLICATION_EXTRA_COLUMNS = {
    "apply_url": "TEXT",
    "confirmation_number": "TEXT",
    "confirmation_snippet": "TEXT",
}


JOB_EXTRA_COLUMNS = {
    "scheduler_resume_draft_path": "TEXT",
    "search_term_used": "TEXT",
    "hard_skip": "INTEGER DEFAULT 0",
    "soft_penalties": "TEXT",
    "filter_reason": "TEXT",
    "all_sources": "TEXT",
    "all_source_urls": "TEXT",
    "application_effort": "TEXT",
    "resume_profile": "TEXT",
    "profile_resume_path": "TEXT",
    "tailored_resume_path": "TEXT",
    "answer_pack_path": "TEXT",
    "campaign_priority": "INTEGER",
    "campaign_reason": "TEXT",
    "estimated_minutes": "INTEGER DEFAULT 0",
    "auto_generate_resume": "INTEGER DEFAULT 0",
    "allow_manual_generate_resume": "INTEGER DEFAULT 0",
    "auto_generate_answer_pack": "INTEGER DEFAULT 0",
    "allow_manual_generate_answer_pack": "INTEGER DEFAULT 0",
    "should_generate_resume": "INTEGER DEFAULT 0",
    "should_generate_answer_pack": "INTEGER DEFAULT 0",
    "campaign_date": "TEXT",
    "campaign_status": "TEXT",
}

CAMPAIGN_ITEM_COLUMNS = [
    "campaign_date", "canonical_job_id", "application_effort", "campaign_priority", "campaign_reason",
    "resume_profile", "profile_resume_path", "tailored_resume_path", "answer_pack_path",
    "estimated_minutes", "auto_generate_resume", "allow_manual_generate_resume",
    "auto_generate_answer_pack", "allow_manual_generate_answer_pack",
    "should_generate_resume", "should_generate_answer_pack", "campaign_status",
    "selected_at", "completed_at", "notes",
]

CAMPAIGN_ITEM_EXTRA_COLUMNS = {
    "auto_generate_resume": "INTEGER DEFAULT 0",
    "allow_manual_generate_resume": "INTEGER DEFAULT 0",
    "auto_generate_answer_pack": "INTEGER DEFAULT 0",
    "allow_manual_generate_answer_pack": "INTEGER DEFAULT 0",
    "should_generate_resume": "INTEGER DEFAULT 0",
    "should_generate_answer_pack": "INTEGER DEFAULT 0",
}

def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_job_columns(conn: sqlite3.Connection) -> None:
    existing = _table_columns(conn, "jobs")
    for column, column_type in JOB_EXTRA_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {column_type}")

def _ensure_application_columns(conn: sqlite3.Connection) -> None:
    existing = _table_columns(conn, "applications")
    for column, column_type in APPLICATION_EXTRA_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE applications ADD COLUMN {column} {column_type}")



def _ensure_campaign_item_columns(conn: sqlite3.Connection) -> None:
    existing = _table_columns(conn, "campaign_items")
    for column, column_type in CAMPAIGN_ITEM_EXTRA_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE campaign_items ADD COLUMN {column} {column_type}")

def _json_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _parse_cell(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _row_to_job(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for key in ["matched_keywords", "missing_keywords", "red_flags", "soft_penalties", "all_sources", "all_source_urls"]:
        data[key] = _parse_cell(data.get(key)) or []
    data["hard_skip"] = bool(data.get("hard_skip"))
    return data

def prepare_job_for_db(job: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    now = now or now_utc_iso()
    row = canonicalize_job(job)
    row["canonical_job_id"] = row.get("canonical_job_id") or stable_id(
        row.get("canonical_company"), row.get("normalized_title"), row.get("normalized_location")
    )
    row["source_job_id"] = normalize_space(row.get("source_job_id") or row.get("job_id"))
    row["country"] = row.get("detected_country") or row.get("country") or ""
    row["posted_at"] = iso_or_blank(row.get("posted_at") or row.get("date_posted"))
    row["description_hash"] = row.get("description_hash") or description_hash(row.get("description"))
    row["first_seen_at"] = row.get("first_seen_at") or now
    row["last_seen_at"] = row.get("last_seen_at") or now
    row["is_active"] = int(row.get("is_active", 1))
    row["score"] = int(row.get("score") or 0)
    row["matched_keywords"] = _json_cell(row.get("matched_keywords") or [])
    row["missing_keywords"] = _json_cell(row.get("missing_keywords") or row.get("missing_keywords_from_master_resume") or [])
    row["red_flags"] = _json_cell(row.get("red_flags") or [])
    row["scheduler_resume_draft_path"] = normalize_space(row.get("scheduler_resume_draft_path") or row.get("resume_file_generated") or "")
    row["search_term_used"] = normalize_space(row.get("search_term_used") or row.get("query") or "")
    row["hard_skip"] = int(bool(row.get("hard_skip")))
    row["soft_penalties"] = _json_cell(row.get("soft_penalties") or [])
    row["filter_reason"] = normalize_space(row.get("filter_reason") or "")
    row["all_sources"] = _json_cell(row.get("all_sources") or ([row.get("source")] if row.get("source") else []))
    row["all_source_urls"] = _json_cell(row.get("all_source_urls") or [url for url in [row.get("job_url"), row.get("apply_url")] if url])
    row["created_at"] = row.get("created_at") or now
    row["updated_at"] = now
    row["missing_count"] = int(row.get("missing_count") or 0)
    row = enrich_freshness(row)
    return row


def _existing_candidates(conn: sqlite3.Connection, job: dict[str, Any]) -> list[sqlite3.Row]:
    candidates: list[sqlite3.Row] = []
    source = normalize_space(job.get("source"))
    source_id = normalize_space(job.get("source_job_id"))
    if source and source_id:
        candidates.extend(conn.execute("SELECT * FROM jobs WHERE source = ? AND source_job_id = ?", (source, source_id)).fetchall())
    for field in ["job_url", "apply_url"]:
        value = normalize_space(job.get(field))
        if value:
            candidates.extend(conn.execute(f"SELECT * FROM jobs WHERE {field} = ?", (value,)).fetchall())
    fp_company = job.get("canonical_company") or ""
    if fp_company:
        candidates.extend(conn.execute("SELECT * FROM jobs WHERE canonical_company = ?", (fp_company,)).fetchall())
    seen = set()
    unique: list[sqlite3.Row] = []
    for row in candidates:
        if row["canonical_job_id"] not in seen:
            unique.append(row)
            seen.add(row["canonical_job_id"])
    return unique


def find_existing_job(conn: sqlite3.Connection, job: dict[str, Any]) -> sqlite3.Row | None:
    row_job = prepare_job_for_db(job)
    for candidate in _existing_candidates(conn, row_job):
        if jobs_are_same(_row_to_job(candidate), row_job):
            return candidate
    return None


def _choose_primary(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if source_rank(incoming.get("source")) > source_rank(existing.get("source")):
        base, fallback = incoming, existing
    else:
        base, fallback = existing, incoming
    merged = dict(base)
    for key, value in fallback.items():
        if merged.get(key) in (None, "", []):
            merged[key] = value
    incoming_has_score = incoming.get("score") not in (None, "")
    if incoming_has_score:
        merged["score"] = int(incoming.get("score") or 0)
        for key in ["recommendation", "matched_keywords", "missing_keywords", "red_flags", "reason_to_apply", "resume_file_generated", "scheduler_resume_draft_path", "hard_skip", "soft_penalties", "filter_reason"]:
            merged[key] = incoming.get(key, merged.get(key))
    else:
        merged["score"] = int(existing.get("score") or 0)
    return merged


def upsert_companies(conn: sqlite3.Connection, companies: list[dict[str, Any]]) -> None:
    now = now_utc_iso()
    for company in companies:
        conn.execute(
            """
            INSERT INTO companies (canonical_company, display_name, region_focus, industry_tags, ats_type, ats_token, careers_url, priority, last_checked_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_company) DO UPDATE SET
                display_name=excluded.display_name,
                region_focus=excluded.region_focus,
                industry_tags=excluded.industry_tags,
                ats_type=excluded.ats_type,
                ats_token=excluded.ats_token,
                careers_url=excluded.careers_url,
                priority=excluded.priority,
                last_checked_at=excluded.last_checked_at,
                notes=excluded.notes
            """,
            (
                company.get("canonical_company"),
                company.get("display_name"),
                _json_cell(company.get("region_focus") or []),
                _json_cell(company.get("industry_tags") or []),
                company.get("ats_type"),
                company.get("ats_token"),
                company.get("careers_url"),
                company.get("priority", 3),
                now,
                company.get("notes", ""),
            ),
        )
    conn.commit()


def upsert_job(conn: sqlite3.Connection, job: dict[str, Any], raw_json_path: str = "") -> tuple[dict[str, Any], bool]:
    now = now_utc_iso()
    incoming = prepare_job_for_db(job, now=now)
    existing_row = find_existing_job(conn, incoming)
    is_new = existing_row is None
    if existing_row:
        existing = _row_to_job(existing_row)
        incoming["canonical_job_id"] = existing["canonical_job_id"]
        incoming["first_seen_at"] = existing.get("first_seen_at") or now
        incoming["created_at"] = existing.get("created_at") or now
        incoming["missing_count"] = 0
        incoming = _choose_primary(existing, incoming)
        incoming["last_seen_at"] = now
        incoming["updated_at"] = now
        incoming["is_active"] = 1
        incoming["is_new_since_last_run"] = 0
    else:
        incoming["first_seen_at"] = incoming.get("first_seen_at") or now
        incoming["last_seen_at"] = now
        incoming["created_at"] = now
        incoming["updated_at"] = now
        incoming["is_new_since_last_run"] = 1
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
            incoming.get("canonical_job_id"),
            now,
            incoming.get("source"),
            raw_json_path,
            incoming.get("description_hash"),
            incoming.get("score"),
            1,
        ),
    )
    conn.commit()
    return _row_to_job(conn.execute("SELECT * FROM jobs WHERE canonical_job_id = ?", (incoming["canonical_job_id"],)).fetchone()), is_new


def mark_missing_inactive(conn: sqlite3.Connection, seen_canonical_ids: set[str], inactive_after_misses: int = 3) -> None:
    rows = conn.execute("SELECT canonical_job_id, missing_count FROM jobs WHERE is_active = 1").fetchall()
    now = now_utc_iso()
    for row in rows:
        canonical_id = row["canonical_job_id"]
        if canonical_id in seen_canonical_ids:
            continue
        missing_count = int(row["missing_count"] or 0) + 1
        is_active = 0 if missing_count >= inactive_after_misses else 1
        conn.execute(
            "UPDATE jobs SET missing_count = ?, is_active = ?, updated_at = ? WHERE canonical_job_id = ?",
            (missing_count, is_active, now, canonical_id),
        )
    conn.commit()


def upsert_jobs(db_path: Path, jobs: list[dict[str, Any]], raw_json_path: str = "", mark_missing: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conn = connect(db_path)
    rows: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for job in jobs:
            row, is_new = upsert_job(conn, job, raw_json_path=raw_json_path)
            rows.append(row)
            seen.add(row["canonical_job_id"])
            if is_new:
                new_rows.append(row)
        if mark_missing:
            mark_missing_inactive(conn, seen)
    finally:
        conn.close()
    return rows, new_rows


def update_application(
    canonical_job_id: str,
    *,
    status: str | None = None,
    resume_used: str | None = None,
    cover_letter_used: str | None = None,
    account_used: str | None = None,
    apply_url: str | None = None,
    confirmation_number: str | None = None,
    confirmation_snippet: str | None = None,
    notes: str | None = None,
    next_action: str | None = None,
    next_action_date: str | None = None,
    applied_at: str | None = None,
    interview_date: str | None = None,
    rejection_date: str | None = None,
    company_response: str | None = None,
    db_path: Path = DEFAULT_DB,
) -> None:
    now = now_utc_iso()
    conn = connect(db_path)
    try:
        existing = conn.execute("SELECT * FROM applications WHERE canonical_job_id = ?", (canonical_job_id,)).fetchone()
        current = dict(existing) if existing else {"canonical_job_id": canonical_job_id}
        updates = {
            "status": status or current.get("status") or "reviewed",
            "status_updated_at": now,
            "applied_at": applied_at if applied_at is not None else current.get("applied_at", ""),
            "resume_used": resume_used if resume_used is not None else current.get("resume_used", ""),
            "cover_letter_used": cover_letter_used if cover_letter_used is not None else current.get("cover_letter_used", ""),
            "account_used": account_used if account_used is not None else current.get("account_used", ""),
            "apply_url": apply_url if apply_url is not None else current.get("apply_url", ""),
            "confirmation_number": confirmation_number if confirmation_number is not None else current.get("confirmation_number", ""),
            "confirmation_snippet": confirmation_snippet if confirmation_snippet is not None else current.get("confirmation_snippet", ""),
            "notes": notes if notes is not None else current.get("notes", ""),
            "next_action": next_action if next_action is not None else current.get("next_action", ""),
            "next_action_date": next_action_date if next_action_date is not None else current.get("next_action_date", ""),
            "interview_date": interview_date if interview_date is not None else current.get("interview_date", ""),
            "rejection_date": rejection_date if rejection_date is not None else current.get("rejection_date", ""),
            "company_response": company_response if company_response is not None else current.get("company_response", ""),
        }
        conn.execute(
            """
            INSERT INTO applications (canonical_job_id, status, status_updated_at, applied_at, resume_used, cover_letter_used, account_used, apply_url, confirmation_number, confirmation_snippet, notes, next_action, next_action_date, interview_date, rejection_date, company_response)
            VALUES (:canonical_job_id, :status, :status_updated_at, :applied_at, :resume_used, :cover_letter_used, :account_used, :apply_url, :confirmation_number, :confirmation_snippet, :notes, :next_action, :next_action_date, :interview_date, :rejection_date, :company_response)
            ON CONFLICT(canonical_job_id) DO UPDATE SET
                status=excluded.status,
                status_updated_at=excluded.status_updated_at,
                applied_at=excluded.applied_at,
                resume_used=excluded.resume_used,
                cover_letter_used=excluded.cover_letter_used,
                account_used=excluded.account_used,
                apply_url=excluded.apply_url,
                confirmation_number=excluded.confirmation_number,
                confirmation_snippet=excluded.confirmation_snippet,
                notes=excluded.notes,
                next_action=excluded.next_action,
                next_action_date=excluded.next_action_date,
                interview_date=excluded.interview_date,
                rejection_date=excluded.rejection_date,
                company_response=excluded.company_response
            """,
            {"canonical_job_id": canonical_job_id, **updates},
        )
        conn.commit()
    finally:
        conn.close()


def get_jobs(db_path: Path = DEFAULT_DB, include_inactive: bool = True) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        sql = """
            SELECT j.*, COALESCE(a.status, 'new') AS status, a.next_action, a.next_action_date, a.applied_at,
                   a.resume_used, a.apply_url AS application_apply_url, a.confirmation_number,
                   a.confirmation_snippet, a.notes, a.interview_date, a.rejection_date, a.company_response
            FROM jobs j
            LEFT JOIN applications a ON a.canonical_job_id = j.canonical_job_id
        """
        if not include_inactive:
            sql += " WHERE j.is_active = 1"
        sql += " ORDER BY j.is_new_since_last_run DESC, j.score DESC, j.updated_at DESC"
        return [_row_to_job(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def get_job_detail(canonical_job_id: str, db_path: Path = DEFAULT_DB) -> dict[str, Any] | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT j.*, COALESCE(a.status, 'new') AS status, a.next_action, a.next_action_date, a.applied_at,
                   a.resume_used, a.cover_letter_used, a.account_used, a.apply_url AS application_apply_url,
                   a.confirmation_number, a.confirmation_snippet, a.notes, a.interview_date,
                   a.rejection_date, a.company_response
            FROM jobs j
            LEFT JOIN applications a ON a.canonical_job_id = j.canonical_job_id
            WHERE j.canonical_job_id = ?
            """,
            (canonical_job_id,),
        ).fetchone()
        if not row:
            return None
        detail = _row_to_job(row)
        detail["snapshots"] = [dict(item) for item in conn.execute("SELECT * FROM job_snapshots WHERE canonical_job_id = ? ORDER BY collected_at DESC", (canonical_job_id,)).fetchall()]
        return detail
    finally:
        conn.close()


def get_applications(db_path: Path = DEFAULT_DB) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM applications ORDER BY status_updated_at DESC").fetchall()]
    finally:
        conn.close()


JOB_CAMPAIGN_SYNC_COLUMNS = [
    "application_effort", "resume_profile", "profile_resume_path", "tailored_resume_path",
    "answer_pack_path", "campaign_priority", "campaign_reason", "estimated_minutes",
    "auto_generate_resume", "allow_manual_generate_resume",
    "auto_generate_answer_pack", "allow_manual_generate_answer_pack",
    "should_generate_resume", "should_generate_answer_pack", "campaign_date", "campaign_status",
]


def _int_cell(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _campaign_item_values(row: dict[str, Any], now: str) -> dict[str, Any]:
    values = {column: row.get(column, "") for column in CAMPAIGN_ITEM_COLUMNS}
    values["campaign_priority"] = _int_cell(values.get("campaign_priority"))
    values["estimated_minutes"] = _int_cell(values.get("estimated_minutes"))
    for flag in ["auto_generate_resume", "allow_manual_generate_resume", "auto_generate_answer_pack", "allow_manual_generate_answer_pack", "should_generate_resume", "should_generate_answer_pack"]:
        values[flag] = int(bool(values.get(flag)))
    values["campaign_status"] = values.get("campaign_status") or "queued"
    values["selected_at"] = values.get("selected_at") or now
    values["completed_at"] = values.get("completed_at") or ""
    values["notes"] = values.get("notes") or ""
    return values


def _sync_campaign_fields_to_job(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    canonical_job_id = str(row.get("canonical_job_id") or "")
    if not canonical_job_id:
        return
    values = {column: row.get(column, "") for column in JOB_CAMPAIGN_SYNC_COLUMNS}
    values["canonical_job_id"] = canonical_job_id
    assignments = ", ".join(f"{column} = :{column}" for column in JOB_CAMPAIGN_SYNC_COLUMNS)
    conn.execute(f"UPDATE jobs SET {assignments} WHERE canonical_job_id = :canonical_job_id", values)


def save_campaign_items(db_path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    now = now_utc_iso()
    placeholders = ", ".join(":" + column for column in CAMPAIGN_ITEM_COLUMNS)
    assignments = ",\n                ".join(
        [
            "application_effort=excluded.application_effort",
            "campaign_priority=excluded.campaign_priority",
            "campaign_reason=excluded.campaign_reason",
            "resume_profile=excluded.resume_profile",
            "profile_resume_path=excluded.profile_resume_path",
            "tailored_resume_path=excluded.tailored_resume_path",
            "answer_pack_path=excluded.answer_pack_path",
            "estimated_minutes=excluded.estimated_minutes",
            "auto_generate_resume=excluded.auto_generate_resume",
            "allow_manual_generate_resume=excluded.allow_manual_generate_resume",
            "auto_generate_answer_pack=excluded.auto_generate_answer_pack",
            "allow_manual_generate_answer_pack=excluded.allow_manual_generate_answer_pack",
            "should_generate_resume=excluded.should_generate_resume",
            "should_generate_answer_pack=excluded.should_generate_answer_pack",
            "campaign_status=CASE WHEN campaign_items.campaign_status IN ('applied', 'skipped') THEN campaign_items.campaign_status ELSE excluded.campaign_status END",
            "selected_at=CASE WHEN campaign_items.selected_at IS NOT NULL AND campaign_items.selected_at != '' THEN campaign_items.selected_at ELSE excluded.selected_at END",
            "completed_at=CASE WHEN campaign_items.completed_at IS NOT NULL AND campaign_items.completed_at != '' THEN campaign_items.completed_at ELSE excluded.completed_at END",
            "notes=CASE WHEN campaign_items.notes IS NOT NULL AND campaign_items.notes != '' THEN campaign_items.notes ELSE excluded.notes END",
        ]
    )
    conn = connect(db_path)
    try:
        for raw in rows:
            values = _campaign_item_values(raw, now)
            conn.execute(
                f"""
                INSERT INTO campaign_items ({', '.join(CAMPAIGN_ITEM_COLUMNS)})
                VALUES ({placeholders})
                ON CONFLICT(campaign_date, canonical_job_id) DO UPDATE SET
                {assignments}
                """,
                values,
            )
            _sync_campaign_fields_to_job(conn, values)
        conn.commit()
    finally:
        conn.close()


def replace_campaign_items(db_path: Path, campaign_date: str, rows: list[dict[str, Any]]) -> None:
    keep_ids = [str(row.get("canonical_job_id") or "") for row in rows if str(row.get("canonical_job_id") or "")]
    conn = connect(db_path)
    try:
        if keep_ids:
            placeholders = ", ".join("?" for _ in keep_ids)
            conn.execute(
                f"""
                DELETE FROM campaign_items
                WHERE campaign_date = ?
                  AND canonical_job_id NOT IN ({placeholders})
                  AND campaign_status != 'applied'
                """,
                [campaign_date, *keep_ids],
            )
        else:
            conn.execute(
                "DELETE FROM campaign_items WHERE campaign_date = ? AND campaign_status != 'applied'",
                (campaign_date,),
            )
        conn.commit()
    finally:
        conn.close()
    save_campaign_items(db_path, rows)


def _campaign_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ["matched_keywords", "missing_keywords", "red_flags", "soft_penalties"]:
        if key in data:
            data[key] = _parse_cell(data.get(key)) or []
    data["hard_skip"] = bool(data.get("hard_skip"))
    new_flags = ["auto_generate_resume", "allow_manual_generate_resume", "auto_generate_answer_pack", "allow_manual_generate_answer_pack"]
    legacy_new_flags_empty = not any(data.get(flag) for flag in new_flags)
    for flag in [*new_flags, "should_generate_resume", "should_generate_answer_pack"]:
        data[flag] = bool(data.get(flag))
    if legacy_new_flags_empty:
        effort = str(data.get("application_effort") or "")
        data["auto_generate_resume"] = bool(data.get("should_generate_resume"))
        data["auto_generate_answer_pack"] = bool(data.get("should_generate_answer_pack"))
        data["allow_manual_generate_resume"] = effort in {"deep_tailor", "standard_tailor"}
        data["allow_manual_generate_answer_pack"] = effort in {"deep_tailor", "standard_tailor"}
    return data


def get_campaign_items(db_path: Path = DEFAULT_DB, campaign_date: str | None = None) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        sql = """
            SELECT ci.*,
                   j.score, j.recommendation, j.title, j.company, j.canonical_company, j.location, j.country,
                   j.remote_type, j.role_category, j.seniority, j.job_url, j.apply_url, j.description,
                   j.posted_at, j.first_seen_at, j.last_seen_at, j.freshness_label, j.is_new_since_last_run,
                   j.matched_keywords, j.missing_keywords, j.red_flags, j.hard_skip, j.soft_penalties,
                   j.filter_reason, j.reason_to_apply, j.resume_file_generated, j.scheduler_resume_draft_path,
                   COALESCE(a.status, 'new') AS application_status,
                   a.applied_at, a.resume_used, a.apply_url AS application_apply_url,
                   a.confirmation_number, a.confirmation_snippet, a.notes AS application_notes
            FROM campaign_items ci
            JOIN jobs j ON j.canonical_job_id = ci.canonical_job_id
            LEFT JOIN applications a ON a.canonical_job_id = ci.canonical_job_id
        """
        params: list[Any] = []
        if campaign_date:
            sql += " WHERE ci.campaign_date = ?"
            params.append(campaign_date)
        sql += " ORDER BY ci.campaign_date DESC, ci.campaign_priority ASC, j.score DESC"
        return [_campaign_row(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_latest_campaign_date(db_path: Path = DEFAULT_DB) -> str:
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT campaign_date FROM campaign_items ORDER BY campaign_date DESC LIMIT 1").fetchone()
        return str(row["campaign_date"] or "") if row else ""
    finally:
        conn.close()


def update_campaign_item_files(
    campaign_date: str,
    canonical_job_id: str,
    *,
    profile_resume_path: str | None = None,
    tailored_resume_path: str | None = None,
    answer_pack_path: str | None = None,
    db_path: Path = DEFAULT_DB,
) -> None:
    updates = {
        key: value
        for key, value in {
            "profile_resume_path": profile_resume_path,
            "tailored_resume_path": tailored_resume_path,
            "answer_pack_path": answer_pack_path,
        }.items()
        if value is not None
    }
    if not updates:
        return
    updates["campaign_date"] = campaign_date
    updates["canonical_job_id"] = canonical_job_id
    assignments = ", ".join(f"{column} = :{column}" for column in updates if column not in {"campaign_date", "canonical_job_id"})
    conn = connect(db_path)
    try:
        conn.execute(
            f"UPDATE campaign_items SET {assignments} WHERE campaign_date = :campaign_date AND canonical_job_id = :canonical_job_id",
            updates,
        )
        job_assignments = ", ".join(f"{column} = :{column}" for column in updates if column not in {"campaign_date", "canonical_job_id"})
        conn.execute(f"UPDATE jobs SET {job_assignments} WHERE canonical_job_id = :canonical_job_id", updates)
        conn.commit()
    finally:
        conn.close()


def update_campaign_item_status(
    campaign_date: str,
    canonical_job_id: str,
    status: str,
    *,
    notes: str | None = None,
    db_path: Path = DEFAULT_DB,
) -> None:
    now = now_utc_iso()
    completed_at = now if status in {"applied", "skipped", "moved_to_hold"} else ""
    conn = connect(db_path)
    try:
        params = {
            "campaign_date": campaign_date,
            "canonical_job_id": canonical_job_id,
            "campaign_status": status,
            "completed_at": completed_at,
            "notes": notes,
        }
        if notes is None:
            conn.execute(
                """
                UPDATE campaign_items
                SET campaign_status = :campaign_status,
                    completed_at = CASE WHEN :completed_at != '' THEN :completed_at ELSE completed_at END
                WHERE campaign_date = :campaign_date AND canonical_job_id = :canonical_job_id
                """,
                params,
            )
        else:
            conn.execute(
                """
                UPDATE campaign_items
                SET campaign_status = :campaign_status,
                    completed_at = CASE WHEN :completed_at != '' THEN :completed_at ELSE completed_at END,
                    notes = :notes
                WHERE campaign_date = :campaign_date AND canonical_job_id = :canonical_job_id
                """,
                params,
            )
        row = conn.execute(
            """
            SELECT ci.*, j.apply_url, j.job_url, j.resume_file_generated, j.scheduler_resume_draft_path,
                   a.apply_url AS application_apply_url
            FROM campaign_items ci
            JOIN jobs j ON j.canonical_job_id = ci.canonical_job_id
            LEFT JOIN applications a ON a.canonical_job_id = ci.canonical_job_id
            WHERE ci.campaign_date = ? AND ci.canonical_job_id = ?
            """,
            (campaign_date, canonical_job_id),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    if status == "applied" and row:
        resume_used = str(row["tailored_resume_path"] or row["profile_resume_path"] or "")
        apply_url = str(row["application_apply_url"] or row["apply_url"] or row["job_url"] or "")
        update_application(
            canonical_job_id,
            status="applied",
            applied_at=now,
            resume_used=resume_used,
            apply_url=apply_url,
            notes=notes,
            db_path=db_path,
        )

def get_companies(db_path: Path = DEFAULT_DB) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT c.*,
                   COUNT(j.id) FILTER (WHERE j.is_active = 1) AS active_jobs_count,
                   COUNT(j.id) FILTER (WHERE j.is_active = 1 AND j.score >= 70) AS high_score_jobs_count
            FROM companies c
            LEFT JOIN jobs j ON j.canonical_company = c.canonical_company
            GROUP BY c.id
            ORDER BY c.priority ASC, high_score_jobs_count DESC, c.display_name ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
SEARCH_COVERAGE_COLUMNS = [
    "run_id", "run_started_at", "run_finished_at", "mode", "country", "source", "query", "location",
    "raw_count", "normalized_count", "deduped_count", "scored_count", "report_count",
    "skipped_by_filter_count", "merged_by_dedupe_count", "average_score", "high_score_count_70",
    "must_apply_count_85", "error_count", "error_message",
]

SOURCE_HEALTH_COLUMNS = [
    "run_id", "source", "enabled", "last_run_at", "last_success_at", "last_error_at", "last_error_message",
    "raw_count_last_run", "normalized_count_last_run", "average_latency_ms", "consecutive_failures", "status",
]

MANUAL_SEARCH_COLUMNS = [
    "source_name", "country", "query", "location", "search_url", "generated_at", "last_checked_at", "notes",
]

MERGE_EVENT_COLUMNS = [
    "run_id", "incoming_source", "incoming_title", "incoming_company", "incoming_location", "incoming_url",
    "merged_into_canonical_job_id", "existing_title", "existing_company", "existing_location", "reason",
    "title_similarity", "company_similarity", "location_similarity", "description_similarity",
]


def _insert_rows(conn: sqlite3.Connection, table: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    placeholders = ", ".join([":" + column for column in columns])
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [{column: row.get(column, "") for column in columns} for row in rows],
    )


def save_search_coverage(db_path: Path, rows: list[dict[str, Any]]) -> None:
    conn = connect(db_path)
    try:
        run_ids = {str(row.get("run_id") or "") for row in rows if row.get("run_id")}
        for run_id in run_ids:
            conn.execute("DELETE FROM search_coverage WHERE run_id = ?", (run_id,))
        _insert_rows(conn, "search_coverage", SEARCH_COVERAGE_COLUMNS, rows)
        conn.commit()
    finally:
        conn.close()


def get_search_coverage_rows(db_path: Path = DEFAULT_DB, *, latest: bool = True) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        if latest:
            run = conn.execute("SELECT run_id FROM search_coverage ORDER BY run_started_at DESC, id DESC LIMIT 1").fetchone()
            if not run:
                return []
            rows = conn.execute("SELECT * FROM search_coverage WHERE run_id = ? ORDER BY country, source, query, location", (run["run_id"],)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM search_coverage ORDER BY run_started_at DESC, country, source, query, location").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def save_source_health(db_path: Path, rows: list[dict[str, Any]]) -> None:
    conn = connect(db_path)
    try:
        run_ids = {str(row.get("run_id") or "") for row in rows if row.get("run_id")}
        for run_id in run_ids:
            conn.execute("DELETE FROM source_health WHERE run_id = ?", (run_id,))
        _insert_rows(conn, "source_health", SOURCE_HEALTH_COLUMNS, rows)
        conn.commit()
    finally:
        conn.close()


def get_source_health_rows(db_path: Path = DEFAULT_DB, *, latest: bool = True) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        if latest:
            run = conn.execute("SELECT run_id FROM source_health ORDER BY last_run_at DESC, id DESC LIMIT 1").fetchone()
            if not run:
                return []
            rows = conn.execute("SELECT * FROM source_health WHERE run_id = ? ORDER BY status DESC, source", (run["run_id"],)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM source_health ORDER BY last_run_at DESC, source").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def upsert_manual_search_urls(db_path: Path, rows: list[dict[str, Any]]) -> None:
    conn = connect(db_path)
    try:
        for row in rows:
            conn.execute(
                """
                INSERT INTO manual_search_urls (source_name, country, query, location, search_url, generated_at, last_checked_at, notes)
                VALUES (:source_name, :country, :query, :location, :search_url, :generated_at, :last_checked_at, :notes)
                ON CONFLICT(source_name, country, query, location, search_url) DO UPDATE SET
                    generated_at=excluded.generated_at,
                    notes=excluded.notes,
                    last_checked_at=CASE
                        WHEN manual_search_urls.last_checked_at IS NOT NULL AND manual_search_urls.last_checked_at != '' THEN manual_search_urls.last_checked_at
                        ELSE excluded.last_checked_at
                    END
                """,
                {column: row.get(column, "") for column in MANUAL_SEARCH_COLUMNS},
            )
        conn.commit()
    finally:
        conn.close()


def get_manual_search_urls(db_path: Path = DEFAULT_DB, *, limit: int = 1000) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM manual_search_urls
            ORDER BY COALESCE(NULLIF(last_checked_at, ''), '0000') ASC, country, source_name, query
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def mark_manual_search_checked(row_id: int, db_path: Path = DEFAULT_DB) -> None:
    conn = connect(db_path)
    try:
        conn.execute("UPDATE manual_search_urls SET last_checked_at = ? WHERE id = ?", (now_utc_iso(), row_id))
        conn.commit()
    finally:
        conn.close()


def record_job_merge_events(db_path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    conn = connect(db_path)
    try:
        columns = MERGE_EVENT_COLUMNS + ["created_at"]
        rows = []
        now = now_utc_iso()
        for event in events:
            row = {column: event.get(column, "") for column in MERGE_EVENT_COLUMNS}
            row["created_at"] = event.get("created_at") or now
            rows.append(row)
        _insert_rows(conn, "job_merge_events", columns, rows)
        conn.commit()
    finally:
        conn.close()


def get_job_merge_events(db_path: Path = DEFAULT_DB, *, run_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        if run_id:
            rows = conn.execute("SELECT * FROM job_merge_events WHERE run_id = ? ORDER BY id DESC LIMIT ?", (run_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM job_merge_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
