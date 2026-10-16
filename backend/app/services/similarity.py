"""Similar-project retrieval: hybrid BM25 + TF-IDF cosine + rapidfuzz.

docs/DECISIONS.md (D3): no sentence-transformers/torch on device, so semantic
matching is approximated by a weighted hybrid of lexical scorers. Each
component is normalized to 0..1 before combining (0.5 BM25, 0.3 TF-IDF cosine,
0.2 rapidfuzz token_set_ratio), which keeps the final score interpretable.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

import numpy as np
from rank_bm25 import BM25Okapi
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.features import FEATURES

BM25_WEIGHT = 0.5
TFIDF_WEIGHT = 0.3
FUZZ_WEIGHT = 0.2
SNIPPET_LENGTH = 90

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase + punctuation-stripped tokens (BM25 vocabulary)."""
    return _TOKEN_RE.findall((text or "").lower())


def _normalize_scores(scores: np.ndarray) -> np.ndarray:
    """Min-max normalize to 0..1; degenerate ranges become 0.0 (no signal)."""
    if scores.size == 0:
        return scores
    low, high = float(scores.min()), float(scores.max())
    if high - low < 1e-12:
        return np.zeros_like(scores)
    return (scores - low) / (high - low)


def _snippet(text: str, length: int = SNIPPET_LENGTH) -> str:
    """First ~90 characters of the email with collapsed whitespace."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= length:
        return collapsed
    return collapsed[:length] + "..."


def find_similar(
    query_text: str,
    corpus: Sequence[Mapping[str, Any]],
    k: int = 3,
    query_features: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the k most similar corpus rows to ``query_text``.

    Args:
        query_text: the new email/RFP text.
        corpus: rows with ``project_id``, ``email_text``, ``features``,
            ``actual_days`` (optional ``title``).
        k: number of results.
        query_features: optional extracted features of the query; when given,
            ``shared_features`` lists features that are 1 in both.

    Returns:
        Top-k dicts: project_id, score (0..1), actual_days, shared_features,
        snippet. Ties break on project_id for determinism.
    """
    if not corpus or k <= 0:
        return []

    query = query_text or ""
    texts = [str(row.get("email_text") or "") for row in corpus]
    n = len(texts)

    # --- BM25 (min-max normalized over the corpus) ---
    query_tokens = _tokenize(query)
    if query_tokens:
        bm25 = BM25Okapi([_tokenize(text) for text in texts])
        bm25_scores = _normalize_scores(np.asarray(bm25.get_scores(query_tokens), dtype=float))
    else:
        bm25_scores = np.zeros(n, dtype=float)

    # --- TF-IDF cosine (vectorizer fit on corpus + query) ---
    tfidf_scores = np.zeros(n, dtype=float)
    try:
        vectorizer = TfidfVectorizer(sublinear_tf=True)
        matrix = vectorizer.fit_transform(texts + [query])
        tfidf_scores = np.clip(
            cosine_similarity(matrix[-1], matrix[:-1]).ravel(), 0.0, 1.0
        )
    except ValueError:
        pass  # empty vocabulary (e.g. blank corpus) -> no TF-IDF signal

    # --- rapidfuzz token_set_ratio (already 0..1) ---
    fuzz_scores = np.array(
        [fuzz.token_set_ratio(query, text) / 100.0 for text in texts], dtype=float
    )

    combined = (
        BM25_WEIGHT * bm25_scores + TFIDF_WEIGHT * tfidf_scores + FUZZ_WEIGHT * fuzz_scores
    )

    order = sorted(
        range(n),
        key=lambda i: (-float(combined[i]), str(corpus[i].get("project_id") or "")),
    )

    results: list[dict[str, Any]] = []
    for index in order[: min(k, n)]:
        shared: list[str] = []
        if query_features:
            row_features = corpus[index].get("features") or {}
            shared = [
                name
                for name in FEATURES
                if query_features.get(name) and row_features.get(name)
            ]
        results.append(
            {
                "project_id": corpus[index].get("project_id"),
                "score": round(float(min(1.0, max(0.0, combined[index]))), 4),
                "actual_days": corpus[index].get("actual_days"),
                "shared_features": shared,
                "snippet": _snippet(texts[index]),
            }
        )
    return results
