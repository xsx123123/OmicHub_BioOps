"""仓库默认知识库首次初始化测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from cygnusx.application.services import knowledge_bootstrap_service


def _scalar_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_empty_lab_knowledge_uses_platform_author_and_syncs_meta(
    monkeypatch, tmp_path
) -> None:
    meta_path = tmp_path / "meta.yaml"
    meta_path.write_text("title: 实验室知识库\nitems: []\n", encoding="utf-8")
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[_scalar_result(None), _scalar_result(None)]
    )
    platform_id = uuid4()

    async def assign_platform_id() -> None:
        session.add.call_args.args[0].id = platform_id

    session.flush = AsyncMock(side_effect=assign_platform_id)
    sync = AsyncMock(return_value=(0, 2, 0))
    monkeypatch.setattr(knowledge_bootstrap_service, "sync", sync)

    result = await knowledge_bootstrap_service.ensure_default_knowledge(
        session, meta_yaml_path=meta_path
    )

    platform_user = session.add.call_args.args[0]
    assert platform_user.username == "platform"
    assert platform_user.nickname == "平台"
    assert platform_user.status == "inactive"
    assert platform_user.preferences == {"system_account": True}
    sync.assert_awaited_once_with(
        meta_path,
        platform_id,
        session,
        index_documents=False,
    )
    assert result == (0, 2, 0)


@pytest.mark.asyncio
async def test_existing_lab_knowledge_skips_repository_sync(monkeypatch, tmp_path) -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result(SimpleNamespace(id=uuid4())))
    sync = AsyncMock()
    monkeypatch.setattr(knowledge_bootstrap_service, "sync", sync)

    result = await knowledge_bootstrap_service.ensure_default_knowledge(
        session, meta_yaml_path=tmp_path / "meta.yaml"
    )

    assert result == (0, 0, 0)
    session.add.assert_not_called()
    sync.assert_not_awaited()
