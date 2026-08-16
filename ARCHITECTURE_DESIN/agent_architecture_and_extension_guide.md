# OmicHub Agent 架构现状与扩展指南

> 依据仓库当前实现整理，更新于 2026-07-26。本文区分“已经运行的能力”“受开关控制的能力”和“尚未形成默认工作流的能力”，避免把设计目标误写为现状。

> 后续能力演进（长期记忆、Agent Handoff、MAS 产品化）的实施路线见
> [`docs/26.7.26/ai_agent/OmicHub平台Agent能力优化方案-记忆与多Agent协作.md`](../docs/26.7.26/ai_agent/OmicHub平台Agent能力优化方案-记忆与多Agent协作.md)。
> 该方案是未来目标，不应反向作为本文件“当前已实现”的证据。

## 0. 2026-07-26 实施状态

下列能力已经进入代码库，但其中需要运行开关、数据库迁移或部署侧条件的能力，不能仅凭
代码存在就视为生产环境已启用：

| 能力 | 代码状态 | 默认行为 / 启用条件 |
| --- | --- | --- |
| P1 长期记忆 | 已实现 | `agent_memories` 通过关键词召回；执行 `alembic upgrade head` 后可用。用户可查看、修改、归档自己的记忆。 |
| P2 Agent Handoff | 已实现 | 白名单 Agent 可经 `transfer_to_agent` 在同一会话转交；ReAct 与 LangGraph 都在收到控制工具结果后停止源 Agent，再以精简交接包启动目标 Agent。 |
| P3 MAS 计划与执行体验 | 已实现、默认灰度关闭 | 需 `MAS_ENABLED=true` 与 Celery/outbox 调度链；该开关会自动加载 `orchestrator`，普通聊天不会自动创建 MAS Run。 |
| P4 语义记忆与多专家会诊 | 已实现、默认关闭 | 向量以 JSONB 持久化并在候选集内语义重排，历史记忆可按需回填；删除会话后可异步提炼摘要；router 可并行征询 2–3 位专家后由主专家汇总。需要单独配置 Embedding 模型与功能开关。 |

P2 的审计数据写入 `chat_handoff_events`；前端通过 SSE `handoff` 事件在消息流显示转交卡片。
P3 为 DAG 节点增加了产物 Schema 边校验、失败节点手动重试和产物下载接口；除 RNA-seq 外还提供
受限 `scanpy-qc` 节点。单细胞模板仅能在 `analysis-scrna` 镜像已部署到 MAS Worker 后灰度开放。

## 1. 结论：当前是否真的使用了 Agent 架构？

**结论：是，OmicHub 已实现了可配置、可调用工具、可多轮行动的单 Agent 架构；但默认产品路径还不是完整的多专家自治协作系统。**

当前默认入口的核心形态是：

1. 用户选择某个 Agent，或先进入 `agent-router`；
2. 路由器使用一次模型调用，从候选专家中选择一个目标 Agent；
3. 目标 Agent 装配自己的提示词、模型、工具、MCP Server、Skill 和 Studio 能力；
4. 模型通过 ReAct 循环或 LangGraph 状态图，按需调用工具并读取结果；
5. 工具结果回灌模型，模型生成最终回答，消息、工具调用和会话状态被持久化。

因此它不是“只有 system prompt 的普通聊天机器人”：它具有明确身份、工具选择、工具执行、状态循环、上下文隔离、路由与审计等 Agent 特征。

但也不能把当前所有助手称作“默认运行的多 Agent 协作群体”：路由器是**单次分派**，随后只运行一个专家；多个专家并不会在同一用户问题中自动互相讨论、并行执行或相互复核。

| 层级 | 当前状态 | 说明 |
| --- | --- | --- |
| 单 Agent ReAct / Tool Agent | 已落地 | 模型可调用 MCP、内置工具、Skill、Studio 工具，并将结果回灌下一轮模型。 |
| LangGraph 状态图 | 部分启用 | `agent-general`、`agent-scrna` 配置 `features.engine: langgraph`，非 Studio 会话走图化 ReAct。 |
| 模型路由 | 已落地 | `agent-router` 用模型把请求转给一个目标专家，失败回退通用助手。 |
| 同会话 Agent Handoff | 已落地 | 由受白名单约束的 `transfer_to_agent` 控制工具触发；源 Agent 不携带完整历史，目标 Agent 仅收到经过大小与路径校验的交接包。 |
| 长期记忆 | 已落地（关键词召回） | L1 常驻注入、L2 按当前问题关键词召回；所有操作均按用户隔离且支持软删除。 |
| MCP / Skill 工具生态 | 已落地 | MCP Server、内置工具 schema、Skill 渐进披露、工具包白名单均已实现。 |
| Studio 代码执行 Agent | 已落地 | 启用 Studio 时，沙盒能力按会话和 runtime profile 装配。 |
| 受审计 MAS DAG | 已实现但默认关闭 | 有 Plan、审批、Run、Node、Artifact、A2A Event、Celery 调度、产物契约、进度/下载/重试界面；`MAS_ENABLED=false` 时不可用。 |
| 多专家自动协作 | 未作为默认入口落地 | 当前 router 后通常只执行一个 Agent；编排器也不在 `data/OmicHub.yaml` 的 enabled 列表内。 |

## 2. 当前目录与配置职责

AI 相关静态资产均位于 `data/ai/`：

```text
data/
├── OmicHub.yaml                    # enabled Agent 名称列表和站点配置
└── ai/
    ├── *.yaml                      # 内置 Agent 声明
    ├── prompts/
    │   ├── registry.yaml           # 通用 Prompt Registry
    │   ├── general.md ...          # 当前 Agent 的详细提示词
    │   ├── copilot/ studio/ ...    # 其他 AI 系统提示词
    │   └── legacy_agents/          # 迁移前副本，仅供对照，不参与当前注册表
    ├── tools/*.yaml                # Agent 工具包的声明式授权
    ├── mas/                        # MAS 能力与工具执行策略
    ├── providers.yaml              # Provider 配置
    ├── provider_templates.yaml     # Provider 模板
    ├── runtime_images.yaml         # Studio / Toolbox 镜像能力目录
    ├── studio.yaml                 # Studio 沙盒配置
    ├── skills/                     # 已安装 Skill 的可写目录
    └── skill_marketplace/          # 内置 Skill 市场
```

已启用的内置 Agent 来自 `data/OmicHub.yaml` 的 `agents.enabled`：

| YAML 名称 | Agent ID | 角色 | 主要运行形态 |
| --- | --- | --- | --- |
| `router.yaml` | `agent-router` | 统一入口和专家分派 | 路由后交给一个目标专家 |
| `general.yaml` | `agent-general` | 通用科研助手 | LangGraph ReAct |
| `rnaseq.yaml` | `agent-rnaseq` | RNA-seq 分析师 | 手写 ReAct 循环 |
| `scrna.yaml` | `agent-scrna` | 单细胞分析师 | LangGraph ReAct |
| `code.yaml` | `agent-code` | 代码与沙盒助手 | 手写 ReAct / Studio |
| `viz.yaml` | `agent-viz` | 可视化助手 | 手写 ReAct / Studio |
| `shania.yaml` | `shania` | 个性化科研助手 | 手写 ReAct / Studio |

`data/ai/orchestrator.yaml` 定义了 `agent-orchestrator`，默认不在 `agents.enabled` 中。设置
`MAS_ENABLED=true` 后，加载器会把它纳入内置 Agent 同步并为其注入计划预览工具；关闭开关时不会暴露该入口。

## 3. 请求运行链路

```text
前端 /api/v1/chat 或 Agent 会话
          │
          ▼
ChatService.stream_agent_chat()
          │
          ├── AgentService.assemble_context(agent_id)
          │     ├── AgentTemplate（数据库）
          │     ├── Model / Provider
          │     ├── MCP Server 与 Tool 白名单
          │     ├── 内置工具 schema
          │     ├── Skill L1 索引与 Skill 工具
          │     └── Studio runtime / capability state
          │
          ├── 如果是 agent-router：_route_to_agent()
          │     └── 一次 LLM 分类 → 目标专家上下文（失败回退通用助手）
          │
          ├── 时效 / 文献问题：强制预搜索并注入来源
          │
          └── 执行引擎
                ├── LangGraph：llm_call → tool_exec → llm_call ... → END
                └── Legacy ReAct：最多 8 轮 LLM ↔ tool 调用循环
                         │
                         ▼
             MCP / 内置 ToolBridge / Skill / Studio / web_search
                         │
                         ▼
                 tool_result 回灌模型 → SSE 事件与消息持久化
```

### 3.1 配置加载与数据库边界

`src/omichub/infrastructure/config/agent_loader.py` 从 `data/OmicHub.yaml` 找到启用项，再读取 `data/ai/<name>.yaml`。加载器会：

- 读取 `prompt_file`，并拒绝越出 Agent YAML 所在目录的路径；
- 将 `tool_packs` 展开成内置工具、平台 MCP、外部 MCP 和 Skill 的授权信息；
- 校验 Studio `runtime_profile` 和 `required_capabilities` 是否可由 `runtime_images.yaml` 满足。

`AgentService.ensure_builtin_agents()` 再把配置幂等写入 `agent_templates` 表。这里有一个非常重要的当前行为：

> **已有内置 Agent 的 YAML 只会同步 `features` 和 Studio 描述；不会自动覆盖管理员已保存的 `system_prompt`、模型、`mcp_ids` 或 `skill_ids`。**

因此 YAML 是“内置 Agent 的初始定义和能力声明”，数据库是实际聊天时读取的 Agent 模板。这个保护策略避免重启覆盖管理员配置，但也意味着仅编辑 Markdown 并不会自动替换已落库 Agent 的提示词。

### 3.2 路由器不是编排器

`agent-router` 使用模型返回一个 JSON 决策，例如：

```json
{"agent_id":"agent-scrna","reason":"用户需要单细胞质控与细胞注释"}
```

随后系统只运行 `agent-scrna`。它不会把问题广播给 RNA-seq、单细胞、代码、可视化多个专家，也不会汇总多份专家结论。这是高效且稳定的“路由 Agent”，不是 MAS 编排。

### 3.3 LangGraph 与手写 ReAct

两种执行器的工具语义一致：模型请求 function call，服务端检查工具来源并执行，结果作为 `role: tool` 消息回灌。

- **LangGraph**：`src/omichub/infrastructure/execution/langgraph_runtime.py` 中的状态图固定为 `llm_call → tool_exec → llm_call`，最大轮数由调用方传入（与手写循环对齐：默认 100 轮，前端确认续轮后 1000 轮），触顶时产出 `round_limit` 事件；适用于标记 `features.engine: langgraph` 的非 Studio Agent。
- **手写 ReAct**：`ChatService.stream_agent_chat()` 中保留的循环（默认 100 轮，确认续轮后 1000 轮）；Studio 会话和未设置 LangGraph 的 Agent 使用它。

这意味着当前 LangGraph 是对 ReAct 控制流的图化，不是一个“自动规划—多节点任务编排图”。

### 3.4 实时与文献检索

`ChatService._requires_fresh_web_search()` 会根据默认关键词及 Agent YAML 的 `features.web_search.triggers` 判断。实时、新闻、天气、论文、文献、研究进展、数据库更新等问题，即便用户未开启界面搜索开关也会先检索；检索失败时系统提示模型不能把记忆表述为已核验的最新事实。

## 4. 工具架构

一个 Agent 可见工具来自四个来源：

| 来源 | 注册位置 | 运行位置 | 授权方式 |
| --- | --- | --- | --- |
| 内置 ToolBridge 工具 | `tool_configs/tools_schema.yaml` | `ToolBridgeService` / 后端服务 / 异步任务 / Flow | `tool_packs.*.builtin_tools` |
| 平台 MCP 工具 | `src/omichub/infrastructure/mcp/presets.py` | OmicHub 内部 handler | `platform_tools` |
| 外部或自建 MCP | 管理端 MCP Server 数据库记录 | `MCPClient` | `mcp_ids` + 可选 `mcp_tools` 白名单 |
| Skill | `data/ai/skills/` / 数据库 | `use_skill`、`skill_resource` 等按需读取 | `skill_ids` |

`data/ai/tools/*.yaml` 只是授权和组合层，不会直接执行 Python 或 Bash；这是为了保证每个工具有输入 schema、用户隔离、审计、错误处理和必要的确认闸门。

## 5. MAS：已有什么，未有什么

启用 `MAS_ENABLED=true` 后，系统已有以下完整的“受控 DAG 运行”基础设施：

- 编排器可通过 `mas_plan_preview` 生成受限的计划草稿；
- `MASPlanValidator` 根据 `data/ai/mas/agent_capabilities.yaml` 校验节点 Agent 能力；
- Run、Node、Artifact、Approval、A2A Event 持久化；
- 用户确认后状态从 `awaiting_approval` 进入 `queued`；
- Celery 定时消费 A2A outbox / Redis Stream，调度满足依赖的节点；
- 已支持 fake、RNAFlow、火山图、quality-gate 等执行器的调度分支、重试和进度事件。

当前限制是：该能力默认关闭，且 `agent-orchestrator` 未列入默认 Agent；普通用户聊天不会自动提升为 MAS Run。若要把“复合分析自动拆解为多个可执行节点”作为主产品体验，还需在前端入口、计划确认 UI、Agent 选择策略和质量门规则上完成产品化。

## 6. 后续修改 Agent 提示词

### 6.1 推荐流程：修改后通过管理端保存到数据库

当前已落库 Agent 的运行时提示词以数据库字段 `agent_templates.system_prompt` 为准。推荐流程：

1. 编辑对应 Markdown，例如 `data/ai/prompts/rnaseq.md`；
2. 在后台“Agent 管理”打开 `agent-rnaseq`，把更新后的内容保存到 `system_prompt`；或者调用 `PUT /api/v1/admin/agents/agent-rnaseq`；
3. 发起一次真实或测试会话，确认输出和工具行为；
4. 保留 Markdown 作为版本化的源码，管理端数据库作为运行时发布版本。

请求体示例：

```json
{
  "system_prompt": "粘贴 data/ai/prompts/rnaseq.md 的完整内容"
}
```

该 API 是部分更新；不带 `model_id`、`mcp_ids`、`skill_ids` 时不会清空已有绑定。保存后无需重启服务。

### 6.2 新建内置 Agent

1. 在 `data/ai/prompts/` 新建提示词，例如 `atac.md`；
2. 新建 `data/ai/atac.yaml`，设置唯一 `agent_id`、`prompt_file`、模型、`features`、`tool_packs` 和可选 Studio 配置；
3. 在 `data/OmicHub.yaml` 的 `agents.enabled` 加入 `atac`；
4. 重启应用或触发内置 Agent 初始化，让 `ensure_builtin_agents()` 创建数据库记录；
5. 在 Agent 列表、路由和工具调用场景验证。

最小示例：

```yaml
agent_id: agent-atac
name: ATAC-seq 分析师
description: 染色质可及性分析、峰注释和差异可及性解释。
model: qwen3.7-max
prompt_file: prompts/atac.md
temperature: 0.3
max_tokens: 4096
features:
  web_search:
    mode: required_for_freshness
    triggers: [最新, 文献, 论文, 指南, 数据库更新]
tool_packs: [workspace, research]
studio:
  enabled: true
  runtime_profile: analysis-core
  required_capabilities: [python, r, bash]
```

### 6.3 建议的后续改进：显式“从 YAML 发布”动作

当前没有“把 `prompt_file` 自动覆盖发布到数据库”的管理动作。建议后续新增一个管理员专用发布接口或 CLI，例如：

```text
omichub agents publish-yaml agent-rnaseq --fields system_prompt,features
```

它应展示 diff，并要求确认后才覆盖选定字段。不要把每次启动都改成强制覆盖，否则管理员在 UI 中的紧急修订会被 YAML 静默覆盖。

## 7. 后续添加工具

### 7.1 仅给现有工具授权：只改工具包 YAML

如果工具已经注册，只需编辑或新建 `data/ai/tools/<pack>.yaml`，再在 Agent YAML 引用它：

```yaml
# data/ai/tools/atac.yaml
id: atac
description: ATAC-seq 分析所需工具。
builtin_tools:
  - omichub_run_kegg_enrichment
platform_tools:
  - list_workspace_files
  - search_workspace_files
```

```yaml
# data/ai/atac.yaml
tool_packs: [workspace, atac]
```

对**新创建**的内置 Agent，工具包会生成初始工具绑定。对**已落库** Agent，`features.tool_packs` 会同步用于工具白名单，但新外部 MCP 或 Skill 的 ID 不会自动覆盖数据库绑定；请在后台 Agent 管理中保存对应 `mcp_ids` / `skill_ids`，或使用未来的“从 YAML 发布”动作。

### 7.2 新增内置后端工具

适用于已有 OmicHub 后端服务、分析 Flow 或可审计异步任务：

1. 在 `tool_configs/tools_schema.yaml` 定义工具名、描述、JSON Schema、`invocation_mode`、权限/确认要求及执行信息；
2. 在 `ToolBridgeService` 对应的服务、shim、异步任务或 `analysis_flow` 中实现执行逻辑；
3. 添加输入校验、当前用户隔离、审计、错误返回和单元测试；
4. 在工具包 YAML 的 `builtin_tools` 引用工具名；
5. 在目标 Agent 的详细提示词中说明何时调用、何时不能调用、如何解释结果；
6. 用真实会话覆盖“模型选择工具 → 服务执行 → 结果回灌”的闭环。

### 7.3 新增外部 / 自建 MCP 工具

适用于独立服务、第三方数据库或不应直接放入主应用的能力：

1. 实现符合 MCP 协议的服务，并把工具输入/输出 schema 设计为稳定、最小权限的接口；
2. 通过管理端 MCP Server API 注册服务，完成连接、健康状态和工具发现验证；
3. 在 `data/ai/tools/<pack>.yaml` 写入 Server UUID，并用 `mcp_tools` 限定允许的工具名；
4. 给目标 Agent 绑定该工具包；已落库 Agent 同时在后台保存对应 `mcp_ids`；
5. 明确超时、重试、数据外发范围、用户授权与审计要求。

示例：

```yaml
id: literature
description: 仅允许文献检索 MCP 的两个只读工具。
mcp_ids:
  - "<literature-mcp-server-uuid>"
mcp_tools:
  "<literature-mcp-server-uuid>":
    - search_literature
    - get_paper_metadata
```

### 7.4 不要采用的方式

- 不要在 Prompt 中要求模型“执行某个 Python/Bash 文件”并假设它会真的执行；
- 不要把用户输入直接拼入 shell 命令；
- 不要通过 YAML 提供任意脚本路径并在服务器端 `subprocess` 执行；
- 不要把高权限工具默认发给所有 Agent；应使用工具包白名单和最小权限。

## 8. 发布前检查清单

### 修改提示词

- [ ] 结论、工具边界、实时检索与引用要求没有互相矛盾；
- [ ] 已通过管理端/API 将运行时提示词发布到对应 Agent；
- [ ] 常规问题、工具问题、实时/文献问题各测试至少一次；
- [ ] 没有声明模型实际上不可见或不可执行的工具。

### 新增工具

- [ ] 工具有稳定名称、清晰描述和严格 JSON Schema；
- [ ] 执行逻辑校验当前用户、输入路径和资源权限；
- [ ] 已处理超时、失败、敏感信息和审计；
- [ ] 工具仅被最需要的 Agent 工具包授权；
- [ ] 已测试工具调用、结果回灌和模型最终解释；
- [ ] 若工具是外部 MCP，已验证服务可用、工具白名单和数据外发边界。

## 9. 关键实现位置

| 目的 | 文件 |
| --- | --- |
| 内置 Agent YAML 加载、提示词文件与工具包展开 | `src/omichub/infrastructure/config/agent_loader.py` |
| Agent 数据库同步与运行时上下文装配 | `src/omichub/application/services/agent_service.py` |
| 路由、搜索、工具循环、SSE 和 Studio 分流 | `src/omichub/application/services/chat_service.py` |
| LangGraph ReAct 状态图 | `src/omichub/infrastructure/execution/langgraph_runtime.py` |
| LangGraph LLM/工具节点 | `src/omichub/infrastructure/execution/langgraph_nodes.py` |
| 内置工具 schema | `tool_configs/tools_schema.yaml` |
| 内置平台 MCP handler | `src/omichub/infrastructure/mcp/presets.py` |
| 工具 schema 分发执行 | `src/omichub/application/services/tool_bridge_service.py` |
| MAS Run / 审批 / Artifact API | `src/omichub/application/services/mas_service.py` |
| MAS DAG 调度 | `src/omichub/application/services/mas_scheduler_service.py` |
| Agent 工具包说明 | `data/ai/tools/README.md` |

## 10. 与优化方案的实现边界

当前架构为长期记忆和多 Agent 协作预留了可复用的工具、审计、会话、事件和 MAS 调度基础，
但以下能力尚未在默认聊天链路中实现：

| 优化项 | 当前缺口 | 实施时必须遵守的架构约束 |
| --- | --- | --- |
| 长期记忆 | 没有跨会话 Memory 表、召回服务或记忆工具 | 当前 `assemble_context(agent_id)` 不接收 `user_id`/query；应由 ChatService 的会话级装配层传入用户隔离和当前消息。 |
| Agent Handoff | 没有 `transfer_to_agent` 工具、handoff SSE 事件或 hop 状态 | 手写 ReAct 和 LangGraph 两条执行器都必须识别同一控制流信号；不能只把它当作普通 ToolBridge 结果回灌。 |
| MAS 产品化 | Run/调度已有，但默认关闭且没有普通聊天入口和确认 UI | 必须同时验证 `MAS_ENABLED`、orchestrator 启用、Celery outbox 消费与目标执行器部署；仅有 API 或 Plan 预览不足以构成可用产品。 |
| YAML 发布 | 已落库 Agent 不自动覆盖提示词/模型/绑定 | 需通过后台 API 发布，或新增带 diff/确认的 YAML 发布命令；禁止启动时无条件覆盖数据库。 |

这四项也是优化方案实施前的架构检查点。
