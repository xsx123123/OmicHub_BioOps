"""Case watch Celery task failure isolation."""

from __future__ import annotations

import pytest

import cygnusx.infrastructure.celery_app.tasks.agentteams as task_module


class FakeRedis:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.set_calls: list[tuple[object, ...]] = []
        self.release_calls: list[tuple[object, ...]] = []

    async def set(self, *args, **kwargs):
        self.set_calls.append((*args, kwargs))
        return self.acquired

    async def eval(self, *args):
        self.release_calls.append(args)
        return 1


@pytest.mark.asyncio
async def test_watch_task_returns_failed_status_when_scan_raises(monkeypatch) -> None:
    class FailingSession:
        async def __aenter__(self):
            raise RuntimeError("database unavailable")

        async def __aexit__(self, *_args):
            return False

    redis = FakeRedis()
    result = await task_module._watch_cases_with_factory(
        lambda: lambda: FailingSession(), object, redis_getter=lambda: redis
    )

    assert result == {"status": "failed"}
    assert len(redis.release_calls) == 1


@pytest.mark.asyncio
async def test_watch_task_skips_when_another_worker_holds_lock() -> None:
    redis = FakeRedis(acquired=False)
    session_factory_called = False

    def session_factory():
        nonlocal session_factory_called
        session_factory_called = True
        raise AssertionError("locked watch must not open a database session")

    result = await task_module._watch_cases_with_factory(
        session_factory, object, redis_getter=lambda: redis
    )

    assert result == {"status": "skipped_locked"}
    assert session_factory_called is False
    assert redis.release_calls == []


@pytest.mark.asyncio
async def test_event_consumer_runs_bound_cases_and_releases_lock(monkeypatch) -> None:
    session = type(
        "BoundSession",
        (),
        {
            "session_id": "session-1",
            "sandbox_meta": {
                "agentteams_case_ids": ["case-1", "case-closed"],
                "agentteams_case_status": {"case-1": "executing", "case-closed": "closed"},
            },
        },
    )()

    class DiscoverySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def scalars(self, _query):
            return type("Rows", (), {"all": lambda self: [session]})()

    class ConsumerSession:
        committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def commit(self):
            self.committed = True

    consumer_session = ConsumerSession()
    sessions = iter([DiscoverySession(), consumer_session])

    class Consumer:
        def __init__(self, db):
            assert db is consumer_session

        async def consume(self, session_id, case_id, *, watch_seconds):
            assert (session_id, case_id, watch_seconds) == ("session-1", "case-1", 2)
            return {"events": 2, "projected": 3, "skipped": 0}

    redis = FakeRedis()
    result = await task_module._consume_case_events_with_factory(
        lambda: lambda: next(sessions),
        Consumer,
        redis_getter=lambda: redis,
        stream_seconds=2,
    )

    assert result == {"bindings": 1, "events": 2, "projected": 3, "failed": 0}
    assert consumer_session.committed is True
    assert len(redis.release_calls) == 1


@pytest.mark.asyncio
async def test_stale_task_watch_runs_service_and_releases_lock(monkeypatch) -> None:
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Service:
        def __init__(self, _session):
            pass

        async def scan(self, *, stale_after_seconds):
            assert stale_after_seconds == 600
            return {"scanned": 1, "requeued": 1, "failed": 0, "skipped": 0}

    monkeypatch.setattr(
        task_module,
        "get_settings",
        lambda: type("Settings", (), {"agentteams_stale_task_seconds": 600})(),
    )
    redis = FakeRedis()
    result = await task_module._requeue_stale_tasks_with_factory(
        lambda: lambda: Session(), Service, redis_getter=lambda: redis
    )

    assert result["requeued"] == 1
    assert len(redis.release_calls) == 1


class FakeAutoConfirmRedis(FakeRedis):
    def __init__(self, marked=(), acquired: bool = True) -> None:
        super().__init__(acquired=acquired)
        self.marked = set(marked)
        self.srem_calls: list[str] = []

    async def smembers(self, _key):
        return set(self.marked)

    async def srem(self, _key, member):
        self.srem_calls.append(member)
        self.marked.discard(member)
        return 1


class _FakeAutoConfirmService:
    def __init__(self, pending=(), details=None, fail_on=(), available: bool = True) -> None:
        self.available = available
        self._pending = list(pending)
        self._details = dict(details or {})
        self._fail_on = set(fail_on)
        self.approve_calls: list[tuple[str, str, str]] = []

    async def admin_list_cases_by_status(self, case_status, *, limit=100):
        assert case_status == "approval_pending"
        return self._pending

    async def admin_get_case(self, case_id):
        return self._details[case_id]

    async def approve_and_submit_task(self, *, case_id, requester_ref, task_name):
        self.approve_calls.append((case_id, requester_ref, task_name))
        if case_id in self._fail_on:
            raise RuntimeError("bridge approval error")
        return {"ok": True}

    async def auto_approve_case_if_autonomous(
        self, case_id, requester_ref, *, db=None, task_name="auto-approved"
    ):
        # 模拟 autonomous 偏好：所有传入的 Case 均视为已授权自动批准。
        result = await self.approve_and_submit_task(
            case_id=case_id, requester_ref=requester_ref, task_name=task_name
        )
        return {"status": "auto_approved", "case_id": case_id, "result": result}


class _NoopSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def _install_fake_service(monkeypatch, service) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_bridge_settings_service.AgentTeamsBridgeSettingsService",
        lambda *_a, **_k: SimpleNamespace(get_runtime_config=AsyncMock(return_value=None)),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_service.AgentTeamsService",
        lambda *_a, **_k: service,
    )


@pytest.mark.asyncio
async def test_auto_confirm_skips_when_another_worker_holds_lock() -> None:
    redis = FakeAutoConfirmRedis(marked={"case-1"}, acquired=False)

    result = await task_module._auto_confirm_cases_with_factory(
        lambda: lambda: _NoopSession(), redis_getter=lambda: redis
    )

    assert result == {"status": "skipped_locked"}
    assert redis.release_calls == []


@pytest.mark.asyncio
async def test_auto_confirm_noop_when_marked_set_is_empty(monkeypatch) -> None:
    redis = FakeAutoConfirmRedis()

    result = await task_module._auto_confirm_cases_with_factory(
        lambda: lambda: _NoopSession(), redis_getter=lambda: redis
    )

    assert result == {"status": "ok", "marked": 0, "confirmed": 0, "skipped": 0, "failed": 0}
    assert len(redis.release_calls) == 1


@pytest.mark.asyncio
async def test_auto_confirm_confirms_only_general_pending_cases(monkeypatch) -> None:
    service = _FakeAutoConfirmService(
        pending=[
            {"case_id": "case-general", "requester_ref": "user-a", "flow_id": None},
            {"case_id": "case-flow", "requester_ref": "user-b", "flow_id": "rna_seq"},
            {"case_id": "case-fail", "requester_ref": "user-c", "flow_id": None},
        ],
        details={
            "case-planning": {"status": "planning_running"},
            "case-closed": {"status": "closed"},
        },
        fail_on={"case-fail"},
    )
    _install_fake_service(monkeypatch, service)
    redis = FakeAutoConfirmRedis(
        marked={"case-general", "case-flow", "case-fail", "case-planning", "case-closed"}
    )

    result = await task_module._auto_confirm_cases_with_factory(
        lambda: lambda: _NoopSession(), redis_getter=lambda: redis
    )

    assert result == {"status": "ok", "marked": 5, "confirmed": 2, "skipped": 1, "failed": 1}
    # 通用与流程 Case 均进入自动确认（失败隔离不影响其他 Case），以 Case 自身 requester_ref 走既有审批链路
    assert service.approve_calls == [
        ("case-fail", "user-c", "auto-ase-fail"),
        ("case-flow", "user-b", "auto-ase-flow"),
        ("case-general", "user-a", "auto--general"),
    ]
    # 已确认 / 终态 → 清理标记；前置状态保留标记等待下一轮
    assert sorted(redis.srem_calls) == ["case-closed", "case-flow", "case-general"]
    assert redis.marked == {"case-fail", "case-planning"}
    assert len(redis.release_calls) == 1


@pytest.mark.asyncio
async def test_auto_confirm_skips_when_bridge_unavailable(monkeypatch) -> None:
    service = _FakeAutoConfirmService(available=False)
    _install_fake_service(monkeypatch, service)
    redis = FakeAutoConfirmRedis(marked={"case-1"})

    result = await task_module._auto_confirm_cases_with_factory(
        lambda: lambda: _NoopSession(), redis_getter=lambda: redis
    )

    assert result == {"status": "skipped_unavailable"}
    assert redis.marked == {"case-1"}
    assert len(redis.release_calls) == 1
