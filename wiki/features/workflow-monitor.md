# 流程监控面板

面向用户和管理员的 Snakemake 分析任务实时监控面板。

## 设计原则

- 模板驱动，而非硬编码图表
- YAML 定义模板，后端提供数据，前端按模板渲染
- 支持按角色过滤 widget

## 模板目录

```text
tool_configs/workflow_monitor/
├── README.md
└── templates/
    ├── default.yaml
    ├── admin.yaml
    └── user.yaml
```

## Widget 类型

| 类型 | 用途 |
|---|---|
| `metric` | 顶部指标卡 |
| `task_table` | 运行中任务列表 |
| `event_stream` | 实时事件流 |
| `error_list` | 近期失败摘要 |
| `rule_timeline` | 单任务 Rule 时间线 |
| `worker_status` | 管理员专用 Worker 状态 |

## 后端 API

| 接口 | 说明 |
|---|---|
| `GET /api/v1/workflow-monitor/templates` | 可用模板列表 |
| `GET /api/v1/workflow-monitor/templates/{id}` | 模板详情 |
| `POST /api/v1/workflow-monitor/templates/reload` | 管理员重载模板 |
| `GET /api/v1/workflow-monitor/overview` | 总览数据 |
| `GET /api/v1/workflow-monitor/tasks/{id}/summary` | 单任务摘要 |
| `GET /api/v1/workflow-monitor/tasks/{id}/events` | 事件查询 |
| `WS /api/v1/workflow-monitor/ws` | 全局监控 WebSocket |
| `WS /api/v1/workflow-monitor/tasks/{id}/ws` | 单任务监控 WebSocket |

## Redis 数据结构

| 用途 | Key |
|---|---|
| 任务摘要 | `workflow_monitor:task:{task_id}:summary` |
| 最近事件 | `workflow_monitor:task:{task_id}:events` |
| 全局运行中任务 | `workflow_monitor:running_tasks` |
| Pub/Sub | `workflow_monitor:global` / `workflow_monitor:user:{user_id}` / `workflow_monitor:task:{task_id}` |
