"""模块权限拦截中间件 — 在 HTTP 层守卫受管控模块的 API

按 data/MODULE_LOCKED.yaml 注册表中各模块的 api_prefix 匹配请求路径，
命中 lockable=true 模块时校验当前用户的 disabled_modules 不含该模块 key，
否则返回 HTTP 403 + MODULE_LOCKED。

匹配规则：「等于前缀」或「以 前缀+'/' 开头」（避免 /api/v1/cookies 误伤
/api/v1/admin/cookies 之类的兄弟前缀）。新增模块接入拦截只需在 YAML 里
配好 api_prefix，无需改本文件。
"""

from __future__ import annotations

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from omichub.infrastructure.config.module_registry import ModuleEntry, get_module_registry

# 命中被禁模块时的统一响应（与前端约定的错误契约）
MODULE_LOCKED_STATUS = 403
MODULE_LOCKED_BODY = '{"detail":"该模块未开通，请联系管理员解锁","code":"MODULE_LOCKED"}'


def match_module_by_path(path: str, modules: list[ModuleEntry]) -> ModuleEntry | None:
    """按 api_prefix 匹配请求路径所属的 lockable 模块，未命中返回 None。

    规则：路径等于前缀，或以「前缀 + '/'」开头。api_prefix 为空的模块永不命中。
    """
    for module in modules:
        for prefix in module.api_prefix:
            if path == prefix or path.startswith(prefix + "/"):
                return module
    return None


class ModuleGateMiddleware(BaseHTTPMiddleware):
    """模块权限拦截中间件 — 受管控模块 API 的按用户授权守卫"""

    async def dispatch(self, request: Request, call_next) -> Response:
        # WebSocket 由端点自行鉴权，放行
        if request.scope["type"] == "websocket":
            return await call_next(request)

        try:
            registry = get_module_registry()
        except Exception:
            # 注册表不可用时降级放行（启动期已硬校验，理论上不会走到这里）
            logger.warning("模块注册表不可用，模块权限拦截降级放行")
            return await call_next(request)

        module = match_module_by_path(request.url.path, registry.lockable_modules())
        if module is None:
            return await call_next(request)

        # AuthMiddleware 已注入 user_id；未认证的请求由后续依赖处理
        user_id = getattr(request.state, "user_id", None)
        if user_id is None:
            return await call_next(request)

        # 查询用户角色与被禁模块；管理员默认拥有全部模块权限
        blocked = await self._is_module_blocked(user_id, module.key)
        if blocked:
            return Response(
                status_code=MODULE_LOCKED_STATUS,
                content=MODULE_LOCKED_BODY,
                media_type="application/json",
            )
        return await call_next(request)

    @staticmethod
    async def _is_module_blocked(user_id: str, module_key: str) -> bool:
        """返回 True 表示拦截。任何异常降级放行并记日志（不阻断正常业务）。"""
        from uuid import UUID

        from omichub.infrastructure.database.models.user import UserModel
        from omichub.infrastructure.database.session import get_session_factory

        try:
            factory = get_session_factory()
            async with factory() as session:
                user = await session.get(UserModel, UUID(user_id))
                if user is None:
                    return False
                if user.role == "admin":
                    return False
                return module_key in (user.disabled_modules or [])
        except Exception as exc:
            logger.warning(f"模块权限校验异常，降级放行 (user={user_id}, module={module_key}): {exc}")
            return False
