"""Tests for the A/B comparison engine."""

from __future__ import annotations

from statistics import fmean, pstdev

import pytest

from app.services.ab import ab_compare
from app.services.providers import StubProvider

EMAIL = "We need a payment integration with Stripe and PCI DSS compliance for card data."


class CycleProvider:
    """Fake deterministic provider cycling through canned day estimates."""

    name = "fake"

    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def complete_json(self, prompt, system=None):
        value = self.values[self.calls % len(self.values)]
        self.calls += 1
        return {"estimated_days": value}


class BrokenProvider:
    name = "broken"

    def complete_json(self, prompt, system=None):
        raise RuntimeError("network down")


class FlakyProvider:
    """Fails every other call, succeeds on the others."""

    name = "flaky"

    def __init__(self):
        self.calls = 0

    def complete_json(self, prompt, system=None):
        self.calls += 1
        if self.calls % 2 == 1:
            raise RuntimeError("transient")
        return {"estimated_days": 25}


def test_real_mode_aggregates_fake_provider_deterministically() -> None:
    values = [30, 32, 28, 31, 29, 33, 27, 30, 31, 29]
    provider = CycleProvider(values)
    result = ab_compare(EMAIL, provider, system_estimate=35.0, n=10)

    assert result["mode"] == "real"
    assert result["n"] == 10
    assert result["errors"] == 0
    assert provider.calls == 10
    assert result["mean"] == pytest.approx(round(fmean(values), 2))
    assert result["std"] == pytest.approx(round(pstdev(values), 2))
    assert result["min"] == 27
    assert result["max"] == 33
    assert result["delta_pct"] == pytest.approx(round((30.0 - 35.0) / 35.0 * 100, 1))
    assert result["values"] == [round(v, 1) for v in values]


def test_stub_mode_is_simulated_and_deterministic() -> None:
    first = ab_compare(EMAIL, StubProvider(), system_estimate=None, n=10)
    second = ab_compare(EMAIL, StubProvider(), system_estimate=None, n=10)

    assert first["mode"] == "simulated"
    assert first["n"] == 10
    assert "SIMULATED" in first["note"]
    assert all(v > 0 for v in first["values"])
    assert first == second
    assert first["system_estimate"] is None
    assert first["delta_pct"] is None


def test_broken_provider_raises_value_error() -> None:
    with pytest.raises(ValueError):
        ab_compare(EMAIL, BrokenProvider(), n=3)


def test_partial_failures_are_counted() -> None:
    result = ab_compare(EMAIL, FlakyProvider(), n=4)
    assert result["mode"] == "real"
    assert result["n"] == 2
    assert result["errors"] == 2
    assert result["mean"] == 25.0


def test_empty_email_raises() -> None:
    with pytest.raises(ValueError, match="Vui lòng paste email"):
        ab_compare("   ", CycleProvider([10]), n=1)
