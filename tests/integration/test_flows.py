"""流程路由集成测试"""

import pytest

from cygnusx.core.security import create_access_token


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """生成测试用认证头"""
    token = create_access_token({"sub": "test-user"})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
async def test_list_flows(client, auth_headers):
    """测试 /api/v1/flows 列表接口返回已加载的流程"""
    response = await client.get("/api/v1/flows", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(item["id"] == "rna_seq" for item in data["items"])


@pytest.mark.integration
async def test_flows_redirect(client, auth_headers):
    """测试顶层 /flows 在开发模式下重定向到 /api/v1/flows"""
    response = await client.get("/flows", headers=auth_headers, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/api/v1/flows"
