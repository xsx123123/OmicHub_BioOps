"""产物血缘用户端点 ASGI 集成测试（批 4.1 / P2-9）。

覆盖真实路由 GET /api/v1/agent-teams/cases/{case_id}/artifact-lineage：
1. owner 正路径：血缘 versions/dependencies + qc_verdicts(counts/checks) 结构完整。
2. 非 owner 被拒（service 层归属校验抛 BusinessError）；未登录被拒（401）。
3. 空 case：无版本/无判决时返回空清单与零计数，不报错。

DB 与 Bridge 通过 dependency_overrides 替换为内存 fake，不触真实库/桥。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import cygnusx.api.v1.agentteams as agentteams_api
from cygnusx.api.deps import get_current_user_id, get_db
from cygnusx.core.exceptions import BusinessError
from cygnusx.core.security import create_access_token
from cygnusx.infrastructure.database.models.chat import (
    CaseArtifactDependencyModel,
    CaseArtifactVersionModel,
    QcVerificationCheckModel,
)
from cygnusx.main import app

_LINEAGE_URL = "/api/v1/agent-teams/cases/case-1/artifact-lineage"
# AuthMiddleware 在依赖注入前校验 Bearer token 形态；用户身份仍由
# get_current_user_id 覆盖注入，token 只需通过中间件。
_AUTH_HEADERS = {
    "Authorization": "Bearer "
    + create_access_token({"sub": "00000000-0000-0000-0000-000000000001"})
}


class _Result:
    """模拟 AsyncSession.execute 返回值的最小表面。"""

    def __init__(self, *, scalars=(), rows=()) -> None:
        self._scalars = scalars
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def all(self):
        return list(self._rows)


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
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )


def _check_row(verdict: str, reason: str = "r") -> QcVerificationCheckModel:
    return QcVerificationCheckModel(
        case_id="case-1",
        claim_hash="b" * 64,
        verdict=verdict,
        evidence_event_id=None,
        reviewer_agent="agent-qc",
        claim_snapshot={},
        reason=reason,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )


def _fake_db(*, execute_results=()) -> SimpleNamespace:
    return SimpleNamespace(execute=AsyncMock(side_effect=list(execute_results)))


def _fake_agentteams(*, owner: bool = True) -> SimpleNamespace:
    if owner:
        get_case = AsyncMock(return_value={"case_id": "case-1"})
    else:
        get_case = AsyncMock(side_effect=BusinessError("无权查看该协作案例"))
    return SimpleNamespace(get_case=get_case)


async def _client_with_overrides(
    db: SimpleNamespace, *, user_id: str | None = "user-1", owner: bool = True
) -> AsyncClient:
    """装配依赖覆盖后的 ASGI 客户端（调用方负责关闭）；user_id=None 时不覆盖认证。"""

    async def _override_db():
        yield db

    async def _override_agentteams():
        return _fake_agentteams(owner=owner)

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[agentteams_api.get_agentteams_service] = _override_agentteams
    if user_id is not None:
        app.dependency_overrides[get_current_user_id] = lambda: user_id
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def overrides_cleanup():
    yield
    app.dependency_overrides.clear()


@pytest.mark.integration
async def test_lineage_owner_happy_path(overrides_cleanup) -> None:
    version = _version_row("exec-01/report.md", 1)
    edge = CaseArtifactDependencyModel(
        case_id="case-1",
        downstream_artifact_id="exec-01/report.md",
        upstream_artifact_id="projects/p1/counts.tsv",
        relation="input_to",
    )
    checks = [_check_row("pass", "一致"), _check_row("fail", "缺证据")]
    db = _fake_db(
        execute_results=[
            _Result(scalars=[version]),
            _Result(scalars=[edge]),
            _Result(rows=[("pass", 2), ("fail", 1)]),
            _Result(scalars=checks),
        ]
    )
    async with await _client_with_overrides(db) as client:
        response = await client.get(_LINEAGE_URL, headers=_AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["versions"][0]["artifact_id"] == "exec-01/report.md"
    assert payload["versions"][0]["upstream"] == [
        {"artifact_id": "projects/p1/counts.tsv", "relation": "input_to"}
    ]
    assert payload["dependencies"][0]["relation"] == "input_to"
    verdicts = payload["qc_verdicts"]
    assert verdicts["counts"] == {"pass": 2, "warn": 0, "fail": 1}
    assert [c["verdict"] for c in verdicts["checks"]] == ["pass", "fail"]
    assert verdicts["checks"][0]["reviewer_agent"] == "agent-qc"


@pytest.mark.integration
async def test_lineage_non_owner_rejected(overrides_cleanup) -> None:
    async with await _client_with_overrides(_fake_db(), owner=False) as client:
        response = await client.get(_LINEAGE_URL, headers=_AUTH_HEADERS)
    assert response.status_code == 400
    assert "无权" in str(response.json()["detail"])


@pytest.mark.integration
async def test_lineage_unauthenticated_rejected(overrides_cleanup) -> None:
    async with await _client_with_overrides(_fake_db(), user_id=None) as client:
        response = await client.get(_LINEAGE_URL)
    assert response.status_code == 401


@pytest.mark.integration
async def test_lineage_empty_case_returns_empty_lists(overrides_cleanup) -> None:
    db = _fake_db(
        execute_results=[
            _Result(scalars=[]),
            _Result(scalars=[]),
            _Result(rows=[]),
            _Result(scalars=[]),
        ]
    )
    async with await _client_with_overrides(db) as client:
        response = await client.get(_LINEAGE_URL, headers=_AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["versions"] == []
    assert payload["dependencies"] == []
    assert payload["qc_verdicts"] == {"counts": {"pass": 0, "warn": 0, "fail": 0}, "checks": []}
