# CygnusX AI 日程管理与提醒系统 - 完整实现文档

> **版本**: v1.0 | **日期**: 2026-08-23 | **状态**: 可直接施工

---

# 第一部分: 实现报告

## 1. 架构决策

### 1.1 核心原则

| 原则 | 说明 |
|------|------|
| **数据库为事实源** | 所有提醒状态以 DB 为准，Celery/WS 只做加速 |
| **复用现有设施** | 不引入 APScheduler/RabbitMQ/新框架，复用 Celery+Beat+Redis |
| **领域独立** | Schedule 是独立领域，不混入 notifications/goals |
| **幂等投递** | 每条 delivery 有唯一键，支持 exactly-once |
| **用户级隔离** | 所有查询必带 user_id，AI 工具从上下文注入 |

### 1.2 技术选型确认

```
调度:     Celery Beat (固定扫描任务) + Celery Worker (投递任务)
数据库:   PostgreSQL + SQLAlchemy 2.x async ORM
缓存/队列: Redis (Pub/Sub + Celery Broker)
实时推送:  Redis Pub/Sub -> WebSocket/SSE
ORM 迁移:  Alembic
AI 工具:   ToolBridge (tools_schema.yaml) + ToolInvocationContext
前端:      Vue3 + Pinia + Naive UI + Axios
```

### 1.3 与现有架构的对接点

| 现有模块 | 对接方式 |
|---------|---------|
| `tool_configs/tools_schema.yaml` | 追加 6 个日程工具定义 |
| `src/cygnusx/api/v1/router.py` | `include_router(schedules.router, prefix="/schedules")` |
| `src/cygnusx/infrastructure/celery_app/celery.py` | Beat 追加 `scan_due_schedules` 周期任务 |
| `src/cygnusx/infrastructure/cache/` | 复用 Redis Pub/Sub 发布用户级通知事件 |
| `frontend/src/stores/notification.ts` | 扩展为统一通知流，复用 Drawer |
| `src/cygnusx/api/deps.py` | `get_current_user` 注入 user_id/workspace_id |

---

## 2. 数据库设计

### 2.1 ER 图

```
users (现有)
  |1
  |
  V*
schedules --1-->* schedule_occurrences --1-->* reminder_deliveries
  |                                              |
  |                                              |
  +- workspace_id --> workspaces (现有)          +- notification_id --> notifications (现有)
```

### 2.2 表结构

#### `schedules` - 日程主表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| user_id | UUID FK -> users.id | 所有者 |
| workspace_id | UUID FK -> workspaces.id | 工作空间 |
| team_id | UUID FK -> teams.id nullable | 团队共享 |
| title | VARCHAR(200) | 标题 |
| description | TEXT | 描述 |
| timezone | VARCHAR(50) | 时区，默认 Asia/Shanghai |
| start_at | TIMESTAMPTZ | 开始时间 (UTC) |
| end_at | TIMESTAMPTZ nullable | 结束时间 |
| duration_seconds | INT | 持续秒数（冗余，方便查询） |
| recurrence_rule | VARCHAR(500) | RFC 5545 RRULE 字符串 |
| next_fire_at | TIMESTAMPTZ | 下一次触发时间（扫描索引） |
| last_fired_at | TIMESTAMPTZ nullable | 上次触发时间 |
| status | VARCHAR(20) | active / paused / cancelled / completed |
| source | VARCHAR(20) | manual / ai / import |
| metadata_json | JSONB | 扩展字段 |
| version | INT | 乐观锁版本号 |
| created_at | TIMESTAMPTZ | 创建时间 |
| updated_at | TIMESTAMPTZ | 更新时间 |

**索引**:
- `idx_schedules_user_status` (user_id, status)
- `idx_schedules_next_fire` (next_fire_at, status) <- 扫描核心索引
- `idx_schedules_workspace` (workspace_id, status)

#### `schedule_occurrences` - 展开实例表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| schedule_id | UUID FK -> schedules.id | 所属日程 |
| occurrence_key | VARCHAR(64) | 实例标识（如日期字符串） |
| scheduled_at | TIMESTAMPTZ | 计划触发时间 |
| status | VARCHAR(20) | pending / fired / completed / skipped |
| fired_at | TIMESTAMPTZ nullable | 实际触发时间 |
| completed_at | TIMESTAMPTZ nullable | 完成时间 |
| created_at | TIMESTAMPTZ | 创建时间 |

**唯一约束**: `(schedule_id, occurrence_key)`
**索引**: `idx_occurrences_schedule` (schedule_id, scheduled_at)

#### `reminder_deliveries` - 投递记录表（幂等核心）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| schedule_id | UUID FK -> schedules.id | 所属日程 |
| occurrence_id | UUID FK -> schedule_occurrences.id | 所属实例 |
| user_id | UUID FK -> users.id | 目标用户 |
| channel | VARCHAR(20) | in_app / email / webhook / browser_push / dingtalk / feishu |
| reminder_offset_minutes | INT | 提前多少分钟（如 15） |
| due_at | TIMESTAMPTZ | 应投递时间 |
| sent_at | TIMESTAMPTZ nullable | 实际发送时间 |
| status | VARCHAR(20) | pending / sending / sent / failed / suppressed |
| attempt_count | INT default 0 | 尝试次数 |
| next_retry_at | TIMESTAMPTZ nullable | 下次重试时间 |
| provider_message_id | VARCHAR(200) nullable | 渠道返回的消息ID |
| last_error | TEXT nullable | 最后一次错误信息 |
| notification_id | UUID FK -> notifications.id nullable | 关联站内通知 |
| created_at | TIMESTAMPTZ | 创建时间 |
| updated_at | TIMESTAMPTZ | 更新时间 |

**唯一约束**: `(occurrence_id, channel, reminder_offset_minutes)` <- 幂等键
**索引**:
- `idx_deliveries_due` (due_at, status) <- 投递扫描索引
- `idx_deliveries_user` (user_id, status, created_at)
- `idx_deliveries_retry` (next_retry_at, status, attempt_count)

---

## 3. 后端实现

### 3.1 目录结构

```
src/cygnusx/
├── infrastructure/database/models/schedule.py      # 模型定义
├── application/schemas/schedule.py                 # Pydantic DTO
├── application/services/schedule_service.py        # 领域服务
├── application/services/reminder_service.py        # 提醒投递服务
├── application/services/schedule_tool_service.py   # AI 工具适配层
├── api/v1/schedules.py                             # REST API
├── api/v1/reminders.py                             # 提醒操作 API
├── infrastructure/celery_app/tasks/schedules.py    # Celery 任务
└── ...
```

### 3.2 核心流程

```
【创建日程】
用户/AI -> POST /schedules -> ScheduleService.create()
    -> 写入 schedules 表
    -> 计算 next_fire_at
    -> 如有重复规则，预生成未来 N 个 occurrence
    -> 为每个 occurrence 创建 reminder_deliveries

【Celery Beat 扫描】(每 30 秒)
scan_due_schedules 任务
    -> SELECT * FROM schedules WHERE next_fire_at <= NOW() AND status = 'active'
      FOR UPDATE SKIP LOCKED LIMIT batch_size
    -> 获取租约 (lease)
    -> 对每个 schedule:
        a. 找到对应的 occurrence (pending 且 scheduled_at <= NOW)
        b. 创建/确认 reminder_deliveries 记录
        c. 发送 Celery 投递任务 (按渠道拆分)
        d. 更新 occurrence.status = 'fired'
        e. 计算并更新 schedule.next_fire_at
        f. 释放租约

【投递任务】
deliver_reminder(delivery_id)
    -> 读取 delivery 记录
    -> 检查 schedule/occurrence 状态（防止取消后仍投递）
    -> 调用对应 Channel 发送
    -> 更新 delivery.status = 'sent' 或 'failed'
    -> 失败则计算 next_retry_at，进入重试队列
    -> 发布 Redis 用户频道事件（实时推送）

【用户确认/暂停/取消】
用户操作 -> 更新 schedule.status
    -> 取消所有 pending delivery（标记为 suppressed）
    -> 如有重复规则，停止生成新 occurrence
```

### 3.3 关键设计决策

**Q: 为什么不直接用 Celery `countdown` 为每个提醒创建定时任务？**
A: 用户日程数量可能很大（每人几十条 x 数千用户），Celery Beat 动态条目管理复杂，且重启后状态恢复困难。用数据库扫描 + 租约模式更可靠，与现有 Goal Runtime 的 lease 设计一致。

**Q: 重复规则怎么实现？**
A: 使用 RFC 5545 RRULE 字符串存储规则，Python 用 `dateutil.rrule` 展开。扫描时按需生成未来 30 天的 occurrence，避免一次性展开所有。

**Q: 时区怎么处理？**
A: DB 统一存 UTC，`start_at/end_at/next_fire_at` 都是 UTC。展示层根据用户 timezone 转换。AI 工具接收自然语言时，服务层统一解析为 UTC。

---

## 4. Celery 调度与投递

### 4.1 Beat 周期任务配置

在 `src/cygnusx/infrastructure/celery_app/celery.py` 的 `beat_schedule` 中追加：

```python
"schedule-scan-due": {
    "task": "src.cygnusx.infrastructure.celery_app.tasks.schedules.scan_due_schedules",
    "schedule": 30.0,  # 每 30 秒
    "options": {"queue": "schedules"},
},
"schedule-retry-failed": {
    "task": "src.cygnusx.infrastructure.celery_app.tasks.schedules.retry_failed_deliveries",
    "schedule": 300.0,  # 每 5 分钟
    "options": {"queue": "schedules"},
},
```

### 4.2 扫描任务实现要点

```python
@celery_app.task(bind=True, max_retries=3)
def scan_due_schedules(self):
    """扫描到期日程，带租约机制防止多 Worker 竞争"""
    lease_key = f"schedule:scan:lease:{datetime.utcnow():%Y%m%d%H%M}"

    # 1. 获取分布式锁（Redis）
    if not redis_client.set(lease_key, "1", nx=True, ex=60):
        return  # 其他 Worker 正在扫描

    try:
        async_to_sync(_do_scan)()
    finally:
        redis_client.delete(lease_key)

async def _do_scan():
    async with async_session() as db:
        now = datetime.utcnow()

        # 2. 批量获取到期且活跃的日程（SKIP LOCKED 防止阻塞）
        result = await db.execute(
            select(Schedule)
            .where(
                Schedule.status == "active",
                Schedule.next_fire_at <= now
            )
            .order_by(Schedule.next_fire_at)
            .limit(settings.SCHEDULE_SCAN_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        schedules = result.scalars().all()

        for schedule in schedules:
            # 3. 处理单个日程
            await process_schedule_firing(db, schedule)

            # 4. 计算下一次触发时间
            schedule.next_fire_at = calculate_next_fire(schedule)
            schedule.last_fired_at = now
            schedule.version += 1

        await db.commit()
```

### 4.3 投递任务实现要点

```python
@celery_app.task(bind=True, max_retries=settings.SCHEDULE_MAX_DELIVERY_ATTEMPTS)
def deliver_reminder(self, delivery_id: str):
    """投递单条提醒"""
    async_to_sync(_do_deliver)(delivery_id)

async def _do_deliver(delivery_id: str):
    async with async_session() as db:
        delivery = await db.get(ReminderDelivery, delivery_id)
        if not delivery or delivery.status in ("sent", "suppressed"):
            return

        # 双重检查：schedule 是否仍活跃
        schedule = await db.get(Schedule, delivery.schedule_id)
        if schedule.status != "active":
            delivery.status = "suppressed"
            await db.commit()
            return

        # 执行投递
        channel = ChannelRegistry.get(delivery.channel)
        success = await channel.send(delivery)

        if success:
            delivery.status = "sent"
            delivery.sent_at = datetime.utcnow()
        else:
            delivery.attempt_count += 1
            if delivery.attempt_count >= settings.SCHEDULE_MAX_DELIVERY_ATTEMPTS:
                delivery.status = "failed"
            else:
                # 指数退避重试
                backoff = 2 ** delivery.attempt_count * 60
                delivery.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff)
                delivery.status = "pending"

        await db.commit()
```

---

## 5. AI 工具接入

### 5.1 工具清单

| 工具名 | 模式 | 需要确认 | 说明 |
|--------|------|---------|------|
| `schedule-create` | sync | 是 | 创建日程 |
| `schedule-list` | sync | 否 | 查询日程列表 |
| `schedule-update` | sync | 是 | 修改日程 |
| `schedule-cancel` | sync | 是 | 取消日程 |
| `reminder-snooze` | sync | 否 | 推迟提醒 |
| `reminder-complete` | sync | 否 | 标记完成 |

### 5.2 自然语言时间解析

AI 可能传入 `"明天下午3点"`、`"每周一上午9点"`、`"48小时后收样"`。

服务层使用 `dateutil.parser` + 自定义规则解析：

```python
def parse_natural_time(text: str, user_timezone: str = "Asia/Shanghai") -> datetime:
    tz = pytz.timezone(user_timezone)
    now = datetime.now(tz)

    # 中文关键词映射
    if "明天" in text:
        base = now + timedelta(days=1)
    elif "后天" in text:
        base = now + timedelta(days=2)
    elif "今天" in text:
        base = now
    else:
        base = now

    # 提取时间
    time_match = re.search(r'(\d{1,2})\s*[:点]\s*(\d{0,2})', text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        if "下午" in text or "晚上" in text and hour < 12:
            hour += 12
        result = base.replace(hour=hour, minute=minute, second=0)
    else:
        result = base

    return result.astimezone(pytz.UTC)
```

### 5.3 工具执行上下文

所有日程工具通过 `ToolInvocationContext` 获取：
- `user_id`（当前登录用户，不可被模型覆盖）
- `workspace_id`
- `session_id`（用于审计）
- `db`（异步数据库会话）

模型参数中的 `user_id` 字段会被忽略或拒绝，防止越权。

---

## 6. 前端实现

### 6.1 组件清单

| 组件 | 文件 | 说明 |
|------|------|------|
| ScheduleView | `views/SchedulesView.vue` | 主页面，含日历+列表 |
| ScheduleCalendar | `components/schedule/ScheduleCalendar.vue` | 月/周/日视图 |
| ScheduleEditor | `components/schedule/ScheduleEditor.vue` | 创建/编辑弹窗 |
| ReminderList | `components/schedule/ReminderList.vue` | 提醒列表+状态 |
| DeliveryStatus | `components/schedule/DeliveryStatus.vue` | 投递历史 |
| useNotificationStream | `composables/useNotificationStream.ts` | 统一通知流 |

### 6.2 状态管理 (Pinia)

```typescript
// stores/schedule.ts
interface ScheduleState {
  schedules: Schedule[];
  occurrences: Occurrence[];
  deliveries: Delivery[];
  currentView: 'month' | 'week' | 'day' | 'list';
  selectedDate: Date;
  loading: boolean;
}

// Actions:
// - fetchSchedules(filter)
// - createSchedule(data)
// - updateSchedule(id, data)
// - cancelSchedule(id)
// - completeSchedule(id)
// - fetchOccurrences(scheduleId)
// - fetchDeliveries(scheduleId)
// - snoozeReminder(deliveryId, minutes)
```

### 6.3 实时通知流

复用现有 WebSocket/Redis 机制，新增用户级频道：

```typescript
// 订阅用户通知频道
const channel = `user:${userId}:notifications`;
redisSubscriber.subscribe(channel, (message) => {
  const data = JSON.parse(message);
  if (data.type === 'reminder') {
    notificationStore.addReminder(data);
    // 播放提示音
    new Audio('/sounds/notification.mp3').play().catch(() => {});
  }
});
```

---

## 7. 集成清单

### 7.1 必须修改的现有文件

| # | 文件 | 修改内容 |
|---|------|---------|
| 1 | `tool_configs/tools_schema.yaml` | 追加 6 个日程工具定义 |
| 2 | `src/cygnusx/api/v1/router.py` | `include_router(schedules.router, prefix="/schedules")` |
| 3 | `src/cygnusx/infrastructure/celery_app/celery.py` | Beat 追加扫描任务 |
| 4 | `src/cygnusx/infrastructure/celery_app/celery.py` | 追加 `schedules` 队列路由 |
| 5 | `src/cygnusx/core/config.py` | 追加日程相关配置项 |
| 6 | `frontend/src/router/index.ts` | 追加 `/schedules` 路由 |
| 7 | `alembic/env.py` | 确保新模型被 Alembic 发现 |

### 7.2 新增文件清单

| # | 文件 | 说明 |
|---|------|------|
| 1 | `src/cygnusx/infrastructure/database/models/schedule.py` | 3 个模型 |
| 2 | `alembic/versions/xxx_add_schedule_tables.py` | 迁移脚本 |
| 3 | `src/cygnusx/application/schemas/schedule.py` | Pydantic DTO |
| 4 | `src/cygnusx/application/services/schedule_service.py` | 领域服务 |
| 5 | `src/cygnusx/application/services/reminder_service.py` | 提醒投递 |
| 6 | `src/cygnusx/application/services/schedule_tool_service.py` | AI 工具适配 |
| 7 | `src/cygnusx/api/v1/schedules.py` | REST API |
| 8 | `src/cygnusx/api/v1/reminders.py` | 提醒操作 API |
| 9 | `src/cygnusx/infrastructure/celery_app/tasks/schedules.py` | Celery 任务 |
| 10 | `frontend/src/api/schedules.ts` | API 封装 |
| 11 | `frontend/src/stores/schedule.ts` | Pinia Store |
| 12 | `frontend/src/views/SchedulesView.vue` | 主页面 |
| 13 | `frontend/src/components/schedule/*.vue` | 子组件 |
| 14 | `frontend/src/composables/useNotificationStream.ts` | 通知流 |

---

## 8. 测试策略

### 8.1 单元测试

```python
# 测试时间解析
def test_parse_natural_time():
    assert parse("明天下午3点").hour == 15
    assert parse("48小时后").day == (now + timedelta(hours=48)).day

# 测试幂等投递
def test_delivery_idempotency():
    # 同一 occurrence + channel + offset 只能有一条 pending
    with pytest.raises(IntegrityError):
        create_duplicate_delivery()

# 测试租约竞争
def test_scan_lease_prevents_duplicate():
    # 模拟两个 Worker 同时扫描，只有一个能获取锁
```

### 8.2 集成测试

```python
# 测试完整流程：创建 -> 到期 -> 投递 -> 确认
async def test_reminder_lifecycle():
    schedule = await create_schedule(start_at=now + timedelta(minutes=1))
    await asyncio.sleep(70)
    deliveries = await get_deliveries(schedule.id)
    assert any(d.status == "sent" for d in deliveries)
```

### 8.3 验收标准

- [ ] 用户可通过 AI 助手说"明天下午3点提醒我开组会"创建日程
- [ ] 创建后 30 秒内数据库出现对应记录
- [ ] 到达提醒时间后，在线用户收到 WebSocket 推送
- [ ] 离线用户打开通知中心可看到未读提醒
- [ ] 取消日程后，未发送的 delivery 被标记为 suppressed
- [ ] 重复日程（每周一）正确生成 occurrence
- [ ] 多 Worker 环境下无重复投递
- [ ] 投递失败 5 次后标记为 failed，不再重试