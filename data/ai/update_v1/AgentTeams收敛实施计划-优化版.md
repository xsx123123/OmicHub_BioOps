# AgentTeams 收敛计划：从多路径并存到单窗口群聊（优化版）

> 版本：1.1（审核优化版，基于 v1.0 修订）
> 日期：2026-08-11
> 性质：施工计划与文件改动清单
> 配套目标文档：`AgentTeams_VISION_FINAL.md`（v1.1）
>
> v1.1 修订要点：统一“16 个 Agent / 14 个可招募专家”口径并修正身份令牌数量；补充自动建单幂等、
> 计划版本化改造项；事件游标迁移改为显式“双写→对账→切读→清理”四步；每个 Phase 增加回退方案与
> 依赖关系；修正 Phase 0 验收措辞（fan-out 在常规页面保留）；新增并发配额与可观测性改造项；
> 明确 Worker 资源池部署形态。

---

## 实施状态（2026-08-11）

**当前结论：本轮收敛实现已初步完成，进入平台页面与真实运行验收阶段。** 本文仍是后续问题修复和增量调整的施工依据，不应将以下运行期验收项标记为已完成。

### 已完成的实现与验证

- 已收敛 AgentTeams 为产品内原生聊天闭环：移除了 Matrix/Element 外链群聊、Element 抽屉及对应公开 API 入口；历史数据字段仅作兼容清理，不再参与新链路。
- 已将 MAS 保持为默认关闭的历史路径；`parallel_subagents` 只保留在常规 AI 助手页面，已从已绑定 AgentTeams Case 的编排路径隔离。
- 已接入角色 registry、Bridge/Gateway/Projector 一致性消费、14 个可招募专家 Worker 资源池，以及聊天内建单、计划确认、审批、取消、重试、报告沙箱预览和审计投影闭环。
- 已实现事件游标的 `dual_write` / `new_only` / `legacy_only` 分阶段迁移逻辑，并提供延迟样本校验脚本及部署说明。
- 已完成受影响后端、Bridge、Gateway、Worker 和前端组件的自动化回归；本机 Compose、Bridge 健康检查及 14 个 Worker 心跳均已验证。

### 平台页面验收中

- 在真实浏览器页面完成建单、计划确认/修改/取消、审批、追问、重试、终止、刷新恢复和报告预览的人工回归；发现问题后以本文的对应章节为准修复并补充测试。
- 每类延迟至少采集 20 条真实样本，验证审计事件到前端可见 P95 ≤ 3 秒、审批点击到后端受理 P95 ≤ 1 秒；不得用单元测试耗时替代。
- 保持 `AGENTTEAMS_CASE_CURSOR_MIGRATION_MODE=dual_write`，待后台 watcher 连续 3 个自然日零 mismatch 后才可切换至 `new_only`；发生迁移事故时回退至 `legacy_only`。

---

## 1. 目标与原则

### 1.1 目标

以 **“用户参与的单窗口多专家群聊”** 为唯一产品形态，收敛当前四条多智能体路径，保留并复用 AgentTeams 基础设施，让平台上全部 14 个可招募专家 Agent 都能作为群聊中的专家被招募（口径见 VISION v1.1 §4.1：`shania` 不承接工单、`agent-router` 仅做路由）。

### 1.2 核心原则

1. **单窗口唯一入口**：用户不跳页、不打开外链。
2. **AgentTeams 只做编排**：状态机、工单、审批、审计；不运行 LLM。
3. **平台 Agent 即专家**：14 个可招募专家 + shania 轻量陪伴 + agent-router 入口路由。
4. **角色映射单一来源**：Bridge/Gateway/投影器共用同一份 registry。
5. **不新造事件类型**：复用 `room_speech` / `overdrive_progress` / `ask_request` / `overdrive_approval_request` / `mode_changed`；payload 扩展字段须进契约测试。
6. **先拆旧枝、再添新叶**：移除重复/关闭的路径，再补全剩余缺口。
7. **每个 Phase 可独立回退**：任何一阶段出问题不影响已上线能力（见各 Phase 回退方案）。

---

## 2. 需要移除的内容

### 2.1 MAS 编排（orchestrator + DAG）

**原因**：默认关闭，与单窗口群聊形态冲突；和 AgentTeams 重复。

| 改动项 | 具体位置 | 操作 |
| --- | --- | --- |
| 默认启用开关 | `src/omichub/core/config.py`：`settings.mas_enabled` | 默认值保持 `False`，并在文档中标记为“deprecated，不再作为用户入口” |
| 动态追加 orchestrator | `src/omichub/infrastructure/config/agent_loader.py` | 删除 `mas_enabled` 打开时自动追加 `orchestrator` 的逻辑 |
| 计划工具挂载 | `data/ai/tools/*.yaml` 中 `mas_plan_preview` 等 | 从所有 Agent 的 Tool Pack 中移除 |
| 前端入口 | 管理台 MAS 开关、聊天中 MAS 计划卡 | 移除 UI 入口，保留后端 API 只读兼容 |
| 文档 | `data/ai/README.md` §11.4 / §12.1 / §13.1 | 改写为“历史路径，已收敛到 AgentTeams” |

### 2.2 对话内 fan-out (`parallel_subagents`) 的范围收敛

**原则**：`parallel_subagents` 作为常规 AI 助手页面的**单会话轻量并行工具**继续保留；本次收敛只限制它**不再作为一条独立的 multi-agent 路径与 AgentTeams 群聊并存**。

**原因**：在 AgentTeams 群聊目标下，复杂多专家协作应由 Case / Work Item 编排；若同时保留 chat 循环内的 fan-out，会造成两条 multi-agent 路径竞争，且 fan-out 的 `ask_user` 不冒泡、无泳道展示。

| 改动项 | 具体位置 | 操作 |
| --- | --- | --- |
| AgentTeams 工具包 | `data/ai/tools/agentteams_case.yaml` | 确保 **不挂载** `subagents` 工具；AgentTeams 内部不通过 fan-out 派生子 Agent |
| AgentTeams 场景下的 chat 循环 | `src/omichub/application/services/chat_service.py` | 当当前会话已绑定 AgentTeams Case 时，不走 `parallel_subagents` 分支；改由 Bridge 派 Work Item |
| 常规 AI 助手页面 | `SettingsView.vue` / `chat_service.py` | **保留** `subagent_fanout_enabled` 开关和 `parallel_subagents` 工具调用能力 |
| 前端事件处理 | `frontend/src/composables/useAgentChatStream.ts` | 保留 `case 'subagents'`，但仅用于常规 AI 助手页面的轻量并行展示；AgentTeams Case 事件走 `room_speech` |
| 管理端开关 | 管理端 `subagent_fanout_enabled` | **保留**，文案明确为“常规助手页面启用轻量并行子 Agent” |

### 2.3 AgentTeams Matrix/Element 外链群聊

**原因**：不是产品内原生群聊，体验割裂。

| 改动项 | 具体位置 | 操作 |
| --- | --- | --- |
| Element iframe 抽屉 | `frontend/src/components/agentteams/AgentTeamsChatDrawer.vue` | 删除组件，或保留为只读历史审计入口（不推荐） |
| Element 外链按钮 | `AgentTeamsCaseView.vue` / `AgentTeamsCaseCard.vue` | 删除“打开群聊室”按钮 |
| Matrix 相关配置 | `deploy/agentteams/` 中 Matrix/Element URL 配置 | 标记为 deprecated，后续移除 |

### 2.4 独立 Case 详情页作为强制入口

**原因**：复杂任务必须在聊天内闭环。

| 改动项 | 具体位置 | 操作 |
| --- | --- | --- |
| 聊天内创建 Case | `frontend/src/components/ai-chat/KimiChatInput.vue:799-805` / `StudioView.vue:604-607` | 改为直接调用 `createCase` API，并插入 `AgentTeamsCaseCard` |
| 审批跳转 | `AgentTeamsCaseCard.vue:71-74` | 在卡片内直接实现“批准/拒绝”按钮，调现有 `POST /api/v1/agent-teams/cases/{id}/submit` |
| Case 详情页定位 | `frontend/src/views/AgentTeamsCaseView.vue` | 保留，但仅作为“查看审计详情/下载 manifest”入口 |

### 2.5 旧版 AgentTeams 文档

| 改动项 | 具体位置 | 操作 |
| --- | --- | --- |
| 归档旧文档 | `data/ai/update/AgentTeams_update*.md`、`AgentTeams_codex_prompt*.md` | 移入 `data/ai/update/archive/` |
| 更新 README | `data/ai/README.md` §13 / §8.1 / §11.4 | 引用 `AgentTeams_VISION_FINAL.md` 作为唯一权威目标 |
| 更新 update_agent.md | `data/ai/update/update_agent.md` | 删除其中 AgentTeams 比赛阶段描述，改为引用 VISION_FINAL；保留赛后超频 v2 长期目标 |

---

## 3. 需要保留并复用的内容

### 3.1 AgentTeams 编排基础设施

| 组件 | 位置 | 复用方式 |
| --- | --- | --- |
| Bridge 状态机 | `integrations/agentteams/bridge/omichub_agentteams_bridge/case_store.py` | 完整保留，作为 Case/Work Item 权威状态；核对 15 态清单与 VISION v1.1 §6.1 一致 |
| Gateway | `integrations/agentteams/gateway/` | 完整保留，作为 Bridge → OmicHub 的受控通道 |
| Worker 集群 | `integrations/agentteams/worker/` | 完整保留，负责认领和转发；改造为按 capability 认领的资源池（见 §4.2） |
| 审批签名 | `integrations/agentteams/bridge/omichub_agentteams_bridge/security.py` | 完整保留 |
| 审计事件 | `integrations/agentteams/bridge/omichub_agentteams_bridge/audit.py` | 完整保留，append-only |
| MinIO 共享存储 | `src/omichub/infrastructure/storage/minio_store.py` | 完整保留，作为 agent 间产物传递 |
| 生命周期清理 | `src/omichub/infrastructure/celery_app/tasks/agentteams.py` | 完整保留 |

### 3.2 OmicHub 平台 Agent

| 组件 | 位置 | 复用方式 |
| --- | --- | --- |
| Agent YAML | `data/ai/*.yaml` | 全部保留，每个 Agent 都可以被招募 |
| Agent 装载 | `src/omichub/application/services/agent_service.py` | `assemble_context(agent_id, user_id=...)` 作为 consultation 执行基础 |
| consultation 端点 | `src/omichub/api/v1/agentteams.py` | 保留并扩展为所有专家角色的统一执行入口 |
| 只读执行内核 | `src/omichub/application/services/agent_consultation_service.py` + `ParallelSubAgentService` | 保留，`safe_only=True` 用于只读专家，`workspace_access=True` 用于执行型专家 |
| 只读数据工具 | `tool_configs/tools_schema.yaml` 中 read-only 工具 | 保留，供专家读取真实数据 |
| 硬规则 QC 门 | `src/omichub/application/services/agentteams_quality_gate_service.py` | 保留 |
| 能力注册表 | `src/omichub/application/services/agentteams_capability_registry.py` | **升级为角色映射单一来源** |

### 3.3 超频模式前端组件

| 组件 | 位置 | 复用方式 |
| --- | --- | --- |
| 房间消息流 | `frontend/src/components/ai-chat/KimiMessageItem.vue` | 复用 `room_speech` / `room_speech_delta` 渲染 |
| 进度卡 | `frontend/src/components/ai-chat/OverdriveProgressCard.vue` | 复用为专家泳道/招募卡 |
| 用户询问 | `frontend/src/components/ai-chat/AskUserCard.vue` / `AskUserModal.vue` | 复用为群内决策弹窗 |
| 审批卡 | `frontend/src/components/ai-chat/OverdriveApprovalCard.vue` | 复用为群内高风险审批 |
| 流解析 | `frontend/src/composables/useAgentChatStream.ts` | 复用现有 `case 'room_speech'` 等分支 |
| Store | `frontend/src/stores/agentHub.ts` | 复用 `applyCaseRoomEvent` |

### 3.4 CaseRoomProjector

| 组件 | 位置 | 复用方式 |
| --- | --- | --- |
| 事件投影器 | `src/omichub/application/services/case_room_projector.py` | 保留并扩展 speech 模板，覆盖全部 14 个专家的发言场景 |
| watch 服务 | `src/omichub/application/services/agentteams_case_watch_service.py` | 保留；interval 从 60s 降至 10-15s，**且降级为非事件驱动来源的兜底**（主链路走事件推送，见 §4.7） |
| 事件消费者 | `src/omichub/application/services/agentteams_case_event_consumer_service.py` | 保留 |

---

## 4. 需要新增/修改的内容

### 4.1 角色映射单一来源改造

**目标**：Bridge/Gateway/投影器共用 `AgentTeamsCapabilityRegistry`。

| 改动 | 位置 | 要点 |
| --- | --- | --- |
| registry 自动聚合 | `src/omichub/application/services/agentteams_capability_registry.py` | registry 改为**从各 Agent YAML 自动聚合生成**（`internal_case_role` + `features.agentteams` + `capability_*` 字段），提供 `role_agent_map()`、`role_labels()`、`agent_capabilities()`；覆盖 14 个专家 + shania/router 的类别标记；旧身份名（如 `data-steward`）作为别名映射保留；加载时校验 status_lines 七键齐备、execution_modes 已声明，缺失即报错 |
| Agent YAML 声明块 | `data/ai/*.yaml` | 每个 Agent 增加 `features.agentteams` 块：recruitable / planner_eligible / execution_modes / max_parallel_work_items / case_mode_excluded_tool_packs / handoff_in_case_mode / work_item_timeout_sec；模板以 `data/ai/atacseq.yaml` 为准 |
| Bridge 消费 registry | `integrations/agentteams/bridge/omichub_agentteams_bridge/service.py` | 创建 Work Item 时调用 registry 解析 `target → agent_id`；删除本地硬编码映射 |
| Gateway 消费 registry | `integrations/agentteams/gateway/service.py` | `agent_policies` 从 registry 动态加载 |
| 投影器消费 registry | `src/omichub/application/services/case_room_projector.py` | 已接入，扩展即可 |
| 测试 | `tests/unit/test_agentteams_capability_registry.py` | 确保映射覆盖全部 16 个 Agent（含类别标记），且三处一致 |

### 4.2 全部专家 Agent 接入 AgentTeams

**目标**：每个可招募专家都能在群聊中被招募，并有稳定的人格/头像/名字。

| 改动 | 位置 | 要点 |
| --- | --- | --- |
| Agent YAML 加 `persona` | `data/ai/*.yaml` | 按 `update_agent.md` §3.1 增加 `features.persona`：archetype/traits/working_style/communication_style/status_lines |
| Agent YAML 加 `internal_case_role` | `data/ai/*.yaml` | 声明该 Agent 在 AgentTeams 中的默认角色 ID（与 Agent ID 同名规范，见 VISION §8.1） |
| 补齐骨架 Agent | `data/ai/data.yaml`、`data/ai/delivery.yaml` | 挂载 skill_ids、补提示词、去掉“正在配置”文案 |
| Bridge 角色配置 | `integrations/agentteams/teams/bioops-delivery.yaml` | 补全 14 个专家角色定义，每个角色指向对应 Agent；shania 标记 `accepts_work_items: false` |
| Bridge env 令牌 | `deploy/agentteams/bridge.env.example` | 补全 **14 个专家身份令牌占位符**（v1.0 写“11+”与角色数不一致，已修正），与 `bridge/config.py` 默认值对齐；真实令牌走密钥管理，不入仓库 |
| Worker 资源池 | `integrations/agentteams/worker/production_runner.py` / `worker_runner.py` / `docker-compose.agentteams.yml` | **不按角色各起一个 Worker 服务**；改为少量 Worker 实例按 `capabilities` 声明认领多类工单，`_AGENT_PROFILES` 覆盖全部角色；docker-compose 仅按需增加 Worker 副本数而非角色数 |

### 4.3 聊天内创建 Case 与审批闭环

**目标**：用户在当前聊天窗口内触发和审批 AgentTeams 群聊。

| 改动 | 位置 | 要点 |
| --- | --- | --- |
| 结构化建单弹窗 | `frontend/src/components/ai-chat/KimiChatInput.vue` | 增加“创建协作 Case”按钮，弹窗收集目标/输入/领域，调 `POST /api/v1/agent-teams/cases` |
| 消息内建单 | `StudioView.vue` / 路由相关 | 同样接入 createCase |
| Case 卡片内审批 | `frontend/src/components/agentteams/AgentTeamsCaseCard.vue` | 增加“批准 / 拒绝”按钮，直接调 submit API；结果经 SSE 刷新 |
| Manager 自动建单 | `src/omichub/application/services/chat_service.py` | Manager 判断需要多专家协作时自动创建 Case 并绑定 session；**必须携带幂等键（`session_id + 意图哈希`）防重复建单**；创建后在群里说明触发理由；计划确认前用户可一键取消 |
| 创建工具 | `data/ai/tools/agentteams_case.yaml` | 保留 `create_agentteams_case`，但降低使用门槛（默认参数由 Manager 自动填充） |
| 三类审批边界落地 | 前端 + 后端 | 按 VISION v1.1 §5.4 的适用边界实现：计划确认走 `ask_request(kind=plan_confirmation)`，高风险操作走 `overdrive_approval_request`，Case 提交走卡片按钮；各自超时策略一并实现 |

### 4.4 群聊投影增强

**目标**：Case 事件在聊天窗口里看起来像群聊。

| 改动 | 位置 | 要点 |
| --- | --- | --- |
| 扩展 speech 模板 | `src/omichub/application/services/case_room_projector.py` | 为每个专家类型定制发言文案；规划、结果回流、点评、QC、交付都有独立模板 |
| Manager 自动点评 | `case_room_projector.py` + Bridge | 每条专家结果回流后自动创建 manager review 隐式工单，`manager_review_ready` 事件投影为 Manager 的 `room_speech`（接受 / 返工 / 触发下游） |
| 进度卡增强 | `OverdriveProgressCard.vue` | 显示“谁在做什么”而不是抽象的 task ID |
| 产物卡片 | 复用 `overdrive_progress` artifacts | 在群里显示最近 3 个产物缩略 + 下载 |
| 动态报告预览 | 前端消息组件 | Plotly 等 HTML 报告以 sandboxed iframe + 严格 CSP 预览（安全约束见 VISION §8.4） |
| payload 契约测试 | `tests/contract/` | `room_speech` 等事件扩展字段（头像、角色名）固化进契约测试 |

### 4.5 规划阶段标准化与计划版本化

**目标**：复杂任务必须先由真实领域 Agent 出 plan，用户确认后再执行；计划可修改且版本可追溯。

| 改动 | 位置 | 要点 |
| --- | --- | --- |
| planning_running 状态 | `integrations/agentteams/bridge/omichub_agentteams_bridge/case_store.py` | 确保未经过 planning 且无 plan_hash 不得进入 approval_pending / executing |
| lead planner 选择 | `src/omichub/application/services/chat_service.py` 或新服务 | Manager 按任务方向 + `capability_scope` 选 lead planner；选择理由落审计 |
| plan-01 Work Item | Bridge `service.py` | 自动创建 planning 工单，target 为 lead planner |
| 计划确认卡 | 前端 + 后端 | `ask_request(kind=plan_confirmation)`，展示 `plan_version` + `plan_hash` 前 8 位 + 摘要 + 参数 |
| 计划版本化 | Bridge `models.py` + `service.py` | `proposed_submission` + `plan_hash` + `plan_version`；用户修改生成新版本并重新确认，旧 hash 立即失效，未开始工单重绑新 hash（规则见 VISION §8.3） |
| 修订上限升级 | Bridge `service.py` | 修订 >5 轮时升级给用户：继续修订 / 更换 lead planner / 取消 |
| 质控决策 | plan.md / `proposed_submission` | lead planner 在计划中显式声明是否需要 `quality_running`；仅声明时创建 `quality-01` |

### 4.6 workspace_execution 通用化

**目标**：不局限于 RNA-seq，treeplot 等通用任务也能跑通。

| 改动 | 位置 | 要点 |
| --- | --- | --- |
| execution_mode 分发 | Bridge `service.py` | `workspace_execution` 工单允许非只读，但必须绑定已确认 plan_hash |
| 产物登记 | `src/omichub/application/services/agentteams_data_tool_service.py` | 确保 `_register_workspace_artifacts` 写 `file_records`（source="agentteams"） |
| artifact_fetch 工具 | `tool_configs/tools_schema.yaml` | 保留并加入所有相关 Tool Pack |
| 输入文件只读保护 | Studio 沙箱 (`manager.py:382-391`) / `data/ai/prompts/shared/agentteams_workspace_execution.md` | 用户真实数据目录以 `mode: "ro"` bind mount 到沙箱 `/data/platform`；只读保证来自挂载层而非软链（软链可被删除替换，不能作为只读手段） |
| 示例 flow | `data/ai/flows/treeplot.yaml` | 保留作为通用分析型标本 |

### 4.7 事件推送主链路 + 游标迁移（v1.1 拆分为独立小节）

| 改动 | 位置 | 要点 |
| --- | --- | --- |
| 事件驱动推送 | Bridge → OmicHub → SSE | 状态变化优先走事件推送，目标 P95 ≤ 3s 前端可见；watch 轮询（10–15s）仅兜底 |
| 游标表迁移（四步） | alembic + `agentteams_case_watch_service.py` | ① 建表 `agentteams_case_cursors`；② **双写**：新旧存储同时写；③ **对账**：后台任务比对双写一致性，连续 3 天零差异后 ④ **切读**新表并停止写旧字段；全程可回退到读 `sandbox_meta` |
| 可观测性接入 | 全链路 | 日志/指标携带 `case_id`/`work_item_id`/`event_id`；上线 Case 时长、失败率、审批等待、自动建单取消率看板（指标清单见 VISION §9.3） |
| 并发配额 | Bridge `service.py` + config | 单 Case 并行工单上限（默认 8）、单用户活跃 Case 上限（默认 3），超出排队并在群里提示 |

---

## 5. 分阶段实施计划

> 依赖关系：Phase 0 独立；Phase 1 依赖 Phase 0 的归档完成（避免文档口径打架）；Phase 2 依赖 Phase 1 的 registry（自动建单要用角色解析）；Phase 3 依赖 Phase 2 的事件闭环；Phase 4 依赖全部前序。
> 人力排期按 1 名后端 + 1 名前端 + 0.5 名测试估算，若有调整按依赖链顺延。

### Phase 0：止血与归档（1 周）

1. 把旧版 AgentTeams 文档移入 `archive/`。
2. 关闭 MAS 编排的动态启用逻辑；从 Agent Tool Pack 中移除 `mas_plan_preview`。
3. 在 AgentTeams 场景下不再通过 `parallel_subagents` 派生子 Agent；确保 `agentteams_case` Tool Pack 不挂载 `subagents`，`chat_service.py` 在已绑定 Case 的会话中走 Bridge Work Item 而非 fan-out。
4. 移除 Element 外链入口和 iframe 抽屉。
5. 把 `AgentTeamsCaseView.vue` 的审批按钮直接暴露到 `AgentTeamsCaseCard.vue`。

**验收**：
- 旧文档不再出现在 `data/ai/update/` 根目录。
- 简单问答不触发 MAS / AgentTeams；fan-out 仅在常规助手页面按开关生效，且不出现在 AgentTeams 群聊会话中。
- 聊天内可对 Case 卡片做批准/拒绝。

**回退**：全部为开关/入口级改动，通过恢复配置与前端入口即可回退，无数据迁移。

### Phase 1：统一角色映射（1 周）

1. 扩展 `AgentTeamsCapabilityRegistry` 覆盖 16 个 Agent（14 专家 + shania + router 类别标记）。
2. Bridge/Gateway/投影器统一消费 registry。
3. 为每个 Agent YAML 增加 `features.persona` 和 `internal_case_role`。
4. 补齐 `agent-data`、`agent-delivery` 的 skill_ids 和提示词。
5. 更新 `bioops-delivery.yaml`（14 角色）和 `bridge.env.example`（14 个令牌占位符）。
6. Worker 改造为 capability 资源池，`_AGENT_PROFILES` 覆盖全部角色。

**验收**：
- `test_agentteams_capability_registry.py` 全绿，验证映射三处一致。
- 触发一个 Case，聊天气泡显示正确专家名字和头像。

**回退**：registry 增加特性开关，异常时切回 Bridge 内置映射（保留一个版本周期后删除）。

### Phase 2：聊天内闭环（1-2 周）

1. Manager 自动判断何时创建 AgentTeams Case（含幂等键、触发理由、可取消）。
2. 实现“创建协作 Case”结构化弹窗。
3. 实现 plan_confirmation 弹窗（确认/修改/取消；修改走计划版本化）。
4. `ask_request` 和 `overdrive_approval_request` 在聊天内闭环（含 §5.4 超时策略）。
5. 事件游标迁移：建表 → 双写 → 对账（本 Phase 内完成①②③，④切读放到 Phase 3 稳定后执行）。
6. 并发配额上线（单 Case / 单用户上限）。

**验收**：
- 用户从发任务到确认计划，全程不跳页；重复触发不产生重复 Case。
- 计划修改生成新版本，旧 hash 失效有群里提示。
- 双写对账连续 3 天零差异。

**回退**：自动建单可开关降级为仅手动建单；游标读路径切回 `sandbox_meta`。

### Phase 3：群聊体验打磨（1-2 周）

1. 扩展 `CaseRoomProjector` speech 模板，让专家发言更像人。
2. Manager 自动验收点评投影为 room_speech。
3. 进度卡显示“谁在做什么”；产物在群里直接展示最近 3 项。
4. 事件推送主链路上线，watch 轮询降为兜底（10-15s）。
5. 动态报告 sandboxed iframe 预览。
6. 游标切读新表（④），观测一周无异常后停止写旧字段。
7. 可观测性看板上线（Case 时长、失败率、审批等待、自动建单取消率）。

**验收**：
- 3 个以上专家参与的 Case，在窗口内按完成顺序逐个发言；事件 → 前端可见 P95 ≤ 3s。
- 产物可点击下载；HTML 报告在沙箱 iframe 内预览且无法携带会话凭证。

**回退**：推送链路异常时把 watch 间隔临时调回主链路模式（配置项），前端无感知。

### Phase 4：端到端验收（1 周）

1. RNA-seq 复合任务端到端（主路径 10 条验收）。
2. 通用 treeplot 任务端到端。
3. 异常路径：计划修改与版本化、取消、失败重试与耗尽、断线恢复、修订超上限升级、用户终止。
4. 非功能：时延、并发配额、可观测性指标达标。
5. 全量回归测试。

**验收**：
- 通过 `AgentTeams_VISION_FINAL.md`（v1.1）§10 全部验收标准（主路径 + 异常路径 + 非功能）。

**回退**：验收不通过项按 Phase 边界局部回退，不影响已验收 Phase。

---

## 6. 文件改动清单

### 6.1 后端

| 文件 | 操作 | 说明 |
| --- | --- | --- |
| `src/omichub/core/config.py` | 修改 | `mas_enabled` 默认 False，标记 deprecated；新增并发配额配置 |
| `src/omichub/infrastructure/config/agent_loader.py` | 修改 | 移除 mas_enabled 追加 orchestrator 逻辑 |
| `src/omichub/application/services/agentteams_capability_registry.py` | 扩展 | 覆盖 16 个 Agent 的角色映射、标签与类别标记；旧身份别名兼容 |
| `src/omichub/application/services/case_room_projector.py` | 扩展 | 增加 Manager 点评和全部专家发言模板 |
| `src/omichub/application/services/agentteams_case_watch_service.py` | 修改 | 降为兜底轮询（10-15s）；游标双写/切读 |
| `src/omichub/application/services/chat_service.py` | 修改 | Manager 自动建 Case（幂等键 + 触发理由 + 可取消）；已绑定 Case 的会话不走 `parallel_subagents` |
| `src/omichub/api/v1/agentteams.py` | 修改 | 保留并扩展 consultation 端点 |
| `tool_configs/tools_schema.yaml` | 修改 | 移除 mas 工具；保留 read_only / artifact_fetch |
| `data/ai/tools/agentteams_case.yaml` | 修改 | 确保不挂载 `subagents`；保留 `create_agentteams_case` 等 |
| `data/ai/tools/*.yaml` | 修改 | 移除 `mas_plan_preview` 等包；常规 Agent 的 `subagents` 包保留 |
| `data/ai/*.yaml` | 修改 | 增加 persona 和 internal_case_role |
| `data/ai/data.yaml`、`delivery.yaml` | 修改 | 补齐 skill_ids 和提示词 |
| `data/OmicHub.yaml` | 修改 | 移除 orchestrator 自动启用描述（如存在） |
| alembic 迁移 | 新增 | `agentteams_case_cursors` 表；Case/WorkItem 增加 `plan_version` 字段（如模型层尚未有） |

### 6.2 AgentTeams Bridge/Gateway/Worker

| 文件 | 操作 | 说明 |
| --- | --- | --- |
| `integrations/agentteams/teams/bioops-delivery.yaml` | 扩展 | 补全 14 个专家角色；shania 标记不接工单 |
| `integrations/agentteams/bridge/omichub_agentteams_bridge/service.py` | 修改 | 消费 registry；删除本地硬编码映射；计划版本化；修订上限升级；并发配额 |
| `integrations/agentteams/bridge/omichub_agentteams_bridge/models.py` | 修改 | `proposed_submission` + `plan_hash` + `plan_version` |
| `integrations/agentteams/bridge/omichub_agentteams_bridge/config.py` | 修改 | 角色默认配置与 registry 对齐 |
| `deploy/agentteams/bridge.env.example` | 修改 | 补全 **14 个身份令牌占位符**（修正 v1.0 的“11+”），注明真实令牌走密钥管理 |
| `deploy/agentteams/docker-compose.agentteams.yml` | 修改 | Worker 改为资源池副本形态，按容量而非角色数扩展 |
| `integrations/agentteams/worker/production_runner.py` / `worker_runner.py` | 扩展 | `_AGENT_PROFILES` 覆盖全部角色；按 capabilities 认领 |
| `integrations/agentteams/gateway/service.py` | 修改 | agent_policies 从 registry 加载 |

### 6.3 前端

| 文件 | 操作 | 说明 |
| --- | --- | --- |
| `frontend/src/components/ai-chat/KimiChatInput.vue` | 修改 | 增加“创建协作 Case”结构化弹窗 |
| `frontend/src/components/agentteams/AgentTeamsCaseCard.vue` | 修改 | 增加批准/拒绝按钮 |
| `frontend/src/components/agentteams/AgentTeamsChatDrawer.vue` | 删除或降级 | 移除 Element iframe |
| `frontend/src/components/agentteams/AgentTeamsCaseView.vue` | 修改 | 移除“打开群聊室”按钮；保留审计详情 |
| `frontend/src/components/ai-chat/OverdriveProgressCard.vue` | 扩展 | 显示专家名字与任务；最近 3 项产物 |
| `frontend/src/components/ai-chat/`（报告预览组件） | 新增/修改 | HTML 报告 sandboxed iframe 预览 |
| `frontend/src/composables/useAgentChatStream.ts` | 修改 | 保留 `subagents` 分支供常规助手页面使用；确保 AgentTeams Case 的 `room_speech` / `overdrive_progress` 事件被消费 |
| `frontend/src/stores/agentHub.ts` | 修改 | 复用 applyCaseRoomEvent |

### 6.4 测试

| 文件 | 操作 | 说明 |
| --- | --- | --- |
| `tests/unit/test_agentteams_capability_registry.py` | 扩展 | 16 Agent 映射三处一致 |
| `tests/contract/` | 新增 | SSE payload 扩展字段契约；Bridge/Gateway 既有契约保持绿 |
| `tests/e2e/agentteams/` | 新增 | 主路径 + 异常路径（修改/取消/重试/断线/超上限）场景，使用固化测试数据 |

### 6.5 文档

| 文件 | 操作 | 说明 |
| --- | --- | --- |
| `data/ai/update/AgentTeams_VISION_FINAL.md` | 新增/更新 | 本计划配套目标文档（v1.1） |
| `data/ai/update/AgentTeams_CONVERGENCE_PLAN.md` | 新增/更新 | 本计划（v1.1） |
| `data/ai/update/archive/*.md` | 归档 | 旧版 v1/v2/v2.1/v2.2/codex 文档 |
| `data/ai/README.md` | 修改 | §13 等章节引用 VISION_FINAL |
| `data/ai/update/update_agent.md` | 修改 | 删除 AgentTeams 比赛阶段描述，引用 VISION_FINAL |

---

## 7. 风险与回退

| 风险 | 影响 | 缓解措施 | 回退 |
| --- | --- | --- | --- |
| 收敛 fan-out 范围时误伤常规助手页面 | 中 | 明确只限制 AgentTeams 场景；常规页面保留开关；加页面级回归测试 | 恢复 `chat_service.py` 分支条件 |
| 关闭 MAS 影响已启用用户 | 低 | MAS 默认关闭，影响面小；保留后端 API 只读兼容 | 恢复配置开关 |
| Bridge 角色映射改造引入回归 | 中 | 契约测试三处一致；registry 特性开关灰度放量 | 切回 Bridge 内置映射 |
| 全部 Agent 接入增加调试面 | 中 | 分 Phase 逐个验证；骨架 Agent 优先补齐 | 按角色逐个禁用招募 |
| 事件游标迁移丢事件 | 高 | 双写 → 对账 3 天 → 切读 → 停旧写的四步流程 | 任一环节异常切回读 `sandbox_meta` |
| 用户不适应“自动建 Case” / 过度编排 | 中 | 触发理由可见、可一键取消、保留手动入口；取消率上监控 | 关闭自动建单，仅手动触发 |
| 自动建单重复触发 | 中 | 幂等键（session + 意图哈希）；建单 API 服务端去重 | — |
| Worker 资源池改造导致工单认领延迟 | 中 | 认领逻辑契约测试；上线前压测认领吞吐 | 回退到按角色静态 profile |
| HTML 报告预览引入 XSS 面 | 高 | sandboxed iframe + CSP + 产物前缀白名单 | 关闭内联预览，仅提供下载 |

---

## 8. 完成检查清单

- [ ] Phase 0 完成：旧文档归档；MAS 入口移除；AgentTeams 场景不再走 fan-out（常规页面保留）；Element 入口移除。
- [ ] Phase 1 完成：16 个 Agent 角色映射（14 专家 + 2 特殊类别）三处一致；Worker 资源池形态上线。
- [ ] Phase 2 完成：聊天内可创建（含幂等）、确认（含版本化修改）、审批 Case；游标双写对账零差异；并发配额生效。
- [ ] Phase 3 完成：专家按完成顺序在群内发言；事件 → 前端 P95 ≤ 3s；产物可下载；报告沙箱预览；可观测看板上线；游标完成切读。
- [ ] Phase 4 完成：主路径 + 异常路径端到端通过；非功能指标达标；回归测试全绿。
- [ ] `AgentTeams_VISION_FINAL.md`（v1.1）§10 验收标准全部打勾。
