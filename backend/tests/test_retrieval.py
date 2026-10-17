"""Tests for the D18 change-retrieval spike (lexical path; no network, no model).

Fixtures build a tiny deterministic git repo in ``tmp_path`` (git on PATH — the
suite already depends on it in ``test_codebase.py``).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.services.retrieval import (
    RetrievalIndex,
    build_commit_docs,
    chunk_code,
    tokenize,
)

FIXTURE_DATE = "2026-01-15T10:00:00+00:00"


def _git(repo: Path, *args: str, date: str = FIXTURE_DATE) -> str:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        }
    )
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout


def _commit(repo: Path, message: str, date: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, date=date)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> dict:
    repo = tmp_path / "fixture"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")

    (repo / "payments.py").write_text(
        '"""Payment provider registry."""\n\n'
        "def add_payment_provider(name):\n"
        "    return {'provider': name}\n\n"
        "def list_providers():\n"
        "    return []\n",
        encoding="utf-8",
    )
    sha1 = _commit(repo, "feat: add payment provider registry", "2026-01-01T10:00:00+00:00")

    (repo / "auth.py").write_text(
        '"""Auth helpers."""\n\n'
        "def login_redirect(next_url):\n"
        "    return next_url\n",
        encoding="utf-8",
    )
    sha2 = _commit(repo, "fix: login redirect bug", "2026-02-01T10:00:00+00:00")

    (repo / "payments.py").write_text(
        (repo / "payments.py").read_text(encoding="utf-8")
        + "\ndef webhook_retry(payload):\n    return payload\n",
        encoding="utf-8",
    )
    sha3 = _commit(repo, "feat: payment provider webhook retries", "2026-03-01T10:00:00+00:00")

    # Noise that must never be indexed.
    vendor = repo / "node_modules" / "lib"
    vendor.mkdir(parents=True)
    (vendor / "payment_helpers.py").write_text("def add_payment(): pass\n", encoding="utf-8")

    return {"repo": repo, "shas": (sha1, sha2, sha3)}


def test_tokenize_splits_identifiers() -> None:
    tokens = tokenize("find_similar_changes")
    assert "find" in tokens and "similar" in tokens and "changes" in tokens
    camel = tokenize("getUserName")
    assert "get" in camel and "user" in camel and "name" in camel


def test_chunk_code_finds_file_and_function_chunks(fixture_repo: dict) -> None:
    chunks = chunk_code(fixture_repo["repo"])
    pairs = {(c.path, c.kind, c.name) for c in chunks}
    assert ("payments.py", "file", "payments.py") in pairs
    assert ("payments.py", "function", "add_payment_provider") in pairs
    assert ("payments.py", "function", "webhook_retry") in pairs


def test_chunk_code_skips_ignored_and_vendor_dirs(fixture_repo: dict) -> None:
    chunks = chunk_code(fixture_repo["repo"])
    assert all("node_modules" not in c.path for c in chunks)


def test_commit_docs_read_history_with_files(fixture_repo: dict) -> None:
    docs = build_commit_docs(fixture_repo["repo"])
    assert len(docs) == 3
    by_sha = {d["sha"]: d for d in docs}
    assert by_sha[fixture_repo["shas"][0]]["files"] == ["payments.py"]
    assert by_sha[fixture_repo["shas"][2]]["files_touched"] == 1


def test_commit_docs_at_date_is_leakage_guarded(fixture_repo: dict) -> None:
    docs = build_commit_docs(fixture_repo["repo"], at_date="2026-02-15")
    dates = sorted(d["date"] for d in docs)
    assert dates == ["2026-01-01", "2026-02-01"]  # 2026-03-01 must not appear


def test_commit_docs_rejects_non_git_dir(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(RuntimeError):
        build_commit_docs(plain)


def test_locate_files_prefers_relevant_module(fixture_repo: dict) -> None:
    index = RetrievalIndex(
        chunks=chunk_code(fixture_repo["repo"]),
        commits=build_commit_docs(fixture_repo["repo"]),
    )
    assert index.mode == "lexical"
    files = index.locate_files("add a payment provider integration", k=3)
    assert files, "expected at least one file"
    assert files[0]["path"] == "payments.py"


def test_search_commits_respects_before_filter(fixture_repo: dict) -> None:
    index = RetrievalIndex(
        chunks=chunk_code(fixture_repo["repo"]),
        commits=build_commit_docs(fixture_repo["repo"]),
    )
    hits = index.search_commits("payment provider", k=5, before="2026-03-01")
    assert hits, "expected earlier commits"
    assert all(h["date"] < "2026-03-01" for h in hits)
    assert hits[0]["sha"] == fixture_repo["shas"][0]


def test_locate_returns_mode_files_and_commits(fixture_repo: dict) -> None:
    root = fixture_repo["repo"]
    index = RetrievalIndex(
        chunks=chunk_code(root),
        commits=build_commit_docs(root),
    )
    result = index.locate("payment provider webhook")
    assert result["mode"] == "lexical"
    assert result["files"]
    assert result["commits"]
    assert result["commit_files"]


def test_empty_query_returns_empty(fixture_repo: dict) -> None:
    index = RetrievalIndex(
        chunks=chunk_code(fixture_repo["repo"]),
        commits=build_commit_docs(fixture_repo["repo"]),
    )
    assert index.locate_files("   ", k=5) == []
    assert index.search_commits("", k=5) == []
