"""OmicStudio sandbox-agent —— 沙盒容器内的执行与文件操作小服务。

自包含设计：仅依赖 fastapi / uvicorn / pydantic，随镜像烘焙进容器，
以非 root 用户（uid 10001）运行，宿主 Sandbox Manager 经共享工作区 Unix Socket 直连。

安全红线（对应架构设计 §6.4）：
- 写路径（write/edit）归一化（含软链解析）后必须落在 /workspace 内，否则 400；
- 读路径（read/list）额外放行经 input/ 软链指向的平台只读挂载 /data/platform
  （数据不搬家：用户数据以只读软链进沙盒）；直接拼 /data/platform 绝对路径
  仍被拒绝，只允许经工作区内软链跳转；
- /exec 强制超时强杀；stdout/stderr 流内最多回传 10KB，溢出落 /workspace/.logs/ 文件；
- 沙盒内没有任何平台密钥，网络隔离由容器层保证（本服务不做鉴权，
  宿主侧保证仅宿主可达容器 IP，公网出站白名单为 P2 项）。
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import errno
import fcntl
import json
import os
import pty
import signal
import struct
import termios
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ===== 常量 =====
WORKSPACE_ROOT = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace"))
PLATFORM_MOUNT_ROOT = Path(os.environ.get("SANDBOX_PLATFORM_MOUNT", "/data/platform"))
OUTPUT_DIR = "output"  # 产物约定目录（相对 /workspace）
LOGS_DIR = ".logs"  # 执行溢出日志目录（相对 /workspace）
STREAM_CAP_BYTES = 10 * 1024  # 流内输出上限 10KB，超出落盘
STREAM_QUEUE_MAX_CHUNKS = 64  # 慢客户端时限制子进程输出在内存中的待发送块数
DEFAULT_READ_LIMIT = 200  # 文件分页读取默认行数
MAX_READ_LIMIT = 2000
DEFAULT_EXEC_TIMEOUT = 600  # 单次执行默认超时（秒）
MAX_EXEC_TIMEOUT = 3600
MCP_BUILDS_DIR = "mcp-builds"  # MCP Builder 生成代码约定目录（相对 /workspace）
MCP_MAX_SERVERS = 8  # 单容器内同时运行的实验 MCP 上限
MCP_SESSION_TIMEOUT = 30  # MCP 初始化/工具调用默认超时（秒）

@contextlib.asynccontextmanager
async def _lifespan(_: FastAPI):
    """启动后放宽共享 UDS 权限，退出时不保留额外状态。"""
    socket_path = Path(os.environ.get("SANDBOX_AGENT_SOCKET", "/workspace/.agent.sock"))
    with contextlib.suppress(OSError):
        await asyncio.to_thread(socket_path.chmod, 0o666)
    yield


app = FastAPI(
    title="OmicStudio Sandbox Agent",
    version="0.1.0",
    lifespan=_lifespan,
)


# ===== 路径防护（纯函数，供单元测试直接导入）=====
class PathEscapeError(ValueError):
    """路径逃逸 /workspace"""


def resolve_workspace_path(user_path: str, root: Path | None = None) -> Path:
    """将用户路径归一化为 /workspace 内的绝对路径。

    - 相对路径基于 root 拼接；绝对路径必须本身位于 root 内；
    - realpath 解析软链后再校验，防止经符号链接逃逸；
    - 越界抛出 PathEscapeError。
    """
    root = WORKSPACE_ROOT if root is None else root
    root_real = Path(os.path.realpath(root))
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = root_real / candidate
    resolved = Path(os.path.realpath(candidate))
    if resolved != root_real and root_real not in resolved.parents:
        raise PathEscapeError(f"路径越出工作区: {user_path}")
    return resolved


def resolve_workspace_read_path(user_path: str, root: Path | None = None) -> tuple[Path, bool]:
    """读路径归一化（与宿主 paths.resolve_workspace_read_path 同源，务必保持一致）。

    返回 (实际路径, via_platform)：
    - realpath 落在工作区内 → 正常放行；
    - realpath 落在平台只读挂载 /data/platform 内 → 仅当词法路径本身在工作区内
      （逃逸完全由工作区内软链跳转造成）才放行，via_platform=True（只读）；
    - 其余一律抛 PathEscapeError。
    """
    root = WORKSPACE_ROOT if root is None else root
    root_real = Path(os.path.realpath(root))
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = root_real / candidate
    lexical = Path(os.path.normpath(candidate))
    lexical_inside = lexical == root_real or root_real in lexical.parents

    resolved = Path(os.path.realpath(lexical))
    if resolved == root_real or root_real in resolved.parents:
        return resolved, False

    mount_real = Path(os.path.realpath(PLATFORM_MOUNT_ROOT))
    if not lexical_inside or (resolved != mount_real and mount_real not in resolved.parents):
        raise PathEscapeError(f"路径越出工作区: {user_path}")
    return resolved, True


def _relative(path: Path, root: Path | None = None) -> str:
    """转为相对 /workspace 的 POSIX 路径"""
    root = WORKSPACE_ROOT if root is None else root
    return path.relative_to(Path(os.path.realpath(root))).as_posix()


def _resolve_or_400(user_path: str) -> Path:
    try:
        return resolve_workspace_path(user_path)
    except PathEscapeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# 平台只读目录前缀（input/、ref/ 经软链指向 /data/platform 只读挂载）
_PROTECTED_WRITE_PREFIXES = frozenset({"input", "ref"})


def _lexical_workspace_path(user_path: str, root: Path | None = None) -> Path:
    """词法路径（不解析软链），用于在用户请求层面判定 input/ / ref/ 前缀。"""
    root = WORKSPACE_ROOT if root is None else root
    root_real = Path(os.path.realpath(root))
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = root_real / candidate
    return Path(os.path.normpath(candidate))


def _is_protected_write_path(lexical_path: Path, root: Path | None = None) -> bool:
    """词法路径是否落在平台只读前缀 input/ 或 ref/ 下。"""
    root = WORKSPACE_ROOT if root is None else root
    root_real = Path(os.path.realpath(root))
    if lexical_path != root_real and root_real not in lexical_path.parents:
        return False
    rel_parts = lexical_path.relative_to(root_real).parts
    return rel_parts and rel_parts[0] in _PROTECTED_WRITE_PREFIXES


def _raise_if_protected_write_prefix(user_path: str) -> None:
    """对 input/ / ref/ 前缀的写请求统一返回 403。"""
    if _is_protected_write_path(_lexical_workspace_path(user_path)):
        raise HTTPException(
            status_code=403,
            detail="input/ 与 ref/ 为平台只读目录，禁止写入、编辑、删除或重命名",
        )


def _resolve_writable_or_403(user_path: str) -> Path:
    """写路径解析：先显式拒绝 input/ / ref/ 前缀，再执行真实路径解析防逃逸。"""
    _raise_if_protected_write_prefix(user_path)
    return _resolve_or_400(user_path)


def _resolve_read_or_400(user_path: str) -> tuple[Path, bool]:
    """读路径解析（允许经软链到平台只读挂载）；越界 400。"""
    try:
        return resolve_workspace_read_path(user_path)
    except PathEscapeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ===== 请求模型 =====
class ExecRequest(BaseModel):
    language: Literal["python", "r", "bash"]
    code: str
    timeout: int | None = Field(default=None, description="超时秒数，缺省用服务默认")


class WriteRequest(BaseModel):
    path: str
    content: str


class EditRequest(BaseModel):
    path: str
    old_string: str
    new_string: str


class PathRequest(BaseModel):
    path: str


class RenameRequest(BaseModel):
    path: str
    new_path: str


# ===== 健康检查 =====
@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ===== 代码执行 =====
_LANG_RUNNERS: dict[str, tuple[str, str]] = {
    # language -> (解释器命令, 脚本后缀)；代码落临时脚本文件再执行，避免 -c 长度限制
    "python": ("python -u", ".py"),
    "r": ("Rscript", ".R"),
    "bash": ("bash", ".sh"),
}


def _terminate_process_group(
    proc: asyncio.subprocess.Process,
    sig: signal.Signals = signal.SIGKILL,
) -> None:
    """终止执行进程及其派生子进程，忽略已退出进程的竞态。"""
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()


def _snapshot_output() -> dict[str, tuple[int, float]]:
    """记录 /workspace/output 下现有文件的 (size, mtime)，用于执行后比对产物。"""
    out_dir = WORKSPACE_ROOT / OUTPUT_DIR
    snapshot: dict[str, tuple[int, float]] = {}
    if not out_dir.is_dir():
        return snapshot
    for p in out_dir.rglob("*"):
        if p.is_file():
            try:
                st = p.stat()
                snapshot[_relative(p)] = (st.st_size, st.st_mtime)
            except OSError:
                continue
    return snapshot


def _collect_artifacts(before: dict[str, tuple[int, float]]) -> list[dict[str, Any]]:
    """收集执行后新增 / 修改的产物文件（相对路径、大小、mtime）。"""
    out_dir = WORKSPACE_ROOT / OUTPUT_DIR
    artifacts: list[dict[str, Any]] = []
    if not out_dir.is_dir():
        return artifacts
    for p in sorted(out_dir.rglob("*")):
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        rel = _relative(p)
        prev = before.get(rel)
        if prev is None or prev != (st.st_size, st.st_mtime):
            artifacts.append({"path": rel, "size": st.st_size, "mtime": st.st_mtime})
    return artifacts


async def _stream_exec(req: ExecRequest):
    """NDJSON 流式执行生成器：stdout/stderr 行 + 最终 result。"""
    language = req.language
    timeout = min(req.timeout or DEFAULT_EXEC_TIMEOUT, MAX_EXEC_TIMEOUT)
    runner, suffix = _LANG_RUNNERS[language]
    exec_id = uuid.uuid4().hex[:12]
    started = time.monotonic()

    logs_dir = WORKSPACE_ROOT / LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    script_path = logs_dir / f"exec-{exec_id}{suffix}"
    script_path.write_text(req.code, encoding="utf-8")

    def emit(event: dict[str, Any]) -> bytes:
        return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

    before = _snapshot_output()
    proc = await asyncio.create_subprocess_shell(
        f"{runner} {script_path}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(WORKSPACE_ROOT),
        start_new_session=True,  # 独立进程组，超时整组强杀
        env={**os.environ, "MPLBACKEND": "Agg"},
    )

    async def _pump(
        stream: asyncio.StreamReader, channel: str, overflow_file
    ) -> AsyncIterator[bytes]:
        """逐行泵送输出；单通道流内上限 10KB，超出部分（含超长行的截断段）写入 .logs 溢出文件。"""
        sent = 0
        streamed_prefix = bytearray()
        truncated = False
        while True:
            line = await stream.readline()
            if not line:
                break
            budget = max(STREAM_CAP_BYTES - sent, 0)
            in_stream, overflow = line[:budget], line[budget:]
            if in_stream:
                sent += len(in_stream)
                streamed_prefix.extend(in_stream)
                text = in_stream.decode("utf-8", errors="replace")
                yield emit({"type": channel, "data": text})
            if overflow:
                if not truncated:
                    truncated = True
                    overflow_file.write(streamed_prefix)
                overflow_file.write(overflow)
                overflow_file.flush()

    overflow_out = open(  # noqa: ASYNC230,SIM115 - 溢出日志随执行流保持打开，无法提前 with 包裹；写入低频小量
        logs_dir / f"exec-{exec_id}.stdout.log", "wb"
    )
    overflow_err = open(  # noqa: ASYNC230,SIM115 - 同上
        logs_dir / f"exec-{exec_id}.stderr.log", "wb"
    )
    timed_out = False
    tasks: list[asyncio.Task[None]] = []
    wait_task: asyncio.Task[int] | None = None
    try:
        # 并发泵送 stdout/stderr 双通道，经队列汇流到主生成器
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=STREAM_QUEUE_MAX_CHUNKS)

        async def _fan(pump: AsyncIterator[bytes]) -> None:
            async for chunk in pump:
                await queue.put(chunk)
            await queue.put(None)

        assert proc.stdout is not None and proc.stderr is not None
        tasks = [
            asyncio.create_task(_fan(_pump(proc.stdout, "stdout", overflow_out))),
            asyncio.create_task(_fan(_pump(proc.stderr, "stderr", overflow_err))),
        ]
        wait_task = asyncio.create_task(proc.wait())
        done_sentinels = 0
        while done_sentinels < 2:
            if time.monotonic() - started > timeout:
                timed_out = True
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            if item is None:
                done_sentinels += 1
            else:
                yield item

        if timed_out:
            # 整组强杀（start_new_session 保证子进程也在组内）
            _terminate_process_group(proc)
            for t in tasks:
                t.cancel()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wait_task, timeout=5)
            exit_code = -1
        else:
            exit_code = await wait_task
    finally:
        # StreamingResponse 在客户端断开时会关闭生成器。此时必须终止进程组，
        # 否则长任务及其派生子进程会在没有消费者的情况下继续占用沙盒资源。
        _terminate_process_group(proc)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            # 已取消的管道读取任务可能等待底层 transport 收尾；断连清理不应
            # 被其阻塞。进程组已杀，后续由事件循环完成回收即可。
            await asyncio.wait(tasks, timeout=1)
        if wait_task is not None and not wait_task.done():
            await asyncio.wait({wait_task}, timeout=1)
        overflow_out.close()
        overflow_err.close()
        # 空溢出日志不留存，减少噪音
        for f in logs_dir.glob(f"exec-{exec_id}.*.log"):
            with contextlib.suppress(OSError):
                if f.stat().st_size == 0:
                    f.unlink()
        with contextlib.suppress(OSError):
            script_path.unlink()

    duration_ms = int((time.monotonic() - started) * 1000)
    artifacts = [] if timed_out else _collect_artifacts(before)
    result: dict[str, Any] = {
        "type": "result",
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "artifacts": artifacts,
    }
    if timed_out:
        result["timed_out"] = True
        result["error"] = f"执行超时（{timeout}s），进程已强杀"
    # 溢出日志存在时在结果中标注
    overflow_logs = [
        _relative(f) for f in sorted(logs_dir.glob(f"exec-{exec_id}.*.log")) if f.is_file()
    ]
    if overflow_logs:
        result["truncated_output_files"] = overflow_logs
    yield emit(result)


@app.post("/exec")
async def exec_code(req: ExecRequest) -> StreamingResponse:
    """流式执行代码，NDJSON 逐行返回 stdout/stderr/result 事件。"""
    return StreamingResponse(
        _stream_exec(req),
        media_type="application/x-ndjson",
        headers={"X-Exec-Engine": "omichub-sandbox-agent"},
    )


# ===== 交互式终端 =====
def _resize_pty(master_fd: int, cols: int, rows: int) -> None:
    safe_cols = max(20, min(int(cols), 500))
    safe_rows = max(5, min(int(rows), 200))
    fcntl.ioctl(
        master_fd,
        termios.TIOCSWINSZ,
        struct.pack("HHHH", safe_rows, safe_cols, 0, 0),
    )


@app.websocket("/terminal")
async def interactive_terminal(websocket: WebSocket) -> None:
    """为当前 Studio 容器提供基于 PTY 的交互式 Bash。"""
    await websocket.accept()
    master_fd, slave_fd = pty.openpty()
    _resize_pty(master_fd, 80, 24)

    def _child_setup() -> None:
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "HOME": str(WORKSPACE_ROOT),
        "PWD": str(WORKSPACE_ROOT),
        # PS1 单层级转义：Python 字符串 \\[ → bash 收到 \[（颜色定界），
        # \\w → bash 收到 \w（当前目录）。此前 \w 多写了一层（\\\\w），
        # 提示符会原样打印字面量 "\w" 而不是真实目录。
        # 仅作 bash 兜底；zsh 提示符由 oh-my-posh 渲染（见下方 zsh 分支）。
        "PS1": "\\[\\033[38;5;111m\\]studio@omicbox\\[\\033[0m\\]:\\[\\033[38;5;150m\\]\\w\\[\\033[0m\\]$ ",
    }
    # 优先 zsh（镜像内置 /opt/conda/bin/zsh + /opt/omichub/zdotdir/.zshrc，
    # oh-my-zsh + oh-my-posh）；缺失时回退 bash + PS1。
    zsh_path = "/opt/conda/bin/zsh"
    zdotdir = "/opt/omichub/zdotdir"
    if os.path.isfile(zsh_path) and os.path.isfile(os.path.join(zdotdir, ".zshrc")):
        shell_argv = [zsh_path, "-i"]
        env["ZDOTDIR"] = zdotdir
    else:
        shell_argv = ["/bin/bash", "--noprofile", "--norc", "-i"]
    proc = await asyncio.create_subprocess_exec(
        *shell_argv,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(WORKSPACE_ROOT),
        env=env,
        preexec_fn=_child_setup,
    )
    os.close(slave_fd)

    async def pump_output() -> None:
        while True:
            try:
                data = await asyncio.to_thread(os.read, master_fd, 65536)
            except OSError as exc:
                if exc.errno in {errno.EIO, errno.EBADF}:
                    break
                raise
            if not data:
                break
            await websocket.send_bytes(data)

    async def pump_input() -> None:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            raw = message.get("bytes")
            if raw is not None:
                await asyncio.to_thread(os.write, master_fd, raw)
                continue
            data = message.get("text") or ""
            if data.startswith("{"):
                try:
                    control = json.loads(data)
                except json.JSONDecodeError:
                    control = None
                if isinstance(control, dict):
                    if control.get("type") == "resize":
                        _resize_pty(master_fd, control.get("cols", 80), control.get("rows", 24))
                        continue
                    if control.get("type") == "ping":
                        continue
            await asyncio.to_thread(os.write, master_fd, data.encode("utf-8"))

    output_task = asyncio.create_task(pump_output())
    input_task = asyncio.create_task(pump_input())
    wait_task = asyncio.create_task(proc.wait())
    try:
        done, pending = await asyncio.wait(
            {output_task, input_task, wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            with contextlib.suppress(WebSocketDisconnect, asyncio.CancelledError, OSError):
                await task
    except WebSocketDisconnect:
        pass
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2)
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            os.close(master_fd)
        with contextlib.suppress(RuntimeError):
            await websocket.close()


# ===== 文件操作 =====
def _file_meta(p: Path) -> dict[str, Any]:
    st = p.stat()
    return {
        "name": p.name,
        "type": "dir" if p.is_dir() else "file",
        "size": st.st_size,
        "mtime": st.st_mtime,
    }


@app.get("/files/list")
async def list_files(path: str = Query(default="")) -> dict[str, Any]:
    """目录列表（相对 /workspace），含名称/类型/大小/mtime。"""
    target, via_platform = _resolve_read_or_400(path or ".")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"不是目录: {path}")
    entries = [_file_meta(p) for p in sorted(target.iterdir(), key=lambda x: x.name)]
    # 平台挂载内路径无法相对 /workspace 表达，回显用户输入路径
    display = path if via_platform else (_relative(target) if target != WORKSPACE_ROOT else "")
    return {"path": display, "entries": entries}


@app.get("/files/read")
async def read_file(
    path: str,
    offset: int = Query(default=0, ge=0, description="起始行（0 基）"),
    limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=MAX_READ_LIMIT),
) -> dict[str, Any]:
    """分页读取文本文件，默认前 200 行。"""
    target, _ = _resolve_read_or_400(path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"读取失败: {e}") from e
    total = len(lines)
    page = lines[offset : offset + limit]
    return {
        "content": "\n".join(page),
        "total_lines": total,
        "truncated": offset + limit < total,
    }


@app.post("/files/write")
async def write_file(req: WriteRequest) -> dict[str, Any]:
    """创建 / 覆盖文件（自动创建父目录）。"""
    target = _resolve_writable_or_403(req.path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(req.content, encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"写入失败: {e}") from e
    return {"path": _relative(target), "size": target.stat().st_size}


def _reverse_edit_payload(
    old_content: str,
    new_content: str,
    index: int,
    old_string: str,
    new_string: str,
) -> dict[str, str] | None:
    """构造可唯一命中的反向精确替换，支持删除类编辑。

    从编辑点两侧逐步扩展上下文，直到修改后的文件中 reverse_old_string
    非空且只出现一次。若修改后文件为空则无法用精确替换回滚，返回 None。
    """
    prefix = old_content[:index]
    suffix = old_content[index + len(old_string) :]
    context = 64
    max_context = max(len(prefix), len(suffix), context)
    while True:
        left = prefix[-context:]
        right = suffix[:context]
        reverse_old = left + new_string + right
        if reverse_old and new_content.count(reverse_old) == 1:
            return {
                "old_string": reverse_old,
                "new_string": left + old_string + right,
            }
        if context >= max_context:
            break
        context = min(context * 2, max_context)
    return None


@app.post("/files/mkdir")
async def make_directory(req: PathRequest) -> dict[str, Any]:
    target = _resolve_writable_or_403(req.path)
    if target == WORKSPACE_ROOT or target.exists():
        raise HTTPException(status_code=400, detail="目录已存在或路径非法")
    try:
        target.mkdir(parents=True)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"创建目录失败: {e}") from e
    return {"path": _relative(target), "type": "dir"}


@app.post("/files/rename")
async def rename_file(req: RenameRequest) -> dict[str, Any]:
    _raise_if_protected_write_prefix(req.path)
    _raise_if_protected_write_prefix(req.new_path)
    source = _resolve_or_400(req.path)
    target = _resolve_or_400(req.new_path)
    if source == WORKSPACE_ROOT or not source.exists() or target.exists():
        raise HTTPException(status_code=400, detail="源路径不存在、目标已存在或路径非法")
    if source.is_symlink():
        raise HTTPException(status_code=403, detail="平台只读文件不可重命名")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"重命名失败: {e}") from e
    return {"path": _relative(target), "old_path": req.path}


@app.delete("/files/delete")
async def delete_file(path: str = Query(...)) -> dict[str, Any]:
    _raise_if_protected_write_prefix(path)
    target = _resolve_or_400(path)
    if target == WORKSPACE_ROOT or not target.exists():
        raise HTTPException(status_code=404, detail="文件或目录不存在")
    if target.is_symlink():
        raise HTTPException(status_code=403, detail="平台只读文件不可删除")
    try:
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"删除失败: {e}") from e
    return {"path": path, "deleted": True}


@app.post("/files/edit")
async def edit_file(req: EditRequest) -> dict[str, Any]:
    """精确字符串替换（old_string 必须唯一出现），返回 unified diff。"""
    target = _resolve_writable_or_403(req.path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {req.path}")
    old_content = target.read_text(encoding="utf-8", errors="replace")
    count = old_content.count(req.old_string)
    if count == 0:
        raise HTTPException(status_code=400, detail="old_string 未在文件中出现")
    if count > 1:
        raise HTTPException(
            status_code=400,
            detail=f"old_string 出现 {count} 次，请提供更多上下文保证唯一匹配",
        )
    edit_index = old_content.find(req.old_string)
    new_content = old_content.replace(req.old_string, req.new_string, 1)
    reverse_edit = _reverse_edit_payload(
        old_content, new_content, edit_index, req.old_string, req.new_string
    )
    target.write_text(new_content, encoding="utf-8")
    diff = "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{_relative(target)}",
            tofile=f"b/{_relative(target)}",
        )
    )
    return {
        "path": _relative(target),
        "diff": diff,
        "size": target.stat().st_size,
        "reverse_edit": reverse_edit,
    }


# ===== MCP Builder：容器内实验 MCP Server 生命周期管理 =====
# 生成的 MCP Server 以 STDIO 子进程运行在本容器内（网络隔离 + 资源限制天然继承），
# 宿主侧经 UDS 调用本组端点完成 tools/list 与 tools/call，无需暴露任何 TCP 端口。
# 设计参考：docs/26.7.30/mcp_builder_framework.md §8.1 / ARCHITECTURE_DESIN/mcp_architecture.md §5.3


class MCPStartRequest(BaseModel):
    path: str = Field(description="server 代码路径（相对 /workspace 或绝对，必须在 /workspace 内）")
    server_id: str | None = Field(default=None, description="自定义 ID，缺省自动生成")
    timeout: int | None = Field(default=None, description="初始化超时秒数")


class MCPCallRequest(BaseModel):
    server_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout: int | None = None


class MCPIdRequest(BaseModel):
    server_id: str


# server_id -> 运行态记录
_MCP_SERVERS: dict[str, dict[str, Any]] = {}
_MCP_LOCK = asyncio.Lock()


async def _mcp_session_for_start(script: Path, timeout: float):
    """在容器内以 STDIO 方式启动 MCP Server 并完成协议握手.

    返回 (exit_stack, session)。失败时 exit_stack 已清理，直接抛异常。
    """
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    stack = contextlib.AsyncExitStack()
    try:
        read, write = await stack.enter_async_context(
            stdio_client(
                StdioServerParameters(
                    command=sys.executable,
                    args=[str(script)],
                    cwd=str(script.parent),
                )
            )
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=timeout)
        return stack, session
    except BaseException:
        await stack.aclose()
        raise


@app.post("/mcp/start")
async def mcp_start(req: MCPStartRequest) -> dict[str, Any]:
    """启动一个实验 MCP Server 子进程并完成 MCP 握手，返回工具清单。"""
    script = _resolve_or_400(req.path)
    if not script.is_file() or script.suffix != ".py":
        raise HTTPException(status_code=404, detail=f"MCP Server 脚本不存在: {req.path}")
    timeout = float(req.timeout or MCP_SESSION_TIMEOUT)

    async with _MCP_LOCK:
        if len(_MCP_SERVERS) >= MCP_MAX_SERVERS:
            raise HTTPException(
                status_code=429,
                detail=f"容器内实验 MCP 数量已达上限 {MCP_MAX_SERVERS}",
            )
        try:
            stack, session = await _mcp_session_for_start(script, timeout)
        except TimeoutError as e:
            raise HTTPException(status_code=504, detail="MCP Server 初始化超时") from e
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"MCP Server 启动失败: {type(e).__name__}: {e}"
            ) from e

        server_id = req.server_id or f"exp-{uuid.uuid4().hex[:12]}"
        # 若同 ID 已存在，先替换（停止旧进程）
        old = _MCP_SERVERS.pop(server_id, None)
        if old is not None:
            with contextlib.suppress(Exception):
                await old["stack"].aclose()

        try:
            listing = await asyncio.wait_for(session.list_tools(), timeout=timeout)
            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema,
                }
                for t in listing.tools
            ]
        except Exception as e:
            with contextlib.suppress(Exception):
                await stack.aclose()
            raise HTTPException(
                status_code=400, detail=f"tools/list 失败: {type(e).__name__}: {e}"
            ) from e

        _MCP_SERVERS[server_id] = {
            "stack": stack,
            "session": session,
            "path": _relative(script),
            "tools": tools,
            "started_at": time.time(),
        }

    return {
        "server_id": server_id,
        "path": _relative(script),
        "tools": tools,
    }


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest) -> dict[str, Any]:
    """调用容器内实验 MCP 的指定工具（宿主侧 MCPClient 的容器代理入口）。"""
    record = _MCP_SERVERS.get(req.server_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"实验 MCP 未运行: {req.server_id}")
    timeout = float(req.timeout or MCP_SESSION_TIMEOUT)
    try:
        result = await asyncio.wait_for(
            record["session"].call_tool(req.tool, req.arguments), timeout=timeout
        )
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"工具调用超时: {req.tool}") from e
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"工具调用失败: {type(e).__name__}: {e}"
        ) from e
    return {
        "server_id": req.server_id,
        "tool": req.tool,
        "is_error": bool(getattr(result, "isError", False)),
        "content": [
            {"type": getattr(c, "type", "text"), "text": getattr(c, "text", str(c))}
            for c in (result.content or [])
        ],
    }


@app.get("/mcp/tools")
async def mcp_tools(server_id: str = Query(...)) -> dict[str, Any]:
    """获取实验 MCP 的工具清单（优先返回启动时缓存，失效则重查）。"""
    record = _MCP_SERVERS.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"实验 MCP 未运行: {server_id}")
    try:
        listing = await asyncio.wait_for(
            record["session"].list_tools(), timeout=MCP_SESSION_TIMEOUT
        )
        record["tools"] = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema,
            }
            for t in listing.tools
        ]
    except Exception:
        pass  # 握手失效时退回缓存值
    return {"server_id": server_id, "tools": record["tools"]}


@app.post("/mcp/stop")
async def mcp_stop(req: MCPIdRequest) -> dict[str, Any]:
    """停止指定实验 MCP Server 子进程。"""
    async with _MCP_LOCK:
        record = _MCP_SERVERS.pop(req.server_id, None)
    if record is None:
        return {"server_id": req.server_id, "stopped": False}
    with contextlib.suppress(Exception):
        await record["stack"].aclose()
    return {"server_id": req.server_id, "stopped": True}


@app.get("/mcp/list")
async def mcp_list() -> dict[str, Any]:
    """列出容器内运行中的实验 MCP Server。"""
    return {
        "servers": [
            {
                "server_id": sid,
                "path": rec["path"],
                "tools": [t["name"] for t in rec["tools"]],
                "started_at": rec["started_at"],
            }
            for sid, rec in _MCP_SERVERS.items()
        ]
    }
