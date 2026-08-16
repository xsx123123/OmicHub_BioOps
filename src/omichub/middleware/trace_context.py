"""请求关联中间件 — 生成/透传 X-Request-ID 并写入 ContextVar

为每个请求建立统一的 request_id，写入 ContextVar 供 loguru patch 注入日志，
实现「同一请求的所有日志可串联」。若客户端/网关已带 X-Request-ID 则透传，
否则生成 UUID4。响应头回写该 ID，便于前端/运维对账。

注册位置：main.py 中最外层（先于 RateLimit add_middleware），确保所有后续
中间件与业务代码都在该 ContextVar 上下文中运行。
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# 当前请求 ID；日志 patch 与业务代码可读取。默认空串表示「请求上下文之外」。
request_id_var: ContextVar[str] = ContextVar("omichub_request_id", default="")

# 当前聊天会话 ID（chat_sessions.session_id）。由会话作用域入口（chat_service 的
# stream_chat / _stream_agent_chat_inner）在解析出 session_id 后设置；日志 patch 读取
# 并注入每条 JSON 日志，实现「按会话串联 AI 助手 / Agent / AI 工作台的全部日志」。
# 默认空串表示「会话上下文之外」。
session_id_var: ContextVar[str] = ContextVar("omichub_session_id", default="")

_HEADER = "x-request-id"


def get_request_id() -> str:
    """读取当前请求 ID（请求上下文之外返回空串）。"""
    return request_id_var.get()


def get_session_id() -> str:
    """读取当前聊天会话 ID（会话上下文之外返回空串）。"""
    return session_id_var.get()


class TraceContextMiddleware(BaseHTTPMiddleware):
    """注入 request_id 到 ContextVar 并回写响应头。"""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        incoming = request.headers.get(_HEADER, "").strip()
        request_id = incoming or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[_HEADER] = request_id
        return response
