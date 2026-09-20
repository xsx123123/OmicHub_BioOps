# AgentTeams 多 Agent 协同优化框架 v2.1（真干活 + 通用化专项，已归档）

> 文档性质：在 v1（`data/ai/AgentTeams_update.md`，编排骨架已验收）与 v2（交互体验与"真干活"优化）之上的**实效与通用化增强规格**。  
> 审核日期：2026-08-11。  
> 问题动机："生成一系列的东西没有干啥子活"、"交互体验不好"、"不能只限于 RNA-seq，要能跑其他任务、也能跑通用任务"。  
> 本文与 v1/v2 的关系：**v1 是权威施工基线**（状态机/租约/审批/审计/投影/§8 施工清单/§10 验收清单）；本文保留 v1 全部原则，在其上补充 v2/v2.1 的优化项、通用化改造与最终验收结果。当本文与 v1 冲突时以本文为准；本文未覆盖的细节回查 v1。  
> 顺序：P0 → P1 → P2 → G（通用化收敛）。

---

## 0. 生产实证审核结论（2026-08-11）

**总结论：v1 的骨架是对的，但"骨架会动、肌肉没有"——历史上 9 个真实 Case 无一到达 `closed`；会诊专家没有读取真实数据的工具（R2）；运行时又被 RNA-seq/scRNA-seq 的硬编码身份/流程白名单绑死（R6）。**

### 0.1 生产 Case 全量清单

| Case | 状态 | 卡死/失败原因 |
|---|---|---|
| bioops_e586… / bioops_7850… | `approval_pending` | 用户从未批准，悬置 11 天 |
| bioops_ed00… | `executing` | 任务 queued 10 天未消费，无看门狗 |
| bioops_e94f… | `execution_failed` | snakemake `--logger rich_loguru` 被拒绝（R1，已修） |
| agentteams-acceptance ×2 | `received` | 验收脚本残留 |

### 0.2 根因分级

| # | 根因 | 证据 | 后果 |
|---|---|---|---|
| R1 | 执行层断裂：snakemake logger 参数被拒 | `core/config.py:273`；`docker-compose.worker.yml:45,105` | 流水线提交即败 |
| R2 | 会诊"无手"：`evidence_refs` 只是 prompt 字符串 | `agent_consultation_service.py:172`；`parallel_subagent_service.py:398-404` | 专家空对空发言 |
| R3 | 通用型 Case 名存实亡：workspace 工单无人认领 | `integrations/agentteams/worker/*.py` | treeplot 跑不起来 |
| R4 | 静默失败：异常被 `try/except` 吞掉 | `agentteams_case_watch_service.py:73-76,101-104,140-142` | 用户不知原因 |
| R5 | 交互断点 | 前端核查 | 体验差 |
| R6 | 运行时硬编码绑定 RNA-seq/scRNA-seq | `bridge/config.py:8,38`；`worker/production_runner.py:30` 等 | 无法扩展新流程 |

---

## 1. P0 — 让 Case 真干活（执行层、会诊层、通用化基础）

> 执行纪律：业务智能只写在 CygnusX 侧；Bridge/Gateway/Worker 只做编排。每完成一项跑回归测试并重启对应容器。

### P0-1 ✅ snakemake logger 参数修复（R1，2026-08-11 已完成）

- `src/cygnusx/core/config.py`：`rich_loguru` → `rich-loguru`。
- `deploy/docker/docker-compose.worker.yml`：同步 env。
- `src/cygnusx/infrastructure/execution/local.py`：守卫放宽为 `{"rich_loguru", "rich-loguru"}`。
- 验证：容器内 `snakemake --logger rich-loguru --dry-run` 通过。

### P0-2 任务看门狗（R1）

**施工**：
1. Bridge `service.py:reconcile_case` 增加超时臂：
   - `queued` 超过 900s → 审计 `omic_task.stalled` → 复核 → 仍 queued 则转 `execution_failed`。
   - `failed` 时把 `error_message` 尾部 500 字符写入审计 `omic_task.failed.payload.error_excerpt`。
2. CygnusX 侧新增 Celery beat `requeue_stale_tasks`（300s）：扫描 queued >10min 且无 `started_at` 的任务，重投一次；仍静止则标记 failed。
3. 存量清理：`f85c814d…` 手动标记 failed。

**验证**：停 Worker 提交任务 → 10min 内 Case 进入 `execution_failed` 且聊天可见原因。

### P0-3 会诊长"手" + 硬规则门（R2）

**问题**：`evidence_refs` 只是字符串，专家看不见真实数据。

**施工**：
1. CygnusX 新增只读工具（`tool_configs/tools_schema.yaml`，`read_only_hint: true`）：
   - `task_result_summary(task_id)`：状态、flow、参数快照、产物清单、QC metrics、错误摘录。
   - `task_file_preview(task_id, path, max_bytes=20000)`：文本产物头部，禁止路径穿越。
   - `workspace_file_preview(path, max_bytes=20000)`：工作区文件预览，按 `requester_ref` 隔离。
   - `task_compare_metrics(task_ids, fields)`：跨任务 metrics 对比。
   - `rule_threshold_lookup(flow_id, metric_name)`：查询 flow 阈值。
2. 新增硬规则 QC 门 `agentteams_quality_gate_service.py`：
   - `mapping_rate < threshold` → `BLOCKED`。
   - `q30 < threshold` → `BLOCKED`。
   - `duplicate_rate > threshold` → `WARNING`。
   - 结论写入审计 `quality.hard_gate`；LLM 质控只负责综合判断。
3. `agent_consultation_service.py` prompt 升级：明确要求"凡引用 task:/file: 必须先调用工具读取"。
4. `agent-qc` 提示词契约（`data/ai/qc.yaml`）：三态结论必须引用 metrics 字段名与数值。

**验证**：mapping_rate 30% 的任务自动 BLOCKED；RNA-seq 解读信封的 `evidence_refs` 含具体 metrics。

### P0-4 workspace_execution 的 Worker 认领实现（R3）

**施工**：
1. Bridge `service.py` 规划阶段对 `agent-code` / `agent-viz` 工单设 `execution_mode=workspace_execution`。
2. `worker/production_runner.py` 透传 `execution_mode`，结果 `artifacts` 回写 work item。
3. 新增 `data/ai/flows/treeplot.yaml` 标本：
   ```yaml
   flow:
     id: treeplot
     bridge_workflow: treeplot
     actor: agent-viz
   stages:
     - key: plot
       executors:
         - key: phylogenetic_tree
           execution_mode: workspace_execution
           queue: general_analysis
           inputs: [sequences]
           outputs: [tree_pdf, tree_png]
   ```
4. `agent-viz.yaml` 增加 `internal_case_role: agent-viz`。

**验证**：treeplot Case 端到端通过，/files 可见产物。

### P0-5 失败诊断与恢复回路（R4）

**施工**：
1. `case_room_projector.py` 增加 `omic_task.failed` / `case.execution_failed` 发言模板（含 `error_excerpt` + 建议）。
2. Bridge `service.py` 新增 `retry_case_submission`，幂等键升版 `submit-v{n+1}`；暴露 `POST /v1/cases/{id}/retry`。
3. `agentteams_case_watch_service.py` 连续 3 次拉取失败时投影同步异常提示。

**验证**：构造必败任务 → 聊天内可见失败原因 + 重试按钮；重试后幂等键升版。

### P0-G 通用化基础：动态流程/角色/Agent 发现（R6）

**设计**：FlowRegistry 描述"有什么流程"，Agent 能力目录描述"谁有能力"，AgentTeams 运行时只负责"按定义路由"。

**施工**：
1. 新增 `AgentTeamsCapabilityRegistry`：
   - 读取 `FlowRegistry` + `agent_ability.yaml` + active Agent YAML。
   - 提供 `allowed_flow_ids()`、`role_agent_map()`、`consultation_agents()`、`worker_profile()`、`agent_for_flow()`。
2. Bridge `config.py`：删除硬编码 `ROLE_AGENT_MAP`；`allowed_flow_ids` 从 CygnusX 拉取；`role_agent_mapping()` 调用 Registry。
3. `worker/production_runner.py`：`_AGENT_PROFILES` 运行时从 Registry 加载。
4. `agent_consultation_service.py`：删除 `ALLOWED_CONSULTATION_AGENTS`，校验 active Agent 的 `internal_case_role`。
5. `case_room_projector.py`：`ROLE_AGENT_MAP` / `ROLE_LABELS` 动态化。
6. `agentteams_case_tool_service.py`：白名单扩展为 Registry 的所有 flow；建单时做 flow 兼容性预检。
7. 给 Agent YAML 补 `internal_case_role`：rnaseq、atacseq、scrna、code、viz、delivery、data；qc 已有。

**验证**：新增 `data/ai/flows/test_general.yaml`（不改代码）→ Case 创建成功、角色映射正确。

---

## 2. P1 — 交互体验闭环

### P1-1 一键建 Case（R5）

**施工**：
1. 信息足够时后端直接弹确认卡，用户点击后前端直接调 `POST /api/v1/agent-teams/cases`，绕过第二次 LLM。
2. 输入框"..."菜单改为结构化建单弹窗。
3. 会诊卡"基于此创建协作 Case"按钮直接建单。

**验证**：点击到 `received` ≤ 1 次确认 + 1 次 API 调用。

### P1-2 聊天内进度泳道与更多发言（R5）

**施工**：
1. `case_room_projector.py` 补模板：`work_item.claimed`、`omic_task.submitted`、`omic_task.progress`、`remediation_pending`、`delivery_ready`、`quality.hard_gate`。
2. `work_item.*` 投影 `overdrive_progress` 带任务栅格。
3. `AgentTeamsCaseCard.vue` 增加最近 3 条事件摘要。

**验证**：完整 Case 聊天内 ≥8 条进展，无 ≥60s 死寂。

### P1-3 实时性：SSE 重连 + 推送替代轮询（R5）

**施工**：
1. `agentHub.ts:startAgentTeamsCaseEvents` 补指数退避重连 + 游标重放。
2. watch 间隔 15s → 5s。

**验证**：断网 30s 恢复后续传不丢；状态翻转 ≤6s 可见。

### P1-4 统一审批与拒绝理由（R5）

**施工**：
1. `AgentTeamsCaseCard` 拒绝按钮弹出理由输入框，理由进审计。
2. 审批卡展示 `plan_hash` 短码 + 参数明细折叠区。
3. 视觉与 `OverdriveApprovalCard` 对齐。

### P1-5 交付可下载（R5）

**施工**：
1. `delivery-01` 信封扩展 `artifacts`。
2. 投影器把 artifacts 投影为超频同款产物区。
3. manifest 文本改为下载按钮 + JSON 折叠预览。
4. `omic_task_ids` 渲染为任务详情页链接。

**验证**：Case 关闭后 1 次点击下载交付文件。

### P1-6 专家视觉身份本地化（R5）

**施工**：前端 `roleIdentity.ts` 静态映射，后端字段缺失时兜底；角色展示从 Agent YAML 动态读取。

### P1-7 会诊质量遥测

**施工**：记录 envelope 解析成功率、工具调用次数、evidence 引用命中率、QC 与硬规则门一致性；进管理端面板。

**验证**：10 个 Case 后引用命中率 ≥80%。

---

## 3. P2 — 架构收敛与健壮性

1. **Bridge → CygnusX 事件推送**：SSE 长连 + 断线游标重放，watch 降为 60s 兜底。
2. **approval_pending 超时提醒**：24h 提醒，7 天自动取消。
3. **acceptance 残留治理**：reconcile 增加 `received` 态推进臂。
4. **plan diff / partial replay**：用户可修改白名单参数，生成新 `plan_hash`，只重跑改动部分。
5. **agent-to-agent remediation 闭环**：QC 生成 `remediation_request`，Manager 派给 data-steward/workflow-operator，修改后重走审批/执行/质控。

---

## 4. G — 通用化落地

> 目标：规范流程（RNA-seq / ATAC-seq / scRNA-seq）与通用任务（代码/可视化/数据清洗）共存，新增 flow/Agent 不改动 AgentTeams 运行时代码。

### 4.1 三种执行模式

| 模式 | 场景 | 执行者 | 产物登记 |
|---|---|---|---|
| `pipeline_execution` | RNA-seq、ATAC-seq、scRNA-seq | `workflow-operator` / `analysis-worker` | pipeline 自动产出 |
| `workspace_execution` | treeplot、自定义可视化、数据清洗 | `agent-code` / `agent-viz` | `_register_workspace_artifacts` |
| `readonly_consultation` | 质控、解读、交付审查 | 任意会诊 Agent | 只出信封 |

### 4.2 规范流程新增示例：ATAC-seq

```yaml
flow:
  id: atacseq
  bridge_workflow: atac_seq
  actor: agent-atacseq
  runtime_image: atacseq
artifacts:
  - {key: fastq_manifest, type: json_manifest}
  - {key: peaks, type: bed}
  - {key: bigwig, type: bigwig}
  - {key: qc_report, type: review_report}
stages:
  - key: atacflow
    executors:
      - key: atacflow
        queue: atacseq_analysis
        inputs: [fastq_manifest]
        outputs: [peaks, bigwig, qc_report]
    review:
      skill: atacseq-qc-review
      inputs: [qc_report, peaks]
      output: qc_review
    gate: {template: annotation_revision, required: true}
```

重启 Bridge 即可支持，无需改 AgentTeams 代码。

### 4.3 通用任务新增示例：销售报表清洗

```yaml
flow:
  id: sales_report
  bridge_workflow: sales_report
  actor: agent-code
stages:
  - key: transform
    executors:
      - key: pandas_clean
        execution_mode: workspace_execution
        queue: general_analysis
        inputs: [raw_csv]
        outputs: [clean_csv, report]
```

### 4.4 兜底策略

- `actor` 未找到 → fallback 到 `agent-general` / `agent-omics`，记录 `actor_fallback`。
- Agent 缺少 `internal_case_role` → warn，不参与 AgentTeams。
- flow 无 stages/executors → `BusinessError("流程定义不完整")`。

---

## 5. 与 v1 / v2 / §17 的关系

- v1 原则全部保留：角色→平台 Agent 映射、只读执行边界、单窗口投影、业务智能不进 Bridge。
- v2 补两块："只读≠无数据"、"审计可追溯≠用户看得懂"。
- v2.1 再补三块：硬规则门 + LLM 质控双轨制、运行时通用化、规范流程与通用任务共存。

---

## 6. v2.1 验收标准与最终结果

### 6.1 真闭环（规范流程）

⬜ 新建 RNA-seq Case，从建单到 `closed` 无人工兜底，snakemake returncode=0，聊天内可下载交付文件。  
验证方式：端到端录屏 + 审计事件导出。

### 6.2 真质控

⬜ 硬规则门：mapping_rate 30% 自动 BLOCKED。  
⬜ LLM 质控：agent-qc PASSED 结论每个关键数值可回溯 metrics。  
⬜ 引用命中率 ≥80%。

### 6.3 真体验

⬜ 建单 ≤1 次确认。  
⬜ 聊天进展无 ≥60s 死寂。  
⬜ 失败时可见原因摘录 + 重试按钮。  
⬜ 断网恢复后续传不丢。  
⬜ 审批卡展示 plan_hash + 参数明细 + 可编辑拒绝理由。

### 6.4 零悬置

⬜ queued >10min 有解释。  
⬜ approval_pending >24h 有提醒。  
⬜ executing 有看门狗。

### 6.5 通用型落地

⬜ treeplot 迷你 Case 端到端通过（/files 可见产物）。  
⬜ 新增测试 flow（如 chipseq / sales_report）不改 AgentTeams 代码即可创建执行。

### 6.6 运行时通用化

⬜ 新增/停用 Agent 或 flow 无需重启运行时可识别。  
⬜ `ROLE_AGENT_MAP` / `ALLOWED_CONSULTATION_AGENTS` / `_AGENT_PROFILES` 三处硬编码消除。

---

## 7. 施工顺序与验证纪律

- P0-1 已完成。其余严格 P0 → P1 → P2 → G。
- 每完成一项：Bridge/Gateway/Worker 契约测试 + CygnusX 单测回归；后端 `docker restart cygnusx-web`；Celery `docker restart cygnusx-worker`。
- 业务智能只写在 CygnusX 侧；Bridge/Gateway/Worker 只做编排、搬运与审计。
- 新增 flow/Agent 必须至少通过一个端到端 Case，且不破坏 RNA-seq / scRNA-seq Case。

---

## 8. 附录：关键契约

### 8.1 硬规则门审计事件

```json
{
  "event_type": "quality.hard_gate",
  "decision": "BLOCKED",
  "reason": "mapping_rate 30.0% 低于阈值 70.0%",
  "metric": "mapping_rate",
  "value": 30.0,
  "threshold": 70.0
}
```

### 8.2 Agent YAML 新增字段

```yaml
features:
  internal_case_role: agent-atacseq
  subagents_spawnable: true
  capability_scope: [Bulk ATAC-seq, QC, peak calling]
```

### 8.3 flow YAML execution_mode

```yaml
stages:
  - key: plot
    executors:
      - key: phylogenetic_tree
        execution_mode: workspace_execution
        inputs: [sequences]
        outputs: [tree_pdf]
```
