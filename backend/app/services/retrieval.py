"""Change retrieval for Codebase Lab (docs/DECISIONS.md D18 — evaluation spike).

Answers the two questions the structural friction signals cannot: "which files
of THIS repo does a request likely touch?" (code locate) and "have similar
changes happened before, and what did they touch?" (analog commits).

Design decisions (D18):
* Lexical core reuses the house recipe from ``similarity.py``: BM25 (rank-bm25)
  + TF-IDF cosine, each min-max normalized before combining.
* Semantic embeddings are OPTIONAL and lazy: ``fastembed`` (ONNX, no torch —
  D3 stays intact) is imported on first use; when unavailable the hybrid
  silently runs lexical-only, and callers can report which mode was used.
* Leakage guard: analog commits are filtered to strictly-before a date, with a
  Python-side date re-check (same discipline as ``codebase.py``).
* NOTHING in the live pipeline imports this module yet: the recall@k gate in
  ``scripts/retrieval_eval.py`` comes first (D18).

Spike scope: file + function chunks, commit-subject documents, deterministic
ordering everywhere (ties break on path/sha), no network at query time when
embeddings are disabled.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_EXTS: frozenset[str] = frozenset(
    {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
        ".md", ".txt", ".sql", ".yml", ".yaml", ".toml", ".ini", ".cfg",
        ".html", ".css", ".scss", ".sh", ".ps1", ".json",
    }
)
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git", "node_modules", ".venv", "venv", "__pycache__", ".next",
        "out", "dist", "build", ".pytest_cache", ".mypy_cache", "vendor",
    }
)
MAX_FILE_BYTES = 200_000
MAX_CHUNK_CHARS = 6_000
#: Score weights: BM25 / TF-IDF / embedding, renormalized per mode.
WEIGHTS_LEXICAL = {"bm25": 0.6, "tfidf": 0.4}
WEIGHTS_HYBRID = {"bm25": 0.35, "tfidf": 0.25, "emb": 0.40}

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"

STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been
    before being below between both but by can cannot could did do does doing don't
    down during each few for from further had has have having he her here hers him
    himself his how i if in into is it its itself just me more most must my myself
    no nor not now of off on once only or other our ours out over own same she
    should so some such than that the their theirs them themselves then there these
    they this those through to too under until up very was we were what when where
    which while who whom why will with won't would you your yours also via use using
    used make makes made new fix fixed fixes add adds added update updates updated
    support supports""".split()
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _run_git(repo: Path, args: Sequence[str], timeout: float = 300.0) -> str:
    """Run git for ``repo``; pinned env so it stays offline/deterministic."""
    env = dict(os.environ)
    env.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_LAZY_FETCH": "1",
            "LC_ALL": "C",
        }
    )
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()}")
    return proc.stdout


def _require_git_repo(repo: Path) -> None:
    if not (repo / ".git").exists():
        raise RuntimeError(f"{repo} is not a git repository (no .git)")


# --------------------------------------------------------------------------- #
# Tokenization (shared by BM25, TF-IDF and message matching)
# --------------------------------------------------------------------------- #


def tokenize(text: str, *, drop_stopwords: bool = False) -> list[str]:
    """Code-aware tokens: split snake_case and camelCase into sub-tokens.

    ``find_similar_changes`` yields find, similar, changes — so a message
    saying "similar changes" can match the identifier. The unsplit token is
    kept as well.
    """
    out: list[str] = []
    for match in _TOKEN_RE.finditer(text or ""):
        raw = match.group(0)
        lowered = raw.lower()
        out.append(lowered)
        for piece in _CAMEL_SPLIT_RE.split(raw):
            for part in piece.split("_"):
                part_low = part.lower()
                if part_low and part_low != lowered:
                    out.append(part_low)
    if drop_stopwords:
        out = [t for t in out if t not in STOPWORDS and len(t) >= 2]
    return out


# --------------------------------------------------------------------------- #
# Code chunking
# --------------------------------------------------------------------------- #


@dataclass
class CodeChunk:
    """One retrievable unit of code: a file head or a top-level definition."""

    path: str
    kind: str  # "file" | "function" | "class"
    name: str
    text: str
    lexical: str = field(default="")  # path-boosted token stream for BM25/TF-IDF

    def __post_init__(self) -> None:
        if not self.lexical:
            path_words = self.path.replace("/", " ").replace("\\", " ").replace(".", " ")
            boost = " ".join([path_words, path_words, self.name, self.name])
            self.lexical = boost + "\n" + self.text


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _tracked_files(repo: Path) -> list[str]:
    out = _run_git(repo, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    return [p for p in out.split("\0") if p]


def chunk_code(repo: str | Path, *, max_file_bytes: int = MAX_FILE_BYTES) -> list[CodeChunk]:
    """Deterministic file/function chunks for every tracked text file."""
    root = Path(repo).expanduser()
    _require_git_repo(root)
    chunks: list[CodeChunk] = []
    for rel in sorted(_tracked_files(root)):
        rel_norm = rel.replace("\\", "/")
        parts = rel_norm.split("/")
        if any(part in SKIP_DIRS for part in parts[:-1]):
            continue
        suffix = Path(rel_norm).suffix.lower()
        if suffix not in DEFAULT_EXTS:
            continue
        full = root / rel_norm
        try:
            if full.stat().st_size > max_file_bytes:
                continue
        except OSError:
            continue
        text = _read_text(full)
        if not text.strip():
            continue
        file_text = text[:MAX_CHUNK_CHARS]
        chunks.append(CodeChunk(path=rel_norm, kind="file", name=Path(rel_norm).name, text=file_text))
        if suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                segment = ast.get_source_segment(text, node) or ""
                if not segment.strip():
                    continue
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                chunks.append(
                    CodeChunk(
                        path=rel_norm,
                        kind=kind,
                        name=node.name,
                        text=segment[:MAX_CHUNK_CHARS],
                    )
                )
    return chunks


# --------------------------------------------------------------------------- #
# Commit history documents
# --------------------------------------------------------------------------- #


def build_commit_docs(repo: str | Path, *, at_date: str | None = None) -> list[dict[str, Any]]:
    """One document per commit: ``{sha, date, subject, files, files_touched}``.

    Only commits strictly before ``at_date`` (when given) — leakage guard with
    a Python-side date re-check, mirroring ``codebase.py``.
    """
    root = Path(repo).expanduser()
    _require_git_repo(root)
    args = ["log", "--date=short", "--format=\x01%H\t%ad\t%s", "--name-only"]
    if at_date:
        args.append(f"--until={str(at_date)[:10]}T00:00:00")
    out = _run_git(root, args)
    docs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in out.splitlines():
        if line.startswith("\x01"):
            if current is not None:
                docs.append(current)
            parts = line[1:].split("\t", 2)
            if len(parts) < 3:
                current = None
                continue
            sha, day, subject = parts
            if at_date and day[:10] >= str(at_date)[:10]:
                current = None  # python-side leakage re-check
                continue
            current = {"sha": sha, "date": day, "subject": subject, "files": []}
        elif line.strip() and current is not None:
            current["files"].append(line.strip())
    if current is not None:
        docs.append(current)
    for doc in docs:
        doc["files_touched"] = len(doc["files"])
    return docs


# --------------------------------------------------------------------------- #
# Embeddings (optional, lazy)
# --------------------------------------------------------------------------- #

_model_cache: dict[str, Any] = {}
_model_failed = False


def embeddings_available() -> bool:
    """True when fastembed imports cleanly (model download happens on first embed)."""
    global _model_failed
    if _model_failed:
        return False
    try:
        import fastembed  # noqa: F401
    except Exception:
        _model_failed = True
        return False
    return True


def _get_model(model_name: str | None = None) -> Any:
    name = model_name or EMBED_MODEL_NAME
    if name not in _model_cache:
        from fastembed import TextEmbedding

        _model_cache[name] = TextEmbedding(model_name=name)
    return _model_cache[name]


def _embed_texts(texts: Sequence[str], model_name: str | None = None) -> np.ndarray:
    """L2-normalized float32 embedding matrix (rows)."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    model = _get_model(model_name)
    vectors = np.asarray(list(model.embed(list(texts))), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #


def _minmax(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return scores
    low, high = float(scores.min()), float(scores.max())
    if high - low < 1e-12:
        return np.zeros_like(scores)
    return (scores - low) / (high - low)


@dataclass
class RetrievalIndex:
    """Hybrid retrieval over code chunks and commit documents.

    ``mode`` reports the ranking actually used: ``"hybrid-emb"`` or ``"lexical"``.
    """

    chunks: list[CodeChunk]
    commits: list[dict[str, Any]]
    use_embeddings: bool = False
    embed_model: str | None = None

    _bm25: BM25Okapi = field(init=False, repr=False)
    _tfidf: TfidfVectorizer = field(init=False, repr=False)
    _tfidf_matrix: Any = field(init=False, repr=False)
    _emb_matrix: np.ndarray | None = field(init=False, default=None, repr=False)
    _bm25_commit: BM25Okapi = field(init=False, repr=False)
    _tfidf_commit: TfidfVectorizer = field(init=False, repr=False)
    _tfidf_commit_matrix: Any = field(init=False, repr=False)
    _emb_commit: np.ndarray | None = field(init=False, default=None, repr=False)
    mode: str = field(init=False, default="lexical")

    def __post_init__(self) -> None:
        chunk_tokens = [tokenize(c.lexical) for c in self.chunks]
        self._bm25 = BM25Okapi(chunk_tokens or [["_empty_"]])
        joined = [" ".join(tokenize(c.lexical)) for c in self.chunks] or ["_empty_"]
        self._tfidf = TfidfVectorizer(lowercase=False, token_pattern=r"\S+")
        self._tfidf_matrix = self._tfidf.fit_transform(joined)

        commit_texts = [self._commit_text(c) for c in self.commits] or ["_empty_"]
        self._bm25_commit = BM25Okapi([tokenize(t, drop_stopwords=True) for t in commit_texts])
        self._tfidf_commit = TfidfVectorizer(lowercase=False, token_pattern=r"\S+")
        self._tfidf_commit_matrix = self._tfidf_commit.fit_transform(
            [" ".join(tokenize(t, drop_stopwords=True)) for t in commit_texts]
        )

        if self.use_embeddings and embeddings_available():
            if self.chunks:
                self._emb_matrix = _embed_texts(
                    [c.lexical[:MAX_CHUNK_CHARS] for c in self.chunks], self.embed_model
                )
            if self.commits:
                self._emb_commit = _embed_texts(
                    [self._commit_text(c) for c in self.commits], self.embed_model
                )
            if self.chunks or self.commits:
                self.mode = "hybrid-emb"

    @staticmethod
    def _commit_text(commit: dict[str, Any]) -> str:
        return str(commit.get("subject") or "")

    # -- code -----------------------------------------------------------------

    def _chunk_scores(self, query: str) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        tokens = tokenize(query)
        bm25 = np.asarray(self._bm25.get_scores(tokens), dtype=np.float64)
        q_vec = self._tfidf.transform([" ".join(tokens)])
        tfidf = np.asarray(
            cosine_similarity(q_vec, self._tfidf_matrix).ravel(), dtype=np.float64
        )
        parts = {"bm25": _minmax(bm25), "tfidf": _minmax(tfidf)}
        if self._emb_matrix is not None:
            q_emb = _embed_texts([query], self.embed_model)[0]
            parts["emb"] = _minmax(np.asarray(self._emb_matrix @ q_emb, dtype=np.float64))
            weights = WEIGHTS_HYBRID
        else:
            weights = WEIGHTS_LEXICAL
        total = sum(weights[key] * parts[key] for key in weights)
        return total, parts

    def search_code(self, query: str, k: int = 10) -> list[dict[str, Any]]:
        """Top-k chunks (dedup not applied — use ``locate`` for file ranking)."""
        if not self.chunks or k <= 0 or not (query or "").strip():
            return []
        scores, _ = self._chunk_scores(query)
        order = np.argsort(-scores, kind="stable")[:k]
        results = []
        for i in order:
            chunk = self.chunks[int(i)]
            results.append(
                {
                    "path": chunk.path,
                    "kind": chunk.kind,
                    "name": chunk.name,
                    "score": round(float(scores[int(i)]), 4),
                }
            )
        return results

    def locate_files(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Top-k FILES: best chunk score per path, deterministic tie-break."""
        if not self.chunks or k <= 0 or not (query or "").strip():
            return []
        scores, _ = self._chunk_scores(query)
        best: dict[str, dict[str, Any]] = {}
        for idx, chunk in enumerate(self.chunks):
            entry = best.get(chunk.path)
            score = float(scores[idx])
            if entry is None or score > entry["score"]:
                best[chunk.path] = {
                    "path": chunk.path,
                    "score": score,
                    "matched": f"{chunk.kind}:{chunk.name}",
                }
        ranked = sorted(best.values(), key=lambda e: (-e["score"], e["path"]))[:k]
        for entry in ranked:
            entry["score"] = round(entry["score"], 4)
        return ranked

    # -- commits ----------------------------------------------------------------

    def search_commits(
        self, query: str, k: int = 5, *, before: str | None = None
    ) -> list[dict[str, Any]]:
        """Top-k analog commits by subject similarity (leakage-guarded date filter)."""
        if not self.commits or k <= 0 or not (query or "").strip():
            return []
        tokens = tokenize(query, drop_stopwords=True)
        bm25 = np.asarray(self._bm25_commit.get_scores(tokens), dtype=np.float64)
        q_vec = self._tfidf_commit.transform([" ".join(tokens)])
        tfidf = np.asarray(
            cosine_similarity(q_vec, self._tfidf_commit_matrix).ravel(), dtype=np.float64
        )
        parts = {"bm25": _minmax(bm25), "tfidf": _minmax(tfidf)}
        if self._emb_commit is not None:
            q_emb = _embed_texts([query], self.embed_model)[0]
            parts["emb"] = _minmax(np.asarray(self._emb_commit @ q_emb, dtype=np.float64))
            weights = WEIGHTS_HYBRID
        else:
            weights = WEIGHTS_LEXICAL
        total = sum(weights[key] * parts[key] for key in weights)

        candidates = []
        for idx, commit in enumerate(self.commits):
            if before is not None and commit.get("date", "") >= str(before)[:10]:
                continue
            candidates.append((float(total[idx]), commit))
        candidates.sort(key=lambda pair: (-pair[0], pair[1].get("sha", "")))
        out = []
        for score, commit in candidates[:k]:
            out.append(
                {
                    "sha": commit.get("sha"),
                    "date": commit.get("date"),
                    "subject": commit.get("subject"),
                    "files_touched": commit.get("files_touched"),
                    "files": list(commit.get("files") or [])[:10],
                    "score": round(score, 4),
                }
            )
        return out

    def locate(self, query: str, k_files: int = 5, k_commits: int = 3) -> dict[str, Any]:
        """One call: relevant files + analog commits + their touched-file union."""
        files = self.locate_files(query, k=k_files)
        commits = self.search_commits(query, k=k_commits)
        union: list[str] = []
        for commit in commits:
            for path in commit.get("files") or []:
                if path not in union:
                    union.append(path)
        return {"mode": self.mode, "files": files, "commits": commits, "commit_files": union}


def build_index(repo: str | Path, *, use_embeddings: bool = False) -> RetrievalIndex:
    """Convenience builder: chunk code + read history + fit the index."""
    root = Path(repo).expanduser()
    return RetrievalIndex(
        chunks=chunk_code(root),
        commits=build_commit_docs(root),
        use_embeddings=use_embeddings,
    )
