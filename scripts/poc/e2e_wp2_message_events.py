"""WP2-Task1 e2e 验收脚本：append-only 事件表 + chunk 落库 + 信封 hash + 双读重建。

真实 dev DB + 真实流式函数（stream_studio_tool / stream_chat_sandbox_tool 的真实
队列/心跳/落库链路，执行体以假实现驱动——e2e 聚焦事件落库与重建链路，不依赖
沙盒容器与 LLM）。使用专用测试会话（e2e-wp2-*），跑完 finally 清理。

用法：
    .venv/bin/python scripts/poc/e2e_wp2_message_events.py
"""

from __future__ import annotations

import asyncio
import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://omichub:omichub_dev_password@127.0.0.1:5432/omichub",
)

import asyncpg
from loguru import logger
from sqlalchemy import select

SESSION_ID = f"e2e-wp2-{uuid.uuid4().hex[:8]}"
PG_DSN = "postgresql://omichub:omichub_dev_password@127.0.0.1:5432/omichub"

MSG_WITH_EVENTS = str(uuid.uuid4())  # 新消息：有事件，走回放
MSG_OLD = str(uuid.uuid4())  # 旧消息：无事件，回落终态快照
TOOL_CALL_ID = "call-e2e-wp2-1"
STDOUT_TEXT = "line-1\nline-2\nline-3\n"  # 三段 chunk 拼接
STDERR_TEXT = "warn-e2e\n"


def _ok(step: str, detail: str = "") -> None:
    print(f"[PASS] {step}" + (f" — {detail}" if detail else ""))


async def _fake_studio_execute(name, args, session_id, **kwargs):
    """假 Studio 执行体：多段 tool_output + 终态信封（与真实 sandbox_execute 同构）。"""
    on_output = kwargs.get("on_output")
    assert on_output is not None
    for piece in ("line-1\n", "line-2\n", "line-3\n"):
        await on_output("stdout", piece)
    await on_output("stderr", "warn-e2e\n")
    return {
        "success": True,
        "result": {
            "llm_payload": {"stdout": STDOUT_TEXT, "stderr": STDERR_TEXT},
            "ui_payload": {"stdout": STDOUT_TEXT, "stderr": STDERR_TEXT},
        },
    }


async def _fake_chat_sandbox_execute(args, user_id, **kwargs):
    on_output = kwargs.get("on_output")
    assert on_output is not None
    for piece in ("line-1\n", "line-2\n", "line-3\n"):
        await on_output("stdout", piece)
    return {
        "success": True,
        "result": {
            "llm_payload": {"stdout": STDOUT_TEXT, "stderr": ""},
            "ui_payload": {"stdout": STDOUT_TEXT, "stderr": "", "language": "python"},
        },
    }


async def main() -> None:
    from cygnusx.application.services import chat_sandbox_tools, studio_tools
    from cygnusx.application.services.chat.dto_support import ChatDtoSupport
    from cygnusx.application.services.chat.utils import _invocation_payload_hash
    from cygnusx.application.services.chat_service import ChatService
    from cygnusx.infrastructure.database.models.chat import (
        ChatMessageEventModel,
        ChatMessageModel,
        ChatSessionModel,
    )
    from cygnusx.infrastructure.database.session import get_session_factory

    conn = await asyncpg.connect(PG_DSN)
    session_factory = get_session_factory()
    chat_msg_id = str(uuid.uuid4())
    injected_msg_id = str(uuid.uuid4())
    try:
        # ===== 准备：测试用户 / 模型 / 会话 / 新旧两条消息 =====
        user_row = await conn.fetchrow("select id, username from users order by created_at limit 1")
        assert user_row, "users 表为空"
        user_id = str(user_row["id"])
        model_row = await conn.fetchrow("select id from ai_provider_configs limit 1")
        assert model_row, "ai_provider_configs 为空"
        model_id = uuid.UUID(str(model_row["id"]))
        print(f"== 测试用户: {user_row['username']} ({user_id[:8]}) 会话: {SESSION_ID} ==")

        envelope: dict = {
            "tool_call_id": TOOL_CALL_ID,
            "tool_name": "sandbox_execute",
            "arguments": {"language": "python", "code": "print('e2e')"},
            "success": True,
            "result": {"stdout": STDOUT_TEXT, "stderr": STDERR_TEXT},
            "ui_payload": {"stdout": STDOUT_TEXT, "stderr": STDERR_TEXT},
            "mcp_server": "studio",
        }
        envelope["payload_hash"] = _invocation_payload_hash(envelope)
        old_envelope: dict = {
            "tool_call_id": "call-old-1",
            "tool_name": "knowledge_search",
            "arguments": {"query": "e2e"},
            "success": True,
            "result": {"hits": []},
            "ui_payload": None,
            "mcp_server": "knowledge",
        }
        old_envelope["payload_hash"] = _invocation_payload_hash(old_envelope)

        async with session_factory() as db:
            db.add(
                ChatSessionModel(
                    id=uuid.uuid4(),
                    session_id=SESSION_ID,
                    user_id=user_id,
                    model_id=model_id,
                    title="E2E-WP2 事件流",
                    status="active",
                    mode="studio",
                    message_count=2,
                )
            )
            db.add(
                ChatMessageModel(
                    id=uuid.uuid4(),
                    message_id=MSG_WITH_EVENTS,
                    session_id=SESSION_ID,
                    role="assistant",
                    content="e2e 新消息",
                    metadata_json={"tool_invocations": [envelope]},
                )
            )
            db.add(
                ChatMessageModel(
                    id=uuid.uuid4(),
                    message_id=MSG_OLD,
                    session_id=SESSION_ID,
                    role="assistant",
                    content="e2e 旧消息",
                    metadata_json={"tool_invocations": [old_envelope], "usage": {"total_tokens": 7}},
                )
            )
            await db.commit()

        # ===== 1) Studio 流式执行：多段 tool_output 逐 chunk 落事件表 =====
        studio_tools.execute_studio_tool = _fake_studio_execute  # 假执行体驱动真实流式链路
        chunks = []
        async for item in studio_tools.stream_studio_tool(
            "sandbox_execute",
            {"language": "python", "code": "print('e2e')"},
            SESSION_ID,
            tool_call_id=TOOL_CALL_ID,
            message_id=MSG_WITH_EVENTS,
        ):
            if getattr(item, "type", None) == "tool_output":
                chunks.append(item)
        assert len(chunks) == 4, f"应产出 4 个 tool_output chunk，实际 {len(chunks)}"
        _ok("1a Studio 流式产出 4 段 tool_output", f"chunks={len(chunks)}")

        async with session_factory() as db:
            rows = (
                await db.execute(
                    select(ChatMessageEventModel)
                    .where(ChatMessageEventModel.message_id == MSG_WITH_EVENTS)
                    .order_by(ChatMessageEventModel.seq)
                )
            ).scalars().all()
        seqs = [r.seq for r in rows]
        assert seqs == sorted(seqs) and len(seqs) == len(set(seqs)), f"seq 非单调唯一: {seqs}"
        assert all(r.event_type == "tool_output" for r in rows)
        replayed = "".join(r.payload["data"] for r in rows if r.payload["stream"] == "stdout")
        assert replayed == STDOUT_TEXT, f"回放 stdout 与终态不一致: {replayed!r}"
        _ok("1b 事件表落库，seq 单调唯一", f"events={len(rows)} seqs={seqs}")

        # ===== 2) chat 沙盒链路同样落事件 =====
        chat_sandbox_tools.execute_chat_sandbox = _fake_chat_sandbox_execute
        async with session_factory() as db:
            db.add(
                ChatMessageModel(
                    id=uuid.uuid4(),
                    message_id=chat_msg_id,
                    session_id=SESSION_ID,
                    role="assistant",
                    content="e2e chat 沙盒消息",
                    metadata_json={"tool_invocations": []},
                )
            )
            await db.commit()
        chat_chunks = 0
        async for item in chat_sandbox_tools.stream_chat_sandbox_tool(
            {"language": "python", "code": "print(1)"},
            user_id=user_id,
            tool_call_id=TOOL_CALL_ID,
            session_id=SESSION_ID,
            message_id=chat_msg_id,
        ):
            if getattr(item, "type", None) == "tool_output":
                chat_chunks += 1
        async with session_factory() as db:
            chat_rows = (
                await db.execute(
                    select(ChatMessageEventModel).where(
                        ChatMessageEventModel.message_id == chat_msg_id
                    )
                )
            ).scalars().all()
        assert chat_chunks == 3 and len(chat_rows) == 3
        _ok("2 chat 沙盒链路 chunk 落事件表", f"events={len(chat_rows)}")

        # ===== 3) 双读重建：新消息回放路径 =====
        async with session_factory() as db:
            service = ChatService(db)
            dtos = await service.get_messages(SESSION_ID, user_id)
        by_id = {d.message_id: d for d in dtos}
        new_dto = by_id[MSG_WITH_EVENTS]
        replay = new_dto.metadata_json.get("tool_output_replay")
        assert replay, "新消息应携带 tool_output_replay"
        assert replay["tool_outputs"][TOOL_CALL_ID]["stdout"] == STDOUT_TEXT
        assert replay["tool_outputs"][TOOL_CALL_ID]["stderr"] == STDERR_TEXT
        assert replay["consistent_with_snapshot"] is True
        # 终态快照原样保留（信封 + hash 未被回放块污染）
        inv = new_dto.metadata_json["tool_invocations"][0]
        assert inv["result"]["stdout"] == STDOUT_TEXT and inv["payload_hash"] == envelope["payload_hash"]
        _ok("3a 新消息走回放路径且与终态一致", f"events={replay['event_count']} consistent=True")

        # ===== 4) 旧消息（无事件）组装与旧行为逐字节一致 =====
        async with session_factory() as db:
            raw_msg = (
                await db.execute(
                    select(ChatMessageModel).where(ChatMessageModel.message_id == MSG_OLD)
                )
            ).scalar_one()
            legacy_dto = ChatDtoSupport._to_msg_dto(raw_msg)  # 旧组装逻辑（无 replay）
        old_dto = by_id[MSG_OLD]
        assert "tool_output_replay" not in old_dto.metadata_json
        assert old_dto.metadata_json == legacy_dto.metadata_json
        assert old_dto.metadata_json == raw_msg.metadata_json
        assert old_dto.tokens == legacy_dto.tokens
        _ok("4 旧消息无 replay 注入，组装结果与旧逻辑一致")

        # ===== 5) 信封 payload_hash 存在且可复算 =====
        async with session_factory() as db:
            stored = by_id[MSG_WITH_EVENTS].metadata_json["tool_invocations"][0]
        recomputed = _invocation_payload_hash(stored)
        assert stored["payload_hash"] == recomputed == envelope["payload_hash"]
        assert len(recomputed) == 64
        # 篡改检测：改动任一字段后 hash 不再匹配
        tampered = {**stored, "success": False}
        assert _invocation_payload_hash(tampered) != stored["payload_hash"]
        _ok("5 payload_hash 可复算且可检出篡改", f"sha256={recomputed[:16]}…")

        # ===== 6) 落库失败注入：流式不中断 + 降级日志 =====
        import cygnusx.infrastructure.database.session as session_mod

        real_factory = session_mod.get_session_factory
        warnings: list[str] = []
        sink_id = logger.add(lambda m: warnings.append(str(m)), level="WARNING")

        def _boom_factory():
            raise RuntimeError("e2e injected db failure")

        session_mod.get_session_factory = _boom_factory
        injected_chunks = 0
        try:
            async for item in studio_tools.stream_studio_tool(
                "sandbox_execute",
                {"language": "python", "code": "print('x')"},
                SESSION_ID,
                tool_call_id="call-injected",
                message_id=injected_msg_id,
            ):
                if getattr(item, "type", None) == "tool_output":
                    injected_chunks += 1
        finally:
            session_mod.get_session_factory = real_factory
            logger.remove(sink_id)
        assert injected_chunks == 4, f"落库失败注入后流式被中断: {injected_chunks} chunks"
        assert any("降级" in w or "失败" in w for w in warnings), "未见降级日志"
        async with session_factory() as db:
            leftover = (
                await db.execute(
                    select(ChatMessageEventModel).where(
                        ChatMessageEventModel.message_id == injected_msg_id
                    )
                )
            ).scalars().all()
        assert not leftover
        _ok("6 落库失败注入：流式 4 chunk 全量产出，降级日志出现，无主链路异常", f"logs={len(warnings)}")

        print("\n== WP2-Task1 e2e 全部通过 ==")
    finally:
        # ===== 清理测试数据 =====
        for mid in (MSG_WITH_EVENTS, MSG_OLD, chat_msg_id, injected_msg_id):
            await conn.execute(
                "delete from chat_message_events where message_id=$1", mid
            )
            await conn.execute("delete from chat_messages where message_id=$1", mid)
        await conn.execute("delete from chat_sessions where session_id=$1", SESSION_ID)
        await conn.close()
        print("== 测试数据已清理 ==")


if __name__ == "__main__":
    asyncio.run(main())
