"""认证路由 - 登录、注册、令牌刷新"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.schemas.auth import (
    LoginResponse,
    RefreshTokenRequest,
    TokenResponse,
    TwoFactorCodeRequest,
    TwoFactorLoginRequest,
    TwoFactorSetupResponse,
    TwoFactorStatusResponse,
    UserRegisterRequest,
)
from omichub.application.schemas.user import UserResponse
from omichub.application.services import AuthService
from omichub.application.services.auth_service import LoginTwoFactorRequired
from omichub.application.services.totp_service import MfaService
from omichub.core.config import get_settings
from omichub.core.exceptions import AuthenticationError, AuthorizationError, ConflictError
from omichub.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
)
from omichub.domain.user.entities import User
from omichub.domain.user.value_objects import Role, UserStatus
from omichub.infrastructure.database.repositories import SqlAlchemyUserRepository
from omichub.middleware.login_rate_limit import LoginRateLimitDep

router = APIRouter()


def get_auth_service(db: DbSession) -> AuthService:
    """获取认证服务实例"""
    return AuthService(SqlAlchemyUserRepository(db), db)


def get_mfa_service(db: DbSession) -> MfaService:
    """获取 2FA 服务实例"""
    return MfaService(SqlAlchemyUserRepository(db), db)


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    rate_limiter: LoginRateLimitDep,
) -> LoginResponse:
    """用户登录（OAuth2 密码模式）。

    - 2FA 未开启：直接返回正式 access/refresh token。
    - 2FA 已开启：返回 requires_2fa=true + challenge_token，前端进入二次校验流程。
    """
    await rate_limiter.check(request)
    try:
        result = await auth_service.login(form_data.username, form_data.password)
    except AuthenticationError:
        await rate_limiter.record_failure(request)
        raise
    await rate_limiter.clear(request)

    if isinstance(result, LoginTwoFactorRequired):
        return LoginResponse(
            requires_2fa=True,
            challenge_token=result.challenge_token,
        )
    return LoginResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type="bearer",
        expires_in=30 * 60,
        first_login=result.is_first_login,
    )


# ====================== 2FA 绑定 / 管理 ======================


@router.get("/2fa/status", response_model=TwoFactorStatusResponse, summary="当前用户 2FA 状态")
async def get_2fa_status(
    current_user_id: CurrentUserId,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TwoFactorStatusResponse:
    user = await auth_service.get_current_user(current_user_id)
    return TwoFactorStatusResponse(enabled=user.is_2fa_enabled, has_secret=bool(user.totp_secret))


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse, summary="生成 2FA 绑定密钥")
async def setup_2fa(
    current_user_id: CurrentUserId,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    mfa_service: Annotated[MfaService, Depends(get_mfa_service)],
) -> TwoFactorSetupResponse:
    """生成随机 TOTP 密钥并加密落盘（不启用）。返回明文密钥 + otpauth_uri 供前端生码。"""
    user = await auth_service.get_current_user(current_user_id)
    secret, uri = await mfa_service.setup(user)
    return TwoFactorSetupResponse(secret=secret, otpauth_uri=uri)


@router.post("/2fa/verify", response_model=TwoFactorStatusResponse, summary="确认启用 2FA")
async def verify_2fa(
    req: TwoFactorCodeRequest,
    current_user_id: CurrentUserId,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    mfa_service: Annotated[MfaService, Depends(get_mfa_service)],
) -> TwoFactorStatusResponse:
    """校验 6 位码通过 → is_2fa_enabled=true。"""
    user = await auth_service.get_current_user(current_user_id)
    await mfa_service.confirm_enable(user, req.code)
    return TwoFactorStatusResponse(enabled=True, has_secret=True)


@router.post("/2fa/disable", response_model=TwoFactorStatusResponse, summary="关闭 2FA")
async def disable_2fa(
    req: TwoFactorCodeRequest,
    current_user_id: CurrentUserId,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    mfa_service: Annotated[MfaService, Depends(get_mfa_service)],
) -> TwoFactorStatusResponse:
    """关闭 2FA：必须校验一次当前验证码，防止他人盗号后关闭。"""
    user = await auth_service.get_current_user(current_user_id)
    await mfa_service.disable(user, req.code)
    return TwoFactorStatusResponse(enabled=False, has_secret=False)


@router.post("/2fa/login", response_model=TokenResponse, summary="2FA 登录校验")
async def login_2fa(
    request: Request,
    req: TwoFactorLoginRequest,
    mfa_service: Annotated[MfaService, Depends(get_mfa_service)],
    rate_limiter: LoginRateLimitDep,
) -> TokenResponse:
    """中间态凭证 + 6 位码 → 正式 access/refresh token。"""
    await rate_limiter.check(request)
    try:
        access_token, refresh_token, _user, first_login = await mfa_service.complete_login(
            req.challenge_token, req.code
        )
    except AuthenticationError:
        await rate_limiter.record_failure(request)
        raise
    await rate_limiter.clear(request)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=30 * 60,
        first_login=first_login,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    req: UserRegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    db: DbSession,
) -> UserResponse:
    """用户注册"""
    # 平台级开关：未开放注册时拒绝
    from omichub.application.services.site_settings_service import SiteSettingsService

    if not await SiteSettingsService(db).is_registration_enabled():
        raise AuthorizationError("平台已关闭注册，请联系管理员")

    user = await auth_service.register(req)
    # 集成点#1: 注册时自动创建饼干账户 + 赠送初始饼干
    if get_settings().enable_cookie_system:
        from omichub.application.services.cookie_service import CookieService

        cookie_service = CookieService(db)
        await cookie_service.get_or_create_account(user.id)
    return UserResponse.model_validate(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    req: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """刷新访问令牌"""
    access_token, refresh_token = await auth_service.refresh_token(req.refresh_token)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=30 * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user_id: CurrentUserId,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """获取当前登录用户信息"""
    user = await auth_service.get_current_user(current_user_id)
    return UserResponse.model_validate(user)


@router.get("/setup-required")
async def setup_required(db: DbSession) -> dict[str, bool]:
    """检查是否需要初始化第一个管理员账号"""
    repo = SqlAlchemyUserRepository(db)
    return {"setup_required": not await repo.has_any_admin()}


@router.post("/setup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def setup_first_admin(
    req: UserRegisterRequest,
    db: DbSession,
) -> TokenResponse:
    """创建第一个管理员账号（仅在系统无管理员时可用）"""
    repo = SqlAlchemyUserRepository(db)

    if await repo.has_any_admin():
        raise ConflictError("系统已存在管理员账号，请通过登录页访问")

    # 检查用户名/邮箱是否已被占用
    if await repo.get_by_username(req.username):
        raise ConflictError(f"用户名 {req.username} 已存在")
    if await repo.get_by_email(req.email):
        raise ConflictError(f"邮箱 {req.email} 已被注册")

    admin = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        role=Role.ADMIN,
        status=UserStatus.ACTIVE,
    )
    created = await repo.save(admin)

    # 如果启用饼干系统，自动创建饼干账户
    if get_settings().enable_cookie_system:
        from omichub.application.services.cookie_service import CookieService

        cookie_service = CookieService(db)
        await cookie_service.get_or_create_account(created.id)

    # 首位管理员也是新用户：创建定向欢迎通知并触发迎新引导
    from omichub.application.services.auth_service import create_welcome_notification

    await create_welcome_notification(db, str(created.id))

    access_token = create_access_token(subject=str(created.id), token_version=0)
    refresh_token = create_refresh_token(subject=str(created.id), token_version=0)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=30 * 60,
        first_login=True,
    )


# ====================== API Key 管理 ======================


@router.post("/api-keys", status_code=status.HTTP_201_CREATED, summary="创建 API Key")
async def create_api_key(
    req: dict,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> dict:
    """创建长期有效的 API Key（供 MCP Server / CLI 工具认证）。明文 key 仅返回一次。"""
    from omichub.application.services.api_key_service import APIKeyService

    service = APIKeyService(db)
    record, plain_key = await service.create_key(
        user_id=current_user_id,
        name=req.get("name", "default"),
        scopes=req.get("scopes"),
    )
    return {
        "id": str(record.id),
        "name": record.name,
        "key": plain_key,
        "key_prefix": record.key_prefix,
        "scopes": record.scopes,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.get("/api-keys", summary="列出 API Keys")
async def list_api_keys(
    current_user_id: CurrentUserId,
    db: DbSession,
) -> list[dict]:
    """列出当前用户的所有活跃 API Key（不含明文）。"""
    from omichub.application.services.api_key_service import APIKeyService

    service = APIKeyService(db)
    keys = await service.list_keys(current_user_id)
    return [
        {
            "id": str(k.id),
            "name": k.name,
            "key_prefix": k.key_prefix,
            "scopes": k.scopes,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="吊销 API Key")
async def revoke_api_key(
    key_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> None:
    """吊销指定的 API Key。"""
    from omichub.application.services.api_key_service import APIKeyService

    service = APIKeyService(db)
    await service.revoke_key(current_user_id, key_id)
