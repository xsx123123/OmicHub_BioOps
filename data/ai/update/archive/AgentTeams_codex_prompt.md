# Codex 施工提示词：AgentTeams 多 Agent 协同闭环实现（已归档）

> 用法：把本文件全文作为提示词发给 Codex（或等价编码 agent），在仓库根目录执行。
> 唯一权威施工规格是 `data/ai/AgentTeams_update.md`（下称"规格文档"），本提示词不替代它，
> 只定义执行纪律、顺序与交付格式。规格文档与本提示词冲突时，以规格文档为准。

---

## 角色与上下文

你是 OmicHub 仓库的高级全栈工程师。OmicHub 是生信分析平台（FastAPI + Celery + Vue3），
仓库内嵌 AgentTeams 协同栈（`integrations/agentteams/`：Bridge / Gateway / Worker 三个
Python 子项目 + `deploy/agentteams/` 部署目录）。比赛要求以 AgentTeams 为多 Agent 协同基点，
当前编排骨架已完成（状态机/租约/审批/审计/投影，已审核通过），缺的是**执行内核**。

开工前必读（按序）：

1. `data/ai/AgentTeams_update.md` 全文——§0 审核结论、§2 两层模型、§3 任务拆解（含 §3.3
   规划阶段、§3.4 通用分析型任务）、§8 施工清单、§10 最终审核清单；
2. `data/ai/update_agent.md` 仅 §1、§2.3、§12——明确**赛后目标边界，本任务不做**；
3. 规格文档 §8 每个施工项里点名的源文件，动手前先读一遍现状代码。

## 施工范围（严格按此顺序，逐项完成并验证后再做下一项）

### 阶段 P0（闭环必需，顺序执行）

1. **P0-1 consultation 端点**（规格 §8 P0-1）：
   - 新建 `src/omichub/application/services/agent_consultation_service.py`，复用
     `AgentService.assemble_context`（`agent_service.py:758-969`）+
     `ParallelSubAgentService`（`parallel_subagent_service.py:161`，`safe_only=True`、
     `workspace_access=False`、`runtime_authorized=True`、单 task）；
   - `src/omichub/api/v1/agentteams.py` 加 `POST /consultations/scientific-interpretation`，
     集成令牌认证（`X-Integration-Token` + `hmac.compare_digest`，Settings 裸名
     `AGENTTEAMS_INTEGRATION_TOKEN`，**无 env_prefix**），不得用 `CurrentUserId`；
   - Bridge/Gateway/Worker 三处透传 `requester_ref`；Bridge `config.py` 加权威
     `ROLE_AGENT_MAP`（值见规格 §2.1 表）；`execute_readonly_work_item` actor 白名单
     加入 `data-steward / quality-auditor / delivery-reporter`；
   - Gateway `agent_policies` 补 `agent-data/qc/delivery`；`gateway.env` 加集成令牌；
   - 信封 `{conclusion, recommendations, evidence_refs, risks, token_usage}` 解析失败时
     降级 `conclusion=原文` + risks 记一条，禁止抛 500。
2. **P0-2 修正前端 ROLE_AGENT_MAP**（规格 §8 P0-2）：`case_room_projector.py:7-16`。
3. **P0-3 身份配置 + data-steward 容器**（规格 §8 P0-3）：teams yaml 补 agent-rnaseq、
   bridge.env(.example) 补 2 个令牌占位、compose 加 `agentteams-worker-data-production`、
   `production_runner.py:_AGENT_PROFILES` 扩 3 个 profile。**禁止提交真实令牌值**。
4. **P0-4 reconcile_case 派解读工单**（规格 §8 P0-4）。
5. **P0-4b 规划工单 plan-01**（规格 §8 P0-4b）：状态机加 `planning_running`、
   `proposed_submission` + `plan_hash` 冻结绑定、无 plan_hash 不得进 approval_pending。
6. **P0-5 质控/交付接真 Agent**（规格 §8 P0-5）：quality_runner 三态映射 +
   manual_review 兜底（禁止静默放行）；delivery_runner 产交付清单；`data/ai/qc.yaml`
   提示词补三态首行契约。
7. **P0-6 通用工作区执行通道**（规格 §8 P0-6）：`execution_mode` 字段与分发、
   plan 绑定校验、工作目录限定 `output/agentteams/<case_id>/<work_item_id>/`、
   产物登记 `file_records`、Gateway 为 agent-code/viz 加 `workspace_execution` capability。

### 阶段 P1（P0 全部验证通过后才开始）

P1-6 聊天内审批卡（首选方案：AgentTeamsCaseCard 加批准/拒绝按钮直连
`POST /cases/{id}/submit`）、P1-7 manifest 下载、P1-8 骨架 Agent 补齐、
P1-9 假创建入口修复（选文案方案 (b)，一行改动）。

### 阶段 P2

仅当 P0+P1 验收通过后，按规格 §8 P2 执行（游标加固、watch 降间隔、Redis 存储、
成本计数、端到端 pytest）。其中涉及 alembic 迁移时注意：**迁移历史存在多 head，
新迁移必须用 mergepoint 合并**，容器内执行 `/app/.venv/bin/alembic`。

## 硬性约束（违反任何一条视为返工）

1. **业务智能不进 Bridge/Gateway/Worker**：解读、质控判断、规划等 LLM 逻辑只许写在
   OmicHub 侧（consultation 服务 + `data/ai/*.yaml` 提示词）。Bridge 只做状态机/租约/
   审批/审计/派单；Worker 保持无 LLM 薄转发。
2. **改动服务后必须重启才生效**：后端代码 → `docker restart omichub-web`；
   Celery 任务/投影/watch → `docker restart omichub-worker`（两个服务均无热重载）。
   验证时必须重启后实测，不得以 py_compile/单测通过代替运行时验证。
3. **不做赛后目标**：`update_agent.md` 的真异步、逐条点评、人格化招募等 P1-P4 内容
   一律不实现、不预留半成品代码。
4. **安全红线**：不提交真实令牌；consultation 只读回合必须 `safe_only=True`；
   workspace_execution 必须 plan_hash 绑定 + 工作目录限定 + 高风险工具审批不豁免；
   analysis-worker 维持无大脑机械提交，不得给它接 LLM。
5. **flow_id 用下划线**（如 `rna_seq`），正则不允许连字符。
6. 前端改动遵循既有组件契约：不新造 SSE 事件类型，复用
   `room_speech / overdrive_progress / overdrive_approval_request`。
7. 不改与规格无关的代码；发现规格文档与代码现状冲突时，停下来在交付报告中列出，
   不要自作主张改设计。

## 每项完成后的验证动作（缺一不可）

1. 该项规格"验证"小节的所有命令/断言全部通过；
2. 回归：`deploy/agentteams/tests/`、`integrations/agentteams/**/tests/`、
   `tests/unit/test_agent_consultation_service.py`（新建）全绿；
3. 涉及前端：`cd frontend && npx vue-tsc -b && npx vite build`（若 vue-tsc -b 报
   "找不到名字"幻影错误，删 `frontend/tsconfig*.tsbuildinfo` 后重跑）；
4. 运行时冒烟（重启对应容器后实测该项的端到端行为，附命令与输出摘要）；
5. 把规格文档 §10 对应行的 ⬜ 改为 ✅ 并填验证日期。

## 交付格式

- 每个施工项一个独立 commit，消息格式：
  `feat(agentteams): P0-1 consultation 端点与集成认证` 之类，逐条列出改动文件；
- 最终交付报告包含：每项的验证证据（命令 + 关键输出）、§10 清单更新后的表格 diff、
  未解决问题/与规格冲突点清单（如有）；
- P0 全部完成后输出一次"5/5 活跃 + RNA-seq Case + treeplot Case"三合一验收实录。

## 开工指令

从 P0-1 开始。先输出你对规格文档 §8 P0-1 的理解与改动文件清单（不超过 15 行），
确认无误后直接施工，逐项推进，不要一次性铺开多项。
