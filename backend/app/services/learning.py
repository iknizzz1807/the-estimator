"""Learning loop as pure functions (spec §4.4, checklist Phase 2).

Two artifacts come from entering an actual duration:

1. ``update_coefficients`` — an *immediate* sliding-average correction of the
   per-feature multipliers. Spec §4.4 requires the coefficients to update
   right away (and to be auditable in the UI as "1.35 -> 1.41"), so this is
   what the corrections UI watches. NOTE: this is the immediate-update +
   audit artifact only (*not* the model). The Ridge estimator itself is
   retrained on the next training run from the full row history — the
   coefficients here do not silently mutate the trained model.

2. ``accuracy_metrics`` — rolling MAE / coverage shown to the user.

Deterministic: same inputs -> same outputs, no randomness, no time.
"""

from __future__ import annotations

from statistics import fmean
from typing import Any, Mapping, Sequence

from app.features import FEATURES

ERR_RATIO_MIN = 0.5
ERR_RATIO_MAX = 2.0
DEFAULT_COEFFICIENT = 1.0


def update_coefficients(
    current: Mapping[str, float],
    row: Mapping[str, Any],
    predicted_days: float,
    sample_counts: Mapping[str, int] | None = None,
) -> tuple[dict[str, float], dict[str, int], list[dict[str, Any]]]:
    """Sliding-average coefficient update for one completed project.

    ``err_ratio = clip(actual_days / predicted_days, 0.5, 2.0)`` then for every
    feature present in the row::

        new[f] = (n[f]*old[f] + old[f]*err_ratio) / (n[f] + 1);  n[f] += 1

    Returns ``(new_coefficients, new_sample_counts, updates)`` where each update
    record is ``{feature, old, new, n}`` (audit trail for spec §4.4).
    """
    predicted = float(predicted_days)
    if predicted <= 0:
        raise ValueError("predicted_days must be > 0")
    actual_raw = row.get("actual_days")
    if actual_raw is None:
        raise ValueError("row.actual_days is required")
    actual = float(actual_raw)
    if actual <= 0:
        raise ValueError("actual_days must be > 0 (spec §9)")

    err_ratio = min(ERR_RATIO_MAX, max(ERR_RATIO_MIN, actual / predicted))

    new_coefficients: dict[str, float] = {k: float(v) for k, v in current.items()}
    new_counts: dict[str, int] = {k: int(v) for k, v in (sample_counts or {}).items()}
    updates: list[dict[str, Any]] = []

    features = row.get("features") or {}
    for name in FEATURES:  # canonical order -> deterministic updates list
        if not features.get(name):
            continue
        old = float(new_coefficients.get(name, DEFAULT_COEFFICIENT))
        n = int(new_counts.get(name, 0))
        new = (n * old + old * err_ratio) / (n + 1)
        new_coefficients[name] = new
        new_counts[name] = n + 1
        updates.append({"feature": name, "old": old, "new": new, "n": n + 1})

    return new_coefficients, new_counts, updates


def accuracy_metrics(rows_with_predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """MAE + interval coverage over rows carrying actuals and predictions.

    Accepted prediction keys: ``p50`` (or ``system_p50``) and optional
    ``p10``/``p90`` for coverage. Empty input -> None values (UI empty state).
    """
    if not rows_with_predictions:
        return {"mae": None, "coverage_pct": None, "n": 0}

    errors: list[float] = []
    coverage_hits = 0
    coverage_total = 0
    for row in rows_with_predictions:
        actual_raw = row.get("actual_days")
        predicted_raw = row.get("p50", row.get("system_p50"))
        if actual_raw is None or predicted_raw is None:
            continue
        actual = float(actual_raw)
        errors.append(abs(actual - float(predicted_raw)))
        p10, p90 = row.get("p10"), row.get("p90")
        if p10 is not None and p90 is not None:
            coverage_total += 1
            if float(p10) <= actual <= float(p90):
                coverage_hits += 1

    if not errors:
        return {"mae": None, "coverage_pct": None, "n": 0}
    coverage_pct = (
        round(100.0 * coverage_hits / coverage_total, 1) if coverage_total else None
    )
    return {"mae": round(fmean(errors), 2), "coverage_pct": coverage_pct, "n": len(errors)}
