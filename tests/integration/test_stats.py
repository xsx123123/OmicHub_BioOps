"""仪表板统计路由集成测试 — 接口契约 + 管理员鉴权阻断。"""

from unittest.mock import AsyncMock, patch

import pytest

from omichub.core.exceptions import AuthorizationError
from omichub.core.security import create_access_token
from omichub.main import app
from omichub.middleware.rbac import require_admin


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
async def test_user_overview_contract(client, auth_headers):
    """个人状态概览返回 running/total/samples。"""
    with patch(
        "omichub.api.v1.stats.StatsService.user_overview",
        new=AsyncMock(return_value={"running": 1, "total": 5, "samples": 12}),
    ):
        resp = await client.get("/api/v1/stats/overview", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"running": 1, "total": 5, "samples": 12}


@pytest.mark.integration
async def test_user_trend_passes_days_param(client, auth_headers):
    """趋势接口透传 days 查询参数。"""
    payload = [{"date": "06/30", "tasks": 1, "samples": 2}]
    with patch(
        "omichub.api.v1.stats.StatsService.user_trend",
        new=AsyncMock(return_value=payload),
    ) as mocked:
        resp = await client.get("/api/v1/stats/trend?days=30", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked.assert_called_once_with("test-user", 30)


@pytest.mark.integration
async def test_admin_stats_forbidden_for_non_admin(client, auth_headers):
    """非管理员访问 /admin/stats/* 必须返回 403（spec 权限阻断标准）。"""

    async def _forbid():
        raise AuthorizationError("需要管理员权限")

    app.dependency_overrides[require_admin] = _forbid
    try:
        resp = await client.get("/api/v1/admin/stats/status", headers=auth_headers)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


@pytest.mark.integration
async def test_admin_status_ok_for_admin(client, auth_headers):
    """管理员可获取全平台状态分布。"""

    async def _allow():
        return None

    app.dependency_overrides[require_admin] = _allow
    try:
        with patch(
            "omichub.api.v1.admin.stats.StatsService.admin_status",
            new=AsyncMock(return_value={"running": 2, "success": 5, "failed": 1}),
        ):
            resp = await client.get("/api/v1/admin/stats/status", headers=auth_headers)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["running"] == 2


@pytest.mark.integration
async def test_admin_recent_failed_contract(client, auth_headers):
    """管理员异常监控端点返回失败任务列表。"""

    async def _allow():
        return None

    app.dependency_overrides[require_admin] = _allow
    try:
        failed = [
            {
                "id": "t-1",
                "name": "崩溃任务",
                "flow_id": "rna_seq",
                "user_id": "u-1",
                "error_message": "oom",
                "created_at": "2026-06-30T10:00:00",
            }
        ]
        with patch(
            "omichub.api.v1.admin.stats.StatsService.admin_recent_failed",
            new=AsyncMock(return_value=failed),
        ):
            resp = await client.get(
                "/api/v1/admin/stats/recent-failed?limit=10",
                headers=auth_headers,
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()[0]["flow_id"] == "rna_seq"
