"""终端路由 - 会话管理 + WebSocket 代理"""

import asyncio
import json
import os
from typing import Annotated
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, WebSocket
from loguru import logger

from cygnusx.api.deps import CurrentUserId, DbSession, get_active_user_from_token_payload
from cygnusx.application.schemas.terminal import (
    CreateTerminalDTO,
    TerminalImageDTO,
    TerminalRuntimeConfigDTO,
    TerminalSessionDTO,
)
from cygnusx.application.services.terminal_service import TerminalService
from cygnusx.core.security import decode_token
from cygnusx.infrastructure.database.session import get_session_factory

router = APIRouter()

# ttyd 1.7.x 协议前缀（与 1.6.x 不同，必须严格对应）
# 客户端 → 服务端
TTYD_INPUT = "0"  # stdin / 键盘输入
TTYD_RESIZE = "1"  # 窗口尺寸变更
TTYD_JSON_DATA = "{"  # 初始 JSON 握手 / 元数据（0x7B）
# 服务端 → 客户端
TTYD_OUTPUT = "0"  # 终端输出（应写入 xterm.js）
TTYD_SET_WINDOW_TITLE = "1"  # 窗口标题变更
TTYD_SET_PREFERENCES = "2"  # 终端偏好设置（字体等）


def get_terminal_service(db: DbSession) -> TerminalService:
    return TerminalService(db)


TerminalServiceDep = Annotated[TerminalService, Depends(get_terminal_service)]


@router.get("/sessions", response_model=list[TerminalSessionDTO], summary="终端会话列表")
async def list_sessions(
    current_user_id: CurrentUserId, service: TerminalServiceDep
) -> list[TerminalSessionDTO]:
    return await service.list_sessions(UUID(current_user_id))


@router.get("/environments", response_model=list[TerminalImageDTO], summary="可用终端镜像列表")
async def list_environments(service: TerminalServiceDep) -> list[TerminalImageDTO]:
    """获取所有启用的沙盒终端镜像（前端镜像选择器数据源）。"""
    return service.get_enabled_images()


@router.get("/config", response_model=TerminalRuntimeConfigDTO, summary="终端运行时配置")
async def get_runtime_config(service: TerminalServiceDep) -> TerminalRuntimeConfigDTO:
    """获取终端启用状态、默认资源和最大资源限制。"""
    return service.get_runtime_config()


@router.post(
    "/sessions",
    response_model=TerminalSessionDTO,
    status_code=201,
    summary="创建终端会话",
)
async def create_session(
    current_user_id: CurrentUserId,
    service: TerminalServiceDep,
    req: CreateTerminalDTO | None = None,
) -> TerminalSessionDTO:
    return await service.create_session(UUID(current_user_id), req)


@router.get("/sessions/{session_id}", response_model=TerminalSessionDTO, summary="终端会话详情")
async def get_session(
    current_user_id: CurrentUserId,
    service: TerminalServiceDep,
    session_id: str,
) -> TerminalSessionDTO:
    return await service.get_session(UUID(current_user_id), session_id)


@router.delete("/sessions/{session_id}", summary="销毁终端会话")
async def delete_session(
    current_user_id: CurrentUserId,
    service: TerminalServiceDep,
    session_id: str,
) -> dict[str, bool]:
    ok = await service.delete_session(UUID(current_user_id), session_id)
    return {"deleted": ok}


@router.websocket("/sessions/{session_id}/ws", name="terminal_websocket")
async def terminal_websocket(websocket: WebSocket, session_id: str) -> None:
    """终端 WebSocket 代理

    连接：wss://host/api/v1/terminal/sessions/<session_id>/ws?token=<JWT>
    双向代理浏览器 ↔ ttyd 容器内 WebSocket
    """
    token = websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=1008, reason="Invalid token")
        return

    user = await get_active_user_from_token_payload(payload)
    if user is None:
        await websocket.close(code=1008, reason="User inactive or not found")
        return

    user_id_str = str(user.id)

    factory = get_session_factory()
    async with factory() as db:
        service = TerminalService(db)
        session = await service.get_session_internal(session_id)
        if session is None or str(session.user_id) != user_id_str:
            await websocket.close(code=1008, reason="Session not found")
            return
        if not session.is_active() or session.host_port is None:
            await websocket.close(code=1008, reason="Session not active")
            return
        host_port = session.host_port

    await websocket.accept(subprotocol="tty")

    # 容器内运行时，经 Docker DNS 直连终端容器的内部端口；
    # 本地开发时回退到宿主映射端口。
    if await asyncio.to_thread(os.path.exists, "/.dockerenv"):
        container_name = f"cygnusx-term-{user_id_str[:8]}-{session_id}"
        ttyd_url = f"ws://{container_name}:7681/ws"
    else:
        ttyd_url = f"ws://localhost:{host_port}/ws"
    ttyd_ws: aiohttp.ClientWebSocketResponse | None = None
    http_session: aiohttp.ClientSession | None = None

    async def forward_client_to_ttyd(ttyd_ws: aiohttp.ClientWebSocketResponse) -> None:
        """浏览器 → ttyd（适配 ttyd 1.7.x 协议前缀）"""
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                data = msg.get("text") or msg.get("bytes")
                if data is None:
                    continue
                if isinstance(data, str):
                    if data.startswith("{"):
                        obj = json.loads(data)
                        msg_type = obj.get("type")
                        if msg_type == "resize":
                            payload = json.dumps({"columns": obj["cols"], "rows": obj["rows"]})
                            await ttyd_ws.send_str(f"{TTYD_RESIZE}{payload}")
                        elif msg_type == "ping":
                            # 前端心跳仅用于维持浏览器→后端 WS，不必转发给 ttyd
                            # ttyd 1.7.x 中 '3' 是 RESUME，误发会导致协议混乱
                            continue
                    else:
                        await ttyd_ws.send_str(f"{TTYD_INPUT}{data}")
                else:
                    await ttyd_ws.send_bytes(b"\x00" + data)
        except Exception:  # noqa: BLE001
            pass

    async def forward_ttyd_to_client(ttyd_ws: aiohttp.ClientWebSocketResponse) -> None:
        """ttyd → 浏览器（按 1.7.x 前缀分发，仅 OUTPUT 写入终端）"""
        try:
            async for msg in ttyd_ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if not msg.data:
                        continue
                    prefix = msg.data[0]
                    payload = msg.data[1:]
                    if prefix == TTYD_OUTPUT:
                        await websocket.send_text(payload)
                    elif prefix == TTYD_SET_WINDOW_TITLE:
                        logger.debug(f"ttyd set title: {payload}")
                    elif prefix == TTYD_SET_PREFERENCES:
                        logger.debug(f"ttyd set preferences: {payload}")
                    elif prefix == TTYD_JSON_DATA:
                        logger.debug(f"ttyd json data: {payload}")
                    # 其他前缀忽略
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    if not msg.data:
                        continue
                    prefix = msg.data[0]
                    payload = msg.data[1:]
                    if prefix == ord(TTYD_OUTPUT):
                        await websocket.send_bytes(payload)
                    # SET_WINDOW_TITLE / SET_PREFERENCES 通常不会以 binary 发送，统一忽略
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except Exception:  # noqa: BLE001
            pass

    try:
        http_session = aiohttp.ClientSession()
        ttyd_ws = await http_session.ws_connect(ttyd_url, protocols=["tty"])

        # ttyd 1.7.x 不会自动 spawn shell，必须在连接建立后先发 JSON_DATA 握手。
        # JSON_DATA 的 "前缀" 就是 JSON 本身的第一个字节 '{'，客户端无需额外再添加字符。
        # 官方客户端行为：socket.send(textEncoder.encode('{"columns":cols,"rows":rows}'))
        await ttyd_ws.send_str('{"columns":80,"rows":24}')

        client_to_ttyd = asyncio.create_task(forward_client_to_ttyd(ttyd_ws))
        ttyd_to_client = asyncio.create_task(forward_ttyd_to_client(ttyd_ws))

        done, pending = await asyncio.wait(
            [client_to_ttyd, ttyd_to_client],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"终端 WebSocket 代理异常 ({session_id}): {e}")
    finally:
        if ttyd_ws and not ttyd_ws.closed:
            await ttyd_ws.close()
        if http_session:
            await http_session.close()

        # 更新心跳
        try:
            async with factory() as db:
                service = TerminalService(db)
                await service.heartbeat(session_id)
                await db.commit()
        except Exception:  # noqa: BLE001
            pass
