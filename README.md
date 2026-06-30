# Local Job Pipeline

Local Job Pipeline is a local-first job application pipeline for collecting public job postings, scoring them, generating local resume, cover-letter, and answer-pack drafts, and tracking manual applications.

This public repository contains code structure, tests, policies, launcher scripts, and fake examples only. Private candidate data is intentionally excluded.

## Safety Boundary

This project is designed for manual, local workflows.

- No auto-apply.
- No auto-submit.
- No login automation.
- No captcha bypass.
- No external LLM or API requirement for local generation.
- Manual review is required before any application material is used.
- Sensitive fields must be answered manually.

Generated drafts are only drafts. Review every factual claim against your own local profile and the job posting before using it.

## Directory Layout

- `config/`: public-safe configuration defaults and local workflow settings.
- `resources/`: tracked public examples, templates, policies, and job taxonomy files.
- `local_resources/`: ignored private profile files that you create locally.
- `generated/`: ignored generated resumes, cover letters, answer packs, reports, and workspaces.
- `data/`: ignored local databases, raw job pulls, processed outputs, and logs.
- `job_pipeline/`: Python package source.
- `tests/`: unit tests that run without private data.

## Resource Setup

Create your local private candidate profile from the public example:

```powershell
New-Item -ItemType Directory -Force local_resources\candidate
Copy-Item resources\candidate\master_profile.example.yaml local_resources\candidate\master_profile.yaml
```

Then edit `local_resources/candidate/master_profile.yaml` with your own facts. Do not edit tracked example files with real resume facts.

Create role-specific private profiles under:

```text
local_resources/role_profiles/*.yaml
```

Tracked role examples live under `resources/role_profiles/*.example.yaml` and contain fake data only.

## Generated Layout

Application workspaces are written under:

```text
generated/YYYYMMDD/company/role__jobid/
```

Formal resume and cover-letter files are written at the workspace root, for example:

```text
generated/20260630/example_company/example_role__job_123/Candidate_Name__Example_Company__Example_Role__Resume.docx
generated/20260630/example_company/example_role__job_123/Candidate_Name__Example_Company__Example_Role__Cover_Letter.pdf
```

Source snapshots and review files are stored inside the same workspace so each draft can be audited before use.

## Private Data Warning

Never commit:

- `local_resources/`
- `data/`
- `generated/`
- SQLite or DB files
- logs
- real resume facts
- real candidate profile YAML
- generated application materials
- credentials, tokens, or `.env` files

Only fake examples should be tracked in this public repository.

## Quick Start

Install dependencies in your preferred Python environment, then run tests:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests
```

Start the local dashboard:

```powershell
streamlit run job_pipeline/dashboard.py
```

You can also use the included local launcher scripts when running on Windows:

```powershell
.\start_local_service.ps1
```

## Public Version Note

This public repo mirrors the private project architecture while excluding private candidate data, generated applications, databases, logs, backups, resume files, and private Git history.