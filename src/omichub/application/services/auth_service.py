"""认证应用服务"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.auth import UserRegisterRequest
from omichub.application.services.notification_service import NotificationService
from omichub.application.services.site_content_service import SiteContentService
from omichub.application.services.site_settings_service import SiteSettingsService
from omichub.core.config import get_settings
from omichub.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    OmicHubError,
)
from omichub.core.security import (
    create_2fa_challenge_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from omichub.domain.user.entities import User
from omichub.domain.user.repositories import IUserRepository
from omichub.domain.user.value_objects import UserStatus
from omichub.infrastructure.database.repositories.notification_repository import (
    SqlAlchemyNotificationRepository,
)

logger = logging.getLogger(__name__)


@dataclass
class LoginSuccess:
    """密码登录成功（2FA 未开启）→ 直接下发正式令牌。"""

    access_token: str
    refresh_token: str
    user: User
    is_first_login: bool


@dataclass
class LoginTwoFactorRequired:
    """密码正确但已开启 2FA → 仅下发短时中间态凭证，不下发正式权限。

    前端据此切换到「请输入 6 位动态验证码」表单，调用 /auth/2fa/login 完成校验。
    """

    challenge_token: str
    user: User


async def create_welcome_notification(db: AsyncSession, user_id: str) -> None:
    """为新用户创建一条定向欢迎通知：先引导前往「实验室知识库」，再提示联系管理员。

    管理员联系方式取自 data/OmicHub.yaml 的 registration.admin_contact；
    通知创建失败仅记录日志，不影响登录主流程。
    """
    try:
        admin_contact = SiteContentService().get_content().registration.admin_contact.strip()
        content = (
            "欢迎使用 OmicHub！建议先前往「实验室知识库」查阅组内标准操作规范与服务器使用指南；"
            "若仍有其他问题，可联系管理员获取帮助。"
        )
        if admin_contact:
            content = f"{content}（管理员联系方式：{admin_contact}）"
        repo = SqlAlchemyNotificationRepository(db)
        await NotificationService(repo).create(
            created_by=user_id,
            title="欢迎来到 OmicHub 🚀",
            content=content,
            level="info",
            is_global=False,
            target_user_id=user_id,
        )
    except Exception:
        logger.exception("为新用户 %s 创建欢迎通知失败", user_id)


class AuthService:
    """认证应用服务"""

    def __init__(self, user_repository: IUserRepository, db: AsyncSession):
        self.user_repo = user_repository
        self._db = db
        self.settings = get_settings()

    async def register(self, req: UserRegisterRequest) -> User:
        """用户注册"""
        # 检查用户名是否已存在
        existing_user = await self.user_repo.get_by_username(req.username)
        if existing_user:
            raise ConflictError(f"用户名 {req.username} 已存在")

        # 检查邮箱是否已存在
        existing_email = await self.user_repo.get_by_email(req.email)
        if existing_email:
            raise ConflictError(f"邮箱 {req.email} 已被注册")

        # 哈希密码
        hashed_pwd = hash_password(req.password)

        # 注册表 default_locked: true 的模块，新用户默认锁定
        from omichub.infrastructure.config.module_registry import get_module_registry

        # 创建用户实体 — 默认 pending 状态，需管理员审批
        user = User(
            username=req.username,
            email=req.email,
            hashed_password=hashed_pwd,
            lab_group=req.lab_group,
            disabled_modules=get_module_registry().default_locked_keys(),
        )
        user.status = UserStatus.PENDING

        # 保存用户
        saved = await self.user_repo.save(user)

        # 注册成功即创建用户默认目录；FileService 内部幂等，兼容重试和历史数据修复。
        from omichub.application.services.file_service import FileService

        await FileService(self._db).ensure_default_directories(saved.id)
        return saved

    async def login(self, username: str, password: str) -> LoginSuccess | LoginTwoFactorRequired:
        """用户登录（密码阶段）。

        - 2FA 未开启：校验通过即下发正式 access/refresh token，更新 last_login_at。
        - 2FA 已开启：仅签发 5 分钟中间态凭证（type=2fa_challenge），不下发正式权限、
          不更新 last_login_at；前端需调 /auth/2fa/login 完成二次校验。
        """
        # 防御性捕获：DB 层异常（缺列、连接失败等）不应冒泡成 500 后被前端误判为
        # "密码错误"。此处显式捕获 SQLAlchemyError，记录关键日志并返回通用 500 提示，
        # 让运维一眼看出是系统故障而非认证失败。
        try:
            user = await self.user_repo.get_by_username(username)
        except Exception as exc:
            logging.critical(f"Database error during login (user='{username}'): {exc}")
            raise OmicHubError("系统内部错误，请联系管理员") from exc
        if not user:
            raise AuthenticationError("用户名或密码错误")

        # 验证密码
        if not verify_password(password, user.hashed_password):
            raise AuthenticationError("用户名或密码错误")

        # 验证用户状态
        if user.status != UserStatus.ACTIVE:
            raise AuthenticationError("账户未激活")

        # 站点策略强制 2FA：未绑定则拒绝登录
        try:
            totp_policy = await SiteSettingsService(self._db).get_totp_policy()
        except Exception:
            totp_policy = "optional"
        if totp_policy == "required" and not user.is_2fa_enabled:
            raise AuthenticationError("平台已强制开启二次验证，请先绑定 2FA 后再登录")

        # 2FA 已开启：签发中间态凭证，等二次校验
        if user.is_2fa_enabled:
            challenge = create_2fa_challenge_token(
                subject=str(user.id), token_version=user.token_version
            )
            return LoginTwoFactorRequired(challenge_token=challenge, user=user)

        # 首次登录判定：在更新 last_login_at 之前检查
        is_first_login = user.last_login_at is None

        # 更新最后登录时间
        user.last_login_at = datetime.now(UTC)
        await self.user_repo.save(user)

        # 首次登录：创建定向欢迎通知（失败不阻断登录）
        if is_first_login:
            await create_welcome_notification(self._db, str(user.id))

        # 创建令牌
        access_token = create_access_token(
            subject=str(user.id), token_version=user.token_version
        )
        refresh_token = create_refresh_token(
            subject=str(user.id), token_version=user.token_version
        )

        return LoginSuccess(access_token, refresh_token, user, is_first_login)

    async def refresh_token(self, refresh_token: str) -> tuple[str, str]:
        """刷新访问令牌"""
        # 解码刷新令牌
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise AuthenticationError("无效的刷新令牌")

        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("令牌中缺少用户信息")

        # 验证用户存在
        user = await self.user_repo.get_by_id(uuid.UUID(user_id))
        if not user:
            raise NotFoundError("用户不存在")

        # 校验 token_version：旧版本 token 拒绝刷新
        if payload.get("token_version") != user.token_version:
            raise AuthenticationError("令牌已失效，请重新登录")

        # 创建新的访问令牌
        access_token = create_access_token(subject=user_id, token_version=user.token_version)
        new_refresh_token = create_refresh_token(
            subject=user_id, token_version=user.token_version
        )

        return access_token, new_refresh_token

    async def get_current_user(self, user_id: str) -> User:
        """获取当前用户"""
        user = await self.user_repo.get_by_id(uuid.UUID(user_id))
        if not user:
            raise NotFoundError("用户不存在")

        return user
