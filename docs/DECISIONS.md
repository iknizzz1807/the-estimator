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



