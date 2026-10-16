"""Distilled student provider: small per-feature classifiers trained on LLM labels.

Spec §6.2 roadmap ("Có thể thay thế LLM bằng classifier nhỏ hơn KHI CÓ ĐỦ DỮ LIỆU")
implemented as a real provider. The student is 15 independent binary pipelines
(TF-IDF word 1-2 grams + logistic regression, one per canonical feature) trained
on labels produced by the DeepSeek teacher over the synthetic corpus — see
``backend/scripts/distillation_experiment.py`` and ``docs/DISTILLATION_EXPERIMENT.md``.

Decision rule (documented, tested; thresholds exported as module constants)::

    p = P(feature present | email)
    p >= PRESENT_THRESHOLD (0.5) -> value 1, confidence p
    p <= ABSENT_THRESHOLD  (0.4) -> value 0, confidence 1 - p
    ABSENT_THRESHOLD < p < PRESENT_THRESHOLD -> value None (abstain), confidence 0.0

The brief's single rule ("probability < 0.5 -> unknown") can never emit an explicit
0; the dead band keeps explicit-negation predictions possible while abstaining near
the boundary, where bag-of-words cannot separate "not needed" from "not mentioned".

``evidence_quote`` is always ``None``: the student does not generate text, so it
never fabricates verbatim evidence (the extraction service verifies quotes).

The model artifact is a joblib dict::

    {"schema": "distilled-v1",
     "metadata": {...},
     "pipelines": {feature_name: sklearn.pipeline.Pipeline | None}}

``load_distilled_model`` raises ``ValueError`` when the file is missing or
malformed; ``get_provider("distilled")`` converts that into a stub fallback.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import joblib

from app.features import FEATURES

MODEL_SCHEMA = "distilled-v1"

#: Repo-root ``data/`` artifact produced by ``scripts/distillation_experiment.py``.
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[3] / "data" / "distilled_model.joblib"

#: p >= PRESENT_THRESHOLD asserts value 1; p <= ABSENT_THRESHOLD asserts value 0;
#: anything in between abstains (value None). See module docstring.
PRESENT_THRESHOLD = 0.5
ABSENT_THRESHOLD = 0.4


def decide_value(probability: float | None) -> tuple[bool | None, float]:
    """Map ``P(feature present)`` to ``(value, confidence)`` using the dead band."""
    if probability is None:
        return None, 0.0
    p = float(probability)
    if p >= PRESENT_THRESHOLD:
        return True, round(p, 4)
    if p <= ABSENT_THRESHOLD:
        return False, round(1.0 - p, 4)
    return None, 0.0


def load_distilled_model(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the trained student artifact.

    Raises:
        ValueError: file missing, unreadable, or not a ``distilled-v1`` artifact
            with a pipeline slot for every canonical feature.
    """
    model_path = Path(path) if path is not None else DEFAULT_MODEL_PATH
    if not model_path.exists():
        raise ValueError(
            f"Distilled model not found at {model_path}; train it with "
            "'python scripts/distillation_experiment.py --train --write'"
        )
    try:
        model = joblib.load(model_path)
    except Exception as exc:  # corrupt/unsupported pickle
        raise ValueError(f"Failed to load distilled model from {model_path}: {exc}") from exc
    if (
        not isinstance(model, dict)
        or model.get("schema") != MODEL_SCHEMA
        or not isinstance(model.get("pipelines"), dict)
    ):
        raise ValueError(f"Unrecognized distilled model file: {model_path}")
    missing = [name for name in FEATURES if name not in model["pipelines"]]
    if missing:
        raise ValueError(f"Distilled model is missing pipelines for: {', '.join(missing)}")
    return model


def save_distilled_model(model: dict[str, Any], path: str | Path | None = None) -> Path:
    """Persist a student artifact (joblib) and return the path written."""
    model_path = Path(path) if path is not None else DEFAULT_MODEL_PATH
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    return model_path


class DistilledProvider:
    """Offline student provider; canonical JSON shape, no generation, no network.

    Reads the email out of the ``<email>...</email>`` block in the prompt (same
    regex as ``StubProvider``) and classifies all 15 canonical features with the
    trained per-feature pipelines, in ``FEATURES`` order.
    """

    name = "distilled"

    EMAIL_BLOCK_RE = re.compile(r"<email>\s*(.*?)\s*</email>", re.DOTALL | re.IGNORECASE)

    def __init__(
        self,
        model_path: str | Path | None = None,
        model: dict[str, Any] | None = None,
    ) -> None:
        """Load the artifact from ``model_path`` unless a preloaded ``model`` is given.

        Raises:
            ValueError: no artifact at ``model_path`` (factory falls back to stub).
        """
        self.model = model if model is not None else load_distilled_model(model_path)
        self.pipelines: dict[str, Any] = self.model["pipelines"]
        self.metadata: dict[str, Any] = self.model.get("metadata", {}) or {}
        self.model_path = str(model_path) if model_path is not None else str(DEFAULT_MODEL_PATH)

    # -- LLMProvider protocol -------------------------------------------------

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        match = self.EMAIL_BLOCK_RE.search(prompt or "")
        email = match.group(1) if match else ""
        return {"features": self.extract_findings(email)}

    # -- Student inference ----------------------------------------------------

    def extract_findings(self, email_text: str) -> dict[str, dict[str, Any]]:
        """Return one canonical finding dict per feature, in ``FEATURES`` order."""
        text = email_text or ""
        empty = not text.strip()
        findings: dict[str, dict[str, Any]] = {}
        for name in FEATURES:
            probability = None if empty else self._probability(name, text)
            value, confidence = decide_value(probability)
            findings[name] = {
                "value": value,
                "confidence": confidence,
                "evidence_quote": None,
            }
        return findings

    def _probability(self, name: str, text: str) -> float | None:
        pipeline = self.pipelines.get(name)
        if pipeline is None:  # feature had too few/one-class teacher labels
            return None
        try:
            probabilities = pipeline.predict_proba([text])[0]
            classes = list(pipeline.classes_)
            return float(probabilities[classes.index(1)])
        except Exception:  # pragma: no cover - defensive: broken artifact/empty vector
            return None
