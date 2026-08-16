"""Matrix 房间镜像钩子与 Case 级证据放行测试。"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from omichub_agentteams_bridge.app import create_app
from omichub_agentteams_bridge.audit import AuditStore
from omichub_agentteams_bridge.config import BridgeSettings
from omichub_agentteams_bridge.room_mirror import AuditRoomMirror
from test_bridge_contract import FixtureOmicHubClient, create_case, headers


class FakeGatewayClient:
    """Loop-neutral Gateway fake：记录镜像调用，可按需失败。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.configured = True
        self.fail = fail
        self.sent: list[dict[str, Any]] = []

    async def aclose(self) -> None:
        return None

    async def post_room_message(
        self,
        room_id: str,
        *,
        sender_identity: str,
        content: str,
        sender: dict[str, Any],
        source: str = "omichub",
    ) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("gateway down")
        self.sent.append(
            {
                "room_id": room_id,
                "sender_identity": sender_identity,
                "content": content,
                "sender": sender,
                "source": source,
            }
        )
        return {"event_id": "$evt:test"}


def _room_binding_event(case_id: str, room_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "actor": "bioops-manager",
        "event_type": "room.created",
        "payload": {"payload": {"room_id": room_id}},
    }


def _user_message_event(case_id: str, content: str = "你好") -> dict[str, Any]:
    return {
        "case_id": case_id,
        "actor": "bioops-manager",
        "event_type": "room.user_message",
        "payload": {"summary": content, "payload": {"actor": "user-1", "content": content}},
    }


async def test_mirror_binds_room_and_mirrors_user_message() -> None:
    gateway = FakeGatewayClient()
    mirror = AuditRoomMirror(gateway)

    mirror.observe(_room_binding_event("bioops_1", "!room:test"))
    assert mirror.room_for("bioops_1") == "!room:test"
    assert gateway.sent == []

    mirror.observe(_user_message_event("bioops_1"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(gateway.sent) == 1
    mirrored = gateway.sent[0]
    assert mirrored["room_id"] == "!room:test"
    assert mirrored["sender_identity"] == "omichub-user-user-1"
    assert mirrored["content"] == "你好"
    assert mirrored["sender"] == {"kind": "user", "name": "user-1"}


async def test_mirror_skips_unbound_cases_and_matrix_events() -> None:
    gateway = FakeGatewayClient()
    mirror = AuditRoomMirror(gateway)

    mirror.observe(_user_message_event("bioops_unknown"))
    mirror.observe(_room_binding_event("bioops_1", "!room:test"))
    mirror.observe({"case_id": "bioops_1", "actor": "bioops-manager", "event_type": "matrix.room.message", "payload": {}})
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert gateway.sent == []


async def test_mirror_agent_event_uses_agent_identity() -> None:
    gateway = FakeGatewayClient()
    mirror = AuditRoomMirror(gateway)
    mirror.observe(_room_binding_event("bioops_1", "!room:test"))

    mirror.observe(
        {
            "case_id": "bioops_1",
            "actor": "agent-rnaseq",
            "event_type": "skill.finished",
            "payload": {"summary": "分析完成"},
        }
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert gateway.sent[0]["sender_identity"] == "agent-rnaseq"
    assert gateway.sent[0]["content"] == "skill.finished: 分析完成"


async def test_mirror_renders_agent_message_as_manager_identity() -> None:
    gateway = FakeGatewayClient()
    mirror = AuditRoomMirror(gateway)
    mirror.observe(_room_binding_event("bioops_1", "!room:test"))

    mirror.observe(
        {
            "case_id": "bioops_1",
            "actor": "bioops-manager",
            "event_type": "room.agent_message",
            "payload": {
                "summary": "质控已通过",
                "payload": {"content": "质控已通过，可以交付。", "agent_id": "agent-general", "role": "bioops-manager"},
            },
        }
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert gateway.sent[0]["sender_identity"] == "bioops-manager"
    assert gateway.sent[0]["content"] == "质控已通过，可以交付。"
    assert gateway.sent[0]["sender"] == {"kind": "agent", "name": "bioops-manager"}


async def test_mirror_gateway_failure_only_logs() -> None:
    gateway = FakeGatewayClient(fail=True)
    mirror = AuditRoomMirror(gateway)
    mirror.observe(_room_binding_event("bioops_1", "!room:test"))

    mirror.observe(_user_message_event("bioops_1"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # 不抛异常即通过


async def test_mirror_skips_typing_and_matrix_origin_events() -> None:
    gateway = FakeGatewayClient()
    mirror = AuditRoomMirror(gateway)
    mirror.observe(_room_binding_event("bioops_1", "!room:test"))

    mirror.observe(
        {
            "case_id": "bioops_1",
            "actor": "bioops-manager",
            "event_type": "room.typing",
            "payload": {"summary": "正在输入", "payload": {"typing": True}},
        }
    )
    mirror.observe(
        {
            "case_id": "bioops_1",
            "actor": "bioops-manager",
            "event_type": "room.user_message",
            "payload": {
                "summary": "来自 Element 的发言",
                "payload": {"actor": "@alice:matrix", "content": "来自 Element 的发言", "via": "matrix"},
            },
        }
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert gateway.sent == []


async def test_mirror_rebinds_rooms_from_audit_history() -> None:
    mirror = AuditRoomMirror(None)
    mirror.rebind([_room_binding_event("bioops_1", "!room:a"), _room_binding_event("bioops_2", "!room:b")])

    assert mirror.room_for("bioops_1") == "!room:a"
    assert mirror.room_for("bioops_2") == "!room:b"
    assert not mirror.enabled


async def test_audit_store_invokes_append_hook(tmp_path) -> None:
    seen: list[dict[str, Any]] = []
    store = AuditStore(str(tmp_path / "audit.jsonl"), on_event=seen.append)

    await store.record(case_id="bioops_1", actor="bioops-manager", event_type="case.created", payload={})

    assert [event["event_type"] for event in seen] == ["case.created"]


@pytest.fixture
def settings(tmp_path):
    return BridgeSettings(
        omichub_base_url="http://omic.test",
        omichub_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities=(
            "approval-authority:approval,bioops-manager:manager,data-steward:steward,"
            "workflow-operator:operator,quality-auditor:auditor,delivery-reporter:reporter"
        ),
        allowed_flow_ids="rna_seq",
        role_agent_map="data-steward:agent-data,quality-auditor:agent-qc",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        manifest_dir=str(tmp_path / "manifests"),
    )


class MirrorASGIClient:
    """与 test_bridge_contract 同款 loop-local 客户端，额外注入 Gateway fake。"""

    def __init__(self, settings: BridgeSettings, gateway: FakeGatewayClient) -> None:
        self._settings = settings
        self._gateway = gateway
        self._calls: list[httpx.Request] = []
        self._clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if loop not in self._clients:
            bridge = create_app(
                self._settings,
                FixtureOmicHubClient(self._settings, self._calls),
                gateway_client=self._gateway,
            )
            self._clients[loop] = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=bridge), base_url="http://bridge.test"
            )
        return self._clients[loop]

    async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._client().get(*args, **kwargs)

    async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._client().post(*args, **kwargs)


@pytest.fixture
def mirror_gateway() -> FakeGatewayClient:
    return FakeGatewayClient()


@pytest.fixture
def mirror_client(settings, mirror_gateway) -> MirrorASGIClient:
    return MirrorASGIClient(settings, mirror_gateway)


async def test_manager_records_case_level_evidence_without_work_item(mirror_client) -> None:
    await create_case(mirror_client, "bioops_room")

    created = await mirror_client.post(
        "/v1/cases/bioops_room/evidence",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "case",
            "event_type": "room.created",
            "summary": "协作房间已创建",
            "payload": {"room_id": "!room:test", "room_url": "http://element.test/#/room/!room:test"},
        },
    )
    assert created.status_code == 201

    events = await mirror_client.get(
        "/v1/cases/bioops_room/events", headers=headers("bioops-manager", "manager")
    )
    event_types = [item["event_type"] for item in events.json()["events"]]
    assert "room.created" in event_types


async def test_non_manager_case_level_evidence_still_requires_work_item(mirror_client) -> None:
    await create_case(mirror_client, "bioops_room")

    denied = await mirror_client.post(
        "/v1/cases/bioops_room/evidence",
        headers=headers("data-steward", "steward"),
        json={
            "work_item_id": "case",
            "event_type": "room.created",
            "summary": "非 manager 不得写 Case 级证据",
            "payload": {"room_id": "!room:test"},
        },
    )
    # _require_case_access 先于 work item 校验：非归属身份一律 403，不会落到 Case 级放行分支。
    assert denied.status_code == 403


async def test_case_events_mirrored_into_bound_room(mirror_client, mirror_gateway) -> None:
    await create_case(mirror_client, "bioops_room")
    bound = await mirror_client.post(
        "/v1/cases/bioops_room/evidence",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "case",
            "event_type": "room.created",
            "summary": "协作房间已创建",
            "payload": {"room_id": "!room:test"},
        },
    )
    assert bound.status_code == 201

    posted = await mirror_client.post(
        "/v1/cases/bioops_room/evidence",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "case",
            "event_type": "room.user_message",
            "summary": "请解释一下质控结果",
            "payload": {"actor": "user-1", "content": "请解释一下质控结果"},
        },
    )
    assert posted.status_code == 201
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(mirror_gateway.sent) == 1
    mirrored = mirror_gateway.sent[0]
    assert mirrored["sender_identity"] == "omichub-user-user-1"
    assert mirrored["content"] == "请解释一下质控结果"


async def test_mirror_failure_does_not_break_evidence_recording(settings, tmp_path) -> None:
    failing_gateway = FakeGatewayClient(fail=True)
    client = MirrorASGIClient(settings, failing_gateway)
    await create_case(client, "bioops_room")
    await client.post(
        "/v1/cases/bioops_room/evidence",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "case",
            "event_type": "room.created",
            "summary": "协作房间已创建",
            "payload": {"room_id": "!room:test"},
        },
    )

    posted = await client.post(
        "/v1/cases/bioops_room/evidence",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "case",
            "event_type": "room.user_message",
            "summary": "Matrix 挂了也要记录",
            "payload": {"actor": "user-1", "content": "Matrix 挂了也要记录"},
        },
    )
    assert posted.status_code == 201
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    events = await client.get(
        "/v1/cases/bioops_room/events", headers=headers("bioops-manager", "manager")
    )
    event_types = [item["event_type"] for item in events.json()["events"]]
    assert "room.user_message" in event_types


def test_matrix_identity_for_requester_mapping() -> None:
    from omichub_agentteams_bridge.room_mirror import matrix_identity_for_requester

    assert matrix_identity_for_requester("user-1") == "omichub-user-user-1"
    assert matrix_identity_for_requester(" 张三@EXAMPLE.com ") == "omichub-user-example.com"
    assert matrix_identity_for_requester("") == "omichub-user"
    assert matrix_identity_for_requester("用户") == "omichub-user"
