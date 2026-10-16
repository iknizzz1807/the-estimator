"""Estimation engine: Ridge regression on log(actual_days) + conformal intervals.

Spec §4.2: estimation is data-driven (never LLM-driven), each feature has a
learned multiplier and the [P10, P90] interval is calibrated. We fit
``log(actual_days) ~ Ridge(alpha=0.3)`` over the 15 binary features and build
the interval from out-of-fold conformal residual quantiles.

Cold start (no history) uses documented conservative industry multipliers with
a deliberately wider interval than a calibrated model.

Unknown features (``None`` in the mapping) are honest missing information:
:func:`estimate_mc` samples them from the training-set prevalence and adds
bootstrapped conformal residuals, so missing answers widen the interval instead
of silently shifting the estimate down toward the all-zeros vector.

Everything here is pure and deterministic: same rows + same features -> same
numbers (spec §7.2, std < 5%). The Monte Carlo sampler is seeded
(``np.random.default_rng(seed)``) and therefore deterministic too.
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold, cross_val_predict

from app.features import FEATURES

MIN_ROWS = 5  # below this there is nothing to learn (spec §9 "khuyến nghị >= 10")
MIN_ROWS_CONFORMAL = 10
RIDGE_ALPHA = 0.3  # CV-selected on the seeded dataset (docs/DECISIONS.md D8)
MIN_DAYS = 3.0
QUANTILE_LEVELS = (0.1, 0.5, 0.9)

#: Fallback residual quantiles (log space) when n < MIN_ROWS_CONFORMAL:
#: approximately x0.58 / x1.0 / x1.73 - intentionally wide ("warm-up mode").
FALLBACK_RESIDUAL_QUANTILES = {"q10": -0.55, "q50": 0.0, "q90": 0.55}

#: Modest relative widening of the conformal tail quantiles about the median
#: (log space). The raw out-of-fold quantiles under-covered the walk-forward
#: replay on the seeded corpus (73.8%); x1.10 lands coverage at ~78.6%, inside
#: the spec §7.1 target band (75-85%). Trade-off: slightly wider intervals.
RESIDUAL_TAIL_WIDENING = 1.10

#: Fallback p(feature == 1) used by :func:`estimate_mc` when the trained model
#: stores no prevalence for a feature (e.g. models pickled before the MC
#: upgrade, or manually built models). ~0.3 is the mean prevalence of the
#: canonical corpus (docs/SPEC.md §5.2, 15 features at Bernoulli(0.35)-ish).
DEFAULT_FEATURE_PREVALENCE = 0.3

#: Extra widening of the residual spread for uncalibrated (warm-up) models in
#: :func:`estimate_mc`. Without out-of-fold residuals there is nothing to
#: bootstrap, so the residual distribution is approximated by a Normal whose
#: 10/90 quantiles match the fallback quantiles scaled by this factor. Spec §9
#: ("< 10 dự án" -> warm-up mode) wants visibly wider intervals while learning.
MC_UNCALIBRATED_WIDENING = 1.5

#: z-score of the standard-normal 90th percentile; converts the [q10, q90]
#: span into a sigma for the fallback residual draws.
_NORMAL_90_Z = 1.2815515655446004

#: Cold-start defaults (documented, not learned): base person-days multiplied
#: by one conservative factor per present feature. Values are pragmatic
#: industry intuitions from docs/SPEC.md §5.2; the trained model replaces them.
COLD_START_BASE_DAYS = 20.0
COLD_START_MULTIPLIERS: dict[str, float] = {
    "third_party_api": 1.30,
    "payment_gateway": 1.40,
    "identity_provider": 1.25,
    "external_data_sync": 1.30,
    "data_migration": 1.50,
    "multi_currency": 1.20,
    "multi_tenancy": 1.35,
    "realtime_ui": 1.25,
    "mobile_app": 1.50,
    "offline_mode": 1.30,
    "pci_dss": 1.35,
    "privacy_compliance": 1.15,
    "audit_logging": 1.20,
    "legacy_tech_stack": 1.30,
    "cross_team_coordination": 1.25,
}
COLD_START_P10_FACTOR = 0.45
COLD_START_P90_FACTOR = 2.2

assert set(COLD_START_MULTIPLIERS) == set(FEATURES)


@dataclass
class EstimatorModel:
    """Trained estimator: Ridge on log-days + conformal residual quantiles."""

    model: Ridge
    feature_names: list[str] = field(default_factory=lambda: list(FEATURES))
    residual_quantiles: dict[str, float] = field(
        default_factory=lambda: dict(FALLBACK_RESIDUAL_QUANTILES)
    )
    n_train: int = 0
    calibrated: bool = False  # True when quantiles come from out-of-fold residuals
    #: Fraction of training rows with feature == 1, per feature. Used by
    #: estimate_mc as the Bernoulli prior for unknown features; missing keys
    #: fall back to DEFAULT_FEATURE_PREVALENCE.
    feature_prevalence: dict[str, float] = field(default_factory=dict)
    #: Out-of-fold conformal residuals in log space, kept for bootstrap
    #: sampling in estimate_mc. None when the model is uncalibrated.
    oof_residuals: NDArray[np.float64] | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def feature_vector(
    features: Mapping[str, Any] | None, feature_names: Sequence[str] | None = None
) -> NDArray[np.float64]:
    """Map a feature dict ({name: 0|1|bool|None}) to the canonical float vector."""
    names = feature_names or FEATURES
    source = features or {}
    return np.array(
        [1.0 if source.get(name) else 0.0 for name in names], dtype=float
    )


def _row_is_valid(row: Mapping[str, Any]) -> bool:
    try:
        actual = float(row.get("actual_days"))
    except (TypeError, ValueError):
        return False
    return math.isfinite(actual) and actual > 0


def _residual_quantiles(residuals: NDArray[np.float64]) -> dict[str, float]:
    """Quantiles of conformal residuals with a simple finite-sample correction.

    Following the spirit of split-conformal: for level q and n samples we
    evaluate quantile ``min(1, q*(n+1)/n)`` with the "higher" method, which
    pushes the tails outward for small samples. Tail quantiles are then
    widened about the median by ``RESIDUAL_TAIL_WIDENING`` (see the constant).
    """
    n = len(residuals)
    out: dict[str, float] = {}
    for key, q in zip(("q10", "q50", "q90"), QUANTILE_LEVELS):
        q_adjusted = min(1.0, q * (n + 1) / n)
        out[key] = float(np.quantile(residuals, q_adjusted, method="higher"))
    # Numerical safety: enforce non-decreasing quantiles.
    ordered = sorted(out.values())
    q10, q50, q90 = ordered
    return {
        "q10": q50 - (q50 - q10) * RESIDUAL_TAIL_WIDENING,
        "q50": q50,
        "q90": q50 + (q90 - q50) * RESIDUAL_TAIL_WIDENING,
    }


def _residual_draws(
    model: EstimatorModel, rng: np.random.Generator, n: int
) -> NDArray[np.float64]:
    """Draw ``n`` residuals (log space) for the Monte Carlo predictive step.

    Preferred path: bootstrap the stored out-of-fold conformal residuals
    (empirical distribution, keeps skew/asymmetry) and re-apply
    ``RESIDUAL_TAIL_WIDENING`` about the conformal median so the MC marginals
    match the quantile logic used by :func:`estimate`.

    Documented fallbacks, both deliberately wider than a calibrated MC:
    * calibrated model without stored residuals (legacy pickle): Gaussian with
      sigma implied by the stored 10/90 quantiles (already widened);
    * uncalibrated warm-up model: the same Gaussian construction on the
      fallback quantiles, widened further by ``MC_UNCALIBRATED_WIDENING``.
    """
    residuals = getattr(model, "oof_residuals", None)
    if residuals is not None and len(residuals) > 0:
        draws = rng.choice(np.asarray(residuals, dtype=float), size=n, replace=True)
        center = float(model.residual_quantiles["q50"])
        return center + (draws - center) * RESIDUAL_TAIL_WIDENING

    q10 = float(model.residual_quantiles["q10"])
    q50 = float(model.residual_quantiles["q50"])
    q90 = float(model.residual_quantiles["q90"])
    if not model.calibrated:
        q10 = q50 - (q50 - q10) * MC_UNCALIBRATED_WIDENING
        q90 = q50 + (q90 - q50) * MC_UNCALIBRATED_WIDENING
    sigma = max((q90 - q10) / (2.0 * _NORMAL_90_Z), 1e-9)
    return rng.normal(loc=q50, scale=sigma, size=n)


def _finish(p10: float, p50: float, p90: float, mode: str) -> dict[str, Any]:
    """Floor, round and enforce ordering for a prediction interval."""
    p10 = max(MIN_DAYS, round(p10, 1))
    p50 = max(MIN_DAYS, round(p50, 1))
    p90 = max(MIN_DAYS, round(p90, 1))
    p10, p50, p90 = sorted((p10, p50, p90))
    return {"p10": p10, "p50": p50, "p90": p90, "mode": mode}


# --------------------------------------------------------------------------- #
# Training
# --------------------------------------------------------------------------- #


def train_model(rows: Sequence[Mapping[str, Any]]) -> EstimatorModel:
    """Train the estimator on canonical rows (docs/API.md row contract).

    Rows without a positive finite ``actual_days`` are ignored. Raises
    ValueError when fewer than MIN_ROWS usable rows remain.
    """
    usable = [row for row in rows if _row_is_valid(row)]
    if len(usable) < MIN_ROWS:
        raise ValueError(
            f"Cần ít nhất {MIN_ROWS} dự án có actual_days để train, hiện có {len(usable)}"
        )

    x = np.vstack([feature_vector(row.get("features")) for row in usable])
    y = np.log(np.array([float(row["actual_days"]) for row in usable]))
    model = Ridge(alpha=RIDGE_ALPHA)
    model.fit(x, y)

    n = len(usable)
    if n >= MIN_ROWS_CONFORMAL:
        folds = KFold(n_splits=min(5, n), shuffle=False)  # deterministic split
        oof = cross_val_predict(Ridge(alpha=RIDGE_ALPHA), x, y, cv=folds)
        quantiles = _residual_quantiles(y - oof)
        calibrated = True
        oof_residuals: NDArray[np.float64] | None = y - oof
    else:
        quantiles = dict(FALLBACK_RESIDUAL_QUANTILES)
        calibrated = False
        oof_residuals = None

    # p(feature == 1) over the usable training rows: the Bernoulli prior that
    # estimate_mc uses for features the extraction could not resolve.
    prevalence = {name: float(x[:, i].mean()) for i, name in enumerate(FEATURES)}

    return EstimatorModel(
        model=model,
        feature_names=list(FEATURES),
        residual_quantiles=quantiles,
        n_train=n,
        calibrated=calibrated,
        feature_prevalence=prevalence,
        oof_residuals=oof_residuals,
    )


# --------------------------------------------------------------------------- #
# Prediction
# --------------------------------------------------------------------------- #


def estimate(model: EstimatorModel, features: Mapping[str, Any] | None) -> dict[str, Any]:
    """Predict ``{p10, p50, p90, mode}`` for a feature dict (mode "calibrated")."""
    x = feature_vector(features, model.feature_names).reshape(1, -1)
    log_pred = float(model.model.predict(x)[0])
    quantiles = model.residual_quantiles
    p10 = math.exp(log_pred + quantiles["q10"])
    p50 = math.exp(log_pred + quantiles["q50"])
    p90 = math.exp(log_pred + quantiles["q90"])
    return _finish(p10, p50, p90, "calibrated")


def estimate_mc(
    model: EstimatorModel,
    features: Mapping[str, Any] | None,
    n: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Interval estimate that treats unknown features as unknown, not as 0.

    A feature is unknown when the mapping explicitly maps it to ``None``
    (``resolve_features`` emits all 15 canonical keys). Keys absent from the
    mapping keep the :func:`estimate` semantics ("not present" = 0), so the
    two functions agree on binary vectors.

    For each of the ``n`` Monte Carlo draws:

    1. every unknown feature is sampled ``Bernoulli(p)`` with ``p`` the
       training-set prevalence stored on the model
       (``DEFAULT_FEATURE_PREVALENCE`` ~0.3 for missing keys);
    2. ``log_pred_draw`` is the Ridge prediction on the completed binary
       vector;
    3. a residual is added, bootstrapped from the stored out-of-fold conformal
       residuals (see :func:`_residual_draws` for the documented fallbacks and
       widening), and the sample is ``exp(log_pred_draw + residual_draw)``.

    ``p10/p50/p90`` are the sample percentiles with the same floor/rounding as
    :func:`estimate`, ordering enforced. Returns ``mode "calibrated"`` and
    ``unit "days"``, with ``method "mc"`` while at least one unknown remains;
    with no unknowns the exact numbers of :func:`estimate` are returned with
    ``method "point"``. Fully deterministic via ``np.random.default_rng(seed)``.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    source = features or {}
    unknown = [
        name for name in model.feature_names if name in source and source[name] is None
    ]
    if not unknown:
        result = estimate(model, source)
        result["unit"] = "days"
        result["method"] = "point"
        return result

    base = feature_vector(source, model.feature_names)  # unknown slots are 0, overwritten below
    rng = np.random.default_rng(seed)
    x_draw = np.tile(base, (n, 1))
    prevalence = getattr(model, "feature_prevalence", None) or {}
    index = {name: i for i, name in enumerate(model.feature_names)}
    for name in unknown:
        p = float(prevalence.get(name, DEFAULT_FEATURE_PREVALENCE))
        x_draw[:, index[name]] = rng.random(n) < p

    log_pred = np.asarray(model.model.predict(x_draw), dtype=float).ravel()
    samples = np.exp(log_pred + _residual_draws(model, rng, n))
    q10, q50, q90 = (float(value) for value in np.quantile(samples, QUANTILE_LEVELS))
    result = _finish(q10, q50, q90, "calibrated")
    result["unit"] = "days"
    result["method"] = "mc"
    return result


def cold_start_estimate(features: Mapping[str, Any] | None) -> dict[str, Any]:
    """Industry-baseline estimate with a wide interval (mode "cold_start").

    p50 = COLD_START_BASE_DAYS x product of COLD_START_MULTIPLIERS of present
    features; p10 = 0.45 x p50 and p90 = 2.2 x p50 — wider than a calibrated
    interval by construction.
    """
    source = features or {}
    multiplier = 1.0
    for name in FEATURES:
        if source.get(name):
            multiplier *= COLD_START_MULTIPLIERS[name]
    p50 = COLD_START_BASE_DAYS * multiplier
    p10 = p50 * COLD_START_P10_FACTOR
    p90 = p50 * COLD_START_P90_FACTOR
    return _finish(p10, p50, p90, "cold_start")


def point_estimate(model: EstimatorModel, features: Mapping[str, Any] | None) -> float:
    """Single calibrated number (P50) in person-days."""
    return estimate(model, features)["p50"]


def coefficients(model: EstimatorModel) -> list[dict[str, Any]]:
    """Per-feature learned multipliers for the UI: exp(raw coef), in feature order."""
    raw = np.asarray(model.model.coef_, dtype=float).ravel()
    return [
        {
            "feature": name,
            "multiplier": round(float(math.exp(raw[i])), 3),
            "raw": round(float(raw[i]), 4),
        }
        for i, name in enumerate(model.feature_names)
    ]


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def save_model(model: EstimatorModel, path: str | Path) -> Path:
    """Pickle the trained model to ``path``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        pickle.dump(model, handle)
    return target


def load_model(path: str | Path) -> EstimatorModel:
    """Load a model previously written by ``save_model``."""
    with Path(path).open("rb") as handle:
        return pickle.load(handle)
