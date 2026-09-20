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

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.tool_bridge_service import get_tool_bridge_service
from cygnusx.infrastructure.mcp.pipeline_preset import (
    CYGNUSX_PIPELINES_SERVER_ID,
    CYGNUSX_PIPELINES_SERVER_NAME,
    build_pipeline_preset,
)

# seqout builtin preset 的确定性 UUID
SEQOUT_SERVER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "seqout.builtin")
SEQOUT_SERVER_NAME = "seqout"

# cygnusx-tools builtin preset 的确定性 UUID（uuid5 DNS namespace + name）
CYGNUSX_TOOLS_SERVER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "cygnusx-tools.builtin")
CYGNUSX_TOOLS_SERVER_NAME = "cygnusx-tools"


async def _cygnusx_tools_handler(
    arguments: dict[str, Any],
    tool_name: str = "",
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
) -> dict[str, Any]:
    """cygnusx-tools builtin preset 的统一 handler。"""
    if not user_id:
        # 禁止从 arguments 里自带 _user_id 伪造身份；builtin 调用必须由网关注入真实用户
        return {"error": "无法识别当前用户"}
    return await get_tool_bridge_service().execute(
        user_id=user_id,
        tool_name=tool_name,
        arguments=arguments,
        context=context,
    )


# ====================== 平台操作工具 (builtin) ======================

CYGNUSX_PLATFORM_SERVER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "cygnusx-platform.builtin")

# 工作区文件工具系统提示后缀 —— 外置到 data/ai/mcp/workspace_files_prompt.md，
# 便于直接编辑提示词而无需改代码；文件缺失时回退到内置精简版。
# 锚定仓库根目录（本文件位于 src/cygnusx/infrastructure/mcp/presets.py），不随进程 CWD 漂移。
_WORKSPACE_FILES_PROMPT_MD = (
    Path(__file__).resolve().parents[4] / "data" / "ai" / "mcp" / "workspace_files_prompt.md"
)

_WORKSPACE_FILES_PROMPT_FALLBACK = """## 工作区文件工具

你拥有当前会话用户工作区的只读文件工具：`list_workspace_files`、`search_workspace_files`、
`find_session_uploads`（按会话找回上传文件），找到文件后将 `file_id` 交给 `workspace_read_file` 读取。
作用域边界：这套工具访问的是平台用户工作区/文件中心（宿主侧存储），看不到 AI 工作台
沙盒里的 /workspace；Studio 模式下查看沙盒工作区（input/、output/ 等）改用
`workspace_list` / `workspace_read`，把文件中心数据引入沙盒用 `datahub_import`。
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
    from cygnusx.application.services.task_service import TaskService
    from cygnusx.infrastructure.database.session import get_session_factory

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
    from cygnusx.application.services.task_service import TaskService
    from cygnusx.infrastructure.database.session import get_session_factory

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
    from cygnusx.application.services.sandbox_service import SandboxService
    from cygnusx.infrastructure.database.session import get_session_factory

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
    from cygnusx.application.services.flow_service import FlowService

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


async def _platform_list_agent_skills(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """查询 Agent 当前绑定的技能列表（YAML 声明 + 实际安装/启用状态）。

    「你绑定了哪些技能 / 某 Agent 会什么」类问题的唯一权威数据源。
    """
    from sqlalchemy import select

    from cygnusx.infrastructure.database.models.agent import AgentTemplateModel
    from cygnusx.infrastructure.database.models.skill import SkillModel
    from cygnusx.infrastructure.database.session import get_session_factory

    agent_id = str(arguments.get("agent_id") or "").strip()
    if not agent_id and context is not None and context.agent_id:
        agent_id = str(context.agent_id)

    async def query(db: Any) -> dict[str, Any]:
        if not agent_id:
            return {"success": False, "error": "缺少 agent_id，且当前上下文无法确定 Agent"}
        agent = (
            await db.execute(
                select(AgentTemplateModel).where(AgentTemplateModel.agent_id == agent_id)
            )
        ).scalar_one_or_none()
        if agent is None:
            return {"success": False, "error": f"Agent '{agent_id}' 不存在"}
        declared = [str(sid) for sid in (agent.skill_ids or [])]
        installed: dict[str, Any] = {}
        if declared:
            rows = (
                (await db.execute(select(SkillModel).where(SkillModel.skill_id.in_(declared))))
                .scalars()
                .all()
            )
            installed = {str(s.skill_id): s for s in rows}
        skills = []
        for sid in declared:
            row = installed.get(sid)
            skills.append(
                {
                    "skill_id": sid,
                    "installed": row is not None,
                    "is_active": bool(row.is_active) if row else False,
                    "name": row.name if row else "",
                    "description": row.description if row else "",
                    "version": row.version if row else None,
                }
            )
        return {
            "success": True,
            "agent_id": agent_id,
            "agent_name": agent.name,
            "skills": skills,
        }

    if context is not None:
        return await query(context.db)
    factory = get_session_factory()
    async with factory() as db:
        return await query(db)


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
    from cygnusx.core.config import get_settings
    from cygnusx.infrastructure.database.session import get_session_factory

    settings = get_settings()

    async def fetch(db: Any) -> dict[str, Any]:
        from cygnusx.infrastructure.database.repositories.user_repository import (
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
            from cygnusx.application.services.cookie_service import CookieService

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

    from cygnusx.core.config import get_settings
    from cygnusx.infrastructure.cache.redis_client import get_redis
    from cygnusx.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
    from cygnusx.infrastructure.database.models.knowledge_chunk import KbChunkModel
    from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
    from cygnusx.infrastructure.database.models.task import TaskModel
    from cygnusx.infrastructure.database.models.user import UserModel
    from cygnusx.infrastructure.database.session import get_session_factory

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
    from cygnusx.core.config import get_settings

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
        ".db", ".sqlite",
    }
)

# read_file 默认内容上限（100KB，超出截断并标注）
_DEFAULT_READ_MAX_BYTES = 100 * 1024
_PDF_SUFFIX = ".pdf"
_DOCX_SUFFIX = ".docx"
_PDF_READ_MAX_CHARS = 50_000


def _is_text_file(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suf) for suf in _TEXT_SUFFIXES)


def _human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"


async def _extract_workspace_pdf_text(
    path: Path, max_chars: int = _PDF_READ_MAX_CHARS
) -> dict[str, Any]:
    """提取工作区 PDF 的分页文本；扫描版和加密文件返回可操作的错误。"""
    from cygnusx.application.services.pdf_models import WORKSPACE_MCP_CONFIG
    from cygnusx.application.services.pdf_processor import PDFProcessor

    config = {**WORKSPACE_MCP_CONFIG, "max_chars": max_chars}
    processor = PDFProcessor(config=config)
    result = await processor.process(str(path))

    if not result.success:
        return {
            "error": f"无法提取文本：{result.fallback_reason or 'unknown error'}。"
            "该 PDF 可能是扫描版或加密文件；请提供可搜索文字版 PDF 或 OCR 版本。"
        }

    # 对 JSON 输出，result.content 是 JSON 字符串；需检查原始 markdown 是否为空
    raw_content = (result.raw_markdown or "").strip()
    if not raw_content and not result.pages:
        return {
            "error": "无法提取文本：该 PDF 可能是扫描版、加密文件或不含可搜索文字。"
            "请提供可搜索文字版 PDF，或使用 OCR 后的文件。"
        }

    return {
        "content": result.content,
        "truncated": result.metadata.truncated,
        "pages_read": result.metadata.total_pages,
        "pdf_type": result.metadata.pdf_type.value,
        "confidence": result.metadata.confidence,
        "source": result.source.value,
        "fallback_reason": result.fallback_reason,
    }


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
    from cygnusx.infrastructure.config.storage_config import get_user_chat_upload_dir
    from cygnusx.infrastructure.database.repositories.file_repository import (
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
        from cygnusx.application.services.file_service import FileService

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
    from cygnusx.application.services.file_service import FileService
    from cygnusx.infrastructure.database.session import get_session_factory

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
    from cygnusx.application.services.file_service import FileService
    from cygnusx.infrastructure.database.session import get_session_factory

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
    from cygnusx.infrastructure.config.storage_config import get_user_chat_upload_dir

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
    from cygnusx.infrastructure.database.session import get_session_factory

    file_id = arguments.get("file_id", "")
    if not user_id:
        return {"error": "无法识别当前用户"}
    factory = get_session_factory()
    async with factory() as db:
        target, meta = await _resolve_workspace_file(user_id, file_id, db)
    if target is None:
        return meta
    meta["exists"] = target.is_file()
    meta["is_text"] = _is_text_file(meta["name"]) or meta["name"].lower().endswith(_PDF_SUFFIX)
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
    from cygnusx.infrastructure.database.session import get_session_factory

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
    if name.lower().endswith(_PDF_SUFFIX):
        extracted = await _extract_workspace_pdf_text(target)
        if error := extracted.get("error"):
            return {"error": error, **meta}
        meta["content"] = extracted["content"]
        meta["truncated"] = bool(extracted["truncated"])
        meta["summary"] = (
            f"PDF {name}（{meta['size_human']}）分页文本"
            + (
                f"，已截断至前 {extracted['pages_read']} 页"
                if extracted["truncated"]
                else ""
            )
        )
        return meta

    # DOCX：OOXML zip 容器，抽取正文纯文本，不按 UTF-8 硬读（否则注入乱码）
    if name.lower().endswith(_DOCX_SUFFIX):
        from cygnusx.application.services.chat.runtime_support import extract_docx_text

        text = await asyncio.to_thread(extract_docx_text, str(target))
        if not text:
            return {
                "error": "无法提取文本：该 DOCX 可能已损坏或不含正文内容。",
                **meta,
            }
        truncated = len(text) > max_bytes
        meta["content"] = text[:max_bytes]
        meta["truncated"] = truncated
        meta["summary"] = (
            f"DOCX {name}（{meta['size_human']}）正文文本"
            + (f"，已截断至前 {max_bytes} 字符" if truncated else "")
        )
        return meta

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
    from cygnusx.application.schemas.download import DownloadRequest
    from cygnusx.application.services.download_service import DownloadService
    from cygnusx.core.config import get_settings
    from cygnusx.infrastructure.database.session import get_session_factory
    from cygnusx.tools.download.config import get_download_config

    if not user_id:
        return {"error": "无法识别当前用户"}

    # 业务参数：剔除 None 值与下划线控制参数（_confirmation_id 等），
    # 保证确认记录哈希与消费时比对的哈希来自同一形态。
    business_args = {
        k: v for k, v in arguments.items() if v is not None and not k.startswith("_")
    }
    try:
        req = DownloadRequest(**business_args)
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

    # 服务端强制二次确认门：dry_run 预检免确认；正式提交必须先经人类点击确认卡
    # （POST /api/v1/ai/tool-invocations/{id}/approve），再以完全相同参数重试。
    if not req.dry_run:
        from cygnusx.application.services.tool_confirmation_service import (
            ConfirmationError,
            get_tool_confirmation_service,
        )

        confirmation_service = get_tool_confirmation_service()
        confirmation_id = str(arguments.get("_confirmation_id") or "").strip()
        if not confirmation_id:
            record = await confirmation_service.create_for_tool(
                user_id, "platform_submit_download", business_args
            )
            return {
                "success": True,
                "is_error": False,
                "llm_payload": {
                    "needs_confirm": True,
                    "tool_name": "platform_submit_download",
                    "confirmation_id": record.confirmation_id,
                    "code": "CONFIRMATION_REQUIRED",
                    "summary": (
                        "下载任务提交前需要用户在确认卡上点击确认；"
                        "请提醒用户确认，之后携带 _confirmation_id 使用完全相同的参数重试。"
                    ),
                    "preview_args": business_args,
                    "expires_at": record.expires_at.isoformat(),
                },
                "ui_payload": {
                    "confirm_card": True,
                    "tool_name": "platform_submit_download",
                    "confirmation_id": record.confirmation_id,
                    "args": business_args,
                    "actions": {
                        "approve": {
                            "method": "POST",
                            "url": (
                                "/api/v1/ai/tool-invocations/"
                                f"{record.confirmation_id}/approve"
                            ),
                        },
                        "reject": {
                            "method": "POST",
                            "url": (
                                "/api/v1/ai/tool-invocations/"
                                f"{record.confirmation_id}/reject"
                            ),
                        },
                    },
                },
            }
        try:
            await confirmation_service.consume_tool_confirmation(
                user_id, confirmation_id, "platform_submit_download", business_args
            )
        except ConfirmationError as e:
            return {"error": f"确认凭证校验失败({e.code}): {e.message}"}

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
    from cygnusx.application.services.download_service import DownloadService
    from cygnusx.infrastructure.database.session import get_session_factory

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
    from cygnusx.application.services.download_service import DownloadService
    from cygnusx.infrastructure.cache.redis_client import get_redis
    from cygnusx.infrastructure.database.session import get_session_factory

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
    from cygnusx.application.services.biomedical_literature_service import (
        BiomedicalLiteratureService,
    )
    from cygnusx.application.services.research_search_optimizer import (
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


async def _platform_arxiv_search(
    arguments: dict[str, Any],
    **_kw: Any,
) -> dict[str, Any]:
    """Search arXiv as a non-biomedical literature fallback."""
    from cygnusx.application.services.arxiv_literature_service import ArxivLiteratureService

    query = " ".join(str(arguments.get("query") or "").split())
    if not query:
        return {"success": False, "error": "缺少 query 参数"}
    max_results = max(1, min(int(arguments.get("max_results") or 8), 20))
    try:
        results = await ArxivLiteratureService(timeout_seconds=10).search(query, max_results)
        return {
            "success": True,
            "result": {
                "query": query,
                "provider": "arXiv",
                "result_count": len(results),
                "results": results,
            },
        }
    except Exception as exc:  # noqa: BLE001 - return a bounded MCP error
        return {"success": False, "error": f"arXiv 检索失败: {type(exc).__name__}"}


async def _platform_ability_catalog_query(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """查询平台内置 Agent 能力目录（data/ai/agent_ability.yaml 权威源，只读）。

    「平台上有哪些 Agent / 某 Agent 能做什么 / 谁适合接这个需求」类问题的唯一
    权威数据源：目录是活文档，模型凭记忆背诵会随版本腐烂。默认返回 summary 层
    清单；传 ``agent_id`` 返回该 Agent 的 detail（四段契约 + 输入示例）。
    """
    from cygnusx.infrastructure.config.agent_ability_catalog import agent_ability_catalog
    from cygnusx.infrastructure.config.agent_loader import load_agent_configs

    agent_id = str(arguments.get("agent_id") or "").strip()
    configs = {
        str(config.get("agent_id")): config
        for config in load_agent_configs()
        if config.get("agent_id")
    }

    def bindings(config: dict[str, Any]) -> dict[str, Any]:
        features = config.get("features") or {}
        packs = features.get("tool_packs") or []
        mcp_tools: dict[str, list[str]] = {}
        for pack in packs:
            if not isinstance(pack, dict):
                continue
            for server_id, names in (pack.get("mcp_tools") or {}).items():
                if not isinstance(names, list):
                    continue
                values = [str(name).strip() for name in names if str(name).strip()]
                if values:
                    mcp_tools.setdefault(str(server_id), []).extend(values)
        return {
            "skill_ids": [
                str(value).strip()
                for value in (config.get("skill_ids") or [])
                if str(value).strip()
            ],
            "mcp_ids": [
                str(value).strip()
                for value in (config.get("mcp_ids") or [])
                if str(value).strip()
            ],
            "mcp_tools": {
                server_id: list(dict.fromkeys(names))
                for server_id, names in mcp_tools.items()
            },
        }

    if agent_id:
        entry = agent_ability_catalog.get(agent_id)
        config = configs.get(agent_id) or {}
        if not entry and not config:
            return {"success": False, "error": f"Agent '{agent_id}' 未在能力目录登记"}
        return {
            "success": True,
            "agent_id": agent_id,
            "detail": entry,
            "bindings": bindings(config),
        }

    agents = []
    catalog = agent_ability_catalog.all()
    for aid in sorted(set(catalog) | set(configs)):
        entry = catalog.get(aid) or {}
        config = configs.get(aid) or {}
        features = config.get("features") or {}
        agentteams = features.get("agentteams") or {}
        asset_bindings = bindings(config)
        agents.append(
            {
                "agent_id": aid,
                "name": str(config.get("name") or aid),
                "summary": entry.get("summary") or "",
                "enabled": bool(config) and config.get("is_active", True) is not False,
                "internal_case_role": str(features.get("internal_case_role") or ""),
                "category": str(agentteams.get("category") or config.get("category") or "general"),
                "recruitable": bool(agentteams.get("recruitable", False)),
                "planner_eligible": bool(agentteams.get("planner_eligible", False)),
                "chat_entry": bool(entry.get("chat_entry", True)),
                "requires_formal_delivery": bool(entry.get("requires_formal_delivery", False)),
                **asset_bindings,
            }
        )
    return {"success": True, "agents": agents}


async def _platform_room_state_query(
    arguments: dict[str, Any],
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """查询当前协作室房间状态（与 GET /rooms/{room_id} 同源，只读）。

    scope 锁当前房间：房间从调用上下文 ``context.session_id``
    （形如 ``agentteams:{case_id}:sub:{run_id}:{index}``，未立项时 case_id 为
    ``room-<room_id>`` 命名空间）解析，不接受任意 room_id 入参，防止跨房间窥探。
    """
    from sqlalchemy import select

    from cygnusx.application.services.agentteams_service import ROOM_NAMESPACE_ID_PREFIX
    from cygnusx.infrastructure.database.models.chat import AgentTeamsRoomModel

    if context is None:
        return {"success": False, "error": "缺少调用上下文，无法确定当前房间"}
    tokens = (context.session_id or "").split(":")
    case_id = tokens[1] if len(tokens) >= 2 and tokens[0] == "agentteams" else ""
    if not case_id:
        return {"success": False, "error": "当前会话不在协作室上下文中，无法定位房间"}

    async def query(db: Any) -> dict[str, Any]:
        if case_id.startswith(ROOM_NAMESPACE_ID_PREFIX):
            room_id = case_id.removeprefix(ROOM_NAMESPACE_ID_PREFIX)
            room = (
                await db.execute(
                    select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.room_id == room_id)
                )
            ).scalar_one_or_none()
        else:
            room = (
                await db.execute(
                    select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.case_id == case_id)
                )
            ).scalar_one_or_none()
        if room is None:
            return {
                "success": False,
                "error": f"未找到与当前会话关联的协作室房间（case_id={case_id}）",
            }
        proposal = room.proposal if isinstance(room.proposal, dict) else None
        return {
            "success": True,
            "room_id": room.room_id,
            "title": room.title,
            "status": room.status,
            "origin": room.origin,
            "origin_ref": room.origin_ref,
            "case_id": room.case_id,
            "matrix_room_provisioned": bool(room.matrix_room_id),
            "has_pending_proposal": bool(proposal and proposal.get("status") == "pending"),
            "created_at": room.created_at.isoformat() if room.created_at else None,
            "updated_at": room.updated_at.isoformat() if room.updated_at else None,
        }

    return await query(context.db)


# ====================== Seqout 公共数据库检索 (builtin) ======================

async def _seqout_handler(
    arguments: dict[str, Any],
    tool_name: str = "",
    user_id: str | None = None,
    context: ToolInvocationContext | None = None,
) -> dict[str, Any]:
    """Seqout builtin preset 的统一 handler — 调用 seqout.org API"""
    import httpx
    import json

    BASE_URL = "https://seqout.org/api"

    def _parse_search_response(data: dict | list, limit: int = 5) -> list[dict]:
        """解析搜索结果"""
        if isinstance(data, dict):
            raw_items = data.get("results", data.get("hits", data))
        else:
            raw_items = data

        if not isinstance(raw_items, list):
            return []

        results = []
        for item in raw_items[:limit]:
            results.append({
                "accession": item.get("accession") or item.get("id"),
                "title": item.get("title"),
                "organism": item.get("organism"),
                "sample_count": item.get("samples_count") or item.get("n_samples"),
                "source_db": item.get("database"),
                "summary": (item.get("summary") or item.get("description") or "")[:200] + "...",
            })
        return results

    def _parse_samples_response(data: dict | list, limit: int = 30) -> list[dict]:
        """解析样本清单"""
        if isinstance(data, dict):
            samples_list = data.get("samples", data.get("data", []))
        else:
            samples_list = data

        if not isinstance(samples_list, list):
            return []

        manifest = []
        for s in samples_list[:limit]:
            manifest.append({
                "sample_accession": s.get("accession") or s.get("geo_accession"),
                "title": s.get("title"),
                "characteristics": s.get("characteristics_ch1") or s.get("attributes") or [],
                "source_name": s.get("source_name_ch1") or s.get("source_name"),
            })
        return manifest

    async def _seqout_request(endpoint: str, params: dict | None = None) -> dict:
        """发送 Seqout API 请求"""
        # seqout.org 对默认 httpx UA 返回 403，须携带浏览器 UA
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            try:
                response = await client.get(f"{BASE_URL}{endpoint}", params=params)
                response.raise_for_status()
                
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type:
                    raise Exception(f"服务端返回 HTML 页面：{response.text[:200]}")
                
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise Exception("触发速率限制 (Rate Limit)，请稍后重试")
                raise Exception(f"Seqout API 错误 {e.response.status_code}: {e.response.text[:200]}")
            except httpx.TimeoutException:
                raise Exception("请求超时")
            except json.JSONDecodeError:
                raise Exception("响应解析失败：非 JSON 格式")

    try:
        if tool_name == "seqout_search":
            data = await _seqout_request("/search", {"q": arguments.get("query", ""), "limit": arguments.get("limit", 5)})
            return {"success": True, "data": _parse_search_response(data, arguments.get("limit", 5))}
        
        elif tool_name == "seqout_search_geo":
            data = await _seqout_request("/search", {"database": "geo", "q": arguments.get("query", ""), "limit": arguments.get("limit", 5)})
            return {"success": True, "data": _parse_search_response(data, arguments.get("limit", 5))}
        
        elif tool_name == "seqout_search_sra":
            data = await _seqout_request("/search", {"database": "sra", "q": arguments.get("query", ""), "limit": arguments.get("limit", 5)})
            return {"success": True, "data": _parse_search_response(data, arguments.get("limit", 5))}
        
        elif tool_name == "seqout_search_structured":
            params = {}
            if arguments.get("organism"):
                params["organism"] = arguments.get("organism")
            if arguments.get("assay"):
                params["assay"] = arguments.get("assay")
            params["limit"] = arguments.get("limit", 5)
            data = await _seqout_request("/search/structured", params)
            return {"success": True, "data": _parse_search_response(data, arguments.get("limit", 5))}
        
        elif tool_name == "seqout_get_project_detail":
            data = await _seqout_request(f"/project/{arguments.get('accession', '')}")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_project_metadata":
            data = await _seqout_request(f"/project/{arguments.get('accession', '')}/metadata")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_project_citation":
            data = await _seqout_request(f"/project/{arguments.get('accession', '')}/citation")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_project_enriched":
            data = await _seqout_request(f"/project/{arguments.get('accession', '')}/enriched")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_experiments":
            data = await _seqout_request(f"/study/{arguments.get('study_accession', '')}/experiments")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_runs":
            data = await _seqout_request(f"/study/{arguments.get('study_accession', '')}/runs")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_run_download":
            data = await _seqout_request(f"/run/{arguments.get('run_accession', '')}/download")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_sample_metadata":
            data = await _seqout_request(f"/sample/{arguments.get('accession', '')}/metadata")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_sample_detail":
            data = await _seqout_request(f"/sample/{arguments.get('accession', '')}")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_sample_manifest":
            data = await _seqout_request(f"/geo/{arguments.get('accession', '')}/samples", 
                                         {"max_samples": arguments.get("max_samples", 30)})
            return {"success": True, "data": _parse_samples_response(data, arguments.get("max_samples", 30))}
        
        elif tool_name == "seqout_resolve_accession":
            data = await _seqout_request(f"/resolve/{arguments.get('accession', '')}")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_resolve_prj":
            data = await _seqout_request(f"/resolve/prj/{arguments.get('prj_accession', '')}")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_ontology_term":
            data = await _seqout_request(f"/ontology/{arguments.get('term', '')}")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_organisms":
            data = await _seqout_request("/organisms")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_common_name":
            data = await _seqout_request(f"/organism/{arguments.get('organism_id', '')}/common-name")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_beacon_info":
            data = await _seqout_request("/beacon/info")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_beacon_runs":
            data = await _seqout_request("/beacon/runs")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_stats_growth":
            data = await _seqout_request("/stats/growth")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_organism_totals":
            data = await _seqout_request("/stats/organism-totals")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_platform_totals":
            data = await _seqout_request("/stats/platform-totals")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_download_links":
            data = await _seqout_request("/download-links")
            return {"success": True, "data": data}
        
        elif tool_name == "seqout_get_metadata_csv":
            data = await _seqout_request("/metadata-csv")
            return {"success": True, "data": data}
        
        else:
            return {"success": False, "error": f"未知工具：{tool_name}"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


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
        "name": "arxiv_search",
        "description": (
            "检索 arXiv 的开放获取预印本，适合作为材料、计算机、物理、数学等非生物医学领域"
            "的文献检索源。返回题名、作者、年份、来源、链接和摘要；不下载全文。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "英文或英文关键词检索式"},
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 8,
                    "description": "返回数量；研究问答推荐 5-8",
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
        "name": "platform_list_agent_skills",
        "description": (
            "查询某个 Agent（智能体）当前绑定的技能（Skill）列表：技能 ID、名称、描述、版本、"
            "是否已安装并启用。用户问「你/某 Agent 绑定了哪些技能、会什么、能用什么技能包」时"
            "必须调用本工具获取实时绑定关系，禁止凭记忆或猜测作答；省略 agent_id 时查询当前对话的 Agent。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID（如 agent-scrna）；省略时查询当前对话的 Agent",
                },
            },
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
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
            "PDF 返回最多 50,000 字符的分页文本；二进制/测序文件（BAM/CRAM/FASTQ 等）只返回元数据。"
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
            "提交前服务端强制二次确认：首次调用返回确认卡（confirmation_id），"
            "用户确认后才可携带 _confirmation_id 以完全相同参数重试提交；dry_run 试验证不需要确认。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "_confirmation_id": {
                    "type": "string",
                    "description": "人类批准确认卡后返回的一次性凭证；缺省时本调用只产生确认卡",
                    "default": "",
                },
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
    {
        "name": "ability_catalog_query",
        "description": (
            "查询平台内置 Agent 能力目录（唯一权威数据源，只读）。默认返回全部 Agent 的"
            " summary 层清单（agent_id / 名称 / 是否启用 / 协作室角色 / 招募资格 / 是否聊天入口 /"
            " Skill 绑定 / MCP 绑定及工具白名单）；"
            "传 agent_id 返回该 Agent"
            " 的 detail（能力、不适用场景、转交时机、偏好输入、输入示例及绑定资产）。被问「平台上有哪些"
            " Agent / 某 Agent 会什么 / 谁适合接这个需求」时必须调用本工具，禁止凭记忆背诵；"
            "询问全部 Agent 或当前 Skill/MCP 时不得只返回当前任务相关的子集。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "可选；传入时返回该 Agent 的 detail 层契约",
                },
            },
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "room_state_query",
        "description": (
            "查询当前协作室房间的状态（只读，scope 锁当前房间）：房间标题、状态、是否已立项"
            "（case_id）、来源、是否有待确认立项卡、创建/更新时间。被问「这个房间/当前协作室"
            " 现在什么状态 / 立项了吗」时调用本工具获取实时数据，禁止凭记忆作答。"
            "本工具不接受 room_id 入参，只能查询当前会话所属房间。"
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
]

PLATFORM_HANDLERS = {
    "europe_pmc_search": _platform_europe_pmc_search,
    "arxiv_search": _platform_arxiv_search,
    "platform_list_tasks": _platform_list_tasks,
    "platform_get_task": _platform_get_task,
    "platform_list_flows": _platform_list_flows,
    "platform_get_user_info": _platform_get_user_info,
    "platform_get_current_time": _platform_get_current_time,
    "platform_list_agent_skills": _platform_list_agent_skills,
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
    "ability_catalog_query": _platform_ability_catalog_query,
    "room_state_query": _platform_room_state_query,
}


# ====================== Seqout 公共数据库检索工具定义 ======================

SEQOUT_PRESET_TOOLS = [
    {
        "name": "seqout_search",
        "description": "在 GEO/SRA/ENA/GSA 等公共数据库中搜索匹配的组学项目",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词（如:'CD8 T cell exhaust','HCC single cell'）"},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20, "description": "最多返回的项目数量"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "seqout_search_geo",
        "description": "仅搜索 GEO 数据库中的基因表达数据集",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "seqout_search_sra",
        "description": "仅搜索 SRA 数据库中的测序原始数据项目",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "seqout_search_structured",
        "description": "使用元数据过滤器结构化搜索（按物种、实验类型等）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "organism": {"type": "string", "description": "物种名称（可选）"},
                "assay": {"type": "string", "description": "实验类型（可选）"},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
            },
        },
    },
    {
        "name": "seqout_get_project_detail",
        "description": "获取项目详情（实验设计、平台、文献引用）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "accession": {"type": "string", "description": "项目登录号（GSE/PRJNA 等）"},
            },
            "required": ["accession"],
        },
    },
    {
        "name": "seqout_get_project_metadata",
        "description": "获取项目标题和描述信息",
        "inputSchema": {
            "type": "object",
            "properties": {
                "accession": {"type": "string", "description": "项目登录号"},
            },
            "required": ["accession"],
        },
    },
    {
        "name": "seqout_get_project_citation",
        "description": "获取项目引用文献 (BibTeX 格式)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "accession": {"type": "string", "description": "项目登录号"},
            },
            "required": ["accession"],
        },
    },
    {
        "name": "seqout_get_project_enriched",
        "description": "获取 AI 增强的样本元数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "accession": {"type": "string", "description": "项目登录号"},
            },
            "required": ["accession"],
        },
    },
    {
        "name": "seqout_get_experiments",
        "description": "列出研究中的所有实验",
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_accession": {"type": "string", "description": "研究登录号"},
            },
            "required": ["study_accession"],
        },
    },
    {
        "name": "seqout_get_runs",
        "description": "列出 FASTQ 下载链接",
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_accession": {"type": "string", "description": "研究登录号"},
            },
            "required": ["study_accession"],
        },
    },
    {
        "name": "seqout_get_run_download",
        "description": "获取单个运行的下载链接",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_accession": {"type": "string", "description": "运行登录号（SRR 等）"},
            },
            "required": ["run_accession"],
        },
    },
    {
        "name": "seqout_get_sample_metadata",
        "description": "获取样本元数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "accession": {"type": "string", "description": "样本登录号（GSM 等）"},
            },
            "required": ["accession"],
        },
    },
    {
        "name": "seqout_get_sample_detail",
        "description": "获取完整的样本详细信息",
        "inputSchema": {
            "type": "object",
            "properties": {
                "accession": {"type": "string", "description": "样本登录号"},
            },
            "required": ["accession"],
        },
    },
    {
        "name": "seqout_get_sample_manifest",
        "description": "获取数据集的样本清单，包含样本组织来源、实验处理组与对照组标记",
        "inputSchema": {
            "type": "object",
            "properties": {
                "accession": {"type": "string", "description": "GEO Series 编号（如 'GSE123456'）"},
                "max_samples": {"type": "integer", "default": 30, "minimum": 1, "maximum": 100, "description": "返回的最大样本数量预览"},
            },
            "required": ["accession"],
        },
    },
    {
        "name": "seqout_resolve_accession",
        "description": "反查样本归属的项目编号（从 GSM/SRR 反查 GSE/PRJNA）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "accession": {"type": "string", "description": "样本或 Run 编号（如:'GSM456789','SRR1234567'）"},
            },
            "required": ["accession"],
        },
    },
    {
        "name": "seqout_resolve_prj",
        "description": "将 BioProject 解析到研究级别",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prj_accession": {"type": "string", "description": "BioProject 登录号"},
            },
            "required": ["prj_accession"],
        },
    },
    {
        "name": "seqout_get_ontology_term",
        "description": "查询本体论术语信息",
        "inputSchema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "术语 ID 或名称"},
            },
            "required": ["term"],
        },
    },
    {
        "name": "seqout_get_organisms",
        "description": "列出所有支持的物种",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "seqout_get_common_name",
        "description": "获取物种的常用名称",
        "inputSchema": {
            "type": "object",
            "properties": {
                "organism_id": {"type": "string", "description": "物种 ID"},
            },
            "required": ["organism_id"],
        },
    },
    {
        "name": "seqout_beacon_info",
        "description": "获取 Beacon 元数据",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "seqout_beacon_runs",
        "description": "浏览测序运行记录",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "seqout_get_stats_growth",
        "description": "获取数据库增长统计",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "seqout_get_organism_totals",
        "description": "获取每个物种的实验总数",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "seqout_get_platform_totals",
        "description": "获取平台实验总数或过滤选项",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "seqout_get_download_links",
        "description": "获取 TSV 格式的下载链接",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "seqout_get_metadata_csv",
        "description": "下载合并的元数据 CSV",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

SEQOUT_HANDLERS = {t["name"]: _seqout_handler for t in SEQOUT_PRESET_TOOLS}


# 预设服务定义
PRESET_SERVERS: list[dict[str, Any]] = [
    {
        "name": "cygnusx-platform",
        "description": "平台操作 MCP - Europe PMC 文献检索、任务管理、流程查询、当前用户与饼干（积分）余额查询、Agent 技能绑定查询、协作室 Agent 能力目录与当前房间状态查询、沙箱执行、结果读取、数据下载（SRA/GEO 公共数据库与多云存储）",
        "transport": "builtin",
        "tools": PLATFORM_PRESET_TOOLS,
        "handlers": PLATFORM_HANDLERS,
    },
    build_pipeline_preset(),
    {
        "name": SEQOUT_SERVER_NAME,
        "description": f"公共数据库检索 MCP - {SEQOUT_SERVER_NAME}.org API 完整覆盖，支持 GEO/SRA/ENA/GSA 项目搜索、样本清单、accession 解析等 26 个工具",
        "transport": "builtin",
        "tools": SEQOUT_PRESET_TOOLS,
        "handlers": SEQOUT_HANDLERS,
    },
]


def _build_cygnusx_tools_preset() -> dict[str, Any]:
    """动态构建 cygnusx-tools builtin preset（tools 来自 tools_schema.yaml + 动态 Flow）。"""
    from cygnusx.application.services.flow_service import FlowService
    from cygnusx.tools.flow_schema_compiler import FlowToolSchemaCompiler
    from cygnusx.tools.schema_loader import schema_loader

    static_tools = schema_loader.to_openai_tools()
    handlers = {t["function"]["name"]: _cygnusx_tools_handler for t in static_tools}

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
                handlers[tool_name] = _cygnusx_tools_handler
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
            handlers[tool_name] = _cygnusx_tools_handler
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
        "name": "cygnusx-tools",
        "description": "CygnusX 生信工具箱 MCP - KEGG 富集、火山图、系统发育树及分析中心流程",
        "transport": "builtin",
        "tools": list(tools_by_name.values()),
        "handlers": handlers,
    }


def get_preset_by_name(name: str) -> dict[str, Any] | None:
    if name == "cygnusx-tools":
        return _build_cygnusx_tools_preset()
    if name == CYGNUSX_PIPELINES_SERVER_NAME:
        return build_pipeline_preset()
    if name == SEQOUT_SERVER_NAME:
        return {
            "name": SEQOUT_SERVER_NAME,
            "description": f"公共数据库检索 MCP - {SEQOUT_SERVER_NAME}.org API 完整覆盖，支持 GEO/SRA/ENA/GSA 项目搜索、样本清单、accession 解析等 26 个工具",
            "transport": "builtin",
            "tools": SEQOUT_PRESET_TOOLS,
            "handlers": SEQOUT_HANDLERS,
        }
    for p in PRESET_SERVERS:
        if p["name"] == name:
            return p
    return None


__all__ = [
    "PRESET_SERVERS",
    "CYGNUSX_TOOLS_SERVER_ID",
    "CYGNUSX_TOOLS_SERVER_NAME",
    "CYGNUSX_PLATFORM_SERVER_ID",
    "WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX",
    "CYGNUSX_PIPELINES_SERVER_ID",
    "CYGNUSX_PIPELINES_SERVER_NAME",
    "SEQOUT_SERVER_ID",
    "SEQOUT_SERVER_NAME",
    "SEQOUT_PRESET_TOOLS",
    "SEQOUT_HANDLERS",
    "PLATFORM_PRESET_TOOLS",
    "PLATFORM_HANDLERS",
    "get_preset_by_name",
    "_build_cygnusx_tools_preset",
]
