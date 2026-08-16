"""Recovery scheduling tests for interrupted Goal workers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call
from uuid import uuid4

import pytest

from omichub.infrastructure.celery_app.tasks.goals import _recover_expired_goal_leases


@pytest.mark.asyncio
async def test_recovery_requeues_each_expired_goal(monkeypatch: pytest.MonkeyPatch) -> None:
    goal_ids = [uuid4(), uuid4()]
    engine = Mock()

    async def recover_expired_leases() -> list:
        return goal_ids

    engine.recover_expired_leases = recover_expired_leases
    enqueue = Mock()
    monkeypatch.setattr(
        "omichub.infrastructure.celery_app.tasks.goals.get_settings",
        lambda: SimpleNamespace(goal_runtime_enabled=True),
    )

    result = await _recover_expired_goal_leases(engine=engine, enqueue=enqueue)

    assert result == {"status": "recovered", "recovered": 2}
    assert enqueue.call_args_list == [
        call(args=[str(goal_ids[0]), "lease_recovered"]),
        call(args=[str(goal_ids[1]), "lease_recovered"]),
    ]
