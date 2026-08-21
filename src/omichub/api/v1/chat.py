"""Cherry Studio 架构聊天 API 路由

SSE 流式聊天 + 会话管理 + 助手管理
API 前缀：/api/v1/chat
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from loguru import logger
from sqlalchemy import select

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.schemas.chat import (
    AgentTeamsUpgradeDecisionRequest,
    ChatAssistantDTO,
    ChatHandoffEventDTO,
    ChatMessageDTO,
    ChatSessionDTO,
    ChatSessionSearchDTO,
    ChatStreamRequest,
    CreateAssistantRequest,
    CreateSessionRequest,
    MessageFeedbackRequest,
    OverdriveBranchApprovalRequest,
    OverdriveControlRequest,
    OverdrivePlanDecisionRequest,
    OverdriveRunCommandRequest,
    RejectOverdriveApprovalRequest,
    UpdateSessionRequest,
)
from omichub.application.schemas.skill import SkillDTO
from omichub.application.services.chat_service import ChatService

router = APIRouter()


async def _resume_orchestrator_graph(
    db: DbSession,
    *,
    run_id: str,
    user_id: str,
    decision: dict,
) -> bool:
    """langgraph 引擎路径：把计划确认决策以 Command(resume=...) 喂回编排图
    interrupt 点，驱动图继续走 dispatch/aggregate 节点。

    决策已先经 OverdriveRunService.decide_plan 落账（command_id 幂等），
    图内 decide 委派命中幂等记录直接返回；dispatch 委派先对账 ledger 再触发
    advance_run，保证不重复确认、不重复派发。无 checkpoint（run 由 legacy
    路径创建或开关中途切换）时返回 False，由调用方回退既有派发链；
    其余异常只记录日志——决策已落账，checkpoint 仍在，可重试。
    """
    from omichub.infrastructure.execution.checkpointer import postgres_checkpointer
    from omichub.infrastructure.execution.orchestrator_graph import (
        build_ledger_resume_deps,
        build_orchestrator_engine,
    )

    deps = build_ledger_resume_deps(db, user_id=user_id, commit=db.commit)
    try:
        async with postgres_checkpointer() as saver:
            snapshot = await saver.aget_tuple(
                {"configurable": {"thread_id": run_id}}
            )
            if snapshot is None:
                return False
            engine = build_orchestrator_engine(deps, checkpointer=saver)
            async for _chunk in engine.resume(run_id, decision):
                # POST JSON 接口不流式透出；进度仍走 overdrive 事件 ledger/SSE 订阅
                pass
        return True
    except Exception:  # noqa: BLE001
        logger.exception("orchestrator 图 resume 失败 run_id={}", run_id)
        return False


@router.get(
    "/sandbox-sessions/{sandbox_session_id}/artifacts/download",
    summary="下载聊天轻量沙盒产物",
)
async def download_chat_sandbox_artifact(
    sandbox_session_id: str,
    current_user_id: CurrentUserId,
    path: str = Query(..., min_length=1, max_length=1_000),
) -> FileResponse:
    import re

    from omichub.core.exceptions import NotFoundError, ValidationError
    from omichub.infrastructure.storage import get_path_factory, get_storage_backend

    safe_session_id = re.sub(r"[^a-zA-Z0-9-]", "-", sandbox_session_id)
    factory = get_path_factory()
    root = (
        factory.workspace_dir(str(current_user_id))
        / "chat-output"
        / safe_session_id
        / "output"
    ).resolve()
    candidate = (root / path.lstrip("/")).resolve()
    # 归属校验由路径中的 current_user_id 保证（沙盒会话回收后 DB 记录删除，
    # 产物仍需可下载），目录禁锢防路径穿越。
    if candidate != root and root not in candidate.parents:
        raise ValidationError("产物路径无效或尚未生成")

    backend = get_storage_backend()
    try:
        local_path = await backend.get_local_path(factory.relative_to_root(candidate))
    except NotFoundError:
        raise ValidationError("产物路径无效或尚未生成") from None
    return FileResponse(local_path, filename=local_path.name)


@router.get(
    "/sessions/{session_id}/overdrive-runs/active",
    summary="读取当前会话可恢复的超频 run 快照",
)
async def active_overdrive_run(
    session_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> dict:
    from omichub.application.services.overdrive_run_service import OverdriveRunService

    service = OverdriveRunService(db)
    run = await service.get_active_for_session(session_id, current_user_id)
    return {"run": service.snapshot(run) if run is not None else None}


@router.get(
    "/sessions/{session_id}/overdrive-runs/latest",
    summary="读取当前会话最近一次超频 run 快照（含终态）",
)
async def latest_overdrive_run(
    session_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> dict:
    from omichub.application.services.overdrive_run_service import OverdriveRunService

    service = OverdriveRunService(db)
    run = await service.get_latest_for_session(session_id, current_user_id)
    return {"run": service.snapshot(run) if run is not None else None}


@router.get(
    "/sessions/{session_id}/overdrive-runs/{run_id}/plan",
    summary="预览当前冻结的超频计划",
    response_class=PlainTextResponse,
)
async def preview_overdrive_plan(
    session_id: str,
    run_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> PlainTextResponse:
    from omichub.application.services.overdrive_run_service import (
        OverdriveRunService,
        overdrive_run_root,
    )
    from omichub.core.exceptions import ValidationError
    from omichub.infrastructure.storage import get_path_factory, get_storage_backend

    service = OverdriveRunService(db)
    run = await service.get_for_user(run_id, current_user_id)
    if run is None or run.session_id != session_id:
        raise ValidationError("超频 run 不存在或不属于当前会话")
    version = int((run.plan or {}).get("version") or 0)
    path = overdrive_run_root(session_id, run_id) / f"plan.v{version}.md"
    factory = get_path_factory()
    backend = get_storage_backend()
    rel = factory.relative_to_root(path)
    if version < 1 or not await backend.exists(rel):
        raise ValidationError("计划快照尚未生成")
    content = await backend.read(rel)
    return PlainTextResponse(
        content.decode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="plan.v{version}.md"'},
    )


@router.get(
    "/sessions/{session_id}/overdrive-runs/{run_id}/artifacts",
    summary="下载已登记的超频产物",
)
async def download_overdrive_artifact(
    session_id: str,
    run_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
    path: str = Query(..., min_length=1, max_length=1_000),
) -> FileResponse:
    from omichub.application.services.overdrive_run_service import (
        OverdriveRunService,
        overdrive_run_root,
        relative_overdrive_run_root,
    )
    from omichub.core.exceptions import NotFoundError, ValidationError
    from omichub.infrastructure.storage import get_path_factory, get_storage_backend

    service = OverdriveRunService(db)
    run = await service.get_for_user(run_id, current_user_id)
    if run is None or run.session_id != session_id:
        raise ValidationError("超频 run 不存在或不属于当前会话")
    root = overdrive_run_root(session_id, run_id).resolve()
    prefix = relative_overdrive_run_root(session_id, run_id)
    relative_path = path.removeprefix(prefix).lstrip("/")
    candidate = (root / relative_path).resolve()
    # 安全边界来自归属校验（get_for_user）+ 目录禁锢（run 根内）+ 真实文件，
    # 不再硬性要求预先登记进 artifact_index：专家在回复中引用的任何 run 内
    # 文件（上游 plan、产物、审计报告）都应可下载。
    if root not in candidate.parents:
        raise ValidationError("产物路径无效或尚未生成")

    factory = get_path_factory()
    backend = get_storage_backend()
    try:
        local_path = await backend.get_local_path(factory.relative_to_root(candidate))
    except NotFoundError:
        raise ValidationError("产物路径无效或尚未生成") from None
    return FileResponse(local_path, filename=local_path.name)


@router.get(
    "/sessions/{session_id}/overdrive-runs/{run_id}/events",
    summary="按单调游标补发超频 run 事件",
)
async def replay_overdrive_events(
    session_id: str,
    run_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
    after_sequence: int = Query(0, ge=0),
) -> dict:
    from omichub.application.services.overdrive_run_service import OverdriveRunService

    service = OverdriveRunService(db)
    run = await service.get_for_user(run_id, current_user_id)
    if run is None or run.session_id != session_id:
        from omichub.core.exceptions import ValidationError

        raise ValidationError("超频 run 不存在或不属于当前会话")
    events = await service.events_after(run_id, current_user_id, after_sequence)
    return {
        "run": service.snapshot(run),
        "events": events,
        "projected_events": [
            projected
            for event in events
            if (projected := service.project_event(event)) is not None
        ],
        "event_cursor": run.event_cursor,
    }


@router.get(
    "/sessions/{session_id}/overdrive-runs/{run_id}/stream",
    summary="订阅可恢复的超频 run 领域事件",
)
async def stream_overdrive_run(
    session_id: str,
    run_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
    after_sequence: int = Query(0, ge=0),
) -> StreamingResponse:
    """Poll the DB authority and emit cursor-replayable SSE across web restarts."""
    import asyncio

    from omichub.application.services.overdrive_run_service import OverdriveRunService
    from omichub.core.exceptions import ValidationError
    from omichub.infrastructure.database.session import get_session_factory

    initial = OverdriveRunService(db)
    run = await initial.get_for_user(run_id, current_user_id)
    if run is None or run.session_id != session_id:
        raise ValidationError("超频 run 不存在或不属于当前会话")

    async def generate_sse():
        cursor = after_sequence
        terminal = {"COMPLETED", "CANCELLED", "TERMINATED", "FAILED"}
        while True:
            async with get_session_factory()() as event_db:
                service = OverdriveRunService(event_db)
                current = await service.get_for_user(run_id, current_user_id)
                if current is None:
                    break
                events = await service.events_after(run_id, current_user_id, cursor)
                for event in events:
                    cursor = max(cursor, int(event["sequence"]))
                    projected = service.project_event(event)
                    if projected is not None:
                        yield f"data: {json.dumps(projected, ensure_ascii=False, default=str)}\n\n"
                is_terminal = current.status in terminal and cursor >= current.event_cursor
            if is_terminal:
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/sessions/{session_id}/overdrive-runs/{run_id}/plan-decision",
    summary="确认、修改或取消一个不可变计划快照",
)
async def decide_overdrive_plan(
    session_id: str,
    run_id: str,
    request: OverdrivePlanDecisionRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> dict:
    from omichub.application.services.overdrive_run_service import OverdriveRunService
    from omichub.application.services.overdrive_runtime import load_overdrive_limits

    service = OverdriveRunService(db)
    run = await service.get_for_user(run_id, current_user_id)
    if run is None or run.session_id != session_id:
        from omichub.core.exceptions import ValidationError

        raise ValidationError("超频 run 不存在或不属于当前会话")
    limits = load_overdrive_limits(str(run.lead_planner_agent_id or ""))
    planning_limits = limits.get("planning") or {}
    result = await service.decide_plan(
        run_id=run_id,
        user_id=current_user_id,
        command_id=request.command_id,
        action=request.action,
        plan_version=request.plan_version,
        plan_digest=request.plan_hash,
        feedback=request.feedback,
        max_revisions=int(planning_limits.get("max_revision_rounds") or 3),
    )
    await db.commit()
    from omichub.core.config import get_settings

    use_langgraph_engine = get_settings().orchestrator_engine == "langgraph"
    # langgraph 路径：approve/cancel 决策以 Command(resume=...) 喂回编排图
    # interrupt 点，由图的 dispatch 节点（带 ledger 对账）触发派发；revise 仍走
    # 既有 replan_run 异步链重规划，图在用户确认新版本时经对账继续。
    if (
        use_langgraph_engine
        and request.action in {"approve", "cancel"}
        and result.get("status") != "COMPLETED"
    ):
        resumed = await _resume_orchestrator_graph(
            db,
            run_id=run_id,
            user_id=current_user_id,
            decision={
                "action": request.action,
                "feedback": request.feedback,
                "command_id": request.command_id,
            },
        )
        if resumed:
            return result
        # 无 checkpoint（如开关中途切换、run 由 legacy 路径创建）：回退既有派发
        logger.warning(
            "orchestrator 图 resume 不可用 run_id={} action={}，回退 advance_run 派发",
            run_id,
            request.action,
        )
    if request.action == "approve" and result.get("status") != "COMPLETED":
        from omichub.infrastructure.celery_app.tasks.overdrive import advance_run

        advance_run.delay(run_id)
    elif request.action == "revise":
        from omichub.infrastructure.celery_app.tasks.overdrive import replan_run

        replan_run.delay(run_id)
    return result


@router.post(
    "/sessions/{session_id}/overdrive-runs/{run_id}/control",
    summary="持久化暂停、恢复或终止超频 run",
)
async def control_overdrive_run(
    session_id: str,
    run_id: str,
    request: OverdriveRunCommandRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> dict:
    from omichub.application.services.overdrive_run_service import OverdriveRunService

    service = OverdriveRunService(db)
    run = await service.get_for_user(run_id, current_user_id)
    if run is None or run.session_id != session_id:
        from omichub.core.exceptions import ValidationError

        raise ValidationError("超频 run 不存在或不属于当前会话")
    result = await service.apply_control(
        run_id=run_id,
        user_id=current_user_id,
        command_id=request.command_id,
        action=request.action,
    )
    await db.commit()
    if request.action in {"resume", "terminate"} and result.get("status") != "TERMINATED":
        from omichub.infrastructure.celery_app.tasks.overdrive import advance_run

        advance_run.delay(run_id)
    return result


@router.post(
    "/sessions/{session_id}/overdrive-runs/{run_id}/approvals/{approval_id}/decision",
    summary="决定一个 v2 超频分支的高风险工具调用",
)
async def decide_overdrive_branch_approval(
    session_id: str,
    run_id: str,
    approval_id: str,
    request: OverdriveBranchApprovalRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> dict:
    from omichub.application.services.overdrive_run_service import OverdriveRunService

    service = OverdriveRunService(db)
    run = await service.get_for_user(run_id, current_user_id)
    if run is None or run.session_id != session_id:
        from omichub.core.exceptions import ValidationError

        raise ValidationError("超频 run 不存在或不属于当前会话")
    result = await service.decide_branch_approval(
        run_id=run_id,
        user_id=current_user_id,
        command_id=request.command_id,
        approval_id=approval_id,
        action=request.action,
        reason=request.reason,
    )
    await db.commit()
    from omichub.infrastructure.celery_app.tasks.overdrive import advance_run

    advance_run.delay(run_id)
    return result


def get_chat_service(db: DbSession) -> ChatService:
    return ChatService(db)


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


@router.post(
    "/sessions/{session_id}/overdrive/control",
    summary="暂停、恢复、跳过或终止超频调度",
)
async def control_overdrive(
    session_id: str,
    request: OverdriveControlRequest,
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
) -> dict:
    return await service.control_overdrive(
        session_id=session_id,
        user_id=current_user_id,
        action=request.action,
        task_id=request.task_id or "",
        directive=request.directive or "",
    )


@router.post(
    "/sessions/{session_id}/overdrive-approvals/{approval_id}/approve",
    summary="批准并恢复执行超频 Worker 工具调用",
)
async def approve_overdrive_approval(
    session_id: str,
    approval_id: str,
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
) -> dict:
    return await service.approve_overdrive_approval(
        session_id=session_id, user_id=current_user_id, approval_id=approval_id
    )


@router.post(
    "/sessions/{session_id}/overdrive-approvals/{approval_id}/reject",
    summary="拒绝超频 Worker 工具调用",
)
async def reject_overdrive_approval(
    session_id: str,
    approval_id: str,
    request: RejectOverdriveApprovalRequest,
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
) -> dict:
    return await service.reject_overdrive_approval(
        session_id=session_id,
        user_id=current_user_id,
        approval_id=approval_id,
        reason=request.reason,
    )


# ============================================================
# SSE 流式聊天（核心接口）
# ============================================================


@router.post("/stream", summary="SSE 流式聊天")
async def chat_stream(
    request: ChatStreamRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> StreamingResponse:
    """SSE 流式聊天接口

    - 传 ``agent_id``：走 Agent 调度中枢（组装模型/系统词/MCP 工具，含 tool_call 闭环）
    - 否则按 ``model_id`` 直连模型
    - Studio 会话（session_id 对应会话行 mode="studio"，或新建时显式传 mode="studio"）
      额外挂载工作台内置工具，sandbox_execute 的 stdout/stderr 以 tool_output 事件实时推送

    响应: data: {"type":"text","content":"你"}\\n\\n ...
    事件类型: text / tool_call / tool_output / tool_result / error / done
    """

    async def generate_sse():
        service = ChatService(db)
        if request.agent_id:
            gen = service.stream_agent_chat(
                user_id=current_user_id,
                agent_id=request.agent_id,
                messages=request.messages,
                session_id=request.session_id,
                model_id=request.model_id,
                attachments=request.attachments,
                enable_web_search=request.enable_web_search,
                enable_code_execution=request.enable_code_execution,
                deep_thinking=request.deep_thinking,
                mode=request.mode,
                project_id=request.project_id,
                mcp_mode=request.mcp_mode,
                extra_mcp_servers=request.extra_mcp_servers,
                multi_agent=request.multi_agent,
                overdrive=request.overdrive,
                extend_max_rounds=request.extend_max_rounds,
            )
        else:
            if not request.model_id:
                yield f"data: {json.dumps({'type': 'error', 'content': 'agent_id 与 model_id 至少传一个'}, ensure_ascii=False)}\n\n"
                return
            gen = service.stream_chat(
                user_id=current_user_id,
                messages=request.messages,
                model_id=request.model_id,
                session_id=request.session_id,
                assistant_id=request.assistant_id,
                system_prompt=request.system_prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                enable_web_search=request.enable_web_search,
                project_id=request.project_id,
            )
        async for chunk in gen:
            if chunk.type == "heartbeat":
                yield ": heartbeat\n\n"
                continue
            data: dict = {"type": chunk.type, "content": chunk.content}
            if chunk.metadata:
                data.update(chunk.metadata)
            yield f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            if chunk.type == "done":
                break
        await db.commit()

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/web-search/availability", summary="联网搜索是否已配置")
async def web_search_availability(
    current_user_id: CurrentUserId, db: DbSession
) -> dict[str, object]:
    from omichub.application.services.search_provider_service import SearchProviderService

    availability = await SearchProviderService(db).availability()
    return availability.model_dump()


@router.get(
    "/sessions/{session_id}/agentteams-events",
    summary="订阅聊天会话的 AgentTeams Case 状态事件",
)
async def agentteams_case_events(
    session_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
    cursor: str | None = None,
) -> StreamingResponse:
    """为当前用户已打开的聊天会话提供后台 Case 状态 SSE。"""
    session = await ChatService(db).get_session(session_id, current_user_id)
    if session is None:

        async def missing_session():
            yield f"data: {json.dumps({'type': 'error', 'content': '会话不存在或无权访问'}, ensure_ascii=False)}\n\n"

        return StreamingResponse(missing_session(), media_type="text/event-stream", status_code=404)

    async def generate_sse():
        from omichub.infrastructure.cache.chat_case_pubsub import (
            replay_chat_case_events,
            subscribe_chat_case_events,
        )

        pubsub = await subscribe_chat_case_events(session_id)
        try:
            for payload in await replay_chat_case_events(session_id, cursor):
                yield f"data: {payload}\n\n"
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/sessions/{session_id}/agentteams-upgrade",
    summary="L2→L4 升级建议卡决策（accept 创建协作室房间并移交上下文 / dismiss 不再弹卡）",
)
async def decide_agentteams_upgrade(
    session_id: str,
    req: AgentTeamsUpgradeDecisionRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> dict:
    """消费 L2 会话中的协作室升级建议卡（愿景 Phase D，建议不强制、非自动跳转）。"""
    from omichub.application.services.agentteams_bridge_settings_service import (
        AgentTeamsBridgeSettingsService,
    )
    from omichub.application.services.agentteams_service import AgentTeamsService
    from omichub.application.services.agentteams_upgrade_advisor import (
        AgentTeamsUpgradeService,
    )
    from omichub.core.config import get_settings

    session = await _get_owned_session(db, session_id, current_user_id)
    if req.action == "dismiss":
        return await AgentTeamsUpgradeService(db, agentteams=None).dismiss(session)
    settings = get_settings()
    runtime = await AgentTeamsBridgeSettingsService(db, settings).get_runtime_config()
    agentteams = AgentTeamsService(settings, runtime)
    return await AgentTeamsUpgradeService(db, agentteams).accept(session, current_user_id)


# ============================================================
# 可用模型列表（供前端选择模型下拉框）
# ============================================================

@router.get("/models", summary="可用模型列表")
async def list_models(db: DbSession) -> list[dict]:

    from omichub.infrastructure.database.models.ai_provider import AIProviderConfigModel

    result = await db.execute(
        select(AIProviderConfigModel)
        .where(AIProviderConfigModel.is_active == True)  # noqa: E712
        .order_by(AIProviderConfigModel.is_default.desc(), AIProviderConfigModel.name)
    )
    configs = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "model": c.model,
            "provider_type": c.provider_type,
            "is_default": c.is_default,
            "temperature": c.temperature,
            "max_tokens": c.max_tokens,
        }
        for c in configs
    ]


# ============================================================
# 会话管理
# ============================================================


@router.post("/sessions", response_model=ChatSessionDTO, summary="创建会话")
async def create_session(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    req: CreateSessionRequest,
) -> ChatSessionDTO:
    return await service.create_session(
        current_user_id,
        req.model_id,
        req.title or "新对话",
        req.assistant_id,
        project_id=req.project_id,
    )


@router.get("/sessions", response_model=list[ChatSessionDTO], summary="会话列表")
async def list_sessions(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ChatSessionDTO]:
    return await service.list_sessions(current_user_id, limit=limit, offset=offset)


@router.get("/sessions/search", response_model=ChatSessionSearchDTO, summary="搜索会话")
async def search_sessions(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    keyword: str = Query(..., min_length=1, max_length=80),
) -> ChatSessionSearchDTO:
    return await service.search_sessions(current_user_id, keyword)


@router.get(
    "/sessions/{session_id}/messages", response_model=list[ChatMessageDTO], summary="会话消息"
)
async def get_messages(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> list[ChatMessageDTO]:
    session = await service.get_session(session_id, current_user_id)
    if not session:
        from omichub.core.exceptions import NotFoundError

        raise NotFoundError("会话不存在或无权访问")
    return await service.get_messages(session_id, current_user_id)


@router.get(
    "/sessions/{session_id}/handoffs",
    response_model=list[ChatHandoffEventDTO],
    summary="会话 Agent 转交审计",
)
async def get_session_handoffs(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> list[ChatHandoffEventDTO]:
    return await service.get_handoff_events(session_id, current_user_id)


# ============================================================
# 消息反馈（点赞 / 点踩）
# ============================================================

_FEEDBACK_EXCERPT_LEN = 800


async def _get_owned_session(db: DbSession, session_id: str, user_id: str):
    from omichub.core.exceptions import NotFoundError
    from omichub.infrastructure.database.models.chat import ChatSessionModel

    session = (
        await db.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id,
                ChatSessionModel.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not session:
        raise NotFoundError("会话不存在或无权访问")
    return session


@router.put(
    "/sessions/{session_id}/messages/{message_id}/feedback",
    summary="消息反馈（点赞 / 点踩 / 撤销）",
)
async def submit_message_feedback(
    current_user_id: CurrentUserId,
    db: DbSession,
    session_id: str,
    message_id: str,
    req: MessageFeedbackRequest,
) -> dict:
    """点赞/点踩 AI 消息。点踩时服务端快照当时的模型、Agent、回复与提问上下文，
    供管理员在会话日志排查中分析并优化提示词 / Agent / 架构。rating=none 撤销反馈。"""
    import uuid as uuid_mod

    from omichub.infrastructure.database.models.chat import (
        ChatMessageFeedbackModel,
        ChatMessageModel,
    )

    session = await _get_owned_session(db, session_id, current_user_id)
    message = (
        await db.execute(
            select(ChatMessageModel).where(
                ChatMessageModel.session_id == session_id,
                ChatMessageModel.message_id == message_id,
            )
        )
    ).scalar_one_or_none()
    if not message:
        from omichub.core.exceptions import NotFoundError

        raise NotFoundError("消息不存在")

    existing = (
        await db.execute(
            select(ChatMessageFeedbackModel).where(
                ChatMessageFeedbackModel.message_id == message_id,
                ChatMessageFeedbackModel.user_id == current_user_id,
            )
        )
    ).scalar_one_or_none()

    if req.rating == "none":
        if existing:
            await db.delete(existing)
        return {"feedback": None}

    meta = message.metadata_json or {}
    context: dict = {}
    if req.rating == "dislike":
        # 找到该回复前最近的一条用户提问，作为优化分析的上下文
        prev_user = (
            await db.execute(
                select(ChatMessageModel)
                .where(
                    ChatMessageModel.session_id == session_id,
                    ChatMessageModel.role == "user",
                    ChatMessageModel.created_at <= message.created_at,
                )
                .order_by(ChatMessageModel.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        context = {
            "session_mode": session.mode,
            "execution_hint": {
                "assistant_id": session.assistant_id,
                "agent_id": session.agent_id,
                "overdrive": bool((session.sandbox_meta or {}).get("overdrive_used")),
                "sender_agent": meta.get("senderAgent"),
            },
            "model": meta.get("model") or meta.get("modelName") or "",
            "message_excerpt": (message.content or "")[:_FEEDBACK_EXCERPT_LEN],
            "user_question_excerpt": ((prev_user.content or "")[:_FEEDBACK_EXCERPT_LEN])
            if prev_user
            else "",
            "message_status": message.status,
        }

    if existing:
        existing.rating = req.rating
        existing.comment = req.comment
        if context:
            existing.context = context
    else:
        db.add(
            ChatMessageFeedbackModel(
                feedback_id=f"fb-{uuid_mod.uuid4().hex}",
                session_id=session_id,
                message_id=message_id,
                user_id=current_user_id,
                rating=req.rating,
                comment=req.comment,
                context=context,
            )
        )
    return {"feedback": {"rating": req.rating}}


@router.get(
    "/sessions/{session_id}/feedbacks",
    summary="会话消息反馈状态（message_id → rating）",
)
async def get_session_feedbacks(
    current_user_id: CurrentUserId,
    db: DbSession,
    session_id: str,
) -> dict[str, str]:
    """前端加载历史消息后，用它恢复每条 AI 消息的点赞/点踩高亮状态。"""
    from omichub.infrastructure.database.models.chat import ChatMessageFeedbackModel

    await _get_owned_session(db, session_id, current_user_id)
    rows = (
        await db.execute(
            select(ChatMessageFeedbackModel.message_id, ChatMessageFeedbackModel.rating).where(
                ChatMessageFeedbackModel.session_id == session_id,
                ChatMessageFeedbackModel.user_id == current_user_id,
            )
        )
    ).all()
    return {row.message_id: row.rating for row in rows}


@router.put("/sessions/{session_id}/title", summary="更新标题")
async def update_title(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    title: str = Query(..., min_length=1, max_length=200),
) -> dict[str, bool]:
    await service.update_session_title(session_id, current_user_id, title)
    return {"success": True}


@router.patch("/sessions/{session_id}", response_model=ChatSessionDTO, summary="重命名会话")
async def patch_session(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    req: UpdateSessionRequest,
) -> ChatSessionDTO:
    return await service.update_session_title(session_id, current_user_id, req.title, locked=True)


@router.post("/sessions/{session_id}/generate-title", response_model=dict, summary="生成会话标题")
async def generate_title(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> dict[str, str]:
    title = await service.generate_session_title(session_id, current_user_id)
    return {"title": title}


@router.delete("/sessions/{session_id}", summary="删除会话")
async def delete_session(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> dict[str, bool]:
    await service.delete_session(session_id, current_user_id)
    return {"success": True}


# ============================================================
# 助手管理
# ============================================================


@router.get("/assistants", response_model=list[ChatAssistantDTO], summary="助手列表")
async def list_assistants(
    service: ChatServiceDep,
    category: str | None = Query(None),
) -> list[ChatAssistantDTO]:
    return await service.list_assistants(category)


@router.get("/assistants/{assistant_id}", response_model=ChatAssistantDTO, summary="助手详情")
async def get_assistant(service: ChatServiceDep, assistant_id: str) -> ChatAssistantDTO:
    return await service.get_assistant_dto(assistant_id)


@router.post("/assistants", response_model=ChatAssistantDTO, summary="创建自定义助手")
async def create_assistant(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    req: CreateAssistantRequest,
) -> ChatAssistantDTO:
    return await service.create_custom_assistant(
        user_id=current_user_id,
        assistant_id=req.assistant_id,
        name=req.name,
        description=req.description,
        system_prompt=req.system_prompt,
        default_temperature=req.default_temperature,
        default_max_tokens=req.default_max_tokens,
        icon=req.icon,
        color=req.color,
        category=req.category,
    )


# ============================================================
# 公开技能列表（供前端插件下拉，仅返回启用的）
# ============================================================


@router.get("/skills", response_model=list[SkillDTO], summary="技能列表（启用）")
async def list_active_skills(
    current_user_id: CurrentUserId,
    db: DbSession,
) -> list[SkillDTO]:
    from omichub.application.services.skill_service import SkillService
    from omichub.infrastructure.database.models.user import UserModel

    user = await db.get(UserModel, current_user_id)
    service = SkillService(db)
    return await service.list_skills(
        active_only=True,
        user_id=str(current_user_id),
        is_admin=bool(user and user.role == "admin"),
    )
