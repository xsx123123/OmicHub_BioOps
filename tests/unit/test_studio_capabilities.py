"""Studio MCP/Skill 渐进式披露与会话边界测试。"""

import contextlib
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from omichub.application.services.agent_service import AgentService
from omichub.application.services.chat_service import ChatService
from omichub.application.services.studio_capabilities import (
    CAPABILITY_LOAD_TOOL,
    CAPABILITY_TOOL_NAMES,
    CAPABILITY_TOOL_SCHEMAS,
    CapabilityState,
    catalog,
    load_capability,
    normalize_state,
    render_prompt,
)
from omichub.domain.mcp.entities import MCPServer, MCPToolRegistry
from omichub.domain.mcp.value_objects import ServerStatus, Transport
from omichub.domain.skill.entities import Skill
from omichub.infrastructure.ai_provider.openai_compatible import ChatChunk, provider_manager
from omichub.infrastructure.database.models.chat import ChatSessionModel


def _skill(skill_id: str = "rna-quality") -> Skill:
    return Skill(
        id=uuid.uuid4(),
        skill_id=skill_id,
        name="RNA 质控",
        description="检查 RNA-seq 质控结果",
        prompt="SECRET_SKILL_INSTRUCTIONS",
        category="rna",
        is_active=True,
    )


def _server(
    *,
    name: str = "literature",
    tool_name: str = "search_papers",
    status: ServerStatus = ServerStatus.ONLINE,
) -> MCPServer:
    server_id = uuid.uuid4()
    return MCPServer(
        id=server_id,
        name=name,
        description="文献检索服务",
        transport=Transport.BUILTIN,
        status=status,
        is_enabled=True,
        env={"SECRET": "must-not-leak"},
        command="secret-command",
        tools=[
            MCPToolRegistry(
                tool_name=tool_name,
                description="检索文献",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                server_id=server_id,
            )
        ],
    )


@pytest.mark.unit
def test_catalog_exposes_metadata_only_and_prompt_is_loaded_on_demand():
    skill = _skill()
    server = _server()
    state = normalize_state({}, [skill], [server])

    visible = catalog([skill], [server], state)
    prompt = render_prompt("BASE_PROMPT", [skill], [server], state)

    assert visible["skills"][0]["capability_id"] == skill.skill_id
    assert "prompt" not in visible["skills"][0]
    assert "env" not in visible["mcp"][0]
    assert "command" not in visible["mcp"][0]
    assert "SECRET_SKILL_INSTRUCTIONS" not in prompt
    assert skill.description in prompt

    loaded, result = load_capability(
        "skill", skill.skill_id, [skill], [server], state, set()
    )
    assert result["success"] is True
    assert loaded is not None
    assert "SECRET_SKILL_INSTRUCTIONS" in render_prompt(
        "BASE_PROMPT", [skill], [server], loaded
    )


@pytest.mark.unit
def test_state_prunes_capabilities_not_bound_to_current_agent():
    skill = _skill("allowed-skill")
    server = _server()
    state = normalize_state(
        {
            "loaded_skill_ids": ["allowed-skill", "foreign-skill"],
            "loaded_mcp_ids": [str(server.id), str(uuid.uuid4())],
            "audit": [{"action": "load"}],
        },
        [skill],
        [server],
    )

    assert state.loaded_skill_ids == ("allowed-skill",)
    assert state.loaded_mcp_ids == (str(server.id),)
    assert state.audit == ({"action": "load"},)


@pytest.mark.unit
def test_loading_rejects_unbound_unavailable_and_conflicting_capabilities():
    skill = _skill()
    server = _server()
    offline = _server(name="offline", status=ServerStatus.OFFLINE)
    state = CapabilityState()

    loaded, result = load_capability(
        "skill", "foreign-skill", [skill], [server], state, set()
    )
    assert loaded is None
    assert result["success"] is False

    loaded, result = load_capability(
        "mcp", str(offline.id), [skill], [offline], state, set()
    )
    assert loaded is None
    assert "不可用" in result["error"]

    loaded, result = load_capability(
        "mcp", str(server.id), [skill], [server], state, {"search_papers"}
    )
    assert loaded is None
    assert "冲突" in result["error"]


@pytest.mark.unit
def test_capability_audit_is_bounded_to_latest_hundred_events():
    skill = _skill()
    state = normalize_state(
        {"audit": [{"sequence": index} for index in range(130)]},
        [skill],
        [],
    )

    assert len(state.audit) == 100
    assert state.audit[0]["sequence"] == 30
    assert state.audit[-1]["sequence"] == 129


@pytest.mark.unit
def test_capability_tool_schemas_are_minimal_and_stable():
    assert {item["function"]["name"] for item in CAPABILITY_TOOL_SCHEMAS} == set(
        CAPABILITY_TOOL_NAMES
    )
    load_schema = next(
        item for item in CAPABILITY_TOOL_SCHEMAS if item["function"]["name"] == CAPABILITY_LOAD_TOOL
    )
    assert load_schema["function"]["parameters"]["required"] == ["kind", "id"]


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeDb:
    def __init__(self, session: ChatSessionModel) -> None:
        self.session = session
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def execute(self, stmt: Any) -> _FakeResult:
        entity = None
        with contextlib.suppress(Exception):
            entity = stmt.column_descriptions[0].get("entity")
        if entity is ChatSessionModel:
            return _FakeResult(self.session)
        return _FakeResult(None)


@pytest.mark.unit
async def test_chat_loads_skill_and_mcp_only_after_capability_tool(monkeypatch):
    skill = _skill()
    server = _server()
    session = ChatSessionModel(
        id=uuid.uuid4(),
        session_id="sess-capabilities",
        user_id="u-1",
        model_id=uuid.uuid4(),
        title="工作台",
        status="active",
        mode="studio",
        message_count=0,
        total_tokens=0,
        sandbox_meta={"image": "omichub-sandbox:bio"},
    )
    ctx = SimpleNamespace(
        agent=SimpleNamespace(name="分析助手", system_prompt="BASE_PROMPT"),
        model_config=SimpleNamespace(
            id=session.model_id, api_key="sk-x", name="test-model", model="test-model"
        ),
        features={},
        tools=[
            {
                "type": "function",
                "function": {"name": "search_papers", "parameters": {"type": "object"}},
            }
        ],
        mcp_servers=[server],
        skills=[skill],
        system_prompt="BASE_PROMPT\n\nSECRET_SKILL_INSTRUCTIONS",
        temperature=0.3,
        max_tokens=2048,
    )

    async def _assemble(self, agent_id):
        return ctx

    monkeypatch.setattr(AgentService, "assemble_context", _assemble)

    import omichub.application.schemas.tool_invocation as invocation_module

    monkeypatch.setattr(
        invocation_module, "ToolInvocationContext", lambda **kwargs: SimpleNamespace(**kwargs)
    )

    calls: list[dict[str, Any]] = []

    def _fake_chat_stream(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            tool_names = {item["function"]["name"] for item in kwargs["tools"]}
            assert "search_papers" not in tool_names
            assert CAPABILITY_LOAD_TOOL in tool_names
            assert "SECRET_SKILL_INSTRUCTIONS" not in kwargs["system_prompt"]
            events = [
                ChatChunk(
                    type="tool_calls",
                    metadata={
                        "tool_calls": [
                            {
                                "id": "load-skill",
                                "type": "function",
                                "function": {
                                    "name": CAPABILITY_LOAD_TOOL,
                                    "arguments": json.dumps(
                                        {"kind": "skill", "id": skill.skill_id}
                                    ),
                                },
                            },
                            {
                                "id": "load-mcp",
                                "type": "function",
                                "function": {
                                    "name": CAPABILITY_LOAD_TOOL,
                                    "arguments": json.dumps(
                                        {"kind": "mcp", "id": str(server.id)}
                                    ),
                                },
                            },
                        ]
                    },
                ),
                ChatChunk(type="done", metadata={}),
            ]
        else:
            tool_names = {item["function"]["name"] for item in kwargs["tools"]}
            assert "search_papers" in tool_names
            assert "SECRET_SKILL_INSTRUCTIONS" in kwargs["system_prompt"]
            events = [
                ChatChunk(type="text", content="能力已按需加载。"),
                ChatChunk(type="done", metadata={}),
            ]

        async def _gen():
            for event in events:
                yield event

        return _gen()

    monkeypatch.setattr(provider_manager, "chat_stream", _fake_chat_stream)

    chunks = [
        chunk
        async for chunk in ChatService(_FakeDb(session)).stream_agent_chat(
            user_id="u-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "加载需要的能力"}],
            session_id=session.session_id,
        )
    ]

    assert any(chunk.type == "done" for chunk in chunks)
    capabilities = session.sandbox_meta["capabilities"]
    assert capabilities["loaded_skill_ids"] == [skill.skill_id]
    assert capabilities["loaded_mcp_ids"] == [str(server.id)]
    assert len(capabilities["audit"]) == 2
    assert all(event["success"] for event in capabilities["audit"])


@pytest.mark.unit
async def test_existing_studio_session_rejects_different_agent(monkeypatch):
    session = ChatSessionModel(
        id=uuid.uuid4(),
        session_id="sess-bound-agent",
        user_id="u-1",
        model_id=uuid.uuid4(),
        agent_id="agent-a",
        title="工作台",
        status="active",
        mode="studio",
        message_count=0,
        total_tokens=0,
        sandbox_meta={},
    )
    ctx = SimpleNamespace(
        agent=SimpleNamespace(name="另一个助手", system_prompt="BASE"),
        model_config=SimpleNamespace(
            id=session.model_id, api_key="sk-x", name="test-model", model="test-model"
        ),
        features={},
        tools=[],
        mcp_servers=[],
        skills=[],
        system_prompt="BASE",
        temperature=0.3,
        max_tokens=1024,
    )

    async def _assemble(self, agent_id):
        return ctx

    monkeypatch.setattr(AgentService, "assemble_context", _assemble)
    called = False

    def _unexpected_chat_stream(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider should not be called")

    monkeypatch.setattr(provider_manager, "chat_stream", _unexpected_chat_stream)

    chunks = [
        chunk
        async for chunk in ChatService(_FakeDb(session)).stream_agent_chat(
            user_id="u-1",
            agent_id="agent-b",
            messages=[{"role": "user", "content": "继续"}],
            session_id=session.session_id,
        )
    ]

    assert called is False
    assert len(chunks) == 1
    assert chunks[0].type == "error"
    assert "Agent" in chunks[0].content
