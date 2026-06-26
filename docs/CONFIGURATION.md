# Configuration

Tracked examples live in `config/*.example.yaml`, `templates/master_resume.example.yaml`, and `templates/resume_profiles/*.example.yaml`.

Local ignored files are created by the setup wizard:

```text
config/search_scope.yaml
config/application_campaign.local.yaml
config/apply_profile.local.yaml
config/resume_profile_paths.local.yaml
config/scoring_rules.local.yaml
templates/master_resume.yaml
templates/resume_profiles/*.local.yaml
```

## Search Scope

`config/search_scope.yaml` controls job boards, countries, locations, role keywords, and simple include/exclude filters. The scheduler loads the local file first and falls back to `config/search_scope.example.yaml` for safe sample behavior.

Validation requires at least one enabled country, at least one location and search term per enabled country, positive `results_wanted`, positive `sleep_seconds`, and a supported site name.

## Campaign

`config/application_campaign.local.yaml` controls daily quotas, score thresholds, company priority lists, and whether manual resume or answer-pack generation is enabled.

## Resume Paths

`config/resume_profile_paths.local.yaml` points each profile to a YAML source and optional local DOCX/PDF resume files. Generated files should stay under `data/` or another ignored local folder.
