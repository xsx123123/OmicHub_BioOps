"""M5 第一刀：Matrix 房间供给接线与用户房间发言测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from omichub.api.v1.agentteams import (
    AgentTeamsCaseCreateRequest,
    AgentTeamsRoomMessageRequest,
    create_case,
    post_case_message,
)
from omichub.application.services.agentteams_service import (
    CASE_LEVEL_WORK_ITEM_ID,
    ROOM_MEMBER_IDENTITIES,
    AgentTeamsService,
)
from omichub.application.services.project_service import ProjectService
from omichub.core.config import Settings
from omichub.core.exceptions import AuthorizationError


@pytest.fixture
def service() -> AgentTeamsService:
    return AgentTeamsService(
        Settings(
            agentteams_bridge_enabled=True,
            agentteams_bridge_url="http://bridge.test",
            agentteams_bridge_manager_token="manager-token",
        )
    )


class FakeRoomGateway:
    def __init__(self, *, available: bool = True, room: dict | None = None, error: Exception | None = None) -> None:
        self._available = available
        self._room = room if room is not None else {"room_id": "!room:test", "element_room_url": "http://element.test/#/room/!room:test"}
        self._error = error
        self.create_calls: list[tuple[str, list[str]]] = []
        self.ensured_calls: list[list[str]] = []

    @property
    def available(self) -> bool:
        return self._available

    async def ensure_users(self, identities: list[str]) -> dict:
        self.ensured_calls.append(list(identities))
        return {"ensured": identities}

    async def create_room(self, session_id: str, identities: list[str]) -> dict:
        self.create_calls.append((session_id, identities))
        if self._error is not None:
            raise self._error
        return self._room


def _install_gateway(monkeypatch: pytest.MonkeyPatch, gateway: FakeRoomGateway) -> None:
    monkeypatch.setattr(
        "omichub.application.services.agentteams_service.AgentTeamsRoomGatewayService",
        lambda: gateway,
    )


@pytest.mark.asyncio
async def test_provision_case_room_creates_room_and_persists_binding(
    service: AgentTeamsService, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeRoomGateway()
    _install_gateway(monkeypatch, gateway)
    evidence = AsyncMock(return_value={"event_id": "evt-1"})
    monkeypatch.setattr(service, "post_case_evidence", evidence)
    bind = AsyncMock()
    monkeypatch.setattr(
        "omichub.application.services.agentteams_room_sync_service.record_room_binding", bind
    )

    room = await service.provision_case_room("bioops_abc", requester_ref="user-a")

    assert room == gateway._room
    assert gateway.create_calls == [("bioops_abc", [*ROOM_MEMBER_IDENTITIES, "omichub-user-user-a"])]
    assert gateway.ensured_calls == [[*ROOM_MEMBER_IDENTITIES, "omichub-user-user-a"]]
    evidence.assert_awaited_once()
    kwargs = evidence.await_args.kwargs
    assert kwargs["work_item_id"] == CASE_LEVEL_WORK_ITEM_ID
    assert kwargs["event_type"] == "room.created"
    assert kwargs["payload"]["room_id"] == "!room:test"
    assert kwargs["payload"]["room_url"] == "http://element.test/#/room/!room:test"
    bind.assert_awaited_once_with("bioops_abc", "!room:test", "user-a")


@pytest.mark.asyncio
async def test_provision_case_room_failure_degrades_without_blocking(
    service: AgentTeamsService, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeRoomGateway(error=RuntimeError("Matrix Gateway 暂时不可用"))
    _install_gateway(monkeypatch, gateway)
    evidence = AsyncMock()
    monkeypatch.setattr(service, "post_case_evidence", evidence)

    room = await service.provision_case_room("bioops_abc")

    assert room is None
    # 建房失败降级为 room.provisioning_failed Case 证据（不阻断创建），供审计流排查。
    evidence.assert_awaited_once()
    kwargs = evidence.await_args.kwargs
    assert kwargs["event_type"] == "room.provisioning_failed"
    assert kwargs["payload"]["reason"] == "gateway_request_failed"


@pytest.mark.asyncio
async def test_provision_case_room_skipped_when_gateway_disabled(
    service: AgentTeamsService, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeRoomGateway(available=False)
    _install_gateway(monkeypatch, gateway)
    evidence = AsyncMock()
    monkeypatch.setattr(service, "post_case_evidence", evidence)

    room = await service.provision_case_room("bioops_abc")

    assert room is None
    assert gateway.create_calls == []
    evidence.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_case_endpoint_provisions_room_after_create(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid4()
    project_id = uuid4()
    request = AgentTeamsCaseCreateRequest(
        project_id=str(project_id),
        intent="bulk_rnaseq_delivery",
        flow_id="approved-flow",
        sample_sheet=[{"sample": "S01"}],
    )
    service = SimpleNamespace(
        create_case=AsyncMock(return_value={"case_id": "bioops_001"}),
        provision_case_room=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(ProjectService, "get_project", AsyncMock())
    monkeypatch.setattr("omichub.api.v1.agentteams._is_chat_case_flow_allowed", lambda _flow: True)
    monkeypatch.setattr(
        "omichub.api.v1.agentteams.get_agentteams_capability_registry",
        lambda: SimpleNamespace(agent_for_flow=lambda _flow: "agent-rnaseq"),
    )

    response = await create_case(request, str(user_id), service, SimpleNamespace())

    assert response == {"case_id": "bioops_001"}
    service.provision_case_room.assert_awaited_once_with(
        "bioops_001", requester_ref=str(user_id)
    )


@pytest.mark.asyncio
async def test_post_room_message_rejects_non_requester(service: AgentTeamsService) -> None:
    service._request = AsyncMock(return_value={"case_id": "bioops_abc", "requester_ref": "user-a"})

    with pytest.raises(AuthorizationError) as excinfo:
        await service.post_room_message("bioops_abc", "user-b", "hello")
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_post_room_message_records_user_message_evidence(service: AgentTeamsService) -> None:
    service._request = AsyncMock(return_value={"case_id": "bioops_abc", "requester_ref": "user-a"})
    evidence = AsyncMock(return_value={"event_id": "evt-9"})
    service.post_case_evidence = evidence

    result = await service.post_room_message("bioops_abc", "user-a", "  请解释一下质控结果  ")

    assert result["event_id"] == "evt-9"
    assert result["dispatch"]["dispatch_mode"] == "manager"
    evidence.assert_awaited_once()
    kwargs = evidence.await_args.kwargs
    assert kwargs["work_item_id"] == CASE_LEVEL_WORK_ITEM_ID
    assert kwargs["event_type"] == "room.user_message"
    assert kwargs["summary"] == "请解释一下质控结果"
    assert kwargs["payload"] == {
        "actor": "user-a",
        "content": "请解释一下质控结果",
        "mentions": [],
        "target_agent_id": None,
        "dispatch_mode": "manager",
    }


@pytest.mark.asyncio
async def test_post_room_message_records_context_refs_in_payload(service: AgentTeamsService) -> None:
    service._request = AsyncMock(return_value={"case_id": "bioops_abc", "requester_ref": "user-a"})
    evidence = AsyncMock(return_value={"event_id": "evt-10"})
    service.post_case_evidence = evidence

    await service.post_room_message(
        "bioops_abc",
        "user-a",
        "看下这个样本表",
        context_refs=[{"kind": "file", "id": "file-1"}],
    )

    payload = evidence.await_args.kwargs["payload"]
    assert payload["context_refs"] == [{"kind": "file", "id": "file-1"}]


@pytest.mark.asyncio
async def test_post_case_message_endpoint_delegates_to_service(monkeypatch: pytest.MonkeyPatch) -> None:
    from omichub.infrastructure.celery_app.tasks.agentteams import respond_to_room_message

    monkeypatch.setattr(respond_to_room_message, "delay", MagicMock())
    service = SimpleNamespace(post_room_message=AsyncMock(return_value={"event_id": "evt-1"}))

    result = await post_case_message(
        "bioops_abc",
        AgentTeamsRoomMessageRequest(content="hello room"),
        "user-a",
        service,
    )

    assert result == {"event_id": "evt-1", "response_dispatch": "queued"}
    service.post_room_message.assert_awaited_once_with(
        "bioops_abc", "user-a", "hello room", context_refs=[], client_message_id=None
    )


@pytest.mark.asyncio
async def test_post_case_message_passes_context_refs_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omichub.infrastructure.celery_app.tasks.agentteams import respond_to_room_message

    monkeypatch.setattr(respond_to_room_message, "delay", MagicMock())
    service = SimpleNamespace(post_room_message=AsyncMock(return_value={"event_id": "evt-2"}))

    result = await post_case_message(
        "bioops_abc",
        AgentTeamsRoomMessageRequest(
            content="看下这个样本表",
            context_refs=[{"kind": "file", "id": "file-1", "location": "demo/samples.csv"}],
        ),
        "user-a",
        service,
    )

    assert result == {"event_id": "evt-2", "response_dispatch": "queued"}
    service.post_room_message.assert_awaited_once_with(
        "bioops_abc",
        "user-a",
        "看下这个样本表",
        context_refs=[{"kind": "file", "id": "file-1", "location": "demo/samples.csv"}],
        client_message_id=None,
    )


@pytest.mark.asyncio
async def test_post_case_message_endpoint_propagates_ownership_403() -> None:
    service = SimpleNamespace(
        post_room_message=AsyncMock(side_effect=AuthorizationError("无权操作该协作案例"))
    )

    with pytest.raises(AuthorizationError) as excinfo:
        await post_case_message(
            "bioops_abc",
            AgentTeamsRoomMessageRequest(content="hello room"),
            "user-b",
            service,
        )
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_post_case_message_dispatches_manager_response_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from omichub.infrastructure.celery_app.tasks.agentteams import respond_to_room_message

    delay = MagicMock()
    monkeypatch.setattr(respond_to_room_message, "delay", delay)
    service = SimpleNamespace(post_room_message=AsyncMock(return_value={"event_id": "evt-1"}))

    result = await post_case_message(
        "bioops_abc",
        AgentTeamsRoomMessageRequest(content="  请汇报进展  "),
        "user-a",
        service,
    )

    assert result == {"event_id": "evt-1", "response_dispatch": "queued"}
    delay.assert_called_once_with("bioops_abc", "user-a", "请汇报进展", None)


@pytest.mark.asyncio
async def test_post_case_message_survives_response_dispatch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omichub.infrastructure.celery_app.tasks.agentteams import respond_to_room_message

    monkeypatch.setattr(
        respond_to_room_message, "delay", MagicMock(side_effect=RuntimeError("broker down"))
    )
    service = SimpleNamespace(post_room_message=AsyncMock(return_value={"event_id": "evt-1"}))

    result = await post_case_message(
        "bioops_abc",
        AgentTeamsRoomMessageRequest(content="hello room"),
        "user-a",
        service,
    )

    assert result == {"event_id": "evt-1", "response_dispatch": "failed"}


class FakeRedis:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.sadd_calls: list[tuple[str, str]] = []

    async def sadd(self, key: str, member: str):
        if self._error is not None:
            raise self._error
        self.sadd_calls.append((key, member))
        return 1


@pytest.mark.asyncio
async def test_create_case_chat_style_injects_workspace_without_auto_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    request = AgentTeamsCaseCreateRequest(intent="分析这两组样本的差异")
    service = SimpleNamespace(
        create_case=AsyncMock(return_value={"case_id": "bioops_chat"}),
        provision_case_room=AsyncMock(return_value=None),
    )
    redis = FakeRedis()
    monkeypatch.setattr("omichub.api.v1.agentteams.get_redis", lambda: redis)

    response = await create_case(request, str(user_id), service, SimpleNamespace())

    assert response == {"case_id": "bioops_chat"}
    kwargs = service.create_case.await_args.kwargs
    assert kwargs["context_refs"] == [{"kind": "workspace", "id": str(user_id)}]
    # 聊天式 Case 改为房间内人工确认，不再写入自动确认集合
    assert redis.sadd_calls == []


@pytest.mark.asyncio
async def test_create_case_flow_case_skips_injection_and_auto_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    project_id = uuid4()
    request = AgentTeamsCaseCreateRequest(
        project_id=str(project_id),
        intent="bulk_rnaseq_delivery",
        flow_id="approved-flow",
        sample_sheet=[{"sample": "S01"}],
    )
    service = SimpleNamespace(
        create_case=AsyncMock(return_value={"case_id": "bioops_flow"}),
        provision_case_room=AsyncMock(return_value=None),
    )
    redis = FakeRedis()
    monkeypatch.setattr("omichub.api.v1.agentteams.get_redis", lambda: redis)
    monkeypatch.setattr(ProjectService, "get_project", AsyncMock())
    monkeypatch.setattr("omichub.api.v1.agentteams._is_chat_case_flow_allowed", lambda _flow: True)
    monkeypatch.setattr(
        "omichub.api.v1.agentteams.get_agentteams_capability_registry",
        lambda: SimpleNamespace(agent_for_flow=lambda _flow: "agent-rnaseq"),
    )

    await create_case(request, str(user_id), service, SimpleNamespace())

    kwargs = service.create_case.await_args.kwargs
    assert kwargs["context_refs"] == []
    assert redis.sadd_calls == []


@pytest.mark.asyncio
async def test_create_case_general_case_keeps_explicit_context_without_auto_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    request = AgentTeamsCaseCreateRequest(
        intent="整理工作区里的质控报告",
        context_refs=[{"kind": "file", "id": "file-1"}],
    )
    service = SimpleNamespace(
        create_case=AsyncMock(return_value={"case_id": "bioops_gen"}),
        provision_case_room=AsyncMock(return_value=None),
    )
    redis = FakeRedis()
    monkeypatch.setattr("omichub.api.v1.agentteams.get_redis", lambda: redis)

    await create_case(request, str(user_id), service, SimpleNamespace())

    kwargs = service.create_case.await_args.kwargs
    assert kwargs["context_refs"] == [{"kind": "file", "id": "file-1"}]
    # 通用 Case 同样走人工确认，不写入自动确认集合
    assert redis.sadd_calls == []


@pytest.mark.asyncio
async def test_create_case_chat_style_survives_redis_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    request = AgentTeamsCaseCreateRequest(intent="分析这两组样本的差异")
    service = SimpleNamespace(
        create_case=AsyncMock(return_value={"case_id": "bioops_chat"}),
        provision_case_room=AsyncMock(return_value=None),
    )
    redis = FakeRedis(error=RuntimeError("redis down"))
    monkeypatch.setattr("omichub.api.v1.agentteams.get_redis", lambda: redis)

    response = await create_case(request, str(user_id), service, SimpleNamespace())

    assert response == {"case_id": "bioops_chat"}


def test_chat_style_request_validator_allows_empty_general_context() -> None:
    request = AgentTeamsCaseCreateRequest(intent="随便问问")
    assert request.context_refs == []

    with pytest.raises(ValidationError):
        AgentTeamsCaseCreateRequest(intent="x", flow_id="rna_seq")
