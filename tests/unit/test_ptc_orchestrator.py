"""PTC 编排执行器单元测试：RPC 往返 / 白名单 / 递归拦截 / 次数上限 / 超时强杀 /
汇总截断 / parallel_calls 并发 / 用户代码异常，以及 schema 条件挂载与审批名单回归。"""

import asyncio
import time
from typing import Any

from cygnusx.application.services import ptc_orchestrator
from cygnusx.application.services.ptc_orchestrator import (
    PTC_ALLOWED_TOOLS,
    run_orchestration,
)


def _envelope(payload: dict[str, Any], success: bool = True) -> dict[str, Any]:
    return {
        "success": success,
        "result": {"llm_payload": payload, "ui_payload": dict(payload)},
    }


class _Recorder:
    """mock 工具分发：记录每次子调用，按名字返回可辨识结果。"""

    def __init__(self, delays: dict[str, float] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.delays = delays or {}

    async def __call__(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(args)))
        delay = self.delays.get(name)
        if delay:
            await asyncio.sleep(delay)
        return _envelope({"tool": name, "echo": args})


async def test_rpc_roundtrip() -> None:
    recorder = _Recorder()
    code = (
        "a = call_tool('workspace_list', path='input/')\n"
        "b = call_tool('knowledge_search', query='tp53')\n"
        "print('done', a['tool'], b['tool'])\n"
    )
    result = await run_orchestration(code, "sess-1", tool_executor=recorder)
    assert result["success"] is True
    llm = result["result"]["llm_payload"]
    assert llm["summary"].strip() == "done workspace_list knowledge_search"
    assert llm["call_count"] == 2
    assert llm["failed_calls"] == 0
    ui = result["result"]["ui_payload"]
    assert [r["name"] for r in ui["calls"]] == ["workspace_list", "knowledge_search"]
    assert all(r["success"] for r in ui["calls"])
    assert recorder.calls[1] == ("knowledge_search", {"query": "tp53"})


async def test_progress_callback() -> None:
    lines: list[str] = []

    async def _on_progress(text: str) -> None:
        lines.append(text)

    code = "call_tool('workspace_list')\nprint('ok')\n"
    result = await run_orchestration(
        code, "sess-1", tool_executor=_Recorder(), on_progress=_on_progress
    )
    assert result["success"] is True
    assert any("workspace_list 开始" in line for line in lines)
    assert any("workspace_list 成功" in line for line in lines)


async def test_whitelist_rejects_ask_user() -> None:
    recorder = _Recorder()
    code = (
        "try:\n"
        "    call_tool('ask_user', question='x')\n"
        "except RuntimeError as exc:\n"
        "    print('blocked:', exc)\n"
    )
    result = await run_orchestration(code, "sess-1", tool_executor=recorder)
    assert result["success"] is True
    assert "不在编排白名单内" in result["result"]["llm_payload"]["summary"]
    assert recorder.calls == []  # 被拦截的调用不应到达分发器


async def test_recursive_orchestrate_rejected() -> None:
    assert "tool_orchestrate" not in PTC_ALLOWED_TOOLS
    recorder = _Recorder()
    code = (
        "try:\n"
        "    call_tool('tool_orchestrate', code='print(1)')\n"
        "except RuntimeError as exc:\n"
        "    print('blocked:', exc)\n"
    )
    result = await run_orchestration(code, "sess-1", tool_executor=recorder)
    assert result["success"] is True
    assert "不在编排白名单内" in result["result"]["llm_payload"]["summary"]
    assert recorder.calls == []


async def test_max_calls_limit() -> None:
    recorder = _Recorder()
    code = (
        "for i in range(3):\n"
        "    try:\n"
        "        call_tool('workspace_list', idx=i)\n"
        "    except RuntimeError as exc:\n"
        "        print('limited:', exc)\n"
    )
    result = await run_orchestration(code, "sess-1", tool_executor=recorder, max_calls=2)
    assert result["success"] is True
    llm = result["result"]["llm_payload"]
    assert llm["call_count"] == 2
    assert "子调用次数上限" in llm["summary"]
    assert len(recorder.calls) == 2


async def test_total_timeout_kills_child() -> None:
    recorder = _Recorder()
    started = time.monotonic()
    result = await run_orchestration(
        "import time\ntime.sleep(60)\n",
        "sess-1",
        tool_executor=recorder,
        timeout_sec=1,
    )
    elapsed = time.monotonic() - started
    assert result["success"] is False
    assert "超时" in result["result"]["llm_payload"]["error"]
    assert result["result"]["ui_payload"]["timed_out"] is True
    assert elapsed < 20  # 子进程被强杀，不会真的睡满 60s


async def test_summary_tail_truncation() -> None:
    code = "print('x' * 5000)\n"
    result = await run_orchestration(code, "sess-1", tool_executor=_Recorder())
    assert result["success"] is True
    llm = result["result"]["llm_payload"]
    assert len(llm["summary"]) == ptc_orchestrator._PTC_LLM_SUMMARY_TAIL
    assert llm["summary_truncated"] is True
    # ui_payload 保留更完整的汇总供前端渲染
    assert len(result["result"]["ui_payload"]["summary"]) > 4000


async def test_parallel_calls_concurrency_and_order() -> None:
    recorder = _Recorder(delays={"workspace_list": 0.4, "knowledge_search": 0.4})
    code = (
        "results = parallel_calls([\n"
        "    {'name': 'workspace_list', 'args': {'path': 'a'}},\n"
        "    {'name': 'knowledge_search', 'args': {'query': 'b'}},\n"
        "])\n"
        "print(results[0]['tool'], results[1]['tool'])\n"
        "print(results[0]['echo']['path'], results[1]['echo']['query'])\n"
    )
    started = time.monotonic()
    result = await run_orchestration(code, "sess-1", tool_executor=recorder)
    elapsed = time.monotonic() - started
    assert result["success"] is True
    summary = result["result"]["llm_payload"]["summary"]
    # 结果按入参顺序对应（先发的慢调用也不错位）
    assert "workspace_list knowledge_search" in summary
    assert "a b" in summary
    assert elapsed < 0.8  # 并发执行：总耗时明显小于串行的 0.8s+


async def test_parallel_calls_partial_failure() -> None:
    async def _executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "knowledge_search":
            return _envelope({"error": "库不可用"}, success=False)
        return _envelope({"tool": name})

    code = (
        "results = parallel_calls([\n"
        "    {'name': 'workspace_list', 'args': {}},\n"
        "    {'name': 'knowledge_search', 'args': {}},\n"
        "])\n"
        "print(results[0]['tool'], 'error' in results[1])\n"
    )
    result = await run_orchestration(code, "sess-1", tool_executor=_executor)
    assert result["success"] is True
    llm = result["result"]["llm_payload"]
    assert "workspace_list True" in llm["summary"]
    assert llm["failed_calls"] == 1


async def test_user_code_exception_friendly_result() -> None:
    code = "print('before')\n1 / 0\n"
    result = await run_orchestration(code, "sess-1", tool_executor=_Recorder())
    assert result["success"] is False
    llm = result["result"]["llm_payload"]
    assert "ZeroDivisionError" in llm["error"]
    assert llm["summary"].startswith("before")  # 异常前的 print 仍回传
    assert result["result"]["ui_payload"]["exit_code"] != 0


async def test_subprocess_isolation_env_cleared() -> None:
    """子进程 env 清空：宿主环境变量不可见（防密钥泄漏进编排代码）。"""
    import os

    os.environ["CYGNUSX_PTC_TEST_SECRET"] = "should-not-leak"
    try:
        code = "import os\nprint('leak' if os.environ.get('CYGNUSX_PTC_TEST_SECRET') else 'clean')\n"
        result = await run_orchestration(code, "sess-1", tool_executor=_Recorder())
        assert result["success"] is True
        assert result["result"]["llm_payload"]["summary"].strip() == "clean"
    finally:
        os.environ.pop("CYGNUSX_PTC_TEST_SECRET", None)


# ===== schema 条件挂载与审批名单回归 =====


def test_schema_mounted_only_when_ptc_enabled() -> None:
    from cygnusx.application.services.studio_tools import (
        STUDIO_TOOL_SCHEMAS,
        studio_runtime_tool_schemas,
    )

    def _names(schemas: list[dict[str, Any]]) -> set[str]:
        return {str(s.get("function", {}).get("name") or "") for s in schemas}

    assert "tool_orchestrate" not in _names(STUDIO_TOOL_SCHEMAS)
    assert "tool_orchestrate" in _names(studio_runtime_tool_schemas({"ptc_enabled": True}))
    assert "tool_orchestrate" not in _names(studio_runtime_tool_schemas({"ptc_enabled": False}))
    assert "tool_orchestrate" not in _names(studio_runtime_tool_schemas(None))


def test_orchestrate_in_studio_tool_names_and_approval_list() -> None:
    from cygnusx.application.services.studio_approval_service import (
        approval_required_tools,
    )
    from cygnusx.application.services.studio_tools import STUDIO_TOOL_NAMES

    assert "tool_orchestrate" in STUDIO_TOOL_NAMES
    assert "tool_orchestrate" in approval_required_tools()


async def test_execute_studio_tool_dispatch() -> None:
    """分发器分支：execute_studio_tool('tool_orchestrate') 落到编排执行器。"""
    from cygnusx.application.services import studio_tools

    captured: dict[str, Any] = {}

    async def _fake_run(code: str, session_id: str, **kwargs: Any) -> dict[str, Any]:
        captured["code"] = code
        captured["session_id"] = session_id
        captured["kwargs"] = kwargs
        return _envelope({"summary": "ok"})

    original = studio_tools.run_orchestration
    studio_tools.run_orchestration = _fake_run
    try:
        result = await studio_tools.execute_studio_tool(
            "tool_orchestrate",
            {"code": "print('hi')", "timeout": 30},
            "sess-dispatch",
            user_id="u1",
        )
    finally:
        studio_tools.run_orchestration = original
    assert result["success"] is True
    assert captured["code"] == "print('hi')"
    assert captured["session_id"] == "sess-dispatch"
    assert captured["kwargs"]["timeout_sec"] == 30
    assert captured["kwargs"]["user_id"] == "u1"


async def test_stream_studio_tool_emits_progress() -> None:
    """流式包装：子调用进度桥接为 tool_output 事件，最后产出结果信封。"""
    from cygnusx.application.services import studio_tools
    from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

    async def _fake_run(code: str, session_id: str, **kwargs: Any) -> dict[str, Any]:
        on_progress = kwargs.get("on_progress")
        if on_progress is not None:
            await on_progress("[子调用 1] workspace_list 开始")
        return _envelope({"summary": "ok"})

    original = studio_tools.run_orchestration
    studio_tools.run_orchestration = _fake_run
    try:
        chunks: list[Any] = []
        async for item in studio_tools.stream_studio_tool(
            "tool_orchestrate", {"code": "print('hi')"}, "sess-stream", tool_call_id="tc-1"
        ):
            chunks.append(item)
    finally:
        studio_tools.run_orchestration = original
    outputs = [
        c for c in chunks
        if isinstance(c, ChatChunk) and c.type == "tool_output"
    ]
    assert any("子调用 1" in str(c.metadata.get("data")) for c in outputs)
    assert all(c.metadata.get("tool_call_id") == "tc-1" for c in outputs)
    envelope = chunks[-1]
    assert isinstance(envelope, dict) and envelope["success"] is True


# ===== WP3 任务 3：llm_query 动态白名单（会话 research_mode.ptc_llm_query 门控） =====


async def test_llm_query_soft_fails_when_gate_off() -> None:
    """默认（无 db / 开关未开）：llm_query 不在白名单，call_tool 软失败且不到达分发器。"""
    recorder = _Recorder()
    code = (
        "try:\n"
        "    call_tool('llm_query', prompt='x')\n"
        "except RuntimeError as exc:\n"
        "    print('blocked:', exc)\n"
    )
    result = await run_orchestration(code, "sess-1", tool_executor=recorder)
    assert result["success"] is True  # 软失败：编排继续
    assert "当前会话未开启 llm_query" in result["result"]["llm_payload"]["summary"]
    assert recorder.calls == []


async def test_llm_query_allowed_when_override_true() -> None:
    """开关开启（显式 override）：llm_query 进白名单并到达分发器（不真调模型）。"""
    recorder = _Recorder()
    code = "print(call_tool('llm_query', prompt='hi')['tool'])\n"
    result = await run_orchestration(
        code, "sess-1", tool_executor=recorder, llm_query_enabled=True
    )
    assert result["success"] is True
    assert [name for name, _ in recorder.calls] == ["llm_query"]
    assert "llm_query" in result["result"]["llm_payload"]["summary"]


async def test_llm_query_gate_reads_session_research_mode() -> None:
    """resolve_ptc_llm_query_enabled 从 chat_sessions.sandbox_meta 读开关。"""
    from cygnusx.application.services.ptc_orchestrator import (
        resolve_ptc_llm_query_enabled,
    )

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _Db:
        def __init__(self, value):
            self._value = value

        async def execute(self, _stmt):
            return _Result(self._value)

    on = await resolve_ptc_llm_query_enabled(
        session_id="s",
        db=_Db({"research_mode": {"enabled": True, "ptc_llm_query": True}}),
    )
    assert on is True
    off = await resolve_ptc_llm_query_enabled(
        session_id="s",
        db=_Db({"research_mode": {"enabled": True, "ptc_llm_query": False}}),
    )
    assert off is False
    assert await resolve_ptc_llm_query_enabled(session_id="s", db=_Db(None)) is False
    assert await resolve_ptc_llm_query_enabled(session_id="s", db=None) is False
    assert await resolve_ptc_llm_query_enabled(session_id="s", db=None, override=True) is True


def test_llm_query_not_in_static_whitelist_and_not_approval_required() -> None:
    """回归：llm_query 默认不在静态白名单，且审批语义不变（不在审批拦截名单）。"""
    from cygnusx.application.services.ptc_orchestrator import (
        PTC_ALLOWED_TOOLS,
        PTC_STATIC_ALLOWED_TOOLS,
    )
    from cygnusx.application.services.studio_approval_service import (
        approval_required_tools,
    )

    assert "llm_query" in PTC_ALLOWED_TOOLS  # 动态成员：候选全集
    assert "llm_query" not in PTC_STATIC_ALLOWED_TOOLS  # 默认编排白名单不含
    assert "tool_orchestrate" in approval_required_tools()  # 整段一次审批不变
    assert "llm_query" not in approval_required_tools()  # 子调用不逐次审批
