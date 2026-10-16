"""API integration tests (FastAPI TestClient over temporary SQLite databases).

The module-scoped ``client`` fixture boots the real app against a temp DB
seeded from the repo's synthetic CSV (``ESTIMATOR_DB_PATH`` isolation); the
cold-start test builds its own client with ``ESTIMATOR_AUTO_SEED=0``. All
tests run offline against the deterministic stub provider.
"""

from __future__ import annotations

import json
import os
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
