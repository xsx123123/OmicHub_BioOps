# E2E-6 气泡可见 —— 未覆盖（前端渲染层），落库侧有佐证

## 验收口径（任务书 2.2）

> 发送→落库→渲染；期望：气泡可见且 event_id 对账替换正确；证据：截图+事件。

## 本次覆盖情况

- **未覆盖渲染层**：本环境为 headless 服务器，无浏览器可做前端截图与气泡渲染验证（任务书允许的记录方式：注明未覆盖+原因）。
- **落库 + event_id 对账侧佐证（绿）**：
  - E2E-7 / E2E-11 的房间事件导出（`../E2E-7/room_events.json`、`../E2E-11/room_events_full.json`）显示：用户发言落 `room.user_message`（含 event_id）、Manager/Agent 回复落 `room.ask_user` / `room.agent_message`（含 event_id 与 `causation_event_id` 回链），事件序列完整，可供前端投影层做对账替换。
  - 前端投影/对账逻辑已有单元测试覆盖：`frontend/src/views/__tests__/agent-teams-room-send.test.ts`（`postCaseMessage`/`postRoomMessage` 返回 `event_id: 'evt-user-1'` 的替换场景、发送失败恢复草稿、空态建房首发等 10+ 用例），`frontend/src/utils/__tests__/agentTeamsRoom.spec.ts` / `agentTeamsState.spec.ts` 覆盖事件流状态归并。

## 结论

未覆盖（渲染截图）。落库与 event_id 对账所需的后端事件形态经真实服务验证存在，前端替换逻辑有单测覆盖。建议平台方在合入后按任务书 Part 3.2 手测清单补前端截图。
