"""Celery entry points for short-lived persistent Goal iterations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from celery import shared_task

from cygnusx.core.config import get_settings

logger = logging.getLogger(__name__)


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.goals.run_goal_step")
def run_goal_step(goal_id: str, cause: str = "continuation") -> dict[str, str | bool]:
    return asyncio.run(_run_goal_step(goal_id, cause))


async def _run_goal_step(goal_id: str, cause: str) -> dict[str, str | bool]:
    from cygnusx.application.services.goal_execution_engine import GoalExecutionEngine
    from cygnusx.infrastructure.database.session import get_session_factory

    settings = get_settings()
    if not settings.goal_runtime_enabled:
        return {"status": "disabled"}
    try:
        should_continue = await GoalExecutionEngine(
            get_session_factory(), lease_seconds=settings.goal_lease_seconds
        ).run_once(UUID(goal_id), cause)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Goal step failed for %s: %s", goal_id, exc)
        return {"status": "failed", "error": str(exc)}
    if should_continue:
        run_goal_step.apply_async(
            args=[goal_id, "auto_continuation"],
            countdown=settings.goal_continuation_delay_seconds,
        )
    return {"status": "continued" if should_continue else "stopped", "continued": should_continue}


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.goals.recover_expired_goal_leases")
def recover_expired_goal_leases() -> dict[str, Any]:
    return asyncio.run(_recover_expired_goal_leases())


async def _recover_expired_goal_leases(
    *,
    engine: Any | None = None,
    enqueue: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.goal_runtime_enabled:
        return {"status": "disabled", "recovered": 0}
    if engine is None:
        from cygnusx.application.services.goal_execution_engine import GoalExecutionEngine
        from cygnusx.infrastructure.database.session import get_session_factory

        engine = GoalExecutionEngine(
            get_session_factory(), lease_seconds=settings.goal_lease_seconds
        )
    recovered_goal_ids = await engine.recover_expired_leases()
    schedule = enqueue or run_goal_step.apply_async
    for goal_id in recovered_goal_ids:
        schedule(args=[str(goal_id), "lease_recovered"])
    return {"status": "recovered", "recovered": len(recovered_goal_ids)}
