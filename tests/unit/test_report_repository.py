from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from omichub.infrastructure.database.repositories.report_repository import ReportRepositoryImpl


@pytest.mark.asyncio
async def test_list_by_user_excludes_studio_artifacts_and_eager_loads_files():
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[count_result, items_result])
    repository = ReportRepositoryImpl(session)

    items, total = await repository.list_by_user(uuid4())

    assert items == []
    assert total == 0
    list_query = session.execute.await_args_list[1].args[0]
    compiled = str(list_query.compile(compile_kwargs={"literal_binds": True}))
    assert "reports.flow_id != 'studio'" in compiled
    assert list_query._with_options
