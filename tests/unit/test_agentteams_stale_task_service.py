from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cygnusx.application.services.agentteams_stale_task_service import (
    AgentTeamsStaleTaskService,
)
from cygnusx.core.exceptions import NotFoundError
from cygnusx.infrastructure.database.models.task import TaskModel


class Result:
    def __init__(self, tasks):
        self._tasks = tasks

    def all(self):
        return self._tasks


class FakeDb:
    def __init__(self, tasks):
        self.tasks = tasks
        self.flushes = 0
        self.commits = 0

    async def scalars(self, _statement):
        return Result(self.tasks)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1


class FakeFlows:
    def get_flow_config(self, flow_id):
        if flow_id == "unknown":
            raise NotFoundError("missing")
        return SimpleNamespace(execution=SimpleNamespace(config_file_name="analysis.yaml"))

    def get_flow(self, flow_id):
        if flow_id == "unknown":
            raise NotFoundError("missing")
        return SimpleNamespace(
            execution={
                "snakefile": "/pipelines/Snakefile",
                "config_file_param": "analysisyaml",
                "default_resources": {"cores": 8},
            }
        )


def _task(tmp_path, *, attempts=0, flow_id="rna_seq"):
    work_dir = tmp_path / "run"
    work_dir.mkdir(exist_ok=True)
    (work_dir / "analysis.yaml").write_text("project: test\n", encoding="utf-8")
    now = datetime.now(UTC)
    return TaskModel(
        id=uuid4(),
        flow_id=flow_id,
        user_id=uuid4(),
        name="stale",
        status="queued",
        parameters={"_agentteams_watchdog_requeue_attempts": attempts} if attempts else {},
        work_dir=str(work_dir),
        logs=[],
        started_at=None,
        created_at=now - timedelta(minutes=20),
        updated_at=now - timedelta(minutes=20),
    )


@pytest.mark.asyncio
async def test_stale_task_is_requeued_once_with_original_execution_contract(tmp_path) -> None:
    task = _task(tmp_path)
    db = FakeDb([task])
    calls = []
    service = AgentTeamsStaleTaskService(
        db, flow_service=FakeFlows(), enqueue=lambda *args, **kwargs: calls.append((args, kwargs))
    )

    result = await service.scan(now=datetime.now(UTC))

    assert result == {"scanned": 1, "requeued": 1, "failed": 0, "skipped": 0}
    assert task.parameters["_agentteams_watchdog_requeue_attempts"] == 1
    assert task.status == "queued"
    assert calls[0][0][1:] == ("/pipelines/Snakefile", str(task.id))
    assert calls[0][1]["task_id"] == f"analysis-{task.id}-attempt-1"
    assert calls[0][1]["cores"] == 8


@pytest.mark.asyncio
async def test_stale_task_is_failed_after_single_requeue(tmp_path) -> None:
    task = _task(tmp_path, attempts=1)
    db = FakeDb([task])
    service = AgentTeamsStaleTaskService(
        db, flow_service=FakeFlows(), enqueue=lambda *_a, **_k: None
    )

    result = await service.scan(now=datetime.now(UTC))

    assert result == {"scanned": 1, "requeued": 0, "failed": 1, "skipped": 0}
    assert task.status == "failed"
    assert task.finished_at is not None
    assert "仍未被 Worker 消费" in task.error_message


@pytest.mark.asyncio
async def test_stale_task_with_missing_flow_is_failed_explicitly(tmp_path) -> None:
    task = _task(tmp_path, flow_id="unknown")
    service = AgentTeamsStaleTaskService(
        FakeDb([task]), flow_service=FakeFlows(), enqueue=lambda *_a, **_k: None
    )

    result = await service.scan(now=datetime.now(UTC))

    assert result == {"scanned": 1, "requeued": 0, "failed": 1, "skipped": 0}
    assert task.status == "failed"
    assert "不存在或已停用" in task.error_message


@pytest.mark.asyncio
async def test_stale_task_is_failed_when_requeue_dispatch_raises(tmp_path) -> None:
    task = _task(tmp_path)

    def fail_enqueue(*_args, **_kwargs):
        raise RuntimeError("broker unavailable")

    service = AgentTeamsStaleTaskService(
        FakeDb([task]), flow_service=FakeFlows(), enqueue=fail_enqueue
    )

    result = await service.scan(now=datetime.now(UTC))

    assert result == {"scanned": 1, "requeued": 0, "failed": 1, "skipped": 0}
    assert task.status == "failed"
    assert "broker unavailable" in task.error_message
