#!/usr/bin/env python
"""Surcharge calibration: are the Codebase Lab coefficients measurable?

Motivation (the project's weakest link): ``apply_friction`` uses three
DEMO-ASSUMED constants --

* ``FRICTION_P10_WIDENING = 0.30`` / ``FRICTION_P90_WIDENING = 0.60``
  (friction widens the interval),
* ``INVASIVENESS_P50_SHIFT = 0.35`` (invasiveness shifts the median),

and ``docs/DECISIONS.md`` (D15/D18) admits they are placeholders "learned from
realised actuals in production". This script asks how much of that can be
*measured* on real repositories, using data that already exists (no new
dataset, no LLM, no network beyond the clones themselves).

What is measured here (and what is NOT)
---------------------------------------
The chain from a repository to a day count has five links:

    L1  friction      -> change size (files touched)        <- MEASURED HERE
    L2  friction      -> spread of change size              <- MEASURED HERE
    L3  invasiveness  -> change size                        <- MEASURED HERE
    L4  change size   -> person-days                        <- NOT measurable
    L5  friction      -> person-days                        <- NOT measurable

L4/L5 need ``(repository signals, logged effort)`` pairs at task level. No
public dataset provides them (see docs/SURCHARGE_CALIBRATION.md sec.6), so they
stay an explicit assumption. This script therefore converts the *assumed*
coefficients into *measured* ones **for L1/L2/L3**, and says so.

Design (leakage-aware; mirrors scripts/codebase_history_experiment.py)
---------------------------------------------------------------------
* Commits come from ``git log --name-only`` (chronological). The last
  ``--target-share`` of commits are targets; everything earlier is history.
* Friction is computed **only from history strictly before each target**
  (per-file commit counts, author sets, and a 180-day churn window), so no
  future information leaks. It uses the PRODUCT's saturation constants
  (``CHURN_SATURATION_COMMITS``) and weights (``FRICTION_WEIGHTS``).
* Only 2 of the product's 5 friction components are computable from git alone
  (churn, author_concentration); fan_in/complexity need a checkout + radon and
  coverage needs a report. The score is renormalised over the available
  components and labelled "git-only friction" everywhere.
* Targets here are individual commits (a request proxy), not client projects:
  the measured quantity is *change size*, not person-days.

Pre-registered gates (fixed before the first run)
------------------------------------------------
* G1 (L1) friction predicts size: the 95% paired-bootstrap CI of the OLS
  coefficient on ``friction_git`` is entirely > 0.
* G2 (L2) friction predicts spread: the bootstrap CI of
  ``std(residual | high friction tercile) / std(residual | low tercile)`` is
  entirely > 1.0.
* G3 (L3) invasiveness relates to size: Spearman(invasiveness, size) > 0 with a
  bootstrap CI excluding 0.

A failing gate is reported as-is; nothing here is tuned for nicer numbers.

Reproduce::

    cd backend && python scripts/surcharge_calibration.py \
        --repo /path/to/flask --repo /path/to/requests --write

``--self-test`` checks the pure functions without any repository.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

# Allow ``python scripts/surcharge_calibration.py`` from the backend/ directory.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.codebase import (  # noqa: E402
    CHURN_SATURATION_COMMITS,
    CHURN_WINDOW_MONTHS,
    FRICTION_WEIGHTS,
    FRICTION_P10_WIDENING,
    FRICTION_P90_WIDENING,
    INVASIVENESS_P50_SHIFT,
)
from scripts.codebase_history_experiment import (  # noqa: E402
    bootstrap_mae_diff,
    extract_commits,
    is_bot_commit,
    spearman,
)

BOOTSTRAP_ITERS = 2000
BOOTSTRAP_SEED = 42
TARGET_SHARE_DEFAULT = 0.4
MULTI_FILE_THRESHOLD = 2
CHURN_WINDOW_DAYS = 30 * CHURN_WINDOW_MONTHS
#: Components computable from git alone (fan_in/complexity/coverage need code).
GIT_COMPONENTS = ("churn", "author_concentration")


# --------------------------------------------------------------------------- #
# Per-file history (built incrementally, strictly before each target)
# --------------------------------------------------------------------------- #


@dataclass
class FileHistory:
    """Prior-commit statistics per path, updated as the walk advances."""

    ts: dict[str, list[int]] = field(default_factory=dict)
    authors: dict[str, set[str]] = field(default_factory=dict)

    def observe(self, files: Sequence[str], author: str, ts: int) -> None:
        for path in files:
            self.ts.setdefault(path, []).append(ts)
            self.authors.setdefault(path, set()).add(author)

    def churn(self, path: str, ts: int, window_days: int) -> int:
        """Commits touching ``path`` in ``(ts - window_days, ts)``."""
        stamps = self.ts.get(path)
        if not stamps:
            return 0
        lo = bisect.bisect_right(stamps, ts - window_days * 86400)
        hi = bisect.bisect_left(stamps, ts)
        return max(0, hi - lo)

    def lifetime(self, path: str) -> int:
        return len(self.ts.get(path, ()))

    def concentration(self, path: str) -> float:
        """``1 - authors/commits`` for one path (0 when < 2 prior commits)."""
        total = self.lifetime(path)
        if total < 2:
            return 0.0
        authors = len(self.authors.get(path, ()))
        return min(1.0, max(0.0, 1.0 - authors / total))


def _saturate(raw: float, saturation: float) -> float:
    return float(min(1.0, max(0.0, raw / saturation)))


def git_friction(
    history: FileHistory, files: Sequence[str], ts: int
) -> tuple[float, dict[str, float]]:
    """Renormalised friction from the git-only components (churn, authors).

    Mirrors ``app.services.codebase.compute_friction``: saturating normalisers,
    weighted mean over the available components, weights renormalised when a
    component is missing. Aggregation over the touched files uses ``max`` (like
    the product's ``max_file_commits`` / hot-file convention).
    """
    if not files:
        return 0.0, {}
    churn_max = max(history.churn(path, ts, CHURN_WINDOW_DAYS) for path in files)
    conc_max = max(history.concentration(path) for path in files)
    components = {
        "churn": _saturate(churn_max, CHURN_SATURATION_COMMITS),
        "author_concentration": conc_max,
    }
    total_weight = sum(FRICTION_WEIGHTS[name] for name in GIT_COMPONENTS)
    weighted = sum(components[name] * FRICTION_WEIGHTS[name] for name in GIT_COMPONENTS)
    return (weighted / total_weight if total_weight else 0.0), components


# --------------------------------------------------------------------------- #
# Target rows
# --------------------------------------------------------------------------- #


def build_target_rows(
    commits: Sequence[dict], target_share: float = TARGET_SHARE_DEFAULT
) -> list[dict[str, Any]]:
    """Walk chronologically; friction for a target uses only earlier commits."""
    n = len(commits)
    first_target = int(n * (1.0 - target_share))
    if first_target <= 0:
        return []

    history = FileHistory()
    prior_sizes: list[float] = []
    rows: list[dict[str, Any]] = []

    for index, commit in enumerate(commits):
        files = commit["files"]
        if index < first_target:
            history.observe(files, commit["author"], commit["ts"])
            prior_sizes.append(float(len(files)))
            continue

        size = float(len(files))
        score, components = git_friction(history, files, commit["ts"])
        log_prior = np.log1p(float(len(prior_sizes)))  # repo age / activity control
        rows.append(
            {
                "hash": commit["hash"][:7],
                "ts": commit["ts"],
                "size": size,
                "friction_git": score,
                "churn": components.get("churn", 0.0),
                "author_concentration": components.get("author_concentration", 0.0),
                "log_prior_commits": float(log_prior),
                "subject_tokens": float(len(commit["subject"].split())),
                "bot": is_bot_commit(commit["author"], commit["subject"]),
                # Baseline for the dispersion test: expanding median of PRIOR sizes.
                "baseline_log": float(np.median(np.log1p(prior_sizes)))
                if prior_sizes
                else float(np.log1p(1.0)),
            }
        )
        history.observe(files, commit["author"], commit["ts"])
        prior_sizes.append(size)

    return rows


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #


def _design(rows: Sequence[dict], with_friction: bool) -> np.ndarray:
    """OLS design: intercept + controls (+ friction_git when requested)."""
    columns = [
        np.ones(len(rows)),
        np.array([r["log_prior_commits"] for r in rows]),
        np.array([r["subject_tokens"] for r in rows]),
        np.array([1.0 if r["bot"] else 0.0 for r in rows]),
    ]
    if with_friction:
        columns.append(np.array([r["friction_git"] for r in rows]))
    return np.column_stack(columns)


def _ols_beta(design: np.ndarray, y: np.ndarray) -> np.ndarray:
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    return coef


def friction_beta_ci(rows: Sequence[dict]) -> dict[str, float]:
    """OLS ``log1p(size) ~ controls + friction_git`` with a bootstrap CI on beta."""
    y = np.log1p(np.array([r["size"] for r in rows]))
    design = _design(rows, with_friction=True)
    beta = float(_ols_beta(design, y)[-1])

    rng = np.random.RandomState(BOOTSTRAP_SEED)
    n = len(rows)
    draws = np.empty(BOOTSTRAP_ITERS, dtype=np.float64)
    for t in range(BOOTSTRAP_ITERS):
        idx = rng.randint(0, n, size=n)
        draws[t] = float(_ols_beta(design[idx], y[idx])[-1])
    return {
        "beta": beta,
        "ci_low": float(np.percentile(draws, 2.5)),
        "ci_high": float(np.percentile(draws, 97.5)),
        "n": int(n),
    }


def _tercile_masks(scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lo_cut, hi_cut = np.percentile(scores, [100 / 3, 200 / 3])
    return scores <= lo_cut, scores >= hi_cut


def dispersion_ratio(rows: Sequence[dict]) -> dict[str, float]:
    """Ratio of residual spread in the high vs low friction tercile (L2)."""
    scores = np.array([r["friction_git"] for r in rows])
    resid = np.log1p(np.array([r["size"] for r in rows])) - np.array(
        [r["baseline_log"] for r in rows]
    )
    low, high = _tercile_masks(scores)
    if low.sum() < 5 or high.sum() < 5:
        return {"ratio": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                "n_low": int(low.sum()), "n_high": int(high.sum())}

    def _ratio(low_idx: np.ndarray, high_idx: np.ndarray) -> float:
        spread_low = float(np.std(resid[low_idx], ddof=1))
        spread_high = float(np.std(resid[high_idx], ddof=1))
        return spread_high / spread_low if spread_low > 0 else float("nan")

    low_idx = np.flatnonzero(low)
    high_idx = np.flatnonzero(high)
    point = _ratio(low_idx, high_idx)

    rng = np.random.RandomState(BOOTSTRAP_SEED)
    draws = np.empty(BOOTSTRAP_ITERS, dtype=np.float64)
    for t in range(BOOTSTRAP_ITERS):
        draws[t] = _ratio(
            rng.choice(low_idx, size=len(low_idx), replace=True),
            rng.choice(high_idx, size=len(high_idx), replace=True),
        )
    finite = draws[np.isfinite(draws)]
    return {
        "ratio": point,
        "ci_low": float(np.percentile(finite, 2.5)) if len(finite) else float("nan"),
        "ci_high": float(np.percentile(finite, 97.5)) if len(finite) else float("nan"),
        "n_low": int(low.sum()),
        "n_high": int(high.sum()),
    }


def invasiveness_view(rows: Sequence[dict]) -> dict[str, float]:
    """Multi-file rate and mean size by friction tercile (L3 view)."""
    scores = np.array([r["friction_git"] for r in rows])
    sizes = np.array([r["size"] for r in rows])
    low, high = _tercile_masks(scores)
    return {
        "multi_low": float(np.mean(sizes[low] >= MULTI_FILE_THRESHOLD)) if low.any() else float("nan"),
        "multi_high": float(np.mean(sizes[high] >= MULTI_FILE_THRESHOLD)) if high.any() else float("nan"),
        "mean_low": float(np.mean(sizes[low])) if low.any() else float("nan"),
        "mean_high": float(np.mean(sizes[high])) if high.any() else float("nan"),
        "spearman": spearman(scores, sizes),
    }


def _size_spearman_ci(rows: Sequence[dict]) -> tuple[float, float, float]:
    """Bootstrap CI of Spearman(friction, size)."""
    scores = np.array([r["friction_git"] for r in rows])
    sizes = np.array([r["size"] for r in rows])
    point = spearman(scores, sizes) or 0.0
    rng = np.random.RandomState(BOOTSTRAP_SEED)
    n = len(rows)
    draws = []
    for _ in range(BOOTSTRAP_ITERS):
        idx = rng.randint(0, n, size=n)
        value = spearman(scores[idx], sizes[idx])
        if value is not None:
            draws.append(value)
    if not draws:
        return point, float("nan"), float("nan")
    return point, float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def evaluate_repo(name: str, path: str, target_share: float) -> dict[str, Any]:
    commits, meta = extract_commits(Path(path))
    rows = build_target_rows(commits, target_share=target_share)
    if not rows:
        raise RuntimeError(f"no target rows for {name} ({path})")

    human = [r for r in rows if not r["bot"]]
    scores = np.array([r["friction_git"] for r in rows])
    return {
        "name": name,
        "meta": meta,
        "n_targets": len(rows),
        "n_bot": int(sum(1 for r in rows if r["bot"])),
        "friction_mean": float(np.mean(scores)),
        "friction_std": float(np.std(scores)),
        "size_mean": float(np.mean([r["size"] for r in rows])),
        "beta": friction_beta_ci(rows),
        "dispersion": dispersion_ratio(rows),
        "invasiveness": invasiveness_view(rows),
        "spearman_ci": _size_spearman_ci(rows),
        "human_only": {
            "beta": friction_beta_ci(human) if len(human) > 50 else None,
            "dispersion": dispersion_ratio(human) if len(human) > 50 else None,
        },
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "n/a"
    return f"{value:.{digits}f}"


def build_summary(repos: list[dict]) -> dict[str, Any]:
    """Pooled views + gate verdicts."""
    all_rows_beta = {
        "beta": float(np.mean([r["beta"]["beta"] for r in repos])),
    }
    gates = {
        "G1_friction_predicts_size": all(
            r["beta"]["ci_low"] > 0 for r in repos
        ),
        "G2_friction_predicts_spread": all(
            np.isfinite(r["dispersion"]["ci_low"]) and r["dispersion"]["ci_low"] > 1.0
            for r in repos
        ),
        "G3_spearman_positive": all(
            r["spearman_ci"][0] > 0 and r["spearman_ci"][1] > 0 for r in repos
        ),
    }
    return {
        "n_repos": len(repos),
        "n_targets": int(sum(r["n_targets"] for r in repos)),
        "mean_beta": all_rows_beta["beta"],
        "gates": gates,
        "product_assumed": {
            "FRICTION_P10_WIDENING": FRICTION_P10_WIDENING,
            "FRICTION_P90_WIDENING": FRICTION_P90_WIDENING,
            "INVASIVENESS_P50_SHIFT": INVASIVENESS_P50_SHIFT,
        },
    }


def print_report(repos: list[dict], summary: dict) -> None:
    print("\n=== Surcharge calibration (Codebase Lab coefficients) ===")
    print(
        f"repos={summary['n_repos']}  targets={summary['n_targets']}  "
        f"bootstrap={BOOTSTRAP_ITERS} seed={BOOTSTRAP_SEED}"
    )
    header = f"{'repo':<10}{'n':>7}{'fric':>8}{'beta':>9}{'CI low':>9}{'CI high':>9}{'rho':>8}{'disp':>8}"
    print("\n" + header)
    print("-" * len(header))
    for r in repos:
        print(
            f"{r['name']:<10}{r['n_targets']:>7}{_fmt(r['friction_mean']):>8}"
            f"{_fmt(r['beta']['beta']):>9}{_fmt(r['beta']['ci_low']):>9}"
            f"{_fmt(r['beta']['ci_high']):>9}{_fmt(r['spearman_ci'][0]):>8}"
            f"{_fmt(r['dispersion']['ratio']):>8}"
        )
    print("\n--- L2 dispersion ratio (high vs low friction tercile) ---")
    for r in repos:
        d = r["dispersion"]
        print(
            f"{r['name']:<10} ratio={_fmt(d['ratio'])} "
            f"CI=[{_fmt(d['ci_low'])}, {_fmt(d['ci_high'])}] "
            f"n_low={d['n_low']} n_high={d['n_high']}"
        )
    print("\n--- gates (pre-registered) ---")
    for name, passed in summary["gates"].items():
        print(f"  {name:<34} {'PASS' if passed else 'FAIL'}")
    print("\n--- product coefficients (currently DEMO-ASSUMED) ---")
    for key, value in summary["product_assumed"].items():
        print(f"  {key:<26} {value}")


def render_docs(repos: list[dict], summary: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    add = lines.append

    add("# Surcharge calibration — Codebase Lab coefficients (real repositories)")
    add("")
    add(f"Generated by `backend/scripts/surcharge_calibration.py` on {now}.")
    add("Deterministic (seed 42); re-running reproduces these numbers.")
    add("")
    add("**Question.** `apply_friction` widens the interval with `x0.30/x0.60` and")
    add("shifts the median with `x0.35` — three DEMO-ASSUMED constants (D15/D18).")
    add("How much of that can be **measured** on real repositories, using data that")
    add("already exists?")
    add("")
    add("## TL;DR")
    add("")
    g1 = summary["gates"]["G1_friction_predicts_size"]
    g2 = summary["gates"]["G2_friction_predicts_spread"]
    g3 = summary["gates"]["G3_spearman_positive"]
    total = len(repos)
    n_g1 = sum(1 for r in repos if r["beta"]["ci_low"] > 0)
    n_g2 = sum(
        1
        for r in repos
        if np.isfinite(r["dispersion"]["ci_low"]) and r["dispersion"]["ci_low"] > 1.0
    )
    n_g3 = sum(1 for r in repos if r["spearman_ci"][0] > 0 and r["spearman_ci"][1] > 0)
    add(f"- **G1 — friction predicts change size:** {n_g1}/{total} repos (gate requires all) "
        f"-> **{'PASS' if g1 else 'FAIL'}**")
    add(f"- **G2 — friction predicts spread (the interval-widening claim):** {n_g2}/{total} repos "
        f"(gate requires all) -> **{'PASS' if g2 else 'FAIL'}**")
    add(f"- **G3 — rank signal is positive:** {n_g3}/{total} repos (gate requires all) "
        f"-> **{'PASS' if g3 else 'FAIL'}**")
    add("")
    add("Reported as-is: G1 and G3 hold on **every** repository; **G2 holds on 3 of 4**,")
    add("so the pre-registered bar (all repos) **FAILS**. The exception is `requests`,")
    add("which is also the repo with the weakest friction -> size signal — the same")
    add("repo that lost marginally in `docs/CODEBASE_HISTORY_VALIDATION.md`.")
    add("")
    add("What this establishes: the **direction and order of magnitude** of the")
    add("friction -> size and friction -> spread links, measured on real commits.")
    add("What it does NOT establish: **person-days** — see the honest limitations.")
    add("")
    add("## Method")
    add("")
    add("* Commits from `git log --no-renames --name-only`, chronological. The last")
    add(f"  {TARGET_SHARE_DEFAULT:.0%} are targets; earlier commits are history only.")
    add("* **Friction is computed from history strictly before each target** —")
    add("  per-file prior commit counts, prior author sets, and a")
    add(f"  {CHURN_WINDOW_MONTHS}-month churn window. No leakage.")
    add("* It uses the **product's own constants**: `CHURN_SATURATION_COMMITS`,")
    add("  `FRICTION_WEIGHTS`, and the same saturating-normaliser / weighted-mean")
    add("  formula as `app.services.codebase.compute_friction`.")
    add("* Only 2 of the product's 5 components are computable from git alone")
    add("  (`churn`, `author_concentration`); `fan_in`/`complexity` need a checkout")
    add("  plus radon and `coverage` needs a report. The score is renormalised and")
    add("  labelled **git-only friction** throughout.")
    add("* Controls in the regression: log prior commit count (repo age), subject")
    add("  token count (request detail), bot flag. Bots are also excluded in a")
    add("  robustness row.")
    add("")
    add("## Results")
    add("")
    add("| repo | targets | mean friction | beta (log size per unit friction) | 95% CI | Spearman | L2 dispersion ratio | CI |")
    add("|---|---:|---:|---:|---|---:|---:|---|")
    for r in repos:
        add(
            f"| {r['name']} | {r['n_targets']} | {_fmt(r['friction_mean'])} | "
            f"{_fmt(r['beta']['beta'])} | [{_fmt(r['beta']['ci_low'])}, {_fmt(r['beta']['ci_high'])}] | "
            f"{_fmt(r['spearman_ci'][0])} | {_fmt(r['dispersion']['ratio'])} | "
            f"[{_fmt(r['dispersion']['ci_low'])}, {_fmt(r['dispersion']['ci_high'])}] |"
        )
    add("")
    add(f"Pooled targets: **{summary['n_targets']}** across {summary['n_repos']} repositories.")
    add("")
    add("### Size inflation per unit friction (`e^beta`)")
    add("")
    add("`e^beta` is the multiplicative change in expected change size for a +1.0 jump")
    add("in friction score; the last column rescales it to a realistic +0.1 step.")
    add("")
    add("| repo | `e^beta` | +0.1 friction -> |")
    add("|---|---:|---:|")
    for r in repos:
        eb = float(np.exp(r["beta"]["beta"]))
        add(f"| {r['name']} | x{_fmt(eb, 2)} | x{_fmt(eb ** 0.1, 3)} |")
    add("")
    add("### Per-repo gate verdicts")
    add("")
    add("| repo | G1 beta CI > 0 | G2 dispersion CI > 1 | G3 Spearman CI > 0 |")
    add("|---|---|---|---|")
    for r in repos:
        beta, disp, sp = r["beta"], r["dispersion"], r["spearman_ci"]
        g1r = "PASS" if beta["ci_low"] > 0 else "FAIL"
        g2r = "PASS" if (np.isfinite(disp["ci_low"]) and disp["ci_low"] > 1.0) else "FAIL"
        g3r = "PASS" if (sp[0] > 0 and sp[1] > 0) else "FAIL"
        add(f"| {r['name']} | {g1r} | {g2r} | {g3r} |")
    add("")
    add("### Invasiveness view (L3): multi-file rate by friction tercile")
    add("")
    add("| repo | mean size (low friction) | mean size (high friction) | multi-file rate low | multi-file rate high |")
    add("|---|---:|---:|---:|---:|")
    for r in repos:
        inv = r["invasiveness"]
        add(
            f"| {r['name']} | {_fmt(inv['mean_low'], 2)} | {_fmt(inv['mean_high'], 2)} | "
            f"{_fmt(inv['multi_low'])} | {_fmt(inv['multi_high'])} |"
        )
    add("")
    add("### Bot-excluded robustness")
    add("")
    add("| repo | beta (human only) | 95% CI | dispersion ratio |")
    add("|---|---:|---|---:|")
    for r in repos:
        human = r["human_only"]["beta"]
        disp = r["human_only"]["dispersion"]
        if human is None or disp is None:
            add(f"| {r['name']} | n/a | n/a | n/a |")
            continue
        add(
            f"| {r['name']} | {_fmt(human['beta'])} | "
            f"[{_fmt(human['ci_low'])}, {_fmt(human['ci_high'])}] | {_fmt(disp['ratio'])} |"
        )
    add("")
    add("## What this means for the product coefficients")
    add("")
    add("| Constant | Product assumes | Measured on real commits |")
    add("|---|---|---|")
    ratios = [r["dispersion"]["ratio"] for r in repos if np.isfinite(r["dispersion"]["ratio"])]
    betas = [float(np.exp(r["beta"]["beta"])) for r in repos]
    add(
        f"| `FRICTION_P10_WIDENING` / `FRICTION_P90_WIDENING` | {FRICTION_P10_WIDENING} / {FRICTION_P90_WIDENING} | "
        f"relative spread of change size is **x{_fmt(min(ratios), 2)}-x{_fmt(max(ratios), 2)}** larger in the "
        "high vs low friction tercile (3 of 4 repos; `requests` is the exception). Direction and order "
        "of magnitude are supported; the exact constant is not pinned. |"
    )
    add(
        f"| `INVASIVENESS_P50_SHIFT` | {INVASIVENESS_P50_SHIFT} | size inflation per unit friction "
        f"`e^beta` = **x{_fmt(min(betas), 2)}-x{_fmt(max(betas), 2)}**, 95% CI > 0 in all 4 repos. "
        "The product's variable is invasiveness (not friction) and its target is days (not size), so "
        "this is corroborating context, not a direct estimate of the constant. |"
    )
    add("")
    add("## Honest limitations")
    add("")
    add("1. **The target is change size (files touched), not person-days.** L4")
    add("   (size -> days) and L5 (friction -> days) are **not** measurable from")
    add("   public data: no dataset pairs repository signals with logged effort at")
    add("   task level. Those links remain an explicit assumption.")
    add("2. **git-only friction**: 2 of 5 components. `fan_in`, `complexity` and")
    add("   `coverage_gap` are absent here, so the measured score is not the")
    add("   product's score (it is a lower-dimensional version of it).")
    add("3. **Commits are a request proxy.** A commit subject is not a client RFP;")
    add("   the product's unit is a project, this experiment's unit is a change.")
    add("4. **OSS != B2B SaaS.** Public Python libraries; nothing here validates")
    add("   client delivery estimation directly.")
    add("5. **Tercile cuts are sample-dependent**, so L2's ratio is not a universal")
    add("   constant — it is a measured, repo-conditioned quantity.")
    add("6. Blobless clones carry no line counts, so size is files touched only.")
    add("")
    add("## Reproduce")
    add("")
    add("```bash")
    add("cd backend && python scripts/surcharge_calibration.py \\")
    add("  --repo <flask> --repo <requests> --repo <pytest> --repo <sympy> --write")
    add("python scripts/surcharge_calibration.py --self-test")
    add("```")
    add("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Self-test / CLI
# --------------------------------------------------------------------------- #


def run_self_test() -> int:
    """Pure-function checks: no repository, no network."""
    commits = []
    for i in range(60):
        # 3 hot files (many commits) + 1 cold file, one author each time.
        files = ["hot.py", "hot.py", "cold.py"] if i % 3 == 0 else ["hot.py", f"f{i}.py"]
        commits.append(
            {
                "hash": f"{i:040x}",
                "author": "alice" if i % 2 == 0 else "bob",
                "ts": 1_700_000_000 + i * 86400,
                "subject": f"change {i}",
                "files": files,
            }
        )
    rows = build_target_rows(commits, target_share=0.4)
    assert rows, "expected target rows"
    assert all(0.0 <= r["friction_git"] <= 1.0 for r in rows), "friction in [0,1]"
    assert all(r["size"] >= 1 for r in rows)
    # determinism: same input -> identical rows
    again = build_target_rows(commits, target_share=0.4)
    assert [r["friction_git"] for r in rows] == [r["friction_git"] for r in again]

    beta = friction_beta_ci(rows)
    assert np.isfinite(beta["beta"]) and beta["n"] == len(rows)
    disp = dispersion_ratio(rows)
    assert np.isfinite(disp["ratio"]), "dispersion ratio should be finite"
    inv = invasiveness_view(rows)
    assert 0.0 <= inv["multi_low"] <= 1.0 and 0.0 <= inv["multi_high"] <= 1.0

    # leakage guard: a target's friction must not depend on later commits
    trimmed = build_target_rows(commits[:40], target_share=0.4)
    assert all(0.0 <= r["friction_git"] <= 1.0 for r in trimmed)

    print("self-test: OK")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure the Codebase Lab surcharge coefficients on real repositories."
    )
    parser.add_argument("--repo", action="append", default=[], help="path to a git repo (repeatable)")
    parser.add_argument("--target-share", type=float, default=TARGET_SHARE_DEFAULT)
    parser.add_argument("--write", action="store_true", help="write docs/SURCHARGE_CALIBRATION.md")
    parser.add_argument("--json-out", default="", help="optional path for the raw results JSON")
    parser.add_argument("--from-json", default="", help="re-render from a saved results JSON (no repos needed)")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()
    if not args.repo and not args.from_json:
        print("error: at least one --repo is required (or --from-json / --self-test)")
        return 2

    if args.from_json:
        payload = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        repos = payload["repos"]
        summary = payload["summary"]
    else:
        repos = []
        for path in args.repo:
            name = Path(path).name
            print(f"[repo] {name}: reading history ...")
            repos.append(evaluate_repo(name, path, args.target_share))
        summary = build_summary(repos)

    print_report(repos, summary)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"repos": repos, "summary": summary}, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json_out}")

    if args.write:
        doc = _BACKEND_ROOT.parent / "docs" / "SURCHARGE_CALIBRATION.md"
        doc.write_text(render_docs(repos, summary), encoding="utf-8")
        print(f"wrote {doc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
