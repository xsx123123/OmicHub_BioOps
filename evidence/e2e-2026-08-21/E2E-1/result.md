# E2E-1 全链路 —— 红（断在 preflight 派单，BUG-E2E-03）

## 验收口径（任务书 2.2）

> scrna 需求：发言→路由→澄清→立项→审批→plan-01→worker 执行；
> 期望事件序列完整、Case 状态机迁移正确；证据：审计链导出。

## 实测路径（旧入口 POST /api/v1/agent-teams/cases）

> 注：房间入口（发言→立项）被 BUG-E2E-01/02 阻断（见 env/），本条用旧路径建 Case，
> 需求文本：小鼠肺部 6 个 scRNA-seq 样本（3 tp53 mutation vs 3 WT）标准流程全套。
> Case：`bioops_20272b2afce74d728ebe0e204bece70c`，审计链导出 118 事件
> （`case_events_export.json`，平台端点翻页全量拉取）。

### 走通的阶段（绿的部分）

- 18:29:04Z `case.created` → `case.handoff_proposed`（flow_id=scrna_seq，lead_planner=agent-scrna）→ `planning_running`。
- 规划阶段真实 LLM 执行：plan-01（skill=planning_advice，target=agent-scrna）4 轮 claimed→running→finished，
  17 次 `agent.tool_call`（rule_threshold_lookup / workspace_file_preview 等真实工具调用）。
- **计划校验自愈回路真实触发**：`consultation.parse_failed` → 3 轮
  `correction_started`/`correction_applied`（missing_fields: proposed_submission → [] → sample_sheet.sample），
  第 4 轮通过 → 18:32:40Z `planning.frozen`（plan_hash=a951c4e8…，quality_gate_required=true）。
  状态机迁移 received→planning_running→preflight_running 全部正确。
- 顺带观察：`flow.stage_unavailable` ×3（upstream/integrate/advanced 阶段暂不可用，属显式降级事件，非静默）。

### 断点（红的部分）

- 18:32:40Z `work_item.assigned` 派出 `preflight-01`（target=`data-steward`，skill=`project-preflight`）后
  **再无事件**。轮询 15 分钟状态恒为 `preflight_running`（`poll_status.log`）。
- 根因 = **BUG-E2E-03**：preflight 工作项 target 硬编码 `data-steward`，bridge inbox 精确匹配，
  生产 worker 池以 `agent-data` 身份轮询，无人能领。实测同 token 下 agent-data 收件箱 0 条、
  data-steward 收件箱 1 条（见 `../env/BUG-03-preflight-target-mismatch.md`）。
- 因此审批（approval_pending）→ 执行 → 交付未到达。即使到达执行，输入文件名为伪造，
  预期执行失败——但本次连该断点都未走到。

## 结论

🟥 红。前半链路（建 Case→路由→规划→校验自愈→冻结）事件序列完整正确；
断在 preflight 派单层（BUG-E2E-03）。主干修复 BUG-03（及 BUG-01/02 解锁房间入口）后重跑。
