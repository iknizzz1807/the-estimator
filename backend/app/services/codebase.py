"""Codebase Lab analyzer: structural friction + invasiveness from real git history.

Why this module exists: the estimator (:mod:`app.services.estimation`) is blind to
the repository where the work will happen. The same requirement costs 3-5 days on
a plugin-pattern repo, and 15-25 days on a spaghetti repo where
``if provider == "stripe"`` is hardcoded across many files. This module makes the
codebase a first-class input to the estimate, from three mechanisms:

1. **Similar past changes** (:func:`find_similar_changes`): commits whose touched
   paths match keywords, summarized as real patch shapes (new vs modified files,
   added/removed lines).
2. **Structural friction** (:func:`collect_signals` + :func:`compute_friction`):
   churn before the estimate date, fan-in of Python imports, radon cyclomatic
   complexity, test-coverage gap (``coverage.xml``) and author concentration.
3. **Invasiveness** (:func:`estimate_invasiveness`): multiplicative expected
   patch shape derived from those similar commits, applied by
   :func:`apply_friction`.

Honesty rules baked into this module (they are what makes it credible):

* Signals are **leading indicators**, not proof of future effort.
* **Leakage guard**: churn counts and similar commits use history strictly
  BEFORE ``at_date`` (git ``--until`` plus a Python-side date re-check; the
  churn window itself starts 6 calendar months before ``at_date``).
* Friction only **widens the prediction interval** (it means "harder to
  predict"); it never moves the median. Invasiveness is the multiplicative P50
  factor.
* The coefficients used by :func:`apply_friction` are **DEMO-ASSUMED**
  placeholders (see :data:`ASSUMPTION_NOTE`); production learns them from
  realised actuals.
* Coverage is read from ``coverage.xml`` when present; when absent the signal is
  ``"unknown"`` (never faked) and is omitted from the weighted friction sum
  (remaining weights are renormalised).

Everything is pure, offline and deterministic given the repo + ``at_date``. All
git calls are read-only (``log`` / ``ls-files`` / ``rev-parse``): the analyzed
repository is never mutated.
"""

from __future__ import annotations

import calendar
import json
import math
import os
import re
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = [
    "ASSUMPTION_NOTE",
    "apply_friction",
    "collect_signals",
    "compute_friction",
    "estimate_invasiveness",
    "find_similar_changes",
]

# --------------------------------------------------------------------------- #
# Documented formula constants (see compute_friction / apply_friction)
# --------------------------------------------------------------------------- #

#: Relative weights of the friction components. They sum to 1.0; when the
#: coverage signal is unknown its weight is dropped and the rest renormalised.
FRICTION_WEIGHTS: dict[str, float] = {
    "churn": 0.30,
    "fan_in": 0.15,
    "complexity": 0.30,
    "coverage_gap": 0.10,
    "author_concentration": 0.15,
}

#: Saturating normalisers: component = min(1, raw / saturation).
CHURN_SATURATION_COMMITS = 20  # commits to one file in the 6-month window
FAN_IN_SATURATION = 8  # files importing one module
COMPLEXITY_SATURATION = 20  # radon max cyclomatic complexity (rank C+)

#: Level thresholds on the weighted score (low < 1/3 <= medium < 2/3 <= high).
LEVEL_MEDIUM_THRESHOLD = 1.0 / 3.0
LEVEL_HIGH_THRESHOLD = 2.0 / 3.0

#: Churn window length and hot-file output cap.
CHURN_WINDOW_MONTHS = 6
TOP_HOT_FILES = 15

#: Files need at least this many commits to contribute an author-concentration
#: signal (a single-touch file says nothing about bus factor).
MIN_FILE_COMMITS_FOR_AUTHOR_SIGNAL = 2

# --- DEMO-ASSUMED coefficients of apply_friction (learned in production) ---- #
FRICTION_P10_WIDENING = 0.30  # p10 x (1 - 0.30 * friction_score)
FRICTION_P90_WIDENING = 0.60  # p90 x (1 + 0.60 * friction_score)
INVASIVENESS_P50_SHIFT = 0.35  # p50 x (1 + 0.35 * modified_ratio)
P10_FACTOR_FLOOR = 0.55  # sane cap: never shrink p10 below 55% of itself
P90_FACTOR_CAP = 1.90  # sane cap on the upper-tail widening
P50_FACTOR_CAP = 1.50  # sane cap on the invasiveness shift
MIN_ADJUSTED_DAYS = 3.0  # same floor as the estimator contract

#: Surfaced verbatim in every :func:`apply_friction` result.
ASSUMPTION_NOTE = (
    "DEMO-ASSUMED coefficients: friction widens the interval "
    "(p10 x (1 - 0.30 * score), p90 x (1 + 0.60 * score)) and invasiveness "
    "shifts the median (p50 x (1 + 0.35 * modified_ratio)). These are "
    "placeholders for the demo; in production they are learned from realised "
    "actuals (predicted vs delivered) instead of assumed."
)

# --------------------------------------------------------------------------- #
# Low-level git helpers (read-only, never mutate the analyzed repo)
# --------------------------------------------------------------------------- #

_HEADER = "%x01%H%x09%an%x09%cd%x09%s"  # \x01 + hash, author, committer date, subject
_RAW_LINE_RE = re.compile(r"^:(\d+) (\d+) ([0-9a-f]+) ([0-9a-f]+) ([A-Z]\d*)\t(.*)$")
_NUMSTAT_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t(.*)$")


def _git_env() -> dict[str, str]:
    """Environment that keeps git read-only, locale-stable and pager-free."""
    env = dict(os.environ)
    env.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return env


def _git(repo: Path, args: Sequence[str], timeout: float = 120.0) -> str:
    """Run a read-only git command; return stdout ("" on any failure).

    On FUSE filesystems (Android / sdcard under PRoot) a repo may be owned by a
    different uid than the current user; git then refuses with "dubious
    ownership". In that case the command is retried once with
    ``safe.directory`` pinned to THIS repo only (never a global ``*``).
    """
    try:
        resolved = str(repo.resolve())
    except OSError:
        resolved = str(repo)

    def run(extra: Sequence[str]) -> subprocess.CompletedProcess[str]:
        cmd = ["git", "-c", "core.quotepath=false", *extra, "-C", str(repo), *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=_git_env(),
        )

    try:
        proc = run(())
        if proc.returncode != 0 and "dubious ownership" in (proc.stderr or ""):
            proc = run(("-c", f"safe.directory={resolved}"))
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _require_git_repo(repo: Path) -> None:
    if not repo.is_dir():
        raise ValueError(f"not a directory: {repo}")
    if not _git(repo, ["rev-parse", "--git-dir"]).strip():
        raise ValueError(f"not a git repository: {repo}")


def _parse_at_date(at_date: str | None) -> date:
    """Parse ``YYYY-MM-DD`` (a full ISO timestamp is truncated); default: today UTC."""
    if at_date is None:
        return datetime.now(timezone.utc).date()
    try:
        return datetime.strptime(str(at_date)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"at_date must be YYYY-MM-DD, got {at_date!r}") from exc


def _months_before(day: date, months: int) -> date:
    """Calendar month arithmetic with day-of-month clamping (2026-03-31 - 1mo -> 2026-02-28)."""
    total = day.month - 1 - months
    year = day.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


# --------------------------------------------------------------------------- #
# Signal collection
# --------------------------------------------------------------------------- #


def _collect_churn(repo: Path, since: date, until: date) -> dict[str, Any]:
    """Per-file commit counts + authors in ``[since, until)``.

    Leakage guard: the git ``--until`` bound is re-checked in Python so a commit
    dated on/after ``at_date`` can never contribute, whatever git's boundary
    semantics are.
    """
    out = _git(
        repo,
        [
            "log",
            f"--since={since.isoformat()}T00:00:00",
            f"--until={until.isoformat()}T00:00:00",
            "--date=short",
            f"--format={_HEADER}",
            "--name-only",
        ],
    )
    files: dict[str, dict[str, Any]] = {}
    total_commits = 0
    current_author: str | None = None
    for line in out.splitlines():
        if line.startswith("\x01"):
            parts = line[1:].split("\t")
            if len(parts) < 3:
                current_author = None
                continue
            try:
                commit_day = datetime.strptime(parts[2][:10], "%Y-%m-%d").date()
            except ValueError:
                current_author = None
                continue
            if since <= commit_day < until:  # leakage guard (date re-check)
                total_commits += 1
                current_author = parts[1]
            else:
                current_author = None
        elif line.strip() and current_author is not None:
            entry = files.setdefault(line, {"commits": 0, "authors": set()})
            entry["commits"] += 1
            entry["authors"].add(current_author)
    return {"files": files, "total_commits": total_commits}


def _tracked_python_files(repo: Path) -> list[str]:
    """Repo-relative Python paths git would track (tracked + untracked, not ignored).

    Ignored/regenerated fixtures (e.g. ``data/demo_repos/``) and virtualenvs are
    therefore never scanned, which keeps signals stable and honest.
    """
    out = _git(
        repo,
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.py"],
    )
    return sorted(path for path in out.split("\x00") if path)


def _python_module(rel_path: str) -> str:
    """``payments/providers/stripe.py`` -> ``payments.providers.stripe``."""
    module = rel_path[: -len(".py")] if rel_path.endswith(".py") else rel_path
    module = module.replace("\\", "/").replace("/", ".")
    if module.endswith(".__init__"):
        module = module[: -len(".__init__")]
    return module


_IMPORT_RE = re.compile(r"^\s*import\s+([^\n#]+)", re.MULTILINE)
_FROM_RE = re.compile(r"^\s*from\s+([.\w]+)\s+import\s+([^\n#]+)", re.MULTILINE)


def _read_text(path: Path, max_bytes: int = 1_000_000) -> str:
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _import_names(raw: str) -> list[str]:
    """Split an import clause into bare names (drops parens, aliases, stars)."""
    names: list[str] = []
    for chunk in raw.replace("(", " ").replace(")", " ").split(","):
        name = chunk.strip().split(" as ")[0].strip()
        if name and name != "*" and name.isidentifier():
            names.append(name)
    return names


def _module_refs(file_module: str, text: str) -> set[str]:
    """Dotted module references made by one file (simple, documented regex scan).

    ``import a.b`` -> {a.b}; ``from a.b import c, d`` -> {a.b, a.b.c, a.b.d};
    relative imports are anchored at the file's own package.
    """
    refs: set[str] = set()
    for match in _IMPORT_RE.finditer(text):
        for raw in match.group(1).replace("(", " ").split(","):
            name = raw.strip().split(" as ")[0].strip()
            if name and all(part.isidentifier() for part in name.split(".")):
                refs.add(name)
    package_parts = file_module.split(".")[:-1]
    for match in _FROM_RE.finditer(text):
        raw_module = match.group(1)
        dots = len(raw_module) - len(raw_module.lstrip("."))
        module = raw_module[dots:]
        if dots:
            anchor = package_parts[: max(0, len(package_parts) - (dots - 1))]
            base = ".".join(anchor + ([module] if module else []))
        else:
            base = module
        if base:
            refs.add(base)
        for name in _import_names(match.group(2)):
            if base:
                refs.add(f"{base}.{name}")
    return refs


def _collect_fan_in(repo: Path, py_files: Sequence[str]) -> dict[str, int]:
    """For each Python file: how many OTHER files import its module.

    Import resolution heuristic: imports are written relative to some source
    root (repo root, ``backend/``, ``src/``, ...). A dotted reference R matches
    the module M of a target file when R is exactly M, or R is a dotted SUFFIX
    of M whose stripped leading directories are a prefix of the importing
    file's own directory -- i.e. the import is rootable at a directory the
    importer actually lives under. So ``from app.features import x`` inside
    ``backend/tests/...`` matches ``backend/app/features.py`` (rooted at
    ``backend/``) without inventing matches from unrelated trees.
    """
    module_to_paths: dict[str, list[str]] = {}
    for rel in py_files:
        module_to_paths.setdefault(_python_module(rel), []).append(rel)

    # suffix index: dotted suffix -> [(stripped leading dirs, target path)]
    suffix_index: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    for module, paths in module_to_paths.items():
        parts = module.split(".")
        for start in range(len(parts)):
            stripped = tuple(parts[:start])
            suffix = ".".join(parts[start:])
            for path in paths:
                suffix_index.setdefault(suffix, []).append((stripped, path))

    fan_in = {rel: 0 for rel in py_files}
    for rel in py_files:
        refs = _module_refs(_python_module(rel), _read_text(repo / rel))
        if not refs:
            continue
        importer_dir = tuple(rel.split("/")[:-1])
        counted: set[str] = set()
        for ref in refs:
            for stripped, target in suffix_index.get(ref, ()):
                if target == rel or target in counted:
                    continue
                if stripped and importer_dir[: len(stripped)] != stripped:
                    continue
                counted.add(target)
                fan_in[target] += 1
    return fan_in


def _run_radon(repo: Path, files: Sequence[str]) -> dict[str, Any] | None:
    """``radon cc -j`` via this interpreter; None when radon is unavailable/errors."""
    if not files:
        return {}
    cmd = [sys.executable, "-m", "radon", "cc", "-j", *files]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _collect_complexity(repo: Path, py_files: Sequence[str]) -> dict[str, Any]:
    """Per-file cyclomatic complexity aggregates from radon (batched for argv limits)."""
    per_file: dict[str, dict[str, float]] = {}
    scored_ok = True
    batch_size = 200
    for start in range(0, len(py_files), batch_size):
        batch = [
            rel for rel in py_files[start : start + batch_size] if (repo / rel).is_file()
        ]
        if not batch:
            continue
        data = _run_radon(repo, batch)
        if data is None:
            scored_ok = False
            continue
        for rel, blocks in data.items():
            values = [
                float(block["complexity"])
                for block in (blocks or [])
                if isinstance(block, dict) and isinstance(block.get("complexity"), (int, float))
            ]
            if values:
                per_file[rel] = {
                    "max": max(values),
                    "mean": round(statistics.fmean(values), 2),
                    "blocks": len(values),
                }
    if not per_file and not scored_ok:
        return {
            "status": "unknown",
            "files_scored": 0,
            "blocks": 0,
            "max_complexity": 0,
            "mean_complexity": None,
            "high_complexity_files": 0,
        }
    file_maxes = [entry["max"] for entry in per_file.values()]
    return {
        "status": "scored" if scored_ok else "partial",
        "files_scored": len(per_file),
        "blocks": int(sum(entry["blocks"] for entry in per_file.values())),
        "max_complexity": int(max(file_maxes)) if file_maxes else 0,
        "mean_complexity": round(statistics.fmean(file_maxes), 2) if file_maxes else None,
        "high_complexity_files": sum(1 for value in file_maxes if value >= 10),
        "per_file": per_file,
    }


def _collect_coverage(repo: Path) -> dict[str, Any]:
    """Parse ``coverage.xml`` at the repo root; ``"unknown"`` when it is missing."""
    path = repo / "coverage.xml"
    unknown: dict[str, Any] = {"status": "unknown", "line_rate": None, "per_file": {}}
    if not path.is_file():
        return unknown
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return unknown
    raw_rate = root.get("line-rate")
    line_rate: float | None = None
    if raw_rate not in (None, ""):
        try:
            line_rate = round(min(1.0, max(0.0, float(raw_rate))), 4)
        except ValueError:
            line_rate = None
    per_file: dict[str, float] = {}
    for element in root.iter("class"):
        filename = element.get("filename")
        raw = element.get("line-rate")
        if filename and raw not in (None, ""):
            try:
                per_file[filename] = round(min(1.0, max(0.0, float(raw))), 4)
            except ValueError:
                continue
    return {"status": "found", "line_rate": line_rate, "per_file": per_file}


def _percentile(values: Sequence[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(q * len(ordered)) - 1)
    return int(ordered[index])


def _author_concentration(files: Mapping[str, Mapping[str, Any]]) -> float:
    """Commit-weighted ``1 - distinct_authors/commits`` over files with >= 2 commits.

    One author on every commit to a hot file -> 1.0 (bus-factor risk); many
    authors evenly spread -> close to 0. Files with a single commit carry no
    signal and are excluded.
    """
    weighted: list[tuple[int, float]] = []
    for entry in files.values():
        commits = int(entry.get("commits") or 0)
        if commits >= MIN_FILE_COMMITS_FOR_AUTHOR_SIGNAL:
            concentration = 1.0 - len(entry.get("authors") or ()) / commits
            weighted.append((commits, max(0.0, concentration)))
    total_weight = sum(weight for weight, _ in weighted)
    if total_weight == 0:
        return 0.0
    return round(sum(w * c for w, c in weighted) / total_weight, 4)


def collect_signals(repo_path: str | Path, at_date: str | None = None) -> dict[str, Any]:
    """Collect structural signals from a git repo as of ``at_date`` (leakage-guarded).

    Signals returned (all JSON-serializable, deterministic given repo + date):

    * ``churn``: commits per file in the 6 calendar months BEFORE ``at_date``
      (``--since/--until`` + Python-side re-check; a commit dated on/after
      ``at_date`` can never contribute);
    * ``fan_in``: regex import scan over git-tracked ``*.py`` files -- how many
      files import each module;
    * ``complexity``: ``radon cc -j`` cyclomatic complexity, per-file max/mean;
    * ``coverage``: ``coverage.xml`` ``line-rate`` at the repo root, or
      ``"unknown"`` when no report exists (never faked);
    * ``authors``: distinct authors + commit-weighted concentration;
    * ``hot_files``: top ``TOP_HOT_FILES`` files by churn, with all of the above
      joined per file.

    The analyzer only ever runs read-only git commands; the repo is not mutated.
    """
    repo = Path(repo_path).expanduser()
    _require_git_repo(repo)
    at = _parse_at_date(at_date)
    since = _months_before(at, CHURN_WINDOW_MONTHS)

    churn = _collect_churn(repo, since, at)
    files: dict[str, dict[str, Any]] = churn["files"]
    py_files = _tracked_python_files(repo)
    fan_in = _collect_fan_in(repo, py_files)
    complexity = _collect_complexity(repo, py_files)
    coverage = _collect_coverage(repo)
    complexity_per_file: dict[str, Any] = complexity.pop("per_file", {})

    churn_values = [int(entry["commits"]) for entry in files.values()]
    author_counts = [len(entry["authors"]) for entry in files.values()]
    all_authors = {author for entry in files.values() for author in entry["authors"]}

    hot_files: list[dict[str, Any]] = []
    for rel, entry in sorted(
        files.items(), key=lambda item: (-int(item[1]["commits"]), item[0])
    )[:TOP_HOT_FILES]:
        complexity_entry = complexity_per_file.get(rel) or {}
        hot_files.append(
            {
                "path": rel,
                "commits": int(entry["commits"]),
                "distinct_authors": len(entry["authors"]),
                "authors": sorted(entry["authors"]),
                "fan_in": int(fan_in.get(rel, 0)),
                "complexity_max": (
                    int(complexity_entry["max"]) if complexity_entry else None
                ),
                "complexity_mean": complexity_entry.get("mean"),
                "coverage_line_rate": coverage["per_file"].get(rel),
            }
        )

    return {
        "repo": {
            "path": str(repo),
            "at_date": at.isoformat(),
            "churn_window": {
                "since": since.isoformat(),
                "until": at.isoformat(),
                "months": CHURN_WINDOW_MONTHS,
            },
        },
        "churn": {
            "total_commits": churn["total_commits"],
            "files_changed": len(files),
            "max_file_commits": max(churn_values) if churn_values else 0,
            "mean_file_commits": (
                round(statistics.fmean(churn_values), 2) if churn_values else 0.0
            ),
            "p90_file_commits": _percentile(churn_values, 0.9),
        },
        "fan_in": {
            "python_files": len(py_files),
            "max_fan_in": max(fan_in.values()) if fan_in else 0,
            "mean_fan_in": (
                round(statistics.fmean(fan_in.values()), 2) if fan_in else 0.0
            ),
            "files_with_fan_in": sum(1 for value in fan_in.values() if value > 0),
        },
        "complexity": complexity,
        "coverage": {"status": coverage["status"], "line_rate": coverage["line_rate"]},
        "authors": {
            "distinct_authors": len(all_authors),
            "max_file_authors": max(author_counts) if author_counts else 0,
            "mean_file_authors": (
                round(statistics.fmean(author_counts), 2) if author_counts else 0.0
            ),
            "concentration": _author_concentration(files),
        },
        "hot_files": hot_files,
    }


# --------------------------------------------------------------------------- #
# Similar past changes + invasiveness
# --------------------------------------------------------------------------- #


def find_similar_changes(
    repo_path: str | Path,
    keywords: Sequence[str],
    at_date: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Past commits whose touched paths match any keyword (case-insensitive substring).

    Leakage guard: only commits strictly BEFORE ``at_date`` (git ``--until`` plus
    a Python-side date re-check); default ``at_date`` is today UTC.

    Selection: a commit is similar when at least one touched path contains any
    keyword (lowercased). Its summary counts the **full patch** of that commit --
    invasiveness is a property of the whole change a similar request produced,
    not only of the path that happened to match (``matched_paths`` still reports
    which paths matched). Results are newest-first, capped at ``limit``.
    """
    if not keywords:
        return []
    repo = Path(repo_path).expanduser()
    _require_git_repo(repo)
    at = _parse_at_date(at_date)
    wanted = [str(keyword).lower() for keyword in keywords if str(keyword).strip()]
    if not wanted or limit <= 0:
        return []

    out = _git(
        repo,
        [
            "log",
            f"--until={at.isoformat()}T00:00:00",
            "--date=short",
            f"--format={_HEADER}",
            "--raw",
            "--numstat",
        ],
    )

    results: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def _flush() -> None:
        if current is None or not current["matched_paths"]:
            return
        if len(current["paths"]) == 0:
            return
        results.append(
            {
                "commit": current["commit"],
                "date": current["date"],
                "author": current["author"],
                "subject": current["subject"],
                "files_touched": len(current["paths"]),
                "new_files": current["new_files"],
                "modified_files": current["modified_files"],
                "deleted_files": current["deleted_files"],
                "added_lines": current["added_lines"],
                "removed_lines": current["removed_lines"],
                "matched_paths": sorted(current["matched_paths"]),
            }
        )

    for line in out.splitlines():
        if line.startswith("\x01"):
            _flush()
            if len(results) >= limit:
                current = None
                break
            parts = line[1:].split("\t")
            if len(parts) < 4:
                current = None
                continue
            try:
                commit_day = datetime.strptime(parts[2][:10], "%Y-%m-%d").date()
            except ValueError:
                current = None
                continue
            if commit_day >= at:  # leakage guard (date re-check)
                current = None
                continue
            current = {
                "commit": parts[0],
                "author": parts[1],
                "date": parts[2][:10],
                "subject": parts[3],
                "paths": set(),
                "new_files": 0,
                "modified_files": 0,
                "deleted_files": 0,
                "added_lines": 0,
                "removed_lines": 0,
                "matched_paths": [],
            }
        elif current is not None and line.startswith(":"):
            match = _RAW_LINE_RE.match(line)
            if not match:
                continue
            status = match.group(5)
            paths = [part for part in match.group(6).split("\t") if part]
            current["paths"].update(paths)
            if status[0] == "A":
                current["new_files"] += 1
            elif status[0] == "D":
                current["deleted_files"] += 1
            else:  # M / R / C / T ... all count as modified
                current["modified_files"] += 1
            for path in paths:
                lowered = path.lower()
                if any(keyword in lowered for keyword in wanted):
                    current["matched_paths"].append(path)
        elif current is not None:
            match = _NUMSTAT_RE.match(line)
            if match:
                if match.group(1).isdigit():
                    current["added_lines"] += int(match.group(1))
                if match.group(2).isdigit():
                    current["removed_lines"] += int(match.group(2))
    else:
        if current is not None:
            _flush()

    return results[:limit]


def estimate_invasiveness(commits: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Multiplicative patch-shape estimate from similar-change commits.

    ``None`` when no commits are given (no evidence -> no adjustment, never a
    fake one). Otherwise:

    * ``modified_ratio`` = modified / (new + modified) over all matched commits
      (0.0 when the commits only add/delete files);
    * ``added_removed_ratio`` = added_lines / (added_lines + removed_lines)
      (0.0 when both are zero) -- growth vs rewrite mix, informational;
    * ``mean_files_touched`` = mean patch size in files;
    * ``based_on_commits`` = number of similar commits behind the estimate.
    """
    if not commits:
        return None
    new_total = sum(int(commit.get("new_files") or 0) for commit in commits)
    modified_total = sum(int(commit.get("modified_files") or 0) for commit in commits)
    added_total = sum(int(commit.get("added_lines") or 0) for commit in commits)
    removed_total = sum(int(commit.get("removed_lines") or 0) for commit in commits)
    files_total = sum(int(commit.get("files_touched") or 0) for commit in commits)
    count = len(commits)
    added_fraction = (
        added_total / (added_total + removed_total)
        if (added_total + removed_total) > 0
        else 0.0
    )
    return {
        "modified_ratio": (
            round(modified_total / (new_total + modified_total), 4)
            if (new_total + modified_total) > 0
            else 0.0
        ),
        "added_removed_ratio": round(added_fraction, 4),
        "mean_files_touched": round(files_total / count, 2),
        "based_on_commits": count,
        "totals": {
            "new_files": new_total,
            "modified_files": modified_total,
            "added_lines": added_total,
            "removed_lines": removed_total,
        },
    }


# --------------------------------------------------------------------------- #
# Friction -> estimate adjustment
# --------------------------------------------------------------------------- #


def _saturate(raw: float, saturation: float) -> float:
    if saturation <= 0:
        return 0.0
    return round(min(1.0, max(0.0, float(raw) / saturation)), 4)


def compute_friction(signals: Mapping[str, Any]) -> dict[str, Any]:
    """Weighted friction score in ``[0, 1]`` from :func:`collect_signals` output.

    Documented normalised weighted formula (saturating normalisers, not
    data-fitted percentiles -- deterministic and cheap):

    * ``churn``                = min(1, max_file_commits / 20)              w=0.30
    * ``fan_in``               = min(1, max_fan_in / 8)                     w=0.15
    * ``complexity``           = min(1, max_complexity / 20; rank C+)       w=0.30
    * ``coverage_gap``         = 1 - coverage.xml line_rate                 w=0.10
    * ``author_concentration`` = commit-weighted 1 - authors/commits        w=0.15

    ``score`` = weighted mean over the components that are available. When no
    ``coverage.xml`` exists, ``coverage_gap`` is ``None`` ("unknown", never
    faked): it is omitted from the sum and the remaining weights are
    renormalised; a note says so.

    Level: score < 1/3 -> ``"low"``, < 2/3 -> ``"medium"``, else ``"high"``.

    Friction is a leading indicator of *predictability* (higher friction ->
    harder to predict), so :func:`apply_friction` uses it to widen the interval
    only -- it never shifts the median.
    """
    churn = signals.get("churn") or {}
    fan_in = signals.get("fan_in") or {}
    complexity = signals.get("complexity") or {}
    coverage = signals.get("coverage") or {}
    authors = signals.get("authors") or {}

    components: dict[str, float | None] = {
        "churn": _saturate(churn.get("max_file_commits") or 0, CHURN_SATURATION_COMMITS),
        "fan_in": _saturate(fan_in.get("max_fan_in") or 0, FAN_IN_SATURATION),
        "complexity": _saturate(
            complexity.get("max_complexity") or 0, COMPLEXITY_SATURATION
        ),
        "coverage_gap": None,
        "author_concentration": round(
            min(1.0, max(0.0, float(authors.get("concentration") or 0.0))), 4
        ),
    }

    notes: list[str] = []
    line_rate = coverage.get("line_rate")
    if coverage.get("status") == "found" and isinstance(line_rate, (int, float)):
        components["coverage_gap"] = round(min(1.0, max(0.0, 1.0 - float(line_rate))), 4)
    else:
        notes.append(
            "coverage.xml not found: coverage_gap is UNKNOWN (never faked) and "
            "was omitted from the weighted sum; remaining weights renormalised."
        )

    available = {
        name: (value, FRICTION_WEIGHTS[name])
        for name, value in components.items()
        if value is not None
    }
    total_weight = sum(weight for _, weight in available.values())
    weighted = sum(value * weight for value, weight in available.values())
    score = round(weighted / total_weight, 4) if total_weight > 0 else 0.0
    if score < LEVEL_MEDIUM_THRESHOLD:
        level = "low"
    elif score < LEVEL_HIGH_THRESHOLD:
        level = "medium"
    else:
        level = "high"

    return {
        "score": score,
        "level": level,
        "components": components,
        "weights": {name: FRICTION_WEIGHTS[name] for name in available},
        "notes": notes,
    }


def apply_friction(
    estimate: Mapping[str, Any],
    friction: Mapping[str, Any] | None,
    invasiveness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Adjust a ``{p10, p50, p90, ...}`` estimate for codebase friction/invasiveness.

    Transformations (DEMO-ASSUMED coefficients, see :data:`ASSUMPTION_NOTE`):

    * friction widens both tails (harder to predict, median untouched):
      ``p10 x (1 - 0.30 * score)`` (factor floored at 0.55),
      ``p90 x (1 + 0.60 * score)`` (factor capped at 1.90);
    * invasiveness shifts the median multiplicatively:
      ``p50 x (1 + 0.35 * modified_ratio)`` (factor capped at 1.50; no similar
      changes -> factor 1.0, never a fabricated shift).

    Guarantees: the interval never narrows (adjusted p10 <= original p10 and
    adjusted p90 >= original p90), ordering ``p10 <= p50 <= p90`` holds, and all
    values respect the estimator's ``MIN_ADJUSTED_DAYS`` (3.0) floor. Everything
    else in the estimate dict (``mode``, ``unit``, ``method``, ...) is preserved.

    Returns ``{"estimate": {...}, "adjustments": [{"what", "factor", "why"}],
    "friction_level", "assumption_note"}``.
    """
    base = dict(estimate)
    try:
        raw = sorted(float(base[key]) for key in ("p10", "p50", "p90"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("estimate must contain numeric p10/p50/p90") from exc
    p10_orig, p50_orig, p90_orig = raw

    score = 0.0
    level = "unknown"
    if friction:
        score = min(1.0, max(0.0, float(friction.get("score") or 0.0)))
        level = str(friction.get("level") or "unknown")
    modified_ratio: float | None = None
    if invasiveness:
        modified_ratio = min(
            1.0, max(0.0, float(invasiveness.get("modified_ratio") or 0.0))
        )

    p10_factor = max(P10_FACTOR_FLOOR, 1.0 - FRICTION_P10_WIDENING * score)
    p90_factor = min(P90_FACTOR_CAP, 1.0 + FRICTION_P90_WIDENING * score)
    p50_factor = (
        min(P50_FACTOR_CAP, 1.0 + INVASIVENESS_P50_SHIFT * modified_ratio)
        if modified_ratio is not None
        else 1.0
    )

    # Never narrow: p10 moves down or stays, p90 moves up or stays.
    adjusted_p10 = min(p10_orig, max(MIN_ADJUSTED_DAYS, p10_orig * p10_factor))
    adjusted_p90 = max(p90_orig, p90_orig * p90_factor)
    adjusted_p50 = max(MIN_ADJUSTED_DAYS, p50_orig * p50_factor)
    adjusted_p50 = min(max(adjusted_p50, adjusted_p10), adjusted_p90)

    result = dict(base)
    result["p10"] = max(MIN_ADJUSTED_DAYS, round(adjusted_p10, 1))
    result["p50"] = max(MIN_ADJUSTED_DAYS, round(adjusted_p50, 1))
    result["p90"] = max(MIN_ADJUSTED_DAYS, round(adjusted_p90, 1))

    if invasiveness is None:
        p50_why = "no similar past changes found: no evidence, so the median is unchanged"
    else:
        p50_why = (
            f"similar changes were {modified_ratio} modified (not new) files: "
            "invasiveness shifts the median (demo-assumed x (1 + 0.35 * ratio))"
        )

    return {
        "estimate": result,
        "adjustments": [
            {
                "what": "p10 (lower tail)",
                "factor": round(p10_factor, 4),
                "why": "friction widens the interval downward; median untouched "
                f"(friction level {level}, score {score})",
            },
            {
                "what": "p90 (upper tail)",
                "factor": round(p90_factor, 4),
                "why": "friction widens the interval upward; median untouched "
                f"(friction level {level}, score {score})",
            },
            {"what": "p50 (median)", "factor": round(p50_factor, 4), "why": p50_why},
        ],
        "friction_level": level,
        "assumption_note": ASSUMPTION_NOTE,
    }
