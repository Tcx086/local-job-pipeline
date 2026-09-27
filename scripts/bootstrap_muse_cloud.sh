#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${JOB_PIPELINE_REPO_URL:-https://github.com/Tcx086/local-job-pipeline.git}"
BRANCH="${JOB_PIPELINE_BRANCH:-main}"
ROOT="${1:-$HOME/workspace/job-search/pipeline}"

if [[ -d "$ROOT/.git" ]]; then
  git -C "$ROOT" fetch origin "$BRANCH"
  git -C "$ROOT" checkout "$BRANCH"
  git -C "$ROOT" pull --ff-only origin "$BRANCH"
else
  mkdir -p "$(dirname "$ROOT")"
  git clone --branch "$BRANCH" "$REPO_URL" "$ROOT"
fi

cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p local_resources/muse
mkdir -p generated/muse_queue
mkdir -p data/db

if [[ ! -f local_resources/muse/muse_facts.yaml ]]; then
  cp resources/muse/muse_facts.example.yaml local_resources/muse/muse_facts.yaml
  echo "Created local_resources/muse/muse_facts.yaml from the public example."
  echo "Edit it with private candidate facts before exporting applications."
fi

echo
echo "Muse cloud workspace ready at: $ROOT"
echo "Next:"
echo "  1. Add private candidate resources under local_resources/."
echo "  2. Add or sync the private SQLite tracker under data/db/."
echo "  3. Run: python -m job_pipeline.muse_queue export"
