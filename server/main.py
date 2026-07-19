"""Standalone FastAPI server for the Agent observability dashboard."""
from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from collector import store

APP_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = APP_ROOT / "dashboard"
SCENARIOS = [
    {"id": "all", "label": "全部场景", "description": "展示所有样例 trace", "task_ids": []},
    {
        "id": "code_fix",
        "label": "正常代码修复",
        "description": "代码修改、测试验证和任务完成链路",
        "task_ids": [
            "task-code-auth-refresh",
            "task-code-cache-bug",
            "task-code-dashboard-copy",
            "task-code-flaky-test",
            "task-code-hook-refactor",
        ],
    },
    {
        "id": "permission",
        "label": "权限失败排查",
        "description": "权限错误、修复动作和重试结果",
        "task_ids": [
            "task-permission-dashboard-log",
            "task-permission-pycache",
            "task-permission-sqlite",
            "task-permission-readonly",
        ],
    },
    {
        "id": "timeout",
        "label": "工具超时重试",
        "description": "远程请求超时和后续成功重试",
        "task_ids": [
            "task-timeout-langfuse-export",
            "task-timeout-npm-install",
            "task-timeout-web-search",
            "task-timeout-report-export",
        ],
    },
    {
        "id": "skill",
        "label": "Skill 触发分析",
        "description": "研究类任务中的 Skill 使用链路",
        "task_ids": [
            "task-skill-research-patterns",
            "task-skill-readme-polish",
            "task-skill-architecture",
            "task-skill-review",
            "task-skill-demo-script",
        ],
    },
]
AGENTS = [
    {
        "id": "engineering",
        "label": "研发部通用 Agent",
        "department": "研发部",
        "task_ids": [
            "task-code-auth-refresh",
            "task-code-cache-bug",
            "task-code-flaky-test",
        ],
    },
    {
        "id": "platform",
        "label": "平台工程部通用 Agent",
        "department": "平台工程部",
        "task_ids": [
            "task-code-hook-refactor",
            "task-permission-dashboard-log",
            "task-permission-pycache",
            "task-permission-sqlite",
            "task-permission-readonly",
            "task-timeout-npm-install",
        ],
    },
    {
        "id": "product_ops",
        "label": "产品运营部通用 Agent",
        "department": "产品运营部",
        "task_ids": [
            "task-code-dashboard-copy",
            "task-skill-readme-polish",
            "task-skill-architecture",
            "task-skill-review",
        ],
    },
    {
        "id": "data_ops",
        "label": "数据运营部通用 Agent",
        "department": "数据运营部",
        "task_ids": [
            "task-timeout-langfuse-export",
            "task-timeout-report-export",
        ],
    },
    {
        "id": "strategy",
        "label": "战略分析部通用 Agent",
        "department": "战略分析部",
        "task_ids": [
            "task-timeout-web-search",
            "task-skill-research-patterns",
        ],
    },
    {
        "id": "sales_enablement",
        "label": "售前支持部通用 Agent",
        "department": "售前支持部",
        "task_ids": ["task-skill-demo-script"],
    },
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.seed_sample_data()
    yield


app = FastAPI(title="Hermes Agent 观测看板", version="0.1.0", lifespan=lifespan)


def _limit(value: int, default: int = 50, maximum: int = 500) -> int:
    try:
        return min(maximum, max(1, int(value)))
    except (TypeError, ValueError):
        return default


def _range_start(range_name: str = "24h") -> Optional[str]:
    value = (range_name or "24h").strip().lower()
    now = datetime.now(timezone.utc)
    if value in {"all", "全部"}:
        return None
    if value in {"1h", "hour"}:
        return (now - timedelta(hours=1)).isoformat()
    if value in {"24h", "day", "1d"}:
        return (now - timedelta(hours=24)).isoformat()
    if value in {"7d", "week"}:
        return (now - timedelta(days=7)).isoformat()
    return (now - timedelta(hours=24)).isoformat()


def _scenario_task_ids(scenario: str = "all") -> list[str]:
    value = (scenario or "all").strip().lower()
    for item in SCENARIOS:
        if item["id"] == value:
            return list(item["task_ids"])
    return []


def _agent_task_ids(agent: str = "all") -> list[str]:
    value = (agent or "all").strip().lower()
    if value in {"all", "全部"}:
        return []
    for item in AGENTS:
        if item["id"] == value:
            return list(item["task_ids"])
    return []


def _filter_clauses(range_name: str = "24h", scenario: str = "all", agent: str = "all") -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    start = _range_start(range_name)
    if start:
        clauses.append("created_at >= ?")
        params.append(start)
    task_ids = _scenario_task_ids(scenario)
    if task_ids:
        clauses.append("task_id IN (" + ",".join("?" for _ in task_ids) + ")")
        params.extend(task_ids)
    agent_task_ids = _agent_task_ids(agent)
    if agent_task_ids:
        clauses.append("task_id IN (" + ",".join("?" for _ in agent_task_ids) + ")")
        params.extend(agent_task_ids)
    return clauses, params


def _where_filters(range_name: str = "24h", scenario: str = "all", agent: str = "all", prefix: str = "WHERE") -> tuple[str, list[Any]]:
    clauses, params = _filter_clauses(range_name, scenario, agent)
    if not clauses:
        return "", []
    return f"{prefix} " + " AND ".join(clauses), params


def _and_filters(range_name: str = "24h", scenario: str = "all", agent: str = "all") -> tuple[str, list[Any]]:
    return _where_filters(range_name, scenario, agent, prefix="AND")


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.pop("payload_json", "{}")
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {}
    row["payload"] = parsed if isinstance(parsed, dict) else {"value": parsed}
    return row


def _rows(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return store.rows(conn, sql, params)


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_text(v) for v in value)
    return str(value)


FAILURE_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "code": "permission_error",
        "label": "权限问题",
        "confidence": 0.92,
        "patterns": ("permission denied", "eacces", "operation not permitted", "forbidden"),
        "suggestions": [
            "检查执行用户是否一致，避免 root 与普通用户混用生成运行文件。",
            "检查目标目录和文件 owner，例如 `chown -R felix:felix <path>`。",
            "确认日志、SQLite、缓存目录对当前进程可写。",
        ],
    },
    {
        "code": "auth_error",
        "label": "认证/API Key 问题",
        "confidence": 0.9,
        "patterns": ("unauthorized", "401", "api key", "invalid token", "authentication"),
        "suggestions": [
            "检查环境变量是否写入当前进程使用的 `.env` 或启动脚本。",
            "区分 public key、secret key、base URL 和 region，避免连到错误项目。",
            "在任务开始时做一次配置自检，把缺失 key 直接暴露成可读错误。",
        ],
    },
    {
        "code": "rate_limit",
        "label": "限流",
        "confidence": 0.86,
        "patterns": ("rate limit", "429", "too many requests", "quota"),
        "suggestions": [
            "为高频工具增加指数退避和最大重试次数。",
            "对重复请求增加缓存或批处理，降低短时间调用峰值。",
            "在看板里按 provider/model 观察限流是否集中出现。",
        ],
    },
    {
        "code": "timeout",
        "label": "超时",
        "confidence": 0.86,
        "patterns": ("timeout", "timed out", "deadline exceeded"),
        "suggestions": [
            "为高延迟工具增加 timeout、重试和退避策略。",
            "对可复用远程结果做缓存，减少重复请求。",
            "记录 retry_count 和最终是否恢复，区分偶发抖动和稳定故障。",
        ],
    },
    {
        "code": "network_error",
        "label": "网络问题",
        "confidence": 0.8,
        "patterns": ("network", "connection refused", "connection reset", "dns", "ssl", "tls"),
        "suggestions": [
            "记录请求目标、region 和错误码，优先判断是否为环境网络问题。",
            "为外部依赖增加健康检查和失败降级路径。",
            "把网络错误与业务错误分开统计，避免误判 Agent 推理质量。",
        ],
    },
    {
        "code": "not_found",
        "label": "资源不存在",
        "confidence": 0.82,
        "patterns": ("not found", "no such file", "enoent", "404"),
        "suggestions": [
            "检查路径、分支、资源 ID 或 API endpoint 是否来自同一环境。",
            "在执行工具前增加存在性检查，给出更早、更清楚的失败信息。",
            "把缺失资源记录到 payload，方便从 trace 详情直接复盘。",
        ],
    },
    {
        "code": "agent_failed",
        "label": "Agent 任务失败",
        "confidence": 0.68,
        "patterns": ("task.failed", "task.interrupted", "agent_task"),
        "suggestions": [
            "打开 trace 时间线，先定位第一个 error 事件而不是只看最终失败。",
            "把失败前后的 LLM、Tool、Skill 事件串起来，判断问题属于规划、执行还是恢复。",
            "给关键阶段补充结构化 payload，让失败原因能被自动归类。",
        ],
    },
    {
        "code": "tool_error",
        "label": "工具执行错误",
        "confidence": 0.62,
        "patterns": ("tool.completed", "tool.started"),
        "suggestions": [
            "统计同一工具的错误率和 P95 耗时，优先治理高频失败工具。",
            "为工具输出增加结构化错误码，减少只能靠日志文本判断的情况。",
            "把可恢复错误接入重试，把不可恢复错误转成对用户可读的下一步动作。",
        ],
    },
]

UNKNOWN_FAILURE = {
    "code": "unknown",
    "label": "未分类",
    "confidence": 0.3,
    "suggestions": [
        "补充结构化错误码、stderr 摘要或异常类型，降低未分类比例。",
        "把未分类失败样本沉淀成新规则，再观察下一轮分类覆盖率。",
    ],
}


def classify_failure(row: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(
        str(part or "")
        for part in (
            row.get("event_type"),
            row.get("name"),
            row.get("status"),
            _flatten_text(row.get("payload")),
        )
    ).lower()
    for rule in FAILURE_KNOWLEDGE:
        matched_pattern = next((pattern for pattern in rule["patterns"] if pattern in text), "")
        if matched_pattern:
            return {
                "code": rule["code"],
                "label": rule["label"],
                "confidence": rule["confidence"],
                "matched_pattern": matched_pattern,
                "suggestions": rule["suggestions"],
            }
    return {**UNKNOWN_FAILURE, "matched_pattern": ""}


def _decorate_failure(row: dict[str, Any]) -> dict[str, Any]:
    row = _payload(row)
    row["failure_category"] = classify_failure(row)
    return row


def _first_payload_value(rows: list[dict[str, Any]], key: str) -> str:
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict) and payload.get(key):
            return str(payload[key])
    return ""


def _next_actions_from_failures(failures: list[dict[str, Any]], limit: int = 4) -> list[str]:
    actions: list[str] = []
    seen: set[str] = set()
    for failure in failures:
        category = failure.get("failure_category") or classify_failure(failure)
        for suggestion in category.get("suggestions", []):
            if suggestion not in seen:
                actions.append(suggestion)
                seen.add(suggestion)
            if len(actions) >= limit:
                return actions
    return actions


def _build_trace_story(rows: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    llm_calls = sum(1 for row in rows if row.get("event_type") == "llm.completed")
    tool_calls = sum(1 for row in rows if row.get("event_type") == "tool.completed")
    skill_calls = sum(1 for row in rows if row.get("event_type") == "skill.used")
    failed_tools = [
        row
        for row in rows
        if row.get("event_type") == "tool.completed" and row.get("status") == "error"
    ]
    task_failed = any(row.get("event_type") == "task.failed" for row in rows)
    task_completed = any(row.get("event_type") == "task.completed" for row in rows)
    failure_seen = bool(failed_tools or failures)

    phases = ["规划"]
    if skill_calls:
        phases.append("Skill 准备")
    if tool_calls:
        phases.append("工具执行")
    if failure_seen:
        phases.append("失败分析")
    if failed_tools and _has_success_after_failure(rows):
        phases.append("重试恢复")
    phases.append("失败收尾" if task_failed else "完成" if task_completed else "未完成")

    outcome = "最终失败" if task_failed else "最终成功" if task_completed else "尚未完成"
    retry_text = "，失败后通过后续工具调用恢复" if failed_tools and _has_success_after_failure(rows) else ""
    skill_text = f"，触发 {skill_calls} 次 Skill" if skill_calls else ""
    failure_text = f"，出现 {len(failures)} 个失败信号" if failures else "，未出现失败信号"
    summary = (
        f"本次任务经历 {llm_calls} 次 LLM 调用、{tool_calls} 次工具调用"
        f"{skill_text}{failure_text}{retry_text}，{outcome}。"
    )

    return {
        "phases": phases,
        "summary": summary,
        "outcome": outcome,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "skill_calls": skill_calls,
        "failure_signals": len(failures),
        "recovered_after_failure": bool(failed_tools and _has_success_after_failure(rows)),
        "next_actions": _next_actions_from_failures(failures),
    }


def _payload_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


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
    return bundles.get(candidate_skill, [candidate_skill] if candidate_skill else [])


def _business_context(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    task_id = str(row.get("task_id") or "")
    scenario = str(payload.get("scenario") or "")
    if task_id.startswith("task-code"):
        fallback = ("engineering", "研发部", "code_assistance", "代码研发辅助", "code-debug-skill", "研发缺陷定位 Agent")
    elif task_id.startswith("task-permission"):
        fallback = ("platform", "平台工程部", "dev_env_repair", "开发环境修复", "env-permission-skill", "开发环境运维 Agent")
    elif task_id.startswith("task-timeout"):
        fallback = ("data_ops", "数据运营部", "remote_recovery", "远程接口恢复", "remote-retry-skill", "数据接口巡检 Agent")
    elif task_id.startswith("task-skill"):
        fallback = ("product_ops", "产品运营部", "content_enablement", "内容与方案生产", "content-polish-skill", "内容运营 Agent")
    else:
        fallback = (scenario or "unknown", "未归属部门", scenario or "unknown", "未归属流程", "unknown-skill", "待评估专项 Agent")

    department_label = str(payload.get("department_label") or fallback[1])
    workflow_label = str(payload.get("workflow_label") or fallback[3])
    agent_candidate = str(payload.get("agent_candidate") or fallback[5])
    candidate_skill = str(payload.get("candidate_skill") or fallback[4])
    skill_bundle = _payload_list(payload.get("skill_bundle")) or _skill_bundle_for(candidate_skill)
    return {
        "department": str(payload.get("department") or fallback[0]),
        "department_label": department_label,
        "department_agent": str(payload.get("department_agent") or f"{department_label}通用 Agent"),
        "workflow": str(payload.get("workflow") or fallback[2]),
        "workflow_label": workflow_label,
        "candidate_skill": candidate_skill,
        "capability_candidate": str(payload.get("capability_candidate") or f"{workflow_label}专项能力"),
        "agent_candidate": agent_candidate,
        "specialized_agent_candidate": str(payload.get("specialized_agent_candidate") or agent_candidate),
        "skill_bundle": skill_bundle,
    }


def _trace_business_rows(
    conn: sqlite3.Connection,
    range_name: str,
    scenario: str,
    agent: str = "all",
) -> list[dict[str, Any]]:
    where_sql, params = _where_filters(range_name, scenario, agent)
    return [
        _payload(row)
        for row in _rows(conn, f"""
            SELECT created_at, trace_id, task_id, session_id, event_type,
                   span_type, name, status, duration_ms, payload_json
            FROM events
            {where_sql}
            ORDER BY created_at ASC
            """, params)
    ]


def _business_traces(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    traces: dict[str, dict[str, Any]] = {}
    for row in rows:
        trace_id = row.get("trace_id")
        if not trace_id:
            continue
        context = _business_context(row)
        trace = traces.setdefault(
            trace_id,
            {
                **context,
                "trace_id": trace_id,
                "task_id": row.get("task_id") or "",
                "started_at": row.get("created_at") or "",
                "last_seen": row.get("created_at") or "",
                "events": 0,
                "tools": 0,
                "skill_uses": 0,
                "has_failure": False,
                "has_intermediate_failure": False,
                "task_success": False,
                "task_failed": False,
                "observed_duration_ms": 0,
                "user_request": _first_payload_value([row], "user_request"),
            },
        )
        trace["last_seen"] = row.get("created_at") or trace["last_seen"]
        trace["events"] += 1
        if row.get("event_type") == "tool.completed":
            trace["tools"] += 1
        if row.get("event_type") == "skill.used":
            trace["skill_uses"] += 1
        if row.get("duration_ms") is not None:
            trace["observed_duration_ms"] += int(row["duration_ms"])
        if row.get("status") in {"error", "interrupted"} or row.get("event_type") in {"task.failed", "task.interrupted"}:
            trace["has_failure"] = True
        if row.get("status") in {"error", "interrupted"} and row.get("event_type") not in {"task.failed", "task.interrupted"}:
            trace["has_intermediate_failure"] = True
        if row.get("event_type") == "task.completed":
            trace["task_success"] = True
        if row.get("event_type") in {"task.failed", "task.interrupted"}:
            trace["task_failed"] = True
    return traces


def _automation_opportunities(
    conn: sqlite3.Connection,
    range_name: str,
    scenario: str,
    agent: str = "all",
    limit: int = 8,
) -> list[dict[str, Any]]:
    rows = _trace_business_rows(conn, range_name, scenario, agent)
    traces = _business_traces(rows)

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for trace in traces.values():
        key = (trace["department"], trace["candidate_skill"], trace["workflow"])
        group = groups.setdefault(
            key,
            {
                "department": trace["department"],
                "department_label": trace["department_label"],
                "department_agent": trace["department_agent"],
                "workflow": trace["workflow"],
                "workflow_label": trace["workflow_label"],
                "candidate_skill": trace["candidate_skill"],
                "capability_candidate": trace["capability_candidate"],
                "agent_candidate": trace["agent_candidate"],
                "specialized_agent_candidate": trace["specialized_agent_candidate"],
                "skill_bundle": [],
                "trace_count": 0,
                "successes": 0,
                "final_failures": 0,
                "intermediate_failure_traces": 0,
                "tool_calls": 0,
                "skill_uses": 0,
                "observed_duration_ms": 0,
                "primary_trace_id": trace["trace_id"],
                "example_requests": [],
            },
        )
        group["trace_count"] += 1
        group["successes"] += 1 if trace["task_success"] and not trace["task_failed"] else 0
        group["final_failures"] += 1 if trace["task_failed"] else 0
        group["intermediate_failure_traces"] += 1 if trace["has_intermediate_failure"] else 0
        group["tool_calls"] += trace["tools"]
        group["skill_uses"] += trace["skill_uses"]
        group["observed_duration_ms"] += trace["observed_duration_ms"]
        for skill in trace["skill_bundle"]:
            if skill not in group["skill_bundle"]:
                group["skill_bundle"].append(skill)
        request = trace.get("user_request", "")
        if request and len(group["example_requests"]) < 2:
            group["example_requests"].append(request)

    opportunities: list[dict[str, Any]] = []
    for group in groups.values():
        trace_count = max(1, int(group["trace_count"]))
        success_rate = group["successes"] / trace_count
        final_failure_rate = group["final_failures"] / trace_count
        intermediate_failure_rate = group["intermediate_failure_traces"] / trace_count
        avg_duration_ms = round(group["observed_duration_ms"] / trace_count, 1)
        avg_tool_calls = round(group["tool_calls"] / trace_count, 1)
        group["success_rate"] = round(success_rate, 3)
        group["final_failure_rate"] = round(final_failure_rate, 3)
        group["intermediate_failure_rate"] = round(intermediate_failure_rate, 3)
        group["avg_duration_ms"] = avg_duration_ms
        group["avg_tool_calls"] = avg_tool_calls
        if trace_count >= 2 and success_rate >= 0.8 and intermediate_failure_rate <= 0.3:
            recommendation = "高频且链路稳定，可进入专项 Agent 设计"
        elif trace_count >= 2 and intermediate_failure_rate > 0.3:
            recommendation = "高频但中间失败集中，先治理失败原因"
        else:
            recommendation = "频率不足，继续观察"
        group["recommendation"] = recommendation
        group["evidence"] = (
            f"{trace_count} 条 trace，最终成功率 {round(success_rate * 100)}%，"
            f"中间失败 {group['intermediate_failure_traces']} 次。"
        )
        group["positioning"] = (
            f"在「{group['department_agent']}」内部，把「{group['capability_candidate']}」"
            f"细化成「{group['specialized_agent_candidate']}」。"
        )
        opportunities.append(group)

    return sorted(
        opportunities,
        key=lambda item: (-item["trace_count"], -item["success_rate"], item["intermediate_failure_rate"], item["department_label"]),
    )[:limit]


def _skill_refinement_priorities(
    conn: sqlite3.Connection,
    range_name: str,
    scenario: str,
    agent: str = "all",
    limit: int = 8,
) -> list[dict[str, Any]]:
    traces = _business_traces(_trace_business_rows(conn, range_name, scenario, agent))
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for trace in traces.values():
        for skill in trace["skill_bundle"]:
            key = (trace["department"], skill)
            group = groups.setdefault(
                key,
                {
                    "department": trace["department"],
                    "department_label": trace["department_label"],
                    "department_agent": trace["department_agent"],
                    "skill": skill,
                    "trace_count": 0,
                    "primary_count": 0,
                    "successes": 0,
                    "final_failures": 0,
                    "intermediate_failure_traces": 0,
                    "tool_calls": 0,
                    "observed_duration_ms": 0,
                    "workflows": [],
                    "specialized_agents": [],
                    "primary_trace_id": trace["trace_id"],
                },
            )
            group["trace_count"] += 1
            group["primary_count"] += 1 if skill == trace["candidate_skill"] else 0
            group["successes"] += 1 if trace["task_success"] and not trace["task_failed"] else 0
            group["final_failures"] += 1 if trace["task_failed"] else 0
            group["intermediate_failure_traces"] += 1 if trace["has_intermediate_failure"] else 0
            group["tool_calls"] += trace["tools"]
            group["observed_duration_ms"] += trace["observed_duration_ms"]
            if trace["workflow_label"] not in group["workflows"]:
                group["workflows"].append(trace["workflow_label"])
            if trace["specialized_agent_candidate"] not in group["specialized_agents"]:
                group["specialized_agents"].append(trace["specialized_agent_candidate"])

    priorities: list[dict[str, Any]] = []
    for group in groups.values():
        trace_count = max(1, int(group["trace_count"]))
        success_rate = group["successes"] / trace_count
        final_failure_rate = group["final_failures"] / trace_count
        intermediate_failure_rate = group["intermediate_failure_traces"] / trace_count
        avg_duration_ms = round(group["observed_duration_ms"] / trace_count, 1)
        avg_tool_calls = round(group["tool_calls"] / trace_count, 1)
        group["success_rate"] = round(success_rate, 3)
        group["final_failure_rate"] = round(final_failure_rate, 3)
        group["intermediate_failure_rate"] = round(intermediate_failure_rate, 3)
        group["avg_duration_ms"] = avg_duration_ms
        group["avg_tool_calls"] = avg_tool_calls
        group["recommendation"] = (
            "高频且覆盖稳定流程，适合下钻设计"
            if trace_count >= 3
            else "频率开始出现，继续观察并补充结构化埋点"
        )
        group["evidence"] = (
            f"被 {trace_count} 条 trace 使用，覆盖 {len(group['workflows'])} 个流程，"
            f"最终成功率 {round(success_rate * 100)}%。"
        )
        priorities.append(group)

    return sorted(
        priorities,
        key=lambda item: (-item["trace_count"], -item["success_rate"], item["intermediate_failure_rate"], -item["primary_count"], item["skill"]),
    )[:limit]


def _trace_automation_opportunity(rows: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    context = _business_context(rows[0])
    failed = bool(failures or any(row.get("event_type") == "task.failed" for row in rows))
    status_text = "需要先降低失败率" if failed else "可进入候选池"
    return {
        **context,
        "recommendation": (
            f"归属「{context['department_agent']}」，可把「{context['capability_candidate']}」"
            f"细化为「{context['specialized_agent_candidate']}」，{status_text}。"
        ),
    }


def _has_success_after_failure(rows: list[dict[str, Any]]) -> bool:
    seen_failure = False
    for row in rows:
        if row.get("event_type") == "tool.completed" and row.get("status") == "error":
            seen_failure = True
        elif (
            seen_failure
            and row.get("event_type") == "tool.completed"
            and row.get("status") == "success"
        ):
            return True
    return False


@app.get("/api/overview")
def overview(
    range: str = Query("24h"),
    scenario: str = Query("all"),
    agent: str = Query("all"),
) -> dict[str, Any]:
    where_sql, params = _where_filters(range, scenario, agent)
    and_sql, and_params = _and_filters(range, scenario, agent)
    with store.connect() as conn:
        totals = dict(conn.execute(
            f"""
            SELECT COUNT(*) AS events,
                   COUNT(DISTINCT trace_id) AS traces,
                   SUM(CASE WHEN event_type = 'tool.completed' THEN 1 ELSE 0 END) AS tools,
                   SUM(CASE WHEN event_type = 'skill.used' THEN 1 ELSE 0 END) AS skills,
                   SUM(CASE WHEN status IN ('error', 'interrupted')
                             OR event_type IN ('task.failed', 'task.interrupted')
                            THEN 1 ELSE 0 END) AS failures,
                   ROUND(AVG(CASE WHEN event_type = 'llm.completed' THEN duration_ms END), 1) AS avg_llm_ms
            FROM events
            {where_sql}
            """,
            params,
        ).fetchone())
        for key in ("events", "traces", "tools", "skills", "failures"):
            totals[key] = int(totals.get(key) or 0)

        event_types = _rows(conn, f"""
            SELECT event_type AS name, COUNT(*) AS count
            FROM events
            {where_sql}
            GROUP BY event_type
            ORDER BY count DESC, name ASC
            LIMIT 12
            """, params)
        tools = _rows(conn, f"""
            SELECT name,
                   COUNT(*) AS count,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                   ROUND(AVG(duration_ms), 1) AS avg_ms,
                   MAX(duration_ms) AS max_ms,
                   MAX(created_at) AS last_seen
            FROM events
            WHERE event_type = 'tool.completed'
            {and_sql}
            GROUP BY name
            ORDER BY count DESC, avg_ms DESC
            LIMIT 12
            """, and_params)
        skills = _rows(conn, f"""
            SELECT name,
                   COUNT(*) AS count,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                   MAX(created_at) AS last_seen
            FROM events
            WHERE event_type = 'skill.used'
            {and_sql}
            GROUP BY name
            ORDER BY count DESC, last_seen DESC
            LIMIT 12
            """, and_params)
        failures = [
            _decorate_failure(row)
            for row in _rows(conn, f"""
                SELECT created_at, trace_id, task_id, session_id, event_type,
                       name, status, duration_ms, payload_json
                FROM events
                WHERE (
                    status IN ('error', 'interrupted')
                    OR event_type IN ('task.failed', 'task.interrupted')
                )
                {and_sql}
                ORDER BY created_at DESC
                LIMIT 12
            """, and_params)
        ]
        failure_categories: dict[str, dict[str, Any]] = {}
        for failure in failures:
            category = failure["failure_category"]
            row = failure_categories.setdefault(
                category["code"],
                {
                    "code": category["code"],
                    "label": category["label"],
                    "confidence": category.get("confidence", 0),
                    "suggestions": category.get("suggestions", []),
                    "count": 0,
                },
            )
            row["count"] += 1
        traces = _rows(conn, f"""
            SELECT trace_id,
                   MIN(created_at) AS started_at,
                   MAX(created_at) AS last_seen,
                   COUNT(*) AS events,
                   SUM(CASE WHEN event_type = 'tool.completed' THEN 1 ELSE 0 END) AS tools,
                   SUM(CASE WHEN event_type = 'skill.used' THEN 1 ELSE 0 END) AS skills,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                   MAX(task_id) AS task_id,
                   MAX(session_id) AS session_id
            FROM events
            {where_sql}
            GROUP BY trace_id
            ORDER BY last_seen DESC
            LIMIT 12
            """, params)
        opportunities = _automation_opportunities(conn, range, scenario, agent)
        skill_priorities = _skill_refinement_priorities(conn, range, scenario, agent)

    return {
        "range": range,
        "scenario": scenario,
        "agent": agent,
        "scenarios": [{key: value for key, value in item.items() if key != "task_ids"} for item in SCENARIOS],
        "agents": [{key: value for key, value in item.items() if key != "task_ids"} for item in AGENTS],
        "paths": {"sqlite": str(store.sqlite_path()), "jsonl": str(store.events_jsonl_path())},
        "totals": totals,
        "event_types": event_types,
        "tools": tools,
        "skills": skills,
        "failures": failures,
        "failure_categories": sorted(failure_categories.values(), key=lambda item: (-item["count"], item["label"])),
        "skill_priorities": skill_priorities,
        "opportunities": opportunities,
        "traces": traces,
    }


@app.get("/api/events")
def events(
    limit: int = Query(30, ge=1, le=500),
    range: str = Query("24h"),
    scenario: str = Query("all"),
    agent: str = Query("all"),
) -> dict[str, Any]:
    where_sql, params = _where_filters(range, scenario, agent)
    with store.connect() as conn:
        result = [
            _payload(row)
            for row in _rows(conn, f"""
                SELECT event_id, created_at, trace_id, task_id, session_id,
                       event_type, span_type, name, status, duration_ms,
                       model, provider, payload_json
                FROM events
                {where_sql}
                ORDER BY created_at DESC
                LIMIT ?
            """, (*params, _limit(limit, maximum=500)))
        ]
    return {"events": result}


@app.get("/api/traces/{trace_id}")
def trace_detail(trace_id: str) -> dict[str, Any]:
    with store.connect() as conn:
        result = [
            _payload(row)
            for row in _rows(conn, """
                SELECT event_id, created_at, trace_id, task_id, session_id,
                       event_type, span_type, name, status, duration_ms,
                       model, provider, payload_json
                FROM events
                WHERE trace_id = ?
                ORDER BY created_at ASC
            """, (trace_id,))
        ]
    if not result:
        return {"trace_id": trace_id, "summary": {}, "events": [], "failures": []}

    failures = [
        row
        for row in result
        if row.get("status") in {"error", "interrupted"}
        or row.get("event_type") in {"task.failed", "task.interrupted"}
    ]
    for failure in failures:
        failure["failure_category"] = classify_failure(failure)

    story = _build_trace_story(result, failures)
    summary = {
        "trace_id": trace_id,
        "task_id": result[-1].get("task_id") or result[0].get("task_id") or "",
        "session_id": result[-1].get("session_id") or result[0].get("session_id") or "",
        "events": len(result),
        "tools": sum(1 for row in result if row.get("event_type") == "tool.completed"),
        "skills": sum(1 for row in result if row.get("event_type") == "skill.used"),
        "errors": len(failures),
        "started_at": result[0]["created_at"],
        "ended_at": result[-1]["created_at"],
        "observed_duration_ms": sum(int(row["duration_ms"]) for row in result if row.get("duration_ms") is not None),
        "user_request": _first_payload_value(result, "user_request"),
        "scenario_label": _first_payload_value(result, "scenario_label"),
        "story": story,
        "automation_opportunity": _trace_automation_opportunity(result, failures),
    }
    return {"trace_id": trace_id, "summary": summary, "events": result, "failures": failures}


@app.get("/api/export")
def export(
    limit: int = Query(1000, ge=1, le=5000),
    range: str = Query("24h"),
    scenario: str = Query("all"),
    agent: str = Query("all"),
) -> dict[str, str]:
    task_ids = _scenario_task_ids(scenario)
    agent_task_ids = _agent_task_ids(agent)
    if task_ids and agent_task_ids:
        task_ids = [task_id for task_id in task_ids if task_id in set(agent_task_ids)]
    elif agent_task_ids:
        task_ids = agent_task_ids
    path = store.export_events(
        limit=_limit(limit, default=1000, maximum=5000),
        started_after=_range_start(range),
        task_ids=task_ids,
    )
    return {"path": str(path)}


@app.get("/api/export/download")
def export_download(
    limit: int = Query(1000, ge=1, le=5000),
    range: str = Query("24h"),
    scenario: str = Query("all"),
    agent: str = Query("all"),
) -> FileResponse:
    task_ids = _scenario_task_ids(scenario)
    agent_task_ids = _agent_task_ids(agent)
    if task_ids and agent_task_ids:
        task_ids = [task_id for task_id in task_ids if task_id in set(agent_task_ids)]
    elif agent_task_ids:
        task_ids = agent_task_ids
    path = store.export_events(
        limit=_limit(limit, default=1000, maximum=5000),
        started_after=_range_start(range),
        task_ids=task_ids,
    )
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"agent-observability-{scenario}-{range}.json",
    )


@app.post("/api/demo/reset")
def reset_demo_data() -> dict[str, str]:
    store.seed_sample_data(force=True)
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(DASHBOARD_DIR / "index.html")


app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")


def main() -> None:
    uvicorn.run("server.main:app", host="127.0.0.1", port=9120, reload=False)


if __name__ == "__main__":
    main()
