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
    assert data["failures"][0]["failure_category"]["suggestions"]
    assert data["opportunities"]
    assert "success_rate" in data["opportunities"][0]
    assert "intermediate_failure_traces" in data["opportunities"][0]
    assert data["skill_priorities"]
    assert data["skill_priorities"][0]["trace_count"] >= data["skill_priorities"][-1]["trace_count"]
    assert any(item["id"] == "permission" for item in data["scenarios"])
    assert any(item["id"] == "task_flow" for item in data["scenarios"])


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
    assert detail["summary"]["story"]["summary"]
    assert "规划" in detail["summary"]["story"]["phases"]
    assert detail["summary"]["automation_opportunity"]["agent_candidate"]
    assert detail["summary"]["automation_opportunity"]["department_agent"]
    assert detail["summary"]["automation_opportunity"]["capability_candidate"]


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
    assert permission["totals"]["traces"] == 4
    assert all(row["task_id"].startswith("task-permission-") for row in permission["traces"])


def test_trace_story_detects_recovery_after_tool_failure(monkeypatch, tmp_path):
    app, _store = fresh_app(monkeypatch, tmp_path)
    client = TestClient(app)
    overview = client.get("/api/overview?range=24h&scenario=timeout").json()
    trace_id = next(
        row["trace_id"]
        for row in overview["traces"]
        if row["task_id"] == "task-timeout-langfuse-export"
    )

    detail = client.get(f"/api/traces/{trace_id}").json()
    story = detail["summary"]["story"]

    assert story["recovered_after_failure"] is True
    assert "失败分析" in story["phases"]
    assert "重试恢复" in story["phases"]
    assert "最终成功" in story["summary"]
    assert story["next_actions"]
    assert any("重试" in action for action in story["next_actions"])


def test_failure_category_exposes_optimization_suggestions(monkeypatch, tmp_path):
    app, _store = fresh_app(monkeypatch, tmp_path)
    client = TestClient(app)
    overview = client.get("/api/overview?range=24h&scenario=permission").json()

    permission_failure = next(
        row for row in overview["failures"]
        if row["failure_category"]["code"] == "permission_error"
    )
    category = permission_failure["failure_category"]

    assert category["label"] == "权限问题"
    assert category["confidence"] > 0.8
    assert any("Agent" in suggestion or "scope" in suggestion for suggestion in category["suggestions"])


def test_automation_opportunities_rank_current_agent_candidates(monkeypatch, tmp_path):
    app, _store = fresh_app(monkeypatch, tmp_path)
    client = TestClient(app)
    overview = client.get("/api/overview?range=24h&scenario=all").json()

    opportunities = overview["opportunities"]
    candidate = next(
        item for item in opportunities
        if item["department"] == "current"
        and item["candidate_skill"] == "test-fix-skill"
    )

    assert candidate["agent_candidate"] == "测试修复 Agent"
    assert candidate["department_agent"] == "当前通用 Agent"
    assert candidate["capability_candidate"] == "测试失败修复专项能力"
    assert candidate["specialized_agent_candidate"] == "测试修复 Agent"
    assert "test-fix-skill" in candidate["skill_bundle"]
    assert "test-runner-skill" in candidate["skill_bundle"]
    assert candidate["trace_count"] >= 2
    assert candidate["success_rate"] > 0
    assert candidate["avg_duration_ms"] > 0
    assert candidate["tool_calls"] > 0
    assert candidate["recommendation"] in {
        "高频且链路稳定，可进入专项 Agent 设计",
        "高频但中间失败集中，先治理失败原因",
        "频率不足，继续观察",
    }
    assert candidate["primary_trace_id"]


def test_skill_refinement_priorities_emphasize_frequency(monkeypatch, tmp_path):
    app, _store = fresh_app(monkeypatch, tmp_path)
    client = TestClient(app)
    overview = client.get("/api/overview?range=24h&scenario=all").json()

    priorities = overview["skill_priorities"]
    access_skill = next(item for item in priorities if item["skill"] == "identity-lookup-skill")

    assert access_skill["trace_count"] == 3
    assert access_skill["department_agent"] == "当前通用 Agent"
    assert access_skill["intermediate_failure_traces"] > 0
    assert access_skill["avg_duration_ms"] > 0
    assert "下钻" in access_skill["recommendation"]


def test_overview_uses_single_agent_scope(monkeypatch, tmp_path):
    app, _store = fresh_app(monkeypatch, tmp_path)
    client = TestClient(app)
    overview = client.get("/api/overview?range=24h&scenario=all").json()

    assert overview["agent"] == "current"
    assert {item["department"] for item in overview["skill_priorities"]} == {"current"}
    assert {item["department_agent"] for item in overview["skill_priorities"]} == {"当前通用 Agent"}
