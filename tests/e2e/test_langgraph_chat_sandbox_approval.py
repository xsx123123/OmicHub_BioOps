"""LangGraph 路径 chat_sandbox_execute 审批闸 e2e（真实 Redis + 真实 LangGraph 图 + 本地 Postgres 审计）。

验证层次：
- 真实 LangGraphRuntimeService 状态图执行（llm_call → tool_exec → llm_call 回灌）；
- 真实 StudioApprovalService（Redis SETEX/BLPOP/Lua 原子决议），本测试扮演 REST
  端点调用 resolve() 写入决议，等价于 api/v1/studio.py 的审批消费路径；
- 真实 record_approval_audit 落 audit_logs（timeout 决议由聊天流落库，与 legacy 一致；
  approve/reject 的落库在 REST 端点，本测试按其调用方式补落以便校验 DB 链路）；
- execute_chat_sandbox 以 stub 替换（避免依赖 docker 沙盒池；另一 Agent 正在并行
  修改 sandbox/pool.py），审批闸本身是被测真代码。

前置：本地 Redis（.env 的 REDIS_HOST 默认指向容器名，本文件探测时回退 127.0.0.1）
与本地 Postgres（开发库默认值，可用 E2E_DATABASE_URL 覆盖）。不可用时自动 skip。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import asyncpg
import pytest

import cygnusx.application.services.chat.runtimes.langgraph_runtime as lg_module
from cygnusx.application.services.chat.runtimes.langgraph_runtime import LangGraphChatRuntime
from cygnusx.application.services.studio_approval_service import (
    APPROVAL_TTL_SECONDS,
    StudioApprovalService,
    record_approval_audit,
)
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

_DEV_DATABASE_URL = (
    "postgresql+asyncpg://omichub:omichub_dev_password@127.0.0.1:5432/omichub"
)


def _probe(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _redis_host() -> str:
    if _probe(os.environ.get("REDIS_HOST", "cache"), 6379):
        return os.environ.get("REDIS_HOST", "cache")
    return "127.0.0.1" if _probe("127.0.0.1", 6379) else ""


_REDIS_HOST = _redis_host()
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _REDIS_HOST, reason="需要本地 Redis（6379）"),
]

USER_ID = "e2e-user-langgraph-approval"
SESSION_ID = "e2e-session-langgraph-approval"


@pytest.fixture(autouse=True)
async def _dispose_db_engine_between_tests() -> Any:
    """每个用例独立事件循环：引擎单例的连接绑定旧 loop 会失效，用例间 dispose。"""
    yield
    from cygnusx.infrastructure.database import session as db_session

    await db_session.close_db()


class _Service:
    """LangGraphChatRuntime 所需的最小 ChatService 面。"""

    def __init__(self, sandbox_meta: dict[str, Any] | None) -> None:
        self.update_message_content = AsyncMock()
        self._apply_usage_to_session = AsyncMock()
        self.get_session = AsyncMock(
            return_value=SimpleNamespace(sandbox_meta=sandbox_meta)
        )


def _fake_chat_stream(
    rounds: list[list[ChatChunk]],
) -> Any:
    """假 LLM：第 N 次调用产出 rounds[N-1]；第 1 轮携带 chat_sandbox_execute 工具调用。"""

    async def _stream(**kwargs: Any) -> Any:
        rounds[0], kwargs  # noqa: B018 - 保持与真签名一致的闭包形态
        _stream.calls.append(kwargs["messages"])
        for chunk in rounds[len(_stream.calls) - 1]:
            yield chunk

    _stream.calls = []
    return _stream


def _rounds() -> list[list[ChatChunk]]:
    return [
        [
            ChatChunk(type="text", content="好的，我来执行代码。"),
            ChatChunk(
                type="tool_calls",
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_e2e_1",
                            "type": "function",
                            "function": {
                                "name": "chat_sandbox_execute",
                                "arguments": json.dumps(
                                    {"language": "python", "code": "print('hi')"}
                                ),
                            },
                        }
                    ]
                },
            ),
        ],
        [
            ChatChunk(type="text", content="代码执行完成。"),
            ChatChunk(type="done", metadata={"usage": {"total_tokens": 30}}),
        ],
    ]


async def _run_stream_until_approval(
    runtime: LangGraphChatRuntime, sandbox_execute: AsyncMock
) -> tuple[list[ChatChunk], asyncio.Task, asyncio.Event, dict[str, str]]:
    chunks: list[ChatChunk] = []
    approval_seen = asyncio.Event()
    holder: dict[str, str] = {}

    async def _collect() -> None:
        async for chunk in runtime._stream_agent_chat_langgraph(
            user_id=USER_ID,
            session_id=SESSION_ID,
            ai_message_id="e2e-message-1",
            model_config=SimpleNamespace(model="e2e-model"),
            llm_messages=[{"role": "user", "content": "帮我跑段代码"}],
            system_prompt=None,
            tools=[],
            temperature=0.2,
            max_tokens=256,
            deep_thinking=False,
            active_mcp_servers=[],
            mcp_client=SimpleNamespace(),
            tool_context=SimpleNamespace(agent_id="agent-e2e"),
        ):
            chunks.append(chunk)
            if chunk.type == "approval_request":
                holder["approval_id"] = chunk.metadata["approval_id"]
                approval_seen.set()

    collector = asyncio.create_task(_collect())
    await asyncio.wait_for(approval_seen.wait(), timeout=15)
    return chunks, collector, approval_seen, holder


@pytest.mark.asyncio
async def test_supervised_approval_approve_then_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_HOST", _REDIS_HOST)
    sandbox_execute = AsyncMock(
        return_value={
            "success": True,
            "result": {"llm_payload": {"ok": True}, "ui_payload": {"ok": True}},
        }
    )
    monkeypatch.setattr(lg_module, "execute_chat_sandbox", sandbox_execute)
    monkeypatch.setattr(
        lg_module.provider_manager, "chat_stream", _fake_chat_stream(_rounds())
    )
    runtime = LangGraphChatRuntime(
        _Service({"permissions": {"mode": "supervised"}})  # type: ignore[arg-type]
    )

    chunks, collector, _, holder = await _run_stream_until_approval(runtime, sandbox_execute)
    approval_id = holder["approval_id"]

    # 模拟 REST 端点：真实 Redis 原子决议（api/v1/studio.py approve 路径）
    service = StudioApprovalService()
    resolved = await service.resolve(approval_id, USER_ID, "approved")
    assert resolved is not None and resolved["status"] == "approved"
    await asyncio.wait_for(collector, timeout=15)

    types = [c.type for c in chunks]
    assert "approval_request" in types and "approval_resolved" in types
    request = next(c for c in chunks if c.type == "approval_request")
    assert request.metadata["tool_call_id"] == "call_e2e_1"
    assert request.metadata["timeout_seconds"] == APPROVAL_TTL_SECONDS
    assert request.metadata["risk_hint"] == "将在沙盒中执行 python 代码"
    resolved_idx = types.index("approval_resolved")
    tool_result_idx = types.index("tool_result")
    assert types.index("approval_request") < resolved_idx < tool_result_idx
    assert next(c for c in chunks if c.type == "approval_resolved").metadata["action"] == (
        "approved"
    )
    # 决议通过后才真正执行沙盒
    sandbox_execute.assert_awaited_once()
    executed_args = sandbox_execute.await_args.args[0]
    assert executed_args["code"] == "print('hi')"
    tool_result = chunks[tool_result_idx]
    assert tool_result.metadata["success"] is True
    # Redis 审批记录已消费（非 pending）
    record = await service.get(approval_id)
    assert record is not None and record["status"] == "approved"
    assert chunks[-1].type == "done"


@pytest.mark.asyncio
async def test_supervised_approval_reject_blocks_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_HOST", _REDIS_HOST)
    sandbox_execute = AsyncMock()
    monkeypatch.setattr(lg_module, "execute_chat_sandbox", sandbox_execute)
    monkeypatch.setattr(
        lg_module.provider_manager, "chat_stream", _fake_chat_stream(_rounds())
    )
    runtime = LangGraphChatRuntime(
        _Service({"permissions": {"mode": "supervised"}})  # type: ignore[arg-type]
    )

    chunks, collector, _, holder = await _run_stream_until_approval(runtime, sandbox_execute)
    service = StudioApprovalService()
    resolved = await service.resolve(
        holder["approval_id"], USER_ID, "rejected", reason="不允许执行"
    )
    assert resolved is not None and resolved["status"] == "rejected"
    await asyncio.wait_for(collector, timeout=15)

    sandbox_execute.assert_not_awaited()
    tool_result = next(c for c in chunks if c.type == "tool_result")
    assert tool_result.metadata["success"] is False
    assert tool_result.metadata["result"] == {"rejected": True, "error": "不允许执行"}
    assert next(
        c for c in chunks if c.type == "approval_resolved"
    ).metadata["action"] == "rejected"


@pytest.mark.asyncio
async def test_supervised_approval_edited_args_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_HOST", _REDIS_HOST)
    sandbox_execute = AsyncMock(
        return_value={
            "success": True,
            "result": {"llm_payload": {"ok": True}, "ui_payload": {"ok": True}},
        }
    )
    monkeypatch.setattr(lg_module, "execute_chat_sandbox", sandbox_execute)
    monkeypatch.setattr(
        lg_module.provider_manager, "chat_stream", _fake_chat_stream(_rounds())
    )
    runtime = LangGraphChatRuntime(
        _Service({"permissions": {"mode": "supervised"}})  # type: ignore[arg-type]
    )

    chunks, collector, _, holder = await _run_stream_until_approval(runtime, sandbox_execute)
    service = StudioApprovalService()
    resolved = await service.resolve(
        holder["approval_id"],
        USER_ID,
        "edited",
        modified_args={"language": "python", "code": "print('edited')"},
    )
    assert resolved is not None
    await asyncio.wait_for(collector, timeout=15)

    sandbox_execute.assert_awaited_once()
    assert sandbox_execute.await_args.args[0]["code"] == "print('edited')"
    assert next(
        c for c in chunks if c.type == "approval_resolved"
    ).metadata["action"] == "edited"


@pytest.mark.asyncio
async def test_no_permission_mode_keeps_current_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """会话未声明权限模式（默认配置现状）：不拦截、无审批事件，直接执行。"""
    monkeypatch.setenv("REDIS_HOST", _REDIS_HOST)
    sandbox_execute = AsyncMock(
        return_value={
            "success": True,
            "result": {"llm_payload": {"ok": True}, "ui_payload": {"ok": True}},
        }
    )
    monkeypatch.setattr(lg_module, "execute_chat_sandbox", sandbox_execute)
    monkeypatch.setattr(
        lg_module.provider_manager, "chat_stream", _fake_chat_stream(_rounds())
    )
    runtime = LangGraphChatRuntime(_Service(None))  # type: ignore[arg-type]

    chunks = [
        chunk
        async for chunk in runtime._stream_agent_chat_langgraph(
            user_id=USER_ID,
            session_id=SESSION_ID,
            ai_message_id="e2e-message-2",
            model_config=SimpleNamespace(model="e2e-model"),
            llm_messages=[{"role": "user", "content": "帮我跑段代码"}],
            system_prompt=None,
            tools=[],
            temperature=0.2,
            max_tokens=256,
            deep_thinking=False,
            active_mcp_servers=[],
            mcp_client=SimpleNamespace(),
            tool_context=SimpleNamespace(agent_id="agent-e2e"),
        )
    ]

    sandbox_execute.assert_awaited_once()
    assert "approval_request" not in [c.type for c in chunks]
    assert chunks[-1].type == "done"


@pytest.mark.asyncio
async def test_supervised_timeout_records_audit_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 BLPOP 超时（缩短至 2s）→ 拒绝信封 + audit_logs 留痕（真实 Postgres）。"""
    monkeypatch.setenv("REDIS_HOST", _REDIS_HOST)
    db_url = os.environ.get("E2E_DATABASE_URL", _DEV_DATABASE_URL)
    monkeypatch.setenv("DATABASE_URL", db_url)

    original_wait = StudioApprovalService.wait_resolution

    async def _short_wait(
        self: StudioApprovalService,
        approval_id: str,
        timeout: int = APPROVAL_TTL_SECONDS,  # noqa: ASYNC109 - 包装签名对齐真实现
    ) -> dict[str, Any]:
        return await original_wait(self, approval_id, timeout=2)

    monkeypatch.setattr(StudioApprovalService, "wait_resolution", _short_wait)
    sandbox_execute = AsyncMock()
    monkeypatch.setattr(lg_module, "execute_chat_sandbox", sandbox_execute)
    monkeypatch.setattr(
        lg_module.provider_manager, "chat_stream", _fake_chat_stream(_rounds())
    )
    runtime = LangGraphChatRuntime(
        _Service({"permissions": {"mode": "supervised"}})  # type: ignore[arg-type]
    )

    chunks, collector, _, holder = await _run_stream_until_approval(runtime, sandbox_execute)
    await asyncio.wait_for(collector, timeout=30)

    sandbox_execute.assert_not_awaited()
    tool_result = next(c for c in chunks if c.type == "tool_result")
    assert tool_result.metadata["success"] is False
    assert tool_result.metadata["result"]["error"] == "用户未响应（超时）"
    assert next(
        c for c in chunks if c.type == "approval_resolved"
    ).metadata["action"] == "timeout"

    # audit_logs 留痕：真实落库链路（record_approval_audit → get_session_factory）
    dsn = db_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT detail FROM audit_logs WHERE resource_id = $1 "
            "AND detail->>'event' = 'approval_decision' ORDER BY created_at DESC LIMIT 1",
            holder["approval_id"],
        )
    finally:
        await conn.close()
    if row is None:
        pytest.fail("audit_logs 未找到 timeout 审批留痕")
    detail = json.loads(row["detail"])
    assert detail["action"] == "timeout"
    assert detail["resolver"] == "timeout"
    assert detail["tool_name"] == "chat_sandbox_execute"
    assert detail["session_id"] == SESSION_ID


@pytest.mark.asyncio
async def test_always_allow_session_skip_and_user_resolution_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """会话 always_allow 命中直接放行；同时按 REST 端点方式验证 approve 决议可落 audit_logs。"""
    monkeypatch.setenv("REDIS_HOST", _REDIS_HOST)
    db_url = os.environ.get("E2E_DATABASE_URL", _DEV_DATABASE_URL)
    monkeypatch.setenv("DATABASE_URL", db_url)
    sandbox_execute = AsyncMock(
        return_value={
            "success": True,
            "result": {"llm_payload": {"ok": True}, "ui_payload": {"ok": True}},
        }
    )
    monkeypatch.setattr(lg_module, "execute_chat_sandbox", sandbox_execute)
    monkeypatch.setattr(
        lg_module.provider_manager, "chat_stream", _fake_chat_stream(_rounds())
    )
    runtime = LangGraphChatRuntime(
        _Service(  # type: ignore[arg-type]
            {"permissions": {"mode": "supervised", "always_allow": ["chat_sandbox_execute"]}}
        )
    )

    chunks = [
        chunk
        async for chunk in runtime._stream_agent_chat_langgraph(
            user_id=USER_ID,
            session_id=SESSION_ID,
            ai_message_id="e2e-message-3",
            model_config=SimpleNamespace(model="e2e-model"),
            llm_messages=[{"role": "user", "content": "帮我跑段代码"}],
            system_prompt=None,
            tools=[],
            temperature=0.2,
            max_tokens=256,
            deep_thinking=False,
            active_mcp_servers=[],
            mcp_client=SimpleNamespace(),
            tool_context=SimpleNamespace(agent_id="agent-e2e"),
        )
    ]

    sandbox_execute.assert_awaited_once()
    assert "approval_request" not in [c.type for c in chunks]

    # 按 api/v1/studio.py 决议端点的方式验证 audit 落库链路可用
    service = StudioApprovalService()
    approval = await service.create(
        user_id=USER_ID,
        session_id=SESSION_ID,
        tool_call_id="call_audit_probe",
        tool_name="chat_sandbox_execute",
        arguments={"language": "python", "code": "print(1)"},
        risk_hint="将在沙盒中执行 python 代码",
    )
    resolved = await service.resolve(approval["approval_id"], USER_ID, "approved")
    assert resolved is not None
    await record_approval_audit(
        user_id=USER_ID,
        approval_id=approval["approval_id"],
        session_id=SESSION_ID,
        tool_name="chat_sandbox_execute",
        action="approved",
        resolver="user",
        arguments={"language": "python", "code": "print(1)"},
    )
    dsn = db_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT detail FROM audit_logs WHERE resource_id = $1 "
            "AND detail->>'event' = 'approval_decision' ORDER BY created_at DESC LIMIT 1",
            approval["approval_id"],
        )
    finally:
        await conn.close()
    if row is None:
        pytest.fail("audit_logs 未找到 approve 审批留痕")
    detail = json.loads(row["detail"])
    assert detail["action"] == "approved"
    assert detail["resolver"] == "user"


@pytest.mark.asyncio
async def test_auto_approve_skips_approval_gate_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI 助手页面（auto_approve=True）：supervised 会话也不弹审批卡，工具直接执行。"""
    monkeypatch.setenv("REDIS_HOST", _REDIS_HOST)
    sandbox_execute = AsyncMock(
        return_value={
            "success": True,
            "result": {"llm_payload": {"ok": True}, "ui_payload": {"ok": True}},
        }
    )
    monkeypatch.setattr(lg_module, "execute_chat_sandbox", sandbox_execute)
    monkeypatch.setattr(
        lg_module.provider_manager, "chat_stream", _fake_chat_stream(_rounds())
    )
    runtime = LangGraphChatRuntime(
        _Service({"permissions": {"mode": "supervised"}})  # type: ignore[arg-type]
    )

    chunks: list[ChatChunk] = []
    async for chunk in runtime._stream_agent_chat_langgraph(
        user_id=USER_ID,
        session_id=SESSION_ID,
        ai_message_id="e2e-message-auto-approve",
        model_config=SimpleNamespace(model="e2e-model"),
        llm_messages=[{"role": "user", "content": "帮我跑段代码"}],
        system_prompt=None,
        tools=[],
        temperature=0.2,
        max_tokens=256,
        deep_thinking=False,
        active_mcp_servers=[],
        mcp_client=SimpleNamespace(),
        tool_context=SimpleNamespace(agent_id="agent-e2e"),
        auto_approve=True,
    ):
        chunks.append(chunk)

    types = [c.type for c in chunks]
    assert "approval_request" not in types
    assert "approval_resolved" not in types
    assert "tool_result" in types
    assert sandbox_execute.await_count == 1
