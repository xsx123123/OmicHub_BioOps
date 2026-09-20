"""OmicStudio AI 分析工作台 API 路由

API 前缀：/api/v1/studio
会话创建 / 列表 / 详情、工作区文件、代码重跑（SSE）、产物清单与下载。

Studio 聊天本身复用 POST /chat/stream（前端传 session_id，mode 由会话行决定），
本路由不再重复实现聊天流。工作区文件操作：沙盒容器运行中走 sandbox-agent，
容器停止时直接读宿主磁盘（bind-mount 同源），路径规则与容器内一致。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import quote

import aiohttp
import httpx
from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from loguru import logger
from sqlalchemy import select
from sqlalchemy import text as sql_text

from cygnusx.api.deps import CurrentUserId, DbSession, get_active_user_from_token_payload
from cygnusx.application.schemas.chat import ChatSessionDTO
from cygnusx.application.schemas.skill import SkillDTO
from cygnusx.application.schemas.studio import (
    CreateStudioSessionFromReportRequest,
    CreateStudioSessionRequest,
    CreateStudioShareRequest,
    EditStudioFileRequest,
    EditStudioFileResponse,
    ExtractStudioSkillRequest,
    ImportStudioDataFileRequest,
    ImportStudioDataFileResponse,
    PromoteStudioSessionRequest,
    RegisterStudioArtifactRequest,
    RegisterStudioArtifactResponse,
    RenameStudioFileRequest,
    SaveStudioFileRequest,
    SaveStudioFileResponse,
    SharedStudioSessionDTO,
    StudioApprovalApproveRequest,
    StudioApprovalRejectRequest,
    StudioInternalExecRequest,
    StudioPathRequest,
    StudioRunRequest,
    StudioSessionDetailDTO,
    StudioShareResponse,
    StudioShareStatusDTO,
    UpdateStudioPermissionsRequest,
    UpdateStudioUiRequest,
)
from cygnusx.application.services.agent_service import AgentService
from cygnusx.application.services.chat_service import ChatService
from cygnusx.application.services.project_scope import resolve_agent_project_scope
from cygnusx.application.services.skill_service import SkillService
from cygnusx.application.services.studio_approval_service import (
    get_studio_approval_service,
    record_approval_audit,
)
from cygnusx.application.services.studio_checkpoints import (
    ensure_checkpoint_repository,
    list_checkpoints,
    restore_checkpoint,
)
from cygnusx.application.services.studio_context_service import (
    create_session_from_report,
    import_datahub_file,
    register_artifact_report,
    user_platform_root,
)
from cygnusx.application.services.studio_sharing import (
    build_shared_snapshot,
    create_share,
    get_shared_session,
    render_printable_report,
    resolve_shared_artifact,
    revoke_share,
    share_is_active,
)
from cygnusx.application.services.studio_skill_service import extract_skill_from_workspace
from cygnusx.application.services.studio_tools import stream_studio_tool
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import (
    AuthenticationError,
    BusinessError,
    ConflictError,
    NotFoundError,
)
from cygnusx.core.security import decode_token
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk
from cygnusx.infrastructure.config.runtime_image_loader import (
    get_runtime_images,
    resolve_studio_image,
)
from cygnusx.infrastructure.config.studio_loader import get_studio_config
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.infrastructure.storage import get_path_factory, get_storage_backend
from cygnusx.infrastructure.studio.audit import emit as emit_audit
from cygnusx.infrastructure.studio.control_client import resolve_studio_control_token
from cygnusx.infrastructure.studio.manager import (
    StudioSandboxUnavailableError,
    studio_sandbox_manager,
)
from cygnusx.infrastructure.studio.paths import PathEscapeError, resolve_workspace_read_path
from cygnusx.infrastructure.studio.workspace import (
    DEFAULT_READ_LIMIT,
    MAX_READ_LIMIT,
    disk_list_files,
    disk_read_file,
    relative_workspace_path,
    resolve_artifact_path,
)

router = APIRouter()


def get_chat_service(db: DbSession) -> ChatService:
    return ChatService(db)


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def _validate_studio_control_token(token: str | None) -> None:
    import hmac

    expected = resolve_studio_control_token(get_settings())
    if not token or not hmac.compare_digest(token, expected):
        raise AuthenticationError("Studio 内部控制令牌无效")


# ============================================================
# 内部辅助
# ============================================================


async def _get_studio_session(
    service: ChatService, session_id: str, user_id: str
) -> ChatSessionModel:
    """取会话并校验归属与 studio 模式；不满足一律 404，不泄露会话存在性。"""
    session = await service.get_session(session_id, user_id)
    if session is None or session.mode != "studio":
        raise NotFoundError("Studio 会话不存在或无权访问")
    return session


def _sandbox_image(session: ChatSessionModel) -> str | None:
    """会话创建时解析并存入 sandbox_meta 的沙盒镜像（None 走默认镜像）。"""
    return (session.sandbox_meta or {}).get("image")


def _normalize_sandbox_capabilities(values: list[str] | None) -> list[str]:
    """规范运行时沙盒能力，始终保留基础代码执行能力。"""
    normalized = list(dict.fromkeys(str(value).strip().lower() for value in values or ["code"]))
    if "code" not in normalized:
        normalized.insert(0, "code")
    return normalized


def _session_sandbox_capabilities(session: ChatSessionModel) -> list[str]:
    """读取已持久化的运行时能力；历史 Studio 会话默认仅代码执行。"""
    return _normalize_sandbox_capabilities(
        (session.sandbox_meta or {}).get("sandbox_capabilities")
    )


_prewarm_tasks: set[asyncio.Task[None]] = set()


def _schedule_sandbox_prewarm(
    session_id: str,
    user_id: str,
    image: str | None,
    *,
    agent_id: str | None = None,
    capabilities: list[str] | None = None,
) -> None:
    """创建会话后后台启动其专属容器，不阻塞 API 响应。

    plain Docker 的 bind mount 与用户只读挂载都在容器创建时固定，不能安全地把一个
    通用 standby 容器改绑给另一用户；因此采用会话级预热，保持一会话一容器隔离。
    """
    if not get_studio_config().session.prewarm_on_create:
        return

    async def _prewarm() -> None:
        try:
            await studio_sandbox_manager.ensure_running(
                session_id,
                image=image,
                user_id=user_id,
                agent_id=agent_id,
                capabilities_requested=capabilities,
            )
            logger.info(f"[Studio] 会话 {session_id[:8]} 专属沙盒预热完成")
        except Exception as exc:  # noqa: BLE001 - 预热失败不影响会话创建与后续懒启动
            logger.warning(f"[Studio] 会话 {session_id[:8]} 沙盒预热失败，保留懒启动: {exc}")

    task = asyncio.create_task(_prewarm())
    _prewarm_tasks.add(task)
    task.add_done_callback(_prewarm_tasks.discard)


async def _workspace_listing(session: ChatSessionModel, path: str = "") -> dict[str, Any]:
    """工作区目录列表：沙盒运行中走 agent（agent 异常回退磁盘），否则读宿主磁盘。

    工作区尚未创建（会话从未执行过）时返回空根目录，前端文件树显示为空。
    input/ 下平台软链经 platform_host_root 翻译后可正常列出（只读语义）。
    """
    session_id = session.session_id
    image = _sandbox_image(session)
    if await studio_sandbox_manager.status(session_id) == "running":
        try:
            return await studio_sandbox_manager.list_files(
                session_id, path, image=image, user_id=session.user_id
            )
        except Exception as e:  # noqa: BLE001 - agent 异常时磁盘回退，语义一致
            logger.warning(f"[Studio] agent 目录列表失败，回退磁盘（会话 {session_id[:8]}）: {e}")
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    factory = get_path_factory()
    backend = get_storage_backend()
    workspace_info = await backend.stat(factory.relative_to_root(workspace))
    if workspace_info is None or not workspace_info.get("is_dir"):
        if path:
            raise NotFoundError(f"路径不存在: {path}")
        return {"path": "", "entries": []}
    try:
        return await disk_list_files(workspace, path, platform_host_root=user_platform_root(session.user_id))
    except PathEscapeError as e:
        raise BusinessError(str(e)) from e


async def _workspace_read(
    session: ChatSessionModel, path: str, offset: int, limit: int
) -> dict[str, Any]:
    """分页读文件：沙盒运行中走 agent，否则读宿主磁盘（同样的路径约束与分页规则）。"""
    session_id = session.session_id
    image = _sandbox_image(session)
    if await studio_sandbox_manager.status(session_id) == "running":
        try:
            return await studio_sandbox_manager.read_file(
                session_id, path, offset=offset, limit=limit, image=image, user_id=session.user_id
            )
        except Exception as e:  # noqa: BLE001 - agent 异常时磁盘回退，语义一致
            logger.warning(f"[Studio] agent 读文件失败，回退磁盘（会话 {session_id[:8]}）: {e}")
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    try:
        return await disk_read_file(
            workspace, path, offset=offset, limit=limit,
            platform_host_root=user_platform_root(session.user_id),
        )
    except PathEscapeError as e:
        raise BusinessError(str(e)) from e


# ============================================================
# Worker -> Web 内部沙盒控制面（不授予 Worker Docker socket）
# ============================================================


@router.post("/internal/sessions/{session_id}/exec", include_in_schema=False)
async def internal_studio_exec(
    session_id: str,
    req: StudioInternalExecRequest,
    control_token: Annotated[
        str | None, Header(alias="X-CygnusX-Studio-Control-Token")
    ] = None,
) -> StreamingResponse:
    _validate_studio_control_token(control_token)

    async def event_stream():
        async for event in studio_sandbox_manager.exec(
            session_id,
            req.language,
            req.code,
            timeout_sec=req.timeout_sec,
            image=req.image,
            user_id=req.user_id,
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/internal/recycle-idle", include_in_schema=False)
async def internal_recycle_idle_studio_sandboxes(
    control_token: Annotated[
        str | None, Header(alias="X-CygnusX-Studio-Control-Token")
    ] = None,
) -> dict[str, int]:
    _validate_studio_control_token(control_token)
    return {"recycled": await studio_sandbox_manager.recycle_idle()}


@router.delete(
    "/internal/sessions/{session_id}/workspace",
    include_in_schema=False,
)
async def internal_cleanup_studio_workspace(
    session_id: str,
    control_token: Annotated[
        str | None, Header(alias="X-CygnusX-Studio-Control-Token")
    ] = None,
) -> dict[str, str]:
    _validate_studio_control_token(control_token)
    return {"status": await studio_sandbox_manager.purge_workspace(session_id)}


# ============================================================
# 公开只读分享（令牌自行鉴权，AuthMiddleware 对该前缀放行）
# ============================================================


@router.get(
    "/shared/{token}",
    response_model=SharedStudioSessionDTO,
    summary="读取公开 Studio 分享快照",
)
async def get_shared_studio_session(token: str, db: DbSession) -> SharedStudioSessionDTO:
    session = await get_shared_session(db, token)
    return await build_shared_snapshot(db, session)


@router.get("/shared/{token}/artifacts", summary="下载公开分享中的 output 产物")
async def download_shared_studio_artifact(
    token: str, db: DbSession, path: str = Query(..., min_length=1)
) -> FileResponse:
    session = await get_shared_session(db, token)
    target = resolve_shared_artifact(session, path)
    return FileResponse(target, filename=target.name)


@router.get(
    "/shared/{token}/report",
    response_class=HTMLResponse,
    summary="公开分享的打印版报告",
)
async def get_shared_studio_report(token: str, db: DbSession) -> HTMLResponse:
    session = await get_shared_session(db, token)
    snapshot = await build_shared_snapshot(db, session)
    return HTMLResponse(render_printable_report(snapshot))

# ============================================================
# 会话管理
# ============================================================


@router.post("/sessions", response_model=ChatSessionDTO, summary="创建 Studio 会话")
async def create_studio_session(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    req: CreateStudioSessionRequest,
) -> ChatSessionDTO:
    """创建 mode="studio" 的工作台会话。

    复用聊天会话创建逻辑，workspace_id 取会话 ID（沙盒容器与工作区均按此命名）；
    Agent yaml studio.image 解析后存入 sandbox_meta，供后续沙盒懒启动使用。
    Agent 未声明 studio 段时默认开放（P0），显式 enabled: false 才拒绝。

    镜像优先级（这里是防止回归的关键契约）：

    1. 请求中的 ``runtime_profile``：用户明确指定，最高优先级；
    2. 请求中的 ``sandbox_capabilities``：用户明确要求额外能力时，按能力选择；
    3. Agent 的 ``studio.image``：Agent 配置的默认专用镜像；
    4. Agent 的 ``studio.runtime_profile``：用于修复旧数据库记录只有 profile、没有
       image 的情况；
    5. 以上都没有才允许后续沙盒管理器使用全局默认镜像。

    绝不能因为请求未传能力列表就自动补成 ``code+browser+document``，也不能在
    profile/image 解析失败时静默回退到 ``analysis-core``。这两种回退会把可视化
    任务错误地放进通用容器，而且错误通常只会在 R/patchwork 执行时才暴露。
    后续如需调整优先级、默认能力或回退策略，必须先向用户询问并确认，不要凭
    “兼容旧客户端”自行修改。
    """
    agent_service = AgentService(db)
    agent = await agent_service.get_agent(req.agent_id)
    if agent is None or not agent.is_active:
        raise NotFoundError("Agent 不存在或已停用")
    studio_cfg = (agent.features or {}).get("studio") or {}
    if studio_cfg and studio_cfg.get("enabled") is False:
        raise BusinessError("该 Agent 未启用 Studio 工作台")

    model_id = req.model_id or await agent_service.resolve_model_id_for_agent(agent)
    if model_id is None:
        raise BusinessError("Agent 未绑定模型，请显式指定 model_id")

    # 能力列表是可选覆盖项。未提供时必须尊重 Agent YAML 的 runtime_profile/image；
    # 旧的默认值 [code,browser,document] 会把 agent-viz 等所有 Agent 错配到
    # browser-office，绕过已构建的 analysis-plot / analysis-scrna 镜像。
    # 这是有意保留 None，而不是立即规范化成 ["code"]：None 表示“没有覆盖意图”，
    # 后面仍要走 Agent 专用镜像分支。若修改此处，请先向用户确认镜像选择语义。
    requested_capabilities = (
        _normalize_sandbox_capabilities(req.sandbox_capabilities)
        if req.sandbox_capabilities is not None
        else None
    )
    allowed_capabilities = _normalize_sandbox_capabilities(
        studio_cfg.get("sandbox_capabilities") or ["code", "browser", "document"]
    )
    if requested_capabilities is not None and not set(requested_capabilities).issubset(
        set(allowed_capabilities)
    ):
        emit_audit(
            "sandbox.capability_denied",
            session_id=None,
            user_id=current_user_id,
            agent_id=req.agent_id,
            capabilities_requested=requested_capabilities,
            policy_result={
                "allowed": allowed_capabilities,
                "reason": "requested capability is not authorized",
            },
        )
        raise BusinessError("请求的沙盒能力未获该 Agent 授权")

    # 默认先取 Agent 的 image；只有显式 runtime_profile 或显式能力覆盖才替换它。
    # 不要把这一行改成 `get_studio_config().default_image`，全局默认只是最终兜底，
    # 不是 Agent 的运行时画像。
    image = resolve_studio_image(studio_cfg)
    if req.runtime_profile and req.runtime_profile.strip():
        # 显式指定的运行时 profile 优先于按能力匹配的镜像
        try:
            _, selected_profile = get_runtime_images().select(
                set(), "studio", preferred_profile=req.runtime_profile.strip()
            )
            image = selected_profile.image
        except (KeyError, ValueError) as exc:
            raise BusinessError(f"运行时选择失败：{exc}") from exc
    elif requested_capabilities is not None:
        # 这是用户主动提出能力覆盖后的分支。能力匹配可以选择 browser-office，
        # 但只能在请求明确包含 browser/document 时发生，不能作为 Agent 默认路径。
        image = get_studio_config().image_for_capabilities(requested_capabilities)
        if not image:
            raise BusinessError("当前部署未配置覆盖所请求能力的 Studio 沙盒镜像")
    # Agent image is the default. If a stale DB row has only runtime_profile,
    # resolve it here rather than falling back to the global core image.
    # 这段是兼容旧数据库记录，不是允许修改 Agent 画像的入口；如需改变兼容策略，
    # 先向用户报告受影响的 Agent/session 范围并询问确认。
    # resolve_studio_image 已处理旧记录的 runtime_profile-only 形态；这里保留
    # image=None 表示 Agent 没有画像，才允许沙盒管理器采用全局默认镜像。
    title = req.title or f"与 {agent.name} 的工作台"
    project_id = resolve_agent_project_scope(
        agent_project_id=agent.project_id,
        session_project_id=req.project_id,
    )
    dto = await service.create_session(
        current_user_id,
        model_id,
        title,
        agent_id=req.agent_id,
        mode="studio",
        sandbox_meta={
            "image": image,
            **(
                {
                    "sandbox_capabilities": requested_capabilities
                    or get_studio_config().capabilities_for_image(image)
                }
                if image
                else {}
            ),
        },
        project_id=project_id,
    )
    await asyncio.to_thread(ensure_checkpoint_repository, dto.session_id)
    _schedule_sandbox_prewarm(
        dto.session_id,
        current_user_id,
        image,
        agent_id=req.agent_id,
        capabilities=requested_capabilities,
    )
    return dto


@router.post(
    "/sessions/{session_id}/promote",
    response_model=ChatSessionDTO,
    summary="将普通聊天会话升级为 Studio 工作台（保留历史消息）",
)
async def promote_session_to_studio(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
    req: PromoteStudioSessionRequest | None = None,
) -> ChatSessionDTO:
    """把已有普通会话就地升级为 mode="studio"，消息记录完整保留。

    用于"路由/交接命中默认工作台的 Agent 后自动进入工作台"的场景：
    不新建空白会话，沙盒按会话 ID 懒启动/预热。可选 agent_id 将会话
    重绑定到目标 Agent（路由场景下会话仍绑定 router），其 studio.image
    写入 sandbox_meta 供沙盒懒启动。
    """
    session = await service.get_session(session_id, current_user_id)
    if session is None:
        raise NotFoundError("会话不存在或已被删除")

    target_agent_id = (req.agent_id if req else None) or session.agent_id
    image: str | None = None
    runtime_profile = (req.runtime_profile if req else None) or ""
    if runtime_profile.strip():
        # 显式指定的运行时 profile 优先于目标 Agent 的 studio.image。
        # 这是用户主动覆盖，不是路由器或 Agent 可以自行改变的默认值；若要扩展
        # 这个入口，请先询问用户并说明会重建当前会话容器。
        try:
            _, selected_profile = get_runtime_images().select(
                set(), "studio", preferred_profile=runtime_profile.strip()
            )
            image = selected_profile.image
        except (KeyError, ValueError) as exc:
            raise BusinessError(f"运行时选择失败：{exc}") from exc
    elif target_agent_id:
        agent = await AgentService(db).get_agent(target_agent_id)
        if agent is not None:
            # 路由/交接升级时沿用目标 Agent 的专用镜像，避免把可视化交接留在
            # 源 Agent 的 analysis-core 容器中。旧记录若只有 profile，则解析 profile。
            studio_cfg = (agent.features or {}).get("studio") or {}
            image = resolve_studio_image(studio_cfg)

    if session.mode == "studio":
        await asyncio.to_thread(ensure_checkpoint_repository, session.session_id)
        return ChatService._to_session_dto(session)

    if target_agent_id:
        session.agent_id = target_agent_id
    session.mode = "studio"
    session.workspace_id = session.workspace_id or session.session_id
    if image:
        # sandbox_meta 可能被进行中的聊天流并发写入（plan 等键），
        # image 键用 jsonb_set 原子写入，避免整体回写擦除并发更新
        await db.execute(
            sql_text(
                "UPDATE chat_sessions SET sandbox_meta = jsonb_set("
                "COALESCE(sandbox_meta, '{}'::jsonb), '{image}', "
                "to_jsonb(CAST(:image AS text)), true) WHERE session_id = :sid"
            ),
            {"image": image, "sid": session_id},
        )
    session.updated_at = datetime.now(UTC)
    await db.flush()
    await asyncio.to_thread(ensure_checkpoint_repository, session.session_id)

    _schedule_sandbox_prewarm(session.session_id, current_user_id, image)
    return ChatService._to_session_dto(session)


@router.post("/sessions/from-report", response_model=ChatSessionDTO, summary="从报告创建 Studio 会话")
async def create_studio_session_from_report(
    current_user_id: CurrentUserId,
    db: DbSession,
    req: CreateStudioSessionFromReportRequest,
) -> ChatSessionDTO:
    """结果报告中心「在 AI 工作台中优化」入口（Context Packager，§7.2）。

    打包来源流程 / run_id / 参数 / 产物文件（软链进 /workspace/input/），
    context_pack 写入会话 sandbox_meta，聊天时注入系统提示词。
    """
    dto = await create_session_from_report(
        current_user_id, req.report_id, req.agent_id, db
    )
    session = await ChatService(db).get_session(dto.session_id, current_user_id)
    await asyncio.to_thread(ensure_checkpoint_repository, dto.session_id)
    _schedule_sandbox_prewarm(
        dto.session_id, current_user_id, _sandbox_image(session) if session else None
    )
    return dto


@router.get("/runtime-profiles", summary="可用 Studio 运行时 profile 列表")
async def list_runtime_profiles(current_user_id: CurrentUserId) -> list[dict[str, Any]]:
    """向前端运行时选择器暴露 runtime_images.yaml 中注册的 profile。"""
    registry = get_runtime_images()
    profiles: list[dict[str, Any]] = []
    for profile_id in registry.profiles:
        profile = registry.resolved_profile(profile_id)
        profiles.append(
            {
                "id": profile_id,
                "name": profile.name,
                "description": profile.description,
                "image": profile.image,
                "capabilities": sorted(profile.capabilities),
                "executor_compatibility": sorted(profile.executor_compatibility),
                "is_default": profile_id == registry.selection.default_profile,
            }
        )
    return profiles


@router.get("/sessions", response_model=list[ChatSessionDTO], summary="Studio 会话列表")
async def list_studio_sessions(
    current_user_id: CurrentUserId, service: ChatServiceDep
) -> list[ChatSessionDTO]:
    return await service.list_sessions(current_user_id, mode="studio")


@router.get(
    "/sessions/{session_id}",
    response_model=StudioSessionDetailDTO,
    summary="Studio 会话详情",
)
async def get_studio_session(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> StudioSessionDetailDTO:
    """会话详情 + 沙盒状态 + 工作区根目录文件树（沙盒停止时读宿主磁盘）+ 当前待办计划。"""
    session = await _get_studio_session(service, session_id, current_user_id)
    sandbox_status = await studio_sandbox_manager.status(session_id)
    sandbox_metrics = await studio_sandbox_manager.metrics(session_id)
    listing = await _workspace_listing(session, "")
    return StudioSessionDetailDTO(
        session=ChatService._to_session_dto(session),
        sandbox_status=sandbox_status,
        workspace_id=session.workspace_id,
        files=listing.get("entries") or [],
        plan=(session.sandbox_meta or {}).get("plan"),
        capabilities=(session.sandbox_meta or {}).get("capabilities"),
        sandbox_capabilities=_session_sandbox_capabilities(session),
        permissions=(session.sandbox_meta or {}).get("permissions") or {"mode": "supervised"},
        sandbox_metrics=sandbox_metrics,
        env_restore=studio_sandbox_manager.env_restore_status(session_id),
        ui={
            "view_mode": (session.sandbox_meta or {}).get("ui", {}).get("view_mode", get_studio_config().ui.default_view_mode),
            "split_ratio": (session.sandbox_meta or {}).get("ui", {}).get("split_ratio", 40),
            "follow_ai": (session.sandbox_meta or {}).get("ui", {}).get("follow_ai", get_studio_config().ui.follow_ai_default),
            "terminal_collapsed": (session.sandbox_meta or {}).get("ui", {}).get("terminal_collapsed", get_studio_config().ui.terminal_collapsed_default),
            "hibernate_on_leave": get_studio_config().ui.hibernate_on_leave,
        },
        share=StudioShareStatusDTO(
            active=share_is_active(session),
            expires_at=session.share_expires_at,
            shared_at=session.shared_at,
        ),
    )


@router.delete("/sessions/{session_id}", summary="删除 Studio 会话")
async def delete_studio_session(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> dict[str, bool]:
    """删除 Studio 会话（软删，语义同 DELETE /chat/sessions/{id}）。

    沙盒忙碌（代码执行/长任务运行中）时拒绝删除；空闲会话先休眠回收容器，
    工作区目录保留，由既有保留期清理机制兜底，删会话不丢工作区文件。
    """
    await _get_studio_session(service, session_id, current_user_id)
    if await studio_sandbox_manager.hibernate(session_id) == "busy":
        raise ConflictError("会话正在执行任务，请稍后再试")
    await service.delete_session(session_id, current_user_id)
    return {"success": True}


@router.post("/sessions/{session_id}/restore", summary="恢复已归档的工作区")
async def restore_studio_workspace(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
) -> dict[str, Any]:
    """解包归档包恢复工作区目录（幂等；409=工作区配额不足；不做容器操作）。

    - 未归档（sandbox_meta 无 workspace_archive 标记）：200 {"restored": false, "reason": "not_archived"}
    - 已恢复过：200 {"restored": true, "idempotent": true}
    - 恢复成功后沙盒按既有懒启动链路在下次执行时拉起。
    """
    await _get_studio_session(service, session_id, current_user_id)
    from cygnusx.application.services.workspace_archive_service import unpack_session

    return await unpack_session(db, session_id, current_user_id)


@router.patch("/sessions/{session_id}/ui", summary="保存 Studio 代码工作室视图状态")
async def update_studio_ui(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
    req: UpdateStudioUiRequest,
) -> dict[str, Any]:
    session = await _get_studio_session(service, session_id, current_user_id)
    patch = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    if patch:
        # sandbox_meta 是多请求共享的 JSONB：聊天流事务会并发写入 plan 等键并长时间持有行锁。
        # 读-改-写整体回写会用陈旧快照覆盖并发写入（曾导致 update_plan 的计划被擦除），
        # 改为 jsonb_set 原子合并：行锁等待后 PG 基于最新已提交版本合并，互不丢更新。
        await db.execute(
            sql_text(
                "UPDATE chat_sessions SET sandbox_meta = jsonb_set("
                "COALESCE(sandbox_meta, '{}'::jsonb), '{ui}', "
                "COALESCE(sandbox_meta->'ui', '{}'::jsonb) || CAST(:patch AS jsonb), true), "
                "updated_at = now() WHERE session_id = :sid"
            ),
            {"patch": json.dumps(patch, ensure_ascii=False), "sid": session_id},
        )
        await db.flush()
        await db.refresh(session)
    return dict((session.sandbox_meta or {}).get("ui") or {})


@router.post("/sessions/{session_id}/permissions", summary="设置 Studio 会话权限模式")
async def update_studio_permissions(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
    req: UpdateStudioPermissionsRequest,
) -> dict[str, Any]:
    """会话级权限模式（§2）：supervised 写/执行类工具需用户批准；auto 即时执行。

    每次切换（含切回同一模式）都清空 permissions.always_allow，
    避免 auto→supervised 后残留"本会话总是允许"的放行。
    """
    session = await _get_studio_session(service, session_id, current_user_id)
    # 与 update_studio_ui 同理：jsonb_set 原子合并，避免覆盖聊天流并发写入的 plan 等键
    await db.execute(
        sql_text(
            "UPDATE chat_sessions SET sandbox_meta = jsonb_set("
            "COALESCE(sandbox_meta, '{}'::jsonb), '{permissions}', "
            "COALESCE(sandbox_meta->'permissions', '{}'::jsonb) || CAST(:patch AS jsonb), true), "
            "updated_at = now() WHERE session_id = :sid"
        ),
        {"patch": json.dumps({"mode": req.mode, "always_allow": []}), "sid": session_id},
    )
    await db.flush()
    await db.refresh(session)
    permissions = dict((session.sandbox_meta or {}).get("permissions") or {})
    return {"permissions": permissions}


@router.get("/sessions/{session_id}/checkpoints", summary="列出工作区检查点")
async def get_studio_checkpoints(
    current_user_id: CurrentUserId, service: ChatServiceDep, session_id: str
) -> dict[str, Any]:
    await _get_studio_session(service, session_id, current_user_id)
    return {"checkpoints": await asyncio.to_thread(list_checkpoints, session_id)}


@router.post("/sessions/{session_id}/checkpoints/{checkpoint_id}/restore", summary="恢复工作区检查点")
async def restore_studio_checkpoint(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    checkpoint_id: str,
) -> dict[str, Any]:
    await _get_studio_session(service, session_id, current_user_id)
    try:
        return await asyncio.to_thread(restore_checkpoint, session_id, checkpoint_id)
    except ValueError as exc:
        raise BusinessError(str(exc)) from exc


# ============================================================
# 工具审批（supervised 模式 HITL，§3）
# ============================================================


@router.get("/approvals", summary="列出指定会话待审批的工具审批")
async def list_pending_studio_approvals(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> dict[str, Any]:
    """审批提示是瞬态 SSE 事件，不落库；前端刷新/断流重进会话时用本端点重建待审批卡片。"""
    await _get_studio_session(service, session_id, current_user_id)
    records = await get_studio_approval_service().list_pending(str(current_user_id), session_id)
    return {"approvals": records}


@router.post("/approvals/{approval_id}/approve", summary="批准（或编辑后批准）工具审批")
async def approve_studio_tool(
    current_user_id: CurrentUserId,
    db: DbSession,
    approval_id: str,
    req: StudioApprovalApproveRequest,
) -> dict[str, Any]:
    service = get_studio_approval_service()
    record = await service.get(approval_id)
    if record is None or record.get("user_id") != str(current_user_id):
        raise NotFoundError("审批不存在或无权访问")
    if record.get("status") != "pending":
        raise ConflictError("审批已被消费")
    action = "edited" if req.modified_args else "approved"
    # 计划审批（approval_kind=plan）不支持 always：计划是一次性的，无"同工具复用"语义
    always = bool(req.always) and record.get("approval_kind", "tool") == "tool"
    resolved = await service.resolve(
        approval_id, str(current_user_id), action, modified_args=req.modified_args, always=always
    )
    if resolved is None:  # 并发消费兜底
        raise ConflictError("审批已被消费")
    if always:
        # "本会话总是允许"：(session, tool) 追加进 permissions.always_allow；
        # jsonb_set 原子合并，不覆盖聊天流并发写入的其他键；切换权限模式时清空。
        await db.execute(
            sql_text(
                "UPDATE chat_sessions SET sandbox_meta = jsonb_set("
                "COALESCE(sandbox_meta, '{}'::jsonb), '{permissions,always_allow}', "
                "COALESCE(sandbox_meta->'permissions'->'always_allow', '[]'::jsonb) "
                "|| CAST(:tool AS jsonb), true), "
                "updated_at = now() WHERE session_id = :sid"
            ),
            {
                "tool": json.dumps(str(resolved.get("tool_name") or "")),
                "sid": str(resolved.get("session_id") or ""),
            },
        )
        await db.flush()
    # 决议落 audit_logs（best-effort，不阻断审批主流程）
    await record_approval_audit(
        user_id=str(current_user_id),
        approval_id=approval_id,
        session_id=str(resolved.get("session_id") or ""),
        tool_name=str(resolved.get("tool_name") or ""),
        action=action,
        resolver="user",
        always=always,
        arguments=resolved.get("arguments")
        if isinstance(resolved.get("arguments"), dict)
        else None,
        approval_kind=str(resolved.get("approval_kind") or "tool"),
    )
    return {"success": True, "status": action, "always": always}


@router.post("/approvals/{approval_id}/reject", summary="退回工具审批")
async def reject_studio_tool(
    current_user_id: CurrentUserId,
    approval_id: str,
    req: StudioApprovalRejectRequest,
) -> dict[str, Any]:
    service = get_studio_approval_service()
    record = await service.get(approval_id)
    if record is None or record.get("user_id") != str(current_user_id):
        raise NotFoundError("审批不存在或无权访问")
    if record.get("status") != "pending":
        raise ConflictError("审批已被消费")
    resolved = await service.resolve(
        approval_id, str(current_user_id), "rejected", reason=req.reason
    )
    if resolved is None:
        raise ConflictError("审批已被消费")
    # 决议落 audit_logs（best-effort，不阻断审批主流程）
    await record_approval_audit(
        user_id=str(current_user_id),
        approval_id=approval_id,
        session_id=str(resolved.get("session_id") or ""),
        tool_name=str(resolved.get("tool_name") or ""),
        action="rejected",
        resolver="user",
        reason=req.reason,
        arguments=resolved.get("arguments")
        if isinstance(resolved.get("arguments"), dict)
        else None,
        approval_kind=str(resolved.get("approval_kind") or "tool"),
    )
    return {"success": True, "status": "rejected"}


@router.post(
    "/sessions/{session_id}/sandbox/hibernate",
    summary="休眠 Studio 沙盒并保留工作区",
)
async def hibernate_studio_sandbox(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> dict[str, Any]:
    """释放容器 CPU/内存与容器对象；工作区文件保留，下一次执行自动快速恢复。"""
    await _get_studio_session(service, session_id, current_user_id)
    status = await studio_sandbox_manager.hibernate(session_id)
    return {"status": status, "workspace_preserved": True}


@router.post(
    "/sessions/{session_id}/share",
    response_model=StudioShareResponse,
    summary="创建或轮换 Studio 只读分享链接",
)
async def create_studio_share(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
    req: CreateStudioShareRequest,
) -> StudioShareResponse:
    session = await _get_studio_session(service, session_id, current_user_id)
    token, expires_at = create_share(session, req.expires_hours)
    await db.flush()
    return StudioShareResponse(
        token=token,
        share_path=f"/studio/shared/{token}",
        expires_at=expires_at,
    )


@router.get(
    "/sessions/{session_id}/share",
    response_model=StudioShareStatusDTO,
    summary="读取 Studio 分享状态",
)
async def get_studio_share_status(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> StudioShareStatusDTO:
    session = await _get_studio_session(service, session_id, current_user_id)
    return StudioShareStatusDTO(
        active=share_is_active(session),
        expires_at=session.share_expires_at,
        shared_at=session.shared_at,
    )


@router.delete(
    "/sessions/{session_id}/share",
    response_model=StudioShareStatusDTO,
    summary="撤销 Studio 分享链接",
)
async def revoke_studio_share(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
) -> StudioShareStatusDTO:
    session = await _get_studio_session(service, session_id, current_user_id)
    revoke_share(session)
    await db.flush()
    return StudioShareStatusDTO(active=False)


@router.post(
    "/sessions/{session_id}/skills/extract",
    response_model=SkillDTO,
    status_code=201,
    summary="将 Studio 脚本提炼为可复用 Skill",
)
async def extract_studio_skill(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
    req: ExtractStudioSkillRequest,
) -> SkillDTO:
    session = await _get_studio_session(service, session_id, current_user_id)
    result = await db.execute(select(UserModel.role).where(UserModel.id == current_user_id))
    visibility = "global" if result.scalar_one_or_none() == "admin" else "private"
    return await extract_skill_from_workspace(
        session,
        req,
        SkillService(db),
        owner_id=str(current_user_id),
        visibility=visibility,
    )


@router.get(
    "/sessions/{session_id}/export",
    response_class=HTMLResponse,
    summary="导出 Studio 打印版报告（浏览器保存为 PDF）",
)
async def export_studio_session_report(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
) -> HTMLResponse:
    session = await _get_studio_session(service, session_id, current_user_id)
    snapshot = await build_shared_snapshot(db, session)
    return HTMLResponse(
        render_printable_report(snapshot),
        headers={"Content-Disposition": f'inline; filename="studio-{session_id[:8]}.html"'},
    )


# ============================================================
# 工作区文件
# ============================================================


@router.put(
    "/sessions/{session_id}/files/write",
    response_model=SaveStudioFileResponse,
    summary="保存工作区文本文件",
)
async def save_workspace_file(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    req: SaveStudioFileRequest,
) -> SaveStudioFileResponse:
    """从工作区编辑器完整覆盖文本文件，路径仍由沙盒守卫校验。"""
    session = await _get_studio_session(service, session_id, current_user_id)
    try:
        result = await studio_sandbox_manager.write_file(
            session.session_id,
            req.path,
            req.content,
            image=_sandbox_image(session),
            user_id=current_user_id,
        )
    except StudioSandboxUnavailableError as exc:
        raise BusinessError(
            f"沙盒暂不可用：{exc}。请确认 Docker 正常且沙盒镜像已构建后重试。"
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = str(exc)
        with contextlib.suppress(Exception):
            detail = str(exc.response.json().get("detail") or detail)
        raise BusinessError(f"沙盒拒绝了该操作：{detail}") from exc

    return SaveStudioFileResponse(
        path=str(result.get("path") or req.path),
        size=int(result.get("size") or len(req.content.encode("utf-8"))),
    )


@router.post("/sessions/{session_id}/files/mkdir", summary="创建工作区目录")
async def make_workspace_directory(current_user_id: CurrentUserId, service: ChatServiceDep, session_id: str, req: StudioPathRequest) -> dict[str, Any]:
    session = await _get_studio_session(service, session_id, current_user_id)
    return await studio_sandbox_manager.make_directory(session_id, req.path, image=_sandbox_image(session), user_id=current_user_id)


@router.post("/sessions/{session_id}/files/rename", summary="重命名工作区文件")
async def rename_workspace_file(current_user_id: CurrentUserId, service: ChatServiceDep, session_id: str, req: RenameStudioFileRequest) -> dict[str, Any]:
    session = await _get_studio_session(service, session_id, current_user_id)
    return await studio_sandbox_manager.rename_file(session_id, req.path, req.new_path, image=_sandbox_image(session), user_id=current_user_id)


@router.delete("/sessions/{session_id}/files/delete", summary="删除工作区文件")
async def delete_workspace_file(current_user_id: CurrentUserId, service: ChatServiceDep, session_id: str, path: str = Query(...)) -> dict[str, Any]:
    session = await _get_studio_session(service, session_id, current_user_id)
    return await studio_sandbox_manager.delete_file(session_id, path, image=_sandbox_image(session), user_id=current_user_id)


@router.post(
    "/sessions/{session_id}/files/edit",
    response_model=EditStudioFileResponse,
    summary="编辑工作区文件",
)
async def edit_workspace_file(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    req: EditStudioFileRequest,
) -> EditStudioFileResponse:
    """精确编辑工作区文件。

    StudioCodeCard 的「拒绝修改」会交换 old_string/new_string 调用此端点，
    依赖 sandbox-agent 的唯一匹配守卫，避免误回滚后续修改。
    """
    session = await _get_studio_session(service, session_id, current_user_id)
    try:
        result = await studio_sandbox_manager.edit_file(
            session.session_id,
            req.path,
            req.old_string,
            req.new_string,
            image=_sandbox_image(session),
            user_id=current_user_id,
        )
    except StudioSandboxUnavailableError as exc:
        raise BusinessError(
            f"沙盒暂不可用：{exc}。请确认 Studio 已启用、Docker 正常且沙盒镜像已构建后重试。"
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = str(exc)
        with contextlib.suppress(Exception):
            detail = str(exc.response.json().get("detail") or detail)
        raise BusinessError(f"沙盒拒绝了该操作：{detail}") from exc

    return EditStudioFileResponse(
        path=str(result.get("path") or req.path),
        diff=str(result.get("diff") or ""),
        size=int(result.get("size") or 0),
    )


@router.get("/sessions/{session_id}/files", summary="工作区目录列表")
async def list_workspace_files(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    path: str = Query("", description="相对 /workspace 的目录路径"),
) -> dict[str, Any]:
    session = await _get_studio_session(service, session_id, current_user_id)
    return await _workspace_listing(session, path)


@router.get("/sessions/{session_id}/files/download", summary="下载或预览工作区文件")
async def download_workspace_file(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    path: str = Query(..., description="相对 /workspace 的文件路径"),
) -> FileResponse:
    session = await _get_studio_session(service, session_id, current_user_id)
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    try:
        target = resolve_workspace_read_path(
            path,
            root=workspace,
            platform_host_root=user_platform_root(session.user_id),
        ).path
    except PathEscapeError as exc:
        raise BusinessError(str(exc)) from exc
    factory = get_path_factory()
    backend = get_storage_backend()
    try:
        local_path = await backend.get_local_path(factory.relative_to_root(target))
    except NotFoundError:
        raise NotFoundError(f"工作区文件不存在: {path}") from None
    return FileResponse(local_path, filename=local_path.name)


@router.get("/sessions/{session_id}/files/read", summary="读取工作区文件")
async def read_workspace_file(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    path: str = Query(..., description="相对 /workspace 的文件路径"),
    offset: int = Query(0, ge=0, description="起始行（0 基）"),
    limit: int = Query(DEFAULT_READ_LIMIT, ge=1, le=MAX_READ_LIMIT, description="读取行数"),
) -> dict[str, Any]:
    session = await _get_studio_session(service, session_id, current_user_id)
    return await _workspace_read(session, path, offset, limit)


@router.post(
    "/sessions/{session_id}/import",
    response_model=ImportStudioDataFileResponse,
    summary="从数据管理或聊天上传引入文件",
)
async def import_data_file(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
    req: ImportStudioDataFileRequest,
) -> ImportStudioDataFileResponse:
    """左栏文件导入入口（浏览器无法直接调 Agent 工具）。

    与 datahub_import 工具同一服务路径（import_datahub_file）：校验数据管理文件
    归属或聊天上传目录边界后，在 /workspace/input/ 下建立只读软链（数据不搬家），
    返回沙盒内路径与当前 input/ 清单。
    """
    session = await _get_studio_session(service, session_id, current_user_id)
    result = await import_datahub_file(
        current_user_id, session.session_id, req.file_id, req.name, db
    )
    return ImportStudioDataFileResponse(
        sandbox_path=result["sandbox_path"],
        name=result["name"],
        size=result["size"],
        file_type=result["file_type"],
        input_files=result["input_files"],
    )


# ============================================================
# 代码重跑（VS Code 回路：用户编辑代码卡片后手动重跑，无需 Agent 轮次）
# ============================================================


@router.websocket("/sessions/{session_id}/terminal", name="studio_terminal_websocket")
async def studio_terminal_websocket(websocket: WebSocket, session_id: str) -> None:
    """浏览器与当前 Studio 会话专属沙箱 PTY 的双向代理。"""
    token = websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=1008, reason="Invalid token")
        return

    user = await get_active_user_from_token_payload(payload)
    if user is None:
        await websocket.close(code=1008, reason="User inactive or not found")
        return

    user_id = str(user.id)
    factory = get_session_factory()
    async with factory() as db:
        service = ChatService(db)
        try:
            session = await _get_studio_session(service, session_id, user_id)
        except Exception:
            await websocket.close(code=1008, reason="Studio session not found")
            return
        image = _sandbox_image(session)

    try:
        handle = await studio_sandbox_manager._handle(
            session_id,
            image=image,
            user_id=user_id,
        )
    except StudioSandboxUnavailableError as exc:
        await websocket.close(code=1011, reason=str(exc)[:120])
        return

    await websocket.accept()
    lease_token = await studio_sandbox_manager._set_busy(session_id, 3600)
    connector = aiohttp.UnixConnector(path=str(handle.agent_socket))
    client = aiohttp.ClientSession(connector=connector)
    agent_ws: aiohttp.ClientWebSocketResponse | None = None

    async def browser_to_agent() -> None:
        assert agent_ws is not None
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await agent_ws.send_bytes(message["bytes"])
            else:
                data = message.get("text") or ""
                await agent_ws.send_str(data)
            await studio_sandbox_manager._touch(session_id)

    async def agent_to_browser() -> None:
        assert agent_ws is not None
        async for message in agent_ws:
            if message.type == aiohttp.WSMsgType.BINARY:
                await websocket.send_bytes(message.data)
            elif message.type == aiohttp.WSMsgType.TEXT:
                await websocket.send_text(message.data)
            elif message.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            }:
                break

    try:
        agent_ws = await client.ws_connect("http://studio-agent/terminal")
        browser_task = asyncio.create_task(browser_to_agent())
        agent_task = asyncio.create_task(agent_to_browser())
        _, pending = await asyncio.wait(
            {browser_task, agent_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except (WebSocketDisconnect, aiohttp.ClientError) as exc:
        logger.debug(f"Studio 终端连接结束 ({session_id[:8]}): {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Studio 终端代理异常 ({session_id[:8]}): {exc}")
    finally:
        if agent_ws is not None and not agent_ws.closed:
            await agent_ws.close()
        await client.close()
        await studio_sandbox_manager._clear_busy(session_id, lease_token)
        await studio_sandbox_manager._touch(session_id)
        with contextlib.suppress(RuntimeError):
            await websocket.close()


@router.post("/sessions/{session_id}/run", summary="重跑代码（SSE 流式）")
async def run_workspace_code(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    req: StudioRunRequest,
) -> StreamingResponse:
    """在会话沙盒中执行用户编辑后的代码，SSE 推送执行过程。

    事件格式与 /chat/stream 一致：
    - {"type":"tool_output","tool":"sandbox_execute","stream":"stdout|stderr","data":"..."}
    - {"type":"tool_result","tool_name":"sandbox_execute","success":bool,
       "result":{llm_payload},"ui_payload":{exit_code,duration_ms,stdout,stderr,artifacts}}
    沙盒未运行时按需懒启动，无需 Agent 轮次参与。
    """
    session = await _get_studio_session(service, session_id, current_user_id)
    image = _sandbox_image(session)
    args: dict[str, Any] = {"language": req.language, "code": req.code}
    if req.timeout is not None:
        args["timeout"] = req.timeout

    async def generate_sse():
        async for item in stream_studio_tool(
            "sandbox_execute", args, session.session_id, image=image, user_id=current_user_id
        ):
            if isinstance(item, ChatChunk):
                data: dict[str, Any] = {"type": item.type, "content": item.content}
                data.update(item.metadata)
            else:
                inner = item.get("result") or {}
                data = {
                    "type": "tool_result",
                    "content": "",
                    "tool_name": "sandbox_execute",
                    "mcp_server": "studio",
                    "success": bool(item.get("success")),
                    "result": inner.get("llm_payload"),
                    "ui_payload": inner.get("ui_payload"),
                }
            yield f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 产物清单与下载
# ============================================================


@router.get("/sessions/{session_id}/artifacts", summary="产物清单")
async def list_artifacts(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
) -> dict[str, Any]:
    """列出 /workspace/output 下的产物文件（含大小 / mtime / 下载 URL）。

    工作区经 bind-mount 与容器同源，直接扫宿主磁盘，沙盒停止时也可用。
    """
    await _get_studio_session(service, session_id, current_user_id)
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    factory = get_path_factory()
    backend = get_storage_backend()
    workspace_info = await backend.stat(factory.relative_to_root(workspace))
    if workspace_info is None or not workspace_info.get("is_dir"):
        artifacts: list[dict[str, Any]] = []
    else:
        out_rel = factory.relative_to_root(workspace / "output")
        entries = await backend.list(out_rel, recursive=True)
        artifacts = [
            {
                "path": relative_workspace_path(factory.data_root / entry["path"], workspace),
                "size": entry["size"],
                "mtime": entry["mtime"],
            }
            for entry in entries
            if entry["type"] == "file"
        ]
    for item in artifacts:
        item["download_url"] = (
            f"/api/v1/studio/sessions/{session_id}/artifacts/download"
            f"?path={quote(item['path'])}"
        )
    return {"artifacts": artifacts}


@router.post(
    "/sessions/{session_id}/artifacts/register",
    response_model=RegisterStudioArtifactResponse,
    summary="登记产物到结果报告中心",
)
async def register_artifact(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    db: DbSession,
    session_id: str,
    req: RegisterStudioArtifactRequest,
) -> RegisterStudioArtifactResponse:
    """右栏产物「保存为新版本」：与 artifact_register 工具同一服务路径。

    产物复制进报告中心存储区并生成新报告；会话由报告优化场景创建时
    自动挂为原报告的下一版本（版本树）。
    """
    session = await _get_studio_session(service, session_id, current_user_id)
    report, file_model = await register_artifact_report(
        current_user_id,
        session,
        req.path,
        req.title,
        db,
        artifact_type=req.type,
        description=req.description,
    )
    return RegisterStudioArtifactResponse(
        report_id=report.id,
        title=report.title,
        version=report.version,
        parent_id=report.parent_id,
        file={"name": file_model.name, "size": file_model.size, "type": file_model.type},
    )


@router.get("/sessions/{session_id}/artifacts/download", summary="下载产物")
async def download_artifact(
    current_user_id: CurrentUserId,
    service: ChatServiceDep,
    session_id: str,
    path: str = Query(..., description="产物路径（相对工作区根，如 output/plot.png）"),
) -> FileResponse:
    await _get_studio_session(service, session_id, current_user_id)
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    try:
        target = resolve_artifact_path(workspace, path)
    except PathEscapeError as e:
        raise BusinessError(str(e)) from e
    factory = get_path_factory()
    backend = get_storage_backend()
    try:
        local_path = await backend.get_local_path(factory.relative_to_root(target))
    except NotFoundError:
        raise NotFoundError(f"产物不存在: {path}") from None
    return FileResponse(local_path, filename=local_path.name)
