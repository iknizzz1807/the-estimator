"""Tests for hybrid similar-project retrieval."""

from __future__ import annotations

from app.features import FEATURES
from app.services.similarity import find_similar


def make_corpus() -> list[dict]:
    def row(project_id: str, text: str, active: list[str], actual: float) -> dict:
        features = {name: int(name in active) for name in FEATURES}
        return {
            "project_id": project_id,
            "email_text": text,
            "features": features,
            "actual_days": actual,
        }

    return [
        row(
            "P1",
            "The project needs a payment gateway integration with Stripe and "
            "PCI-DSS compliance for card data.",
            ["payment_gateway", "pci_dss", "third_party_api"],
            45.0,
        ),
        row(
            "P2",
            "Build an offline mobile app for iOS and Android so field workers "
            "can work without internet.",
            ["mobile_app", "offline_mode"],
            60.0,
        ),
        row(
            "P3",
            "Migrate data from a legacy COBOL system into a modern data warehouse.",
            ["data_migration", "legacy_tech_stack"],
            50.0,
        ),
        row(
            "P4",
            "A real-time dashboard with live updates over websockets for operators.",
            ["realtime_ui"],
            30.0,
        ),
        row(
            "P5",
            "Single sign-on with OAuth for enterprise customers using Azure AD.",
            ["identity_provider"],
            25.0,
        ),
    ]


def test_payment_query_ranks_payment_row_first() -> None:
    query = "We need payment integration with Stripe and PCI DSS compliance."
    results = find_similar(query, make_corpus(), k=3)

    assert results
    assert results[0]["project_id"] == "P1"
    for item in results:
        assert 0.0 <= item["score"] <= 1.0
        assert item["snippet"]


def test_k_is_respected_and_shared_features_reported() -> None:
    corpus = make_corpus()
    query = "Payment gateway with Stripe and card data compliance."
    query_features = {name: 0 for name in FEATURES}
    query_features.update({"payment_gateway": 1, "pci_dss": 1})

    top2 = find_similar(query, corpus, k=2, query_features=query_features)
    assert len(top2) == 2
    assert top2[0]["project_id"] == "P1"
    assert set(top2[0]["shared_features"]) == {"payment_gateway", "pci_dss"}

    everything = find_similar(query, corpus, k=99)
    assert len(everything) == len(corpus)

    assert find_similar(query, corpus, k=0) == []
    assert find_similar(query, [], k=3) == []


def test_scores_are_bounded_and_snippet_is_short() -> None:
    corpus = make_corpus()
    query = "Mobile app offline support for construction sites."
    results = find_similar(query, corpus, k=5)

    assert results[0]["project_id"] == "P2"
    for item in results:
        assert 0.0 <= item["score"] <= 1.0
        assert len(item["snippet"]) <= 95  # ~90 chars + "..."
    long_snippet = find_similar("x", corpus, k=1)[0]["snippet"]
    assert long_snippet
