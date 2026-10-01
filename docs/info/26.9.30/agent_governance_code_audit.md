# Agent Prompt / MCP / Skill 治理与执行代码审计

审计日期：2026-09-30  
审计范围：`src/cygnusx/`、`data/ai/`、`mcp-server/`、相关测试与运行配置。  
判定口径：只有执行路径上的 Python/数据库/容器校验才计为“硬实现”；Markdown、Prompt 或注释中的要求只计为软约束。

## 1. 实现成熟度总览

| 技术点 | 判定 | 结论 |
|---|---|---|
| 声明式 Prompt 与 Agent 装配 | **部分实现（半工程半 Prompt）** | YAML 是 Agent、MCP、Skill、Studio profile 的装配源；`agent_loader` 做路径、运行时镜像和包目录注入，但系统提示词主体仍是 Markdown，自由文本没有统一的 JSON Schema/Pydantic 输出校验。 |
| Agent 工具/权限护栏 | **已完整硬编码实现（边界内）** | 工具列表来自绑定关系并在运行时裁剪；MCP 传输校验、文件引用权限、工具参数 schema、沙箱容器基线和 Studio capability 是代码边界。模型仍可生成普通文本，不能据此宣称所有业务语义都被 schema 化。 |
| MCP 接入与能力发现 | **已完整硬编码实现** | `MCPClient` 对 builtin/stdio/SSE/streamable HTTP 做发现、调用、超时、重试、熔断、fallback 和审计；外部上下文不会直接传入。 |
| Skill 元数据与生命周期 | **部分实现（半工程半 Prompt）** | `SKILL.md` 有 frontmatter、大小/路径/危险脚本扫描、磁盘真相源、DB 三表、L1/L2/L3 渐进披露和调用审计。 |
| Skill 三层生信契约 | **仅部分硬实现，其余为 Prompt 文本约定** | MAS Flow 的 executor/artifact contract 与 QC gate 有服务器校验；普通 Skill 的 integer counts、重复数 `N>=3`、效应量/P-adj/QC 图表等没有通用执行前断言。 |
| 幂等提交 | **已完整硬编码实现（分路径）** | Task DB unique idempotency key + service 重放；MAS 节点和 AgentTeams 事件也有 key/dedupe。需注意部分确认存储在 Redis 不可用时回退进程内存。 |
| 审批令牌 / HITL | **已完整硬编码实现** | 人类 JWT 端点是批准写入点；参数 hash、归属、TTL、一次性状态迁移、重复消费拦截均有代码。AgentTeams Bridge 另有 approval token。 |
| QC / 质量门 | **已完整硬编码实现（覆盖已登记路径）** | `AgentTeamsQualityGateService`、`domain.mas.quality_gate` 和 `MASPlanValidator` 对 QC、产物打开性及绕过质量门的 DAG 依赖做确定性判定；未登记的新 Skill 不会自动获得相同校验。 |

## 2. 维度一：Prompt 治理与执行护栏

### 2.1 装配入口

核心入口是 `load_agent_configs()`：

- [`src/cygnusx/infrastructure/config/agent_loader.py:29`](../../../src/cygnusx/infrastructure/config/agent_loader.py) 从 `data/CygnusX.yaml` 的 `agents.enabled` 读取 Agent，再加载 `data/ai/<agent>.yaml`。
- [`agent_loader.py:97-116`](../../../src/cygnusx/infrastructure/config/agent_loader.py) 读取 `prompt_file`/`prompt_ref`，并统一追加 `prompts/shared/sandbox_protocol.md` 与 `communication_style.md`。
- [`agent_loader.py:140-167`](../../../src/cygnusx/infrastructure/config/agent_loader.py) 校验 Studio runtime profile 和 required capabilities；不匹配的 runtime 会拒绝加载。
- [`agent_loader.py:172-189`](../../../src/cygnusx/infrastructure/config/agent_loader.py) 只替换 `{{runtime_images}}`、`{{bio_packages}}` 两个受控占位符。
- [`agent_loader.py:241-250`](../../../src/cygnusx/infrastructure/config/agent_loader.py) 对 `prompt_file` 做根目录边界校验，不能通过 YAML 把提示词路径越界到任意文件。

`AgentService.ensure_builtin_agents()` 将 YAML 声明同步到 `agent_templates`，并重建 `mcp_ids`/`skill_ids`，清除历史绑定漂移：
[`src/cygnusx/application/services/agent_service.py:225-291`](../../../src/cygnusx/application/services/agent_service.py)。

这证明“声明式装配”是真实存在的，但没有证明 Prompt 本身是结构化程序。系统提示词仍由 Markdown 文本组成，`features`/`tool_packs` 是结构化的，领域 SOP、统计规则和交付要求多数仍在 Prompt/Skill 正文里。

### 2.2 LLM 输出约束

- LangGraph 节点把已经裁剪好的 OpenAI tools 传给 Provider：[`src/cygnusx/infrastructure/execution/langgraph_nodes.py:139-160`](../../../src/cygnusx/infrastructure/execution/langgraph_nodes.py)。达到轮次上限后会物理移除 tools，强制最终答复。
- Provider 明确支持 OpenAI Function Calling 的 `tools` 列表，并累积 `tool_calls`：[`src/cygnusx/infrastructure/ai_provider/openai_compatible.py:282-301`](../../../src/cygnusx/infrastructure/ai_provider/openai_compatible.py)。
- Tool schema 由领域服务生成。例如 Skill 工具的 `skill_id` 使用 enum 白名单：[`src/cygnusx/domain/skill/services.py:11-60`](../../../src/cygnusx/domain/skill/services.py)。
- 未发现统一的 `response_format=json_schema`、所有 Agent 输出对应的 Pydantic discriminator，或对普通最终文本做通用 JSON Schema 验证。故“工具调用契约”是硬的，“最终回答契约”不是全局硬的。

### 2.3 物理护栏

- MCP builtin handler 只从注册 preset 取函数，未知工具直接失败：[`src/cygnusx/infrastructure/mcp/client.py:463-489`](../../../src/cygnusx/infrastructure/mcp/client.py)。
- 非 builtin transport 不传递数据库/请求上下文：[`client.py:491-513`](../../../src/cygnusx/infrastructure/mcp/client.py)。
- 工作区文件引用先经 `resolve_workspace_file_refs()`，因此 Agent 不能用普通参数绕过用户文件授权。
- 外部 stdio 命令拒绝绝对路径、路径穿越、shell 解释器、shell 元字符并要求命令存在于 PATH：[`client.py:99-127`](../../../src/cygnusx/infrastructure/mcp/client.py)。SSE/HTTP URL 拒绝内网、回环和 metadata 地址：[`client.py:85-96`](../../../src/cygnusx/infrastructure/mcp/client.py)。
- 通用沙箱通过 Docker 运行，设置 `cap_drop=["ALL"]`、非 root 用户、只读 rootfs、pids/memory 限制、no-new-privileges、网络隔离和受控 bind mount：[`src/cygnusx/infrastructure/sandbox/pool.py:258-337`](../../../src/cygnusx/infrastructure/sandbox/pool.py)。存量容器不符合基线会被销毁重建：[`pool.py:347-373`](../../../src/cygnusx/infrastructure/sandbox/pool.py)。

这些是物理边界，已经超过“只在 Prompt 中说不要执行 shell”。但边界保护的是工具和容器，不是对所有领域推理结果的正确性保证。

## 3. 维度二：MCP 与 Skill

### 3.1 MCP 能力发现与调用

`MCPClient.list_tools()` 对 builtin preset 直接返回工具 schema，对外部服务调用 MCP SDK `session.list_tools()`：
[`src/cygnusx/infrastructure/mcp/client.py:234-258`](../../../src/cygnusx/infrastructure/mcp/client.py)、[`client.py:615-639`](../../../src/cygnusx/infrastructure/mcp/client.py)。

`call_tool()` 经过超时、Trace/Log/Metrics、重试和健康熔断；外部调用失败可切 builtin 或本地 fallback：
[`client.py:267-325`](../../../src/cygnusx/infrastructure/mcp/client.py)、[`client.py:327-443`](../../../src/cygnusx/infrastructure/mcp/client.py)。健康注册表使用连续失败阈值和 half-open 探测：[`src/cygnusx/infrastructure/mcp/reliability.py:93-152`](../../../src/cygnusx/infrastructure/mcp/reliability.py)。

因此 MCP 不是接口占位：发现、调用、连接复用、隔离和故障处理均在执行代码中。能力目录的实际来源是 preset/DB server/tool 表和 Agent YAML 绑定；未发现一个通用、独立命名为 `ability_catalog_query` 的单一目录 API，目录能力分散在 MCP 管理端点与运行时发现路径。

### 3.2 Skill 三层存储与运行

- [`src/cygnusx/infrastructure/skills/skillmd.py:1-9`](../../../src/cygnusx/infrastructure/skills/skillmd.py) 定义 L1 frontmatter、L2 正文、L3 scripts/references/assets。
- `parse_skill_folder()` 强制 UTF-8、唯一 `SKILL.md`、frontmatter 的 `name`/`description`、单文件 512 KiB、总目录 1 MiB、相对路径和危险脚本扫描：[`skillmd.py:174-277`](../../../src/cygnusx/infrastructure/skills/skillmd.py)。危险模式目前是 warning，不是拒绝导入（见 `skillmd.py:29-39`）。
- 磁盘是内容真相源，DB 保存索引/正文缓存；`read_skill_resource()` 仅允许 `references/` 和 `assets/`，禁止脚本直接读回上下文，并限制单文件 200 KiB：[`src/cygnusx/infrastructure/skills/skill_store.py:1-6`](../../../src/cygnusx/infrastructure/skills/skill_store.py)、[`skill_store.py:92-123`](../../../src/cygnusx/infrastructure/skills/skill_store.py)。
- DB 物理模型包含 `skills`、`skill_versions`、`skill_invocations` 三表：[`src/cygnusx/infrastructure/database/models/skill.py:18-120`](../../../src/cygnusx/infrastructure/database/models/skill.py)。
- 运行时只允许绑定 Skill 的 `use_skill`/`skill_resource` 工具，并记录调用生命周期：[`src/cygnusx/application/services/chat/skill_execution.py:21-114`](../../../src/cygnusx/application/services/chat/skill_execution.py)。

仓库当前 `data/ai/skills` 有 12 个 `SKILL.md`，不是代码注释中泛称的“600+ 项”本身。即使外部市场/同步源提供更多 Skill，平台的通用执行器也不会自动替每个 Skill 解释其领域统计假设。

### 3.3 三层契约的真实边界

普通 Skill 的确会写“触发前提、输入契约、输出契约”，例如 `data/ai/skills/delivery-report/SKILL.md` 明确列出质量门状态、交付阈值、artifact 清单和校验步骤；但 `skillmd.py` 只解析并存储这些文本，未把它们编译为 precondition evaluator。

硬校验来自另一条 MAS/Flow 路径：

- `MASPlanValidator.validate()` 校验 Agent 能力、executor actor、输入/输出 artifact type 和上游产物边：[`src/cygnusx/application/services/mas_plan_validator.py:26-100`](../../../src/cygnusx/application/services/mas_plan_validator.py)。
- 对 `deg-volcano` 强制存在上游 `quality-gate`，禁止绕过 QC 阻断：[`mas_plan_validator.py:124-145`](../../../src/cygnusx/application/services/mas_plan_validator.py)。
- 这属于注册 Flow/executor 的契约，不是所有 `SKILL.md` 的通用语义编译器。

因此对审查清单中的三层 Skill 契约，应分别判定：

1. **前置条件**：文件结构、路径、大小、Skill 绑定是硬的；integer counts/FPKM/TPM 等生物信息学输入语义通常仍是正文。
2. **统计假设**：普通 Skill 未见通用的重复数 `N >= 3` 或设计降级断言；具体 Flow 可以在 YAML executor/QC 服务内实现规则。
3. **输出规范**：MAS artifact schema/依赖边是硬的；普通 Skill 正文中写的效应量、P-adj、QC 图表清单不会自动被统一校验。

## 4. 维度三：幂等、审批与质量门

### 4.1 幂等提交

- Task 领域接口声明 `get_by_idempotency_key()`，ORM 对 `tasks.idempotency_key` 建 unique index：[`src/cygnusx/domain/task/repositories.py:11-24`](../../../src/cygnusx/domain/task/repositories.py)、[`src/cygnusx/infrastructure/database/models/task.py:1-42`](../../../src/cygnusx/infrastructure/database/models/task.py)。
- `TaskService.submit()` 在构建 Flow 文件前查询已有 key；同用户直接返回已有任务，跨用户拒绝：[`src/cygnusx/application/services/task_service.py:53-69`](../../../src/cygnusx/application/services/task_service.py)。
- `TaskRepositoryImpl` 还按 key 前缀统计 attempt，处理终态重试：[`src/cygnusx/infrastructure/database/repositories/task_repository.py:28-42`](../../../src/cygnusx/infrastructure/database/repositories/task_repository.py)。
- Studio 任务、MAS node 和 AgentTeams 事件也生成稳定 key；例如 Studio 的派生与竞态处理位于 [`src/cygnusx/application/services/studio_task_service.py:51-178`](../../../src/cygnusx/application/services/studio_task_service.py)。

这是真正的数据库去重与重放，不只是请求头记录。需要保留的限制是：确认记录在 Redis 不可用时回退 `_MemoryStore`，仅适合单 worker/测试，见 [`src/cygnusx/application/services/tool_confirmation_service.py:135-185`](../../../src/cygnusx/application/services/tool_confirmation_service.py)。

### 4.2 Tool/Task 审批令牌

`ToolConfirmationService` 是完整的状态机：`PENDING -> APPROVED -> CONSUMED/SUBMITTED`，另有 `REJECTED/EXPIRED/INVALID`。

- Redis store 使用 TTL 和 Lua 原子迁移，多 worker 共享：[`tool_confirmation_service.py:187-214`](../../../src/cygnusx/application/services/tool_confirmation_service.py)。
- 创建确认时保存规范化参数的 SHA-256：[`tool_confirmation_service.py:259-316`](../../../src/cygnusx/application/services/tool_confirmation_service.py)。
- `approve_by_human()` 是 tool 记录进入 APPROVED 的唯一人类路径：[`tool_confirmation_service.py:320-340`](../../../src/cygnusx/application/services/tool_confirmation_service.py)。
- 模型通道不能自行把 PENDING 变成可执行；`approve()` 要求人类先批准、校验过期并以原子状态迁移防重复提交：[`tool_confirmation_service.py:344-403`](../../../src/cygnusx/application/services/tool_confirmation_service.py)。
- `consume_tool_confirmation()` 对工具名、参数 hash、归属、TTL 和一次性消费做硬校验；参数改变会使旧确认变 INVALID：[`tool_confirmation_service.py:425-474`](../../../src/cygnusx/application/services/tool_confirmation_service.py)。
- REST 人类入口在 [`src/cygnusx/api/v1/ai.py:173-254`](../../../src/cygnusx/api/v1/ai.py)。

这满足“模型不能自证确认”的物理要求。AgentTeams Bridge 的 approval authority/token 是另一条跨服务审批链，调用处集中在 [`src/cygnusx/application/services/agentteams_service.py:745-850`](../../../src/cygnusx/application/services/agentteams_service.py)。

### 4.3 QC 状态机与自动熔断

- RNA mapping rate 的 Pydantic 不可变结果和 `REVIEW_REQUIRED/WARNING/PASS/FAIL` 枚举在 [`src/cygnusx/domain/mas/quality_gate.py:10-90`](../../../src/cygnusx/domain/mas/quality_gate.py)。低于 blocking threshold 时禁止 downstream visualization；override 必须携带至少 10 字符理由。
- AgentTeams 质量门在 LLM review 前运行，按 flow YAML 阈值计算 mapping_rate、q30、duplicate_rate，并输出 `BLOCKED/WARNING/PASSED/MANUAL_REVIEW` 与审计事件：[`src/cygnusx/application/services/agentteams_quality_gate_service.py:1-75`](../../../src/cygnusx/application/services/agentteams_quality_gate_service.py)。
- 交付报告还有 citation completeness 和文件可打开性门控：[`agentteams_quality_gate_service.py:77-168`](../../../src/cygnusx/application/services/agentteams_quality_gate_service.py)。
- `MASPlanValidator` 阻断没有经过 quality-gate 的火山图节点，防止 DAG 绕过 QC：[`mas_plan_validator.py:124-145`](../../../src/cygnusx/application/services/mas_plan_validator.py)。

这已经是代码级质量门，但它的覆盖面取决于任务是否进入已登记 Flow/MAS executor 路径。自由 Skill 正文中的“质量门结论”不会自动调用这个服务。

## 5. 可展示的硬核实现

1. **声明式 Agent 装配 + 漂移清理**：YAML → loader → DB runtime，内置 Agent 的 MCP/Skill 绑定按声明集合重建，能清掉历史脏绑定。
2. **MCP 外部调用的完整工程闭环**：SDK 发现、长连接复用、传输安全校验、超时、重试、熔断、builtin/local fallback、Trace/Log/Metrics。
3. **审批参数绑定**：确认记录保存参数 hash；人类批准后只能以同一 tool/同一参数、在 TTL 内一次消费，模型不能伪造 `_confirmed` 绕过。
4. **沙箱安全基线收敛**：capability/镜像选择与 Docker `cap_drop=ALL`、非 root、只读 rootfs、pids/网络/挂载限制相互配合；旧容器不符合基线直接销毁重建。
5. **QC 与 DAG 结构联动**：不仅计算指标，还在计划验证阶段强制 artifact contract 和 quality-gate 依赖，防止下游可视化绕过质量门。

## 6. Gap Analysis 与最小加固建议

### G1：普通 Skill 的生信语义没有统一硬校验

**证据**：`skillmd.py` 只校验文件/元数据；`delivery-report/SKILL.md` 的输入、重复数、产物和降级要求没有对应通用 evaluator。  
**风险**：模型可以加载正文后仍把 TPM 当 counts，或在重复数不足时继续规划；Skill 的“契约”依赖模型遵守文字。  
**最小加固**：为 Skill frontmatter 增加可选 `contract`（`inputs`, `preconditions`, `assumptions`, `outputs`）字段；导入时用 Pydantic 编译；执行 `use_skill` 前由 `SkillContractValidator` 对文件类型、矩阵单位、样本数和 artifact schema 做硬拒绝/降级。没有 contract 的旧 Skill 明确标记 `prompt_only`。

### G2：最终回答没有统一结构化输出校验

**证据**：Provider 使用 OpenAI `tools`，但没有全局 `response_format`/Pydantic 结果验证；无 tools fallback 还会回到纯文本：[`openai_compatible.py:326-332`](../../../src/cygnusx/infrastructure/ai_provider/openai_compatible.py)。  
**风险**：计划、质量结论和交付摘要在不同执行路径可能出现字段漂移。  
**最小加固**：只对需要机器消费的节点（plan/QC/delivery）启用版本化 Pydantic envelope；自然语言最终回答保留文本，不要试图把所有聊天强制 JSON 化。

### G3：Skill 危险脚本扫描目前是 warning

**证据**：`DANGEROUS_PATTERNS` 扫描结果进入 `warnings`，`parse_skill_folder()` 不因命中而拒绝导入：[`skillmd.py:29-39`](../../../src/cygnusx/infrastructure/skills/skillmd.py)、[`skillmd.py:238-255`](../../../src/cygnusx/infrastructure/skills/skillmd.py)。  
**风险**：如果下游把 Skill 脚本直接交给沙箱执行，安装审查未完成时仍可能进入运行面。  
**最小加固**：区分 `warning` 与 `blocked`；危险模式、脚本解释器和网络写入策略至少在执行前由 sandbox capability 再拦一次；保留管理员显式 override 和审计记录。

### G4：确认服务的内存回退不适合多 worker 生产

**证据**：Redis 初始化失败时回退 `_MemoryStore`，注释明确是单 worker/测试场景：[`tool_confirmation_service.py:135-185`](../../../src/cygnusx/application/services/tool_confirmation_service.py)。  
**风险**：一个 worker 写入的批准状态对另一个 worker 不可见。  
**最小加固**：生产配置下 Redis 不可用直接 fail closed；仅在测试或显式 development profile 允许内存回退，并把存储后端状态写入健康检查。

### G5：MCP 能力目录缺少单一查询契约

**证据**：发现能力分散在 preset、DB server/tool 表、Agent binding 和 `MCPClient.list_tools()`；未找到统一 `ability_catalog_query`。  
**风险**：前端目录、Router 候选和运行时工具列表可能分别演进。  
**最小加固**：增加只读 `ability_catalog_query` service/API，输出 server/tool/skill、版本、required capabilities、input schema、availability 和 source，并让管理页、Router 与 Agent 装配共用该投影。

## 7. 最终判断

仓库已经具备真实的 Agent 平台执行骨架：Prompt/Agent 装配、MCP 调用隔离、Docker 沙箱、数据库幂等、审批状态机和 MAS QC 质量门都不是空接口。对外表述“AI 只调度、不生成流程、不直接写 DB”在工具和沙箱边界上有工程依据。

但不能把它描述成“600+ 生信 Skill 均已被三层统计契约硬校验”。当前更准确的说法是：**Skill 有标准化生命周期、渐进披露和审计；已登记 Flow/MAS 路径有 artifact/QC 硬门；普通 Skill 的生物信息学前置条件、统计假设和详细输出规范仍主要由 Markdown/Prompt 约束。**
