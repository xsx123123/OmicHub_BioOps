"""安全模块 - JWT 签发/验证、密码哈希、对称加密"""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet

from cygnusx.core.config import get_settings


def _get_fernet() -> Fernet | None:
    """根据配置返回 Fernet 实例；未配置加密密钥时返回 None"""
    key = get_settings().ai_provider_key_encryption_key
    if not key:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception:
        return None


def encrypt_value(plain: str) -> str:
    """对称加密字符串；未配置密钥时原样返回"""
    if not plain:
        return plain
    fernet = _get_fernet()
    if fernet is None:
        return plain
    return fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_value(cipher: str) -> str:
    """解密字符串；未配置密钥或原文时原样返回"""
    if not cipher:
        return cipher
    fernet = _get_fernet()
    if fernet is None:
        return cipher
    try:
        return fernet.decrypt(cipher.encode("utf-8")).decode("utf-8")
    except Exception:
        return cipher


def hash_password(password: str) -> str:
    """密码哈希（bcrypt）"""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希是否匹配"""
    pwd_bytes = plain_password.encode("utf-8")
    hash_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(pwd_bytes, hash_bytes)


def create_access_token(
    subject: str | int,
    token_version: int | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """创建 Access Token"""
    settings = get_settings()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "type": "access",
    }
    if token_version is not None:
        payload["token_version"] = token_version
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    subject: str | int,
    token_version: int | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """创建 Refresh Token"""
    settings = get_settings()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(days=settings.refresh_token_expire_days)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "type": "refresh",
    }
    if token_version is not None:
        payload["token_version"] = token_version
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    """解码 JWT Token，失败返回 None"""
    settings = get_settings()
    try:
        return jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None


def create_2fa_challenge_token(
    subject: str | int,
    token_version: int | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """创建 2FA 中间态凭证（短时 JWT，type=2fa_challenge，默认 5 分钟）。

    仅用于密码校验通过、但需完成 TOTP 二次校验的过渡态；不携带任何正式权限。
    """
    settings = get_settings()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=5))
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "type": "2fa_challenge",
    }
    if token_version is not None:
        payload["token_version"] = token_version
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_2fa_challenge_token(token: str) -> str | None:
    """解码 2FA 中间态凭证，返回 user_id；非法/过期/类型不符返回 None。"""
    payload = decode_token(token)
    if payload is None or payload.get("type") != "2fa_challenge":
        return None
    user_id = payload.get("sub")
    return str(user_id) if user_id else None
