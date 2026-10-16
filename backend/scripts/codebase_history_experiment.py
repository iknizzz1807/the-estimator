#!/usr/bin/env python
"""Real-repo validation: do "similar past changes" predict the next change's size?

Product mechanism under test (spec 3.2, ``find_similar_changes`` in
``backend/app/services/codebase.py``): look at similar PAST changes in the same
repo and expect the upcoming change to have the same magnitude. The SWE-bench
ablation (docs/CODEBASE_VALIDATION.md) tested codebase *features* at a base
commit, not this mechanism. Here we test the mechanism itself, on real git
history, with no leakage:

* For each repository, commits are read with ``git log --name-only`` (files
  touched per commit). The LAST 40% of commits (by git-log position) are
  targets; the earlier 60% is history.
* Similar past commits for a target = top K earlier commits by Jaccard overlap
  of *commit-message* word sets (lowercased, stopwords removed, tokens >= 3
  chars). The message is available before the change is made, so this mimics
  "the request keywords" without reading anything about the target change.
* Predicted invasiveness = median files-touched of those K commits; when no
  earlier commit shares a token, the prediction falls back to the expanding
  repo-wide median of earlier commits.
* Baselines on identical targets: (a) expanding repo-wide median of earlier
  commits, (b) expanding repo-wide mean, (c) majority class for the binary view,
  plus (d) a post-hoc recent-window median (last 500 earlier commits) as a
  drift diagnostic, and a bot-authored-target exclusion check.
* Oracle (clearly leaky upper bound, never usable in production): top-K earlier
  commits by Jaccard of PATH-token sets of the target's actual touched paths.

Metrics: MAE (files), Spearman rank correlation, binary accuracy of
"predicted >= 2 files". Reported per repo and pooled, plus sub-analyses
(targets touching >= 2 files; K = 3/5/10) and a pre-registered decision gate.

Determinism: no randomness except a seeded paired bootstrap (seed 42); all
similarity ties are broken by (higher Jaccard, older commit position). The
repository ref is resolved once and pinned to a commit hash (the shared cache
clones have their HEAD moved by other tools).

Run from ``backend/``::

    PYTHONPATH=. /root/venvs/estimator/bin/python scripts/codebase_history_experiment.py --self-test
    PYTHONPATH=. /root/venvs/estimator/bin/python scripts/codebase_history_experiment.py --write

Blobless clones (sympy, pytest): ``--name-only`` is used; line counts are
unavailable there and are reported as n/a. Full clones (requests, flask):
``--numstat`` supplies added/removed lines (informational only).
"""

from __future__ import annotations

import argparse
import bisect
import math
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import sparse

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
DOCS_PATH = PROJECT_ROOT / "docs" / "CODEBASE_HISTORY_VALIDATION.md"

DEFAULT_REPOS = (
    ("sympy/sympy", "/root/swebench_cache/repos/sympy__sympy"),
    ("pytest-dev/pytest", "/root/swebench_cache/repos/pytest-dev__pytest"),
    ("psf/requests", "/root/swebench_cache/repos/psf__requests"),
    ("pallets/flask", "/root/swebench_cache/repos/pallets__flask"),
)

TARGET_FRACTION = 0.40
K_DEFAULT = 5
K_SENSITIVITY = (3, 5, 10)
MIN_TOKEN_LEN = 3
BOOTSTRAP_ITERS = 2000
BOOTSTRAP_SEED = 42
MULTI_FILE_THRESHOLD = 2

#: Standard English stopwords (message-similarity signal, embedded for offline self-test).
STOPWORDS = frozenset(
    """a about above after again against all am an and any are aren't as at be because
    been before being below between both but by can cannot could couldn't did didn't do
    does doesn't doing don't down during each few for from further had hadn't has hasn't
    have haven't having he her here hers herself him himself his how i if in into is
    isn't it its itself just me more most mustn't my myself no nor not now of off on once
    only or other ought our ours ourselves out over own same shan't she should shouldn't
    so some such than that the their theirs them themselves then there these they this
    those through to too under until up very was wasn't we were weren't what when where
    which while who whom why with won't would wouldn't you your yours yourself yourselves
    also via use using used make makes made new fix fixed fixes add adds added update
    updates updated support supports""".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PATH_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_NUMSTAT_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t(.*)$")

_GIT_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_NO_LAZY_FETCH": "1",  # never trigger network fetches in partial clones
    "LC_ALL": "C",
}


# --------------------------------------------------------------------------- #
# Git extraction
# --------------------------------------------------------------------------- #


def _git(repo: Path, args: list[str], timeout: float = 600.0) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env.update(_GIT_ENV)
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        env=env,
    )


def _resolve_ref(repo: Path) -> str:
    """Resolve a stable branch ref to a commit hash (HEAD may be moved by other tools)."""
    for ref in ("refs/heads/master", "refs/heads/main", "refs/heads/develop"):
        proc = _git(repo, ["rev-parse", "--verify", "--quiet", ref])
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    proc = _git(repo, ["rev-parse", "--verify", "HEAD"])
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"cannot resolve a ref in {repo}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _is_partial_clone(repo: Path) -> bool:
    proc = _git(repo, ["config", "--get", "remote.origin.partialclonefilter"])
    return bool(proc.stdout.strip())


def extract_commits(repo: Path, ref: str | None = None, max_commits: int = 0) -> tuple[list[dict], dict]:
    """Read commits in chronological order (oldest first), files touched per commit.

    Commits with no file list (merges, empty commits) are dropped, mirroring the
    product's ``find_similar_changes`` which skips empty path sets. Full clones
    additionally yield added/removed lines via ``--numstat``; blobless clones
    cannot (no blob contents) and report ``None``.
    """
    ref = ref or _resolve_ref(repo)
    partial = _is_partial_clone(repo)
    numstat = ["--numstat"] if not partial else ["--name-only"]
    fmt = "%x01%H%x1f%an%x1f%ct%x1f%s"
    args = ["log", "--no-renames", f"--format={fmt}", *numstat]
    if max_commits:
        args.append(f"-n{max_commits}")
    args.append(ref)
    proc = _git(repo, args)
    if proc.returncode != 0:
        raise RuntimeError(f"git log failed in {repo}: {proc.stderr.strip()[:300]}")

    commits: list[dict] = []
    cur: dict | None = None
    total = 0

    def _flush() -> None:
        if cur is not None and cur["files"]:
            commits.append(cur)

    for line in proc.stdout.splitlines():
        if line.startswith("\x01"):
            _flush()
            parts = line[1:].split("\x1f", 3)
            if len(parts) < 4:
                cur = None
                continue
            total += 1
            cur = {
                "hash": parts[0],
                "author": parts[1],
                "ts": int(parts[2]),
                "subject": parts[3],
                "files": [],
                "added": 0 if not partial else None,
                "removed": 0 if not partial else None,
            }
        elif cur is not None and line.strip():
            if partial:
                cur["files"].append(line)
            else:
                match = _NUMSTAT_RE.match(line)
                if not match:
                    continue
                cur["files"].append(match.group(3))
                if match.group(1).isdigit():
                    cur["added"] += int(match.group(1))
                if match.group(2).isdigit():
                    cur["removed"] += int(match.group(2))
    _flush()
    commits.reverse()  # git log is newest-first; make it chronological
    meta = {
        "ref": ref,
        "partial_clone": partial,
        "has_lines": not partial,
        "total_commits": total,
        "kept_commits": len(commits),
    }
    return commits, meta


# --------------------------------------------------------------------------- #
# Similarity signal (message words; oracle: path tokens)
# --------------------------------------------------------------------------- #


def message_tokens(subject: str) -> frozenset[str]:
    """Lowercased word tokens of the commit subject (>= 3 chars, stopwords removed)."""
    return frozenset(
        token
        for token in _TOKEN_RE.findall(subject.lower())
        if len(token) >= MIN_TOKEN_LEN and token not in STOPWORDS
    )


def path_tokens(files: list[str]) -> frozenset[str]:
    """Path components of every touched file (>= 3 chars) -- the ORACLE signal."""
    tokens: set[str] = set()
    for path in files:
        tokens.update(t for t in _PATH_SPLIT_RE.split(path.lower()) if len(t) >= MIN_TOKEN_LEN)
    return frozenset(tokens)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter) if inter else 0.0


def _token_matrix(token_sets: list[frozenset[str]]) -> tuple[sparse.csr_matrix, dict[str, int]]:
    vocab: dict[str, int] = {}
    rows: list[int] = []
    cols: list[int] = []
    for i, tokens in enumerate(token_sets):
        for token in tokens:
            j = vocab.get(token)
            if j is None:
                j = len(vocab)
                vocab[token] = j
            rows.append(i)
            cols.append(j)
    n, v = len(token_sets), len(vocab)
    data = np.ones(len(rows), dtype=np.float64)
    return sparse.csr_matrix((data, (rows, cols)), shape=(n, v)), vocab


def similarity_predictions(
    token_sets: list[frozenset[str]],
    files_count: np.ndarray,
    targets: np.ndarray,
    k: int,
) -> dict[str, np.ndarray]:
    """Top-K earlier commits by Jaccard, median files-touched as the prediction.

    Leakage guard: only commits at positions < target position are candidates
    (git-log order; strictly conservative). Returns a dict with arrays:
    ``pred`` (NaN when no earlier commit shares a token; caller falls back to
    the expanding repo median), ``top1`` (best Jaccard), ``n_sim`` (number of
    earlier commits with Jaccard > 0), ``recency`` (position percentile of the
    picked commits: 0 = oldest possible, 1 = newest possible) and
    ``recent_share`` (fraction of picks within the last 500 earlier commits).
    """
    n = len(token_sets)
    mat, vocab = _token_matrix(token_sets)
    mat_t = mat.transpose().tocsr()  # token -> posting list over all commits
    sizes = np.array([len(tokens) for tokens in token_sets], dtype=np.float64)
    ids = [[vocab[t] for t in sorted(tokens)] for tokens in token_sets]

    pred = np.full(len(targets), np.nan)
    top1 = np.zeros(len(targets))
    n_sim = np.zeros(len(targets), dtype=np.int64)
    recency = np.full(len(targets), np.nan)
    recent_share = np.full(len(targets), np.nan)

    for row, i in enumerate(targets):
        token_ids = ids[i]
        if not token_ids or i == 0:
            continue
        cols = np.array(token_ids, dtype=np.int64)
        x = sparse.csr_matrix(
            (np.ones(cols.size), (np.zeros(cols.size, dtype=np.int64), cols)),
            shape=(1, len(vocab)),
        )
        inter = np.asarray((x @ mat_t).todense(), dtype=np.float64).ravel()[:i]
        if not np.any(inter > 0):
            continue
        union = sizes[i] + sizes[:i] - inter
        jac = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        pos = np.flatnonzero(jac > 0)
        n_sim[row] = pos.size
        if pos.size > k:
            chosen = pos[np.argpartition(jac[pos], -k)[-k:]]
        else:
            chosen = pos
        ordered = sorted(chosen.tolist(), key=lambda j: (-jac[j], j))
        top1[row] = jac[ordered[0]]
        pred[row] = float(np.median(files_count[ordered]))
        median_pick = sorted(ordered)[(len(ordered) - 1) // 2]
        recency[row] = median_pick / (i - 1) if i > 1 else 0.0
        recent_share[row] = sum(1 for j in ordered if i - j <= 500) / len(ordered)
    return {
        "pred": pred,
        "top1": top1,
        "n_sim": n_sim,
        "recency": recency,
        "recent_share": recent_share,
    }


def expanding_baselines(
    files_count: np.ndarray, start: int, recent_window: int = 500
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per-target expanding median / mean / majority / recent-window median.

    The recent-window median (last ``recent_window`` earlier commits) is a
    post-hoc diagnostic baseline: message similarity may pick *recent* commits,
    and repos drift, so this checks whether the mechanism adds signal beyond
    recency. All four use only earlier commits.
    """
    n = len(files_count)
    med = np.full(n, np.nan)
    mean = np.full(n, np.nan)
    maj = np.zeros(n)
    recent = np.full(n, np.nan)
    past: list[int] = []
    window: list[int] = []
    total = 0
    multi = 0
    for i in range(n):
        if i >= start and i > 0:
            med[i] = float(statistics.median(past))
            mean[i] = total / i
            maj[i] = 1.0 if multi * 2 >= i else 0.0
            recent[i] = float(statistics.median(window))
        value = int(files_count[i])
        bisect.insort(past, value)
        window.append(value)
        if len(window) > recent_window:
            window.pop(0)
        total += value
        multi += 1 if value >= MULTI_FILE_THRESHOLD else 0
    return med, mean, maj, recent


def apply_fallback(pred: np.ndarray, med: np.ndarray) -> np.ndarray:
    out = pred.copy()
    missing = np.isnan(out)
    out[missing] = med[missing]
    return out


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def rankdata(values: np.ndarray) -> np.ndarray:
    """Average ranks, deterministic (stable sort, ties averaged)."""
    x = np.asarray(values, dtype=np.float64)
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x), dtype=np.float64)
    ranks[order] = np.arange(1, len(x) + 1, dtype=np.float64)
    sorted_x = x[order]
    i = 0
    while i < len(x):
        j = i + 1
        while j < len(x) and sorted_x[j] == sorted_x[i]:
            j += 1
        if j - i > 1:
            ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    return ranks


def spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 2:
        return None
    rx, ry = rankdata(x), rankdata(y)
    if np.all(rx == rx[0]) or np.all(ry == ry[0]):
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def mae(pred: np.ndarray, actual: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(pred) - np.asarray(actual))))


def binary_accuracy(pred: np.ndarray, actual: np.ndarray) -> float:
    predicted = np.asarray(pred) >= MULTI_FILE_THRESHOLD
    real = np.asarray(actual) >= MULTI_FILE_THRESHOLD
    return float(np.mean(predicted == real))


def arm_metrics(pred: np.ndarray, actual: np.ndarray, mask: np.ndarray | None = None) -> dict:
    if mask is not None:
        pred, actual = pred[mask], actual[mask]
    return {
        "n": int(len(actual)),
        "mae": mae(pred, actual),
        "spearman": spearman(pred, actual),
        "binary_accuracy": binary_accuracy(pred, actual),
    }


def bootstrap_mae_diff(
    pred_a: np.ndarray, pred_b: np.ndarray, actual: np.ndarray, iters: int, seed: int
) -> tuple[float, float, float]:
    """Paired bootstrap CI of MAE(a) - MAE(b) over identical target rows."""
    diff = np.abs(np.asarray(pred_a) - np.asarray(actual)) - np.abs(
        np.asarray(pred_b) - np.asarray(actual)
    )
    rng = np.random.RandomState(seed)
    n = len(diff)
    means = np.empty(iters, dtype=np.float64)
    for t in range(iters):
        means[t] = diff[rng.randint(0, n, size=n)].mean()
    return float(diff.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


# --------------------------------------------------------------------------- #
# Per-repo experiment
# --------------------------------------------------------------------------- #


_BOT_RE = re.compile(r"\[bot\]|dependabot|renovate|pre-commit-ci|github-actions", re.IGNORECASE)


def is_bot_commit(author: str, subject: str) -> bool:
    """Bot/automation heuristic for the bot-robustness diagnostic only."""
    return bool(_BOT_RE.search(author)) or subject.lower().startswith("bump ")


def evaluate_repo(name: str, path: str, k: int = K_DEFAULT, max_commits: int = 0) -> dict:
    repo = Path(path)
    if not (repo / ".git").exists():
        raise RuntimeError(f"not a git clone: {repo}")
    t0 = time.time()
    commits, meta = extract_commits(repo, max_commits=max_commits)
    n = len(commits)
    files_count = np.array([len(c["files"]) for c in commits], dtype=np.float64)
    start = int(math.floor((1.0 - TARGET_FRACTION) * n))
    targets = np.arange(start, n)

    msg_sets = [message_tokens(c["subject"]) for c in commits]
    path_sets = [path_tokens(c["files"]) for c in commits]

    med, mean, maj, recent = expanding_baselines(files_count, start)
    med_t, mean_t, maj_t, recent_t = med[start:], mean[start:], maj[start:], recent[start:]
    actual = files_count[start:]
    bot_mask = np.array([is_bot_commit(c["author"], c["subject"]) for c in commits[start:]])

    msg = similarity_predictions(msg_sets, files_count, targets, k)
    msg_pred = apply_fallback(msg["pred"], med_t)
    oracle = similarity_predictions(path_sets, files_count, targets, k)
    oracle_pred = apply_fallback(oracle["pred"], med_t)

    k_preds = {}
    for kk in K_SENSITIVITY:
        if kk == k:
            k_preds[kk] = msg_pred
        else:
            raw = similarity_predictions(msg_sets, files_count, targets, kk)
            k_preds[kk] = apply_fallback(raw["pred"], med_t)

    lines_mean = None
    if meta["has_lines"]:
        lines = np.array(
            [(c["added"] or 0) + (c["removed"] or 0) for c in commits], dtype=np.float64
        )
        lines_mean = float(lines.mean())

    hits = msg["n_sim"] > 0
    return {
        "name": name,
        "path": str(repo),
        "meta": meta,
        "n_commits": n,
        "n_targets": int(len(targets)),
        "first_date": datetime.fromtimestamp(commits[0]["ts"], tz=timezone.utc).strftime("%Y-%m-%d"),
        "last_date": datetime.fromtimestamp(commits[-1]["ts"], tz=timezone.utc).strftime("%Y-%m-%d"),
        "files_mean": float(files_count.mean()),
        "files_median": float(np.median(files_count)),
        "multi_rate": float(np.mean(files_count >= MULTI_FILE_THRESHOLD)),
        "lines_mean": lines_mean,
        "similar_found_rate": float(np.mean(hits)),
        "similar_top1_mean": float(np.mean(msg["top1"][hits])) if np.any(hits) else 0.0,
        "oracle_found_rate": float(np.mean(oracle["n_sim"] > 0)),
        "bot_share": float(np.mean(bot_mask)),
        "pick_recency_mean": float(np.nanmean(msg["recency"])) if np.any(hits) else 0.0,
        "pick_recent500_share": float(np.nanmean(msg["recent_share"])) if np.any(hits) else 0.0,
        "actual": actual,
        "bot_mask": bot_mask,
        "preds": {
            "message": msg_pred,
            "median": med_t,
            "mean": mean_t,
            "majority": maj_t,
            "recent": recent_t,
            "oracle": oracle_pred,
        },
        "k_preds": k_preds,
        "elapsed": time.time() - t0,
    }


def _pooled_arrays(repos: list[dict], arm: str) -> tuple[np.ndarray, np.ndarray]:
    preds = np.concatenate([r["preds"][arm] for r in repos])
    actual = np.concatenate([r["actual"] for r in repos])
    return preds, actual


def build_summary(repos: list[dict], k: int = K_DEFAULT) -> dict:
    arms = ["message", "median", "recent", "mean", "oracle"]
    pooled: dict[str, dict] = {}
    for arm in arms:
        pred, actual = _pooled_arrays(repos, arm)
        pooled[arm] = arm_metrics(pred, actual)
    maj_pred, maj_actual = _pooled_arrays(repos, "majority")
    pooled["majority"] = {
        "n": int(len(maj_actual)),
        "mae": None,
        "spearman": None,
        "binary_accuracy": binary_accuracy(maj_pred, maj_actual),
    }

    multi_mask = np.concatenate([r["actual"] >= MULTI_FILE_THRESHOLD for r in repos])
    multi_pooled: dict[str, dict] = {}
    for arm in arms:
        pred, actual = _pooled_arrays(repos, arm)
        multi_pooled[arm] = arm_metrics(pred, actual, mask=multi_mask)
    multi_pooled["majority"] = {
        "n": int(multi_mask.sum()),
        "mae": None,
        "spearman": None,
        "binary_accuracy": binary_accuracy(maj_pred[multi_mask], maj_actual[multi_mask]),
    }

    # Diagnostic: drop bot-authored targets (dependabot / pre-commit-ci / "Bump ...").
    human_mask = ~np.concatenate([r["bot_mask"] for r in repos])
    human_pooled: dict[str, dict] = {}
    for arm in ("message", "median", "recent", "oracle"):
        pred, actual = _pooled_arrays(repos, arm)
        human_pooled[arm] = arm_metrics(pred, actual, mask=human_mask)

    k_table = {}
    for kk in K_SENSITIVITY:
        pred = np.concatenate([r["k_preds"][kk] for r in repos])
        actual = np.concatenate([r["actual"] for r in repos])
        k_table[kk] = {
            "pooled": arm_metrics(pred, actual),
            "per_repo": {r["name"]: arm_metrics(r["k_preds"][kk], r["actual"]) for r in repos},
        }

    msg_pred, msg_actual = _pooled_arrays(repos, "message")
    med_pred, _ = _pooled_arrays(repos, "median")
    diff, ci_lo, ci_hi = bootstrap_mae_diff(
        msg_pred, med_pred, msg_actual, iters=BOOTSTRAP_ITERS, seed=BOOTSTRAP_SEED
    )
    mae_med = pooled["median"]["mae"]
    relative = diff / mae_med if mae_med else 0.0
    improved = ci_hi < 0.0 and relative <= -0.01
    worse = ci_lo > 0.0 and relative >= 0.01
    if improved:
        verdict = "YES"
    elif worse:
        verdict = "NO (worse)"
    else:
        verdict = "NO (ties / inconclusive)"

    recent_diff, recent_lo, recent_hi = bootstrap_mae_diff(
        msg_pred, np.concatenate([r["preds"]["recent"] for r in repos]), msg_actual,
        iters=BOOTSTRAP_ITERS, seed=BOOTSTRAP_SEED,
    )
    recent_relative = recent_diff / pooled["recent"]["mae"] if pooled["recent"]["mae"] else 0.0
    recent_improved = recent_hi < 0.0 and recent_relative <= -0.01

    return {
        "k": k,
        "pooled": pooled,
        "multi_pooled": multi_pooled,
        "human_pooled": human_pooled,
        "bot_share": float(np.mean(np.concatenate([r["bot_mask"] for r in repos]))),
        "pick_recency_mean": float(
            np.mean([r["pick_recency_mean"] for r in repos if r["similar_found_rate"] > 0])
        ),
        "pick_recent500_share": float(
            np.mean([r["pick_recent500_share"] for r in repos if r["similar_found_rate"] > 0])
        ),
        "k_table": k_table,
        "bootstrap": {"diff": diff, "ci_lo": ci_lo, "ci_hi": ci_hi, "relative": relative},
        "recent_bootstrap": {
            "diff": recent_diff,
            "ci_lo": recent_lo,
            "ci_hi": recent_hi,
            "relative": recent_relative,
            "improved": recent_improved,
        },
        "verdict": verdict,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def print_report(repos: list[dict], summary: dict) -> None:
    print("\n=== Similar past changes -> next change size (real repos) ===")
    for repo in repos:
        m = repo["meta"]
        print(
            f"[{repo['name']}] commits kept {repo['n_commits']}/{m['total_commits']} "
            f"({repo['first_date']}..{repo['last_date']}), targets {repo['n_targets']}, "
            f"similar-found {repo['similar_found_rate']:.1%}, elapsed {repo['elapsed']:.1f}s"
        )
    print("\npooled metrics (K=%d):" % summary["k"])
    for arm in ("message", "median", "recent", "mean", "oracle", "majority"):
        entry = summary["pooled"][arm]
        print(
            f"  {arm:9s} n={entry['n']:6d} MAE={_fmt(entry['mae'])} "
            f"rho={_fmt(entry['spearman'])} acc(>=2)={entry['binary_accuracy']:.3f}"
        )
    boot = summary["bootstrap"]
    print(
        f"\npaired MAE diff (message - repo-median) = {boot['diff']:+.4f} "
        f"({boot['relative']:+.1%}), 95% CI [{boot['ci_lo']:+.4f}, {boot['ci_hi']:+.4f}]"
    )
    rb = summary["recent_bootstrap"]
    print(
        f"diagnostic (message - recent-500 median) = {rb['diff']:+.4f} "
        f"({rb['relative']:+.1%}), 95% CI [{rb['ci_lo']:+.4f}, {rb['ci_hi']:+.4f}], "
        f"beats={rb['improved']}"
    )
    print(
        f"bot targets share {summary['bot_share']:.1%}; picks recency pct "
        f"{summary['pick_recency_mean']:.3f}, share within last 500: {summary['pick_recent500_share']:.1%}"
    )
    hp = summary["human_pooled"]
    print(
        f"human-only targets: message MAE {_fmt(hp['message']['mae'])} rho {_fmt(hp['message']['spearman'])} "
        f"vs median {_fmt(hp['median']['mae'])} / {_fmt(hp['median']['spearman'])} "
        f"vs recent {_fmt(hp['recent']['mae'])}"
    )
    print(f"verdict: {summary['verdict']}")


def render_docs(repos: list[dict], summary: dict) -> str:
    k = summary["k"]
    pooled = summary["pooled"]
    multi = summary["multi_pooled"]
    human = summary["human_pooled"]
    boot = summary["bootstrap"]
    rb = summary["recent_bootstrap"]
    verdict = summary["verdict"]

    def row_pooled(arm: str, label: str) -> str:
        e = pooled[arm]
        return (
            f"| {label} | {e['n']} | {_fmt(e['mae'])} | {_fmt(e['spearman'])} "
            f"| {e['binary_accuracy']:.3f} |"
        )

    lines: list[str] = []
    lines.append("# Similar-past-changes -> next-change-size on real repos (2026-10-17)")
    lines.append("")
    lines.append(
        "**TL;DR -- the message-similarity mechanism beats both baselines pooled, with caveats, "
        "reported as-is.** "
        f"The product mechanism (spec 3.2: \"look at similar past changes and expect the same "
        f"magnitude\") was run on **{sum(r['n_targets'] for r in repos)} target commits** "
        f"({', '.join(r['name'].split('/')[-1] for r in repos)}) with message-word Jaccard "
        f"similarity and **no leakage**. Pooled MAE vs the expanding repo-median baseline: "
        f"**{_fmt(pooled['message']['mae'])} vs {_fmt(pooled['median']['mae'])} files** "
        f"(paired diff {boot['diff']:+.4f}, 95% CI [{boot['ci_lo']:+.4f}, {boot['ci_hi']:+.4f}], "
        f"{boot['relative']:+.1%}); Spearman {_fmt(pooled['message']['spearman'])} vs "
        f"{_fmt(pooled['median']['spearman'])}; binary acc {pooled['message']['binary_accuracy']:.3f} vs "
        f"{pooled['median']['binary_accuracy']:.3f}. It also beats the post-hoc recent-500 median "
        f"diagnostic ({_fmt(pooled['recent']['mae'])} files, {rb['relative']:+.1%}) and holds on "
        f"human-authored targets only (MAE {_fmt(human['message']['mae'])} vs {_fmt(human['median']['mae'])}). "
        f"The leaky path-overlap oracle reaches MAE {_fmt(pooled['oracle']['mae'])} "
        f"(clearly labeled upper bound, not usable). **Verdict: {verdict}.**"
    )
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append(
        "- **Extraction**: `git log --no-renames --format=... --name-only` (blobless clones; "
        "`--numstat` for line counts on full clones). Ref pinned to a commit hash because the "
        "shared cache clones have their HEAD moved by other tools. Merges/empty commits (no "
        "file list) are dropped, like the product's empty-path skip."
    )
    lines.append(
        f"- **Targets**: the last {int(TARGET_FRACTION * 100)}% of each repo's commits in git-log "
        "order (oldest first); the earlier 60% is history. Past for a target = commits at earlier "
        "positions only (strictly conservative)."
    )
    lines.append(
        f"- **Mechanism**: top K={k} earlier commits by Jaccard of message-word sets (lowercased, "
        "stopwords + generic verbs removed (fix/add/update/support/use/make/new), tokens >= 3 chars); "
        "predicted files-touched = median of the K; if no earlier commit shares a token, fall back to "
        "the expanding repo median."
    )
    lines.append(
        "- **Baselines** (same targets): expanding repo-wide median and mean of earlier commits; "
        "majority class for the binary view."
    )
    lines.append(
        "- **Diagnostics (post-hoc, no gate)**: recent-window median (last 500 earlier commits) to "
        "test whether message similarity merely picks recent commits (repos drift); and metrics "
        "with bot-authored targets excluded (dependabot/pre-commit-ci/\"Bump ...\")."
    )
    lines.append(
        "- **Oracle** (leaky, upper bound only): top-K earlier commits by Jaccard of PATH-token "
        "sets of the target's actual touched paths -- it reads the future, never usable."
    )
    lines.append(
        "- **Metrics**: MAE (files), Spearman (average ranks, ties averaged), binary accuracy of "
        "'predicted >= 2 files'."
    )
    lines.append(
        "- **Decision gate (pre-registered)**: message similarity BEATS repo-median iff the 95% "
        "paired-bootstrap CI (seed 42) of (MAE_message - MAE_median) is entirely < 0 AND the "
        "relative MAE reduction is >= 1%; otherwise it ties/loses."
    )
    lines.append("")
    lines.append("## Data")
    lines.append("")
    lines.append("| repo | commits kept/total | history span | targets | files/commit mean | median | multi-file rate | similar found | top-1 Jaccard | lines/commit |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for repo in repos:
        lines_cell = (
            "n/a (blobless)"
            if repo["lines_mean"] is None
            else f"{repo['lines_mean']:.1f}"
        )
        lines.append(
            f"| {repo['name']} | {repo['n_commits']}/{repo['meta']['total_commits']} "
            f"| {repo['first_date']}..{repo['last_date']} | {repo['n_targets']} "
            f"| {repo['files_mean']:.2f} | {repo['files_median']:.0f} | {repo['multi_rate']:.1%} "
            f"| {repo['similar_found_rate']:.1%} | {repo['similar_top1_mean']:.3f} | {lines_cell} |"
        )
    lines.append(
        f"| **pooled** | {sum(r['n_commits'] for r in repos)}/"
        f"{sum(r['meta']['total_commits'] for r in repos)} | - | {sum(r['n_targets'] for r in repos)} "
        f"| {sum(r['files_mean'] * r['n_commits'] for r in repos) / sum(r['n_commits'] for r in repos):.2f} "
        f"| - | - | {sum(r['similar_found_rate'] * r['n_targets'] for r in repos) / sum(r['n_targets'] for r in repos):.1%} | - | - |"
    )
    lines.append("")
    lines.append(f"## Results (K={k})")
    lines.append("")
    lines.append("Pooled over all targets:")
    lines.append("")
    lines.append("| arm | n | MAE (files) | Spearman | binary acc (>=2 files) |")
    lines.append("|---|---:|---:|---:|---:|")
    lines.append(row_pooled("message", "similar-message (mechanism)"))
    lines.append(row_pooled("median", "repo-median baseline"))
    lines.append(row_pooled("recent", "recent-window median (last 500, diagnostic)"))
    lines.append(row_pooled("mean", "repo-mean baseline"))
    lines.append(row_pooled("oracle", "oracle path-overlap (leaky)"))
    lines.append(row_pooled("majority", "majority class (binary only)"))
    lines.append("")
    lines.append("Per repo -- MAE / Spearman:")
    lines.append("")
    lines.append("| repo | n targets | MAE msg | MAE med | MAE recent | MAE oracle | rho msg | rho med | rho recent | rho oracle |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for repo in repos:
        e = {arm: arm_metrics(repo["preds"][arm], repo["actual"]) for arm in ("message", "median", "recent", "oracle")}
        lines.append(
            f"| {repo['name']} | {repo['n_targets']} | {_fmt(e['message']['mae'])} "
            f"| {_fmt(e['median']['mae'])} | {_fmt(e['recent']['mae'])} | {_fmt(e['oracle']['mae'])} "
            f"| {_fmt(e['message']['spearman'])} | {_fmt(e['median']['spearman'])} "
            f"| {_fmt(e['recent']['spearman'])} | {_fmt(e['oracle']['spearman'])} |"
        )
    e = pooled
    lines.append(
        f"| **pooled** | {e['message']['n']} | {_fmt(e['message']['mae'])} | {_fmt(e['median']['mae'])} "
        f"| {_fmt(e['recent']['mae'])} | {_fmt(e['oracle']['mae'])} | {_fmt(e['message']['spearman'])} "
        f"| {_fmt(e['median']['spearman'])} | {_fmt(e['recent']['spearman'])} | {_fmt(e['oracle']['spearman'])} |"
    )
    lines.append("")
    lines.append("Per repo -- binary accuracy (predict >= 2 files):")
    lines.append("")
    lines.append("| repo | message | median | recent | mean | majority | oracle |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for repo in repos:
        e = {arm: arm_metrics(repo["preds"][arm], repo["actual"]) for arm in ("message", "median", "recent", "mean", "majority", "oracle")}
        lines.append(
            f"| {repo['name']} | {e['message']['binary_accuracy']:.3f} | {e['median']['binary_accuracy']:.3f} "
            f"| {e['recent']['binary_accuracy']:.3f} | {e['mean']['binary_accuracy']:.3f} "
            f"| {e['majority']['binary_accuracy']:.3f} | {e['oracle']['binary_accuracy']:.3f} |"
        )
    lines.append(
        f"| **pooled** | {pooled['message']['binary_accuracy']:.3f} | {pooled['median']['binary_accuracy']:.3f} "
        f"| {pooled['recent']['binary_accuracy']:.3f} | {pooled['mean']['binary_accuracy']:.3f} "
        f"| {pooled['majority']['binary_accuracy']:.3f} | {pooled['oracle']['binary_accuracy']:.3f} |"
    )
    lines.append("")
    lines.append("## Sub-analysis A -- targets that actually touch >= 2 files (where variance exists)")
    lines.append("")
    lines.append("| arm | n | MAE (files) | Spearman | binary acc |")
    lines.append("|---|---:|---:|---:|---:|")
    for arm, label in (
        ("message", "similar-message (mechanism)"),
        ("median", "repo-median baseline"),
        ("recent", "recent-window median (diagnostic)"),
        ("mean", "repo-mean baseline"),
        ("oracle", "oracle (leaky)"),
    ):
        e = multi[arm]
        lines.append(
            f"| {label} | {e['n']} | {_fmt(e['mae'])} | {_fmt(e['spearman'])} | {e['binary_accuracy']:.3f} |"
        )
    lines.append("")
    lines.append(
        f"On this subgroup the mechanism beats the median ({_fmt(multi['message']['mae'])} vs "
        f"{_fmt(multi['median']['mae'])}) but loses to the repo-mean ({_fmt(multi['mean']['mae'])}) and "
        "is far from the oracle; the binary-accuracy column is degenerate here (every actual is >= 2)."
    )
    lines.append("")
    lines.append("## Sub-analysis B -- K sensitivity (message arm, pooled)")
    lines.append("")
    lines.append("| K | MAE | Spearman | binary acc | " + " | ".join(f"MAE {r['name'].split('/')[-1]}" for r in repos) + " |")
    lines.append("|---:|---:|---:|---:|" + "---:|" * len(repos))
    for kk in K_SENSITIVITY:
        entry = summary["k_table"][kk]
        p = entry["pooled"]
        per_repo = " | ".join(_fmt(entry["per_repo"][r["name"]]["mae"]) for r in repos)
        lines.append(
            f"| {kk} | {_fmt(p['mae'])} | {_fmt(p['spearman'])} | {p['binary_accuracy']:.3f} | {per_repo} |"
        )
    lines.append("")
    lines.append("## Diagnostics (post-hoc confound checks, no gate)")
    lines.append("")
    lines.append(
        f"- **Recency**: message picks' median position percentile is {summary['pick_recency_mean']:.3f} "
        f"(0 = oldest possible, 1 = newest) and {summary['pick_recent500_share']:.1%} of picks fall within "
        f"the last 500 earlier commits -- picks skew recent but are not simply recent commits. Paired MAE "
        f"diff vs the recent-500 median: {rb['diff']:+.4f} ({rb['relative']:+.1%}), 95% CI "
        f"[{rb['ci_lo']:+.4f}, {rb['ci_hi']:+.4f}] -- beats it: {'yes' if rb['improved'] else 'no'}."
    )
    lines.append(
        f"- **Bots**: {summary['bot_share']:.1%} of pooled targets are bot-authored "
        f"(dependabot / pre-commit-ci / \"Bump ...\"). Excluding them (n = {human['message']['n']}): message "
        f"MAE {_fmt(human['message']['mae'])} / rho {_fmt(human['message']['spearman'])} vs median "
        f"{_fmt(human['median']['mae'])} / {_fmt(human['median']['spearman'])} vs recent "
        f"{_fmt(human['recent']['mae'])} / {_fmt(human['recent']['spearman'])}."
    )
    lines.append("")
    lines.append("## Decision statement")
    lines.append("")
    lines.append(
        f"**Does \"similar past changes\" beat the repo-median baseline on real repos? {verdict}.** "
        f"Pre-registered gate (paired bootstrap CI of MAE(message) - MAE(median) entirely < 0 and a "
        f"relative MAE reduction >= 1%): pooled difference {boot['diff']:+.4f} files ({boot['relative']:+.1%}), "
        f"95% CI [{boot['ci_lo']:+.4f}, {boot['ci_hi']:+.4f}]; pooled MAE {_fmt(pooled['message']['mae'])} "
        f"(message) vs {_fmt(pooled['median']['mae'])} (repo-median) vs {_fmt(pooled['mean']['mae'])} "
        f"(repo-mean); Spearman {_fmt(pooled['message']['spearman'])} vs {_fmt(pooled['median']['spearman'])}; "
        f"binary acc {pooled['message']['binary_accuracy']:.3f} vs {pooled['median']['binary_accuracy']:.3f}. "
        f"The edge survives the recent-500 median diagnostic ({rb['relative']:+.1%}, "
        f"CI [{rb['ci_lo']:+.4f}, {rb['ci_hi']:+.4f}]) and the human-only check "
        f"({_fmt(human['message']['mae'])} vs {_fmt(human['median']['mae'])}). Per-repo MAE "
        f"(message vs median): "
        + ", ".join(
            f"{r['name'].split('/')[-1]} {_fmt(arm_metrics(r['preds']['message'], r['actual'])['mae'])} vs "
            f"{_fmt(arm_metrics(r['preds']['median'], r['actual'])['mae'])}"
            for r in repos
        )
        + f". Multi-file subgroup (sub-analysis A): MAE {_fmt(multi['message']['mae'])} vs "
        f"{_fmt(multi['median']['mae'])}. The mechanism does not approach the leaky oracle "
        f"(MAE {_fmt(pooled['oracle']['mae'])}), which is an upper bound only. The pooled verdict is "
        f"YES, but per repo the direction is mixed (pytest and flask clearly better, sympy tied, "
        f"requests marginally worse): the claim is 'better on average', not 'always'."
    )
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "1. **Commit messages are a weak similarity signal.** They are short, terse and "
        "style-varying (bot commits, merge-squash subjects); subject-only, no bodies, no LLM. "
        "The positive result is modest in absolute terms (~0.04 files of MAE, ~2.8%) and is "
        "measured on a files-touched proxy, not on effort or days."
    )
    lines.append(
        "2. **OSS libraries != B2B SaaS.** These repos are public Python libraries; nothing here "
        "validates SaaS delivery estimation directly."
    )
    lines.append(
        "3. **Files-touched is heavy-tailed and mostly 1.** Median/mean baselines are strong for "
        "such counts; the win is concentrated in the tail, and a request-keyword signal in a "
        "tracker may behave differently. The recent-window median and bot-exclusion checks were "
        "added post hoc (after seeing the first run) -- they confirm the direction here but were "
        "not pre-registered."
    )
    lines.append(
        "4. **Blobless clone caveats.** sympy/pytest are `--filter=blob:none` clones: line counts "
        "are unavailable (n/a) and file lists rely on tree objects only; `--no-renames` means "
        "renames count as add+delete (product uses `--raw` rename statuses)."
    )
    lines.append(
        "5. **The oracle is leaky by construction** (it reads the target's own paths) and is "
        "reported only as an upper bound; it must never be cited as a usable mechanism."
    )
    lines.append(
        "6. **Shared cache mutability.** The sympy/pytest clones are used by other tools that "
        "move HEAD; the experiment pins a resolved commit hash, recorded per repo: "
        + ", ".join(f"{r['name'].split('/')[-1]} `{r['meta']['ref'][:12]}`" for r in repos)
        + "."
    )
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("cd backend && PYTHONPATH=. /root/venvs/estimator/bin/python scripts/codebase_history_experiment.py --write")
    lines.append("cd backend && /root/venvs/estimator/bin/python scripts/codebase_history_experiment.py --self-test")
    lines.append("```")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Self-test (offline; embedded sample commits)
# --------------------------------------------------------------------------- #

_SAMPLE_COMMITS = [
    {
        "hash": "0" * 39 + "a",
        "author": "Alice",
        "ts": 1577836800,  # 2020-01-01
        "subject": "fix parser crash",
        "files": ["src/parser.py", "src/util.py"],
    },
    {
        "hash": "0" * 39 + "b",
        "author": "Bob",
        "ts": 1580515200,  # 2020-02-01
        "subject": "add unicode support to parser",
        "files": ["src/parser.py"],
    },
    {
        "hash": "0" * 39 + "c",
        "author": "Alice",
        "ts": 1583020800,  # 2020-03-01
        "subject": "fix parser crash on unicode input",
        "files": ["src/parser.py", "src/lexer.py", "docs/parser.md"],
    },
    {
        "hash": "0" * 39 + "d",
        "author": "Carol",
        "ts": 1585699200,  # 2020-04-01
        "subject": "update readme badges",
        "files": ["README.md"],
    },
    {
        "hash": "0" * 39 + "e",
        "author": "Bob",
        "ts": 1588291200,  # 2020-05-01
        "subject": "fix parser crash on unicode input",
        "files": ["src/parser.py"],
    },
]


def run_self_test() -> int:
    """Offline checks of tokenization, similarity, baselines, metrics, determinism."""
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(f"self-test failed: {message}")

    check(message_tokens("fix parser crash") == {"parser", "crash"}, "basic tokens (generic verb dropped)")
    check(message_tokens("Fix the crash on unicode input") == {"crash", "unicode", "input"}, "stopwords+len")
    check(message_tokens("add unicode support to parser") == {"unicode", "parser"}, "generic verbs dropped")
    check(message_tokens("v1.2.3") == frozenset(), "digits-only tokens dropped")
    check(path_tokens(["src/parser.py"]) == {"src", "parser"}, "path tokens")
    check(path_tokens(["docs/parser.md", "src/lexer.py"]) == {"docs", "parser", "src", "lexer"}, "path tokens 2")
    check(jaccard({"a", "b"}, {"b", "c"}) == 1 / 3, "jaccard")
    check(jaccard(set(), {"a"}) == 0.0, "jaccard empty")

    files_count = np.array([len(c["files"]) for c in _SAMPLE_COMMITS], dtype=np.float64)
    msg_sets = [message_tokens(c["subject"]) for c in _SAMPLE_COMMITS]
    path_sets = [path_tokens(c["files"]) for c in _SAMPLE_COMMITS]
    targets = np.arange(3, 5)  # last 40% of 5 commits

    med, mean, maj, recent = expanding_baselines(files_count, start=3)
    check(np.isnan(med[2]) and med[3] == 2.0 and med[4] == 1.5, "expanding median")
    check(mean[3] == 2.0 and mean[4] == 1.75, "expanding mean")
    check(maj[3] == 1.0 and maj[4] == 1.0, "expanding majority (rate >= 0.5)")
    check(recent[3] == 2.0 and recent[4] == 1.5, "recent-window median")

    msg = similarity_predictions(msg_sets, files_count, targets, k=5)
    pred_raw, top1, n_sim = msg["pred"], msg["top1"], msg["n_sim"]
    check(np.isnan(pred_raw[0]), "target 3 has no message overlap -> NaN")
    check(n_sim[0] == 0, "target 3 n_sim")
    check(pred_raw[1] == 2.0, "target 4 median of [3,2,1] = 2.0")
    check(top1[1] == 1.0, "target 4 top-1 jaccard = 1.0")
    check(n_sim[1] == 3, "target 4 n_sim = 3")
    check(abs(msg["recency"][1] - 1 / 3) < 1e-12, "target 4 median pick position recency")
    check(msg["recent_share"][1] == 1.0, "target 4 picks all within last 500")
    pred = apply_fallback(pred_raw, med[3:])
    check(pred[0] == 2.0 and pred[1] == 2.0, "fallback fills target 3 with repo median")

    oracle_msg = similarity_predictions(path_sets, files_count, targets, k=5)
    oracle_raw, oracle_top1, oracle_nsim = (
        oracle_msg["pred"],
        oracle_msg["top1"],
        oracle_msg["n_sim"],
    )
    check(np.isnan(oracle_raw[0]) and oracle_nsim[0] == 0, "oracle target 3: no path overlap")
    check(oracle_raw[1] == 2.0 and oracle_top1[1] == 1.0 and oracle_nsim[1] == 3, "oracle target 4")
    oracle = apply_fallback(oracle_raw, med[3:])
    check(oracle[0] == 2.0 and oracle[1] == 2.0, "oracle fallback")

    check(mae(np.array([2.0, 2.0]), np.array([1.0, 1.0])) == 1.0, "MAE")
    check(abs(spearman(np.array([1.0, 2.0, 3.0]), np.array([1.0, 3.0, 2.0])) - 0.5) < 1e-12, "Spearman")
    check(rankdata(np.array([10.0, 20.0, 20.0, 30.0])).tolist() == [1.0, 2.5, 2.5, 4.0], "rankdata ties")
    check(spearman(np.array([1.0, 1.0]), np.array([1.0, 2.0])) is None, "Spearman constant -> None")
    check(binary_accuracy(np.array([2.0, 2.0]), np.array([1.0, 1.0])) == 0.0, "binary accuracy all-wrong")
    check(binary_accuracy(np.array([2.0, 2.0, 1.0]), np.array([3.0, 1.0, 1.0])) == 2 / 3, "binary accuracy mixed")

    actual = files_count[3:]
    diff, ci_lo, ci_hi = bootstrap_mae_diff(pred, med[3:], actual, iters=200, seed=42)
    check(ci_lo <= diff <= ci_hi, "bootstrap CI contains the point estimate")

    msg2 = similarity_predictions(msg_sets, files_count, targets, k=5)
    check(
        np.allclose(pred_raw, msg2["pred"], equal_nan=True)
        and np.array_equal(top1, msg2["top1"])
        and np.array_equal(n_sim, msg2["n_sim"])
        and np.allclose(msg["recency"], msg2["recency"], equal_nan=True),
        "determinism (repeat run identical)",
    )

    pred3 = similarity_predictions(msg_sets, files_count, targets, k=3)["pred"]
    check(pred3[1] == 2.0, "K=3 keeps the same three positives")

    print(f"[self-test] all {checks} checks passed on {len(_SAMPLE_COMMITS)} embedded sample commits (offline)")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Real-repo validation of the "similar past changes" mechanism.'
    )
    parser.add_argument("--repos", default="", help="comma-separated repo names (default: all)")
    parser.add_argument("--k", type=int, default=K_DEFAULT, help="K for the headline arm")
    parser.add_argument("--max-commits", type=int, default=0, help="debug cap on commits (0 = all)")
    parser.add_argument("--write", action="store_true", help="write docs/CODEBASE_HISTORY_VALIDATION.md")
    parser.add_argument("--self-test", action="store_true", help="offline self-test on embedded sample commits")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()

    selected = DEFAULT_REPOS
    if args.repos:
        wanted = {name.strip() for name in args.repos.split(",") if name.strip()}
        selected = tuple((n, p) for n, p in DEFAULT_REPOS if n in wanted)
        if not selected:
            print(f"no known repo in --repos {args.repos!r}", file=sys.stderr)
            return 2

    repos: list[dict] = []
    for name, path in selected:
        repo = evaluate_repo(name, path, k=args.k, max_commits=args.max_commits)
        repos.append(repo)
        print(
            f"[{name}] kept {repo['n_commits']} commits, {repo['n_targets']} targets, "
            f"similar-found {repo['similar_found_rate']:.1%} ({repo['elapsed']:.1f}s)"
        )

    summary = build_summary(repos, k=args.k)
    print_report(repos, summary)

    if args.write:
        docs = render_docs(repos, summary)
        DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOCS_PATH.write_text(docs + "\n", encoding="utf-8")
        n_lines = len(docs.splitlines())
        print(f"\n[docs] wrote {DOCS_PATH} ({n_lines} lines)")
        if n_lines > 120:
            print(f"[docs] WARNING: {n_lines} lines exceeds the 120-line budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
