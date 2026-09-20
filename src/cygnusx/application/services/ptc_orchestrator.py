"""Programmatic Tool Calling 编排执行器（tool_orchestrate 后端）。

语义：模型把一段 Python 编排代码作为一次工具调用提交，代码在宿主 Web 进程派生的
受限子进程中运行；子进程内注入 ``call_tool`` / ``parallel_calls`` 帮助函数，
通过 stdin/stdout JSON-lines RPC 回调父进程，父进程校验白名单后复用
``execute_studio_tool`` 分发执行（沙盒类调用照常落会话容器，平台类调用传
user_id/db）。中间结果全程不进模型上下文，最终只有子进程 print 的汇总进入
llm_payload，每次子调用明细进入 ui_payload 供前端渲染。

子进程协议：
- 父进程把用户代码追加到注入前导代码（定义 call_tool / parallel_calls）后运行；
- 子进程 stdout 中以 ``\\x1e`` 开头的行是 RPC 帧（单行 JSON），其余行是用户
  print 的普通输出，收集为最终汇总；
- 父进程对每次调用回写一行 ``{"id", "ok", "result"|"error"}`` 到子进程 stdin；
  parallel_calls 的子调用按 RPC id 并发执行、按 id 对应回写。

安全边界（如实说明）：rlimit（CPU/内存/文件大小）+ env 清空 + cwd 临时目录 +
总超时强杀 + 子调用次数上限 + 工具白名单，强于在 Web 进程内直接 exec，但弱于
Docker 容器；默认只对显式开启 ptc_enabled 的 agent 挂载，且 supervised 模式下
整段编排代码先经一次审批（内部子调用不再逐次弹窗）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ===== 白名单与限额 =====

# 编排代码允许回调的工具：工作区读写、沙盒执行、知识/流程查询、文档工具、
# 平台数据引入与产物登记、受限问答（llm_query，经 ptc_llm_handler 发起并审计）。
# 禁止项（不在名单内即拒绝）：ask_user / update_plan /
# transfer_to_agent / create_agentteams_case / parallel_subagents /
# tool_orchestrate 自身（防递归）/ browser_*（独立会话状态）/ onlyoffice_*。
PTC_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "workspace_read",
        "workspace_list",
        "workspace_write",
        "workspace_edit",
        "sandbox_execute",
        "knowledge_search",
        "pipeline_query",
        "document_inspect",
        "document_create",
        "document_edit",
        "document_convert",
        "datahub_import",
        "platform_result_import",
        "artifact_register",
        "llm_query",
    }
)

# WP3 任务 3：llm_query 为动态白名单成员——仅在会话科研开关
# research_mode.ptc_llm_query=true 时加入本次编排的白名单（默认不在）。
# 审批语义不变：tool_orchestrate 整段仍是一次审批，子调用不逐次弹窗。
PTC_STATIC_ALLOWED_TOOLS: frozenset[str] = PTC_ALLOWED_TOOLS - {"llm_query"}


async def resolve_ptc_llm_query_enabled(
    *,
    session_id: str,
    db: AsyncSession | None = None,
    override: bool | None = None,
) -> bool:
    """判定本次编排是否放行 llm_query（会话 research_mode.ptc_llm_query）。

    - override 显式传入（测试/内部调用）时优先；
    - 否则读 chat_sessions.sandbox_meta.research_mode.ptc_llm_query；
      db 不可用或读取异常按未开启（False）降级。
    """
    if override is not None:
        return bool(override)
    if db is None:
        return False
    try:
        from cygnusx.infrastructure.database.models.chat import ChatSessionModel

        result = await db.execute(
            select(ChatSessionModel.sandbox_meta).where(
                ChatSessionModel.session_id == session_id
            )
        )
        sandbox_meta = result.scalar_one_or_none() or {}
        research_mode = sandbox_meta.get("research_mode")
        if not isinstance(research_mode, dict):
            return False
        return bool(research_mode.get("ptc_llm_query"))
    except Exception as exc:  # noqa: BLE001 - 开关读取失败按未开启降级，不阻断编排
        logger.info(f"[PTC] llm_query 开关读取失败（会话 {session_id[:8]}）: {exc}")
        return False

PTC_DEFAULT_TIMEOUT_SECONDS = 600  # 编排总超时默认值
PTC_MAX_TIMEOUT_SECONDS = 1800  # 编排总超时上限
PTC_DEFAULT_MAX_CALLS = 50  # 单次编排的子调用次数上限
_PTC_STREAM_LIMIT = 1024 * 1024  # 子进程 stdout 单行上限（RPC 帧可能携带大参数）
_PTC_CHILD_MEMORY_BYTES = 512 * 1024 * 1024  # 子进程地址空间上限（编排本身不做重计算）
_PTC_CHILD_FSIZE_BYTES = 16 * 1024 * 1024  # 子进程可写文件大小上限
_PTC_CHILD_RESULT_CAP = 4000  # 回写子进程的单次子调用结果截断（字符）
_PTC_LLM_SUMMARY_TAIL = 2000  # llm_payload 汇总截尾（对齐 _LLM_STDOUT_TAIL 风格）
_PTC_UI_SUMMARY_CAP = 20000  # ui_payload 汇总上限（对齐 _UI_OUTPUT_CAP）
_PTC_CALL_RECORD_CAP = 1000  # ui_payload 单次子调用结果/参数截尾
_PTC_STDERR_TAIL = 2000  # 子进程 stderr 保留尾部上限

# RPC 帧标记：子进程 stdout 中以此字符开头的行是 RPC 帧，其余为用户 print 输出
_RPC_MARK = "\x1e"

# 进度回调：每次子调用开始/结束推一行人类可读文本（stream_studio_tool 桥接为
# tool_output 事件）；工具执行器：(name, args) -> execute_studio_tool 信封
ProgressCallback = Callable[[str], Awaitable[None]]
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

# ===== 注入子进程的前导代码 =====
# 定义 call_tool / parallel_calls：RPC 帧写入 stdout（\x1e 前缀 + 单行 JSON，
# json.dumps 会转义换行，保证一帧一行），后台线程读 stdin 按 id 分发响应。
# 注意：本字符串为 raw string，其中的 \x1e / \n 转义由子进程解释。

_CHILD_PREAMBLE = r'''
import itertools as _it
import json as _json
import sys as _sys
import threading as _threading

_RPC_MARK = "\x1e"
_call_ids = _it.count(1)
_pending = {}
_pending_lock = _threading.Lock()
_write_lock = _threading.Lock()
_reader_started = False


def _reader():
    for _line in _sys.stdin:
        _line = _line.strip()
        if not _line:
            continue
        try:
            _msg = _json.loads(_line)
        except ValueError:
            continue
        with _pending_lock:
            _entry = _pending.pop(_msg.get("id"), None)
        if _entry is not None:
            _entry["response"] = _msg
            _entry["event"].set()


def _ensure_reader():
    global _reader_started
    if not _reader_started:
        _reader_started = True
        _threading.Thread(target=_reader, daemon=True).start()


def _send_call(name, args):
    _ensure_reader()
    _rid = next(_call_ids)
    _entry = {"event": _threading.Event(), "response": None}
    with _pending_lock:
        _pending[_rid] = _entry
    _frame = _json.dumps(
        {"type": "call", "id": _rid, "name": name, "args": args},
        ensure_ascii=False,
        default=str,
    )
    with _write_lock:
        _sys.stdout.write(_RPC_MARK + _frame + "\n")
        _sys.stdout.flush()
    _entry["event"].wait()
    _resp = _entry["response"] or {}
    if _resp.get("ok"):
        return _resp.get("result")
    raise RuntimeError(str(_resp.get("error") or ("工具 " + str(name) + " 调用失败")))


def call_tool(name, **args):
    """调用一个平台工具；成功返回其结果 dict，失败抛出 RuntimeError。"""
    return _send_call(str(name), dict(args))


def parallel_calls(calls):
    """并发执行多次工具调用。

    calls 为 [{"name": 工具名, "args": {参数}}] 列表；按入参顺序返回结果列表，
    单项失败时对应位置为 {"error": ...}，不中断其它子调用。
    """
    _results = [None] * len(calls)

    def _run_one(_i, _spec):
        try:
            _results[_i] = _send_call(str(_spec.get("name")), dict(_spec.get("args") or {}))
        except Exception as _exc:
            _results[_i] = {"error": str(_exc)}

    _threads = [
        _threading.Thread(target=_run_one, args=(_i, _spec))
        for _i, _spec in enumerate(calls)
    ]
    for _t in _threads:
        _t.start()
    for _t in _threads:
        _t.join()
    return _results
'''


def _child_preexec(cpu_seconds: int) -> Callable[[], None]:
    """子进程预 exec 资源限制：CPU 秒数（略宽于总超时兜底）、地址空间、文件大小。"""

    def _apply() -> None:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (_PTC_CHILD_MEMORY_BYTES,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (_PTC_CHILD_FSIZE_BYTES,) * 2)

    return _apply


def _tail_text(text: str, limit: int) -> tuple[str, bool]:
    """保留尾部 limit 字符，返回 (文本, 是否截断)。"""
    if len(text) <= limit:
        return text, False
    return text[-limit:], True


def _truncate_for_child(payload: Any) -> Any:
    """回写子进程的单次子调用结果：超长时替换为截尾文本，防子进程内存膨胀。"""
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"result": str(payload)}
    if len(text) <= _PTC_CHILD_RESULT_CAP:
        return payload
    return {"truncated": True, "result_tail": text[-_PTC_CHILD_RESULT_CAP:]}


def _record_text(value: Any) -> str:
    """ui_payload 明细字段：JSON 序列化后截尾。"""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return _tail_text(text, _PTC_CALL_RECORD_CAP)[0]


def _ok_result(llm_payload: dict[str, Any], ui_payload: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "result": {"llm_payload": llm_payload, "ui_payload": ui_payload}}


def _fail_result(
    llm_payload: dict[str, Any], ui_payload: dict[str, Any]
) -> dict[str, Any]:
    """编排级失败（超时 / 用户代码异常退出）：保留已收集的汇总与子调用明细，
    让模型可据此修正代码，闭环不中断。"""
    return {"success": False, "result": {"llm_payload": llm_payload, "ui_payload": ui_payload}}


async def _default_tool_executor(
    name: str,
    args: dict[str, Any],
    *,
    session_id: str,
    user_id: str | None,
    db: AsyncSession | None,
    image: str | None,
    orchestration_id: str = "",
) -> dict[str, Any]:
    """默认子调用分发：复用 Studio 内置工具分发器（惰性 import 避免循环依赖）。

    llm_query 为编排专用受限问答，不经 execute_studio_tool，直接交
    ptc_llm_handler（system 锚定 + 审计同窗）。"""
    if name == "llm_query":
        from cygnusx.application.services.ptc_llm_handler import execute_llm_query

        return await execute_llm_query(
            args, session_id=session_id, user_id=user_id, db=db,
            orchestration_id=orchestration_id,
        )

    from cygnusx.application.services.studio_tools import execute_studio_tool

    return await execute_studio_tool(
        name, args, session_id, image=image, user_id=user_id, db=db
    )


async def run_orchestration(
    code: str,
    session_id: str,
    *,
    user_id: str | None = None,
    db: AsyncSession | None = None,
    image: str | None = None,
    timeout_sec: int = PTC_DEFAULT_TIMEOUT_SECONDS,
    max_calls: int = PTC_DEFAULT_MAX_CALLS,
    tool_executor: ToolExecutor | None = None,
    on_progress: ProgressCallback | None = None,
    llm_query_enabled: bool | None = None,
) -> dict[str, Any]:
    """运行一段编排代码，返回 {"success": bool, "result": {"llm_payload", "ui_payload"}}。

    - tool_executor 可注入（测试用），缺省时走 execute_studio_tool 分发；
    - on_progress 每次子调用开始/结束各收到一行文本；
    - llm_query_enabled 显式覆盖 llm_query 白名单判定；缺省时按会话
      research_mode.ptc_llm_query 动态决定（默认不在白名单）；
    - 任何异常（子进程启动失败 / 超时 / 用户代码非零退出）都收敛为
      success=False 的友好 payload，绝不上抛。
    """
    started = time.monotonic()
    timeout_sec = max(1, min(int(timeout_sec), PTC_MAX_TIMEOUT_SECONDS))
    max_calls = max(1, int(max_calls))
    # 本次编排 run id：ui_payload 透出，并作为 llm_query 审计行的关联键
    orchestration_id = uuid4().hex
    # WP3 任务 3：llm_query 按会话科研开关动态进出白名单（默认不进）
    llm_allowed = await resolve_ptc_llm_query_enabled(
        session_id=session_id, db=db, override=llm_query_enabled
    )
    allowed_tools = PTC_ALLOWED_TOOLS if llm_allowed else PTC_STATIC_ALLOWED_TOOLS

    async def _execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_executor is not None:
            return await tool_executor(name, args)
        return await _default_tool_executor(
            name, args, session_id=session_id, user_id=user_id, db=db, image=image,
            orchestration_id=orchestration_id,
        )

    async def _progress(text: str) -> None:
        if on_progress is None:
            return
        with contextlib.suppress(Exception):
            await on_progress(text)

    output_text = ""  # 用户 print 汇总（只留尾部，防内存膨胀）
    stderr_text = ""
    records: list[dict[str, Any]] = []
    calls_started = 0
    calls_failed = 0
    pending: set[asyncio.Task[None]] = set()

    with tempfile.TemporaryDirectory(prefix="cygnusx-ptc-") as workdir:
        script = Path(workdir) / "orchestration.py"
        script.write_text(f"{_CHILD_PREAMBLE}\n\n{code}\n", encoding="utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",  # 隔离模式：忽略用户 site-packages 与环境变量注入
                str(script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                # 清空环境变量（不带宿主密钥/配置），仅保留 UTF-8 输出所需项
                env={"PYTHONUTF8": "1", "LANG": "C.UTF-8"},
                preexec_fn=_child_preexec(timeout_sec + 60),
                limit=_PTC_STREAM_LIMIT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[PTC] 编排子进程启动失败（会话 {session_id[:8]}）: {exc}")
            payload = {"error": f"编排子进程启动失败: {exc}"}
            return _fail_result(payload, {**payload, "code": code, "calls": []})

        stdin_lock = asyncio.Lock()

        async def _write_response(frame: dict[str, Any]) -> None:
            data = (json.dumps(frame, ensure_ascii=False, default=str) + "\n").encode()
            async with stdin_lock:
                if proc.stdin is None or proc.stdin.is_closing():
                    return
                proc.stdin.write(data)
                await proc.stdin.drain()

        async def _drain_stderr() -> None:
            nonlocal stderr_text
            assert proc.stderr is not None
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                stderr_text, _ = _tail_text(
                    stderr_text + chunk.decode("utf-8", "replace"), _PTC_STDERR_TAIL
                )

        async def _handle_call(index: int, rid: Any, name: str, args: dict[str, Any]) -> None:
            """执行一次子调用并回写响应；并行调用按 RPC id 各回各家。"""
            nonlocal calls_failed
            await _progress(f"[子调用 {index}] {name} 开始")
            call_started = time.monotonic()
            success = False
            result_payload: Any = None
            error_text = ""
            try:
                envelope = await _execute(name, args)
                success = bool(envelope.get("success"))
                result = envelope.get("result") or {}
                result_payload = result.get("llm_payload")
                if not success and isinstance(result_payload, dict):
                    error_text = str(result_payload.get("error") or "工具调用失败")
            except Exception as exc:  # noqa: BLE001 - 分发器设计上不抛，此处兜底
                error_text = str(exc)
                logger.info(f"[PTC] 子调用 {name} 异常（会话 {session_id[:8]}）: {exc}")
            duration_ms = int((time.monotonic() - call_started) * 1000)
            if not success:
                calls_failed += 1
            records.append(
                {
                    "index": index,
                    "id": rid,
                    "name": name,
                    "args": _record_text(args),
                    "success": success,
                    "duration_ms": duration_ms,
                    **(
                        {"error": error_text or "工具调用失败"}
                        if not success
                        else {"result": _record_text(result_payload)}
                    ),
                }
            )
            await _progress(
                f"[子调用 {index}] {name} {'成功' if success else '失败'}（{duration_ms}ms）"
            )
            frame: dict[str, Any] = {"id": rid, "ok": success}
            if success:
                frame["result"] = _truncate_for_child(result_payload)
            else:
                frame["error"] = error_text or "工具调用失败"
            # 子进程已退出（如被超时强杀）时响应无人接收，断管属预期
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                await _write_response(frame)

        stderr_task = asyncio.create_task(_drain_stderr())
        timed_out = False
        exit_code = -1
        try:
            deadline = time.monotonic() + timeout_sec
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    assert proc.stdout is not None
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                except TimeoutError:
                    timed_out = True
                    break
                if not line:
                    break  # EOF：子进程正常结束
                text = line.decode("utf-8", "replace").rstrip("\r\n")
                if not text.startswith(_RPC_MARK):
                    output_text, _ = _tail_text(
                        f"{output_text}\n{text}" if output_text else text,
                        _PTC_UI_SUMMARY_CAP,
                    )
                    continue
                try:
                    msg = json.loads(text[len(_RPC_MARK) :])
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict) or msg.get("type") != "call":
                    continue
                rid = msg.get("id")
                name = str(msg.get("name") or "")
                args = msg.get("args") if isinstance(msg.get("args"), dict) else {}
                if name not in allowed_tools:
                    logger.info(f"[PTC] 拒绝白名单外工具 {name}（会话 {session_id[:8]}）")
                    if name == "llm_query":
                        # WP3 任务 3：科研开关未开启时的专属软失败信息（软失败：编排继续）
                        error = (
                            "当前会话未开启 llm_query"
                            "（科研模式开关 research_mode.ptc_llm_query 未启用）"
                        )
                    else:
                        error = f"工具 {name} 不在编排白名单内"
                    await _write_response({"id": rid, "ok": False, "error": error})
                    continue
                if calls_started >= max_calls:
                    await _write_response(
                        {
                            "id": rid,
                            "ok": False,
                            "error": f"已达单次编排的子调用次数上限（{max_calls} 次）",
                        }
                    )
                    continue
                calls_started += 1
                task = asyncio.create_task(_handle_call(calls_started, rid, name, args))
                pending.add(task)
                task.add_done_callback(pending.discard)
        finally:
            if timed_out or proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            with contextlib.suppress(Exception):
                await proc.wait()
            await stderr_task

        duration_ms = int((time.monotonic() - started) * 1000)
        if not timed_out:
            exit_code = proc.returncode if proc.returncode is not None else -1
        summary_tail, summary_cut = _tail_text(output_text, _PTC_LLM_SUMMARY_TAIL)
        ui_payload: dict[str, Any] = {
            "code": code,
            "orchestration_id": orchestration_id,
            "summary": output_text,
            "calls": records,
            "call_count": calls_started,
            "failed_calls": calls_failed,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
            "timed_out": timed_out,
        }
        llm_payload: dict[str, Any] = {
            "summary": summary_tail or "（编排代码未 print 任何汇总）",
            "call_count": calls_started,
            "failed_calls": calls_failed,
            "duration_ms": duration_ms,
        }
        if summary_cut:
            llm_payload["summary_truncated"] = True
        if timed_out:
            llm_payload["error"] = f"编排执行超时（>{timeout_sec}s），子进程已终止"
            return _fail_result(llm_payload, ui_payload)
        if exit_code != 0:
            stderr_tail = stderr_text.strip()
            llm_payload["error"] = (
                f"编排代码异常退出（exit_code={exit_code}）"
                + (f": {stderr_tail}" if stderr_tail else "")
            )
            return _fail_result(llm_payload, ui_payload)
        return _ok_result(llm_payload, ui_payload)
