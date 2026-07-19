# Hermes Agent 观测看板

一个独立的 Agent Observability 作品集 demo：展示 trace 时间线、工具调用、Skill 使用、失败分类、部门内专项化分析、本地存储和可导出的运行事件。

这个项目是从真实 Hermes Agent 插件中抽出来的独立展示版。Hermes 分支负责说明“如何接入真实 Agent 运行时”，这个仓库负责提供“打开就能看的作品集 demo”。

![观测看板截图](docs/assets/dashboard.png)

## 为什么做

Agent 系统经常像黑盒。用户只能看到最终回答，但看不到：

- 调用了哪些工具
- 激活了哪些 Skill
- 延迟耗在哪里
- 任务为什么失败
- 修改 prompt、tool 或 skill 后效果有没有变好
- 部门通用 Agent 内部哪些 Skill 值得细化成全流程专项 Agent

这个项目把 Agent 的运行步骤抽象成结构化事件，并通过本地看板展示出来，形成一个小而完整的分析闭环。除了排查失败，它也用运行数据分析部门通用 Agent 内部哪些 Skill/流程值得进一步细化，产品化成更精细的全流程专项 Agent。

## 架构图

```mermaid
flowchart LR
  A["Agent hooks<br/>LLM / Tool / Skill / Task"] --> B["Event Store<br/>JSONL + SQLite"]
  B --> C["Analytics API<br/>聚合统计 / Trace 详情 / 导出"]
  C --> D["Dashboard<br/>场景筛选 / 时间线 / 失败分类"]
  D --> E["Opportunity Analysis<br/>部门通用 Agent / Skill / 专项化候选"]
  E --> F["Optimization Loop<br/>定位问题 -> 修改 Agent -> 对比结果"]
  F --> A
```

## 一分钟面试讲法

这个项目解决的是 Agent 运行过程黑盒的问题：用户只看到最终回答，但开发者很难知道中间到底调用了哪个 Tool、触发了哪个 Skill、失败发生在哪一步。

我的做法是在 Agent 的 LLM、Tool、Skill 和任务结果 hook 上采集结构化事件，用 `trace_id` 把一次用户请求串成完整链路。事件同时写入 JSONL 和 SQLite：JSONL 方便导出，SQLite 方便本地分析 API 查询。

看板侧我做了整体 KPI、场景筛选、trace 时间线、用户请求摘要、任务故事归纳、失败原因分类和优化建议。进一步，我给每条 trace 补了部门通用 Agent、业务流程、可细化 Skill、预计人工耗时和风险等级，用这些数据计算“专项化机会分”。

这里的假设不是“一个通用 Agent 给所有部门用”，而是每个部门都有自己的部门通用 Agent。看板要回答的是：在某个部门通用 Agent 内部，哪些 Skill 不是只被调用过，而是真的高频、可复用、风险可控，值得细化成全流程专项 Agent。

## 功能

- 本地 JSONL + SQLite 事件存储
- FastAPI 分析接口
- 静态 Dashboard，无需前端构建
- 首次启动自动生成 18 条 trace、百余条事件的样例数据
- 时间范围筛选：1 小时、24 小时、7 天、全部
- 样例场景切换：正常代码修复、权限失败排查、工具超时重试、Skill 触发分析
- Trace 详情时间线
- Trace 顶部展示用户请求摘要
- Trace 阶段归纳和任务故事摘要
- Tool 性能表
- Skill 使用表
- 失败原因分类与优化建议
- 部门内专项 Agent 候选：按部门通用 Agent、Skill、业务流程、成功率、人工节省时间和风险计算机会分
- 网页直接下载 JSON 导出文件

## 快速启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
uvicorn server.main:app --reload --port 9120
```

打开：

```text
http://127.0.0.1:9120
```

应用会自动生成 18 条 trace、百余条事件的样例数据。需要重置样例数据时运行：

```bash
python scripts/generate_sample_data.py
```

## 数据模型

每个运行步骤都会被存成一个事件：

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

业务机会分析字段也放在 `payload` 里，方便在不改 schema 的情况下扩展：

```text
department / department_label
department_agent
workflow / workflow_label
candidate_skill
capability_candidate
agent_candidate
specialized_agent_candidate
estimated_manual_minutes
human_intervention
automation_fit
risk_level
```

代表性事件类型：

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
GET /api/overview?range=24h&scenario=all
GET /api/events?range=24h&scenario=all&limit=30
GET /api/traces/{trace_id}
GET /api/export?range=24h&scenario=all&limit=1000
GET /api/export/download?range=24h&scenario=all&limit=1000
POST /api/demo/reset
```

支持的时间范围是 `1h`、`24h`、`7d`、`all`。
支持的样例场景是 `all`、`code_fix`、`permission`、`timeout`、`skill`。

## 优化闭环

```text
采集运行事件
-> 查看整体健康度
-> 打开失败或慢 trace
-> 定位 tool、skill、prompt 或权限问题
-> 判断部门通用 Agent 内部的专项化候选
-> 修改 Agent 行为
-> 对比下一次运行结果
```

## 真实 Hermes 集成

真实集成分支在这里：

```text
https://github.com/felix-windsor/hermes-agent/tree/agent/local-observability-dashboard
```

那个分支把观测能力接入了 Hermes Agent 的 LLM、Tool、Skill 和任务结果 hook。这个仓库则保留成轻量、清晰、方便面试展示的独立版本。
