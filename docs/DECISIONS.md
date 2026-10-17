# Decision log — The Estimator

Short entries, newest last. One paragraph per decision: what, why, what we gave up.

## D1 — Stack: FastAPI + SQLite + Next.js 15 (2026-10-16)

Chosen per docs/SPEC.md §8.3 and checklist Phase 0 defaults: FastAPI + SQLite backend, Next.js 15 + TailwindCSS frontend, deploy Vercel + Render. Trade-off: Next.js adds build weight on-device, but maximizes familiarity and deployment options.

## D2 — LLM provider: Gemini Flash by default, pluggable + offline stub (2026-10-16)

No API key available during the build, so the extraction service is provider-agnostic (gemini | openai | stub). The `stub` provider is a deterministic rule-based extractor so tests, replay and demos run with zero network. Real Gemini calls activate as soon as `GEMINI_API_KEY` is set. Trade-off: stub quality < real LLM, must be disclosed in UI/README.

## D3 — No sentence-transformers / torch (2026-10-16)

The spec suggested sentence-transformers for similar-project retrieval. Installing torch (~GBs) on an Android proot is slow and fragile, so similarity uses a hybrid of BM25 + TF-IDF cosine + rapidfuzz (no torch). Trade-off: slightly weaker semantic matching; acceptable for demo, documented as a limitation. Embeddings can be swapped in later behind the same interface.

## D4 — Synthetic data with hidden formula, generated offline (2026-10-16)

Phase 1 data generator is template-based (no LLM calls) and deterministic (seeded): hidden multiplicative formula over 15 features + lognormal noise, systematic underestimation bias in `team_estimate`, ~30% of emails omit 1–2 present features. Ground truth dumped to data/ground_truth.json for validation only — the estimator never reads it. Trade-off: emails are less varied than real RFP text; disclosed in README.

## D5 — Parallel agent execution with file ownership (2026-10-16)

Two agents build Phase 1 (data + DB) and Phase 2 (core services) in parallel with disjoint file ownership; interfaces frozen in docs/API.md (canonical row + CSV format). Avoids merge conflict and integration drift. Trade-off: integration wiring happens in wave 2 (API layer).

## D6 — Wave 2: API layer, SSE streaming, replay cache (2026-10-16)

FastAPI endpoints implemented exactly per docs/API.md (10 routes + SSE stream). Startup computes the walk-forward replay once, persists it (`model_version "replay-v1"`) and caches it in memory; History/Proof read from this cache so the UI stays fast. Conformal tail quantiles widened ×1.10 → seeded replay coverage 73.8% → 78.6% (target 75–85%), MAE unchanged. Demo DB note: `data/estimator.db` accumulates smoke projects (P061+) on this device — delete the file to auto-reseed 60 pristine projects on next startup.

## D7 — Wave 3: live integration verification (2026-10-16)

Both servers verified together, live: CORS `access-control-allow-origin: http://localhost:3000` on preflight + real requests; `POST /api/scenarios/{id}/load` returns the full EstimateResponse (Scenario A detects payments/PCI/mobile/realtime/3rd-party); `/api/projects` rows carry `system_p10/p50/p90`; actuals flow returns `coefficient_updates` + `accuracy`; invalid actuals → 422 with Vietnamese detail string; SSE emits 6 steps + result. Demo DB reset to a pristine 60-project state (auto-seeded on startup).

Ops caveat (this device only): building `frontend/` in place on `/sdcard` fails on FUSE (no symlinks; Node cannot mmap native `.node` binaries from the mount). Workaround: build in a rootfs copy (`/root/est-build/frontend`) and copy `.next` back; npm scripts invoke the Next CLI via `node ./node_modules/next/dist/bin/next` (portable); on-device installs need `--no-bin-links`. Standard machines (and Vercel CI) are unaffected.

## D8 — Ridge alpha tuned 1.0 → 0.3 (2026-10-16)

Multi-seed CV sweep on the seeded 52-project dataset: alpha 0.1 → 8.90, 0.3 → 8.95, 1.0 → 9.69, 10 → 14.19 (CV MAE, days). Set `RIDGE_ALPHA = 0.3`: walk-forward MAE 12.58 → **10.70 days (-15%)**, coverage stays 78.6%, in-sample R² 0.87 → 0.90. Learning-curve experiment (same hidden formula, sampled histories): CV MAE 10.2 @ n=60 → 8.5 @ n=120 → ~8.1 plateau (= lognormal noise floor); rare features (pci_dss, 17%) converge with more data.

## D9 — TAWOS cross-dataset validation: documented negative result (2026-10-16)

Official TAWOS dump (637 MB) was too slow to download (~75 KB/s) → used a GitHub mirror; subset committed as `data/tawos_subset.csv` (5,850 stories / 39 projects, Apache-2.0 attribution in `data/tawos_README.txt`). Offline stub extraction fires on only 22.3% of rows (Jira story vocabulary ≠ RFP vocabulary) and the 3-day prediction floor binds on ~85% of test rows (story points ≠ person-days — exactly the spec §11.1 warning). Cross-project result: MAE 2.48 SP ≈ global-median baseline (2.48 SP), R² ≈ −0.02 → **no learning signal**. Documented honestly in `docs/TAWOS_VALIDATION.md` + README limitations. Real cross-dataset validation requires LLM-based extraction and person-day data.

## D10 — Default LLM provider: DeepSeek V4.1 Flash (2026-10-16)

Added `DeepSeekProvider` (`deepseek-flash` = DeepSeek-V4.1-Flash, OpenAI-compatible chat completions at https://api.deepseek.com, JSON output mode, thinking mode explicitly disabled for fast cheap deterministic extraction) and made `deepseek` the recommended provider in `.env.example` (user preference over Gemini). Reference pricing per 1M tokens: input $0.15/$0.30 off-peak/peak (cache hit ~$0.003–0.006), output $0.60/$1.20 — roughly 2–4× cheaper than Gemini 2.5 Flash; the whole 60-email extraction batch costs ≈ $0.03–0.07. Gemini/OpenAI providers remain; the zero-key default stays the offline stub.

## D11 — Wave B product upgrades (2026-10-17)

Addressing review feedback, all with tests (140 total, offline/stub-forced):
- **Monte Carlo over unknown features** (`estimate_mc`): unknowns are sampled from training prevalence; intervals widen with missing info (live demo: 10 unknowns ⇒ 256–364-day range; fully answered ⇒ `method:"point"`).
- **Interactive answers** (`POST /api/estimate` gains `answers`): each ranked question has Yes/No; the range shrinks live. Refinement calls are side-effect free (no P0nn rows).
- **Budget-fit packages** (`build_packages`): Essential/Standard/Full tiers phase out the most expensive optional capabilities; over-budget probability via a documented lognormal fit of the conformal interval.
- **Third baseline** (`llm_baseline`): LLM + company history in the prompt; `ab_measurement.py` measured all baselines for real on `deepseek-flash` (system 23.5 vs team 30.4 vs LLM+history 36.0 vs LLM-only 243 MAE days; 5× variance probe std 0.000 — the spec's "±15 days" claim is retired and replaced by measured calibration findings).
- **Extraction eval** (`extraction_eval.py`): per-feature precision/recall on the 60 emails with known ground truth (DeepSeek F1 0.923 vs stub 0.841; negation 100% vs 35%).
- **Realistic generator**: interactions (pg×pci +20%, migration×legacy +15%, mobile×offline +8%), mid-history drift (+22% from 2026-02; post-drift last-10 System 15.65 vs Team 33.30 MAE) and 5% outliers.

## D12 — Single-service deploy (2026-10-17)

Next.js switches to `output: "export"`; `lib/api.ts` defaults to same-origin `""` so the static UI is served by FastAPI (`StaticExportFiles` subclass: `.html` retry for extensionless routes, `/api/*` never falls into the static mount). Multi-stage Dockerfile (node build → python runtime) + one Render Docker web service (`render.yaml`); `.dockerignore` keeps `.env`/`node_modules` out of the build context; `frontend/out` is gitignored (built in-image / on-device via the D7 rootfs dance). Removes CORS and the two-service failure mode; Vercel demoted to a documented fallback.

## D13 — Dataset expanded 60 → 240 projects (2026-10-17)

Approved after the measured learning curve (CV MAE 10.2 @60 → 8.5 @120 → ~8.1 @240 plateau). Regenerated deterministically (same DGP: interactions, drift ×1.22, 5% outliers); 228 done / 12 open; all downstream numbers re-measured: walk-forward System MAE 23.50 → **17.36** (218 steps), coverage **189/218 (86.7%)**, extraction F1 0.933 (DeepSeek) / 0.845 (stub). Full re-measurement cost ≈ $0.23.

## D14 — Validation wave 2 — two negatives, one positive, one honest "not yet" (2026-10-17)

- **SWE-bench (C2 + multi-file refinement C8)**: predicting patch invasiveness from issue text ± codebase signals does **not** improve (original 2,294 instances and the 571-instance multi-file subset; paired CIs include 0) → no accuracy claim; the module stays "risk explanation".
- **Similar past changes (C9) — POSITIVE**: on 29,058 targets / 4 real repos, "similar-message → median of K=5" beats the repo-median baseline (−2.8% MAE, 95% CI [−0.060, −0.022]; Spearman 0.323 vs 0.034; oracle 0.881). Per-repo mixed (pytest/flask win, sympy ties, requests loses slightly) — reported as-is.
- **Itemlet (C7)**: 114 real projects with absolute logged hours (of 204; 90 have zero logs) — conformal coverage 76–86% (target 75–85 ✓; TAWOS's 48.5% failure does not reproduce) but the point estimate ties the median: only 6.5% of issues have logged time.
- **Distillation (C6)**: teacher DeepSeek F1 0.923 vs student 0.442 at n=240, plateaued → "replace the LLM when enough data" is real but far off at demo scale; `LLM_PROVIDER=distilled` ships offline with a stub fallback and honest labels.

## D15 — Codebase Lab integration + positioning (2026-10-17)

`POST /api/estimate` accepts `repo: demo_a | demo_b | self`; the response carries a `codebase` block (friction, invasiveness, similar changes, base vs adjusted estimate, adjustment breakdown, honest note). Demo repos are generated deterministically on demand; keywords for similar-changes come from the extracted features. UI: repo selector + `CodebasePanel` on the Estimate screen. **Positioning per the decision gate: risk explanation, one-directional surcharge (never a discount), demo-assumed coefficients (×0.30/×0.60 widening, ×0.35 invasiveness shift) until a real pilot learns them.**





