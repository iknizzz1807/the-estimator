# TAWOS cross-dataset validation (bonus experiment, 2026-10-16)

**TL;DR — negative result, reported as-is.** The product's estimation math (Ridge on
log(target) + split-conformal P10/P90, `backend/app/services/estimation.py` — unmodified)
was run on **5,850 real Jira issues from 39 TAWOS projects** with story points in the
target slot and features extracted offline by the `StubProvider`. Cross-project
(coverage: unseen projects in test) **R² = -0.021, MAE = 2.48 SP**, i.e. the model
**ties the global-median baseline (2.48 SP) and does not beat it**. We found **no
evidence of learning or generalization on this real data** under the offline stub
extractor. Details and caveats below; nothing here was tuned to make the numbers nicer.

## 1. Dataset, provenance, license

- Source: **TAWOS v1.1** — Tawosi, Al-Subaihin, Moussa, Sarro, *"A Versatile Dataset of
  Agile Open Source Software Projects"*, MSR 2022. Official record:
  <https://doi.org/10.5522/04/21308124> (UCL RDR, `TAWOS.sql.zip`, 637.6 MB MySQL dump).
  **License: Apache-2.0** (figshare record; the TAWOS README terms of use request
  research use — attribution kept in `data/tawos_README.txt`).
- Mirror actually used: <https://github.com/barkhahbpp/tawosdataset> — 39 per-project
  CSVs exported from the official dump (columns: `Title, Description, Story_Point,
  Type, Priority, Status, Creation_Date, Estimation_Date`). The official dump download
  was aborted after ~35 min at ~75 KB/s (est. >2 h); spot-checks of the mirror match the
  official Issue schema, but it is third-party and was not diffed against the full dump.
- Row counts: 65,427 mirror rows → 63,011 with `Story_Point > 0` + non-empty text →
  **62,171** after dropping 699 entries with SP < 0.5 (sub-day noise) and 141 with
  SP > 100 (up to 26,710,114 — clearly bad entries) → deterministic cap of 150
  rows/project (sorted by `Creation_Date`, evenly spaced) → **5,850 rows / 39 projects**,
  committed as `data/tawos_subset.csv` (3.3 MB; every project contributes 150 rows).
- Column mapping: `story_id = "<csv-stem>:<source row>"`, `project_id = csv stem`,
  `description = Title + " " + Description` (whitespace-collapsed, truncated to 2,000
  chars), `story_points = Story_Point`. Full notes: `data/tawos_README.txt`.
- Issue-type mix of the eligible rows: Story 33%, Bug 29%, Improvement 11%, Task 11%,
  others 16% — TAWOS attaches story points to all issue types, not only to Stories.
- SP distribution in the subset: min 0.5 · P25 1 · median 3 · P75 5 · P90 8 · P99 21 ·
  max 100 (mean 4.00) — heavy-tailed; ~55% of labels are below the app's 3.0 floor.

## 2. Method (exactly what was run)

- **Features:** `StubProvider.extract_findings(description)`; `value == 1` → 1.0,
  everything else (0/None) → 0.0. No LLM calls — the stub's under-coverage of domain
  vocabulary is part of what this experiment measures.
- **Model:** `train_model` / `estimate` unchanged; story points passed as `actual_days`
  (only the unit label changes — everything is fit in log space). Conformal quantiles
  come from in-training out-of-fold residuals (`KFold(shuffle=False)`).
- **Splits:** (a) random 5-fold CV, seeded `np.random.RandomState(42)`; (b)
  **cross-project `GroupKFold(5)` on `project_id`** — test projects are never seen in
  training (the primary cross-dataset claim); (c) baselines on the same test rows:
  global **mean** and **median** of the *training* story points.
- **Metrics:** MAE / RMSE / median |error| in story points; **R² in story-point space**;
  empirical coverage of the API's [P10, P90] output. Diagnostic (clearly not the product
  output): the same conformal outputs with the 3.0 "person-day" floor removed.
- **Variants:** all 15 features vs "TAWOS-adapted" (only features firing in ≥3% of rows;
  SPEC §5.5 permits a reduced set for TAWOS).
- **Command:** `cd backend && PYTHONPATH=. /root/venvs/estimator/bin/python scripts/tawos_validation.py`
  — reruns are byte-identical (numpy 2.5.4, scikit-learn 1.9.1).

## 3. Results

### 3.1 StubProvider prevalence (n = 5,850; 1,307 rows — 22.34% — fire ≥1 feature)

| feature | count | prev. | feature | count | prev. | feature | count | prev. |
|---|---|---|---|---|---|---|---|---|
| third_party_api | 601 | 10.27% | mobile_app | 314 | 5.37% | audit_logging | 99 | 1.69% |
| identity_provider | 204 | 3.49% | external_data_sync | 91 | 1.56% | data_migration | 79 | 1.35% |
| payment_gateway | 45 | 0.77% | legacy_tech_stack | 27 | 0.46% | offline_mode | 16 | 0.27% |
| realtime_ui | 12 | 0.21% | cross_team_coordination | 7 | 0.12% | multi_tenancy | 3 | 0.05% |
| privacy_compliance | 2 | 0.03% | multi_currency | 1 | 0.02% | pci_dss | 0 | 0.00% |

Adapted set (≥3%): `third_party_api`, `identity_provider`, `mobile_app`.

### 3.2 Random 5-fold CV (all 15 features)

| fold | n_test | MAE | RMSE | R² | cov [P10,P90] | base mean MAE | base median MAE |
|---|---|---|---|---|---|---|---|
| 1 | 1170 | 2.670 | 7.164 | -0.023 | 0.492 | 2.951 | 2.670 |
| 2 | 1170 | 2.307 | 4.361 | -0.015 | 0.489 | 2.631 | 2.309 |
| 3 | 1170 | 2.462 | 6.091 | -0.022 | 0.483 | 2.785 | 2.463 |
| 4 | 1170 | 2.463 | 6.445 | -0.020 | 0.485 | 2.774 | 2.459 |
| 5 | 1170 | 2.492 | 6.662 | -0.018 | 0.474 | 2.836 | 2.486 |
| **all** | **5850** | **2.479** | **6.219** | **-0.020** | **0.484** | **2.796** | **2.477** |

Median |error| = 2.00 SP. Diagnostic without the 3.0 floor: MAE 2.479, R² -0.028,
coverage 0.911; the P50 would hit the 3.0 floor on 84.4% of test rows.

### 3.3 Cross-project GroupKFold(5) — primary claim (per fold: 7–8 unseen projects)

| fold | n_test | MAE | RMSE | R² | cov [P10,P90] | base mean MAE | base median MAE |
|---|---|---|---|---|---|---|---|
| 1 | 1200 | 1.957 | 3.569 | -0.026 | 0.555 | 2.235 | 1.971 |
| 2 | 1200 | 2.432 | 4.401 | -0.090 | 0.590 | 2.542 | 2.441 |
| 3 | 1200 | 3.221 | 9.442 | -0.033 | 0.468 | 3.431 | 3.196 |
| 4 | 1200 | 2.870 | 7.580 | -0.015 | 0.390 | 3.270 | 2.865 |
| 5 | 1050 | 1.854 | 3.394 | -0.004 | 0.411 | 2.548 | 1.833 |
| **all** | **5850** | **2.482** | **6.223** | **-0.021** | **0.485** | **2.812** | **2.477** |

Median |error| = 2.00 SP. Diagnostic without the 3.0 floor: MAE 2.509, R² -0.037,
coverage 0.912; floor binds on 86.9% of test rows. **Verdict:** the model beats the
global-mean baseline by 0.33 SP, **ties/slightly loses to the global-median baseline**
(+0.005 SP worse), and has **negative R²** — it is worse than predicting the test mean.

### 3.4 TAWOS-adapted variant (3 features)

| evaluation | MAE | RMSE | R² | coverage | (no-floor cov) |
|---|---|---|---|---|---|
| random 5-fold CV | 2.478 | 6.223 | -0.021 | 0.485 | 0.915 |
| cross-project | 2.482 | 6.229 | -0.023 | 0.486 | 0.916 |

Per-fold cross-project R²: -0.027, -0.097, -0.034, -0.017, 0.000 — same picture:
the adaptation changes nothing; all signal comes from the intercept.

## 4. Honest limitations

1. **Stub extractor ≠ LLM.** The offline keyword stub fires on only 22% of rows and
   ≥3% prevalence for just 3/15 features — Jira bug-report vocabulary is not RFP
   vocabulary ("api" as a substring-ish token, no business features like payments/PCI).
   With a real LLM extractor the prevalence (and possibly the signal) would differ;
   this experiment measures the *offline* configuration honestly.
2. **Story point ≠ person-day.** SP labels are ordinal-ish team-relative units; pooling
   them across 39 projects mixes different scales (median 3 SP, heavy tail). The math
   is unit-agnostic but MAE/R² in SP are not comparable to the demo's day-based numbers.
3. **3.0-day floor is meant for days, not SP.** It makes predictions nearly constant
   (floor binds on ~85–87% of test rows) and flattens coverage to ~48.5% — far below
   the 75–85% target. Without the floor, coverage is ~91%: the interval math itself is
   not plainly broken, but it is miscalibrated for this scale, and R² stays ≈0 either way.
4. **Domain shift / no personalization.** TAWOS projects are open-source issue trackers;
   the product targets client RFP projects. Cross-project transfer of story-point
   estimates is known to be hard (per-project velocity differs systematically).
5. **Data hygiene.** Third-party CSV mirror (not the official dump); 0.5–100 SP filter
   drops 1.3% of rows; 150 rows/project evenly-spaced sampling; 2,000-char description
   truncation — all deterministic and documented in `data/tawos_README.txt`.
6. **Baselines are strong by nature here.** For heavy-tailed counts, the constant
   median predictor is a hard baseline; "ties median" is the truthful summary.

## 5. Conclusion (no spin)

1. On real TAWOS data the pipeline **runs end-to-end, deterministically, and returns
   calibrated-looking ranges — but shows no evidence of learning**: cross-project
   R² = -0.021, MAE ties the global-median baseline, and only ~22% of stories produce
   any feature signal with the offline stub.
2. The two concrete defects exposed are (a) the keyword stub's domain-vocabulary gap
   and (b) the 3.0 person-day floor + day-calibrated conformal bands being invalid for
   story-point space (~48% floored coverage vs the 75–85% target).
3. Claim to keep: the estimation math is unit-agnostic and robust to running on foreign
   data, but **cross-dataset validity on TAWOS is NOT demonstrated** — a real LLM
   extractor and story-point-scale calibration would be the minimum next steps.
