"""Agent 模板管理端点集成测试 — 校验创建/更新/列表契约及 model_id 处理。"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from cygnusx.core.security import create_access_token
from cygnusx.main import app
from cygnusx.middleware.rbac import require_admin


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_override():
    async def _allow() -> None:
        return None

    app.dependency_overrides[require_admin] = _allow
    yield
    app.dependency_overrides.clear()


@pytest.mark.integration
async def test_update_agent_rejects_nonexistent_model_id(client, auth_headers, admin_override):
    """更新 Agent 时绑定不存在的 model_id 应返回 400 业务错误，而不是 500。"""
    resp = await client.post(
        "/api/v1/admin/agents",
        json={"name": "模型校验", "category": "general"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    agent_id = resp.json()["agent_id"]

    resp = await client.put(
        f"/api/v1/admin/agents/{agent_id}",
        json={"model_id": str(uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "模型配置不存在" in resp.json()["detail"]


@pytest.mark.integration
async def test_list_agents_contract(client, auth_headers, admin_override):
    """/admin/agents 列表端点应返回 Agent 数组。"""
    payload = [
        {
            "agent_id": "assistant-general",
            "name": "通用助手",
            "description": "",
            "avatar": "🤖",
            "color": "#4f8ef7",
            "category": "general",
            "model_id": None,
            "model_name": "",
            "model_engine": "",
            "system_prompt": "",
            "welcome_message": "你好",
            "mcp_ids": [],
            "skill_ids": [],
            "features": {},
            "temperature": 0.7,
            "max_tokens": 4096,
            "is_builtin": False,
            "is_active": True,
            "is_default": False,
            "created_at": None,
            "updated_at": None,
        }
    ]
    with patch(
        "cygnusx.api.v1.admin.agents.AgentService.list_agents",
        new=AsyncMock(return_value=payload),
    ):
        resp = await client.get("/api/v1/admin/agents", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()[0]["agent_id"] == "assistant-general"


@pytest.mark.integration
async def test_create_agent_with_valid_model_id(client, auth_headers, admin_override):
    """创建 Agent 时传入合法 UUID 模型 ID 应成功。"""
    model_id = str(uuid4())
    created = {
        "agent_id": "agent-test",
        "name": "测试助手",
        "description": "",
        "avatar": "🤖",
        "color": "#4f8ef7",
        "category": "general",
        "model_id": model_id,
        "model_name": "测试模型",
        "model_engine": "qdoubao-seed-evolving",
        "system_prompt": "",
        "welcome_message": "你好",
        "mcp_ids": [],
        "skill_ids": [],
        "features": {},
        "temperature": 0.7,
        "max_tokens": 4096,
        "is_builtin": False,
        "is_active": True,
        "is_default": False,
        "created_at": None,
        "updated_at": None,
    }
    with patch(
        "cygnusx.api.v1.admin.agents.AgentService.create_agent",
        new=AsyncMock(return_value=created),
    ) as mocked:
        resp = await client.post(
            "/api/v1/admin/agents",
            json={"name": "测试助手", "model_id": model_id},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    assert resp.json()["model_id"] == model_id
    mocked.assert_awaited_once()


@pytest.mark.integration
async def test_create_agent_rejects_invalid_model_id(client, auth_headers, admin_override):
    """创建 Agent 时传入非法 model_id 应返回 422 而非 500。"""
    resp = await client.post(
        "/api/v1/admin/agents",
        json={"name": "测试助手", "model_id": "qdoubao-seed-evolving"},
        headers=auth_headers,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "请求参数校验失败"


@pytest.mark.integration
async def test_update_agent_with_empty_model_id(client, auth_headers, admin_override):
    """更新 Agent 时清空 model_id（传空字符串）应被接受。"""
    updated = {
        "agent_id": "assistant-general",
        "name": "通用助手",
        "description": "",
        "avatar": "🤖",
        "color": "#4f8ef7",
        "category": "general",
        "model_id": None,
        "model_name": "",
        "model_engine": "",
        "system_prompt": "",
        "welcome_message": "你好",
        "mcp_ids": [],
        "skill_ids": [],
        "features": {},
        "temperature": 0.7,
        "max_tokens": 4096,
        "is_builtin": False,
        "is_active": True,
        "is_default": False,
        "created_at": None,
        "updated_at": None,
    }
    with patch(
        "cygnusx.api.v1.admin.agents.AgentService.update_agent",
        new=AsyncMock(return_value=updated),
    ) as mocked:
        resp = await client.put(
            "/api/v1/admin/agents/assistant-general",
            json={"model_id": ""},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    mocked.assert_awaited_once()
