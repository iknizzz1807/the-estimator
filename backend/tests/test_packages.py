"""Tests for budget-fit scope packages (docs/API.md v0.2 POST /api/packages).

Offline and deterministic: the tiny inline model follows test_estimation.py's
pattern (synthetic rows with known per-feature multipliers), and the tests
exercise both the estimate_mc path (via a fake import hook / injected
estimator) and the documented ImportError point-estimate fallback.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.features import FEATURES
from app.services import packages
from app.services.estimation import coefficients, estimate, train_model
from app.services.packages import (
    CUTTABLE_OPTIONALS,
    OVER_BUDGET_THRESHOLD,
    build_packages,
)

# Tiny test-local model: all six cuttables get distinct positive multipliers,
# so cutting the highest-impact ones lowers P50 monotonically.
TRUE_MULTIPLIERS = {
    "offline_mode": 1.65,
    "mobile_app": 1.55,
    "realtime_ui": 1.30,
    "multi_currency": 1.45,
    "external_data_sync": 1.40,
    "audit_logging": 1.20,
    "data_migration": 1.18,
    "third_party_api": 1.15,
}
BASE_DAYS = 18.0
NOISE_SIGMA = 0.08


def make_rows(n: int = 160, seed: int = 42) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        features = {name: int(rng.random() < 0.3) for name in FEATURES}
        multiplier = math.prod(
            TRUE_MULTIPLIERS.get(name, 1.0)
            for name, present in features.items()
            if present
        )
        actual = BASE_DAYS * multiplier * math.exp(rng.normal(0.0, NOISE_SIGMA))
        rows.append(
            {"project_id": f"P{i:03d}", "actual_days": round(actual, 1), "features": features}
        )
    return rows


@pytest.fixture(scope="module")
def model():
    return train_model(make_rows())


def demo_features(**overrides) -> dict[str, int | None]:
    """All 15 features absent unless overridden (None = unknown)."""
    return {name: 0 for name in FEATURES} | overrides


FULL_DEMO = demo_features(
    offline_mode=1,
    mobile_app=1,
    realtime_ui=1,
    multi_currency=1,
    external_data_sync=1,
    audit_logging=1,
    data_migration=1,
    third_party_api=1,
)


def expected_ranking(model_, features) -> list[str]:
    """Reference ranking: present cuttables by learned multiplier, ties stable."""
    by_name = {c["feature"]: c["multiplier"] for c in coefficients(model_)}
    order = {name: i for i, name in enumerate(CUTTABLE_OPTIONALS)}
    present = [name for name in CUTTABLE_OPTIONALS if features.get(name) == 1]
    return sorted(present, key=lambda name: (-by_name[name], order[name]))


# --------------------------------------------------------------------------- #
# Shape + tier edits
# --------------------------------------------------------------------------- #


def test_response_shape_and_tier_edits(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=10_000)

    assert result["budget_days"] == 10_000
    assert [pkg["tier"] for pkg in result["packages"]] == ["core", "standard", "full"]
    assert [pkg["label"] for pkg in result["packages"]] == [
        "Essential",
        "Standard",
        "Full scope",
    ]
    assert result["recommendation"] == "full"
    assert result["method"] in {"mc", "point"}
    assert "recommendation_note" not in result  # generous budget: no caveat

    ranked = expected_ranking(model, FULL_DEMO)
    assert [pkg["excluded"] for pkg in result["packages"]] == [
        ranked[:2],
        ranked[:1],
        [],
    ]

    for package in result["packages"]:
        assert set(package) == {
            "tier",
            "label",
            "estimate",
            "over_budget_prob",
            "features_included",
            "excluded",
            "notes",
        }
        assert set(package["estimate"]) == {
            "p10",
            "p50",
            "p90",
            "mode",
            "unit",
            "method",
        }
        assert package["estimate"]["unit"] == "days"
        assert (
            package["estimate"]["p10"]
            <= package["estimate"]["p50"]
            <= package["estimate"]["p90"]
        )
        assert list(package["features_included"]) == FEATURES
        assert all(
            value in (0, 1, None) for value in package["features_included"].values()
        )
        assert isinstance(package["notes"], str) and package["notes"]
        assert isinstance(package["over_budget_prob"], float)
        assert 0.0 < package["over_budget_prob"] < 1.0
        assert package["over_budget_prob"] == round(package["over_budget_prob"], 3)

    # features_included reflects the cuts: cut optionals -> 0, others unchanged.
    core = result["packages"][0]
    for name in ranked[:2]:
        assert core["features_included"][name] == 0
    for name in ranked[2:]:
        assert core["features_included"][name] == 1
    assert core["features_included"]["data_migration"] == 1  # non-cuttables kept
    assert core["features_included"]["pci_dss"] == 0


def test_unknown_features_stay_unknown_in_all_tiers(model) -> None:
    features = demo_features(offline_mode=1, mobile_app=1, pci_dss=None, audit_logging=None)
    result = build_packages(model, features, budget_days=60)

    for package in result["packages"]:
        assert package["features_included"]["pci_dss"] is None
        assert package["features_included"]["audit_logging"] is None
    # Unknown cuttables are never phased out: they stay None and out of `excluded`.
    for package in result["packages"]:
        assert "audit_logging" not in package["excluded"]
    assert result["packages"][0]["excluded"] == expected_ranking(model, features)


def test_ranking_uses_learned_multipliers_and_only_present(model) -> None:
    features = packages._normalize_features(
        {"offline_mode": 1, "multi_currency": 1, "audit_logging": 0, "realtime_ui": None}
    )
    ranked = packages._rank_present_cuttables(model, features)
    assert set(ranked) == {"offline_mode", "multi_currency"}
    by_name = {c["feature"]: c["multiplier"] for c in coefficients(model)}
    assert [by_name[name] for name in ranked] == sorted(
        (by_name[name] for name in ranked), reverse=True
    )


# --------------------------------------------------------------------------- #
# Tier ordering + over-budget probability
# --------------------------------------------------------------------------- #


def test_tier_p50_is_monotonic_in_scope(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=45)
    p50 = [package["estimate"]["p50"] for package in result["packages"]]
    assert p50[0] <= p50[1] <= p50[2]
    assert p50[0] < p50[2]  # cuttables have strictly positive learned impact
    probs = [package["over_budget_prob"] for package in result["packages"]]
    assert probs[0] <= probs[1] <= probs[2]


def test_over_budget_prob_decreases_as_budget_grows(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=45)
    full = next(p for p in result["packages"] if p["tier"] == "full")
    budgets = [full["estimate"]["p50"] * factor for factor in (0.5, 0.75, 1.25, 2.0, 5.0)]
    probs = [packages._over_budget_prob(full["estimate"], budget) for budget in budgets]
    assert probs == sorted(probs, reverse=True)
    assert probs[0] > probs[-1]

    tight = build_packages(model, FULL_DEMO, budget_days=20)
    loose = build_packages(model, FULL_DEMO, budget_days=200)
    for tier_idx in range(3):
        assert (
            tight["packages"][tier_idx]["over_budget_prob"]
            >= loose["packages"][tier_idx]["over_budget_prob"]
        )


def test_over_budget_prob_is_half_at_the_tier_median(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=45)
    for package in result["packages"]:
        probability = packages._over_budget_prob(
            package["estimate"], package["estimate"]["p50"]
        )
        assert probability == 0.5  # lognormal median = P50


# --------------------------------------------------------------------------- #
# Recommendation
# --------------------------------------------------------------------------- #


def test_generous_budget_recommends_full_scope(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=5000)
    assert result["recommendation"] == "full"
    assert "recommendation_note" not in result


def test_tight_budget_recommends_core_with_risk_note(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=5)
    probs = [p["over_budget_prob"] for p in result["packages"]]
    assert all(prob > OVER_BUDGET_THRESHOLD for prob in probs)
    assert result["recommendation"] == "core"
    assert "recommendation_note" in result
    assert "risk" in result["recommendation_note"].lower()


def test_recommendation_picks_most_scoped_tier_within_threshold() -> None:
    def package(tier: str, probability: float | None) -> dict:
        return {"tier": tier, "over_budget_prob": probability}

    # full qualifies -> full; only standard -> standard; only core -> core.
    tiers = [package("core", 0.10), package("standard", 0.20), package("full", 0.24)]
    assert packages._recommend(tiers, 30) == ("full", None)
    tiers = [package("core", 0.10), package("standard", 0.20), package("full", 0.90)]
    assert packages._recommend(tiers, 30) == ("standard", None)
    tiers = [package("core", 0.20), package("standard", 0.80), package("full", 0.90)]
    assert packages._recommend(tiers, 30) == ("core", None)

    # Boundary: exactly 0.25 qualifies, tie-breaks to the higher tier.
    tiers = [package("core", 0.20), package("standard", 0.25), package("full", 0.25)]
    assert packages._recommend(tiers, 30) == ("full", None)
    assert packages._recommend(tiers, None) == ("full", None)

    # None qualifies -> core + risk note.
    tiers = [package("core", 0.80), package("standard", 0.90), package("full", 0.95)]
    tier, note = packages._recommend(tiers, 30)
    assert tier == "core" and note


def test_recommendation_consistent_across_budgets(model) -> None:
    for budget in (10, 25, 40, 60, 90, 150):
        result = build_packages(model, FULL_DEMO, budget_days=budget)
        probs = {pkg["tier"]: pkg["over_budget_prob"] for pkg in result["packages"]}
        recommendation = result["recommendation"]
        if recommendation == "full":
            assert probs["full"] <= OVER_BUDGET_THRESHOLD
        elif recommendation == "standard":
            assert probs["full"] > OVER_BUDGET_THRESHOLD
            assert probs["standard"] <= OVER_BUDGET_THRESHOLD
        else:
            if "recommendation_note" in result:
                # No tier qualified: core is the least-risk fallback + caveat.
                assert all(prob > OVER_BUDGET_THRESHOLD for prob in probs.values())
            else:
                assert probs["core"] <= OVER_BUDGET_THRESHOLD
                assert probs["standard"] > OVER_BUDGET_THRESHOLD
                assert probs["full"] > OVER_BUDGET_THRESHOLD


def test_budget_none_has_no_probabilities_and_recommends_full(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=None)
    assert result["budget_days"] is None
    assert all(pkg["over_budget_prob"] is None for pkg in result["packages"])
    assert result["recommendation"] == "full"
    assert "recommendation_note" not in result


# --------------------------------------------------------------------------- #
# No cuttables / determinism / fallback paths
# --------------------------------------------------------------------------- #


def test_no_cuttables_present_makes_tiers_identical_with_note(model) -> None:
    features = demo_features(data_migration=1, third_party_api=1)
    result = build_packages(model, features, budget_days=30)

    core, standard, full = result["packages"]
    assert core["excluded"] == [] and standard["excluded"] == [] and full["excluded"] == []
    assert core["features_included"] == standard["features_included"] == full["features_included"]
    assert core["estimate"] == standard["estimate"] == full["estimate"]
    assert core["over_budget_prob"] == standard["over_budget_prob"] == full["over_budget_prob"]
    assert "no phaseable optional capabilities" in core["notes"]
    assert "no phaseable optional capabilities" in standard["notes"]


def test_single_cuttable_notes_the_core_standard_coincidence(model) -> None:
    result = build_packages(model, demo_features(mobile_app=1), budget_days=30)
    core, standard, full = result["packages"]
    assert core["excluded"] == ["mobile_app"] == standard["excluded"]
    assert core["estimate"] == standard["estimate"]
    assert "identical to Standard" in core["notes"]


def test_deterministic_for_same_seed(model) -> None:
    features = demo_features(offline_mode=1, mobile_app=1, pci_dss=None)
    first = build_packages(model, features, budget_days=30, n=500, seed=42)
    second = build_packages(model, features, budget_days=30, n=500, seed=42)
    assert first == second


def test_point_fallback_when_estimate_mc_missing(model, monkeypatch) -> None:
    def missing_mc():
        raise ImportError("simulated: estimate_mc not shipped yet")

    monkeypatch.setattr(packages, "_load_estimate_mc", missing_mc)
    features = demo_features(offline_mode=1, mobile_app=1, pci_dss=None)
    result = build_packages(model, features, budget_days=30)

    assert result["method"] == "point"
    for package in result["packages"]:
        assert package["estimate"]["method"] == "point"
        assert package["estimate"]["unit"] == "days"
        assert package["features_included"]["pci_dss"] is None  # still reported unknown

    # Fallback math: unknowns treated as absent, tier cuts applied.
    ranked = expected_ranking(model, features)
    zeroed = {name: (0 if value is None else value) for name, value in features.items()}
    for package, cut_count in (("core", 2), ("standard", 1), ("full", 0)):
        expected_features = {
            **zeroed,
            **{name: 0 for name in ranked[:cut_count]},
        }
        actual = next(p for p in result["packages"] if p["tier"] == package)
        assert actual["estimate"]["p50"] == estimate(model, expected_features)["p50"]


def test_default_estimator_prefers_estimate_mc_and_passes_seed(model, monkeypatch) -> None:
    calls: list[tuple[int, int]] = []

    def fake_mc(model_, features_, n=0, seed=0):
        calls.append((n, seed))
        return {
            "p10": 9.0,
            "p50": 18.0,
            "p90": 29.0,
            "mode": "calibrated",
            "unit": "days",
            "method": "mc",
        }

    monkeypatch.setattr(packages, "_load_estimate_mc", lambda: fake_mc)
    features = packages._normalize_features({"pci_dss": None})
    result = packages._tier_estimate(model, features, n=123, seed=7)
    assert result == {
        "p10": 9.0,
        "p50": 18.0,
        "p90": 29.0,
        "mode": "calibrated",
        "unit": "days",
        "method": "mc",
    }
    assert calls == [(123, 7)]


def test_tier_estimate_accepts_injected_estimator(model) -> None:
    seen: list[tuple[int, int]] = []

    def injected(model_, features_, n, seed):
        seen.append((n, seed))
        return {"p10": 5.0, "p50": 9.0, "p90": 15.0, "mode": "custom"}

    result = packages._tier_estimate(
        model,
        packages._normalize_features({name: 0 for name in FEATURES}),
        n=11,
        seed=3,
        estimator=injected,
    )
    # Missing keys get documented defaults; no unknowns -> method "point".
    assert result == {
        "p10": 5.0,
        "p50": 9.0,
        "p90": 15.0,
        "mode": "custom",
        "unit": "days",
        "method": "point",
    }
    assert seen == [(11, 3)]


def test_default_path_reports_mc_when_estimate_mc_is_available(model) -> None:
    try:
        from app.services.estimation import estimate_mc
    except ImportError:
        pytest.skip("estimate_mc not shipped yet - fallback covered above")

    features = demo_features(offline_mode=1, pci_dss=None)
    result = build_packages(model, features, budget_days=30, n=300, seed=42)
    assert estimate_mc is not None
    assert result["method"] == "mc"
    assert all(pkg["estimate"]["method"] == "mc" for pkg in result["packages"])


# --------------------------------------------------------------------------- #
# Pricing curve (contract v0.2, top-level "pricing" block)
# --------------------------------------------------------------------------- #

PRICING_KEYS = {
    "scope",
    "p10",
    "p50",
    "p90",
    "curve",
    "safe_quote_25",
    "safe_quote_10",
}


def full_estimate(result: dict) -> dict:
    return next(
        package["estimate"] for package in result["packages"] if package["tier"] == "full"
    )


def test_pricing_block_shape_and_log_spaced_range(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=45)
    pricing = result["pricing"]
    full = full_estimate(result)

    assert set(pricing) == PRICING_KEYS
    assert pricing["scope"] == "full"
    # Fitted from the Full tier's own interval (never from another tier).
    assert (pricing["p10"], pricing["p50"], pricing["p90"]) == (
        full["p10"],
        full["p50"],
        full["p90"],
    )

    curve = pricing["curve"]
    assert len(curve) == packages.PRICING_CURVE_POINTS == 25
    days = [point["days"] for point in curve]
    assert days == sorted(days)
    # ~25 log-spaced points spanning [p10 * 0.6, p90 * 1.5] (1-decimal).
    assert days[0] == round(full["p10"] * 0.6, 1)
    assert days[-1] == round(full["p90"] * 1.5, 1)
    ratios = [b / a for a, b in zip(days, days[1:])]
    assert max(ratios) - min(ratios) < 0.01  # ~evenly log-spaced (1-decimal rounding)

    for point in curve:
        assert set(point) == {"days", "over_prob"}
        assert point["days"] == round(point["days"], 1)
        assert point["days"] > 0
        assert 0.001 <= point["over_prob"] <= 0.999
        assert point["over_prob"] == round(point["over_prob"], 3)


def test_pricing_curve_monotone_decreasing_in_days(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=45)
    probs = [point["over_prob"] for point in result["pricing"]["curve"]]
    assert probs == sorted(probs, reverse=True)
    assert probs[0] > probs[-1]  # more days quoted -> strictly lower risk


def test_pricing_curve_reuses_the_tier_probability_model(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=30)
    full = full_estimate(result)
    for point in result["pricing"]["curve"]:
        assert point["over_prob"] == packages._over_budget_prob(full, point["days"])


def test_pricing_agrees_with_full_tier_at_the_budget(model) -> None:
    """At days == budget, curve and Full tier must report the same risk."""
    first = build_packages(model, FULL_DEMO, budget_days=45)
    day = first["pricing"]["curve"][12]["days"]  # an exact curve point
    second = build_packages(model, FULL_DEMO, budget_days=day)

    full = next(pkg for pkg in second["packages"] if pkg["tier"] == "full")
    # Same interval => same curve and same Full-tier probability at that day.
    assert second["pricing"]["curve"][12] == first["pricing"]["curve"][12]
    assert second["pricing"]["curve"][12]["days"] == day
    assert full["over_budget_prob"] == second["pricing"]["curve"][12]["over_prob"]


def test_pricing_safe_quotes(model) -> None:
    result = build_packages(model, FULL_DEMO, budget_days=45)
    pricing = result["pricing"]
    full = full_estimate(result)

    mu = math.log(pricing["p50"])
    sigma = (math.log(pricing["p90"]) - math.log(pricing["p10"])) / (2 * packages.Z_P90)
    expected_25 = math.exp(mu + packages.Z_P25 * sigma)
    expected_10 = math.exp(mu + packages.Z_P90 * sigma)

    # Documented closed forms, displayed at 1 decimal (same as curve days).
    assert abs(pricing["safe_quote_25"] - expected_25) <= 0.05
    assert abs(pricing["safe_quote_10"] - expected_10) <= 0.05
    # Sanity: quoting 10%-risk needs more days than 25%-risk, both above P50.
    assert pricing["safe_quote_10"] > pricing["safe_quote_25"] > pricing["p50"]

    risk_25 = packages._over_budget_prob(full, pricing["safe_quote_25"])
    risk_10 = packages._over_budget_prob(full, pricing["safe_quote_10"])
    assert risk_25 <= 0.252  # honours "<= 25%" (1-decimal display rounding)
    assert risk_10 <= 0.102  # honours "<= 10%"
    assert risk_10 < risk_25

    # And they are the *smallest* such quotes: one day less already breaches.
    assert packages._over_budget_prob(full, pricing["safe_quote_25"] - 1) > 0.25
    assert packages._over_budget_prob(full, pricing["safe_quote_10"] - 1) > 0.10


def test_pricing_block_present_when_tiers_coincide_and_without_budget(model) -> None:
    # No cuttables present: all three tiers are identical - pricing is still
    # fitted from the (coincident) full interval.
    no_cut = build_packages(
        model, demo_features(data_migration=1, third_party_api=1), budget_days=30
    )
    assert no_cut["pricing"]["scope"] == "full"
    assert no_cut["pricing"]["p50"] == full_estimate(no_cut)["p50"]

    # The curve models quote -> risk, so it does not depend on the budget.
    without_budget = build_packages(model, FULL_DEMO, budget_days=None)
    with_budget = build_packages(model, FULL_DEMO, budget_days=45)
    assert without_budget["pricing"] == with_budget["pricing"]


def test_pricing_block_degenerate_interval_falls_back_to_median() -> None:
    pricing = packages._pricing_block(10.0, 10.0, 10.0)
    assert set(pricing) == PRICING_KEYS
    assert pricing["scope"] == "full"
    assert len(pricing["curve"]) == 25
    assert pricing["safe_quote_25"] == 10.0
    assert pricing["safe_quote_10"] == 10.0
    for point in pricing["curve"]:
        assert point["days"] > 0
        assert point["over_prob"] in (0.001, 0.999)  # p50 step fallback
