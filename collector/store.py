"""SQLite-backed event store for the standalone Agent observability demo."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

_LOCK = threading.RLock()
_SCHEMA_READY_FOR: set[str] = set()


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    override = os.environ.get("HERMES_OBSERVABILITY_DATA_DIR", "").strip()
    return Path(override).expanduser() if override else project_root() / "data"


def sqlite_path() -> Path:
    return data_dir() / "observability.sqlite"


def events_jsonl_path() -> Path:
    return data_dir() / "events.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def trace_id_for(task_id: str = "", session_id: str = "") -> str:
    seed = task_id or session_id or "default"
    return hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:32]


def text_summary(value: Any) -> dict[str, Any]:
    text = "" if value is None else str(value)
    return {
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest(),
    }


def _ensure_schema(conn: sqlite3.Connection) -> None:
    db_key = str(sqlite_path())
    if db_key in _SCHEMA_READY_FOR:
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            span_type TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            duration_ms INTEGER,
            model TEXT NOT NULL,
            provider TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
        CREATE INDEX IF NOT EXISTS idx_events_trace_id ON events(trace_id);
        CREATE INDEX IF NOT EXISTS idx_events_type_name ON events(event_type, name);
        CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
        """
    )
    _SCHEMA_READY_FOR.add(db_key)


def connect() -> sqlite3.Connection:
    data_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def record_event(
    *,
    event_type: str,
    task_id: str = "",
    session_id: str = "",
    span_type: str = "",
    name: str = "",
    status: str = "",
    duration_ms: Optional[int] = None,
    model: str = "",
    provider: str = "",
    payload: Optional[dict[str, Any]] = None,
    created_at: Optional[str] = None,
) -> dict[str, Any]:
    event = {
        "event_id": str(uuid.uuid4()),
        "created_at": created_at or now_iso(),
        "trace_id": trace_id_for(task_id, session_id),
        "task_id": task_id or "",
        "session_id": session_id or "",
        "event_type": event_type,
        "span_type": span_type or "",
        "name": name or "",
        "status": status or "",
        "duration_ms": duration_ms,
        "model": model or "",
        "provider": provider or "",
        "payload": payload or {},
    }
    payload_json = json.dumps(event["payload"], ensure_ascii=False, sort_keys=True)
    json_line = json.dumps(event, ensure_ascii=False, sort_keys=True)

    with _LOCK:
        data_dir().mkdir(parents=True, exist_ok=True)
        with events_jsonl_path().open("a", encoding="utf-8") as fh:
            fh.write(json_line + "\n")
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    event_id, created_at, trace_id, task_id, session_id,
                    event_type, span_type, name, status, duration_ms,
                    model, provider, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["created_at"],
                    event["trace_id"],
                    event["task_id"],
                    event["session_id"],
                    event["event_type"],
                    event["span_type"],
                    event["name"],
                    event["status"],
                    event["duration_ms"],
                    event["model"],
                    event["provider"],
                    payload_json,
                ),
            )
    return event


def rows(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, tuple(params))]


def event_count() -> int:
    with connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] or 0)


def export_events(
    limit: int = 1000,
    started_after: Optional[str] = None,
    task_ids: Optional[Sequence[str]] = None,
) -> Path:
    clauses = []
    params: list[Any] = []
    if started_after:
        clauses.append("created_at >= ?")
        params.append(started_after)
    if task_ids:
        clauses.append("task_id IN (" + ",".join("?" for _ in task_ids) + ")")
        params.extend(task_ids)
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    with connect() as conn:
        result = rows(
            conn,
            f"""
            SELECT event_id, created_at, trace_id, task_id, session_id,
                   event_type, span_type, name, status, duration_ms,
                   model, provider, payload_json
            FROM events
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        )
    events = []
    for row in reversed(result):
        payload = json.loads(row.pop("payload_json") or "{}")
        row["payload"] = payload
        events.append(row)
    out = data_dir() / f"export-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(events, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return out


def _at(offset_minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


def seed_sample_data(force: bool = False) -> None:
    """Create demo traces so the dashboard has useful data on first launch."""
    if not force and event_count() > 0:
        return
    if force and sqlite_path().exists():
        sqlite_path().unlink()
        _SCHEMA_READY_FOR.discard(str(sqlite_path()))
    if force and events_jsonl_path().exists():
        events_jsonl_path().unlink()

    runs = [
        {
            "task_id": "task-code-auth-refresh",
            "scenario": "code_fix",
            "scenario_label": "正常代码修复",
            "minute": -455,
            "user_request": "修复 auth refresh 相关的 pytest 失败",
            "steps": [
                _tool("terminal", 410, command="pytest tests/test_auth.py -q"),
                _tool("read_file", 160, path="agent/auth.py"),
                _tool("apply_patch", 95, patch="refresh token fallback"),
                _tool("terminal", 1230, command="pytest tests/test_auth.py -q"),
            ],
        },
        {
            "task_id": "task-code-cache-bug",
            "scenario": "code_fix",
            "scenario_label": "正常代码修复",
            "minute": -405,
            "user_request": "定位缓存命中后工具结果没有刷新的问题",
            "steps": [
                _tool("search_files", 330, query="tool cache invalidation"),
                _tool("read_file", 210, path="agent/tool_cache.py"),
                _tool("apply_patch", 120, patch="invalidate cache after tool error"),
                _tool("terminal", 980, command="pytest tests/test_tool_cache.py -q"),
            ],
        },
        {
            "task_id": "task-code-dashboard-copy",
            "scenario": "code_fix",
            "scenario_label": "正常代码修复",
            "minute": -355,
            "user_request": "把观测看板里的英文按钮改成中文",
            "steps": [
                _tool("read_file", 180, path="dashboard/app.js"),
                _tool("apply_patch", 85, patch="localize dashboard labels"),
                _tool("terminal", 420, command="node --check dashboard/app.js"),
            ],
        },
        {
            "task_id": "task-code-flaky-test",
            "scenario": "code_fix",
            "scenario_label": "正常代码修复",
            "minute": -310,
            "user_request": "处理偶发失败的 dashboard API 测试",
            "steps": [
                _tool("terminal", 1450, status="error", command="pytest tests/test_dashboard_api.py -q", error="AssertionError: stale sqlite fixture was reused"),
                _tool("read_file", 145, path="tests/test_dashboard_api.py"),
                _tool("apply_patch", 90, patch="force regenerate sample data per test"),
                _tool("terminal", 760, command="pytest tests/test_dashboard_api.py -q"),
            ],
        },
        {
            "task_id": "task-code-hook-refactor",
            "scenario": "code_fix",
            "scenario_label": "正常代码修复",
            "minute": -270,
            "user_request": "重构 Hermes hook 事件归一化逻辑",
            "steps": [
                _tool("search_files", 280, query="invoke_hook post_llm_call"),
                _tool("read_file", 260, path="hermes_cli/plugins.py"),
                _tool("apply_patch", 140, patch="normalize task_id and trace_id"),
                _tool("terminal", 1520, command="pytest tests/plugins -q"),
            ],
        },
        {
            "task_id": "task-permission-dashboard-log",
            "scenario": "permission",
            "scenario_label": "权限失败排查",
            "minute": -235,
            "user_request": "从 home 目录启动 dashboard",
            "steps": [
                _tool("terminal", 75, status="error", command="uvicorn server.main:app", error="Permission denied: /home/felix/.hermes/dashboard.log"),
                _tool("terminal", 220, command="chown -R felix:felix /home/felix/.hermes/logs"),
                _tool("terminal", 310, command="uvicorn server.main:app --port 9120"),
            ],
        },
        {
            "task_id": "task-permission-pycache",
            "scenario": "permission",
            "scenario_label": "权限失败排查",
            "minute": -205,
            "user_request": "修复 pytest 写 __pycache__ 的权限问题",
            "steps": [
                _tool("terminal", 95, status="error", command="pytest -q", error="Permission denied: tests/__pycache__"),
                _tool("terminal", 180, command="chown -R felix:felix tests"),
                _tool("terminal", 840, command="pytest -q"),
            ],
        },
        {
            "task_id": "task-permission-sqlite",
            "scenario": "permission",
            "scenario_label": "权限失败排查",
            "minute": -175,
            "user_request": "修复观测 SQLite 文件无法写入的问题",
            "steps": [
                _tool("terminal", 60, status="error", command="python scripts/generate_sample_data.py", error="Permission denied: data/observability.sqlite"),
                _tool("terminal", 150, command="mkdir -p data && chown -R felix:felix data"),
                _tool("terminal", 270, command="python scripts/generate_sample_data.py"),
            ],
        },
        {
            "task_id": "task-permission-readonly",
            "scenario": "permission",
            "scenario_label": "权限失败排查",
            "minute": -145,
            "user_request": "解释为什么 root 写出的文件 felix 不能改",
            "final_status": "error",
            "steps": [
                _tool("terminal", 70, status="error", command="git status", error="dubious ownership in repository"),
                _tool("read_file", 120, path=".git/config"),
            ],
        },
        {
            "task_id": "task-timeout-langfuse-export",
            "scenario": "timeout",
            "scenario_label": "工具超时重试",
            "minute": -115,
            "user_request": "拉取远程 trace 导出文件",
            "steps": [
                _tool("http_fetch", 10000, status="error", url="https://cloud.langfuse.com/api/public/traces", error="request timed out after 10s"),
                _tool("http_fetch", 1450, url="https://cloud.langfuse.com/api/public/traces?limit=20"),
            ],
        },
        {
            "task_id": "task-timeout-npm-install",
            "scenario": "timeout",
            "scenario_label": "工具超时重试",
            "minute": -95,
            "user_request": "安装前端依赖并处理网络超时",
            "steps": [
                _tool("terminal", 30000, status="error", command="npm install", error="network timeout while fetching package metadata"),
                _tool("terminal", 5200, command="npm install --prefer-offline"),
                _tool("terminal", 420, command="node --check dashboard/app.js"),
            ],
        },
        {
            "task_id": "task-timeout-web-search",
            "scenario": "timeout",
            "scenario_label": "工具超时重试",
            "minute": -76,
            "user_request": "搜索 Agent observability 的行业做法",
            "steps": [
                _tool("web_search", 8000, status="error", query="Agent observability trace dashboard", error="search provider timeout"),
                _tool("web_search", 1220, query="Langfuse OpenTelemetry Agent observability"),
                _tool("read_file", 190, path="docs/architecture.md"),
            ],
        },
        {
            "task_id": "task-timeout-report-export",
            "scenario": "timeout",
            "scenario_label": "工具超时重试",
            "minute": -58,
            "user_request": "导出 24 小时内的观测事件 JSON",
            "steps": [
                _tool("http_fetch", 1800, url="/api/export/download?range=24h"),
                _tool("terminal", 220, command="wc -c exported.json"),
            ],
        },
        {
            "task_id": "task-skill-research-patterns",
            "scenario": "skill",
            "scenario_label": "Skill 触发分析",
            "minute": -43,
            "user_request": "总结 Agent 观测机制的常见模式",
            "steps": [
                _skill("researcher"),
                _tool("web_search", 860, query="agent observability traces tools skills"),
                _tool("read_file", 180, path="README.md"),
            ],
        },
        {
            "task_id": "task-skill-readme-polish",
            "scenario": "skill",
            "scenario_label": "Skill 触发分析",
            "minute": -34,
            "user_request": "把 README 改成更适合面试讲解的版本",
            "steps": [
                _skill("writer"),
                _tool("read_file", 130, path="README.md"),
                _tool("apply_patch", 170, patch="add portfolio explanation"),
                _tool("terminal", 360, command="pytest -q"),
            ],
        },
        {
            "task_id": "task-skill-architecture",
            "scenario": "skill",
            "scenario_label": "Skill 触发分析",
            "minute": -26,
            "user_request": "补一张面试讲解用的架构图",
            "steps": [
                _skill("diagrammer"),
                _tool("read_file", 110, path="README.md"),
                _tool("apply_patch", 100, patch="add mermaid architecture diagram"),
            ],
        },
        {
            "task_id": "task-skill-review",
            "scenario": "skill",
            "scenario_label": "Skill 触发分析",
            "minute": -18,
            "user_request": "检查 dashboard 导出 JSON 的交互是否合理",
            "steps": [
                _skill("reviewer"),
                _tool("search_files", 170, query="/api/export"),
                _tool("read_file", 150, path="dashboard/app.js"),
                _tool("apply_patch", 90, patch="switch export button to browser download"),
                _tool("terminal", 480, command="pytest -q"),
            ],
        },
        {
            "task_id": "task-skill-demo-script",
            "scenario": "skill",
            "scenario_label": "Skill 触发分析",
            "minute": -10,
            "user_request": "生成一段一分钟面试 demo 讲解脚本",
            "steps": [
                _skill("presenter"),
                _tool("read_file", 90, path="docs/demo-script.md"),
                _tool("apply_patch", 110, patch="add short walkthrough"),
            ],
        },
    ]

    for run in runs:
        _record_sample_trace(**run)


def _tool(
    name: str,
    duration_ms: int,
    *,
    status: str = "success",
    error: str = "",
    **metadata: Any,
) -> dict[str, Any]:
    return {
        "kind": "tool",
        "name": name,
        "duration_ms": duration_ms,
        "status": status,
        "error": error,
        "metadata": metadata,
    }


def _skill(name: str, *, source: str = "scenario") -> dict[str, Any]:
    return {"kind": "skill", "name": name, "source": source}


def _record_sample_trace(
    *,
    task_id: str,
    scenario: str,
    scenario_label: str,
    minute: int,
    user_request: str,
    steps: list[dict[str, Any]],
    final_status: str = "success",
) -> None:
    business_context = _business_context(task_id, scenario)
    base_payload = {
        "scenario": scenario,
        "scenario_label": scenario_label,
        "user_request": user_request,
        **business_context,
    }
    current = minute
    api_call = 1

    def llm_pair(reason: str, duration_ms: int) -> None:
        nonlocal current, api_call
        name = f"api_call_{api_call}"
        record_event(
            event_type="llm.requested",
            task_id=task_id,
            session_id=task_id,
            span_type="llm",
            name=name,
            status="started",
            model="gpt-5",
            provider="demo",
            payload={
                **base_payload,
                "reason": reason,
                "user_message": text_summary(user_request),
                "message_count": 2 + api_call,
            },
            created_at=_at(current),
        )
        current += 1
        record_event(
            event_type="llm.completed",
            task_id=task_id,
            session_id=task_id,
            span_type="llm",
            name=name,
            status="success",
            duration_ms=duration_ms,
            model="gpt-5",
            provider="demo",
            payload={**base_payload, "finish_reason": "tool_calls", "reason": reason},
            created_at=_at(current),
        )
        current += 1
        api_call += 1

    llm_pair("plan_next_action", 2100 + len(steps) * 180)
    has_error = False
    tool_count = 0

    for step in steps:
        if step["kind"] == "skill":
            record_event(
                event_type="skill.used",
                task_id=task_id,
                session_id=task_id,
                span_type="skill",
                name=step["name"],
                status="success",
                payload={**base_payload, "source": step.get("source", "scenario")},
                created_at=_at(current),
            )
            current += 1
            continue

        tool_count += 1
        status = step.get("status", "success")
        has_error = has_error or status == "error"
        record_event(
            event_type="tool.completed",
            task_id=task_id,
            session_id=task_id,
            span_type="tool",
            name=step["name"],
            status=status,
            duration_ms=step["duration_ms"],
            payload={
                **base_payload,
                "ok": status == "success",
                "error": step.get("error") or _sample_error(step["name"]) if status == "error" else "",
                "metadata": step.get("metadata") or {},
            },
            created_at=_at(current),
        )
        current += 1
        if status == "error":
            llm_pair("analyze_tool_failure", 1650 + tool_count * 140)

    failed = final_status == "error"
    record_event(
        event_type="task.failed" if failed else "task.completed",
        task_id=task_id,
        session_id=task_id,
        span_type="task",
        name="agent_task",
        status="error" if failed else "success",
        duration_ms=None,
        payload={
            **base_payload,
            "failed": failed,
            "had_intermediate_error": has_error,
            "tool_count": tool_count,
            "final_response_chars": 380 + tool_count * 90,
        },
        created_at=_at(current),
    )


def _sample_error(tool_name: str) -> str:
    if tool_name == "terminal":
        return "Permission denied: /home/felix/.hermes/dashboard.log，当前用户没有写入权限"
    if tool_name == "http_fetch":
        return "request timed out after 10s，远程 trace 导出接口超时"
    return "tool execution failed，工具执行失败"


def _business_context(task_id: str, scenario: str) -> dict[str, Any]:
    contexts: dict[str, dict[str, Any]] = {
        "task-code-auth-refresh": {
            "department": "engineering",
            "department_label": "研发部",
            "workflow": "pytest_failure_fix",
            "workflow_label": "测试失败修复",
            "candidate_skill": "test-fix-skill",
            "agent_candidate": "研发测试修复 Agent",
            "estimated_manual_minutes": 35,
            "human_intervention": False,
            "automation_fit": "high",
            "risk_level": "medium",
        },
        "task-code-cache-bug": {
            "department": "engineering",
            "department_label": "研发部",
            "workflow": "code_defect_diagnosis",
            "workflow_label": "代码缺陷定位",
            "candidate_skill": "code-debug-skill",
            "agent_candidate": "研发缺陷定位 Agent",
            "estimated_manual_minutes": 45,
            "human_intervention": False,
            "automation_fit": "high",
            "risk_level": "medium",
        },
        "task-code-dashboard-copy": {
            "department": "product_ops",
            "department_label": "产品运营部",
            "workflow": "dashboard_content_localization",
            "workflow_label": "看板文案本地化",
            "candidate_skill": "dashboard-copy-skill",
            "agent_candidate": "运营看板配置 Agent",
            "estimated_manual_minutes": 20,
            "human_intervention": False,
            "automation_fit": "medium",
            "risk_level": "low",
        },
        "task-code-flaky-test": {
            "department": "engineering",
            "department_label": "研发部",
            "workflow": "pytest_failure_fix",
            "workflow_label": "测试失败修复",
            "candidate_skill": "test-fix-skill",
            "agent_candidate": "研发测试修复 Agent",
            "estimated_manual_minutes": 40,
            "human_intervention": True,
            "automation_fit": "high",
            "risk_level": "medium",
        },
        "task-code-hook-refactor": {
            "department": "platform",
            "department_label": "平台工程部",
            "workflow": "agent_hook_refactor",
            "workflow_label": "Agent Hook 重构",
            "candidate_skill": "agent-hook-skill",
            "agent_candidate": "平台 Agent 工程助手",
            "estimated_manual_minutes": 55,
            "human_intervention": True,
            "automation_fit": "medium",
            "risk_level": "medium",
        },
        "task-permission-dashboard-log": {
            "department": "platform",
            "department_label": "平台工程部",
            "workflow": "dev_env_permission_repair",
            "workflow_label": "开发环境权限修复",
            "candidate_skill": "env-permission-skill",
            "agent_candidate": "开发环境运维 Agent",
            "estimated_manual_minutes": 18,
            "human_intervention": False,
            "automation_fit": "medium",
            "risk_level": "medium",
        },
        "task-permission-pycache": {
            "department": "platform",
            "department_label": "平台工程部",
            "workflow": "dev_env_permission_repair",
            "workflow_label": "开发环境权限修复",
            "candidate_skill": "env-permission-skill",
            "agent_candidate": "开发环境运维 Agent",
            "estimated_manual_minutes": 15,
            "human_intervention": False,
            "automation_fit": "medium",
            "risk_level": "medium",
        },
        "task-permission-sqlite": {
            "department": "platform",
            "department_label": "平台工程部",
            "workflow": "dev_env_permission_repair",
            "workflow_label": "开发环境权限修复",
            "candidate_skill": "env-permission-skill",
            "agent_candidate": "开发环境运维 Agent",
            "estimated_manual_minutes": 22,
            "human_intervention": False,
            "automation_fit": "medium",
            "risk_level": "medium",
        },
        "task-permission-readonly": {
            "department": "platform",
            "department_label": "平台工程部",
            "workflow": "dev_env_permission_repair",
            "workflow_label": "开发环境权限修复",
            "candidate_skill": "env-permission-skill",
            "agent_candidate": "开发环境运维 Agent",
            "estimated_manual_minutes": 12,
            "human_intervention": True,
            "automation_fit": "medium",
            "risk_level": "medium",
        },
        "task-timeout-langfuse-export": {
            "department": "data_ops",
            "department_label": "数据运营部",
            "workflow": "remote_trace_export",
            "workflow_label": "远程数据拉取",
            "candidate_skill": "remote-retry-skill",
            "agent_candidate": "数据接口巡检 Agent",
            "estimated_manual_minutes": 28,
            "human_intervention": False,
            "automation_fit": "high",
            "risk_level": "low",
        },
        "task-timeout-npm-install": {
            "department": "platform",
            "department_label": "平台工程部",
            "workflow": "dependency_install_recovery",
            "workflow_label": "依赖安装恢复",
            "candidate_skill": "dependency-recovery-skill",
            "agent_candidate": "工程环境修复 Agent",
            "estimated_manual_minutes": 25,
            "human_intervention": False,
            "automation_fit": "medium",
            "risk_level": "medium",
        },
        "task-timeout-web-search": {
            "department": "strategy",
            "department_label": "战略分析部",
            "workflow": "market_research_synthesis",
            "workflow_label": "行业研究汇总",
            "candidate_skill": "research-synthesis-skill",
            "agent_candidate": "行业研究 Agent",
            "estimated_manual_minutes": 60,
            "human_intervention": True,
            "automation_fit": "medium",
            "risk_level": "low",
        },
        "task-timeout-report-export": {
            "department": "data_ops",
            "department_label": "数据运营部",
            "workflow": "report_export_check",
            "workflow_label": "报表导出核验",
            "candidate_skill": "report-export-skill",
            "agent_candidate": "报表运营 Agent",
            "estimated_manual_minutes": 16,
            "human_intervention": False,
            "automation_fit": "high",
            "risk_level": "low",
        },
        "task-skill-research-patterns": {
            "department": "strategy",
            "department_label": "战略分析部",
            "workflow": "market_research_synthesis",
            "workflow_label": "行业研究汇总",
            "candidate_skill": "research-synthesis-skill",
            "agent_candidate": "行业研究 Agent",
            "estimated_manual_minutes": 75,
            "human_intervention": True,
            "automation_fit": "medium",
            "risk_level": "low",
        },
        "task-skill-readme-polish": {
            "department": "product_ops",
            "department_label": "产品运营部",
            "workflow": "portfolio_content_polish",
            "workflow_label": "文档内容润色",
            "candidate_skill": "content-polish-skill",
            "agent_candidate": "内容运营 Agent",
            "estimated_manual_minutes": 30,
            "human_intervention": False,
            "automation_fit": "high",
            "risk_level": "low",
        },
        "task-skill-architecture": {
            "department": "product_ops",
            "department_label": "产品运营部",
            "workflow": "architecture_visualization",
            "workflow_label": "架构图生成",
            "candidate_skill": "diagram-skill",
            "agent_candidate": "方案展示 Agent",
            "estimated_manual_minutes": 35,
            "human_intervention": False,
            "automation_fit": "high",
            "risk_level": "low",
        },
        "task-skill-review": {
            "department": "product_ops",
            "department_label": "产品运营部",
            "workflow": "dashboard_review",
            "workflow_label": "看板交互评审",
            "candidate_skill": "product-review-skill",
            "agent_candidate": "产品体验评审 Agent",
            "estimated_manual_minutes": 45,
            "human_intervention": True,
            "automation_fit": "medium",
            "risk_level": "low",
        },
        "task-skill-demo-script": {
            "department": "sales_enablement",
            "department_label": "售前支持部",
            "workflow": "demo_script_generation",
            "workflow_label": "演示脚本生成",
            "candidate_skill": "demo-script-skill",
            "agent_candidate": "售前演示 Agent",
            "estimated_manual_minutes": 40,
            "human_intervention": False,
            "automation_fit": "high",
            "risk_level": "low",
        },
    }
    fallback = {
        "department": scenario,
        "department_label": "未归属部门",
        "workflow": scenario,
        "workflow_label": "未归属流程",
        "candidate_skill": f"{scenario}-skill",
        "agent_candidate": "待评估专项 Agent",
        "estimated_manual_minutes": 20,
        "human_intervention": False,
        "automation_fit": "medium",
        "risk_level": "medium",
    }
    context = dict(contexts.get(task_id, fallback))
    context["department_agent"] = context.get("department_agent") or f"{context['department_label']}通用 Agent"
    context["capability_candidate"] = context.get("capability_candidate") or f"{context['workflow_label']}专项能力"
    context["specialized_agent_candidate"] = (
        context.get("specialized_agent_candidate") or context["agent_candidate"]
    )
    context["skill_bundle"] = context.get("skill_bundle") or _skill_bundle_for(context["candidate_skill"])
    return context


def _skill_bundle_for(candidate_skill: str) -> list[str]:
    bundles = {
        "test-fix-skill": ["test-fix-skill", "code-search-skill", "patch-apply-skill", "test-runner-skill"],
        "code-debug-skill": ["code-debug-skill", "code-search-skill", "patch-apply-skill", "test-runner-skill"],
        "dashboard-copy-skill": ["dashboard-copy-skill", "ui-copy-skill", "patch-apply-skill"],
        "agent-hook-skill": ["agent-hook-skill", "code-search-skill", "architecture-review-skill", "test-runner-skill"],
        "env-permission-skill": ["env-permission-skill", "shell-diagnosis-skill", "permission-repair-skill"],
        "remote-retry-skill": ["remote-retry-skill", "api-diagnosis-skill", "retry-policy-skill"],
        "dependency-recovery-skill": ["dependency-recovery-skill", "shell-diagnosis-skill", "cache-policy-skill"],
        "research-synthesis-skill": ["research-synthesis-skill", "web-search-skill", "source-review-skill", "summary-writer-skill"],
        "report-export-skill": ["report-export-skill", "api-diagnosis-skill", "data-check-skill"],
        "content-polish-skill": ["content-polish-skill", "doc-structure-skill", "style-review-skill"],
        "diagram-skill": ["diagram-skill", "architecture-review-skill", "doc-structure-skill"],
        "product-review-skill": ["product-review-skill", "ui-review-skill", "interaction-check-skill"],
        "demo-script-skill": ["demo-script-skill", "summary-writer-skill", "scenario-story-skill"],
    }
    return bundles.get(candidate_skill, [candidate_skill])
