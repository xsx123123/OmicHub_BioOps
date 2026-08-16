"""MCP 预设服务注册表 — 内置 MCP（平台操作 / 生信工具箱）

内置服务（transport=builtin）在进程内执行，无需外部进程，便于开箱即用。
真实 stdio/sse MCP 由 MCPClient 通过 Python MCP SDK 接入。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.tool_bridge_service import get_tool_bridge_service
from omichub.infrastructure.mcp.pipeline_preset import (
    OMICHUB_PIPELINES_SERVER_ID,
    OMICHUB_PIPELINES_SERVER_NAME,
    build_pipeline_preset,
)

# omichub-tools builtin preset 的确定性 UUID（uuid5 DNS namespace + name）
OMICHUB_TOOLS_SERVER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "omichub-tools.builtin")
OMICHUB_TOOLS_SERVER_NAME = "omichub-tools"


async def _omichub_tools_handler(
    arguments: dict[str, Any],
    tool_name: str = "",
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
) -> dict[str, Any]:
    """omichub-tools builtin preset 的统一 handler。"""
    if not user_id:
        user_id = arguments.get("_user_id", "anonymous")
    return await get_tool_bridge_service().execute(
        user_id=user_id,
        tool_name=tool_name,
        arguments=arguments,
        context=context,
    )


# ====================== 平台操作工具 (builtin) ======================

OMICHUB_PLATFORM_SERVER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "omichub-platform.builtin")

# 工作区文件工具系统提示后缀 —— 外置到 data/ai/mcp/workspace_files_prompt.md，
# 便于直接编辑提示词而无需改代码；文件缺失时回退到内置精简版。
_WORKSPACE_FILES_PROMPT_MD = Path("data/ai/mcp/workspace_files_prompt.md")

_WORKSPACE_FILES_PROMPT_FALLBACK = """## 工作区文件工具

你拥有当前会话用户工作区的只读文件工具：`list_workspace_files`、`search_workspace_files`、
`find_session_uploads`（按会话找回上传文件），找到文件后将 `file_id` 交给 `workspace_read_file` 读取。
数据缺失或任务背景不清晰时，必须先调用 `ask_user` 弹窗向用户澄清（options 给可点选选项，
推荐项放第一个标注“（推荐）”），禁止自行假设开干；用户已给出关键信息时直接执行，不重复澄清。
会话隔离：只允许使用本会话中用户上传或明确指定的文件；其它会话的文件禁止主动读取或
当作本次任务数据，确需使用必须先经 `ask_user` 弹窗得到用户明确确认。
系统发育树 / ggtree：必须先确认输入是 `.treefile` / `.contree` / `.nwk` / `.newick` / `.tree`
等可解析树文件；`.iqtree` 是文本报告，不能整份直接交给 `ape::read.tree()` 或 `ggtree`。
若用户只提供 `.iqtree`，先检查并可靠提取 `Tree in newick format:` 段到独立 `.nwk`，否则调用
`ask_user` 请求同批产物中的 `.treefile` 或 `.contree`；解析验证通过后才绘图。
"""


def _load_workspace_files_prompt() -> str:
    try:
        text = _WORKSPACE_FILES_PROMPT_MD.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    return _WORKSPACE_FILES_PROMPT_FALLBACK


WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX = _load_workspace_files_prompt()


async def _platform_list_tasks(
    arguments: dict[str, Any], user_id: str | None = None, **_kw: Any
) -> dict[str, Any]:
    from omichub.application.services.task_service import TaskService
    from omichub.infrastructure.database.session import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        service = TaskService(db)
        result = await service.list_tasks(user_id or "anonymous", status=arguments.get("status"))
        tasks = result.tasks if hasattr(result, "tasks") else []
        return {
            "tasks": [
                {"id": str(t.id), "name": t.name, "flow_id": t.flow_id, "status": t.status, "progress": t.progress}
                for t in tasks[:30]
            ]
        }


async def _platform_get_task(
    arguments: dict[str, Any], user_id: str | None = None, **_kw: Any
) -> dict[str, Any]:
    from omichub.application.services.task_service import TaskService
    from omichub.infrastructure.database.session import get_session_factory

    task_id = arguments.get("task_id", "")
    factory = get_session_factory()
    async with factory() as db:
        service = TaskService(db)
        t = await service.get_task(uuid.UUID(task_id), user_id or "anonymous")
        return {
            "id": str(t.id), "name": t.name, "flow_id": t.flow_id,
            "status": t.status, "progress": t.progress,
            "work_dir": t.work_dir, "error_message": t.error_message,
            "created_at": str(t.created_at), "started_at": str(t.started_at),
        }


async def _platform_sandbox_execute(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    from omichub.application.services.sandbox_service import SandboxService
    from omichub.infrastructure.database.session import get_session_factory

    code = str(arguments.get("code", ""))
    language = str(arguments.get("language") or "python")
    if language not in {"python", "r", "bash"}:
        return {"stdout": "", "stderr": "", "error": f"不支持的语言: {language}"}

    async def execute(db: Any) -> dict[str, Any]:
        service = SandboxService(db)
        uid = uuid.UUID(user_id) if user_id else uuid.UUID(int=0)
        session = await service.create_session(uid, language)
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        error = None
        async for event in service.execute_code(uid, session.id, code, 300, language):
            etype = event.get("type")
            if etype == "stdout":
                stdout_parts.append(event.get("data", ""))
            elif etype == "stderr":
                stderr_parts.append(event.get("data", ""))
            elif etype == "error":
                error = event.get("detail")
        return {
            "stdout": "".join(stdout_parts)[-3000:],
            "stderr": "".join(stderr_parts)[-1000:],
            "error": error,
            "session_id": str(session.id),
        }

    if context is not None:
        return await execute(context.db)

    factory = get_session_factory()
    async with factory() as db:
        result = await execute(db)
        await db.commit()
        return result


async def _platform_list_flows(arguments: dict[str, Any], **_kw: Any) -> dict[str, Any]:
    from omichub.application.services.flow_service import FlowService

    service = FlowService()
    result = service.list_flows(category=arguments.get("category"))
    items = result.items if hasattr(result, "items") else []
    return {
        "flows": [
            {"id": f.id, "name": f.name, "category": f.category, "version": f.version}
            for f in items
        ]
    }


async def _platform_get_current_time(
    arguments: dict[str, Any], **_kw: Any
) -> dict[str, Any]:
    """Return the current platform-server time without starting a sandbox."""
    timezone_name = str(arguments.get("timezone") or "").strip()
    try:
        timezone = ZoneInfo(timezone_name) if timezone_name else datetime.now().astimezone().tzinfo
    except ZoneInfoNotFoundError:
        return {
            "error": "无效时区，请使用 IANA 时区名称，例如 Asia/Shanghai 或 America/Los_Angeles",
            "timezone": timezone_name,
        }

    now = datetime.now(timezone)
    return {
        "datetime": now.isoformat(),
        "date": now.date().isoformat(),
        "time": now.time().replace(microsecond=0).isoformat(),
        "weekday": now.strftime("%A"),
        "timezone": now.tzname(),
        "timezone_name": timezone_name or str(timezone),
        "utc_offset": now.strftime("%z"),
        "unix_timestamp": int(now.timestamp()),
    }


async def _platform_get_user_info(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """返回当前用户的基本信息与饼干（积分）账户余额。

    余额必须实时取自已落库的饼干账户（cookie_accounts），禁止由模型凭记忆/猜测
    作答；本工具是"我还有多少饼干/积分/额度"类问题的唯一权威数据源。
    """
    from omichub.core.config import get_settings
    from omichub.infrastructure.database.session import get_session_factory

    settings = get_settings()

    async def fetch(db: Any) -> dict[str, Any]:
        from omichub.infrastructure.database.repositories.user_repository import (
            SqlAlchemyUserRepository,
        )

        data: dict[str, Any] = {"success": True}
        uid: uuid.UUID | None = None
        if user_id:
            try:
                uid = uuid.UUID(str(user_id))
            except (ValueError, TypeError):
                uid = None
        if uid is None:
            return {"success": False, "error": "无法确定当前用户身份"}

        user = await SqlAlchemyUserRepository(db).get_by_id(uid)
        if user is not None:
            role = getattr(user.role, "value", user.role)
            data.update(
                {
                    "username": user.username,
                    "nickname": getattr(user, "nickname", None) or user.username,
                    "email": user.email,
                    "role": str(role),
                    "storage_quota_bytes": int(getattr(user, "storage_quota", 0) or 0),
                    "used_storage_bytes": int(getattr(user, "used_storage", 0) or 0),
                }
            )

        if settings.enable_cookie_system:
            from omichub.application.services.cookie_service import CookieService

            account = await CookieService(db).get_account(uid)
            data.update(
                {
                    "cookie_balance": float(account.balance),
                    "cookie_frozen_balance": float(account.frozen_balance),
                    "cookie_available_balance": float(account.available_balance),
                    "cookie_total_earned": float(account.total_earned),
                    "cookie_total_spent": float(account.total_spent),
                    "cookie_account_status": account.status,
                }
            )
        return data

    if context is not None:
        data = await fetch(context.db)
    else:
        factory = get_session_factory()
        async with factory() as db:
            data = await fetch(db)

    if not data.get("success"):
        return data

    def _fmt(num: float) -> str:
        s = f"{num:,.1f}"
        return s[:-2] if s.endswith(".0") else s

    lines: list[str] = []
    if "username" in data:
        lines.append(f"用户: {data['username']}（{data.get('email', '?')}），角色: {data.get('role', '?')}")
    if "cookie_available_balance" in data:
        lines.append(
            f"🍪 饼干余额: {_fmt(data['cookie_available_balance'])}"
            + (f"（其中冻结 {_fmt(data['cookie_frozen_balance'])}）" if data["cookie_frozen_balance"] else "")
        )
    if data.get("storage_quota_bytes"):
        used_gb = data["used_storage_bytes"] / 1024**3
        total_gb = data["storage_quota_bytes"] / 1024**3
        lines.append(f"存储: {used_gb:.1f}GB / {total_gb:.1f}GB")
    data["summary"] = "\n".join(lines) if lines else "已获取用户信息"
    return data


async def _platform_admin_health_check(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Return a read-only platform health snapshot after enforcing the admin role."""
    from sqlalchemy import func, select

    from omichub.core.config import get_settings
    from omichub.infrastructure.cache.redis_client import get_redis
    from omichub.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
    from omichub.infrastructure.database.models.knowledge_chunk import KbChunkModel
    from omichub.infrastructure.database.models.knowledge_document import KbDocumentModel
    from omichub.infrastructure.database.models.task import TaskModel
    from omichub.infrastructure.database.models.user import UserModel
    from omichub.infrastructure.database.session import get_session_factory

    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return {"success": False, "error": "无法确定当前管理员身份"}

    async def inspect(db: Any) -> dict[str, Any]:
        user = await db.get(UserModel, uid)
        if user is None or str(user.role) != "admin":
            return {"success": False, "error": "仅平台管理员可以执行运维健康检查"}

        user_rows = (
            await db.execute(select(UserModel.status, func.count()).group_by(UserModel.status))
        ).all()
        task_rows = (
            await db.execute(select(TaskModel.status, func.count()).group_by(TaskModel.status))
        ).all()
        knowledge_base_count = (
            await db.execute(
                select(func.count())
                .select_from(KnowledgeBaseModel)
                .where(
                    KnowledgeBaseModel.is_enabled.is_(True),
                    KnowledgeBaseModel.ai_searchable.is_(True),
                )
            )
        ).scalar_one()
        document_count = (
            await db.execute(select(func.count()).select_from(KbDocumentModel))
        ).scalar_one()
        chunk_count = (
            await db.execute(select(func.count()).select_from(KbChunkModel))
        ).scalar_one()
        return {
            "success": True,
            "database": {"status": "ok"},
            "users_by_status": {str(status): int(count) for status, count in user_rows},
            "tasks_by_status": {str(status): int(count) for status, count in task_rows},
            "knowledge": {
                "searchable_bases": int(knowledge_base_count),
                "documents": int(document_count),
                "chunks": int(chunk_count),
            },
        }

    if context is not None:
        snapshot = await inspect(context.db)
    else:
        factory = get_session_factory()
        async with factory() as db:
            snapshot = await inspect(db)
    if not snapshot.get("success"):
        return snapshot

    try:
        redis_ok = bool(await asyncio.wait_for(get_redis().ping(), timeout=2.0))
        redis_error = None
    except Exception as exc:  # noqa: BLE001 - health checks must return partial evidence
        redis_ok = False
        redis_error = type(exc).__name__
    snapshot["redis"] = {"status": "ok" if redis_ok else "error", "error": redis_error}

    settings = get_settings()
    storage_path = Path(settings.storage_path)
    storage: dict[str, Any] = {
        "path": str(storage_path),
        "exists": storage_path.is_dir(),  # noqa: ASYNC240 - bounded local health probe
        "readable": os.access(storage_path, os.R_OK),
        "writable": os.access(storage_path, os.W_OK),
    }
    try:
        usage = shutil.disk_usage(storage_path)
        storage.update(
            {
                "total_bytes": int(usage.total),
                "used_bytes": int(usage.used),
                "free_bytes": int(usage.free),
                "used_percent": round(usage.used / usage.total * 100, 2) if usage.total else None,
            }
        )
    except OSError as exc:
        storage["error"] = type(exc).__name__
    snapshot["storage"] = storage

    unhealthy = []
    if not redis_ok:
        unhealthy.append("redis")
    if not storage["exists"] or not storage["readable"] or not storage["writable"]:
        unhealthy.append("storage")
    snapshot["status"] = "healthy" if not unhealthy else "degraded"
    snapshot["attention_required"] = unhealthy
    snapshot["checked_at"] = datetime.now().astimezone().isoformat()
    return snapshot


async def _platform_read_file(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    from omichub.core.config import get_settings

    settings = get_settings()
    file_path = arguments.get("file_path", "")
    max_lines = int(arguments.get("max_lines", 50))
    user_root = Path(settings.storage_path) / "users" / (user_id or "anonymous")
    target = (user_root / file_path).resolve()

    if not str(target).startswith(str(user_root.resolve())):
        return {"error": "路径越权"}
    if not target.is_file():
        return {"error": "文件不存在"}

    lines: list[str] = []
    try:
        with open(target, errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line.rstrip("\n"))
    except OSError as e:
        return {"error": str(e)}

    return {"path": file_path, "lines": lines, "truncated": len(lines) >= max_lines}


# ====================== 工作区文件感知（builtin，按用户隔离，只读） ======================
# 对应《星尘 AI 工作区文件感知 + @ 引用》阶段 1：
#   workspace_list_files / workspace_read_file / workspace_get_file_info
# 权限硬限定为当前登录用户的工作区根目录；默认只读，不暴露任何写/删除能力。

# 可直接返回内容预览的文本类扩展名
_TEXT_SUFFIXES = frozenset(
    {
        ".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".log",
        ".vcf", ".gff", ".gtf", ".bed", ".sam", ".fasta", ".fa", ".fna",
        ".py", ".r", ".sh", ".xml", ".html", ".tsv.gz", ".csv.gz",
    }
)

# 二进制 / 测序原始数据：只回元数据，绝不读内容
_BINARY_ONLY_SUFFIXES = frozenset(
    {
        ".bam", ".cram", ".bai", ".crai", ".fastq", ".fq", ".fastq.gz", ".fq.gz",
        ".h5ad", ".h5", ".rds", ".rdata", ".loom", ".bw", ".bigwig", ".2bit",
        ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff",
        ".pdf", ".db", ".sqlite",
    }
)

# read_file 默认内容上限（100KB，超出截断并标注）
_DEFAULT_READ_MAX_BYTES = 100 * 1024


def _is_text_file(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suf) for suf in _TEXT_SUFFIXES)


def _human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"


async def _resolve_workspace_file(
    user_id: str, file_id: str, db: Any
) -> tuple[Path | None, dict[str, Any]]:
    """把工作区文件引用解析为物理路径 + 元数据。

    支持两种 file_id：
      - 文件中心记录（UUID，引用形如 file://{uuid}）；
      - 聊天上传文件（32 位 hex，引用形如 upload://{hex}）。
    强制按 user_id 做归属校验，拒绝路径逃逸。返回 (path, metadata)；
    path 为 None 时表示解析失败，metadata 含 error 说明。
    """
    from omichub.infrastructure.config.storage_config import get_user_chat_upload_dir
    from omichub.infrastructure.database.repositories.file_repository import (
        FileRepositoryImpl,
    )

    fid = (file_id or "").strip()
    # 兼容 file://uuid、upload://hex，以及被二次包裹的 upload://file://uuid。
    # 显式 upload://  scheme 直接走聊天上传通道：32 位 hex 的聊天上传 id
    # 也能被 uuid.UUID() 解析，误判会错路由到文件中心分支导致"文件不存在"。
    explicit_upload_scheme = False
    for _ in range(3):
        if fid.startswith("file://"):
            fid = fid[len("file://"):]
        elif fid.startswith("upload://"):
            fid = fid[len("upload://"):]
            explicit_upload_scheme = True
        else:
            break
    fid = fid.strip()
    if not fid or ".." in fid or fid.startswith("/"):
        return None, {"error": f"非法 file_id: {file_id}"}

    # 1) 文件中心记录（UUID）——仓储层强制 user_id 过滤防水平越权
    try:
        file_uuid = uuid.UUID(fid)
    except ValueError:
        file_uuid = None

    if file_uuid is not None and not explicit_upload_scheme:
        from omichub.application.services.file_service import FileService

        repo = FileRepositoryImpl(db)
        data_file = await repo.get_by_id(uuid.UUID(user_id), file_uuid)
        if data_file is not None:
            service = FileService(db)
            target = await service.get_file_path(uuid.UUID(user_id), file_uuid)  # 已做路径越权校验
            try:
                target.resolve().relative_to(service.user_root(uuid.UUID(user_id)).resolve())
            except ValueError:
                return None, {"error": "文件不在当前用户工作区内"}
            meta = {
                "file_id": fid,
                "ref": f"file://{fid}",
                "name": data_file.original_name,
                "size": data_file.size,
                "size_human": _human_size(data_file.size),
                "file_type": (
                    data_file.file_type.value
                    if hasattr(data_file.file_type, "value")
                    else str(data_file.file_type)
                ),
                "directory": getattr(data_file, "directory", "") or "",
                "created_at": (
                    data_file.created_at.isoformat() if getattr(data_file, "created_at", None) else None
                ),
            }
            return target, meta
        # 文件中心未命中：可能是裸 hex 的聊天上传 id，继续走聊天上传分支兜底

    # 2) 聊天上传文件（hex id，落盘名可能带扩展名，用前缀 glob 匹配）
    upload_dir = get_user_chat_upload_dir(user_id)
    candidates = sorted(upload_dir.glob(f"{fid}*"), key=lambda p: (len(p.suffix), p.name))
    if not candidates:
        return None, {"error": f"文件不存在: {fid}"}
    target = candidates[0]
    try:
        target.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        return None, {"error": "路径越权"}
    stat = target.stat()
    meta = {
        "file_id": fid,
        "ref": f"upload://{fid}",
        "name": target.name,
        "size": stat.st_size,
        "size_human": _human_size(stat.st_size),
        "file_type": "chat_upload",
        "directory": "workspace/chat-uploads",
        "created_at": None,
    }
    return target, meta


async def _workspace_list_files(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """兼容旧工具名，委托规范的 ``list_workspace_files`` 实现。"""
    result = await _list_workspace_files(arguments, user_id=user_id, context=context)
    result["files"] = [
        {**item, "file_id": f"file://{item['file_id']}"}
        for item in result["items"]
        if item["type"] == "file"
    ]
    result["directories"] = [
        item["relative_path"] for item in result["items"] if item["type"] == "folder"
    ]
    return result


async def _list_workspace_files(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
) -> dict[str, Any]:
    """列出当前用户工作区目录的文件和文件夹。"""
    from omichub.application.services.file_service import FileService
    from omichub.infrastructure.database.session import get_session_factory

    uid = uuid.UUID(user_id) if user_id else None
    if uid is None:
        return {"error": "无法识别当前用户"}
    if context is not None:
        result = await FileService(context.db).list_workspace_files(
            uid,
            path=arguments.get("path"),
            pattern=arguments.get("pattern"),
            recursive=bool(arguments.get("recursive", False)),
        )
    else:
        factory = get_session_factory()
        async with factory() as db:
            result = await FileService(db).list_workspace_files(
                uid,
                path=arguments.get("path"),
                pattern=arguments.get("pattern"),
                recursive=bool(arguments.get("recursive", False)),
            )

    lines = []
    for item in result["items"]:
        if item["type"] == "folder":
            lines.append(f"- [文件夹] {item['name']}/ · 修改于 {item['modified_at']}")
        else:
            lines.append(
                f"- {item['name']} · {_human_size(int(item['size']))} · "
                f"修改于 {item['modified_at']} · file_id={item['file_id']}"
            )
    scope = result["path"] or "工作区根目录"
    summary_limit = 100
    summary_lines = lines[:summary_limit]
    summary_suffix = (
        f"\n…其余 {len(lines) - summary_limit} 项请使用返回的 items 字段。"
        if len(lines) > summary_limit
        else ""
    )
    result["summary"] = (
        f"{scope} 下共 {result['total']} 项：\n"
        + "\n".join(summary_lines)
        + summary_suffix
        if lines
        else f"{scope} 为空"
    )
    result["hint"] = (
        "请直接依据 summary 汇总并回复用户；不要重复调用本工具。"
        "如需查看文件内容，再将文件项的 file_id 交给 workspace_read_file。"
    )
    return result


async def _search_workspace_files(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
) -> dict[str, Any]:
    """按文件名模糊搜索当前用户工作区的统一文件索引。"""
    from omichub.application.services.file_service import FileService
    from omichub.infrastructure.database.session import get_session_factory

    uid = uuid.UUID(user_id) if user_id else None
    if uid is None:
        return {"error": "无法识别当前用户"}
    query = str(arguments.get("query") or "").strip()
    try:
        limit = max(1, min(int(arguments.get("limit", 50)), 50))
    except (TypeError, ValueError):
        limit = 50

    if context is not None:
        listing = await FileService(context.db).search_files(uid, query=query, limit=limit)
    else:
        factory = get_session_factory()
        async with factory() as db:
            listing = await FileService(db).search_files(uid, query=query, limit=limit)

    items = [
        {
            "file_id": str(file.id),
            "name": file.original_name,
            "relative_path": file.path,
            "modified_at": file.modified_at.isoformat(),
        }
        for file in listing.items
    ]
    lines = [
        f"- {item['name']} · {item['relative_path']} · 修改于 {item['modified_at']} · "
        f"file_id={item['file_id']}"
        for item in items
    ]
    return {
        "query": query,
        "items": items,
        "total": len(items),
        "summary": (
            f"找到 {len(items)} 个匹配文件：\n" + "\n".join(lines)
            if lines
            else f"未找到名称包含“{query}”的文件"
        ),
        "hint": "可将匹配项的 file_id 直接交给 workspace_read_file 读取或分析。",
    }


async def _find_session_uploads(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
) -> dict[str, Any]:
    """按会话 ID 检索该聊天窗口中上传过的文件。

    聊天上传文件名内嵌会话短标记（``.s{session_id前8位}``），本工具按标记
    在 chat-uploads 目录中匹配；session_id 缺省时取当前调用上下文中的会话 ID。
    """
    from omichub.infrastructure.config.storage_config import get_user_chat_upload_dir

    session_id = str(arguments.get("session_id") or "").strip()
    if not session_id and context is not None:
        session_id = (context.session_id or "").strip()
    short = session_id[:8]
    if not short:
        return {"error": "缺少 session_id，且当前调用上下文无会话信息"}
    if not user_id:
        return {"error": "无法识别当前用户"}

    upload_dir = get_user_chat_upload_dir(user_id)
    marker = f".s{short}"
    items: list[dict[str, Any]] = []
    if upload_dir.is_dir():
        for path in sorted(upload_dir.iterdir()):
            if not path.is_file() or marker not in path.name:
                continue
            fid = path.name.split(".", 1)[0]
            stat = path.stat()
            items.append(
                {
                    "file_id": fid,
                    "ref": f"upload://{fid}",
                    "name": path.name,
                    "size": stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "session_id": session_id,
                }
            )
    lines = [f"- {item['name']} · {item['size_human']} · file_id={item['ref']}" for item in items]
    if not items:
        # 跨会话兜底：本（或指定）会话没有标记上传时，列出该用户最近上传的文件，
        # 覆盖"上一个聊天窗口上传的数据在新窗口要继续用"的场景；
        # 老文件（无会话标记）也能在这里被找回。
        try:
            recent = sorted(
                (p for p in upload_dir.iterdir() if p.is_file()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:10]
        except OSError:
            recent = []
        for path in recent:
            fid = path.name.split(".", 1)[0]
            stat = path.stat()
            items.append(
                {
                    "file_id": fid,
                    "ref": f"upload://{fid}",
                    "name": path.name,
                    "size": stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "session_id": None,
                }
            )
        if items:
            lines = [f"- {item['name']} · {item['size_human']} · file_id={item['ref']}" for item in items]
            return {
                "session_id": session_id,
                "items": items,
                "total": len(items),
                "fallback": "recent_uploads",
                "summary": (
                    f"会话 {session_id} 下没有检索到上传文件；"
                    f"以下 {len(items)} 个文件来自其它会话的上传历史：\n" + "\n".join(lines)
                ),
                "hint": (
                    "这些文件不属于当前会话，禁止直接当作本次任务的数据使用。"
                    "必须先调用 ask_user 弹窗向用户确认是否使用其中某个文件"
                    "（或请用户重新上传），得到用户明确确认后方可读取。"
                ),
            }
    return {
        "session_id": session_id,
        "items": items,
        "total": len(items),
        "summary": (
            f"会话 {session_id} 上传过 {len(items)} 个文件：\n" + "\n".join(lines)
            if items
            else f"会话 {session_id} 下没有检索到上传文件，也没有可回溯的历史上传"
        ),
        "hint": "可将 file_id（upload://…）直接交给 workspace_read_file 读取或分析。",
    }


async def _workspace_get_file_info(
    arguments: dict[str, Any], user_id: str | None = None, **_kw: Any
) -> dict[str, Any]:
    """返回工作区文件的元数据（不读内容）。"""
    from omichub.infrastructure.database.session import get_session_factory

    file_id = arguments.get("file_id", "")
    if not user_id:
        return {"error": "无法识别当前用户"}
    factory = get_session_factory()
    async with factory() as db:
        target, meta = await _resolve_workspace_file(user_id, file_id, db)
    if target is None:
        return meta
    meta["exists"] = target.is_file()
    meta["is_text"] = _is_text_file(meta["name"])
    meta["summary"] = (
        f"{meta['name']}（{meta['size_human']}，{meta['file_type']}，"
        f"{'文本' if meta['is_text'] else '二进制'}）"
    )
    return meta


async def _workspace_read_file(
    arguments: dict[str, Any], user_id: str | None = None, **_kw: Any
) -> dict[str, Any]:
    """读取工作区文本文件内容预览。

    - 文本类：返回前 max_bytes（默认 100KB）内容，超出截断并标注；
    - 二进制类（BAM/CRAM/FASTQ 等）：只返回元数据，不读内容，引导走分析流程。
    """
    from omichub.infrastructure.database.session import get_session_factory

    file_id = arguments.get("file_id", "")
    try:
        max_bytes = int(arguments.get("max_bytes", _DEFAULT_READ_MAX_BYTES))
    except (TypeError, ValueError):
        max_bytes = _DEFAULT_READ_MAX_BYTES
    max_bytes = max(1, min(max_bytes, 1024 * 1024))  # 上限 1MB，防撑爆上下文

    if not user_id:
        return {"error": "无法识别当前用户"}
    factory = get_session_factory()
    async with factory() as db:
        target, meta = await _resolve_workspace_file(user_id, file_id, db)
    if target is None:
        return meta
    if not target.is_file():
        return {"error": "文件已被移除", **meta}

    name = meta["name"]
    # 二进制 / 测序原始数据：只回元数据
    if not _is_text_file(name) or name.lower().endswith(tuple(_BINARY_ONLY_SUFFIXES)):
        meta["content"] = None
        meta["truncated"] = False
        meta["summary"] = (
            f"{name} 为二进制/测序数据（{meta['size_human']}），不直接读取内容。"
            "请使用相应分析流程处理，或用 workspace_get_file_info 查看元数据。"
        )
        return meta

    size = target.stat().st_size
    truncated = size > max_bytes
    try:
        with open(target, encoding="utf-8", errors="replace") as fh:
            content = fh.read(max_bytes)
    except OSError as e:
        return {"error": f"读取失败: {e}", **meta}

    meta["content"] = content
    meta["truncated"] = truncated
    meta["summary"] = (
        f"文件 {name}（{meta['size_human']}）内容预览"
        + (f"，已截断至前 {max_bytes} 字节" if truncated else "")
    )
    return meta


async def _platform_submit_download(
    arguments: dict[str, Any], user_id: str | None = None, **_kw: Any
) -> dict[str, Any]:
    """提交数据下载任务（SRA/GEO 公共数据库、云存储、直链）。"""
    from omichub.application.schemas.download import DownloadRequest
    from omichub.application.services.download_service import DownloadService
    from omichub.core.config import get_settings
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.tools.download.config import get_download_config

    if not user_id:
        return {"error": "无法识别当前用户"}

    payload = {k: v for k, v in arguments.items() if v is not None}
    try:
        req = DownloadRequest(**payload)
    except Exception as e:  # noqa: BLE001
        return {"error": f"下载参数不合法: {e}"}

    # 与 REST 路由 _ensure_enabled 保持一致的功能开关校验
    settings = get_settings()
    config = get_download_config()
    if req.source == "direct_link":
        if not (config.features.direct_link or settings.enable_direct_download):
            return {"error": "直链下载功能未启用"}
    elif req.source == "cloud_storage":
        if not (config.features.cloud_storage or settings.enable_cloud_storage_download):
            return {"error": "云存储下载功能未启用"}
    elif not (config.features.ebi or settings.enable_ebi_download):
        return {"error": "公共数据库下载功能未启用"}

    factory = get_session_factory()
    async with factory() as db:
        service = DownloadService(db)
        resp = await service.submit(user_id, req)
        await db.commit()
        work_dir = getattr(resp, "work_dir", "") or ""
        return {
            "task_id": str(resp.id),
            "name": resp.name,
            "status": resp.status,
            "work_dir": work_dir,
            "summary": (
                f"下载任务已提交: {resp.name}（task_id={resp.id}）\n"
                f"产物目录: {work_dir or '用户 raw_data'}（完成后自动登记到数据管理）"
            ),
            "next_steps": [
                f"调用 platform_get_download_progress(task_id='{resp.id}') 查看下载进度",
            ],
        }


async def _platform_list_downloads(
    arguments: dict[str, Any], user_id: str | None = None, **_kw: Any
) -> dict[str, Any]:
    """列出当前用户的数据下载任务。"""
    from omichub.application.services.download_service import DownloadService
    from omichub.infrastructure.database.session import get_session_factory

    if not user_id:
        return {"error": "无法识别当前用户"}
    factory = get_session_factory()
    async with factory() as db:
        resp = await DownloadService(db).list_downloads(user_id)
    items = [
        {"id": str(t.id), "name": t.name, "status": t.status, "progress": t.progress}
        for t in resp.items
    ]
    lines = [
        f"- [{t['status']}] {t['name']} (progress={t['progress']:.0%}, id={t['id']})"
        for t in items
    ]
    return {
        "downloads": items,
        "summary": "下载任务:\n" + "\n".join(lines) if lines else "暂无下载任务",
    }


async def _platform_get_download_progress(
    arguments: dict[str, Any], user_id: str | None = None, **_kw: Any
) -> dict[str, Any]:
    """获取下载任务的逐 run 分阶段进度（下载/解压/压缩）。"""
    from omichub.application.services.download_service import DownloadService
    from omichub.infrastructure.cache.redis_client import get_redis
    from omichub.infrastructure.database.session import get_session_factory

    if not user_id:
        return {"error": "无法识别当前用户"}
    task_id = str(arguments.get("task_id", "")).strip()
    if not task_id:
        return {"error": "缺少 task_id"}
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        return {"error": f"task_id 不合法: {task_id}"}

    factory = get_session_factory()
    async with factory() as db:
        service = DownloadService(db)
        try:
            task_resp = await service.get_task_for_user(task_uuid, user_id)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    redis = get_redis()
    raw = await redis.get(f"download_progress:{task_uuid}")
    if raw is None:
        return {
            "task_id": task_id,
            "task_status": task_resp.status,
            "overall_percent": task_resp.progress * 100,
            "runs": {},
            "summary": (
                f"进度暂不可用（任务状态 {task_resp.status}，排队中或进度接口未就绪），"
                f"任务整体进度 {task_resp.progress * 100:.1f}%，可稍后再查。"
            ),
        }

    import json

    runs_data = json.loads(raw)
    runs: dict[str, Any] = {}
    lines = []
    for run_id, rp in runs_data.items():
        runs[run_id] = {
            "stage": rp["stage"],
            "overall_percent": rp["overall_percent"],
        }
        lines.append(f"- {run_id}: {rp['stage']} ({rp['overall_percent']:.1f}%)")
    overall = (
        sum(r["overall_percent"] for r in runs.values()) / len(runs) if runs else 0.0
    )
    return {
        "task_id": task_id,
        "task_status": task_resp.status,
        "overall_percent": overall,
        "runs": runs,
        "summary": f"总进度: {overall:.1f}%\n" + "\n".join(lines),
    }


async def _platform_europe_pmc_search(
    arguments: dict[str, Any],
    **_kw: Any,
) -> dict[str, Any]:
    """Search Europe PMC and return a relevance-ranked biomedical evidence set."""
    from omichub.application.services.biomedical_literature_service import (
        BiomedicalLiteratureService,
    )
    from omichub.application.services.research_search_optimizer import (
        ResearchSearchOptimizer,
    )

    query = " ".join(str(arguments.get("query") or "").split())
    if not query:
        return {"success": False, "error": "缺少 query 参数"}
    max_results = max(1, min(int(arguments.get("max_results") or 8), 20))
    try:
        candidates = await BiomedicalLiteratureService(timeout_seconds=10).search(
            query,
            max(max_results * 2, 8),
            year_from=arguments.get("year_from"),
            year_to=arguments.get("year_to"),
            open_access_only=bool(arguments.get("open_access_only", False)),
        )
        results = await ResearchSearchOptimizer().rerank(
            query,
            candidates,
            limit=max_results,
        )
        return {
            "success": True,
            "result": {
                "query": query,
                "provider": "Europe PMC",
                "result_count": len(results),
                "results": results,
            },
        }
    except Exception as exc:  # noqa: BLE001 - return a bounded MCP error
        return {"success": False, "error": f"Europe PMC 检索失败: {type(exc).__name__}"}


PLATFORM_PRESET_TOOLS = [
    {
        "name": "europe_pmc_search",
        "description": (
            "检索 Europe PMC 权威生物医学论文，并按用户问题对标题与摘要进行语义/词项混合重排。"
            "适合基因、疾病机制、单细胞、肿瘤免疫、组学方法和临床研究证据检索。"
            "返回题名、摘要、作者、期刊、年份、PMID/PMCID/DOI、开放获取状态和可追溯链接。"
            "只读且不下载全文；研究问答通常保留最相关的 5-8 篇。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "英文联合检索式；建议使用 2-4 个核心概念并以 AND/OR 连接",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 8,
                    "description": "返回数量；研究问答推荐 5-8",
                },
                "year_from": {"type": "integer", "description": "可选起始发表年份"},
                "year_to": {"type": "integer", "description": "可选结束发表年份"},
                "open_access_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否仅返回开放获取论文",
                },
            },
            "required": ["query"],
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "platform_list_tasks",
        "description": "列出用户的分析任务（状态、进度）",
        "inputSchema": {
            "type": "object",
            "properties": {"status": {"type": "string", "description": "过滤状态"}},
        },
    },
    {
        "name": "platform_get_task",
        "description": "获取任务详情（状态、进度、工作目录、错误）",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "platform_list_flows",
        "description": "列出可用的分析流程",
        "inputSchema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
        },
    },
    {
        "name": "platform_get_user_info",
        "description": (
            "获取当前用户的账户信息与饼干（积分）余额：用户名、角色、存储配额/已用空间，"
            "以及饼干可用余额/冻结/累计收支。用户询问「我还有多少饼干/积分/额度/余额」时"
            "必须调用本工具获取实时数据，禁止凭记忆或估计作答。"
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "platform_get_current_time",
        "description": (
            "获取平台服务器当前时间、今天日期、星期、时区偏移和 Unix 时间戳。"
            "查询当前时间或日期时优先调用，不需要启动沙箱。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "可选 IANA 时区，如 Asia/Shanghai、America/Los_Angeles；留空使用平台服务器本地时区",
                }
            },
        },
    },
    {
        "name": "platform_admin_health_check",
        "description": (
            "管理员专用的只读平台巡检：检查数据库可查询性、Redis、共享存储容量与权限、"
            "用户/任务状态分布及知识库文档和分块数量。不会修改配置、重启服务或执行修复。"
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "platform_sandbox_execute",
        "description": "在沙箱中执行 Python、R 或 Bash 代码（mambaforge 环境，含 ggtree 绘图依赖）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "enum": ["python", "r", "bash"],
                    "default": "python",
                    "description": "执行语言；ggtree 必须使用 r",
                },
                "code": {"type": "string", "description": "要执行的完整代码"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "platform_read_file",
        "description": "读取用户目录下分析结果文件（前 N 行）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "相对路径"},
                "max_lines": {"type": "integer", "default": 50},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "list_workspace_files",
        "description": (
            "列出当前会话用户工作区指定目录的直接子项，返回 file_id、名称、文件/文件夹类型、"
            "大小、相对路径和修改时间。用户询问工作区有什么文件时必须调用。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "工作区内相对目录，留空表示根目录；禁止绝对路径和 ..",
                },
                "pattern": {
                    "type": "string",
                    "description": "可选 glob 过滤，如 *.csv、sample_*.fastq.gz",
                },
                "recursive": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否递归列出目录下所有文件；用户询问有哪些数据文件时设为 true",
                },
            },
        },
    },
    {
        "name": "search_workspace_files",
        "description": (
            "从当前会话用户工作区根目录递归按文件名模糊搜索，返回 file_id、名称、相对路径和修改时间。"
            "用户要求寻找某个数据文件时必须调用。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "文件名搜索词"},
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "workspace_list_files",
        "description": (
            "兼容旧版名称；列出当前用户工作区某目录下的文件与子目录。"
            "新调用优先使用 list_workspace_files。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对目录路径，空串=工作区根目录（如 raw_data、results、enrichment）",
                },
                "pattern": {"type": "string", "description": "可选 glob 过滤，如 *.csv"},
            },
        },
    },
    {
        "name": "workspace_read_file",
        "description": (
            "按 file_id 读取工作区文本文件内容预览（默认前 100KB，超出截断）；"
            "二进制/测序文件（BAM/CRAM/FASTQ 等）只返回元数据。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文件 ID，形如 file://{uuid} 或 upload://{hex}（来自列表或 @ 引用）",
                },
                "max_bytes": {"type": "integer", "default": 102400, "description": "最多读取字节数"},
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "find_session_uploads",
        "description": (
            "按会话 ID 检索该聊天窗口中用户上传过的文件（聊天上传文件名内嵌会话标记）。"
            "session_id 留空时默认使用当前会话。需要找回本会话之前上传的数据文件时调用。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "聊天会话 ID（UUID），留空表示当前会话",
                },
            },
        },
    },
    {
        "name": "workspace_get_file_info",
        "description": "按 file_id 返回工作区文件的元数据（名称、大小、类型、目录、创建时间），不读内容。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文件 ID，形如 file://{uuid} 或 upload://{hex}",
                },
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "platform_submit_download",
        "description": (
            "提交数据下载任务，产物落到当前用户工作区 raw_data 目录（可选子目录），完成后自动登记到数据管理。"
            "支持三类来源（source）："
            "① sra（公共数据库高速下载，默认）：支持 NCBI SRA/GEO 系列登录号，包括项目号（PRJNA/PRJEB/PRJ 开头，"
            "如 PRJNA1285930）、测序 run（SRR/ERR/DRR 开头）、GEO 样本（GSM 开头）等；"
            "download_method 可选 aws（推荐，S3 全球镜像最快）/aspera/ftp，multithreads 控制并发 run 数，"
            "aws_threads 控制单文件 AWS 并发线程，dry_run=True 可先验证登录号不实际下载。"
            "② cloud_storage（多云服务商对象存储高速下载）：cloud_provider 取 aliyun(oss://)/volc(tos://)/huawei(obs://)，"
            "object_uri 需带对应前缀，recursive 控制是否递归。"
            "③ direct_link：links 传 HTTP/HTTPS/FTP 链接列表批量下载。"
            "提交前必须先用 ask_user 向用户确认登录号/地址与目标目录；用户已明确给出时直接提交。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["sra", "cloud_storage", "direct_link"],
                    "default": "sra",
                    "description": "下载来源：sra=公共数据库，cloud_storage=云存储，direct_link=直链",
                },
                "accession": {
                    "type": "string",
                    "description": "公共数据库登录号（PRJNA…/PRJEB…/SRR…/ERR…/DRR…/GSM…），source=sra 时必填",
                },
                "download_method": {
                    "type": "string",
                    "enum": ["aws", "aspera", "ftp"],
                    "default": "aws",
                    "description": "SRA 下载方式，aws 最快（仅 source=sra 有效）",
                },
                "multithreads": {
                    "type": "integer", "default": 4, "minimum": 1, "maximum": 32,
                    "description": "并发下载 run 数",
                },
                "aws_threads": {
                    "type": "integer", "default": 8, "minimum": 1, "maximum": 64,
                    "description": "单文件 AWS 并发线程数",
                },
                "cloud_provider": {
                    "type": "string",
                    "enum": ["aliyun", "volc", "huawei"],
                    "description": "云商（source=cloud_storage 时必填）",
                },
                "object_uri": {
                    "type": "string",
                    "description": "对象路径，如 oss://bucket/path、tos://bucket/path、obs://bucket/path（source=cloud_storage 时必填）",
                },
                "recursive": {
                    "type": "boolean", "default": True,
                    "description": "云存储目录是否递归下载",
                },
                "links": {
                    "type": "array", "items": {"type": "string"},
                    "description": "HTTP/HTTPS/FTP 下载链接列表（source=direct_link 时必填）",
                },
                "target_directory": {
                    "type": "string",
                    "description": "下载到用户 raw_data 下的子目录（如 project_x），留空=raw_data 根目录",
                },
                "dry_run": {
                    "type": "boolean", "default": False,
                    "description": "仅模拟下载验证登录号（仅 SRA）",
                },
            },
        },
    },
    {
        "name": "platform_list_downloads",
        "description": "列出当前用户的数据下载任务（名称、状态、进度、任务 ID）。用户询问下载情况/下载历史时调用。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "platform_get_download_progress",
        "description": (
            "获取下载任务的逐 run 分阶段进度（下载/解压/压缩）与总进度百分比。"
            "提交下载任务后可轮询此工具向用户汇报进度。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "下载任务 ID（UUID）"},
            },
            "required": ["task_id"],
        },
    },
]

PLATFORM_HANDLERS = {
    "europe_pmc_search": _platform_europe_pmc_search,
    "platform_list_tasks": _platform_list_tasks,
    "platform_get_task": _platform_get_task,
    "platform_list_flows": _platform_list_flows,
    "platform_get_user_info": _platform_get_user_info,
    "platform_get_current_time": _platform_get_current_time,
    "platform_admin_health_check": _platform_admin_health_check,
    "platform_sandbox_execute": _platform_sandbox_execute,
    "platform_read_file": _platform_read_file,
    "list_workspace_files": _list_workspace_files,
    "search_workspace_files": _search_workspace_files,
    "workspace_list_files": _workspace_list_files,
    "workspace_read_file": _workspace_read_file,
    "workspace_get_file_info": _workspace_get_file_info,
    "find_session_uploads": _find_session_uploads,
    "platform_submit_download": _platform_submit_download,
    "platform_list_downloads": _platform_list_downloads,
    "platform_get_download_progress": _platform_get_download_progress,
}


# 预设服务定义
PRESET_SERVERS: list[dict[str, Any]] = [
    {
        "name": "omichub-platform",
        "description": "平台操作 MCP - Europe PMC 文献检索、任务管理、流程查询、当前用户与饼干（积分）余额查询、沙箱执行、结果读取、数据下载（SRA/GEO 公共数据库与多云存储）",
        "transport": "builtin",
        "tools": PLATFORM_PRESET_TOOLS,
        "handlers": PLATFORM_HANDLERS,
    },
    build_pipeline_preset(),
]


def _build_omichub_tools_preset() -> dict[str, Any]:
    """动态构建 omichub-tools builtin preset（tools 来自 tools_schema.yaml + 动态 Flow）。"""
    from omichub.application.services.flow_service import FlowService
    from omichub.tools.flow_schema_compiler import FlowToolSchemaCompiler
    from omichub.tools.schema_loader import schema_loader

    static_tools = schema_loader.to_openai_tools()
    handlers = {t["function"]["name"]: _omichub_tools_handler for t in static_tools}

    # 动态编译 ai.enabled 的 Flow 为 MCP tool
    compiler = FlowToolSchemaCompiler()
    flow_service = FlowService()
    dynamic_tools: list[dict[str, Any]] = []
    try:
        for flow_config in flow_service.list_ai_enabled_flows():
            try:
                tool_def = compiler.compile_prepare_tool(flow_config)
                tool_name = tool_def["name"]
                dynamic_tools.append(
                    {
                        "name": tool_name,
                        "description": tool_def["description"],
                        "inputSchema": tool_def["input_schema"],
                    }
                )
                handlers[tool_name] = _omichub_tools_handler
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).warning(
                    f"动态编译 Flow tool 失败: {flow_config.meta.id}", exc_info=True
                )

        # 通用查询工具
        for tool_def in [compiler.compile_status_tool(), compiler.compile_summary_tool()]:
            tool_name = tool_def["name"]
            dynamic_tools.append(
                {
                    "name": tool_name,
                    "description": tool_def["description"],
                    "inputSchema": tool_def["input_schema"],
                }
            )
            handlers[tool_name] = _omichub_tools_handler
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning("加载动态 Flow tools 失败", exc_info=True)

    def _tool_view(t: dict[str, Any]) -> dict[str, Any]:
        # 静态工具是 OpenAI function 格式，动态 Flow 工具已是 {name, description, inputSchema}
        f = t.get("function", t)
        return {
            "name": f["name"],
            "description": f.get("description", ""),
            "inputSchema": f.get("parameters") or f.get("inputSchema") or {},
        }

    tools_by_name: dict[str, dict[str, Any]] = {}
    for tool in [*static_tools, *dynamic_tools]:
        view = _tool_view(tool)
        tools_by_name.setdefault(view["name"], view)

    return {
        "name": "omichub-tools",
        "description": "OmicHub 生信工具箱 MCP - KEGG 富集、火山图、系统发育树及分析中心流程",
        "transport": "builtin",
        "tools": list(tools_by_name.values()),
        "handlers": handlers,
    }


def get_preset_by_name(name: str) -> dict[str, Any] | None:
    if name == "omichub-tools":
        return _build_omichub_tools_preset()
    if name == OMICHUB_PIPELINES_SERVER_NAME:
        return build_pipeline_preset()
    for p in PRESET_SERVERS:
        if p["name"] == name:
            return p
    return None


__all__ = [
    "PRESET_SERVERS",
    "OMICHUB_TOOLS_SERVER_ID",
    "OMICHUB_TOOLS_SERVER_NAME",
    "OMICHUB_PLATFORM_SERVER_ID",
    "WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX",
    "OMICHUB_PIPELINES_SERVER_ID",
    "OMICHUB_PIPELINES_SERVER_NAME",
    "PLATFORM_PRESET_TOOLS",
    "PLATFORM_HANDLERS",
    "get_preset_by_name",
    "_build_omichub_tools_preset",
]
