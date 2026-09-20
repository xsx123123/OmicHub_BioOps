import json

import pytest

from cygnusx.application.services import studio_approval_service as module
from cygnusx.application.services.studio_approval_service import StudioApprovalService


@pytest.mark.asyncio
async def test_resolve_uses_single_atomic_redis_script(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeRedis:
        async def eval(self, *args: object) -> str:
            calls.append(args)
            return json.dumps({"approval_id": "approval-1", "user_id": "user-1", "status": "approved"})

    monkeypatch.setattr(module, "get_redis", lambda: FakeRedis())

    result = await StudioApprovalService().resolve(
        "approval-1", "user-1", "approved", modified_args={"path": "output/a.png"}
    )

    assert result is not None
    assert result["status"] == "approved"
    assert len(calls) == 1
    script, key_count, record_key, result_key, user_id, action, payload, reason, ttl = calls[0]
    assert "RPUSH" in str(script)
    assert key_count == 2
    assert str(record_key).endswith("approval-1")
    assert str(result_key).endswith("approval-1")
    assert user_id == "user-1"
    assert action == "approved"
    assert json.loads(str(payload)) == {"action": "approved", "modified_args": {"path": "output/a.png"}}
    assert reason == ""
    assert ttl == "300"


@pytest.mark.asyncio
async def test_resolve_returns_none_when_atomic_guard_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRedis:
        async def eval(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(module, "get_redis", lambda: FakeRedis())

    assert await StudioApprovalService().resolve("approval-1", "user-1", "rejected") is None
