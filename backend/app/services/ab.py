"""A/B comparison: repeated LLM-only estimates vs the system estimate.

Spec §4.5: run the same email through an LLM-only path n times, report mean /
std / min / max and compare with the calibrated system estimate. With a real
provider every call hits the network; with the offline stub (no API key) the
variation is SIMULATED with seeded gaussian noise around the cold-start P50 —
that path is flagged ``mode == "simulated"`` and must be labeled as such in
the UI (docs/DECISIONS.md D2).

Contract additions v0.2 (docs/API.md): when ``history_rows`` is provided,
``ab_compare`` also runs a THIRD baseline — the same email through an LLM
whose prompt includes the most recent finished projects (see
:mod:`app.services.llm_baseline`). The response gains::

    "baseline_history": {"values": [...], "mean": .., "std": .., "n": ..,
                         "mode": "real" | "simulated", ...}

All pre-v0.2 response keys are unchanged.
"""

from __future__ import annotations

from statistics import fmean, pstdev
from typing import Any, Mapping, Sequence

import numpy as np

from app.services.estimation import cold_start_estimate
from app.services.extraction import extract_features
from app.services.llm_baseline import extract_days, llm_history_estimate
from app.services.providers import LLMProvider, StubProvider
from app.services.replay import stable_seed

SIMULATED_SIGMA_RATIO = 0.15  # ~ +/-15% lognormal spread for the stub stand-in
HISTORY_SEED_TAG = "|with-history"  # distinct simulated stream for the history baseline

AB_SYSTEM_PROMPT = (
    "You are a senior software estimation analyst. Estimate the effort of the "
    "project described in the email as a single number of person-days. "
    "Answer with JSON only."
)

_AB_PROMPT_TEMPLATE = """Based ONLY on the email below, give your best single-point effort estimate in person-days.

Return exactly this JSON shape: {{"estimated_days": <number>}}

EMAIL:
<email>
{EMAIL}
</email>
"""


def build_llm_only_prompt(email_text: str) -> str:
    """The exact prompt used by every LLM-only call (A/B + measurement script)."""
    return _AB_PROMPT_TEMPLATE.replace("{EMAIL}", email_text)


def llm_only_point(email_text: str, provider: LLMProvider) -> float:
    """One LLM-only point estimate in person-days.

    Raises:
        ValueError: when the provider fails or its answer has no usable number.
    """
    payload = provider.complete_json(build_llm_only_prompt(email_text), AB_SYSTEM_PROMPT)
    days = extract_days(payload)
    if days is None:
        raise ValueError("LLM response without a usable day estimate")
    return days


def _simulated_spread(base: float, seed_key: str, count: int, floor: float = 3.0) -> list[float]:
    """Seeded gaussian stand-in around ``base`` (deterministic per seed_key)."""
    rng = np.random.default_rng(stable_seed(seed_key))
    return [
        max(floor, round(base * float(np.exp(rng.normal(0.0, SIMULATED_SIGMA_RATIO))), 1))
        for _ in range(count)
    ]


def _aggregate_block(
    values: Sequence[float],
    requested_n: int,
    errors: int,
    mode: str,
    note: str,
) -> dict[str, Any]:
    """Common aggregation shape for the history baseline block."""
    block: dict[str, Any] = {
        "values": [round(v, 1) for v in values],
        "mean": round(fmean(values), 2) if values else None,
        "std": round(pstdev(values), 2) if values else None,
        "min": round(min(values), 2) if values else None,
        "max": round(max(values), 2) if values else None,
        "n": len(values),
        "requested_n": requested_n,
        "errors": errors,
        "mode": mode,
        "note": note,
    }
    return block


def ab_compare(
    email_text: str,
    provider: LLMProvider,
    system_estimate: float | None = None,
    n: int = 10,
    history_rows: Sequence[Mapping[str, Any]] | None = None,
    history_n: int = 3,
) -> dict[str, Any]:
    """Run the LLM-only A/B comparison for one email.

    Args:
        email_text: customer email/RFP text.
        provider: LLM provider used for the repeat calls.
        system_estimate: calibrated P50 to compare against (optional).
        n: number of LLM-only calls (default 10, spec §4.5).
        history_rows: finished projects for the LLM-with-history baseline
            (contract v0.2). When None the ``baseline_history`` key is omitted.
        history_n: number of LLM-with-history calls (default 3).

    Returns:
        Dict with mode ("real" | "simulated"), values, mean/std/min/max,
        system_estimate, delta_pct, errors (failed calls) and a note. When
        ``history_rows`` is not None it additionally carries the
        ``baseline_history`` block (values/mean/std/min/max/n/errors/mode/note)
        with the same "real" | "simulated" flagging rules.

    Raises:
        ValueError: no valid LLM-only response at all in real mode, or empty
            email. A fully failed *history* batch does NOT raise: it is
            reported as ``baseline_history`` with ``n == 0`` and ``errors ==
            history_n`` so one bad baseline cannot discard the other results.
    """
    if not email_text or not email_text.strip():
        raise ValueError("Vui lòng paste email")
    count = max(1, int(n))
    history_count = max(1, int(history_n))
    provider_name = str(getattr(provider, "name", None) or type(provider).__name__)
    is_stub = isinstance(provider, StubProvider) or provider_name == "stub"

    errors = 0
    base: float | None = None
    if is_stub:
        # SIMULATED stand-in: no network, seeded noise around the cold-start P50.
        extraction = extract_features(email_text, provider=provider)
        features: dict[str, int] = {
            finding.name: int(bool(finding.value)) for finding in extraction.findings
        }
        base = cold_start_estimate(features)["p50"]
        values = _simulated_spread(base, email_text, count)
        mode = "simulated"
        note = (
            "SIMULATED LLM-only spread: offline stub provider with seeded "
            "gaussian noise (no real LLM calls). Set a real API key for live mode."
        )
    else:
        values = []
        for _ in range(count):
            try:
                values.append(llm_only_point(email_text, provider))
            except Exception:
                errors += 1
        if not values:
            raise ValueError("A/B comparison failed: no valid LLM response")
        mode = "real"
        note = f"Real LLM-only: {len(values)} calls via {provider_name} provider."

    mean = fmean(values)
    result: dict[str, Any] = {
        "mode": mode,
        "provider": provider_name,
        "n": len(values),
        "requested_n": count,
        "errors": errors,
        "values": [round(v, 1) for v in values],
        "mean": round(mean, 2),
        "std": round(pstdev(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "system_estimate": system_estimate,
        "delta_pct": (
            round((mean - float(system_estimate)) / float(system_estimate) * 100.0, 1)
            if system_estimate
            else None
        ),
        "note": note,
    }

    if history_rows is not None:
        result["baseline_history"] = _history_baseline(
            email_text, provider, provider_name, is_stub, base, history_rows, history_count
        )
    return result


def _history_baseline(
    email_text: str,
    provider: LLMProvider,
    provider_name: str,
    is_stub: bool,
    base: float | None,
    history_rows: Sequence[Mapping[str, Any]],
    history_count: int,
) -> dict[str, Any]:
    """Third baseline: LLM prompted with the recent finished projects."""
    if is_stub:
        simulated = _simulated_spread(
            float(base), f"{email_text}{HISTORY_SEED_TAG}", history_count
        )
        return _aggregate_block(
            simulated,
            history_count,
            0,
            "simulated",
            "SIMULATED LLM-with-history spread: offline stub provider with seeded "
            "gaussian noise around the stub cold-start point (no real LLM calls). "
            "Set a real API key for live mode.",
        )

    try:
        history_values = llm_history_estimate(
            email_text, history_rows, provider, n=history_count
        )
    except Exception:
        history_values = []
    history_errors = history_count - len(history_values)
    if history_values:
        note = (
            f"Real LLM-with-history: {len(history_values)}/{history_count} calls via "
            f"{provider_name} provider over {len(history_rows)} history rows."
        )
    else:
        note = (
            f"LLM-with-history failed: all {history_count} calls via {provider_name} "
            "provider returned no usable number; baseline unavailable."
        )
    return _aggregate_block(
        history_values, history_count, history_errors, "real", note
    )
