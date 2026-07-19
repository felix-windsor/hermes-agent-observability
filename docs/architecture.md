# 架构说明

这个项目把 Agent 观测链路拆成四个很小的部分：

```text
Agent 运行时 / 样例数据生成器
-> collector.store
-> SQLite + JSONL
-> FastAPI 分析 API
-> 静态 Dashboard
```

## Collector

`collector/store.py` 定义事件模型和本地存储层。每条事件会同时写入：

- JSONL：方便导出、离线分析、后续接入数据管道。
- SQLite：方便 Dashboard 做聚合查询。

核心字段：

```text
event_id, created_at, trace_id, task_id, session_id
event_type, span_type, name, status, duration_ms
model, provider, payload
```

## 分析 API

`server/main.py` 提供 Dashboard 所需接口：

```text
GET /api/overview?range=24h
GET /api/events?range=24h&limit=30
GET /api/traces/{trace_id}
GET /api/export?range=24h&limit=1000
GET /api/export/download?range=24h&limit=1000
POST /api/demo/reset
```

失败分类第一版使用规则判断，保持结果稳定、容易解释：

```text
权限问题
认证/API Key 问题
限流
超时
网络问题
资源不存在
Agent 任务失败
工具执行错误
未分类
```

## Dashboard

Dashboard 是静态页面，不需要前端构建。它使用浏览器原生 API 拉取数据并展示：

- 健康度 KPI
- 事件类型分布
- 失败原因分类
- Trace 列表
- Trace 时间线
- Tool 性能
- Skill 使用
- 最近失败和最近事件

## Hermes 集成关系

真实 Hermes 集成在 fork 分支中：

```text
felix-windsor/hermes-agent:agent/local-observability-dashboard
```

那个分支展示如何把 collector 接入真实 Agent 运行时；这个独立仓库是作品集/demo 层。
