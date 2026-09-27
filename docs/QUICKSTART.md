# Quickstart

1. Clone and install dependencies.

```powershell
git clone <repo-url>
cd job_pipeline
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

2. Create local config files from the public examples (private data stays in
git-ignored `local_resources/`; never edit the tracked examples with real facts).

```powershell
New-Item -ItemType Directory -Force local_resources\candidate
Copy-Item resources\candidate\master_profile.example.yaml local_resources\candidate\master_profile.yaml
```

3. Test with sample data.

```powershell
python -m job_pipeline.scheduler --run-once --sample
python -m job_pipeline.campaign --today --dry-run
streamlit run job_pipeline/dashboard.py
```

4. Review `config/search_scope.yaml`, then run a real search.

```powershell
python -m job_pipeline.scheduler --run-once --mode normal
```
