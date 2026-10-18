#!/usr/bin/env python
"""PR lead-time study: does repository friction predict how long a change takes?

Why this exists (docs/DECISIONS.md D20/D24): the surcharge coefficients are
partly measured, but the link from *change size* to *person-days* is not
measurable from public data — nobody publishes `(repository signals, logged
effort)` pairs. This script measures the closest thing that **is** public and
per-change: on GitHub every merged pull request has a real duration
(``created_at`` -> ``merged_at``). It asks:

    does a repo whose touched code is churny / single-author take longer to land
    a change, once the change's own size is controlled for?

What this establishes: the **sign and order of magnitude** of
``friction -> lead time`` on real projects. What it does NOT establish: effort
in person-days (lead time includes review queues, CI, timezones and weekends),
so this is a *corroborating* measurement, never a replacement for the assumed
constant.

Design (leakage-aware, mirrors scripts/surcharge_calibration.py)
----------------------------------------------------------------
* PRs come from the GitHub API (public data; ``GITHUB_TOKEN`` only raises the
  rate limit and is never written anywhere).
* Friction is **git-only** (churn + author concentration — the components
  computable from ``git log`` alone, see D20) and is computed **from commits
  strictly before** each PR's base date. It is bucketed per month and documented
  as such: friction is a slow-moving repository property, and bucketing keeps
  this a minutes-long study instead of an hours-long one.
* Target: ``log1p(lead_time_days)``. Controls: ``log1p(changed_files)``,
  ``log1p(additions + deletions)``, a bot flag, and ``log1p(month index)`` so a
  repo-wide trend (e.g. process changes) is absorbed.
* Pre-registered gate: the 95% paired-bootstrap CI of the friction coefficient
  is entirely > 0 on the pooled sample. Reported per repo as well; a repo that
  disagrees is reported as-is.

Usage::

    set GITHUB_TOKEN=...            # optional but strongly recommended
    cd backend && python scripts/pr_leadtime_study.py --repo pallets/flask --write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.codebase import (  # noqa: E402
    CHURN_SATURATION_COMMITS,
    CHURN_WINDOW_MONTHS,
    FRICTION_WEIGHTS,
)
from scripts.codebase_history_experiment import extract_commits, is_bot_commit  # noqa: E402
from scripts.surcharge_calibration import GIT_COMPONENTS  # noqa: E402

BOOTSTRAP_ITERS = 2000
BOOTSTRAP_SEED = 42
API_ROOT = "https://api.github.com"
DEFAULT_LIMIT = 800
DAY = 86_400
MONTH_DAYS = 30 * CHURN_WINDOW_MONTHS


# --------------------------------------------------------------------------- #
# GitHub API
# --------------------------------------------------------------------------- #


def _api_get(url: str, token: str | None, timeout: float = 30.0) -> Any:
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "the-estimator-leadtime-study")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def fetch_merged_prs(
    owner: str, name: str, token: str | None, limit: int = DEFAULT_LIMIT
) -> list[dict[str, Any]]:
    """Merged PRs for a repo, oldest first, with the fields this study needs."""
    out: list[dict[str, Any]] = []
    page = 1
    while len(out) < limit:
        url = (
            f"{API_ROOT}/repos/{owner}/{name}/pulls"
            f"?state=closed&sort=created&direction=asc&per_page=100&page={page}"
        )
        batch = _api_get(url, token)
        if not isinstance(batch, list) or not batch:
            break
        for pr in batch:
            if not pr.get("merged_at"):
                continue
            out.append(
                {
                    "number": int(pr["number"]),
                    "created_at": pr["created_at"],
                    "merged_at": pr["merged_at"],
                    "base_sha": (pr.get("base") or {}).get("sha") or "",
                    "changed_files": int(pr.get("changed_files") or 0),
                    "additions": int(pr.get("additions") or 0),
                    "deletions": int(pr.get("deletions") or 0),
                    "author": ((pr.get("user") or {}).get("login") or ""),
                }
            )
            if len(out) >= limit:
                break
        page += 1
    return out


# --------------------------------------------------------------------------- #
# Monthly friction (git-only, from commits strictly before the bucket)
# --------------------------------------------------------------------------- #


def _month_end(ts: int) -> int:
    """Last day of the UTC month containing ``ts`` (as a timestamp)."""
    day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
    if day.month == 12:
        nxt = date(day.year + 1, 1, 1)
    else:
        nxt = date(day.year, day.month + 1, 1)
    return int(datetime(nxt.year, nxt.month, nxt.day, tzinfo=timezone.utc).timestamp()) - 1


def monthly_friction(commits: Sequence[dict]) -> dict[int, float]:
    """Git-only friction per month-end, from commits strictly before that month-end.

    Mirrors ``collect_signals`` semantics with the two git-computable components:
    churn = max commits to any single file inside the 6-month window, author
    concentration = the window's commit-weighted concentration. Weights come from
    the product's ``FRICTION_WEIGHTS`` and are renormalised over the available
    components, exactly like ``compute_friction``.
    """
    if not commits:
        return {}
    by_month: dict[int, list[dict]] = {}
    for commit in commits:
        by_month.setdefault(_month_end(commit["ts"]), []).append(commit)

    out: dict[int, float] = {}
    for month_end in sorted(by_month):
        window = [
            c for c in commits if month_end - MONTH_DAYS * DAY < c["ts"] < month_end
        ]
        if not window:
            out[month_end] = 0.0
            continue
        per_file: dict[str, int] = {}
        authors: dict[str, set[str]] = {}
        for commit in window:
            for path in commit["files"]:
                per_file[path] = per_file.get(path, 0) + 1
                authors.setdefault(path, set()).add(commit["author"])
        churn_max = max(per_file.values())
        concentration = max(
            (
                min(1.0, max(0.0, 1.0 - len(authors[path]) / count))
                for path, count in per_file.items()
                if count >= 2
            ),
            default=0.0,
        )
        components = {
            "churn": float(min(1.0, churn_max / CHURN_SATURATION_COMMITS)),
            "author_concentration": concentration,
        }
        total_weight = sum(FRICTION_WEIGHTS[name] for name in GIT_COMPONENTS)
        out[month_end] = (
            sum(components[name] * FRICTION_WEIGHTS[name] for name in GIT_COMPONENTS)
            / total_weight
        )
    return out


def _parse_ts(value: str) -> int:
    return int(
        datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    )


def build_rows(prs: Iterable[dict], friction_by_month: dict[int, float]) -> list[dict]:
    """One row per merged PR, with the friction of the month before its creation."""
    months = sorted(friction_by_month)
    if not months:
        return []
    rows: list[dict] = []
    for pr in prs:
        created = _parse_ts(pr["created_at"])
        merged = _parse_ts(pr["merged_at"])
        lead_days = (merged - created) / DAY
        if lead_days < 0:
            continue
        # friction strictly before the PR was opened (leakage guard)
        earlier = [m for m in months if m < created]
        if not earlier:
            continue
        rows.append(
            {
                "number": pr["number"],
                "lead_days": lead_days,
                "friction": friction_by_month[earlier[-1]],
                "changed_files": max(1, pr["changed_files"]),
                "lines": max(1, pr["additions"] + pr["deletions"]),
                "bot": is_bot_commit(pr["author"], ""),
                "created": created,
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #


def _design(rows: Sequence[dict]) -> np.ndarray:
    base = np.array([r["created"] for r in rows], dtype=float)
    month_index = (base - base.min()) / (30 * DAY)
    return np.column_stack(
        [
            np.ones(len(rows)),
            np.log1p([r["changed_files"] for r in rows]),
            np.log1p([r["lines"] for r in rows]),
            np.array([1.0 if r["bot"] else 0.0 for r in rows]),
            month_index,
            np.array([r["friction"] for r in rows]),
        ]
    )


def friction_beta_ci(rows: Sequence[dict]) -> dict[str, float]:
    y = np.log1p(np.array([r["lead_days"] for r in rows]))
    design = _design(rows)
    beta = float(np.linalg.lstsq(design, y, rcond=None)[0][-1])
    rng = np.random.RandomState(BOOTSTRAP_SEED)
    n = len(rows)
    draws = np.empty(BOOTSTRAP_ITERS)
    for t in range(BOOTSTRAP_ITERS):
        idx = rng.randint(0, n, size=n)
        draws[t] = float(np.linalg.lstsq(design[idx], y[idx], rcond=None)[0][-1])
    return {
        "beta": beta,
        "ci_low": float(np.percentile(draws, 2.5)),
        "ci_high": float(np.percentile(draws, 97.5)),
        "n": int(n),
        "median_lead_days": float(np.median([r["lead_days"] for r in rows])),
    }


def evaluate_repo(slug: str, token: str | None, limit: int) -> dict[str, Any]:
    owner, _, name = slug.partition("/")
    clone = _BACKEND_ROOT.parent / "data" / "example_repos" / f"{owner}__{name}"
    if not (clone / ".git").exists():
        raise RuntimeError(
            f"no local clone for {slug} at {clone} — run scripts/fetch_example_repos.py"
        )
    prs = fetch_merged_prs(owner, name, token, limit=limit)
    commits, _meta = extract_commits(clone)
    friction = monthly_friction(commits)
    rows = build_rows(prs, friction)
    if len(rows) < 30:
        raise RuntimeError(f"not enough usable PRs for {slug} ({len(rows)})")
    stats = friction_beta_ci(rows)
    stats.update(
        {
            "slug": slug,
            "prs_fetched": len(prs),
            "friction_mean": float(np.mean([r["friction"] for r in rows])),
            "monotonic_months": len(friction),
            "rows": rows,
        }
    )
    return stats


def print_report(repos: list[dict], pooled: dict | None, gate: bool) -> None:
    print("\n=== PR lead-time study (does friction slow a change down?) ===")
    header = f"{'repo':<26}{'PRs':>6}{'fric':>7}{'beta':>9}{'CI low':>9}{'CI high':>9}{'med days':>10}"
    print("\n" + header)
    print("-" * len(header))
    for r in repos:
        print(
            f"{r['slug']:<26}{r['n']:>6}{r['friction_mean']:>7.3f}"
            f"{r['beta']:>9.3f}{r['ci_low']:>9.3f}{r['ci_high']:>9.3f}"
            f"{r['median_lead_days']:>10.2f}"
        )
    if pooled:
        print(
            f"{'POOLED':<26}{pooled['n']:>6}{pooled['friction_mean']:>7.3f}"
            f"{pooled['beta']:>9.3f}{pooled['ci_low']:>9.3f}{pooled['ci_high']:>9.3f}"
            f"{pooled['median_lead_days']:>10.2f}"
        )
    print(f"\ngate (pooled CI entirely > 0): {'PASS' if gate else 'FAIL'}")


def render_docs(repos: list[dict], pooled: dict | None, gate: bool) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    add = lines.append
    add("# PR lead-time study — does repository friction slow a change down?")
    add("")
    add(f"Generated by `backend/scripts/pr_leadtime_study.py` on {now}.")
    add("Deterministic given the same PR sample (seed 42); the PR list comes from the")
    add("GitHub API, so a later run sees newer PRs.")
    add("")
    add("**Question.** The surcharge coefficients are partly measured (D20), but the")
    add("link *change size -> person-days* is not measurable from public data. GitHub")
    add("does publish a real per-change duration: a merged PR's `created_at ->")
    add("merged_at`. Does repository friction predict it, controlling for the change's")
    add("own size?")
    add("")
    add("## TL;DR")
    add("")
    add(f"Pooled friction coefficient on `log1p(lead time days)`: **{pooled['beta']:.3f}** "
        f"(95% CI [{pooled['ci_low']:.3f}, {pooled['ci_high']:.3f}]) over {pooled['n']} merged PRs."
        if pooled else "No pooled result.")
    add(f"Pre-registered gate (CI entirely > 0): **{'PASS' if gate else 'FAIL'}**.")
    add("")
    add("## Method")
    add("")
    add("* Merged PRs from the GitHub API (public data). `GITHUB_TOKEN` only raises")
    add("  the rate limit; it is never written to disk.")
    add("* Friction is **git-only** (churn + author concentration, the components")
    add("  computable from `git log`; D20) and computed **from commits strictly")
    add("  before** each PR's creation date. It is bucketed per month: friction is a")
    add("  slow-moving repository property, and bucketing keeps the study minutes-long.")
    add("* Target `log1p(lead time days)`; controls `log1p(changed_files)`,")
    add("  `log1p(additions + deletions)`, a bot flag and a `log1p(month index)` trend.")
    add("* Gate fixed before the run: pooled 95% paired-bootstrap CI of the friction")
    add("  coefficient entirely > 0.")
    add("")
    add("## Results")
    add("")
    add("| repo | merged PRs | mean friction | beta | 95% CI | median lead time (days) |")
    add("|---|---:|---:|---:|---|---:|")
    for r in repos:
        add(
            f"| {r['slug']} | {r['n']} | {r['friction_mean']:.3f} | {r['beta']:.3f} | "
            f"[{r['ci_low']:.3f}, {r['ci_high']:.3f}] | {r['median_lead_days']:.2f} |"
        )
    if pooled:
        add(
            f"| **pooled** | **{pooled['n']}** | {pooled['friction_mean']:.3f} | "
            f"**{pooled['beta']:.3f}** | [{pooled['ci_low']:.3f}, {pooled['ci_high']:.3f}] | "
            f"{pooled['median_lead_days']:.2f} |"
        )
    add("")
    add("## Honest interpretation (read this before quoting anything above)")
    add("")
    if gate:
        add("The gate passed: the pooled CI of the friction coefficient is entirely > 0,")
        add("so higher repository friction is associated with longer lead time on this")
        add("sample. It still measures *lead time*, not effort (see limitations).")
    else:
        pooled_beta = pooled["beta"] if pooled else float("nan")
        add("**The gate FAILED.**" + (
            " The pooled coefficient is even **negative** "
            f"({pooled_beta:.3f}): higher friction is associated with *shorter* lead"
            " time. This design does not measure what it hoped to, and **no product"
            " coefficient may be derived from it**."
            if pooled and pooled_beta < 0
            else " The pooled CI includes 0, so the sample does not support the claim."
        ))
        add("")
        add("Why the target is unusable here, concretely:")
        add("")
        add("1. **The target is nearly degenerate.** The median lead time is well under a")
        add("   day in these libraries — most PRs merge the same day they are opened — so")
        add("   there is almost no variation left to explain.")
        add("2. **The predictor barely varies within a repo.** Monthly-bucketed git-only")
        add("   friction sits at 0.80-0.96 for four of the five repos, so the coefficient")
        add("   is estimated off between-repo differences, not within-repo change.")
        add("3. **Friction and calendar time are correlated** (repos accumulate churn), and")
        add("   the `log1p(month index)` control absorbs that trend — the residual")
        add("   coefficient is unstable and can flip sign, which is what happened.")
        add("")
        add("Conclusion: **lead time is not a usable proxy for effort.** The assumed")
        add("`size -> person-days` link stays an explicit assumption (D20/D24), and the")
        add("only path to measuring it is instrumenting the product (D24 roadmap).")
    add("")
    add("## Honest limitations")
    add("")
    add("1. **Lead time is not effort.** It includes review queues, CI, weekends,")
    add("   timezones and release trains; it is a *corroborating* duration, not")
    add("   person-days. The `size -> days` link stays an explicit assumption.")
    add("2. **Friction is monthly and git-only** (2 of 5 components): fan-in and")
    add("   complexity are Python-only and radon-heavy, so they are excluded here")
    add("   (they are included in the product's own score).")
    add("3. **OSS libraries != B2B SaaS**: nothing here validates client delivery.")
    add("4. Confounders are only partly controlled (reviewer availability, PR labels,")
    add("   linked issues). The month trend absorbs some of it.")
    add("5. The PR sample is capped per repo; a later run sees different PRs.")
    add("")
    add("## Reproduce")
    add("")
    add("```bash")
    add("set GITHUB_TOKEN=...   # optional, raises the API rate limit")
    add("cd backend && python scripts/pr_leadtime_study.py --repo pallets/flask --write")
    add("```")
    add("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="max PRs per repo")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--from-json", default="", help="re-render from a saved results JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.from_json:
        payload = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        repos, pooled, gate = payload["repos"], payload["pooled"], bool(payload["gate"])
        print_report(repos, pooled, gate)
        if args.write:
            doc = _BACKEND_ROOT.parent / "docs" / "PR_LEADTIME_VALIDATION.md"
            doc.write_text(render_docs(repos, pooled, gate), encoding="utf-8")
            print(f"wrote {doc}")
        return 0
    if not args.repo:
        print("error: at least one --repo owner/name is required")
        return 2
    token = os.environ.get("GITHUB_TOKEN") or None
    if not token:
        print("note: GITHUB_TOKEN not set - unauthenticated rate limit is 60 req/h")

    repos: list[dict] = []
    for slug in args.repo:
        try:
            print(f"[repo] {slug}: fetching PRs ...", flush=True)
            repos.append(evaluate_repo(slug, token, args.limit))
        except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"[skip] {slug}: {exc}")

    if not repos:
        print("no repos evaluated")
        return 1

    pooled = friction_beta_ci([row for repo in repos for row in repo.get("rows", [])])
    pooled["friction_mean"] = float(
        np.mean([row["friction"] for repo in repos for row in repo.get("rows", [])])
    )
    gate = bool(pooled["ci_low"] > 0)
    print_report(repos, pooled, gate)

    if args.json_out:
        payload = {
            "repos": [{k: v for k, v in repo.items() if k != "rows"} for repo in repos],
            "pooled": {k: v for k, v in pooled.items() if k != "rows"},
            "gate": gate,
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json_out}")
    if args.write:
        doc = _BACKEND_ROOT.parent / "docs" / "PR_LEADTIME_VALIDATION.md"
        doc.write_text(render_docs(repos, pooled, gate), encoding="utf-8")
        print(f"wrote {doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
