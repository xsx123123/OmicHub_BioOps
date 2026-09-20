from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from cygnusx.application.services.report_service import ReportService
from cygnusx.core.exceptions import NotFoundError
from cygnusx.infrastructure.database.models.report import ReportModel


def _report(user_id: UUID, *, version: int, parent_id: UUID | None = None) -> ReportModel:
    return ReportModel(
        id=uuid4(),
        task_id=uuid4(),
        user_id=user_id,
        flow_id="studio",
        flow_name="OmicStudio",
        flow_version="",
        flow_icon="",
        title=f"版本 {version}",
        description="",
        status="completed",
        sample_count=0,
        duration=0,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        is_read=False,
        is_starred=False,
        parent_id=parent_id,
        version=version,
        files=[],
    )


@pytest.mark.asyncio
async def test_list_versions_returns_root_and_all_descendants():
    user_id = uuid4()
    root = _report(user_id, version=1)
    second = _report(user_id, version=2, parent_id=root.id)
    third = _report(user_id, version=3, parent_id=second.id)
    unrelated = _report(user_id, version=1)

    service = ReportService(MagicMock())
    service._repo = AsyncMock()
    service._repo.get_by_id.return_value = second
    service._repo.list_version_candidates.return_value = [third, unrelated, second, root]

    result = await service.list_versions(second.id, str(user_id))

    assert result.root_id == root.id
    assert result.current_id == second.id
    assert [item.id for item in result.items] == [root.id, second.id, third.id]
    assert [item.version for item in result.items] == [1, 2, 3]


@pytest.mark.asyncio
async def test_list_versions_hides_other_users_report():
    report = _report(uuid4(), version=1)
    service = ReportService(MagicMock())
    service._repo = AsyncMock()
    service._repo.get_by_id.return_value = report

    with pytest.raises(NotFoundError, match="报告不存在"):
        await service.list_versions(report.id, str(uuid4()))

    service._repo.list_version_candidates.assert_not_called()
