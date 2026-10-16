"""Feature extraction service (spec §4.1, checklist Phase 2).

Pipeline: build prompt -> provider.complete_json -> parse/validate -> verify
evidence quotes with rapidfuzz -> post-process warnings. The service never
raises for provider/parse failures: after MAX_ATTEMPTS it degrades to an
all-null result so the API layer can still show the missing-information flow.
Empty/whitespace input is the only ValueError (spec §9: "Vui lòng paste email").
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator
from rapidfuzz import fuzz

from app.features import FEATURE_DEFINITIONS, FEATURES
from app.services.providers import LLMProvider, get_provider

logger = logging.getLogger(__name__)

MAX_EMAIL_CHARS = 10_000
EVIDENCE_THRESHOLD = 85.0  # rapidfuzz partial_ratio (0..100)
MAX_ATTEMPTS = 3

WARN_LONG_EMAIL = "Email dài, kết quả có thể kém chính xác"
WARN_CONFLICT = "Mâu thuẫn: realtime_ui và offline_mode"
WARN_NO_FEATURES = "Không tìm thấy features, vui lòng review"


class FeatureFinding(BaseModel):
    """Extraction outcome for one canonical feature."""

    name: str
    value: bool | None = None
    confidence: float = 0.0
    evidence_quote: str | None = None

    @field_validator("confidence")
    @classmethod
    def _clip_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class ExtractionResult(BaseModel):
    """Always contains exactly 15 findings, in ``app.features.FEATURES`` order."""

    findings: list[FeatureFinding] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str = "stub"


SYSTEM_PROMPT = (
    "You are a senior software estimation analyst in an outsourcing company. "
    "You read customer emails/RFPs and extract structured project complexity signals. "
    "You are strictly factual: you never infer, assume or invent information. "
    "You answer with a single JSON object and nothing else."
)

_EXTRACTION_PROMPT_TEMPLATE = """Read the customer email and determine, for EACH of the 15 binary features below, whether the project includes it.

FEATURES (canonical names and definitions):
{FEATURES}

OUTPUT — return ONE JSON object with exactly this shape, all 15 keys, nothing else:
{SCHEMA}

VALUE RULES:
- value = 1  -> the email clearly mentions the project includes this feature
- value = 0  -> the email clearly states the project does NOT need this feature
- value = null -> the email does not mention this feature at all

STRICT RULES:
1. evidence_quote MUST be copied VERBATIM from the email (one sentence). Never paraphrase or translate.
2. If a feature is not mentioned, value=null, evidence_quote=null. Never guess from the type of project.
3. confidence is your certainty in [0,1]; use lower values when the mention is indirect.
4. Output all 15 keys, exactly once each, using the exact canonical names.

EMAIL:
<email>
{EMAIL}
</email>
"""


def build_extraction_prompt(email_text: str) -> str:
    """Render the extraction prompt for real LLM providers."""
    features_block = "\n".join(
        f"- {name}: {FEATURE_DEFINITIONS[name]}" for name in FEATURES
    )
    schema_example: dict[str, Any] = {
        "features": {
            name: {"value": None, "confidence": 0.0, "evidence_quote": None}
            for name in FEATURES
        }
    }
    schema_example["features"]["third_party_api"] = {
        "value": 1,
        "confidence": 0.9,
        "evidence_quote": "verbatim sentence copied from the email",
    }
    schema_example["features"]["data_migration"] = {
        "value": 0,
        "confidence": 0.8,
        "evidence_quote": "sentence stating it is not needed",
    }
    schema_json = json.dumps(schema_example, ensure_ascii=False, indent=2)
    return (
        _EXTRACTION_PROMPT_TEMPLATE.replace("{FEATURES}", features_block)
        .replace("{SCHEMA}", schema_json)
        .replace("{EMAIL}", email_text)
    )


_TRUE_STRINGS = {"1", "true", "yes", "y", "có", "co"}
_FALSE_STRINGS = {"0", "false", "no", "n", "không", "khong"}


def _coerce_value(raw: Any) -> bool | None:
    """Normalize a provider value (bool/int/str/None) to bool | None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        if raw in (0, 1):
            return bool(raw)
        raise ValueError(f"Invalid feature value: {raw!r}")
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in _TRUE_STRINGS:
            return True
        if token in _FALSE_STRINGS:
            return False
        if token in ("", "null", "none", "unknown", "không rõ"):
            return None
        raise ValueError(f"Invalid feature value: {raw!r}")
    raise ValueError(f"Invalid feature value type: {type(raw).__name__}")


def _parse_features_payload(data: Any) -> dict[str, dict[str, Any]]:
    """Validate the provider JSON and normalize it to canonical per-feature dicts.

    Raises ValueError on malformed payloads so the caller can retry.
    """
    if not isinstance(data, dict):
        raise ValueError("Provider JSON is not an object")
    features = data.get("features")
    if features is None and any(name in data for name in FEATURES):
        features = data  # tolerate a flat {feature: ...} object
    if not isinstance(features, dict):
        raise ValueError("Provider JSON has no 'features' object")

    normalized: dict[str, dict[str, Any]] = {}
    for name in FEATURES:
        entry = features.get(name)
        if entry is None:
            normalized[name] = {"value": None, "confidence": 0.0, "evidence_quote": None}
            continue
        if isinstance(entry, dict):
            value = _coerce_value(entry.get("value"))
            confidence = float(entry.get("confidence", 0.5) or 0.0)
            quote = entry.get("evidence_quote") or entry.get("evidence") or entry.get("quote")
        else:  # bare scalar (bool/int/str)
            value = _coerce_value(entry)
            confidence = 0.5
            quote = None
        confidence = max(0.0, min(1.0, confidence))
        quote = str(quote).strip() if isinstance(quote, str) and quote.strip() else None
        normalized[name] = {"value": value, "confidence": confidence, "evidence_quote": quote}
    return normalized


def _verify_evidence(
    finding: FeatureFinding, email_text: str, warnings: list[str]
) -> FeatureFinding:
    """Drop quotes that are not (fuzzily) present in the email; halve confidence."""
    if not finding.evidence_quote:
        return finding
    ratio = fuzz.partial_ratio(finding.evidence_quote, email_text)
    if ratio >= EVIDENCE_THRESHOLD:
        return finding
    warnings.append(
        f"Evidence của {finding.name} không khớp email "
        f"(độ khớp {ratio:.0f}% < {EVIDENCE_THRESHOLD:.0f}%), đã bỏ trích dẫn và giảm confidence"
    )
    return finding.model_copy(
        update={"evidence_quote": None, "confidence": finding.confidence / 2.0}
    )


def _postprocess(
    findings: list[FeatureFinding], warnings: list[str], provider_name: str
) -> ExtractionResult:
    values = {f.name: f.value for f in findings}
    if values.get("realtime_ui") and values.get("offline_mode"):
        warnings.append(WARN_CONFLICT)
    if all(value is None for value in values.values()) and findings:
        warnings.append(WARN_NO_FEATURES)
    missing = [f.name for f in findings if f.value is None]
    return ExtractionResult(
        findings=findings, missing=missing, warnings=warnings, provider=provider_name
    )


def extract_features(
    email_text: str, provider: LLMProvider | tuple[LLMProvider, str] | None = None
) -> ExtractionResult:
    """Extract the 15 canonical features from a customer email.

    Args:
        email_text: raw email/RFP text (EN or VI).
        provider: optional ``LLMProvider`` (or ``(provider, name)`` tuple). When
            omitted, ``get_provider()`` picks gemini/openai/stub from settings.

    Raises:
        ValueError: empty/whitespace input only ("Vui lòng paste email").
    """
    if not email_text or not email_text.strip():
        raise ValueError("Vui lòng paste email")

    if isinstance(provider, tuple):
        provider, provider_name = provider
    elif provider is None:
        provider, provider_name = get_provider()
    else:
        provider_name = str(getattr(provider, "name", None) or type(provider).__name__)

    email = email_text
    warnings: list[str] = []
    if len(email_text) > MAX_EMAIL_CHARS:
        warnings.append(WARN_LONG_EMAIL)

    prompt = build_extraction_prompt(email)
    payload: dict[str, dict[str, Any]] | None = None
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = provider.complete_json(prompt, SYSTEM_PROMPT)
            payload = _parse_features_payload(raw)
            break
        except Exception as exc:  # provider errors, invalid JSON, bad shapes
            last_error = exc
            logger.warning(
                "Extraction attempt %d/%d failed (%s): %s",
                attempt,
                MAX_ATTEMPTS,
                type(exc).__name__,
                exc,
            )

    if payload is None:
        warnings.append(
            f"Không thể trích xuất features sau {MAX_ATTEMPTS} lần thử "
            f"({type(last_error).__name__}); trả về toàn bộ giá trị chưa rõ"
        )
        findings = [FeatureFinding(name=name) for name in FEATURES]
    else:
        findings = [
            FeatureFinding(
                name=name,
                value=payload[name]["value"],
                confidence=payload[name]["confidence"],
                evidence_quote=payload[name]["evidence_quote"],
            )
            for name in FEATURES
        ]
        findings = [_verify_evidence(f, email, warnings) for f in findings]

    return _postprocess(findings, warnings, provider_name)
