from __future__ import annotations

import argparse
import logging
import time
from typing import Any

import requests

from .normalize import detect_country
from .utils import now_utc_iso, normalize_space, strip_html

LOGGER = logging.getLogger(__name__)
GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def _request_json(url: str, *, timeout: int, retries: int, user_agent: str) -> dict[str, Any]:
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001 - collector must be fault tolerant
            last_error = exc
            LOGGER.warning("Greenhouse request failed attempt=%s url=%s error=%s", attempt + 1, url, exc)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Greenhouse request failed for {url}: {last_error}")


def _names(values: list[dict[str, Any]] | None) -> list[str]:
    return [normalize_space(item.get("name")) for item in values or [] if normalize_space(item.get("name"))]


def collect_greenhouse_board(
    *,
    company_name: str,
    board_token: str,
    country_focus: list[str] | None = None,
    tags: list[str] | None = None,
    timeout: int = 20,
    retries: int = 2,
    user_agent: str = "job-pipeline-local/2.0",
) -> list[dict[str, Any]]:
    url = GREENHOUSE_URL.format(token=board_token) + "?content=true"
    collected_at = now_utc_iso()
    data = _request_json(url, timeout=timeout, retries=retries, user_agent=user_agent)
    rows: list[dict[str, Any]] = []
    for job in data.get("jobs", []):
        location = normalize_space((job.get("location") or {}).get("name"))
        description = strip_html(job.get("content"))
        offices = _names(job.get("offices"))
        departments = _names(job.get("departments"))
        country = detect_country(location, "", description) or (country_focus or [""])[0]
        job_id = str(job.get("id") or job.get("internal_job_id") or "")
        absolute_url = job.get("absolute_url") or ""
        rows.append(
            {
                "job_id": f"greenhouse:{board_token}:{job_id}" if job_id else "",
                "source_job_id": job_id,
                "source": "greenhouse",
                "title": normalize_space(job.get("title")),
                "company": company_name,
                "location": location,
                "country": country,
                "date_posted": job.get("created_at") or "",
                "posted_at": job.get("created_at") or "",
                "updated_at": job.get("updated_at") or "",
                "job_type": "",
                "salary_min": "",
                "salary_max": "",
                "currency": "",
                "job_url": absolute_url,
                "apply_url": absolute_url,
                "absolute_url": absolute_url,
                "description": description,
                "departments": departments,
                "offices": offices,
                "ats_company_token": board_token,
                "ats_type": "greenhouse",
                "company_tags": tags or [],
                "collected_at": collected_at,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public Greenhouse jobs for one board token.")
    parser.add_argument("board_token")
    parser.add_argument("--company", default="")
    args = parser.parse_args()
    rows = collect_greenhouse_board(company_name=args.company or args.board_token, board_token=args.board_token)
    print(f"Collected {len(rows)} Greenhouse jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())