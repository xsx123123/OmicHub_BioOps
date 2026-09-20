"""饼干消费拦截中间件 — 在 HTTP 层守卫消费类请求

对消费类端点（如任务提交、沙盒启动）做账户状态检查，
余额不足或账户冻结/停用时直接拦截，避免请求进入服务层。
精确的预估+预扣仍由 TaskCookieConsumer 在服务层完成。
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from cygnusx.core.config import get_settings

# 消费类路径：(method, path_prefix) — 命中时执行余额守卫
CONSUMING_ROUTES: tuple[tuple[str, str], ...] = (("POST", "/api/v1/tasks"),)


class CookieRequiredMiddleware(BaseHTTPMiddleware):
    """饼干消费拦截中间件 — 消费类请求的账户状态守卫"""

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if not settings.enable_cookie_system:
            return await call_next(request)

        path = request.url.path
        method = request.method

        # WebSocket / 公开路径放行
        if request.scope["type"] == "websocket":
            return await call_next(request)

        # 仅拦截消费类路由
        if not self._is_consuming_route(method, path):
            return await call_next(request)

        # AuthMiddleware 已注入 user_id；未认证的请求由后续依赖处理
        user_id = getattr(request.state, "user_id", None)
        if user_id is None:
            return await call_next(request)

        # 查询账户状态
        check = await self._check_account(user_id)
        if check is not None:
            return check

        return await call_next(request)

    @staticmethod
    def _is_consuming_route(method: str, path: str) -> bool:
        return any(method == m and path.startswith(prefix) for m, prefix in CONSUMING_ROUTES)

    @staticmethod
    async def _check_account(user_id: str) -> Response | None:
        """返回 Response 拦截请求，返回 None 放行"""
        from uuid import UUID

        from cygnusx.domain.cookie.value_objects import AccountStatus
        from cygnusx.infrastructure.database.repositories.cookie_repository import (
            SqlAlchemyAccountRepository,
        )
        from cygnusx.infrastructure.database.session import get_session_factory

        factory = get_session_factory()
        try:
            async with factory() as session:
                repo = SqlAlchemyAccountRepository(session)
                account = await repo.get_by_user(UUID(user_id))
                # 无账户时放行 — 服务层会通过 get_or_create_account 自动建户
                if account is None:
                    return None
                if account.status == AccountStatus.FROZEN:
                    return Response(
                        status_code=402,
                        content='{"detail":"饼干账户已冻结，无法消费"}',
                        media_type="application/json",
                    )
                if account.status == AccountStatus.SUSPENDED:
                    return Response(
                        status_code=403,
                        content='{"detail":"饼干账户已停用"}',
                        media_type="application/json",
                    )
                # 账户正常但可用余额为零 — 放行让服务层做精确预估
                # (余额刚好够的情况由服务层 pre_deduct 判断)
                return None
        except Exception:
            # 数据库异常时不阻断请求（降级策略），由服务层兜底
            return None
