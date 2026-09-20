"""API 依赖注入"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.totp_service import MfaService
from cygnusx.core.exceptions import AuthenticationError, AuthorizationError
from cygnusx.core.security import decode_token
from cygnusx.domain.user.value_objects import Role
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.repositories import SqlAlchemyUserRepository
from cygnusx.infrastructure.database.session import get_session_factory

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """获取数据库会话"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user_id(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    """解析当前用户 ID：优先 X-API-Key，其次 JWT Bearer token。"""
    if x_api_key and getattr(request.state, "auth_type", "") == "api_key":
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return str(user_id)
    if x_api_key:
        return await _authenticate_api_key(x_api_key)
    if token:
        return await _authenticate_jwt(token)
    raise AuthenticationError("缺少认证凭证：需要 Bearer token 或 X-API-Key")


async def _authenticate_api_key(api_key: str) -> str:
    from cygnusx.application.services.api_key_service import APIKeyService

    factory = get_session_factory()
    async with factory() as db:
        service = APIKeyService(db)
        user_id = await service.authenticate(api_key)
        await db.commit()
    return user_id


async def _authenticate_jwt(token: str) -> str:
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise AuthenticationError("无效的访问令牌")
    user_id = payload.get("sub")
    if user_id is None:
        raise AuthenticationError("令牌中缺少用户信息")

    try:
        uuid_val = uuid.UUID(str(user_id))
    except ValueError as exc:
        raise AuthenticationError("令牌中用户信息无效") from exc
    factory = get_session_factory()
    async with factory() as db:
        user = await db.get(UserModel, uuid_val)
        if user is None or user.status != "active":
            raise AuthenticationError("用户不存在或已被禁用")
        if payload.get("token_version") != user.token_version:
            raise AuthenticationError("令牌已失效，请重新登录")

    return str(user_id)


CurrentUserId = Annotated[str, Depends(get_current_user_id)]


async def require_admin_totp(
    current_user_id: CurrentUserId,
    db: DbSession,
    x_totp_code: Annotated[str | None, Header(alias="X-TOTP-Code")] = None,
) -> str:
    """管理员敏感操作二次校验：请求头 X-TOTP-Code 须为最新的 6 位 TOTP 码。

    用法：在被保护端点的依赖里加 ``AdminTotpRequired``。
    - 非管理员 → 403
    - 管理员未开启 2FA → 403（强制先在个人中心开启）
    - 缺少/错误验证码 → 401
    返回 user_id 供端点继续使用。
    """
    repo = SqlAlchemyUserRepository(db)
    user = await repo.get_by_id(uuid.UUID(current_user_id))
    if not user:
        raise AuthenticationError("无效的访问令牌")
    if user.role != Role.ADMIN:
        raise AuthorizationError("仅管理员可执行此操作")
    if not user.is_2fa_enabled:
        raise AuthorizationError("请先在个人中心开启 2FA 后再执行敏感操作")
    mfa = MfaService(repo, db)
    if not x_totp_code or not mfa.verify_user_code(user, x_totp_code):
        raise AuthenticationError("二次验证码错误或已过期")
    return current_user_id


AdminTotpRequired = Annotated[str, Depends(require_admin_totp)]


async def require_admin(
    current_user_id: CurrentUserId,
    db: DbSession,
) -> str:
    """管理员操作校验（不含 TOTP）：仅校验登录态与角色。

    用于非高敏感的管理操作（如功能灰度开关）。高敏感操作仍用 ``AdminTotpRequired``。
    """
    repo = SqlAlchemyUserRepository(db)
    user = await repo.get_by_id(uuid.UUID(current_user_id))
    if not user:
        raise AuthenticationError("无效的访问令牌")
    if user.role != Role.ADMIN:
        raise AuthorizationError("仅管理员可执行此操作")
    return current_user_id


AdminRequired = Annotated[str, Depends(require_admin)]


async def get_active_user_from_token_payload(payload: dict[str, Any]) -> UserModel | None:
    """从已解码的 JWT payload 中解析用户并校验其处于 active 状态与 token_version。

    用于 WebSocket 端点：token 合法并不够，还需确认用户未被禁用、删除或 token 已被吊销。
    """
    user_id = payload.get("sub")
    if not user_id:
        return None
    try:
        uuid_val = uuid.UUID(str(user_id))
    except ValueError:
        return None
    factory = get_session_factory()
    async with factory() as db:
        user = await db.get(UserModel, uuid_val)
        if user is None or user.status != "active":
            return None
        if payload.get("token_version") != user.token_version:
            return None
        return user
