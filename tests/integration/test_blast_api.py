from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

import cygnusx.api.deps as api_deps
from cygnusx.core.security import create_access_token
from cygnusx.tools.blast.schema import (
    BlastTaskListResponse,
    BlastTaskResponse,
)


@pytest.fixture
def auth_headers(monkeypatch) -> dict[str, str]:
    user_id = uuid4()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, model, key):
            return SimpleNamespace(status="active", token_version=0)

        async def commit(self):
            return None

        async def rollback(self):
            return None

    monkeypatch.setattr(api_deps, "get_session_factory", lambda: lambda: FakeSession())
    token = create_access_token(subject=str(user_id), token_version=0)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
async def test_submit_blast_task_endpoint(client, auth_headers) -> None:
    task_id = uuid4().hex
    response_model = BlastTaskResponse(
        task_id=task_id,
        status="queued",
        progress=0,
        message="任务已投递",
        submitted_at=datetime.now(UTC),
    )
    with patch(
        "cygnusx.tools.blast.api.blast_service.submit",
        new=AsyncMock(return_value=response_model),
    ):
        response = await client.post(
            "/api/v1/blast/submit",
            json={
                "db_id": str(uuid4()),
                "query_sequence": ">query\nATGCGTACGTATGCGTACGT",
                "query_title": "integration-query",
                "evalue": 1e-5,
                "max_target_seqs": 10,
            },
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json()["task_id"] == task_id
    assert response.json()["status"] == "queued"


@pytest.mark.integration
async def test_list_blast_tasks_supports_search(client, auth_headers) -> None:
    with patch(
        "cygnusx.tools.blast.api.blast_service.list_user_tasks",
        new=AsyncMock(return_value=BlastTaskListResponse(items=[], total=0)),
    ) as mocked:
        response = await client.get(
            "/api/v1/blast/tasks",
            params={"status": "completed", "search": "rice"},
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert mocked.await_args.kwargs["status"] == "completed"
    assert mocked.await_args.kwargs["search"] == "rice"


@pytest.mark.integration
async def test_blast_task_event_stream_returns_terminal_snapshot(client, auth_headers) -> None:
    task_id = uuid4().hex
    terminal = BlastTaskResponse(task_id=task_id, status="completed", progress=100, message="完成")
    pubsub = Mock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.close = AsyncMock()

    with (
        patch(
            "cygnusx.tools.blast.api.blast_service.get_status",
            new=AsyncMock(return_value=terminal),
        ),
        patch(
            "cygnusx.tools.blast.api.subscribe_blast_events",
            new=AsyncMock(return_value=pubsub),
        ),
    ):
        response = await client.get(f"/api/v1/blast/tasks/{task_id}/events", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"status": "completed"' in response.text
