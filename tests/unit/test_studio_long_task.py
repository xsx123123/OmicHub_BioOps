"""Studio Celery 长任务生命周期测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest

from omichub.application.services import studio_task_service
from omichub.domain.task.entities import Task, TaskLog
from omichub.domain.task.value_objects import ExecutionMode, LogLevel, TaskStatus
from omichub.infrastructure.celery_app.tasks import studio as studio_tasks


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _FakeRepo:
    def __init__(self, task: Task) -> None:
        self.task = task

    async def get_by_id(self, task_id: UUID) -> Task | None:
        return self.task if self.task.id == task_id else None

    async def save(self, task: Task) -> Task:
        self.task = task
        return task

    async def append_log(self, task_id: UUID, log_entry: dict[str, Any]) -> None:
        if task_id != self.task.id:
            return
        self.task.logs.append(
            TaskLog(
                timestamp=datetime.fromisoformat(log_entry["timestamp"]),
                level=LogLevel(log_entry["level"]),
                message=log_entry["message"],
                source=log_entry["source"],
            )
        )


class _SubmissionRepo:
    def __init__(self) -> None:
        self.task: Task | None = None

    async def get_by_id(self, task_id: UUID) -> Task | None:
        return self.task if self.task and self.task.id == task_id else None

    async def save(self, task: Task) -> Task:
        self.task = task
        return task

    async def append_log(self, task_id: UUID, log_entry: dict[str, Any]) -> None:
        return None


class _FakeCeleryTask:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def delay(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _FakeManager:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.calls = 0

    def exec(self, *args, **kwargs):
        self.calls += 1

        async def generator():
            for event in self.events:
                yield event

        return generator()


def _task(status: TaskStatus = TaskStatus.QUEUED) -> Task:
    return Task(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        flow_id="studio_sandbox",
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        name="Studio 长任务",
        status=status,
        execution_mode=ExecutionMode.LOCAL,
        parameters={"studio_session_id": "sess-1"},
    )


def _patch_runtime(monkeypatch, task: Task, events: list[dict[str, Any]]):
    db = _FakeDb()
    repo = _FakeRepo(task)
    manager = _FakeManager(events)

    @asynccontextmanager
    async def session_context():
        yield db

    def session_factory():
        return session_context()

    monkeypatch.setattr(
        "omichub.infrastructure.database.session.get_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        "omichub.infrastructure.database.repositories.task_repository.TaskRepositoryImpl",
        lambda _db: repo,
    )
    monkeypatch.setattr(
        "omichub.infrastructure.studio.manager.studio_sandbox_manager",
        manager,
    )

    progress_events: list[tuple[str, float, str]] = []
    task_logs: list[tuple[str, str]] = []

    async def publish_progress(task_id: str, phase: str, progress: float, message: str):
        progress_events.append((phase, progress, message))

    async def publish_log(task_id: str, level: str, message: str, source: str = ""):
        task_logs.append((level, message))

    monkeypatch.setattr(studio_tasks, "publish_arq_progress", publish_progress)
    monkeypatch.setattr(studio_tasks, "publish_task_log", publish_log)
    return db, repo, manager, progress_events, task_logs


@pytest.mark.unit
async def test_submit_studio_long_task_commits_before_celery_dispatch(monkeypatch, tmp_path):
    db = _FakeDb()
    repo = _SubmissionRepo()
    celery_task = _FakeCeleryTask()

    @asynccontextmanager
    async def session_context():
        yield db

    def session_factory():
        return session_context()

    monkeypatch.setattr(studio_task_service, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(studio_task_service, "TaskRepositoryImpl", lambda _db: repo)
    monkeypatch.setattr(studio_task_service, "run_studio_sandbox", celery_task)
    monkeypatch.setattr(
        studio_task_service.studio_sandbox_manager,
        "workspace_dir",
        lambda session_id: tmp_path / session_id,
    )

    result = await studio_task_service.submit_studio_sandbox_task(
        user_id="11111111-1111-1111-1111-111111111111",
        session_id="sess-1",
        language="python",
        code="print(1)",
        timeout_sec=601,
        image="omichub-sandbox:bio",
    )

    assert db.commits == 1
    assert repo.task is not None
    assert repo.task.status == TaskStatus.QUEUED
    assert repo.task.flow_id == "studio_sandbox"
    assert repo.task.work_dir.endswith("sess-1")
    assert celery_task.calls[0]["task_id"] == str(repo.task.id)
    assert result["task_url"].endswith(str(repo.task.id))
    assert result["result_url"] == "/studio/sess-1"


@pytest.mark.unit
async def test_studio_long_task_success_persists_result(monkeypatch):
    db, repo, manager, progress_events, task_logs = _patch_runtime(
        monkeypatch,
        _task(),
        [
            {"type": "stdout", "data": "done"},
            {
                "type": "result",
                "exit_code": 0,
                "duration_ms": 12,
                "artifacts": [{"path": "output/result.csv", "size": 4, "mtime": 1.0}],
            },
        ],
    )

    result = await studio_tasks._run_studio_sandbox(
        task_id=str(repo.task.id),
        user_id=str(repo.task.user_id),
        session_id="sess-1",
        language="python",
        code="print('done')",
        timeout_sec=601,
        image=None,
    )

    assert result["status"] == "success"
    assert repo.task.status == TaskStatus.SUCCESS
    assert repo.task.parameters["studio_result"]["stdout"] == "done"
    assert repo.task.result_path.endswith("/studio/sessions/sess-1/artifacts")
    assert any(event[0] == "COMPLETED" for event in progress_events)
    assert any(message == "Studio 长任务执行完成" for _, message in task_logs)
    assert manager.calls == 1
    assert db.commits >= 3


@pytest.mark.unit
async def test_studio_long_task_cancelled_before_start_is_not_executed(monkeypatch):
    _, repo, manager, progress_events, _ = _patch_runtime(
        monkeypatch,
        _task(TaskStatus.CANCELLED),
        [],
    )

    result = await studio_tasks._run_studio_sandbox(
        task_id=str(repo.task.id),
        user_id=str(repo.task.user_id),
        session_id="sess-1",
        language="bash",
        code="sleep 1",
        timeout_sec=601,
        image=None,
    )

    assert result == {"status": "cancelled", "task_id": str(repo.task.id)}
    assert repo.task.status == TaskStatus.CANCELLED
    assert manager.calls == 0
    assert progress_events == []
