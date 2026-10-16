"""Tests for the A/B comparison engine and the LLM-with-history baseline."""

from __future__ import annotations

import datetime as dt
from statistics import fmean, pstdev

import pytest

from app.services.ab import AB_SYSTEM_PROMPT, ab_compare
from app.services.llm_baseline import (
    HISTORY_SYSTEM_PROMPT,
    MAX_CLAMP_DAYS,
    build_history_prompt,
    llm_history_estimate,
)
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


class DaysProvider:
    """Canned ``{"days": ...}`` answers (Exceptions in the list are raised)."""

    name = "daysfake"

    def __init__(self, values):
        self.values = list(values)
        self.prompts: list[str] = []
        self.systems: list[str | None] = []
        self.calls = 0

    def complete_json(self, prompt, system=None):
        self.prompts.append(prompt)
        self.systems.append(system)
        value = self.values[self.calls % len(self.values)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return {"days": value}


class RawJsonProvider:
    """Returns a raw (fenced) JSON string instead of a parsed dict."""

    name = "rawjson"

    def complete_json(self, prompt, system=None):
        return 'Sure! Here is the answer:\n```json\n{"days": 34}\n```'


class HistoryBrokenProvider:
    """LLM-only calls succeed, every history call fails."""

    name = "historybroken"

    def complete_json(self, prompt, system=None):
        if '"days"' in prompt:
            raise RuntimeError("history endpoint down")
        return {"estimated_days": 25}


class HistoryFlakyProvider:
    """LLM-only succeeds; every other history call fails."""

    name = "historyflaky"

    def __init__(self):
        self.history_calls = 0

    def complete_json(self, prompt, system=None):
        if '"days"' in prompt:
            self.history_calls += 1
            if self.history_calls % 2 == 1:
                raise RuntimeError("transient")
            return {"days": 50}
        return {"estimated_days": 25}


def make_history_rows(n: int = 20, start: dt.date = dt.date(2025, 1, 1)) -> list[dict]:
    """Deterministic finished projects, oldest first (P000 oldest, P{n-1} newest)."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "project_id": f"P{i:03d}",
                "date": (start + dt.timedelta(days=i)).isoformat(),
                "actual_days": 10.0 + i,
                "team_estimate": 9.0 + i,
                "status": "done",
                "features": {"payment_gateway": i % 2 == 0, "data_migration": i % 3 == 0},
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# llm_history_estimate — prompt construction
# --------------------------------------------------------------------------- #


def test_history_prompt_contains_most_recent_15_finished_projects() -> None:
    provider = DaysProvider([30])
    llm_history_estimate(EMAIL, make_history_rows(20), provider, n=1)

    prompt = provider.prompts[0]
    assert provider.systems[0] == HISTORY_SYSTEM_PROMPT
    assert "RECENT FINISHED PROJECTS" in prompt
    assert EMAIL in prompt
    assert '"days"' in prompt  # DeepSeek needs the word json in the prompt too
    # 20 rows -> only the 15 most recent (P019..P005) are rendered.
    assert "P019" in prompt and "P005" in prompt
    assert "P004" not in prompt and "P000" not in prompt
    # Newest first.
    assert prompt.index("P019") < prompt.index("P005")
    # Feature names + actual days of the sample rows.
    assert "payment_gateway" in prompt
    assert "29" in prompt  # P019 actual_days = 10 + 19


def test_history_prompt_drops_non_done_and_invalid_rows() -> None:
    rows = make_history_rows(3)
    rows.append(
        {"project_id": "PP", "date": "2025-06-01", "actual_days": 40, "status": "planned",
         "features": {}}
    )
    rows.append(
        {"project_id": "PZ", "date": "2025-06-02", "actual_days": None, "status": "done",
         "features": {}}
    )
    prompt = build_history_prompt(EMAIL, rows)
    assert "PP" not in prompt and "PZ" not in prompt
    assert "P002" in prompt


def test_history_prompt_without_rows_says_so() -> None:
    prompt = build_history_prompt(EMAIL, [])
    assert "(no finished projects yet)" in prompt


# --------------------------------------------------------------------------- #
# llm_history_estimate — value collection
# --------------------------------------------------------------------------- #


def test_history_estimate_clamps_values_to_1_365() -> None:
    values = llm_history_estimate(EMAIL, make_history_rows(3), DaysProvider([10, 0.4, 500]), n=3)
    assert values == [10.0, 1.0, MAX_CLAMP_DAYS]


def test_history_estimate_skips_failed_calls() -> None:
    provider = DaysProvider([RuntimeError("boom"), 7])
    values = llm_history_estimate(EMAIL, make_history_rows(3), provider, n=2)
    assert values == [7.0]
    assert provider.calls == 2  # failure count = n - len(values) = 1


def test_history_estimate_returns_empty_when_all_calls_fail() -> None:
    values = llm_history_estimate(EMAIL, make_history_rows(3), BrokenProvider(), n=2)
    assert values == []


def test_history_estimate_parses_raw_json_string_response() -> None:
    values = llm_history_estimate(EMAIL, make_history_rows(3), RawJsonProvider(), n=1)
    assert values == [34.0]


def test_history_estimate_empty_email_raises() -> None:
    with pytest.raises(ValueError, match="Vui lòng paste email"):
        llm_history_estimate("   ", make_history_rows(3), DaysProvider([10]), n=1)


# --------------------------------------------------------------------------- #
# ab_compare — existing LLM-only behaviour
# --------------------------------------------------------------------------- #


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
    assert "baseline_history" not in result


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


# --------------------------------------------------------------------------- #
# ab_compare — third baseline (LLM with history, contract v0.2)
# --------------------------------------------------------------------------- #


def test_history_baseline_real_provider_adds_block() -> None:
    provider = CycleProvider([30, 32, 60, 64])  # 2 llm-only calls, then 2 history calls
    result = ab_compare(EMAIL, provider, system_estimate=50.0, n=2, history_rows=make_history_rows(5), history_n=2)

    assert provider.calls == 4
    assert result["values"] == [30.0, 32.0]  # llm-only unchanged
    baseline = result["baseline_history"]
    assert baseline["mode"] == "real"
    assert baseline["values"] == [60.0, 64.0]
    assert baseline["mean"] == 62.0
    assert baseline["std"] == pytest.approx(2.0)
    assert baseline["min"] == 60.0 and baseline["max"] == 64.0
    assert baseline["n"] == 2 and baseline["requested_n"] == 2 and baseline["errors"] == 0
    assert "Real LLM-with-history" in baseline["note"]


def test_history_baseline_stub_is_simulated_and_deterministic() -> None:
    rows = make_history_rows(5)
    first = ab_compare(EMAIL, StubProvider(), n=4, history_rows=rows, history_n=3)
    second = ab_compare(EMAIL, StubProvider(), n=4, history_rows=rows, history_n=3)

    baseline = first["baseline_history"]
    assert baseline["mode"] == "simulated"
    assert baseline["n"] == 3
    assert len(baseline["values"]) == 3
    assert all(v > 0 for v in baseline["values"])
    assert "SIMULATED" in baseline["note"]
    assert first == second
    # The simulated history stream is independent from the llm-only stream.
    assert baseline["values"] != first["values"]


def test_history_baseline_absent_without_history_rows() -> None:
    result = ab_compare(EMAIL, CycleProvider([30]), n=1)
    assert "baseline_history" not in result


def test_history_baseline_all_failures_are_flagged() -> None:
    result = ab_compare(EMAIL, HistoryBrokenProvider(), n=2, history_rows=make_history_rows(4), history_n=3)

    assert result["mode"] == "real" and result["values"] == [25.0, 25.0]
    baseline = result["baseline_history"]
    assert baseline["mode"] == "real"
    assert baseline["n"] == 0
    assert baseline["errors"] == 3
    assert baseline["mean"] is None and baseline["std"] is None
    assert baseline["values"] == []
    assert "failed" in baseline["note"]


def test_history_baseline_partial_failures_are_counted() -> None:
    result = ab_compare(EMAIL, HistoryFlakyProvider(), n=2, history_rows=make_history_rows(4), history_n=3)

    baseline = result["baseline_history"]
    assert baseline["n"] == 1
    assert baseline["errors"] == 2
    assert baseline["values"] == [50.0]
