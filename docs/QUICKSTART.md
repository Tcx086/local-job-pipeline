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

2. Create local config files.

```powershell
python -m job_pipeline.setup_wizard --init
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
