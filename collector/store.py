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

    samples = [
        ("task-code-fix", "code_fix", "正常代码修复", -52, "修复 auth refresh 相关的 pytest 失败", "terminal", "success", 410),
        ("task-code-fix", "code_fix", "正常代码修复", -51, "修复 auth refresh 相关的 pytest 失败", "read_file", "success", 160),
        ("task-code-fix", "code_fix", "正常代码修复", -50, "修复 auth refresh 相关的 pytest 失败", "apply_patch", "success", 90),
        ("task-code-fix", "code_fix", "正常代码修复", -48, "修复 auth refresh 相关的 pytest 失败", "terminal", "success", 1230),
        ("task-permission", "permission", "权限失败排查", -38, "从 home 目录启动 dashboard", "terminal", "error", 75),
        ("task-permission", "permission", "权限失败排查", -37, "从 home 目录启动 dashboard", "terminal", "success", 180),
        ("task-research", "skill", "Skill 触发分析", -24, "总结 Agent 观测机制的常见模式", "web_search", "success", 860),
        ("task-research", "skill", "Skill 触发分析", -23, "总结 Agent 观测机制的常见模式", "skill_view", "success", 40),
        ("task-timeout", "timeout", "工具超时重试", -13, "拉取远程 trace 导出文件", "http_fetch", "error", 10000),
        ("task-timeout", "timeout", "工具超时重试", -12, "拉取远程 trace 导出文件", "http_fetch", "success", 1450),
    ]

    for task_id, scenario, scenario_label, minute, user_message, tool_name, status, tool_ms in samples:
        base_payload = {
            "scenario": scenario,
            "scenario_label": scenario_label,
            "user_request": user_message,
        }
        record_event(
            event_type="llm.requested",
            task_id=task_id,
            session_id=task_id,
            span_type="llm",
            name="api_call_1",
            status="started",
            model="gpt-5",
            provider="demo",
            payload={**base_payload, "user_message": text_summary(user_message), "message_count": 2},
            created_at=_at(minute),
        )
        record_event(
            event_type="llm.completed",
            task_id=task_id,
            session_id=task_id,
            span_type="llm",
            name="api_call_1",
            status="success",
            duration_ms=2100 + (tool_ms // 3),
            model="gpt-5",
            provider="demo",
            payload={**base_payload, "finish_reason": "tool_calls"},
            created_at=_at(minute + 1),
        )
        if tool_name == "skill_view":
            record_event(
                event_type="skill.used",
                task_id=task_id,
                session_id=task_id,
                span_type="skill",
                name="researcher",
                status="success",
                payload={**base_payload, "source": "skill_view"},
                created_at=_at(minute + 2),
            )
        record_event(
            event_type="tool.completed",
            task_id=task_id,
            session_id=task_id,
            span_type="tool",
            name=tool_name,
            status=status,
            duration_ms=tool_ms,
            payload={**base_payload, "error": _sample_error(tool_name) if status == "error" else "", "ok": status == "success"},
            created_at=_at(minute + 3),
        )
        record_event(
            event_type="task.failed" if status == "error" else "task.completed",
            task_id=task_id,
            session_id=task_id,
            span_type="task",
            name="agent_task",
            status="error" if status == "error" else "success",
            payload={**base_payload, "final_response_chars": 420, "failed": status == "error"},
            created_at=_at(minute + 4),
        )


def _sample_error(tool_name: str) -> str:
    if tool_name == "terminal":
        return "Permission denied: /home/felix/.hermes/dashboard.log，当前用户没有写入权限"
    if tool_name == "http_fetch":
        return "request timed out after 10s，远程 trace 导出接口超时"
    return "tool execution failed，工具执行失败"
