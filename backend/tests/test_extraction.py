"""Tests for the extraction service (stub provider, retries, guardrails)."""

from __future__ import annotations

import pytest
from rapidfuzz import fuzz

from app.features import FEATURES
from app.services.extraction import (
    MAX_ATTEMPTS,
    ExtractionResult,
    extract_features,
)
from app.services.providers import DEEPSEEK_URL, DeepSeekProvider, StubProvider, get_provider, parse_json_response

EN_EMAIL = (
    "Hello, we need to integrate with a third-party CRM through an external API. "
    "Customers will pay via Stripe for the yearly subscription and we need reports of payments. "
    "The project includes a data migration from the existing database."
)

VI_EMAIL = (
    "Chúng tôi cần tích hợp thanh toán qua VNPay và đồng bộ dữ liệu với hệ thống ERP."
)


def findings_by_name(result: ExtractionResult) -> dict:
    return {finding.name: finding for finding in result.findings}


def test_stub_detects_english_features() -> None:
    result = extract_features(EN_EMAIL, provider=StubProvider())

    assert len(result.findings) == 15
    assert [f.name for f in result.findings] == FEATURES

    findings = findings_by_name(result)
    for name in ("third_party_api", "payment_gateway", "data_migration"):
        assert findings[name].value is True, name
        assert findings[name].evidence_quote, name
        assert findings[name].confidence >= 0.6
        # quotes are verbatim sentences from the email
        assert findings[name].evidence_quote in EN_EMAIL
        assert fuzz.partial_ratio(findings[name].evidence_quote, EN_EMAIL) >= 85


def test_stub_detects_vietnamese_features() -> None:
    result = extract_features(VI_EMAIL, provider=StubProvider())
    findings = findings_by_name(result)

    assert findings["payment_gateway"].value is True  # "thanh toán"
    assert findings["external_data_sync"].value is True  # "đồng bộ"
    assert findings["payment_gateway"].evidence_quote
    assert findings["payment_gateway"].evidence_quote in VI_EMAIL


def test_negation_marks_feature_explicitly_absent() -> None:
    result = extract_features("The client said no mobile app is needed for phase one.")
    findings = findings_by_name(result)

    assert findings["mobile_app"].value is False
    assert "mobile_app" not in result.missing

    vi = extract_features("Chúng tôi không cần thanh toán trực tuyến.")
    assert findings_by_name(vi)["payment_gateway"].value is False


class FakeProvider:
    """Deterministic provider returning pre-canned payloads."""

    name = "fake"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def complete_json(self, prompt, system=None):
        self.calls += 1
        item = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def full_payload(**entries):
    features = {
        name: {"value": None, "confidence": 0.0, "evidence_quote": None}
        for name in FEATURES
    }
    features.update(entries)
    return {"features": features}


def test_fabricated_evidence_is_dropped_and_confidence_halved() -> None:
    provider = FakeProvider(
        [
            full_payload(
                data_migration={
                    "value": 1,
                    "confidence": 0.8,
                    "evidence_quote": "This sentence does not appear in the email at all.",
                }
            )
        ]
    )
    result = extract_features("We are building a small reporting dashboard.", provider=provider)
    finding = findings_by_name(result)["data_migration"]

    assert finding.value is True
    assert finding.evidence_quote is None
    assert finding.confidence == pytest.approx(0.4)
    assert any("Evidence" in w for w in result.warnings)


def test_empty_email_raises() -> None:
    with pytest.raises(ValueError, match="Vui lòng paste email"):
        extract_features("")
    with pytest.raises(ValueError, match="Vui lòng paste email"):
        extract_features("   \n\t  ")


def test_long_email_warns() -> None:
    long_email = ("We need a reporting dashboard for the sales team. " * 300)[:12000]
    assert len(long_email) > 10_000
    result = extract_features(long_email, provider=StubProvider())

    assert any("Email dài" in w for w in result.warnings)


def test_failing_provider_returns_all_null_result_without_raising() -> None:
    provider = FakeProvider([RuntimeError("boom")])
    result = extract_features("Some email about a project.", provider=provider)

    assert provider.calls == MAX_ATTEMPTS
    assert len(result.findings) == 15
    assert [f.name for f in result.findings] == FEATURES
    assert all(f.value is None for f in result.findings)
    assert result.warnings
    assert result.provider == "fake"
    assert "Không tìm thấy features, vui lòng review" in result.warnings


def test_conflict_warning_and_no_feature_warning() -> None:
    conflict = extract_features(
        "We need real-time notifications and an offline mode for field teams."
    )
    findings = findings_by_name(conflict)
    assert findings["realtime_ui"].value is True
    assert findings["offline_mode"].value is True
    assert "Mâu thuẫn: realtime_ui và offline_mode" in conflict.warnings
    # both flags are kept as extracted - the system never auto-changes them
    assert findings["realtime_ui"].value is True

    nothing = extract_features("Hello, thanks for your time.")
    assert all(f.value is None for f in nothing.findings)
    assert "Không tìm thấy features, vui lòng review" in nothing.warnings


def test_missing_list_and_provider_name() -> None:
    result = extract_features(EN_EMAIL, provider=StubProvider())
    assert result.provider == "stub"
    assert result.missing == [f.name for f in result.findings if f.value is None]


def test_retry_recovers_after_transient_failure() -> None:
    payload = full_payload(
        third_party_api={"value": 1, "confidence": 0.9, "evidence_quote": EN_EMAIL}
    )
    provider = FakeProvider([RuntimeError("transient"), payload])
    result = extract_features(EN_EMAIL, provider=provider)

    assert provider.calls == 2
    assert findings_by_name(result)["third_party_api"].value is True


def test_malformed_payload_triggers_retries_then_all_null() -> None:
    provider = FakeProvider([{"features": "not a dict"}])
    result = extract_features(EN_EMAIL, provider=provider)

    assert provider.calls == MAX_ATTEMPTS
    assert all(f.value is None for f in result.findings)


def test_parse_json_response_variants() -> None:
    assert parse_json_response('{"a": 1}') == {"a": 1}
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_response('Sure, here it is: {"a": 1} - done.') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_response("no json in this answer")
    with pytest.raises(ValueError):
        parse_json_response("")


def test_parse_json_response_repairs_missing_final_brace() -> None:
    # deepseek-flash occasionally drops the final '}' (finish_reason "stop").
    full = '{"features": {"payment_gateway": {"value": 1, "confidence": 0.9, "evidence_quote": null}}}'
    data = parse_json_response(full[:-1])  # one closing brace missing
    assert data["features"]["payment_gateway"]["value"] == 1

    # Braces inside strings must not confuse the repair.
    tricky = '{"note": "ends with } inside a string", "x": 1'
    assert parse_json_response(tricky)["x"] == 1

    # Balanced-but-invalid JSON is still rejected.
    with pytest.raises(ValueError):
        parse_json_response('{"a": }')
    # Unterminated string -> no repair claim.
    with pytest.raises(ValueError):
        parse_json_response('{"a": "unterminated')


def test_get_provider_falls_back_to_stub_without_api_key(monkeypatch) -> None:
    # Env vars take precedence over any .env file, so explicitly blank the keys.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    provider, name = get_provider()
    assert name == "stub"
    assert isinstance(provider, StubProvider)

    assert get_provider("openai")[1] == "stub"
    assert get_provider("deepseek")[1] == "stub"
    assert get_provider("stub")[1] == "stub"
    assert get_provider("nonsense-provider")[1] == "stub"


def test_get_provider_builds_deepseek_when_key_set(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")

    provider, name = get_provider()
    assert name == "deepseek"
    assert isinstance(provider, DeepSeekProvider)
    assert provider.model == "deepseek-flash"
    assert DEEPSEEK_URL.endswith("/chat/completions")
