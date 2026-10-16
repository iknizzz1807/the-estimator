# Itemlet project-level validation (real absolute effort, 2026-10-17)

**TL;DR — inconclusive overall, two clear halves.** The estimation math (Ridge(alpha=0.3) on log(target) + split-conformal P10/P90 with the x1.10 tail widening, mirrored from `backend/app/services/estimation.py`) was run on **114 real open-source projects** with **absolute effort in logged hours** (Itemlet, Zenodo 10.5281/zenodo.19411554, CC-BY-4.0). **Interval calibration generalizes**: coverage 76.3–86.0% vs the 75–85% target in every configuration. **Point estimates generalize only where targets are trustworthy** (logging coverage ≥ 10%, n=37: domain-holdout R²=0.364, MAE 8,649h beats global-mean 14,252h / global-median 10,200h). On the full 114-project set there is **no signal** (domain-holdout R²=-0.023, MAE ties the global median). The binding constraint is data quality, not the estimator. Nothing was tuned for nicer numbers.

## 1. Dataset, provenance, license

- **Itemlet** ("A Multi-project, Multi-domain, and Feature-engineered Dataset for Empirical Software Engineering", Zenodo record 19411554, <https://doi.org/10.5281/zenodo.19411554>): 727,282 Jira issues from 204 open-source projects across 19 domains; absolute effort (`Total Time Logged (hours)`, from worklogs) + 108 engineered columns. **CC-BY-4.0**; attribution + full md5 list in `data/itemlet_README.txt`.
- All Zenodo API downloads **md5-verified** 2026-10-16: `project_summary.csv` f8f4cf3f…, `project_domain.csv` 3a49d083…, `data_dictionary.csv` e62d3884…, `itemlet_dataset.parquet` (107,856,639 B) **e80d4f6b521d5ace92c039fb49325480**. Parquet download ~9 min at ~200 KB/s — under the 15-min budget, **no CSV fallback needed**. Verified 727,282 rows × 108 cols; issue counts summary vs parquet: **0 mismatches**.

## 2. Schema findings (effort / domain / text)

- Effort: `Total Time Logged (hours)` (target), `worklog_total` (s), `Cycle Time (hours)`, `story_points` (66.5% null), `workratio`. Text: `issue_summary` (no `description`) + text-derived `has_technical_terms`, `mentions_external`. Domain: only in `project_summary.csv`/`project_domain.csv`.
- **Logging reality (central caveat):** only **6.5% of all 727,282 issues** have any logged time; **90/204 projects have zero**; among the 114 usable, coverage is median **3.2%**. v1.0 dictionary notes `Completion Time (hours)` is a derivation error (identical to Cycle Time) — not used.

## 3. Project-level dataset (target + features)

- 204 rows committed; validation uses the **114 with `target_hours > 0`** (zero-logged projects have no absolute-effort target — mirrors the product's `actual_days > 0` rule). Target = sum of logged hours: min 0.5 · P25 44.5 · median 249 · P75 1,826.7 · P90 7,914 · max 225,695.5 · mean 5,990.6 h (person-days ÷8: median 31.1, max 28,211.9 — conversion label, not a claim). Alternates: issue counts (median 1,851); median per-issue hours ≈ 0h (§2).
- **15 features** (deterministic; heavy-tailed ones log1p'd): `log_issue_count`, `story_point_coverage_pct`, `median_story_points`, `resolved_share`, `log_sprint_count`, `has_sprint_data`, `log_median_cycle_time_h`, `log_span_months`, `bug_share`, `story_share`, `log_mean_total_days`, `assignees_per_100_issues`, `log_mean_comment_count`, `has_technical_terms_share`, `high_priority_share`.
- Deliberately **excluded** any logged-time aggregate as a feature: `sum = n_logged × mean_logged` reconstructs the target mechanically; that identity is shown separately as a labeled **leakage diagnostic** (§5) to prove the pipeline learns when a real signal exists.

## 4. Method (exactly what was run)

- **Math mirror** of `estimation.py` (not `train_model`, which hardcodes the 15 binary RFP features): Ridge(alpha=0.3) on log(hours); out-of-fold conformal residual quantiles via `KFold(shuffle=False)` + verbatim finite-sample `"higher"` quantile + x1.10 tail widening; P50/P10/P90 = `exp(log_pred + q)`. One documented adaptation: features z-scored with **train-fold** statistics (binary features never needed it; without it alpha=0.3 is meaningless at these scales). The 3.0 floor mirror never binds.
- **Splits:** (a) random 5-fold CV (seeded shuffle, seed 42); (b) **domain-holdout GroupKFold(5)** — whole domains unseen in training (primary test). Baselines on the same test rows: global mean, global median, per-domain mean (unseen domains → global mean; 100% unseen in (b)).
- **Metrics:** MAE hours + person-days (÷8), R² hours, R² log (secondary — the model optimizes log error on a heavy-tailed target), coverage vs 75–85%.
- Command: `cd backend && PYTHONPATH=. /root/venvs/estimator/bin/python scripts/itemlet_validation.py` (rebuild: `--build`; math checks: `--self-test`). **Two full runs byte-identical** (md5 1cf2e04d…), rebuild md5-identical; `pytest tests/ -q`: **165 passed**.

## 5. Results

Random 5-fold CV and domain-holdout, same model/features, n=114 (aggregate rows in bold; baseline MAE columns are hours):

| eval | fold | n_test | MAE h | MAE d(÷8) | R² | R²log | cov | base mean h | base med h |
|---|---|---|---|---|---|---|---|---|---|
| random CV | 1 | 23 | 4,425.8 | 553.2 | -0.046 | -0.396 | 0.652 | 7,457.7 | 4,569.2 |
| random CV | 2 | 23 | 11,225.8 | 1,403.2 | -0.021 | 0.092 | 0.826 | 13,287.4 | 11,378.4 |
| random CV | 3 | 23 | 1,746.4 | 218.3 | -0.172 | -0.129 | 0.913 | 5,999.7 | 1,348.9 |
| random CV | 4 | 23 | 4,019.2 | 502.4 | 0.358 | 0.287 | 0.957 | 8,655.3 | 5,680.2 |
| random CV | 5 | 22 | 6,693.7 | 836.7 | -0.013 | 0.020 | 0.955 | 10,136.3 | 6,699.5 |
| **random CV** | **all** | **114** | **5,612.8** | **701.6** | **0.016** | **-0.027** | **0.860** | **9,098.2** | **5,928.5** |
| domain-holdout | 1 | 23 | 1,887.1 | 235.9 | -0.376 | -1.058 | 0.913 | 5,972.1 | 1,648.0 |
| domain-holdout | 2 | 23 | 1,148.3 | 143.5 | 0.393 | -0.746 | 0.870 | 6,451.7 | 892.3 |
| domain-holdout | 3 | 23 | 16,906.3 | 2,113.3 | -0.096 | -0.099 | 0.696 | 16,928.5 | 16,355.2 |
| domain-holdout | 4 | 23 | 6,688.2 | 836.0 | -0.025 | -0.544 | 0.913 | 9,447.8 | 6,771.5 |
| domain-holdout | 5 | 22 | 3,935.0 | 491.9 | -0.033 | -0.477 | 0.409 | 7,993.3 | 3,945.2 |
| **domain-holdout** | **all** | **114** | **6,132.1** | **766.5** | **-0.023** | **-0.358** | **0.763** | **9,370.7** | **5,939.8** |

Random CV: median |error| 546.4h, RMSE 24,895.7h — R²≈0, beats global mean, just edges global median: no real signal. Domain-holdout (primary; folds hold out 3–4 whole domains each): median |error| 908.6h, RMSE 25,384.2h, per-domain-mean baseline = global mean (100% unseen domains) — beats global mean by 3.2k MAE, **ties/slightly loses to the global median (+192h)**, negative R²: **no evidence of learning on the full noisy set**.

**Sensitivity — logging-coverage filter (target validity; rCV=random CV, DH=domain-holdout):**

| set | n | rCV MAE h | R² | R²log | cov | rCV baselines mean/med/dom h | DH MAE h | R² | R²log | cov | DH baselines mean/med h |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cov ≥ 5% | 48 | 3,818.9 | 0.818 | 0.511 | 0.833 | 11,790/8,153/12,759 | 25,497.1 | -46.9* | 0.457 | 0.833 | 11,909/8,154 |
| cov ≥ 10% | 37 | 5,144.2 | 0.712 | 0.544 | 0.838 | 13,840/9,914/14,640 | 8,649.3 | 0.364 | 0.064 | 0.838 | 14,252/10,200 |

\* one held-out fold (9 projects) contains a 126k-hour project missed by ~100k h. On **trustworthy targets the model beats all three baselines in random CV and both global baselines across unseen domains** (≥10%: 8,649h vs 14,252h/10,200h), but log-space R² is near zero (0.064) — the signal is mostly level/scale, not precise ranking. **Leakage diagnostic** (NOT a fair test; target components as features): R²=1.000, MAE=48.2h, cov=0.939 — the pipeline learns when a true signal exists.

**Text diagnostic** (StubProvider on 8,160 summaries, ≤40/project): per-project shares of summaries firing each keyword feature are tiny (largest: `third_party_api` 4.2%, `payment_gateway` 1.3%, `identity_provider` 1.2%; `pci_dss`/`cross_team_coordination` 0%). Strongest Spearman rho vs log(target): +0.175 (`identity_provider`, p=0.063) — **below the pre-set |rho| ≥ 0.25 bar, so text shares were not added to the model**. Honest note: adding the 13 rare z-scored shares was tried and destabilized the Ridge numerically (rare feature → huge z-score → exp() blow-up) — itself evidence of no usable signal at n=114.

## 6. Comparison vs TAWOS (why this is the fairer test)

| | TAWOS (2026-10-16) | Itemlet (this run) |
|---|---|---|
| Target | story points (ordinal, team-relative) | **absolute logged hours** |
| Unit | individual stories | **projects (RFP-like unit)** |
| Features | 15 binary, offline keyword stub | 15 project aggregates, engineered |
| Cross-domain test | GroupKFold on project | **GroupKFold holding out domains** |
| Cross-domain R² | -0.021 | -0.023 (n=114) / **+0.364 (n=37, cov≥10%)** |
| Coverage vs 75–85% | 48.5% (floor broken in SP space) | **76.3–86.0% in every config** |

TAWOS's negative was partly structural (SP ≠ effort, stories ≠ projects, ~22% stub coverage, 3-day floor invalid in SP space). Itemlet removes those confounds: same weak-negative headline on the full set, but the interval math now calibrates as designed, and the trustworthy-target subset shows the first positive point-estimate signal in a cross-dataset test.

## 7. Honest limitations

1. **Project-level aggregation is a proxy for RFP-level estimation**: Jira project totals include bugfix/maintenance work; an RFP's scope is not a Jira project.
2. **Logging coverage is the dominant noise source**: 6.5% of issues logged, 90/204 projects empty, usable-set coverage median 3.2% — total logged hours is a lower bound and a poor proxy for low-coverage projects. n=37 is where this validation is most defensible.
3. **Engineered features ≠ the product's 15 text features**: this validates the *math* (log-Ridge + conformal + coverage), not the extraction pipeline; §5 shows the offline stub carries no signal on Jira summaries.
4. **Open-source Jira ≠ B2B SaaS RFP work**: CMS/library-heavy domain mix, volunteer teams, no client deadlines.
5. **Small n, heavy tail**: 114/48/37 rows; max target 226k h from an 0.25%-coverage logging artifact; hours-space R² is dominated by single large projects — log-space metrics are the robust view.
6. **Adaptations**: train-fold z-scoring and log1p of heavy-tailed features were necessary for continuous inputs; both documented and leakage-free.

## 8. Decision statement (no spin)

On real absolute-effort data, at project level, the estimation math shows: **no point-estimate generalization on the full valid set** (domain-holdout n=114: R²=-0.023, MAE 6,132h ties the global-median baseline 5,940h); **weak positive evidence where targets are trustworthy** (cov ≥ 10%, n=37: domain-holdout R²=0.364, MAE 8,649h vs 14,252h/10,200h baselines, but log-space R²=0.064); and **calibrated conformal intervals** on real data (coverage 76.3–86.0% across all configurations vs the 75–85% target — the TAWOS 48.5% failure does not reproduce). Overall: **INCONCLUSIVE — negative on the full noisy set, weak-positive on the clean subset, positive for calibration.** The estimator is not the binding constraint; target data quality is. Claim to keep: the estimation math runs deterministically on real absolute-effort data, its intervals are honest, and it beats constant baselines exactly to the extent that effort logging is trustworthy.
