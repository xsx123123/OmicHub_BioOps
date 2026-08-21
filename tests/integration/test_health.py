"""健康检查集成测试"""

import pytest


@pytest.mark.integration
async def test_health_check(client):
    """测试 /health 端点返回 ok"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    # 部署版本可观测：version/git_sha/build_time 必须始终存在（未注入时为 "unknown"）
    assert data["version"]
    assert data["git_sha"]
    assert data["build_time"]
