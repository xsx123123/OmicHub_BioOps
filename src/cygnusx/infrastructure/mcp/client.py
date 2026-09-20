"""MCP Client - MCP Server 生命周期管理、工具发现、调用路由与错误隔离"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import shutil
import time
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from cygnusx.core.config import get_settings
from cygnusx.core.telemetry import get_meter, get_tracer
from cygnusx.domain.mcp.entities import MCPServer
from cygnusx.domain.mcp.value_objects import ServerStatus, Transport
from cygnusx.infrastructure.mcp.presets import get_preset_by_name
from cygnusx.infrastructure.mcp.reliability import (
    MCPExternalCallError,
    MCPHealthRegistry,
    ToolRetryPolicy,
    counts_toward_circuit_breaker,
    execute_local_fallback,
    get_default_health_registry,
    health_key,
)
from cygnusx.infrastructure.mcp.workspace_file_refs import resolve_workspace_file_refs

# ===== MCP 调用遥测指标（全局代理 meter，未初始化时为 noop）=====
_mcp_meter = get_meter("cygnusx.mcp")
_mcp_duration = _mcp_meter.create_histogram(
    "mcp.call.duration", unit="ms", description="MCP 工具调用耗时"
)
_mcp_count = _mcp_meter.create_counter("mcp.call.count", description="MCP 工具调用次数")

# stdio transport 禁止使用的 shell 解释器（大小写不敏感）
_DENIED_STDIO_COMMANDS = {
    "sh",
    "bash",
    "zsh",
    "dash",
    "csh",
    "tcsh",
    "fish",
    "cmd",
    "command",
    "powershell",
    "pwsh",
}


def _is_internal_host(host: str) -> bool:
    """判断主机名是否为内网、回环、链路本地、组播或 metadata 地址。"""
    if host == "169.254.169.254":
        return True
    try:
        addr = ipaddress.ip_address(host)
        return (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
        )
    except ValueError:
        return False


def validate_sse_url(url: str) -> None:
    """校验 SSE URL：仅允许 http/https，且禁止指向内网/本地/metadata 地址。"""
    if not url:
        raise ValueError("SSE URL 不能为空")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不支持的 SSE URL scheme: {parsed.scheme}")
    host = parsed.hostname
    if not host:
        raise ValueError("SSE URL 缺少主机名")
    if _is_internal_host(host):
        raise ValueError("SSE URL 禁止指向内网、回环或 metadata 地址")


def validate_stdio_command(command: str) -> None:
    """校验 stdio command：禁止空值、路径遍历、绝对路径、shell 解释器，且必须位于 PATH。"""
    if not command:
        raise ValueError("stdio command 不能为空")
    if ".." in command:
        raise ValueError("stdio command 禁止路径遍历")
    if "/" in command or "\\" in command:
        raise ValueError("stdio command 禁止使用绝对路径")
    if command.lower() in _DENIED_STDIO_COMMANDS:
        raise ValueError(f"stdio command 禁止调用 shell 解释器: {command}")
    if shutil.which(command) is None:
        raise ValueError(f"stdio command 不在 PATH 中: {command}")


# 禁止 args 中的 shell 元字符与路径穿越
_DENIED_STDIO_ARG_PATTERN = re.compile(r"[;&|<>()`$]|\$\(|\`")


def validate_stdio_args(args: list[str] | None) -> None:
    """校验 stdio args：禁止 shell 元字符、路径穿越与绝对路径。"""
    if not args:
        return
    for arg in args:
        if ".." in arg:
            raise ValueError("stdio args 禁止路径遍历")
        if arg.startswith("/") or arg.startswith("\\"):
            raise ValueError("stdio args 禁止使用绝对路径")
        if _DENIED_STDIO_ARG_PATTERN.search(arg):
            raise ValueError(f"stdio args 包含非法字符: {arg}")


def validate_working_dir(working_dir: str | None) -> None:
    """校验 stdio 工作目录（子进程 cwd）：可为空或绝对路径，但禁止路径穿越与 shell 元字符。"""
    if not working_dir:
        return
    if ".." in working_dir:
        raise ValueError("working_dir 禁止路径遍历")
    if _DENIED_STDIO_ARG_PATTERN.search(working_dir):
        raise ValueError(f"working_dir 包含非法字符: {working_dir}")


# ===== 外部 stdio/sse MCP 会话复用池 =====
# 历史实现每次工具调用都新建子进程/连接并立即销毁（node/cmm 冷启动 + MCP initialize 握手
# 单次可达数秒），这是外部 MCP「很堵」的主要来源。这里改为按 server 缓存长活会话：
#   - 同一 server 的多次调用复用同一 ClientSession。MCP Python SDK 的 ClientSession
#     按 jsonrpc id 路由响应、天然支持并发多路复用，因此 per-server 锁只保护
#     「建立/重建/回收会话」阶段，工具调用本身不持锁——避免 stdio 上一个 60s 超时
#     的慢调用把同 server 的全部用户串行卡死（队头阻塞）；
#   - 会话损坏/超时后自动关闭并重建（按连接对象身份比对，不误关他人新建的会话）；
#   - 空闲超过 _MCP_SESSION_IDLE_TIMEOUT 惰性回收；
#   - server 连接配置变化时按 fingerprint 重建；
#   - 池关闭（应用退出/测试收尾）在锁内置 closing 标志、拒绝新借用后再关，
#     避免与在途建连/回收竞态。
# 池为模块级单例，跨 MCPClient 实例（agent 流 / 子 Agent / 管理端）共享。

_MCP_SESSION_IDLE_TIMEOUT = 300.0


class _ExternalConnection:
    """一个长活的外部 MCP 连接（stdio 子进程或 SSE/HTTP 流 + ClientSession）。"""

    __slots__ = ("fingerprint", "transport_cm", "session_cm", "last_used", "closed")

    def __init__(self, fingerprint: str, transport_cm: Any, session_cm: Any) -> None:
        self.fingerprint = fingerprint
        self.transport_cm = transport_cm
        self.session_cm = session_cm
        self.last_used = time.monotonic()
        self.closed = False


_external_connections: dict[str, _ExternalConnection] = {}
_external_locks: dict[str, asyncio.Lock] = {}
# 置位期间 _acquire_external_connection 拒绝新借用（见 close_external_connections）。
_external_pool_closing = False


def _external_fingerprint(server: MCPServer) -> str:
    return (
        f"{server.transport}|{server.command}|{server.args}|{server.url}|"
        f"{server.env}|{server.working_dir}"
    )


def _external_lock(server: MCPServer) -> asyncio.Lock:
    key = str(server.id)
    lock = _external_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _external_locks[key] = lock
    return lock


def _connection_usable(conn: _ExternalConnection, fingerprint: str) -> bool:
    """连接是否仍可借用：未关闭、配置未变、未空闲超期。"""
    return (
        not conn.closed
        and conn.fingerprint == fingerprint
        and time.monotonic() - conn.last_used <= _MCP_SESSION_IDLE_TIMEOUT
    )


async def close_external_connections() -> None:
    """关闭并清空外部 MCP 会话池（应用退出/测试收尾时调用）。

    先置 closing 标志拒绝新借用，再逐个 server 在其建连锁下摘除并关闭连接，
    避免与 _acquire_external_connection 的建连/回收竞态。收尾后复位标志，
    允许后续（如测试场景）重新建池。
    """
    global _external_pool_closing
    _external_pool_closing = True
    try:
        for key in sorted(set(_external_connections) | set(_external_locks)):
            lock = _external_locks.setdefault(key, asyncio.Lock())
            async with lock:
                conn = _external_connections.pop(key, None)
                if conn is not None:
                    await _close_external_connection(conn)
    finally:
        _external_connections.clear()
        _external_locks.clear()
        _external_pool_closing = False


async def _close_external_connection(conn: _ExternalConnection) -> None:
    if conn is None or conn.closed:
        return
    conn.closed = True
    for cm in (conn.session_cm, conn.transport_cm):
        if cm is None:
            continue
        with suppress(Exception):
            await cm.__aexit__(None, None, None)


class MCPClient:
    """MCP 客户端 - 统一管理 builtin / stdio / sse 三种传输

    builtin：进程内直接调用预设 handler（开箱即用）
    stdio/sse：通过 Python MCP SDK 建立会话调用（错误隔离，失败不影响主流程）
    """

    async def list_tools(self, server: MCPServer) -> list[dict[str, Any]]:
        """发现某 MCP Server 提供的工具"""
        if server.transport == Transport.BUILTIN:
            preset = get_preset_by_name(server.name)
            if preset is None:
                return []
            return [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["inputSchema"],
                }
                for t in preset["tools"]
            ]

        # stdio / sse：发现工具时让连接/校验错误向上抛（区别于 call_tool 的错误隔离），
        # 由上层把失败标成 error 并回传真实原因，而不是误报 online + 0 工具。
        return await asyncio.wait_for(self._list_tools_external(server), timeout=server.timeout)

    def __init__(self, health_registry: MCPHealthRegistry | None = None) -> None:
        self.health_registry = health_registry or get_default_health_registry()
        self.health_registry.circuit_cooldown_seconds = (
            get_settings().mcp_circuit_breaker_cooldown_seconds
        )
        self.retry_policy = ToolRetryPolicy()

    async def call_tool(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str | None = None,
        context: Any | None = None,
        fallback_servers: list[MCPServer] | None = None,
    ) -> dict[str, Any]:
        """调用某 MCP Server 的指定工具（带 Trace/Log/Metrics 埋点）"""
        tracer = get_tracer("cygnusx.mcp")
        with tracer.start_as_current_span(
            "mcp.call_tool",
            attributes={
                "mcp.server": server.name,
                "mcp.transport": str(server.transport),
                "mcp.tool": tool_name,
            },
        ) as span:
            start = time.perf_counter()
            status = "success"
            try:
                result = await self._call_with_reliability(
                    server,
                    tool_name,
                    arguments,
                    user_id,
                    context,
                    fallback_servers or [],
                )
                if not result.get("success"):
                    status = "error"
                return result
            except Exception as exc:  # noqa: BLE001
                status = "error"
                span.record_exception(exc)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                attrs = {
                    "mcp.server": server.name,
                    "mcp.tool": tool_name,
                    "mcp.status": status,
                }
                span.set_attribute("mcp.status", status)
                span.set_attribute("mcp.duration_ms", round(duration_ms, 2))
                try:
                    _mcp_duration.record(duration_ms, attrs)
                    _mcp_count.add(1, attrs)
                except Exception:  # noqa: BLE001
                    pass
                logger.bind(
                    event="mcp.call_tool",
                    server=server.name,
                    transport=str(server.transport),
                    tool=tool_name,
                    status=status,
                    duration_ms=round(duration_ms, 2),
                ).info("mcp.call_tool completed")

    async def _call_with_reliability(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str | None,
        context: Any | None,
        fallback_servers: list[MCPServer],
    ) -> dict[str, Any]:
        key = health_key(server.name, tool_name)
        policy = ToolRetryPolicy(max_attempts=1) if server.transport == Transport.BUILTIN else self.retry_policy
        # 熔断门控：degraded 的外部 server:tool 在冷却窗口内直接短路走兜底链，
        # 不再打满重试；窗口过后放行一次单发半开试探。builtin 本地工具不受影响。
        short_circuited = False
        if server.transport != Transport.BUILTIN:
            circuit_state = self.health_registry.try_acquire_call(key)
            if circuit_state == "open":
                short_circuited = True
            elif circuit_state == "half_open":
                policy = ToolRetryPolicy(max_attempts=1)

        last_result: dict[str, Any] = {"success": False, "error": "工具调用失败"}
        attempts_made = policy.max_attempts
        if short_circuited:
            attempts_made = 0
            logger.warning(f"MCP 熔断短路：{key} 处于 degraded 冷却期，跳过远程调用")
            last_result = {
                "success": False,
                "error": "外部服务连续失败，已进入熔断冷却",
                "failure_kind": "circuit_open",
            }
        else:
            for attempt in range(1, policy.max_attempts + 1):
                started = time.perf_counter()
                try:
                    result = await self._call_tool_inner(
                        server, tool_name, arguments, user_id, context
                    )
                except Exception as exc:  # noqa: BLE001
                    result = {"success": False, "error": str(exc)}
                latency_ms = (time.perf_counter() - started) * 1000
                if result.get("success"):
                    self.health_registry.record_success(key, latency_ms)
                    if attempt > 1:
                        result["reliability"] = {"attempts": attempt, "recovered": True}
                    return result
                # 熔断只统计传输层/server 级失败。tool_error/validation/file_reference
                # 等调用方错误（典型场景：模型连续传坏参数）不计入，避免把健康
                # server 短路。builtin 不经熔断门控，维持原有全量统计口径。
                failure_kind = result.get("failure_kind")
                if (
                    server.transport == Transport.BUILTIN
                    or counts_toward_circuit_breaker(failure_kind)
                ):
                    self.health_registry.record_failure(key, latency_ms)
                else:
                    # 半开试探收到调用方错误：server 实际已应答，必须释放试探占位，
                    # 否则熔断永久卡死；但不计入失败统计。
                    self.health_registry.release_probe(key)
                last_result = result
                if attempt < policy.max_attempts:
                    await asyncio.sleep(policy.delay_for(attempt))

        fallback = next(
            (
                candidate
                for candidate in fallback_servers
                if candidate.id != server.id
                and candidate.transport == Transport.BUILTIN
                and any(item.tool_name == tool_name for item in candidate.tools)
            ),
            None,
        )
        if fallback is not None:
            fallback_result = await self._call_tool_inner(
                fallback, tool_name, arguments, user_id, context
            )
            if fallback_result.get("success"):
                fallback_result["reliability"] = {
                    "attempts": attempts_made,
                    "fallback_used": fallback.name,
                    "primary_status": self.health_registry.snapshot(key)["status"],
                    "short_circuited": short_circuited,
                }
                return fallback_result

        local_result = await execute_local_fallback(tool_name, arguments)
        if local_result is not None and local_result.get("success"):
            local_result["reliability"] = {
                "attempts": attempts_made,
                "fallback_used": "local",
                "primary_status": self.health_registry.snapshot(key)["status"],
                "short_circuited": short_circuited,
            }
            return local_result

        failure_kind = (
            last_result.get("failure_kind")
            if isinstance(last_result, dict)
            else "unknown"
        )
        # 保留真实根因：固定文案只作前缀，原始错误（server 返回/异常信息）随附回传，
        # 便于调用方与日志定位，而非被统一文案覆盖。
        root_cause = str(last_result.get("error") or "").strip() if isinstance(last_result, dict) else ""
        generic_message = "当前外部服务暂时不可用，备用计算方式也不可用，请稍后重试。"
        error_text = f"{generic_message}（根因：{root_cause}）" if root_cause else generic_message

        return {
            **last_result,
            "error": error_text,
            "reliability": {
                "attempts": attempts_made,
                "primary_status": self.health_registry.snapshot(key)["status"],
                "failure_kind": failure_kind or "unknown",
                "short_circuited": short_circuited,
            },
        }

    async def _call_tool_inner(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str | None = None,
        context: Any | None = None,
    ) -> dict[str, Any]:
        """call_tool 的实际分发逻辑（builtin / stdio / sse）"""
        try:
            arguments = await resolve_workspace_file_refs(
                arguments,
                user_id=user_id,
                context=context,
            )
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc), "failure_kind": "file_reference"}

        if server.transport == Transport.BUILTIN:
            preset = get_preset_by_name(server.name)
            if preset is None:
                return {"success": False, "error": f"未找到内置服务: {server.name}"}
            handler = preset["handlers"].get(tool_name)
            if handler is None:
                return {"success": False, "error": f"工具 {tool_name} 不存在于 {server.name}"}
            try:
                import inspect

                sig = inspect.signature(handler)
                kwargs: dict[str, Any] = {}
                if "user_id" in sig.parameters:
                    kwargs["user_id"] = user_id
                if "tool_name" in sig.parameters:
                    kwargs["tool_name"] = tool_name
                if "context" in sig.parameters:
                    kwargs["context"] = context
                elif context is not None:
                    logger.warning(
                        f"ToolInvocationContext 被忽略：{server.name}.{tool_name} 不接受 context 参数"
                    )
                result = await handler(arguments, **kwargs)
                return {"success": True, "result": result}
            except Exception as e:  # noqa: BLE001
                logger.warning(f"MCP 工具调用失败 {server.name}.{tool_name}: {e}")
                return {"success": False, "error": str(e)}

        # stdio / sse：仍不传递数据库上下文；file:// 已在上方按用户权限解析为文本。
        if context is not None:
            logger.warning(f"ToolInvocationContext blocked for non-builtin transport: {server.name}")

        # stdio / sse
        try:
            result = await self._safe_external(
                server, lambda s: self._call_tool_external(s, tool_name, arguments)
            )
        except MCPExternalCallError as exc:
            return {"success": False, "error": exc.detail, "failure_kind": exc.kind}
        if isinstance(result, dict) and result.get("isError"):
            content = result.get("content") or []
            message = next(
                (
                    str(item.get("text"))
                    for item in content
                    if isinstance(item, dict) and item.get("text")
                ),
                "MCP 工具返回错误",
            )
            return {"success": False, "error": message, "failure_kind": "tool_error"}
        return {"success": True, "result": result}

    async def _safe_external(self, server: MCPServer, fn: Any) -> Any:
        """外部 MCP 调用的错误隔离包装"""
        try:
            return await asyncio.wait_for(fn(server), timeout=server.timeout)
        except TimeoutError as exc:
            logger.warning(f"MCP Server {server.name} 调用超时")
            raise MCPExternalCallError("timeout", f"MCP Server {server.name} 调用超时") from exc
        except Exception as e:  # noqa: BLE001
            logger.warning(f"MCP Server {server.name} 调用异常: {e}")
            detail = str(e) or type(e).__name__
            lowered = detail.lower()
            kind = (
                "command_not_found"
                if "不在 path" in detail or "no such file" in lowered
                else "connection_error"
            )
            raise MCPExternalCallError(kind, detail) from e

    async def _connect_external(self, server: MCPServer) -> _ExternalConnection:
        """建立并初始化一个长活的外部 MCP 连接。"""
        try:
            from mcp import ClientSession
        except ImportError:
            raise RuntimeError("mcp SDK 未安装") from None

        transport_cm = self._open_session(server)
        read, write = await transport_cm.__aenter__()
        session_cm = ClientSession(read, write)
        try:
            session = await session_cm.__aenter__()
            await session.initialize()
        except BaseException:
            await _close_external_connection(
                _ExternalConnection("", transport_cm, session_cm)
            )
            raise
        return _ExternalConnection(
            fingerprint=_external_fingerprint(server),
            transport_cm=transport_cm,
            session_cm=session_cm,
        )

    async def _acquire_external_connection(self, server: MCPServer) -> _ExternalConnection:
        """借用（或建立）该 server 的长活连接。

        per-server 锁只保护「建立/重建/回收」阶段：先在锁外走快速借用路径，
        未命中再进锁 double-check。锁内检查 closing 标志，池关闭期间拒绝新借用。
        """
        key = str(server.id)
        fingerprint = _external_fingerprint(server)
        # close_external_connections 先置标志再做任何 await：锁外快检即可让关闭在途
        # 期间的新借用立即被拒（否则要排队等关闭放锁才看到标志）。
        if _external_pool_closing:
            raise MCPExternalCallError("pool_closing", "MCP 会话池正在关闭")
        conn = _external_connections.get(key)
        if conn is not None and _connection_usable(conn, fingerprint):
            return conn
        async with _external_lock(server):
            if _external_pool_closing:
                raise MCPExternalCallError("pool_closing", "MCP 会话池正在关闭")
            conn = _external_connections.get(key)
            if conn is not None and _connection_usable(conn, fingerprint):
                return conn
            if conn is not None:
                # 陈旧（空闲超期/配置变更/已关闭）：锁内摘除并关闭，再重建
                _external_connections.pop(key, None)
                await _close_external_connection(conn)
            conn = await self._connect_external(server)
            _external_connections[key] = conn
            return conn

    async def _invalidate_external_connection(
        self, server: MCPServer, conn: _ExternalConnection
    ) -> None:
        """按对象身份摘除并关闭一个可能已损坏的连接（锁内执行，不误关新会话）。"""
        key = str(server.id)
        async with _external_lock(server):
            if _external_connections.get(key) is conn:
                _external_connections.pop(key, None)
            await _close_external_connection(conn)

    async def _with_external_session(self, server: MCPServer, fn: Any) -> Any:
        """在复用池中取一个该 server 的可用会话执行 fn(session)。

        工具调用本身不持建连锁：MCP Python SDK 的 ClientSession 按 jsonrpc id
        路由响应、支持单会话并发多路复用，慢调用（如 stdio 60s 超时）不再把同
        server 的其他请求排队卡死。会话损坏/超时后关闭并重建；空闲超期惰性回收
        （回收关闭同样走建连锁）；连接配置变化按 fingerprint 重建。
        """
        conn = await self._acquire_external_connection(server)
        try:
            out = await fn(conn.session_cm)
        except BaseException:
            # 连接可能已损坏（含 wait_for 超时取消导致的 CancelledError），
            # 关闭并移除，保证下次调用重新连接而非复用坏会话。
            await self._invalidate_external_connection(server, conn)
            raise
        conn.last_used = time.monotonic()
        return out

    async def _list_tools_external(self, server: MCPServer) -> list[dict[str, Any]]:
        """通过 MCP SDK 发现外部 stdio/sse 服务的工具（复用长活会话）"""
        try:
            from mcp import ClientSession  # noqa: F401
        except ImportError:
            return []

        result = await self._with_external_session(
            server, lambda session: session.list_tools()
        )
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema or {},
            }
            for t in result.tools
        ]

    async def _call_tool_external(
        self, server: MCPServer, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """通过 MCP SDK 调用外部服务工具（复用长活会话）"""
        try:
            from mcp import ClientSession  # noqa: F401
        except ImportError:
            raise RuntimeError("mcp SDK 未安装") from None

        result = await self._with_external_session(
            server, lambda session: session.call_tool(tool_name, arguments=arguments)
        )
        return {
            "content": [c.model_dump() for c in result.content] if result.content else [],
            "isError": result.isError,
        }

    def _open_session(self, server: MCPServer) -> Any:
        """根据传输模式打开 MCP 会话上下文（含安全校验）"""
        if server.transport == Transport.STDIO:
            from mcp.client.stdio import StdioServerParameters, stdio_client

            command = server.command or ""
            validate_stdio_command(command)
            parts = command.split() if command else []
            command = parts[0] if parts else ""
            args = parts[1:] if len(parts) > 1 else []
            if server.args:
                args = list(server.args)
            validate_stdio_args(args)
            validate_working_dir(server.working_dir)
            params = StdioServerParameters(
                command=command,
                args=args,
                env=server.env or None,
                # working_dir 作为子进程 cwd：本地脚本型 MCP（如 node build/index.js）
                # 用「工作目录 + 相对脚本路径」运行，规避 args 绝对路径禁令。
                cwd=server.working_dir or None,
            )
            return stdio_client(params)
        if server.transport in (Transport.SSE, Transport.STREAMABLE_HTTP):
            if server.transport == Transport.STREAMABLE_HTTP:
                from mcp.client.streamable_http import streamable_http_client

                validate_sse_url(server.url)
                return streamable_http_client(server.url)
            from mcp.client.sse import sse_client

            validate_sse_url(server.url)
            return sse_client(server.url)
        raise ValueError(f"不支持的传输模式: {server.transport}")


def status_from_available(ok: bool) -> str:
    return ServerStatus.ONLINE.value if ok else ServerStatus.ERROR.value
