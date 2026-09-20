# CygnusX 总体架构

**版本**：v1.0 汇总版  
**日期**：2026-08-22  
**范围**：`ARCHITECTURE_DESIN/` 下项目级架构、现状、设计规范和实施方案  
**文档定位**：统一导航与架构总览，不替代各领域的详细设计文档

> 本文将目录内多个时期的“当前实现”“评审方案”和“未来规划”归并为一张架构地图。凡标记为“规划/候选/待验收”的内容，不应当作已经上线的能力；具体实现以代码、配置和对应领域文档为准。

---

## 1. 一页结论

CygnusX 是一个面向生物信息学和多组学分析的 AI 原生平台，采用 **Vue 3 前端 + FastAPI 应用层 + PostgreSQL/pgvector + Redis/Celery + Docker 沙箱/Worker + MCP/Agent 编排** 的组合架构。

平台当前有四条主要执行形态：

1. **普通 Chat/Agent**：以 `/api/v1/chat/stream` 为统一入口，按 Agent、模型、工具和 MCP 配置装配请求，运行手写 ReAct 或 LangGraph 闭环。
2. **OmicStudio**：面向代码、数据分析、工作区文件和结果产物的交互式工作台；一个会话对应一个 Studio 沙箱容器。
3. **AgentTeams 协作室**：用户、Manager、领域 Agent 和 Worker 通过房间、Case、派单、会诊与事件记录协作。
4. **Pipeline/Worker**：通过 Celery/Snakemake/RNAFlow/ATACFlow 等执行长任务，将输入、日志、状态和结果写入共享存储或对象存储。

横切系统包括：

- **MCP 子系统**：内置 preset、外部 MCP、MCP Builder 和管线工具的注册、发现、调用、审核与隔离。
- **记忆系统**：旧归档、常驻 memory blocks、事实召回、Studio 文件记忆和协作室记忆。
- **知识库系统**：文档、分块、向量索引、审核、问题反馈和知识检索。
- **统一事件与日志**：SSE/UI 事件、结构化应用日志、任务日志、审计日志、工具调用和 AgentTeams 过程记录。

---

## 2. 总体分层

```text
┌────────────────────────────────────────────────────────────────────┐
│                           Presentation Layer                       │
│ Vue3 / TypeScript / Pinia / Monaco / Studio UI / AgentTeams UI     │
└───────────────────────────────┬────────────────────────────────────┘
                                │ REST / WebSocket / SSE
┌───────────────────────────────▼────────────────────────────────────┐
│                           API & Gateway Layer                       │
│ FastAPI v1 routes · JWT · DTO · permission · project/user scope    │
│ chat · studio · sandbox · mcp · mcp-builder · agentteams · reports  │
└───────────────────────────────┬────────────────────────────────────┘
                                │ application services
┌───────────────────────────────▼────────────────────────────────────┐
│                         Application / Orchestration                 │
│ Agent assembly · routing · ReAct/LangGraph · Studio tools           │
│ AgentTeams room/Case/Manager · memory · knowledge · artifact/report │
└───────────────┬──────────────────┬──────────────────┬───────────────┘
                │                  │                  │
┌───────────────▼──────┐ ┌─────────▼─────────┐ ┌──────▼───────────────┐
│ AI / MCP Providers    │ │ Async Execution    │ │ Domain & Persistence │
│ OpenAI-compatible     │ │ Celery / Redis    │ │ SQLAlchemy / Alembic │
│ LangGraph / MCP       │ │ Snakemake / Worker│ │ PostgreSQL / pgvector│
│                       │ │ capabilities      │ │                     │
└───────────────┬──────┘ └─────────┬─────────┘ └──────┬───────────────┘
                │                  │                  │
┌───────────────▼──────────────────▼──────────────────▼───────────────┐
│                         Infrastructure Runtime                      │
│ Docker Studio sandbox · legacy sandbox pool · external Worker images │
│ shared workspace · MinIO/S3 · egress proxy · Nginx · observability   │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.1 跨进程能力边界

- **Knowledge** 是检索、索引和证据获取的跨进程能力集合；Application 层只负责编排、
  权限、上下文和结果投影，不将其表述为已独立存在的内部应用模块。
- **Worker** 是由 Celery、Snakemake 和容器镜像承载的受控执行能力；Application 层负责
  提交、状态契约和审计，不直接拥有 Worker 进程或把它误画为单体内部子模块。
- 未来若将任一能力独立为包或服务，应先定义稳定接口、部署边界和所有权，再调整包结构与
  架构图；在此之前保持“能力集合”的表述。

### 2.2 设计原则

- API 层只负责协议、鉴权、参数校验和调用应用服务，不承载复杂编排。
- 前后端先定义 DTO、事件形状和错误语义，再实现页面或服务。
- 用户、项目、Agent、会话、工作区、数据文件和报告必须有明确的归属边界。
- 长任务走异步任务系统；短交互走流式响应；二者通过稳定的状态和事件契约衔接。
- 沙箱是受限执行环境，不是平台数据库、密钥或整个存储根目录的代理。
- 规划文档与当前实现分离；新增功能必须标明已实现、灰度、候选或未开始。

---

## 3. 核心请求与执行链路

### 3.1 普通 Chat/Agent

```text
用户消息
  → JWT / 用户与项目范围校验
  → 会话与 Agent 装配
  → 模型、系统提示词、工具、MCP、记忆、知识上下文装配
  → 路径登记：Legacy ReAct / LangGraph / Studio / Worker / AgentTeams
  → 模型流式输出
  → 工具调用循环
  → tool_result / tool_output / plan / error / done 事件
  → 消息、工具调用和审计元数据持久化
```

Agent 装配包括：

- Agent 数据库配置、绑定模型和工具包；
- 系统提示词、领域知识和记忆上下文；
- 内置工具、外部 MCP、Skill 和能力渐进披露；
- 会话模式（chat、studio、overdrive 等）；
- loop guard、连续失败熔断、上下文压缩和停止语义。

工具结果使用双通道：

- `llm_payload`：发送给模型的紧凑结果，限制输出和上下文膨胀；
- `ui_payload`：发送给前端的完整结果，包含 diff、产物、执行流和渲染信息。

### 3.2 Studio 执行链

```text
Studio 会话创建
  → Agent studio policy / sandbox_capabilities 校验
  → 选择 analysis-core/analysis-plot/analysis-scrna/base/bio/browser-office 镜像
  → 默认镜像为 cygnusx-analysis:core-v0.0.2dev（default_image）
  → ChatSession.sandbox_meta 持久化 image + sandbox_capabilities
  → StudioSandboxManager 懒启动/预热
  → Docker 每会话一个容器
  → /workspace/.agent.sock 访问 sandbox-agent
  → sandbox_execute / workspace_* / artifact / plan 工具
  → output 产物、报告版本树和前端 Studio 面板
```

### 3.3 AgentTeams 执行链

```text
用户进入协作室
  → 房间意图路由
  → 直接回复 / Case 执行 / Manager 会诊 / 人工澄清
  → Manager 生成计划并派单领域 Agent
  → Worker 受限执行并回传事件
  → Bridge / Gateway 聚合消息、状态、血缘和判决
  → 房间消息、Case、Turn、通知和报告归档
```

---

## 4. 后端与数据边界

### 4.1 API 域

主要 API 前缀：

| 域 | 前缀 | 职责 |
|---|---|---|
| Chat | `/api/v1/chat` | 普通对话、SSE 流、消息与工具事件 |
| Studio | `/api/v1/studio` | Studio 会话、工作区、运行、产物、分享和权限 |
| Legacy Sandbox | `/api/v1/sandbox` | 旧代码执行沙箱的会话、REST、WebSocket |
| MCP | `/api/v1/mcp` | MCP 注册、发现、绑定和调用 |
| MCP Builder | `/api/v1/mcp-builder` | MCP 生成、静态检查、测试、审核和生命周期 |
| AgentTeams | `/api/v1/agent-teams` | 协作室、Case、成员、通知、审计和过程报告 |
| Reports | 相关报告路由 | 结果、产物、版本树和下载 |
| Terminal | `/api/v1/terminal` | 云端终端会话和资源配置 |

所有路由应遵循：

1. 先校验当前用户、会话/资源归属和项目范围；
2. 使用 Pydantic DTO 明确输入输出；
3. 将业务逻辑委托给 application service；
4. 对流式事件保持稳定 `type`、`tool_call_id`、`session_id` 和追踪字段；
5. 不向客户端泄漏其他用户、内部路径、密钥或容器网络信息。

### 4.2 主要持久化域

- **用户与身份**：用户、权限、Agent、项目和组织范围。
- **聊天**：`chat_sessions`、消息、工具调用元数据、会话模式和 Studio `sandbox_meta`。
- **Studio/沙箱**：工作区、容器状态、活跃时间、执行租约、文件、产物和报告关联。
- **流程任务**：任务、运行状态、Celery/Snakemake 日志、输入、结果和失败信息。
- **MCP**：Server、工具、绑定、调用日志、Builder 构建、版本、审核和实验 TTL。
- **知识与记忆**：知识文档、分块、向量索引、memory blocks、memory facts、旧归档和审计。
- **AgentTeams**：房间、成员、Case、Turn、派单、事件、判决、通知和报告。

数据库迁移必须通过 Alembic；JSONB 字段扩展要考虑并发写入、旧数据兼容和回滚策略。

---

## 5. Agent 架构

### 5.1 Agent 形态

| 形态 | 特征 | 适用场景 |
|---|---|---|
| Legacy 手写 ReAct | 轻量工具循环、兼容旧链路 | 普通聊天和既有工具 |
| LangGraph ReAct | 显式图状态、节点和边 | 复杂检索、规划和可观测执行 |
| Studio Agent | 工作区、代码、文件和产物工具 | 交互式数据分析 |
| Worker ReAct | 受限任务执行、偏后台 | 长任务和受控流程 |
| AgentTeams | Manager/领域 Agent/Worker 协作 | 多专家协作与 Case |

### 5.2 统一保护

- 每轮工具调用有上限；连续失败触发熔断或降级。
- `update_plan` 产生前端 `plan` 事件并持久化计划。
- 工具调用必须能关联到用户、会话、Agent、消息和执行路径。
- 流式输出之后不重复重放正文；断线重连依赖事件 ID、消息持久化和历史重建。
- `ask_user` 用于缺少物种、文件、参数或任务边界时的澄清，不允许模型编造关键输入。

### 5.3 扩展规则

- 只给现有 Agent 授权工具：修改工具包 YAML/数据库绑定，不复制实现。
- 新增内置工具：定义 schema、application service、权限、审计、前端投影和测试。
- 新增 MCP：先注册、发现、验证、审核，再进入 Agent 的可用工具目录。
- 不把路由器当编排器，不在 prompt 中假装已有不存在的工具。

---

## 6. AgentTeams 协作室

### 6.1 四层拓扑

1. **Room 层**：承载用户、平台 Agent 和协作消息。
2. **Case 层**：承载一个分析任务的目标、计划、状态和证据。
3. **Bridge/Gateway 层**：连接 Matrix/房间、平台 API、Agent 服务和通知。
4. **Evidence/Decision 层**：保存过程记录、血缘、判决、自省、报告和可见性裁剪。

### 6.2 房间意图状态

房间输入应归入有限状态：

- 直接回复；
- 创建/继续 Case；
- Manager 会诊；
- 需要用户澄清或人工介入。

### 6.3 协作不变量

- 成员身份由平台代持，外部 Matrix 身份不能绕过平台授权。
- 房间成员、Case 成员、报告可见性和数据文件权限必须分开校验。
- 每个 Turn 有稳定 ID、输入、输出、工具调用、状态、时间和关联 Case。
- 失败、拒绝、暂停、重试和人工决策都必须形成可追溯事件。
- 房间归档、Matrix 清理、报告保留和敏感内容可见性要有明确策略。

---

## 7. OmicStudio 与沙箱

### 7.1 当前沙箱形态

CygnusX 同时保留两套沙箱：

- **Legacy `/api/v1/sandbox`**：数据库会话 + Docker warm pool，支持 Python、R、Bash，提供 REST 收集式执行和 WebSocket 流式执行。
- **Studio sandbox**：每会话一个 Docker 容器，工作区挂载到 `/workspace`，sandbox-agent 通过 Unix Socket 提供执行和文件 API。

Studio 普通镜像用于数据分析；具备浏览器/文档能力的镜像必须独立，不能让所有会话承担 Chromium、LibreOffice 和更大的攻击面。

### 7.2 Studio 工作区契约

```text
/workspace
├── input/       # 平台输入文件的用户级只读软链
├── ref/         # 参考数据或引用
├── scripts/     # 用户/Agent 脚本
├── output/      # 结果、图表、日志、临时产物
├── .logs/       # 执行输出溢出日志
└── mcp-builds/  # 实验 MCP 构建目录
```

平台数据只挂载当前用户目录到 `/data/platform`，禁止把整个 storage 根目录暴露给沙箱。读路径可经工作区软链访问用户级只读数据；写路径必须严格限制在工作区。

### 7.3 当前安全基线

Studio 容器创建参数包括：

- `nano_cpus`、`mem_limit`、`pids_limit`；
- `cap_drop=["ALL"]`；
- `security_opt=["no-new-privileges:true", "seccomp=default"]`；
- `user=10001:10001`；
- `read_only=true`；
- `/tmp` 受限 tmpfs；
- 默认 `network_mode=none`，白名单模式使用每会话 internal 网络和 egress proxy；
- 10 GiB 默认工作区配额兜底，sandbox-agent 周期统计并保护写操作。

容器复用前会检查安全基线；不合规旧容器会被重建。当前生产 Docker daemon 的 inspect 和 egress 真机验收仍需在具备 Docker 权限的环境执行。

### 7.4 Capability 路由

允许的运行能力为 `code`、`browser`、`document`：

- Agent 的 `features.studio.sandbox_capabilities` 是授权源；
- 会话 `sandbox_meta.sandbox_capabilities` 保存实际能力；
- `studio.images` 根据能力集合选择镜像；
- 未授权能力拒绝创建并写 `sandbox.capability_denied`；
- MCP/Skill 的 `sandbox_meta.capabilities` 与运行时沙箱能力严格分开。

### 7.5 审计事件

Studio 生命周期事件通过结构化日志写出：

- `sandbox.create`；
- `sandbox.rebuild`；
- `sandbox.capability_denied`；
- `sandbox.reuse`；
- `sandbox.reclaim`；
- `sandbox.quota_exceeded`。

审计失败不得阻断会话主流程。浏览器/文档工具上线前，工具级调用还必须补齐调用者、能力、参数摘要、策略结果、产物和资源峰值审计。

---

## 8. MCP 子系统

### 8.1 三层体系

1. **内置平台 MCP**：平台原生工具、preset、搜索、文件和流程查询。
2. **外部/自建 MCP**：按 Server、工具、绑定、权限和可用性注册。
3. **MCP Builder**：自然语言生成代码 → AST/静态安全检查 → 沙箱 STDIO 测试 → 审核 → 实验 MCP → 转正/过期。

### 8.2 MCP 安全边界

- Server 和工具必须经过启用、归属、绑定和可用性校验。
- 工具 schema 明确参数，调用结果保留成功/失败和 UI payload。
- Builder 生成代码不能直接进入生产工具池；必须经过静态检查、沙箱测试、人工审核和 TTL。
- MCP 运行时不应携带平台密钥进入不可信沙箱。
- 对路径、命令、网络、子进程、文件和依赖安装做显式 allow/deny。

### 8.3 管线 MCP

RNAFlow、ATACFlow 等流程通过受控 MCP/工具入口暴露查询、验证、运行和结果读取；流程本体由 Worker/Snakemake 执行，不由前端直接执行宿主命令。

---

## 9. 记忆与知识

### 9.1 记忆分层

- `agent_memories`：旧归档或兼容层；
- `memory_blocks`：用户/项目/Agent 的常驻结构化块；
- `memory_facts`：可检索事实和召回层；
- Studio 文件记忆：工作区中的规则、上下文、检查点和可复用文件；
- AgentTeams 记忆：协作室和 Case 的可见过程记录。

读取链路根据开关选择兼容旧路径，或将常驻块与事实召回合并；写入需要来源、归属、置信度、敏感级别和幂等规则。

### 9.2 安全与回滚

- 用户记忆不能跨用户召回；项目记忆不能脱离项目范围。
- 不可信上下文不能覆盖系统指令、工具权限和安全策略。
- Git 检查点不得包含 API key、密码或平台密钥。
- 记忆 v2 使用灰度开关、迁移脚本、双读/双写策略和可回滚边界。

### 9.3 知识库

知识库包括文档、分块、embedding/向量索引、编辑者、审核日志和问题反馈。导入、切块、索引和检索应异步执行，并保留文档版本、来源和项目归属。

---

## 10. 数据分析与 Worker 执行

### 10.1 Worker 边界

Worker 镜像只包含 OS、Python、Celery、Snakemake、Micromamba 和最小系统工具；RNAFlow/ATACFlow 代码、Conda 环境、参考基因组和索引通过运行时挂载或共享存储提供。

固定容器路径：

```text
/app
/opt/cygnusx/pipelines
/data/cygnusx
/data/cygnusx/.conda_envs
/data/cygnusx/.mamba
/data/cygnusx/reference
```

流程环境按照 env YAML 内容哈希缓存；Web 与 Worker 必须看到同一逻辑工作区。不要把宿主机 `/home/.../miniconda3` 等私有路径硬编码进流程。

### 10.2 长任务状态

```text
pending → queued → running → success
                  ├→ failed ──重试──→ pending / queued
                  └→ cancelled ──重新入队──→ pending
```

成功态为 `success`（非 `succeeded`）；无独立 `retrying` 状态，重试建模为 `failed → pending/queued` 的转移（`domain/task/value_objects.py` 的 `TaskStatus` 与 `VALID_TRANSITIONS`）。`succeeded` 仅存在于 MAS 子系统的另一套状态机。

任务状态、日志、输入、输出和错误必须可关联到用户、项目、流程、运行 ID 和工作区。长任务失败不能只靠 stdout 排查。

---

## 11. 前端架构

前端采用 Vue 3 + TypeScript + Pinia，主要界面包括：

- AI Chat：普通对话、工具调用、思考/正文、MCP 卡片和历史重建；
- Studio：聊天、代码编辑器、文件树、终端、计划时间线、产物和沙箱状态；
- AgentTeams：房间、成员、Case 步骤、通知、过程报告和判决；
- 管理台：Agent、MCP、终端、工具、用户、日志和配置管理；
- 生信工具箱：流程、浏览器式参数表单、运行状态和结果预览。

前端约束：

- 设计 token、组件状态、响应式断点和可访问性统一管理；
- SSE/WebSocket 事件先进入 store，再投影到组件；
- 不把后端内部字段直接当成稳定 UI 契约；
- Studio 的工具输出使用 `tool_call_id` 精确匹配，避免并发工具串卡；
- 普通 `/ai` 视觉链路不能被 Studio 专属展示逻辑污染。

---

## 12. 日志、审计与可观测性

### 12.1 日志分层

| 类型 | 位置/通道 | 主要内容 |
|---|---|---|
| 应用日志 | web/worker/beat 结构化日志 | 请求、异常、服务生命周期 |
| 任务日志 | Celery/Snakemake/流程日志 | 任务输出、阶段、失败和重试 |
| 访问日志 | Nginx/网关 | 请求时间、状态码、来源和响应大小 |
| 审计日志 | AgentTeams、MCP、Studio sandbox 事件 | 身份、策略、工具、审批、回收和拒绝 |
| 追踪指标 | OpenTelemetry/Prometheus 预留 | 延迟、调用次数、资源、错误率 |
| 前端事件 | SSE/WebSocket projection | tool_call、tool_result、tool_output、plan、done |

### 12.2 日志治理

- 日志目录和 Docker stdout 都要有容量上限、轮转和清理策略。
- 数据库任务日志与文件日志不能无限重复写入；保留一处权威正文和可索引摘要。
- 审计事件不能被普通业务日志覆盖或静默丢弃。
- 日志中禁止明文密钥、完整 token、跨租户路径和不必要的敏感数据。

---

## 13. 部署与运行时

### 13.1 主部署

主路径是 Docker Compose，包含 Web、Worker、Beat、PostgreSQL/pgvector、Redis、MinIO、Nginx 及按需的流程/工具服务。AgentTeams 另有 Matrix、Bridge、Gateway 和 Kubernetes/开发环境部署文件。

### 13.2 配置来源

- `.env`：数据库、Redis、JWT、模型 Provider、存储和部署环境；
- `data/ai/*.yaml`：Agent、工具、Studio、MCP、提示词和流程配置；
- 数据库：用户可编辑 Agent、模型、MCP、权限和运行状态；
- `ARCHITECTURE_DESIN/`：设计约束、实施计划、验收和交接文档。

配置热重载必须有默认值、非法回退、字段校验和变更影响说明。生产配置不能依赖开发机绝对路径。

### 13.3 发布与回滚

1. 先迁移数据库并验证回滚路径；
2. 构建 Web/Worker/沙箱镜像；
3. 灰度启动并验证健康检查、工具、任务和日志；
4. 逐步切流；
5. 出现错误时按 feature flag、镜像标签、数据库迁移和路由兼容策略回滚。

---

## 14. 安全与隔离模型

### 14.1 身份和租户

- JWT 是 API 入口的认证基础；资源访问必须再次校验用户/项目归属。
- `/data/platform` 只允许挂载当前用户目录；工作区与结果报告分开保留。
- AgentTeams 的房间成员、Case 成员、报告可见性和文件权限不能互相替代。

### 14.2 沙箱

Docker 是当前容器边界，不等价于 VM 级隔离。对于未认证任意代码、多租户不可信执行、高敏数据和浏览器下载场景，触发 gVisor/Kata/MicroVM 评估。

### 14.3 网络

- 默认沙箱无网络；
- 白名单模式使用 per-session internal network + egress proxy；
- 代理只允许配置域名、HTTP 80/HTTPS 443，并拒绝 IP 字面量、私网和回环地址；
- T5/T6/T7 绕过代理、DNS/DoH 和跨会话凭据隔离仍需要具备 Docker 权限的环境真机验证。

### 14.4 密钥

平台 API key、数据库密码、JWT secret、对象存储凭据和代理凭据不能进入不可信容器工作区、用户文件、模型上下文或普通日志。

---

## 15. 当前状态与待办

### 已具备的主干能力

- Vue/FastAPI/PostgreSQL/Redis/Celery 基础平台；
- Agent 装配、多执行闭环和统一流式事件；`AgentContextBuilder` 提供带指标的缓存装配，
  `request_preparation` 统一处理上下文、模型可用性和 DeepSeek token 预检，
  `ChatEventService` 在 SSE 出口校验生命周期事件；
- Chat Runtime 拆分基础：Session/Router/Event 服务与 Direct、Legacy、LangGraph、Studio、
  Overdrive Runtime 适配器已落地；Legacy/Studio/Overdrive 事件流与 Direct 输入错误契约有
  可复现 golden record 和双跑回归；Skill 生命周期事件、执行与落库也已从入口编排中拆出；
- Studio 工作台、会话沙箱、工作区、产物和计划；
- AgentTeams 房间、Case、成员、派单、记录和报告；
- MCP 注册/发现/调用及 MCP Builder 基础链路；
- 记忆、知识库和流程执行基础设施；
- 日志、审计、指标和回收机制的基础框架；
- Studio capability 路由、容器安全基线和配额兜底已进入代码。

### 需要继续验收/建设

- Docker 真机 inspect：seccomp、实际运行用户、存储驱动和旧容器存量；
- egress T1–T7 真机测试；
- XFS project quota 可用性与硬磁盘配额升级；
- browser/document 工具、前端面板和独立镜像的真实功能验收；
- gVisor/Kata/MicroVM 评估；
- AgentTeams 生产级故障恢复、扩缩容和跨服务一致性演练；
- Worker 真实流程 E2E、共享存储和失败恢复演练；
- 记忆 v2、知识索引和 MCP Builder 的生产灰度收口。
- Chat Runtime 的真实隔离请求 golden：继续补齐工具多轮、`ask_user`、错误与断流场景，并在
  运行时迁移后执行新旧双跑差异审阅；

---

## 16. 修改入口与文档索引

| 主题 | 首选详细文档 |
|---|---|
| 项目模块和接入规范 | `cygnusx_design.md` |
| Agent 现状与扩展 | `agent_execution_framework.md`、`agent_framework_baseline.md`（原 `agent_architecture_and_extension_guide.md` 已并入其中） |
| Agent 可观测性 | `agent_execution_framework.md` §6/§7.3（原 `agent_execution_loop_observability_2026-08.md` 已并入其中） |
| Chat Runtime 分层与事件契约 | `chat_execution_layers_2026-08.md` |
| AgentTeams | `deprecated/agentteams_room_architecture.md`、`deprecated/agentteams_department_collaboration.md` |
| Studio | `cygnusx_studio_handover_2026-07.md` |
| 沙箱安全与能力路由 | `cygnusx_sandbox_architecture_2026-08-22.md` |
| MCP | `mcp_architecture.md`（含 §5 MCP 构建师 agent-mcp-builder as-built 章节，原 `mcp_builder_agent.md` 已于 2026-09-18 并入） |
| 记忆 | `memory_architecture.md` |
| 知识库 | `knowledge_architecture.md` |
| 多智能体/A2A/共享工作区 | `mas_a2a_plan_2026-07.md` |
| Worker 镜像与动态环境 | `worker_images_plan.md` |
| 日志 | `log_architecture.md` |
| 前端规范 | `frontend.md` |
| 愿景 | `cygnusx_platform_vision_2026-08.md` |

目录内另有评审稿、提示词、修复记录和历史版本文档。它们用于追踪决策，不应直接覆盖本文列出的当前实现状态。

---

## 17. 来源文件清单

本总览提取自 `ARCHITECTURE_DESIN/` 当前文件，包括：

- `README.md`
- `log_architecture.md`
- `cygnusx_design.md`
- `cygnusx_studio_handover_2026-07.md`
- `cygnusx_sandbox_architecture_2026-08-22.md`
- `frontend.md`
- `mas_a2a_plan_2026-07.md`
- `agent_framework_baseline.md`
- `agent_architecture_review_2026-07.md`
- `agent_execution_framework.md`
- `deprecated/agentteams_overdrive.md`
- `deprecated/agentteams_department_collaboration.md`
- `deprecated/agentteams_room_architecture.md`（2026-09-18 起已并入并替代原 `agentteams_room_framework_research_2026-08.md`、`agentteams_room_plan.md`、`manager_role_bioinfo_department_manager_2026-08.md` 三份文档）
- `mcp_architecture.md`
- `memory_architecture.md`
- `knowledge_architecture.md`
- `worker_images_plan.md`
- `multi_agent_fanout_2026-07.md`
- `domain_prompt_sedimentation_2026-08.md`
- `mas_a2a_plan_2026-07.md`
- `cygnusx_platform_vision_2026-08.md`

本文刻意不复制每个领域文档的全部接口和任务清单；新增模块或修改执行链路时，应回到对应详细文档和代码进行核对。
