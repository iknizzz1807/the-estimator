"""CLI for the Codebase Lab analyzer (friction + invasiveness + adjusted interval).

Usage (from ``backend/``)::

    python scripts/codebase_cli.py --repo /path/to/repo [--at 2026-04-01] \\
        [--keywords payment,provider] [--json]
    python scripts/codebase_cli.py --demo          # build + A/B contrast table

Read-only and offline: this only inspects git history/files; it never mutates
the analyzed repository and needs no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

# Allow `python scripts/codebase_cli.py` from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.codebase import (  # noqa: E402
    apply_friction,
    collect_signals,
    compute_friction,
    estimate_invasiveness,
    find_similar_changes,
)
from build_demo_repos import DEMO_REPOS_DIR, build_demo_repos  # noqa: E402

#: Just after the demo history ends, so the 6-month churn window covers it all.
DEMO_AT_DATE = "2026-04-01"

#: Same vocabulary for both demo repos: the paths where "add a payment provider"
#: must land. In the plugin repo that is ``payments/*``; in the spaghetti repo it
#: is the checkout/billing/orders/api files that hardcode provider branches.
DEMO_KEYWORDS = ["payment", "payments", "provider", "checkout", "billing", "orders"]

EXAMPLE_ESTIMATE: dict[str, Any] = {
    "p10": 10.0,
    "p50": 20.0,
    "p90": 40.0,
    "mode": "example",
    "unit": "days",
    "method": "point",
}


def analyze(repo: str | Path, at_date: str | None, keywords: Sequence[str]) -> dict[str, Any]:
    """Run the full read-only analysis on one repo."""
    signals = collect_signals(repo, at_date=at_date)
    friction = compute_friction(signals)
    similar = find_similar_changes(repo, keywords, at_date=at_date)
    invasiveness = estimate_invasiveness(similar)
    example = apply_friction(EXAMPLE_ESTIMATE, friction, invasiveness)
    return {
        "signals": signals,
        "friction": friction,
        "similar_changes": similar,
        "invasiveness": invasiveness,
        "example_adjusted": example,
    }


def _num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)


def _short(value: Any, digits: int = 3) -> str:
    return _num(value, digits)


def print_report(repo: str, result: dict[str, Any]) -> None:
    signals = result["signals"]
    friction = result["friction"]
    similar = result["similar_changes"]
    invasiveness = result["invasiveness"]
    example = result["example_adjusted"]
    window = signals["repo"]["churn_window"]

    print(f"== Codebase signals: {repo} ==")
    print(
        f"at_date {signals['repo']['at_date']} | churn window "
        f"{window['since']} .. {window['until']} ({window['months']} months)"
    )
    print(
        f"commits {signals['churn']['total_commits']} | files changed "
        f"{signals['churn']['files_changed']} | max churn "
        f"{signals['churn']['max_file_commits']} | max fan-in "
        f"{signals['fan_in']['max_fan_in']}"
    )
    complexity = signals["complexity"]
    print(
        f"complexity {complexity['status']}: max {complexity['max_complexity']}, "
        f"mean {_num(complexity['mean_complexity'])}, "
        f"{complexity['files_scored']} files scored | coverage: "
        + (
            f"line-rate {signals['coverage']['line_rate']}"
            if signals["coverage"]["status"] == "found"
            else "unknown (no coverage.xml -- never faked)"
        )
        + f" | authors {signals['authors']['distinct_authors']} "
        f"(concentration {signals['authors']['concentration']})"
    )
    print("hot files:")
    for entry in signals["hot_files"]:
        print(
            f"  {entry['path']:<34} commits={entry['commits']} "
            f"authors={entry['distinct_authors']} fan_in={entry['fan_in']} "
            f"cplx_max={_num(entry['complexity_max'])} "
            f"coverage={_num(entry['coverage_line_rate'])}"
        )

    print(f"friction: score={friction['score']} level={friction['level']}")
    for name, value in friction["components"].items():
        weight = friction["weights"].get(name)
        if weight is None:
            print(f"  {name:<22} {_num(value, 4)}  (omitted: unknown)")
        else:
            print(f"  {name:<22} {_num(value, 4)}  x {weight:.2f}")
    for note in friction["notes"]:
        print(f"  note: {note}")

    print(f"similar changes (keywords: {','.join(result['keywords'])}): {len(similar)}")
    for commit in similar:
        print(
            f"  {commit['date']} {commit['commit'][:10]} {commit['author']:<12} "
            f"{commit['subject'][:44]:<44} files={commit['files_touched']} "
            f"new={commit['new_files']} mod={commit['modified_files']} "
            f"+{commit['added_lines']}/-{commit['removed_lines']}"
        )

    if invasiveness is None:
        print("invasiveness: none (no similar past changes -> no shift, never faked)")
    else:
        print(
            f"invasiveness: modified_ratio={invasiveness['modified_ratio']} "
            f"added_removed_ratio={invasiveness['added_removed_ratio']} "
            f"mean_files_touched={invasiveness['mean_files_touched']} "
            f"based_on_commits={invasiveness['based_on_commits']}"
        )

    adjusted = example["estimate"]
    print(
        f"example apply_friction on {{p10, p50, p90}} = "
        f"{{{EXAMPLE_ESTIMATE['p10']:.0f}, {EXAMPLE_ESTIMATE['p50']:.0f}, "
        f"{EXAMPLE_ESTIMATE['p90']:.0f}}}"
    )
    print(
        f"  adjusted: p10 {adjusted['p10']} | p50 {adjusted['p50']} | "
        f"p90 {adjusted['p90']} | friction level {example['friction_level']}"
    )
    for adjustment in example["adjustments"]:
        print(
            f"  {adjustment['what']:<18} x{adjustment['factor']}  "
            f"({adjustment['why']})"
        )
    print(f"  assumption note: {example['assumption_note']}")


def print_demo_table(reports: dict[str, dict[str, Any]], at_date: str,
                     keywords: Sequence[str]) -> None:
    print()
    print(f"== Codebase Lab demo A/B (at_date={at_date}, keywords={','.join(keywords)}) ==")
    print()
    print("friction (component values are normalised 0..1 before weighting):")
    header = (f"{'repo':<20}{'churn':>7}{'fan-in':>8}{'cplx':>7}{'cov_gap':>9}"
              f"{'authors':>9}{'score':>9}{'level':>8}")
    print(header)
    for name, result in reports.items():
        components = result["friction"]["components"]
        print(
            f"{name:<20}{_num(components['churn']):>7}{_num(components['fan_in']):>8}"
            f"{_num(components['complexity']):>7}{_num(components['coverage_gap']):>9}"
            f"{_num(components['author_concentration']):>9}"
            f"{_short(result['friction']['score'], 4):>9}"
            f"{result['friction']['level']:>8}"
        )
    print()
    print("invasiveness of 'add a payment provider' (from similar past patches):")
    print(f"{'repo':<20}{'commits':>8}{'new':>5}{'mod':>5}{'mod_ratio':>11}"
          f"{'files/c':>9}{'p50x':>7}")
    for name, result in reports.items():
        invasiveness = result["invasiveness"]
        example = result["example_adjusted"]
        p50_factor = next(
            adjustment["factor"]
            for adjustment in example["adjustments"]
            if adjustment["what"].startswith("p50")
        )
        if invasiveness is None:
            print(f"{name:<20}{'none':>8}")
            continue
        totals = invasiveness["totals"]
        print(
            f"{name:<20}{invasiveness['based_on_commits']:>8}{totals['new_files']:>5}"
            f"{totals['modified_files']:>5}{_num(invasiveness['modified_ratio'], 4):>11}"
            f"{_num(invasiveness['mean_files_touched']):>9}{_short(p50_factor):>7}"
        )
    print()
    print("Reading: high friction widens the interval (harder to predict, median "
          "untouched); a high modified_ratio shifts the median up. Coefficients "
          "are DEMO-ASSUMED (learned from actuals in production).")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="path to a git repository to analyze")
    parser.add_argument("--at", dest="at_date", default=None, help="estimate date YYYY-MM-DD")
    parser.add_argument(
        "--keywords",
        default="",
        help="comma-separated path keywords for similar-change search",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument(
        "--demo", action="store_true", help="build/analyze both demo repos and print the A/B table"
    )
    args = parser.parse_args(argv)

    if not args.demo and not args.repo:
        parser.error("either --repo PATH or --demo is required")

    try:
        if args.demo:
            repos = build_demo_repos()
            reports = {}
            for name, repo in repos.items():
                result = analyze(repo, DEMO_AT_DATE, DEMO_KEYWORDS)
                result["keywords"] = DEMO_KEYWORDS
                reports[name] = result
            if args.json:
                print(json.dumps(reports, indent=2, sort_keys=True))
            else:
                for name, result in reports.items():
                    print_report(str(repos[name]), result)
                    print()
                print_demo_table(reports, DEMO_AT_DATE, DEMO_KEYWORDS)
            return 0

        keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]
        result = analyze(args.repo, args.at_date, keywords)
        result["keywords"] = keywords
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print_report(args.repo, result)
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
