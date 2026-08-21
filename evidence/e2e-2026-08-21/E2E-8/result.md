# E2E-8 MinIO 恢复结果：绿

测试 Case：e2e-20260821-minio-021846（Bridge 级创建，context_refs 含 project 引用，
4 条持久事件：case.created + e2e.probe×3；事件 digest=30bee70ebeff2e29）

## 阶段 1：docker rm -f Bridge + compose up -d 重建
- 重建后 bridge healthy；GET /v1/cases/{case} 状态一致（received）、context_refs 一致；
- 事件流 4 条、event_id 序列 digest 重建前后**完全一致**（events_before/after.json）；
- MinIO 对象完好（snapshot.json + events/audit.jsonl，minio_objects_before.txt）；
- healthz：minio_enabled=true, minio_reachable=true（healthz_after_recreate.json）。
- 判定：零状态损失可重放 ✅

## 阶段 2：损坏快照（仅改本测试 Case 的 snapshot.json：last_event_id → bogus）
- `docker restart omichub-agentteams-bridge` → 进程退出（Exited 1），/healthz 不可达；
- 日志明确告警：`RuntimeError: case e2e-20260821-minio-021846 snapshot last_event_id
  'e2e-corrupted-bogus-event-id' is not in the event stream; refusing to start with an
  inconsistent snapshot`（refuse_start_log.txt）。
- 判定：损坏快照拒启动 + 日志告警 ✅

## 阶段 3：恢复快照（last_event_id 回写 None，即原始值）
- bridge 重新 healthy；事件流 4 条 digest 仍 30bee70ebeff2e29，与初始一致 ✅

## 环境恢复确认
- 仅 bridge 容器被 rm/restart；db/cache/minio/rocketmq 未动；栈完整可用。
- 观察项：健康告警面——bridge 拒启动期间 compose 状态为 Exited(1)，healthz 仅体现
  进程存活与否；case_store_skipped_cases 指标与「拒启动」语义无关（实为 work item 计数），
  损坏快照不会以 skipped 形式静默降级——符合 fail-fast 设计。
agentteams-agentteams-worker-professional-pool-1	Up 6 minutes
agentteams-agentteams-worker-professional-pool-2	Up 6 minutes
agentteams-worker-analysis	Up 6 minutes
agentteams-worker-delivery	Up 6 minutes
agentteams-worker-quality	Up 6 minutes
omichub-agentteams-bridge	Up 30 seconds (healthy)
omichub-agentteams-gateway	Up 7 minutes (healthy)
omichub-agentteams-state	Up 7 minutes (healthy)
