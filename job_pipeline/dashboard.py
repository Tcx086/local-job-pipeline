from __future__ import annotations

import html
import json
from datetime import datetime, timedelta
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from job_pipeline.application_answers import answer_pack_paths, generate_answer_pack, load_answer_pack
from job_pipeline.config_loader import public_config_status
from job_pipeline.campaign import build_daily_campaign, load_resume_profile_paths, profile_resume_exists, profile_resume_path, profile_resume_source_path
from job_pipeline.browser_launcher import open_apply_url, open_company_careers_page, open_resume_file, read_local_text
from job_pipeline import database as database_module
from job_pipeline.database import DEFAULT_DB, get_campaign_items, get_companies, get_job_detail, get_jobs, get_latest_campaign_date, replace_campaign_items, save_campaign_items, update_application, update_campaign_item_files, update_campaign_item_status, upsert_jobs
from job_pipeline.keyword_extract import extract_keywords
from job_pipeline.profile_export import export_profile
from job_pipeline.normalize import normalize_job
from job_pipeline.query_expander import load_reporting_config
from job_pipeline.search_scope import SearchScopeError, enabled_countries, load_search_scope
from job_pipeline.resume_tailor import generate_profile_resumes, generate_resume
from job_pipeline.score import score_job
from job_pipeline.utils import CONFIG_DIR, flatten_text, load_yaml, now_utc_iso, today_yyyymmdd

st.set_page_config(page_title="Job Pipeline Dashboard", layout="wide")

DASHBOARD_DEFAULT_MIN_SCORE = int(load_reporting_config().get("dashboard_default_min_score") or 35)
APPLY_ASSIST_DEFAULT_MIN_SCORE = 70


def _empty_diagnostic_rows(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return []


def _noop_mark_manual_search_checked(*args: Any, **kwargs: Any) -> None:
    return None


get_search_coverage_rows = getattr(database_module, "get_search_coverage_rows", _empty_diagnostic_rows)
get_source_health_rows = getattr(database_module, "get_source_health_rows", _empty_diagnostic_rows)
get_manual_search_urls = getattr(database_module, "get_manual_search_urls", _empty_diagnostic_rows)
mark_manual_search_checked = getattr(database_module, "mark_manual_search_checked", _noop_mark_manual_search_checked)
get_job_merge_events = getattr(database_module, "get_job_merge_events", _empty_diagnostic_rows)

DASHBOARD_TAB_LABELS = [
    "Overview",
    "Setup / Search Scope",
    "Job Radar",
    "Application Tracker",
    "Company Tracker",
    "Resume Center",
    "Apply Assist",
    "Application Campaign",
    "Search Coverage",
    "Source Health",
    "Manual Search",
    "Dedupe Audit",
]


def _config() -> dict[str, Any]:
    try:
        return load_yaml(CONFIG_DIR / "dashboard_config.yaml") or {}
    except Exception:
        return {}



def setup_search_scope_page() -> None:
    st.header("Setup / Search Scope")
    status_rows = public_config_status()
    st.subheader("Config Files")
    _dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)

    try:
        scope = load_search_scope()
    except (RuntimeError, SearchScopeError, FileNotFoundError) as exc:
        st.error(str(exc))
        st.info("Run python -m job_pipeline.setup_wizard --init, then edit config/search_scope.yaml.")
        return

    search = scope.get("search") if isinstance(scope.get("search"), dict) else {}
    st.subheader("Active Search Settings")
    st.write(
        {
            "hours_old": search.get("hours_old"),
            "results_wanted": search.get("results_wanted"),
            "sleep_seconds": search.get("sleep_seconds"),
            "mode": search.get("mode"),
            "sites": search.get("sites") or [],
        }
    )

    rows: list[dict[str, Any]] = []
    for country, payload in enabled_countries(scope).items():
        rows.append(
            {
                "country": country,
                "locations": "; ".join(str(item) for item in payload.get("locations") or []),
                "search_terms": "; ".join(str(item) for item in payload.get("search_terms") or []),
            }
        )
    st.subheader("Enabled Countries")
    _dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.info("Edit config/search_scope.yaml to change countries, locations, role keywords, job boards, and filters.")
    st.warning("Do not store sensitive identity, government ID, demographic, health, or financial data in config files.")

def _configured_country_options() -> list[str]:
    try:
        options = sorted(enabled_countries(load_search_scope()).keys())
    except Exception:
        options = []
    for value in ["Remote", ""]:
        if value not in options:
            options.append(value)
    return options
def _jobs_df() -> pd.DataFrame:
    rows = get_jobs(DEFAULT_DB, include_inactive=True)
    return pd.DataFrame(rows)


def _safe_list(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df.columns or df.empty:
        return []
    return sorted(str(v) for v in df[column].dropna().unique() if str(v))

POST_APPLY_STATUSES = {"applied", "interview", "rejected"}
CAMPAIGN_APPLICATION_BUCKETS = ["Not applied", "Applied", "All"]


def _lower_text_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series("", index=df.index, dtype=str)
    return df[column].fillna("").astype(str).str.strip().str.lower()


def _nonempty_text_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    return df[column].fillna("").astype(str).str.strip() != ""


def _applied_jobs_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    status = _lower_text_series(df, "status")
    applied_at = _nonempty_text_series(df, "applied_at")
    return df[status.isin(POST_APPLY_STATUSES) | applied_at].copy()


def _campaign_applied_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(False, index=df.index, dtype=bool)
    campaign_status = _lower_text_series(df, "campaign_status")
    application_status = _lower_text_series(df, "application_status")
    applied_at = _nonempty_text_series(df, "applied_at")
    return (campaign_status == "applied") | application_status.isin(POST_APPLY_STATUSES) | applied_at


def _campaign_df_with_application_bucket(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    if output.empty:
        output["application_bucket"] = []
        return output
    applied_mask = _campaign_applied_mask(output)
    output["application_bucket"] = applied_mask.map({True: "Applied", False: "Not applied"})
    return output


def _filter_campaign_bucket(df: pd.DataFrame, bucket: str) -> pd.DataFrame:
    bucket_series = df.get("application_bucket", pd.Series("", index=df.index))
    if bucket == "Applied":
        return df[bucket_series == "Applied"].copy()
    if bucket == "Not applied":
        return df[bucket_series == "Not applied"].copy()
    return df.copy()


def _resolve_dashboard_path(path_text: Any) -> Path:
    path = Path(str(path_text or ""))
    return path if path.is_absolute() else PROJECT_ROOT / path


def _file_exists(path_text: Any) -> bool:
    if not path_text:
        return False
    return _resolve_dashboard_path(path_text).exists()


def _file_updated_at(path_text: Any) -> str:
    if not path_text:
        return ""
    path = _resolve_dashboard_path(path_text)
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _profile_resume_rows(profile_paths: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    profile_paths = profile_paths or load_resume_profile_paths()
    profiles = profile_paths.get("profiles") if isinstance(profile_paths.get("profiles"), dict) else {}
    rows: list[dict[str, Any]] = []
    for profile, payload in profiles.items():
        configured = payload if isinstance(payload, dict) else {}
        source_path = profile_resume_source_path(str(profile), profile_paths)
        selected_path = profile_resume_path(str(profile), profile_paths)
        pdf_path = str(configured.get("pdf") or "")
        docx_path = str(configured.get("docx") or "")
        rows.append(
            {
                "profile": str(profile),
                "ready": _file_exists(pdf_path) and _file_exists(docx_path),
                "source_exists": _file_exists(source_path),
                "pdf_exists": _file_exists(pdf_path),
                "docx_exists": _file_exists(docx_path),
                "updated_at": max(_file_updated_at(pdf_path), _file_updated_at(docx_path)),
                "selected_path": selected_path,
                "pdf_path": pdf_path,
                "docx_path": docx_path,
                "source_path": source_path,
            }
        )
    return rows


def _tailored_resume_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "tailored_resume_path" not in df.columns:
        return pd.DataFrame()
    tailored = df[df["tailored_resume_path"].fillna("").astype(str).str.strip() != ""].copy()
    if tailored.empty:
        return tailored
    if "campaign_date" in tailored.columns:
        sort_columns = ["campaign_date"]
        ascending = [False]
        if "score" in tailored.columns:
            sort_columns.append("score")
            ascending.append(False)
        tailored = tailored.sort_values(sort_columns, ascending=ascending)
    return tailored

def _apply_url(detail: dict[str, Any]) -> str:
    return str(detail.get("application_apply_url") or detail.get("apply_url") or detail.get("job_url") or "")


URL_COLUMN_LABELS = {
    "apply_url": "Apply URL",
    "application_apply_url": "Application Apply URL",
    "job_url": "Job URL",
    "search_url": "Search URL",
    "careers_url": "Careers URL",
    "company_careers_url": "Company Careers URL",
    "incoming_url": "Incoming URL",
    "existing_url": "Existing URL",
}


def _url_column_config(df: pd.DataFrame) -> dict[str, Any]:
    return {
        column: st.column_config.LinkColumn(label, display_text="Open", width="medium")
        for column, label in URL_COLUMN_LABELS.items()
        if column in df.columns
    }


def _dataframe(data: Any, **kwargs: Any) -> Any:
    column_config = dict(kwargs.pop("column_config", {}) or {})
    if kwargs.pop("use_container_width", None) is True and "width" not in kwargs:
        kwargs["width"] = "stretch"
    if isinstance(data, pd.DataFrame):
        column_config = {**_url_column_config(data), **column_config}
    if column_config:
        kwargs["column_config"] = column_config
    return st.dataframe(data, **kwargs)

def _recommended_resume(detail: dict[str, Any]) -> str:
    return str(detail.get("resume_used") or detail.get("tailored_resume_path") or detail.get("profile_resume_path") or detail.get("scheduler_resume_draft_path") or detail.get("resume_file_generated") or "")


def _company_careers_url(detail: dict[str, Any]) -> str:
    canonical = str(detail.get("canonical_company") or "").strip().lower()
    if not canonical:
        return ""
    for company in get_companies(DEFAULT_DB):
        if str(company.get("canonical_company") or "").strip().lower() == canonical:
            return str(company.get("careers_url") or "")
    return ""


def _copy_button(label: str, text: str, key: str) -> None:
    payload = json.dumps(text or "")
    element_id = "copy_" + re.sub(r"[^a-zA-Z0-9_]+", "_", key)
    components.html(
        f"""
        <button id="{element_id}" style="font: 14px system-ui; padding: 0.45rem 0.7rem; border: 1px solid #d0d7de; border-radius: 6px; background: #fff; cursor: pointer;">{html.escape(label)}</button>
        <script>
        const button = document.getElementById({json.dumps(element_id)});
        button.onclick = async () => {{
          await navigator.clipboard.writeText({payload});
          button.textContent = "Copied";
          setTimeout(() => button.textContent = {json.dumps(label)}, 1200);
        }};
        </script>
        """,
        height=42,
    )


def _pack_markdown(pack: dict[str, Any] | None) -> str:
    if not pack:
        return ""
    paths = pack.get("paths") or {}
    md_path = paths.get("markdown") or str(answer_pack_paths(str((pack.get("metadata") or {}).get("canonical_job_id") or ""))["markdown"])
    return read_local_text(md_path)


def _load_pack_for_detail(detail: dict[str, Any]) -> dict[str, Any] | None:
    canonical_id = str(detail.get("canonical_job_id") or "")
    if not canonical_id:
        return None
    return load_answer_pack(canonical_id)


def _generate_pack_for_detail(detail: dict[str, Any]) -> dict[str, Any]:
    return generate_answer_pack(detail, generated_resume_file=_recommended_resume(detail))


def _render_apply_shortcuts(detail: dict[str, Any], prefix: str) -> None:
    canonical_id = str(detail.get("canonical_job_id") or prefix)
    pack = _load_pack_for_detail(detail)
    cols = st.columns(4)
    if cols[0].button("Generate Answer Pack", key=f"{prefix}_gen_{canonical_id}"):
        pack = _generate_pack_for_detail(detail)
        st.success(f"Answer pack generated: {pack['paths']['markdown']}")
        st.rerun()
    if cols[1].button("Open Apply Page", key=f"{prefix}_open_apply_{canonical_id}"):
        if open_apply_url(detail):
            st.success("Opened apply page")
        else:
            st.warning("No valid apply URL found.")
    if cols[2].button("Open Company Careers", key=f"{prefix}_open_company_{canonical_id}"):
        if open_company_careers_page(_company_careers_url(detail)):
            st.success("Opened company careers page")
        else:
            st.warning("No company careers URL found.")
    if cols[3].button("Open Resume File", key=f"{prefix}_open_resume_{canonical_id}"):
        if open_resume_file(_recommended_resume(detail)):
            st.success("Opened resume file")
        else:
            st.warning("No generated resume file found.")
    if pack:
        answers = pack.get("answers") or {}
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            _copy_button("Copy Answer Pack", _pack_markdown(pack), f"{prefix}_copy_pack_{canonical_id}")
        with c2:
            _copy_button("Copy Why Role", str(answers.get("why_this_role") or ""), f"{prefix}_copy_role_{canonical_id}")
        with c3:
            _copy_button("Copy Work Authorization", str(answers.get("work_authorization") or ""), f"{prefix}_copy_auth_{canonical_id}")
        with c4:
            _copy_button("Copy Tell Me", str(answers.get("tell_me_about_yourself") or ""), f"{prefix}_copy_tell_{canonical_id}")


def overview(df: pd.DataFrame) -> None:
    st.header("Overview")
    today_new = int(((df.get("freshness_label") == "new_today") | (df.get("is_new_since_last_run") == 1)).sum()) if not df.empty else 0
    high_score = int((df.get("score", pd.Series(dtype=int)).fillna(0).astype(int) >= 70).sum()) if not df.empty else 0
    must_apply = int((df.get("score", pd.Series(dtype=int)).fillna(0).astype(int) >= 85).sum()) if not df.empty else 0
    applied = int((df.get("status", pd.Series(dtype=str)).fillna("new") == "applied").sum()) if not df.empty else 0
    pending = int((df.get("status", pd.Series(dtype=str)).fillna("new").isin(["new", "reviewed", "apply_today"])).sum()) if not df.empty else 0
    interview = int((df.get("status", pd.Series(dtype=str)).fillna("new") == "interview").sum()) if not df.empty else 0
    rejected = int((df.get("status", pd.Series(dtype=str)).fillna("new") == "rejected").sum()) if not df.empty else 0
    cols = st.columns(7)
    for col, label, value in zip(cols, ["New", "Score >= 70", "Must Apply", "Applied", "Pending", "Interview", "Rejected"], [today_new, high_score, must_apply, applied, pending, interview, rejected]):
        col.metric(label, value)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("By Country")
        if "country" in df:
            st.bar_chart(df["country"].fillna("unknown").value_counts())
    with c2:
        st.subheader("By Role Category")
        if "role_category" in df:
            st.bar_chart(df["role_category"].fillna("unknown").value_counts())


def job_radar(df: pd.DataFrame) -> None:
    st.header("Job Radar")
    if df.empty:
        st.info("No jobs in SQLite yet. Run the scheduler first.")
        return
    filtered = df.copy()
    c1, c2, c3, c4 = st.columns(4)
    country = c1.multiselect("Country", _safe_list(df, "country"), key="radar_country")
    company = c2.multiselect("Company", _safe_list(df, "company"), key="radar_company")
    recommendation = c3.multiselect("Recommendation", _safe_list(df, "recommendation"), key="radar_recommendation")
    freshness = c4.multiselect("Freshness", _safe_list(df, "freshness_label"), key="radar_freshness")
    c5, c6, c7, c8 = st.columns(4)
    role = c5.multiselect("Role", _safe_list(df, "role_category"), key="radar_role")
    source = c6.multiselect("Source", _safe_list(df, "source"), key="radar_source")
    status = c7.multiselect("Status", _safe_list(df, "status"), key="radar_status")
    score_range = c8.slider("Score range", 0, 100, (DASHBOARD_DEFAULT_MIN_SCORE, 100))
    keyword = st.text_input("Keyword search")

    for column, values in [("country", country), ("company", company), ("recommendation", recommendation), ("freshness_label", freshness), ("role_category", role), ("source", source), ("status", status)]:
        if values:
            filtered = filtered[filtered[column].fillna("").isin(values)]
    filtered = filtered[filtered["score"].fillna(0).astype(int).between(score_range[0], score_range[1])]
    if keyword:
        haystack = filtered.fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        filtered = filtered[haystack.str.contains(keyword.lower(), regex=False)]

    display_cols = ["score", "score_band", "recommendation", "freshness_label", "title", "company", "country", "location", "role_category", "seniority", "posted_at", "first_seen_at", "source", "apply_url", "status", "next_action", "canonical_job_id"]
    _dataframe(filtered[[c for c in display_cols if c in filtered.columns]], use_container_width=True, hide_index=True)

    manual_review = filtered[(filtered["score"].fillna(0).astype(int) >= 35) & (filtered["score"].fillna(0).astype(int) < 55)]
    st.subheader("Manual Review 35-54")
    if manual_review.empty:
        st.info("No manual review candidates in the current filters.")
    else:
        _dataframe(manual_review[[c for c in display_cols if c in manual_review.columns]], use_container_width=True, hide_index=True)
    selected = st.selectbox("Select job detail", [""] + filtered.get("canonical_job_id", pd.Series(dtype=str)).fillna("").tolist())
    if selected:
        detail = get_job_detail(selected, DEFAULT_DB)
        if detail:
            st.subheader(f"{detail.get('title')} - {detail.get('company')}")
            st.write(detail.get("reason_to_apply"))
            st.markdown("**Apply Assist**")
            _render_apply_shortcuts(detail, "radar")
            st.markdown("**Apply URL**")
            st.write(_apply_url(detail))
            st.markdown("**Matched keywords**")
            st.write(detail.get("matched_keywords"))
            st.markdown("**Missing keywords**")
            st.write(detail.get("missing_keywords"))
            st.markdown("**Red flags**")
            st.write(detail.get("red_flags"))
            st.markdown("**Resume draft**")
            st.code(_recommended_resume(detail))
            st.markdown("**Description**")
            st.write(detail.get("description") or "")
            st.markdown("**Snapshots**")
            _dataframe(pd.DataFrame(detail.get("snapshots") or []), use_container_width=True, hide_index=True)


def application_tracker(df: pd.DataFrame) -> None:
    st.header("Application Tracker")
    if df.empty:
        st.info("No jobs available.")
        return
    applied_df = _applied_jobs_df(df)
    if applied_df.empty:
        st.info("No applied jobs yet. Mark a campaign item as applied first.")
        return
    if "applied_at" in applied_df.columns:
        applied_df = applied_df.sort_values(["applied_at", "company", "title"], ascending=[False, True, True])
    options = {
        f"{row.get('company')} - {row.get('title')} [{row.get('canonical_job_id')} ]": row.get("canonical_job_id")
        for _, row in applied_df.iterrows()
    }
    selected_label = st.selectbox("Applied job", list(options.keys()))
    canonical_id = options[selected_label]
    detail = get_job_detail(canonical_id, DEFAULT_DB) or {}
    statuses = _config().get("statuses", ["new", "reviewed", "apply_today", "applied", "interview", "rejected", "archived", "skipped"])
    with st.form("status_form"):
        status = st.selectbox("Status", statuses, index=statuses.index(detail.get("status", "new")) if detail.get("status", "new") in statuses else 0)
        applied_at = st.text_input("Applied at", value=str(detail.get("applied_at") or ""))
        resume_used = st.text_input("Resume used", value=_recommended_resume(detail))
        cover_letter_used = st.text_input("Cover letter used", value=str(detail.get("cover_letter_used") or ""))
        apply_url = st.text_input("Apply URL", value=_apply_url(detail))
        confirmation_number = st.text_input("Confirmation number", value=str(detail.get("confirmation_number") or ""))
        confirmation_snippet = st.text_area("Confirmation email snippet", value=str(detail.get("confirmation_snippet") or ""))
        notes = st.text_area("Notes", value=str(detail.get("notes") or ""))
        next_action = st.text_input("Next action", value=str(detail.get("next_action") or ""))
        next_action_date = st.text_input("Next action date", value=str(detail.get("next_action_date") or ""))
        interview_date = st.text_input("Interview date", value=str(detail.get("interview_date") or ""))
        rejection_date = st.text_input("Rejection date", value=str(detail.get("rejection_date") or ""))
        company_response = st.text_area("Company response", value=str(detail.get("company_response") or ""))
        if st.form_submit_button("Save"):
            update_application(
                canonical_id,
                status=status,
                applied_at=applied_at,
                resume_used=resume_used,
                cover_letter_used=cover_letter_used,
                apply_url=apply_url,
                confirmation_number=confirmation_number,
                confirmation_snippet=confirmation_snippet,
                notes=notes,
                next_action=next_action,
                next_action_date=next_action_date,
                interview_date=interview_date,
                rejection_date=rejection_date,
                company_response=company_response,
                db_path=DEFAULT_DB,
            )
            st.success("Saved")


def company_tracker() -> None:
    st.header("Company Tracker")
    companies = pd.DataFrame(get_companies(DEFAULT_DB))
    _dataframe(companies, use_container_width=True, hide_index=True)


def resume_center(df: pd.DataFrame) -> None:
    st.header("Resume Center")
    profile_rows = _profile_resume_rows()
    profile_df = pd.DataFrame(profile_rows)
    tailored_df = _tailored_resume_rows(df)
    ready_count = int(profile_df.get("ready", pd.Series(dtype=bool)).sum()) if not profile_df.empty else 0
    legacy_count = 0
    for legacy_column in ["scheduler_resume_draft_path", "resume_file_generated"]:
        if legacy_column in df.columns:
            legacy_count += int((df[legacy_column].fillna("").astype(str).str.strip() != "").sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Profile resumes", f"{ready_count}/{len(profile_rows)}")
    c2.metric("Tailored resumes", int(len(tailored_df)))
    c3.metric("Scheduler drafts", legacy_count)

    if st.button("Regenerate Profile Resumes", key="resume_center_regenerate_profiles"):
        results = generate_profile_resumes()
        st.success(f"Generated {len(results)} profile resume set(s).")
        st.rerun()

    st.subheader("Profile Resumes")
    if profile_df.empty:
        st.info("No resume profiles configured.")
    else:
        profile_columns = ["profile", "ready", "source_exists", "pdf_exists", "docx_exists", "updated_at", "pdf_path", "docx_path", "source_path"]
        _dataframe(profile_df[[c for c in profile_columns if c in profile_df.columns]], use_container_width=True, hide_index=True)
        selected_profile = st.selectbox("Profile", profile_df["profile"].tolist(), key="resume_center_profile")
        selected = profile_df[profile_df["profile"] == selected_profile].iloc[0].to_dict()
        actions = st.columns(3)
        if actions[0].button("Open PDF", key=f"resume_center_open_pdf_{selected_profile}"):
            if open_resume_file(selected.get("pdf_path")):
                st.success("Opened PDF")
            else:
                st.warning("PDF file not found.")
        if actions[1].button("Open DOCX", key=f"resume_center_open_docx_{selected_profile}"):
            if open_resume_file(selected.get("docx_path")):
                st.success("Opened DOCX")
            else:
                st.warning("DOCX file not found.")
        if actions[2].button("Open Source YAML", key=f"resume_center_open_source_{selected_profile}"):
            if open_resume_file(selected.get("source_path")):
                st.success("Opened source YAML")
            else:
                st.warning("Source YAML not found.")

    st.subheader("Tailored Resumes")
    if tailored_df.empty:
        st.info("No tailored resumes generated yet.")
    else:
        tailored_columns = ["campaign_date", "title", "company", "score", "application_effort", "campaign_status", "application_status", "resume_profile", "tailored_resume_path", "answer_pack_path", "canonical_job_id"]
        _dataframe(tailored_df[[c for c in tailored_columns if c in tailored_df.columns]], use_container_width=True, hide_index=True)

    with st.expander("Scheduler Drafts", expanded=False):
        draft_column = "scheduler_resume_draft_path" if "scheduler_resume_draft_path" in df else "resume_file_generated"
        if df.empty or draft_column not in df:
            st.info("No scheduler drafts found.")
            return
        resumes = df[df[draft_column].fillna("").astype(str).str.strip() != ""].copy()
        if resumes.empty:
            st.info("No scheduler drafts found.")
            return
        if "missing_keywords" in resumes.columns:
            resumes["missing_keywords_to_review"] = resumes["missing_keywords"]
        columns = ["title", "company", "score", "scheduler_resume_draft_path", "resume_file_generated", "missing_keywords_to_review", "role_category"]
        _dataframe(resumes[[c for c in columns if c in resumes.columns]], use_container_width=True, hide_index=True)


def apply_assist_page(df: pd.DataFrame) -> None:
    st.header("Apply Assist")
    c1, c2 = st.columns([1, 3])
    if c1.button("Generate Profile Export"):
        result = export_profile()
        st.success(f"Profile export generated: {result['paths']['markdown']}")
    c2.warning("Manual application boundary: no auto-submit, no login automation, no captcha bypass, and no sensitive field autofill.")
    if df.empty:
        st.info("No jobs available.")
        return
    min_score = st.slider("Minimum score", 0, 100, APPLY_ASSIST_DEFAULT_MIN_SCORE, key="apply_assist_min_score")
    candidates = df[df["score"].fillna(0).astype(int) >= min_score].copy()
    if candidates.empty:
        st.info("No jobs match this score threshold.")
        return
    options = {
        f"{int(row.get('score') or 0)} - {row.get('company')} - {row.get('title')} [{row.get('canonical_job_id')}]": row.get("canonical_job_id")
        for _, row in candidates.iterrows()
    }
    selected_label = st.selectbox("Job", list(options.keys()), key="apply_assist_job")
    canonical_id = str(options[selected_label])
    detail = get_job_detail(canonical_id, DEFAULT_DB) or {}
    pack = _load_pack_for_detail(detail)
    apply_url = _apply_url(detail)
    resume_path = _recommended_resume(detail)

    top = st.columns(4)
    top[0].metric("Score", int(detail.get("score") or 0))
    top[1].metric("Status", str(detail.get("status") or "new"))
    top[2].metric("Country", str(detail.get("country") or ""))
    top[3].metric("Recommendation", str(detail.get("recommendation") or ""))

    st.subheader(f"{detail.get('title')} - {detail.get('company')}")
    info_cols = st.columns(2)
    with info_cols[0]:
        st.markdown("**Apply URL**")
        st.write(apply_url)
        st.markdown("**Recommended resume**")
        st.code(resume_path or "Generate/select a resume before applying.")
        st.markdown("**Next action**")
        st.write(detail.get("next_action") or "Review and apply manually")
    with info_cols[1]:
        st.markdown("**Sensitive field warning**")
        st.write("Answer EEO, diversity, disability, veteran, government ID, banking, medical, and exact birth date fields manually.")
        st.markdown("**Notes**")
        st.write(detail.get("notes") or "")

    _render_apply_shortcuts(detail, "assist")

    st.markdown("**Answer pack**")
    if pack:
        st.code(pack.get("paths", {}).get("markdown", ""))
        st.markdown(_pack_markdown(pack))
    else:
        st.info("Generate an answer pack for this job.")

    st.subheader("Application Status")
    notes = st.text_area("Notes", value=str(detail.get("notes") or ""), key=f"assist_notes_{canonical_id}")
    next_action = st.text_input("Next action", value=str(detail.get("next_action") or ""), key=f"assist_next_{canonical_id}")
    confirmation_number = st.text_input("Confirmation number", value=str(detail.get("confirmation_number") or ""), key=f"assist_conf_no_{canonical_id}")
    confirmation_snippet = st.text_area("Confirmation email snippet", value=str(detail.get("confirmation_snippet") or ""), key=f"assist_conf_snip_{canonical_id}")
    buttons = st.columns(4)
    if buttons[0].button("Mark as Applied", key=f"assist_applied_{canonical_id}"):
        update_application(
            canonical_id,
            status="applied",
            applied_at=now_utc_iso(),
            resume_used=resume_path,
            apply_url=apply_url,
            notes=notes,
            next_action=next_action,
            confirmation_number=confirmation_number,
            confirmation_snippet=confirmation_snippet,
            db_path=DEFAULT_DB,
        )
        st.success("Marked as applied")
        st.rerun()
    if buttons[1].button("Mark as Skipped", key=f"assist_skipped_{canonical_id}"):
        update_application(canonical_id, status="skipped", apply_url=apply_url, notes=notes, next_action=next_action, db_path=DEFAULT_DB)
        st.success("Marked as skipped")
        st.rerun()
    if buttons[2].button("Mark as Interview", key=f"assist_interview_{canonical_id}"):
        update_application(canonical_id, status="interview", apply_url=apply_url, notes=notes, next_action=next_action, db_path=DEFAULT_DB)
        st.success("Marked as interview")
        st.rerun()
    if buttons[3].button("Add Note", key=f"assist_note_{canonical_id}"):
        update_application(
            canonical_id,
            status=str(detail.get("status") or "reviewed"),
            apply_url=apply_url,
            notes=notes,
            next_action=next_action,
            confirmation_number=confirmation_number,
            confirmation_snippet=confirmation_snippet,
            db_path=DEFAULT_DB,
        )
        st.success("Note saved")
        st.rerun()




def _campaign_resume_path(row: dict[str, Any]) -> str:
    return str(row.get("tailored_resume_path") or row.get("profile_resume_path") or row.get("resume_used") or "")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _next_campaign_date(campaign_date: str) -> str:
    try:
        return (datetime.strptime(campaign_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    except ValueError:
        return today_yyyymmdd()


def _generate_tailored_resume_for_campaign(row: dict[str, Any]) -> str:
    if not _truthy(row.get("allow_manual_generate_resume")):
        return ""
    canonical_id = str(row.get("canonical_job_id") or "")
    detail = get_job_detail(canonical_id, DEFAULT_DB) or row
    resume_profile = str(row.get("resume_profile") or detail.get("resume_profile") or "")
    source_path_text = profile_resume_source_path(resume_profile)
    if not source_path_text:
        return ""
    source_path = Path(source_path_text)
    if not source_path.exists():
        return ""
    profile_source = load_yaml(source_path)
    keyword_info = extract_keywords(str(detail.get("description") or ""), flatten_text(profile_source))
    paths = generate_resume(master_resume_path=source_path, job=detail, keyword_info=keyword_info)
    resume_path = str(paths.get("pdf") or paths.get("docx") or paths.get("markdown") or "")
    if resume_path:
        update_campaign_item_files(str(row.get("campaign_date") or ""), canonical_id, tailored_resume_path=resume_path, db_path=DEFAULT_DB)
    return resume_path


def _generate_answer_pack_for_campaign(row: dict[str, Any]) -> str:
    if not _truthy(row.get("allow_manual_generate_answer_pack")):
        return ""
    canonical_id = str(row.get("canonical_job_id") or "")
    detail = get_job_detail(canonical_id, DEFAULT_DB) or row
    pack = generate_answer_pack(detail, generated_resume_file=_campaign_resume_path(row))
    answer_path = str((pack.get("paths") or {}).get("markdown") or "")
    if answer_path:
        update_campaign_item_files(str(row.get("campaign_date") or ""), canonical_id, answer_pack_path=answer_path, db_path=DEFAULT_DB)
    return answer_path


def application_campaign_page(df: pd.DataFrame) -> None:
    st.header("Application Campaign")
    default_date = get_latest_campaign_date(DEFAULT_DB) or today_yyyymmdd()
    c1, c2 = st.columns([1, 2])
    campaign_date = c1.text_input("Campaign date", value=default_date)
    if c2.button("Generate Today Campaign"):
        result = build_daily_campaign(get_jobs(DEFAULT_DB, include_inactive=False), campaign_date=campaign_date)
        replace_campaign_items(DEFAULT_DB, result["campaign_date"], result["today_campaign"])
        st.success(f"Campaign generated: {result['summary']['total_items']} items")
        st.rerun()

    rows = get_campaign_items(DEFAULT_DB, campaign_date=campaign_date)
    campaign_df = _campaign_df_with_application_bucket(pd.DataFrame(rows))
    if campaign_df.empty:
        st.info("No campaign items for this date. Generate a campaign first.")
        return

    effort = campaign_df.get("application_effort", pd.Series(dtype=str)).fillna("")
    status = campaign_df.get("campaign_status", pd.Series(dtype=str)).fillna("")
    applied_mask = _campaign_applied_mask(campaign_df)
    queued = (status == "queued") & ~applied_mask
    metrics = st.columns(7)
    metrics[0].metric("Deep Tailor", int((effort == "deep_tailor").sum()))
    metrics[1].metric("Standard Tailor", int((effort == "standard_tailor").sum()))
    metrics[2].metric("Quick Apply", int((effort == "quick_apply").sum()))
    metrics[3].metric("Estimated Minutes", int(campaign_df.loc[queued, "estimated_minutes"].fillna(0).astype(int).sum()) if "estimated_minutes" in campaign_df else 0)
    metrics[4].metric("Applied", int(applied_mask.sum()))
    metrics[5].metric("Not Applied", int((~applied_mask).sum()))
    metrics[6].metric("Remaining", int(queued.sum()))

    bucket_view = st.radio("Application bucket", CAMPAIGN_APPLICATION_BUCKETS, horizontal=True, key="campaign_application_bucket")
    bucket_df = _filter_campaign_bucket(campaign_df, bucket_view)
    filtered = bucket_df.copy()
    f1, f2, f3, f4 = st.columns(4)
    effort_filter = f1.multiselect("Effort", _safe_list(bucket_df, "application_effort"), key="campaign_effort")
    country_filter = f2.multiselect("Country", _safe_list(bucket_df, "country"), key="campaign_country")
    profile_filter = f3.multiselect("Resume Profile", _safe_list(bucket_df, "resume_profile"), key="campaign_resume_profile")
    status_filter = f4.multiselect("Campaign Status", _safe_list(bucket_df, "campaign_status"), key="campaign_status")
    f5, f6 = st.columns([1, 3])
    score_range = f5.slider("Score range", 0, 100, (0, 100), key="campaign_score_range")
    company_filter = f6.multiselect("Company", _safe_list(bucket_df, "company"), key="campaign_company")
    for column, values in [
        ("application_effort", effort_filter),
        ("country", country_filter),
        ("resume_profile", profile_filter),
        ("campaign_status", status_filter),
        ("company", company_filter),
    ]:
        if values and column in filtered:
            filtered = filtered[filtered[column].fillna("").isin(values)]
    if "score" in filtered:
        filtered = filtered[filtered["score"].fillna(0).astype(int).between(score_range[0], score_range[1])]

    display_cols = [
        "score", "score_band", "application_effort", "title", "company", "country", "location",
        "resume_profile", "campaign_reason", "estimated_minutes", "application_bucket", "apply_url",
        "auto_generate_resume", "allow_manual_generate_resume", "auto_generate_answer_pack", "allow_manual_generate_answer_pack",
        "profile_resume_path", "tailored_resume_path", "answer_pack_path", "campaign_status", "application_status", "canonical_job_id",
    ]
    _dataframe(filtered[[c for c in display_cols if c in filtered.columns]], use_container_width=True, hide_index=True)
    if filtered.empty:
        st.info("No campaign items match the current filters.")
        return

    options = {
        f"{int(row.get('score') or 0)} - {row.get('application_effort')} - {row.get('company')} - {row.get('title')} [{row.get('canonical_job_id')} ]": row.get("canonical_job_id")
        for _, row in filtered.iterrows()
    }
    selected_label = st.selectbox("Campaign item", list(options.keys()))
    canonical_id = str(options[selected_label])
    row = filtered[filtered["canonical_job_id"] == canonical_id].iloc[0].to_dict()
    effort_value = str(row.get("application_effort") or "")
    resume_path = _campaign_resume_path(row)

    st.subheader(f"{row.get('title')} - {row.get('company')}")
    top = st.columns(5)
    top[0].metric("Score", int(row.get("score") or 0))
    top[1].metric("Effort", effort_value)
    top[2].metric("Status", str(row.get("campaign_status") or ""))
    top[3].metric("Country", str(row.get("country") or ""))
    top[4].metric("Minutes", int(row.get("estimated_minutes") or 0))

    info_cols = st.columns(2)
    with info_cols[0]:
        st.markdown("**Apply URL**")
        st.write(row.get("apply_url") or row.get("job_url") or "")
        st.markdown("**Campaign reason**")
        st.write(row.get("campaign_reason") or "")
        st.markdown("**Profile resume**")
        st.code(str(row.get("profile_resume_path") or ""))
        if row.get("profile_resume_path") and not profile_resume_exists(str(row.get("profile_resume_path"))):
            st.warning("Profile resume file is missing. Generate the profile resume before using this item.")
        elif effort_value in {"deep_tailor", "standard_tailor", "quick_apply"} and not row.get("profile_resume_path"):
            st.warning("No profile resume path configured for this resume profile.")
    with info_cols[1]:
        st.markdown("**Tailored resume**")
        st.code(str(row.get("tailored_resume_path") or ""))
        st.markdown("**Answer pack**")
        st.code(str(row.get("answer_pack_path") or ""))
        st.markdown("**Red flags**")
        st.write(row.get("red_flags") or [])

    note_key = f"campaign_note_{campaign_date}_{canonical_id}"
    notes = st.text_area("Note", value=str(row.get("notes") or row.get("application_notes") or ""), key=note_key)

    actions = st.columns(4)
    if actions[0].button("Open Apply Page", key=f"campaign_open_apply_{canonical_id}"):
        if open_apply_url(row):
            st.success("Opened apply page")
        else:
            st.warning("No valid apply URL found.")
    if actions[1].button("Open Resume File", key=f"campaign_open_resume_{canonical_id}"):
        if open_resume_file(resume_path):
            st.success("Opened resume file")
        else:
            st.warning("No resume file found.")
    if actions[2].button("Generate Tailored Resume", key=f"campaign_gen_resume_{canonical_id}", disabled=not _truthy(row.get("allow_manual_generate_resume"))):
        generated_path = _generate_tailored_resume_for_campaign(row)
        if generated_path:
            st.success(f"Tailored resume generated: {generated_path}")
        else:
            st.warning("Resume generation did not produce a file.")
        st.rerun()
    if actions[3].button("Generate Answer Pack", key=f"campaign_gen_pack_{canonical_id}", disabled=not _truthy(row.get("allow_manual_generate_answer_pack"))):
        answer_path = _generate_answer_pack_for_campaign(row)
        if answer_path:
            st.success(f"Answer pack generated: {answer_path}")
        else:
            st.warning("Answer pack generation did not produce a file.")
        st.rerun()

    status_actions = st.columns(5)
    if status_actions[0].button("Mark Applied", key=f"campaign_applied_{canonical_id}"):
        update_campaign_item_status(campaign_date, canonical_id, "applied", notes=notes, db_path=DEFAULT_DB)
        st.success("Marked applied")
        st.rerun()
    if status_actions[1].button("Mark Skipped", key=f"campaign_skipped_{canonical_id}"):
        update_campaign_item_status(campaign_date, canonical_id, "skipped", notes=notes, db_path=DEFAULT_DB)
        st.success("Marked skipped")
        st.rerun()
    if status_actions[2].button("Move to Hold", key=f"campaign_hold_{canonical_id}"):
        update_campaign_item_status(campaign_date, canonical_id, "moved_to_hold", notes=notes, db_path=DEFAULT_DB)
        st.success("Moved to hold")
        st.rerun()
    if status_actions[3].button("Defer to Tomorrow", key=f"campaign_defer_{canonical_id}"):
        tomorrow = _next_campaign_date(campaign_date)
        tomorrow_row = dict(row)
        tomorrow_row.update({"campaign_date": tomorrow, "campaign_status": "queued", "selected_at": now_utc_iso(), "completed_at": "", "notes": notes})
        save_campaign_items(DEFAULT_DB, [tomorrow_row])
        update_campaign_item_status(campaign_date, canonical_id, "deferred", notes=notes, db_path=DEFAULT_DB)
        st.success(f"Deferred to {tomorrow}")
        st.rerun()
    if status_actions[4].button("Add Note", key=f"campaign_note_save_{canonical_id}"):
        update_campaign_item_status(campaign_date, canonical_id, str(row.get("campaign_status") or "queued"), notes=notes, db_path=DEFAULT_DB)
        st.success("Note saved")
        st.rerun()
def search_coverage_page() -> None:
    st.header("Search Coverage")
    rows = get_search_coverage_rows(DEFAULT_DB)
    if not rows:
        st.info("No search coverage rows yet. Run the scheduler first.")
        return
    df = pd.DataFrame(rows)
    for column in ["raw_count", "normalized_count", "deduped_count", "scored_count", "report_count", "skipped_by_filter_count", "merged_by_dedupe_count", "high_score_count_70", "must_apply_count_85", "error_count"]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)
    if "average_score" in df:
        df["average_score"] = pd.to_numeric(df["average_score"], errors="coerce")
    metrics = st.columns(6)
    metrics[0].metric("Raw", int(df["raw_count"].sum()))
    metrics[1].metric("Normalized", int(df["normalized_count"].sum()))
    metrics[2].metric("Deduped", int(df["deduped_count"].sum()))
    metrics[3].metric("Score >= 70", int(df["high_score_count_70"].sum()))
    metrics[4].metric("Score >= 85", int(df["must_apply_count_85"].sum()))
    metrics[5].metric("Hard skipped", int(df["skipped_by_filter_count"].sum()))
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("By Source")
        st.bar_chart(df.groupby("source")["raw_count"].sum())
    with c2:
        st.subheader("By Country")
        st.bar_chart(df.groupby("country")["raw_count"].sum())
    with c3:
        st.subheader("By Query")
        st.bar_chart(df.groupby("query")["raw_count"].sum().sort_values(ascending=False).head(20))
    st.subheader("Zero-result Queries")
    _dataframe(df[df["raw_count"] == 0][["country", "source", "query", "location"]], use_container_width=True, hide_index=True)
    st.subheader("Error Sources")
    _dataframe(df[df["error_count"] > 0], use_container_width=True, hide_index=True)
    st.subheader("Coverage Rows")
    _dataframe(df, use_container_width=True, hide_index=True)


def source_health_page() -> None:
    st.header("Source Health")
    rows = get_source_health_rows(DEFAULT_DB)
    if not rows:
        st.info("No source health rows yet. Run the scheduler first.")
        return
    df = pd.DataFrame(rows)
    _dataframe(df, use_container_width=True, hide_index=True)
    if "status" in df:
        st.bar_chart(df["status"].fillna("unknown").value_counts())


def manual_search_page() -> None:
    st.header("Manual Search")
    rows = get_manual_search_urls(DEFAULT_DB, limit=2000)
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No manual URLs yet. Run the scheduler or python -m job_pipeline.search_url_builder --generate --db data/job_pipeline.sqlite")
    else:
        c1, c2, c3 = st.columns(3)
        country = c1.multiselect("Country", _safe_list(df, "country"), key="manual_search_country")
        source = c2.multiselect("Source", _safe_list(df, "source_name"), key="manual_search_source")
        query = c3.text_input("Query contains")
        filtered = df.copy()
        if country:
            filtered = filtered[filtered["country"].fillna("").isin(country)]
        if source:
            filtered = filtered[filtered["source_name"].fillna("").isin(source)]
        if query:
            filtered = filtered[filtered["query"].fillna("").str.contains(query, case=False, regex=False)]
        _dataframe(filtered, use_container_width=True, hide_index=True)
        selected = st.selectbox("Mark URL checked", [""] + [str(x) for x in filtered.get("id", pd.Series(dtype=str)).tolist()])
        if selected and st.button("Mark Checked"):
            mark_manual_search_checked(int(selected), DEFAULT_DB)
            st.success("Marked checked")
            st.rerun()

    st.subheader("Add Manual Job")
    with st.form("manual_job_form"):
        title = st.text_input("Title")
        company = st.text_input("Company")
        location = st.text_input("Location")
        country_value = st.selectbox("Country", _configured_country_options())
        job_url = st.text_input("Job URL")
        apply_url = st.text_input("Apply URL")
        source_name = st.text_input("Source", value="manual_search")
        description = st.text_area("Description")
        if st.form_submit_button("Save Manual Job"):
            job = normalize_job({
                "source": source_name or "manual_search",
                "title": title,
                "company": company,
                "location": location,
                "country": country_value,
                "job_url": job_url,
                "apply_url": apply_url or job_url,
                "description": description,
            })
            scored = score_job(job)
            upsert_jobs(DEFAULT_DB, [scored], mark_missing=False)
            st.success("Manual job saved")
            st.rerun()


def dedupe_audit_page() -> None:
    st.header("Dedupe Audit")
    rows = get_job_merge_events(DEFAULT_DB, limit=2000)
    if not rows:
        st.info("No merge events yet.")
        return
    df = pd.DataFrame(rows)
    st.metric("Merge events", len(df))
    if "incoming_source" in df:
        st.bar_chart(df["incoming_source"].fillna("unknown").value_counts())
    _dataframe(df, use_container_width=True, hide_index=True)
    st.caption("If a merge looks wrong, split manually is a TODO for the next version; this page exposes the evidence needed to identify it.")

def main() -> None:
    st.title("Local Job Pipeline")
    df = _jobs_df()
    tabs = st.tabs(DASHBOARD_TAB_LABELS)
    with tabs[0]:
        overview(df)
    with tabs[1]:
        setup_search_scope_page()
    with tabs[2]:
        job_radar(df)
    with tabs[3]:
        application_tracker(df)
    with tabs[4]:
        company_tracker()
    with tabs[5]:
        resume_center(df)
    with tabs[6]:
        apply_assist_page(df)
    with tabs[7]:
        application_campaign_page(df)
    with tabs[8]:
        search_coverage_page()
    with tabs[9]:
        source_health_page()
    with tabs[10]:
        manual_search_page()
    with tabs[11]:
        dedupe_audit_page()

if __name__ == "__main__":
    _ = main()
