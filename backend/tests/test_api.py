"""API integration tests (FastAPI TestClient over temporary SQLite databases).

The module-scoped ``client`` fixture boots the real app against a temp DB
seeded from the repo's synthetic CSV (``ESTIMATOR_DB_PATH`` isolation); the
cold-start test builds its own client with ``ESTIMATOR_AUTO_SEED=0``. All
tests run offline against the deterministic stub provider.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.features import FEATURES
from app.scenarios import SCENARIOS, get_scenario

REPO_ROOT = Path(__file__).resolve().parents[2]
ESTIMATE_CONTRACT_KEYS = {
    "project_id",
    "findings",
    "estimate",
    "similar_projects",
    "questions",
    "coefficients",
    "warnings",
}
PROJECT_CONTRACT_KEYS = {
    "project_id",
    "date",
    "status",
    "team_estimate",
    "system_p50",
    "actual_days",
    "delta_pct",
    "features",
}
#: Present features of the first open project (P229) in the 240-project history.
P229_FEATURES = {
    "third_party_api",
    "payment_gateway",
    "privacy_compliance",
    "audit_logging",
    "cross_team_coordination",
}
CSV_HEADER = ",".join(
    [
        "project_id",
        "date",
        "actual_days",
        "team_estimate",
        "status",
        "is_synthetic",
        "email_text",
        *[f"feat_{name}" for name in FEATURES],
    ]
)


# --------------------------------------------------------------------------- #
# Fixtures + helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory):
    """Real app on a temp DB seeded from data/synthetic_history.csv (240 rows)."""
    db_path = tmp_path_factory.mktemp("api_db") / "estimator.db"
    os.environ["ESTIMATOR_DB_PATH"] = str(db_path)
    try:
        from app.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        os.environ.pop("ESTIMATOR_DB_PATH", None)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE payload into ``[(event, data), ...]`` (order preserved)."""
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        event_name = "message"
        data = ""
        for line in lines:
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data += line[len("data:"):].strip()
        events.append((event_name, json.loads(data) if data else {}))
    return events


def _csv_row(
    project_id: str,
    date: str,
    actual: str,
    team: str,
    status: str,
    email: str,
    ones: tuple[str, ...] = (),
) -> str:
    """One canonical CSV row with 0/1 feature columns."""
    features = ["1" if name in ones else "0" for name in FEATURES]
    return ",".join([project_id, date, actual, team, status, "0", f'"{email}"', *features])


def _upload(client: TestClient, content: str | bytes, name: str = "import.csv"):
    data = content.encode("utf-8") if isinstance(content, str) else content
    return client.post("/api/import", files={"file": (name, data, "text/csv")})


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


def test_health_reports_seeded_calibrated(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["llm_provider"] == "stub"
    assert body["projects_count"] == 240
    assert body["mode"] == "calibrated"


# --------------------------------------------------------------------------- #
# Estimate (calibrated)
# --------------------------------------------------------------------------- #


def test_estimate_empty_email_rejected(client: TestClient) -> None:
    response = client.post("/api/estimate", json={"email_text": "   "})
    assert response.status_code == 422
    assert response.json()["detail"] == "Vui lòng paste email"


def test_estimate_returns_calibrated_contract_payload(client: TestClient) -> None:
    email_text = get_scenario("A")["email_text"]
    response = client.post("/api/estimate", json={"email_text": email_text})
    assert response.status_code == 200
    body = response.json()

    assert ESTIMATE_CONTRACT_KEYS <= set(body)
    assert body["project_id"] and body["project_id"].startswith("P")
    # A fresh id after the 240 seeded projects (exact value depends on how many
    # estimate calls ran before this test).
    assert int(body["project_id"][1:]) > 240
    assert body["provider"] == "stub"

    findings = body["findings"]
    assert len(findings) == 15
    assert [finding["name"] for finding in findings] == FEATURES  # canonical order
    for finding in findings:
        assert finding["value"] in (0, 1, None)
        assert 0.0 <= finding["confidence"] <= 1.0
    by_name = {finding["name"]: finding for finding in findings}
    for expected in ("payment_gateway", "pci_dss", "mobile_app", "realtime_ui", "third_party_api"):
        assert by_name[expected]["value"] == 1, expected
        assert by_name[expected]["evidence_quote"]

    estimate = body["estimate"]
    assert {"p10", "p50", "p90", "unit", "mode"} <= set(estimate)
    assert estimate["mode"] == "calibrated"
    assert estimate["unit"] == "days"
    assert estimate["p10"] <= estimate["p50"] <= estimate["p90"]

    assert len(body["similar_projects"]) == 3
    for item in body["similar_projects"]:
        assert {"project_id", "title_hint", "score", "actual_days", "shared_features"} <= set(item)
        assert item["title_hint"]
        assert 0.0 <= item["score"] <= 1.0

    assert 1 <= len(body["questions"]) <= 5
    for question in body["questions"]:
        assert {"feature", "impact_days", "question_vi", "question_en"} <= set(question)
        assert question["feature"] in FEATURES

    assert len(body["coefficients"]) == 15
    for coefficient in body["coefficients"]:
        assert {"feature", "multiplier", "sample_count"} <= set(coefficient)
        assert coefficient["multiplier"] > 0
        assert coefficient["sample_count"] >= 0

    assert isinstance(body["warnings"], list)
    # Round-trip: the persisted project shows up in the projects listing.
    rows = client.get("/api/projects", params={"status": "pending"}).json()
    assert any(row["project_id"] == body["project_id"] for row in rows)


def test_estimate_stream_empty_email_422(client: TestClient) -> None:
    response = client.post("/api/estimate/stream", json={"email_text": ""})
    assert response.status_code == 422
    assert response.json()["detail"] == "Vui lòng paste email"


def test_estimate_stream_emits_steps_then_result(client: TestClient) -> None:
    email_text = get_scenario("B")["email_text"]
    with client.stream("POST", "/api/estimate/stream", json={"email_text": email_text}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        payload = "".join(response.iter_text())

    events = parse_sse(payload)
    steps = [data for event, data in events if event == "step"]
    assert [step["step"] for step in steps] == [
        "extracting",
        "validating",
        "similar",
        "estimating",
        "questions",
        "done",
    ]
    assert all(step["message"] for step in steps)

    results = [data for event, data in events if event == "result"]
    assert len(results) == 1
    result = results[0]
    assert ESTIMATE_CONTRACT_KEYS <= set(result)
    assert result["estimate"]["mode"] == "calibrated"
    assert len(result["findings"]) == 15
    assert result["project_id"] is not None

    # The final event carries the same shape as POST /api/estimate.
    direct = client.post("/api/estimate", json={"email_text": email_text})
    assert ESTIMATE_CONTRACT_KEYS <= set(direct.json())


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #


def test_projects_list_and_filters(client: TestClient) -> None:
    rows = client.get("/api/projects").json()
    assert len(rows) >= 240
    first = rows[0]
    assert PROJECT_CONTRACT_KEYS <= set(first)
    assert set(first["features"]) == set(FEATURES)
    for row in rows:
        assert {"system_p10", "system_p50", "system_p90", "system_source"} <= set(row)
    # Walk-forward replay backs most done projects; extra rows fall back.
    assert any(row["system_source"] == "replay" for row in rows)
    assert any(row["delta_pct"] is not None for row in rows)

    done = client.get("/api/projects", params={"status": "done"}).json()
    assert done and all(row["status"] == "done" for row in done)

    with_migration = client.get("/api/projects", params={"feature": "data_migration=1"}).json()
    assert with_migration
    assert all(row["features"]["data_migration"] == 1 for row in with_migration)

    without_migration = client.get("/api/projects", params={"feature": "data_migration=0"}).json()
    assert without_migration
    assert all(row["features"]["data_migration"] != 1 for row in without_migration)

    recent = client.get("/api/projects", params={"from": "2025-01-01"}).json()
    assert recent and all(row["date"] >= "2025-01-01" for row in recent)

    invalid = client.get("/api/projects", params={"feature": "not_a_feature"})
    assert invalid.status_code == 422


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #


def test_replay_endpoint_is_cached_and_deterministic(client: TestClient) -> None:
    response = client.get("/api/replay")
    assert response.status_code == 200
    body = response.json()
    assert body["min_train"] == 10
    assert body["summary"]["n_steps"] == len(body["steps"]) > 0
    assert body["summary"]["llm_only_mode"] == "simulated"
    assert 0.0 <= body["summary"]["coverage_pct"] <= 100.0
    for step in body["steps"][:3]:
        assert {"i", "project_id", "p10", "p50", "p90", "actual", "mae_system", "in_interval"} <= set(step)
        assert step["p10"] <= step["p50"] <= step["p90"]

    assert client.get("/api/replay").json() == body  # served from the cache

    custom = client.get("/api/replay", params={"min_train": 20}).json()
    assert custom["min_train"] == 20
    assert 0 < custom["summary"]["n_steps"] < body["summary"]["n_steps"]


def test_replay_custom_min_train_cache_invalidated_after_actual(client: TestClient) -> None:
    """A data change must not leave a stale non-default min_train cache behind."""
    before = client.get("/api/replay", params={"min_train": 5}).json()
    assert before["steps"]

    actual = client.post("/api/projects/P001/actual", json={"actual_days": 99})
    assert actual.status_code == 200

    after = client.get("/api/replay", params={"min_train": 5}).json()
    assert after["steps"] != before["steps"]


# --------------------------------------------------------------------------- #
# Actuals (learning loop)
# --------------------------------------------------------------------------- #


def test_enter_actual_p229_returns_coefficients_and_accuracy(client: TestClient) -> None:
    response = client.post("/api/projects/P229/actual", json={"actual_days": 64})
    assert response.status_code == 200
    body = response.json()

    assert PROJECT_CONTRACT_KEYS <= set(body["project"])
    assert body["project"]["project_id"] == "P229"
    assert body["project"]["status"] == "done"
    assert body["project"]["actual_days"] == 64

    updates = body["coefficient_updates"]
    assert {update["feature"] for update in updates} == P229_FEATURES
    for update in updates:
        assert {"feature", "old", "new", "sample_count"} <= set(update)
        assert update["old"] > 0 and update["new"] > 0
        assert update["sample_count"] >= 1
        assert update["n"] == update["sample_count"]

    accuracy = body["accuracy"]
    assert {"mae_before", "mae_after", "coverage_pct"} <= set(accuracy)
    assert accuracy["mae_before"] is not None
    assert accuracy["mae_after"] is not None

    assert body["warning"] is None

    # Persisted: now done, visible with the new actual in the listing.
    p229 = next(
        row for row in client.get("/api/projects").json() if row["project_id"] == "P229"
    )
    assert p229["status"] == "done" and p229["actual_days"] == 64

    # Coefficients now come from the corrections table (still 15 entries).
    coefficients = client.post(
        "/api/estimate", json={"email_text": get_scenario("A")["email_text"]}
    ).json()["coefficients"]
    assert len(coefficients) == 15
    assert all(coefficient["sample_count"] >= 1 for coefficient in coefficients)


@pytest.mark.parametrize("bad_value", [0, -5])
def test_enter_actual_rejects_non_positive(client: TestClient, bad_value: float) -> None:
    response = client.post("/api/projects/P230/actual", json={"actual_days": bad_value})
    assert response.status_code == 422
    assert "lớn hơn 0" in response.json()["detail"]


@pytest.mark.parametrize("bad_literal", ["NaN", "Infinity"])
def test_enter_actual_rejects_non_finite(client: TestClient, bad_literal: str) -> None:
    """NaN/Infinity are not valid durations: reject instead of corrupting state."""
    response = client.post(
        "/api/projects/P232/actual",
        content=f'{{"actual_days": {bad_literal}}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "lớn hơn 0" in response.json()["detail"]

    row = next(
        item
        for item in client.get("/api/projects").json()
        if item["project_id"] == "P232"
    )
    assert row["status"] != "done"  # nothing was persisted


def test_enter_actual_unknown_project_404(client: TestClient) -> None:
    response = client.post("/api/projects/P999/actual", json={"actual_days": 30})
    assert response.status_code == 404
    assert "P999" in response.json()["detail"]


def test_enter_actual_accepts_large_value_with_warning(client: TestClient) -> None:
    response = client.post("/api/projects/P231/actual", json={"actual_days": 1500})
    assert response.status_code == 200
    body = response.json()
    assert body["warning"] == "Giá trị bất thường, vui lòng kiểm tra lại"
    assert body["project"]["actual_days"] == 1500
    assert body["project"]["status"] == "done"


# --------------------------------------------------------------------------- #
# CSV import
# --------------------------------------------------------------------------- #


def test_import_csv_reports_imported_skipped_errors(client: TestClient) -> None:
    content = "\n".join(
        [
            CSV_HEADER,
            _csv_row("P901", "2026-01-05", "40", "35", "done", "Imported CRM integration project", ("third_party_api",)),
            _csv_row("P001", "2026-01-06", "30", "25", "done", "Duplicate id, must be skipped"),
            _csv_row("P902", "2026-01-07", "", "20", "done", "Missing actual, must be skipped"),
        ]
    )
    response = _upload(client, content)
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == 2
    assert len(body["errors"]) == 2
    assert "đã tồn tại" in body["errors"][0]
    assert "actual_days" in body["errors"][1]

    p901 = next(
        row for row in client.get("/api/projects").json() if row["project_id"] == "P901"
    )
    assert p901["status"] == "done"
    assert p901["actual_days"] == 40
    assert p901["features"]["third_party_api"] == 1


def test_import_csv_malformed_rejected(client: TestClient) -> None:
    response = _upload(client, "project_id,date\nP903,2026-01-01\n")
    assert response.status_code == 422
    assert "thiếu cột bắt buộc" in response.json()["detail"]

    empty = _upload(client, b"", name="empty.csv")
    assert empty.status_code == 422
    assert "CSV" in empty.json()["detail"]


def test_import_csv_invalid_numeric_feature_value_skipped(client: TestClient) -> None:
    """A numeric feat_* cell outside {0,1} must be skipped, never stored verbatim."""
    features = ["2" if name == "third_party_api" else "0" for name in FEATURES]
    row = ",".join(
        ["P905", "2026-02-01", "20", "18", "done", "0", "bad feature value", *features]
    )
    response = _upload(client, "\n".join([CSV_HEADER, row]))
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 0
    assert body["skipped"] == 1
    assert "feat_third_party_api" in body["errors"][0]
    assert all(
        item["project_id"] != "P905" for item in client.get("/api/projects").json()
    )


def test_import_csv_unparseable_numbers_do_not_abort_the_import(client: TestClient) -> None:
    """Bad numeric cells are reported per row (or stored as NULL), never a 422."""
    # done row with an unparseable actual_days -> clean per-row skip.
    bad_actual = _csv_row("P906", "2026-02-02", "abc", "18", "done", "bad actual")
    response = _upload(client, "\n".join([CSV_HEADER, bad_actual]))
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 0 and body["skipped"] == 1
    assert "actual_days" in body["errors"][0]

    # non-finite actual_days (1e400 parses as inf) is skipped too.
    inf_actual = _csv_row("P907", "2026-02-03", "1e400", "18", "done", "inf actual")
    inf_body = _upload(client, "\n".join([CSV_HEADER, inf_actual])).json()
    assert inf_body["imported"] == 0 and inf_body["skipped"] == 1

    # unparseable team_estimate -> row imported with NULL team_estimate.
    bad_team = _csv_row("P908", "2026-02-04", "20", "abc", "done", "bad team")
    team_body = _upload(client, "\n".join([CSV_HEADER, bad_team])).json()
    assert team_body["imported"] == 1
    row = next(
        item for item in client.get("/api/projects").json() if item["project_id"] == "P908"
    )
    assert row["team_estimate"] is None


def test_import_csv_empty_cells_are_null_not_nan_strings(client: TestClient) -> None:
    """Empty date/email cells must not become the literal string 'nan'."""
    features = ",".join("0" for _ in FEATURES)
    row = ",".join(["P909", "", "20", "18", "done", "0", "", features])
    response = _upload(client, "\n".join([CSV_HEADER, row]))
    assert response.status_code == 200
    assert response.json()["imported"] == 1

    imported = next(
        item for item in client.get("/api/projects").json() if item["project_id"] == "P909"
    )
    assert imported["date"] is None
    assert imported["summary"] == ""


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #


def test_scenarios_list_and_load(client: TestClient) -> None:
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert [scenario["id"] for scenario in scenarios] == ["A", "B", "C"]
    for scenario in scenarios:
        assert {"id", "title", "email_text", "notes"} <= set(scenario)
        assert len(scenario["email_text"].split()) >= 150

    load = client.post("/api/scenarios/A/load")
    assert load.status_code == 200
    body = load.json()
    assert ESTIMATE_CONTRACT_KEYS <= set(body)
    assert len(body["findings"]) == 15
    assert body["estimate"]["mode"] == "calibrated"
    by_name = {finding["name"]: finding["value"] for finding in body["findings"]}
    assert by_name["payment_gateway"] == 1 and by_name["pci_dss"] == 1

    missing = client.post("/api/scenarios/Z/load")
    assert missing.status_code == 404


# --------------------------------------------------------------------------- #
# A/B comparison
# --------------------------------------------------------------------------- #


def test_ab_simulated_with_stub_provider(client: TestClient) -> None:
    response = client.post(
        "/api/ab", json={"email_text": get_scenario("C")["email_text"], "n": 6}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "simulated"
    assert len(body["values"]) == 6
    assert body["mean"] > 0 and body["std"] >= 0
    assert body["min"] <= body["mean"] <= body["max"]
    assert body["system_estimate"] is not None
    assert body["delta_pct"] is not None
    assert "SIMULATED" in body["note"]


# --------------------------------------------------------------------------- #
# Cold start (own empty DB, seeding disabled)
# --------------------------------------------------------------------------- #


def test_cold_start_health_estimate_and_actual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ESTIMATOR_DB_PATH", str(tmp_path / "cold.db"))
    monkeypatch.setenv("ESTIMATOR_AUTO_SEED", "0")
    from app.main import create_app

    with TestClient(create_app()) as cold:
        health = cold.get("/api/health").json()
        assert health["model_loaded"] is False
        assert health["mode"] == "cold_start"
        assert health["projects_count"] == 0

        response = cold.post("/api/estimate", json={"email_text": SCENARIOS[0]["email_text"]})
        assert response.status_code == 200
        body = response.json()
        assert body["project_id"] == "P001"
        assert body["estimate"]["mode"] == "cold_start"
        assert len(body["findings"]) == 15
        assert body["similar_projects"] == []  # no history to compare against
        assert len(body["coefficients"]) == 15
        assert all(coefficient["source"] == "cold_start" for coefficient in body["coefficients"])

        # Entering one actual must not crash retraining (spec §9: keep old model).
        actual = cold.post("/api/projects/P001/actual", json={"actual_days": 30})
        assert actual.status_code == 200
        payload = actual.json()
        assert payload["accuracy"]["mae_before"] is None
        assert payload["accuracy"]["mae_after"] is not None


# --------------------------------------------------------------------------- #
# Contract v0.2: answers + MC intervals
# --------------------------------------------------------------------------- #


def test_estimate_with_answers_refines_interval_without_persisting(
    client: TestClient,
) -> None:
    email_text = get_scenario("A")["email_text"]
    direct = client.post("/api/estimate", json={"email_text": email_text})
    assert direct.status_code == 200
    body = direct.json()
    missing = [finding["name"] for finding in body["findings"] if finding["value"] is None]
    assert missing  # the stub leaves scenario A unknowns open
    assert body["missing"] == missing
    assert body["project_id"] is not None  # direct call persists (v0.1 behaviour)

    first_estimate = body["estimate"]
    assert first_estimate["method"] == "mc"  # unknowns remain -> Monte Carlo
    assert first_estimate["mode"] == "calibrated"
    width_before = round(first_estimate["p90"] - first_estimate["p10"], 1)

    count_before = client.get("/api/health").json()["projects_count"]

    # Partial answer: the feature becomes known, missing shrinks, still MC.
    first = missing[0]
    partial = client.post(
        "/api/estimate", json={"email_text": email_text, "answers": {first: 1}}
    ).json()
    assert partial["project_id"] is None
    assert first not in partial["missing"]
    assert len(partial["missing"]) == len(missing) - 1
    by_name = {finding["name"]: finding["value"] for finding in partial["findings"]}
    assert by_name[first] == 1
    assert partial["estimate"]["method"] == "mc"

    # Full answers: every feature known -> point estimate whose interval is
    # narrower than the MC interval computed with the unknowns open.
    answers = {name: 0 for name in missing}
    full = client.post(
        "/api/estimate", json={"email_text": email_text, "answers": answers}
    ).json()
    assert full["project_id"] is None
    assert full["missing"] == []
    assert full["estimate"]["method"] == "point"
    assert full["estimate"]["mode"] == "calibrated"
    width_after = round(full["estimate"]["p90"] - full["estimate"]["p10"], 1)
    assert width_after <= width_before

    # v0.1 contract keys survive on every variant.
    assert ESTIMATE_CONTRACT_KEYS <= set(body)
    assert ESTIMATE_CONTRACT_KEYS <= set(partial)
    assert ESTIMATE_CONTRACT_KEYS <= set(full)

    # Neither refinement call persisted a project row (side-effect free).
    assert client.get("/api/health").json()["projects_count"] == count_before


def test_estimate_answers_validation(client: TestClient) -> None:
    email_text = get_scenario("A")["email_text"]
    bad_name = client.post(
        "/api/estimate", json={"email_text": email_text, "answers": {"not_a_feature": 1}}
    )
    assert bad_name.status_code == 422
    assert "not_a_feature" in bad_name.json()["detail"]

    bad_value = client.post(
        "/api/estimate", json={"email_text": email_text, "answers": {"pci_dss": 2}}
    )
    assert bad_value.status_code == 422
    assert "pci_dss" in bad_value.json()["detail"]


def test_estimate_stream_accepts_answers_without_persisting(client: TestClient) -> None:
    email_text = get_scenario("B")["email_text"]
    direct = client.post("/api/estimate", json={"email_text": email_text}).json()
    count_before = client.get("/api/health").json()["projects_count"]

    answers = {name: 0 for name in direct["missing"]}
    with client.stream(
        "POST", "/api/estimate/stream", json={"email_text": email_text, "answers": answers}
    ) as response:
        assert response.status_code == 200
        payload = "".join(response.iter_text())

    results = [data for event, data in parse_sse(payload) if event == "result"]
    assert len(results) == 1
    result = results[0]
    assert result["missing"] == []
    assert result["estimate"]["method"] == "point"
    assert result["project_id"] is None
    assert client.get("/api/health").json()["projects_count"] == count_before


# --------------------------------------------------------------------------- #
# Contract v0.2: budget-fit packages
# --------------------------------------------------------------------------- #


def test_packages_contract_shape_and_tier_ordering(client: TestClient) -> None:
    response = client.post(
        "/api/packages",
        json={"email_text": get_scenario("A")["email_text"], "budget_days": 200},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["budget_days"] == 200
    assert body["method"] in {"mc", "point"}
    assert body["recommendation"] in {"core", "standard", "full"}
    assert body["provider"] == "stub"

    packages = body["packages"]
    assert [package["tier"] for package in packages] == ["core", "standard", "full"]
    for package in packages:
        assert {
            "tier",
            "label",
            "estimate",
            "over_budget_prob",
            "features_included",
            "excluded",
            "notes",
        } <= set(package)
        estimate = package["estimate"]
        assert {"p10", "p50", "p90", "mode", "unit", "method"} <= set(estimate)
        assert estimate["p10"] <= estimate["p50"] <= estimate["p90"]
        assert estimate["unit"] == "days"
        assert 0.0 <= package["over_budget_prob"] <= 1.0
        assert set(package["features_included"]) == set(FEATURES)
        assert all(
            value in (0, 1, None) for value in package["features_included"].values()
        )
        assert isinstance(package["excluded"], list)
        assert package["notes"]

    # More scope -> never fewer estimated days (floors may tie tiers).
    p50s = [package["estimate"]["p50"] for package in packages]
    assert p50s == sorted(p50s)


def test_packages_includes_pricing_curve(client: TestClient) -> None:
    email = get_scenario("A")["email_text"]
    response = client.post("/api/packages", json={"email_text": email, "budget_days": 200})
    assert response.status_code == 200
    body = response.json()

    pricing = body["pricing"]
    assert set(pricing) == {
        "scope",
        "p10",
        "p50",
        "p90",
        "curve",
        "safe_quote_25",
        "safe_quote_10",
    }
    assert pricing["scope"] == "full"
    full = next(package for package in body["packages"] if package["tier"] == "full")
    assert (pricing["p10"], pricing["p50"], pricing["p90"]) == (
        full["estimate"]["p10"],
        full["estimate"]["p50"],
        full["estimate"]["p90"],
    )

    curve = pricing["curve"]
    assert len(curve) == 25
    days = [point["days"] for point in curve]
    probs = [point["over_prob"] for point in curve]
    assert days == sorted(days)
    assert probs == sorted(probs, reverse=True)  # more days -> lower risk
    assert all(0.001 <= probability <= 0.999 for probability in probs)
    assert pricing["safe_quote_10"] > pricing["safe_quote_25"] > pricing["p50"]

    # At a quote that is exactly a curve day, Full tier and curve agree.
    day = curve[12]["days"]
    second = client.post(
        "/api/packages", json={"email_text": email, "budget_days": day}
    ).json()
    full_second = next(
        package for package in second["packages"] if package["tier"] == "full"
    )
    assert second["pricing"]["curve"][12]["over_prob"] == full_second["over_budget_prob"]


def test_packages_budget_validation(client: TestClient) -> None:
    payload_base = {"email_text": get_scenario("A")["email_text"]}
    for bad_budget in (0, -25):
        response = client.post("/api/packages", json={**payload_base, "budget_days": bad_budget})
        assert response.status_code == 422
        assert "lớn hơn 0" in response.json()["detail"]

    missing_budget = client.post("/api/packages", json=payload_base)
    assert missing_budget.status_code == 422
    assert "lớn hơn 0" in missing_budget.json()["detail"]


def test_packages_cold_start_returns_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ESTIMATOR_DB_PATH", str(tmp_path / "cold_packages.db"))
    monkeypatch.setenv("ESTIMATOR_AUTO_SEED", "0")
    from app.main import create_app

    with TestClient(create_app()) as cold:
        response = cold.post(
            "/api/packages",
            json={"email_text": SCENARIOS[0]["email_text"], "budget_days": 60},
        )
        assert response.status_code == 409
        assert "cold start" in response.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# Contract v0.2: AB history baseline
# --------------------------------------------------------------------------- #


def test_ab_includes_history_baseline(client: TestClient) -> None:
    scenario_email = get_scenario("C")["email_text"]
    response = client.post(
        "/api/ab", json={"email_text": scenario_email, "n": 4, "history_n": 3}
    )
    assert response.status_code == 200
    body = response.json()
    # All v0.1 keys are unchanged.
    assert {
        "mode",
        "values",
        "mean",
        "std",
        "min",
        "max",
        "system_estimate",
        "delta_pct",
        "note",
    } <= set(body)

    baseline = body["baseline_history"]
    assert baseline["mode"] == "simulated"  # stub provider stays flagged
    assert baseline["n"] == 3
    assert len(baseline["values"]) == 3
    assert baseline["mean"] > 0 and baseline["std"] >= 0
    assert baseline["min"] <= baseline["mean"] <= baseline["max"]
    assert "SIMULATED" in baseline["note"]

    # history_n defaults to 3 when the body omits it.
    default = client.post(
        "/api/ab", json={"email_text": scenario_email, "n": 2}
    ).json()
    assert default["baseline_history"]["n"] == 3


# --------------------------------------------------------------------------- #
# Contract v0.2: demo data reset
# --------------------------------------------------------------------------- #


def test_reset_restores_pristine_demo_db(client: TestClient) -> None:
    extra = client.post("/api/estimate", json={"email_text": get_scenario("C")["email_text"]})
    assert extra.status_code == 200 and extra.json()["project_id"]
    assert client.get("/api/health").json()["projects_count"] > 240

    response = client.post("/api/reset")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "projects_count": 240}

    health = client.get("/api/health").json()
    assert health["projects_count"] == 240
    assert health["model_loaded"] is True
    assert len(client.get("/api/projects").json()) == 240

    # Idempotent: a second reset also lands on the pristine 240.
    assert client.post("/api/reset").json() == {"status": "ok", "projects_count": 240}


# --------------------------------------------------------------------------- #
# Contract v0.2: codebase context (Codebase Lab, docs/API.md)
# --------------------------------------------------------------------------- #

#: Exact contract keys of the `codebase` block (docs/API.md v0.2).
CODEBASE_CONTRACT_KEYS = {
    "repo",
    "language",
    "friction",
    "invasiveness",
    "similar_changes",
    "base_estimate",
    "adjusted_estimate",
    "adjustments",
    "note",
}
FRICTION_COMPONENT_KEYS = {
    "churn",
    "fan_in",
    "complexity",
    "coverage_gap",
    "author_concentration",
}
SIMILAR_CHANGE_KEYS = {"commit", "date", "files_touched", "new_files", "modified_files"}
#: Verbatim honest-limitations note frozen in docs/API.md v0.2.
CODEBASE_NOTE = (
    "DEMO-ASSUMED coefficients; the similar-past-changes mechanism is validated "
    "on 29k real commits (docs/CODEBASE_HISTORY_VALIDATION.md); no "
    "text-prediction accuracy claim (docs/CODEBASE_VALIDATION.md). "
    "One-directional by design: surcharge only, never a discount."
)


@pytest.fixture(scope="module")
def demo_repos_env(tmp_path_factory: pytest.TempPathFactory):
    """Build both demo repos once per session into a tmp dir (no real data/).

    ``ESTIMATOR_DEMO_REPOS_DIR`` points the API at this directory; the module
    teardown restores the previous value. Repos are built with the deterministic
    builder (identical commit hashes on every rebuild).
    """
    from scripts.build_demo_repos import build_demo_repos

    root = tmp_path_factory.mktemp("demo_repos")
    build_demo_repos(root)
    previous = os.environ.get("ESTIMATOR_DEMO_REPOS_DIR")
    os.environ["ESTIMATOR_DEMO_REPOS_DIR"] = str(root)
    try:
        yield root
    finally:
        if previous is None:
            os.environ.pop("ESTIMATOR_DEMO_REPOS_DIR", None)
        else:
            os.environ["ESTIMATOR_DEMO_REPOS_DIR"] = previous


def _assert_estimate_shape(estimate: dict) -> None:
    assert {"p10", "p50", "p90", "unit", "mode", "method"} <= set(estimate)
    assert estimate["unit"] == "days"
    assert estimate["p10"] <= estimate["p50"] <= estimate["p90"]


def test_estimate_repo_demo_a_codebase_block_shape(
    client: TestClient, demo_repos_env: Path
) -> None:
    email_text = get_scenario("A")["email_text"]
    response = client.post("/api/estimate", json={"email_text": email_text, "repo": "demo_a"})
    assert response.status_code == 200
    body = response.json()
    assert ESTIMATE_CONTRACT_KEYS <= set(body)

    codebase = body["codebase"]
    assert set(codebase) == CODEBASE_CONTRACT_KEYS
    assert codebase["repo"] == "demo_a"

    friction = codebase["friction"]
    assert set(friction) == {"score", "level", "components"}
    assert 0.0 <= friction["score"] <= 1.0
    assert friction["level"] in {"low", "medium", "high"}
    assert set(friction["components"]) == FRICTION_COMPONENT_KEYS

    invasiveness = codebase["invasiveness"]
    assert set(invasiveness) == {"modified_ratio", "mean_files_touched", "based_on_commits"}
    assert invasiveness["based_on_commits"] >= 1
    assert 0.0 <= invasiveness["modified_ratio"] <= 1.0
    assert invasiveness["mean_files_touched"] >= 1

    changes = codebase["similar_changes"]
    assert 1 <= len(changes) <= 5  # capped at the 5 newest for the UI
    today = datetime.now(timezone.utc).date().isoformat()
    for change in changes:
        assert set(change) == SIMILAR_CHANGE_KEYS
        assert len(change["commit"]) == 7
        assert change["date"] < today  # leakage guard: strictly before at_date
        assert change["new_files"] + change["modified_files"] <= change["files_touched"]

    _assert_estimate_shape(codebase["base_estimate"])
    _assert_estimate_shape(codebase["adjusted_estimate"])
    # The top-level estimate IS the adjusted estimate (contract v0.2).
    assert body["estimate"] == codebase["adjusted_estimate"]
    # One-directional: never a discount (p10 down-or-equal, p90 up-or-equal).
    assert codebase["adjusted_estimate"]["p10"] <= codebase["base_estimate"]["p10"]
    assert codebase["adjusted_estimate"]["p90"] >= codebase["base_estimate"]["p90"]

    adjustments = codebase["adjustments"]
    assert adjustments
    for adjustment in adjustments:
        assert {"what", "factor", "why"} <= set(adjustment)
        assert adjustment["factor"] > 0
        assert adjustment["why"]
    assert codebase["note"] == CODEBASE_NOTE


def test_estimate_repo_demo_b_adjusts_more_than_demo_a(
    client: TestClient, demo_repos_env: Path
) -> None:
    email_text = get_scenario("A")["email_text"]
    a = client.post("/api/estimate", json={"email_text": email_text, "repo": "demo_a"}).json()
    b = client.post("/api/estimate", json={"email_text": email_text, "repo": "demo_b"}).json()

    a_block = a["codebase"]
    b_block = b["codebase"]
    # Same email + same model state -> identical base estimate for both repos.
    assert b_block["base_estimate"] == a_block["base_estimate"]

    # Spaghetti is structurally messier than the plugin repo.
    assert b_block["friction"]["score"] > a_block["friction"]["score"]
    assert b_block["invasiveness"]["modified_ratio"] > a_block["invasiveness"]["modified_ratio"]

    # demo_b really moves the estimate (invasiveness shifts the median) ...
    assert b_block["adjusted_estimate"] != b_block["base_estimate"]
    assert b_block["adjusted_estimate"]["p50"] > b_block["base_estimate"]["p50"]
    # ... and its upper tail is at least as wide as demo_a's.
    assert b_block["adjusted_estimate"]["p90"] >= a_block["adjusted_estimate"]["p90"]
    assert b["estimate"]["p90"] == b_block["adjusted_estimate"]["p90"]


def test_estimate_unknown_repo_rejected_with_vietnamese_detail(client: TestClient) -> None:
    email_text = get_scenario("A")["email_text"]
    response = client.post("/api/estimate", json={"email_text": email_text, "repo": "demo_c"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "demo_c" in detail
    assert "demo_a" in detail and "demo_b" in detail and "self" in detail

    stream = client.post(
        "/api/estimate/stream", json={"email_text": email_text, "repo": "nope"}
    )
    assert stream.status_code == 422


def test_estimate_without_repo_has_no_codebase_block(client: TestClient) -> None:
    """Backward compatibility: `repo` absent -> the response shape is unchanged."""
    email_text = get_scenario("B")["email_text"]
    body = client.post("/api/estimate", json={"email_text": email_text}).json()
    assert ESTIMATE_CONTRACT_KEYS <= set(body)
    assert "codebase" not in body


def test_estimate_repo_refinement_reapplies_codebase(
    client: TestClient, demo_repos_env: Path
) -> None:
    email_text = get_scenario("A")["email_text"]
    direct = client.post(
        "/api/estimate", json={"email_text": email_text, "repo": "demo_b"}
    ).json()
    missing = [finding["name"] for finding in direct["findings"] if finding["value"] is None]
    assert missing
    answers = {name: 0 for name in missing}
    count_before = client.get("/api/health").json()["projects_count"]

    refined = client.post(
        "/api/estimate",
        json={"email_text": email_text, "repo": "demo_b", "answers": answers},
    ).json()
    assert refined["project_id"] is None  # answer-refinement stays side-effect free
    assert refined["missing"] == []
    assert refined["estimate"]["method"] == "point"
    assert refined["codebase"]["repo"] == "demo_b"
    assert refined["estimate"] == refined["codebase"]["adjusted_estimate"]
    assert refined["codebase"]["adjusted_estimate"] != refined["codebase"]["base_estimate"]
    assert client.get("/api/health").json()["projects_count"] == count_before


def test_estimate_stream_with_repo_includes_codebase(
    client: TestClient, demo_repos_env: Path
) -> None:
    email_text = get_scenario("A")["email_text"]
    with client.stream(
        "POST", "/api/estimate/stream", json={"email_text": email_text, "repo": "demo_b"}
    ) as response:
        assert response.status_code == 200
        payload = "".join(response.iter_text())

    events = parse_sse(payload)
    steps = [data["step"] for event, data in events if event == "step"]
    assert steps == ["extracting", "validating", "similar", "estimating", "questions", "done"]
    results = [data for event, data in events if event == "result"]
    assert len(results) == 1
    result = results[0]
    assert set(result["codebase"]) == CODEBASE_CONTRACT_KEYS
    assert result["codebase"]["repo"] == "demo_b"
    assert result["estimate"] == result["codebase"]["adjusted_estimate"]


def test_estimate_repo_builds_demo_repos_on_demand(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing demo repo is built by the API itself (subprocess + lock)."""
    fresh = tmp_path / "fresh_demo_repos"
    monkeypatch.setenv("ESTIMATOR_DEMO_REPOS_DIR", str(fresh))
    assert not fresh.exists()

    response = client.post(
        "/api/estimate", json={"email_text": get_scenario("A")["email_text"], "repo": "demo_b"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["codebase"]["repo"] == "demo_b"
    assert (fresh / "payment_spaghetti").is_dir()
    assert body["codebase"]["similar_changes"]  # the built repo has matching history


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #


def test_parallel_persist_estimate_allocates_unique_ids(tmp_path: Path) -> None:
    """Concurrent direct estimates must never collide on the P0nn id (500 race)."""
    from concurrent.futures import ThreadPoolExecutor

    from app.api import state as state_mod
    from app.db.database import init_db
    from app.services.extraction import extract_features
    from app.services.providers import StubProvider

    db_path = tmp_path / "parallel.db"
    init_db(db_path)
    state = state_mod.AppState(db_path=db_path)
    email_text = "Parallel persistence probe with payments and a mobile app."
    extraction = extract_features(email_text, provider=StubProvider())
    prediction = {"p10": 10.0, "p50": 20.0, "p90": 30.0}

    def persist(_: int) -> str:
        return state_mod.persist_estimate(state, email_text, extraction, prediction)

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(persist, range(8)))

    assert len(ids) == len(set(ids)) == 8
    assert sorted(ids) == [f"P{index:03d}" for index in range(1, 9)]
    assert state.project_count() == 8


# --------------------------------------------------------------------------- #
# Final QA fixes: delta_pct semantics, pinned demo date, broken repos
# --------------------------------------------------------------------------- #


def test_delta_pct_is_actual_vs_system(client: TestClient) -> None:
    """Contract (docs/API.md): delta_pct = (actual - system P50)/system P50."""
    rows = client.get("/api/projects").json()
    checked = 0
    for row in rows:
        if row["actual_days"] is None or row["system_p50"] in (None, 0):
            continue
        expected = round(
            (float(row["actual_days"]) - float(row["system_p50"])) / float(row["system_p50"]) * 100.0,
            1,
        )
        assert row["delta_pct"] == pytest.approx(expected, abs=0.05)
        assert row["actual_vs_system_pct"] == pytest.approx(expected, abs=0.05)
        if row["team_estimate"]:
            bias = round(
                (float(row["system_p50"]) - float(row["team_estimate"]))
                / float(row["team_estimate"])
                * 100.0,
                1,
            )
            assert row["system_vs_team_pct"] == pytest.approx(bias, abs=0.05)
        checked += 1
    assert checked >= 5  # the seeded history has plenty of done rows


def test_delta_pct_null_without_actual(client: TestClient) -> None:
    rows = client.get("/api/projects").json()
    pending = [row for row in rows if row["status"] != "done"]
    assert pending
    assert all(row["delta_pct"] is None for row in pending)


def test_broken_demo_repo_degrades_gracefully(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A demo-repo directory without .git must not kill the estimate.

    The estimate does not depend on the repository, so the response stays 200:
    no ``codebase`` block and a ``codebase_error`` explaining what happened
    (DECISIONS D20 — a codebase problem is never fatal).
    """
    broken_root = tmp_path / "broken_demo_repos"
    (broken_root / "payment_plugin").mkdir(parents=True)  # exists but is not a git repo
    monkeypatch.setenv("ESTIMATOR_DEMO_REPOS_DIR", str(broken_root))

    response = client.post(
        "/api/estimate", json={"email_text": get_scenario("A")["email_text"], "repo": "demo_a"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "codebase" not in body
    assert "git repository" in body["codebase_error"]
    assert body["estimate"]["p50"] > 0  # the estimate itself still works


def test_repo_selector_accepts_public_github_forms() -> None:
    from app.api import state as state_mod

    for raw in (
        "https://github.com/pallets/flask",
        "https://github.com/pallets/flask.git",
        "https://github.com/pallets/flask/",
        "github.com/pallets/flask",
        "pallets/flask",
        "Pallets/Flask",
    ):
        assert state_mod.normalize_repo_selector(raw) == "gh:pallets/flask"
    # built-in choices pass through unchanged
    for raw in ("demo_a", "demo_b", "self"):
        assert state_mod.normalize_repo_selector(raw) == raw


def test_repo_selector_rejects_non_github_targets() -> None:
    """SSRF guard: only github.com/<owner>/<repo> is ever accepted."""
    from app.api import state as state_mod

    for raw in (
        "http://github.com/pallets/flask",          # plain http
        "https://evil.com/pallets/flask",           # other host
        "https://github.com.evil.com/a/b",          # suffix trick
        "https://user:pw@github.com/a/b",           # userinfo
        "https://github.com:8443/a/b",              # port
        "https://github.com/a/b?x=1",               # query
        "https://github.com/a/b#frag",              # fragment
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://localhost:8000/a/b",
        "ssh://git@github.com/a/b",
        "https://github.com/a",                     # missing repo
        "a/b/c",
    ):
        with pytest.raises(ValueError):
            state_mod.normalize_repo_selector(raw)


def test_estimate_rejects_invalid_repo_selector(client: TestClient) -> None:
    response = client.post(
        "/api/estimate",
        json={"email_text": get_scenario("A")["email_text"], "repo": "https://evil.com/a/b"},
    )
    assert response.status_code == 422
    assert "repo không hợp lệ" in response.json()["detail"]


def test_repo_selector_accepts_example_ids() -> None:
    from app.api import state as state_mod

    for example_id in state_mod.CODEBASE_EXAMPLE_REPOS:
        assert state_mod.normalize_repo_selector(example_id) == example_id
    with pytest.raises(ValueError):
        state_mod.normalize_repo_selector("ex_not_a_real_example")


def test_available_examples_lists_only_fetched_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The UI must offer only examples that are actually on disk (build-time fetch)."""
    from app.api import state as state_mod

    root = tmp_path / "example_repos"
    monkeypatch.setenv(state_mod.CODEBASE_EXAMPLE_REPOS_DIR_ENV, str(root))
    assert state_mod.available_examples() == []

    (root / "pallets__flask" / ".git").mkdir(parents=True)
    (root / state_mod.CODEBASE_EXAMPLE_MANIFEST).write_text(
        '{"ex_flask": {"pinned_date": "2026-10-07"}}', encoding="utf-8"
    )
    available = state_mod.available_examples()
    assert [item["id"] for item in available] == ["ex_flask"]
    assert available[0]["label"] == "Flask"
    assert available[0]["lang"] == "Python"
    assert available[0]["pinned_date"] == "2026-10-07"
    assert state_mod.example_pinned_date("ex_flask") == "2026-10-07"


def test_missing_example_repo_degrades_gracefully(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unfetched example must not kill the estimate (D20/D23)."""
    from app.api import state as state_mod

    monkeypatch.setenv(state_mod.CODEBASE_EXAMPLE_REPOS_DIR_ENV, str(tmp_path / "empty"))
    response = client.post(
        "/api/estimate",
        json={"email_text": get_scenario("A")["email_text"], "repo": "ex_flask"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "codebase" not in body
    assert "chưa được tải" in body["codebase_error"]
    assert body["estimate"]["p50"] > 0


def test_non_python_repo_is_refused_cleanly(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codebase Lab is Python-only: a C repo is refused, not mis-scored (D24).

    Before this gate, cJSON (2 stray .py test scripts out of 229 files) reported
    ``complexity`` 0.75 as if it described the whole repository.
    """
    from scripts.build_demo_repos import ALICE, _commit, _init_repo, _write

    root = tmp_path / "c_demo_repos"
    repo = root / "payment_plugin"
    _init_repo(repo)
    for i in range(5):
        _write(repo, f"src/f{i}.c", "int f(void){return 0;}\n")
    _write(repo, "tests/helper.py", "print('x')\n")  # stray Python must not win
    _commit(repo, "2026-01-05", ALICE, "c library")
    monkeypatch.setenv("ESTIMATOR_DEMO_REPOS_DIR", str(root))

    response = client.post(
        "/api/estimate", json={"email_text": get_scenario("A")["email_text"], "repo": "demo_a"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "codebase" not in body
    assert "chỉ phân tích repo Python" in body["codebase_error"]
    assert "C" in body["codebase_error"]
    assert body["estimate"]["p50"] > 0


def test_codebase_block_reports_language(
    client: TestClient, demo_repos_env: Path
) -> None:
    """The block says which language was analysed (Python-only scope, D24)."""
    response = client.post(
        "/api/estimate",
        json={"email_text": get_scenario("A")["email_text"], "repo": "demo_a"},
    )
    language = response.json()["codebase"]["language"]
    assert language["dominant"] == "Python"
    assert language["python_files"] > 0
    assert language["python_share"] == pytest.approx(1.0)


def test_health_reports_codebase_capabilities(client: TestClient) -> None:
    """The UI hides options the deployment cannot serve (D17: no .git in cloud)."""
    body = client.get("/api/health").json()
    assert body["codebase"]["choices"] == ["demo_a", "demo_b", "self"]
    assert body["codebase"]["self_available"] is True  # a full checkout in tests
    assert body["codebase"]["url_clone"] is True
    # Example list depends on whether the image was built with the fetch step,
    # so only its shape is contractual — never a count.
    assert isinstance(body["codebase"]["examples"], list)


def test_public_repo_clone_is_full_and_hardened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The clone must be FULL (numstat needs blobs) and hardened, and cached.

    A blobless clone makes ``git log --raw --numstat`` re-fetch every commit over
    the network (measured 221 s vs ~1 s); the hardening flags stop a public,
    unauthenticated endpoint from hanging on credentials or following redirects.
    """
    from app.api import state as state_mod

    cache = tmp_path / "repo_cache"
    monkeypatch.setenv(state_mod.CODEBASE_REPO_CACHE_DIR_ENV, str(cache))

    calls: list[list[str]] = []
    envs: list[dict[str, str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN202
        calls.append(list(cmd))
        envs.append(dict(kwargs.get("env") or {}))
        target = Path(cmd[-1])
        (target / ".git").mkdir(parents=True, exist_ok=True)
        return _Proc()

    monkeypatch.setattr(state_mod.subprocess, "run", fake_run)
    path = state_mod.clone_github_repo("pallets", "flask")

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "git"
    assert "--filter=blob:none" not in cmd  # full clone: numstat needs blobs
    assert "--single-branch" in cmd
    assert "--no-recurse-submodules" in cmd
    assert "http.followRedirects=false" in cmd
    assert "https://github.com/pallets/flask.git" in cmd
    assert envs[0]["GIT_TERMINAL_PROMPT"] == "0"  # never hang on credentials
    assert envs[0]["GIT_CONFIG_NOSYSTEM"] == "1"
    assert (path / state_mod.CODEBASE_CLONE_FORMAT_MARKER).exists()

    # a second call reuses the cached clone (no new git process)
    again = state_mod.clone_github_repo("pallets", "flask")
    assert again == path
    assert len(calls) == 1


def test_demo_repo_analysis_uses_pinned_reference_date(
    client: TestClient, demo_repos_env: Path
) -> None:
    """Demo repos are frozen artifacts: friction must not decay over time."""
    from app.api import state as state_mod

    features = {name: 0 for name in FEATURES}
    features["payment_gateway"] = 1
    features["third_party_api"] = 1
    base = {"p10": 10.0, "p50": 20.0, "p90": 40.0}

    block_a1 = state_mod.build_codebase_block("demo_a", features, base)
    block_a2 = state_mod.build_codebase_block("demo_a", features, base)
    block_b = state_mod.build_codebase_block("demo_b", features, base)

    assert block_a1["friction"]["score"] == block_a2["friction"]["score"]  # deterministic
    assert block_b["friction"]["score"] > block_a1["friction"]["score"]  # messy > clean
    assert block_a1["friction"]["level"] != block_b["friction"]["level"]
