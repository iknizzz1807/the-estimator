"""Tests for the walk-forward replay engine."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np

from app.features import FEATURES
from app.services.replay import replay, simulated_llm_only_point


def make_rows(n: int = 40, seed: int = 11) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        features = {name: int(rng.random() < 0.3) for name in FEATURES}
        multiplier = 1.0
        if features["data_migration"]:
            multiplier *= 1.6
        if features["mobile_app"]:
            multiplier *= 1.5
        actual = 18.0 * multiplier * math.exp(rng.normal(0.0, 0.15))
        rows.append(
            {
                "project_id": f"P{i:03d}",
                "date": (dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat(),
                "actual_days": round(actual, 1),
                "team_estimate": round(actual * 0.85, 1),
                "features": features,
            }
        )
    return rows


def test_replay_produces_walk_forward_steps() -> None:
    rows = make_rows(40)
    result = replay(rows, min_train=10)

    assert len(result["steps"]) == 30
    summary = result["summary"]
    assert summary["n_steps"] == 30
    assert summary["llm_only_mode"] == "simulated"
    assert math.isfinite(summary["mae_system"])
    assert math.isfinite(summary["mae_team"])
    assert math.isfinite(summary["mae_llm_only"])
    assert 0.0 <= summary["coverage_pct"] <= 100.0

    for step in result["steps"]:
        assert step["p10"] <= step["p50"] <= step["p90"]
        assert isinstance(step["in_interval"], bool)
        assert math.isfinite(step["mae_system"])


def test_replay_is_deterministic() -> None:
    rows = make_rows(24)
    first = replay(rows, min_train=10)
    second = replay(rows, min_train=10)
    assert first == second


def test_replay_accepts_provided_llm_baseline() -> None:
    rows = make_rows(20)
    result = replay(rows, min_train=10, llm_only_baseline=lambda row: 20.0)
    assert result["summary"]["llm_only_mode"] == "provided"
    assert result["summary"]["n_steps"] == 10
    assert math.isfinite(result["summary"]["mae_llm_only"])


def test_replay_handles_too_few_rows() -> None:
    result = replay(make_rows(5), min_train=10)
    assert result["steps"] == []
    assert result["summary"]["n_steps"] == 0
    assert result["summary"]["mae_system"] is None


def test_simulated_llm_only_point_is_seeded_and_log_normal() -> None:
    row = {"project_id": "P777", "features": {"data_migration": 1}}
    first = simulated_llm_only_point(row)
    second = simulated_llm_only_point(row)
    assert first == second  # same row -> same value (stable seed)

    other = simulated_llm_only_point({"project_id": "P778", "features": {"data_migration": 1}})
    assert other != first
    assert first > 0
