"""AgentTeams Bridge 的低频状态巡检任务。"""

from __future__ import annotations

import asyncio
import logging
import uuid

from celery import shared_task

from cygnusx.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeSettingsService,
)
from cygnusx.application.services.agentteams_room_response_service import (
    AgentTeamsRoomResponseService,
)
from cygnusx.application.services.agentteams_service import AgentTeamsService
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.cache.redis_client import get_redis
from cygnusx.infrastructure.database.session import get_session_factory

logger = logging.getLogger(__name__)

_WATCH_LOCK_KEY = "agentteams:case-watch:lock"
_EVENT_CONSUMER_LOCK_KEY = "agentteams:case-event-consumer:lock"
_APPROVAL_TIMEOUT_LOCK_KEY = "agentteams:approval-timeout:lock"
_STALE_TASK_LOCK_KEY = "agentteams:stale-task-watch:lock"
_AUTO_CONFIRM_LOCK_KEY = "agentteams:auto-confirm:lock"
_RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.agentteams.watch_cases")
def watch_cases() -> dict[str, int | str]:
    return asyncio.run(_watch_cases())


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.agentteams.consume_case_events")
def consume_case_events() -> dict[str, int | str]:
    return asyncio.run(_consume_case_events())


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.agentteams.requeue_stale_tasks")
def requeue_stale_tasks() -> dict[str, int | str]:
    return asyncio.run(_requeue_stale_tasks())


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.agentteams.reconcile_approval_timeouts")
def reconcile_approval_timeouts() -> dict[str, int | str]:
    return asyncio.run(_reconcile_approval_timeouts())


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.agentteams.auto_confirm_cases")
def auto_confirm_cases() -> dict[str, int | str]:
    return asyncio.run(_auto_confirm_cases())


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.agentteams.cleanup_evidence")
def cleanup_evidence() -> dict[str, object]:
    return asyncio.run(_cleanup_evidence())


@shared_task(
    bind=True,
    name="cygnusx.infrastructure.celery_app.tasks.agentteams.respond_to_room_message",
    max_retries=120,
)
def respond_to_room_message(
    self,
    case_id: str,
    requester_ref: str,
    content: str,
    dispatch: dict[str, object] | None = None,
    model_id: str | None = None,
) -> dict[str, str]:
    selected_model_id = _parse_model_id(model_id)
    if dispatch is None:
        if selected_model_id is None:
            result = asyncio.run(_respond_to_room_message(case_id, requester_ref, content))
        else:
            result = asyncio.run(
                _respond_to_room_message(
                    case_id, requester_ref, content, model_id=selected_model_id
                )
            )
    else:
        if selected_model_id is None:
            result = asyncio.run(
                _respond_to_room_message(case_id, requester_ref, content, dispatch)
            )
        else:
            result = asyncio.run(
                _respond_to_room_message(
                    case_id,
                    requester_ref,
                    content,
                    dispatch,
                    model_id=selected_model_id,
                )
            )
    if result.get("status") == "skipped_locked":
        raise self.retry(countdown=2)
    return result


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.agentteams.sync_case_rooms")
def sync_case_rooms() -> dict[str, object]:
    return asyncio.run(_sync_case_rooms())


@shared_task(
    bind=True,
    name="cygnusx.infrastructure.celery_app.tasks.agentteams.respond_to_room_namespace_message",
    max_retries=120,
)
def respond_to_room_namespace_message(
    self,
    room_id: str,
    requester_ref: str,
    content: str,
    dispatch: dict[str, object] | None = None,
    actor_user_id: str | None = None,
    model_id: str | None = None,
) -> dict[str, str]:
    """协作室房间（含未立项房间）发言的 Manager 响应任务。"""
    result = asyncio.run(
        _respond_to_room_namespace_message(
            room_id,
            requester_ref,
            content,
            dispatch,
            actor_user_id=actor_user_id,
            model_id=_parse_model_id(model_id),
        )
    )
    if result.get("status") == "skipped_locked":
        raise self.retry(countdown=2)
    return result


async def _respond_to_room_namespace_message(
    room_id: str,
    requester_ref: str,
    content: str,
    dispatch: dict[str, object] | None = None,
    actor_user_id: str | None = None,
    model_id: uuid.UUID | None = None,
) -> dict[str, str]:
    try:
        settings = get_settings()
        async with get_session_factory()() as db:
            runtime = await AgentTeamsBridgeSettingsService(db, settings).get_runtime_config()
            agentteams = AgentTeamsService(settings, runtime)
            if not agentteams.available:
                return {"status": "skipped_unavailable"}
            from cygnusx.application.services.agentteams_room_service import (
                AgentTeamsRoomService,
            )

            room = await AgentTeamsRoomService(db, agentteams).get_room(room_id, requester_ref)
            result = await AgentTeamsRoomResponseService(db, agentteams=agentteams).respond_room(
                room,
                requester_ref,
                content,
                actor_user_id=actor_user_id or requester_ref,
                model_id=model_id,
                target_agent_id=str(dispatch.get("target_agent_id") or "") or None
                if isinstance(dispatch, dict) and dispatch.get("dispatch_mode") == "direct"
                else None,
                target_agent_ids=[str(item) for item in (dispatch.get("target_agent_ids") or [])]
                if isinstance(dispatch, dict) and dispatch.get("dispatch_mode") == "multi_direct"
                else None,
            )
            # BUG-E2E-02：立项卡等房间行写入此前只 flush 不 commit，会话关闭即回滚，
            # confirm-proposal 恒 400。失败态不提交，随会话关闭回滚保持一致。
            if result.get("status") != "failed":
                await db.commit()
            return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentTeams room namespace response task failed: %s", exc)
        return {"status": "failed"}


async def _sync_case_rooms() -> dict[str, object]:
    from cygnusx.infrastructure.database.session import get_session_factory

    return await _sync_case_rooms_with_factory(get_session_factory)


async def _sync_case_rooms_with_factory(
    session_factory,
    *,
    redis_getter=get_redis,
    stream_seconds: int | None = None,
) -> dict[str, object]:
    from cygnusx.application.services.agentteams_bridge_settings_service import (
        AgentTeamsBridgeSettingsService,
    )
    from cygnusx.application.services.agentteams_room_gateway_service import (
        AgentTeamsRoomGatewayService,
    )
    from cygnusx.application.services.agentteams_room_sync_service import (
        AgentTeamsRoomSyncService,
    )
    from cygnusx.application.services.agentteams_service import AgentTeamsService

    try:
        gateway = AgentTeamsRoomGatewayService()
        if not gateway.available:
            return {"status": "skipped_unavailable"}
        settings = get_settings()
        async with session_factory()() as db:
            runtime = await AgentTeamsBridgeSettingsService(db, settings).get_runtime_config()
            agentteams = AgentTeamsService(settings, runtime)
            if not agentteams.available:
                return {"status": "skipped_unavailable"}
            return await AgentTeamsRoomSyncService(
                agentteams, gateway=gateway, redis_getter=redis_getter
            ).run(watch_seconds=stream_seconds or settings.agentteams_case_event_stream_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentTeams room sync orchestration failed: %s", exc)
        return {"status": "failed"}


async def _respond_to_room_message(
    case_id: str,
    requester_ref: str,
    content: str,
    dispatch: dict[str, object] | None = None,
    model_id: uuid.UUID | None = None,
) -> dict[str, str]:
    try:
        settings = get_settings()
        async with get_session_factory()() as db:
            runtime = await AgentTeamsBridgeSettingsService(db, settings).get_runtime_config()
            agentteams = AgentTeamsService(settings, runtime)
            if not agentteams.available:
                return {"status": "skipped_unavailable"}
            return await AgentTeamsRoomResponseService(db, agentteams=agentteams).respond(
                case_id,
                requester_ref,
                content,
                model_id=model_id,
                target_agent_id=str(dispatch.get("target_agent_id") or "") or None
                if isinstance(dispatch, dict) and dispatch.get("dispatch_mode") == "direct"
                else None,
                target_agent_ids=[str(item) for item in (dispatch.get("target_agent_ids") or [])]
                if isinstance(dispatch, dict) and dispatch.get("dispatch_mode") == "multi_direct"
                else None,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentTeams room response task failed: %s", exc)
        return {"status": "failed"}


def _parse_model_id(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        logger.warning("Ignoring invalid AgentTeams model override: %s", value)
        return None


async def _cleanup_evidence() -> dict[str, object]:
    from cygnusx.application.services.agentteams_evidence_gc_service import (
        AgentTeamsEvidenceGcService,
    )

    try:
        return await AgentTeamsEvidenceGcService().cleanup()
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentTeams evidence cleanup failed: %s", exc)
        return {"status": "failed", "error": str(exc)}


async def _watch_cases() -> dict[str, int | str]:
    from cygnusx.application.services.agentteams_case_watch_service import (
        AgentTeamsCaseWatchService,
    )
    from cygnusx.infrastructure.database.session import get_session_factory

    return await _watch_cases_with_factory(get_session_factory, AgentTeamsCaseWatchService)


async def _consume_case_events() -> dict[str, int | str]:
    from cygnusx.application.services.agentteams_case_event_consumer_service import (
        AgentTeamsCaseEventConsumerService,
    )
    from cygnusx.infrastructure.database.session import get_session_factory

    return await _consume_case_events_with_factory(
        get_session_factory, AgentTeamsCaseEventConsumerService
    )


async def _requeue_stale_tasks() -> dict[str, int | str]:
    from cygnusx.application.services.agentteams_stale_task_service import (
        AgentTeamsStaleTaskService,
    )
    from cygnusx.infrastructure.database.session import get_session_factory

    return await _requeue_stale_tasks_with_factory(
        get_session_factory, AgentTeamsStaleTaskService
    )


async def _reconcile_approval_timeouts() -> dict[str, int | str]:
    from cygnusx.infrastructure.database.session import get_session_factory

    return await _reconcile_approval_timeouts_with_factory(get_session_factory)


async def _auto_confirm_cases() -> dict[str, int | str]:
    from cygnusx.infrastructure.database.session import get_session_factory

    return await _auto_confirm_cases_with_factory(get_session_factory)


# 仍可能推进到 approval_pending 的前置状态；其余状态（含终态/已批准）视为自动确认终点。
_AUTO_CONFIRM_PENDING_STATUSES = frozenset(
    {
        "queued",
        "received",
        "planning_running",
        "preflight_running",
        "preflight_blocked",
        "waiting_for_correction",
    }
)


async def _auto_confirm_cases_with_factory(
    session_factory,
    *,
    redis_getter=get_redis,
) -> dict[str, int | str]:
    """清理历史自动确认标记，确保遗留标记不会绕过人工审批。"""
    from cygnusx.application.services.agentteams_bridge_settings_service import (
        AgentTeamsBridgeSettingsService,
    )
    from cygnusx.application.services.agentteams_service import (
        AUTO_CONFIRM_CASES_KEY,
        AgentTeamsService,
    )

    lock_token = uuid.uuid4().hex
    redis = redis_getter()
    acquired = False
    try:
        acquired = bool(await redis.set(_AUTO_CONFIRM_LOCK_KEY, lock_token, nx=True, ex=60))
        if not acquired:
            return {"status": "skipped_locked"}
        marked = {str(item) for item in await redis.smembers(AUTO_CONFIRM_CASES_KEY)}
        summary: dict[str, int | str] = {
            "status": "ok",
            "marked": len(marked),
            "confirmed": 0,
            "skipped": 0,
            "failed": 0,
        }
        if not marked:
            return summary
        settings = get_settings()
        async with session_factory()() as db:
            runtime = await AgentTeamsBridgeSettingsService(db, settings).get_runtime_config()
            service = AgentTeamsService(settings, runtime)
            if not service.available:
                return {"status": "skipped_unavailable"}
            pending_cases = await service.admin_list_cases_by_status("approval_pending")
            pending_by_id = {
                str(case.get("case_id")): case
                for case in pending_cases
                if case.get("case_id")
            }
            for case_id in sorted(marked):
                case = pending_by_id.get(case_id)
                if case is None:
                    # 未进入待审批：仍在前置状态则保留标记，否则清理（含已批准/终态）。
                    try:
                        current = await service.admin_get_case(case_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "AgentTeams auto-confirm status probe failed for %s: %s",
                            case_id,
                            exc,
                        )
                        summary["failed"] = int(summary["failed"]) + 1
                        continue
                    if str(current.get("status") or "") not in _AUTO_CONFIRM_PENDING_STATUSES:
                        await redis.srem(AUTO_CONFIRM_CASES_KEY, case_id)
                        summary["skipped"] = int(summary["skipped"]) + 1
                    continue
                requester_ref = case.get("requester_ref")
                if not isinstance(requester_ref, str) or not requester_ref:
                    summary["failed"] = int(summary["failed"]) + 1
                    continue
                try:
                    result = await service.auto_approve_case_if_autonomous(
                        case_id=case_id,
                        requester_ref=requester_ref,
                        db=db,
                        task_name=f"auto-{case_id[-8:]}",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "AgentTeams auto-confirm failed for %s: %s", case_id, exc
                    )
                    summary["failed"] = int(summary["failed"]) + 1
                    continue
                status_value = str(result.get("status") or "")
                if status_value.startswith("idempotent_") or status_value in {
                    "auto_approved",
                    "skipped_manual_approval_required",
                }:
                    await redis.srem(AUTO_CONFIRM_CASES_KEY, case_id)
                    if status_value != "skipped_manual_approval_required":
                        summary["confirmed"] = int(summary["confirmed"]) + 1
                    else:
                        summary["skipped"] = int(summary["skipped"]) + 1
                else:
                    summary["skipped"] = int(summary["skipped"]) + 1
            return summary
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentTeams auto-confirm orchestration failed: %s", exc)
        return {"status": "failed"}
    finally:
        if acquired:
            try:
                await redis.eval(_RELEASE_LOCK_LUA, 1, _AUTO_CONFIRM_LOCK_KEY, lock_token)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AgentTeams auto-confirm lock release failed: %s", exc)


async def _watch_cases_with_factory(
    session_factory,
    watch_service_cls,
    *,
    redis_getter=get_redis,
    lock_ttl_seconds: int | None = None,
) -> dict[str, int | str]:
    ttl = lock_ttl_seconds or max(30, get_settings().agentteams_case_watch_interval_seconds * 2)
    lock_token = uuid.uuid4().hex
    redis = redis_getter()
    try:
        acquired = await redis.set(_WATCH_LOCK_KEY, lock_token, nx=True, ex=ttl)
        if not acquired:
            logger.info("AgentTeams Case watch skipped because another worker holds the lock")
            return {"status": "skipped_locked"}
        async with session_factory()() as session:
            result = await watch_service_cls(session).scan()
            await session.commit()
            return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentTeams Case watch failed: %s", exc)
        return {"status": "failed"}
    finally:
        if "acquired" in locals() and acquired:
            try:
                await redis.eval(_RELEASE_LOCK_LUA, 1, _WATCH_LOCK_KEY, lock_token)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AgentTeams Case watch lock release failed: %s", exc)


async def _consume_case_events_with_factory(
    session_factory,
    consumer_service_cls,
    *,
    redis_getter=get_redis,
    stream_seconds: int | None = None,
) -> dict[str, int | str]:
    from cygnusx.application.services.agentteams_case_watch_service import (
        TERMINAL_STATUSES,
        _watchable_sessions_query,
    )

    settings = get_settings()
    duration = stream_seconds or settings.agentteams_case_event_stream_seconds
    lock_token = uuid.uuid4().hex
    redis = redis_getter()
    acquired = False
    try:
        acquired = bool(
            await redis.set(
                _EVENT_CONSUMER_LOCK_KEY,
                lock_token,
                nx=True,
                ex=max(30, duration + 15),
            )
        )
        if not acquired:
            return {"status": "skipped_locked"}
        async with session_factory()() as discovery_session:
            sessions = list((await discovery_session.scalars(_watchable_sessions_query())).all())
            bindings = [
                (session.session_id, case_id)
                for session in sessions
                for case_id in (session.sandbox_meta or {}).get("agentteams_case_ids", [])
                if isinstance(case_id, str)
                and (session.sandbox_meta or {})
                .get("agentteams_case_status", {})
                .get(case_id)
                not in TERMINAL_STATUSES
            ]

        async def consume_binding(session_id: str, case_id: str) -> dict[str, int]:
            async with session_factory()() as db:
                result = await consumer_service_cls(db).consume(
                    session_id, case_id, watch_seconds=duration
                )
                await db.commit()
                return result

        results = await asyncio.gather(
            *(consume_binding(session_id, case_id) for session_id, case_id in bindings),
            return_exceptions=True,
        )
        summary = {"bindings": len(bindings), "events": 0, "projected": 0, "failed": 0}
        for result in results:
            if isinstance(result, BaseException):
                summary["failed"] += 1
                logger.warning("AgentTeams Case SSE consumer failed: %s", result)
                continue
            summary["events"] += result["events"]
            summary["projected"] += result["projected"]
        return summary
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentTeams Case SSE consumer orchestration failed: %s", exc)
        return {"status": "failed"}
    finally:
        if acquired:
            try:
                await redis.eval(_RELEASE_LOCK_LUA, 1, _EVENT_CONSUMER_LOCK_KEY, lock_token)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AgentTeams Case SSE consumer lock release failed: %s", exc)


async def _requeue_stale_tasks_with_factory(
    session_factory,
    service_cls,
    *,
    redis_getter=get_redis,
    lock_ttl_seconds: int = 290,
) -> dict[str, int | str]:
    lock_token = uuid.uuid4().hex
    redis = redis_getter()
    try:
        acquired = await redis.set(
            _STALE_TASK_LOCK_KEY, lock_token, nx=True, ex=lock_ttl_seconds
        )
        if not acquired:
            logger.info("AgentTeams stale task watch skipped because another worker holds the lock")
            return {"status": "skipped_locked"}
        async with session_factory()() as session:
            return await service_cls(session).scan(
                stale_after_seconds=get_settings().agentteams_stale_task_seconds
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentTeams stale task watch failed: %s", exc)
        return {"status": "failed"}
    finally:
        if "acquired" in locals() and acquired:
            try:
                await redis.eval(_RELEASE_LOCK_LUA, 1, _STALE_TASK_LOCK_KEY, lock_token)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AgentTeams stale task watch lock release failed: %s", exc)


async def _reconcile_approval_timeouts_with_factory(
    session_factory,
    *,
    redis_getter=get_redis,
) -> dict[str, int | str]:
    from cygnusx.application.services.agentteams_bridge_settings_service import (
        AgentTeamsBridgeSettingsService,
    )
    from cygnusx.application.services.agentteams_service import AgentTeamsService

    lock_token = uuid.uuid4().hex
    redis = redis_getter()
    acquired = False
    try:
        acquired = bool(
            await redis.set(
                _APPROVAL_TIMEOUT_LOCK_KEY, lock_token, nx=True, ex=3500
            )
        )
        if not acquired:
            return {"status": "skipped_locked"}
        settings = get_settings()
        async with session_factory()() as db:
            runtime = await AgentTeamsBridgeSettingsService(db, settings).get_runtime_config()
            service = AgentTeamsService(settings, runtime)
            if not service.available:
                return {"status": "skipped_unavailable"}
            return await service.reconcile_approval_timeouts()
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentTeams approval timeout reconciliation failed: %s", exc)
        return {"status": "failed"}
    finally:
        if acquired:
            try:
                await redis.eval(_RELEASE_LOCK_LUA, 1, _APPROVAL_TIMEOUT_LOCK_KEY, lock_token)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AgentTeams approval timeout lock release failed: %s", exc)
