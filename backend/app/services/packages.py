"""Budget-fit scope packages for closing deals (contract docs/API.md v0.2).

Given a customer budget in days and the extracted feature vector, propose
three scope packages built from the *same* model:

* ``core`` / "Essential"   — phase out the two highest-impact optionals,
* ``standard`` / "Standard" — phase out the single highest-impact optional,
* ``full`` / "Full scope"   — everything the customer asked for.

Only the capabilities in :data:`CUTTABLE_OPTIONALS` are ever phased out, and
only when they are *present* (value == 1): the list is the subset of the 15
canonical features that is plausibly sellable as "phase 2". Unknown features
(``None``) stay unknown in **every** tier so the predictive interval keeps its
honest uncertainty (they are never silently treated as absent by the MC
engine). Present optionals are ranked by their learned impact — the model
multiplier from :func:`app.services.estimation.coefficients` — and ties keep
the :data:`CUTTABLE_OPTIONALS` order so ranking is deterministic.

Over-budget probability uses a documented lognormal approximation of each
tier's predictive distribution, fitted from its own interval::

    mu    = ln(p50)
    sigma = (ln(p90) - ln(p10)) / (2 * z90),  z90 = 1.2816 (normal 90% point)
    prob  = P(actual > budget) = 1 - Phi((ln(budget) - mu) / sigma)

This mirrors the shape of the conformal interval without re-fitting, is cheap,
and is deterministic. The probability is clamped to a tiny epsilon and rounded
to 3 decimals.

The tier estimates themselves come from the Monte-Carlo engine
(``app.services.estimation.estimate_mc``) which is imported lazily: while the
MC engine is not yet on disk (or in stripped-down deployments) the fallback
treats unknown features as absent and uses the point estimator, reporting
``method: "point"``. The import hook (:func:`_load_estimate_mc`) is separate
so tests can simulate the missing-MC path.

Public API (frozen shape, docs/API.md v0.2)::

    build_packages(model, features, budget_days, n=2000, seed=42) -> dict

``features_included`` is always the full 15-name map after the tier edits
(unknowns stay ``None``); ``excluded`` lists only the capabilities that tier
deliberately phased out.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping

from app.features import FEATURES
from app.services.estimation import EstimatorModel, coefficients, estimate

#: Plausibly phaseable capabilities, in the order used to break ranking ties.
#: This is the frozen list the three scope tiers are built from.
CUTTABLE_OPTIONALS: list[str] = [
    "offline_mode",
    "mobile_app",
    "realtime_ui",
    "multi_currency",
    "external_data_sync",
    "audit_logging",
]

#: Tier -> (label, number of highest-impact present optionals phased out).
TIER_CUTS: dict[str, int] = {"core": 2, "standard": 1, "full": 0}
TIER_LABELS: dict[str, str] = {"core": "Essential", "standard": "Standard", "full": "Full scope"}
#: Response order (least scope -> most scope), as in docs/API.md v0.2.
TIER_ORDER: tuple[str, ...] = ("core", "standard", "full")

#: A tier qualifies for recommendation when its over-budget risk is at most this.
OVER_BUDGET_THRESHOLD = 0.25
#: Probabilities are clamped to [EPSILON, 1 - EPSILON] (never exactly 0/1).
PROB_EPSILON = 0.001
#: Standard-normal 90% quantile, i.e. the z for the P10/P90 conformal tail.
Z_P90 = 1.2816

RISK_NOTE = (
    "all packages exceed the 25% over-budget threshold; Essential (core) is the "
    "minimum-risk scope - renegotiate the budget or timeline"
)

#: Estimator callable signature: (model, features, n, seed) -> estimate dict.
EstimatorFn = Callable[[EstimatorModel, Mapping[str, int | None], int, int], dict[str, Any]]


# --------------------------------------------------------------------------- #
# Feature helpers
# --------------------------------------------------------------------------- #


def _normalize_features(features: Mapping[str, Any] | None) -> dict[str, int | None]:
    """Canonical 15-name map: present -> 1, absent -> 0, unknown/missing -> None."""
    source = features or {}
    return {
        name: (None if source.get(name) is None else int(bool(source.get(name))))
        for name in FEATURES
    }


def _rank_present_cuttables(
    model: EstimatorModel, features: Mapping[str, int | None]
) -> list[str]:
    """Present (== 1) cuttables, highest learned multiplier first.

    Ties (identical rounded multipliers) fall back to CUTTABLE_OPTIONALS order.
    """
    multipliers = {
        item["feature"]: float(item["multiplier"]) for item in coefficients(model)
    }
    order = {name: index for index, name in enumerate(CUTTABLE_OPTIONALS)}
    present = [name for name in CUTTABLE_OPTIONALS if features.get(name) == 1]
    present.sort(key=lambda name: (-multipliers.get(name, 1.0), order[name]))
    return present


# --------------------------------------------------------------------------- #
# Estimation
# --------------------------------------------------------------------------- #


def _load_estimate_mc() -> Callable[..., dict[str, Any]]:
    """Import hook for the Monte-Carlo engine (separate so tests can stub it).

    Raises ImportError while ``estimate_mc`` is not shipped, which drives the
    documented point-estimate fallback in :func:`_default_estimator`.
    """
    from app.services.estimation import estimate_mc

    return estimate_mc


def _point_fallback(
    model: EstimatorModel, features: Mapping[str, int | None]
) -> dict[str, Any]:
    """Unknowns-as-absent point estimate (used when estimate_mc is missing).

    Unknown features are set to 0 for the math (documented fallback), while the
    tier's ``features_included`` still reports them as ``None``.
    """
    zeroed = {name: (0 if value is None else value) for name, value in features.items()}
    return {**estimate(model, zeroed), "unit": "days", "method": "point"}


def _default_estimator(
    model: EstimatorModel, features: Mapping[str, int | None], n: int, seed: int
) -> dict[str, Any]:
    """estimate_mc when available, else the documented point fallback."""
    try:
        estimate_mc = _load_estimate_mc()
    except ImportError:
        return _point_fallback(model, features)
    try:
        return estimate_mc(model, features, n=n, seed=seed)
    except TypeError:
        # Tolerate an estimate_mc variant with fixed n/seed (different
        # signature): fall back to its own defaults rather than crashing.
        return estimate_mc(model, features)


def _tier_estimate(
    model: EstimatorModel,
    features: Mapping[str, int | None],
    n: int = 2000,
    seed: int = 42,
    estimator: EstimatorFn | None = None,
) -> dict[str, Any]:
    """Estimate one tier; returns the contract estimate dict.

    ``estimator`` is injectable for tests; it defaults to estimate_mc with the
    point fallback (see :func:`_default_estimator`).
    """
    raw = (estimator or _default_estimator)(model, features, n, seed)
    has_unknowns = any(value is None for value in features.values())
    return {
        "p10": float(raw["p10"]),
        "p50": float(raw["p50"]),
        "p90": float(raw["p90"]),
        "mode": str(raw.get("mode", "calibrated")),
        "unit": str(raw.get("unit", "days")),
        "method": str(raw.get("method", "mc" if has_unknowns else "point")),
    }


# --------------------------------------------------------------------------- #
# Over-budget probability + recommendation
# --------------------------------------------------------------------------- #


def _phi(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _over_budget_prob(estimate_row: Mapping[str, Any], budget_days: float | None) -> float | None:
    """P(actual days > budget) under the tier's lognormal interval fit.

    ``None`` budget -> ``None`` (the caller recommends the full scope). A
    degenerate interval (p10 == p90) falls back to a step at p50. The result is
    clamped to [EPSILON, 1 - EPSILON] and rounded to 3 decimals.
    """
    if budget_days is None:
        return None
    p10 = float(estimate_row["p10"])
    p50 = float(estimate_row["p50"])
    p90 = float(estimate_row["p90"])
    budget = float(budget_days)

    if p10 > 0 and p90 > p10 and p50 > 0 and budget > 0:
        sigma = (math.log(p90) - math.log(p10)) / (2.0 * Z_P90)
        z = (math.log(budget) - math.log(p50)) / sigma
        probability = 1.0 - _phi(z)
    else:  # degenerate interval and/or non-positive budget
        probability = 1.0 if budget < p50 else 0.0

    return round(min(1.0 - PROB_EPSILON, max(PROB_EPSILON, probability)), 3)


def _recommend(
    packages: list[dict[str, Any]], budget_days: float | None
) -> tuple[str, str | None]:
    """Most-scoped tier with P(over budget) <= 0.25, else core + a risk note.

    Walks full -> standard -> core, so ties resolve to the higher tier.
    """
    if budget_days is None:
        return "full", None
    for package in reversed(packages):  # TIER_ORDER reversed: full, standard, core
        probability = package["over_budget_prob"]
        if probability is not None and probability <= OVER_BUDGET_THRESHOLD:
            return str(package["tier"]), None
    return "core", RISK_NOTE


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def _tier_note(tier: str, cut: list[str], n_present: int) -> str:
    """Human note per tier: what was phased out (or why nothing could be)."""
    if not cut:
        if tier == "full":
            return "full scope: nothing phased out"
        return "no phaseable optional capabilities detected; equivalent to Full scope"
    names = ", ".join(cut)
    if tier == "core":
        if len(cut) == 1:
            note = f"phased scope: drop the highest-impact optional capability ({names})"
            if n_present < 2:
                note += (
                    "; identical to Standard because only one phaseable capability"
                    " was detected"
                )
            return note
        return f"phased scope: drop the top-{len(cut)} highest-impact optional capabilities ({names})"
    return f"phased scope: drop the highest-impact optional capability ({names})"


def build_packages(
    model: EstimatorModel,
    features: Mapping[str, int | None],
    budget_days: float | None,
    n: int = 2000,
    seed: int = 42,
) -> dict:
    """Build the three budget-fit scope packages (docs/API.md v0.2).

    Deterministic for a given ``seed``. Returns::

        {"budget_days", "packages": [{tier, label, estimate, over_budget_prob,
         features_included, excluded, notes}], "recommendation", "method"}

    plus ``recommendation_note`` when every tier exceeds the 25% risk
    threshold (the core tier is still recommended, with the caveat).
    """
    normalized = _normalize_features(features)
    ranked = _rank_present_cuttables(model, normalized)

    budget = None if budget_days is None else float(budget_days)
    packages: list[dict[str, Any]] = []
    for tier in TIER_ORDER:
        cut = ranked[: TIER_CUTS[tier]]
        tier_features = {
            name: (0 if name in cut else normalized[name]) for name in FEATURES
        }
        estimate_row = _tier_estimate(model, tier_features, n=n, seed=seed)
        packages.append(
            {
                "tier": tier,
                "label": TIER_LABELS[tier],
                "estimate": estimate_row,
                "over_budget_prob": _over_budget_prob(estimate_row, budget),
                "features_included": dict(tier_features),
                "excluded": list(cut),
                "notes": _tier_note(tier, cut, n_present=len(ranked)),
            }
        )

    recommendation, risk_note = _recommend(packages, budget)
    method = "mc" if any(pkg["estimate"]["method"] == "mc" for pkg in packages) else "point"
    result: dict[str, Any] = {
        "budget_days": budget_days,
        "packages": packages,
        "recommendation": recommendation,
        "method": method,
    }
    if risk_note:
        result["recommendation_note"] = risk_note
    return result
