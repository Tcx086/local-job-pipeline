from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from .utils import CONFIG_DIR, DATA_DIR, RESUMES_DIR, TEMPLATES_DIR, load_yaml, now_utc_iso, write_json

APPLY_ASSIST_DIR = DATA_DIR / "apply_assist"
APPLY_PROFILE_PATH = CONFIG_DIR / "apply_profile.yaml"
COMMON_ANSWERS_PATH = CONFIG_DIR / "common_answers.yaml"
MASTER_RESUME_PATH = TEMPLATES_DIR / "master_resume.yaml"


FORBIDDEN_EXPORT_KEYS = {
    "sin",
    "ssn",
    "passport",
    "passport_number",
    "driver_license",
    "bank",
    "banking",
    "bank_account",
    "social_insurance_number",
    "date_of_birth",
    "birth_date",
    "dob",
    "medical",
    "disability",
    "race",
    "ethnicity",
    "gender",
    "veteran",
    "eeo",
}

FORBIDDEN_EXPORT_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"passport",
        r"bank(_|\s|-)?account",
        r"social(_|\s|-)?insurance(_|\s|-)?number",
        r"\bsin\b",
        r"\bssn\b",
        r"date(_|\s|-)?of(_|\s|-)?birth",
        r"birth(_|\s|-)?date",
        r"\bdob\b",
        r"driver(_|\s|-)?licen[sc]e",
        r"government(_|\s|-)?id",
    ]
]


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = load_yaml(path)
    return data if isinstance(data, dict) else {}


def _forbidden_key(key: Any) -> bool:
    marker = str(key).strip().lower().replace(" ", "_").replace("-", "_")
    return marker in FORBIDDEN_EXPORT_KEYS or any(pattern.search(marker) for pattern in FORBIDDEN_EXPORT_PATTERNS)


def _remove_forbidden(data: Any) -> Any:
    if isinstance(data, dict):
        clean: dict[str, Any] = {}
        for key, value in data.items():
            if _forbidden_key(key):
                continue
            clean[key] = _remove_forbidden(value)
        return clean
    if isinstance(data, list):
        return [_remove_forbidden(item) for item in data]
    return data


def _skills(master: dict[str, Any]) -> list[str]:
    skills: list[str] = []
    for values in (master.get("skills") or {}).values():
        if isinstance(values, list):
            skills.extend(str(value) for value in values if str(value).strip())
    seen: set[str] = set()
    result: list[str] = []
    for skill in skills:
        marker = skill.lower()
        if marker not in seen:
            seen.add(marker)
            result.append(skill)
    return result


def _resume_paths() -> dict[str, Any]:
    generated = sorted(str(path) for path in RESUMES_DIR.rglob("*.pdf")) if RESUMES_DIR.exists() else []
    return {
        "master_docx": str(TEMPLATES_DIR / "master_resume_source.docx"),
        "master_pdf": str(TEMPLATES_DIR / "master_resume_source.pdf"),
        "generated_pdf": generated,
    }


def _render_markdown(export: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Apply Assist Profile Export")
    lines.append("")
    lines.append(f"Generated at: {export.get('generated_at', '')}")
    lines.append("")
    lines.append("## Privacy Boundary")
    lines.append(export.get("privacy_boundary", ""))
    lines.append("")
    profile = export.get("profile") or {}
    lines.append("## Basic Personal Info")
    for key, value in (profile.get("personal") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Education")
    for key, value in (profile.get("education") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Links")
    for key, value in (profile.get("links") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Work Authorization")
    for country, details in (profile.get("work_authorization") or {}).items():
        lines.append(f"### {country}")
        if isinstance(details, dict):
            for key, value in details.items():
                lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Standard Answers")
    for key, value in (export.get("standard_answers") or {}).items():
        lines.append(f"### {key}")
        lines.append(str(value))
    lines.append("")
    lines.append("## Skills")
    for skill in export.get("skills") or []:
        lines.append(f"- {skill}")
    lines.append("")
    lines.append("## Resume File Paths")
    paths = export.get("resume_file_paths") or {}
    for key, value in paths.items():
        if isinstance(value, list):
            lines.append(f"- {key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines).strip() + "\n"


def export_profile(
    *,
    output_dir: Path = APPLY_ASSIST_DIR,
    apply_profile_path: Path = APPLY_PROFILE_PATH,
    common_answers_path: Path = COMMON_ANSWERS_PATH,
    master_resume_path: Path = MASTER_RESUME_PATH,
) -> dict[str, Any]:
    profile = _remove_forbidden(_load(apply_profile_path))
    common_answers = _load(common_answers_path)
    master = _load(master_resume_path)
    questions = common_answers.get("questions") or {}
    standard_answers = {
        key: str((value or {}).get("template") or "")
        for key, value in questions.items()
        if isinstance(value, dict)
    }
    export = {
        "generated_at": now_utc_iso(),
        "privacy_boundary": "Highly sensitive identity, health, demographic, government ID, and financial-account fields are intentionally excluded. Review all third-party autofill data before submitting.",
        "profile": profile,
        "standard_answers": standard_answers,
        "skills": _skills(master),
        "resume_file_paths": _resume_paths(),
        "source_note": "Generated from local config/apply_profile.yaml, config/common_answers.yaml, and templates/master_resume.yaml.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "profile_export.json"
    md_path = output_dir / "profile_export.md"
    write_json(json_path, export)
    md_path.write_text(_render_markdown(export), encoding="utf-8")
    export["paths"] = {"json": str(json_path), "markdown": str(md_path)}
    return export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a safe Apply Assist profile reference for manual autofill setup.")
    parser.add_argument("--out", type=Path, default=APPLY_ASSIST_DIR)
    args = parser.parse_args(argv)
    result = export_profile(output_dir=args.out)
    print(result["paths"]["markdown"])
    print(result["paths"]["json"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
