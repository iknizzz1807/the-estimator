# HANDOFF — The Estimator (2026-10-18)

> **For any new agent/model picking this project up.** Read this file first, then `docs/DECISIONS.md` (every design decision, **D1–D28**) and `README.md` (product + measured results). This file is the operational state of the world; it is updated by whoever finishes a work session.

## 0. TL;DR

- **Product is complete AND DEPLOYED**: **242 backend tests** green, single-service app (FastAPI serves the static Next.js UI + API on one port), 240-project demo dataset, real DeepSeek extraction live.
- **Live app**: https://the-estimator-xqzc.onrender.com — **verified live 2026-10-18** (see §5). Plan `0.5c-512mb` (~$7/mo, no cold start) — downgrade to Free or delete after ~22/10 to stop billing.
- **GitHub**: https://github.com/iknizzz1807/the-estimator (public). `main` @ `8f1cd42` **+ 1 unpushed commit** (see §2).
- **Next steps, in order**: (1) **push** `8f1cd42` and confirm the Render redeploy (§5); (2) fill the live URL into `docs/SUBMISSION.md` (still `TBD`) and submit via the portal; (3) **revoke the GitHub token + rotate the DeepSeek key** — both were pasted into a chat again on 2026-10-18 (§8).
- **Deadline**: Sunday **2026-10-18 23:59** (self-imposed) / Monday 19-10 official. Competition: *Agent in the Shell* — Anduin Cybernetics, Challenge #2 "The Estimator".

## 1. What this is (one paragraph)

Paste a customer email/RFP → LLM (DeepSeek V4.1 Flash) extracts 15 binary project-complexity features with verbatim evidence → **math** (Ridge α=0.3 on log-days + split conformal prediction + Monte Carlo over unknowns) produces a calibrated **P10/P50/P90** range → ranked clarifying questions whose answers **shrink the range live** → budget-fit quote packages (Essential/Standard/Full + over-budget probability) → a pricing curve (quote-days → overrun risk) → optional **Codebase Lab** (friction + invasiveness + similar past changes widen the range; risk explanation only) → a learning loop (actuals retrain; mid-history drift proves adaptation) → walk-forward Replay + A/B proof screens. Runs fully offline with a deterministic stub; real LLM with a key.

**Codebase Lab as of 2026-10-18** (D20–D27): the repository selector offers **demo_a / demo_b** (synthetic), **5 pre-cloned real Python repos** (Flask, Click, Requests, Stripe SDK, SMART-on-FHIR — one click, instant), **"This project"** (local checkout, or a build-time clone of this repo on cloud), and a **pasted public GitHub URL** (strict `github.com` allow-list). It is **Python-only, enforced** — a repo whose primary source language is not Python is refused with a clear message rather than mis-scored.

Key docs: `README.md` · `docs/SPEC.md` (business spec) · `docs/API.md` (contract incl. v0.2 + the Codebase Lab additions) · `docs/DECISIONS.md` (D1–D28) · `docs/SUBMISSION.md` (submission text EN+VI).

## 2. Git state

- `main` @ **`8f1cd42`** (D27), **ahead of `origin/main` by 1** — that commit is not pushed yet.
- Session commits (2026-10-18), newest last:
  - `cda3a20` — D20: surcharge coefficients measured on 29,059 real commits
  - `d81f348` — D21–D24: paste-a-repo, graceful degradation, non-Python fix, clickable examples, Python-only gate
  - `2144113` — D25: AST import scan, tests out of complexity, coverage in subdirs
  - `c1fc8c5` — D26: PR lead-time study (negative, rejected)
  - `5970e38` — README test count 188 → 239
  - `e0a4aad` — *user's parallel session* (SpotlightTour.tsx UI)
  - `8f1cd42` — D27: "This project" fallback clone
- The user runs **parallel sessions** (separate UI commits land mid-session). Pull before editing; **never `git add -A`** — commit only your own paths.
- Commit convention: ASCII messages, scoped prefixes (`feat(api):`, `fix(frontend):`, `docs:`, `chore(deploy):`).

## 3. Environment specifics

### On a computer (fresh clone — recommended for deploy work)
```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
bash scripts/run_api.sh            # API-only unless frontend/out exists
cd ../frontend && npm install && npm run build   # builds frontend/out (served by FastAPI)
python -m pytest tests/ -q         # 242 tests, offline
docker build -f backend/Dockerfile -t the-estimator .   # full single-service image
```

### On the Windows box used for this session (2026-10-18)
- Python 3.12; venv at `backend\.venv` (Windows `Scripts\` layout — no bash).
- No system git/node; portable tools, no admin needed:
  - MinGit 2.56: `%LOCALAPPDATA%\Temp\opencode\git\cmd` (**must be on PATH** — Codebase Lab shells out to git, and so do the tests)
  - Node 20.20.2: `%LOCALAPPDATA%\Temp\opencode\nodejs` (normal `npm ci && npm run build`)
- **Helpers added this session** (Windows ports, committed):
  - `backend\scripts\run_api.ps1` — run the API/UI on `:8000` (auto-uses `.venv`, auto-adds the portable git/node to PATH)
  - `frontend\build.ps1` — `npm ci` (first run) + `next build` → `frontend\out`
- **Local eval clones** (gitignored, not committed): `%LOCALAPPDATA%\Temp\opencode\eval-repos` (flask/requests/pytest/sympy, blobless — for `surcharge_calibration.py`).
- Run: `cd backend; .\scripts\run_api.ps1` → UI+API at `http://127.0.0.1:8000`.
- **Secrets**: repo-root `.env` (gitignored) holds `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY`. `tests/conftest.py` forces `LLM_PROVIDER=stub`, so pytest is offline/deterministic/free.

### On the phone (Android/Termux + PRoot Debian, where this was originally built)
- Python venv: `/root/venvs/estimator/bin/python`; run with `PYTHON=/root/venvs/estimator/bin/python bash scripts/run_api.sh`.
- **Frontend build workaround (D7/D12)**: `/sdcard` is FUSE (no symlinks, no mmap) — build in `/root/est-build/frontend`, then copy `out/` back. `next.config.ts` uses `output: "export"`.
- git on `/sdcard` needs `safe.directory` + `core.fileMode false`.

## 4. What's built (map)

- **Backend** `backend/app/`: `api/routes.py` (endpoints + SSE), `api/state.py` (pipeline, DB wiring, Codebase Lab block, repo resolution/validation, example registry, reset, import), `services/`: `extraction.py`, `providers.py` (deepseek|gemini|openai|stub|distilled + truncated-JSON repair), `estimation.py`, `similarity.py`, `voi.py`, `learning.py`, `replay.py`, `ab.py`, `llm_baseline.py`, `packages.py`, `codebase.py` (friction/invasiveness/similar-changes + `detect_primary_language` + `is_test_file`), `retrieval.py` (D18 spike — **not wired**), `distilled.py`; `data_gen/`; `db/`.
- **Codebase Lab scope (important)**: **Python-only, enforced** (D24). `fan_in` (AST import scan, D25) and `complexity` (radon, test files excluded) are Python signals; a repo whose primary source language is not Python is **refused** with a clear message. `churn`, `author_concentration`, `similar_changes`, `invasiveness` are language-agnostic. Multi-language is a stated later feature (`lizard` covers complexity; fan-in needs per-language resolvers).
- **Frontend** `frontend/`: Next.js 15 static export; pages `/` (onboarding), `/estimate` (SSE steps, feature cards, answers→refinement, packages, pricing curve, codebase panel, repo selector + example chips + URL input), `/history`, `/proof`.
- **Scripts** `backend/scripts/`: `run_api.sh` / `run_api.ps1`, `seed_db.py`, `build_demo_repos.py`, `fetch_example_repos.py` (**new** — clones the 5 examples + the `self` fallback), `extraction_eval.py`, `ab_measurement.py`, `surcharge_calibration.py` (**new**, D20), `pr_leadtime_study.py` (**new**, D26), `swebench_validation.py`, `codebase_history_experiment.py`, `itemlet_validation.py`, `distillation_experiment.py`, `tawos_validation.py`, `retrieval_eval.py`.
- **Data** `data/`: `synthetic_history.csv` (240 projects / 228 done, sha1 `b1df6f1b…`), `ground_truth.json` (never read by services), `tawos_subset.csv`, `itemlet_projects.csv`, `distillation_labels.csv` + `distilled_model.joblib`. **Gitignored & regenerable**: `estimator.db`, `demo_repos/`, `repo_cache/` (pasted-URL clones), `example_repos/` (pre-cloned examples + `examples.json` manifest + the `self` fallback).

## 5. DEPLOY STATUS (verified 2026-10-18)

1. **GitHub** ✅ public. `main` @ `8f1cd42`; **1 commit unpushed** (`8f1cd42`, D27).
2. **Render** ✅ DEPLOYED AND LIVE: https://the-estimator-xqzc.onrender.com — manual Web Service, Docker runtime, branch `main`, region Singapore, health check `/api/health`, env `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY`. The Dockerfile's build-time `fetch_example_repos.py` step **works on Render** (verified — the examples are present).
3. **Live verification (2026-10-18, this session)**:
   - `GET /api/health` → `status ok`, `model_loaded true`, `llm_provider deepseek`, `mode calibrated`, `n_train 228`, `codebase.url_clone true`, **`codebase.examples` = the 5 Python repos** (Flask/Click/Requests/Stripe/SMART-FHIR with pinned dates).
   - `GET /` and `GET /estimate` → HTTP 200; `GET /api/scenarios` → 200.
   - **`POST /api/estimate` with `repo=ex_flask` → 4.9 s, `codebase.friction` 0.6604 (medium), `language` Python 83/83, components identical to local, 5 similar changes, base P50 207.3 → adjusted 279.9.** The whole Codebase Lab path works in production.
   - ⚠️ `codebase.self_available` is **false** on the live deploy because it predates D27 — so **"This project" is hidden there** (correct pre-D27 behaviour: hidden rather than broken). Pushing `8f1cd42` + the redeploy flips it to **true** (build-time fallback clone) — re-check this after pushing.
   - **Re-verified after the D27 push (same day)**: `self_available` is now **true**; `POST /api/estimate` with `repo="self"` → **4.2 s, friction 0.8092 (high), Python 58/100, 5 similar changes, base P50 207.3 → adjusted 276.7**. A live/local mismatch found here (0.7343 locally) was traced to a nested demo fixture being read as our own coverage report and fixed in **D28** — local and cloud now agree exactly.
4. **Not verified live**: the pasted-URL path (needs a request that clones a repo; the guards were verified locally), and the SSE screen click-through (§6).
5. **After submitting**: revoke the GitHub token, rotate the DeepSeek key (§8), and downgrade/delete the Render service after ~22/10.

## 5b. D18 retrieval — state and the path forward

**What it is**: a *locator/evidence* layer, NOT a second friction. Friction answers "how expensive is change in this repo, overall?"; retrieval answers "which files does this request touch, and what did similar past changes touch?". It does not add to friction, and it does not touch the estimate numbers.

**State (unchanged since 2026-10-17)**: code `backend/app/services/retrieval.py` (+ `tests/test_retrieval.py`, `scripts/retrieval_eval.py`); **NOT imported by the live pipeline**; `fastembed` is not in `requirements.txt` — zero runtime impact. Gate **PASSED** (analog hit@10 0.650–0.807, locate hit@10 0.683–0.776); numbers + model decisions: `docs/RETRIEVAL_VALIDATION.md` (D18).

**Next actions, in order**: (1) default — nothing, it stays a documented, gated result; (2) wire the **display-only panel** (candidate files + top-3 analog commits, labelled `retrieval — candidates, not a verdict`, kept OUT of the numeric adjustment, lexical-only on Render); (3) P2 capability inventory + `unmapped_asks` warning; (4) numeric coupling only via the pre-registered ablation — and note **the gate as written is not runnable** (the replay has no repository dimension and the real-repo experiment has no conformal interval; it needs pinning down first).

## 6. Live-test checklist (human UI pass)

> API-level equivalents verified live 2026-10-18 (§5). The boxes below are the human UI pass.

- [ ] `/` loads → Onboarding → "Load Sample Data" scenario A runs SSE steps → populated Estimate screen
- [ ] Answer 2–3 questions (Yes/No) → range shrinks live (`method` flips to `point` when fully answered)
- [ ] Enter a budget → 3 quote packages + over-budget % + recommendation; pricing curve slider responds
- [ ] Repo selector: **click an example chip (e.g. Flask) → instant result + friction panel**; try a pasted GitHub URL
- [ ] Demo A vs Demo B → different ranges + friction panel with commit evidence
- [ ] History: filters, Enter Actuals on an open project → coefficient updates + accuracy delta
- [ ] Proof: Run Replay (chart + coverage 189/218) and A/B (real provider → `mode:"real"` badges)
- [ ] Reset demo data button restores 240 projects

## 7. Known issues (deliberate, reported-only)

- **Codebase Lab is Python-only (D24)**: non-Python repos are refused, not mis-scored; `fan_in`/`complexity` remain Python-only. Multi-language is a later feature.
- **Surcharge magnitude is partly measured, partly assumed (D20)**: friction → size (4/4 repos) and friction → spread (3/4; `requests` is the exception) are measured on 29,059 real commits; the last link (**change size → person-days**) is **not** measurable from public data. A public-data workaround (PR lead time) was **tried and rejected** (D26 — pooled coefficient −0.892, gate failed).
- **The product is not instrumented**: nothing records `(repo signals, actual days)` pairs, so the codebase coefficient cannot be learned yet. This is the only remaining path (deliberately not done on the submission-critical path).
- **`/api/estimate` has no auth and no rate limit** → an anonymous visitor can spend the DeepSeek budget. Consider a per-IP limit, or `LLM_PROVIDER=stub` on a public demo.
- Codebase adjustments are **one-directional** (surcharge only, never a discount) and the coefficients are labelled `DEMO-ASSUMED` in every API response.
- `/api/ab` treats `n=0` as default-10; re-submitting an actual is not idempotent; `answers={}` persists a row; `ImportCSVModal` error hint checks the wrong string; Reset doesn't clear `sessionStorage`; `mock.ts` values are stale (offline-only mode, contract keys match).
- An **external monitor** polls `GET /health` (wrong path — the real one is `/api/health`) roughly every 10 s and gets 404s. Harmless; find and disable it.
- Codebase Lab does not answer "does the request fit this codebase" (gap review 2026-10-17); the D18 change-retrieval spike is done and its recall@k gate **PASSED** — see §5b.
- D17: cloud builds have no `.git`; D27 works around it for `repo="self"` with a build-time fallback clone.

## 8. Secrets & credentials map (WHERE, never WHAT)

| Secret | Where it lives | Action |
|---|---|---|
| `DEEPSEEK_API_KEY` | phone `.env` (gitignored) · Render env var · cafe-PC `.env` · this Windows `.env` (gitignored) | never commit; **pasted into a chat again on 2026-10-18 → rotate after submission** |
| GitHub push token (`ghp_…`) | **pasted into a chat on 2026-10-18** (used for the PR lead-time study) and possibly stored in a Windows Credential Manager entry | **REVOKE NOW** (GitHub → Settings → Developer settings → Tokens); clear any stored credential |
| Render account | user's GitHub login | — |

Audit note: `git log --all --full-history -- .env` is empty; secret scans (D16) found no keys in tracked files. `.env` is gitignored and is **not** in any commit.

## 9. Conventions for new agents

- **Ownership discipline**: one writer per file set per wave; commit only your own paths; never `git add -A` blindly; ASCII commit messages.
- **Tests**: keep them offline/deterministic (conftest forces the stub); `pytest tests/ -q` must stay green (**242 today**).
- **Honesty bar**: no claim without committed evidence; every number in README/docs must match a `docs/*.md` artifact (D14/D16). Decision gates: if an ablation fails, do not claim improvement — publish it (D26 is the newest example).
- **Docs**: append a new `D<n>` entry to `docs/DECISIONS.md` for any significant decision; keep `docs/API.md` in sync with the implemented contract; **update this file** at the end of a session.
- **Codebase Lab**: the block must stay honest — `null` for a component that was not measured (never a fake zero), `codebase_error` instead of a failed estimate, and one-directional adjustments only.

## 10. Quick commands

```bash
# tests (offline)
cd backend && python -m pytest tests/ -q                 # 242 tests

# run locally (UI+API on :8000; UI needs frontend/out)
cd backend && bash scripts/run_api.sh                    # POSIX
cd backend; .\scripts\run_api.ps1                        # Windows

# rebuild UI (computer) / phone: see D7 dance
cd frontend && npm run build                             # POSIX
cd frontend; .\build.ps1                                 # Windows

# rebuild demo repos / pre-clone the examples / reset demo DB
cd backend && python scripts/build_demo_repos.py --force
cd backend && python scripts/fetch_example_repos.py [--force]
curl -X POST http://localhost:8000/api/reset

# measurements
cd backend && python scripts/surcharge_calibration.py --repo <path> --write      # D20
cd backend && python scripts/pr_leadtime_study.py --repo pallets/flask --write   # D26 (needs GITHUB_TOKEN)

# D18 retrieval evaluation (optional: pip install fastembed; git on PATH)
cd backend && python scripts/retrieval_eval.py --repo <path> [--embed-model BAAI/bge-small-en-v1.5] [--no-embed]
```
