# API contract — The Estimator (v0.1 draft)

Base URL dev: `http://localhost:8000` — all routes under `/api`.
Responses are JSON unless noted. Errors use FastAPI standard `{"detail": "..."}`.

## Data conventions

### Canonical row (used by estimation / replay / learning services)

```json
{
  "project_id": "P012",
  "date": "2025-08-01",
  "actual_days": 42.0,
  "team_estimate": 31.0,
  "features": { "third_party_api": 1, "payment_gateway": 0, "...": 0 }
}
```

`features` keys are the 15 canonical names from `backend/app/features.py` (single source of truth).

### CSV format (`data/synthetic_history.csv`)

Columns (exact order):

```
project_id,date,actual_days,team_estimate,status,is_synthetic,email_text,
feat_third_party_api,feat_payment_gateway,feat_identity_provider,feat_external_data_sync,
feat_data_migration,feat_multi_currency,feat_multi_tenancy,
feat_realtime_ui,feat_mobile_app,feat_offline_mode,
feat_pci_dss,feat_privacy_compliance,feat_audit_logging,
feat_legacy_tech_stack,feat_cross_team_coordination
```

- `actual_days` empty when `status != done`
- `is_synthetic` = 0|1

## Endpoints

### GET /api/health

```json
{ "status": "ok", "model_loaded": true, "llm_provider": "stub|deepseek|gemini|openai", "projects_count": 240 }
```

### POST /api/estimate

Body: `{ "email_text": "..." }`

```json
{
  "project_id": "P241",
  "findings": [
    { "name": "data_migration", "value": 1, "confidence": 0.9, "evidence_quote": "..." },
    { "name": "pci_dss", "value": null, "confidence": 0.2, "evidence_quote": null }
  ],
  "estimate": { "p10": 25, "p50": 38, "p90": 52, "unit": "days", "mode": "calibrated|cold_start" },
  "similar_projects": [
    { "project_id": "P014", "title_hint": "...", "score": 0.82, "actual_days": 40, "shared_features": ["..."] }
  ],
  "questions": [
    { "feature": "pci_dss", "impact_days": 14, "question_vi": "...", "question_en": "..." }
  ],
  "coefficients": [ { "feature": "third_party_api", "multiplier": 1.35, "sample_count": 42 } ],
  "warnings": []
}
```

### POST /api/estimate/stream (SSE)

Same input. Emits `step` events (`extracting → validating → similar → estimating → questions → done`), then a final `result` event (same payload as above), or `error`.

### GET /api/projects?status=&feature=&from=&to=

```json
[ { "project_id": "P012", "date": "2025-08-01", "status": "done",
    "team_estimate": 31, "system_p50": 38, "actual_days": 42, "delta_pct": 10.5,
    "features": { "third_party_api": 1 } } ]
```

### POST /api/projects/{project_id}/actual

Body: `{ "actual_days": 42 }`

Validation per docs/SPEC.md §9: reject `actual_days <= 0` (422); accept `actual_days > 1000` but include a `warning` field ("Giá trị bất thường, vui lòng kiểm tra lại").

```json
{
  "project": { "...updated row..." },
  "coefficient_updates": [ { "feature": "third_party_api", "old": 1.35, "new": 1.41, "sample_count": 43 } ],
  "accuracy": { "mae_before": 9.8, "mae_after": 9.2, "coverage_pct": 80.0 }
}
```

### GET /api/replay?min_train=10

```json
{
  "steps": [ { "i": 12, "project_id": "P012", "p10": 20, "p50": 33, "p90": 48,
               "actual": 42, "mae_system": 8.1, "mae_team": 12.4, "in_interval": true } ],
  "summary": { "mae_system": 9.2, "mae_team": 14.7, "mae_llm_only": 13.1, "coverage_pct": 79.4 }
}
```

### POST /api/ab

Body: `{ "email_text": "...", "n": 10 }`

Runs the same email `n` times through an LLM-only point estimator to expose run-to-run variance (spec §4.5). With the offline stub provider the response is clearly flagged (`mode:"simulated"`).

```json
{ "mode": "real|simulated", "values": [31, 35, 29, "..."], "mean": 33.4, "std": 2.1,
  "min": 29, "max": 38, "system_estimate": 36.0, "delta_pct": -7.2, "note": "..." }
```

### POST /api/import (multipart CSV)

```json
{ "imported": 12, "skipped": 1, "errors": ["row 7: actual_days invalid"] }
```

### GET /api/scenarios

```json
[ { "id": "A", "title": "Fintech payment + PCI", "email_text": "...", "notes": "..." } ]
```

### POST /api/scenarios/{id}/load

Runs a full estimate on a sample scenario (powers the 1-click "Load Sample Data" buttons).

## Notes

- LLM provider is pluggable (deepseek | gemini | openai | stub). Without an API key the app runs with `stub` and must say so in the UI (`llm_provider` in /api/health).
- Everything must work with zero network access (offline demo mode).

## Contract additions v0.2 (2026-10-16)

### POST /api/estimate — optional answers + Monte Carlo intervals

Body may include an optional override map:

```json
{ "email_text": "...", "answers": { "pci_dss": 1, "offline_mode": 0 } }
```

`answers` set previously-unknown features (powers the interactive "answer a question → interval shrinks" flow; the frontend just re-calls this endpoint with accumulated answers). Persistence rule: a new project row (P0nn) is only created for a direct estimate call **without** `answers`; answer-refinement calls are side-effect free.

`estimate` gains a `method` field: `"mc"` when unknown features remain (interval sampled from historical feature prevalence — more unknowns ⇒ honestly wider range) or `"point"` when the vector is fully known / cold start.

### POST /api/reset

Reseeds the demo database to the pristine synthetic history (retrains model + refreshes replay cache). Frame in the UI as "Reset demo data".

```json
{ "status": "ok", "projects_count": 240 }
```

### POST /api/packages

Body: `{ "email_text": "...", "budget_days": 30 }`

```json
{
  "budget_days": 30,
  "packages": [
    { "tier": "core", "label": "Essential",
      "estimate": { "p10": 21, "p50": 29, "p90": 44, "mode": "calibrated", "unit": "days", "method": "mc" },
      "over_budget_prob": 0.34,
      "features_included": { "third_party_api": 1, "...": null },
      "excluded": ["offline_mode", "mobile_app"],
      "notes": "phased scope: drop the most expensive optional capabilities" },
    { "tier": "standard", "label": "Standard", "...": "..." },
    { "tier": "full", "label": "Full scope", "...": "..." }
  ],
  "recommendation": "standard",
  "method": "mc"
}
```

Tiers differ by which optional capabilities are phased out (`excluded`); `over_budget_prob` = P(actual days > budget) under the tier's predictive distribution. Deterministic (seeded MC).

### POST /api/ab — third baseline (LLM with history)

Response keeps all existing fields and adds:

```json
{ "baseline_history": { "values": [37, 41, 39], "mean": 39.0, "std": 2.0, "n": 3, "mode": "real|simulated" } }
```

`baseline_history` = the same email run through an LLM whose prompt includes the most recent finished projects (features + actual days), i.e. the fair "LLM + company history" strawman judges will ask about.
