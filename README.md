# Hermes Agent Observability

A standalone portfolio demo for Agent observability: trace timelines, tool
calls, skill usage, failure classification, local storage, and a dashboard that
opens with sample data.

This project was extracted from a real Hermes Agent plugin. The Hermes branch
shows production integration; this repository focuses on a clean, runnable demo.

## Why

Agent behavior is often a black box. A user sees the final answer, but not:

- which tools were called
- which skills were activated
- where latency accumulated
- why a task failed
- whether a change improved or regressed behavior

This project turns Agent runtime steps into structured events and displays them
as an analysis dashboard.

## Features

- Local JSONL + SQLite event storage
- FastAPI analytics API
- Static dashboard with no frontend build step
- Sample data generated automatically on first launch
- Time range filters: 1 hour, 24 hours, 7 days, all time
- Trace detail timeline
- Tool performance table
- Skill usage table
- Failure category analysis
- JSON export

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
uvicorn server.main:app --reload --port 9120
```

Open:

```text
http://127.0.0.1:9120
```

The app seeds sample traces automatically. To reset the demo data:

```bash
python scripts/generate_sample_data.py
```

## Data Model

Each runtime step is stored as an event:

```text
event_id
created_at
trace_id
task_id
session_id
event_type
span_type
name
status
duration_ms
model
provider
payload
```

Representative event types:

```text
llm.requested
llm.completed
tool.completed
skill.used
task.completed
task.failed
task.interrupted
```

## Dashboard API

```text
GET /api/overview?range=24h
GET /api/events?range=24h&limit=30
GET /api/traces/{trace_id}
GET /api/export?range=24h&limit=1000
POST /api/demo/reset
```

Supported ranges are `1h`, `24h`, `7d`, and `all`.

## Optimization Loop

```text
collect runtime events
-> inspect health metrics
-> open a failed or slow trace
-> identify tool, skill, prompt, or permission issue
-> change the Agent
-> compare the next run
```

## Real Hermes Integration

The integration branch is here:

```text
https://github.com/felix-windsor/hermes-agent/tree/agent/local-observability-dashboard
```

That branch wires observability into Hermes Agent hooks. This repo keeps the
dashboard and analysis path small enough to review and demo quickly.
