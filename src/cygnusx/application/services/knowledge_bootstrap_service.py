"""仓库内置知识库的首次初始化。"""

from __future__ import annotations

import secrets
from pathlib import Path

from scripts.sync_knowledge_from_files import sync
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.security import hash_password
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.user import UserModel

PLATFORM_KNOWLEDGE_USERNAME = "platform"
PLATFORM_KNOWLEDGE_EMAIL = "platform@cygnusx.local"
PLATFORM_KNOWLEDGE_NICKNAME = "平台"
DEFAULT_KNOWLEDGE_META_PATH = Path("docs/knowledge/meta.yaml")


def _meta_exists(meta_yaml_path: Path) -> bool:
    return meta_yaml_path.is_file()


async def ensure_default_knowledge(
    session: AsyncSession,
    *,
    meta_yaml_path: Path = DEFAULT_KNOWLEDGE_META_PATH,
) -> tuple[int, int, int]:
    """为空的实验室知识库导入仓库声明，并以平台账号标记初始版本。"""
    existing = await session.execute(
        select(KbDocumentModel.id).where(KbDocumentModel.kb_id == "lab").limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return 0, 0, 0

    if not _meta_exists(meta_yaml_path):
        return 0, 0, 0

    platform_user = (
        await session.execute(
            select(UserModel).where(UserModel.username == PLATFORM_KNOWLEDGE_USERNAME)
        )
    ).scalar_one_or_none()
    if platform_user is None:
        platform_user = UserModel(
            username=PLATFORM_KNOWLEDGE_USERNAME,
            email=PLATFORM_KNOWLEDGE_EMAIL,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            role="user",
            status="inactive",
            nickname=PLATFORM_KNOWLEDGE_NICKNAME,
            preferences={"system_account": True},
            disabled_modules=[],
        )
        session.add(platform_user)
        await session.flush()

    return await sync(
        meta_yaml_path,
        platform_user.id,
        session,
        index_documents=False,
    )
