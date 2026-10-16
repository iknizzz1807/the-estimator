"""A/B comparison: repeated LLM-only estimates vs the system estimate.

Spec §4.5: run the same email through an LLM-only path n times, report mean /
std / min / max and compare with the calibrated system estimate. With a real
provider every call hits the network; with the offline stub (no API key) the
variation is SIMULATED with seeded gaussian noise around the cold-start P50 —
that path is flagged ``mode == "simulated"`` and must be labeled as such in
the UI (docs/DECISIONS.md D2).
"""

from __future__ import annotations

import math
from statistics import fmean, pstdev
from typing import Any, Mapping

import numpy as np

from app.services.estimation import cold_start_estimate
from app.services.extraction import extract_features
from app.services.providers import LLMProvider, StubProvider
from app.services.replay import stable_seed

SIMULATED_SIGMA_RATIO = 0.15  # ~ +/-15% lognormal spread for the stub stand-in

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

_DAYS_KEYS = ("estimated_days", "days", "estimate", "p50")


def _extract_days(data: Any) -> float | None:
    """Pull a numeric day estimate out of a provider JSON payload."""
    if not isinstance(data, Mapping):
        return None
    for key in _DAYS_KEYS:
        if key in data:
            try:
                value = float(data[key])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                return value
    return None


def ab_compare(
    email_text: str,
    provider: LLMProvider,
    system_estimate: float | None = None,
    n: int = 10,
) -> dict[str, Any]:
    """Run the LLM-only A/B comparison for one email.

    Args:
        email_text: customer email/RFP text.
        provider: LLM provider used for the repeat calls.
        system_estimate: calibrated P50 to compare against (optional).
        n: number of LLM calls (default 10, spec §4.5).

    Returns:
        Dict with mode ("real" | "simulated"), values, mean/std/min/max,
        system_estimate, delta_pct, errors (failed calls) and a note.

    Raises:
        ValueError: no valid LLM response at all in real mode, or empty email.
    """
    if not email_text or not email_text.strip():
        raise ValueError("Vui lòng paste email")
    count = max(1, int(n))
    provider_name = str(getattr(provider, "name", None) or type(provider).__name__)
    is_stub = isinstance(provider, StubProvider) or provider_name == "stub"

    errors = 0
    if is_stub:
        # SIMULATED stand-in: no network, seeded noise around the cold-start P50.
        extraction = extract_features(email_text, provider=provider)
        features: dict[str, int] = {
            finding.name: int(bool(finding.value)) for finding in extraction.findings
        }
        base = cold_start_estimate(features)["p50"]
        rng = np.random.default_rng(stable_seed(email_text))
        values = [
            max(3.0, round(base * float(np.exp(rng.normal(0.0, SIMULATED_SIGMA_RATIO))), 1))
            for _ in range(count)
        ]
        mode = "simulated"
        note = (
            "SIMULATED LLM-only spread: offline stub provider with seeded "
            "gaussian noise (no real LLM calls). Set a real API key for live mode."
        )
    else:
        prompt = _AB_PROMPT_TEMPLATE.replace("{EMAIL}", email_text)
        values = []
        for _ in range(count):
            try:
                data = provider.complete_json(prompt, AB_SYSTEM_PROMPT)
                days = _extract_days(data)
            except Exception:
                days = None
            if days is None:
                errors += 1
            else:
                values.append(days)
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
    return result
