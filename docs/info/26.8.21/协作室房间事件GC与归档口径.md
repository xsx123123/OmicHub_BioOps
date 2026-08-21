# 协作室房间事件 GC 与归档口径（C1 观测项配套）

> 日期：2026-08-21
> 来源：《协作室框架文档v3复审问题清单.md》C1（闲聊数据永久进事实源、无删除通道）。
> 状态：**只定口径，未实施**。本文档落地前不代表任何代码行为已改变；
> 已实施的只有"房间事件量监控指标"（见下文 §3）。

## 1. 背景与现状

- Bridge 房间命名空间事件流（`room-<room_id>`，含全部纯闲聊内容）与 Case 事件
  一样完整 MinIO 持久化（事实源）；房间删除/归档端点不存在（无 DELETE /rooms）。
- 两者叠加 = 闲聊数据不可删除、无限膨胀，占用事实源存储与审计链查询带宽。
- 持久化分级（阶段 0 起）：business 事件进 MinIO；瞬态 `room.agent_stream`
  走 Redis 热缓存 + 内存索引；operational（心跳/轮询/typing）只计数不落盘。

## 2. GC / 归档口径（设计约定，待实施）

**适用范围**：仅房间命名空间流（`room-<room_id>`）；已立项 Case 的事件流
不在本口径内，随 Case 既有生命周期与证据 GC 策略管理。

**归档触发**：未立项房间 **N 天无活动**（建议默认 N=30，以最后一条 business
事件的 `recorded_at` 判定；operational/stream 事件不算活动）可归档。

**归档语义**（归档 ≠ 删除）：
1. 事件流转冷存：MinIO 中该命名空间的事件卷对象迁移/标记到冷存前缀
   （如 `archive/rooms/<room_id>/...`），在线审计链查询不再加载；
2. 房间标只读：主后端 `AgentTeamsRoomModel` 置只读状态，发言入口拒绝并提示
   "房间已归档"；Bridge 侧对只读命名空间的 evidence 写入返回显式错误；
3. 归档动作本身落审计事件 `room.archived`（操作者、原因、冷存位置），
   写到归档前的事件流末尾，随冷存一并保留。

**删除口径**：归档后保留 M 天（建议 M=90）无人访问/申诉方可物理删除；
删除动作落独立审计记录（`room.deleted`，含操作者、归档编号、事件量快照），
删除操作的审计记录本身不随数据删除。删除仅限管理员触发，禁止用户侧直接删除。

**恢复**：归档房间的恢复 = 冷存事件卷回搬 + 房间解除只读，落 `room.unarchived`
审计事件。恢复后审计链需能完整重放（与 persist-then-commit 恢复演练同验收口径）。

## 3. 已实施：房间事件量监控指标

Bridge `GET /v1/metrics` 新增按房间命名空间展平的事件量计数
（`audit.py` `metrics()`，数据来自内存索引/共享事件清单，不经 MinIO 全量扫描）：

- `room_namespace_count`：有事件的房间命名空间数；
- `room_events__room-<id>`：该房间 business（持久化）事件数；
- `room_stream_events__room-<id>`：该房间瞬态 `room.agent_stream` 事件数。

operational 事件沿用既有 `operational_events__<event_type>` 键，不按房间拆分。
监控面板据此观察各房间事件量增长，作为归档窗口（N/M 取值）的校准依据。
