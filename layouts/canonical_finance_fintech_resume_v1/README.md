# canonical_finance_fintech_resume_v1

Frozen finance/fintech one-page resume layout. Approved baseline: Alpaca V4.1 (2026-09-26).

## Freeze policy

- `golden/` holds the approved reference DOCX + PDF and their SHA256SUMS. These files are NEVER overwritten or regenerated. They are the visual regression baseline.
- `LAYOUT_SPEC.yaml` documents every frozen layout attribute.
- `renderer.py` is the ONLY code path allowed to render targeted resumes for finance / fintech / capital markets / data / risk / trading-operations roles. It takes a content dict and applies the frozen layout. Agents must not restyle, resize, recolor, or re-space anything; only content varies per role profile.
- `golden/content_v4_1.json` is the V4.1 content dict used for renderer regression tests.

## Regression rule

If a renderer/layout change produces a visually different result for the same content (compared against `golden/`), that is a REGRESSION — revert, do not ship.

## Content layer

Role profiles (narrative guidance) live in `config/role_profiles.yaml`:
trading_operations, capital_markets_data, data_analytics, risk_operations, technical_operations.
Different profiles change ONLY content, never layout.
