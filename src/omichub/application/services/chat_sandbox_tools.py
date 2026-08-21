"""聊天模式轻量沙盒工具 — 复用 standalone sandbox pool，无工作区耦合。

与 Studio sandbox_execute 的区别：
 - 后端：走 SandboxService（容器池），不走 studio_sandbox_manager
 - 前端：ChatCodeCard（轻量卡片），不走 StudioCodeCard
 - 无审批、无工作区文件操作；交付文件写入 /tmp/chat_output/ 或容器内 /workspace/output/，
   执行后复制到宿主机 storage_path/chat_sandbox/<user>/<session>/output 持久化并提供下载
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote
from uuid import UUID

from loguru import logger

from omichub.domain.file.value_objects import FileSource
from omichub.infrastructure.ai_provider.openai_compatible import ChatChunk
from omichub.infrastructure.storage import get_path_factory, get_storage_backend
from omichub.infrastructure.storage.file_registry import FileRegistry

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

# 执行前清理交付目录的 bash 命令：容器来自 warm pool 可能被复用，
# 必须清掉上一个会话遗留的产物，避免跨会话文件串扰。
# mkdir 时一并创建 figures/results 常用子目录，避免用户代码直接
# savefig("/tmp/chat_output/figures/xxx.png") 时因子目录不存在而报 FileNotFoundError。
_ARTIFACT_DIR_RESET_CMD = (
    f"rm -rf {CHAT_ARTIFACT_CONTAINER_DIR} {CHAT_WORKSPACE_OUTPUT_CONTAINER_DIR}"
    f" && mkdir -p"
    f" {CHAT_ARTIFACT_CONTAINER_DIR}/figures {CHAT_ARTIFACT_CONTAINER_DIR}/results"
    f" {CHAT_WORKSPACE_OUTPUT_CONTAINER_DIR}/figures {CHAT_WORKSPACE_OUTPUT_CONTAINER_DIR}/results"
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
) -> list[dict[str, Any]]:
    """执行后把 /tmp/chat_output 下的交付文件复制到宿主机，生成可下载产物清单。

    产物统一归置到 users/{uid}/workspace/chat-output/{session_id}/output，
    并注册进 file_records（source=CHAT_SANDBOX），使 AI 助手 / 文件中心可见。
    归属校验由下载端点路径中的用户 id 保证；沙盒会话回收后文件仍保留在宿主机，
    历史消息中的下载链接继续有效。
    """
    if not container_id:
        return []
    from omichub.infrastructure.sandbox import get_sandbox_pool

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
        return []
    # 两个目录平铺到同一宿主目录，按 path 去重（后收集的覆盖先收集的）
    items = list({str(item["path"]): item for item in items}.values())

    # 注册到统一文件索引；失败只记录日志，不阻断产物返回
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
        fresh_items.append(item)
    return fresh_items


# ===== 执行器 =====


async def execute_chat_sandbox(
    args: dict[str, Any],
    user_id: str,
    on_output: Any | None = None,
) -> dict[str, Any]:
    """在 standalone sandbox pool 中执行代码，返回 llm_payload + ui_payload。"""
    from omichub.application.services.sandbox_service import SandboxService
    from omichub.infrastructure.database.session import get_session_factory

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
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[ChatSandbox] 交付目录清理失败（继续执行）: {e}")

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

            artifacts = await _collect_artifacts(
                session.container_id, user_id, session.id, db=db
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
            if artifacts:
                llm_payload["artifacts"] = [str(item["path"]) for item in artifacts]
                llm_payload["artifacts_note"] = (
                    "交付文件已保存，消息中已附下载按钮；回复用户时报文件名即可"
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
) -> AsyncIterator[ChatChunk | dict[str, Any]]:
    """流式执行聊天沙盒工具，产出 tool_output 事件 + 最终结果信封。"""
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=_STREAM_QUEUE_MAX_CHUNKS)

    async def _on_output(stream: str, data: str) -> None:
        await queue.put((stream, data))

    task = asyncio.create_task(execute_chat_sandbox(args, user_id, on_output=_on_output))

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
    try:
        yield await task
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ChatSandbox] 流式执行异常: {e}")
        yield _error_result(f"工具执行失败: {e}")
