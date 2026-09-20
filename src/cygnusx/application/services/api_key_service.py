"""API Key 认证服务"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.exceptions import AuthenticationError, NotFoundError
from cygnusx.infrastructure.database.models.api_key import APIKeyModel
from cygnusx.infrastructure.database.models.user import UserModel

KEY_PREFIX = "omh_"


def generate_api_key() -> tuple[str, str, str]:
    """生成 API Key，返回 (明文key, sha256_hash, prefix)"""
    raw = secrets.token_urlsafe(32)
    plain = f"{KEY_PREFIX}{raw}"
    key_hash = hashlib.sha256(plain.encode()).hexdigest()
    prefix = plain[:12]
    return plain, key_hash, prefix


def hash_api_key(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


class APIKeyService:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create_key(
        self,
        user_id: str,
        name: str,
        scopes: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[APIKeyModel, str]:
        """创建 API Key，返回 (record, 明文key)。明文仅此次可见。"""
        plain, key_hash, prefix = generate_api_key()
        record = APIKeyModel(
            user_id=uuid.UUID(user_id),
            name=name,
            key_hash=key_hash,
            key_prefix=prefix,
            scopes=scopes or ["*"],
            expires_at=expires_at,
            is_active=True,
        )
        self._db.add(record)
        await self._db.flush()
        return record, plain

    async def list_keys(self, user_id: str) -> list[APIKeyModel]:
        stmt = (
            select(APIKeyModel)
            .where(APIKeyModel.user_id == uuid.UUID(user_id), APIKeyModel.is_active.is_(True))
            .order_by(APIKeyModel.created_at.desc())
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def revoke_key(self, user_id: str, key_id: str) -> None:
        stmt = select(APIKeyModel).where(
            APIKeyModel.id == uuid.UUID(key_id),
            APIKeyModel.user_id == uuid.UUID(user_id),
        )
        result = await self._db.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFoundError("API Key 不存在")
        record.is_active = False

    async def authenticate(self, plain_key: str) -> str:
        """验证 API Key，返回 user_id。失败抛 AuthenticationError。"""
        user_id, _ = await self.authenticate_with_scopes(plain_key)
        return user_id

    async def authenticate_with_scopes(self, plain_key: str) -> tuple[str, frozenset[str]]:
        """验证 API Key，返回用户 ID 与该 Key 的已声明权限范围。"""
        key_hash = hash_api_key(plain_key)
        stmt = select(APIKeyModel).where(
            APIKeyModel.key_hash == key_hash,
            APIKeyModel.is_active.is_(True),
        )
        result = await self._db.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            raise AuthenticationError("无效的 API Key")

        if record.expires_at and record.expires_at < datetime.now(UTC):
            raise AuthenticationError("API Key 已过期")

        user = await self._db.get(UserModel, record.user_id)
        if user is None or user.status != "active":
            raise AuthenticationError("关联用户不存在或已被禁用")

        record.last_used_at = datetime.now(UTC)
        return str(record.user_id), frozenset(str(scope) for scope in (record.scopes or []))
