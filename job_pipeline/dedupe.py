from __future__ import annotations

import hashlib
import json
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .company_registry import canonical_company_name
from .utils import PROCESSED_DIR, normalize_space, now_utc_iso, stable_id

try:
    from rapidfuzz import fuzz  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal installs
    fuzz = None

DEFAULT_DB = PROCESSED_DIR / "jobs.sqlite"
SOURCE_PRIORITY = {
    "company_page": 100,
    "company_page_manual": 95,
    "greenhouse": 90,
    "lever": 90,
    "ashby": 90,
    "linkedin": 70,
    "indeed": 65,
    "google": 60,
    "glassdoor": 55,
    "zip_recruiter": 50,
    "sample": 10,
}


def similarity(a: Any, b: Any) -> float:
    left = normalize_space(a).lower()
    right = normalize_space(b).lower()
    if not left and not right:
        return 100.0
    if not left or not right:
        return 0.0
    if fuzz:
        return float(fuzz.token_set_ratio(left, right))
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if left_tokens and right_tokens:
        left_sorted = " ".join(sorted(left_tokens))
        right_sorted = " ".join(sorted(right_tokens))
        common = " ".join(sorted(left_tokens & right_tokens))
        if common:
            return max(
                SequenceMatcher(None, common, left_sorted).ratio(),
                SequenceMatcher(None, common, right_sorted).ratio(),
                SequenceMatcher(None, left_sorted, right_sorted).ratio(),
                SequenceMatcher(None, left, right).ratio(),
            ) * 100
    return SequenceMatcher(None, left, right).ratio() * 100


def canonical_location(value: Any) -> str:
    text = normalize_space(value).lower()
    if not text:
        return ""
    if "remote" in text:
        if "canada" in text:
            return "remote canada"
        if "singapore" in text:
            return "remote singapore"
        if "hong kong" in text or " hk" in f" {text} ":
            return "remote hong kong"
        return "remote"
    text = text.replace("greater ", "")
    text = text.replace("area", "")
    text = text.replace(" city", "")
    return normalize_space(text)


def source_job_id(job: dict[str, Any]) -> str:
    return normalize_space(job.get("source_job_id") or job.get("job_id"))


def description_hash(description: Any) -> str:
    text = normalize_space(description).lower()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32] if text else ""


def description_prefix(job: dict[str, Any], chars: int = 500) -> str:
    return normalize_space(job.get("description") or "").lower()[:chars]


def _clean_url(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    text = normalize_space(value)
    return "" if text.lower() in {"nan", "none", "null"} else text


def _url_values(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [text]
        return [_clean_url(item) for item in parsed if _clean_url(item)] if isinstance(parsed, list) else [_clean_url(parsed)]
    if isinstance(value, (list, tuple, set)):
        return [_clean_url(item) for item in value if _clean_url(item)]
    cleaned = _clean_url(value)
    return [cleaned] if cleaned else []

def canonicalize_job(job: dict[str, Any]) -> dict[str, Any]:
    row = dict(job)
    row["canonical_company"] = row.get("canonical_company") or canonical_company_name(row.get("company"))
    row["normalized_title"] = row.get("normalized_title") or normalize_space(row.get("title")).lower()
    row["normalized_location"] = row.get("normalized_location") or canonical_location(row.get("location"))
    row["remote_type"] = row.get("remote_type") or ("remote" if "remote" in row.get("normalized_location", "") else "onsite_or_hybrid")
    row["source_job_id"] = source_job_id(row)
    row["description_hash"] = row.get("description_hash") or description_hash(row.get("description"))
    row["job_fingerprint"] = job_fingerprint(row)
    return row


def job_fingerprint(job: dict[str, Any]) -> str:
    return stable_id(
        job.get("canonical_company") or canonical_company_name(job.get("company")),
        job.get("normalized_title") or normalize_space(job.get("title")).lower(),
        job.get("normalized_location") or canonical_location(job.get("location")),
        job.get("role_category") or "",
    )


def exact_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("source") and b.get("source") and a.get("source") == b.get("source"):
        if source_job_id(a) and source_job_id(a) == source_job_id(b):
            return True
    for field in ["job_url", "apply_url"]:
        left = normalize_space(a.get(field))
        right = normalize_space(b.get(field))
        if left and right and left == right:
            return True
    return False


def same_company_role(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ca = canonicalize_job(a)
    cb = canonicalize_job(b)
    return (
        ca.get("canonical_company") == cb.get("canonical_company")
        and ca.get("normalized_title") == cb.get("normalized_title")
        and ca.get("normalized_location") == cb.get("normalized_location")
        and (ca.get("role_category") or "") == (cb.get("role_category") or "")
    )


def fuzzy_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ca = canonicalize_job(a)
    cb = canonicalize_job(b)
    if similarity(ca.get("canonical_company"), cb.get("canonical_company")) < 95:
        return False
    if similarity(ca.get("normalized_title"), cb.get("normalized_title")) < 90:
        return False
    if similarity(ca.get("normalized_location"), cb.get("normalized_location")) < 85:
        if ca.get("remote_type") != cb.get("remote_type"):
            return False
    if ca.get("description_hash") and ca.get("description_hash") == cb.get("description_hash"):
        return True
    left_prefix = description_prefix(ca)
    right_prefix = description_prefix(cb)
    if left_prefix and right_prefix and similarity(left_prefix, right_prefix) >= 88:
        return True
    return not left_prefix or not right_prefix


def jobs_are_same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return exact_duplicate(a, b) or same_company_role(a, b) or fuzzy_duplicate(a, b)


def source_rank(source: Any) -> int:
    return SOURCE_PRIORITY.get(str(source or "").lower(), 20)


def merge_jobs(primary: dict[str, Any], duplicate: dict[str, Any]) -> dict[str, Any]:
    left = canonicalize_job(primary)
    right = canonicalize_job(duplicate)
    if source_rank(right.get("source")) > source_rank(left.get("source")):
        base, extra = right, left
    else:
        base, extra = left, right
    merged = dict(base)
    for key, value in extra.items():
        if key not in merged or merged.get(key) in (None, "", []):
            merged[key] = value
    sources = set(merged.get("all_sources") or [])
    sources.add(str(left.get("source") or ""))
    sources.add(str(right.get("source") or ""))
    merged["all_sources"] = sorted(source for source in sources if source)
    urls = set(_url_values(merged.get("all_source_urls")))
    for job in [left, right]:
        for field in ["job_url", "apply_url"]:
            cleaned = _clean_url(job.get(field))
            if cleaned:
                urls.add(cleaned)
    merged["all_source_urls"] = sorted(urls)
    merged["canonical_job_id"] = merged.get("canonical_job_id") or stable_id(
        merged.get("canonical_company"), merged.get("normalized_title"), merged.get("normalized_location")
    )
    return merged



def merge_event(incoming: dict[str, Any], existing: dict[str, Any], merged: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
    ca = canonicalize_job(incoming)
    cb = canonicalize_job(existing)
    if exact_duplicate(cb, ca):
        reason = "exact_url_or_source_id"
    elif same_company_role(cb, ca):
        reason = "same_company_role_location"
    else:
        reason = "fuzzy_company_title_location_description"
    return {
        "run_id": run_id,
        "incoming_source": ca.get("source") or "",
        "incoming_title": ca.get("title") or "",
        "incoming_company": ca.get("company") or ca.get("canonical_company") or "",
        "incoming_location": ca.get("location") or "",
        "incoming_url": ca.get("job_url") or ca.get("apply_url") or "",
        "merged_into_canonical_job_id": merged.get("canonical_job_id") or existing.get("canonical_job_id") or "",
        "existing_title": cb.get("title") or "",
        "existing_company": cb.get("company") or cb.get("canonical_company") or "",
        "existing_location": cb.get("location") or "",
        "reason": reason,
        "title_similarity": round(similarity(ca.get("normalized_title"), cb.get("normalized_title")), 1),
        "company_similarity": round(similarity(ca.get("canonical_company"), cb.get("canonical_company")), 1),
        "location_similarity": round(similarity(ca.get("normalized_location"), cb.get("normalized_location")), 1),
        "description_similarity": round(similarity(description_prefix(ca), description_prefix(cb)), 1),
    }

def dedupe_current_jobs(jobs: list[dict[str, Any]], *, run_id: str = "", return_events: bool = False):
    unique: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for job in jobs:
        row = canonicalize_job(job)
        matched_index: int | None = None
        for index, existing in enumerate(unique):
            if jobs_are_same(existing, row):
                matched_index = index
                break
        if matched_index is None:
            row["canonical_job_id"] = row.get("canonical_job_id") or stable_id(
                row.get("canonical_company"), row.get("normalized_title"), row.get("normalized_location")
            )
            row["all_sources"] = [row.get("source")] if row.get("source") else []
            row["all_source_urls"] = [url for url in [row.get("job_url"), row.get("apply_url")] if url]
            unique.append(row)
        else:
            existing = unique[matched_index]
            merged = merge_jobs(existing, row)
            row["duplicate_of_job_id"] = merged.get("canonical_job_id")
            duplicates.append(row)
            events.append(merge_event(row, existing, merged, run_id=run_id))
            unique[matched_index] = merged
    if return_events:
        return unique, duplicates, events
    return unique, duplicates


# Legacy Phase 1 SQLite helpers kept for backward-compatible tests and commands.
def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE NOT NULL,
            fingerprint TEXT NOT NULL,
            job_url TEXT,
            title TEXT,
            company TEXT,
            location TEXT,
            country TEXT,
            source TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(job_url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company_location ON jobs(company, location)")
    conn.commit()


def make_fingerprint(job: dict[str, Any]) -> str:
    return job_fingerprint(canonicalize_job(job))


def find_duplicate(conn: sqlite3.Connection, job: dict[str, Any], fuzzy_threshold: float = 0.92) -> sqlite3.Row | None:
    job_url = normalize_space(job.get("job_url"))
    if job_url:
        row = conn.execute("SELECT * FROM jobs WHERE job_url = ? LIMIT 1", (job_url,)).fetchone()
        if row:
            return row
    fingerprint = make_fingerprint(job)
    row = conn.execute("SELECT * FROM jobs WHERE fingerprint = ? LIMIT 1", (fingerprint,)).fetchone()
    if row:
        return row
    row_job = canonicalize_job(job)
    candidates = conn.execute("SELECT * FROM jobs").fetchall()
    for candidate in candidates:
        existing = {"company": candidate["company"], "title": candidate["title"], "location": candidate["location"], "job_url": candidate["job_url"]}
        if fuzzy_duplicate(existing, row_job):
            return candidate
    return None


def insert_job(conn: sqlite3.Connection, job: dict[str, Any]) -> None:
    now = now_utc_iso()
    fingerprint = make_fingerprint(job)
    conn.execute(
        """
        INSERT OR IGNORE INTO jobs (
            job_id, fingerprint, job_url, title, company, location, country, source,
            first_seen, last_seen, status, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.get("job_id") or stable_id(job.get("source"), job.get("title"), job.get("company"), job.get("job_url")),
            fingerprint,
            job.get("job_url"),
            job.get("normalized_title") or job.get("title"),
            job.get("normalized_company") or job.get("company"),
            job.get("normalized_location") or job.get("location"),
            job.get("detected_country") or job.get("country"),
            job.get("source"),
            now,
            now,
            job.get("status") or "new",
            json.dumps(job, ensure_ascii=False, default=str),
        ),
    )
    conn.commit()


def touch_duplicate(conn: sqlite3.Connection, existing: sqlite3.Row, job: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE jobs SET last_seen = ?, payload_json = ? WHERE id = ?",
        (now_utc_iso(), json.dumps(job, ensure_ascii=False, default=str), existing["id"]),
    )
    conn.commit()


def dedupe_jobs(jobs: list[dict[str, Any]], db_path: Path = DEFAULT_DB, fuzzy_threshold: float = 0.92) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conn = connect(db_path)
    new_jobs: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    try:
        for job in jobs:
            if not job.get("job_id"):
                job["job_id"] = stable_id(job.get("source"), job.get("title"), job.get("company"), job.get("job_url"))
            existing = find_duplicate(conn, job, fuzzy_threshold=fuzzy_threshold)
            if existing:
                duplicate = dict(job)
                duplicate["duplicate_of_job_id"] = existing["job_id"]
                duplicates.append(duplicate)
                touch_duplicate(conn, existing, duplicate)
                continue
            insert_job(conn, job)
            new_jobs.append(job)
    finally:
        conn.close()
    return new_jobs, duplicates


def update_status(job_id: str, status: str, db_path: Path = DEFAULT_DB) -> None:
    allowed = {"new", "reviewed", "apply_today", "applied", "skipped", "interview", "rejected", "archived"}
    if status not in allowed:
        raise ValueError(f"status must be one of {sorted(allowed)}")
    conn = connect(db_path)
    try:
        conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
        conn.commit()
    finally:
        conn.close()
