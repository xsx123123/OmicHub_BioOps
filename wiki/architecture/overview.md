# 系统架构总览

OmicHub 是私有化多组学分析平台。它将面向用户的控制面、可扩展的计算 Worker、共享数据目录和
可配置的 AI/知识库能力分开部署，以便从单机逐步扩展到跨机器、HPC 或 Kubernetes。

## 技术栈

| 层级 | 当前实现 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Pinia；Naive UI 与 Arco Design Vue 共用设计令牌 |
| 后端 | FastAPI、Pydantic v2、SQLAlchemy 2.0、DDD 分层 |
| 数据与检索 | PostgreSQL；可选 pgvector、只读副本、备份与指标验收 |
| 异步任务 | Celery 为默认队列；可按配置启用 RocketMQ Worker |
| 分析执行 | Snakemake、独立 Worker / 运行时镜像、共享存储 |
| AI | OpenAI-compatible Provider、SSE、MCP、Skill、Agent 配置与工作台 |
| 部署 | Docker Compose 主栈 + Worker 栈；支持跨机器与逐步扩展 |

## 分层与职责

```text
Browser
  ↓ HTTPS / SSE
Nginx → FastAPI (/api/v1)
  ├─ api/            HTTP、SSE、鉴权入口
  ├─ application/    用例服务、DTO、事务编排
  ├─ domain/         业务规则、状态和契约
  └─ infrastructure/ 数据库、队列、文件、模型与外部系统适配
  ↓
PostgreSQL / Redis / 可选 RocketMQ / Worker / Snakemake / 共享存储
```

前端不直接访问数据库或 Worker；路由层只负责请求校验和授权，业务规则放在应用与领域层，外部系统
通过基础设施适配层隔离。

## 关键领域

| 领域 | 责任 |
| --- | --- |
| 身份与权限 | 用户、角色、项目/工作区隔离、审计 |
| 文件与存储 | 上传、用户目录、产物、配额和文件引用 |
| Flow 与任务 | YAML 流程定义、参数契约、任务状态、日志和交付 |
| AI 与 Agent | 会话、消息、Provider、工具、技能、记忆、路由与协作 |
| 知识库 | 文档版本、附件、分块、关键词与向量检索 |
| 参考数据与工具 | 参考基因组、JBrowse、平台工具和运行时镜像 |

## 关键数据流

- **交互请求**：浏览器 → Nginx → FastAPI → 应用服务 → PostgreSQL / 存储。
- **分析任务**：API → 队列 → Worker → Snakemake / 运行时镜像 → 共享存储 → 任务与产物记录。
- **AI 对话**：浏览器 → SSE → Agent 服务 → Provider、知识库、MCP / Skill → 结构化事件和消息记录。
- **知识库更新**：Markdown 源内容 → 同步脚本 → 数据库版本 → 分块/向量索引 → `knowledge_search`。

## 权威配置位置

| 变更类型 | 位置 |
| --- | --- |
| 环境与服务开关 | `.env.example`、`.env`、`data/OmicHub.yaml` |
| Agent、工具和提示词 | `data/ai/` |
| 流程定义 | `flows/` 与 `pipelines/` |
| 工具配置 | `tool_configs/` |
| 用户帮助与知识库源 | `wiki/`、`docs/knowledge/` |

具体目录见 [项目结构](../development/project-structure) 和 [数据目录结构](data-directory)。
