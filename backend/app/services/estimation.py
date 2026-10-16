"""Estimation engine: Ridge regression on log(actual_days) + conformal intervals.

Spec §4.2: estimation is data-driven (never LLM-driven), each feature has a
learned multiplier and the [P10, P90] interval is calibrated. We fit
``log(actual_days) ~ Ridge(alpha=0.3)`` over the 15 binary features and build
the interval from out-of-fold conformal residual quantiles.

Cold start (no history) uses documented conservative industry multipliers with
a deliberately wider interval than a calibrated model.

Everything here is pure and deterministic: same rows + same features -> same
numbers (spec §7.2, std < 5%).
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
    else:
        quantiles = dict(FALLBACK_RESIDUAL_QUANTILES)
        calibrated = False

    return EstimatorModel(
        model=model,
        feature_names=list(FEATURES),
        residual_quantiles=quantiles,
        n_train=n,
        calibrated=calibrated,
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
