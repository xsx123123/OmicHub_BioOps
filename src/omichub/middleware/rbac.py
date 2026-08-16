"""RBAC 权限检查 — 基于数据库角色的 FastAPI 依赖

角色字段：UserModel.role（admin / user）。本模块提供按角色查库校验的统一依赖，
消除历史各 admin 路由内重复的 require_admin 实现。
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select

from omichub.api.deps import CurrentUserId, DbSession
from omichub.core.exceptions import AuthorizationError


def require_roles(*roles: str) -> Callable[..., None]:
    """要求当前用户具有指定角色之一（实时查库校验）。

    用法:
        # 路由级守卫
        @router.delete("/{id}", dependencies=[Depends(require_roles("admin"))])
    """
    allowed = {r.lower() for r in roles}

    async def _check_role(user_id: CurrentUserId, db: DbSession) -> None:
        # 延迟导入，规避模型加载顺序导致的循环引用
        from omichub.infrastructure.database.models.user import UserModel

        result = await db.execute(select(UserModel.role).where(UserModel.id == UUID(user_id)))
        role = result.scalar_one_or_none()
        if role is None:
            raise AuthorizationError("用户不存在")
        if role.lower() not in allowed:
            raise AuthorizationError("权限不足")

    return _check_role


# 管理员校验：模块级稳定函数，便于测试用 dependency_overrides 覆盖。
# AdminRequired 与本函数绑定同一对象，故 overrides[require_admin] 可生效。
async def require_admin(user_id: CurrentUserId, db: DbSession) -> None:
    """校验当前用户为管理员（实时查库）。"""
    from omichub.infrastructure.database.models.user import UserModel

    result = await db.execute(select(UserModel.role).where(UserModel.id == UUID(user_id)))
    role = result.scalar_one_or_none()
    if role is None:
        raise AuthorizationError("用户不存在")
    if role.lower() != "admin":
        raise AuthorizationError("权限不足")


# 便捷依赖：要求管理员角色。各 admin 路由统一从这里导入，避免重复实现。
AdminRequired = Annotated[None, Depends(require_admin)]
# 别名，与计划文档命名一致
RequireAdmin = AdminRequired
