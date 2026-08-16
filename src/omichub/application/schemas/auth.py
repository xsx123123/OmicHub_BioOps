"""认证相关DTO模型"""

import re

from pydantic import Field, field_validator

from omichub.application.schemas.base import OmicsHubBaseSchema


class UserRegisterRequest(OmicsHubBaseSchema):
    """用户注册请求"""

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$",
        description="用户名：字母/数字/下划线，3-50字符",
    )
    email: str = Field(
        ...,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
        description="邮箱地址",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="密码：至少8位字符",
    )
    lab_group: str | None = Field(
        default=None,
        max_length=120,
        description="所属课题组（研究组/实验室，可空）",
    )

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """密码强度校验"""
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class RefreshTokenRequest(OmicsHubBaseSchema):
    """刷新 Token 请求"""

    refresh_token: str = Field(..., description="Refresh Token")


class TokenResponse(OmicsHubBaseSchema):
    """Token 响应体"""

    access_token: str = Field(description="访问令牌（短期有效，默认30分钟）")
    refresh_token: str = Field(description="刷新令牌（长期有效，默认7天）")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(description="访问令牌过期时间（秒）")
    first_login: bool = Field(
        default=False,
        description="是否为首次登录（last_login_at 为空时判定为 True），前端据此触发迎新引导",
    )


class LoginResponse(OmicsHubBaseSchema):
    """登录响应（兼容 2FA 拦截）。

    - requires_2fa=False：access_token/refresh_token 为正式令牌，直接登录成功。
    - requires_2fa=True：access_token/refresh_token 为空，challenge_token 为 5 分钟
      中间态凭证；前端切换到「6 位动态验证码」表单，调 /auth/2fa/login 完成校验。
    """

    access_token: str = Field(default="", description="访问令牌；2FA 拦截时为空")
    refresh_token: str = Field(default="", description="刷新令牌；2FA 拦截时为空")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(default=0, description="访问令牌过期秒数；2FA 拦截时为 0")
    first_login: bool = Field(default=False)
    requires_2fa: bool = Field(default=False, description="是否需要二次验证")
    challenge_token: str | None = Field(
        default=None, description="2FA 中间态凭证（仅 requires_2fa=true 时返回）"
    )


class TwoFactorCodeRequest(OmicsHubBaseSchema):
    """6 位 TOTP 验证码请求体（绑定确认 / 关闭 / 管理员敏感操作）。"""

    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="6 位数字验证码",
    )


class TwoFactorLoginRequest(OmicsHubBaseSchema):
    """2FA 登录校验请求体。"""

    challenge_token: str = Field(..., description="密码阶段返回的 2FA 中间态凭证")
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TwoFactorSetupResponse(OmicsHubBaseSchema):
    """绑定密钥响应：前端据 otpauth_uri 生成二维码。"""

    secret: str = Field(description="明文 base32 密钥（可手动输入）")
    otpauth_uri: str = Field(description="otpauth://totp/... URI，用于生成二维码")


class TwoFactorStatusResponse(OmicsHubBaseSchema):
    """当前用户 2FA 状态。"""

    enabled: bool = Field(description="是否已开启 2FA")
    has_secret: bool = Field(description="是否已生成绑定密钥（可能尚未确认启用）")
