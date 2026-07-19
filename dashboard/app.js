(function () {
  "use strict";

  const app = document.getElementById("app");
  const state = {
    range: "24h",
    scenario: "all",
    agent: "engineering",
    scenarios: [],
    agents: [],
    overview: null,
    events: [],
    trace: null,
    selectedTraceId: "",
    loading: true,
    error: "",
    exportMessage: "",
  };

  const ranges = [
    ["1h", "1 小时"],
    ["24h", "24 小时"],
    ["7d", "7 天"],
    ["all", "全部"],
  ];

  const defaultScenarios = [
    { id: "all", label: "全部场景", description: "展示所有样例 trace" },
    { id: "code_fix", label: "正常代码修复", description: "代码修改、测试验证和任务完成链路" },
    { id: "permission", label: "权限失败排查", description: "权限错误、修复动作和重试结果" },
    { id: "timeout", label: "工具超时重试", description: "远程请求超时和后续成功重试" },
    { id: "skill", label: "Skill 触发分析", description: "研究类任务中的 Skill 使用链路" },
  ];
  const defaultAgents = [
    { id: "engineering", label: "研发部通用 Agent", department: "研发部" },
    { id: "platform", label: "平台工程部通用 Agent", department: "平台工程部" },
    { id: "product_ops", label: "产品运营部通用 Agent", department: "产品运营部" },
    { id: "data_ops", label: "数据运营部通用 Agent", department: "数据运营部" },
    { id: "strategy", label: "战略分析部通用 Agent", department: "战略分析部" },
    { id: "sales_enablement", label: "售前支持部通用 Agent", department: "售前支持部" },
  ];

  const eventLabels = {
    "llm.requested": "LLM 请求",
    "llm.completed": "LLM 完成",
    "tool.completed": "工具完成",
    "skill.used": "Skill 使用",
    "task.completed": "任务完成",
    "task.failed": "任务失败",
    "task.interrupted": "任务中断",
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

  function fmtPercent(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) ? Math.round(n * 100) + "%" : "0%";
  }

  function dateShort(value) {
    if (!value) return "";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  }

  function shortId(value) {
    return String(value || "").slice(0, 12);
  }

  function compactText(value, max = 42) {
    const text = String(value || "");
    return text.length > max ? text.slice(0, max - 1) + "..." : text;
  }

  function eventLabel(value) {
    return eventLabels[value] || value || "-";
  }

  function statusLabel(value) {
    if (value === "started") return "开始";
    if (value === "success") return "成功";
    if (value === "error") return "错误";
    if (value === "interrupted") return "中断";
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
    state.exportMessage = "";
    render();
    try {
      const query = "?range=" + encodeURIComponent(state.range) + "&scenario=" + encodeURIComponent(state.scenario) + "&agent=" + encodeURIComponent(state.agent);
      const [overview, recent] = await Promise.all([
        getJSON("/api/overview" + query),
        getJSON("/api/events?limit=30&range=" + encodeURIComponent(state.range) + "&scenario=" + encodeURIComponent(state.scenario) + "&agent=" + encodeURIComponent(state.agent)),
      ]);
      state.overview = overview;
      state.events = recent.events || [];
      state.scenarios = overview.scenarios || defaultScenarios;
      state.agents = overview.agents || defaultAgents;
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
    const url = "/api/export/download?range=" + encodeURIComponent(state.range) + "&scenario=" + encodeURIComponent(state.scenario) + "&agent=" + encodeURIComponent(state.agent) + "&limit=1000";
    const link = document.createElement("a");
    link.href = url;
    link.download = "agent-observability-" + state.range + ".json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    state.exportMessage = "已开始下载当前时间范围的 JSON 文件。";
    render();
  }

  async function resetDemo() {
    await getJSON("/api/demo/reset", { method: "POST" });
    state.selectedTraceId = "";
    state.trace = null;
    await load();
  }

  async function changeScenario(scenario) {
    state.scenario = scenario;
    state.selectedTraceId = "";
    state.trace = null;
    await load();
  }

  async function changeAgent(agent) {
    state.agent = agent;
    state.selectedTraceId = "";
    state.trace = null;
    await load();
  }

  function kpi(label, value, hint) {
    return `<div class="kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${hint ? `<small>${escapeHtml(hint)}</small>` : ""}</div>`;
  }

  function bars(rows, labelKey = "name", labelFn = null) {
    if (!rows || !rows.length) return `<div class="empty">暂无数据。</div>`;
    const max = Math.max(1, ...rows.map((row) => Number(row.count || 0)));
    return `<div class="bars">${rows.map((row) => {
      const label = labelFn ? labelFn(row) : row.label || row[labelKey] || row.name;
      const width = Math.max(4, Math.round((Number(row.count || 0) / max) * 100));
      return `<div class="bar-row">
        <span title="${escapeHtml(label)}">${escapeHtml(label)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
        <code>${fmtNumber(row.count)}</code>
      </div>`;
    }).join("")}</div>`;
  }

  function toolTable(rows) {
    if (!rows || !rows.length) return `<div class="empty">暂无工具调用记录。</div>`;
    return `<table><thead><tr><th>工具</th><th>调用次数</th><th>错误</th><th>平均耗时</th><th>最长耗时</th></tr></thead><tbody>
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
    if (!rows || !rows.length) return `<div class="empty">暂无 Skill 使用记录。</div>`;
    return `<table><thead><tr><th>Skill</th><th>使用次数</th><th>错误</th><th>最近出现</th></tr></thead><tbody>
      ${rows.map((row) => `<tr>
        <td><code>${escapeHtml(row.name)}</code></td>
        <td>${fmtNumber(row.count)}</td>
        <td class="${row.errors ? "error" : ""}">${fmtNumber(row.errors)}</td>
        <td>${dateShort(row.last_seen)}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function compactList(items, max = 2) {
    const values = Array.isArray(items) ? items : [];
    if (!values.length) return "-";
    const shown = values.slice(0, max).join(" / ");
    return values.length > max ? shown + " +" + (values.length - max) : shown;
  }

  function skillPriorityTable(rows) {
    if (!rows || !rows.length) return `<div class="empty">暂无高频 Skill 数据。</div>`;
    return `<table class="clickable opportunity-table"><thead><tr><th>高频 Skill</th><th>调用频率</th><th>覆盖流程</th><th>最终成功率</th><th>中间失败</th><th>平均耗时</th><th>工具调用</th><th>下钻判断</th></tr></thead><tbody>
      ${rows.map((row) => `<tr data-trace-id="${escapeHtml(row.primary_trace_id)}">
        <td><code>${escapeHtml(row.skill)}</code></td>
        <td><strong>${fmtNumber(row.trace_count)}</strong> 次</td>
        <td title="${escapeHtml((row.workflows || []).join(" / "))}">${escapeHtml(compactList(row.workflows))}</td>
        <td>${fmtPercent(row.success_rate)}</td>
        <td>${fmtNumber(row.intermediate_failure_traces)} 次 / ${fmtPercent(row.intermediate_failure_rate)}</td>
        <td>${fmtMs(row.avg_duration_ms)}</td>
        <td>${fmtNumber(row.tool_calls)}</td>
        <td title="${escapeHtml(row.evidence || "")}">${escapeHtml(row.recommendation)}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function skillBundle(skills) {
    const values = Array.isArray(skills) ? skills : [];
    if (!values.length) return "-";
    return `<div class="skill-bundle">${values.slice(0, 4).map((skill) => `<code>${escapeHtml(skill)}</code>`).join("")}${values.length > 4 ? `<span>+${values.length - 4}</span>` : ""}</div>`;
  }

  function opportunityTable(rows) {
    if (!rows || !rows.length) return `<div class="empty">暂无部门内专项化候选。</div>`;
    return `<table class="clickable opportunity-table"><thead><tr><th>业务流程</th><th>高频 Skill</th><th>Skill 组合</th><th>全流程专项 Agent</th><th>Trace 数</th><th>最终成功率</th><th>中间失败</th><th>平均耗时</th><th>工具调用</th><th>下钻判断</th></tr></thead><tbody>
      ${rows.map((row) => `<tr data-trace-id="${escapeHtml(row.primary_trace_id)}">
        <td>${escapeHtml(row.workflow_label)}</td>
        <td><code>${escapeHtml(row.candidate_skill)}</code></td>
        <td>${skillBundle(row.skill_bundle)}</td>
        <td>${escapeHtml(row.specialized_agent_candidate || row.agent_candidate)}</td>
        <td>${fmtNumber(row.trace_count)}</td>
        <td>${fmtPercent(row.success_rate)}</td>
        <td>${fmtNumber(row.intermediate_failure_traces)} 次 / ${fmtPercent(row.intermediate_failure_rate)}</td>
        <td>${fmtMs(row.avg_duration_ms)}</td>
        <td>${fmtNumber(row.tool_calls)}</td>
        <td title="${escapeHtml(row.evidence || "")}">${escapeHtml(row.recommendation)}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function traceTable(rows) {
    if (!rows || !rows.length) return `<div class="empty">暂无 trace 记录。</div>`;
    return `<table class="clickable"><thead><tr><th>Trace</th><th>事件数</th><th>工具</th><th>Skills</th><th>错误</th><th>最近出现</th></tr></thead><tbody>
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
    if (!rows || !rows.length) return `<div class="empty">暂无失败记录。</div>`;
    return `<table class="clickable"><thead><tr><th>时间</th><th>分类</th><th>事件</th><th>名称</th><th>建议</th><th>Trace</th></tr></thead><tbody>
      ${rows.map((row) => {
        const suggestions = row.failure_category && row.failure_category.suggestions ? row.failure_category.suggestions : [];
        const firstSuggestion = suggestions[0] || "打开 trace 查看上下文";
        return `<tr data-trace-id="${escapeHtml(row.trace_id)}">
        <td>${dateShort(row.created_at)}</td>
        <td class="error">${escapeHtml(row.failure_category ? row.failure_category.label : "未分类")}</td>
        <td>${escapeHtml(eventLabel(row.event_type))}</td>
        <td><code>${escapeHtml(row.name || "agent_task")}</code></td>
        <td title="${escapeHtml(firstSuggestion)}">${escapeHtml(compactText(firstSuggestion))}</td>
        <td><code>${shortId(row.trace_id)}</code></td>
      </tr>`;
      }).join("")}
    </tbody></table>`;
  }

  function traceDetail() {
    const detail = state.trace;
    if (!detail || !detail.events || !detail.events.length) {
      return `<div class="empty">选择一条 trace 查看完整时间线。</div>`;
    }
    const summary = detail.summary || {};
    const story = summary.story || {};
    const opportunity = summary.automation_opportunity || {};
    return `<div class="trace-detail">
      <div class="trace-request">
        <span>用户请求</span>
        <strong>${escapeHtml(summary.user_request || "暂无请求摘要")}</strong>
        ${summary.scenario_label ? `<em>${escapeHtml(summary.scenario_label)}</em>` : ""}
      </div>
      <div class="trace-story">
        <span>任务故事</span>
        <strong>${escapeHtml(story.summary || "暂无阶段归纳")}</strong>
        ${story.phases && story.phases.length ? `<div class="phase-chain">${story.phases.map((phase) => `<b>${escapeHtml(phase)}</b>`).join("<i>→</i>")}</div>` : ""}
      </div>
      ${story.next_actions && story.next_actions.length ? `<div class="trace-actions">
        <span>建议动作</span>
        <ul>${story.next_actions.map((action) => `<li>${escapeHtml(action)}</li>`).join("")}</ul>
      </div>` : ""}
      ${opportunity.agent_candidate ? `<div class="trace-opportunity">
        <span>部门内专项化判断</span>
        <strong>${escapeHtml(opportunity.recommendation)}</strong>
        <div class="opportunity-meta">
          <b>${escapeHtml(opportunity.department_agent || opportunity.department_label)}</b>
          <b>${escapeHtml(opportunity.capability_candidate || opportunity.candidate_skill)}</b>
          <b>${escapeHtml(opportunity.workflow_label)}</b>
        </div>
      </div>` : ""}
      <div class="trace-summary">
        ${kpi("Trace", shortId(summary.trace_id))}
        ${kpi("事件", fmtNumber(summary.events))}
        ${kpi("工具", fmtNumber(summary.tools))}
        ${kpi("错误", fmtNumber(summary.errors))}
        ${kpi("观测耗时", fmtMs(summary.observed_duration_ms))}
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
    const data = state.overview || { totals: {}, event_types: [], failure_categories: [], skill_priorities: [], opportunities: [], traces: [], tools: [], skills: [], failures: [] };
    const totals = data.totals || {};
    const scenarios = state.scenarios.length ? state.scenarios : defaultScenarios;
    const agents = state.agents.length ? state.agents : defaultAgents;
    const currentAgent = agents.find((item) => item.id === state.agent) || agents[0] || {};
    app.innerHTML = `
      <header class="hero">
        <div>
          <h1>${escapeHtml(currentAgent.label || "单部门 Agent 观测看板")}</h1>
          <p class="subtitle">单部门 Agent 视角：展示 trace 时间线、工具调用、Skill 高频口径、失败分类和专项化下钻判断。</p>
          <p class="data-note">当前数据为脱敏模拟样例，不包含真实组织、用户、内部系统表名或原始业务数据。</p>
        </div>
        <div class="actions">
          <div class="ranges">${ranges.map(([key, label]) => `<button data-range="${key}" class="${state.range === key ? "active" : ""}">${label}</button>`).join("")}</div>
          <button data-action="refresh">${state.loading ? "刷新中" : "刷新"}</button>
          <button data-action="export">导出 JSON</button>
          <button data-action="reset">重置样例</button>
        </div>
      </header>
      <section class="scenario-strip">
        ${agents.map((item) => `<button data-agent="${escapeHtml(item.id)}" class="${state.agent === item.id ? "active" : ""}">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.department || "")}</span>
        </button>`).join("")}
      </section>
      <section class="scenario-strip compact">
        ${scenarios.map((item) => `<button data-scenario="${escapeHtml(item.id)}" class="${state.scenario === item.id ? "active" : ""}">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.description || "")}</span>
        </button>`).join("")}
      </section>
      ${state.error ? `<div class="banner error">${escapeHtml(state.error)}</div>` : ""}
      ${state.exportMessage ? `<div class="banner">${escapeHtml(state.exportMessage)}</div>` : ""}
      <section class="kpis">
        ${kpi("事件总数", fmtNumber(totals.events))}
        ${kpi("Trace 数", fmtNumber(totals.traces))}
        ${kpi("工具调用", fmtNumber(totals.tools))}
        ${kpi("Skill 使用", fmtNumber(totals.skills))}
        ${kpi("失败次数", fmtNumber(totals.failures))}
        ${kpi("LLM 平均耗时", fmtMs(totals.avg_llm_ms))}
      </section>
      <section class="single">
        ${panel("高频 Skill 下钻分析", skillPriorityTable(data.skill_priorities))}
      </section>
      <section class="single">
        ${panel("专项 Agent 候选链路", opportunityTable(data.opportunities))}
      </section>
      <section class="grid">
        ${panel("事件类型分布", bars(data.event_types, "name", (row) => eventLabel(row.name)))}
        ${panel("失败原因分类", bars(data.failure_categories, "code"))}
      </section>
      <section class="grid traces">
        ${panel("最近 Trace", traceTable(data.traces))}
        ${panel("Trace 详情", traceDetail())}
      </section>
      <section class="grid">
        ${panel("工具性能", toolTable(data.tools))}
        ${panel("Skill 使用", skillTable(data.skills))}
      </section>
      <section class="grid">
        ${panel("失败记录", failureTable(data.failures))}
        ${panel("最近事件", recentEvents())}
      </section>
      <footer>
        <span>脱敏模拟数据，仅用于作品集演示和观测机制说明。</span>
        <code>SQLite: ${escapeHtml(data.paths ? data.paths.sqlite : "")}</code>
      </footer>
    `;
    wire();
  }

  function recentEvents() {
    if (!state.events.length) return `<div class="empty">暂无事件。</div>`;
    return `<table><thead><tr><th>时间</th><th>类型</th><th>名称</th><th>状态</th></tr></thead><tbody>
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
    document.querySelectorAll("[data-scenario]").forEach((button) => {
      button.addEventListener("click", () => changeScenario(button.dataset.scenario));
    });
    document.querySelectorAll("[data-agent]").forEach((button) => {
      button.addEventListener("click", () => changeAgent(button.dataset.agent));
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
