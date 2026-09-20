"""Focused tests for the Redis Goal execution lease."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cygnusx.infrastructure.cache.goal_lease import GoalRedisLease, get_goal_lease_key


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        assert nx is True
        assert ex > 0
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, _script: str, _keys: int, key: str, owner: str, *args: str) -> int:
        if self.values.get(key) != owner:
            return 0
        if args:
            return 1
        del self.values[key]
        return 1


@pytest.mark.asyncio
async def test_goal_lease_is_exclusive_and_releases_only_its_owner() -> None:
    redis = FakeRedis()
    goal_id = "goal-1"
    key = get_goal_lease_key(goal_id)

    async with GoalRedisLease(goal_id, "owner-a", 30, redis_getter=lambda: redis) as first:
        assert first.acquired is True
        assert redis.values[key] == "owner-a"
        async with GoalRedisLease(goal_id, "owner-b", 30, redis_getter=lambda: redis) as second:
            assert second.acquired is False
        assert redis.values[key] == "owner-a"

    assert key not in redis.values


@pytest.mark.asyncio
async def test_goal_lease_marks_itself_lost_when_renewal_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    lease = GoalRedisLease("goal-1", "owner-a", 1, redis_getter=lambda: redis)
    lease.acquired = True
    redis.eval = AsyncMock(return_value=0)  # type: ignore[method-assign]

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("cygnusx.infrastructure.cache.goal_lease.asyncio.sleep", no_wait)

    await lease._heartbeat()

    assert lease.lost is True
