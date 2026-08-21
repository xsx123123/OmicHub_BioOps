# E2E-4 规划失败显式化 —— 未实测（故障注入未执行），代码走查有佐证 + 口径偏差

## 验收口径（任务书 2.2）

> 注入 Bridge 故障 → 期望：`planning_failed` 事件 + 前端可见提示，不停在 received；证据：事件流+截图。

## 本次覆盖情况

- **未实测**：注入 Bridge 故障需停/改 bridge 容器，而验收窗口内 E2E-1 全链路 Case 正在 bridge 上跑 preflight（真实 LLM + 工具调用），停 bridge 会污染在跑用例；按「不新开大型用例、不扩大爆炸半径」原则未执行注入。
- **代码走查佐证（错误不会静默停在 received）**：
  - Bridge 侧计划校验失败有自愈回路：`integrations/agentteams/bridge/omichub_agentteams_bridge/service.py:1644 _handle_plan_validation_failure` —— 3 次内 `correction_started`/`correction_applied` 反馈 Planner 重试，超限后状态迁移 `planning_running → waiting_for_correction` 并落 `correction_failed` + `planning.validation_failed`（`retry_exhausted: true`）审计事件。
  - 执行层失败有 `case.execution_failed` 事件与 `execution_failed` 状态（service.py:610/625）。
- **口径偏差（需主干确认）**：bridge 状态机（`case_store.py:53-58`）**不存在 `planning_failed` 状态/事件**，任务书期望的事件名与实际实现的 `planning.validation_failed` / `correction_failed` / `waiting_for_correction` 不一致。前端是否有对应可见提示无法在本 headless 环境验证。

## 结论

未覆盖（故障注入未执行）。代码路径表明规划失败不会停在 received，但事件命名与任务书口径不符，建议主干 hotfix 时统一口径后重跑本条。
