"""JWT 认证中间件 - 全局请求拦截校验"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from cygnusx.core.security import decode_token

# 不需要认证的路径前缀/精确匹配
PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
        "/api/v1/auth/setup-required",
        "/api/v1/auth/setup",
        # 站点级公开配置：登录页未登录即需读取
        "/api/v1/site-settings",  # 注册开关（关闭时登录页拦截注册按钮）
        "/api/v1/site-content",  # 首页文案 + 注册提示文案（YAML 驱动）
        "/api/v1/workflow-monitor/events",  # Worker 内部流程监控原生事件摄取
        "/api/v1/workflow-monitor/loki/api/v1/push",  # Worker 内部 Loki-compatible 摄取
    }
)

PUBLIC_PREFIXES = ("/api/v1/studio/shared/",)

SELF_AUTHENTICATED_PREFIXES = (
    "/api/v1/studio/internal/",
    "/api/v1/agent-teams/consultations/",
    # F4 自省查询面：端点内以 X-Integration-Token 自鉴权（Bridge authenticate=False 调用）
    "/api/v1/agent-teams/introspection/",
)

SELF_AUTHENTICATED_PATHS = frozenset(
    {
        "/api/v1/agent-teams/capabilities",
    }
)


def required_api_key_scope(method: str, path: str) -> str | None:
    """Return the least privilege required for Bridge-accessed CygnusX endpoints."""
    if path.startswith("/api/v1/flows") and method == "GET":
        return "flows:read"
    if path == "/api/v1/tasks" and method == "POST":
        return "tasks:submit"
    if path.startswith("/api/v1/tasks/") and method == "POST" and path.endswith("/cancel"):
        return "tasks:cancel"
    if path == "/api/v1/tasks" and method == "GET":
        return "tasks:read"
    if path.startswith("/api/v1/tasks/") and method == "GET":
        return "tasks:read"
    return None


def api_key_allows_scope(scopes: frozenset[str], required_scope: str | None) -> bool:
    """Legacy unrestricted keys retain compatibility; restricted keys deny unmapped routes."""
    if "*" in scopes:
        return True
    return required_scope is not None and required_scope in scopes


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT 认证中间件 - 校验 Authorization 头并注入 user_id 到 request.state"""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # 公开路径或端点自行鉴权的内部路径直接放行
        if (
            path in PUBLIC_PATHS
            or path in SELF_AUTHENTICATED_PATHS
            or path.startswith(PUBLIC_PREFIXES + SELF_AUTHENTICATED_PREFIXES)
        ):
            return await call_next(request)

        # WebSocket 连接由端点内自行处理
        if request.scope["type"] == "websocket":
            return await call_next(request)

        # 静态资源 / 文档放行
        if path.startswith(("/docs", "/redoc", "/assets")):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if api_key:
            try:
                from cygnusx.application.services.api_key_service import APIKeyService
                from cygnusx.infrastructure.database.session import get_session_factory

                factory = get_session_factory()
                async with factory() as db:
                    user_id, scopes = await APIKeyService(db).authenticate_with_scopes(api_key)
                    await db.commit()
            except Exception:  # noqa: BLE001
                return Response(
                    status_code=401,
                    content='{"detail":"API Key 无效或已过期"}',
                    media_type="application/json",
                )
            request.state.user_id = user_id
            request.state.auth_type = "api_key"
            request.state.api_key_scopes = scopes
            required_scope = required_api_key_scope(request.method, path)
            if not api_key_allows_scope(scopes, required_scope):
                return Response(
                    status_code=403,
                    content='{"detail":"API Key 缺少该操作所需权限范围"}',
                    media_type="application/json",
                )
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return Response(
                status_code=401,
                content='{"detail":"未提供认证令牌"}',
                media_type="application/json",
            )

        token = auth_header.removeprefix("Bearer ")
        payload = decode_token(token)
        if payload is None:
            return Response(
                status_code=401,
                content='{"detail":"令牌无效或已过期"}',
                media_type="application/json",
            )

        # 将用户 ID 注入 request state，供后续依赖使用
        request.state.user_id = payload.get("sub")

        return await call_next(request)
