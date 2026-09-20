"""Studio Celery 长任务生命周期测试（WP2 任务4 三契约）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest

from cygnusx.application.services import studio_task_service
from cygnusx.core.exceptions import ConflictError, NotFoundError, ValidationError
from cygnusx.domain.task.entities import Task, TaskLog
from cygnusx.domain.task.value_objects import ExecutionMode, LogLevel, TaskStatus
from cygnusx.infrastructure.celery_app.tasks import studio as studio_tasks


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeRepo:
    def __init__(self, task: Task) -> None:
        self.task = task

    async def get_by_id(self, task_id: UUID) -> Task | None:
        return self.task if self.task.id == task_id else None

    async def get_by_idempotency_key(self, key: str) -> Task | None:
        return None

    async def count_attempts_by_key_prefix(self, key_prefix: str) -> int:
        return 0

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
    """按幂等键索引的内存仓储：模拟 DB UNIQUE 约束下的查询行为。"""

    def __init__(self) -> None:
        self.tasks: dict[UUID, Task] = {}
        self.enforce_unique = True

    async def get_by_id(self, task_id: UUID) -> Task | None:
        return self.tasks.get(task_id)

    async def get_by_idempotency_key(self, key: str) -> Task | None:
        for task in self.tasks.values():
            if task.idempotency_key == key:
                return task
        return None

    async def count_attempts_by_key_prefix(self, key_prefix: str) -> int:
        return sum(
            1
            for task in self.tasks.values()
            if task.idempotency_key
            and task.idempotency_key.startswith(f"{key_prefix}:a")
        )

    async def save(self, task: Task) -> Task:
        self.tasks[task.id] = task
        return task

    async def append_log(self, task_id: UUID, log_entry: dict[str, Any]) -> None:
        task = self.tasks.get(task_id)
        if task is None:
            return
        task.logs.append(
            TaskLog(
                timestamp=datetime.fromisoformat(log_entry["timestamp"]),
                level=LogLevel(log_entry["level"]),
                message=log_entry["message"],
                source=log_entry["source"],
            )
        )


class _FakeCeleryTask:
    """模拟 enqueue_task 走 Celery 分支所需的 task 协议（name/apply_async）。"""

    name = "cygnusx.infrastructure.celery_app.tasks.studio.run_studio_sandbox"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.options: list[dict[str, Any]] = []

    def apply_async(self, args: Any = None, kwargs: Any = None, **options: Any) -> None:
        self.calls.append(dict(kwargs or {}))
        self.options.append(options)


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
        "cygnusx.infrastructure.database.session.get_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.database.repositories.task_repository.TaskRepositoryImpl",
        lambda _db: repo,
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.studio.manager.studio_sandbox_manager",
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


def _submission_runtime(monkeypatch, tmp_path):
    """submit 链路的内存运行时：独立会话工厂 + 按键索引的仓储 + 假 Celery task。"""
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
    return db, repo, celery_task


_SUBMIT_KWARGS = dict(
    user_id="11111111-1111-1111-1111-111111111111",
    session_id="sess-1",
    language="python",
    code="print(1)",
    timeout_sec=601,
    image="cygnusx-sandbox:bio",
)


@pytest.mark.unit
async def test_submit_studio_long_task_commits_before_celery_dispatch(monkeypatch, tmp_path):
    """契约 a：job 行先落盘（commit）再投递队列；Celery task id == DB task id。"""
    db, repo, celery_task = _submission_runtime(monkeypatch, tmp_path)

    result = await studio_task_service.submit_studio_sandbox_task(**_SUBMIT_KWARGS)

    assert db.commits == 1
    assert len(repo.tasks) == 1
    task = next(iter(repo.tasks.values()))
    assert task.status == TaskStatus.QUEUED
    assert task.flow_id == "studio_sandbox"
    assert task.work_dir.endswith("sess-1")
    assert task.idempotency_key is not None and task.idempotency_key.startswith("studio:")
    assert celery_task.calls[0]["session_id"] == "sess-1"
    assert celery_task.options[0]["task_id"] == str(task.id)  # Celery id == DB id，可对账
    assert result["task_url"].endswith(str(task.id))
    assert result["result_url"] == "/studio/sess-1"
    assert result["deduplicated"] is False


@pytest.mark.unit
async def test_submit_studio_long_task_dispatch_failure_marks_failed(monkeypatch, tmp_path):
    """契约 a 续：投递失败必须留痕——job 标记 failed，不留悬挂 pending。"""
    db, repo, celery_task = _submission_runtime(monkeypatch, tmp_path)

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("broker down")

    celery_task.apply_async = _boom  # type: ignore[method-assign]

    with pytest.raises(ConnectionError):
        await studio_task_service.submit_studio_sandbox_task(**_SUBMIT_KWARGS)

    task = next(iter(repo.tasks.values()))
    assert task.status == TaskStatus.FAILED
    assert task.error_message == "Celery 任务投递失败"
    assert task.finished_at is not None


@pytest.mark.unit
async def test_submit_same_command_id_returns_existing_job(monkeypatch, tmp_path):
    """幂等：同一 command_id 重复提交返回同一 job，不新建行、不重复投递。"""
    db, repo, celery_task = _submission_runtime(monkeypatch, tmp_path)

    first = await studio_task_service.submit_studio_sandbox_task(
        **_SUBMIT_KWARGS, command_id="cmd-e2e-0001"
    )
    second = await studio_task_service.submit_studio_sandbox_task(
        **_SUBMIT_KWARGS, command_id="cmd-e2e-0001"
    )

    assert first["task_id"] == second["task_id"]
    assert second["deduplicated"] is True
    assert len(repo.tasks) == 1
    assert len(celery_task.calls) == 1  # 队列只投了一次


@pytest.mark.unit
async def test_submit_invalid_command_id_rejected(monkeypatch, tmp_path):
    _db, repo, celery_task = _submission_runtime(monkeypatch, tmp_path)
    with pytest.raises(ValidationError):
        await studio_task_service.submit_studio_sandbox_task(
            **_SUBMIT_KWARGS, command_id="x" * 129
        )
    assert len(repo.tasks) == 0 and len(celery_task.calls) == 0


@pytest.mark.unit
async def test_derived_key_terminal_job_bumps_attempt(monkeypatch, tmp_path):
    """派生键命中终态 job 时抬升 attempt 后缀：重跑同内容得到新 job 行。"""
    db, repo, celery_task = _submission_runtime(monkeypatch, tmp_path)

    first = await studio_task_service.submit_studio_sandbox_task(**_SUBMIT_KWARGS)
    first_task = repo.tasks[UUID(first["task_id"])]
    first_task.status = TaskStatus.FAILED  # 模拟终态

    second = await studio_task_service.submit_studio_sandbox_task(**_SUBMIT_KWARGS)

    assert second["task_id"] != first["task_id"]
    assert len(repo.tasks) == 2
    assert second["idempotency_key"].endswith(":a2")
    # 第三次重跑 → :a3
    repo.tasks[UUID(second["task_id"])].status = TaskStatus.SUCCESS
    third = await studio_task_service.submit_studio_sandbox_task(**_SUBMIT_KWARGS)
    assert third["idempotency_key"].endswith(":a3")


@pytest.mark.unit
async def test_retry_terminal_job_refused_with_409(monkeypatch, tmp_path):
    """契约 b：终态不可重开——重试入口对 success/failed/cancelled 返回 409 语义。"""
    db, repo, _celery = _submission_runtime(monkeypatch, tmp_path)
    result = await studio_task_service.submit_studio_sandbox_task(**_SUBMIT_KWARGS)
    task = repo.tasks[UUID(result["task_id"])]

    for terminal in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
        task.status = terminal
        with pytest.raises(ConflictError) as exc_info:
            await studio_task_service.retry_studio_sandbox_task(
                task_id=str(task.id), user_id=_SUBMIT_KWARGS["user_id"]
            )
        assert exc_info.value.status_code == 409
        assert "不可重开" in exc_info.value.detail
        assert terminal.value in exc_info.value.detail


@pytest.mark.unit
async def test_retry_live_job_refused_and_unknown_404(monkeypatch, tmp_path):
    """契约 b 续：存活态重试同样拒绝（409 语义）；非本任务 404。"""
    db, repo, _celery = _submission_runtime(monkeypatch, tmp_path)
    result = await studio_task_service.submit_studio_sandbox_task(**_SUBMIT_KWARGS)
    task = repo.tasks[UUID(result["task_id"])]

    with pytest.raises(ConflictError) as exc_info:
        await studio_task_service.retry_studio_sandbox_task(
            task_id=str(task.id), user_id=_SUBMIT_KWARGS["user_id"]
        )
    assert exc_info.value.status_code == 409
    assert "无需重试" in exc_info.value.detail

    with pytest.raises(NotFoundError):
        await studio_task_service.retry_studio_sandbox_task(
            task_id=str(task.id), user_id="99999999-9999-9999-9999-999999999999"
        )
    with pytest.raises(NotFoundError):
        await studio_task_service.retry_studio_sandbox_task(
            task_id="00000000-0000-0000-0000-000000000000",
            user_id=_SUBMIT_KWARGS["user_id"],
        )


@pytest.mark.unit
async def test_terminal_states_cannot_reopen_in_state_machine():
    """契约 b 的域层兜底：状态机终态出边为空（对齐 OpenAI4S TERMINAL_STATES）。"""
    for terminal in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
        task = _task(terminal)
        assert task.can_transition_to(TaskStatus.PENDING) is False
        assert task.can_transition_to(TaskStatus.QUEUED) is False
        assert task.can_transition_to(TaskStatus.RUNNING) is False


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


class _ModelRef:
    """对账加载器返回的最小模型存根（代码只读 model.id）。"""

    def __init__(self, task_id: UUID) -> None:
        self.id = task_id


def _reconcile_runtime(monkeypatch, *, queued_models: list, running_models: list):
    """对账链路的内存运行时：返回 (db, repo) 供断言。"""
    db = _FakeDb()
    repo = _FakeRepo(_task())

    @asynccontextmanager
    async def session_context():
        yield db

    def session_factory():
        return session_context()

    monkeypatch.setattr(
        "cygnusx.infrastructure.database.session.get_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.database.repositories.task_repository.TaskRepositoryImpl",
        lambda _db: repo,
    )
    async def _fake_queued(_db: Any, _cutoff: Any) -> list:
        return list(queued_models)

    async def _fake_running(_db: Any, _cutoff: Any) -> list:
        return list(running_models)

    monkeypatch.setattr(studio_tasks, "_load_stale_queued_models", _fake_queued)
    monkeypatch.setattr(studio_tasks, "_load_stale_running_models", _fake_running)
    return db, repo


@pytest.mark.unit
async def test_reconcile_marks_lost_queued_job_failed_without_resubmit(monkeypatch):
    """契约 c：DB QUEUED 悬挂 + 队列无消息 + worker 未开始 → 标记 failed，绝不重提交。"""
    task = _task(TaskStatus.QUEUED)
    db, repo = _reconcile_runtime(
        monkeypatch, queued_models=[_ModelRef(task.id)], running_models=[]
    )
    monkeypatch.setattr(studio_tasks, "_celery_backend_state", lambda _tid: "PENDING")
    monkeypatch.setattr(studio_tasks, "_celery_message_in_queue", lambda _tid, queue="analysis": False)

    result = await studio_tasks._reconcile_studio_long_tasks()

    assert result["queued_marked_failed"] == [str(task.id)]
    assert repo.task.status == TaskStatus.FAILED
    assert repo.task.finished_at is not None
    assert "不会自动重提交" in repo.task.error_message
    assert any(log.source == "reconcile" for log in repo.task.logs)
    assert result["errors"] == 0


@pytest.mark.unit
async def test_reconcile_keeps_queued_job_still_in_broker(monkeypatch):
    """契约 c：消息仍在 broker 队列 → 不动状态，仅报告。"""
    task = _task(TaskStatus.QUEUED)
    db, repo = _reconcile_runtime(
        monkeypatch, queued_models=[_ModelRef(task.id)], running_models=[]
    )
    monkeypatch.setattr(studio_tasks, "_celery_backend_state", lambda _tid: "PENDING")
    monkeypatch.setattr(studio_tasks, "_celery_message_in_queue", lambda _tid, queue="analysis": True)

    result = await studio_tasks._reconcile_studio_long_tasks()

    assert result["queued_still_pending"] == [str(task.id)]
    assert result["queued_marked_failed"] == []
    assert repo.task.status == TaskStatus.QUEUED


@pytest.mark.unit
async def test_reconcile_recovers_success_from_backend_meta(monkeypatch):
    """契约 c：worker 已完成但 DB 未回写 → 按 backend 结果恢复终态（不重新执行）。"""
    task = _task(TaskStatus.QUEUED)
    db, repo = _reconcile_runtime(
        monkeypatch, queued_models=[_ModelRef(task.id)], running_models=[]
    )
    monkeypatch.setattr(studio_tasks, "_celery_backend_state", lambda _tid: "SUCCESS")
    monkeypatch.setattr(
        studio_tasks,
        "_celery_backend_result",
        lambda _tid: {"status": "success", "task_id": str(task.id), "exit_code": 0, "stdout": "ok"},
    )

    result = await studio_tasks._reconcile_studio_long_tasks()

    assert result["queued_recovered"] == [str(task.id)]
    assert repo.task.status == TaskStatus.SUCCESS
    assert repo.task.parameters["studio_result"]["exit_code"] == 0
    assert "未重新执行" in repo.task.parameters["reconcile_note"]


@pytest.mark.unit
async def test_reconcile_unknown_backend_state_reports_only(monkeypatch):
    """契约 c：backend 状态无法确认（None）→ 仅报告，不动状态。"""
    task = _task(TaskStatus.QUEUED)
    db, repo = _reconcile_runtime(
        monkeypatch, queued_models=[_ModelRef(task.id)], running_models=[]
    )
    monkeypatch.setattr(studio_tasks, "_celery_backend_state", lambda _tid: None)

    result = await studio_tasks._reconcile_studio_long_tasks()

    assert result["queued_still_pending"] == [str(task.id)]
    assert repo.task.status == TaskStatus.QUEUED


@pytest.mark.unit
async def test_reconcile_stale_running_reported_not_touched(monkeypatch):
    """契约 c：滞留 RUNNING（对应 OpenAI4S unknown=live）→ 只报告，状态不变、不重提交。"""
    task = _task(TaskStatus.RUNNING)
    db, repo = _reconcile_runtime(
        monkeypatch, queued_models=[], running_models=[_ModelRef(task.id)]
    )
    repo.task = task  # 对账加载器只给 id，仓储返回该实体

    result = await studio_tasks._reconcile_studio_long_tasks()

    assert result["running_reported"] == [str(task.id)]
    assert repo.task.status == TaskStatus.RUNNING  # 未被改动
    assert repo.task.finished_at is None
    assert any(log.source == "reconcile" for log in repo.task.logs)
