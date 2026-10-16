"""Tests for the estimation engine (Ridge + conformal intervals + cold start)."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pytest

from app.features import FEATURES
from app.services.estimation import (
    RIDGE_ALPHA,
    cold_start_estimate,
    coefficients,
    estimate,
    load_model,
    point_estimate,
    save_model,
    train_model,
)

# Known test-local formula (independent from the data-gen agent's hidden one):
# actual = 20 * 1.6^data_migration * 1.5^mobile_app * 1.4^third_party_api * lognormal(0.15)
TRUE_MULTIPLIERS = {"data_migration": 1.6, "mobile_app": 1.5, "third_party_api": 1.4}
BASE_DAYS = 20.0
NOISE_SIGMA = 0.15


def make_rows(n: int, seed: int = 42, start_index: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        features = {name: int(rng.random() < 0.35) for name in FEATURES}
        multiplier = math.prod(
            TRUE_MULTIPLIERS.get(name, 1.0) for name, present in features.items() if present
        )
        actual = BASE_DAYS * multiplier * math.exp(rng.normal(0.0, NOISE_SIGMA))
        index = start_index + i
        rows.append(
            {
                "project_id": f"P{index:03d}",
                "date": (dt.date(2025, 1, 1) + dt.timedelta(days=index)).isoformat(),
                "actual_days": round(actual, 1),
                "team_estimate": round(actual * 0.82, 1),
                "features": features,
            }
        )
    return rows


@pytest.fixture(scope="module")
def train_rows() -> list[dict]:
    return make_rows(120, seed=42)


@pytest.fixture(scope="module")
def model(train_rows):
    return train_model(train_rows)


def test_train_requires_at_least_five_rows() -> None:
    with pytest.raises(ValueError):
        train_model(make_rows(4, seed=1))


def test_recovers_known_multiplier(model) -> None:
    by_name = {c["feature"]: c for c in coefficients(model)}
    assert len(by_name) == 15
    assert set(by_name) == set(FEATURES)
    assert by_name["data_migration"]["raw"] > 0
    assert 1.3 <= by_name["data_migration"]["multiplier"] <= 1.9
    assert RIDGE_ALPHA == 0.3  # pinned; CV-tuned in docs/DECISIONS.md D8
    assert model.n_train == 120
    assert model.calibrated is True


def test_coverage_on_holdout_rows(model) -> None:
    holdout = make_rows(40, seed=99)
    covered = 0
    for row in holdout:
        prediction = estimate(model, row["features"])
        if prediction["p10"] <= row["actual_days"] <= prediction["p90"]:
            covered += 1
    coverage_pct = 100.0 * covered / len(holdout)
    assert 60.0 <= coverage_pct <= 100.0


def test_deterministic_same_rows_same_output(train_rows, model) -> None:
    model_again = train_model(train_rows)
    scenarios = [
        {},
        {"data_migration": 1},
        {"mobile_app": 1, "payment_gateway": 1},
        {name: 1 for name in FEATURES},
    ]
    for features in scenarios:
        assert estimate(model, features) == estimate(model_again, features)


def test_intervals_are_ordered_and_floor_at_three_days(model) -> None:
    scenarios = [{}] + [{name: int(i % 2 == 0)} for i, name in enumerate(FEATURES)]
    for features in scenarios:
        calibrated = estimate(model, features)
        cold = cold_start_estimate(features)
        for prediction in (calibrated, cold):
            assert prediction["p10"] <= prediction["p50"] <= prediction["p90"]
            assert prediction["p10"] >= 3.0
        assert calibrated["mode"] == "calibrated"
        assert cold["mode"] == "cold_start"


def test_cold_start_is_monotonic_and_wider(model) -> None:
    none_present = cold_start_estimate({})["p50"]
    one = cold_start_estimate({"data_migration": 1})["p50"]
    two = cold_start_estimate({"data_migration": 1, "mobile_app": 1})["p50"]
    assert none_present <= one <= two

    for features in ({}, {"pci_dss": 1}, {"data_migration": 1, "mobile_app": 1}):
        cold = cold_start_estimate(features)
        calibrated = estimate(model, features)
        cold_ratio = (cold["p90"] - cold["p10"]) / cold["p50"]
        cal_ratio = (calibrated["p90"] - calibrated["p10"]) / calibrated["p50"]
        assert cold_ratio > cal_ratio


def test_point_estimate_matches_p50(model) -> None:
    features = {"data_migration": 1, "realtime_ui": 1}
    assert point_estimate(model, features) == estimate(model, features)["p50"]


def test_save_and_load_roundtrip(model, tmp_path) -> None:
    path = save_model(model, tmp_path / "estimator_model.pkl")
    loaded = load_model(path)
    features = {"data_migration": 1, "third_party_api": 1}
    assert estimate(loaded, features) == estimate(model, features)


def test_small_training_set_uses_wide_fallback() -> None:
    small = train_model(make_rows(7, seed=5))
    assert small.calibrated is False
    prediction = estimate(small, {})
    ratio = (prediction["p90"] - prediction["p10"]) / prediction["p50"]
    assert ratio >= 1.0  # deliberately wide warm-up interval
