"""WP3-Task1/2 e2e 验收：cell 语义落库字段 + 只读确定性 .ipynb 导出。

真实 dev DB：造专用测试会话（e2e-wp3-*），写入带 cell_index/language 的
tool_invocations 信封（与 chat_service 落库组装同构：先写字段再算 payload_hash），
经 ChatNotebookExportService + 路由处理函数真实导出，finally 清理。

用法：
    .venv/bin/python scripts/poc/e2e_wp3_notebook_export.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://omichub:omichub_dev_password@127.0.0.1:5432/omichub",
)

from datetime import UTC, datetime

import asyncpg

BASE_TS = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)

SESSION_ID = f"e2e-wp3-{uuid.uuid4().hex[:8]}"
PG_DSN = "postgresql://omichub:omichub_dev_password@127.0.0.1:5432/omichub"

MSG_USER = str(uuid.uuid4())
MSG_CODE = str(uuid.uuid4())
MSG_TEXT = str(uuid.uuid4())


def _ok(step: str, detail: str = "") -> None:
    print(f"[PASS] {step}" + (f" — {detail}" if detail else ""))


def _envelope(tool_call_id: str, code: str, language: str, cell_index: int, **overrides):
    """与 chat_service.py 落库组装同构：cell 字段先写入，payload_hash 覆盖之。"""
    from cygnusx.application.services.chat.utils import (
        _code_cell_envelope_fields,
        _invocation_payload_hash,
    )

    args = {"language": language, "code": code}
    envelope: dict = {
        "tool_call_id": tool_call_id,
        "tool_name": "sandbox_execute",
        "arguments": args,
        "success": True,
        "result": {"stdout": f"out-{cell_index}\n"},
        "ui_payload": {"language": language, "stdout": f"out-{cell_index}\n", "stderr": ""},
        "mcp_server": "studio",
        **_code_cell_envelope_fields("sandbox_execute", args, cell_index),
    }
    envelope.update(overrides)
    envelope["payload_hash"] = _invocation_payload_hash(envelope)
    return envelope


async def main() -> None:
    from cygnusx.application.services.chat.notebook_export_service import (
        ChatNotebookExportService,
    )
    from cygnusx.application.services.chat.utils import _invocation_payload_hash
    from cygnusx.application.services.chat_service import ChatService
    from cygnusx.core.exceptions import NotFoundError
    from cygnusx.infrastructure.database.models.chat import (
        ChatMessageModel,
        ChatSessionModel,
    )
    from cygnusx.infrastructure.database.session import get_session_factory

    conn = await asyncpg.connect(PG_DSN)
    session_factory = get_session_factory()
    try:
        # ===== 准备：测试用户 / 模型 / 会话（两段代码 + 一段截断 + 普通文本） =====
        user_row = await conn.fetchrow("select id, username from users order by created_at limit 1")
        assert user_row, "users 表为空"
        user_id = str(user_row["id"])
        other_row = await conn.fetchrow(
            "select id from users where id <> $1 order by created_at limit 1", user_id
        )
        other_user_id = str(other_row["id"]) if other_row else "user-not-exists-e2e"
        model_row = await conn.fetchrow("select id from ai_provider_configs limit 1")
        assert model_row, "ai_provider_configs 为空"
        model_id = uuid.UUID(str(model_row["id"]))
        print(f"== 用户: {user_row['username']} 会话: {SESSION_ID} ==")

        truncated = _envelope(
            "call-wp3-2",
            "print('truncated')",
            "r",
            1,
            result={"_cygnusx_payload_truncated": True},
            result_truncation={
                "payload_truncated": True,
                "truncation_note": "工具结果序列化超过 200KB 落库护栏，已替换为截断标记",
                "original_bytes": 123456,
            },
        )
        envelopes = [
            _envelope("call-wp3-1", "print('cell-zero')", "python", 0),
            truncated,
            # 非代码工具：cell_index 为 null
            {
                "tool_call_id": "call-wp3-3",
                "tool_name": "knowledge_search",
                "arguments": {"query": "e2e"},
                "success": True,
                "result": {"hits": []},
                "ui_payload": None,
                "mcp_server": "knowledge",
                "cell_index": None,
                "language": None,
            },
        ]
        envelopes[2]["payload_hash"] = _invocation_payload_hash(envelopes[2])

        async with session_factory() as db:
            db.add(
                ChatSessionModel(
                    id=uuid.uuid4(),
                    session_id=SESSION_ID,
                    user_id=user_id,
                    model_id=model_id,
                    title="E2E-WP3 notebook 导出",
                    status="active",
                    mode="studio",
                    message_count=3,
                )
            )
            db.add(
                ChatMessageModel(
                    id=uuid.uuid4(),
                    message_id=MSG_USER,
                    session_id=SESSION_ID,
                    role="user",
                    content="跑两段代码看看",
                    created_at=BASE_TS,
                )
            )
            db.add(
                ChatMessageModel(
                    id=uuid.uuid4(),
                    message_id=MSG_CODE,
                    session_id=SESSION_ID,
                    role="assistant",
                    content="代码执行完毕",
                    metadata_json={"tool_invocations": envelopes},
                    created_at=BASE_TS.replace(second=1),
                )
            )
            db.add(
                ChatMessageModel(
                    id=uuid.uuid4(),
                    message_id=MSG_TEXT,
                    session_id=SESSION_ID,
                    role="assistant",
                    content="最终总结：全部完成",
                    created_at=BASE_TS.replace(second=2),
                )
            )
            await db.commit()

        # ===== 1) 落库信封：cell_index/language 存在且 payload_hash 复算通过 =====
        async with session_factory() as db:
            service = ChatService(db)
            dtos = await service.get_messages(SESSION_ID, user_id)
        code_msg = next(d for d in dtos if d.message_id == MSG_CODE)
        stored = code_msg.metadata_json["tool_invocations"]
        assert stored[0]["cell_index"] == 0 and stored[0]["language"] == "python"
        assert stored[1]["cell_index"] == 1 and stored[1]["language"] == "r"
        assert stored[2]["cell_index"] is None and stored[2]["language"] is None
        for inv in stored:
            assert inv["payload_hash"] == _invocation_payload_hash(inv), (
                f"hash 复算失败: {inv['tool_call_id']}"
            )
        tampered = {**stored[0], "cell_index": 42}
        assert _invocation_payload_hash(tampered) != stored[0]["payload_hash"]
        _ok("1 落库信封 cell_index/language 存在，payload_hash 复算+篡改检测通过")

        # ===== 2) 导出：nbformat 4.x、cell 顺序与历史一致、截断带说明 =====
        async with session_factory() as db:
            service = ChatService(db)
            session = await service.get_session(SESSION_ID, user_id)
            exported = await ChatNotebookExportService(db).export_session(session)
        assert exported["content_type"] == "application/x-ipynb+json"
        assert exported["filename"].endswith(".ipynb") and "E2E-WP3" in exported["filename"]
        nb = json.loads(exported["data"])
        assert nb["nbformat"] == 4 and nb["nbformat_minor"] == 5
        assert nb["metadata"]["kernelspec"]["name"] == "python3"
        sequence = [(c["cell_type"], "".join(c["source"])) for c in nb["cells"]]
        assert sequence[0] == ("markdown", "跑两段代码看看")
        assert sequence[1][0] == "code" and "print('cell-zero')" in sequence[1][1]
        # 截断条目：说明 markdown cell + code cell 内 stderr 注释，均不静默丢弃
        assert sequence[2][0] == "markdown" and "截断" in sequence[2][1]
        assert sequence[3][0] == "code" and "print('truncated')" in sequence[3][1]
        assert sequence[4] == ("markdown", "代码执行完毕")
        assert sequence[5] == ("markdown", "最终总结：全部完成")
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        assert [c["execution_count"] for c in code_cells] == [1, 2]
        assert code_cells[0]["outputs"][0] == {
            "name": "stdout",
            "output_type": "stream",
            "text": ["out-0\n"],
        }
        stderr_text = "".join(
            line
            for o in code_cells[1]["outputs"]
            if o.get("name") == "stderr"
            for line in o["text"]
        )
        assert "截断说明" in stderr_text and "123456" in stderr_text
        _ok("2 导出 nbformat 4.x，cell 顺序与历史一致，截断条目带说明", f"cells={len(nb['cells'])}")

        # ===== 3) 确定性：导出两次字节级一致 =====
        async with session_factory() as db:
            session2 = await ChatService(db).get_session(SESSION_ID, user_id)
            second = await ChatNotebookExportService(db).export_session(session2)
        assert second["data"] == exported["data"], "同一份历史两次导出不一致"
        assert (
            second["sha256"] == exported["sha256"] == hashlib.sha256(exported["data"]).hexdigest()
        )
        _ok("3 两次导出字节级一致", f"sha256={exported['sha256'][:16]}…")

        # ===== 4) 路由处理函数：属主导出 200，非属主/不存在 404 =====
        from cygnusx.api.v1.chat import export_session_notebook

        async with session_factory() as db:
            route_service = ChatService(db)
            resp = await export_session_notebook(
                current_user_id=user_id,
                service=route_service,
                db=db,
                session_id=SESSION_ID,
            )
        assert resp.status_code == 200
        assert resp.media_type == "application/x-ipynb+json"
        disposition = resp.headers.get("Content-Disposition", "")
        assert disposition.startswith("attachment; filename=") and ".ipynb" in disposition
        assert resp.body == exported["data"]
        for wrong_user in (other_user_id, "user-definitely-not-exists"):
            try:
                async with session_factory() as db:
                    await export_session_notebook(
                        current_user_id=wrong_user,
                        service=ChatService(db),
                        db=db,
                        session_id=SESSION_ID,
                    )
            except NotFoundError:
                continue
            raise AssertionError(f"非属主访问未被 NotFoundError 拦截: {wrong_user}")
        _ok("4 属主导出 200 + 正确头；非属主与不存在用户均 404")

        print("\n== WP3-Task1/2 e2e 全部通过 ==")
    finally:
        for mid in (MSG_USER, MSG_CODE, MSG_TEXT):
            await conn.execute("delete from chat_messages where message_id=$1", mid)
        await conn.execute("delete from chat_sessions where session_id=$1", SESSION_ID)
        await conn.close()
        print("== 测试数据已清理 ==")


if __name__ == "__main__":
    asyncio.run(main())
