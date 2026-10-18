#!/usr/bin/env python
"""Fetch the Codebase Lab example repositories (build-time or local dev).

The examples are **ordinary public repos**, cloned once into
``data/example_repos/`` (gitignored) and analysed by the **same live path** as a
pasted repo — nothing is precomputed, so an example shows the product's real
numbers, not canned ones. They exist so a visitor can click an example and get a
result **instantly**, with no clone at request time and no URL to paste.

Run it at Docker build time (see ``backend/Dockerfile``) and locally:

    python scripts/fetch_example_repos.py                 # all missing examples
    python scripts/fetch_example_repos.py --only ex_flask  # one
    python scripts/fetch_example_repos.py --force          # re-clone everything

It writes ``data/example_repos/examples.json``: for each example the resolved
commit hash and the fetch date. The date is used to pin the analysis (churn
window, leakage guard) so repeated requests return identical friction instead of
drifting as the calendar moves.

Honest scope note: the ``kind``/``domain`` labels describe what each *library*
is for (a payments SDK, a FHIR client, a web framework). They are a codebase
sample, **not** a validated client project — the product's domain limitation
(OSS != B2B SaaS) is unchanged.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.api.state import (  # noqa: E402
    CODEBASE_EXAMPLE_REPOS,
    example_repos_dir,
    example_repo_path,
)

GIT_TIMEOUT_SECONDS = 300.0
MANIFEST_NAME = "examples.json"


def _git(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def fetch_one(example_id: str, force: bool = False) -> dict:
    """Clone one example if needed and return its manifest entry."""
    entry = CODEBASE_EXAMPLE_REPOS[example_id]
    target = example_repo_path(example_id)
    if force and target.exists():
        import shutil

        shutil.rmtree(target, ignore_errors=True)
    if not (target / ".git").exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{entry['repo']}.git"
        print(f"[fetch] {example_id}: cloning {entry['repo']} ...", flush=True)
        proc = subprocess.run(
            [
                "git",
                "-c",
                "http.https://github.com/.extraheader=",
                "clone",
                "--quiet",
                "--single-branch",
                "--no-recurse-submodules",
                url,
                str(target),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0 or not (target / ".git").exists():
            raise RuntimeError(
                f"clone failed for {entry['repo']}: {(proc.stderr or proc.stdout).strip()[:200]}"
            )
    commit = _git(target, ["rev-parse", "HEAD"])
    head_date = _git(target, ["log", "-1", "--format=%cI"])[:10]
    return {
        "id": example_id,
        **entry,
        "commit": commit,
        "fetched_at": datetime.now(timezone.utc).date().isoformat(),
        "pinned_date": head_date,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", default=[], help="example id (repeatable)")
    parser.add_argument("--force", action="store_true", help="re-clone even when present")
    args = parser.parse_args(argv)

    ids = args.only or list(CODEBASE_EXAMPLE_REPOS)
    unknown = [i for i in ids if i not in CODEBASE_EXAMPLE_REPOS]
    if unknown:
        print(f"error: unknown example id(s): {unknown}")
        print(f"known: {sorted(CODEBASE_EXAMPLE_REPOS)}")
        return 2

    manifest_path = example_repos_dir() / MANIFEST_NAME
    manifest: dict[str, dict] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    # Drop entries whose example left the registry (e.g. the non-Python ones
    # removed when the scope became Python-only, D24).
    manifest = {key: value for key, value in manifest.items() if key in CODEBASE_EXAMPLE_REPOS}

    failures = 0
    for example_id in ids:
        try:
            manifest[example_id] = fetch_one(example_id, force=args.force)
            entry = manifest[example_id]
            print(
                f"[ok] {example_id:<14} {entry['repo']:<28} {entry['commit'][:8]} "
                f"pinned={entry['pinned_date']}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"[fail] {example_id}: {exc}", flush=True)

    if manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nwrote {manifest_path} ({len(manifest)} entries)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
