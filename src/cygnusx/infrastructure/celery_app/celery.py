"""Celery 应用实例"""

from celery import Celery
from celery.schedules import crontab

from cygnusx.core.config import get_settings
from cygnusx.core.logging import setup_logging
from cygnusx.infrastructure.celery_app.logging import LoggedTask

settings = get_settings()
setup_logging()

from cygnusx.core.telemetry import setup_telemetry  # noqa: E402
from cygnusx.infrastructure.celery_app.tracing import wire_celery_tracing  # noqa: E402

setup_telemetry("worker")
# 集中接线 trace context 传播：发布方注入 traceparent/session_id，worker 侧提取恢复，
# 无需改动各 apply_async/delay 派发点。
wire_celery_tracing()

celery_app = Celery(
    "cygnusx",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    task_cls=LoggedTask,
    include=[
        "cygnusx.infrastructure.celery_app.tasks.analysis",
        "cygnusx.infrastructure.celery_app.tasks.cookie",
        "cygnusx.infrastructure.celery_app.tasks.download",
        "cygnusx.tools.jbrowse.tasks",
        "cygnusx.tools.phylogenetic_tree.tasks",
        "cygnusx.tools.blast.tasks",
        "cygnusx.tools.enrichments.tasks",
        "cygnusx.tools.deg.tasks",
        "cygnusx.tools.synteny.tasks",
        "cygnusx.infrastructure.celery_app.tasks.sandbox",
        "cygnusx.infrastructure.celery_app.tasks.storage",
        "cygnusx.infrastructure.celery_app.tasks.studio",
        "cygnusx.infrastructure.celery_app.tasks.mas",
        "cygnusx.infrastructure.celery_app.tasks.overdrive",
        "cygnusx.infrastructure.celery_app.tasks.memory",
        "cygnusx.infrastructure.celery_app.tasks.mcp_builder",
        "cygnusx.infrastructure.celery_app.tasks.agentteams",
        "cygnusx.infrastructure.celery_app.tasks.goals",
        "cygnusx.infrastructure.celery_app.tasks.ai_metrics",
        "cygnusx.infrastructure.celery_app.tasks.observability",
        "cygnusx.infrastructure.celery_app.tasks.schedules",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600 * 6,  # 6 小时超时
    task_soft_time_limit=3600 * 5,  # 5 小时软超时
    worker_prefetch_multiplier=1,  # 长任务场景公平调度
    worker_max_tasks_per_child=10,  # 防止内存泄漏
    # 默认队列与 task_routes 一致：所有任务路由到 "analysis"，
    # worker（无 -Q 时）消费默认队列，故默认队列必须是 analysis，否则任务进队列后无人消费
    task_default_queue="analysis",
    # 强制使用 settings 中的 broker/backend（避免 .env 中的 CELERY_BROKER_URL 覆盖带密码的版本）
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
)

# 队列路由
celery_app.conf.task_routes = {
    "cygnusx.infrastructure.celery_app.tasks.analysis.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.cookie.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.download.*": {"queue": "analysis"},
    "cygnusx.tools.jbrowse.tasks.*": {"queue": "analysis"},
    "cygnusx.tools.phylogenetic_tree.tasks.*": {"queue": "phylo_tree"},
    "cygnusx.tools.blast.tasks.run_blast_search": {"queue": "blast_search"},
    "cygnusx.tools.blast.tasks.build_blast_database": {"queue": "blast_db_build"},
    "cygnusx.tools.enrichments.tasks.*": {"queue": "analysis"},
    "cygnusx.tools.deg.tasks.*": {"queue": "analysis"},
    "cygnusx.tools.synteny.tasks.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.sandbox.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.storage.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.studio.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.mas.rnaflow.*": {"queue": "mas_apptainer"},
    "cygnusx.infrastructure.celery_app.tasks.mas.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.overdrive.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.memory.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.agentteams.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.goals.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.ai_metrics.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.observability.*": {"queue": "analysis"},
    "cygnusx.infrastructure.celery_app.tasks.schedules.*": {"queue": "schedules"},
}

# 定时任务
celery_app.conf.beat_schedule = {
    "schedule-scan-due": {
        "task": "cygnusx.infrastructure.celery_app.tasks.schedules.scan_due_schedules",
        "schedule": 30.0,
        "options": {"queue": "schedules"},
    },
    "schedule-retry-failed": {
        "task": "cygnusx.infrastructure.celery_app.tasks.schedules.retry_failed_deliveries",
        "schedule": 300.0,
        "options": {"queue": "schedules"},
    },
    "agentteams-evidence-retention": {
        "task": "cygnusx.infrastructure.celery_app.tasks.agentteams.cleanup_evidence",
        "schedule": crontab(hour=2, minute=45),
    },
    # 每天凌晨 2 点清理过期/僵尸上传会话 + 临时文件 + 冷数据归档
    "cleanup-expired-archives": {
        "task": "cygnusx.infrastructure.celery_app.tasks.storage.cleanup_expired",
        "schedule": crontab(hour=2, minute=0),
    },
    # 每天凌晨 3 点空间使用量对账（校准 used_storage）
    "storage-reconcile-used": {
        "task": "cygnusx.infrastructure.celery_app.tasks.storage.reconcile_used_storage",
        "schedule": crontab(hour=3, minute=0),
    },
    # 每天凌晨 2:30 饼干日终对账 + 异常检测
    "cookie-daily-reconcile": {
        "task": "cygnusx.infrastructure.celery_app.tasks.cookie.daily_reconcile",
        "schedule": crontab(hour=2, minute=30),
    },
    # 每分钟扫描，回收空闲超过 5 分钟的普通聊天轻量沙盒会话
    "sandbox-recycle-expired": {
        "task": "cygnusx.infrastructure.celery_app.tasks.sandbox.recycle_expired",
        "schedule": crontab(minute="*"),
    },
    # 每 5 分钟回收空闲 Studio 沙盒容器
    "studio-sandbox-recycle": {
        "task": "cygnusx.infrastructure.celery_app.tasks.studio.recycle_idle_sandboxes",
        "schedule": crontab(minute="*/5"),
    },
    # 每 10 分钟对账 Studio 长任务：悬挂 queued / 滞留 running 只报告或标记漂移，
    # 绝不自动重提交（WP2 任务4 契约 c：reconcile-only）
    "studio-long-task-reconcile": {
        "task": "cygnusx.infrastructure.celery_app.tasks.studio.reconcile_studio_long_tasks",
        "schedule": 600.0,
    },
    # 每天凌晨 3:30 清理超过保留期且未在分享/执行中的 Studio 工作区
    "studio-workspace-retention": {
        "task": "cygnusx.infrastructure.celery_app.tasks.studio.cleanup_expired_workspaces",
        "schedule": crontab(hour=3, minute=30),
    },
    # 每天凌晨 4:30 休眠打包：先工作区配额清理，再 dormant 扫描（WP1）
    "studio-workspace-dormant-archive": {
        "task": "cygnusx.infrastructure.celery_app.tasks.studio.hibernate_dormant_workspaces",
        "schedule": crontab(hour=4, minute=30),
    },
    # 每天凌晨 5:30 清理到期归档包（WP1）
    "studio-archive-expire-cleanup": {
        "task": "cygnusx.infrastructure.celery_app.tasks.studio.cleanup_expired_workspace_archives",
        "schedule": crontab(hour=5, minute=30),
    },
    # 每 5 分钟下线过期实验 MCP（MCP Builder TTL 机制）
    "mcp-builder-expire-experimental": {
        "task": "cygnusx.infrastructure.celery_app.tasks.mcp_builder.expire_experimental",
        "schedule": crontab(minute="*/5"),
    },
    "mas-outbox-publish": {
        "task": "cygnusx.infrastructure.celery_app.tasks.mas.publish_outbox",
        "schedule": 10.0,
    },
    "mas-event-consume": {
        "task": "cygnusx.infrastructure.celery_app.tasks.mas.consume_events",
        "schedule": 5.0,
    },
    "agentteams-case-watch": {
        "task": "cygnusx.infrastructure.celery_app.tasks.agentteams.watch_cases",
        "schedule": float(settings.agentteams_case_watch_interval_seconds),
    },
    # 仅清理历史自动确认标记；新 Case 的真实计算必须由用户在审批卡显式确认。
    "agentteams-auto-confirm-cases": {
        "task": "cygnusx.infrastructure.celery_app.tasks.agentteams.auto_confirm_cases",
        "schedule": float(settings.agentteams_case_watch_interval_seconds),
    },
    "agentteams-case-event-consume": {
        "task": "cygnusx.infrastructure.celery_app.tasks.agentteams.consume_case_events",
        "schedule": float(settings.agentteams_case_event_stream_interval_seconds),
    },
    # Matrix → 平台反向同步：仅 agentteams_gateway_enabled 时任务内部才真正启动
    "agentteams-room-sync": {
        "task": "cygnusx.infrastructure.celery_app.tasks.agentteams.sync_case_rooms",
        "schedule": float(settings.agentteams_case_event_stream_interval_seconds),
    },
    "agentteams-stale-task-requeue": {
        "task": "cygnusx.infrastructure.celery_app.tasks.agentteams.requeue_stale_tasks",
        "schedule": 300.0,
    },
    "agentteams-approval-timeout-reconcile": {
        "task": "cygnusx.infrastructure.celery_app.tasks.agentteams.reconcile_approval_timeouts",
        "schedule": 3600.0,
    },
    "goal-lease-recovery": {
        "task": "cygnusx.infrastructure.celery_app.tasks.goals.recover_expired_goal_leases",
        "schedule": max(15.0, settings.goal_lease_seconds / 2),
    },
    # 每 5 分钟评估 AI 指标告警（错误率/p95 延迟/日成本）
    "ai-metrics-alert-check": {
        "task": "cygnusx.infrastructure.celery_app.tasks.ai_metrics.check_alerts",
        "schedule": crontab(minute="*/5"),
    },
    # 每天凌晨 2:15 清理超期可观测性归档（C6 冷数据留存）
    "observability-retention": {
        "task": "cygnusx.infrastructure.celery_app.tasks.observability.prune_archives",
        "schedule": crontab(hour=2, minute=15),
    },
}
