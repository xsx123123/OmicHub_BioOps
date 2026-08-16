"""数据下载路由集成测试 — 接口契约 + 启用开关 + 鉴权。"""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from omichub.application.schemas.task import TaskResponse
from omichub.core.config import get_settings
from omichub.core.security import create_access_token
from omichub.main import app  # noqa: F401  (确保路由注册)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
async def test_downloads_disabled_by_default(client, auth_headers, monkeypatch):
    """enable_ebi_download=False 时提交被拒（422）。"""
    monkeypatch.setattr(get_settings(), "enable_ebi_download", False)

    resp = await client.post(
        "/api/v1/downloads",
        json={"accession": "PRJNA1"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_submit_download_contract(client, auth_headers, monkeypatch):
    """启用后提交下载，返回任务对象（mock 掉真实下载执行）。"""
    monkeypatch.setattr(get_settings(), "enable_ebi_download", True)

    fake = TaskResponse(
        id=uuid4(),
        flow_id="ebi_download",
        user_id=uuid4(),
        name="EBI 下载 PRJNA1",
        status="queued",
        execution_mode="local",
        parameters={"accession": "PRJNA1"},
        work_dir="/tmp/ebi_download/PRJNA1",
        result_path="",
        error_message="",
        progress=0.0,
        logs=[],
        created_at=datetime.now(),
        started_at=None,
        finished_at=None,
    )
    with patch(
        "omichub.api.v1.downloads.DownloadService.submit",
        new=AsyncMock(return_value=fake),
    ):
        resp = await client.post(
            "/api/v1/downloads",
            json={"accession": "PRJNA1", "download_method": "aws"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["flow_id"] == "ebi_download"
    assert data["status"] == "queued"


@pytest.mark.integration
async def test_submit_cloud_storage_download_contract(client, auth_headers, monkeypatch):
    """启用云存储后可通过同一 /downloads 接口提交云存储直拉任务。"""
    monkeypatch.setattr(get_settings(), "enable_cloud_storage_download", True)

    fake = TaskResponse(
        id=uuid4(),
        flow_id="ebi_download",
        user_id=uuid4(),
        name="云存储下载 阿里云 OSS oss://bucket/raw/",
        status="queued",
        execution_mode="local",
        parameters={"source": "cloud_storage", "object_uri": "oss://bucket/raw/"},
        work_dir="/tmp/raw_data/aliyun_oss_bucket_raw",
        result_path="",
        error_message="",
        progress=0.0,
        logs=[],
        created_at=datetime.now(),
        started_at=None,
        finished_at=None,
    )
    with patch(
        "omichub.api.v1.downloads.DownloadService.submit",
        new=AsyncMock(return_value=fake),
    ):
        resp = await client.post(
            "/api/v1/downloads",
            json={
                "source": "cloud_storage",
                "cloud_provider": "aliyun",
                "object_uri": "oss://bucket/raw/",
            },
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["flow_id"] == "ebi_download"
    assert data["parameters"]["source"] == "cloud_storage"


@pytest.mark.integration
async def test_downloads_requires_auth(client):
    """未认证访问返回 401（路由存在）。"""
    resp = await client.post("/api/v1/downloads", json={"accession": "PRJNA1"})
    assert resp.status_code == 401
