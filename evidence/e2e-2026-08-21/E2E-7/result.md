# E2E-7「hi 不建 Case」结果：绿（含一条观察项）

- 房间：e2e-20260821-hi-test / 2b4d50d55bc7449d912ab13cc80ca54a（经 BUG-E2E-01 绕过方式创建）
- 发言 "hi" → POST /rooms/{id}/messages 201，dispatch_mode=manager，response_dispatch=queued
- 事件流（room_events.json，70 条）：room.namespace_created / room.created / room.user_message /
  room.agent_stream ×65（流式分片）/ room.ask_user ×1 / room.response_timing ×1
- 断言：
  - ✅ 无 Case 创建事件；room.case_id = null（room_detail.json 与 PG 行双重确认）
  - ✅ 无立项卡：proposal IS NULL，has_pending_proposal=false
  - ✅ 仅一条 Manager 回复（room.ask_user 一条，LLM 真实响应，response_timing llm=9576ms）
  - ✅ 无进度条类事件（无 case.* 执行事件）
- 观察项（留人工裁定，非红）：Manager 回复以 room.ask_user（含 questions 选项按钮）
  形式落地，而非纯文本气泡；任务书期望「仅一条 Manager 对话回复」，本条回复确为一条、
  内容是对话式，但形态是带选项的澄清卡。另回复文案提到「当前 Case 处于已接收状态」，
  但此时无 Case，措辞不准确。
