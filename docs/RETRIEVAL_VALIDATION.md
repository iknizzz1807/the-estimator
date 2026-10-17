# Change-Retrieval Validation (D18 spike) — 2026-10-17

What was tested, how, and what passed. Companion to `docs/DECISIONS.md` D18.
Nothing in the live pipeline consumes this signal yet; the gate below is the
first step required before any integration.

## Question

Codebase Lab's structural friction answers "how expensive is change here?" but
not "**which files does this request touch, and have similar changes happened
before?**". The spike adds change retrieval (code chunks + commit analogs) and
this document registers its evaluation gate.

## Design (leakage-aware, mirrors `scripts/codebase_history_experiment.py` conventions)

* **Corpus**: `git ls-files` text files -> file chunks + top-level Python
  function/class chunks (path-boosted lexical text); commit docs from
  `git log --name-only` (subject + touched files).
* **Query**: the commit SUBJECT of a target commit (available before the
  change — a request proxy). Targets = newest 40% of commits with a usable
  subject and >= 1 touched file.
* **Probe 1 — analog commits (leakage-clean)**: rank earlier commits only
  (strictly-before date filter, re-checked in Python); `hit@k` = any touched
  file of the target appears in the union of top-k retrieved commits' files;
  `recall@k` = share of the target's files covered by that union.
* **Probe 2 — code locate (labelled biased proxy)**: rank chunks of the
  CURRENT tree (the target's own code is present — reports an upper-ish bound;
  kept because it mirrors the production query: request -> current codebase).
  Gold = target files that still exist at HEAD (skips reported).
* **Ranking**: BM25 + TF-IDF cosine (min-max normalized, 0.6/0.4), optional
  embedding arm (0.35/0.25/0.40). Deterministic; ties break on path/sha.
* **Pre-registered gate** (set before the flask/requests runs started):
  analog `hit@10 >= 0.50` AND locate `hit@10 >= 0.60` on at least two real
  repos with ~300 targets each.

## Results (real repos, real history, 2026-10-17)

Flask 5,562 commits / 300 targets (19 targets skipped in locate: gold file no
longer at HEAD); requests 6,495 commits / 300 targets (14 skipped).

| Metric | flask lexical | flask +bge-small | flask +jina-code | flask +multiling-MiniLM | requests lexical | requests +bge-small |
|---|---|---|---|---|---|---|
| analog hit@5 | 0.743 | 0.743 | 0.757 | 0.740 | 0.540 | 0.597 |
| analog hit@10 | 0.783 | 0.800 | 0.807 | 0.800 | 0.630 | 0.650 |
| analog recall@10 | 0.634 | 0.660 | 0.665 | 0.656 | 0.562 | 0.588 |
| locate hit@5 | 0.541 | 0.548 | n/a (OOM) | 0.555 | 0.678 | 0.699 |
| locate hit@10 | 0.673 | 0.683 | n/a (OOM) | 0.669 | 0.745 | 0.776 |
| locate MRR | 0.400 | 0.407 | n/a (OOM) | 0.430 | 0.552 | 0.571 |

This repository itself (58 commits, 23 targets — small sample): analog hybrid
hit@10 0.565, locate hybrid hit@10 0.870 / MRR 0.671 (lexical: 0.522 / 0.870 /
0.635). Caveat: this repo's history spans ~2 days, so the day-granularity
leakage guard discards same-day analysts for older targets — treat its numbers
as a smoke test, not evidence.

**Gate verdict: PASS** on both real repos (analog hit@10 0.650–0.807 >= 0.50;
locate hit@10 0.683–0.776 >= 0.60). Lexical-only already passes; embeddings add
a small consistent gain (analog hit@10 +1.7 to +5.7pp) and are kept optional.

## Embedding-model findings (the "do we need a code model?" question)

* **No code-specialized model delivered a measurable win.** jina-code's analog
  edge (+0.7pp hit@10 on 300 samples) is inside the noise band, and its locate
  probe **crashed**: ONNXRuntime attempted a 52 GB allocation (one 8192-ctx
  batch padded to the longest dense chunk) on a 16 GB machine. A 640 MB model
  that OOMs at default batching is disqualified for a 512 MB deploy target
  regardless of its benchmark pedigree.
* **Default stays `BAAI/bge-small-en-v1.5`** (384d, 67 MB): fastest to embed
  (~70 s for 5.5k commit docs), competitive everywhere measured.
* **Multilingual option**: `paraphrase-multilingual-MiniLM-L12-v2` (384d,
  220 MB) is statistically tied on English (MRR slightly higher on locate)
  and is the cheapest fastembed model that can embed **Vietnamese queries**
  (scenario B). It is NOT adopted yet: no Vietnamese retrieval evaluation
  exists — adopting it on language grounds alone would be a vibes claim.
* **BGE-M3 considered and rejected for runtime**: not in fastembed (needs
  custom ONNX registration) and 568M params (~0.6–2.2 GB) exceed the deploy
  RAM budget by itself. Revisit only with a larger plan or API-based query
  embedding.

## Honest limitations

* Queries here are **English commit subjects**; a real requirement sentence is
  longer, noisier, and possibly Vietnamese (untested — see above).
* Probe 2 is a **biased proxy** by construction (target code present in the
  current tree); probe 1 is the clean signal and is the one the gate leans on.
* Day-granularity leakage guard discards same-day earlier commits.
* `hit@k` over file SETS favors key files but a human still decides which
  candidates matter — this is a *locate* aid, not an automatic scope.

## Positioning (plain language): what this is and what it is not

* **Friction answers "how expensive is change in this repo, overall?"** — whole-repo
  structural signals (churn, fan-in, complexity, coverage, author concentration)
  that widen the interval and shift the median. It does not know what the
  request touches.
* **Retrieval answers "which files does this request touch, and what did similar
  past changes touch?"** — a locator/evidence layer. It is **not** a second
  friction, it does not add to friction, and it does not touch the estimate
  numbers. It ships (if wired) as an information panel: candidate files +
  analog commits (sha/date/files), each with its match scores, labelled
  `retrieval — candidates, not a verdict`.

Two levels of "better", kept apart on purpose:

1. **Locates the right place** — PROVEN and measured: hit@10 0.65–0.81 across
   flask/requests vs ~0 for random guessing. Useful for orientation.
2. **Makes the estimate more accurate** — NOT proven, therefore NOT used. No
   numeric coupling until the next gate passes.

## Next gate (proposed, pre-registered before running)

Targeted friction ablation, in walk-forward replay, same targets:
(a) current whole-repo friction vs (b) friction computed **only on the file
set retrieval selects**. Pre-registered pass bar: (b) improves `mae_system`
by >= 5% relative while coverage stays within the 75–85% band. Fail => the
panel stays display-only forever; pass => targeted friction becomes a D19
entry and only then may feed the estimate.

Reproduce: `backend/scripts/retrieval_eval.py --repo <path> [--embed-model X]`
(eval checkouts cached outside the repo, not committed).
