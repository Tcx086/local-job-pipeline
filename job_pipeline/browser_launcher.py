from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .utils import DATA_DIR, PROJECT_ROOT, RESUMES_DIR, TEMPLATES_DIR

SAFE_URL_SCHEMES = {"http", "https"}
GENERATED_DIR = PROJECT_ROOT / "generated"
ALLOWED_LOCAL_DIRS = [RESUMES_DIR, DATA_DIR / "apply_assist", TEMPLATES_DIR, GENERATED_DIR]


def safe_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in SAFE_URL_SCHEMES or not parsed.netloc:
        return ""
    return url


def open_url(url: Any) -> bool:
    target = safe_url(url)
    if not target:
        return False
    return bool(webbrowser.open(target, new=2))


def open_apply_url(job: dict[str, Any]) -> bool:
    return open_url(job.get("application_apply_url") or job.get("apply_url") or job.get("job_url"))


def open_company_careers_page(url: Any) -> bool:
    return open_url(url)


def _resolve_local_path(path: Any) -> Path | None:
    if not path:
        return None
    candidate = Path(str(path)).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    allowed_roots = [root.resolve() for root in ALLOWED_LOCAL_DIRS]
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    return None


def _open_local_path(path: Path) -> bool:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return True
    return bool(webbrowser.open(path.as_uri(), new=2))


def open_resume_file(path: Any) -> bool:
    resume_path = _resolve_local_path(path)
    if not resume_path or not resume_path.exists() or not resume_path.is_file():
        return False
    return _open_local_path(resume_path)


def open_application_folder(path: Any) -> bool:
    folder = _resolve_local_path(path)
    if not folder or not folder.exists() or not folder.is_dir():
        return False
    return _open_local_path(folder)


def read_local_text(path: Any) -> str:
    target = _resolve_local_path(path)
    if not target or not target.exists() or not target.is_file():
        return ""
    return target.read_text(encoding="utf-8", errors="replace")
