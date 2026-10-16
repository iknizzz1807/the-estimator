"""LLM provider abstraction for The Estimator (deepseek | gemini | openai | stub).

docs/DECISIONS.md (D2): the product must run fully offline, so ``stub`` is a
deterministic rule-based extractor that returns the exact JSON shape the real
providers are asked to produce. Network providers are plain httpx calls with
temperature 0 and 2 retries — they are never exercised by unit tests.

Canonical provider JSON shape returned by ``complete_json``::

    {"features": {name: {"value": 1 | 0 | null,
                         "confidence": 0.0..1.0,
                         "evidence_quote": "verbatim sentence" | null}}}

(``value`` may also be a plain bool/int JSON scalar; the extraction service
normalizes both forms.)
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.features import FEATURES

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2  # + initial attempt = 3 tries total
RETRY_BACKOFF_SECONDS = 0.5


# --------------------------------------------------------------------------- #
# Settings (pydantic-settings, reads .env at repo root or backend/)
# --------------------------------------------------------------------------- #


class Settings(BaseSettings):
    """Env-driven settings; missing cloud API keys degrade to the stub."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    llm_provider: str = "stub"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"


def get_settings() -> Settings:
    """Load settings from environment / .env (fresh read, test-friendly)."""
    return Settings()


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal provider contract used by every service in this package."""

    name: str

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        """Run a completion and return the parsed JSON object."""
        ...


# --------------------------------------------------------------------------- #
# JSON parsing helper
# --------------------------------------------------------------------------- #

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_response(text: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response.

    Handles bare JSON, ```json fenced blocks and prose around the object.
    Raises ValueError when no JSON object can be parsed.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty LLM response")
    candidates: list[str] = []
    fenced = _FENCED_JSON_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("LLM response is not a JSON object")


# --------------------------------------------------------------------------- #
# Cloud providers
# --------------------------------------------------------------------------- #


class GeminiProvider:
    """Google Gemini ``generateContent`` with forced JSON output."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        if not api_key:
            raise ValueError("GeminiProvider requires a non-empty API key")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        url = GEMINI_URL.format(model=self.model) + f"?key={self.api_key}"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return parse_json_response(text)
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
        raise ValueError(f"Gemini call failed after {self.max_retries + 1} attempts: {last_error}")


class OpenAIProvider:
    """OpenAI chat completions with ``response_format=json_object``."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIProvider requires a non-empty API key")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(OPENAI_URL, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                text = data["choices"][0]["message"]["content"]
                return parse_json_response(text)
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
        raise ValueError(f"OpenAI call failed after {self.max_retries + 1} attempts: {last_error}")


class DeepSeekProvider:
    """DeepSeek chat completions (OpenAI-compatible) with forced JSON output.

    ``deepseek-flash`` (DeepSeek-V4.1-Flash) enables *thinking* mode by default;
    feature extraction wants fast, cheap, deterministic JSON, so thinking is
    explicitly disabled. Output is forced with
    ``response_format={"type": "json_object"}`` (the extraction prompt asks for
    a JSON object, as the API requires the word "json" in the prompt).
    """

    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-flash",
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        if not api_key:
            raise ValueError("DeepSeekProvider requires a non-empty API key")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(DEEPSEEK_URL, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                text = data["choices"][0]["message"]["content"]
                return parse_json_response(text)
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
        raise ValueError(f"DeepSeek call failed after {self.max_retries + 1} attempts: {last_error}")


# --------------------------------------------------------------------------- #
# Stub provider — deterministic offline rule-based extractor
# --------------------------------------------------------------------------- #

STRONG = 0.85  # explicit mention
WEAK = 0.6  # synonym / softer signal

#: Words that turn a keyword into an explicit "not needed" statement when they
#: appear within NEGATION_WINDOW words before the match (spec §4.1).
NEGATORS = {
    "no",
    "not",
    "without",
    "never",
    "dont",
    "doesnt",
    "didnt",
    "isnt",
    "arent",
    "cant",
    "wont",
    "khong",
    "chua",
    "ko",
    "k",
    "không",
    "chưa",
}
NEGATION_WINDOW = 3

#: Keyword sets per canonical feature (EN + VI). Order inside a feature only
#: matters for equal match positions (strongest listed first).
FEATURE_KEYWORDS: dict[str, list[tuple[str, float]]] = {
    "third_party_api": [
        ("third party", STRONG),
        ("integrate with", STRONG),
        ("external api", STRONG),
        ("tích hợp", STRONG),
        ("hệ thống ngoài", STRONG),
        ("integration", WEAK),
        ("rest api", WEAK),
        ("api", WEAK),
        ("crm", WEAK),
        ("erp", WEAK),
        ("webhook", WEAK),
        ("kết nối", WEAK),
        ("vendor system", WEAK),
    ],
    "payment_gateway": [
        ("payment", STRONG),
        ("stripe", STRONG),
        ("vnpay", STRONG),
        ("momo", STRONG),
        ("checkout", STRONG),
        ("thanh toán", STRONG),
        ("cổng thanh toán", STRONG),
        ("pay via", WEAK),
        ("paypal", WEAK),
        ("credit card", WEAK),
        ("debit card", WEAK),
        ("visa", WEAK),
        ("mastercard", WEAK),
        ("wallet", WEAK),
        ("billing", WEAK),
        ("hóa đơn", WEAK),
        ("ví điện tử", WEAK),
    ],
    "identity_provider": [
        ("sso", STRONG),
        ("oauth", STRONG),
        ("single sign-on", STRONG),
        ("identity provider", STRONG),
        ("đăng nhập một lần", STRONG),
        ("openid", WEAK),
        ("saml", WEAK),
        ("ldap", WEAK),
        ("active directory", WEAK),
        ("azure ad", WEAK),
        ("login", WEAK),
        ("sign in", WEAK),
        ("authentication", WEAK),
        ("đăng nhập", WEAK),
        ("xác thực", WEAK),
    ],
    "external_data_sync": [
        ("sync", STRONG),
        ("đồng bộ", STRONG),
        ("synchronization", WEAK),
        ("synchronize", WEAK),
        ("two-way data", WEAK),
        ("data feed", WEAK),
        ("webhook", WEAK),
        ("đồng bộ hóa", WEAK),
        ("cập nhật dữ liệu", WEAK),
    ],
    "data_migration": [
        ("migrate", STRONG),
        ("migration", STRONG),
        ("legacy database", STRONG),
        ("chuyển dữ liệu", STRONG),
        ("import data", WEAK),
        ("existing data", WEAK),
        ("current database", WEAK),
        ("di chuyển dữ liệu", WEAK),
        ("cơ sở dữ liệu cũ", WEAK),
    ],
    "multi_currency": [
        ("multi-currency", STRONG),
        ("multiple currencies", STRONG),
        ("đa tiền tệ", STRONG),
        ("đa loại tiền", STRONG),
        ("currency", WEAK),
        ("exchange rate", WEAK),
        ("forex", WEAK),
        ("tỷ giá", WEAK),
        ("ngoại tệ", WEAK),
        ("quy đổi tiền", WEAK),
    ],
    "multi_tenancy": [
        ("multi-tenant", STRONG),
        ("multi tenancy", STRONG),
        ("nhiều khách hàng", STRONG),
        ("tenant", WEAK),
        ("saas platform", WEAK),
        ("white-label", WEAK),
        ("phân tách dữ liệu", WEAK),
        ("nhiều công ty", WEAK),
    ],
    "realtime_ui": [
        ("real-time", STRONG),
        ("realtime", STRONG),
        ("live updates", STRONG),
        ("websocket", STRONG),
        ("thời gian thực", STRONG),
        ("live dashboard", WEAK),
        ("instant updates", WEAK),
        ("streaming updates", WEAK),
        ("server-sent events", WEAK),
        ("sse", WEAK),
        ("cập nhật tức thời", WEAK),
        ("cập nhật trực tiếp", WEAK),
    ],
    "mobile_app": [
        ("mobile app", STRONG),
        ("ios", STRONG),
        ("android", STRONG),
        ("native app", STRONG),
        ("ứng dụng di động", STRONG),
        ("mobile application", WEAK),
        ("app store", WEAK),
        ("smartphone", WEAK),
        ("react native", WEAK),
        ("flutter", WEAK),
        ("ứng dụng mobile", WEAK),
        ("điện thoại", WEAK),
    ],
    "offline_mode": [
        ("offline", STRONG),
        ("no internet", STRONG),
        ("ngoại tuyến", STRONG),
        ("without internet", WEAK),
        ("no connectivity", WEAK),
        ("local storage", WEAK),
        ("mất kết nối", WEAK),
        ("không có mạng", WEAK),
        ("không có internet", WEAK),
    ],
    "pci_dss": [
        ("pci", STRONG),
        ("card data", STRONG),
        ("cardholder", WEAK),
        ("credit card data", WEAK),
        ("payment card", WEAK),
        ("thẻ tín dụng", WEAK),
        ("dữ liệu thẻ", WEAK),
    ],
    "privacy_compliance": [
        ("gdpr", STRONG),
        ("hipaa", STRONG),
        ("privacy compliance", STRONG),
        ("tuân thủ", STRONG),
        ("privacy", WEAK),
        ("data protection", WEAK),
        ("personal data", WEAK),
        ("consent", WEAK),
        ("ccpa", WEAK),
        ("quyền riêng tư", WEAK),
        ("bảo vệ dữ liệu", WEAK),
        ("dữ liệu cá nhân", WEAK),
    ],
    "audit_logging": [
        ("audit", STRONG),
        ("audit trail", STRONG),
        ("audit log", STRONG),
        ("lịch sử thao tác", STRONG),
        ("logging", WEAK),
        ("activity log", WEAK),
        ("track changes", WEAK),
        ("nhật ký", WEAK),
        ("ghi log", WEAK),
        ("ghi nhật ký", WEAK),
    ],
    "legacy_tech_stack": [
        ("legacy", STRONG),
        ("cobol", STRONG),
        ("old system", STRONG),
        ("hệ thống cũ", STRONG),
        ("on-prem", STRONG),
        ("mainframe", WEAK),
        ("as/400", WEAK),
        ("vb6", WEAK),
        ("monolith", WEAK),
        ("hệ thống hiện tại", WEAK),
        ("máy chủ nội bộ", WEAK),
        ("công nghệ cũ", WEAK),
    ],
    "cross_team_coordination": [
        ("multiple teams", STRONG),
        ("coordinate with", STRONG),
        ("stakeholders", STRONG),
        ("nhiều team", STRONG),
        ("phối hợp", STRONG),
        ("cross-team", WEAK),
        ("coordination", WEAK),
        ("multiple vendors", WEAK),
        ("các bên liên quan", WEAK),
        ("nhiều bộ phận", WEAK),
        ("nhiều phòng ban", WEAK),
    ],
}

assert set(FEATURE_KEYWORDS) == set(FEATURES), "Stub keywords must cover all 15 features"

_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?…]+(?=\s|$)|[\n\r]+")


@lru_cache(maxsize=512)
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Compile a keyword into a word-boundary regex.

    Whitespace/hyphen variants are interchangeable ("third party" matches
    "third-party") and a trailing ASCII plural "s" is tolerated on the last
    token ("payment" matches "payments").
    """
    raw_words = re.split(r"[\s\-]+", keyword)
    core = r"[\s\-]+".join(re.escape(w) for w in raw_words)
    plural = r"(?:s)?" if re.fullmatch(r"[A-Za-z]{3,}", raw_words[-1]) else ""
    return re.compile(rf"\b{core}{plural}\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    """NFC-normalize so Unicode input is matched consistently."""
    return unicodedata.normalize("NFC", text)


def _is_negated(text: str, match_start: int) -> bool:
    """True when a negator appears within NEGATION_WINDOW words before the match."""
    prefix_words = re.findall(r"\w+", text[:match_start])
    return any(w.lower() in NEGATORS for w in prefix_words[-NEGATION_WINDOW:])


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        spans.append((start, match.end()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _sentence_for(text: str, spans: list[tuple[int, int]], position: int) -> str:
    for start, end in spans:
        if start <= position < end:
            return " ".join(text[start:end].split())
    return " ".join(text.split())


class StubProvider:
    """Deterministic offline rule-based extractor (no network, no randomness).

    Reads the email out of the ``<email>...</email>`` block in the prompt and
    returns the canonical provider JSON shape. Negation handling per spec §4.1:
    a keyword preceded within 3 words by no/not/without/không/chưa marks the
    feature as explicitly excluded (value 0).
    """

    name = "stub"

    EMAIL_BLOCK_RE = re.compile(r"<email>\s*(.*?)\s*</email>", re.DOTALL | re.IGNORECASE)

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        match = self.EMAIL_BLOCK_RE.search(prompt or "")
        email = match.group(1) if match else ""
        return {"features": self.extract_findings(email)}

    def extract_findings(self, email_text: str) -> dict[str, dict[str, Any]]:
        """Return one finding dict per canonical feature, in FEATURES order."""
        text = _normalize(email_text or "")
        spans = _sentence_spans(text)
        findings: dict[str, dict[str, Any]] = {}
        for name in FEATURES:
            findings[name] = self._find_feature(name, text, spans)
        return findings

    def _find_feature(
        self, name: str, text: str, spans: list[tuple[int, int]]
    ) -> dict[str, Any]:
        # (negated, position, -confidence, match) — non-negated earliest wins.
        candidates: list[tuple[bool, int, float, re.Match[str]]] = []
        for keyword, confidence in FEATURE_KEYWORDS[name]:
            for match in _keyword_pattern(keyword).finditer(text):
                negated = _is_negated(text, match.start())
                candidates.append((negated, match.start(), -confidence, match))
        if not candidates:
            return {"value": None, "confidence": 0.0, "evidence_quote": None}
        candidates.sort(key=lambda c: (c[0], c[1], c[2]))
        negated, _, neg_confidence, match = candidates[0]
        return {
            "value": 0 if negated else 1,
            "confidence": -neg_confidence,
            "evidence_quote": _sentence_for(text, spans, match.start()),
        }


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def get_provider(name: str | None = None) -> tuple[LLMProvider, str]:
    """Return ``(provider, provider_name)`` honoring LLM_PROVIDER.

    Missing cloud API keys (or unknown names) log a warning and fall back to
    the stub; the returned name always reflects the provider actually used.
    """
    settings = get_settings()
    requested = (name or settings.llm_provider or "stub").strip().lower()

    if requested == "gemini":
        if settings.gemini_api_key:
            return GeminiProvider(settings.gemini_api_key, settings.gemini_model), "gemini"
        logger.warning("GEMINI_API_KEY is not set - falling back to the offline stub provider")
        return StubProvider(), "stub"

    if requested == "openai":
        if settings.openai_api_key:
            return OpenAIProvider(settings.openai_api_key, settings.openai_model), "openai"
        logger.warning("OPENAI_API_KEY is not set - falling back to the offline stub provider")
        return StubProvider(), "stub"

    if requested == "deepseek":
        if settings.deepseek_api_key:
            return DeepSeekProvider(settings.deepseek_api_key, settings.deepseek_model), "deepseek"
        logger.warning("DEEPSEEK_API_KEY is not set - falling back to the offline stub provider")
        return StubProvider(), "stub"

    if requested not in ("stub", ""):
        logger.warning("Unknown LLM_PROVIDER %r - falling back to the offline stub provider", requested)
    return StubProvider(), "stub"
