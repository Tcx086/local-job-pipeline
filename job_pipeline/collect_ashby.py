from __future__ import annotations

import argparse
import logging
import time
from typing import Any

import requests

from .normalize import detect_country
from .utils import now_utc_iso, normalize_space, strip_html

LOGGER = logging.getLogger(__name__)
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def _request_json(url: str, *, timeout: int, retries: int, user_agent: str) -> dict[str, Any]:
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            LOGGER.warning("Ashby request failed attempt=%s url=%s error=%s", attempt + 1, url, exc)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Ashby request failed for {url}: {last_error}")


def _job_url(board: str, job: dict[str, Any]) -> str:
    return job.get("jobUrl") or job.get("job_url") or job.get("applicationUrl") or f"https://jobs.ashbyhq.com/{board}/{job.get('id', '')}"


def _compensation(job: dict[str, Any]) -> tuple[str, str, str]:
    comp = job.get("compensation") or job.get("salary") or {}
    if not isinstance(comp, dict):
        return "", "", ""
    return str(comp.get("min") or comp.get("minimum") or ""), str(comp.get("max") or comp.get("maximum") or ""), str(comp.get("currency") or "")


def collect_ashby_board(
    *,
    company_name: str,
    ashby_board: str,
    country_focus: list[str] | None = None,
    tags: list[str] | None = None,
    timeout: int = 20,
    retries: int = 2,
    user_agent: str = "job-pipeline-local/2.0",
) -> list[dict[str, Any]]:
    url = ASHBY_URL.format(board=ashby_board)
    collected_at = now_utc_iso()
    data = _request_json(url, timeout=timeout, retries=retries, user_agent=user_agent)
    jobs = data.get("jobs") if isinstance(data, dict) else []
    rows: list[dict[str, Any]] = []
    for job in jobs or []:
        location = normalize_space(job.get("locationName") or job.get("location") or "")
        description = strip_html(job.get("descriptionHtml") or job.get("description") or "")
        country = detect_country(location, "", description) or (country_focus or [""])[0]
        source_job_id = str(job.get("id") or job.get("jobId") or "")
        salary_min, salary_max, currency = _compensation(job)
        job_url = _job_url(ashby_board, job)
        rows.append(
            {
                "job_id": f"ashby:{ashby_board}:{source_job_id}" if source_job_id else "",
                "source_job_id": source_job_id,
                "source": "ashby",
                "title": normalize_space(job.get("title")),
                "company": company_name,
                "location": location,
                "country": country,
                "date_posted": job.get("publishedAt") or job.get("createdAt") or "",
                "posted_at": job.get("publishedAt") or job.get("createdAt") or "",
                "updated_at": job.get("updatedAt") or "",
                "job_type": job.get("employmentType") or "",
                "salary_min": salary_min,
                "salary_max": salary_max,
                "currency": currency,
                "job_url": job_url,
                "apply_url": job.get("applicationUrl") or job_url,
                "department": job.get("departmentName") or "",
                "employment_type": job.get("employmentType") or "",
                "description": description,
                "ats_company_token": ashby_board,
                "ats_type": "ashby",
                "company_tags": tags or [],
                "collected_at": collected_at,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public Ashby jobs for one board.")
    parser.add_argument("ashby_board")
    parser.add_argument("--company", default="")
    args = parser.parse_args()
    rows = collect_ashby_board(company_name=args.company or args.ashby_board, ashby_board=args.ashby_board)
    print(f"Collected {len(rows)} Ashby jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())