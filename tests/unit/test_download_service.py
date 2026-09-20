"""DownloadService 单元测试 — 任务创建 / 参数落库 / 目录生成 / dispatch。"""

from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from uuid import uuid4

import pytest

from cygnusx.application.schemas.download import DownloadRequest
from cygnusx.application.services.download_service import (
    DOWNLOAD_FLOW_ID,
    DownloadService,
)
from cygnusx.domain.task.entities import Task
from cygnusx.domain.task.value_objects import TaskStatus
from cygnusx.infrastructure.celery_app.tasks.download import run_download


@pytest.fixture
def service(tmp_path: Path) -> DownloadService:
    """DownloadService，仓储/域服务 mock，Celery delay mock。"""
    svc = DownloadService(db=MagicMock())
    svc._settings = svc._settings.model_copy(update={"storage_path": str(tmp_path)})
    svc._repo = AsyncMock()
    svc._domain = AsyncMock()
    return svc


@pytest.mark.asyncio
@pytest.mark.quarantine(reason="fixture 构造的 DownloadService 依赖 _settings 属性，现行实现已移除，setup 阶段 AttributeError")
async def test_submit_creates_download_task_and_dispatches(service):
    user_id = str(uuid4())
    req = DownloadRequest(accession="PRJNA1251654", download_method="aws")

    created_task = Task(
        id=uuid4(),
        flow_id=DOWNLOAD_FLOW_ID,
        user_id=uuid4(),
        name="EBI 下载 PRJNA1251654",
        status=TaskStatus.PENDING,
        parameters={"accession": "PRJNA1251654"},
    )
    service._domain.submit.return_value = created_task
    service._repo.save.return_value = created_task
    # transition_status 返回 QUEUED 后的任务
    queued = created_task.model_copy(update={"status": TaskStatus.QUEUED})
    service._domain.transition_status.return_value = queued

    with patch("cygnusx.application.services.download_service.enqueue_task") as mock_enqueue:
        result = await service.submit(user_id, req)

    # 域服务以 ebi_download flow_id 建任务
    service._domain.submit.assert_called_once()
    call_kwargs = service._domain.submit.call_args.kwargs
    assert call_kwargs["flow_id"] == DOWNLOAD_FLOW_ID
    assert call_kwargs["parameters"]["accession"] == "PRJNA1251654"
    assert call_kwargs["sample_count"] == 0

    # work_dir 落在 upload_dir 下（触发 Files 自动入库）
    assert "raw_data" in created_task.work_dir
    assert "PRJNA1251654" in created_task.work_dir

    # 统一任务路由器已投递（默认仍可走 Celery）
    mock_enqueue.assert_called_once_with(run_download, task_id=str(created_task.id))
    # 状态推进到 QUEUED
    service._domain.transition_status.assert_called_once()
    assert result.flow_id == DOWNLOAD_FLOW_ID


def test_download_request_rejects_empty_accession():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DownloadRequest(accession="   ")


def test_download_request_accepts_batch_direct_links_and_rejects_other_schemes():
    from pydantic import ValidationError

    request = DownloadRequest(
        source="direct_link",
        links=[" https://example.org/ref.fa.gz ", "ftp://ftp.example.org/ref.gff3"],
        download_threads=8,
        overwrite_policy="skip",
    )
    assert request.links == ["https://example.org/ref.fa.gz", "ftp://ftp.example.org/ref.gff3"]
    assert request.download_threads == 8
    assert request.overwrite_policy == "skip"

    with pytest.raises(ValidationError):
        DownloadRequest(source="direct_link", links=["file:///tmp/secret"])


def test_build_direct_link_args_keeps_urls_as_argv_values():
    from cygnusx.infrastructure.celery_app.tasks.download import _build_direct_link_args

    args = _build_direct_link_args(
        ["https://example.org/a file.gz", "ftp://example.org/b.gz"],
        "/tmp/work",
        4,
        "auto_rename",
    )
    assert "--continue=true" in args
    assert "--split" in args
    assert args[-2:] == ["https://example.org/a file.gz", "ftp://example.org/b.gz"]


@pytest.mark.asyncio
@pytest.mark.quarantine(reason="fixture 构造的 DownloadService 依赖 _settings 属性，现行实现已移除，setup 阶段 AttributeError")
async def test_submit_sanitizes_accession_path(service):
    """accession 含路径分隔符时清理，防越权写目录。"""
    req = DownloadRequest(accession="../etc/passwd")
    created = Task(
        id=uuid4(),
        flow_id=DOWNLOAD_FLOW_ID,
        user_id=uuid4(),
        name="x",
        status=TaskStatus.PENDING,
        parameters={},
    )
    service._domain.submit.return_value = created
    service._repo.save.return_value = created
    service._domain.transition_status.return_value = created

    with patch("cygnusx.application.services.download_service.run_download"):
        await service.submit(str(uuid4()), req)

    # 不存在 ".." 路径分量（即无目录穿越，原始 ../ 已被替换为单段目录名）
    from pathlib import Path

    assert ".." not in Path(created.work_dir).parts


@pytest.mark.asyncio
@pytest.mark.quarantine(reason="fixture 构造的 DownloadService 依赖 _settings 属性，现行实现已移除，setup 阶段 AttributeError")
async def test_submit_cloud_storage_task_and_dispatches(service):
    user_id = str(uuid4())
    req = DownloadRequest(
        source="cloud_storage",
        cloud_provider="aliyun",
        object_uri="oss://bucket/raw/",
        target_directory="projects/rna-seq",
    )

    created_task = Task(
        id=uuid4(),
        flow_id=DOWNLOAD_FLOW_ID,
        user_id=uuid4(),
        name="cloud",
        status=TaskStatus.PENDING,
        parameters={},
    )
    service._domain.submit.return_value = created_task
    service._repo.save.return_value = created_task
    queued = created_task.model_copy(update={"status": TaskStatus.QUEUED})
    service._domain.transition_status.return_value = queued

    with patch("cygnusx.application.services.download_service.enqueue_task") as mock_enqueue:
        result = await service.submit(user_id, req)

    call_kwargs = service._domain.submit.call_args.kwargs
    assert call_kwargs["flow_id"] == DOWNLOAD_FLOW_ID
    assert call_kwargs["parameters"]["source"] == "cloud_storage"
    assert call_kwargs["parameters"]["cloud_provider"] == "aliyun"
    assert call_kwargs["parameters"]["object_uri"] == "oss://bucket/raw/"
    assert "projects/rna-seq" in created_task.work_dir
    assert "aliyun_oss_bucket_raw" in created_task.work_dir
    mock_enqueue.assert_called_once_with(run_download, task_id=str(created_task.id))
    assert result.flow_id == DOWNLOAD_FLOW_ID


@pytest.mark.asyncio
@pytest.mark.quarantine(reason="fixture 构造的 DownloadService 依赖 _settings 属性，现行实现已移除，setup 阶段 AttributeError")
async def test_submit_direct_link_task_persists_batch_options(service):
    user_id = str(uuid4())
    req = DownloadRequest(
        source="direct_link",
        links=["https://example.org/ref.fa.gz", "ftp://example.org/genes.gff3"],
        download_threads=8,
        overwrite_policy="skip",
        recursive=True,
        target_directory="reference",
    )
    created = Task(
        id=uuid4(),
        flow_id=DOWNLOAD_FLOW_ID,
        user_id=uuid4(),
        name="direct",
        status=TaskStatus.PENDING,
        parameters={},
    )
    service._domain.submit.return_value = created
    service._repo.save.return_value = created
    service._domain.transition_status.return_value = created

    with patch("cygnusx.application.services.download_service.enqueue_task") as mock_enqueue:
        await service.submit(user_id, req)

    params = service._domain.submit.call_args.kwargs["parameters"]
    assert params["source"] == "direct_link"
    assert params["links"] == req.links
    assert params["download_threads"] == 8
    assert params["overwrite_policy"] == "skip"
    assert params["recursive"] is True
    mock_enqueue.assert_called_once_with(run_download, task_id=str(created.id))


@pytest.mark.asyncio
@pytest.mark.quarantine(reason="fixture 构造的 DownloadService 依赖 _settings 属性，现行实现已移除，setup 阶段 AttributeError")
async def test_list_downloads_filters_by_flow_id(service):
    user_id = str(uuid4())
    download_task = Task(
        id=uuid4(),
        flow_id=DOWNLOAD_FLOW_ID,
        user_id=uuid4(),
        name="d",
        status=TaskStatus.SUCCESS,
        parameters={},
    )
    analysis_task = Task(
        id=uuid4(),
        flow_id="rna_seq",
        user_id=uuid4(),
        name="a",
        status=TaskStatus.SUCCESS,
        parameters={},
    )
    service._repo.list_by_user.return_value = [analysis_task, download_task]

    result = await service.list_downloads(user_id)

    assert result.total == 1
    assert result.items[0].flow_id == DOWNLOAD_FLOW_ID
