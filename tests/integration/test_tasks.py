"""任务路由集成测试"""

from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from cygnusx.application.schemas.task import TaskResponse
from cygnusx.core.security import create_access_token
from cygnusx.domain.task.value_objects import ExecutionMode


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """生成测试用认证头"""
    token = create_access_token({"sub": "test-user"})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
async def test_submit_task_endpoint(client, auth_headers):
    """测试提交任务端点能正确接收请求并返回任务响应"""
    fake_task = TaskResponse(
        id=uuid4(),
        flow_id="rna_seq",
        user_id=uuid4(),
        name="Test Task",
        status="queued",
        execution_mode=ExecutionMode.LOCAL.value,
        parameters={"project_name": "Test"},
        work_dir="/tmp/tasks/test",
        result_path="",
        error_message="",
        progress=0.0,
        logs=[],
        created_at=datetime.now(),
        started_at=None,
        finished_at=None,
    )

    with patch("cygnusx.api.v1.tasks.TaskService.submit", return_value=fake_task):
        response = await client.post(
            "/api/v1/tasks",
            json={
                "flow_id": "rna_seq",
                "name": "Test Task",
                "parameters": {"project_name": "Test"},
                "sample_sheet": [{"sample": "S1", "sample_name": "Sample1", "group": "control"}],
            },
            headers=auth_headers,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["flow_id"] == "rna_seq"
    assert data["status"] == "queued"


@pytest.mark.integration
async def test_list_tasks_endpoint(client, auth_headers):
    """测试任务列表端点返回正确结构"""
    with patch(
        "cygnusx.api.v1.tasks.TaskService.list_tasks",
        return_value={"items": [], "total": 0},
    ):
        response = await client.get("/api/v1/tasks", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
