# Contributing

Thanks for taking the time to improve Local Job Pipeline. This project is intentionally local-first, review-first, and privacy-conscious.

## Boundaries

This project does not accept changes that add auto-apply, final application submission, login automation, captcha bypass, Cloudflare bypass, proxy-based evasion, or scraping of private/non-public application systems.

Do not commit real resumes, generated resumes, SQLite databases, application records, private job-search notes, API keys, `.env` files, or local config files. Public config and templates must use placeholder/example data only.

## Development Expectations

- Keep new behavior configurable and local-first.
- Add or update tests for new features and bug fixes.
- Use example files for public defaults, and local ignored files for personal data.
- Run `python -B -m pytest` before opening a pull request.
- Run the sample smoke commands when touching setup, scheduling, reporting, or campaign flows.

## Useful Checks

```powershell
python -B -m pytest
python -B -m job_pipeline.setup_wizard --dry-run
python -B -m job_pipeline.scheduler --run-once --sample
python -B -m job_pipeline.campaign --today --dry-run
```