"""F4 自省端点 ASGI 集成测试（批 3.2 / N4 合并施工）。

覆盖两个真实路由：
- POST /api/v1/agent-teams/introspection/query
- GET  /api/v1/agent-teams/introspection/schema

断言三层行为：
1. 授权粒度：X-Integration-Token 缺失/错误 → 401；正确 → 放行。
2. SQL 绕过：UNION、子查询、行注释、块注释、表别名 → 400（IntrospectionDeniedError），
   且 denied 命中词不泄漏到对外报错文案。
3. 模板正路径：artifact_versions 模板经真实路由返回 200 与行数据。

DB 与 Bridge 通过 dependency_overrides 替换为内存 fake，不触真实库/桥。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import cygnusx.api.v1.agentteams as agentteams_api
from cygnusx.api.deps import get_db
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsRoomModel,
    CaseArtifactVersionModel,
)
from cygnusx.main import app

_TOKEN = "itest-integration-token"
_QUERY_URL = "/api/v1/agent-teams/introspection/query"
_SCHEMA_URL = "/api/v1/agent-teams/introspection/schema"
_HEADERS = {"X-Integration-Token": _TOKEN}


class _Result:
    """模拟 AsyncSession.execute 返回值的最小表面。"""

    def __init__(self, *, scalars=(), one=None) -> None:
        self._scalars = scalars
        self._one = one

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def one(self):
        return self._one


def _room() -> AgentTeamsRoomModel:
    return AgentTeamsRoomModel(
        room_id="room-1", owner_id="user-1", case_id="case-1", proposal=None
    )


def _version_row(artifact_id: str, version_no: int) -> CaseArtifactVersionModel:
    return CaseArtifactVersionModel(
        case_id="case-1",
        artifact_id=artifact_id,
        version_no=version_no,
        checksum_sha256="a" * 64,
        size_bytes=10,
        content_type="text/markdown",
        storage_uri=f"s3://agentteams/cases/case-1/{artifact_id}",
        environment_snapshot={},
    )


def _fake_db(*, scalars=(), execute_results=()) -> SimpleNamespace:
    return SimpleNamespace(
        scalar=AsyncMock(side_effect=list(scalars)),
        execute=AsyncMock(side_effect=list(execute_results)),
    )


def _fake_agentteams() -> SimpleNamespace:
    return SimpleNamespace(
        post_case_evidence=AsyncMock(return_value={"event_id": "audit-1"}),
        get_case=AsyncMock(return_value={"case_id": "case-1"}),
    )


async def _client_with_overrides(db: SimpleNamespace) -> AsyncClient:
    """装配依赖覆盖后的 ASGI 客户端（调用方负责关闭）。"""

    async def _override_db():
        yield db

    async def _override_agentteams():
        return _fake_agentteams()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[agentteams_api.get_agentteams_service] = _override_agentteams
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def integration_token(monkeypatch):
    """把路由模块内的 get_settings 钉到固定 integration token。"""

    monkeypatch.setattr(
        agentteams_api,
        "get_settings",
        lambda: SimpleNamespace(agentteams_integration_token=_TOKEN),
    )
    yield
    app.dependency_overrides.clear()


# ---- 授权粒度 ----


@pytest.mark.integration
async def test_query_without_token_rejected(integration_token) -> None:
    async with await _client_with_overrides(_fake_db()) as client:
        response = await client.post(
            _QUERY_URL, json={"case_id": "case-1", "caller": "manager", "template": "artifact_versions"}
        )
    assert response.status_code == 401


@pytest.mark.integration
async def test_query_with_wrong_token_rejected(integration_token) -> None:
    async with await _client_with_overrides(_fake_db()) as client:
        response = await client.post(
            _QUERY_URL,
            headers={"X-Integration-Token": "wrong-token"},
            json={"case_id": "case-1", "caller": "manager", "template": "artifact_versions"},
        )
    assert response.status_code == 401


@pytest.mark.integration
async def test_schema_without_token_rejected(integration_token) -> None:
    async with await _client_with_overrides(_fake_db()) as client:
        response = await client.get(_SCHEMA_URL)
    assert response.status_code == 401


@pytest.mark.integration
async def test_schema_with_token_returns_document(integration_token) -> None:
    async with await _client_with_overrides(_fake_db()) as client:
        response = await client.get(_SCHEMA_URL, headers=_HEADERS)
    assert response.status_code == 200
    assert response.json()["document"]


# ---- SQL 绕过（N4 缺口：UNION / 子查询 / 注释 / 别名显式用例进集成测试）----


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT artifact_id FROM case_artifact_versions UNION SELECT token FROM worker_tokens",
        "SELECT artifact_id FROM case_artifact_versions WHERE artifact_id IN (SELECT artifact_id FROM worker_tokens)",
        "SELECT artifact_id FROM case_artifact_versions -- 注释掉后续 WHERE",
        "SELECT artifact_id FROM case_artifact_versions /* 块注释 */ WHERE version_no > 0",
        "SELECT v.artifact_id FROM case_artifact_versions v",
    ],
)
@pytest.mark.integration
async def test_query_sql_bypass_variants_rejected(integration_token, sql: str) -> None:
    db = _fake_db(scalars=[_room(), 0])
    async with await _client_with_overrides(db) as client:
        response = await client.post(
            _QUERY_URL,
            headers=_HEADERS,
            json={"case_id": "case-1", "caller": "manager", "sql": sql},
        )
    assert response.status_code in {400, 422}
    # 无论走 denied（400）还是语法收窄（422），对外文案都不得泄漏命中细节
    detail = str(response.json()["detail"])
    assert "worker_tokens" not in detail
    assert "token" not in detail.lower()


# ---- 模板正路径经真实路由 ----


@pytest.mark.integration
async def test_query_template_artifact_versions_happy_path(integration_token) -> None:
    rows = [_version_row("exec-01/a.md", 1)]
    db = _fake_db(
        scalars=[_room(), 1],
        execute_results=[_Result(one=(1, 10)), _Result(scalars=rows)],
    )
    async with await _client_with_overrides(db) as client:
        response = await client.post(
            _QUERY_URL,
            headers=_HEADERS,
            json={"case_id": "case-1", "caller": "manager", "template": "artifact_versions"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["template"] == "artifact_versions"
    assert payload["row_count"] == 1
    assert payload["rows"][0]["artifact_id"] == "exec-01/a.md"
