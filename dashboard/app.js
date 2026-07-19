(function () {
  "use strict";

  const app = document.getElementById("app");
  const state = {
    range: "24h",
    overview: null,
    events: [],
    trace: null,
    selectedTraceId: "",
    loading: true,
    error: "",
    exportPath: "",
  };

  const ranges = [
    ["1h", "1 hour"],
    ["24h", "24 hours"],
    ["7d", "7 days"],
    ["all", "All"],
  ];

  const eventLabels = {
    "llm.requested": "LLM requested",
    "llm.completed": "LLM completed",
    "tool.completed": "Tool completed",
    "skill.used": "Skill used",
    "task.completed": "Task completed",
    "task.failed": "Task failed",
    "task.interrupted": "Task interrupted",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function fmtNumber(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) ? n.toLocaleString() : "0";
  }

  function fmtMs(value) {
    if (value === null || value === undefined) return "n/a";
    const n = Number(value);
    if (!Number.isFinite(n)) return "n/a";
    return n >= 1000 ? (n / 1000).toFixed(2) + "s" : Math.round(n) + "ms";
  }

  function dateShort(value) {
    if (!value) return "";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  }

  function shortId(value) {
    return String(value || "").slice(0, 12);
  }

  function eventLabel(value) {
    return eventLabels[value] || value || "-";
  }

  function statusLabel(value) {
    if (value === "success") return "success";
    if (value === "error") return "error";
    if (value === "interrupted") return "interrupted";
    return value || "-";
  }

  function payloadPreview(payload) {
    try {
      return JSON.stringify(payload || {}).slice(0, 260);
    } catch (_err) {
      return "";
    }
  }

  async function getJSON(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  async function load() {
    state.loading = true;
    state.error = "";
    render();
    try {
      const [overview, recent] = await Promise.all([
        getJSON("/api/overview?range=" + encodeURIComponent(state.range)),
        getJSON("/api/events?limit=30&range=" + encodeURIComponent(state.range)),
      ]);
      state.overview = overview;
      state.events = recent.events || [];
      if (!state.selectedTraceId && overview.traces && overview.traces.length) {
        state.selectedTraceId = overview.traces[0].trace_id;
      }
      await loadTrace(state.selectedTraceId, false);
    } catch (err) {
      state.error = err.message || String(err);
    } finally {
      state.loading = false;
      render();
    }
  }

  async function loadTrace(traceId, shouldRender = true) {
    if (!traceId) {
      state.trace = null;
      return;
    }
    state.selectedTraceId = traceId;
    try {
      state.trace = await getJSON("/api/traces/" + encodeURIComponent(traceId));
    } catch (err) {
      state.error = err.message || String(err);
    }
    if (shouldRender) render();
  }

  async function exportEvents() {
    const result = await getJSON("/api/export?range=" + encodeURIComponent(state.range) + "&limit=1000");
    state.exportPath = result.path || "";
    render();
  }

  async function resetDemo() {
    await getJSON("/api/demo/reset", { method: "POST" });
    state.selectedTraceId = "";
    state.trace = null;
    await load();
  }

  function kpi(label, value, hint) {
    return `<div class="kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${hint ? `<small>${escapeHtml(hint)}</small>` : ""}</div>`;
  }

  function bars(rows, labelKey = "name") {
    if (!rows || !rows.length) return `<div class="empty">No data yet.</div>`;
    const max = Math.max(1, ...rows.map((row) => Number(row.count || 0)));
    return `<div class="bars">${rows.map((row) => {
      const label = row.label || row[labelKey] || row.name;
      const width = Math.max(4, Math.round((Number(row.count || 0) / max) * 100));
      return `<div class="bar-row">
        <span title="${escapeHtml(label)}">${escapeHtml(label)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
        <code>${fmtNumber(row.count)}</code>
      </div>`;
    }).join("")}</div>`;
  }

  function toolTable(rows) {
    if (!rows || !rows.length) return `<div class="empty">No tool calls recorded.</div>`;
    return `<table><thead><tr><th>Tool</th><th>Calls</th><th>Errors</th><th>Avg</th><th>Max</th></tr></thead><tbody>
      ${rows.map((row) => `<tr>
        <td><code>${escapeHtml(row.name)}</code></td>
        <td>${fmtNumber(row.count)}</td>
        <td class="${row.errors ? "error" : ""}">${fmtNumber(row.errors)}</td>
        <td>${fmtMs(row.avg_ms)}</td>
        <td>${fmtMs(row.max_ms)}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function skillTable(rows) {
    if (!rows || !rows.length) return `<div class="empty">No skill usage recorded.</div>`;
    return `<table><thead><tr><th>Skill</th><th>Uses</th><th>Errors</th><th>Last seen</th></tr></thead><tbody>
      ${rows.map((row) => `<tr>
        <td><code>${escapeHtml(row.name)}</code></td>
        <td>${fmtNumber(row.count)}</td>
        <td class="${row.errors ? "error" : ""}">${fmtNumber(row.errors)}</td>
        <td>${dateShort(row.last_seen)}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function traceTable(rows) {
    if (!rows || !rows.length) return `<div class="empty">No traces recorded.</div>`;
    return `<table class="clickable"><thead><tr><th>Trace</th><th>Events</th><th>Tools</th><th>Skills</th><th>Errors</th><th>Last seen</th></tr></thead><tbody>
      ${rows.map((row) => `<tr data-trace-id="${escapeHtml(row.trace_id)}" class="${row.trace_id === state.selectedTraceId ? "selected" : ""}">
        <td><code title="${escapeHtml(row.trace_id)}">${shortId(row.trace_id)}</code></td>
        <td>${fmtNumber(row.events)}</td>
        <td>${fmtNumber(row.tools)}</td>
        <td>${fmtNumber(row.skills)}</td>
        <td class="${row.errors ? "error" : ""}">${fmtNumber(row.errors)}</td>
        <td>${dateShort(row.last_seen)}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function failureTable(rows) {
    if (!rows || !rows.length) return `<div class="empty">No failures recorded.</div>`;
    return `<table class="clickable"><thead><tr><th>Time</th><th>Category</th><th>Event</th><th>Name</th><th>Trace</th></tr></thead><tbody>
      ${rows.map((row) => `<tr data-trace-id="${escapeHtml(row.trace_id)}">
        <td>${dateShort(row.created_at)}</td>
        <td class="error">${escapeHtml(row.failure_category ? row.failure_category.label : "Unknown")}</td>
        <td>${escapeHtml(eventLabel(row.event_type))}</td>
        <td><code>${escapeHtml(row.name || "agent_task")}</code></td>
        <td><code>${shortId(row.trace_id)}</code></td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function traceDetail() {
    const detail = state.trace;
    if (!detail || !detail.events || !detail.events.length) {
      return `<div class="empty">Select a trace to inspect the timeline.</div>`;
    }
    const summary = detail.summary || {};
    return `<div class="trace-detail">
      <div class="trace-summary">
        ${kpi("Trace", shortId(summary.trace_id))}
        ${kpi("Events", fmtNumber(summary.events))}
        ${kpi("Tools", fmtNumber(summary.tools))}
        ${kpi("Errors", fmtNumber(summary.errors))}
        ${kpi("Observed", fmtMs(summary.observed_duration_ms))}
      </div>
      <div class="timeline">
        ${detail.events.map((row) => `<div class="timeline-item ${row.status === "error" ? "failed" : ""}">
          <div class="dot"></div>
          <div class="timeline-card">
            <div class="timeline-head">
              <strong>${escapeHtml(eventLabel(row.event_type))}</strong>
              <span>${dateShort(row.created_at)}</span>
            </div>
            <div class="timeline-meta">
              <code>${escapeHtml(row.name || row.span_type || "-")}</code>
              <span class="${row.status === "error" ? "error" : "success"}">${escapeHtml(statusLabel(row.status))}</span>
              ${row.duration_ms === null || row.duration_ms === undefined ? "" : `<span>${fmtMs(row.duration_ms)}</span>`}
            </div>
            ${payloadPreview(row.payload) ? `<pre>${escapeHtml(payloadPreview(row.payload))}</pre>` : ""}
          </div>
        </div>`).join("")}
      </div>
    </div>`;
  }

  function panel(title, body) {
    return `<section class="panel"><div class="panel-head"><h2>${escapeHtml(title)}</h2></div>${body}</section>`;
  }

  function render() {
    const data = state.overview || { totals: {}, event_types: [], failure_categories: [], traces: [], tools: [], skills: [], failures: [] };
    const totals = data.totals || {};
    app.innerHTML = `
      <header class="hero">
        <div>
          <p class="eyebrow">Agent Observability Portfolio Demo</p>
          <h1>Hermes Agent Observability</h1>
          <p class="subtitle">Trace timelines, tool calls, skill usage, failure categories, and exportable runtime events.</p>
        </div>
        <div class="actions">
          <div class="ranges">${ranges.map(([key, label]) => `<button data-range="${key}" class="${state.range === key ? "active" : ""}">${label}</button>`).join("")}</div>
          <button data-action="refresh">${state.loading ? "Refreshing" : "Refresh"}</button>
          <button data-action="export">Export JSON</button>
          <button data-action="reset">Reset demo</button>
        </div>
      </header>
      ${state.error ? `<div class="banner error">${escapeHtml(state.error)}</div>` : ""}
      ${state.exportPath ? `<div class="banner">Exported to <code>${escapeHtml(state.exportPath)}</code></div>` : ""}
      <section class="kpis">
        ${kpi("Events", fmtNumber(totals.events))}
        ${kpi("Traces", fmtNumber(totals.traces))}
        ${kpi("Tool calls", fmtNumber(totals.tools))}
        ${kpi("Skill uses", fmtNumber(totals.skills))}
        ${kpi("Failures", fmtNumber(totals.failures))}
        ${kpi("Avg LLM", fmtMs(totals.avg_llm_ms))}
      </section>
      <section class="grid">
        ${panel("Event mix", bars(data.event_types))}
        ${panel("Failure categories", bars(data.failure_categories, "code"))}
      </section>
      <section class="grid traces">
        ${panel("Recent traces", traceTable(data.traces))}
        ${panel("Trace detail", traceDetail())}
      </section>
      <section class="grid">
        ${panel("Tool performance", toolTable(data.tools))}
        ${panel("Skill usage", skillTable(data.skills))}
      </section>
      <section class="grid">
        ${panel("Failures", failureTable(data.failures))}
        ${panel("Recent events", recentEvents())}
      </section>
      <footer><code>SQLite: ${escapeHtml(data.paths ? data.paths.sqlite : "")}</code></footer>
    `;
    wire();
  }

  function recentEvents() {
    if (!state.events.length) return `<div class="empty">No events yet.</div>`;
    return `<table><thead><tr><th>Time</th><th>Type</th><th>Name</th><th>Status</th></tr></thead><tbody>
      ${state.events.slice(0, 12).map((row) => `<tr>
        <td>${dateShort(row.created_at)}</td>
        <td>${escapeHtml(eventLabel(row.event_type))}</td>
        <td><code>${escapeHtml(row.name || "")}</code></td>
        <td class="${row.status === "error" ? "error" : "success"}">${escapeHtml(statusLabel(row.status))}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function wire() {
    document.querySelectorAll("[data-range]").forEach((button) => {
      button.addEventListener("click", async () => {
        state.range = button.dataset.range;
        state.selectedTraceId = "";
        state.trace = null;
        await load();
      });
    });
    document.querySelectorAll("[data-trace-id]").forEach((row) => {
      row.addEventListener("click", () => loadTrace(row.dataset.traceId));
    });
    document.querySelector('[data-action="refresh"]')?.addEventListener("click", load);
    document.querySelector('[data-action="export"]')?.addEventListener("click", exportEvents);
    document.querySelector('[data-action="reset"]')?.addEventListener("click", resetDemo);
  }

  load();
})();
