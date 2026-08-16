"""审计日志中间件

记录写操作（POST/PUT/PATCH/DELETE）到 audit_logs 表：
- 谁操作（user_id/username，来自 AuthMiddleware 注入的 request.state.user_id）
- 操作了什么（method/path/resource_type/resource_id，资源从路径启发式解析）
- 结果（status_code）、来源（ip/user_agent）

设计要点：
- GET / 静态资源不记录，避免噪声
- 用独立 session 写入（get_session_factory），不耦合请求事务；DB 异常仅告警不影响主请求
- AuthMiddleware 已在外层（注册顺序），本中间件读取其注入的 request.state.user_id
"""

import re
import uuid

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# 路径 → (resource_type, resource_id) 启发式解析
# 匹配 /api/v1/{resource}/{id} 或 /api/v1/admin/{resource}/{id}
_RESOURCE_RE = re.compile(r"^/api/v1/(?:admin/)?(?P<type>[a-z_-]+)/(?P<id>[^/]+)")


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    return request.client.host if request.client else None


def _parse_resource(path: str) -> tuple[str | None, str | None]:
    """从路径解析资源类型与 ID，如 /api/v1/tasks/abc → ('tasks', 'abc')。"""
    m = _RESOURCE_RE.match(path)
    if not m:
        return None, None
    return m.group("type"), m.group("id")


class AuditMiddleware(BaseHTTPMiddleware):
    """写操作审计日志记录。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        # 仅审计写操作；非写直接放行，不增加开销
        if request.method not in _WRITE_METHODS:
            return await call_next(request)

        response = await call_next(request)

        # 异步落库，失败不阻断已生成的响应
        try:
            await self._record(request, response)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"审计日志写入失败: {e}")
        return response

    @staticmethod
    async def _record(request: Request, response: Response) -> None:
        from omichub.infrastructure.database.models.audit_log import AuditLogModel
        from omichub.infrastructure.database.session import get_session_factory

        path = request.url.path
        # 静态资源 / 文档 / 健康检查即便方法匹配也不记录（POST 一般也不会命中，保险起见）
        if path.startswith(("/docs-static", "/assets", "/docs", "/redoc")) or path in ("/health",):
            return

        user_id_str = getattr(request.state, "user_id", None)
        user_id = uuid.UUID(user_id_str) if user_id_str else None
        resource_type, resource_id = _parse_resource(path)

        entry = AuditLogModel(
            user_id=user_id,
            username=None,  # 仅记 user_id，避免每次回查 users 表；如需可后续join
            method=request.method,
            path=path,
            resource_type=resource_type,
            resource_id=resource_id,
            status_code=response.status_code,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            detail={},
        )

        factory = get_session_factory()
        async with factory() as session:
            session.add(entry)
            await session.commit()

        # 文本备份：写入 JSON 日志，供后续 Loki/审计排查；失败不影响主请求
        try:
            logger.bind(service="audit").info(
                {
                    "timestamp": entry.created_at.isoformat() if entry.created_at else None,
                    "user_id": str(entry.user_id) if entry.user_id else None,
                    "method": entry.method,
                    "path": entry.path,
                    "resource_type": entry.resource_type,
                    "resource_id": entry.resource_id,
                    "status_code": entry.status_code,
                    "ip": entry.ip,
                    "user_agent": entry.user_agent,
                    "result": "SUCCESS" if entry.status_code < 400 else "FAILURE",
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"审计日志文本备份失败: {e}")
