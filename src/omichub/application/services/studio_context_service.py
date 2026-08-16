"""OmicStudio 上下文打包与产物登记服务（架构设计 §7.2）。

两个职责：
1. Context Packager：从结果报告中心一键创建 Studio 会话 —— 打包来源流程、run_id、
   参数与产物文件（软链进 /workspace/input/），context_pack 写入会话 sandbox_meta，
   聊天时由 chat_service 渲染进系统提示词；
2. Artifact Service：把 /workspace/output/ 下的产物复制进报告中心存储区并登记为
   新报告，与原报告建立版本树（parent_id + version）。
   （复制而非软链：工作区 7 天后会被清理，报告中心需独立存续。）
"""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from omichub.application.schemas.chat import ChatSessionDTO
from omichub.application.services.file_service import ensure_directory_chain
from omichub.core.config import get_settings
from omichub.core.exceptions import BusinessError, NotFoundError, OmicHubError
from omichub.domain.file.value_objects import FileSource
from omichub.infrastructure.config.deployment_config import get_deployment_config
from omichub.infrastructure.config.storage_config import get_user_chat_upload_dir
from omichub.infrastructure.database.models.chat import ChatSessionModel
from omichub.infrastructure.database.models.file import FileRecordModel
from omichub.infrastructure.database.models.report import ReportFileModel, ReportModel
from omichub.infrastructure.database.models.task import TaskModel
from omichub.infrastructure.database.session import get_session_factory
from omichub.infrastructure.storage import get_path_factory, get_storage_backend
from omichub.infrastructure.storage.file_registry import FileRegistry
from omichub.infrastructure.studio.manager import studio_sandbox_manager
from omichub.infrastructure.studio.paths import PathEscapeError
from omichub.infrastructure.studio.workspace import (
    link_platform_file,
    list_input_links,
    platform_user_rel,
    resolve_artifact_path,
)

# Studio 会话登记报告时的流程标识（reports.flow_id 非空列，用 sentinel 区分平台流程）
STUDIO_FLOW_ID = "studio"
STUDIO_FLOW_NAME = "OmicStudio"
STUDIO_FLOW_ICON = "🧪"

CONTEXT_PACK_HINT = (
    "用户对上述流程产出的结果不满意，希望在你的协助下诊断、复现并改进。"
    "所有分析必须可复现、可修改、可重跑；满意的产物可用 artifact_register "
    "登记为原报告的新版本（版本树）。"
)

_CHAT_UPLOAD_ID_RE = re.compile(r"^[a-fA-F0-9]{16,128}$")


async def _resolve_chat_upload_file(
    user_id: str, upload_id: str, backend=None
) -> tuple[Path, str, int]:
    """解析当前用户聊天上传文件，返回路径、平台相对路径与大小。"""
    backend = backend or get_storage_backend()
    factory = get_path_factory()
    upload_dir = get_user_chat_upload_dir(user_id)
    upload_rel_dir = factory.relative_to_root(upload_dir)
    entries = await backend.list(upload_rel_dir, recursive=False)
    candidates = [
        e for e in entries if e["type"] == "file" and e["name"].startswith(upload_id)
    ]
    if not candidates:
        raise NotFoundError("聊天上传文件不存在或无权访问")
    chosen = sorted(candidates, key=lambda e: (len(Path(e["name"]).suffix), e["name"]))[0]
    rel_path = f"{upload_rel_dir}/{chosen['name']}".strip("/")
    abs_path = factory.data_root / rel_path
    try:
        abs_path.relative_to(upload_dir.resolve())
        storage_rel = factory.relative_to_root(abs_path)
    except ValueError as exc:
        raise BusinessError("聊天上传文件路径异常") from exc
    local_path = await backend.get_local_path(storage_rel)
    size = chosen["size"] or 0
    return local_path, storage_rel, size


def user_platform_root(user_id: str) -> Path:
    """当前用户的平台数据根；保留给 Studio 路由的兼容接口。"""
    return get_path_factory().user_root(user_id)


def report_file_mount_rel(file_path: str, user_id: str) -> str | None:
    """报告文件绝对路径 → 平台挂载（/data/platform）内相对路径。

    越出平台存储根或不属于该用户时返回 None（调用方跳过，不阻断整体引入）。
    """
    try:
        rel = Path(file_path).resolve().relative_to(Path(get_settings().storage_path).resolve())
    except ValueError:
        return None
    try:
        return platform_user_rel(rel.as_posix(), user_id)
    except PathEscapeError:
        return None


async def link_report_files(
    report: ReportModel, workspace: Path, user_id: str
) -> list[dict[str, Any]]:
    """把报告全部产物文件软链进 workspace/input/。

    返回 [{name, sandbox_path, role, size}]；磁盘上已丢失或路径越权的文件跳过。
    """
    backend = get_storage_backend()
    factory = get_path_factory()
    linked: list[dict[str, Any]] = []
    for f in report.files:
        mount_rel = report_file_mount_rel(f.path, user_id)
        if mount_rel is None:
            continue
        try:
            rel_path = factory.relative_to_root(Path(f.path))
        except ValueError:
            continue
        if await backend.stat(rel_path) is None:
            continue
        link_name = link_platform_file(workspace, mount_rel, f.name)
        linked.append(
            {
                "name": link_name,
                "sandbox_path": f"/workspace/input/{link_name}",
                "role": "主报告" if f.is_primary else f"产物（{f.type}）",
                "size": f.size,
            }
        )
    return linked


async def create_session_from_report(
    user_id: str, report_id: UUID | str, agent_id: str, db: AsyncSession
) -> ChatSessionDTO:
    """从报告创建 Studio 会话（「在 AI 工作台中优化」入口）。

    流程：校验报告归属 → 校验 Agent 开放 Studio → 创建 studio 会话 →
    报告产物软链进工作区 input/ → context_pack 写入 sandbox_meta。
    """
    # 延迟导入防循环：chat_service -> studio_tools -> 本模块
    from omichub.application.services.agent_service import AgentService
    from omichub.application.services.chat_service import ChatService

    result = await db.execute(
        select(ReportModel)
        .where(ReportModel.id == UUID(str(report_id)))
        .options(selectinload(ReportModel.files))
    )
    report = result.scalar_one_or_none()
    if report is None or str(report.user_id) != str(user_id):
        raise NotFoundError("报告不存在或无权访问")

    agent = await AgentService(db).get_agent(agent_id)
    if agent is None or not agent.is_active:
        raise NotFoundError("Agent 不存在或已停用")
    studio_cfg = (agent.features or {}).get("studio") or {}
    if studio_cfg and studio_cfg.get("enabled") is False:
        raise BusinessError("该 Agent 未启用 Studio 工作台")
    if agent.model_id is None:
        raise BusinessError("Agent 未绑定模型，无法创建 Studio 会话")

    # 产出该报告的任务（取用户当时参数）；报告可能来自 Studio 回填（无任务行）
    task = await db.get(TaskModel, report.task_id)
    params = dict(task.parameters or {}) if task is not None else {}

    service = ChatService(db)
    image = studio_cfg.get("image")
    dto = await service.create_session(
        user_id,
        agent.model_id,
        f"优化：{report.title}"[:200],
        agent_id=agent_id,
        mode="studio",
        sandbox_meta={"image": image} if image else None,
    )

    # 报告产物软链进工作区（数据不搬家），再回填 context_pack
    workspace = studio_sandbox_manager.workspace_dir(dto.session_id)
    studio_sandbox_manager.ensure_workspace_dirs(workspace)
    linked = await link_report_files(report, workspace, str(user_id))

    context_pack: dict[str, Any] = {
        "source": {
            "pipeline": report.flow_id,
            "pipeline_name": report.flow_name,
            "run_id": str(report.task_id),
            "params": params,
            "report_id": str(report.id),
            "report_title": report.title,
        },
        "files": [{"path": item["sandbox_path"], "role": item["role"]} for item in linked],
        "hint": CONTEXT_PACK_HINT,
    }
    missing = len(report.files) - len(linked)
    if missing > 0:
        context_pack["note"] = f"{missing} 个报告文件已丢失或不可访问，未引入工作区"

    session = await service.get_session(dto.session_id, user_id)
    if session is None:  # 刚创建的会话不可能查不到，防御性兜底
        raise BusinessError("Studio 会话创建失败")
    meta = dict(session.sandbox_meta or {})
    meta["context_pack"] = context_pack
    session.sandbox_meta = meta  # 整体重赋值触发 JSONB 变更检测
    await db.flush()
    return ChatService._to_session_dto(session)


def render_context_pack_hint(pack: dict[str, Any]) -> str:
    """把 context_pack 渲染为中文系统提示词段（追加在 Studio 提示词后缀之后）。"""
    source = pack.get("source") or {}
    lines = [
        "## 本次会话来源（Context Pack）",
        "",
        "用户从结果报告中心发起了「在 AI 工作台中优化」：",
        f"- 来源流程：{source.get('pipeline_name') or source.get('pipeline') or '未知'}"
        f"（{source.get('pipeline', '')}）",
        f"- 运行 ID：{source.get('run_id', '')}",
        f"- 原报告：{source.get('report_title', '')}（report_id: {source.get('report_id', '')}）",
    ]
    params = source.get("params") or {}
    if params:
        params_text = json.dumps(params, ensure_ascii=False, default=str)
        if len(params_text) > 800:
            params_text = params_text[:800] + "…（已截断）"
        lines.append(f"- 当时参数：{params_text}")
    files = pack.get("files") or []
    if files:
        lines.extend(["", "已引入 /workspace/input/ 的结果文件："])
        for f in files:
            lines.append(f"- {f.get('path')}（{f.get('role')}）")
    if pack.get("note"):
        lines.append(f"注意：{pack['note']}")
    if pack.get("hint"):
        lines.extend(["", f"优化提示：{pack['hint']}"])
    return "\n".join(lines)


def _infer_artifact_type(name: str) -> str:
    """按扩展名推断产物类型（对应 report_files.type 的 html/pdf/png/zip/csv 风格）。"""
    suffix = Path(name).suffix.lower().lstrip(".")
    return suffix[:20] if suffix else "other"


# ===== 数据管理引入（datahub_import 工具与 REST 入口共用路径） =====


def _resolve_storage_file(storage_path: str, rel_path: str) -> Path | None:
    """落盘路径校验（同步辅助）：相对存储根的路径 → 绝对路径，越界返回 None。"""
    storage_root = Path(storage_path).resolve()
    abs_path = (storage_root / rel_path).resolve()
    if abs_path != storage_root and storage_root not in abs_path.parents:
        return None
    return abs_path


async def import_datahub_file(
    user_id: str,
    session_id: str,
    file_id: str,
    name: str | None,
    db: AsyncSession,
    *,
    idempotent: bool = False,
) -> dict[str, Any]:
    """把数据管理文件或聊天上传文件引入 Studio 工作区。

    校验文件归属（强制 user_id 匹配，杜绝跨租户水平越权）与 active 状态，
    软链目标为容器内 /data/platform/<用户相对路径>。返回
    {sandbox_path, name, size, file_type, original_name, input_files}；
    失败抛 NotFoundError / BusinessError（由调用方按通道收敛）。

    ``idempotent=True`` 时同一文件重复引入复用既有软链（聊天附件自动挂载用），
    默认 False 保持 datahub_import 工具的原始同名去重语义。
    """
    raw_file_id = str(file_id or "").strip()
    if not raw_file_id:
        raise BusinessError("file_id 不能为空")

    if raw_file_id.startswith("upload://"):
        upload_id = raw_file_id.removeprefix("upload://").strip()
        if not _CHAT_UPLOAD_ID_RE.fullmatch(upload_id):
            raise BusinessError("聊天上传 file_id 格式非法")

        upload_path, storage_rel, upload_size = await _resolve_chat_upload_file(
            str(user_id), upload_id
        )

        workspace = studio_sandbox_manager.workspace_dir(session_id)
        studio_sandbox_manager.ensure_workspace_dirs(workspace)
        try:
            mount_rel = platform_user_rel(storage_rel, str(user_id))
        except PathEscapeError as exc:
            raise BusinessError(str(exc)) from exc
        link_name = link_platform_file(
            workspace, mount_rel, name or upload_path.name, idempotent=idempotent
        )
        return {
            "sandbox_path": f"/workspace/input/{link_name}",
            "name": link_name,
            "size": upload_size,
            "file_type": "chat_upload",
            "original_name": upload_path.name,
            "input_files": [f"/workspace/input/{item}" for item in list_input_links(workspace)],
        }

    normalized_file_id = raw_file_id.removeprefix("file://")
    try:
        file_uuid = uuid.UUID(normalized_file_id)
        user_uuid = uuid.UUID(str(user_id))
    except ValueError as exc:
        raise BusinessError("file_id 格式非法") from exc

    backend = get_storage_backend()
    factory = get_path_factory()

    result = await db.execute(
        select(FileRecordModel).where(
            FileRecordModel.id == file_uuid,
            FileRecordModel.user_id == user_uuid,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise NotFoundError("文件不存在或无权访问")
    if record.status != "active":
        raise BusinessError(f"文件当前状态（{record.status}）不可用，仅支持 active 文件")

    abs_path = factory.data_root / record.storage_path
    if not factory.is_within_root(abs_path):
        raise BusinessError("文件存储路径异常（越出存储根）")
    if await backend.stat(record.storage_path) is None:
        raise BusinessError("文件在磁盘上已丢失，请在数据管理中重新上传")

    workspace = studio_sandbox_manager.workspace_dir(session_id)
    studio_sandbox_manager.ensure_workspace_dirs(workspace)
    try:
        mount_rel = platform_user_rel(record.storage_path, str(user_id))
    except PathEscapeError as e:
        raise BusinessError(str(e)) from e
    link_name = link_platform_file(
        workspace, mount_rel, name or record.original_name, idempotent=idempotent
    )

    sandbox_path = f"/workspace/input/{link_name}"
    return {
        "sandbox_path": sandbox_path,
        "name": link_name,
        "size": record.size,
        "file_type": record.file_type,
        "original_name": record.original_name,
        "input_files": [f"/workspace/input/{n}" for n in list_input_links(workspace)],
    }


async def link_session_file_refs(
    user_id: str,
    session_id: str,
    refs: list[str],
    db: AsyncSession,
) -> tuple[dict[str, str], dict[str, str]]:
    """把一批文件引用（upload://hex 或 file://uuid）幂等地引入 Studio 工作区。

    逐个走 :func:`import_datahub_file`（与 datahub_import 工具同一服务路径），
    成功的引用返回 ``/workspace/input/<name>`` 沙盒可读路径，失败的记录错误原因
    而不中断整体。返回 (paths, errors)：

    - paths: {原始 ref: sandbox_path}，供聊天提示词直接告诉模型用工作区路径读取；
    - errors: {原始 ref: 错误描述}，仅供日志/降级，不向模型暴露。

    设计动机：沙盒内无法解析 ``file://``/``upload://`` 引用，只有挂载进
    ``/workspace/input/`` 的平台软链才能被沙盒代码按文件系统路径直接读取。
    """
    paths: dict[str, str] = {}
    errors: dict[str, str] = {}
    seen: set[str] = set()
    for raw_ref in refs:
        ref = str(raw_ref or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        try:
            payload = await import_datahub_file(
                user_id=str(user_id),
                session_id=session_id,
                file_id=ref,
                name=None,
                db=db,
                idempotent=True,
            )
            paths[ref] = payload["sandbox_path"]
        except OmicHubError as exc:
            errors[ref] = exc.detail
        except Exception as exc:  # noqa: BLE001 - 单个文件失败不阻断其余引入
            logger.warning("Studio 自动引入文件失败 ref={}: {}", ref, exc)
            errors[ref] = str(exc)
    return paths, errors


async def link_session_workspace_refs(
    user_id: str,
    session_id: str,
    refs: list[str],
    db: AsyncSession,
) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, str]]:
    """Compatibility entry point for all controlled Session workspace resources.

    New callers must use this function rather than duplicating file/directory parsing
    in Studio, chat, or Overdrive.  ``link_session_file_refs`` remains for existing
    API callers that only need legacy file behaviour.
    """
    from omichub.application.services.workspace_references import (
        link_session_workspace_refs as _link_session_workspace_refs,
    )

    return await _link_session_workspace_refs(user_id, session_id, refs, db)


async def register_artifact_report(
    user_id: str,
    session: ChatSessionModel,
    path: str,
    title: str,
    db: AsyncSession,
    artifact_type: str | None = None,
    description: str | None = None,
) -> tuple[ReportModel, ReportFileModel]:
    """把 /workspace/output/ 下的产物登记为结果报告中心的新报告。

    - path 强制落在工作区 output/ 内（resolve_artifact_path 守卫）；
    - 产物复制到项目运行目录的 ``output/``（工作区保留期仅 7 天，报告需独立
      存续，故复制而非软链）；
    - 会话 sandbox_meta.context_pack.source.report_id 存在时挂为原报告的
      下一版本（parent_id + version=父版本+1），否则 version=1。
    """
    if not title.strip():
        raise BusinessError("报告标题不能为空")
    backend = get_storage_backend()
    path_factory = get_path_factory()

    deployment_cfg = get_deployment_config()
    if deployment_cfg.scratch_volume_enabled:
        scratch = studio_sandbox_manager.scratch_volume(session.session_id)
        workspace = scratch.volume.workspace if scratch else studio_sandbox_manager.workspace_dir(session.session_id)
    else:
        workspace = studio_sandbox_manager.workspace_dir(session.session_id)
    try:
        target = resolve_artifact_path(workspace, path)
    except PathEscapeError as e:
        raise BusinessError(str(e)) from e
    target_rel = path_factory.relative_to_root(target)
    if deployment_cfg.scratch_volume_enabled:
        if not target.is_file():
            raise NotFoundError(f"产物不存在: {path}")
    elif await backend.stat(target_rel) is None:
        raise NotFoundError(f"产物不存在: {path}")

    project_name = session.title.strip()
    if not project_name or project_name == "新对话":
        raise BusinessError("请先将 Studio 会话标题设置为项目名称，再登记分析产物")
    run_dir = path_factory.create_project_run_dir(user_id, project_name, "studio")
    dest_dir = run_dir / "output"
    relative_run_dir = run_dir.relative_to(path_factory.user_root(user_id)).as_posix()
    dest_dir_rel = path_factory.relative_to_root(dest_dir)
    await backend.ensure_dir(dest_dir_rel)

    async def persist(anchor_db: AsyncSession) -> tuple[ReportModel, ReportFileModel]:
        # 版本树：父报告来自会话 context_pack；父报告已删除/不属于本人时退化为 v1
        parent: ReportModel | None = None
        pack = (session.sandbox_meta or {}).get("context_pack") or {}
        parent_id_raw = (pack.get("source") or {}).get("report_id")
        if parent_id_raw:
            try:
                candidate = await anchor_db.get(ReportModel, UUID(str(parent_id_raw)))
            except ValueError:
                candidate = None
            if candidate is not None and str(candidate.user_id) == str(user_id):
                parent = candidate
        version = (parent.version or 1) + 1 if parent is not None else 1

        await ensure_directory_chain(anchor_db, UUID(str(user_id)), relative_run_dir)
        dest = dest_dir / target.name
        dest_rel = path_factory.relative_to_root(dest)
        n = 1
        while await backend.stat(dest_rel) is not None:
            n += 1
            dest = dest_dir / f"{target.stem} ({n}){target.suffix}"
            dest_rel = path_factory.relative_to_root(dest)
        if deployment_cfg.scratch_volume_enabled:
            content = target.read_bytes()
            await backend.write(dest_rel, content)
        else:
            await backend.copy(target_rel, dest_rel)

        now = datetime.now()
        report = ReportModel(
            id=uuid.uuid4(),
            # Studio 会话不是任务中心任务：task_id 用随机哨兵值，避免与真实任务混淆
            task_id=uuid.uuid4(),
            user_id=UUID(str(user_id)),
            flow_id=STUDIO_FLOW_ID,
            flow_name=STUDIO_FLOW_NAME,
            flow_version="",
            flow_icon=STUDIO_FLOW_ICON,
            title=title.strip()[:200],
            description=(description or "")[:2000] if description else "",
            status="completed",
            sample_count=0,
            duration=0,
            created_at=now,
            completed_at=now,
            parent_id=parent.id if parent is not None else None,
            version=version,
        )
        try:
            anchor_db.add(report)
            await anchor_db.flush()

            dest_info = await backend.stat(dest_rel)
            file_model = ReportFileModel(
                id=uuid.uuid4(),
                report_id=report.id,
                name=dest.name,
                type=(artifact_type or _infer_artifact_type(dest.name))[:20],
                size=dest_info["size"] if dest_info else 0,
                path=str(dest),
                is_primary=True,
            )
            anchor_db.add(file_model)
            await anchor_db.flush()

            # 产物同时注册到统一文件索引，使 AI 助手 / 文件中心可见
            try:
                registry = FileRegistry(anchor_db)
                dest_directory = dest_dir.relative_to(
                    path_factory.user_root(user_id)
                ).as_posix()
                await registry.register(
                    UUID(str(user_id)),
                    dest,
                    source=FileSource.STUDIO,
                    directory=dest_directory,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Studio 产物注册到 file_records 失败（非阻塞）: {}", exc
                )

            await anchor_db.commit()
        except Exception:
            with contextlib.suppress(NotFoundError):
                await backend.delete(dest_rel)
            raise
        return report, file_model

    if not isinstance(db, AsyncSession):
        return await persist(db)
    async with get_session_factory()() as anchor_db:
        return await persist(anchor_db)
