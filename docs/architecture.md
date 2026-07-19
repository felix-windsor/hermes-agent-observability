# Architecture

This project separates an Agent observability loop into four small pieces.

```text
Agent runtime / sample generator
-> collector.store
-> SQLite + JSONL
-> FastAPI analytics API
-> static dashboard
```

## Collector

`collector/store.py` defines the event schema and storage layer. It writes every
event to JSONL for export and SQLite for fast dashboard queries.

Important fields:

```text
event_id, created_at, trace_id, task_id, session_id
event_type, span_type, name, status, duration_ms
model, provider, payload
```

## Analytics API

`server/main.py` provides the dashboard endpoints:

```text
GET /api/overview?range=24h
GET /api/events?range=24h&limit=30
GET /api/traces/{trace_id}
GET /api/export?range=24h&limit=1000
POST /api/demo/reset
```

The API keeps failure classification rule-based so the demo is deterministic:
permission, auth/API key, rate limit, timeout, network, not found, agent failed,
tool error, and unknown.

## Dashboard

The dashboard is intentionally static and dependency-free. It uses native
browser APIs to fetch data and render:

- health KPIs
- event mix
- failure categories
- trace table
- trace timeline
- tool performance
- skill usage
- recent failures and events

## Hermes Integration

The original Hermes integration lives in the Hermes Agent fork branch:

```text
felix-windsor/hermes-agent:agent/local-observability-dashboard
```

That branch shows how the collector hooks into a real Agent runtime. This
standalone repository is the portfolio/demo layer.
