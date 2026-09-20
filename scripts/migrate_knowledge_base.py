#!/usr/bin/env python3
"""存量知识库数据迁移脚本

将现有的 docs/knowledge/meta.yaml + .md 文件导入数据库。
仅需执行一次，建议在运行 `alembic upgrade head` 之后执行。

用法示例:
    source .venv/bin/activate
    python scripts/migrate_knowledge_base.py \
        --meta-yaml docs/knowledge/meta.yaml \
        --admin-user-id 00000000-0000-0000-0000-000000000001
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path

import yaml
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_editor import DocEditorModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.session import get_session_factory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def migrate(
    meta_yaml_path: Path,
    admin_user_id: uuid.UUID,
    session: AsyncSession,
) -> int:
    """执行迁移，返回导入文档数量。"""
    section_dir = meta_yaml_path.parent

    # 获取管理员昵称快照
    user_result = await session.execute(
        select(UserModel.username, UserModel.nickname).where(UserModel.id == admin_user_id)
    )
    user_row = user_result.one_or_none()
    if user_row is None:
        raise ValueError(f"admin_user_id {admin_user_id} 不存在")
    admin_name = user_row.nickname or user_row.username

    with open(meta_yaml_path, encoding="utf-8") as f:
        meta = yaml.safe_load(f) or {}

    migrated = 0
    for item in meta.get("items", []):
        doc_id = item.get("id")
        title = item.get("title")
        category = item.get("category") or "未分类"
        md_file = item.get("file")
        if not doc_id or not title or not md_file:
            print(f"[跳过] 条目缺少 id/title/file: {item}")
            continue

        file_path = section_dir / md_file
        content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

        # 1. 创建文档主表记录
        document = KbDocumentModel(
            doc_id=doc_id,
            title=title,
            category=category,
            file_path=str(file_path),
            status=1,
            created_by=admin_user_id,
        )
        session.add(document)
        await session.flush()  # 获取 document.id

        # 2. 创建初始版本
        revision = DocRevisionModel(
            document_id=document.id,
            content=content,
            edit_summary="初始版本（系统迁移）",
            edited_by=admin_user_id,
            status=1,
        )
        session.add(revision)
        await session.flush()  # 获取 revision.id

        # 3. 关联当前版本
        document.current_rev = revision.id

        # 4. 记录编辑者
        editor = DocEditorModel(
            document_id=document.id,
            user_id=admin_user_id,
            user_name=admin_name,
            edit_count=1,
        )
        session.add(editor)

        migrated += 1
        print(f"[已导入] {doc_id}: {title}")

    await session.commit()
    return migrated


async def main() -> None:
    parser = argparse.ArgumentParser(description="迁移存量知识库文件到数据库")
    parser.add_argument(
        "--meta-yaml",
        type=Path,
        default=Path("docs/knowledge/meta.yaml"),
        help="知识库 meta.yaml 路径",
    )
    parser.add_argument(
        "--admin-user-id",
        type=str,
        required=True,
        help="用于标记初始版本创建者的用户 UUID",
    )
    args = parser.parse_args()

    if not args.meta_yaml.exists():
        raise FileNotFoundError(f"meta.yaml 不存在: {args.meta_yaml}")

    admin_user_id = uuid.UUID(args.admin_user_id)

    factory = get_session_factory()
    async with factory() as session:
        migrated = await migrate(args.meta_yaml, admin_user_id, session)

    print(f"迁移完成：共导入 {migrated} 篇文档")


if __name__ == "__main__":
    asyncio.run(main())
