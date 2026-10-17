# HANDOFF — The Estimator (2026-10-17)

> **For any new agent/model picking this project up.** Read this file first, then `docs/DECISIONS.md` (every design decision, D1–D16) and `README.md` (product + measured results). This file is the operational state of the world; it is updated by whoever finishes a work session.

## 0. TL;DR

- **Product is complete and deploy-ready**: 201 backend tests green, single-service app (FastAPI serves the static Next.js UI + API on one port), 240-project demo dataset, real DeepSeek extraction live.
- **GitHub**: https://github.com/iknizzz1807/the-estimator (public, `main`).
- **Local working copy (phone)**: `/sdcard/Documents/the-estimator` — git tree clean.
- **Next steps**: Render deploy (§5) → live-URL test → submit → revoke the push token (§8).
- **Deadline**: Sunday 2026-10-18 23:59 (self-imposed) / Monday 19-10 official. Competition: *Agent in the Shell* — Anduin Cybernetics, Challenge #2 "The Estimator".

## 1. What this is (one paragraph)

Paste a customer email/RFP → LLM (DeepSeek V4.1 Flash) extracts 15 binary project-complexity features with verbatim evidence → **math** (Ridge α=0.3 on log-days + split conformal prediction + Monte Carlo over unknowns) produces a calibrated **P10/P50/P90** range → ranked clarifying questions whose answers **shrink the range live** → budget-fit quote packages (Essential/Standard/Full + over-budget probability) → a pricing curve (quote-days → overrun risk) → optional **Codebase Lab** (repo friction + similar past changes widen the range; risk explanation only) → a learning loop (actuals retrain; mid-history drift proves adaptation) → walk-forward Replay + A/B proof screens. Runs fully offline with a deterministic stub; real LLM with a key.

Key docs: `README.md` · `docs/SPEC.md` (business spec) · `docs/API.md` (frozen contract incl. v0.2) · `docs/DECISIONS.md` (D1–D16) · `docs/SUBMISSION.md` (submission text EN+VI).

## 2. Git state

- `main` @ `cbe851c` (before this handoff commit), 51 commits, working tree clean.
- History was rewritten once by an agent (amend + cherry-pick race fix); content-verified, no dangling objects (`git fsck` clean).
- Commit convention: ASCII messages, scoped prefixes (`feat(api):`, `fix(frontend):`, `docs:`, `chore(deploy):`).

## 3. Environment specifics

### On the phone (Android/Termux + PRoot Debian, where this was built)
- Python venv: `/root/venvs/estimator/bin/python` (numpy, pandas, scikit-learn, scipy, fastapi, uvicorn, httpx, rapidfuzz, rank-bm25, pydantic, pyarrow, radon, tiktoken, pytest).
- Run the app: `cd backend && PYTHON=/root/venvs/estimator/bin/python bash scripts/run_api.sh` → UI+API at `:8000`.
- **Frontend build workaround (D7/D12)**: `/sdcard` is FUSE (no symlinks, no mmap of native binaries). Build in `/root/est-build/frontend` (copy sources byte-identical, `rm -rf .next out` FIRST, `npm run build`), then copy `out/` back to `frontend/out`. `next.config.ts` uses `output: "export"`.
- git on `/sdcard` needs `safe.directory` (already configured globally) and `core.fileMode false` (set per repo).
- **Secrets**: repo-root `.env` (gitignored) holds `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY` — never print/commit it. `tests/conftest.py` forces `LLM_PROVIDER=stub` so pytest is offline/deterministic/free.

### On a computer (fresh clone — recommended for deploy work)
Standard flow, **no workarounds needed**:
```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
bash scripts/run_api.sh            # API-only unless frontend/out exists
cd ../frontend && npm install && npm run build   # builds frontend/out (served by FastAPI)
python -m pytest tests/ -q         # 201 tests, offline
docker build -f backend/Dockerfile -t the-estimator .   # full single-service image
```

## 4. What's built (map)

- **Backend** `backend/app/`: `api/routes.py` (all endpoints + SSE), `api/state.py` (pipeline, DB wiring, codebase block, reset, import), `services/`: `extraction.py` (LLM→features + evidence verification), `providers.py` (deepseek|gemini|openai|stub|distilled + truncated-JSON repair), `estimation.py` (Ridge + conformal + `estimate_mc`), `similarity.py`, `voi.py`, `learning.py`, `replay.py`, `ab.py`, `llm_baseline.py`, `packages.py`, `codebase.py`, `distilled.py`; `data_gen/` (synthetic history DGP), `db/` (SQLite schema/helpers).
- **Frontend** `frontend/`: Next.js 15 static export; pages: `/` (onboarding), `/estimate` (SSE steps, feature cards, answers→shrink, packages, pricing curve, codebase panel, repo selector), `/history` (filters, Enter Actuals), `/proof` (replay chart, A/B with history baseline).
- **Scripts** `backend/scripts/`: `run_api.sh`, `build_demo_repos.py`, `extraction_eval.py`, `ab_measurement.py`, `swebench_validation.py`, `codebase_history_experiment.py`, `itemlet_validation.py`, `distillation_experiment.py`, `codebase_cli.py`, `seed_db.py`.
- **Data** `data/`: `synthetic_history.csv` (240 projects / 228 done, sha1 `b1df6f1b…`), `ground_truth.json` (never read by services), `tawos_subset.csv`, `distillation_labels.csv` + `distilled_model.joblib` (committed, 1 MB). `data/estimator.db` + `data/demo_repos/` are gitignored and auto-generated.

## 5. DEPLOY STATUS (where the world stands)

1. **GitHub** ✅ pushed (public). Description + topics set.
2. **Render** — blueprint ready (`render.yaml`: one Docker web service, `backend/Dockerfile`, health `/api/health`, free plan). Steps for the user:
   - render.com → Sign in with GitHub → **New + → Blueprint** → pick `the-estimator` → Apply.
   - When prompted (or in Environment), set `DEEPSEEK_API_KEY` (the key lives in the phone `.env`, the Render dashboard prompt, and the user's notes — **never in git**). `LLM_PROVIDER=deepseek` is already the default in `render.yaml`; without a key the app gracefully falls back to the stub.
   - Build ≈ 8–10 min (node build + pip install). First request after deploy seeds 240 projects + trains + replay (~10 s). Free tier sleeps after 15 min idle → next hit ~30–60 s cold start.
3. **After deploy**: test the flows (§6 checklist), paste the live URL + repo URL into the submission (text ready in `docs/SUBMISSION.md`), submit via the competition portal before the deadline.
4. **Then revoke the GitHub push token** (it was pasted into a chat; see §8).

## 6. Live-test checklist (for the deployed URL)

- [ ] `/` loads → Onboarding → "Load Sample Data" scenario A runs SSE steps → populated Estimate screen
- [ ] Answer 2–3 questions (Yes/No) → range shrinks live (relative spread drops; `method` flips to `point` when fully answered)
- [ ] Enter a budget → 3 quote packages + over-budget % + recommendation; pricing curve slider responds
- [ ] Repo selector: Demo A vs Demo B → different ranges + friction panel with commit evidence
- [ ] History: filters, Enter Actuals on an open project → coefficient updates + accuracy delta
- [ ] Proof: Run Replay (chart + coverage 189/218) and A/B (real provider → `mode:"real"` badges)
- [ ] Reset demo data button restores 240 projects

## 7. Known issues (deliberate, reported-only)

- `/api/ab` treats `n=0` as default-10; re-submitting an actual is not idempotent (it re-applies a correction step — legitimate); `answers={}` persists a row (documented); `ImportCSVModal` error hint checks the wrong string; Reset doesn't clear `sessionStorage` estimate; `mock.ts` values are stale (offline-only mode, contract keys match).
- Codebase Lab: one-directional surcharge (never a discount); adjustment coefficients are demo-assumed (×0.30/×0.60 widening, ×0.35 invasiveness); positioning = **risk explanation** — the text-prediction claim failed on SWE-bench and is not made. Mechanism "similar past changes" IS validated (positive) on 29k real commits.
- DeepSeek occasionally returns JSON missing the final `}` → `parse_json_response` now repairs it; if extraction still fails after retries → all-null + review warning (by design, spec §9).
- README color claims that lacked committed artifacts were softened during the QA audit (see D16).

## 8. Secrets & credentials map (WHERE, never WHAT)

| Secret | Where it lives | Action |
|---|---|---|
| `DEEPSEEK_API_KEY` | phone `.env` (gitignored) · Render env var · user's notes | never commit; rotate if ever exposed |
| GitHub push token (`ghp_…`, scope repo/workflow/write:packages) | pasted in chat; used for the initial push only | **revoke after submission** (GitHub → Settings → Developer settings → Tokens) |
| Render account | user's GitHub login | — |

Audit note: `git log --all --full-history -- .env` is empty; secret scans (D16) found no keys in tracked files.

## 9. Conventions for new agents

- **Ownership discipline**: one writer per file set per wave; commit only your own paths; never `git add -A` blindly; ASCII commit messages.
- **Tests**: keep them offline/deterministic (conftest forces the stub); `pytest tests/ -q` must stay green (201 today).
- **Honesty bar**: no claim without committed evidence; every number in README/docs must match a `docs/*.md` artifact (see D14/D16). Decision gates: if an ablation fails, do not claim improvement.
- **Docs**: append a new `D17+` entry to `docs/DECISIONS.md` for any significant decision; keep `docs/API.md` in sync with the implemented contract.

## 10. Quick commands

```bash
# tests (offline)
cd backend && python -m pytest tests/ -q

# run locally (UI+API on :8000; UI needs frontend/out)
cd backend && bash scripts/run_api.sh

# rebuild UI (computer) / phone: see D7 dance
cd frontend && npm run build

# rebuild demo repos / reset demo DB
cd backend && python scripts/build_demo_repos.py --force
curl -X POST http://localhost:8000/api/reset
```
