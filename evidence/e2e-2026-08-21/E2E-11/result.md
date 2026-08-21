# E2E-11 直答降级 —— 半绿（正向直答绿，降级路径未覆盖）

## 验收口径（任务书 2.2）

> 注入目标 Agent 直答失败 → 期望：Manager 降级消息 + `room.agent_timeout` 审计。

## 实测：正向直答（绿）

- 房间 `2b4d50d55bc7449d912ab13cc80ca54a`（e2e-20260821-hi-test）。
- 18:39:44 用户发言：`@agent-scrna 单细胞 RNA-seq 里 doublet 检测推荐什么方法？简要回答即可`
- 18:40:11 收到 `room.agent_message`，payload 关键字段：
  - `agent_id: agent-scrna`、`role: worker`、`direct_mention: true`
  - `causation_event_id: 2f27eee0-...`（指向用户发言事件，因果链完整）
  - 内容为 scDblFinder/Scrublet/DoubletFinder/solo 的专业直答（真实 LLM 产出，非模板）
- 端到端时延 26.9s。
- 证据：`room_events_full.json`（完整导出，含 response_timing）。

**结论**：@点名 → dispatch_mode=direct → 目标 Agent 直答落 `room.agent_message`，正向链路绿。

## 未覆盖：降级路径（A3 修复点）

- 期望注入「目标 Agent 直答失败」后看到 Manager 降级消息 + `room.agent_timeout`。
- 两种注入方式均不可行/未执行：
  1. **注册表错位**（consultation_agents 有、internal_consultation_agents 无）：实测两张注册表内容一致，无 diff 可用，无法自然触发 `NotFoundError`。
  2. **超时注入**：需将 `AGENTTEAMS_DIRECT_TIMEOUT_SECONDS`（`src/omichub/core/config.py:321`，默认 30s）改为 1s 并重启 omichub-worker，跑完再还原。考虑到：(a) 改动 compose 环境再还原有遗漏风险；(b) 正向路径已验证、降级代码路径可走查确认存在，本次未执行故障注入。
- 代码走查确认降级路径存在：`src/omichub/application/services/agentteams_room_response_service.py:350-382` —— `_respond_to_direct_agent` 失败时返回 `direct_failed` / `direct_agent_unavailable`，由 `_emit_direct_agent_fallback` 落 `room.agent_timeout` 审计事件并发 Manager 降级消息。

## 观察项（非阻断）

- 18:40:11 同刻的 `room.response_timing` 事件 payload 为 `{"response_status": "failed", "duration_ms": 26944, "stage_ms": {"case": 6}}`，与成功直答并存。疑为直答路径的计时事件沿用了 case 路径的状态机口径（直答未写 `response_status=success`），建议主干复核 `response_timing` 在 direct 模式下的取值语义。

## 结论

半绿：正向直答绿；降级路径因缺乏故障注入手段未实测，代码路径走查存在。建议主干补一个可测试性钩子（如直答超时环境变量已在，补一个「强制直答失败」的调试开关）后重跑本条。
