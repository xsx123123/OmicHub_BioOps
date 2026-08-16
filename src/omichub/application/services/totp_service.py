"""TOTP 二次验证（2FA）应用服务。

基于 pyotp 实现，密钥经 Fernet 加密落盘（复用 ai_provider_key_encryption_key，
未配置密钥时明文，与 AI provider key 同机制）。无第三方短信/邮件依赖。

职责：
  1. setup: 为用户生成随机密钥 → 加密存盘（不启用）→ 返回明文密钥 + otpauth URI 供前端生码。
  2. confirm_enable: 校验用户输入的 6 位码 → 通过则 is_2fa_enabled=True。
  3. disable: 校验一次码 → 清除密钥 + 关闭（防被他人关闭）。
  4. verify_user_code: 通用校验（登录二次校验 + 管理员敏感操作保护复用）。
  5. complete_login: 中间态凭证 + 6 位码 → 下发正式 access/refresh token。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.core.exceptions import AuthenticationError, BusinessError, NotFoundError
from omichub.core.security import (
    create_2fa_challenge_token,
    create_access_token,
    create_refresh_token,
    decode_2fa_challenge_token,
    decrypt_value,
    encrypt_value,
)
from omichub.domain.user.entities import User
from omichub.domain.user.repositories import IUserRepository
from omichub.domain.user.value_objects import UserStatus

logger = logging.getLogger(__name__)

# TOTP 验证码有效窗口：当前 + 前后各 1 步（共 ±30s），兼顾手机时钟漂移
_VALID_WINDOW = 1
# 2FA 中间态凭证有效期
_CHALLENGE_TTL_MINUTES = 5
_ISSUER = "OmicHub"


class MfaService:
    """TOTP 2FA 应用服务。"""

    def __init__(self, user_repository: IUserRepository, db: AsyncSession) -> None:
        self.user_repo = user_repository
        self._db = db

    # ------------------------------------------------------------------ #
    # 纯工具（无状态）
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_secret() -> str:
        """随机 base32 密钥（32 字符）。"""
        return pyotp.random_base32()

    @staticmethod
    def build_otpauth_uri(username: str, secret: str) -> str:
        """拼接 otpauth://totp/OmicHub:{username}?secret=...&issuer=OmicHub。

        pyotp 在 issuer_name 给定时会自动产出 "{issuer}:{name}" 形式的 label，
        故 name 只传 username，避免出现 "OmicHub:OmicHub:alice" 双前缀。
        """
        return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=_ISSUER)

    @staticmethod
    def _verify(plain_secret: str, code: str) -> bool:
        """校验 6 位码；非法输入/不匹配返回 False（不抛异常）。"""
        if not plain_secret or not code:
            return False
        try:
            return pyotp.TOTP(plain_secret).verify(code, valid_window=_VALID_WINDOW)
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # 绑定 / 启用 / 关闭
    # ------------------------------------------------------------------ #
    async def setup(self, user: User) -> tuple[str, str]:
        """生成绑定密钥：加密落盘（不启用），返回 (明文密钥, otpauth_uri) 供前端生码。"""
        secret = self.generate_secret()
        user.totp_secret = encrypt_value(secret)
        user.is_2fa_enabled = False  # 显式：setup 不等于启用
        await self.user_repo.save(user)
        return secret, self.build_otpauth_uri(user.username, secret)

    async def confirm_enable(self, user: User, code: str) -> bool:
        """确认绑定：校验 6 位码通过 → is_2fa_enabled=True。"""
        if not user.totp_secret:
            raise BusinessError("请先获取绑定密钥（调用 setup）")
        plain = decrypt_value(user.totp_secret)
        if not self._verify(plain, code):
            raise AuthenticationError("验证码错误或已过期")
        user.is_2fa_enabled = True
        await self.user_repo.save(user)
        return True

    async def disable(self, user: User, code: str) -> bool:
        """关闭 2FA：必须校验一次当前验证码，防止他人盗号后关闭。"""
        if not user.is_2fa_enabled:
            raise BusinessError("当前未开启 2FA")
        plain = decrypt_value(user.totp_secret) if user.totp_secret else ""
        if not self._verify(plain, code):
            raise AuthenticationError("验证码错误或已过期")
        user.totp_secret = None
        user.is_2fa_enabled = False
        await self.user_repo.save(user)
        return True

    def verify_user_code(self, user: User, code: str) -> bool:
        """通用校验：用户已开启 2FA 且码匹配。登录二次校验 / 管理员敏感操作复用。"""
        if not user.is_2fa_enabled or not user.totp_secret:
            return False
        return self._verify(decrypt_value(user.totp_secret), code)

    # ------------------------------------------------------------------ #
    # 登录二次校验
    # ------------------------------------------------------------------ #
    async def complete_login(self, challenge_token: str, code: str) -> tuple[str, str, User, bool]:
        """2FA 登录校验：中间态凭证 + 6 位码 → 正式 token。

        返回 (access_token, refresh_token, user, is_first_login)。校验通过才更新 last_login_at。
        """
        user_id = decode_2fa_challenge_token(challenge_token)
        if not user_id:
            raise AuthenticationError("2FA 凭证无效或已过期，请重新登录")

        user = await self.user_repo.get_by_id(uuid.UUID(user_id))
        if not user:
            raise NotFoundError("用户不存在")
        if user.status != UserStatus.ACTIVE:
            raise AuthenticationError("账户未激活")
        if not user.is_2fa_enabled:
            raise BusinessError("当前账号未开启 2FA")
        if not self.verify_user_code(user, code):
            raise AuthenticationError("验证码错误或已过期")

        # 2FA 通过：更新登录时间并下发正式令牌
        is_first_login = user.last_login_at is None
        user.last_login_at = datetime.now(UTC)
        await self.user_repo.save(user)

        if is_first_login:
            await self._safe_create_welcome_notification(str(user.id))

        access_token = create_access_token(subject=str(user.id), token_version=user.token_version)
        refresh_token = create_refresh_token(
            subject=str(user.id), token_version=user.token_version
        )
        return access_token, refresh_token, user, is_first_login

    @staticmethod
    async def _safe_create_welcome_notification(user_id: str) -> None:
        """首次登录欢迎通知：失败不阻断登录主流程。"""
        try:
            from omichub.application.services.auth_service import create_welcome_notification
            from omichub.infrastructure.database.session import get_session_factory

            factory = get_session_factory()
            async with factory() as session:
                await create_welcome_notification(session, user_id)
        except Exception:
            logger.exception("为 %s 创建欢迎通知失败", user_id)


def issue_2fa_challenge(user_id: str | uuid.UUID) -> str:
    """便捷：签发 2FA 中间态凭证。"""
    return create_2fa_challenge_token(subject=str(user_id), expires_delta=None)
