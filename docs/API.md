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
  "steps": [ { "i": 12, "project_id": "P013", "p10": 20.9, "p50": 40.4, "p90": 53.7,
               "actual": 34.0, "mae_system": 21.0, "mae_team": 5.33, "in_interval": true } ],
  "summary": { "mae_system": 17.36, "mae_team": 32.93, "mae_llm_only": 20.81, "coverage_pct": 86.7 }
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

Each response also includes a top-level `pricing` block computed from the Full-scope interval via a lognormal fit of the conformal interval — this powers the interactive **pricing curve** (quote days → overrun risk + implied margin):

```json
{ "pricing": {
    "scope": "full",
    "p10": 87.3, "p50": 138.0, "p90": 248.2,
    "curve": [ { "days": 60.0, "over_prob": 0.42 }, "…~25 log-spaced points…" ],
    "safe_quote_25": 154.3,
    "safe_quote_10": 208.7
} }
```

- `curve[].over_prob` = P(actual days > quote days) — same lognormal model as `over_budget_prob` (so at `days == budget`, the Full-tier numbers must agree).
- `safe_quote_25` / `safe_quote_10` = smallest quote such that P(overrun) ≤ 25% / 10% respectively.
- Implied margin at a quote = `(quote − p50) / p50` (display + tooltip only; no extra API field needed).

### POST /api/estimate — optional codebase context (Codebase Lab)

Body may include `"repo": "demo_a" | "demo_b" | "self"` — the two built-in demo repos (plugin-pattern vs spaghetti, generated on demand into `data/demo_repos/`, gitignored) or the server's own checkout. When present, the response gains a `codebase` block (all other keys unchanged; the top-level `estimate` becomes the ADJUSTED estimate):

```json
{ "codebase": {
    "repo": "demo_b",
    "language": { "dominant": "Python", "python_files": 8, "source_files": 8, "python_share": 1.0 },
    "friction": { "score": 0.3958, "level": "medium", "components": { "churn": 0.0, "fan_in": 0.875, "complexity": 0.75, "coverage_gap": null, "author_concentration": 0.0 } },
    "invasiveness": { "modified_ratio": 0.8571, "mean_files_touched": 5.44, "based_on_commits": 9 },
    "similar_changes": [ { "commit": "e1d1767", "date": "2026-03-10", "files_touched": 6, "new_files": 0, "modified_files": 6 } ],
    "base_estimate": { "p10": 113.9, "p50": 207.3, "p90": 444.3, "mode": "calibrated", "unit": "days", "method": "mc" },
    "adjusted_estimate": { "p10": 100.4, "p50": 269.5, "p90": 549.8, "mode": "calibrated", "unit": "days", "method": "mc" },
    "adjustments": [ { "what": "p90 (upper tail)", "factor": 1.2375, "why": "friction widens the interval upward; median untouched (friction level medium, score 0.3958)" } ],
    "note": "DEMO-ASSUMED coefficients; the similar-past-changes mechanism is validated on 29k real commits (docs/CODEBASE_HISTORY_VALIDATION.md); no text-prediction accuracy claim (docs/CODEBASE_VALIDATION.md). One-directional by design: surcharge only, never a discount."
} }
```

(Example values: live `demo_b` response for the scenario A email, measured 2026-10-17.)

- Keywords for `find_similar_changes` are derived from the extracted features (documented mapping in the API layer).
- Unknown `repo` value → 422; `repo` absent → response unchanged (backward compatible). Persistence rule unchanged.
- **Python-only scope (DECISIONS D24)**: `fan_in` (import scan) and `complexity` (radon) are Python signals, so a repository whose primary source language is not Python is **refused** rather than mis-scored — the estimate still returns 200 with a `codebase_error` explaining it (e.g. *"repo này chủ yếu là C: 2/117 file nguồn là .py"*). Multi-language support is a stated later feature. The `language` field in the block always shows the analysed scope.

### POST /api/estimate — pasted public repo URL (contract addition)

`repo` also accepts a **public GitHub repository** instead of the built-in ids:

```
"repo": "https://github.com/pallets/flask"     # or the shorthand "pallets/flask"
```

The server canonicalises it to `gh:<owner>/<repo>`, clones it once into a cache
(`data/repo_cache/`, gitignored) and analyses it like any other repo. Response
shape is unchanged (`codebase.repo` is the canonical id).

**Acceptance is deliberately narrow (security).** Only `github.com/<owner>/<repo>`
is accepted — optionally with the `https://` scheme, a trailing `.git` or `/`.
Any other host, scheme, port, userinfo, query or fragment → **422** (this is what
keeps a public, unauthenticated endpoint from becoming an SSRF proxy). The clone
itself is hardened: `GIT_TERMINAL_PROMPT=0` (never hang on credentials),
`http.followRedirects=false`, `--no-recurse-submodules`, `--single-branch`, a
wall-clock timeout (180 s), a post-clone size cap (300 MB) and an LRU cap on the
cache (6 repos). **A full clone is required, not `--filter=blob:none`**:
`find_similar_changes` runs `git log --raw --numstat`, and numstat needs blob
contents, so a blobless clone re-fetches every commit over the network
(measured: 221 s for a 2.3k-commit repo vs ~1 s for a full clone).

### `codebase_error` — a repository problem is never fatal

When the repository cannot be analysed (missing `.git`, clone failed, too large),
the response is still **200**: the estimate is returned unchanged, `codebase` is
absent and the payload carries

```json
{ "codebase_error": "Repo 'self' không phải là git repository (thiếu .git) — ..." }
```

The estimate does not depend on the repository, so a codebase failure must never
cost the user their numbers (DECISIONS D20).

### GET /api/health — Codebase Lab capabilities

Adds a non-contract extra so the UI never offers an option the host cannot serve
(cloud images ship no `.git` — DECISIONS D17; examples are only listed when the
build-time fetch succeeded — D23):

```json
{ "codebase": {
    "choices": ["demo_a", "demo_b", "self"],
    "self_available": true,
    "url_clone": true,
    "examples": [
      { "id": "ex_flask", "repo": "pallets/flask", "label": "Flask",
        "lang": "Python", "kind": "web framework", "pinned_date": "2026-10-07" }
    ] } }
```

`codebase.examples` entries are pre-cloned public repos; sending one as `repo`
(`"repo": "ex_flask"`) returns an instant result — no clone at request time and
no URL to paste. They are analysed by the same live path as a pasted repo, and
the analysis is pinned to `pinned_date` so friction never drifts.

### POST /api/ab — third baseline (LLM with history)

Response keeps all existing fields and adds:

```json
{ "baseline_history": { "values": [37, 41, 39], "mean": 39.0, "std": 2.0, "n": 3, "mode": "real|simulated" } }
```

`baseline_history` = the same email run through an LLM whose prompt includes the most recent finished projects (features + actual days), i.e. the fair "LLM + company history" strawman judges will ask about.
