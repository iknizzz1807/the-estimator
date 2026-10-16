"""Synthetic project-history generator for The Estimator (checklist GIAI ĐOẠN 1).

Builds a deterministic fake corpus of software-project RFPs plus the hidden
ground truth used only for validation:

* 15 binary features drawn independently per project from a documented
  probability table (spec §5.4 correlations are intentionally NOT modelled -
  the estimation model should learn interactions from the data itself).
* ``actual_days`` from a hidden multiplicative formula over per-feature
  coefficients plus lognormal noise (owned here, never read by the estimator).
* ``team_estimate`` from the same formula with weakened integration/migration
  coefficients and a systematic optimism factor (the classic Tech Lead bias
  described in the checklist: "team hay quên third_party, data_migration").
* One client email per project (see ``email_writer``) that mentions most
  present features, omits 1-2 of them in ~30% of projects and explicitly
  negates ~8% of absent features.

Template-based, offline and fully deterministic: the same ``--seed`` always
produces byte-identical CSV and JSON outputs.

CLI:
    python -m app.data_gen.generate_history --n 60 --seed 42 \\
        --out data/synthetic_history.csv --truth data/ground_truth.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.data_gen.email_writer import compose_email
from app.features import FEATURES, csv_columns

# --- Hidden data-generating process (never read by the estimator) ------------

BASE_DAYS = 15.0
MIN_DAYS = 5

HIDDEN_COEFFICIENTS: dict[str, float] = {
    "third_party_api": 1.35,
    "payment_gateway": 1.45,
    "identity_provider": 1.25,
    "external_data_sync": 1.30,
    "data_migration": 1.60,
    "multi_currency": 1.15,
    "multi_tenancy": 1.50,
    "realtime_ui": 1.30,
    "mobile_app": 1.55,
    "offline_mode": 1.25,
    "pci_dss": 1.40,
    "privacy_compliance": 1.35,
    "audit_logging": 1.20,
    "legacy_tech_stack": 1.45,
    "cross_team_coordination": 1.25,
}

# Independent Bernoulli probabilities per feature (documented; 0.15-0.45).
FEATURE_PROBABILITIES: dict[str, float] = {
    "third_party_api": 0.45,
    "payment_gateway": 0.25,
    "identity_provider": 0.25,
    "external_data_sync": 0.30,
    "data_migration": 0.30,
    "multi_currency": 0.15,
    "multi_tenancy": 0.20,
    "realtime_ui": 0.25,
    "mobile_app": 0.25,
    "offline_mode": 0.20,
    "pci_dss": 0.20,
    "privacy_compliance": 0.25,
    "audit_logging": 0.20,
    "legacy_tech_stack": 0.20,
    "cross_team_coordination": 0.25,
}

# Tech Lead blind spots: integrations and data migration get damped, and a flat
# optimism factor pushes the whole estimate low (checklist GIAI ĐOẠN 1).
TEAM_WEAKENED_COEFFICIENTS: dict[str, float] = {
    **HIDDEN_COEFFICIENTS,
    "third_party_api": HIDDEN_COEFFICIENTS["third_party_api"] ** 0.5,
    "data_migration": HIDDEN_COEFFICIENTS["data_migration"] ** 0.6,
}
TEAM_BIAS_FACTOR = 0.75

ACTUAL_NOISE_SIGMA = 0.18
TEAM_NOISE_SIGMA = 0.08

OMISSION_RATE = 0.30  # share of projects that omit 1-2 present features in the email
NEGATION_RATE = 0.08  # share of absent features explicitly negated in the email

# Date window: the 24 months ending 2026-10-10 (today is 2026-10-16).
DATE_END = date(2026, 10, 10)
DATE_START = date(2024, 10, 10)
DATE_JITTER_DAYS = 6

RECENT_PROJECT_COUNT = 8  # newest projects stay open for the "Enter Actuals" demo
RECENT_STATUSES = ("in_progress", "in_progress", "in_progress", "in_progress",
                   "in_progress", "pending", "pending", "pending")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CSV_PATH = REPO_ROOT / "data" / "synthetic_history.csv"
DEFAULT_TRUTH_PATH = REPO_ROOT / "data" / "ground_truth.json"

METADATA_COLUMNS = [
    "project_id",
    "date",
    "actual_days",
    "team_estimate",
    "status",
    "is_synthetic",
    "email_text",
]
CSV_COLUMNS = METADATA_COLUMNS + csv_columns()


@dataclass(frozen=True)
class ProjectRecord:
    """One synthetic project: hidden inputs, observed outputs and email bookkeeping."""

    project_id: str
    date: str
    actual_days: int | None
    team_estimate: int
    status: str
    features: Mapping[str, int]
    email_text: str
    mentioned: tuple[str, ...]
    omitted: tuple[str, ...]
    negated: tuple[str, ...]


def _coefficient_product(features: Mapping[str, int], coefficients: Mapping[str, float]) -> float:
    """Multiplicative effect of all present features under ``coefficients``."""
    return math.prod(
        coefficients[name] ** features[name] for name in FEATURES if features[name]
    )


def effort_days(features: Mapping[str, int], coefficients: Mapping[str, float] | None = None) -> float:
    """Hidden effort model: BASE_DAYS times the coefficient product of present features."""
    return BASE_DAYS * _coefficient_product(features, coefficients or HIDDEN_COEFFICIENTS)


def _project_dates(rng: random.Random, n: int) -> list[str]:
    """``n`` ISO dates spread evenly across the 24-month window, plus jitter."""
    span = (DATE_END - DATE_START).days
    step = span / max(n - 1, 1)
    days = []
    for i in range(n):
        base = DATE_START + timedelta(days=round(i * step))
        jittered = base + timedelta(days=rng.randint(-DATE_JITTER_DAYS, DATE_JITTER_DAYS))
        days.append(min(DATE_END, max(DATE_START, jittered)))
    days.sort()
    return [d.isoformat() for d in days]


def generate(n: int = 60, seed: int = 42) -> tuple[list[ProjectRecord], dict[str, Any]]:
    """Generate ``n`` projects plus ground truth for the given seed.

    Args:
        n: number of projects (project ids P001..P{n:03d}, oldest first).
        seed: RNG seed; identical seed -> identical output.

    Returns:
        (records, ground_truth). ``ground_truth`` matches the structure dumped
        to ``--truth``: seed, hidden coefficients, probabilities, per-project
        features/mention bookkeeping. It must never be read by the estimator.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    rng = random.Random(seed)
    dates = _project_dates(rng, n)
    records: list[ProjectRecord] = []
    gt_projects: dict[str, dict[str, Any]] = {}

    for i in range(n):
        project_id = f"P{i + 1:03d}"
        features = {
            name: int(rng.random() < FEATURE_PROBABILITIES[name]) for name in FEATURES
        }

        effort = effort_days(features)
        # The noise is drawn even for open projects so the RNG stream stays
        # identical no matter how statuses are later re-split.
        actual_days = max(MIN_DAYS, round(effort * rng.lognormvariate(0.0, ACTUAL_NOISE_SIGMA)))
        team_estimate = max(
            MIN_DAYS,
            round(
                effort_days(features, TEAM_WEAKENED_COEFFICIENTS)
                * TEAM_BIAS_FACTOR
                * rng.lognormvariate(0.0, TEAM_NOISE_SIGMA)
            ),
        )

        if i < n - RECENT_PROJECT_COUNT:
            status = "done"
        else:
            status = RECENT_STATUSES[i - (n - RECENT_PROJECT_COUNT)]
            actual_days = None  # demo fills this via the "Enter Actuals" flow

        present = [name for name in FEATURES if features[name]]
        omitted: list[str] = []
        if present and rng.random() < OMISSION_RATE:
            k = 2 if rng.random() < 0.5 else 1
            omitted = rng.sample(present, k=min(k, len(present)))
            omitted.sort(key=FEATURES.index)
        mentioned = [name for name in present if name not in omitted]
        negated = [
            name
            for name in FEATURES
            if not features[name] and rng.random() < NEGATION_RATE
        ]

        email_text = compose_email(rng, mentioned=mentioned, negated=negated)

        records.append(
            ProjectRecord(
                project_id=project_id,
                date=dates[i],
                actual_days=actual_days,
                team_estimate=team_estimate,
                status=status,
                features=features,
                email_text=email_text,
                mentioned=tuple(mentioned),
                omitted=tuple(omitted),
                negated=tuple(negated),
            )
        )
        gt_projects[project_id] = {
            "features": dict(features),
            "mentioned": list(mentioned),
            "omitted": list(omitted),
            "negated": list(negated),
            "actual_days": actual_days,
            "team_estimate": team_estimate,
        }

    ground_truth: dict[str, Any] = {
        "seed": seed,
        "hidden_coefficients": dict(HIDDEN_COEFFICIENTS),
        "feature_probabilities": dict(FEATURE_PROBABILITIES),
        "projects": gt_projects,
    }
    return records, ground_truth


def write_csv(records: Sequence[ProjectRecord], path: str | Path) -> Path:
    """Write records to ``path`` in the frozen CSV format (docs/API.md)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for record in records:
            writer.writerow(
                [
                    record.project_id,
                    record.date,
                    "" if record.actual_days is None else record.actual_days,
                    record.team_estimate,
                    record.status,
                    1,  # is_synthetic
                    record.email_text,
                    *(record.features[name] for name in FEATURES),
                ]
            )
    return path


def write_ground_truth(ground_truth: Mapping[str, Any], path: str | Path) -> Path:
    """Write ground truth JSON (validation only; the estimator never reads it)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(ground_truth, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    """CLI parser; defaults resolve to the repo-root data/ dir regardless of CWD."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=60, help="number of projects (default: 60)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    parser.add_argument("--out", type=Path, default=DEFAULT_CSV_PATH, help=f"CSV output path (default: {DEFAULT_CSV_PATH})")
    parser.add_argument("--truth", type=Path, default=DEFAULT_TRUTH_PATH, help=f"ground-truth JSON path (default: {DEFAULT_TRUTH_PATH})")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the dataset and write both artifacts; returns the exit code."""
    args = build_parser().parse_args(argv)
    records, ground_truth = generate(n=args.n, seed=args.seed)
    csv_path = write_csv(records, args.out)
    truth_path = write_ground_truth(ground_truth, args.truth)
    done = sum(1 for record in records if record.status == "done")
    print(f"Generated {len(records)} projects ({done} done, {len(records) - done} open) -> {csv_path}")
    print(f"Ground truth -> {truth_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
