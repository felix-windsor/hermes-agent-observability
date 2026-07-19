from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def fresh_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_OBSERVABILITY_DATA_DIR", str(tmp_path / "data"))
    import collector.store as store
    import server.main as main

    importlib.reload(store)
    importlib.reload(main)
    store.seed_sample_data(force=True)
    return main.app, store


def test_overview_contains_sample_data(monkeypatch, tmp_path):
    app, _store = fresh_app(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/api/overview?range=24h")

    assert response.status_code == 200
    data = response.json()
    assert data["totals"]["events"] > 0
    assert data["totals"]["traces"] > 0
    assert data["tools"]
    assert data["failure_categories"]
    assert any(item["id"] == "permission" for item in data["scenarios"])


def test_trace_detail_returns_timeline(monkeypatch, tmp_path):
    app, _store = fresh_app(monkeypatch, tmp_path)
    client = TestClient(app)
    overview = client.get("/api/overview?range=24h").json()
    trace_id = overview["traces"][0]["trace_id"]

    response = client.get(f"/api/traces/{trace_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["summary"]["events"] == len(detail["events"])
    assert detail["events"][0]["created_at"] <= detail["events"][-1]["created_at"]
    assert detail["summary"]["user_request"]
    assert detail["summary"]["scenario_label"]


def test_range_filter_and_export(monkeypatch, tmp_path):
    app, _store = fresh_app(monkeypatch, tmp_path)
    client = TestClient(app)

    one_hour = client.get("/api/overview?range=1h").json()
    all_time = client.get("/api/overview?range=all").json()
    export = client.get("/api/export?range=24h&scenario=permission&limit=10").json()
    download = client.get("/api/export/download?range=24h&scenario=permission&limit=10")

    assert all_time["totals"]["events"] >= one_hour["totals"]["events"]
    assert export["path"].endswith(".json")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")
    assert "attachment" in download.headers["content-disposition"]
    assert "permission-24h" in download.headers["content-disposition"]


def test_scenario_filter_focuses_dashboard(monkeypatch, tmp_path):
    app, _store = fresh_app(monkeypatch, tmp_path)
    client = TestClient(app)

    all_data = client.get("/api/overview?range=24h&scenario=all").json()
    permission = client.get("/api/overview?range=24h&scenario=permission").json()

    assert permission["totals"]["events"] < all_data["totals"]["events"]
    assert permission["totals"]["traces"] == 1
    assert permission["traces"][0]["task_id"] == "task-permission"
