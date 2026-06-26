from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from .normalize import detect_country
from .utils import now_utc_iso, normalize_space, strip_html

LOGGER = logging.getLogger(__name__)
LEVER_URL = "https://api.lever.co/v0/postings/{slug}"


def _request_json(url: str, *, timeout: int, retries: int, user_agent: str) -> list[dict[str, Any]]:
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout, params={"mode": "json"})
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            LOGGER.warning("Lever request failed attempt=%s url=%s error=%s", attempt + 1, url, exc)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Lever request failed for {url}: {last_error}")


def _ms_to_iso(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return str(value)


def collect_lever_board(
    *,
    company_name: str,
    lever_slug: str,
    country_focus: list[str] | None = None,
    tags: list[str] | None = None,
    timeout: int = 20,
    retries: int = 2,
    user_agent: str = "job-pipeline-local/2.0",
) -> list[dict[str, Any]]:
    url = LEVER_URL.format(slug=lever_slug)
    collected_at = now_utc_iso()
    data = _request_json(url, timeout=timeout, retries=retries, user_agent=user_agent)
    rows: list[dict[str, Any]] = []
    for job in data:
        categories = job.get("categories") or {}
        location = normalize_space(categories.get("location") or job.get("location"))
        description = strip_html(job.get("descriptionPlain") or job.get("description") or "")
        country = detect_country(location, "", description) or (country_focus or [""])[0]
        source_job_id = str(job.get("id") or "")
        posted_at = _ms_to_iso(job.get("createdAt"))
        rows.append(
            {
                "job_id": f"lever:{lever_slug}:{source_job_id}" if source_job_id else "",
                "source_job_id": source_job_id,
                "source": "lever",
                "title": normalize_space(job.get("text")),
                "company": company_name,
                "location": location,
                "country": country,
                "date_posted": posted_at,
                "posted_at": posted_at,
                "updated_at": _ms_to_iso(job.get("updatedAt")),
                "job_type": categories.get("commitment") or "",
                "salary_min": "",
                "salary_max": "",
                "currency": "",
                "job_url": job.get("hostedUrl") or "",
                "apply_url": job.get("applyUrl") or job.get("hostedUrl") or "",
                "team": categories.get("team") or "",
                "department": categories.get("department") or categories.get("team") or "",
                "commitment": categories.get("commitment") or "",
                "workplace_type": categories.get("workplaceType") or categories.get("workplace_type") or "",
                "description": description,
                "ats_company_token": lever_slug,
                "ats_type": "lever",
                "company_tags": tags or [],
                "collected_at": collected_at,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public Lever jobs for one slug.")
    parser.add_argument("lever_slug")
    parser.add_argument("--company", default="")
    args = parser.parse_args()
    rows = collect_lever_board(company_name=args.company or args.lever_slug, lever_slug=args.lever_slug)
    print(f"Collected {len(rows)} Lever jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())