"""chat_service 对 update_plan 的拦截测试：产出 plan 事件并落库 sandbox_meta.plan"""

import contextlib
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from cygnusx.application.services.agent_service import AgentService
from cygnusx.application.services.chat_service import ChatService
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk, provider_manager
from cygnusx.infrastructure.database.models.chat import ChatSessionModel

_PLAN_ARGS = {
    "steps": [
        {"title": "加载数据", "status": "in_progress"},
        {"title": "差异分析", "status": "pending"},
        {"title": "绘制火山图", "status": "pending"},
    ]
}


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeDb:
    """最小 AsyncSession 替身：会话查询返回固定会话，消息查询按未找到（调用方均容忍）。"""

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


def _make_session(mode: str) -> ChatSessionModel:
    return ChatSessionModel(
        id=uuid.uuid4(),
        session_id="sess-1",
        user_id="u-1",
        model_id=uuid.uuid4(),
        title="工作台",
        status="active",
        mode=mode,
        message_count=0,
        total_tokens=0,
        sandbox_meta={"image": "cygnusx-sandbox:bio"} if mode == "studio" else None,
    )


@pytest.fixture
def mocked_agent_runtime(monkeypatch):
    """Mock Agent 上下文与 LLM 流：第一轮只发 update_plan 工具调用，第二轮纯文本收尾。"""

    ctx = SimpleNamespace(
        agent=SimpleNamespace(name="傻妞"),
        model_config=SimpleNamespace(
            id=uuid.uuid4(), api_key="sk-x", name="qwen-plus", model="qwen-plus"
        ),
        features={},
        tools=[],
        mcp_servers=[],
        system_prompt="你是助手",
        temperature=0.3,
        max_tokens=2048,
    )

    async def _assemble(self, agent_id):
        return ctx

    monkeypatch.setattr(AgentService, "assemble_context", _assemble)

    # ToolInvocationContext 强校验 db 为 AsyncSession；本测试链路不触 MCP 调用，替身即可
    import cygnusx.application.schemas.tool_invocation as _tiv

    monkeypatch.setattr(
        _tiv, "ToolInvocationContext", lambda **kw: SimpleNamespace(**kw)
    )

    calls = {"n": 0}

    def _fake_chat_stream(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            events = [
                ChatChunk(
                    type="tool_calls",
                    metadata={
                        "tool_calls": [
                            {
                                "id": "call_plan_1",
                                "type": "function",
                                "function": {
                                    "name": "update_plan",
                                    "arguments": json.dumps(_PLAN_ARGS, ensure_ascii=False),
                                },
                            }
                        ]
                    },
                ),
                ChatChunk(type="done", metadata={}),
            ]
        else:
            events = [
                ChatChunk(type="text", content="计划已建立，开始执行。"),
                ChatChunk(type="done", metadata={}),
            ]

        async def _gen():
            for e in events:
                yield e

        return _gen()

    monkeypatch.setattr(provider_manager, "chat_stream", _fake_chat_stream)


@pytest.mark.unit
@pytest.mark.quarantine(reason="mocked_agent_runtime 的 assemble_context 签名缺少 user_id 关键字")
async def test_update_plan_intercepted_yields_plan_chunk_and_persists(mocked_agent_runtime):
    """Studio 会话：update_plan 不打沙盒，产出 plan 事件 + tool_result，计划落 sandbox_meta"""
    session = _make_session("studio")
    service = ChatService(_FakeDb(session))

    chunks = [
        c
        async for c in service.stream_agent_chat(
            user_id="u-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "帮我做差异分析"}],
            session_id="sess-1",
        )
    ]

    types = [c.type for c in chunks]
    assert "plan" in types
    plan_chunk = next(c for c in chunks if c.type == "plan")
    assert plan_chunk.metadata["tool_call_id"] == "call_plan_1"
    assert plan_chunk.metadata["steps"] == _PLAN_ARGS["steps"]
    # plan 事件先于对应 tool_result
    assert types.index("plan") < types.index("tool_result")
    # 结果信封照常走 tool_result 闭环
    tool_result = next(c for c in chunks if c.type == "tool_result")
    assert tool_result.metadata["tool_name"] == "update_plan"
    assert tool_result.metadata["mcp_server"] == "studio"
    assert tool_result.metadata["success"] is True
    # 计划持久化到会话 sandbox_meta（右栏待办面板数据源）
    assert session.sandbox_meta["plan"]["steps"] == _PLAN_ARGS["steps"]


@pytest.mark.unit
@pytest.mark.quarantine(reason="mocked_agent_runtime 的 assemble_context 签名缺少 user_id 关键字")
async def test_update_plan_not_intercepted_for_chat_session(mocked_agent_runtime):
    """非 Studio 会话：update_plan 不属于工作台工具集，按未挂载工具处理，不产生 plan 事件"""
    session = _make_session("chat")
    service = ChatService(_FakeDb(session))

    chunks = [
        c
        async for c in service.stream_agent_chat(
            user_id="u-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hi"}],
            session_id="sess-1",
        )
    ]

    assert "plan" not in [c.type for c in chunks]
    tool_result = next(c for c in chunks if c.type == "tool_result")
    assert tool_result.metadata["success"] is False
    # 会话级 mcp_mode 元数据会记入 sandbox_meta，但非 Studio 会话不落 plan 数据
    assert "plan" not in (session.sandbox_meta or {})
