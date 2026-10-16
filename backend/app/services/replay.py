"""Walk-forward replay history (spec §3.5, checklist Phase 2).

For i = min_train .. n-1: train on rows[:i] (chronological), predict row i,
accumulate running MAE for the system, the team baseline and the LLM-only
baseline, plus interval coverage.

====================== SIMULATED DATA WARNING ================================
The default LLM-only baseline is SIMULATED. It is NOT real LLM output: it is
cold-start P50 multiplied by seeded lognormal noise (sigma = 0.25), keyed by a
stable hash of the project id, standing in for 10 repeated LLM calls per
project (spec §4.5). Anything produced through this path carries
``llm_only_mode == "simulated"`` and must be labeled as simulated in the UI
(README limitation #1). Pass ``llm_only_baseline=<callable>`` to inject real
LLM measurements; the mode then becomes "provided".
=============================================================================
"""

from __future__ import annotations

import hashlib
import math
from statistics import fmean
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from app.services.estimation import cold_start_estimate, estimate, train_model

LLM_ONLY_SIGMA = 0.25  # lognormal sigma of the simulated LLM-only variation


def stable_seed(text: str) -> int:
    """Cross-process stable seed (Python's hash() is salted per process)."""
    digest = hashlib.blake2b(str(text).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def simulated_llm_only_point(row: Mapping[str, Any]) -> float:
    """SIMULATED LLM-only baseline: cold-start P50 x seeded lognormal noise.

    Deterministic per project_id: the same row always yields the same value,
    so the replay chart is reproducible without any network call.
    """
    base = cold_start_estimate(row.get("features") or {})["p50"]
    rng = np.random.default_rng(
        stable_seed(row.get("project_id") or row.get("date") or "unknown")
    )
    return base * float(np.exp(rng.normal(0.0, LLM_ONLY_SIGMA)))


def replay(
    rows: Sequence[Mapping[str, Any]],
    min_train: int = 10,
    llm_only_baseline: Callable[[Mapping[str, Any]], float] | None = None,
) -> dict[str, Any]:
    """Run the walk-forward replay and return steps + summary.

    Args:
        rows: canonical rows (project_id, date, actual_days, team_estimate, features).
        min_train: number of rows used before the first prediction (>= 5).
        llm_only_baseline: optional callable row -> point estimate; when None
            the SIMULATED seeded baseline is used and flagged in the summary.

    Returns:
        ``{"steps": [...], "summary": {mae_system, mae_team, mae_llm_only,
        coverage_pct, n_steps, llm_only_mode}}``.
    """
    ordered = sorted(
        rows, key=lambda r: (str(r.get("date") or ""), str(r.get("project_id") or ""))
    )
    n = len(ordered)
    llm_mode = "provided" if llm_only_baseline is not None else "simulated"
    llm_fn = llm_only_baseline or simulated_llm_only_point

    empty_summary = {
        "mae_system": None,
        "mae_team": None,
        "mae_llm_only": None,
        "coverage_pct": None,
        "n_steps": 0,
        "llm_only_mode": llm_mode,
    }
    if n <= min_train:
        return {"steps": [], "summary": empty_summary}

    steps: list[dict[str, Any]] = []
    system_errors: list[float] = []
    team_errors: list[float] = []
    llm_errors: list[float] = []
    coverage_hits = 0

    for i in range(min_train, n):
        row = ordered[i]
        actual = float(row["actual_days"])
        model = train_model(ordered[:i])
        prediction = estimate(model, row.get("features") or {})

        system_errors.append(abs(actual - prediction["p50"]))
        team_abs = abs(actual - float(row.get("team_estimate") or actual))
        team_errors.append(team_abs)
        llm_point = float(llm_fn(row))
        llm_errors.append(abs(actual - llm_point))
        in_interval = prediction["p10"] <= actual <= prediction["p90"]
        coverage_hits += int(in_interval)

        steps.append(
            {
                "i": i,
                "project_id": row.get("project_id"),
                "p10": prediction["p10"],
                "p50": prediction["p50"],
                "p90": prediction["p90"],
                "actual": round(actual, 1),
                "team_estimate": row.get("team_estimate"),
                "llm_only_days": round(llm_point, 1),
                "mae_system": round(fmean(system_errors), 2),
                "mae_team": round(fmean(team_errors), 2),
                "mae_llm_only": round(fmean(llm_errors), 2),
                "in_interval": in_interval,
            }
        )

    n_steps = len(steps)
    summary = {
        "mae_system": round(fmean(system_errors), 2),
        "mae_team": round(fmean(team_errors), 2),
        "mae_llm_only": round(fmean(llm_errors), 2),
        "coverage_pct": round(100.0 * coverage_hits / n_steps, 1),
        "n_steps": n_steps,
        "llm_only_mode": llm_mode,
    }
    return {"steps": steps, "summary": summary}
