"""聊天模式轻量沙盒工具 — 复用 standalone sandbox pool，无工作区耦合。

与 Studio sandbox_execute 的区别：
 - 后端：走 SandboxService（容器池），不走 studio_sandbox_manager
 - 前端：ChatCodeCard（轻量卡片），不走 StudioCodeCard
 - 无审批、无工作区文件操作；交付文件写入 /tmp/chat_output/ 或容器内 /workspace/output/，
   执行后复制到宿主机 storage_path/chat_sandbox/<user>/<session>/output 持久化并提供下载
 - 输入方向：本聊天会话的上传附件在执行前注入容器 /workspace/input/，
   真实路径通过工具结果的 input_files 回写给模型
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

from loguru import logger

from cygnusx.application.services.artifact_manifest import build_file_entry, reconcile_declared
from cygnusx.application.services.chat_message_event_service import message_event_service
from cygnusx.domain.file.value_objects import FileSource
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk
from cygnusx.infrastructure.storage import get_path_factory, get_storage_backend
from cygnusx.infrastructure.storage.file_registry import FileRegistry

# ===== 工具 schema =====

CHAT_SANDBOX_EXECUTE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "chat_sandbox_execute",
        "description": (
            "在轻量级沙盒中执行代码（python/r/bash），适合快速验证、简单计算和可视化。"
            "流式返回 stdout/stderr/图表。需要交付给用户的文件（Excel、表格、图片等）"
            "先创建目录并写入 /tmp/chat_output/ 或工作区 output/（如 output/figures/xxx.png），"
            "执行后平台自动收集并在消息中提供预览与下载。"
            "用户随消息上传的文件会在执行前自动注入沙盒 /workspace/input/，"
            "执行结果的 input_files 会列出真实路径，代码中按该路径直接读取即可。"
            "复杂分析（多文件协作、工作区管理）请使用工作台。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "enum": ["python", "r", "bash"],
                    "description": "执行语言，默认 python",
                },
                "code": {"type": "string", "description": "要执行的完整代码"},
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数，缺省 300s",
                },
                "artifacts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "声明本次执行将产出的交付文件（相对 /tmp/chat_output/ 或 "
                        "/workspace/output/ 的路径，支持 * glob，如 \"results/summary.csv\""
                        "、\"figures/*.png\"）。执行结束后平台逐文件实测 size+sha256 对账；"
                        "声明了但未产出的文件会在结果 missing_artifacts 中告警"
                    ),
                },
            },
            "required": ["language", "code"],
        },
    },
}

CHAT_SANDBOX_TOOL_NAME = "chat_sandbox_execute"

# 聊天轻量沙盒的交付文件目录：模型把需要用户下载的文件写入这里，
# 执行结束后由后端复制到宿主机持久化并生成下载链接。
CHAT_ARTIFACT_CONTAINER_DIR = "/tmp/chat_output"

# 兼容约定：可视化/沙盒协议提示词让模型把产物写到工作区 output/（容器内 /workspace/output），
# 与上面的 /tmp/chat_output 并行收集，保证两种写法都能在消息里出现预览/下载。
CHAT_WORKSPACE_OUTPUT_CONTAINER_DIR = "/workspace/output"

# 用户上传附件的注入目录：执行前由后端把本会话上传文件 docker cp 进容器，
# 模型按执行结果 input_files 里的真实路径读取。
CHAT_INPUT_CONTAINER_DIR = "/workspace/input"

# 执行前清理交付/输入目录的 bash 命令：容器来自 warm pool 可能被复用，
# 必须清掉上一个会话遗留的产物与输入文件，避免跨会话文件串扰。
# mkdir 时一并创建 figures/results 常用子目录，避免用户代码直接
# savefig("/tmp/chat_output/figures/xxx.png") 时因子目录不存在而报 FileNotFoundError。
# 注意：/workspace/output、/workspace/input 在只读 rootfs 基线下是 tmpfs 挂载点，
# rm -rf 无法删除挂载点本身（退出码非零），用 `;` 保证后续 mkdir 一定执行。
_ARTIFACT_DIR_RESET_CMD = (
    f"rm -rf {CHAT_ARTIFACT_CONTAINER_DIR} {CHAT_WORKSPACE_OUTPUT_CONTAINER_DIR}"
    f" {CHAT_INPUT_CONTAINER_DIR} 2>/dev/null; mkdir -p"
    f" {CHAT_ARTIFACT_CONTAINER_DIR}/figures {CHAT_ARTIFACT_CONTAINER_DIR}/results"
    f" {CHAT_WORKSPACE_OUTPUT_CONTAINER_DIR}/figures {CHAT_WORKSPACE_OUTPUT_CONTAINER_DIR}/results"
    f" {CHAT_INPUT_CONTAINER_DIR}"
)

# 交付目录重置归属：container_id -> 上次执行重置的 session_id。
# 沙盒会话按用户亲和复用，同一 agent loop 内多轮工具调用通常落在同一容器，
# 若每次都 rm -rf 会清掉上一轮刚生成的产物；只有容器被其他会话占用过才需要重置。
# 进程重启后该表为空，回落到重置，语义安全。
_artifact_dir_owner: dict[str, str] = {}

# 同一会话内已收集产物的签名：session_id -> {relpath: (size, mtime)}。
# 后续调用只把新增/内容变化的文件返回给前端，避免同一文件在多轮消息的
# artifacts 清单里重复出现（宿主机复制仍全量执行，保证文件落盘）。
_collected_artifacts: dict[str, dict[str, tuple]] = {}

# 同一会话内产物 sha256 实测缓存：session_id -> {relpath: (size, mtime, sha256|None)}。
# 与 _collected_artifacts 同生命周期：(size, mtime) 签名未变的文件不重复读盘 hash，
# 签名变化（内容被覆盖）时重新实测，保证 manifest 里的 sha256 始终对应当前字节。
_artifact_digests: dict[str, dict[str, tuple]] = {}

# 容器内已注入输入文件的签名：container_id -> {文件名: (size, mtime)}。
# 同一容器被同一会话亲和复用时跳过未变化的重复注入；容器切换会话（交付目录重置）
# 时清空对应条目，重新全量注入。
_injected_inputs: dict[str, dict[str, tuple]] = {}

# 单次注入的附件总大小上限，防止超大上传撑爆容器磁盘/内存。
_INJECT_MAX_TOTAL_BYTES = 512 * 1024 * 1024

# ===== 内部工具 =====

_STREAM_QUEUE_MAX_CHUNKS = 64
_STREAM_HEARTBEAT_INTERVAL_SECONDS = 15.0


def _error_result(message: str) -> dict[str, Any]:
    payload = {"error": message}
    return {
        "success": False,
        "result": {"llm_payload": payload, "ui_payload": dict(payload)},
    }


def _ok_result(llm_payload: dict[str, Any], ui_payload: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "result": {"llm_payload": llm_payload, "ui_payload": ui_payload}}


def _tail(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[-limit:], True


def _append_bounded_text(current: str, data: str, limit: int) -> tuple[str, bool]:
    combined = f"{current}\n{data}" if current else data
    return _tail(combined, limit)


async def _collect_artifacts(
    container_id: str | None,
    user_id: str,
    session_id: Any,
    db: Any | None = None,
    declared: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """执行后把 /tmp/chat_output 下的交付文件复制到宿主机，生成可下载产物清单。

    产物统一归置到 users/{uid}/workspace/chat-output/{session_id}/output，
    并注册进 file_records（source=CHAT_SANDBOX），使 AI 助手 / 文件中心可见。
    归属校验由下载端点路径中的用户 id 保证；沙盒会话回收后文件仍保留在宿主机，
    历史消息中的下载链接继续有效。

    返回 (fresh_items, manifest, missing)：
    - fresh_items：本轮新增/内容变化的产物（含实测 sha256 字段）；
    - manifest：本轮收集到的全部产物逐文件 {path, size, sha256} 实测记录
      （读取失败标 error，sha256/size 为 None，不抛出）；新建 file_records
      记录时 sha256 同时写入 checksum 列；
    - missing：声明了（declared globs）但没有任何实测成功文件兑现的 glob，
      由调用方写入 missing_artifacts 告警，杜绝"exit 0 即成功"的静默假成功。
    """
    if not container_id:
        return [], [], []
    from cygnusx.infrastructure.sandbox import get_sandbox_pool

    path_factory = get_path_factory()
    backend = get_storage_backend()
    host_dest = (
        path_factory.workspace_dir(str(user_id))
        / "chat-output"
        / str(session_id)
        / "output"
    )
    await backend.ensure_dir(path_factory.relative_to_root(host_dest))
    try:
        items = await get_sandbox_pool().copy_dir_out(
            container_id, CHAT_ARTIFACT_CONTAINER_DIR, host_dest
        )
        # 兼容写到 /workspace/output 的产物（可视化协议约定的 output/figures 等路径）
        items.extend(
            await get_sandbox_pool().copy_dir_out(
                container_id, CHAT_WORKSPACE_OUTPUT_CONTAINER_DIR, host_dest
            )
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ChatSandbox] 产物收集失败: {e}")
        return [], [], []
    # 两个目录平铺到同一宿主目录，按 path 去重（后收集的覆盖先收集的）
    items = list({str(item["path"]): item for item in items}.values())

    # sha256 实测对账（OpenAI4S compute/manifest 契约）：逐文件流式 hash，
    # (size, mtime) 签名未变时走缓存；读取失败的文件记入 manifest 并标
    # error，不抛异常、不阻断登记主流程。
    digests = _artifact_digests.setdefault(str(session_id), {})
    manifest: list[dict[str, Any]] = []
    sha_by_rel: dict[str, str | None] = {}
    for item in items:
        relpath = str(item["path"])
        sig = (item.get("size"), item.get("mtime"))
        cached = digests.get(relpath)
        if cached and cached[0] == sig[0] and cached[1] == sig[1]:
            sha = cached[2]
            entry: dict[str, Any] = {"path": relpath, "size": sig[0], "sha256": sha}
            if sha is None:
                entry["error"] = cached[3] if len(cached) > 3 else "sha256 实测失败"
        else:
            entry = build_file_entry(host_dest, host_dest / relpath)
            sha = entry.get("sha256")
            digests[relpath] = (sig[0], sig[1], sha, entry.get("error") or "")
            if entry.get("error"):
                logger.warning(
                    f"[ChatSandbox] 产物 sha256 实测失败（记入 manifest error）: "
                    f"{relpath} {entry['error']}"
                )
        sha_by_rel[relpath] = sha
        manifest.append(entry)
    manifest.sort(key=lambda e: str(e.get("path")))

    # 声明产物对账：只有实测成功（有 sha256）的文件能兑现声明；
    # 声明了但落空的 glob 进 missing，由调用方置 missing_artifacts 告警。
    _featured, missing = reconcile_declared(manifest, declared)
    if missing:
        logger.warning(
            f"[ChatSandbox] 声明产物未产出（missing_artifacts）: session={session_id} {missing}"
        )

    # 注册到统一文件索引；失败只记录日志，不阻断产物返回。
    # 新建记录时把实测 sha256 写入 checksum 列；幂等命中已有记录保持原值。
    registered_ids: dict[str, str] = {}
    if db is not None:
        try:
            registry = FileRegistry(db)
            chat_directory = f"workspace/chat-output/{session_id}/output"
            for item in items:
                abs_path = host_dest / str(item["path"])
                rel_path = path_factory.relative_to_root(abs_path)
                if not await backend.exists(rel_path):
                    continue
                record = await registry.register(
                    UUID(user_id),
                    abs_path,
                    source=FileSource.CHAT_SANDBOX,
                    directory=chat_directory,
                    checksum=sha_by_rel.get(str(item["path"])) or None,
                )
                registered_ids[str(item["path"])] = str(record.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ChatSandbox] 产物注册到 file_records 失败: {exc}")

    for item in items:
        item["url"] = (
            f"/api/v1/chat/sandbox-sessions/{session_id}/artifacts/download"
            f"?path={quote(str(item['path']))}"
        )
        item["file_id"] = registered_ids.get(str(item["path"]))
    # 同一会话内按 (size, mtime) 签名去重：前几轮已收集且内容未变的文件
    # 不再出现在本轮 artifacts 清单里（宿主机复制仍是全量，文件均已落盘）。
    collected = _collected_artifacts.setdefault(str(session_id), {})
    fresh_items = []
    for item in items:
        relpath = str(item["path"])
        signature = (item.get("size"), item.get("mtime"))
        if collected.get(relpath) == signature:
            continue
        collected[relpath] = signature
        item["sha256"] = sha_by_rel.get(relpath)
        fresh_items.append(item)
    return fresh_items, manifest, missing


# ===== 执行器 =====


async def _collect_session_attachment_refs(
    db: Any, chat_session_id: str, user_id: str
) -> list[tuple[str, str]]:
    """收集本聊天会话的附件引用：消息元数据为主，chat-uploads 会话标记扫描兜底。

    返回 [(规范化引用(upload://… / file://…), 展示名)]，按消息顺序去重。
    目录引用（directory://）走 Studio 工作区，不注入聊天沙盒。
    """
    from sqlalchemy import select

    from cygnusx.infrastructure.database.models.chat import ChatMessageModel

    refs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(file_id: Any, name: Any) -> None:
        fid = str(file_id or "").strip()
        if not fid:
            return
        ref = fid if "://" in fid else f"upload://{fid}"
        if ref in seen:
            return
        seen.add(ref)
        refs.append((ref, str(name or "")))

    try:
        result = await db.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == str(chat_session_id))
            .order_by(ChatMessageModel.created_at)
        )
        for msg in result.scalars().all():
            if msg.role != "user":
                continue
            for att in (msg.metadata_json or {}).get("attachments") or []:
                if att.get("type") == "directory":
                    continue
                _add(att.get("file_id"), att.get("name"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ChatSandbox] 收集会话附件引用失败: {e}")

    # 兜底：上传时前端尚未拿到真实 session_id 的文件没有会话标记，
    # 未进入消息元数据的本会话上传按文件名内嵌标记找回。
    try:
        from cygnusx.infrastructure.config.storage_config import get_user_chat_upload_dir

        upload_dir = get_user_chat_upload_dir(str(user_id))
        marker = f".s{str(chat_session_id)[:8]}"
        if marker != ".s" and upload_dir.is_dir():
            for path in sorted(upload_dir.iterdir()):
                if path.is_file() and marker in path.name:
                    _add(path.name.split(".", 1)[0], path.name)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ChatSandbox] 扫描 chat-uploads 目录失败: {e}")
    return refs


async def _inject_session_files(
    db: Any, user_id: str, chat_session_id: str | None, container_id: str | None
) -> list[dict[str, Any]]:
    """把本聊天会话的上传附件复制进容器 /workspace/input/，返回 [{name, path, size}]。

    未变化（size+mtime 相同）的文件跳过重复注入；任一文件解析失败仅跳过，
    整体失败返回空列表，不阻断代码执行。
    """
    if not chat_session_id or not container_id:
        return []
    from cygnusx.infrastructure.mcp.presets import _resolve_workspace_file
    from cygnusx.infrastructure.sandbox import get_sandbox_pool

    refs = await _collect_session_attachment_refs(db, chat_session_id, user_id)
    if not refs:
        return []

    container_key = str(container_id)
    # ref -> (容器内文件名, size, mtime)：按引用追踪，同名不同文件不会误判为已注入
    injected = _injected_inputs.setdefault(container_key, {})
    used_names: set[str] = {value[0] for value in injected.values()}
    pending: list[tuple[Any, str, tuple, str]] = []
    metas: list[dict[str, Any]] = []
    total_bytes = 0
    for ref, display_name in refs:
        try:
            target, meta = await _resolve_workspace_file(str(user_id), ref, db)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ChatSandbox] 解析附件引用失败 {ref}: {e}")
            continue
        if target is None or not target.is_file():
            continue
        try:
            stat = target.stat()
        except OSError:
            continue
        signature = (stat.st_size, stat.st_mtime)
        existing = injected.get(ref)
        if existing and existing[1:] == signature:
            # 同引用同内容：容器里已有，直接复用
            metas.append(
                {
                    "name": existing[0],
                    "path": f"{CHAT_INPUT_CONTAINER_DIR}/{existing[0]}",
                    "size": stat.st_size,
                }
            )
            continue
        arcname = Path(display_name).name or target.name
        if not arcname or arcname in used_names:
            arcname = f"{str(meta.get('file_id') or '')[:8]}_{arcname or target.name}"
        total_bytes += stat.st_size
        if total_bytes > _INJECT_MAX_TOTAL_BYTES:
            logger.warning(
                f"[ChatSandbox] 注入附件总大小超过 {_INJECT_MAX_TOTAL_BYTES} 上限，"
                f"跳过 {arcname} 及后续文件"
            )
            break
        used_names.add(arcname)
        pending.append((target, arcname, signature, ref))
        metas.append(
            {
                "name": arcname,
                "path": f"{CHAT_INPUT_CONTAINER_DIR}/{arcname}",
                "size": stat.st_size,
            }
        )

    if pending:
        try:
            written = set(
                await get_sandbox_pool().copy_files_in(
                    container_key,
                    [(src, name) for src, name, _sig, _ref in pending],
                    CHAT_INPUT_CONTAINER_DIR,
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ChatSandbox] 附件注入容器失败: {e}")
            return []
        for _src, name, sig, ref in pending:
            if name in written:
                injected[ref] = (name, *sig)
    # 只报告容器里确实存在的文件：本轮写入的 + 签名未变的存量
    valid_names = {value[0] for value in injected.values()}
    return [m for m in metas if m["name"] in valid_names]


async def execute_chat_sandbox(
    args: dict[str, Any],
    user_id: str,
    on_output: Any | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """在 standalone sandbox pool 中执行代码，返回 llm_payload + ui_payload。"""
    from cygnusx.application.services.sandbox_service import SandboxService
    from cygnusx.infrastructure.database.session import get_session_factory

    language = str(args.get("language") or "python")
    code = str(args.get("code") or "")
    timeout = int(args.get("timeout") or 300)

    if not code.strip():
        return _error_result("code 不能为空")

    if language not in {"python", "r", "bash"}:
        return _error_result(f"不支持的语言: {language}")

    try:
        async with get_session_factory()() as db:
            service = SandboxService(db)

            session = await service.create_session(UUID(user_id), language)
            await db.commit()

            # 容器来自 warm pool 可能被跨会话复用：执行前清空交付目录，
            # 防止上一会话遗留文件被当作本次产物收集（也避免跨用户串文件）。
            # 同一 agent loop 内容器被同一会话亲和复用时跳过重置，
            # 保留前几轮已生成的产物（子目录由首次 reset 建好）。
            container_key = str(session.container_id)
            if _artifact_dir_owner.get(container_key) == str(session.id):
                pass
            else:
                try:
                    async for _ in service.execute_code(
                        UUID(user_id), session.id, _ARTIFACT_DIR_RESET_CMD, 30, language="bash"
                    ):
                        pass
                    _artifact_dir_owner[container_key] = str(session.id)
                    # 输入目录随重置被清空，注入签名一并失效
                    _injected_inputs.pop(container_key, None)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[ChatSandbox] 交付目录清理失败（继续执行）: {e}")

            # 执行前把本聊天会话的上传附件注入容器 /workspace/input/，
            # 让模型代码可以按真实文件系统路径直接读取用户文件。
            try:
                input_files = await _inject_session_files(
                    db, user_id, session_id, session.container_id
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[ChatSandbox] 会话附件注入失败（继续执行）: {e}")
                input_files = []

            stdout_parts: list[str] = []
            stderr_parts: list[str] = []
            images: list[str] = []
            echarts: list[Any] = []
            plotly_figures: list[Any] = []
            error: str | None = None

            async for event in service.execute_code(
                UUID(user_id), session.id, code, timeout, language=language
            ):
                etype = event.get("type")
                if etype == "stdout":
                    data = str(event.get("data", ""))
                    stdout_parts.append(data)
                    if on_output:
                        await on_output("stdout", data)
                elif etype == "stderr":
                    data = str(event.get("data", ""))
                    stderr_parts.append(data)
                    if on_output:
                        await on_output("stderr", data)
                elif etype == "image":
                    images.append(str(event.get("data", "")))
                elif etype == "echarts":
                    echarts.append(event.get("data", {}))
                elif etype == "plotly":
                    figure = event.get("data")
                    if isinstance(figure, dict):
                        plotly_figures.append(figure)
                elif etype == "error":
                    error = str(event.get("detail", "执行错误"))
                elif etype == "done":
                    pass

            # SandboxService 只负责状态流转并 flush；该工具使用独立 session，
            # 必须显式提交，才能让 5 分钟回收任务看到最新 last_activity/status。
            await db.commit()

            declared_raw = args.get("artifacts")
            declared: list[str] | None = None
            if isinstance(declared_raw, str):
                declared = [declared_raw]
            elif isinstance(declared_raw, list):
                declared = [str(p) for p in declared_raw]
            artifacts, artifact_manifest, missing_artifacts = await _collect_artifacts(
                session.container_id, user_id, session.id, db=db, declared=declared
            )
            # 产物注册到 file_records 后需要再提交一次，确保元数据持久化
            try:
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[ChatSandbox] 产物注册后提交失败: {exc}")

            stdout_full = "".join(stdout_parts)
            stderr_full = "".join(stderr_parts)

            llm_stdout, _ = _tail(stdout_full, 2000)
            llm_stderr, _ = _tail(stderr_full, 1000)

            llm_payload: dict[str, Any] = {
                "success": error is None,
                "stdout": llm_stdout,
                "stderr": llm_stderr,
                "images_count": len(images),
                "echarts_count": len(echarts),
            }
            if plotly_figures:
                llm_payload["plotly_count"] = len(plotly_figures)
                llm_payload["plotly_note"] = (
                    "plotly 图表已在消息中内联交互预览，无需再引导用户下载 HTML 查看"
                )
            if input_files:
                llm_payload["input_files"] = [
                    {"name": item["name"], "path": item["path"]} for item in input_files
                ]
                llm_payload["input_files_note"] = (
                    "用户上传的附件已注入沙盒，代码中请直接按上述 path 读取，"
                    "不要再去 /tmp 或全盘搜索文件"
                )
            if artifacts:
                llm_payload["artifacts"] = [str(item["path"]) for item in artifacts]
                llm_payload["artifacts_note"] = (
                    "交付文件已保存，消息中已附下载按钮；回复用户时报文件名即可"
                )
            if artifact_manifest:
                llm_payload["artifact_manifest"] = artifact_manifest
            if missing_artifacts:
                # 声明了产物但文件不存在：显式告警，不允许静默假成功。
                # missing_artifacts 与 payload_truncation 同为信封平级字段，
                # 前端历史重建时可据此渲染告警（本期前端不改，字段先落库）。
                llm_payload["missing_artifacts"] = missing_artifacts
                llm_payload["missing_artifacts_note"] = (
                    "以下声明的交付文件未产出，请检查代码写文件路径"
                    "（/tmp/chat_output/ 或 /workspace/output/）后重试"
                )
            if error:
                llm_payload["error"] = error

            ui_payload: dict[str, Any] = {
                "language": language,
                "stdout": stdout_full,
                "stderr": stderr_full,
                "images": images,
                "echarts": echarts,
            }
            if plotly_figures:
                ui_payload["plotly_figures"] = plotly_figures
            if artifacts:
                ui_payload["artifacts"] = artifacts
            if artifact_manifest:
                ui_payload["artifact_manifest"] = artifact_manifest
            if missing_artifacts:
                ui_payload["missing_artifacts"] = missing_artifacts
            if error:
                ui_payload["error"] = error

            return _ok_result(llm_payload, ui_payload)

    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ChatSandbox] 执行异常: {e}")
        return _error_result(f"沙盒执行失败: {e}")


# ===== 流式包装 =====


async def stream_chat_sandbox_tool(
    args: dict[str, Any],
    user_id: str,
    tool_call_id: str = "",
    session_id: str | None = None,
    message_id: str | None = None,
) -> AsyncIterator[ChatChunk | dict[str, Any]]:
    """流式执行聊天沙盒工具，产出 tool_output 事件 + 最终结果信封。

    tool_output chunk 同时按 message_id 追加到 chat_message_events
    （攒批落库，失败降级不影响流式）。
    """
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=_STREAM_QUEUE_MAX_CHUNKS)

    async def _on_output(stream: str, data: str) -> None:
        await queue.put((stream, data))

    task = asyncio.create_task(
        execute_chat_sandbox(args, user_id, on_output=_on_output, session_id=session_id)
    )

    last_emit = time.monotonic()
    while True:
        if task.done() and queue.empty():
            break
        try:
            stream, data = await asyncio.wait_for(queue.get(), timeout=0.05)
        except TimeoutError:
            if time.monotonic() - last_emit >= _STREAM_HEARTBEAT_INTERVAL_SECONDS:
                last_emit = time.monotonic()
                yield ChatChunk(type="heartbeat")
            continue
        last_emit = time.monotonic()
        yield ChatChunk(
            type="tool_output",
            metadata={
                "tool": CHAT_SANDBOX_TOOL_NAME,
                "tool_call_id": tool_call_id,
                "stream": stream,
                "data": data,
            },
        )
        # WP2：tool_output chunk 追加到事件表（攒批，失败降级不阻塞流式）
        await message_event_service.append_tool_output(
            message_id or "",
            tool_call_id=tool_call_id,
            stream=stream,
            data=data,
        )
    await message_event_service.flush_message_events(message_id or "")
    try:
        yield await task
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ChatSandbox] 流式执行异常: {e}")
        yield _error_result(f"工具执行失败: {e}")
