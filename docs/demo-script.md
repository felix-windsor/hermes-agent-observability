# Demo Script

Use this short flow in an interview or portfolio walkthrough.

1. Start the app:

```bash
uvicorn server.main:app --reload --port 9120
```

2. Open the dashboard:

```text
http://127.0.0.1:9120
```

3. Explain the problem:

Agent systems are hard to debug because a final answer hides the chain of LLM
calls, tools, skills, retries, failures, and latency.

4. Show the observability model:

Every runtime step is converted into an event with a trace ID. Events are stored
as JSONL for portability and SQLite for dashboard queries.

5. Walk through the dashboard:

- Use the range picker to switch between 1 hour, 24 hours, 7 days, and all time.
- Point at KPIs for health and latency.
- Open a trace and show the timeline.
- Show failure categories and how they guide debugging.
- Export JSON to show the data can feed offline analysis.

6. Connect it back to the real integration:

The standalone dashboard is extracted from a real Hermes Agent plugin, while the
Hermes branch demonstrates production hooks for LLM calls, tool execution,
skills, and task outcomes.
