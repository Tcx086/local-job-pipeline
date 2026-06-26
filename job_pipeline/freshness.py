from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) >= 12:
        try:
            return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
        except Exception:
            return None
    if text.isdigit() and len(text) == 8:
        try:
            return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y"]:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def iso_or_blank(value: Any) -> str:
    parsed = parse_datetime(value)
    return parsed.isoformat(timespec="seconds") if parsed else ""


def calculate_age_days(posted_at: Any, first_seen_at: Any, reference: datetime | None = None) -> int | None:
    reference = reference or now_utc()
    basis = parse_datetime(posted_at) or parse_datetime(first_seen_at)
    if not basis:
        return None
    return max(0, (reference - basis).days)


def freshness_label(posted_at: Any, first_seen_at: Any, reference: datetime | None = None) -> str:
    age = calculate_age_days(posted_at, first_seen_at, reference)
    if age is None:
        return "unknown"
    if age == 0:
        return "new_today"
    if age <= 7:
        return "new_this_week"
    if age <= 30:
        return "recent"
    return "old"


def enrich_freshness(job: dict[str, Any], reference: datetime | None = None) -> dict[str, Any]:
    row = dict(job)
    row["age_days"] = calculate_age_days(row.get("posted_at"), row.get("first_seen_at"), reference)
    row["freshness_label"] = freshness_label(row.get("posted_at"), row.get("first_seen_at"), reference)
    return row