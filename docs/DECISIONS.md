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


