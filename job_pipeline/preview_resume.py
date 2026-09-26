from __future__ import annotations

import argparse
import json
from pathlib import Path

from .database import DEFAULT_DB, get_job_detail
from .keyword_extract import extract_keywords
from .resources import load_candidate_master
from .resume_tailor import generate_resume
from .utils import flatten_text


def generate_preview_for_job(
    canonical_job_id: str,
    *,
    db_path: Path = DEFAULT_DB,
    make_pdf: bool = True,
    make_docx: bool = True,
) -> dict[str, str]:
    job = get_job_detail(canonical_job_id, db_path)
    if not job:
        raise ValueError(f"Unknown canonical_job_id: {canonical_job_id}")
    master = load_candidate_master()
    keyword_info = extract_keywords(
        str(job.get("description") or ""),
        flatten_text(master),
    )
    result = generate_resume(
        job=job,
        keyword_info=keyword_info,
        make_pdf=make_pdf,
        make_docx=make_docx,
    )
    return {
        "canonical_job_id": canonical_job_id,
        "company": str(job.get("company") or ""),
        "title": str(job.get("title") or ""),
        "job_url": str(job.get("job_url") or ""),
        "apply_url": str(job.get("apply_url") or ""),
        "workspace": str(result.get("workspace") or ""),
        "markdown": str(result.get("markdown") or ""),
        "docx": str(result.get("docx") or ""),
        "pdf": str(result.get("pdf") or ""),
        "manifest": str(result.get("manifest") or ""),
        "docx_renderer": str(result.get("docx_renderer") or ""),
        "pdf_renderer": str(result.get("pdf_renderer") or ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a targeted resume preview for one job already in SQLite.")
    parser.add_argument("--job-id", required=True, help="Canonical job ID from the local pipeline database.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--no-docx", action="store_true")
    args = parser.parse_args(argv)

    result = generate_preview_for_job(
        args.job_id,
        db_path=args.db,
        make_pdf=not args.no_pdf,
        make_docx=not args.no_docx,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
