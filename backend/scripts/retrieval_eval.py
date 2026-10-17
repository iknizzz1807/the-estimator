"""Evaluation harness for the D18 change-retrieval spike (no claims without it).

Two leakage-aware probes on real git history (design mirrors
``scripts/codebase_history_experiment.py`` conventions):

1. **Analog-commit retrieval** (leakage-clean, the primary gate):
   for the newest 40% of commits, query = the commit subject (available BEFORE
   the change), gold = the files that commit actually touched. Retrieval ranks
   *earlier* commits only (strictly-before date filter, re-checked in Python);
   recall@k is computed over the UNION of the retrieved commits' touched files.

2. **Code-locate retrieval** (labelled biased proxy): rebuild nothing — rank
   chunks of the CURRENT working tree. Honest caveat: the target commit's own
   code is present in the tree, so this probe reports an upper-ish bound; it is
   kept because it mirrors the production query (request -> current codebase).

Variants: lexical (BM25 + TF-IDF, house recipe) and hybrid with fastembed
embeddings when installed (``--no-embed`` forces lexical).

Usage (from ``backend/``, git on PATH)::

    python scripts/retrieval_eval.py --repo <path> [--repo <path> ...]
        [--target-fraction 0.4] [--limit-targets N] [--no-embed] [--out file.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Allow `python scripts/retrieval_eval.py` from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.retrieval import (  # noqa: E402
    RetrievalIndex,
    build_commit_docs,
    chunk_code,
    embeddings_available,
    tokenize,
)

KS = (5, 10)


def _targets_for(docs: list[dict], fraction: float, limit: int | None) -> list[dict]:
    """Newest ``fraction`` of commits with a usable subject and touched files.

    ``docs`` is newest-first (git log order). Targets must be able to look back
    at strictly-earlier commits, so the oldest ~10 commits are excluded from
    targets by construction of the split.
    """
    cut = max(1, int(len(docs) * fraction))
    targets = []
    for doc in docs[:cut]:  # newest first
        if not doc.get("files"):
            continue
        tokens = tokenize(doc.get("subject") or "", drop_stopwords=True)
        if len(tokens) < 2:
            continue
        targets.append(doc)
    targets = targets[: limit] if limit else targets
    return targets


def _eval_analog(index: RetrievalIndex, targets: list[dict], k_max: int) -> dict:
    hits_at = {k: 0 for k in KS}
    recall_at = {k: 0.0 for k in KS}
    counted = 0
    started = time.time()
    for target in targets:
        gold = set(target["files"])
        if not gold:
            continue
        hits = index.search_commits(target["subject"], k=k_max, before=target["date"])
        union: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            union.update(hit.get("files") or [])
            if rank in KS:
                inter = len(gold & union)
                if inter:
                    hits_at[rank] += 1
                recall_at[rank] += inter / len(gold)
        counted += 1
    elapsed = time.time() - started
    return {
        "n_targets": counted,
        "hit@5": round(hits_at[5] / counted, 4) if counted else None,
        "hit@10": round(hits_at[10] / counted, 4) if counted else None,
        "recall@5": round(recall_at[5] / counted, 4) if counted else None,
        "recall@10": round(recall_at[10] / counted, 4) if counted else None,
        "seconds": round(elapsed, 1),
    }


def _eval_locate(index: RetrievalIndex, targets: list[dict], repo: Path, k_max: int) -> dict:
    hits_at = {k: 0 for k in KS}
    recall_at = {k: 0.0 for k in KS}
    mrr_sum = 0.0
    counted = 0
    skipped_no_file = 0
    started = time.time()
    for target in targets:
        gold = {f for f in target["files"] if (repo / f).exists()}
        if not gold:
            skipped_no_file += 1
            continue
        ranked = index.locate_files(target["subject"], k=k_max)
        order = [entry["path"] for entry in ranked]
        for rank, path in enumerate(order, start=1):
            if rank in KS:
                inter = len(gold & set(order[:rank]))
                if inter:
                    hits_at[rank] += 1
                recall_at[rank] += inter / len(gold)
        for rank, path in enumerate(order, start=1):
            if path in gold:
                mrr_sum += 1.0 / rank
                break
        counted += 1
    elapsed = time.time() - started
    return {
        "n_targets": counted,
        "skipped_no_existing_gold": skipped_no_file,
        "hit@5": round(hits_at[5] / counted, 4) if counted else None,
        "hit@10": round(hits_at[10] / counted, 4) if counted else None,
        "recall@5": round(recall_at[5] / counted, 4) if counted else None,
        "recall@10": round(recall_at[10] / counted, 4) if counted else None,
        "mrr": round(mrr_sum / counted, 4) if counted else None,
        "seconds": round(elapsed, 1),
    }


def evaluate_repo(repo: Path, fraction: float, limit: int | None, use_embed: bool) -> dict:
    print(f"\n=== repo: {repo} ===", flush=True)
    docs = build_commit_docs(repo)
    targets = _targets_for(docs, fraction, limit)
    print(f"commits: {len(docs)} | targets evaluated: {len(targets)}", flush=True)
    result: dict = {"repo": str(repo), "n_commits": len(docs), "n_targets": len(targets)}

    # --- probe 1: analog commits (message -> earlier commits -> files) ---------
    message_index_lex = RetrievalIndex(chunks=[], commits=docs, use_embeddings=False)
    result["analog_lexical"] = _eval_analog(message_index_lex, targets, max(KS))
    print("  analog-commit recall (lexical):", result["analog_lexical"], flush=True)

    if use_embed and embeddings_available():
        try:
            t0 = time.time()
            message_index_emb = RetrievalIndex(chunks=[], commits=docs, use_embeddings=True)
            print(f"  [embeddings for {len(docs)} commit docs: {time.time()-t0:.1f}s]", flush=True)
            result["analog_hybrid_emb"] = _eval_analog(message_index_emb, targets, max(KS))
            print("  analog-commit recall (hybrid+emb):", result["analog_hybrid_emb"], flush=True)
        except Exception as exc:  # keep the run lexical-only, report honestly
            print(f"  [embeddings failed: {exc!r} - lexical-only for this probe]", flush=True)
            result["embeddings_error"] = str(exc)[:300]

    # --- probe 2: code locate on the current tree (biased proxy, see module) ---
    chunks = chunk_code(repo)
    code_index_lex = RetrievalIndex(chunks=chunks, commits=[], use_embeddings=False)
    result["locate_lexical_current_tree"] = _eval_locate(code_index_lex, targets, repo, max(KS))
    print(f"  code-locate ({len(chunks)} chunks, lexical, current-tree proxy):",
          result["locate_lexical_current_tree"], flush=True)

    if use_embed and embeddings_available():
        try:
            t0 = time.time()
            code_index_emb = RetrievalIndex(chunks=chunks, commits=[], use_embeddings=True)
            print(f"  [embeddings for {len(chunks)} chunks: {time.time()-t0:.1f}s]", flush=True)
            result["locate_hybrid_emb_current_tree"] = _eval_locate(code_index_emb, targets, repo, max(KS))
            print("  code-locate (hybrid+emb, current-tree proxy):",
                  result["locate_hybrid_emb_current_tree"], flush=True)
        except Exception as exc:  # keep the run lexical-only, report honestly
            print(f"  [embeddings failed: {exc!r} - lexical-only for this probe]", flush=True)
            result["embeddings_error_locate"] = str(exc)[:300]

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", action="append", required=True, help="repository path (repeatable)")
    parser.add_argument("--target-fraction", type=float, default=0.4)
    parser.add_argument("--limit-targets", type=int, default=None)
    parser.add_argument("--no-embed", action="store_true", help="force lexical-only")
    parser.add_argument("--out", type=Path, default=None, help="write JSON report here")
    args = parser.parse_args(argv)

    use_embed = not args.no_embed
    if use_embed and not embeddings_available():
        print("fastembed not installed - lexical-only run", flush=True)
        use_embed = False

    reports = []
    for repo_arg in args.repo:
        repo = Path(repo_arg).expanduser()
        if not (repo / ".git").exists():
            print(f"skip (not a git repo): {repo}", flush=True)
            continue
        reports.append(evaluate_repo(repo, args.target_fraction, args.limit_targets, use_embed))

    if args.out and reports:
        args.out.write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(f"\nreport written: {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
