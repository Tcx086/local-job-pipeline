from __future__ import annotations

from typing import Any

from .utils import now_utc_iso


def collect_company_page_links(company_pages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return manual company-career entries for dashboard tracking.

    Complex ATS platforms such as Workday, Taleo, Oracle, and SuccessFactors are
    intentionally not scraped generically. The dashboard shows these URLs as
    manual check entries instead.
    """
    collected_at = now_utc_iso()
    rows: list[dict[str, Any]] = []
    for item in company_pages or []:
        rows.append(
            {
                "company": item.get("company_name") or "",
                "source": "company_page_manual",
                "ats_type": item.get("adapter_type") or "manual_url",
                "careers_url": item.get("careers_url") or "",
                "country_focus": item.get("country_focus") or [],
                "company_tags": item.get("tags") or [],
                "collected_at": collected_at,
            }
        )
    return rows