# Codex 施工提示词：AgentTeams v2.1（真干活 + 通用化，已归档）

> 用法：把本文件全文作为提示词发给 Codex（或等价编码 agent），在仓库根目录执行。  
> 权威施工规格：`data/ai/update/AgentTeams_update_v2.md`（下称"v2.1 规格"）与 `data/ai/AgentTeams_update.md`（下称"v1 基线"）。本提示词不替代它们，只定义执行纪律、顺序与交付格式。规格/基线与本提示词冲突时，以 v2.1 规格为准。  
> 目标：让 AgentTeams Case 真正产出可用结果，并支持 RNA-seq 规范流程与通用任务共存。

---

## 角色与上下文

你是 CygnusX 仓库的高级全栈工程师。CygnusX 是生信分析平台（FastAPI + Celery + Vue3），仓库内嵌 AgentTeams 协同栈（`integrations/agentteams/`：Bridge / Gateway / Worker 三个 Python 子项目 + `deploy/agentteams/` 部署目录）。

当前编排骨架（状态机/租约/审批/审计/投影）已验收（v1 基线），但存在三个核心缺口：
1. 会诊专家没有读取真实数据的工具（R2）；
2. 任务无看门狗、失败静默、交互体验差（R1/R4/R5）；
3. 运行时被 RNA-seq/scRNA-seq 硬编码绑定，无法扩展新流程（R6）。

本任务要求你在 v1 基线上实现 v2.1 规格，**严格按 P0 → P1 → P2 → G 顺序**逐项完成并验证。

---

## 开工前必读（按序）

1. `data/ai/update/AgentTeams_update_v2.md` 全文——§0 审核结论、§1 P0、§2 P1、§3 P2、§4 G 通用化、§6 验收标准；
2. `data/ai/AgentTeams_update.md` 的 §2（两层模型）、§3（任务拆解）、§8（施工清单）、§10（验收清单）——作为细节补充；
3. 规格文档中点名的源文件，动手前先读一遍现状代码。

---

## 施工范围与顺序（严格 P0 → P1 → P2 → G）

### 阶段 P0（不做则闭环跑不通）

必须逐项完成，P0 任意一项未验证通过不得开始 P1。

#### P0-1 ✅ snakemake logger 参数修复（R1，已完，跳过）

v2.1 规格 §1 P0-1 已标记完成。Codex 无需重做，但需确认：
- `worker` / `rocketmq-worker` 容器内 `snakemake --logger rich-loguru --dry-run` 通过。

#### P0-2 任务看门狗（R1）

1. Bridge `integrations/agentteams/bridge/cygnusx_agentteams_bridge/service.py`：
   - `reconcile_case` 增加 `omic_task_ids` 关联任务 queued 超时臂（默认 900s）；
   - 审计事件 `omic_task.stalled`，复核后仍 queued 则转 `execution_failed`；
   - 任务 failed 时把 `error_message` 尾部 500 字符写入审计 `omic_task.failed.payload.error_excerpt`。
2. CygnusX `src/cygnusx/infrastructure/celery_app/tasks/`：新增 `requeue_stale_tasks` beat 任务（300s）。
3. 存量 `f85c814d…` 手动标记 failed（交付报告中记录）。

#### P0-3 会诊长"手" + 硬规则门（R2）

1. `tool_configs/tools_schema.yaml` 注册 5 个只读工具（`read_only_hint: true`）：
   - `task_result_summary`
   - `task_file_preview`
   - `workspace_file_preview`
   - `task_compare_metrics`
   - `rule_threshold_lookup`
2. 实现对应 service/shim（复用 `pipeline_result_service` / `file_records`）。
3. 新增 `src/cygnusx/application/services/agentteams_quality_gate_service.py`：
   - 硬规则：mapping_rate / q30 / duplicate_rate；
   - 输出审计事件 `quality.hard_gate`。
4. `src/cygnusx/application/services/agent_consultation_service.py`：
   - prompt 升级：要求引用 task:/file: 必须先调用工具；
   - `evidence_refs` 升级为"已核验引用"。
5. `data/ai/qc.yaml`：提示词要求三态结论引用 metrics 字段名与数值。

#### P0-4 workspace_execution 的 Worker 认领实现（R3）

1. Bridge `service.py`：规划阶段对 `agent-code` / `agent-viz` 工单设 `execution_mode=workspace_execution`。
2. `worker/production_runner.py`：透传 `execution_mode`，结果 `artifacts` 回写 work item。
3. 新增 `data/ai/flows/treeplot.yaml`。
4. `data/ai/viz.yaml` 增加 `internal_case_role: agent-viz`。

#### P0-5 失败诊断与恢复回路（R4）

1. `case_room_projector.py`：增加 `omic_task.failed` / `case.execution_failed` 发言模板（含 `error_excerpt` + 建议）。
2. Bridge `service.py`：新增 `retry_case_submission`，幂等键升版；暴露 `POST /v1/cases/{id}/retry`。
3. `agentteams_case_watch_service.py`：连续 3 次拉取失败时投影同步异常提示。
4. CygnusX `src/cygnusx/api/v1/agentteams.py` 加 retry 代理端点。

#### P0-G 通用化基础：动态流程/角色/Agent 发现（R6）

**这是整个 v2.1 的底座，必须稳扎稳打。**

1. 新建 `src/cygnusx/application/services/agentteams_capability_registry.py`：
   - 读取 `FlowRegistry` + `agent_ability.yaml` + active Agent YAML；
   - 接口：`allowed_flow_ids()`、`role_agent_map()`、`consultation_agents()`、`worker_profile(identity)`、`agent_for_flow(flow_id)`。
2. Bridge `config.py`：
   - 删除硬编码 `ROLE_AGENT_MAP`；
   - `allowed_flow_ids` 从 CygnusX 拉取（启动时缓存，支持热重载）；
   - `role_agent_mapping()` 调用 Registry。
3. `worker/production_runner.py`：`_AGENT_PROFILES` 运行时从 Registry 加载。
4. `agent_consultation_service.py`：删除 `ALLOWED_CONSULTATION_AGENTS`，校验 active Agent 的 `internal_case_role`。
5. `case_room_projector.py`：`ROLE_AGENT_MAP` / `ROLE_LABELS` 动态化。
6. `agentteams_case_tool_service.py`：白名单扩展为 Registry 的所有 flow；建单时做 flow 兼容性预检。
7. 给 Agent YAML 补 `internal_case_role`：rnaseq、atacseq、scrna、code、viz、delivery、data（qc 已有）。

---

### 阶段 P1（P0 全部验证通过后才开始）

按 v2.1 规格 §2 逐项执行：

1. **P1-1 一键建 Case**
2. **P1-2 聊天内进度泳道与更多发言**
3. **P1-3 实时性：SSE 重连 + 5s 轮询**
4. **P1-4 统一审批与拒绝理由**
5. **P1-5 交付可下载**
6. **P1-6 专家视觉身份本地化**
7. **P1-7 会诊质量遥测**

---

### 阶段 P2（P0+P1 验收通过后才开始）

1. **P2-1 Bridge → CygnusX 事件推送**：SSE 长连 + 断线游标重放。
2. **P2-2 approval_pending 超时提醒**：24h 提醒，7 天自动取消。
3. **P2-3 acceptance 残留治理**：reconcile 增加 `received` 态推进臂。
4. **P2-4 plan diff / partial replay**。
5. **P2-5 agent-to-agent remediation 闭环**。

---

### 阶段 G（通用化收敛，可与 P2 部分并行）

1. 验证：新增 `data/ai/flows/test_general.yaml`（不改代码）→ Case 创建成功。
2. 新增 ATAC-seq flow YAML 示例，验证规范流程可扩展。
3. 新增 sales_report / treeplot 通用任务 flow YAML 示例，验证 workspace_execution 可扩展。

---

## 硬性约束（违反任何一条视为返工）

1. **业务智能不进 Bridge/Gateway/Worker**：解读、质控判断、规划等 LLM 逻辑只许写在 CygnusX 侧（consultation 服务 + `data/ai/*.yaml` 提示词）。Bridge 只做状态机/租约/审批/审计。
2. **改动服务后必须重启才生效**：后端代码 → `docker restart cygnusx-web`；Celery 任务/投影/watch → `docker restart cygnusx-worker`。
3. **安全红线**：
   - consultation 只读回合必须 `safe_only=True`；
   - `task_file_preview` 必须做路径校验，禁止 `..`、符号链接、任务目录外文件；
   - workspace_execution 必须 plan_hash 绑定 + 工作目录限定；
   - analysis-worker 维持无大脑机械提交，不得给它接 LLM。
4. **flow_id 用下划线**（如 `rna_seq`），正则不允许连字符。
5. 前端改动遵循既有组件契约：不新造 SSE 事件类型，复用 `room_speech / overdrive_progress / overdrive_approval_request`。
6. 不改与规格无关的代码；发现规格文档与代码现状冲突时，停下来在交付报告中列出，不要自作主张改设计。

---

## 每项完成后的验证动作（缺一不可）

1. 该项规格"验证"小节的所有命令/断言全部通过；
2. 回归：`deploy/agentteams/tests/`、`integrations/agentteams/**/tests/`、`tests/unit/` 全绿；
3. 涉及前端：`cd frontend && npx vue-tsc -b && npx vite build`；
4. 运行时冒烟（重启对应容器后实测该项的端到端行为，附命令与输出摘要）；
5. 把 v2.1 规格 §6 对应行的 ⬜ 改为 ✅ 并填验证日期。

---

## 交付格式

- 每个施工项一个独立 commit，消息格式：
  - `feat(agentteams): P0-2 任务看门狗与 stale task 重投`
  - `feat(agentteams): P0-3 只读数据访问工具包 + 硬规则 QC 门`
  - `feat(agentteams): P0-G 动态流程/角色/Agent 发现`
  - 依此类推。
- 逐条列出改动文件。
- 最终交付报告包含：
  - 每项的验证证据（命令 + 关键输出）；
  - v2.1 规格 §6 清单更新后的表格 diff；
  - 未解决问题/与规格冲突点清单（如有）。
- P0 全部完成后输出一次"RNA-seq Case + treeplot Case + 新增测试 flow Case"三合一验收实录。

---

## 开工指令

从 **P0-G** 开始（通用化底座）。先输出你对 v2.1 规格 §1 P0-G 的理解与改动文件清单（不超过 15 行），确认无误后直接施工。

为什么从 P0-G 开始：P0-3 的只读工具需要知道允许哪些 Agent，P0-4 的 workspace_execution 需要知道 `agent-code` / `agent-viz` 的 `internal_case_role`，这些依赖通用化 Registry。Registry 搭好后，后续 P0 项才能干净落地。
