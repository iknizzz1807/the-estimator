"""Synthetic project-history generator for The Estimator (checklist GIAI ĐOẠN 1).

Builds a deterministic fake corpus of software-project RFPs plus the hidden
ground truth used only for validation:

* 15 binary features drawn independently per project from a documented
  probability table (spec §5.4 correlations are intentionally NOT modelled -
  the estimation model should learn interactions from the data itself).
* ``actual_days`` from a hidden multiplicative formula over per-feature
  coefficients, extra *joint* multipliers for co-occurring feature pairs
  (e.g. payment_gateway & pci_dss), a mid-history scope/productivity *drift*
  factor and occasional blow-up *outliers* (~5% of projects, x2.0-x3.0),
  plus lognormal noise (owned here, never read by the estimator).
* ``team_estimate`` from the same formula with weakened integration/migration
  coefficients and a systematic optimism factor (the classic Tech Lead bias
  described in the checklist: "team hay quên third_party, data_migration").
  It does NOT know about interactions, drift or outliers: after the drift
  switch date the team keeps pricing with pre-drift perceptions, so its
  estimates get worse while the walk-forward model can re-learn.
* One client email per project (see ``email_writer``) that mentions most
  present features, omits 1-2 of them in ~30% of projects and explicitly
  negates ~8% of absent features.

The full recipe (coefficient table + all hidden parameters) is documented in
``docs/DATA_GENERATION.md``; keep both in sync.

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

# --- Added realism: interactions, mid-history drift, outliers ---------------
# (see docs/DATA_GENERATION.md for the rationale and the recovered values)

#: Extra joint multipliers when both features co-occur (integration/rework
#: overhead on top of the independent main effects). Kept small (~1.1) so the
#: main effects stay recoverable from the 52-project training corpus
#: (Ridge log-space coefficient error <= 20%, checked in the test suite).
INTERACTION_MULTIPLIERS: dict[tuple[str, str], float] = {
    ("payment_gateway", "pci_dss"): 1.15,
    ("mobile_app", "offline_mode"): 1.10,
    ("data_migration", "legacy_tech_stack"): 1.12,
}

#: Mid-history drift: the company grew and scope got heavier. From this date
#: on, hidden actual effort is multiplied by DRIFT_FACTOR. ``team_estimate``
#: keeps the old formula (old perceptions) - post-drift team estimates get
#: worse while the walk-forward model can re-learn from post-drift actuals.
DRIFT_SWITCH_DATE = date(2026, 2, 1)
DRIFT_FACTOR = 1.22

#: Real blow-ups: ~5% of done projects get an extra multiplicative shock on
#: actual_days, uniform in [OUTLIER_SHOCK_MIN, OUTLIER_SHOCK_MAX].
OUTLIER_RATE = 0.05
OUTLIER_SHOCK_MIN = 2.0
OUTLIER_SHOCK_MAX = 3.0

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


def interaction_multiplier(features: Mapping[str, int]) -> float:
    """Joint multiplier product for co-occurring feature pairs (1.0 when none)."""
    multiplier = 1.0
    for (first, second), value in INTERACTION_MULTIPLIERS.items():
        if features.get(first) and features.get(second):
            multiplier *= value
    return multiplier


def drift_factor(project_date: str) -> float:
    """DRIFT_FACTOR for projects dated on/after the switch date, else 1.0."""
    return DRIFT_FACTOR if date.fromisoformat(project_date) >= DRIFT_SWITCH_DATE else 1.0


def _outlier_shocks(rng: random.Random, n: int, done_count: int) -> dict[int, float]:
    """Seeded blow-up shocks: ``{project index: factor}`` for ~5% of done rows.

    Sampled from the done projects only (shocks on open projects would never
    surface: open rows have no ``actual_days``). Uses a dedicated RNG so the
    main generator stream stays stable when this feature is tuned.
    """
    if done_count <= 0:
        return {}
    count = min(done_count, max(1, round(n * OUTLIER_RATE)))
    chosen = sorted(rng.sample(range(done_count), k=count))
    return {i: round(rng.uniform(OUTLIER_SHOCK_MIN, OUTLIER_SHOCK_MAX), 2) for i in chosen}


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
    # Dedicated RNG: choosing/applying outliers does not shift the main stream.
    outlier_rng = random.Random(f"{seed}:outliers")
    outliers = _outlier_shocks(outlier_rng, n, max(n - RECENT_PROJECT_COUNT, 0))
    records: list[ProjectRecord] = []
    gt_projects: dict[str, dict[str, Any]] = {}

    for i in range(n):
        project_id = f"P{i + 1:03d}"
        features = {
            name: int(rng.random() < FEATURE_PROBABILITIES[name]) for name in FEATURES
        }

        interactions = interaction_multiplier(features)
        drift = drift_factor(dates[i])
        shock = outliers.get(i)
        shock_factor = 1.0 if shock is None else shock
        # The noise draw stays the first (and only) RNG call in this block so
        # the stream order - and therefore features/emails - is unchanged.
        actual_days = max(
            MIN_DAYS,
            round(
                effort_days(features)
                * interactions
                * drift
                * shock_factor
                * rng.lognormvariate(0.0, ACTUAL_NOISE_SIGMA)
            ),
        )
        # Team estimate keeps the pre-drift perception: no interactions, no
        # drift, no outlier knowledge (weakened coefficients + optimism only).
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
            "interaction_multiplier": interactions,
            "drift_factor": drift,
            "outlier_shock": shock,
        }

    ground_truth: dict[str, Any] = {
        "seed": seed,
        "hidden_coefficients": dict(HIDDEN_COEFFICIENTS),
        "feature_probabilities": dict(FEATURE_PROBABILITIES),
        "interaction_multipliers": [
            {"features": list(pair), "multiplier": value}
            for pair, value in INTERACTION_MULTIPLIERS.items()
        ],
        "drift": {"switch_date": DRIFT_SWITCH_DATE.isoformat(), "factor": DRIFT_FACTOR},
        "outliers": {f"P{i + 1:03d}": shock for i, shock in outliers.items()},
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
