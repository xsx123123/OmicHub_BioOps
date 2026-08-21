"""ProjectService.get_or_create_project_by_name 的复用语义回归测试。

回归背景（2026-08-20）：聊天式 AgentTeams Case 的项目名由需求文本自动生成；
用户在前端删除 Case 后项目仍然保留，用同一需求重新建单时
``create_project`` 抛 "同名项目已存在"，被用户感知为"会话已经存在"。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from omichub.application.services.project_service import ProjectService


class _FakeResult:
    def __init__(self, model):  # noqa: ANN001
        self._model = model

    def scalar_one_or_none(self):  # noqa: ANN202
        return self._model


def _existing_project(user_id):  # noqa: ANN001, ANN202
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        name="我想进行小鼠肺部6个样本 3v3 TP53mutation ",
        slug="我想进行小鼠肺部6个样本_3v3_tp53mutation",
        description=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_get_or_create_reuses_existing_same_slug_project() -> None:
    user_id = uuid4()
    model = _existing_project(user_id)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_FakeResult(model))
    service = ProjectService(session)
    service.create_project = AsyncMock()  # type: ignore[method-assign]

    project = await service.get_or_create_project_by_name(
        user_id, "我想进行小鼠肺部6个样本 3v3 TP53mutation vs TP53 WT 单细胞分析"
    )

    assert project["id"] == str(model.id)
    assert project["slug"] == model.slug
    service.create_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_or_create_falls_back_to_create_when_absent() -> None:
    user_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_FakeResult(None))
    service = ProjectService(session)
    service.create_project = AsyncMock(return_value={"id": "new-project"})  # type: ignore[method-assign]

    project = await service.get_or_create_project_by_name(user_id, "全新需求")

    assert project == {"id": "new-project"}
    service.create_project.assert_awaited_once()
