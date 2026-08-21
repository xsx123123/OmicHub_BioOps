"""Authenticated read-only Case views backed by the external AgentTeams Bridge."""

from __future__ import annotations

import hmac
import json
import mimetypes
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.agent_consultation_service import (
    AgentConsultationService,
    ConsultationEnvelope,
)
from omichub.application.services.agentteams_audit_chain_service import (
    AgentTeamsAuditChainService,
)
from omichub.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeSettingsService,
)
from omichub.application.services.agentteams_capability_registry import (
    get_agentteams_capability_registry,
)
from omichub.application.services.agentteams_case_tool_service import AgentTeamsCaseToolService
from omichub.application.services.agentteams_room_response_service import (
    DEFAULT_MANAGER_DISPLAY_NAME,
    MANAGER_ROOM_ROLE,
)
from omichub.application.services.agentteams_room_service import AgentTeamsRoomService
from omichub.application.services.agentteams_service import (
    AUTO_CONFIRM_CASES_KEY,
    AgentTeamsService,
)
from omichub.application.services.flow_registry import get_flow_registry
from omichub.application.services.project_service import ProjectService
from omichub.core.config import get_settings
from omichub.core.exceptions import BusinessError
from omichub.infrastructure.cache.redis_client import get_redis
from omichub.infrastructure.database.models.chat import (
    AgentTeamsRoomModel,
    ChatMessageModel,
    ChatSessionModel,
)
from omichub.infrastructure.database.repositories.user_repository import (
    SqlAlchemyUserRepository,
)
from omichub.infrastructure.storage.minio_store import MinioStore

router = APIRouter()


async def _attach_requester_user_display_info(db: DbSession, items: list[dict[str, Any]]) -> None:
    """按 requester_ref 回填用户展示信息（去重后逐个查询；列表通常只有当前用户，至多一次查询）。

    与 TaskService 的用户展示信息回填同一约定：前端不得直接展示裸 UUID（§33.2 ④）。
    """
    refs = {item.get("requester_ref") for item in items if item.get("requester_ref")}
    if not refs:
        return
    user_repo = SqlAlchemyUserRepository(db)
    users: dict[str, tuple[str, str | None]] = {}
    for ref in refs:
        try:
            user = await user_repo.get_by_id(UUID(ref))
        except ValueError:
            continue
        if user is not None:
            users[ref] = (user.username, user.nickname)
    for item in items:
        user = users.get(item.get("requester_ref") or "")
        if user:
            item["requester_username"], item["requester_nickname"] = user


async def get_agentteams_service(db: DbSession) -> AgentTeamsService:
    settings = get_settings()
    bridge_config = await AgentTeamsBridgeSettingsService(db, settings).get_runtime_config()
    return AgentTeamsService(settings, bridge_config)


AgentTeamsServiceDep = Annotated[AgentTeamsService, Depends(get_agentteams_service)]


def require_integration_token(
    token: Annotated[str | None, Header(alias="X-Integration-Token")] = None,
) -> None:
    expected = get_settings().agentteams_integration_token
    if not token or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid integration token"
        )


IntegrationTokenRequired = Annotated[None, Depends(require_integration_token)]


@router.get("/capabilities", summary="读取 AgentTeams 运行时能力快照")
async def agentteams_capabilities(
    _integration_token: IntegrationTokenRequired,
) -> dict[str, Any]:
    return get_agentteams_capability_registry().snapshot()


class ScientificInterpretationRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=8_000)
    capability: Literal[
        "interpretation",
        "planning_advice",
        "result_interpretation",
        "qc_advice",
        "project-preflight",
        "quality-gate",
        "delivery-pack",
        "workspace_execution",
    ]
    evidence_refs: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(
        default_factory=list, max_length=50
    )
    requested_tools: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=20
    )
    # Gateway 转发时会携带以下字段；缺失会导致 run_consultation 因缺少
    # requester_ref 抛 TypeError，会诊一律 500 并退化为 manual_review。
    requester_ref: str = Field(min_length=1, max_length=256)
    work_item_id: str | None = Field(default=None, min_length=1, max_length=128)
    execution_mode: Literal["readonly_consultation", "workspace_execution"] = (
        "readonly_consultation"
    )


class AgentTeamsChangeDecisionRequest(BaseModel):
    work_item_ids: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        min_length=1, max_length=100
    )
    decision: Literal["resume", "replan", "branch", "cancel"]
    rationale: str = Field(default="", max_length=4_000)
    requester_ref: str = Field(min_length=1, max_length=256)
    work_item_id: str | None = Field(default=None, min_length=1, max_length=128)
    execution_mode: Literal["readonly_consultation", "workspace_execution"] = "readonly_consultation"


class AgentTeamsContextRef(BaseModel):
    kind: Literal["workspace", "file"]
    id: str = Field(min_length=1, max_length=256)
    location: str | None = Field(default=None, max_length=512)


@router.post(
    "/consultations/scientific-interpretation",
    response_model=ConsultationEnvelope,
    summary="执行 AgentTeams 受控科学会诊",
)
async def scientific_interpretation(
    request: ScientificInterpretationRequest,
    _integration_token: IntegrationTokenRequired,
    db: DbSession,
    agentteams: AgentTeamsServiceDep,
) -> ConsultationEnvelope:
    return await AgentConsultationService(db, agentteams_service=agentteams).run_consultation(
        **request.model_dump()
    )


class AgentTeamsCaseCreateRequest(BaseModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=50)
    project_id: str | None = Field(default=None, min_length=1, max_length=256)
    project_name: str | None = Field(default=None, min_length=1, max_length=200)
    context_refs: list[AgentTeamsContextRef] = Field(default_factory=list, max_length=100)
    intent: str = Field(min_length=1, max_length=256)
    flow_id: str | None = Field(default=None, min_length=1, max_length=128)
    sample_sheet: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)
    comparisons: list[dict[str, Any]] | None = Field(default=None, max_length=1_000)
    origin_consultation_id: str | None = Field(default=None, max_length=256)
    consultation_summary: str | None = Field(default=None, max_length=1_800)

    @model_validator(mode="after")
    def _validate_execution_context(self) -> AgentTeamsCaseCreateRequest:
        if self.flow_id and not self.project_id and not self.project_name:
            raise ValueError("流程型 Case 必须关联项目或提供项目名称")
        # 通用 Case 允许空上下文：端点会为聊天式直发注入发起人工作区只读引用。
        return self


class AgentTeamsCaseSubmitRequest(BaseModel):
    task_name: str = Field(min_length=1, max_length=128)


class AgentTeamsCaseRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=512)


class AgentTeamsQualityGateRequest(BaseModel):
    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    decision: Literal["passed", "blocked", "manual_review"]
    rule_version: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=4_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class AgentTeamsRoomMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4_000)
    # 房间 @ 引用的工作区文件，作为发言补充上下文写入审计 payload（只读引用）。
    context_refs: list[AgentTeamsContextRef] = Field(default_factory=list, max_length=20)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=128)


class AgentTeamsRoomCreateRequest(BaseModel):
    """创建协作室房间（轻量会话实体；立项确认前不创建 Case）。"""

    title: str | None = Field(default=None, max_length=200)
    origin: str = Field(default="manual", min_length=1, max_length=20)


class AgentTeamsProposalConfirmRequest(BaseModel):
    """消费房间立项确认卡：confirm 建 Case 绑定房间；modify/cancel 关闭卡片。

    confirm_token 为可选的二次校验 nonce（复审清单 B1）：token 不再经事件流
    分发，owner + 房间存在 pending 立项卡即可确认；携带 token 时须比对通过。
    """

    confirm_token: str | None = Field(default=None, min_length=20, max_length=256)
    decision: Literal["confirm", "modify", "cancel"]
    # followup 卡（Case 终态后再立项）专用：基于上一 Case 继续 / 新建工单。
    followup_mode: Literal["continue", "new"] | None = None
    note: str | None = Field(default=None, max_length=1_000)


class AgentTeamsPlanRevisionRequest(BaseModel):
    expected_plan_hash: str = Field(min_length=64, max_length=64)
    parameters: dict[str, Any]
    reason: str = Field(min_length=3, max_length=512)


class AgentTeamsCaseConfirmRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=50)
    objective: str = Field(min_length=1, max_length=500)
    project_id: str = Field(min_length=1, max_length=256)
    flow_id: str = Field(min_length=1, max_length=128)
    sample_context_refs: list[AgentTeamsContextRef] = Field(default_factory=list, max_length=100)
    origin_consultation_id: str | None = Field(default=None, max_length=256)
    consultation_summary: str | None = Field(default=None, max_length=1800)
    confirmation_key: str = Field(min_length=64, max_length=64)
    confirmation_token: str = Field(min_length=20, max_length=256)


def _is_chat_case_flow_allowed(flow_id: str) -> bool:
    settings = get_settings()
    configured = {
        item.strip() for item in settings.agentteams_chat_flow_whitelist.split(",") if item.strip()
    }
    return flow_id in configured | get_flow_registry().bridge_flow_ids()


async def _require_owned_project(db: DbSession, user_id: str, project_id: str) -> None:
    """验证项目属于当前请求用户，避免直接 Case API 绕过受控聊天入口。"""
    try:
        owner_id = UUID(user_id)
        owned_project_id = UUID(project_id)
    except ValueError as exc:
        raise BusinessError("项目 ID 无效") from exc
    await ProjectService(db).get_project(owner_id, owned_project_id)


@router.get("/status", summary="获取 AgentTeams Bridge 接入状态")
async def get_status(service: AgentTeamsServiceDep) -> dict[str, bool | str | None]:
    return await service.connection_status()


@router.get("/role-labels", summary="获取 AgentTeams 角色展示元数据")
async def agentteams_role_labels(_current_user_id: CurrentUserId) -> dict[str, Any]:
    """用户态只读端点：供团队协作室渲染发言人名称/头像/颜色。

    同时下发 Manager 展示身份（display_name 的唯一权威来源是 manager agent
    YAML 的 name）：前端仅存储用户手动覆盖值，无覆盖时透传本字段。
    """
    snapshot = get_agentteams_capability_registry().snapshot()
    manager_label = snapshot["role_labels"].get(MANAGER_ROOM_ROLE) or {}
    manager_display_name = (
        str(manager_label.get("name") or "").strip() or DEFAULT_MANAGER_DISPLAY_NAME
    )
    return {
        "role_labels": snapshot["role_labels"],
        "role_agent_map": snapshot["role_agent_map"],
        "manager": {
            "agent_id": get_settings().agentteams_manager_agent_id,
            "display_name": manager_display_name,
        },
    }


@router.get("/cases", summary="获取当前用户的 Agent 协作案例")
async def list_cases(
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    db: DbSession,
    case_status: Annotated[str | None, Query(alias="status")] = None,
    project_id: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    result = await service.list_cases(
        current_user_id,
        case_status=case_status,
        project_id=project_id,
        cursor=cursor,
        limit=limit,
    )
    await _attach_requester_user_display_info(db, result.get("items", []))
    return result


@router.post("/cases", status_code=status.HTTP_201_CREATED, summary="创建当前用户的协作案例")
async def create_case(
    request: AgentTeamsCaseCreateRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    db: DbSession,
) -> dict[str, Any]:
    if request.flow_id and not _is_chat_case_flow_allowed(request.flow_id):
        raise BusinessError("该流程不在 AgentTeams Case 白名单中")
    if request.flow_id and get_agentteams_capability_registry().agent_for_flow(request.flow_id) is None:
        raise BusinessError("该流程没有可用的 active Agent，无法创建协作 Case")
    if request.project_id:
        await _require_owned_project(db, current_user_id, request.project_id)
    elif request.project_name:
        # 聊天式 Case 的项目名由需求文本生成：同名存量项目直接复用，
        # 删除 Case 后用同一需求重新建单不应报"同名项目已存在"。
        project = await ProjectService(db).get_or_create_project_by_name(
            UUID(current_user_id), request.project_name
        )
        request.project_id = str(project["id"])
    elif request.flow_id:
        raise BusinessError("流程型 Case 必须关联项目或提供项目名称")
    session = None
    if request.session_id:
        session = await db.scalar(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == request.session_id,
                ChatSessionModel.user_id == current_user_id,
            )
        )
        if session is None:
            raise BusinessError("聊天会话不存在或无权创建协作 Case")
        if request.project_id and not AgentTeamsCaseToolService._session_owns_project(
            session.sandbox_meta,
            request.project_id,
        ):
            raise BusinessError("项目未绑定到当前受控会话，无法创建协作 Case")
    chat_created = not request.flow_id and not request.project_id
    context_refs = [ref.model_dump(exclude_none=True) for ref in request.context_refs]
    if chat_created and not context_refs:
        # 聊天式直发（无流程、无项目）缺省绑定发起人工作区只读引用，
        # 保持"通用 Case 必须携带上下文"的语义而不让前端伪造引用。
        context_refs = [{"kind": "workspace", "id": current_user_id}]
    case = await service.create_case(
        case_id=f"bioops_{uuid4().hex}",
        project_id=request.project_id,
        project_name=request.project_name,
        context_refs=context_refs,
        intent=request.intent,
        requester_ref=current_user_id,
        flow_id=request.flow_id,
        sample_sheet=request.sample_sheet or None,
        comparisons=request.comparisons,
        origin_consultation_id=request.origin_consultation_id,
        consultation_summary=request.consultation_summary,
        db=db,
    )
    if session is not None:
        meta = dict(session.sandbox_meta or {})
        title = request.intent.strip()[:80]
        key = AgentTeamsCaseToolService._idempotency_key(
            request.intent.strip(), request.project_id or "", request.flow_id or "general"
        )
        AgentTeamsCaseToolService._bind_case(
            meta,
            key,
            str(case["case_id"]),
            title,
            str(case.get("status") or "received"),
        )
        session.sandbox_meta = meta
        session.updated_at = datetime.now(UTC)
        await db.flush()
    await service.provision_case_room(str(case["case_id"]), requester_ref=current_user_id)
    # 聊天式 Case 不再自动确认：计划冻结后由房间内审批卡人工确认（产品决策，
    # 不依赖用户偏好 autonomy 默认值）。beat 的自动确认仅消费存量已标记 Case。
    return case


async def _mark_case_auto_confirm(case_id: str) -> None:
    """把聊天式创建的通用 Case 写入自动确认集合；Redis 异常时降级为人工审批。

    当前已无调用点：新建聊天 Case 一律走房间内人工确认。函数与 beat 消费逻辑
    保留以兼容存量已标记 Case，确认存量消化完毕后可随 beat 分支一并移除。
    """
    try:
        redis = get_redis()
        # redis-py asyncio stub 将 sadd 标为 Awaitable[int] | int，此处必为协程。
        await cast(Awaitable[int], redis.sadd(AUTO_CONFIRM_CASES_KEY, case_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("AgentTeams auto-confirm mark failed for %s: %s", case_id, exc)


@router.post(
    "/cases/confirm",
    status_code=status.HTTP_201_CREATED,
    summary="确认卡直接创建协作案例",
)
async def confirm_case(
    request: AgentTeamsCaseConfirmRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> dict[str, Any]:
    db.add(
        ChatMessageModel(
            message_id=f"case-confirm-{uuid4().hex}",
            session_id=request.session_id,
            role="user",
            content="确认创建协作 Case",
            content_type="text",
            status="complete",
            metadata_json={
                "agentteams_case_confirmation": {
                    "key": request.confirmation_key,
                    "token": request.confirmation_token,
                    "confirmed": True,
                }
            },
        )
    )
    await db.flush()
    return await AgentTeamsCaseToolService().run(
        objective=request.objective,
        project_id=request.project_id,
        flow_id=request.flow_id,
        sample_context_refs=[item.model_dump(exclude_none=True) for item in request.sample_context_refs],
        origin_consultation_id=request.origin_consultation_id,
        consultation_summary=request.consultation_summary,
        context=ToolInvocationContext(
            user_id=current_user_id,
            session_id=request.session_id,
            db=db,
        ),
    )


@router.get("/cases/{case_id}", summary="获取当前用户的 Agent 协作案例详情")
async def get_case(
    case_id: str, current_user_id: CurrentUserId, service: AgentTeamsServiceDep, db: DbSession
) -> dict[str, Any]:
    case = await service.get_case(case_id, current_user_id)
    if case.get("status") == "closed":
        try:
            await service.get_manifest_with_delivery(case_id, current_user_id, db=db)
        except Exception:
            logger.exception("AgentTeams delivery projection failed for case {}", case_id)
    return case


@router.post("/cases/{case_id}/refresh", summary="同步当前协作案例的任务状态")
async def refresh_case(
    case_id: str, current_user_id: CurrentUserId, service: AgentTeamsServiceDep
) -> dict[str, Any]:
    return await service.refresh_case(case_id, current_user_id)


@router.post("/cases/{case_id}/retry", summary="重试执行失败的协作任务")
async def retry_case(
    case_id: str, current_user_id: CurrentUserId, service: AgentTeamsServiceDep
) -> dict[str, Any]:
    return await service.retry_case(case_id, current_user_id)


@router.post("/cases/{case_id}/plan/revise", summary="修改冻结计划白名单参数")
async def revise_case_plan(
    case_id: str,
    request: AgentTeamsPlanRevisionRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    return await service.revise_case_plan(
        case_id,
        current_user_id,
        expected_plan_hash=request.expected_plan_hash,
        parameters=request.parameters,
        reason=request.reason,
    )


@router.get("/cases/{case_id}/manifest", summary="获取当前用户的交付 Manifest")
async def get_manifest(
    case_id: str, current_user_id: CurrentUserId, service: AgentTeamsServiceDep, db: DbSession
) -> dict[str, Any]:
    return await service.get_manifest_with_delivery(case_id, current_user_id, db=db)


@router.get("/cases/{case_id}/capability-check", summary="获取 Flow 交接前能力检查")
async def get_case_capability_check(
    case_id: str,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    case = await service.get_case(case_id, current_user_id)
    flow_id = str(case.get("flow_id") or "")
    if not flow_id:
        return {"flow_id": None, "available": True, "stages": [], "reason": "通用 Case 无专项 Flow"}
    return await service.flow_capability_check(flow_id)


@router.get("/cases/{case_id}/artifacts/{artifact_path:path}", summary="读取当前 Case 的受控产物")
async def get_case_artifact(
    case_id: str,
    artifact_path: str,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    download: bool = False,
) -> Response:
    await service.get_case(case_id, current_user_id)
    normalized = artifact_path.replace("\\", "/").strip("/")
    if not normalized or ".." in normalized.split("/"):
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    settings = get_settings()
    max_bytes = settings.agentteams_artifact_fetch_max_mb * 1024 * 1024
    if normalized.lower().endswith((".html", ".htm")) and not download:
        max_bytes = settings.agentteams_report_preview_max_mb * 1024 * 1024
    try:
        payload = await run_in_threadpool(
            MinioStore(settings).read_case_object,
            case_id,
            normalized,
            max_bytes=max_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid artifact path") from exc
    media_type = mimetypes.guess_type(normalized)[0] or "application/octet-stream"
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if download:
        filename = normalized.rsplit("/", maxsplit=1)[-1].replace('"', "")
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    elif media_type == "text/html":
        headers["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; img-src data: blob:; font-src data:; "
            "style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; "
            "frame-src 'none'; form-action 'none'; base-uri 'none'"
        )
    return Response(content=payload, media_type=media_type, headers=headers)


@router.post(
    "/cases/{case_id}/submit",
    status_code=status.HTTP_201_CREATED,
    summary="人工确认并提交协作任务",
)
async def approve_and_submit_case_task(
    case_id: str,
    request: AgentTeamsCaseSubmitRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    return await service.approve_and_submit_task(
        case_id=case_id,
        requester_ref=current_user_id,
        task_name=request.task_name,
    )


@router.post("/cases/{case_id}/reject", summary="拒绝当前协作案例的待确认计划")
async def reject_case(
    case_id: str,
    request: AgentTeamsCaseRejectRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    return await service.reject_case(case_id, current_user_id, request.reason)


@router.post("/cases/{case_id}/quality-gate", summary="提交质量门禁结论")
async def submit_quality_gate(
    case_id: str,
    request: AgentTeamsQualityGateRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    evidence_refs: list[dict[str, Any]] = []
    for ref in request.evidence_refs:
        kind, _, id_ = ref.partition(":")
        if not kind or not id_:
            raise HTTPException(status_code=400, detail=f"证据引用格式错误: {ref}")
        evidence_refs.append({"kind": kind, "id": id_})
    return await service.submit_quality_gate(
        case_id=case_id,
        requester_ref=current_user_id,
        task_id=request.task_id,
        decision=request.decision,
        rule_version=request.rule_version,
        summary=request.summary,
        evidence_refs=evidence_refs,
    )


@router.post("/cases/{case_id}/cancel", summary="取消当前用户的协作案例")
async def cancel_case(
    case_id: str,
    request: AgentTeamsCaseRejectRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    return await service.cancel_case(case_id, current_user_id, request.reason)


@router.delete("/cases/{case_id}", summary="删除当前用户的协作案例（聊天房间）")
async def delete_case(
    case_id: str,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    return await service.delete_case(case_id, current_user_id)


@router.post(
    "/cases/{case_id}/messages",
    status_code=status.HTTP_201_CREATED,
    summary="向当前协作案例的房间发送用户发言",
)
async def post_case_message(
    case_id: str,
    request: AgentTeamsRoomMessageRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    result = await service.post_room_message(
        case_id,
        current_user_id,
        request.content,
        context_refs=[ref.model_dump(exclude_none=True) for ref in request.context_refs],
        client_message_id=request.client_message_id,
    )
    response_dispatch = "deduplicated" if result.get("deduplicated") else "queued"
    if not result.get("deduplicated"):
        try:
            from omichub.infrastructure.celery_app.tasks.agentteams import respond_to_room_message

            respond_to_room_message.delay(
                case_id,
                current_user_id,
                request.content.strip(),
                result.get("dispatch") if isinstance(result, dict) else None,
            )
        except Exception as exc:  # noqa: BLE001 - Manager 响应调度失败不影响发言落盘
            logger.bind(case_id=case_id).warning(
                "AgentTeams room response dispatch failed: {}", exc
            )
            response_dispatch = "failed"
    return {**result, "response_dispatch": response_dispatch}


def _room_payload(room: AgentTeamsRoomModel) -> dict[str, Any]:
    proposal = room.proposal if isinstance(room.proposal, dict) else None
    pending_proposal = bool(proposal and proposal.get("status") == "pending")
    return {
        "room_id": room.room_id,
        "title": room.title,
        "status": room.status,
        "origin": room.origin,
        "origin_ref": room.origin_ref,
        "case_id": room.case_id,
        "matrix_room_provisioned": bool(room.matrix_room_id),
        "has_pending_proposal": pending_proposal,
        "created_at": room.created_at.isoformat() if room.created_at else None,
        "updated_at": room.updated_at.isoformat() if room.updated_at else None,
    }


@router.post(
    "/rooms",
    status_code=status.HTTP_201_CREATED,
    summary="创建协作室房间（轻量会话实体，立项确认前不创建 Case）",
)
async def create_room(
    request: AgentTeamsRoomCreateRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    db: DbSession,
) -> dict[str, Any]:
    room = await AgentTeamsRoomService(db, service).create_room(
        owner_id=current_user_id, title=request.title, origin=request.origin
    )
    return _room_payload(room)


@router.get("/rooms", summary="获取当前用户的协作室房间列表")
async def list_rooms(
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    db: DbSession,
) -> dict[str, Any]:
    rooms = await AgentTeamsRoomService(db, service).list_rooms(current_user_id)
    return {"items": [_room_payload(room) for room in rooms], "total": len(rooms)}


@router.get("/rooms/{room_id}", summary="获取协作室房间详情")
async def get_room(
    room_id: str,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    db: DbSession,
) -> dict[str, Any]:
    room = await AgentTeamsRoomService(db, service).get_room(room_id, current_user_id)
    return _room_payload(room)


@router.post(
    "/rooms/{room_id}/messages",
    status_code=status.HTTP_201_CREATED,
    summary="向协作室房间发送用户发言（未立项房间落房间级事件流）",
)
async def post_room_message(
    room_id: str,
    request: AgentTeamsRoomMessageRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    db: DbSession,
) -> dict[str, Any]:
    rooms = AgentTeamsRoomService(db, service)
    room = await rooms.get_room(room_id, current_user_id)
    result = await rooms.post_room_message(
        room,
        current_user_id,
        request.content,
        context_refs=[ref.model_dump(exclude_none=True) for ref in request.context_refs],
        client_message_id=request.client_message_id,
    )
    response_dispatch = "deduplicated" if result.get("deduplicated") else "queued"
    if not result.get("deduplicated"):
        try:
            from omichub.infrastructure.celery_app.tasks.agentteams import (
                respond_to_room_namespace_message,
            )

            respond_to_room_namespace_message.delay(
                room.room_id,
                current_user_id,
                request.content.strip(),
                result.get("dispatch") if isinstance(result, dict) else None,
            )
        except Exception as exc:  # noqa: BLE001 - Manager 响应调度失败不影响发言落盘
            logger.bind(room_id=room.room_id).warning(
                "AgentTeams room response dispatch failed: {}", exc
            )
            response_dispatch = "failed"
    return {**result, "response_dispatch": response_dispatch, "room_id": room.room_id}


@router.post(
    "/rooms/{room_id}/confirm-proposal",
    summary="确认/修改/取消房间立项卡（确认后才创建 Case 并绑定房间）",
)
async def confirm_room_proposal(
    room_id: str,
    request: AgentTeamsProposalConfirmRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    db: DbSession,
) -> dict[str, Any]:
    rooms = AgentTeamsRoomService(db, service)
    room = await rooms.get_room(room_id, current_user_id)
    return await rooms.confirm_proposal(
        room,
        current_user_id,
        confirm_token=request.confirm_token,
        decision=request.decision,
        followup_mode=request.followup_mode,
        note=request.note,
    )


@router.get("/rooms/{room_id}/events", summary="获取协作室房间聚合事件（房间级 + 已绑定 Case 级）")
async def get_room_events(
    room_id: str,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    db: DbSession,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1)] = 100,
) -> dict[str, Any]:
    rooms = AgentTeamsRoomService(db, service)
    room = await rooms.get_room(room_id, current_user_id)
    # E2E-2 口径：limit 超上界不对用户报 422，钳制到单页上限 100，
    # 调用方凭 next_cursor 续拉剩余事件。
    return await rooms.get_room_events(
        room, current_user_id, cursor=cursor, limit=min(limit, 100)
    )


@router.get("/rooms/{room_id}/events/stream", summary="实时监听协作室房间聚合事件")
async def stream_room_events(
    room_id: str,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    db: DbSession,
    cursor: str | None = None,
) -> StreamingResponse:
    rooms = AgentTeamsRoomService(db, service)
    room = await rooms.get_room(room_id, current_user_id)

    async def event_generator():
        try:
            async for event in rooms.stream_room_events(room, current_user_id, cursor=cursor):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[AgentTeams] 房间事件流中断（room {room_id[:16]}）: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/cases/{case_id}/change-decisions",
    status_code=status.HTTP_201_CREATED,
    summary="提交运行中工作项的变更决策",
)
async def apply_case_change_decision(
    case_id: str,
    request: AgentTeamsChangeDecisionRequest,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    result = await service.apply_change_decision(
        case_id,
        current_user_id,
        work_item_ids=request.work_item_ids,
        decision=request.decision,
        rationale=request.rationale,
    )
    if request.decision in {"resume", "replan", "branch"}:
        try:
            from omichub.infrastructure.celery_app.tasks.agentteams import respond_to_room_message

            respond_to_room_message.delay(
                case_id,
                current_user_id,
                f"系统决策：用户选择 {request.decision}。请 Manager 根据审计事件继续编排，必要时先补充澄清和审批。",
            )
        except Exception as exc:  # noqa: BLE001 - decision evidence must survive dispatch failure
            logger.bind(case_id=case_id).warning(
                "AgentTeams change decision follow-up dispatch failed: {}", exc
            )
    return result


@router.get("/cases/{case_id}/events", summary="获取协作案例审计事件")
async def get_case_events(
    case_id: str,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> dict[str, Any]:
    return await service.get_case_events(case_id, current_user_id, cursor=cursor, limit=limit)


@router.get(
    "/cases/{case_id}/audit-chain",
    summary="获取协作案例全量业务事件链（含房间关联事件，统一审计总线查询入口）",
)
async def get_case_audit_chain(
    case_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
    service: AgentTeamsServiceDep,
    max_events: Annotated[int, Query(ge=1, le=20000)] = 5000,
) -> dict[str, Any]:
    chain_service = AgentTeamsAuditChainService(db, agentteams=service)
    return await chain_service.get_case_audit_chain(
        case_id, current_user_id, max_events=max_events
    )


@router.get("/cases/{case_id}/response-timing", summary="获取协作案例响应耗时摘要")
async def get_case_response_timing(
    case_id: str,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
) -> dict[str, Any]:
    return await service.get_room_response_timing_summary(case_id, current_user_id)


@router.get("/cases/{case_id}/events/stream", summary="实时监听当前用户的协作案例事件")
async def stream_case_events(
    case_id: str,
    current_user_id: CurrentUserId,
    service: AgentTeamsServiceDep,
    cursor: str | None = None,
) -> StreamingResponse:
    async def event_generator():
        # StreamingResponse 在开始迭代前就已发送响应头，生成器内抛出的异常
        # 会被 starlette 包装成 "response already started" 并刷错误日志；
        # 这里转为一条 error 事件，前端按既有重连逻辑处理即可。
        try:
            async for event in service.stream_case_events(case_id, current_user_id, cursor=cursor):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[AgentTeams] 案例事件流中断（case {case_id[:16]}）: {exc}"
            )
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
