# 日志架构

平台日志统一归集到 `/data/cygnusx/logs/`，兼顾可读文本、结构化 JSON 与容量保护。

## 目录结构

```text
/data/cygnusx/logs/
├── app/
│   ├── cygnusx.log        # 可读文本主日志
│   ├── cygnusx.json.log   # JSON 结构化日志
│   └── error.log          # ERROR 级以上
├── celery/tasks/
│   └── {task_id}.log      # 单任务日志
├── nginx/
│   ├── access.log
│   └── error.log
└── snakemake/
    └── {project}/{timestamp}/
        ├── stdout.log
        └── stderr.log
```

## 应用日志环境变量

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `SERVICE_NAME` | `app` | web/beat/worker 标识 |
| `CYGNUSX_LOG_LEVEL` | `INFO` | stdout 级别 |
| `CYGNUSX_LOG_DIR` | `/app/logs` | 容器内日志根目录 |
| `CYGNUSX_LOG_ROTATION` | `50 MB` | 单文件轮转阈值 |
| `CYGNUSX_LOG_RETENTION` | `30 days` | 保留期 |
| `CYGNUSX_LOG_COMPRESSION` | `zip` | 压缩格式 |

## 容量保护策略

| 日志类型 | 策略 | 默认值 |
|---|---|---|
| 应用日志 | loguru rotation/retention | 50 MB / 30 days / zip |
| Celery 单任务日志 | loguru | 20 MB / 7 days / zip |
| Docker stdout | json-file | 50 m × 3 |
| Nginx 日志 | logrotate | 100 M 或 daily，保留 14 轮 |
| Snakemake 日志 | logrotate + crontab | 建议 30 天清理 |
| DB 任务日志 | 仓储截断 | 单条 8192 字符 / 单任务 1000 条 |

## 排障命令

```bash
tail -f /data/cygnusx/logs/app/cygnusx.log
tail -f /data/cygnusx/logs/app/error.log
tail -f /data/cygnusx/logs/celery/tasks/{task_id}.log
jq 'select(.record.extra.service == "audit")' /data/cygnusx/logs/app/cygnusx.json.log
jq 'select(.status >= 500)' /data/cygnusx/logs/nginx/access.log
```

## 可观测性（OpenTelemetry + 业务级事件）

统一埋点产出 Trace / Log / Metrics 三信号：日志自动注入 `trace_id`/`span_id`/`request_id`/`session_id`；
`/metrics` 暴露 Prometheus 指标；AI 调用指标持久化到 `ai_call_metrics` 驱动管理端「AI 指标仪表盘」与
阈值告警（错误率/p95/日成本，`AI_ALERT_*` 配置）；管理端「会话日志排查」（`/admin/session-logs`）
可按会话时间线聚合全部事件。未配置 OTLP 端点时自动降级，**本地与测试零配置可用，遥测异常绝不中断
业务**。覆盖 `ai.chat` / `mcp.call_tool` / `skill.execute` / `agent.run` / `celery.task` / `toolbox.*`
等 span，属性不落密钥。

OTel 之上还有两层业务级观测：**统一生命周期事件框架**（所有执行路径的工具事件按同一 `tool_call_id`
串联 `agent_tool_call → started → result → context_reinjected`，Worker 事件经 Bridge 投影为协作室
证据事件）与 **Case LLM 过程全量记录**（AgentTeams 每个 turn 的 prompt / reasoning / tool_calls /
usage 全文写 MinIO append-only，PostgreSQL `agentteams_turn_records` 存摘要索引，OTel span 只存
`turn_record_uri` 引用——正文绝不进 span/日志/Redis；按角色服务端裁剪，member 不可见 prompt/reasoning
全文）。
