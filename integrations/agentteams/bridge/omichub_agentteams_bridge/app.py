"""FastAPI application for the AgentTeams sidecar Bridge."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any, get_args

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from .audit import AuditStore, json_default
from .case_store import CaseStore
from .client import GatewayClient, OmicHubClient
from .config import BridgeSettings
from .minio_store import MinioBridgeStorage
from .models import (
    ApprovalRequest,
    CancelTaskRequest,
    CaseCancelRequest,
    CaseCloseRequest,
    CaseCreateRequest,
    CaseStateUpdate,
    CaseStatus,
    EvidenceRequest,
    ExecuteGeneralPlanRequest,
    PlanRevisionRequest,
    PreflightRequest,
    QualityGateRequest,
    QueueApprovedSubmissionRequest,
    ReadOnlyExecutionRequest,
    RetryCaseSubmissionRequest,
    SubmitTaskRequest,
    WorkerTokenIssueRequest,
    WorkItemCreateRequest,
    WorkItemHeartbeatRequest,
    WorkItemUpdateRequest,
)
from .room_mirror import AuditRoomMirror
from .security import require_identity, require_role
from .service import BridgeService
from .size_limits import BodySizeLimitMiddleware
from .worker_tokens import WorkerTokenStore


async def get_service(request: Request) -> BridgeService:
    return request.app.state.bridge_service


def case_gc_autorun_enabled(settings: BridgeSettings) -> bool:
    """Scheduled Case GC (startup + daily) is only enabled outside production."""
    return settings.environment != "production" and settings.case_gc_days > 0


async def _case_gc_loop(service: BridgeService) -> None:
    logger = logging.getLogger(__name__)
    while True:
        try:
            summary = await service.gc_cases("bioops-manager")
            if summary["deleted_cases"]:
                logger.info(
                    "Bridge case GC removed %d case(s) and %d audit event(s)",
                    summary["deleted_cases"],
                    summary["deleted_events"],
                )
        except Exception:
            logger.exception("Bridge case GC run failed")
        await asyncio.sleep(24 * 60 * 60)


async def _work_item_watchdog_loop(service: BridgeService, interval_seconds: float) -> None:
    """Periodically reclaim lost Workers' leases so killed Workers never stall a Case.

    The sweep goes through the shared CaseStore lock, so it is safe with multiple
    Bridge replicas; whichever replica sweeps first records the timeline events.
    """
    logger = logging.getLogger(__name__)
    while True:
        try:
            summary = await service.sweep_work_items()
            if summary["requeued"] or summary["timed_out"] or summary["retry_promoted"]:
                logger.info(
                    "Bridge work item sweep: %d requeued, %d timed out, %d retry-promoted",
                    summary["requeued"],
                    summary["timed_out"],
                    summary["retry_promoted"],
                )
        except Exception:
            logger.exception("Bridge work item sweep failed")
        await asyncio.sleep(interval_seconds)


async def authenticate_identity(
    request: Request,
    x_bridge_identity: str | None = Header(default=None),
    x_bridge_token: str | None = Header(default=None),
) -> str:
    return await require_identity(
        request.app.state.bridge_settings,
        request.app.state.worker_token_store,
        x_bridge_identity,
        x_bridge_token,
    )


def create_app(
    settings: BridgeSettings | None = None,
    client: OmicHubClient | None = None,
    gateway_client: GatewayClient | None = None,
    minio_storage: MinioBridgeStorage | None = None,
) -> FastAPI:
    runtime_settings = settings or BridgeSettings()
    runtime_client = client or OmicHubClient(runtime_settings)
    runtime_gateway_client = gateway_client
    if runtime_gateway_client is None and (
        runtime_settings.gateway_url and runtime_settings.gateway_manager_token
    ):
        runtime_gateway_client = GatewayClient(runtime_settings)
    if minio_storage is None:
        minio_storage = MinioBridgeStorage.from_settings(runtime_settings)
    if minio_storage is None:
        # 非生产允许的回退路径：Redis/本地文件模式。生产由 BridgeSettings 校验器拦截。
        logging.getLogger(__name__).warning(
            "BRIDGE_MINIO_ENDPOINT 未配置：Bridge 持久层回退到 Redis/本地文件模式（仅限非生产环境）"
        )
    room_mirror = AuditRoomMirror(runtime_gateway_client)
    audit_store = AuditStore(
        runtime_settings.audit_log_path,
        runtime_settings.state_store_url,
        f"{runtime_settings.state_store_key_prefix}:audit",
        on_event=room_mirror.observe if room_mirror.enabled else None,
        minio_storage=minio_storage,
    )
    case_store = CaseStore(
        runtime_settings.case_store_path,
        runtime_settings.state_store_url,
        f"{runtime_settings.state_store_key_prefix}:cases",
        minio_storage=minio_storage,
    )
    worker_token_store = WorkerTokenStore(
        runtime_settings.worker_token_store_path,
        runtime_settings.state_store_url,
        f"{runtime_settings.state_store_key_prefix}:worker-tokens",
    )
    service = BridgeService(
        runtime_settings,
        runtime_client,
        audit_store,
        case_store,
        runtime_gateway_client,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if room_mirror.enabled:
            try:
                room_mirror.rebind(await audit_store.all_events())
            except Exception:
                logging.getLogger(__name__).warning(
                    "room mirror binding rebuild failed", exc_info=True
                )
        gc_task: asyncio.Task[None] | None = None
        if case_gc_autorun_enabled(runtime_settings):
            gc_task = asyncio.create_task(_case_gc_loop(service))
        watchdog_task: asyncio.Task[None] | None = None
        if runtime_settings.work_item_sweep_interval_seconds > 0:
            watchdog_task = asyncio.create_task(
                _work_item_watchdog_loop(
                    service, runtime_settings.work_item_sweep_interval_seconds
                )
            )
        if runtime_settings.omichub_integration_token:
            try:
                await service.refresh_capabilities()
            except Exception:
                logger = logging.getLogger(__name__)

                async def _retry_capabilities() -> None:
                    for attempt in range(1, 11):
                        await asyncio.sleep(min(attempt * 5, 30))
                        try:
                            await service.refresh_capabilities()
                            logger.info("capabilities refreshed after %d retries", attempt)
                            return
                        except Exception:
                            logger.debug("capabilities retry %d/10 failed", attempt)
                    logger.warning("giving up capabilities refresh after 10 retries")

                asyncio.create_task(_retry_capabilities())
        yield
        if watchdog_task is not None:
            watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog_task
        if gc_task is not None:
            gc_task.cancel()
            with suppress(asyncio.CancelledError):
                await gc_task
        await runtime_client.aclose()
        if runtime_gateway_client is not None:
            await runtime_gateway_client.aclose()
        await audit_store.aclose()
        await case_store.aclose()
        await worker_token_store.aclose()

    app = FastAPI(title="OmicHub AgentTeams Bridge", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_request_bytes=runtime_settings.max_request_bytes,
        max_response_bytes=runtime_settings.max_response_bytes,
    )
    app.state.bridge_service = service
    app.state.bridge_settings = runtime_settings
    app.state.case_store = case_store
    app.state.worker_token_store = worker_token_store
    logging.getLogger(__name__).info(
        "AgentTeams Bridge started build_sha=%s build_time=%s",
        runtime_settings.build_sha,
        runtime_settings.build_time,
    )

    @app.get("/healthz", tags=["Health"])
    async def healthz() -> dict[str, Any]:
        health: dict[str, Any] = {
            "status": "ok",
            "case_store_skipped_cases": case_store.skipped_case_count,
            "build_sha": runtime_settings.build_sha,
            "build_time": runtime_settings.build_time,
        }
        if minio_storage is not None:
            minio_health = minio_storage.health()
            health["minio_enabled"] = True
            health["minio_reachable"] = minio_health["reachable"]
            health["minio_last_write_latency_ms"] = minio_health["last_write_latency_ms"]
        else:
            health["minio_enabled"] = False
        return health

    @app.get("/v1/metrics", tags=["Observability"])
    async def get_metrics(
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict[str, int]:
        require_role(identity, "bioops-manager", "delivery-reporter")
        return await service.metrics()

    @app.get("/v1/health/identity", tags=["Health"])
    async def identity_health(identity: Annotated[str, Depends(authenticate_identity)]) -> dict[str, str]:
        """Authenticated probe used by OmicHub to validate its four Bridge credentials."""
        return {"status": "ok", "identity": identity}

    @app.get("/v1/health/workers", tags=["Health"])
    async def worker_health(
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        return await service.worker_health()

    @app.get("/v1/flows", tags=["Flows"])
    async def list_flows(
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(
            identity, "bioops-manager", "data-steward", "workflow-operator", "quality-auditor"
        )
        return await service.list_flows()

    @app.get("/v1/capabilities", tags=["Flows"])
    async def capabilities(
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
        reload: bool = False,
    ) -> dict:
        require_role(identity, "bioops-manager", *service.worker_identities())
        return await service.capabilities(reload=reload)

    @app.post("/v1/cases", status_code=status.HTTP_201_CREATED, tags=["Cases"])
    async def create_case(
        payload: CaseCreateRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        return (await service.create_case(payload, identity)).model_dump(mode="json")

    @app.get("/v1/cases", tags=["Cases"])
    async def list_cases(
        request: Request,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager", "delivery-reporter")
        requester_ref = request.query_params.get("requester_ref")
        if requester_ref is not None and len(requester_ref) > 256:
            raise HTTPException(status_code=422, detail="requester_ref is too long")
        case_status = request.query_params.get("status")
        project_id = request.query_params.get("project_id")
        cursor = request.query_params.get("cursor")
        limit = request.query_params.get("limit", "20")
        if case_status is not None and case_status not in get_args(CaseStatus):
            raise HTTPException(status_code=422, detail="Invalid Case status")
        if project_id is not None and len(project_id) > 256:
            raise HTTPException(status_code=422, detail="project_id is too long")
        if cursor is not None and len(cursor) > 128:
            raise HTTPException(status_code=422, detail="cursor is too long")
        try:
            page_limit = int(limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="limit must be an integer") from exc
        if not 1 <= page_limit <= 100:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "LIMIT_EXCEEDED",
                    "message": "limit must be between 1 and 100",
                },
            )
        return (
            await service.list_cases(
                requester_ref,
                case_status=case_status,
                project_id=project_id,
                cursor=cursor,
                limit=page_limit,
            )
        ).model_dump(mode="json")

    @app.get("/v1/cases/{case_id}", tags=["Cases"])
    async def get_case(
        case_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(
            identity,
            "bioops-manager",
            "analysis-worker",
            *service.worker_identities(),
        )
        return await service.get_case_view(case_id, identity)

    @app.get("/v1/work-items/assigned", tags=["Work Items"])
    async def list_assigned_work_items(
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(
            identity,
            "analysis-worker",
            *service.worker_identities(),
        )
        return (await service.list_worker_inbox(identity)).model_dump(mode="json")

    @app.post("/v1/cases/{case_id}/state", tags=["Cases"])
    async def update_case_state(
        case_id: str,
        payload: CaseStateUpdate,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        return (await service.update_case_state(case_id, payload, identity)).model_dump(mode="json")

    @app.post("/v1/cases/{case_id}/reconcile", tags=["Cases"])
    async def reconcile_case(
        case_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        return (await service.reconcile_case(case_id, identity)).model_dump(mode="json")

    @app.post("/v1/cases/{case_id}/plan/revise", tags=["Cases"])
    async def revise_case_plan(
        case_id: str,
        payload: PlanRevisionRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        return (await service.revise_plan(case_id, payload, identity)).model_dump(mode="json")

    @app.post("/v1/maintenance/approval-timeouts", tags=["Maintenance"])
    async def reconcile_approval_timeouts(
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict[str, int]:
        require_role(identity, "bioops-manager")
        return await service.reconcile_approval_timeouts(identity)

    @app.post("/v1/maintenance/case-gc", tags=["Maintenance"])
    async def case_gc(
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        return await service.gc_cases(identity)

    @app.post("/v1/worker-tokens", status_code=status.HTTP_201_CREATED, tags=["Worker Tokens"])
    async def issue_worker_token(
        payload: WorkerTokenIssueRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        """Issue a revocable per-worker token; the raw value is returned exactly once."""
        require_role(identity, "bioops-manager")
        # 可铸造身份仅限外部 Worker（注册表岗位 + analysis-worker）；平台身份
        # （approval-authority、bioops-manager 等 BRIDGE_IDENTITIES 静态身份）一律 403，
        # 杜绝持 manager 凭证自铸 approval-authority token 绕过人工审批（审查 B1）。
        mintable_identities = service.worker_identities() | {"analysis-worker"}
        if payload.identity not in mintable_identities:
            if payload.identity in runtime_settings.identity_secrets():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Platform identities cannot be minted as worker tokens",
                )
            raise HTTPException(status_code=422, detail="Unknown Worker identity")
        token, record = await worker_token_store.issue(
            identity=payload.identity,
            ttl_seconds=payload.ttl_seconds,
            note=payload.note,
        )
        return {"token": token, "record": record.model_dump(mode="json", exclude={"token_hash"})}

    @app.get("/v1/worker-tokens", tags=["Worker Tokens"])
    async def list_worker_tokens(
        identity: Annotated[str, Depends(authenticate_identity)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        records = await worker_token_store.list()
        return {
            "items": [
                record.model_dump(mode="json", exclude={"token_hash"}) for record in records
            ]
        }

    @app.delete("/v1/worker-tokens/{token_id}", tags=["Worker Tokens"])
    async def revoke_worker_token(
        token_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        record = await worker_token_store.revoke(token_id)
        return record.model_dump(mode="json", exclude={"token_hash"})

    @app.post("/v1/cases/{case_id}/retry", tags=["Cases"])
    async def retry_case_submission(
        case_id: str,
        payload: RetryCaseSubmissionRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        return (
            await service.retry_case_submission(case_id, payload, identity)
        ).model_dump(mode="json")

    @app.post("/v1/cases/{case_id}/work-items", status_code=status.HTTP_201_CREATED, tags=["Cases"])
    async def assign_work_item(
        case_id: str,
        payload: WorkItemCreateRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        return (await service.assign_work_item(case_id, payload, identity)).model_dump(mode="json")

    @app.post("/v1/cases/{case_id}/work-items/{work_item_id}", tags=["Cases"])
    async def update_work_item(
        case_id: str,
        work_item_id: str,
        payload: WorkItemUpdateRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(
            identity,
            "bioops-manager",
            "analysis-worker",
            *service.worker_identities(),
        )
        return (
            await service.update_work_item(case_id, work_item_id, payload, identity)
        ).model_dump(mode="json")

    @app.post("/v1/cases/{case_id}/work-items/{work_item_id}/claim", tags=["Work Items"])
    async def claim_work_item(
        case_id: str,
        work_item_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(
            identity,
            "analysis-worker",
            *service.worker_identities(),
        )
        return (await service.claim_work_item(case_id, work_item_id, identity)).model_dump(
            mode="json"
        )

    @app.post("/v1/cases/{case_id}/work-items/{work_item_id}/heartbeat", tags=["Work Items"])
    async def heartbeat_work_item(
        case_id: str,
        work_item_id: str,
        payload: WorkItemHeartbeatRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(
            identity,
            "analysis-worker",
            *service.worker_identities(),
        )
        return (
            await service.heartbeat_work_item(case_id, work_item_id, payload, identity)
        ).model_dump(mode="json")

    @app.post(
        "/v1/cases/{case_id}/work-items/{work_item_id}/execute-readonly",
        tags=["Work Items"],
    )
    async def execute_readonly_work_item(
        case_id: str,
        work_item_id: str,
        payload: ReadOnlyExecutionRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, *service.worker_identities())
        return (
            await service.execute_readonly_work_item(case_id, work_item_id, payload, identity)
        ).model_dump(mode="json")

    @app.get("/v1/cases/{case_id}/events", tags=["Cases"])
    async def get_case_events(
        case_id: str,
        request: Request,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(
            identity,
            "bioops-manager",
            "data-steward",
            "workflow-operator",
            "quality-auditor",
            "delivery-reporter",
        )
        cursor = request.query_params.get("cursor")
        limit = request.query_params.get("limit", "100")
        if cursor is not None and len(cursor) > 128:
            raise HTTPException(status_code=422, detail="cursor is too long")
        try:
            page_limit = int(limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="limit must be an integer") from exc
        if not 1 <= page_limit <= 100:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "LIMIT_EXCEEDED",
                    "message": "limit must be between 1 and 100",
                },
            )
        return (
            await service.get_case_events(case_id, identity, cursor=cursor, limit=page_limit)
        ).model_dump(mode="json")

    @app.get("/v1/cases/{case_id}/manifest", tags=["Cases"])
    async def get_manifest(
        case_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager", "delivery-reporter")
        return await service.get_manifest(case_id, identity)

    @app.get("/v1/cases/{case_id}/events/stream", tags=["Cases"])
    async def stream_case_events(
        case_id: str,
        request: Request,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> StreamingResponse:
        require_role(identity, "bioops-manager", "data-steward", "workflow-operator", "quality-auditor", "delivery-reporter")
        cursor = request.query_params.get("cursor")
        if cursor is not None and len(cursor) > 128:
            raise HTTPException(status_code=422, detail="cursor is too long")
        watch_seconds = request.query_params.get("watch_seconds", "60")
        try:
            duration = int(watch_seconds)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="watch_seconds must be an integer") from exc
        if not 1 <= duration <= 60:
            raise HTTPException(status_code=422, detail="watch_seconds must be between 1 and 60")

        async def event_generator() -> AsyncIterator[str]:
            async for event in service.stream_case_events(
                case_id, identity, cursor=cursor, watch_seconds=duration
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=json_default)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/projects/{project_id}/preflight", tags=["Preflight"])
    async def preflight(
        project_id: str,
        payload: PreflightRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "data-steward")
        if not any(ref.kind == "project" and ref.id == project_id for ref in payload.context_refs):
            payload.context_refs.append({"kind": "project", "id": project_id})
        return (await service.preflight(payload, identity)).model_dump(mode="json")

    @app.post("/v1/approvals", status_code=status.HTTP_201_CREATED, tags=["Approvals"])
    async def create_approval(
        payload: ApprovalRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "approval-authority")
        return (await service.issue_approval(payload, identity)).model_dump(mode="json")

    @app.post("/v1/general-plans/execute", tags=["Approvals"])
    async def execute_general_plan(
        payload: ExecuteGeneralPlanRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "approval-authority")
        return (await service.execute_general_plan(payload.case_id, payload.approval_token, identity)).model_dump(mode="json")

    @app.post("/v1/tasks", status_code=status.HTTP_201_CREATED, tags=["Tasks"])
    async def submit_task(
        payload: SubmitTaskRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "workflow-operator")
        return (await service.submit_task(payload, identity)).model_dump(mode="json")

    @app.post("/v1/approved-submissions", status_code=status.HTTP_201_CREATED, tags=["Approvals"])
    async def queue_approved_submission(
        payload: QueueApprovedSubmissionRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "approval-authority")
        return (await service.queue_approved_submission(payload, identity)).model_dump(mode="json")

    @app.post(
        "/v1/cases/{case_id}/work-items/{work_item_id}/submit-approved",
        status_code=status.HTTP_201_CREATED,
        tags=["Tasks"],
    )
    async def submit_approved_work_item(
        case_id: str,
        work_item_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "analysis-worker")
        return (
            await service.submit_approved_work_item(case_id, work_item_id, identity)
        ).model_dump(mode="json")

    @app.get("/v1/tasks/{task_id}", tags=["Tasks"])
    async def get_task(
        task_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        return await service.get_task(task_id, identity)

    @app.get("/v1/tasks/{task_id}/events", tags=["Tasks"])
    async def get_task_events(
        task_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        return await service.get_task(task_id, identity)

    @app.get("/v1/tasks/{task_id}/artifacts", tags=["Tasks"])
    async def get_task_artifacts(
        task_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        return await service.get_artifacts(task_id, identity)

    @app.post("/v1/tasks/{task_id}/quality-gate", tags=["Quality"])
    async def quality_gate(
        task_id: str,
        payload: QualityGateRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        return (await service.quality_gate(task_id, payload, identity)).model_dump(mode="json")

    @app.post("/v1/tasks/{task_id}/cancel", tags=["Tasks"])
    async def cancel_task(
        task_id: str,
        payload: CancelTaskRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "workflow-operator")
        return await service.cancel_task(task_id, payload, identity)

    @app.post(
        "/v1/cases/{case_id}/evidence", status_code=status.HTTP_201_CREATED, tags=["Evidence"]
    )
    async def record_evidence(
        case_id: str,
        payload: EvidenceRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        # B2：身份白名单收口——平台身份（bioops-manager/workflow-operator）与
        # 已登记 Worker 身份可写；approval-authority 等其余平台身份一律 403。
        # 写约束（target 绑定/租约/因果锚点/命名空间）在 service.record_evidence 强制。
        require_role(
            identity,
            "bioops-manager",
            "workflow-operator",
            "analysis-worker",
            *service.worker_identities(),
        )
        return (await service.record_evidence(case_id, payload, identity)).model_dump(mode="json")

    @app.post("/v1/cases/{case_id}/close", tags=["Cases"])
    async def close_case(
        case_id: str,
        payload: CaseCloseRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        if payload.case_id != case_id:
            raise HTTPException(status_code=400, detail="Case path and payload mismatch")
        return (await service.close_case(payload, identity)).model_dump(mode="json")

    @app.post("/v1/cases/{case_id}/cancel", tags=["Cases"])
    async def cancel_case(
        case_id: str,
        payload: CaseCancelRequest,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
    ) -> dict:
        require_role(identity, "bioops-manager")
        return (await service.cancel_case(case_id, payload, identity)).model_dump(mode="json")

    @app.delete("/v1/cases/{case_id}", tags=["Cases"])
    async def delete_case(
        case_id: str,
        identity: Annotated[str, Depends(authenticate_identity)],
        service: Annotated[BridgeService, Depends(get_service)],
        reason: str | None = None,
    ) -> dict:
        require_role(identity, "bioops-manager")
        return await service.delete_case(case_id, identity, reason)

    return app


app = create_app()
