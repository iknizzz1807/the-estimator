# Similar-past-changes -> next-change-size on real repos (2026-10-17)

**TL;DR -- the message-similarity mechanism beats both baselines pooled, with caveats, reported as-is.** The product mechanism (spec 3.2: "look at similar past changes and expect the same magnitude") was run on **29058 target commits** (sympy, pytest, requests, flask) with message-word Jaccard similarity and **no leakage**. Pooled MAE vs the expanding repo-median baseline: **1.478 vs 1.520 files** (paired diff -0.0420, 95% CI [-0.0602, -0.0222], -2.8%); Spearman 0.323 vs 0.034; binary acc 0.678 vs 0.607. It also beats the post-hoc recent-500 median diagnostic (1.515 files, -2.4%) and holds on human-authored targets only (MAE 1.518 vs 1.559). The leaky path-overlap oracle reaches MAE 0.881 (clearly labeled upper bound, not usable). **Verdict: YES.**

## Method

- **Extraction**: `git log --no-renames --format=... --name-only` (blobless clones; `--numstat` for line counts on full clones). Ref pinned to a commit hash because the shared cache clones have their HEAD moved by other tools. Merges/empty commits (no file list) are dropped, like the product's empty-path skip.
- **Targets**: the last 40% of each repo's commits in git-log order (oldest first); the earlier 60% is history. Past for a target = commits at earlier positions only (strictly conservative).
- **Mechanism**: top K=5 earlier commits by Jaccard of message-word sets (lowercased, stopwords + generic verbs removed (fix/add/update/support/use/make/new), tokens >= 3 chars); predicted files-touched = median of the K; if no earlier commit shares a token, fall back to the expanding repo median.
- **Baselines** (same targets): expanding repo-wide median and mean of earlier commits; majority class for the binary view.
- **Diagnostics (post-hoc, no gate)**: recent-window median (last 500 earlier commits) to test whether message similarity merely picks recent commits (repos drift); and metrics with bot-authored targets excluded (dependabot/pre-commit-ci/"Bump ...").
- **Oracle** (leaky, upper bound only): top-K earlier commits by Jaccard of PATH-token sets of the target's actual touched paths -- it reads the future, never usable.
- **Metrics**: MAE (files), Spearman (average ranks, ties averaged), binary accuracy of 'predicted >= 2 files'.
- **Decision gate (pre-registered)**: message similarity BEATS repo-median iff the 95% paired-bootstrap CI (seed 42) of (MAE_message - MAE_median) is entirely < 0 AND the relative MAE reduction is >= 1%; otherwise it ties/loses.

## Data

| repo | commits kept/total | history span | targets | files/commit mean | median | multi-file rate | similar found | top-1 Jaccard | lines/commit |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| sympy/sympy | 50755/63045 | 2007-07-19..2026-10-15 | 20302 | 2.51 | 1 | 43.0% | 99.1% | 0.559 | n/a (blobless) |
| pytest-dev/pytest | 13197/17820 | 2007-01-24..2026-10-13 | 5279 | 3.42 | 1 | 48.2% | 99.8% | 0.465 | n/a (blobless) |
| psf/requests | 4862/6495 | 2011-02-13..2026-09-21 | 1945 | 1.67 | 1 | 25.8% | 91.9% | 0.524 | 65.5 |
| pallets/flask | 3828/5562 | 2010-04-06..2026-10-07 | 1532 | 2.48 | 1 | 41.2% | 99.1% | 0.504 | 65.8 |
| **pooled** | 72642/92922 | - | 29058 | 2.62 | - | - | 98.7% | - | - |

## Results (K=5)

Pooled over all targets:

| arm | n | MAE (files) | Spearman | binary acc (>=2 files) |
|---|---:|---:|---:|---:|
| similar-message (mechanism) | 29058 | 1.478 | 0.323 | 0.678 |
| repo-median baseline | 29058 | 1.520 | 0.034 | 0.607 |
| recent-window median (last 500, diagnostic) | 29058 | 1.515 | 0.084 | 0.612 |
| repo-mean baseline | 29058 | 2.131 | 0.073 | 0.419 |
| oracle path-overlap (leaky) | 29058 | 0.881 | 0.746 | 0.848 |
| majority class (binary only) | 29058 | n/a | n/a | 0.610 |

Per repo -- MAE / Spearman:

| repo | n targets | MAE msg | MAE med | MAE recent | MAE oracle | rho msg | rho med | rho recent | rho oracle |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sympy/sympy | 20302 | 1.391 | 1.391 | 1.392 | 0.912 | 0.296 | n/a | 0.067 | 0.678 |
| pytest-dev/pytest | 5279 | 1.986 | 2.150 | 2.136 | 0.924 | 0.376 | 0.002 | 0.027 | 0.889 |
| psf/requests | 1945 | 0.817 | 0.791 | 0.791 | 0.409 | 0.205 | n/a | n/a | 0.792 |
| pallets/flask | 1532 | 1.722 | 1.985 | 1.933 | 0.913 | 0.364 | n/a | 0.124 | 0.846 |
| **pooled** | 29058 | 1.478 | 1.520 | 1.515 | 0.881 | 0.323 | 0.034 | 0.084 | 0.746 |

Per repo -- binary accuracy (predict >= 2 files):

| repo | message | median | recent | mean | majority | oracle |
|---|---:|---:|---:|---:|---:|---:|
| sympy/sympy | 0.675 | 0.622 | 0.622 | 0.378 | 0.622 | 0.821 |
| pytest-dev/pytest | 0.677 | 0.538 | 0.551 | 0.446 | 0.554 | 0.916 |
| psf/requests | 0.718 | 0.716 | 0.716 | 0.716 | 0.716 | 0.913 |
| pallets/flask | 0.676 | 0.498 | 0.550 | 0.502 | 0.498 | 0.900 |
| **pooled** | 0.678 | 0.607 | 0.612 | 0.419 | 0.610 | 0.848 |

## Sub-analysis A -- targets that actually touch >= 2 files (where variance exists)

| arm | n | MAE (files) | Spearman | binary acc |
|---|---:|---:|---:|---:|
| similar-message (mechanism) | 11342 | 3.332 | 0.162 | 0.482 |
| repo-median baseline | 11342 | 3.851 | 0.066 | 0.036 |
| recent-window median (diagnostic) | 11342 | 3.789 | 0.074 | 0.097 |
| repo-mean baseline | 11342 | 2.902 | 0.121 | 0.951 |
| oracle (leaky) | 11342 | 1.828 | 0.644 | 0.760 |

On this subgroup the mechanism beats the median (3.332 vs 3.851) but loses to the repo-mean (2.902) and is far from the oracle; the binary-accuracy column is degenerate here (every actual is >= 2).

## Sub-analysis B -- K sensitivity (message arm, pooled)

| K | MAE | Spearman | binary acc | MAE sympy | MAE pytest | MAE requests | MAE flask |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 1.557 | 0.315 | 0.672 | 1.446 | 2.177 | 0.828 | 1.810 |
| 5 | 1.478 | 0.323 | 0.678 | 1.391 | 1.986 | 0.817 | 1.722 |
| 10 | 1.455 | 0.339 | 0.678 | 1.363 | 1.971 | 0.806 | 1.716 |

## Diagnostics (post-hoc confound checks, no gate)

- **Recency**: message picks' median position percentile is 0.657 (0 = oldest possible, 1 = newest) and 24.5% of picks fall within the last 500 earlier commits -- picks skew recent but are not simply recent commits. Paired MAE diff vs the recent-500 median: -0.0371 (-2.4%), 95% CI [-0.0555, -0.0180] -- beats it: yes.
- **Bots**: 3.6% of pooled targets are bot-authored (dependabot / pre-commit-ci / "Bump ..."). Excluding them (n = 28017): message MAE 1.518 / rho 0.314 vs median 1.559 / 0.032 vs recent 1.552 / 0.086.

## Decision statement

**Does "similar past changes" beat the repo-median baseline on real repos? YES.** Pre-registered gate (paired bootstrap CI of MAE(message) - MAE(median) entirely < 0 and a relative MAE reduction >= 1%): pooled difference -0.0420 files (-2.8%), 95% CI [-0.0602, -0.0222]; pooled MAE 1.478 (message) vs 1.520 (repo-median) vs 2.131 (repo-mean); Spearman 0.323 vs 0.034; binary acc 0.678 vs 0.607. The edge survives the recent-500 median diagnostic (-2.4%, CI [-0.0555, -0.0180]) and the human-only check (1.518 vs 1.559). Per-repo MAE (message vs median): sympy 1.391 vs 1.391, pytest 1.986 vs 2.150, requests 0.817 vs 0.791, flask 1.722 vs 1.985. Multi-file subgroup (sub-analysis A): MAE 3.332 vs 3.851. The mechanism does not approach the leaky oracle (MAE 0.881), which is an upper bound only. The pooled verdict is YES, but per repo the direction is mixed (pytest and flask clearly better, sympy tied, requests marginally worse): the claim is 'better on average', not 'always'.

## Limitations

1. **Commit messages are a weak similarity signal.** They are short, terse and style-varying (bot commits, merge-squash subjects); subject-only, no bodies, no LLM. The positive result is modest in absolute terms (~0.04 files of MAE, ~2.8%) and is measured on a files-touched proxy, not on effort or days.
2. **OSS libraries != B2B SaaS.** These repos are public Python libraries; nothing here validates SaaS delivery estimation directly.
3. **Files-touched is heavy-tailed and mostly 1.** Median/mean baselines are strong for such counts; the win is concentrated in the tail, and a request-keyword signal in a tracker may behave differently. The recent-window median and bot-exclusion checks were added post hoc (after seeing the first run) -- they confirm the direction here but were not pre-registered.
4. **Blobless clone caveats.** sympy/pytest are `--filter=blob:none` clones: line counts are unavailable (n/a) and file lists rely on tree objects only; `--no-renames` means renames count as add+delete (product uses `--raw` rename statuses).
5. **The oracle is leaky by construction** (it reads the target's own paths) and is reported only as an upper bound; it must never be cited as a usable mechanism.
6. **Shared cache mutability.** The sympy/pytest clones are used by other tools that move HEAD; the experiment pins a resolved commit hash, recorded per repo: sympy `50e68debd256`, pytest `c9c19f8e62c1`, requests `611c6162cbc4`, flask `d086db856be1`.

## Reproduce

```bash
cd backend && PYTHONPATH=. /root/venvs/estimator/bin/python scripts/codebase_history_experiment.py --write
cd backend && /root/venvs/estimator/bin/python scripts/codebase_history_experiment.py --self-test
```
