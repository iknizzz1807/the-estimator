"""Tests for the learning loop pure functions."""

from __future__ import annotations

import pytest

from app.services.learning import (
    ERR_RATIO_MAX,
    ERR_RATIO_MIN,
    accuracy_metrics,
    update_coefficients,
)

ROW = {"actual_days": 40.0, "features": {"third_party_api": 1, "payment_gateway": 1}}


def test_err_ratio_two_pulls_coefficients_toward_double() -> None:
    coefficients, counts, updates = update_coefficients(
        {"third_party_api": 1.3}, ROW, predicted_days=20.0, sample_counts={"third_party_api": 0}
    )

    assert coefficients["third_party_api"] == pytest.approx(2.6)  # 1.3 * err_ratio(2.0)
    assert coefficients["payment_gateway"] == pytest.approx(2.0)  # default 1.0, n=0
    assert counts == {"third_party_api": 1, "payment_gateway": 1}

    update_map = {u["feature"]: u for u in updates}
    assert update_map["third_party_api"]["old"] == pytest.approx(1.3)
    assert update_map["third_party_api"]["new"] == pytest.approx(2.6)
    assert update_map["third_party_api"]["n"] == 1
    assert update_map["payment_gateway"]["old"] == pytest.approx(1.0)


def test_sliding_average_moves_partially_with_existing_samples() -> None:
    coefficients, counts, _ = update_coefficients(
        {"third_party_api": 1.3}, ROW, predicted_days=20.0, sample_counts={"third_party_api": 3}
    )
    # new = (3*1.3 + 1.3*2.0) / 4 = 1.625
    assert coefficients["third_party_api"] == pytest.approx(1.625)
    assert counts["third_party_api"] == 4


def test_err_ratio_clipping() -> None:
    # actual overestimated 5x -> clipped to ERR_RATIO_MAX (2.0)
    up, _, _ = update_coefficients({}, {"actual_days": 100.0, "features": {"mobile_app": 1}}, 20.0)
    assert up["mobile_app"] == pytest.approx(1.0 * ERR_RATIO_MAX)

    # actual 10x smaller -> clipped to ERR_RATIO_MIN (0.5)
    down, _, _ = update_coefficients({}, {"actual_days": 2.0, "features": {"mobile_app": 1}}, 20.0)
    assert down["mobile_app"] == pytest.approx(1.0 * ERR_RATIO_MIN)


def test_absent_features_are_not_updated() -> None:
    coefficients, counts, updates = update_coefficients(
        {"pci_dss": 1.35}, ROW, predicted_days=20.0, sample_counts={"pci_dss": 5}
    )
    assert coefficients["pci_dss"] == pytest.approx(1.35)
    assert counts["pci_dss"] == 5
    assert {u["feature"] for u in updates} == {"third_party_api", "payment_gateway"}


def test_deterministic_and_inputs_not_mutated() -> None:
    current = {"third_party_api": 1.3}
    counts = {"third_party_api": 2}
    first = update_coefficients(current, ROW, 25.0, counts)
    second = update_coefficients(current, ROW, 25.0, counts)

    assert first == second
    assert current == {"third_party_api": 1.3}
    assert counts == {"third_party_api": 2}


def test_invalid_inputs_raise() -> None:
    with pytest.raises(ValueError):
        update_coefficients({}, ROW, predicted_days=0.0)
    with pytest.raises(ValueError):
        update_coefficients({}, {"actual_days": 0.0, "features": {}}, predicted_days=10.0)


def test_accuracy_metrics_mae_and_coverage() -> None:
    rows = [
        {"actual_days": 40.0, "p10": 30.0, "p50": 35.0, "p90": 45.0},  # error 5, covered
        {"actual_days": 20.0, "p10": 25.0, "p50": 30.0, "p90": 40.0},  # error 10, not covered
        {"actual_days": 30.0, "system_p50": 32.0},  # error 2, no interval
    ]
    metrics = accuracy_metrics(rows)

    assert metrics["n"] == 3
    assert metrics["mae"] == pytest.approx((5 + 10 + 2) / 3, abs=0.01)
    assert metrics["coverage_pct"] == pytest.approx(50.0)


def test_accuracy_metrics_empty() -> None:
    metrics = accuracy_metrics([])
    assert metrics == {"mae": None, "coverage_pct": None, "n": 0}
