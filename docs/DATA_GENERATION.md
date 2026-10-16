# Synthetic data generation — The Estimator

Deterministic recipe for `data/synthetic_history.csv` + validation-only
`data/ground_truth.json` (the estimator never reads the latter). Generator:
`python -m app.data_gen.generate_history` (defaults: 60 projects, seed 42).
P001–P052 done, P053–P060 open; dates 2024-10-10 … 2026-10-10; same seed ⇒
byte-identical outputs.

## Hidden effort model (actual_days)

    expected    = 15.0 × Π main_coefficient[f] (present)
                       × Π interaction_multiplier[(a,b)] (both present)
                       × drift_factor(date) × outlier_shock(project)
    actual_days = round(max(5, expected × lognormal(σ=0.18)))

| feature                 | main coef | P(present) |
|-------------------------|-----------|------------|
| third_party_api         | 1.35      | 0.45       |
| payment_gateway         | 1.45      | 0.25       |
| identity_provider       | 1.25      | 0.25       |
| external_data_sync      | 1.30      | 0.30       |
| data_migration          | 1.60      | 0.30       |
| multi_currency          | 1.15      | 0.15       |
| multi_tenancy           | 1.50      | 0.20       |
| realtime_ui             | 1.30      | 0.25       |
| mobile_app              | 1.55      | 0.25       |
| offline_mode            | 1.25      | 0.20       |
| pci_dss                 | 1.40      | 0.20       |
| privacy_compliance      | 1.35      | 0.25       |
| audit_logging           | 1.20      | 0.20       |
| legacy_tech_stack       | 1.45      | 0.20       |
| cross_team_coordination | 1.25      | 0.25       |

Interactions (extra joint multipliers; small enough that the Ridge learning
loop recovers every main effect within 20% on n=52, worst 18.1% = pci_dss):

| pair                                | multiplier |
|-------------------------------------|------------|
| payment_gateway & pci_dss           | 1.15       |
| mobile_app & offline_mode           | 1.10       |
| data_migration & legacy_tech_stack  | 1.12       |

Drift — from **2026-02-01** actual effort × **1.22** (company grew, heavier
scope); 13/52 done projects are post-switch. The team formula ignores drift,
so post-drift team estimates degrade while the walk-forward model re-learns
(last 10 replay steps: system MAE 15.7 vs team MAE 33.3 days; coverage 83%).

Outliers — seeded choice of **3 projects (5% of 60)**, U[2.0, 3.0]:
P012 ×2.75, P021 ×2.91, P034 ×2.35 (dedicated `"{seed}:outliers"` RNG, so
tuning outliers never shifts the main stream).

## Team estimate (the optimist under test)

    team = round(max(5, 15.0 × Π team_coefficient[f] × 0.75 × lognormal(σ=0.08)))
    team_coefficient = main table except third_party_api 1.35^0.5 = 1.162 and
                       data_migration 1.60^0.6 = 1.325 (blind spots)

No interactions, drift or outlier knowledge; mean team/actual ratio on the
done projects is 0.62 (0.59 with third_party_api vs 0.64 without).

## Emails, omissions, negations

One client email per project, 120–350 words, keyword-rich sentences per
present feature (`email_writer.py`). ~30% of projects omit 1–2 present
features; ~8% of absent features are explicitly negated; mix ~70% EN / 15%
VI / 15% mixed (VI keeps the EN keyword). Features are drawn independently —
no co-occurrence structure is injected; joint effects must be learned.

## Ground truth blocks (validation only)

`interaction_multipliers` `[{features: [a, b], multiplier}]`, `drift`
`{switch_date: "2026-02-01", factor: 1.22}`, `outliers` `{project_id: shock}`,
plus per-project `interaction_multiplier`, `drift_factor`, `outlier_shock`.
`backend/tests/test_data_gen.py` covers byte determinism, CSV schema, team
bias, omission/negation rates, drift direction + magnitude, outlier rate,
interaction uplift (6-seed pool) and main-effect recoverability.
## Checksums (seed 42)

    data/synthetic_history.csv  sha1 e9e0a0969febbbdaa2ff84b6ff7b649bc2bbf5be
    data/ground_truth.json      sha1 7700d6d74b078cc6dc084e74f9cfc320b35247b7
