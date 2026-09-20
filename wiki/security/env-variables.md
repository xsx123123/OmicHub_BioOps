# 环境变量与密钥

所有敏感配置放在私有 `.env` 或受控密钥管理系统中；不要将实际密码、Token、Provider API Key 或
生产地址提交到 Git。字段的完整默认值与注释以 `.env.example` 为准。

## 首次部署必填

| 变量 | 作用 |
| --- | --- |
| `JWT_SECRET_KEY` | JWT 签名密钥 |
| `APP_SECRET_KEY` | Cookie / Session 签名密钥 |
| `POSTGRES_PASSWORD` | PostgreSQL 密码 |
| `REDIS_PASSWORD` | Redis 认证密码 |
| `AI_PROVIDER_KEY_ENCRYPTION_KEY` | 加密已保存 AI Provider 密钥的 Fernet 密钥 |
| `OMICHBUB_INIT_ADMIN_PASSWORD` | 生产环境首位管理员强密码 |

`AI_PROVIDER_KEY_ENCRYPTION_KEY` 必须在首次写入加密数据前确定，之后不能更改，否则历史加密字段
无法解密。生产环境必须使用高熵、互不重复的随机值，并限制 `.env` 的文件权限。

## 常见配置组

| 配置组 | 示例变量 | 何时修改 |
| --- | --- | --- |
| 数据根与 HTTP 入口 | `CYGNUSX_DATA_ROOT`、`CYGNUSX_HTTP_*` | 更换数据盘、反向代理或监听地址 |
| AI Provider | `AI_*`、Provider YAML | 接入或轮换模型服务密钥 |
| Worker 与共享存储 | `CYGNUSX_CONTROL_*`、`WORKER_*` | 跨机器或 NAS 挂载部署 |
| 多 Agent 与 AgentTeams | `UNIFIED_INTENT_ROUTER_ENABLED`、`MAS_ENABLED`、`AGENTTEAMS_*` | 灰度启用协作能力 |
| 知识库与检索 | 数据库、模型和缓存相关变量 | 部署向量检索、备份或索引服务 |
| 可观测性 | `TELEMETRY_ENABLED`、`METRICS_ENABLED`、`OTEL_*` | 接入指标和追踪平台 |

## 操作原则

1. 新部署从 `.env.example` 复制，不要从其他环境盲目复制完整 `.env`。
2. 修改密钥、数据库地址、队列或 AI Provider 后，按受影响服务重启，并执行健康检查。
3. 跨机器部署必须让控制面和 Worker 使用一致的认证密钥，同时将数据库、Redis 和 AgentTeams 端口
   限制在可信私网。
4. 排查配置时只记录变量名、是否已设置和脱敏后的状态；不要把完整值写入工单、日志或聊天记录。

安全加固项见 [安全加固清单](hardening-checklist)。
