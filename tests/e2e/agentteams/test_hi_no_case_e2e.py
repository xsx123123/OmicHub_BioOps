"""E2E-7「hi 不建 Case」：新房间输入 "hi" 不得创建 Case（防 08-21 症状回归）。

进程内默认可跑（不进 CI 门控、无需真实服务）：以房间响应主回路
``AgentTeamsRoomResponseService.respond_room`` 为被测链路，Bridge/DB/LLM 用
内存 fake 替身。断言：
1. 无 Case 创建（``create_case`` 未被调用，事件流无 case.created / 立项确认卡）；
2. 无进度条数据（无 route_decision / work_item / planning 类事件）；
3. 只有 Manager 对话回复（恰好一条 room.agent_message）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from omichub.application.services.agent_consultation_service import (
    AgentConsultationService,
    ConsultationEnvelope,
)
from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from omichub.application.services.agentteams_execution_intent import (
    ExecutionIntent,
    classify_execution_intent,
)
from omichub.application.services.agentteams_room_response_service import (
    AgentTeamsRoomResponseService,
)

_STATUS_LINES = {
    key: [key]
    for key in (
        "recruited",
        "queued",
        "running",
        "reviewing",
        "succeeded",
        "failed",
        "awaiting_input",
    )
}


def _manager_agent_config() -> dict:
    return {
        "agent_id": "agentteams-manager",
        "name": "生物信息部门经理",
        "features": {
            "internal_case_role": "bioops-manager",
            "agentteams": {
                "category": "manager",
                "recruitable": False,
                "planner_eligible": True,
                "execution_modes": ["readonly_consultation"],
            },
            "persona": {"status_lines": _STATUS_LINES},
        },
    }


class _FakeAbilityCatalog:
    def all(self) -> dict[str, dict]:
        return {"agentteams-manager": {}}


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def set(self, *args, **kwargs):
        if args and not kwargs.get("nx"):
            self.store[str(args[0])] = args[1] if len(args) > 1 else "1"
        return True

    async def get(self, key):
        return self.store.get(str(key))

    async def eval(self, *args):
        return 1


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_hi_in_new_room_creates_no_case(monkeypatch, tmp_path) -> None:
    # 前置不变式：纯闲聊必须被意图分类判为 CHAT（不触发任何执行/立项分支）。
    assert classify_execution_intent("hi", []) is ExecutionIntent.CHAT

    # 新房间首轮发言：房间命名空间事件流里只有这条 room.user_message。
    events = [
        {
            "event_id": "evt-hi-1",
            "event_type": "room.user_message",
            "payload": {"summary": "hi", "payload": {"actor": "user-e2e", "content": "hi"}},
        }
    ]
    agentteams = SimpleNamespace(
        # 未立项房间的命名空间记录：无 flow_id、received、无 work_items。
        get_case=AsyncMock(
            return_value={"case_id": "room-room-hi", "intent": "", "status": "received"}
        ),
        get_case_events=AsyncMock(return_value={"events": events, "next_cursor": None}),
        post_case_evidence=AsyncMock(return_value={"event_id": "evt-reply"}),
        create_case=AsyncMock(),
        start_chat_planning=AsyncMock(),
    )
    registry = AgentTeamsCapabilityRegistry(
        ability_catalog=_FakeAbilityCatalog(),
        agent_configs=[_manager_agent_config()],
    )
    service = AgentTeamsRoomResponseService(
        SimpleNamespace(),
        agentteams=agentteams,
        registry=registry,
        redis_getter=_FakeRedis,
    )
    run = AsyncMock(
        return_value=ConsultationEnvelope(conclusion="你好！我是生物信息部门经理，有什么可以帮你？")
    )
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    room = SimpleNamespace(case_id=None, room_id="room-hi")
    result = await service.respond_room(room, "user-e2e", "hi")

    # 只有 Manager 对话回复。
    assert result == {"status": "responded"}
    assert run.await_count == 1
    event_types = [
        call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list
    ]
    assert event_types.count("room.agent_message") == 1
    # 无 Case 创建：create_case 未被调用，事件流无 case.created / 立项确认卡。
    agentteams.create_case.assert_not_called()
    agentteams.start_chat_planning.assert_not_called()
    # 无进度条数据：不产生 route_decision / work_item / planning / 追问卡等执行类事件。
    assert set(event_types) <= {"room.typing", "room.agent_message"}
