"""Celery 应用实例"""

from celery import Celery
from celery.schedules import crontab

from omichub.core.config import get_settings
from omichub.core.logging import setup_logging
from omichub.infrastructure.celery_app.logging import LoggedTask

settings = get_settings()
setup_logging()

from omichub.core.telemetry import setup_telemetry  # noqa: E402

setup_telemetry("worker")

celery_app = Celery(
    "omichub",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    task_cls=LoggedTask,
    include=[
        "omichub.infrastructure.celery_app.tasks.analysis",
        "omichub.infrastructure.celery_app.tasks.cookie",
        "omichub.infrastructure.celery_app.tasks.download",
        "omichub.tools.jbrowse.tasks",
        "omichub.tools.phylogenetic_tree.tasks",
        "omichub.tools.blast.tasks",
        "omichub.tools.enrichments.tasks",
        "omichub.tools.deg.tasks",
        "omichub.tools.synteny.tasks",
        "omichub.infrastructure.celery_app.tasks.sandbox",
        "omichub.infrastructure.celery_app.tasks.storage",
        "omichub.infrastructure.celery_app.tasks.studio",
        "omichub.infrastructure.celery_app.tasks.mas",
        "omichub.infrastructure.celery_app.tasks.overdrive",
        "omichub.infrastructure.celery_app.tasks.memory",
        "omichub.infrastructure.celery_app.tasks.mcp_builder",
        "omichub.infrastructure.celery_app.tasks.agentteams",
        "omichub.infrastructure.celery_app.tasks.goals",
        "omichub.infrastructure.celery_app.tasks.ai_metrics",
        "omichub.infrastructure.celery_app.tasks.observability",
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
    "omichub.infrastructure.celery_app.tasks.analysis.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.cookie.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.download.*": {"queue": "analysis"},
    "omichub.tools.jbrowse.tasks.*": {"queue": "analysis"},
    "omichub.tools.phylogenetic_tree.tasks.*": {"queue": "phylo_tree"},
    "omichub.tools.blast.tasks.run_blast_search": {"queue": "blast_search"},
    "omichub.tools.blast.tasks.build_blast_database": {"queue": "blast_db_build"},
    "omichub.tools.enrichments.tasks.*": {"queue": "analysis"},
    "omichub.tools.deg.tasks.*": {"queue": "analysis"},
    "omichub.tools.synteny.tasks.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.sandbox.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.storage.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.studio.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.mas.rnaflow.*": {"queue": "mas_apptainer"},
    "omichub.infrastructure.celery_app.tasks.mas.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.overdrive.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.memory.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.agentteams.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.goals.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.ai_metrics.*": {"queue": "analysis"},
    "omichub.infrastructure.celery_app.tasks.observability.*": {"queue": "analysis"},
}

# 定时任务
celery_app.conf.beat_schedule = {
    "agentteams-evidence-retention": {
        "task": "omichub.infrastructure.celery_app.tasks.agentteams.cleanup_evidence",
        "schedule": crontab(hour=2, minute=45),
    },
    # 每天凌晨 2 点清理过期/僵尸上传会话 + 临时文件 + 冷数据归档
    "cleanup-expired-archives": {
        "task": "omichub.infrastructure.celery_app.tasks.storage.cleanup_expired",
        "schedule": crontab(hour=2, minute=0),
    },
    # 每天凌晨 3 点空间使用量对账（校准 used_storage）
    "storage-reconcile-used": {
        "task": "omichub.infrastructure.celery_app.tasks.storage.reconcile_used_storage",
        "schedule": crontab(hour=3, minute=0),
    },
    # 每天凌晨 2:30 饼干日终对账 + 异常检测
    "cookie-daily-reconcile": {
        "task": "omichub.infrastructure.celery_app.tasks.cookie.daily_reconcile",
        "schedule": crontab(hour=2, minute=30),
    },
    # 每分钟扫描，回收空闲超过 5 分钟的普通聊天轻量沙盒会话
    "sandbox-recycle-expired": {
        "task": "omichub.infrastructure.celery_app.tasks.sandbox.recycle_expired",
        "schedule": crontab(minute="*"),
    },
    # 每 5 分钟回收空闲 Studio 沙盒容器
    "studio-sandbox-recycle": {
        "task": "omichub.infrastructure.celery_app.tasks.studio.recycle_idle_sandboxes",
        "schedule": crontab(minute="*/5"),
    },
    # 每天凌晨 3:30 清理超过保留期且未在分享/执行中的 Studio 工作区
    "studio-workspace-retention": {
        "task": "omichub.infrastructure.celery_app.tasks.studio.cleanup_expired_workspaces",
        "schedule": crontab(hour=3, minute=30),
    },
    # 每 5 分钟下线过期实验 MCP（MCP Builder TTL 机制）
    "mcp-builder-expire-experimental": {
        "task": "omichub.infrastructure.celery_app.tasks.mcp_builder.expire_experimental",
        "schedule": crontab(minute="*/5"),
    },
    "mas-outbox-publish": {
        "task": "omichub.infrastructure.celery_app.tasks.mas.publish_outbox",
        "schedule": 10.0,
    },
    "mas-event-consume": {
        "task": "omichub.infrastructure.celery_app.tasks.mas.consume_events",
        "schedule": 5.0,
    },
    "agentteams-case-watch": {
        "task": "omichub.infrastructure.celery_app.tasks.agentteams.watch_cases",
        "schedule": float(settings.agentteams_case_watch_interval_seconds),
    },
    # 仅清理历史自动确认标记；新 Case 的真实计算必须由用户在审批卡显式确认。
    "agentteams-auto-confirm-cases": {
        "task": "omichub.infrastructure.celery_app.tasks.agentteams.auto_confirm_cases",
        "schedule": float(settings.agentteams_case_watch_interval_seconds),
    },
    "agentteams-case-event-consume": {
        "task": "omichub.infrastructure.celery_app.tasks.agentteams.consume_case_events",
        "schedule": float(settings.agentteams_case_event_stream_interval_seconds),
    },
    # Matrix → 平台反向同步：仅 agentteams_gateway_enabled 时任务内部才真正启动
    "agentteams-room-sync": {
        "task": "omichub.infrastructure.celery_app.tasks.agentteams.sync_case_rooms",
        "schedule": float(settings.agentteams_case_event_stream_interval_seconds),
    },
    "agentteams-stale-task-requeue": {
        "task": "omichub.infrastructure.celery_app.tasks.agentteams.requeue_stale_tasks",
        "schedule": 300.0,
    },
    "agentteams-approval-timeout-reconcile": {
        "task": "omichub.infrastructure.celery_app.tasks.agentteams.reconcile_approval_timeouts",
        "schedule": 3600.0,
    },
    "goal-lease-recovery": {
        "task": "omichub.infrastructure.celery_app.tasks.goals.recover_expired_goal_leases",
        "schedule": max(15.0, settings.goal_lease_seconds / 2),
    },
    # 每 5 分钟评估 AI 指标告警（错误率/p95 延迟/日成本）
    "ai-metrics-alert-check": {
        "task": "omichub.infrastructure.celery_app.tasks.ai_metrics.check_alerts",
        "schedule": crontab(minute="*/5"),
    },
    # 每天凌晨 2:15 清理超期可观测性归档（C6 冷数据留存）
    "observability-retention": {
        "task": "omichub.infrastructure.celery_app.tasks.observability.prune_archives",
        "schedule": crontab(hour=2, minute=15),
    },
}
