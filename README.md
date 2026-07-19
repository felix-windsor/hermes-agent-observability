# Hermes Agent 观测看板

一个独立的 Agent Observability 看板：用于展示单个通用 Agent 的 trace 时间线、工具调用、Skill 使用、失败分类、专项化分析、本地存储和可导出的运行事件。

这个项目把 Agent 运行事件采集、存储、分析 API 和本地看板拆成一个轻量独立版本，便于验证观测链路和分析口径。

> 数据说明：仓库内数据均为脱敏模拟样例，不包含真实组织名称、用户信息、内部系统表名、原始周报或生产业务数据。样例只保留单个通用 Agent 观测与专项化分析的结构和口径。

![观测看板截图](docs/assets/dashboard.png)

## 为什么做

Agent 系统经常像黑盒。用户只能看到最终回答，但看不到：

- 调用了哪些工具
- 激活了哪些 Skill
- 延迟耗在哪里
- 任务为什么失败
- 修改 prompt、tool 或 skill 后效果有没有变好
- 当前通用 Agent 内部哪些 Skill 值得细化成全流程专项 Agent

这个项目把 Agent 的运行步骤抽象成结构化事件，并通过本地看板展示出来，形成一个小而完整的分析闭环。除了排查失败，它也用运行数据分析当前通用 Agent 内部哪些 Skill/流程值得进一步细化，产品化成更精细的全流程专项 Agent。这里最核心的口径是调用频率：越高频的 Skill，越值得继续拆细流程、补工具链和做专项化。

## 架构图

```mermaid
flowchart LR
  A["Agent hooks<br/>LLM / Tool / Skill / Task"] --> B["Event Store<br/>JSONL + SQLite"]
  B --> C["Analytics API<br/>聚合统计 / Trace 详情 / 导出"]
  C --> D["Dashboard<br/>场景筛选 / 时间线 / 失败分类"]
  D --> E["Opportunity Analysis<br/>频率优先 / Skill 组合 / 专项化候选"]
  E --> F["Optimization Loop<br/>定位问题 -> 修改 Agent -> 对比结果"]
  F --> A
```

## 设计思路

Agent 运行过程天然容易变成黑盒：最终回答只能说明结果，不能说明中间调用了哪个 Tool、触发了哪个 Skill、失败发生在哪一步。

这个项目在 LLM、Tool、Skill 和任务结果 hook 上采集结构化事件，用 `trace_id` 把一次用户请求串成完整链路。事件同时写入 JSONL 和 SQLite：JSONL 方便导出，SQLite 方便本地分析 API 查询。

看板侧提供整体 KPI、场景筛选、trace 时间线、用户请求摘要、任务故事归纳、失败原因分类和优化建议。进一步，每条 trace 会补充业务流程、可细化 Skill 和 Skill 组合，用这些结构化字段分析当前通用 Agent 内部哪些能力值得下钻。

这里的页面口径是“单个通用 Agent 的运行观测”。分析链路先看高频 Skill，因为频率越高说明价值越大；再看这些 Skill 通常和哪些能力组合成流程，判断是否值得细化成全流程专项 Agent。

## 功能

- 本地 JSONL + SQLite 事件存储
- FastAPI 分析接口
- 静态 Dashboard，无需前端构建
- 首次启动自动生成 18 条 trace、百余条事件的样例数据
- 时间范围筛选：1 小时、24 小时、7 天、全部
- 样例场景切换：任务处理链路、访问权限校验、工具超时重试、Skill 触发分析
- Trace 详情时间线
- Trace 顶部展示用户请求摘要
- Trace 阶段归纳和任务故事摘要
- Tool 性能表
- Skill 使用表
- 失败原因分类与优化建议
- 高频 Skill 下钻分析：按调用频率、覆盖流程、最终成功率、中间失败、平均耗时和工具调用数排序
- 专项 Agent 候选链路：按业务流程、Skill 组合、Trace 数、最终成功率和中间失败给出下钻判断
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

业务分组字段也放在 `payload` 里，方便在不改 schema 的情况下扩展：

```text
workflow / workflow_label
candidate_skill
capability_candidate
skill_bundle
agent_candidate
specialized_agent_candidate
```

所有样例字段均经过泛化处理，例如：

```text
真实组织名 -> A制造集团 / 某制造企业
内部助手名 -> 当前通用 Agent / 专项 Agent
内部系统表名 -> ERP 接口 / 流程系统 / 数据仓库
精确业务数字 -> 脱敏样例数字或区间化口径
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

## 指标口径

核心指标优先使用 event log 直接统计，避免把估算值包装成确定结论。

```text
调用频率 = 包含该 Skill 的 trace 数
Trace 数 = trace_id 去重数量
工具调用数 = event_type = tool.completed 的数量
平均耗时 = 相关 trace 内 duration_ms 汇总后按 trace 平均
最终成功率 = task.completed 且没有 task.failed/task.interrupted 的 trace 数 / 总 trace 数
中间失败数 = 相关 trace 中出现过非 task 终态 error/interrupted 的 trace 数
中间失败率 = 中间失败数 / 总 trace 数
```

覆盖流程来自结构化业务字段，不是 LLM 主观判断：

```text
覆盖流程 = 包含该 Skill 的 trace 中 workflow_label 去重后的列表
```

真实落地时，`workflow` 可以来自入口路由、Planner 分类、Skill 配置或人工标注。页面里的“下钻判断”是可解释规则，用于辅助排序：

```text
高频 + 流程稳定 + 最终成功率较高 -> 可进入专项 Agent 设计
高频 + 中间失败集中 -> 先治理失败原因
频率不足 -> 继续观察
```

## Dashboard API

```text
GET /api/overview?range=24h&scenario=all
GET /api/events?range=24h&scenario=all&limit=30
GET /api/traces/{trace_id}
GET /api/export?range=24h&scenario=all&limit=1000
GET /api/export/download?range=24h&scenario=all&limit=1000
POST /api/sample/reset
```

支持的时间范围是 `1h`、`24h`、`7d`、`all`。
支持的样例场景是 `all`、`task_flow`、`permission`、`timeout`、`skill`。

## 优化闭环

```text
采集运行事件
-> 查看整体健康度
-> 打开失败或慢 trace
-> 定位 tool、skill、prompt 或权限问题
-> 先看高频 Skill 下钻分析
-> 判断当前通用 Agent 内部的专项化候选
-> 修改 Agent 行为
-> 对比下一次运行结果
```

## 真实 Hermes 集成

真实集成分支在这里：

```text
https://github.com/felix-windsor/hermes-agent/tree/agent/local-observability-dashboard
```

那个分支把观测能力接入了 Hermes Agent 的 LLM、Tool、Skill 和任务结果 hook。这个仓库保留轻量独立版本，用于验证事件模型、分析 API 和本地看板。
