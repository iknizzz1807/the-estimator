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

## D16 — Pre-deploy QA sweep (2026-10-17)

Three parallel QA agents (backend adversarial testing, frontend/integration contract checks, repo hygiene + claims audit). Fixed before deploy: parallel-estimate id race (`BEGIN IMMEDIATE`), non-finite `actual_days` accepted (corruption + replay 500), CSV import feature-value validation, replay cache invalidation for custom `min_train`, **Docker image missing `git` (Codebase Lab would 500 on Render)**, `delta_pct` semantics aligned to the contract (actual-vs-system; the system-vs-team bias stays as the extra key `system_vs_team_pct`), demo-repo analysis pinned to reference date 2026-04-01 (friction no longer decays as the churn window slides; deterministic demo values), truncated-JSON brace repair for the `deepseek-flash` missing-`}` quirk, and clean errors for non-git/broken demo repos. Frontend: clipboard-failure false alarm, EN/VI warning dedupe, stale copy/counts, `project_id: null` typing — rebuilt and redeployed. Hygiene audit: no secrets in history, clean clone reproduces, 201 tests. Claims audit fixed 5 stale numbers in README/API.md/DECISIONS. Docker image now ships `.git` so `repo="self"` works in production.

## D17 — Render build context has no `.git` (2026-10-17)

D16 promised "Docker image ships `.git` so `repo="self"` works in production", but Render's Docker build context comes from a GitHub checkout **without** `.git`, so the hard `COPY .git ./.git` failed the first live deploy ("failed to compute cache key: /.git: not found"). The Dockerfile now copies `.git` conditionally via a BuildKit bind mount (`RUN --mount=type=bind,target=/ctx if [ -d /ctx/.git ]; ...`): local builds from a full checkout keep shipping history (self-analysis works), Render deploys build cleanly and `repo="self"` returns the existing clean "not a git repository" message while demo_a/demo_b (the showcased repos) work unchanged. Revisit only if cloud self-analysis is needed (e.g. clone history at build time).

## D18 — Change-retrieval signal for Codebase Lab (gate PASSED — see docs/RETRIEVAL_VALIDATION.md) (2026-10-17)

Direction after the "can the codebase and the request fit each other?" review. The structural friction signals stay (they answer "how expensive is change here"); this adds the missing "have we done something like this before, and what did it touch" layer:

- **Lean pipeline**: chunk the repo (file/function + commit messages) → embed **once offline** into a committed `.npy` (runtime embeds only the query: fastembed ONNX or a provider embedding API — **no torch**, D3 stays intact, Render 512 MB) → hybrid retrieval **BM25 (rank-bm25, already a dependency) + cosine** → show top matching files, top-3 similar past commits (with files-touched counts) and the structural friction (fan-in/churn/complexity, history cut at the request date — leakage guard) of the retrieved file set.
- **Positioning**: a *locate/retrieve* signal first. It may only feed the estimate after passing its own evaluation gate: **recall@k on real issue→patch pairs** using existing assets (`itemlet_projects.csv`, 29k real commits; SWE-bench subsets; `scripts/itemlet_validation.py` / `swebench_validation.py`). Fail → ship labelled "uncalibrated" or not at all; no prediction claim.
- **Rejected**: a vector database for a few thousand chunks (numpy+cosine is enough); torch/sentence-transformers (D3 + Render RAM); synthetic codebases for validation (circular); importing external accuracy numbers (the contested "84%" vs thesis "44%/30%" of Vector Impact of Change) — claims stay self-measured (D14/D16).
- **Sequencing**: submission-critical path first; this lands only after the live app is final. Companion improvement (P2): deterministic capability inventory (dependency/import scan per taxonomy feature) + an `unmapped_asks` warning for out-of-taxonomy requests (e.g. "add Google Maps" is not a feature; it must not be silently absorbed).
- **Evaluation (2026-10-17) — gate PASSED**: recall@k on flask (5,562 commits) + requests (6,495 commits), 300 targets each, pre-registered bars (analog hit@10 ≥ 0.50, locate hit@10 ≥ 0.60): analog hit@10 0.650–0.807, locate hit@10 0.683–0.776. Embedding arms: **bge-small-en-v1.5 stays the default**; jina-code showed no measurable edge (delta within noise) and OOM'd the locate probe (52 GB ONNX allocation, 8192-ctx padding) — rejected; multilingual-MiniLM tied on English and is the only cheap VI-capable option (not adopted without a Vietnamese eval); BGE-M3 rejected for runtime RAM (0.6–2.2 GB). Integration recommendation: candidate-files/analog-commits panel labelled `retrieval`; numeric coupling to the estimate stays out until separately validated. Full numbers: `docs/RETRIEVAL_VALIDATION.md`.
- **Numeric coupling is a separate, pre-registered gate**: retrieval is a locator/evidence layer, NOT a second friction — it does not add to friction and does not touch the estimate. Proposed next ablation (pre-registered in `docs/RETRIEVAL_VALIDATION.md`): walk-forward replay comparing whole-repo friction vs friction computed only on retrieval-selected files; pass bar = `mae_system` improves ≥ 5% relative with coverage inside 75–85%. Fail ⇒ display-only forever; pass ⇒ D19 and only then may feed the estimate.

## D20 — Surcharge coefficients measured on 29,059 real commits (D19 stays reserved) (2026-10-18)

The weakest link in Codebase Lab was never the friction *measurement* (churn/fan-in/complexity/authors are computed from real git) but the three **DEMO-ASSUMED surcharge constants** of `apply_friction` (`FRICTION_P10_WIDENING=0.30`, `FRICTION_P90_WIDENING=0.60`, `INVASIVENESS_P50_SHIFT=0.35`). The chain repo → days has five links; L1 (friction → change size), L2 (friction → spread), L3 (invasiveness → size) are measurable on public data; L4 (size → person-days) and L5 (friction → person-days) are **not** (no public dataset pairs repository signals with logged effort at task level — checked: SEOSS/JIRA-Repository/TAWOS have no worklog, Itemlet has worklog but no commit link and only ~3.25% logging coverage, AgES has resolution time not effort).

`backend/scripts/surcharge_calibration.py` measures L1–L3 leakage-free on flask/requests/pytest/sympy (**29,059 targets**), reusing the product's own constants (`CHURN_SATURATION_COMMITS`, `FRICTION_WEIGHTS`) and formula; friction is computed only from commits strictly before each target, and only the 2 git-computable components (churn, author_concentration) are used, renormalised ("git-only friction"). Pre-registered gates: **G1 friction→size PASS (4/4 repos, β CI > 0)**; **G2 friction→spread 3/4 → gate FAILS as written** (`requests` 1.124, CI [0.855, 1.494], includes 1 — the same repo that lost marginally in `docs/CODEBASE_HISTORY_VALIDATION.md`); **G3 rank signal PASS (4/4)**. Measured: size inflation per unit friction `e^β` = ×1.12–×2.05; relative spread ×1.12–×1.78 larger in the high-friction tercile; multi-file rate 0.20→0.78 (flask). Reported as-is, no tuning.

Decision: **the three constants stay numerically unchanged**, but they are no longer purely assumed — L1/L2/L3 now have measured support with the direction confirmed, and every surface keeps the honest label. L4/L5 remain an explicit assumption until a pilot records `(repo signals, actual days)` pairs; the product is not yet instrumented for that (roadmap). Full numbers, method, gates and limitations: `docs/SURCHARGE_CALIBRATION.md`; tests: `backend/tests/test_surcharge_calibration.py`. Note: D19 remains reserved for the retrieval numeric-coupling ablation (D18).

## D21 — Paste a public GitHub repo + graceful codebase degradation (2026-10-18)

Two gaps found in a judge-facing review: (1) `repo="self"` is the *default-looking* option but is **guaranteed to fail on Render** (D17: the cloud build context has no `.git`), and it failed with a **500 that killed the whole estimate** ("nothing was stored") plus a misleading message telling users to delete `data/demo_repos`; (2) the only repositories on offer were synthetic demo repos, while the product's real input is *the customer's* repo.

- **Graceful degradation**: `run_estimate_pipeline` (and the SSE path) now catch a codebase `RuntimeError`, log it, and return the **estimate unchanged** with `codebase_error` instead of failing. The numbers never depended on the repository, so a codebase problem must not cost the user their estimate. This also covers clone failures, oversized repos and a missing `git`.
- **Paste a repo**: `repo` accepts a public GitHub repo (`https://github.com/<owner>/<repo>` or `<owner>/<repo>`), canonicalised to `gh:<owner>/<repo>`, cloned once into `data/repo_cache/` (gitignored, LRU-capped at 6). Analysis is pinned to the cached HEAD commit date so repeat runs are deterministic. This is the *correct* input model — the customer's codebase, not our own.
- **Security (a public endpoint with no auth)**: acceptance is a strict allow-list of `github.com/<owner>/<repo>` (no other host/scheme/port/userinfo/query/fragment) → 422 otherwise, which is what prevents SSRF (`169.254.169.254`, `localhost`, `file://`). The clone is hardened (`GIT_TERMINAL_PROMPT=0`, `http.followRedirects=false`, `--no-recurse-submodules`, `--single-branch`), bounded (180 s timeout, 300 MB cap) and serialized by a lock.
- **Clone format**: a **full** clone is required, not `--filter=blob:none` — `find_similar_changes` runs `git log --raw --numstat` and numstat needs blob contents, so a blobless clone re-fetches every commit over the network (measured **221 s** for a 2.3k-commit repo vs **~1 s** full). A format marker in each cache entry invalidates stale clones.
- **UI**: the selector hides `This project` when `/api/health` reports `self_available: false` (so the cloud deployment never shows a button that cannot work), and adds a "paste a public repo" input; `codebase_error` renders as a neutral notice, not a red crash.
- **Rejected**: shipping real repos (flask/requests) in the image as the cheap alternative — the paste flow is the real product model and costs no image size; keeping the 500 (a judge clicking the default option would see a crash); allowing non-GitHub hosts (SSRF).

Verified live locally: URL 4.5 s (friction 0.9315, adj P50 274.9, 5 similar changes), shorthand 3.5 s (cache hit), `self` 2.4 s, `evil.com` rejected in 0 s. Tests: `backend/tests/test_api.py` (selector accept/reject, SSRF cases, health capabilities, clone command hardening, graceful degradation). Contract: `docs/API.md`.

## D22 — Language scope of the friction signals (non-Python repos were biased low) (2026-10-18)

Pasting an arbitrary repo exposed a correctness bug. Of the five friction components, **only three are language-agnostic** (`churn`, `author_concentration` — both from `git log` — and, when a report exists, `coverage_gap`); **`fan_in` and `complexity` are Python-only** (an import scan over tracked `*.py` files and `radon`), and `coverage_gap` needs a Python `coverage.xml`. For a repo with no Python files, `_collect_complexity` returned `status: "scored"` with `files_scored: 0`, and `compute_friction` mapped the missing components to a **measured `0.0`** instead of unknown. A zero enters the weighted mean with **0.45 of the total weight**, so friction was biased **DOWN**: measured on `expressjs/express` (JavaScript), the score was **0.3405 (medium)** when the available components give **0.681 (high)** — a ~2x dilution that, under the one-directional surcharge rule, means **under-quoting risk on non-Python repos** (the exact failure the design is meant to prevent).

Fix: `compute_friction` now treats `fan_in`/`complexity` as **`None` (unknown, never faked)** when they were not actually measured (`python_files == 0`, or complexity `status == "unknown"` / `files_scored == 0`), omits them from the sum, renormalises the remaining weights and adds an explicit note — exactly the treatment `coverage_gap` already had. Python repos are unaffected (verified: `pallets/click` 0.9315 before and after). Documented as a user-visible limitation: on a non-Python repo the score rests on 2 of 5 components. Tests: `backend/tests/test_codebase.py::test_non_python_repo_marks_python_only_components_unknown`.

**Still Python-only, not fixed here** (would need per-language analyzers): `fan_in`, `complexity`, and the `coverage.xml` reader. `find_similar_changes` (path keywords) and `invasiveness` (files touched) are already language-agnostic, and the unwired `retrieval.py` already lists many source extensions (`.ts/.tsx/.js/.go`-style coverage would need its own chunker/analyzer).

## D23 — Clickable pre-cloned example repos (instant results, no URL) (2026-10-18)

A visitor should not have to invent a repo or paste a URL to see the Codebase Lab work, and the two demo repos are synthetic while `self` is our own code. Seven **real** repos are now pre-cloned at image build time by `scripts/fetch_example_repos.py` into `data/example_repos/` (gitignored), reported by `/api/health` under `codebase.examples`, and rendered as one-click chips on the Estimate screen.

- **Same live path, nothing precomputed**: an example is analysed by exactly the code that handles a pasted repo, so the numbers are the product's real numbers. The analysis is pinned to the fetch-time HEAD date (`examples.json` manifest) so friction does not drift as the calendar moves.
- **Selection** (7 repos, 4 languages, ~36 MB, ~16 s of build-time clone): `ex_flask` pallets/flask (Python, web framework), `ex_requests` psf/requests (Python, HTTP client), `ex_stripe` stripe/stripe-python (Python, payments SDK), `ex_fhir` smart-on-fhir/client-py (Python, healthcare FHIR client), `ex_gin` gin-gonic/gin (Go), `ex_ripgrep` BurntSushi/ripgrep (Rust), `ex_cjson` DaveGamble/cJSON (C). `medplum/medplum` was measured and **rejected** (246 MB, 68 s) — too heavy for the image.
- **Best-effort at build**: the Dockerfile runs the fetch step with `|| echo ...`, so a network hiccup cannot fail a deploy; the app simply offers fewer examples (`available_examples()` only lists what is on disk, and selecting a missing one degrades gracefully via D20/D21).
- **Honest caveats** (all user-visible): (a) the `kind` labels say what each *library* is for — a codebase sample, **not** a validated client project (OSS != B2B SaaS is unchanged); (b) non-Python examples are scored on 2 of 5 friction components (D22) and show it (gin 0.2923 low, ripgrep 0.6766 high, cJSON 0.2667 low); (c) **mixed-language repos are not yet corrected**: cJSON tracks 229 files of which only **2 are `.py`** (Unity test scripts), so `fan_in`/`complexity` are "measured" on those 2 files yet reported as full components (`complexity` 0.75) — a Python-*share* caveat, the mirror image of D22. The raw counts (`fan_in.python_files`, `complexity.files_scored`) exist in `collect_signals` but are not surfaced in the `codebase` block; fixing it (a share threshold, or surfacing the counts) is a follow-up, deliberately not done on the submission-critical path.
- **Rejected**: caching precomputed codebase blocks per (repo, scenario) — it would freeze `similar_changes` per email, create a second code path and lose the "real numbers" property; shipping the clones in git (36 MB of third-party history in our repo).

**Update (D24):** the non-Python examples listed above (Gin/Go, ripgrep/Rust, cJSON/C) were **removed** when the scope became Python-only; the registry now holds 5 Python repos. The "Selection (7 repos, 4 languages)" line above is superseded — see D24.

## D24 — Codebase Lab is Python-only, enforced (2026-10-18)

Decision after the mixed-language review: **stop half-supporting other languages and say so.** `fan_in` (import scan) and `complexity` (radon) are Python signals; rather than reporting them as full components on a repo that is mostly another language, the analyzer now **refuses** a repository whose primary source language is not Python.

- **Gate** (`codebase.detect_primary_language`): counts tracked source files per language (`SOURCE_EXTENSIONS`), and Python must be the **most common** source language (ties count as supported, so a repo that is at least half Python still analyses). Otherwise `build_codebase_block` raises a clean Vietnamese message — *"Codebase Lab hiện chỉ phân tích repo Python (hỗ trợ đa ngôn ngữ sẽ bổ sung sau) — repo này chủ yếu là C: 2/117 file nguồn là .py"* — and the graceful-degradation path (D20) returns the estimate plus `codebase_error`. Multi-language is a stated later feature, not a silent approximation.
- **Why enforced, not just labelled**: measured on `DaveGamble/cJSON` (2 stray `.py` Unity test scripts out of 229 tracked files) the old path reported `complexity` **0.75** as if it described a C library — the mirror image of D22's deflation. A gate removes the whole class of error; the D22 `None` handling stays as a safety net (e.g. radon unavailable).
- **Contract**: the `codebase` block gains `language` (`{dominant, python_files, source_files, python_share}`) so the analysed scope is visible on every response, and the UI shows it in the panel subtitle (`Python · 83/83 source files`). `docs/API.md` updated; `CODEBASE_CONTRACT_KEYS` in the tests updated.
- **Examples**: the registry is now **5 Python repos** (Flask, Click, Requests, Stripe SDK, SMART FHIR — ~32 MB); Gin/ripgrep/cJSON were removed from the registry, their clones deleted, and the fetch manifest prunes entries that leave the registry. Measured after the change: Flask 0.6604 (medium), Click 0.9315 (high), Requests 0.8586 (high), Stripe 0.8296 (high), SMART FHIR 0.5000 (medium); all 5 report `python_share = 1.0`.
- **Rejected**: silently keeping non-Python repos with a warning (the number would still misrepresent the repo); a Python-share threshold instead of a dominance rule (another arbitrary constant); making `fan_in`/`complexity` multi-language now (lizard covers complexity, but fan-in needs per-language import resolvers — a real feature, not a patch, and it changes every measured number).
- **Python-quality roadmap (explicitly NOT done on the submission-critical path)**: AST-based import scan instead of the documented regex (exactness, stdlib only), excluding test files from `complexity` (test scaffolding inflates it), locating `coverage.xml` in subdirectories, and using `lizard` for a later multi-language release. Each of these **changes measured friction values**, so each needs a full re-measurement — not a deadline-weekend change.

## D25 — Python-quality pass: exact import scan, tests out of complexity, coverage in subdirs (2026-10-18)

The three Python-only quality items deferred by D24 were implemented (all stdlib, no new dependency). **Published numbers did not move**, so no re-measurement of the docs was needed — see below.

- **(a) AST import scan** (`_module_refs` now parses with `ast`; the documented regex survives as `_module_refs_regex`, used only when a file does not parse, so one broken file cannot blank the signal). The text scan was measurably wrong in both directions: it counted `import` inside **comments and strings** (22 phantom refs in flask) and **missed every multi-line parenthesised import** (7,733 missed refs in stripe-python — its fan-in max is now 741). Same output shape, so `_collect_fan_in` is unchanged.
- **(b) Test files excluded from `complexity`** (`is_test_file`, documented convention: any `test`/`tests`/`testing` directory segment, or `test_*.py` / `*_test.py` / `conftest.py`). Test scaffolding is long and branchy by construction; measured: **48/83** Python files in flask and **59/91** in click are tests. The skipped count is reported as `complexity.test_files_excluded` (flask 48, click 59, requests 15, stripe 77).
- **(c) `coverage.xml` found in subdirectories** (`_find_coverage_xml`: repo root first, else the shallowest then lexicographically first match, with a bounded walk and skip-dirs). Reports below the root were previously reported as "unknown". The resolved location is reported as `coverage.path` with **POSIX separators** (a Windows backslash had leaked into the contract — fixed while testing).
- **Why the published values are unchanged** (verified after the change): `fan_in` and `complexity` are saturating components (`min(1, max/8)` and `min(1, max/20)`), and on every published repo the max is already **above the cap** — flask fan-in 20, click 9, requests 10, stripe 741; complexity 23/35/21/28. So demo_a 0.2085, demo_b 0.6874, ex_flask 0.6604, ex_click 0.9315, ex_requests 0.8586, ex_stripe 0.8296, ex_fhir 0.5000 are **identical before and after**. The improvements are real but only visible on a repo whose max sits below the cap — which is exactly why the *method* matters more than these numbers.
- **Tests**: 6 new (`_module_refs` exactness incl. comment/string and multi-line, relative anchoring, syntax-error fallback; `is_test_file` conventions; complexity exclusion; coverage-in-subdirectory + POSIX path). Suite: **239 passed**.
- **Still open** (unchanged from D24): `fan_in`/`complexity` remain Python-only; `lizard` + per-language import resolvers are the multi-language path; test files are still counted in `churn` and `fan_in` (deliberately: they are real maintenance surface — only `complexity` was approved for exclusion).

## D26 — PR lead time as an effort proxy: tried and REJECTED (2026-10-18)

D20 left one link assumed: *change size -> person-days*, unmeasurable because no public dataset pairs repository signals with logged effort. This entry closes the cheapest public-data workaround I had proposed: GitHub publishes a real per-change duration (a merged PR's `created_at -> merged_at`), so `scripts/pr_leadtime_study.py` tested whether repository friction predicts it, controlling for the change's own size (changed files, added+removed lines), a bot flag and a month trend. Friction is git-only (D20 components) and computed from commits strictly before each PR's creation (leakage guard), bucketed per month.

**Pre-registered gate: FAILED.** Pooled over **3,240 merged PRs** (flask, click, requests, stripe-python, client-py) the friction coefficient on `log1p(lead time days)` is **-0.892** (95% CI [-1.263, -0.507]) — not merely non-positive, but **negative**: higher friction is associated with *shorter* lead time. Per repo: flask 0.015 [-0.637, 0.644], click -1.836 [-2.606, -1.112], requests 0.525 [-4.134, 4.954], stripe-python -0.001 [-0.401, 0.400], client-py -7.783 [-10.849, -3.789].

Why the design cannot work here: (1) the target is **nearly degenerate** — median lead time is 0.30–0.64 days, i.e. most PRs in these libraries merge the day they are opened, leaving almost no variation; (2) the predictor **barely varies within a repo** (0.80–0.96 for four of five), so the coefficient is estimated off between-repo differences; (3) friction and calendar time are correlated and the month-trend control absorbs that trend, making the residual coefficient unstable and able to flip sign — which it did.

**Decision: no product coefficient is derived from this, and lead time is not a usable effort proxy.** The assumed `size -> person-days` link stands (D20/D24), and the only remaining path to measuring it is instrumenting the product to record `(repo signals, actual days)` pairs (D24 roadmap). Reported as a documented negative, in the same spirit as `docs/TAWOS_VALIDATION.md` and `docs/CODEBASE_VALIDATION.md`. Full numbers, method and limitations: `docs/PR_LEADTIME_VALIDATION.md`. Note: the study needs `GITHUB_TOKEN` at run time only (never persisted); the local clones come from `scripts/fetch_example_repos.py`.





