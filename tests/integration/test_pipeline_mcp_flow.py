"""RNA-seq MCP 流水线 API 提交与结果获取集成测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.api.deps import get_current_user_id, get_db
from omichub.application.services.pipeline_controller import PipelineController
from omichub.core.security import create_access_token
from omichub.main import app


class _FakeAsyncSession(AsyncSession):
    def __init__(self):
        pass


async def _user_override() -> str:
    return "00000000-0000-0000-0000-000000000001"


async def _db_override() -> AsyncIterator[AsyncSession]:
    yield _FakeAsyncSession()  # type: ignore[misc]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rna_pipeline_prepare_submit_status_and_results(client) -> None:
    task_id = "11111111-1111-1111-1111-111111111111"
    headers = {
        "Authorization": "Bearer "
        + create_access_token({"sub": "00000000-0000-0000-0000-000000000001"})
    }
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_db] = _db_override
    try:
        with (
            patch.object(
                PipelineController,
                "prepare",
                new_callable=AsyncMock,
                return_value={
                    "valid": True,
                    "prepared_params": {
                        "confirmation_id": "confirm-1",
                        "pipeline_type": "rna_seq",
                    },
                },
            ),
            patch.object(
                PipelineController,
                "submit",
                new_callable=AsyncMock,
                return_value={
                    "task_id": task_id,
                    "pipeline_type": "rna_seq",
                    "status": "QUEUED",
                    "progress": 0,
                },
            ),
            patch.object(
                PipelineController,
                "status",
                new_callable=AsyncMock,
                return_value={
                    "task_id": task_id,
                    "pipeline_type": "rna_seq",
                    "status": "success",
                    "progress": 1,
                    "is_terminal": True,
                },
            ),
            patch.object(
                PipelineController,
                "results",
                new_callable=AsyncMock,
                return_value={
                    "task_id": task_id,
                    "pipeline_type": "rna_seq",
                    "status": "success",
                    "metrics": {
                        "differential_gene_count": 12,
                        "upregulated_count": 7,
                        "downregulated_count": 5,
                    },
                    "artifacts": [{"name": "report.html", "path": "output/report.html"}],
                },
            ),
        ):
            prepare_response = await client.post(
                "/api/v1/pipelines/rna_seq/prepare",
                json={
                    "raw_data_path": "inbox/rna",
                    "species": "Homo sapiens",
                    "genome_version": "hg38",
                    "sample_sheet": [
                        {"sample": "S1", "sample_name": "Control", "group": "control"}
                    ],
                    "comparisons": [],
                    "library_type": "fr-unstranded",
                    "task_name": "RNA MCP task",
                    "project_name": "RNA MCP",
                },
                headers=headers,
            )
            assert prepare_response.status_code == 200
            prepared_params = prepare_response.json()["prepared_params"]

            submit_response = await client.post(
                "/api/v1/pipelines/rna_seq/submit",
                json={"prepared_params": prepared_params},
                headers=headers,
            )
            assert submit_response.status_code == 200
            assert submit_response.json()["task_id"] == task_id

            status_response = await client.get(
                f"/api/v1/pipelines/rna_seq/{task_id}/status",
                headers=headers,
            )
            assert status_response.json()["is_terminal"] is True

            results_response = await client.post(
                f"/api/v1/pipelines/rna_seq/{task_id}/results",
                json={"result_types": ["summary", "artifacts"]},
                headers=headers,
            )
            assert results_response.status_code == 200
            assert results_response.json()["metrics"]["upregulated_count"] == 7
    finally:
        app.dependency_overrides.clear()
