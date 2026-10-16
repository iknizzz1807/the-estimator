"""Tests for the distilled student provider and the distillation machinery (offline).

Everything here is network-free: a tiny student model is trained in-test on ~12
hand-written rows and saved to ``tmp_path``; the factory branch is exercised by
monkeypatching the module-level default model path.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
from sklearn.pipeline import Pipeline

from app.features import FEATURES
from app.services import distilled
from app.services.distilled import (
    ABSENT_THRESHOLD,
    PRESENT_THRESHOLD,
    DistilledProvider,
    decide_value,
    load_distilled_model,
    save_distilled_model,
)
from app.services.extraction import build_extraction_prompt, extract_features
from app.services.providers import StubProvider, get_provider
from scripts.distillation_experiment import (
    build_pipeline,
    cv_predictions,
    load_labels_rows,
    train_feature_pipeline,
    write_labels_csv,
)

# 12 tiny emails: 6 assert third-party integration, 6 explicitly deny it.
TINY_POSITIVE = "We need to integrate with a third party CRM through an external API."
TINY_NEGATIVE = "The client said no third party integration is needed for phase one."
TINY_EMAILS = [f"{TINY_POSITIVE} Project {i}." for i in range(6)] + [
    f"{TINY_NEGATIVE} Project {i}." for i in range(6)
]
TINY_LABELS = [1] * 6 + [0] * 6


def tiny_model(tmp_path):
    """Train + save a 1-feature student; other features abstain (no pipeline)."""
    pipelines = {name: None for name in FEATURES}
    pipelines["third_party_api"] = train_feature_pipeline(TINY_EMAILS, TINY_LABELS)
    assert pipelines["third_party_api"] is not None
    model = {"schema": distilled.MODEL_SCHEMA, "metadata": {}, "pipelines": pipelines}
    path = tmp_path / "tiny_distilled.joblib"
    save_distilled_model(model, path)
    return path


class FakePipeline:
    """Deterministic stand-in exposing sklearn's predict_proba/classes_ contract."""

    def __init__(self, probability: float) -> None:
        self.probability = probability
        self.classes_ = np.array([0, 1])

    def predict_proba(self, _texts):
        p = self.probability
        return np.array([[1.0 - p, p]])


def fake_model(**probabilities: float) -> dict:
    pipelines = {name: None for name in FEATURES}
    for name, probability in probabilities.items():
        pipelines[name] = FakePipeline(probability)
    return {"schema": distilled.MODEL_SCHEMA, "metadata": {}, "pipelines": pipelines}


# --------------------------------------------------------------------------- #
# Decision thresholds
# --------------------------------------------------------------------------- #


def test_decide_value_thresholds() -> None:
    assert decide_value(0.9) == (True, 0.9)
    assert decide_value(PRESENT_THRESHOLD) == (True, 0.5)  # boundary asserts present
    assert decide_value(0.49) == (None, 0.0)  # dead band -> abstain
    assert decide_value(0.41) == (None, 0.0)
    assert decide_value(ABSENT_THRESHOLD) == (False, 0.6)  # boundary asserts absent
    assert decide_value(0.1) == (False, 0.9)
    assert decide_value(None) == (None, 0.0)


def test_provider_thresholds_and_confidence() -> None:
    provider = DistilledProvider(
        model=fake_model(third_party_api=0.9, payment_gateway=0.45, data_migration=0.3)
    )
    findings = provider.complete_json(build_extraction_prompt("some email"))["features"]

    assert findings["third_party_api"] == {
        "value": True,
        "confidence": 0.9,
        "evidence_quote": None,
    }
    assert findings["payment_gateway"] == {
        "value": None,
        "confidence": 0.0,
        "evidence_quote": None,
    }
    assert findings["data_migration"] == {
        "value": False,
        "confidence": 0.7,
        "evidence_quote": None,
    }


def test_provider_broken_pipeline_abstains() -> None:
    class Broken(FakePipeline):
        def predict_proba(self, _texts):
            raise RuntimeError("single-class artifact")

    pipelines = {name: None for name in FEATURES}
    pipelines["payment_gateway"] = Broken(0.9)
    provider = DistilledProvider(model={"schema": distilled.MODEL_SCHEMA, "metadata": {}, "pipelines": pipelines})
    findings = provider.complete_json(build_extraction_prompt("x"))["features"]

    assert all(entry["value"] is None for entry in findings.values())


# --------------------------------------------------------------------------- #
# Provider behaviour on a tiny real model
# --------------------------------------------------------------------------- #


def test_provider_canonical_shape_order_and_determinism(tmp_path) -> None:
    path = tiny_model(tmp_path)
    provider = DistilledProvider(model_path=path)
    prompt = build_extraction_prompt(f"{TINY_POSITIVE} Please advise.")

    first = provider.complete_json(prompt)
    second = provider.complete_json(prompt)

    assert first == second  # deterministic
    assert list(first["features"].keys()) == FEATURES
    for name in FEATURES:
        entry = first["features"][name]
        assert set(entry) == {"value", "confidence", "evidence_quote"}
        assert entry["value"] in (True, False, None)
        assert 0.0 <= entry["confidence"] <= 1.0
        assert entry["evidence_quote"] is None  # never fabricates quotes
    # The trained feature fires on a matching email; untrained features abstain.
    assert first["features"]["third_party_api"]["value"] is True
    assert first["features"]["third_party_api"]["confidence"] >= PRESENT_THRESHOLD
    assert first["features"]["payment_gateway"]["value"] is None


def test_provider_without_email_block_returns_all_null(tmp_path) -> None:
    provider = DistilledProvider(model_path=tiny_model(tmp_path))
    findings = provider.complete_json("no email block here")["features"]

    assert list(findings) == FEATURES
    assert all(entry["value"] is None for entry in findings.values())
    assert all(entry["confidence"] == 0.0 for entry in findings.values())


def test_extract_features_end_to_end_with_distilled(tmp_path) -> None:
    provider = DistilledProvider(model_path=tiny_model(tmp_path))
    result = extract_features(
        f"{TINY_NEGATIVE} Reporting only.", provider=(provider, "distilled")
    )

    assert result.provider == "distilled"
    assert [finding.name for finding in result.findings] == FEATURES
    assert len(result.findings) == 15
    assert all(finding.evidence_quote is None for finding in result.findings)
    assert "Không thể trích xuất" not in " ".join(result.warnings)


# --------------------------------------------------------------------------- #
# Model loading / saving
# --------------------------------------------------------------------------- #


def test_load_missing_model_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        load_distilled_model(tmp_path / "does_not_exist.joblib")
    with pytest.raises(ValueError, match="not found"):
        DistilledProvider(model_path=tmp_path / "does_not_exist.joblib")


def test_load_corrupt_model_raises(tmp_path) -> None:
    path = tmp_path / "corrupt.joblib"
    path.write_bytes(b"this is not a joblib artifact")
    with pytest.raises(ValueError, match="Failed to load"):
        load_distilled_model(path)


def test_load_model_missing_pipeline_raises(tmp_path) -> None:
    path = tmp_path / "incomplete.joblib"
    save_distilled_model(
        {"schema": distilled.MODEL_SCHEMA, "metadata": {}, "pipelines": {}}, path
    )
    with pytest.raises(ValueError, match="missing pipelines"):
        load_distilled_model(path)


def test_save_load_round_trip(tmp_path) -> None:
    path = tiny_model(tmp_path)
    model = load_distilled_model(path)

    assert model["schema"] == distilled.MODEL_SCHEMA
    assert list(model["pipelines"]) == FEATURES
    assert model["pipelines"]["third_party_api"] is not None


# --------------------------------------------------------------------------- #
# Factory branch
# --------------------------------------------------------------------------- #


def test_factory_builds_distilled_when_model_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(distilled, "DEFAULT_MODEL_PATH", tiny_model(tmp_path))

    provider, name = get_provider("distilled")
    assert name == "distilled"
    assert isinstance(provider, DistilledProvider)
    assert provider.name == "distilled"


def test_factory_distilled_falls_back_to_stub_without_model(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(distilled, "DEFAULT_MODEL_PATH", tmp_path / "missing.joblib")

    with caplog.at_level(logging.WARNING):
        provider, name = get_provider("distilled")

    assert name == "stub"
    assert isinstance(provider, StubProvider)
    assert any("Distilled" in record.message or "distilled" in record.message for record in caplog.records)


# --------------------------------------------------------------------------- #
# Experiment machinery (offline pieces)
# --------------------------------------------------------------------------- #


def test_pipeline_recipe_matches_documented_parameters() -> None:
    pipeline = build_pipeline(seed=42)

    assert isinstance(pipeline, Pipeline)
    tfidf = pipeline.named_steps["tfidf"]
    clf = pipeline.named_steps["clf"]
    assert tfidf.ngram_range == (1, 2)
    assert tfidf.min_df == 2
    assert tfidf.sublinear_tf is True
    assert clf.max_iter == 1000
    assert clf.class_weight == "balanced"


def test_cv_predictions_deterministic_and_predict_unknown_rows() -> None:
    emails = TINY_EMAILS + ["A short email with no signal.", "Another signal-free email."]
    labels = TINY_LABELS + [None, None]

    first = cv_predictions(emails, labels, seed=42)
    second = cv_predictions(emails, labels, seed=42)

    assert first == second
    assert any(p is not None for p in first)  # folds trained
    assert first[10] is not None  # teacher-null rows are predicted on, not trained on


def test_cv_predictions_untrainable_feature_returns_all_none() -> None:
    assert cv_predictions(TINY_EMAILS, [1] * 12) == [None] * 12  # one class only
    assert cv_predictions(TINY_EMAILS, [None] * 12) == [None] * 12  # nothing labeled


def test_labels_csv_round_trip(tmp_path, monkeypatch) -> None:
    from scripts import distillation_experiment as script

    monkeypatch.setattr(script, "LABELS_PATH", tmp_path / "labels.csv")
    rows = [
        {
            "project_id": "P001",
            "email_sha1": "abc123",
            "labels": {name: "" for name in FEATURES},
        }
    ]
    rows[0]["labels"]["third_party_api"] = "1"
    rows[0]["labels"]["data_migration"] = "0"

    write_labels_csv(rows)
    loaded = load_labels_rows()

    assert loaded["P001"]["project_id"] == "P001"
    assert loaded["P001"]["email_sha1"] == "abc123"
    assert loaded["P001"]["labels"]["third_party_api"] == "1"
    assert loaded["P001"]["labels"]["data_migration"] == "0"
    assert loaded["P001"]["labels"]["multi_currency"] == ""
