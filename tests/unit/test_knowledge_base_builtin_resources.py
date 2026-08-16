from unittest.mock import AsyncMock, Mock

import pytest

from omichub.application.services.knowledge_base_service import (
    BUILTIN_KNOWLEDGE_BASES,
    KnowledgeBaseService,
)
from omichub.core.exceptions import BusinessError


@pytest.mark.asyncio
async def test_ensure_builtin_bases_creates_qc_and_cloud() -> None:
    db = AsyncMock()
    db.add = Mock()
    db.get.return_value = None

    created = await KnowledgeBaseService(db).ensure_builtin_bases()

    assert created == 2
    assert {call.args[0].id for call in db.add.call_args_list} == {"qc", "cloud"}
    assert all(not call.args[0].show_in_lab for call in db.add.call_args_list)
    assert all(call.args[0].ai_searchable for call in db.add.call_args_list)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_builtin_bases_preserves_existing_configuration() -> None:
    db = AsyncMock()
    db.add = Mock()
    db.get.side_effect = [object(), object()]

    created = await KnowledgeBaseService(db).ensure_builtin_bases()

    assert created == 0
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kb_id", BUILTIN_KNOWLEDGE_BASES)
async def test_builtin_bases_cannot_be_deleted(kb_id: str) -> None:
    service = KnowledgeBaseService(AsyncMock())

    with pytest.raises(BusinessError, match="内置知识库不可删除"):
        await service.delete_base(kb_id)
