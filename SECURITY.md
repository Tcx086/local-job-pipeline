# Security Policy

Local Job Pipeline handles local job-search data, resume-profile inputs, application notes, reports, and generated files. Treat those artifacts as private.

## Reporting A Vulnerability

Please open a GitHub issue with a minimal, sanitized reproduction. Do not include real resumes, government IDs, exact birth dates, immigration documents, financial data, health data, demographic answers, application records, private job-search notes, API keys, `.env` files, SQLite databases, or generated reports/resumes.

If a report needs examples, use placeholder data and redact local paths or account-specific details.

## Privacy Boundary

This project is a local-first workflow tool. It should not auto-submit applications, automate protected login flows, bypass captchas or Cloudflare, evade rate limits, scrape private data, or store sensitive application answers in public files.