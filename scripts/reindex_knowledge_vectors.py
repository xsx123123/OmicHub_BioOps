#!/usr/bin/env python3
"""Rebuild kb_chunks and embeddings for published knowledge-base documents."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow direct execution from the repository root without requiring callers to
# export PYTHONPATH=src first.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cygnusx.application.services.knowledge_index_service import KnowledgeIndexService
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel
from cygnusx.infrastructure.database.session import close_db, get_session_factory
from sqlalchemy import select


async def reindex(limit: int) -> int:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(KbDocumentModel, DocRevisionModel.content)
                .join(DocRevisionModel, KbDocumentModel.current_rev == DocRevisionModel.id)
                .where(KbDocumentModel.status == 1)
                .order_by(KbDocumentModel.updated_at.asc())
                .limit(limit)
            )
        ).all()
        indexer = KnowledgeIndexService(session)
        indexed = 0
        for document, content in rows:
            await indexer.index_document(document, content, include_unreferenced_assets=True)
            indexed += 1
        await session.commit()
        return indexed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10_000)
    args = parser.parse_args()
    try:
        count = asyncio.run(reindex(max(1, args.limit)))
        print(f"Reindexed {count} knowledge documents.")
    finally:
        asyncio.run(close_db())


if __name__ == "__main__":
    main()
