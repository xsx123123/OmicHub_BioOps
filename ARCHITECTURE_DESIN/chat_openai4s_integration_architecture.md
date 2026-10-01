# Chat 与 OpenAI4S 融合架构调查

> 基线日期：2026-09-26。本文是基于当前 OmicHub 工作树的调查结果，记录 OpenAI4S 契约在平台中的衔接方式、对话执行链路，以及 MCP、Skill、沙箱和分析任务的调用边界。
>
> 本文不表示 OmicHub 直接依赖或复制 OpenAI4S。OpenAI4S 是长对话、动作路由、宿主回调、任务状态和产物校验语义的参照实现；当前能力以 OmicHub 代码和各专项 as-built 文档为准。

## 1. 一页结论

OmicHub 当前由以下层次组成：

```text
Vue 3 / Pinia / Studio / AgentTeams 前端
        |
        | REST / SSE / WebSocket
        v
FastAPI API 层（JWT、DTO、权限、事件出口）
        |
        v
ChatService / AgentService / Runtime Gateway
        |
        +--> OpenAI-compatible Provider
        +--> LangGraph Agent Runtime
        +--> MCP / Skill / Sandbox / Sub-Agent
        +--> AgentTeams / Case / Workflow
        |
        v
PostgreSQL + pgvector / Redis + Celery / Docker / Snakemake / MinIO
```

平台有四条主要执行形态：

1. **普通 Chat/Agent**：对话、工具调用、知识检索和 Skill/MCP 组合。
2. **OmicStudio**：带工作区、代码执行、文件操作和产物管理的交互式分析。
3. **AgentTeams**：Manager、领域 Agent、Worker、质量审计和交付报告的协作链。
4. **Pipeline/Worker**：Celery、Snakemake、RNAFlow、ATACFlow 等确定性计算任务。

OpenAI4S 的主要融合点是上下文压缩和运行时契约，而不是模型 SDK 替换。OmicHub 保留自己的数据库、LangGraph、Docker 和 MCP/Skill 子系统。

## 2. 参考文档与代码入口

### 2.1 架构文档

- `ARCHITECTURE_DESIN/cygnusx_architecture.md`：平台总体架构。
- `ARCHITECTURE_DESIN/agent_architecture.md`：单 Agent 的数据模型、接口和装配。
- `ARCHITECTURE_DESIN/agent_execution_framework.md`：Agent 执行路径、事件和运行保护。
- `ARCHITECTURE_DESIN/mcp_architecture.md`：MCP 注册、发现、安全和 Builder。
- `ARCHITECTURE_DESIN/skill_architecture.md`：平台 Skill 生命周期和调用契约。
- `ARCHITECTURE_DESIN/cygnusx_sandbox_architecture_2026-08-22.md`：Studio 沙箱和 capability 安全基线。
- `docs/info/26.9.25/openai4s-long-conversation-architecture.md`：OpenAI4S 长对话参照。
- `docs/info/26.9.23/migration-spec-openai4s-to-omichub.md`：上下文压缩迁移规格和验收状态。

### 2.2 对话代码入口

- 前端：`frontend/src/stores/agentHub.ts`
- 前端 SSE：`frontend/src/composables/useAgentChatStream.ts`
- API：`src/cygnusx/api/v1/chat.py`
- Agent 装配：`src/cygnusx/application/services/agent_service.py`
- 对话编排：`src/cygnusx/application/services/chat_service.py`
- Runtime 路由：`src/cygnusx/application/services/chat/chat_router_service.py`
- LangGraph：`src/cygnusx/application/services/chat/runtimes/langgraph_runtime.py`
- 上下文估算：`src/cygnusx/application/services/chat/context_estimate.py`
- 上下文压缩：`src/cygnusx/application/services/chat/context_compaction.py`
- 压缩编排：`src/cygnusx/application/services/chat/runtime_support.py`

## 3. 普通对话完整链路

### 3.1 前端请求构造

前端 `agentHub.sendMessage()` 先更新本地会话，再创建一个 assistant 占位消息，随后调用 `useAgentChatStream.streamChat()`。

请求包含：

- `agent_id`、`model_id`、`session_id`；
- 最近一段对话历史；
- 页面上下文和项目 ID；
- 文件附件；
- 深度思考、联网搜索和代码执行开关；
- `mcp_mode`、额外 MCP Server；
- `multi_agent`、`overdrive`、`runtime_profile`；
- `auto_approve` 和续轮参数。

前端默认只发送最近约 20 条消息。服务端的上下文压缩是第二层保护，不改变数据库中的完整原文。

请求统一进入：

```text
POST /api/v1/chat/stream
```

### 3.2 API 分流

`chat.py` 的 SSE 入口根据参数分流：

```text
agent_id 存在
  -> ChatService.stream_agent_chat()
  -> Agent 装配 + 工具闭环

只有 model_id
  -> ChatService.stream_chat()
  -> 直接模型聊天
```

输出是 SSE `data:` 帧。常见事件包括：

```text
text / tool_call / tool_output / tool_result / skill
approval_request / plan / ask_request
context_compressed / round_limit / done / error
```

API 层负责心跳、异常转化、终态判定和提交数据库事务，不负责复杂的 Agent 编排。

### 3.3 Agent Context 装配

`AgentService.assemble_context()` 根据 Agent 模板、用户能力和会话参数组装：

- 当前 Agent 和绑定模型；
- Agent system prompt 和通信约束；
- MCP Server 及工具 schema；
- 内置 `cygnusx-tools` 工具；
- Skill L1 索引和按需工具；
- Studio capability catalog；
- 工具包白名单和工具检索结果；
- AgentTeams、Workspace、Handoff 等提示词后缀。

返回的 `AgentContext` 是本轮模型调用的完整装配结果：

```text
AgentContext
  ├── agent
  ├── model_config
  ├── system_prompt
  ├── tools
  ├── mcp_servers
  ├── skills
  └── features
```

### 3.4 Runtime 路由

普通聊天当前默认进入 LangGraph Runtime：

```text
ChatService
  -> AgentRuntimeGateway
  -> ChatRouterService
  -> LangGraphChatRuntime
  -> llm_call / tool_exec / route 节点
```

保留的回退路径：

- Agent 配置 `engine: legacy`；
- 全局 `chat_force_legacy_runtime`；
- 特殊 Studio、MAS、Worker 运行路径。

Legacy 和 LangGraph 共用工具契约、事件字段、上下文压缩和审批语义。LangGraph checkpoint 只作为图恢复载体，不是数据库事实源。

## 4. OpenAI-compatible Provider

### 4.1 Provider 边界

`OpenAICompatibleProvider` 使用 HTTPX 直接对接 OpenAI Chat Completions 风格的 SSE 接口。支持 OpenAI、Kimi、DeepSeek、Qwen、智谱、火山方舟以及其他兼容端点。

模型请求包括：

- messages；
- system prompt；
- temperature；
- max tokens；
- OpenAI function tools；
- deep thinking 扩展参数。

Provider 将不同供应商的 usage 统一为标准字段，供 token 计费和上下文估算使用。

### 4.2 流式与重试

Provider 会累积 OpenAI 分片式 tool call，流结束后形成完整调用。重试条件包括：

- 尚未向用户输出正文；
- 尚未产生有效工具调用；
- 网络超时或连接失败；
- 429 限流；
- 空响应。

一旦已经输出正文或工具调用，错误直接向上抛出，避免重试造成重复回答。

## 5. OpenAI4S 融合的上下文机制

### 5.1 融合原则

OpenAI4S 的核心机制是“上下文投影 + 摘要交接 + 归档”，OmicHub 采用同类语义，但保留自身数据边界：

```text
完整 chat_messages（数据库原文）
  -> 每次模型调用前构造上下文视图
  -> 必要时压缩/外置
  -> 只把压缩视图发送给模型
  -> 数据库仍保留完整原文
```

### 5.2 Token 估算与触发

当前压缩策略会分别估算：

- 文本；
- 图片；
- tool schema；
- tool call；
- tool result；
- artifact reference；
- wire state；
- system prompt。

上一轮 Provider 返回的真实 `prompt_tokens` 会用于校准 session/model 级 ratio，ratio 限制在 0.5 到 8 之间。

默认触发逻辑为：

```text
estimated_total * calibration_ratio
  > model_context_window * trigger_ratio
```

同时需要满足最小消息数量，避免短对话被过早压缩。

### 5.3 滚动摘要和 handoff

压缩时保留：

- 最初的 head 消息；
- 最近的 tail 消息；
- 中间消息的滚动摘要。

摘要必须保留以下结构化字段：

```text
Objective
Constraints
Decisions
Done
In Progress
Blocked
Next Move
Key Artifacts
Active Kernel Generation
```

其中 `Active Kernel Generation` 在 OmicHub 中由宿主提供的沙箱/工作区状态替代，模型不能自行编造。

### 5.4 大输出外置

超过阈值的工具结果会被写入内容寻址归档：

```text
storage/context-archive/<session>/context-blobs/
```

上下文只保留 preview 和读回提示。归档使用 SHA-256、原子写入和路径/符号链接校验。Studio 会话还可以同步到：

```text
/workspace/.context-archive/
```

真实用户输入、普通 assistant 回复和原生 tool call 不应被误判为可外置内容。

### 5.5 双熔断和失败语义

压缩策略跟踪两类问题：

- 连续摘要/归档失败；
- 连续压缩收益低于阈值。

熔断后不硬截断、不返回 500，而是保留原始上下文继续请求。上下文增长到约 1.5 倍后再尝试打开压缩。用户主动取消不计入失败次数。

### 5.6 与 OpenAI4S 的差异

| 维度 | OpenAI4S | OmicHub |
| --- | --- | --- |
| 原始消息 | 运行时 state 可原地写入投影 | `chat_messages` 始终保存完整原文 |
| 压缩恢复 | Action Ledger 恢复投影 | 由数据库原文重新构造 |
| 执行单元 | 原生 Code Cell + 持久 Kernel | 工具调用 + Docker 沙箱进程 |
| Kernel 状态 | Kernel generation | 沙箱/工作区状态 |
| 事件恢复 | Ledger 驱动 | 事件表 + 原文重放 |
| LangGraph checkpoint | 可用于运行状态 | 仅作图恢复载体 |

当前迁移规格中 P0 至 P5 的核心代码已实现；真实 Docker、Postgres、外部 Provider 和大输出容器读回仍属于部署环境验收项。

## 6. MCP 调用流程

### 6.1 MCP 三层

平台 MCP 分为：

1. **内置 preset**：`cygnusx-platform`、`cygnusx-pipelines`、`cygnusx-tools`。
2. **外部 MCP**：STDIO、SSE、Streamable HTTP。
3. **管线专属 MCP**：RNAFlow、ATACFlow 等流程能力。

### 6.2 注册和绑定

```text
应用启动
  -> MCPService.ensure_presets()
  -> 幂等写入 mcp_servers

管理员注册外部 MCP
  -> 验证 command/url/args
  -> 写入 mcp_servers

Agent YAML / 用户能力配置 mcp_ids
  -> AgentService.assemble_context()
  -> 加载启用且通过审核的 Server
  -> 应用工具白名单
  -> 转换为 OpenAI function schema
```

模型看到的是标准 function tool，不直接感知 MCP Session 细节。

### 6.3 调用和返回

```text
LLM tool_call
  -> 根据 tool_call_id 找到 MCP Server
  -> 检查绑定、启用状态、工具白名单和审批状态
  -> Builtin 直接调用 handler
  -> 外部 MCP 建立 session 后 call_tool()
  -> 形成 llm_payload + ui_payload
  -> tool_result SSE
  -> 回灌模型并继续循环
```

`llm_payload` 用于控制上下文大小；`ui_payload` 用于前端渲染表格、图表、确认卡和任务进度。

### 6.4 MCP 安全

外部 Server 注册和调用会校验：

- 禁止 shell 解释器；
- 禁止绝对路径和路径穿越；
- 禁止 shell 元字符；
- 禁止内网、回环和云元数据地址；
- 调用超时；
- Server enabled/status；
- Agent 挂载和工具白名单。

MCP Builder 生成的代码必须经过 AST 检查、沙箱 STDIO 测试、人工审核和 TTL 管理，不能直接进入生产工具池。

## 7. Skill 调用流程

### 7.1 两套 Skill 体系

仓库中的 `.agents/skills/` 是编码助手使用的 Skill；`data/ai/skills/` 和数据库中的 Skill 是 CygnusX 业务 Agent 使用的 Skill，两者不能混淆。

### 7.2 平台 Skill 生命周期

```text
市场 / GitHub / ZIP / Markdown / JSON
  -> 预览
  -> 用户确认
  -> 写入 data/ai/skills/<skill_id>
  -> upsert skills
  -> 创建 skill_versions 快照
  -> 绑定 Agent skill_ids
  -> 对话中按需调用
  -> 写入 skill_invocations
```

### 7.3 三层渐进式披露

```text
L1：name + description
  -> 常驻 system prompt

L2：SKILL.md 正文
  -> 模型调用 use_skill(skill_id)

L3：references/ 和 assets/
  -> 模型调用 skill_resource(skill_id, path)
```

Skill 正文读取优先级：

```text
会话 skill_pins 快照
  -> 磁盘 SKILL.md
  -> 数据库 prompt 兜底
```

未绑定 Skill 不会注入 `use_skill` 和 `skill_resource` 工具；Skill 会话版本固定，避免任务中途被升级或回滚影响。

### 7.4 Skill 事件

调用过程向前端发送：

```text
skill: invoked
skill: completed
skill: failed
```

管理端可查询 Skill 版本、来源、耗时、用户、会话和失败原因。

## 8. 沙箱调用流程

### 8.1 Chat 轻量沙箱

工具名为 `chat_sandbox_execute`，支持 Python、R、Bash，适用于快速验证、简单计算和图表生成。

```text
模型生成代码
  -> SandboxPool
  -> 注入 /workspace/input
  -> 执行代码
  -> 收集 stdout/stderr
  -> 收集 /tmp/chat_output 和 /workspace/output
  -> SHA-256 manifest 对账
  -> 注册 file_records
  -> 生成下载 URL
  -> tool_result.ui_payload
```

模型声明但未生成的文件进入 `missing_artifacts`，不会被视为成功交付。

### 8.2 Studio 沙箱

Studio 按会话创建独立 Docker 容器：

```text
Studio session
  -> runtime profile
  -> capability 路由
  -> 选择镜像
  -> StudioSandboxManager.ensure_running()
  -> /workspace/.agent.sock
  -> sandbox-agent
  -> exec / workspace / artifact 工具
```

授权能力主要为：

```text
code / browser / document
```

Agent 的 `features.studio.sandbox_capabilities` 是授权源，会话 `sandbox_meta` 保存实际能力。

### 8.3 安全基线

Studio 容器具备：

- 固定非 root 用户；
- `cap_drop=ALL`；
- `no-new-privileges`；
- seccomp；
- 只读 rootfs；
- CPU、内存和 PID 限制；
- 默认 `network_mode=none`；
- 受限 `/tmp`；
- 工作区配额；
- 执行超时；
- 容器复用前重新 inspect。

白名单网络模式通过 internal Docker network 和 egress proxy 控制允许访问的域名。

### 8.4 工作区路径

```text
/workspace/input
/workspace/ref
/workspace/scripts
/workspace/output
/workspace/.logs
/workspace/.context-archive
```

工作区 API 会阻止路径穿越、符号链接逃逸和跨用户访问。平台不会把整个存储根目录挂载到容器。

## 9. AgentTeams 与正式分析任务

正式任务通常使用以下链路：

```text
用户需求
  -> Room 意图路由
  -> Manager
  -> Case / Plan
  -> 领域 Agent
  -> Worker / Workflow
  -> Quality Auditor
  -> Delivery Reporter
```

职责边界：

- Manager 负责接单、派单、验收、交付和异常处理；
- 领域 Agent 负责专业分析，不自行决定质量门；
- Worker 只执行授权的流程和工具；
- Quality Auditor 独立核验；
- Delivery Reporter 只交付通过质量门的产物。

RNAFlow、ATACFlow 和其他 Snakemake 流程由 Worker 执行。Agent 可以理解需求、组织参数、调用流程和解释结果，但不直接改写流程主体。

## 10. 状态、审计和交付物

平台坚持以下边界：

```text
模型输出不等于科学结论
工具成功不等于分析成功
进程 exit 0 不等于产物交付成功
checkpoint 不等于业务事实
压缩视图不等于原始消息
```

执行过程会关联：

- user、project、session、agent；
- model 和 execution path；
- tool_call_id、MCP Server、Skill revision；
- sandbox、worker、task；
- 输入、日志、产物、manifest；
- size、SHA-256、环境和软件版本；
- 审批、重试、失败和质量判定。

正式交付以 `Case / Artifact / Evidence / Manifest / Report` 组成证据链。

## 11. 当前实现状态与验收边界

### 已落地

- OpenAI-compatible Provider 和 SSE 流式调用；
- Agent 数据驱动装配；
- LangGraph 默认 Runtime 和 Legacy 逃生舱；
- MCP preset、外部 MCP 和管线 MCP；
- Skill 三层渐进式披露、版本快照和调用审计；
- Chat 轻量沙箱和 Studio 独立沙箱；
- capability 路由、容器安全基线和工作区路径保护；
- 产物 manifest、SHA-256 和缺失产物告警；
- OpenAI4S 风格上下文估算、压缩、外置、归档和双熔断；
- `context_compressed`、tool、skill、approval、plan 等前端事件投影；
- AgentTeams、Case、Worker 和报告交付框架。

### 仍需部署环境验证

- 真实 Docker daemon 下的容器安全 inspect；
- 真实 Postgres 下的迁移、权限和管理端热加载；
- 外部 Provider 的限流、故障和 usage 兼容性；
- 外部 MCP 的真实网络隔离；
- 超大上下文归档在容器中的读回；
- 生产 Worker、Snakemake、参考数据和对象存储挂载；
- 全量测试套件中依赖 Docker/Postgres 的测试。

## 12. 修改约束

修改这套系统时应遵守：

1. API 层只做协议、鉴权、DTO 和事件出口，复杂编排放到 application service。
2. Agent、MCP、Skill 和沙箱权限必须由配置和服务端校验决定，不能只靠 prompt。
3. 工具结果同时区分 `llm_payload` 和 `ui_payload`，避免模型上下文被前端展示数据撑大。
4. 数据库原文、任务状态、产物 manifest 和审计事件分别保留权威边界。
5. 压缩失败必须保留原上下文继续执行，不得因摘要失败直接 500。
6. 新增 MCP Builder 产物必须经过静态检查、沙箱测试和人工审核。
7. 新增 Skill 必须有版本、来源、绑定范围和调用审计。
8. 沙箱能力必须走 capability 路由，禁止根据用户文本直接授予高权限。
9. 标准生信流程由 Worker/Snakemake 执行，Agent 不直接修改流程本体。
