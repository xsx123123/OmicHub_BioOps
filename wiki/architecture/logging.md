# 日志架构

平台日志统一归集到 `/data/omichub/logs/`，兼顾可读文本、结构化 JSON 与容量保护。

## 目录结构

```text
/data/omichub/logs/
├── app/
│   ├── omichub.log        # 可读文本主日志
│   ├── omichub.json.log   # JSON 结构化日志
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
| `OMICHUB_LOG_LEVEL` | `INFO` | stdout 级别 |
| `OMICHUB_LOG_DIR` | `/app/logs` | 容器内日志根目录 |
| `OMICHUB_LOG_ROTATION` | `50 MB` | 单文件轮转阈值 |
| `OMICHUB_LOG_RETENTION` | `30 days` | 保留期 |
| `OMICHUB_LOG_COMPRESSION` | `zip` | 压缩格式 |

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
tail -f /data/omichub/logs/app/omichub.log
tail -f /data/omichub/logs/app/error.log
tail -f /data/omichub/logs/celery/tasks/{task_id}.log
jq 'select(.record.extra.service == "audit")' /data/omichub/logs/app/omichub.json.log
jq 'select(.status >= 500)' /data/omichub/logs/nginx/access.log
```
