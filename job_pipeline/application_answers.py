from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config_loader import load_path_with_fallback
from .database import DEFAULT_DB, get_job_detail
from .keyword_extract import extract_keywords
from .utils import CONFIG_DIR, DATA_DIR, TEMPLATES_DIR, flatten_text, load_yaml, now_utc_iso, slugify, write_json

APPLY_ASSIST_DIR = DATA_DIR / "apply_assist"
MASTER_RESUME_PATH = TEMPLATES_DIR / "master_resume.yaml"
APPLY_PROFILE_PATH = CONFIG_DIR / "apply_profile.local.yaml"
COMMON_ANSWERS_PATH = CONFIG_DIR / "common_answers.yaml"
SENSITIVE_POLICY_PATH = CONFIG_DIR / "sensitive_fields_policy.yaml"
MANUAL_ANSWER = "ANSWER MANUALLY"


def answer_pack_paths(canonical_job_id: str, output_dir: Path = APPLY_ASSIST_DIR) -> dict[str, Path]:
    stem = slugify(canonical_job_id, 80) or "job"
    return {
        "markdown": output_dir / f"{stem}_answer_pack.md",
        "json": output_dir / f"{stem}_answer_pack.json",
    }


def _load_config(path: Path) -> dict[str, Any]:
    data = load_path_with_fallback(path)
    return data if isinstance(data, dict) else {}


def _template(common_answers: dict[str, Any], key: str) -> str:
    item = (common_answers.get("questions") or {}).get(key) or {}
    return str(item.get("template") or "").strip()


def _country_key(country: Any) -> str:
    text = str(country or "").strip().lower().replace(" ", "_").replace("-", "_")
    if "canada" in text:
        return "canada"
    if "singapore" in text:
        return "singapore"
    if "hong" in text or text in {"hk", "hkg"}:
        return "hong_kong"
    return text


def _score_text(value: Any, keywords: list[str]) -> int:
    text = flatten_text(value).lower()
    return sum(1 for keyword in keywords if keyword and keyword.lower() in text)


def _rank_items(items: list[Any], keywords: list[str], limit: int) -> list[Any]:
    ranked = sorted(items, key=lambda item: _score_text(item, keywords), reverse=True)
    return ranked[:limit]


def _dedupe(items: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = " ".join(str(item or "").split())
        marker = cleaned.lower()
        if not cleaned or marker in seen:
            continue
        seen.add(marker)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _skills_from_master(master: dict[str, Any]) -> list[str]:
    skills: list[str] = []
    for values in (master.get("skills") or {}).values():
        if isinstance(values, list):
            skills.extend(str(value) for value in values if str(value).strip())
    return _dedupe(skills, 200)


def _build_work_authorization(country: Any, profile: dict[str, Any], common_answers: dict[str, Any]) -> str:
    key = _country_key(country)
    templates = [f"work_authorization_{key}", "work_authorization_default"]
    profile_auth = profile.get("work_authorization") or {}
    profile_payload = profile_auth.get(key) if isinstance(profile_auth, dict) else {}
    if not isinstance(profile_payload, dict):
        profile_payload = profile_auth.get("default") if isinstance(profile_auth, dict) else {}
    for template_key in templates:
        answer = _template(common_answers, template_key)
        if answer:
            return answer
    if isinstance(profile_payload, dict) and profile_payload.get("explanation"):
        return str(profile_payload.get("explanation"))
    return "TODO: Confirm work authorization requirements for this location before answering."


def _relevant_project_summary(master: dict[str, Any], keywords: list[str]) -> list[dict[str, Any]]:
    projects = _rank_items(_dict_items(master.get("projects")), keywords, 2)
    summaries: list[dict[str, Any]] = []
    for project in projects:
        bullets = _rank_items(project.get("bullets") or [], keywords, 2)
        summaries.append(
            {
                "name": project.get("name", ""),
                "type": project.get("type", ""),
                "dates": project.get("dates", ""),
                "bullets": bullets,
            }
        )
    return summaries


def _talking_points(master: dict[str, Any], keywords: list[str]) -> list[str]:
    points: list[str] = []
    for project in _rank_items(_dict_items(master.get("projects")), keywords, 3):
        for bullet in _rank_items(project.get("bullets") or [], keywords, 3):
            points.append(str(bullet))
    for role in _rank_items(_dict_items(master.get("experience")), keywords, 2):
        for bullet in _rank_items(role.get("bullets") or [], keywords, 2):
            points.append(str(bullet))
    for skill in _rank_items(_skills_from_master(master), keywords, 8):
        points.append(f"Skill to mention: {skill}")
    return _dedupe(points, 5)



def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]

def _render_project_summary(projects: list[dict[str, Any]]) -> str:
    if not projects:
        return "TODO: Pick the most relevant real project from the master resume before submitting."
    lines: list[str] = []
    for project in projects:
        header = " | ".join(str(x) for x in [project.get("name"), project.get("type"), project.get("dates")] if x)
        lines.append(header)
        for bullet in project.get("bullets") or []:
            lines.append(f"- {bullet}")
    return "\n".join(lines)


def _sensitive_answers(policy: dict[str, Any]) -> dict[str, str]:
    groups = policy.get("manual_question_groups") or {}
    if not isinstance(groups, dict) or not groups:
        return {"sensitive_fields": MANUAL_ANSWER}
    return {str(key): MANUAL_ANSWER for key in groups}


def _build_answers(
    *,
    job: dict[str, Any],
    master: dict[str, Any],
    profile: dict[str, Any],
    common_answers: dict[str, Any],
    keywords: list[str],
) -> dict[str, str]:
    company = str(job.get("company") or "the company").strip()
    title = str(job.get("title") or "this role").strip()
    keyword_phrase = ", ".join(keywords[:5]) if keywords else "the responsibilities listed in the job description"
    why_company_base = _template(common_answers, "why_company")
    why_role_base = _template(common_answers, "why_role")
    tell_me = _template(common_answers, "tell_me_about_yourself")
    return {
        "why_this_company": (
            f"{why_company_base}\n\nCompany-specific TODO: Before submitting, add one concrete reason based on {company}'s product, market, or team."
        ).strip(),
        "why_this_role": (
            f"{why_role_base}\n\nFor the {title} role, I would emphasize {keyword_phrase}, using only the projects and experience already listed in my resume."
        ).strip(),
        "tell_me_about_yourself": tell_me,
        "work_authorization": _build_work_authorization(job.get("country"), profile, common_answers),
        "salary_expectation": _template(common_answers, "salary_expectation"),
        "relocation": _template(common_answers, "relocation"),
        "availability": _template(common_answers, "availability") or str((profile.get("availability") or {}).get("notice_period") or ""),
    }


def _render_markdown(pack: dict[str, Any]) -> str:
    meta = pack.get("metadata") or {}
    answers = pack.get("answers") or {}
    lines: list[str] = []
    lines.append(f"# Answer Pack - {meta.get('company', '')} - {meta.get('title', '')}".strip())
    lines.append("")
    lines.append(f"- Canonical job id: {meta.get('canonical_job_id', '')}")
    lines.append(f"- Country: {meta.get('country', '')}")
    lines.append(f"- Role category: {meta.get('role_category', '')}")
    lines.append(f"- Resume file: {meta.get('generated_resume_file', '') or 'TODO: Generate or select resume before applying.'}")
    lines.append(f"- Created at: {meta.get('created_at', '')}")
    lines.append("")
    lines.append("## Sensitive Field Warning")
    lines.append(pack.get("sensitive_field_warning") or "Sensitive fields must be answered manually.")
    lines.append("")
    for key, title in [
        ("why_this_company", "Why This Company"),
        ("why_this_role", "Why This Role"),
        ("tell_me_about_yourself", "Tell Me About Yourself"),
        ("work_authorization", "Work Authorization"),
        ("salary_expectation", "Salary Expectation"),
        ("relocation", "Relocation"),
        ("availability", "Availability"),
    ]:
        lines.append(f"## {title}")
        lines.append(str(answers.get(key) or "TODO: Review manually."))
        lines.append("")
    lines.append("## Relevant Project Summary")
    lines.append(pack.get("relevant_project_summary_text") or "TODO: Review manually.")
    lines.append("")
    lines.append("## Top Talking Points")
    for point in pack.get("top_talking_points") or []:
        lines.append(f"- {point}")
    lines.append("")
    lines.append("## Top Keywords To Mention")
    for keyword in pack.get("top_keywords_to_mention") or []:
        lines.append(f"- {keyword}")
    lines.append("")
    lines.append("## Sensitive Questions")
    for key, value in (pack.get("sensitive_question_answers") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## TODO")
    for item in pack.get("todo") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).strip() + "\n"


def generate_answer_pack(
    job: dict[str, Any],
    *,
    generated_resume_file: str = "",
    output_dir: Path = APPLY_ASSIST_DIR,
    master_resume_path: Path = MASTER_RESUME_PATH,
    apply_profile_path: Path = APPLY_PROFILE_PATH,
    common_answers_path: Path = COMMON_ANSWERS_PATH,
    sensitive_policy_path: Path = SENSITIVE_POLICY_PATH,
) -> dict[str, Any]:
    master = _load_config(master_resume_path)
    profile = _load_config(apply_profile_path)
    common_answers = _load_config(common_answers_path)
    policy = _load_config(sensitive_policy_path)
    resume_text = flatten_text(master)
    description = str(job.get("description") or "")
    keyword_info = extract_keywords(description, resume_text)
    ordered_keyword_candidates: list[str] = []
    for bucket in [
        "required_skills",
        "preferred_skills",
        "tools",
        "financial_products",
        "responsibilities",
        "ats_keywords",
        "top_keywords",
    ]:
        ordered_keyword_candidates.extend(str(x) for x in keyword_info.get(bucket) or [])
    keywords = _dedupe(ordered_keyword_candidates, 12)
    if not keywords:
        keywords = _dedupe([str(x) for x in keyword_info.get("repeated_keywords") or []], 12)
    projects = _relevant_project_summary(master, keywords)
    answers = _build_answers(job=job, master=master, profile=profile, common_answers=common_answers, keywords=keywords)
    canonical_job_id = str(job.get("canonical_job_id") or job.get("job_id") or slugify(job.get("company"), 40))
    pack = {
        "metadata": {
            "canonical_job_id": canonical_job_id,
            "company": job.get("company", ""),
            "title": job.get("title", ""),
            "country": job.get("country", ""),
            "role_category": job.get("role_category", ""),
            "apply_url": job.get("application_apply_url") or job.get("apply_url") or job.get("job_url") or "",
            "generated_resume_file": generated_resume_file or job.get("resume_used") or job.get("tailored_resume_path") or job.get("profile_resume_path") or job.get("scheduler_resume_draft_path") or job.get("resume_file_generated") or "",
            "created_at": now_utc_iso(),
        },
        "answers": answers,
        "relevant_project_summary": projects,
        "relevant_project_summary_text": _render_project_summary(projects),
        "top_talking_points": _talking_points(master, keywords),
        "top_keywords_to_mention": keywords[:5],
        "sensitive_field_warning": policy.get("warning") or "Sensitive fields must be answered manually.",
        "sensitive_question_answers": _sensitive_answers(policy),
        "keyword_info": keyword_info,
        "todo": [
            "Review every field before submitting the application.",
            "Add one company-specific reason before using the why-company answer.",
            "Answer EEO, diversity, disability, veteran, government ID, banking, medical, and exact birth date questions manually.",
            "Do not let any tool click submit automatically.",
        ],
    }
    paths = answer_pack_paths(canonical_job_id, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(paths["json"], pack)
    paths["markdown"].write_text(_render_markdown(pack), encoding="utf-8")
    pack["paths"] = {key: str(value) for key, value in paths.items()}
    return pack


def load_answer_pack(canonical_job_id: str, output_dir: Path = APPLY_ASSIST_DIR) -> dict[str, Any] | None:
    path = answer_pack_paths(canonical_job_id, output_dir)["json"]
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an Apply Assist answer pack for one job.")
    parser.add_argument("--job-id", required=True, help="canonical_job_id from the SQLite jobs table")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=APPLY_ASSIST_DIR)
    args = parser.parse_args(argv)
    job = get_job_detail(args.job_id, args.db)
    if not job:
        raise SystemExit(f"Unknown canonical_job_id: {args.job_id}")
    pack = generate_answer_pack(job, generated_resume_file=str(job.get("resume_used") or job.get("tailored_resume_path") or job.get("profile_resume_path") or job.get("scheduler_resume_draft_path") or job.get("resume_file_generated") or ""), output_dir=args.out)
    print(pack["paths"]["markdown"])
    print(pack["paths"]["json"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
