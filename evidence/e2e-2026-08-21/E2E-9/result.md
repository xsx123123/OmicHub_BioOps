# E2E-9 游标分页结果：红（终止性缺陷）；不重不漏子项绿

环境：reload 后新栈（web/bridge build_sha=4680155，2026-08-21 02:1x +0800）。
房间：e2e-20260821-pagination（7281bc13b11940a3a8abd0f4cfd0542f），
Bridge 事实源（MinIO cases/room-7281.../events/audit.jsonl）= 20 条持久事件。

## 断言结果
- ✅ 不重不漏：limit=7 翻页 7+7+6=20 条，与 Bridge 持久流计数一致，event_id 零重复
  （pagination_trace_round2.json）。
- 🟥 **分页不终止**：第 2 页（最后一页，6 条）之后 next_cursor 仍非空；
  第 3~11 页连续返回「0 条事件 + next_cursor 非空」，游标永不清空（死循环）。
  调用方无法判断事件流已结束。对应任务书"回查复审 A2 修复"——A2 修复在终止条件上仍有缺口。
- ⬜ 与 audit-chain 顺序一致性：需房间立项出 Case 后比对（立项入口被澄清单拦截 +
  BUG-E2E-01 影响，见 E2E-10）；本条子项未覆盖。

## 附带发现（设计行为，非 bug）
- room.agent_stream 打字机增量为**瞬态事件**（bridge audit.py STREAM_EVENT_TYPES：
  只写 Redis 热缓存/内存索引，不写 MinIO）。Bridge 重建后 247 条 stream 增量消失、
  20 条持久事件完整恢复——设计如此，但任务书/审计口径若要求"事件完整"需知会这一点。
- reload 前首轮探测（260 条含瞬态）同样观察到空页 next_cursor 现象
  （pagination_probe_round1.md），复验后定论。

## 修复方向
get_room_events 在「本页事件数 < limit 且两源流均耗尽」时应返回 next_cursor=null；
当前实现疑似只按 namespace 流位置推进游标而不判空。
