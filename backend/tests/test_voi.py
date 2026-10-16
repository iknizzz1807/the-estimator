"""Tests for the Value-of-Information question ranker."""

from __future__ import annotations

import math

import numpy as np

from app.features import FEATURES
from app.services.estimation import coefficients, train_model
from app.services.extraction import FeatureFinding
from app.services.voi import QUESTION_TEMPLATES, rank_questions


def make_model_with_dominant_migration():
    rng = np.random.default_rng(7)
    rows = []
    for i in range(60):
        features = {name: int(rng.random() < 0.2) for name in FEATURES}
        features["data_migration"] = int(rng.random() < 0.5)
        # data_migration dominates: x2.0 while everything else is x1.0
        multiplier = 2.0 if features["data_migration"] else 1.0
        actual = 20.0 * multiplier * math.exp(rng.normal(0.0, 0.1))
        rows.append({"project_id": f"P{i:03d}", "actual_days": actual, "features": features})
    return train_model(rows)


def all_unknown_findings() -> list[FeatureFinding]:
    return [FeatureFinding(name=name) for name in FEATURES]


def test_unknown_feature_with_largest_coefficient_ranks_first() -> None:
    model = make_model_with_dominant_migration()
    by_name = {c["feature"]: c["multiplier"] for c in coefficients(model)}
    assert by_name["data_migration"] == max(by_name.values())

    ranked = rank_questions(model, all_unknown_findings(), top_k=15)
    assert len(ranked) == 15
    assert ranked[0]["feature"] == "data_migration"
    for item in ranked:
        assert item["impact_days"] >= 0.0
    by_feature = {item["feature"]: item for item in ranked}
    assert by_feature["data_migration"]["impact_days"] > by_feature["multi_currency"]["impact_days"]


def test_templates_are_complete_for_all_features() -> None:
    ranked = rank_questions(None, all_unknown_findings(), top_k=15)
    assert {item["feature"] for item in ranked} == set(FEATURES)
    for item in ranked:
        assert item["impact_days"] >= 0.0
        assert item["p50_with"] > 0 and item["p50_without"] > 0
        assert item["question_vi"].strip()
        assert item["question_en"].strip()
        assert item["feature"] in QUESTION_TEMPLATES


def test_cold_start_fallback_when_no_model() -> None:
    ranked = rank_questions(None, all_unknown_findings(), top_k=5)
    assert len(ranked) == 5
    assert ranked[0]["feature"] == "data_migration"  # ties break on FEATURES order
    for item in ranked:
        assert item["impact_days"] > 0.0


def test_only_unknown_features_are_asked_and_top_k_applied() -> None:
    unknown_names = {"third_party_api", "pci_dss"}
    findings = [
        FeatureFinding(name=name, value=None if name in unknown_names else 0)
        for name in FEATURES
    ]
    ranked = rank_questions(None, findings, top_k=5)

    assert {item["feature"] for item in ranked} == unknown_names
    assert len(rank_questions(None, all_unknown_findings(), top_k=3)) == 3
