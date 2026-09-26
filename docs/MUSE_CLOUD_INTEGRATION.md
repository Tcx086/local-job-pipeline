# Muse Cloud Integration

This integration keeps **Local Job Pipeline** as the discovery, scoring, dedupe, and application-control plane while using Muse only as a browser/application execution layer.

The design goal is:

```text
job sources -> local-job-pipeline -> approved application workspace -> Muse queue
          -> Muse browser execution -> result.json -> local tracker
```

Muse should not independently search for replacement postings, rescore jobs, invent candidate facts, rewrite resumes, or decide ambiguous work-authorization answers.

## 1. Cloud bootstrap

Muse workspaces commonly expose a Linux-style home directory such as `~/workspace`. If shell access is available, use:

```bash
git clone https://github.com/Tcx086/local-job-pipeline.git ~/workspace/job-search/pipeline
cd ~/workspace/job-search/pipeline
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

For a feature branch before merge:

```bash
git clone --branch feature/muse-cloud-handoff-v1 \
  https://github.com/Tcx086/local-job-pipeline.git \
  ~/workspace/job-search/pipeline
```

Never store private candidate data in Git.

## 2. Private Muse facts

Create the ignored local file:

```bash
mkdir -p local_resources/muse
cp resources/muse/muse_facts.example.yaml local_resources/muse/muse_facts.yaml
```

Edit it with only facts that may be reused safely. Keep ambiguous or sensitive fields unset.

Examples of fields that should remain explicit rather than inferred:

- current and future sponsorship;
- U.S. work authorization versus business-travel documentation;
- salary expectations without a posted range;
- demographic responses;
- legal or background attestations.

## 3. Private application artifacts

Application resumes, cover letters, answer packs, and the SQLite tracker belong under ignored directories such as:

```text
local_resources/
data/
generated/
```

The Muse queue exporter will only export jobs whose application tracker status is explicitly approved (default: `apply_today`).

## 4. Export approved jobs

Export every approved job:

```bash
python -m job_pipeline.muse_queue export
```

Export one explicit job:

```bash
python -m job_pipeline.muse_queue export \
  --job-id CANONICAL_JOB_ID
```

Default output:

```text
generated/muse_queue/
  _queue_summary.json
  company__role__jobid/
    manifest.json
    artifacts/
      resume.pdf
      resume.docx
      cover_letter.pdf
      cover_letter_body.txt
      answer_pack.md
      job_description.md
```

A job is blocked from export when required application inputs are missing.

By default:

- a direct application URL is required;
- a resume PDF is required;
- the private Muse facts file is required.

## 5. Muse execution contract

Give Muse the instructions in `resources/muse/MUSE_EXECUTOR_PROMPT.md`.

Muse should process only bundles whose manifest says:

```json
{
  "queue_status": "READY_TO_APPLY"
}
```

For every bundle it must:

1. open only `job.official_application_url`;
2. use only candidate facts included in the manifest;
3. upload only listed artifacts;
4. stop before submission if any configured stop condition is triggered;
5. write `result.json` in the same bundle.

It should not search the web for another copy of the role.

## 6. Result file

Successful submission example:

```json
{
  "outcome": "SUBMITTED",
  "canonical_job_id": "job_123",
  "timestamp": "2026-09-26T18:00:00Z",
  "notes": "Submitted through official ATS.",
  "confirmation_number": "ABC123",
  "confirmation_text": "Thank you for applying",
  "final_url": "https://..."
}
```

Blocked example:

```json
{
  "outcome": "BLOCKED",
  "canonical_job_id": "job_123",
  "timestamp": "2026-09-26T18:00:00Z",
  "notes": "Need user decision.",
  "blocking_question": "Will you now or in the future require sponsorship?",
  "blocking_reason": "Future sponsorship answer is not preapproved."
}
```

## 7. Import Muse result into the tracker

```bash
python -m job_pipeline.muse_queue import-result \
  generated/muse_queue/company__role__jobid/result.json
```

Mappings:

- `SUBMITTED` -> application status `applied`;
- `BLOCKED` -> application stays `apply_today` with a next action;
- `SKIPPED` -> application status `skipped`.

## 8. Recommended separation of responsibilities

### Local Job Pipeline owns

- source registry;
- official ATS collection;
- discovery-source enrichment;
- freshness verification;
- dedupe;
- fit scoring;
- role family;
- application tier;
- targeted resume generation;
- answer packs;
- work-authorization facts;
- application history;
- follow-up timing.

### Muse owns

- opening the approved official URL;
- browser form entry;
- artifact upload;
- pausing on unknown questions;
- final submission when authorized;
- confirmation capture;
- writing the result contract.

This separation makes browser automation replaceable without changing the search and decision logic.
