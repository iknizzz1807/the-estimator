"""Tests for the surcharge-calibration experiment (offline, deterministic).

Pure functions only: synthetic commit dicts, no repository, no network, no LLM.
The heavy real-repo run lives in ``scripts/surcharge_calibration.py``.
"""

from __future__ import annotations

import numpy as np

from scripts.surcharge_calibration import (
    BOOTSTRAP_SEED,
    FileHistory,
    build_summary,
    build_target_rows,
    dispersion_ratio,
    friction_beta_ci,
    git_friction,
    invasiveness_view,
    run_self_test,
)

DAY = 86_400


def _commits(n: int = 80, hot: str = "hot.py") -> list[dict]:
    """Synthetic history: one hot file touched often, plus per-commit files."""
    out = []
    for i in range(n):
        files = [hot, hot, "cold.py"] if i % 3 == 0 else [hot, f"f{i}.py"]
        out.append(
            {
                "hash": f"{i:040x}",
                "author": "alice" if i % 2 == 0 else "bob",
                "ts": 1_700_000_000 + i * DAY,
                "subject": f"change {i}",
                "files": files,
            }
        )
    return out


def test_file_history_counts_only_prior_commits() -> None:
    history = FileHistory()
    history.observe(["a.py"], "alice", 1000)
    history.observe(["a.py"], "bob", 2000)
    # window includes only commits strictly before ts
    assert history.churn("a.py", 2500, window_days=30) == 2
    assert history.churn("a.py", 1500, window_days=30) == 1
    assert history.churn("a.py", 500, window_days=30) == 0
    assert history.lifetime("a.py") == 2
    assert history.lifetime("missing.py") == 0


def test_concentration_needs_two_commits() -> None:
    history = FileHistory()
    history.observe(["a.py"], "alice", 1000)
    assert history.concentration("a.py") == 0.0  # a single touch says nothing
    history.observe(["a.py"], "bob", 2000)
    assert history.concentration("a.py") == 0.0  # two authors, two commits -> 0
    history.observe(["a.py"], "alice", 3000)
    assert history.concentration("a.py") > 0.0  # 2 authors / 3 commits


def test_git_friction_is_bounded_and_renormalised() -> None:
    history = FileHistory()
    for i in range(25):
        history.observe(["hot.py"], f"dev{i}", 1000 + i)
    score, components = git_friction(history, ["hot.py"], ts=2000 + 25)
    assert 0.0 <= score <= 1.0
    assert components["churn"] == 1.0  # 25 prior commits saturate at 20
    assert set(components) == {"churn", "author_concentration"}
    # a brand-new file has no history -> no friction
    fresh, _ = git_friction(history, ["brand_new.py"], ts=2000 + 25)
    assert fresh == 0.0


def test_build_target_rows_uses_only_history() -> None:
    commits = _commits(80)
    rows = build_target_rows(commits, target_share=0.4)
    assert len(rows) == 32  # 40% of 80
    assert all(r["size"] >= 1 for r in rows)
    assert all(0.0 <= r["friction_git"] <= 1.0 for r in rows)
    # targets are the LAST 40% of the chronological order
    assert rows[0]["ts"] < rows[-1]["ts"]


def test_build_target_rows_is_leakage_free() -> None:
    """Friction for a target must be identical when later commits are removed."""
    full = build_target_rows(_commits(80), target_share=0.4)
    truncated = build_target_rows(_commits(60), target_share=0.4)
    # compare the overlapping early targets by timestamp
    by_ts_full = {r["ts"]: r["friction_git"] for r in full}
    by_ts_trunc = {r["ts"]: r["friction_git"] for r in truncated}
    shared = sorted(set(by_ts_full) & set(by_ts_trunc))
    assert shared, "expected overlapping targets"
    for ts in shared:
        assert by_ts_full[ts] == by_ts_trunc[ts]


def test_build_target_rows_is_deterministic() -> None:
    first = build_target_rows(_commits(80), target_share=0.4)
    second = build_target_rows(_commits(80), target_share=0.4)
    assert [r["friction_git"] for r in first] == [r["friction_git"] for r in second]


def test_metrics_are_finite_and_bounded() -> None:
    rows = build_target_rows(_commits(120), target_share=0.4)
    beta = friction_beta_ci(rows)
    assert beta["n"] == len(rows)
    assert np.isfinite(beta["beta"])
    assert beta["ci_low"] <= beta["beta"] <= beta["ci_high"]

    disp = dispersion_ratio(rows)
    assert np.isfinite(disp["ratio"])
    assert disp["n_low"] > 0 and disp["n_high"] > 0

    inv = invasiveness_view(rows)
    assert 0.0 <= inv["multi_low"] <= 1.0
    assert 0.0 <= inv["multi_high"] <= 1.0


def test_bootstrap_seed_is_fixed() -> None:
    assert BOOTSTRAP_SEED == 42


def test_build_summary_reports_gates() -> None:
    rows = build_target_rows(_commits(120), target_share=0.4)
    repo = {
        "name": "toy",
        "n_targets": len(rows),
        "beta": friction_beta_ci(rows),
        "dispersion": dispersion_ratio(rows),
        "spearman_ci": (0.1, 0.05, 0.15),
        "human_only": {"beta": None, "dispersion": None},
    }
    summary = build_summary([repo])
    assert set(summary["gates"]) == {
        "G1_friction_predicts_size",
        "G2_friction_predicts_spread",
        "G3_spearman_positive",
    }
    assert summary["n_targets"] == len(rows)


def test_self_test_passes() -> None:
    assert run_self_test() == 0
