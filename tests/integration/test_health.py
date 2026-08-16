"""健康检查集成测试"""

import pytest


@pytest.mark.integration
async def test_health_check(client):
    """测试 /health 端点返回 ok"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
