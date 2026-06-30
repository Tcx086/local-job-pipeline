from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils import now_utc_iso, slugify, today_yyyymmdd
from .paths import PathRegistry


WINDOWS_ILLEGAL_CHARS = r'<>:"/\|?*'
CANDIDATE_FILE_PREFIX = "Candidate_Name"


def _date_folder(value: str | None) -> str:
    text = re.sub(r"[^0-9]", "", str(value or ""))
    return text[:8] if len(text) >= 8 else today_yyyymmdd()


def _safe_filename_part(value: Any, fallback: str, max_len: int = 70) -> str:
    text = str(value or fallback).strip() or fallback
    for char in WINDOWS_ILLEGAL_CHARS:
        text = text.replace(char, " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[^A-Za-z0-9 ._'-]+", "", text).strip(" ._")
    text = text.replace(" ", "_")
    return (text[:max_len].strip(" ._") or fallback).replace("__", "_")


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass(frozen=True)
class ApplicationWorkspace:
    paths: PathRegistry
    date: str
    company: str
    title: str
    canonical_job_id: str
    job_slug: str
    company_slug: str
    role_slug: str
    root: Path
    source_dir: Path
    review_dir: Path
    application_dir: Path
    manifest_path: Path
    job: dict[str, Any]

    @classmethod
    def from_job(
        cls,
        job: dict[str, Any],
        paths: PathRegistry | None = None,
        date: str | None = None,
    ) -> "ApplicationWorkspace":
        registry = paths or PathRegistry.from_project_root()
        workspace_date = _date_folder(date)
        company = str(job.get("company") or job.get("canonical_company") or "company").strip() or "company"
        title = str(job.get("title") or job.get("normalized_title") or job.get("role_category") or "role").strip() or "role"
        canonical_job_id = str(job.get("canonical_job_id") or job.get("job_id") or job.get("source_job_id") or "job").strip() or "job"
        company_slug = slugify(company, 60)
        role_slug = slugify(title, 70)
        job_slug = slugify(canonical_job_id, 80)
        root = registry.resolve_generated(workspace_date, company_slug, f"{role_slug}__{job_slug}")
        return cls(
            paths=registry,
            date=workspace_date,
            company=company,
            title=title,
            canonical_job_id=canonical_job_id,
            job_slug=job_slug,
            company_slug=company_slug,
            role_slug=role_slug,
            root=root,
            source_dir=root / "source",
            review_dir=root / "review",
            application_dir=root / "application",
            manifest_path=root / "_manifest.json",
            job=dict(job),
        )

    def ensure_dirs(self) -> None:
        for path in [self.root, self.source_dir, self.review_dir, self.application_dir]:
            path.mkdir(parents=True, exist_ok=True)

    def job_description_path(self) -> Path:
        return self.source_dir / "job_description.md"

    def job_snapshot_path(self) -> Path:
        return self.source_dir / "job_snapshot.json"

    def scoring_snapshot_path(self) -> Path:
        return self.source_dir / "scoring_snapshot.json"

    def resume_source_json_path(self) -> Path:
        return self.source_dir / "resume_source.json"

    def cover_letter_source_json_path(self) -> Path:
        return self.source_dir / "cover_letter_source.json"

    def answer_pack_json_path(self) -> Path:
        return self.source_dir / "answer_pack.json"

    def resume_review_md_path(self) -> Path:
        return self.review_dir / "resume_review.md"

    def cover_letter_review_md_path(self) -> Path:
        return self.review_dir / "cover_letter_review.md"

    def formal_resume_basename(self) -> str:
        return f"{CANDIDATE_FILE_PREFIX}__{_safe_filename_part(self.company, 'Company')}__{_safe_filename_part(self.title, 'Role')}__Resume"

    def formal_cover_letter_basename(self) -> str:
        return f"{CANDIDATE_FILE_PREFIX}__{_safe_filename_part(self.company, 'Company')}__{_safe_filename_part(self.title, 'Role')}__Cover_Letter"

    def resume_docx_path(self) -> Path:
        return self.root / f"{self.formal_resume_basename()}.docx"

    def resume_pdf_path(self) -> Path:
        return self.root / f"{self.formal_resume_basename()}.pdf"

    def cover_letter_docx_path(self) -> Path:
        return self.root / f"{self.formal_cover_letter_basename()}.docx"

    def cover_letter_pdf_path(self) -> Path:
        return self.root / f"{self.formal_cover_letter_basename()}.pdf"

    def cover_letter_body_txt_path(self) -> Path:
        return self.root / "cover_letter_body.txt"

    def answer_pack_md_path(self) -> Path:
        return self.root / "answer_pack.md"

    def notes_path(self) -> Path:
        return self.root / "notes.md"

    def submission_record_path(self) -> Path:
        return self.application_dir / "submission_record.json"

    def confirmation_path(self) -> Path:
        return self.application_dir / "confirmation.txt"

    def relative_to_root(self, path: Path) -> str:
        return _relative_path(self.root, path)

    def build_manifest(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        now = now_utc_iso()
        existing = self.read_manifest() or {}
        manifest = {
            "schema_version": 1,
            "canonical_job_id": self.canonical_job_id,
            "job_slug": self.job_slug,
            "company": self.company,
            "title": self.title,
            "country": self.job.get("country", ""),
            "role_category": self.job.get("role_category", ""),
            "role_family": self.job.get("role_family", ""),
            "resume_profile": self.job.get("resume_profile", ""),
            "application_effort": self.job.get("application_effort", ""),
            "workspace_date": self.date,
            "workspace_path": _relative_path(self.paths.project_root, self.root),
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
            "manual_review_required": True,
            "submitted": bool(existing.get("submitted", False)),
            "artifacts": {
                "job_description": self.relative_to_root(self.job_description_path()),
                "job_snapshot": self.relative_to_root(self.job_snapshot_path()),
                "scoring_snapshot": self.relative_to_root(self.scoring_snapshot_path()),
                "resume_pdf": self.relative_to_root(self.resume_pdf_path()),
                "resume_docx": self.relative_to_root(self.resume_docx_path()),
                "cover_letter_pdf": self.relative_to_root(self.cover_letter_pdf_path()),
                "cover_letter_docx": self.relative_to_root(self.cover_letter_docx_path()),
                "cover_letter_body": self.relative_to_root(self.cover_letter_body_txt_path()),
                "answer_pack": self.relative_to_root(self.answer_pack_md_path()),
                "notes": self.relative_to_root(self.notes_path()),
            },
        }
        if extra:
            extra = dict(extra)
            artifacts = extra.pop("artifacts", None)
            manifest.update(extra)
            if isinstance(artifacts, dict):
                manifest["artifacts"].update(artifacts)
        return manifest

    def write_manifest(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_dirs()
        manifest = self.build_manifest(extra)
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def read_manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None
