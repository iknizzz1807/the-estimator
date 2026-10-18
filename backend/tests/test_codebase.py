"""Tests for the Codebase Lab analyzer: friction, invasiveness, demo repos.

Offline and deterministic: the demo repos are built by
``scripts/build_demo_repos.py`` (fixed authors/dates) into pytest tmp dirs, and
the analyzer only reads git history plus local files. No network, no LLM.

The demo A/B outcome asserted here is the module's headline claim:
``friction(payment_plugin) < friction(payment_spaghetti)`` with a clear margin,
and "add a payment provider" is mostly new files in the plugin repo but mostly
modified files in the spaghetti repo.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.codebase import (
    apply_friction,
    collect_signals,
    compute_friction,
    detect_primary_language,
    estimate_invasiveness,
    find_similar_changes,
)
from scripts.build_demo_repos import ALICE, BOB, _commit, _init_repo, _write, build_demo_repos

BACKEND = Path(__file__).resolve().parents[1]
DEMO_AT = "2026-04-01"
DEMO_KEYWORDS = ["payment", "payments", "provider", "checkout", "billing", "orders"]
SPAGHETTI_FILES = (
    "checkout.py", "orders.py", "billing.py", "api.py",
    "models.py", "utils.py", "admin.py", "legacy.py",
)


@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> dict[str, Path]:
    """Both demo repos, built once per test module."""
    root = tmp_path_factory.mktemp("demo_repos")
    return build_demo_repos(root)


def _hot(signals: dict) -> dict[str, dict]:
    return {entry["path"]: entry for entry in signals["hot_files"]}


# --------------------------------------------------------------------------- #
# Demo repos
# --------------------------------------------------------------------------- #


def test_demo_repos_built_with_expected_shape(demo: dict[str, Path]) -> None:
    plugin = demo["payment_plugin"]
    spaghetti = demo["payment_spaghetti"]
    assert (plugin / ".git").is_dir()
    assert (spaghetti / ".git").is_dir()
    assert (plugin / "coverage.xml").is_file()
    assert not (spaghetti / "coverage.xml").exists()

    # CLEAN repo: providers as new files, tests present.
    assert (plugin / "payments" / "base.py").is_file()
    assert (plugin / "payments" / "providers" / "klarna.py").is_file()
    assert (plugin / "tests" / "test_registry.py").is_file()

    # MESSY repo: the same hardcoded branch in every module, no tests.
    for name in SPAGHETTI_FILES:
        assert 'if provider == "stripe"' in (spaghetti / name).read_text()
    assert not (spaghetti / "tests").exists()

    assert collect_signals(plugin, DEMO_AT)["churn"]["total_commits"] == 8
    assert collect_signals(spaghetti, DEMO_AT)["churn"]["total_commits"] == 10


def test_demo_friction_contrast(demo: dict[str, Path]) -> None:
    clean = compute_friction(collect_signals(demo["payment_plugin"], DEMO_AT))
    messy = compute_friction(collect_signals(demo["payment_spaghetti"], DEMO_AT))

    assert clean["score"] < messy["score"]
    assert messy["score"] - clean["score"] > 0.25  # clear margin, not a photo finish
    assert clean["level"] == "low"
    assert messy["level"] == "high"

    # Coverage: found + high for the plugin repo, honestly unknown for spaghetti.
    assert clean["components"]["coverage_gap"] == pytest.approx(0.06)
    assert clean["notes"] == []
    assert messy["components"]["coverage_gap"] is None
    assert messy["notes"]  # renormalisation is disclosed, not hidden


def test_demo_invasiveness_contrast(demo: dict[str, Path]) -> None:
    clean_commits = find_similar_changes(demo["payment_plugin"], DEMO_KEYWORDS, DEMO_AT)
    messy_commits = find_similar_changes(demo["payment_spaghetti"], DEMO_KEYWORDS, DEMO_AT)
    clean = estimate_invasiveness(clean_commits)
    messy = estimate_invasiveness(messy_commits)

    assert clean is not None and messy is not None
    assert clean["based_on_commits"] == len(clean_commits) >= 5
    assert messy["based_on_commits"] == len(messy_commits) >= 5
    # Plugin: the change lands as mostly NEW provider files.
    assert clean["modified_ratio"] < 0.5
    assert clean["totals"]["new_files"] > clean["totals"]["modified_files"]
    # Spaghetti: the same change lands as mostly MODIFIED existing files.
    assert messy["modified_ratio"] > 0.75
    assert messy["totals"]["modified_files"] > 5 * messy["totals"]["new_files"]
    assert messy["mean_files_touched"] > clean["mean_files_touched"]


# --------------------------------------------------------------------------- #
# collect_signals: leakage guard, authors, fan-in, complexity, coverage
# --------------------------------------------------------------------------- #


def test_churn_leakage_guard(demo: dict[str, Path]) -> None:
    plugin = demo["payment_plugin"]
    early = collect_signals(plugin, "2026-01-01")
    late = collect_signals(plugin, DEMO_AT)

    # Commits dated on/after at_date are excluded from the churn window.
    assert early["churn"]["total_commits"] == 4  # a1, a2, a3, a4
    assert late["churn"]["total_commits"] == 8
    assert early["repo"]["churn_window"]["since"] == "2025-07-01"
    assert late["repo"]["churn_window"]["since"] == "2025-10-01"
    assert _hot(early)["payments/registry.py"]["commits"] == 2
    assert _hot(late)["payments/registry.py"]["commits"] == 4


def test_author_concentration_counts_distinct_authors(tmp_path: Path) -> None:
    repo = tmp_path / "authors"
    _init_repo(repo)
    _write(repo, "hot.py", "VALUE = 1\n")
    _write(repo, "solo.py", "VALUE = 1\n")
    _commit(repo, "2026-01-05", ALICE, "init")
    _write(repo, "hot.py", "VALUE = 1\nMORE = 2\n")
    _commit(repo, "2026-01-12", BOB, "touch hot")
    _write(repo, "hot.py", "VALUE = 1\nMORE = 2\nEXTRA = 3\n")
    _write(repo, "solo.py", "VALUE = 1\nSIDE = 0\n")
    _commit(repo, "2026-01-19", ALICE, "touch hot and solo")

    signals = collect_signals(repo, "2026-06-01")
    hot = _hot(signals)
    assert hot["hot.py"]["commits"] == 3
    assert hot["hot.py"]["distinct_authors"] == 2
    assert hot["hot.py"]["authors"] == sorted(["Alice Tran", "Bao Pham"])
    assert hot["solo.py"]["distinct_authors"] == 1
    assert signals["authors"]["distinct_authors"] == 2
    assert signals["authors"]["max_file_authors"] == 2
    # hot.py: 1 - 2/3, solo.py: 1 - 1/2, commit-weighted -> exactly 0.4
    assert signals["authors"]["concentration"] == pytest.approx(0.4)


def test_fan_in_counts_known_import(tmp_path: Path) -> None:
    repo = tmp_path / "fanin"
    _init_repo(repo)
    _write(repo, "helper.py", "def thing():\n    return 1\n")
    _write(repo, "one.py", "from helper import thing\n")
    _write(repo, "two.py", "import helper\n")
    _write(repo, "three.py", "import unrelated\n")
    _commit(repo, "2026-01-05", ALICE, "imports")

    signals = collect_signals(repo, "2026-06-01")
    hot = _hot(signals)
    assert hot["helper.py"]["fan_in"] == 2  # one.py + two.py
    assert hot["one.py"]["fan_in"] == 0
    assert signals["fan_in"]["max_fan_in"] == 2


def test_non_python_repo_marks_python_only_components_unknown(tmp_path: Path) -> None:
    """fan_in/complexity are Python-only; on a JS repo they are UNKNOWN, not 0.

    Reporting them as a measured zero includes them in the weighted mean with
    0.45 of the weight and biases friction DOWN (=> under-surcharge) on
    non-Python repos; unknown components are omitted and weights renormalised.
    """
    repo = tmp_path / "jsrepo"
    _init_repo(repo)
    _write(repo, "src/app.js", "export const app = 1;\n")
    _write(repo, "src/util.js", "export const util = 2;\n")
    _commit(repo, "2026-01-05", ALICE, "add js sources")
    _write(repo, "src/app.js", "export const app = 3;\n")
    _commit(repo, "2026-01-06", ALICE, "tweak app")

    signals = collect_signals(repo, "2026-06-01")
    assert signals["fan_in"]["python_files"] == 0
    assert signals["complexity"]["files_scored"] == 0

    friction = compute_friction(signals)
    assert friction["components"]["fan_in"] is None
    assert friction["components"]["complexity"] is None
    assert friction["components"]["coverage_gap"] is None
    assert friction["components"]["churn"] is not None
    # the score is renormalised over the components actually measured
    assert set(friction["weights"]) == {"churn", "author_concentration"}
    assert any("fan_in is UNKNOWN" in note for note in friction["notes"])
    assert any("complexity not measured" in note for note in friction["notes"])


def test_detect_primary_language_gates_non_python(tmp_path: Path) -> None:
    """Python must be the dominant source language (D24 scope gate)."""
    python_repo = tmp_path / "pyrepo"
    _init_repo(python_repo)
    _write(python_repo, "app/main.py", "def main():\n    return 1\n")
    _write(python_repo, "app/util.py", "VALUE = 1\n")
    _commit(python_repo, "2026-01-05", ALICE, "python only")

    info = detect_primary_language(python_repo)
    assert info["dominant"] == "Python"
    assert info["python_supported"] is True
    assert info["python_files"] == 2 and info["source_files"] == 2
    assert info["python_share"] == pytest.approx(1.0)

    c_repo = tmp_path / "crepo"
    _init_repo(c_repo)
    for i in range(5):
        _write(c_repo, f"src/f{i}.c", "int f(void){return 0;}\n")
    _write(c_repo, "tests/helper.py", "print('x')\n")  # a stray .py must not win
    _commit(c_repo, "2026-01-05", ALICE, "c library")

    info = detect_primary_language(c_repo)
    assert info["dominant"] == "C"
    assert info["python_supported"] is False
    assert info["python_files"] == 1 and info["source_files"] == 6
    assert info["languages"]["C"] == 5


def test_complexity_and_coverage_signals(demo: dict[str, Path]) -> None:
    clean = collect_signals(demo["payment_plugin"], DEMO_AT)
    messy = collect_signals(demo["payment_spaghetti"], DEMO_AT)

    # radon: the spaghetti checkout is positively complex, the plugin is not.
    assert messy["complexity"]["status"] == "scored"
    checkout = _hot(messy)["checkout.py"]
    assert checkout["complexity_max"] >= 10
    assert checkout["complexity_mean"] > 0
    assert clean["complexity"]["max_complexity"] < 10

    # coverage.xml parsed when present, "unknown" when absent (never faked).
    assert clean["coverage"]["status"] == "found"
    assert clean["coverage"]["line_rate"] == pytest.approx(0.94)
    assert _hot(clean)["payments/registry.py"]["coverage_line_rate"] == pytest.approx(0.95)
    assert messy["coverage"] == {"status": "unknown", "line_rate": None}


# --------------------------------------------------------------------------- #
# estimate_invasiveness
# --------------------------------------------------------------------------- #


def test_estimate_invasiveness_empty_and_ratios() -> None:
    assert estimate_invasiveness([]) is None

    commits = [
        {"new_files": 3, "modified_files": 1, "added_lines": 100, "removed_lines": 0, "files_touched": 4},
        {"new_files": 1, "modified_files": 3, "added_lines": 10, "removed_lines": 30, "files_touched": 8},
    ]
    invasiveness = estimate_invasiveness(commits)
    assert invasiveness is not None
    assert invasiveness["modified_ratio"] == pytest.approx(4 / 8)
    assert invasiveness["added_removed_ratio"] == pytest.approx(110 / 140, abs=1e-4)
    assert invasiveness["mean_files_touched"] == pytest.approx(6.0)
    assert invasiveness["based_on_commits"] == 2
    assert invasiveness["totals"] == {
        "new_files": 4,
        "modified_files": 4,
        "added_lines": 110,
        "removed_lines": 30,
    }

    empty = estimate_invasiveness([{"files_touched": 0}])
    assert empty is not None
    assert empty["modified_ratio"] == 0.0
    assert empty["added_removed_ratio"] == 0.0
    assert empty["mean_files_touched"] == 0.0


# --------------------------------------------------------------------------- #
# apply_friction
# --------------------------------------------------------------------------- #


def test_apply_friction_monotone_and_never_narrows() -> None:
    estimate = {"p10": 10.0, "p50": 20.0, "p90": 40.0, "mode": "calibrated"}
    previous_width = -1.0
    previous_p10 = float("inf")
    previous_p90 = -1.0
    for score in (0.0, 0.25, 0.5, 0.75, 1.0):
        friction = {"score": score, "level": "low"}
        result = apply_friction(estimate, friction, None)["estimate"]
        assert result["p10"] <= previous_p10
        assert result["p90"] >= previous_p90
        width = result["p90"] - result["p10"]
        assert width >= previous_width
        assert width >= estimate["p90"] - estimate["p10"]  # never narrows
        assert result["p10"] <= result["p50"] <= result["p90"]
        assert result["p50"] == pytest.approx(estimate["p50"])  # friction never moves p50
        previous_width, previous_p10, previous_p90 = width, result["p10"], result["p90"]

    # score 0 leaves the interval untouched.
    zero = apply_friction(estimate, {"score": 0.0, "level": "low"}, None)["estimate"]
    assert (zero["p10"], zero["p50"], zero["p90"]) == (10.0, 20.0, 40.0)


def test_apply_friction_invasiveness_raises_p50() -> None:
    estimate = {"p10": 10.0, "p50": 20.0, "p90": 40.0}
    friction = {"score": 0.0, "level": "low"}

    shifted = apply_friction(estimate, friction, {"modified_ratio": 1.0})["estimate"]
    assert shifted["p50"] == pytest.approx(27.0)  # 20 * (1 + 0.35 * 1.0)
    assert shifted["p10"] == pytest.approx(10.0)  # no friction -> tails untouched

    no_evidence = apply_friction(estimate, friction, None)["estimate"]
    assert no_evidence["p50"] == pytest.approx(20.0)
    zero_ratio = apply_friction(estimate, friction, {"modified_ratio": 0.0})["estimate"]
    assert zero_ratio["p50"] == pytest.approx(20.0)



def test_apply_friction_breakdown_and_determinism(demo: dict[str, Path]) -> None:
    signals = collect_signals(demo["payment_spaghetti"], DEMO_AT)
    friction = compute_friction(signals)
    similar = find_similar_changes(demo["payment_spaghetti"], DEMO_KEYWORDS, DEMO_AT)
    invasiveness = estimate_invasiveness(similar)
    estimate = {"p10": 10.0, "p50": 20.0, "p90": 40.0, "mode": "calibrated", "unit": "days", "method": "point"}

    first = apply_friction(estimate, friction, invasiveness)
    second = apply_friction(estimate, friction, invasiveness)
    assert first == second  # deterministic

    assert first["adjustments"]
    for adjustment in first["adjustments"]:
        assert set(adjustment) == {"what", "factor", "why"}
        assert adjustment["why"]
    assert first["friction_level"] == friction["level"] == "high"
    assert "DEMO-ASSUMED" in first["assumption_note"]
    assert "learned" in first["assumption_note"]
    # Original estimate untouched; other keys preserved.
    assert estimate == {"p10": 10.0, "p50": 20.0, "p90": 40.0, "mode": "calibrated", "unit": "days", "method": "point"}
    assert first["estimate"]["unit"] == "days"
    assert first["estimate"]["method"] == "point"


def test_apply_friction_floor_and_sane_caps() -> None:
    tiny = {"p10": 3.0, "p50": 3.0, "p90": 3.0}
    result = apply_friction(tiny, {"score": 1.0, "level": "high"}, {"modified_ratio": 1.0})
    adjusted = result["estimate"]
    assert adjusted["p10"] >= 3.0 and adjusted["p50"] >= 3.0 and adjusted["p90"] >= 3.0
    assert adjusted["p10"] <= 3.0 and adjusted["p90"] >= 3.0  # never narrows
    assert adjusted["p10"] <= adjusted["p50"] <= adjusted["p90"]

    factors = {item["what"]: item["factor"] for item in result["adjustments"]}
    assert factors["p10 (lower tail)"] == pytest.approx(0.7)
    assert factors["p90 (upper tail)"] == pytest.approx(1.6)
    assert factors["p50 (median)"] == pytest.approx(1.35)

    # Out-of-range inputs are clamped, not extrapolated.
    clamped = apply_friction(
        {"p10": 10.0, "p50": 20.0, "p90": 40.0},
        {"score": 5.0, "level": "high"},
        {"modified_ratio": 2.0},
    )
    factors = {item["what"]: item["factor"] for item in clamped["adjustments"]}
    assert factors["p10 (lower tail)"] <= 1.0
    assert factors["p90 (upper tail)"] <= 1.9  # sane cap
    assert factors["p50 (median)"] <= 1.5  # sane cap


# --------------------------------------------------------------------------- #
# find_similar_changes
# --------------------------------------------------------------------------- #


def test_find_similar_changes_keywords_order_and_limit(demo: dict[str, Path]) -> None:
    plugin = demo["payment_plugin"]
    commits = find_similar_changes(plugin, ["payments"], at_date=DEMO_AT)
    assert [commit["date"] for commit in commits] == [
        "2026-02-01", "2026-01-15", "2025-12-01", "2025-11-10", "2025-11-02",
    ], "newest-first, only commits touching payments/*"
    for commit in commits:
        assert len(commit["commit"]) == 40
        assert any("payments" in path.lower() for path in commit["matched_paths"])

    limited = find_similar_changes(plugin, ["payments"], at_date=DEMO_AT, limit=2)
    assert [commit["date"] for commit in limited] == ["2026-02-01", "2026-01-15"]

    assert find_similar_changes(plugin, ["zzz-not-a-path"], at_date=DEMO_AT) == []
    assert find_similar_changes(plugin, [], at_date=DEMO_AT) == []
    assert find_similar_changes(plugin, ["payments"], at_date=DEMO_AT, limit=0) == []


def test_find_similar_changes_respects_at_date(demo: dict[str, Path]) -> None:
    early = find_similar_changes(demo["payment_plugin"], ["payments"], at_date="2026-01-01")
    assert [commit["date"] for commit in early] == ["2025-12-01", "2025-11-10", "2025-11-02"]
    assert all(commit["date"] < "2026-01-01" for commit in early)

    stripe_commit = next(commit for commit in early if commit["date"] == "2025-11-10")
    assert stripe_commit["files_touched"] == 3
    assert stripe_commit["new_files"] == 3
    assert stripe_commit["modified_files"] == 0
    assert stripe_commit["added_lines"] > 0
    assert stripe_commit["removed_lines"] == 0


# --------------------------------------------------------------------------- #
# Determinism, JSON contract, CLI smoke
# --------------------------------------------------------------------------- #


def test_signals_deterministic_and_json_serializable(tmp_path_factory) -> None:
    root = tmp_path_factory.mktemp("rebuild")
    build_demo_repos(root, force=True)
    first = {
        name: collect_signals(path, DEMO_AT) for name, path in build_demo_repos(root).items()
    }
    build_demo_repos(root, force=True)  # byte-comparable regeneration
    second = {
        name: collect_signals(path, DEMO_AT) for name, path in build_demo_repos(root).items()
    }
    assert first == second
    assert json.loads(json.dumps(first)) == first  # JSON-serializable
    # Same repo + same date twice -> identical dict.
    assert collect_signals(root / "payment_plugin", DEMO_AT) == first["payment_plugin"]


def test_analyzer_rejects_non_git_directories(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        collect_signals(tmp_path)
    with pytest.raises(ValueError):
        find_similar_changes(tmp_path, ["anything"])


def test_cli_smoke_subprocess(demo: dict[str, Path]) -> None:
    cli = BACKEND / "scripts" / "codebase_cli.py"
    proc = subprocess.run(
        [
            sys.executable, str(cli),
            "--repo", str(demo["payment_plugin"]),
            "--at", DEMO_AT,
            "--keywords", "payment,provider",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "friction" in proc.stdout
    assert "DEMO-ASSUMED" in proc.stdout

    json_proc = subprocess.run(
        [
            sys.executable, str(cli),
            "--repo", str(demo["payment_spaghetti"]),
            "--at", DEMO_AT,
            "--keywords", "checkout,billing,orders",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert json_proc.returncode == 0, json_proc.stderr
    payload = json.loads(json_proc.stdout)
    assert payload["friction"]["level"] == "high"
    assert payload["signals"]["coverage"]["status"] == "unknown"
    assert payload["invasiveness"]["based_on_commits"] >= 5
