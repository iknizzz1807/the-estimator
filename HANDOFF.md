# HANDOFF — The Estimator (2026-10-17)

> **For any new agent/model picking this project up.** Read this file first, then `docs/DECISIONS.md` (every design decision, D1–D18) and `README.md` (product + measured results). This file is the operational state of the world; it is updated by whoever finishes a work session.

## 0. TL;DR

- **Product is complete AND DEPLOYED**: 211 backend tests green, single-service app (FastAPI serves the static Next.js UI + API on one port), 240-project demo dataset, real DeepSeek extraction live.
- **Live app**: https://the-estimator-xqzc.onrender.com (Render web service, `0.5c-512mb` paid plan — no cold start; downgrade to Free or delete after ~22/10 to stop billing). Verified live 2026-10-17 (see §5).
- **GitHub**: https://github.com/iknizzz1807/the-estimator (public, `main` @ `915a810` + this handoff docs commit).
- **Local working copy (phone)**: `/sdcard/Documents/the-estimator` — `git pull` to sync the cafe-PC commits (Windows fixes, D17, UI copy fix, D18 retrieval spike + docs).
- **Next steps, in order**: (1) submit via the competition portal (paste live URL + repo URL; text in `docs/SUBMISSION.md`); (2) revoke tokens / rotate key (§8); (3) optional post-submission — wire the D18 retrieval panel exactly as §5b prescribes; (4) optional P2 (`unmapped_asks` capability warnings, §5b).
- **Deadline**: Sunday 2026-10-18 23:59 (self-imposed) / Monday 19-10 official. Competition: *Agent in the Shell* — Anduin Cybernetics, Challenge #2 "The Estimator".

## 1. What this is (one paragraph)

Paste a customer email/RFP → LLM (DeepSeek V4.1 Flash) extracts 15 binary project-complexity features with verbatim evidence → **math** (Ridge α=0.3 on log-days + split conformal prediction + Monte Carlo over unknowns) produces a calibrated **P10/P50/P90** range → ranked clarifying questions whose answers **shrink the range live** → budget-fit quote packages (Essential/Standard/Full + over-budget probability) → a pricing curve (quote-days → overrun risk) → optional **Codebase Lab** (repo friction + similar past changes widen the range; risk explanation only) → a learning loop (actuals retrain; mid-history drift proves adaptation) → walk-forward Replay + A/B proof screens. Runs fully offline with a deterministic stub; real LLM with a key.

Key docs: `README.md` · `docs/SPEC.md` (business spec) · `docs/API.md` (frozen contract incl. v0.2) · `docs/DECISIONS.md` (D1–D18) · `docs/SUBMISSION.md` (submission text EN+VI).

## 2. Git state

- `main` @ `915a810` + this handoff commit; cafe-PC session commits: `2d1d322` (Windows test/script fixes), `ab6519c` (D17 conditional `.git` copy), `00afecb` (honest answer-refinement copy), `39c5afb` + `7628f9e` (D18 retrieval spike + eval arms), `915a810` (D18 gate + validation doc), this commit (handoff §5b for the next agent).
- Note: the user runs parallel sessions (separate UI commits `ee90a07` "Linear-style UI" and `c648dc1` "guide + tour" landed mid-session). Pull before editing to avoid stepping on each other.
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
python -m pytest tests/ -q         # 211 tests, offline
docker build -f backend/Dockerfile -t the-estimator .   # full single-service image
```

### On the cafe Windows PC (session 2026-10-17)
- Python 3.12; backend venv at `backend\.venv` (Windows `Scripts\` layout — no bash: run uvicorn directly).
- No system git/node/docker (and Docker is not installable there); portable tools were used, no admin needed:
  - MinGit 2.56: `%LOCALAPPDATA%\Temp\opencode\git\mingit\cmd` (must be on PATH for Codebase Lab / git work).
  - Node 20.20.2: `%LOCALAPPDATA%\Temp\opencode\nodejs\node-v20.20.2-win-x64` (normal `npm ci && npm run build`; the D7 phone workarounds do not apply).
- Windows portability fixes committed in `2d1d322` (read-only git objects during force-rebuild; sqlite close in seed tests) — suite is 201/201 on Windows after them.
- Run: `$env:Path = "<mingit>\cmd;<node>;$env:Path"; cd backend; .\.venv\Scripts\python -m uvicorn app.main:app --port 8000`

## 4. What's built (map)

- **Backend** `backend/app/`: `api/routes.py` (all endpoints + SSE), `api/state.py` (pipeline, DB wiring, codebase block, reset, import), `services/`: `extraction.py` (LLM→features + evidence verification), `providers.py` (deepseek|gemini|openai|stub|distilled + truncated-JSON repair), `estimation.py` (Ridge + conformal + `estimate_mc`), `similarity.py`, `voi.py`, `learning.py`, `replay.py`, `ab.py`, `llm_baseline.py`, `packages.py`, `codebase.py`, `distilled.py`, `retrieval.py` (D18 spike: change retrieval — not wired into the pipeline); `data_gen/` (synthetic history DGP), `db/` (SQLite schema/helpers).
- **Frontend** `frontend/`: Next.js 15 static export; pages: `/` (onboarding), `/estimate` (SSE steps, feature cards, answers→refinement, packages, pricing curve, codebase panel, repo selector), `/history` (filters, Enter Actuals), `/proof` (replay chart, A/B with history baseline).
- **Scripts** `backend/scripts/`: `run_api.sh`, `build_demo_repos.py`, `extraction_eval.py`, `ab_measurement.py`, `swebench_validation.py`, `codebase_history_experiment.py`, `itemlet_validation.py`, `distillation_experiment.py`, `codebase_cli.py`, `seed_db.py`, `retrieval_eval.py` (D18 recall@k harness — `--embed-model` for arm A/B).
- **Data** `data/`: `synthetic_history.csv` (240 projects / 228 done, sha1 `b1df6f1b…`), `ground_truth.json` (never read by services), `tawos_subset.csv`, `distillation_labels.csv` + `distilled_model.joblib` (committed, 1 MB). `data/estimator.db` + `data/demo_repos/` are gitignored and auto-generated.

## 5. DEPLOY STATUS (where the world stands)

1. **GitHub** ✅ pushed (public) — `main` @ `915a810` (+ handoff docs). Description + topics set.
2. **Render** ✅ DEPLOYED AND LIVE: https://the-estimator-xqzc.onrender.com
   - Created as a **manual Web Service** (not Blueprint): Docker runtime, branch `main`, region Singapore, root dir empty, Dockerfile path `backend/Dockerfile`, health check `/api/health`, env vars `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY`.
   - Plan: **0.5c-512mb (~$7/mo, no cold start)** — Render bills per-second; downgrade to Free or delete after ~22/10 to stop billing (the $1 card verification is refunded). No cron-job.org needed while on this plan.
   - First deploy failed on `COPY .git` (Render's build context has no `.git`) → fixed in `ab6519c` (D17); redeploy green.
3. **Live verification** ✅ (2026-10-17, via API; see the session transcript): health `240 projects / deepseek / calibrated`; estimate scenario A `113.9/207.3/444.3`; Codebase Lab demo_a (friction low) vs demo_b (friction high, 5 similar changes); replay coverage 86.7% (189/218); packages (3 tiers + 25-point pricing curve; local audit: Full-tier over-budget agrees with the curve within 0.0004 at the same budget); A/B `mode:"real"`; reset restores 240. UI click-through left to the user (§6 boxes).
4. **Next**: paste the live URL + repo URL into the submission (text ready in `docs/SUBMISSION.md`) and submit via the portal; **then revoke the GitHub token and rotate the DeepSeek key** (both were exposed during this session — see §8).

## 5b. D18 retrieval — state and the path forward (for the next agent)

**What it is**: a *locator/evidence* layer, NOT a second friction. Friction answers "how expensive is change in this repo, overall?"; retrieval answers "which files does this request touch, and what did similar past changes touch?". It does not add to friction, and it does not touch the estimate numbers.

**State (2026-10-17)**:
- Code: `backend/app/services/retrieval.py` (+ `tests/test_retrieval.py`, harness `scripts/retrieval_eval.py`). NOT imported by the live pipeline; fastembed is NOT in `requirements.txt` — zero runtime impact today.
- Gate **PASSED** (pre-registered): analog hit@10 0.650–0.807, locate hit@10 0.683–0.776 (flask + requests, 300 targets each); lexical-only already passes; embedding arms add +1.7–5.7pp. Numbers + limitations: `docs/RETRIEVAL_VALIDATION.md`; decision record: D18.
- Model A/B (measured, cafe PC): **`BAAI/bge-small-en-v1.5` stays the default** (~67 MB file; **~+190 MB RAM loaded — measured**; on the $7 plan, lexical-only is the safe deploy mode). jina-code: no measurable edge + OOM'd the locate probe (52 GB ONNX allocation attempt) — rejected. multilingual-MiniLM: tied on English, the only cheap VI-capable option — NOT adopted until a Vietnamese eval exists. BGE-M3: rejected for runtime RAM (0.6–2.2 GB, not in fastembed).
- Eval assets (cafe PC only, NOT committed): flask/requests full clones under `%LOCALAPPDATA%\Temp\opencode\eval-repos`; demo scripts under `%LOCALAPPDATA%\Temp\opencode`. Reproduce: `python scripts/retrieval_eval.py --repo <path> [--embed-model X] [--no-embed]` (optional `pip install fastembed` for embedding arms). Needs git on PATH (MinGit).

**Next actions, in order**:
1. Default (cheapest): nothing — retrieval stays a documented, gated result.
2. Wire the **display-only panel** (recommended if there is time): candidate files + top-3 analog commits (sha/date/files touched/scores) exposed via the `codebase` block and shown on the estimate page, labelled `retrieval — candidates, not a verdict`. Keep it OUT of the numeric adjustment. Lexical-only on Render.
3. P2 (independent of the above): deterministic capability inventory (dependency/import scan per taxonomy feature) + an `unmapped_asks` warning for out-of-taxonomy requests.
4. Numeric coupling (only if pursued deliberately): run the **pre-registered ablation** in `docs/RETRIEVAL_VALIDATION.md` — whole-repo friction vs friction computed on retrieval-selected files, in walk-forward replay; pass bar = `mae_system` improves ≥ 5% relative AND coverage stays inside 75–85%. Fail ⇒ the panel stays display-only forever; pass ⇒ record as D19, and only then may retrieval feed the estimate.

## 6. Live-test checklist (for the deployed URL)

> API-level equivalents verified live 2026-10-17 (§5). The boxes below are the human UI pass.

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
- Answer refinement: the *relative* spread always drops as unknowns resolve, but absolute width is not monotone (a scope-adding Yes raises P50 and can widen it); README §10 documents this and the in-app copy was made honest in `00afecb` (RangeCompare already showed the "+% — the answer added scope" chip).
- Codebase Lab does not answer "does the request fit this codebase" (gap review 2026-10-17); the D18 change-retrieval spike is done and its recall@k gate **PASSED** — state, model decisions and the ordered next actions live in **§5b**; numeric coupling requires the pre-registered ablation (`docs/RETRIEVAL_VALIDATION.md`).

## 8. Secrets & credentials map (WHERE, never WHAT)

| Secret | Where it lives | Action |
|---|---|---|
| `DEEPSEEK_API_KEY` | phone `.env` (gitignored) · Render env var · cafe-PC `.env` (this session) · user's notes | never commit; **it was pasted into a chat 2026-10-17 → rotate after submission** |
| GitHub push token (`ghp_…`, scope repo/workflow/write:packages) | pasted in chat; used for pushes from the cafe PC — credentials may still be stored in that PC's Windows Credential Manager | **revoke after submission** (GitHub → Settings → Developer settings → Tokens); clear the stored credential on the cafe PC (Control Panel → Credential Manager → `git:https://github.com`) |
| Render account | user's GitHub login | — |

Audit note: `git log --all --full-history -- .env` is empty; secret scans (D16) found no keys in tracked files. The cafe-PC `.env` holds a live key — delete it (or the whole checkout) before abandoning that machine.

## 9. Conventions for new agents

- **Ownership discipline**: one writer per file set per wave; commit only your own paths; never `git add -A` blindly; ASCII commit messages.
- **Tests**: keep them offline/deterministic (conftest forces the stub); `pytest tests/ -q` must stay green (211 today).
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

# D18 retrieval evaluation (optional: pip install fastembed for embedding arms; git on PATH)
cd backend && python scripts/retrieval_eval.py --repo <path> [--embed-model BAAI/bge-small-en-v1.5] [--no-embed]
```
