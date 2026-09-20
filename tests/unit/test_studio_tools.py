"""Studio 内置工具单元测试：schema 合法性 + 分发器行为（mock sandbox manager）"""

import json
from typing import Any

import httpx
import pytest

from cygnusx.application.services import studio_tools
from cygnusx.application.services.studio_tools import (
    STUDIO_SYSTEM_PROMPT_SUFFIX,
    STUDIO_TOOL_NAMES,
    STUDIO_TOOL_SCHEMAS,
    TOOL_ORCHESTRATE_SCHEMA,
    execute_studio_tool,
    stream_studio_tool,
)
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk
from cygnusx.infrastructure.studio.manager import StudioSandboxUnavailableError

# ===== 假 manager：记录调用参数，按脚本产出事件 =====


class _FakeManager:
    def __init__(self) -> None:
        self.exec_calls: list[dict[str, Any]] = []
        self.read_file_calls: list[dict[str, Any]] = []
        self.exec_events: list[dict[str, Any]] = []
        self.edit_result: dict[str, Any] = {}
        self.read_result: dict[str, Any] = {}
        self.raise_on: dict[str, Exception] = {}

    def exec(self, session_id, language, code, timeout_sec=None, image=None, user_id=None):
        self.exec_calls.append(
            {
                "session_id": session_id,
                "language": language,
                "code": code,
                "timeout_sec": timeout_sec,
                "image": image,
                "user_id": user_id,
            }
        )
        events = self.exec_events

        async def _gen():
            for e in events:
                yield e

        return _gen()

    async def write_file(self, session_id, path, content, image=None, user_id=None):
        if "write" in self.raise_on:
            raise self.raise_on["write"]
        return {"path": path, "size": len(content)}

    async def edit_file(self, session_id, path, old_string, new_string, image=None, user_id=None):
        if "edit" in self.raise_on:
            raise self.raise_on["edit"]
        return self.edit_result

    async def read_file(self, session_id, path, offset=0, limit=200, image=None, user_id=None):
        self.read_file_calls.append(
            {"session_id": session_id, "path": path, "offset": offset, "limit": limit}
        )
        return self.read_result

    async def list_files(self, session_id, path="", image=None, user_id=None):
        return {
            "path": path,
            "entries": [{"name": "a.csv", "type": "file", "size": 3, "mtime": 1.0}],
        }

    async def browser_navigate(self, *args, **kwargs):
        return {"url": args[1], "title": "Example", "status": 200, "text": "ok", "links": []}

    async def browser_screenshot(self, *args, **kwargs):
        return {"path": "output/page.png", "size": 10}

    async def browser_click(self, *args, **kwargs):
        return {"selector": args[1], "url": "https://example.test"}

    async def browser_type(self, *args, **kwargs):
        return {"selector": args[1], "url": "https://example.test"}

    async def browser_press(self, *args, **kwargs):
        return {"selector": args[1], "key": args[2], "url": "https://example.test"}

    async def browser_close(self, *args, **kwargs):
        return {"closed": True}

    async def document_call(self, session_id, endpoint, payload, image=None, user_id=None):
        return {"endpoint": endpoint, **payload}

    async def onlyoffice_status(self, *args, **kwargs):
        return {"configured": False, "reachable": False}


@pytest.fixture
def fake_manager(monkeypatch) -> _FakeManager:
    fake = _FakeManager()
    monkeypatch.setattr(studio_tools, "studio_sandbox_manager", fake)
    return fake


# ===== schema 合法性 =====


@pytest.mark.unit
def test_tool_schemas_cover_all_tools():
    """全部 Studio 内置工具均提供 OpenAI schema。

    tool_orchestrate 的 schema 独立成 TOOL_ORCHESTRATE_SCHEMA（不进
    STUDIO_TOOL_SCHEMAS），由 chat_service 按 agent features.ptc_enabled 条件挂载。
    """
    names = {t["function"]["name"] for t in (*STUDIO_TOOL_SCHEMAS, TOOL_ORCHESTRATE_SCHEMA)}
    assert names == set(STUDIO_TOOL_NAMES)
    assert len(STUDIO_TOOL_SCHEMAS) + 1 == len(STUDIO_TOOL_NAMES)
    assert {
        "datahub_import",
        "platform_result_import",
        "artifact_register",
        "update_plan",
        "pipeline_query",
        "knowledge_search",
        "browser_navigate",
        "browser_screenshot",
        "browser_click",
        "browser_type",
        "browser_press",
        "browser_close",
        "document_inspect",
        "document_create",
        "document_edit",
        "document_convert",
        "onlyoffice_status",
        "onlyoffice_convert",
        "ask_user",
    } <= names


@pytest.mark.unit
def test_tool_schemas_openai_format_and_serializable():
    """每个 schema 都是合法 OpenAI function 格式，且可 JSON 序列化（要进 LLM 请求体）"""
    for tool in STUDIO_TOOL_SCHEMAS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["name"] and fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict)
        assert isinstance(params["required"], list)
        for req in params["required"]:
            assert req in params["properties"]
    json.dumps(STUDIO_TOOL_SCHEMAS, ensure_ascii=False)


@pytest.mark.unit
def test_tool_schemas_required_params():
    """关键必填参数契约"""
    by_name = {t["function"]["name"]: t for t in STUDIO_TOOL_SCHEMAS}
    assert by_name["sandbox_execute"]["function"]["parameters"]["required"] == [
        "language",
        "code",
    ]
    assert by_name["workspace_edit"]["function"]["parameters"]["required"] == [
        "path",
        "old_string",
        "new_string",
    ]
    assert by_name["workspace_read"]["function"]["parameters"]["required"] == ["path"]
    lang = by_name["sandbox_execute"]["function"]["parameters"]["properties"]["language"]
    assert lang["enum"] == ["python", "r", "bash"]
    # P1 平台联动工具必填参数契约
    assert by_name["datahub_import"]["function"]["parameters"]["required"] == ["file_id"]
    assert by_name["platform_result_import"]["function"]["parameters"]["required"] == [
        "report_id"
    ]
    assert by_name["artifact_register"]["function"]["parameters"]["required"] == [
        "path",
        "title",
    ]
    assert by_name["update_plan"]["function"]["parameters"]["required"] == ["steps"]
    assert by_name["pipeline_query"]["function"]["parameters"]["required"] == []
    assert by_name["knowledge_search"]["function"]["parameters"]["required"] == ["query"]
    plan_status = by_name["update_plan"]["function"]["parameters"]["properties"]["steps"][
        "items"
    ]["properties"]["status"]
    assert plan_status["enum"] == ["pending", "in_progress", "done"]


@pytest.mark.unit
def test_system_prompt_suffix_mentions_workspace_rules():
    """系统提示词后缀包含工作区约定与代码透明原则"""
    assert "/workspace" in STUDIO_SYSTEM_PROMPT_SUFFIX
    assert "output" in STUDIO_SYSTEM_PROMPT_SUFFIX
    assert "200" in STUDIO_SYSTEM_PROMPT_SUFFIX  # read 默认 200 行
    assert "代码透明" in STUDIO_SYSTEM_PROMPT_SUFFIX


@pytest.mark.unit
def test_system_prompt_suffix_mentions_p1_platform_tools():
    """系统提示词后缀引导使用 P1 平台联动工具（计划/数据引入/产物登记）"""
    assert "update_plan" in STUDIO_SYSTEM_PROMPT_SUFFIX
    assert "datahub_import" in STUDIO_SYSTEM_PROMPT_SUFFIX
    assert "artifact_register" in STUDIO_SYSTEM_PROMPT_SUFFIX
    assert "pipeline_query" in STUDIO_SYSTEM_PROMPT_SUFFIX
    assert "knowledge_search" in STUDIO_SYSTEM_PROMPT_SUFFIX


# ===== sandbox_execute =====


@pytest.mark.unit
async def test_sandbox_execute_happy_path(fake_manager: _FakeManager):
    """正常执行：llm/ui 双通道齐全，on_output 收到流式增量，session/image 透传"""
    fake_manager.exec_events = [
        {"type": "stdout", "data": "hello"},
        {"type": "stderr", "data": "warn"},
        {
            "type": "result",
            "exit_code": 0,
            "duration_ms": 42,
            "artifacts": [{"path": "output/a.png", "size": 10, "mtime": 1.0}],
        },
    ]
    deltas: list[tuple[str, str]] = []

    async def on_output(stream: str, data: str) -> None:
        deltas.append((stream, data))

    result = await execute_studio_tool(
        "sandbox_execute",
        {"language": "python", "code": "print(1)"},
        "sess-1",
        image="cygnusx-sandbox:bio",
        on_output=on_output,
    )

    assert result["success"] is True
    payload = result["result"]
    llm, ui = payload["llm_payload"], payload["ui_payload"]
    assert llm["exit_code"] == 0
    assert llm["stdout"] == "hello"
    assert llm["stderr"] == "warn"
    assert llm["artifacts"] == [{"path": "output/a.png", "size": 10, "mtime": 1.0}]
    assert "output_truncated" not in llm
    assert ui["duration_ms"] == 42
    assert ui["language"] == "python"

    assert deltas == [("stdout", "hello"), ("stderr", "warn")]
    assert fake_manager.exec_calls[0]["session_id"] == "sess-1"
    assert fake_manager.exec_calls[0]["image"] == "cygnusx-sandbox:bio"


@pytest.mark.unit
async def test_sandbox_execute_llm_output_tail_truncated(fake_manager: _FakeManager):
    """超长输出：llm_payload 只留尾部 ≤3000 字符并标注截断，ui_payload 保留更多"""
    fake_manager.exec_events = [
        {"type": "stdout", "data": "x" * 5000},
        {"type": "result", "exit_code": 0, "duration_ms": 1, "artifacts": []},
    ]
    result = await execute_studio_tool("sandbox_execute", {"code": "x"}, "sess-1")

    payload = result["result"]
    assert len(payload["llm_payload"]["stdout"]) == 2000
    assert payload["llm_payload"]["output_truncated"] is True
    assert "note" in payload["llm_payload"]
    assert len(payload["ui_payload"]["stdout"]) == 5000


@pytest.mark.unit
async def test_sandbox_execute_ui_output_is_bounded(fake_manager: _FakeManager):
    """异常多增量输出也不会在 Web 工具结果中无限累积。"""
    fake_manager.exec_events = [
        {"type": "stdout", "data": "x" * 15000},
        {"type": "stdout", "data": "y" * 15000},
        {"type": "result", "exit_code": 0, "duration_ms": 1, "artifacts": []},
    ]

    result = await execute_studio_tool("sandbox_execute", {"code": "x"}, "sess-1")
    payload = result["result"]

    assert len(payload["ui_payload"]["stdout"]) == 20000
    assert len(payload["llm_payload"]["stdout"]) == 2000
    assert payload["llm_payload"]["output_truncated"] is True


@pytest.mark.unit
async def test_stream_studio_tool_uses_bounded_queue(fake_manager: _FakeManager, monkeypatch):
    """tool_output 队列有上限，慢客户端会反压工具执行而不是无限排队。"""
    queue_sizes: list[int] = []
    queue_type = studio_tools.asyncio.Queue

    class _ObservedQueue(queue_type):
        def __init__(self, maxsize=0):
            queue_sizes.append(maxsize)
            super().__init__(maxsize=maxsize)

    monkeypatch.setattr(studio_tools.asyncio, "Queue", _ObservedQueue)
    fake_manager.exec_events = [
        {"type": "stdout", "data": "hello"},
        {"type": "result", "exit_code": 0, "duration_ms": 1, "artifacts": []},
    ]

    items = [item async for item in stream_studio_tool("sandbox_execute", {"code": "x"}, "sess-1")]

    assert queue_sizes == [32]
    assert any(isinstance(item, ChatChunk) and item.type == "tool_output" for item in items)


@pytest.mark.unit
async def test_sandbox_execute_nonzero_exit_not_tool_failure(fake_manager: _FakeManager):
    """非零退出码不算工具失败：结果照常回灌给模型解读"""
    fake_manager.exec_events = [
        {"type": "stderr", "data": "Traceback ..."},
        {"type": "result", "exit_code": 1, "duration_ms": 5, "artifacts": []},
    ]
    result = await execute_studio_tool("sandbox_execute", {"code": "x"}, "sess-1")
    assert result["success"] is True
    assert result["result"]["llm_payload"]["exit_code"] == 1


@pytest.mark.unit
async def test_sandbox_execute_rejects_bad_language(fake_manager: _FakeManager):
    result = await execute_studio_tool(
        "sandbox_execute", {"language": "julia", "code": "x"}, "sess-1"
    )
    assert result["success"] is False
    assert "不支持的语言" in result["result"]["llm_payload"]["error"]


@pytest.mark.unit
async def test_sandbox_execute_over_ten_minutes_queues_background_task(
    fake_manager: _FakeManager, monkeypatch
):
    """显式超时超过 600 秒时创建任务中心记录，不占用聊天请求执行沙盒。"""
    submitted: dict[str, Any] = {}

    async def fake_submit(**kwargs):
        submitted.update(kwargs)
        return {
            "task_id": "task-1",
            "task_type": "studio_sandbox",
            "status": "queued",
            "task_url": "/api/v1/tasks/task-1",
            "progress_url": "/api/v1/tasks/task-1/progress",
            "result_url": "/studio/sess-1",
        }

    monkeypatch.setattr(
        "cygnusx.application.services.studio_task_service.submit_studio_sandbox_task",
        fake_submit,
    )
    result = await execute_studio_tool(
        "sandbox_execute",
        {"language": "python", "code": "run()", "timeout": 601},
        "sess-1",
        image="cygnusx-sandbox:bio",
        user_id="11111111-1111-1111-1111-111111111111",
    )

    assert result["success"] is True
    assert result["result"]["ui_payload"]["task_id"] == "task-1"
    assert result["result"]["ui_payload"]["task_url"] == "/api/v1/tasks/task-1"
    assert submitted["timeout_sec"] == 601
    assert submitted["image"] == "cygnusx-sandbox:bio"
    assert fake_manager.exec_calls == []


@pytest.mark.unit
async def test_sandbox_execute_long_task_timeout_is_clamped(
    fake_manager: _FakeManager, monkeypatch
):
    """后台任务沿用 sandbox-agent 的 3600 秒最大超时约束。"""
    submitted: dict[str, Any] = {}

    async def fake_submit(**kwargs):
        submitted.update(kwargs)
        return {
            "task_id": "task-2",
            "task_type": "studio_sandbox",
            "status": "queued",
            "task_url": "/api/v1/tasks/task-2",
            "progress_url": "/api/v1/tasks/task-2/progress",
            "result_url": "/studio/sess-1",
        }

    monkeypatch.setattr(
        "cygnusx.application.services.studio_task_service.submit_studio_sandbox_task",
        fake_submit,
    )
    await execute_studio_tool(
        "sandbox_execute",
        {"language": "bash", "code": "sleep 1", "timeout": 9999},
        "sess-1",
        user_id="11111111-1111-1111-1111-111111111111",
    )

    assert submitted["timeout_sec"] == 3600
    assert fake_manager.exec_calls == []


@pytest.mark.unit
async def test_sandbox_execute_ten_minutes_stays_inline(fake_manager: _FakeManager):
    """600 秒是同步执行边界，只有严格超过阈值才进入 Celery。"""
    fake_manager.exec_events = [
        {"type": "result", "exit_code": 0, "duration_ms": 1, "artifacts": []}
    ]
    result = await execute_studio_tool(
        "sandbox_execute",
        {"language": "python", "code": "print(1)", "timeout": 600},
        "sess-1",
        user_id="11111111-1111-1111-1111-111111111111",
    )

    assert result["success"] is True
    assert fake_manager.exec_calls[0]["timeout_sec"] == 600


@pytest.mark.unit
async def test_browser_and_document_tools_dispatch(fake_manager: _FakeManager):
    browser = await execute_studio_tool(
        "browser_navigate", {"url": "https://example.test"}, "sess-1", user_id="user-1"
    )
    document = await execute_studio_tool(
        "document_edit",
        {"path": "output/report.md", "operations": [{"old": "a", "new": "b"}]},
        "sess-1",
        user_id="user-1",
    )
    assert browser["success"] is True
    assert browser["result"]["llm_payload"]["status"] == 200
    assert document["success"] is True
    assert document["result"]["llm_payload"]["endpoint"] == "/document/edit"


# ===== workspace_edit / read / write =====


@pytest.mark.unit
async def test_workspace_edit_diff_passthrough(fake_manager: _FakeManager):
    """ui_payload 带完整 diff，llm_payload 保持紧凑"""
    diff = "--- a/s.py\n+++ b/s.py\n@@ -1 +1 @@\n-a\n+b\n"
    reverse = {"old_string": "context b", "new_string": "context a"}
    fake_manager.edit_result = {
        "path": "s.py", "diff": diff, "size": 2, "reverse_edit": reverse
    }
    result = await execute_studio_tool(
        "workspace_edit", {"path": "s.py", "old_string": "a", "new_string": "b"}, "sess-1"
    )

    assert result["success"] is True
    payload = result["result"]
    assert payload["ui_payload"]["diff"] == diff
    assert payload["ui_payload"]["reverse_edit"] == reverse
    assert "diff" not in payload["llm_payload"]
    assert payload["llm_payload"]["path"] == "s.py"


@pytest.mark.unit
async def test_workspace_read_respects_default_limit(fake_manager: _FakeManager):
    """不传 limit 时走 manager 默认 200 行（不在 dispatcher 里另设默认值）"""
    fake_manager.read_result = {"content": "1\n2", "total_lines": 2, "truncated": False}
    result = await execute_studio_tool("workspace_read", {"path": "a.csv"}, "sess-1")

    assert result["success"] is True
    call = fake_manager.read_file_calls[0]
    assert call["offset"] == 0
    assert call["limit"] == 200  # manager 签名默认值
    assert result["result"]["llm_payload"]["content"] == "1\n2"


@pytest.mark.unit
async def test_workspace_read_passes_explicit_limit(fake_manager: _FakeManager):
    fake_manager.read_result = {"content": "", "total_lines": 0, "truncated": False}
    await execute_studio_tool(
        "workspace_read", {"path": "a.csv", "offset": 10, "limit": 50}, "sess-1"
    )
    call = fake_manager.read_file_calls[0]
    assert call["offset"] == 10
    assert call["limit"] == 50


# ===== 异常收敛 =====


@pytest.mark.unit
async def test_agent_400_wrapped_as_friendly_error(fake_manager: _FakeManager):
    """sandbox-agent 的 4xx（如路径逃逸）收敛为 success=False + detail 透传"""
    fake_manager.raise_on["edit"] = httpx.HTTPStatusError(
        "Bad Request",
        request=httpx.Request("POST", "http://agent/files/edit"),
        response=httpx.Response(400, json={"detail": "old_string 未在文件中出现"}),
    )
    result = await execute_studio_tool(
        "workspace_edit", {"path": "s.py", "old_string": "a", "new_string": "b"}, "sess-1"
    )
    assert result["success"] is False
    error = result["result"]["llm_payload"]["error"]
    assert "old_string 未在文件中出现" in error


@pytest.mark.unit
async def test_sandbox_unavailable_wrapped(fake_manager: _FakeManager):
    """沙盒不可用（镜像未构建等）收敛为友好文案而非抛异常"""
    fake_manager.raise_on["write"] = StudioSandboxUnavailableError("沙盒容器启动失败: 镜像缺失")
    result = await execute_studio_tool(
        "workspace_write", {"path": "a.py", "content": "1"}, "sess-1"
    )
    assert result["success"] is False
    error = result["result"]["llm_payload"]["error"]
    assert "沙盒暂不可用" in error
    assert "镜像缺失" in error


class _KnowledgeRows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _KnowledgeDb:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _KnowledgeRows(self.rows)

    async def scalar(self, _statement):
        return None


@pytest.mark.unit
async def test_knowledge_search_returns_bounded_published_excerpts():
    db = _KnowledgeDb(
        [
            (
                "rna-qc",
                "RNA-seq 质量控制",
                "RNA-seq",
                "开头说明。" + "x" * 240 + "FastQC 指标解释" + "y" * 800,
                "质量控制",
                1.0,
            ),
        ]
    )

    result = await execute_studio_tool(
        "knowledge_search",
        {"query": "FastQC", "limit": 5},
        "sess-1",
        db=db,  # type: ignore[arg-type]
        user_id="user-1",
    )

    assert result["success"] is True
    payload = result["result"]["llm_payload"]
    assert payload["total"] == 1
    assert payload["results"][0]["doc_id"] == "rna-qc"
    assert len(payload["results"][0]["excerpt"]) <= 602
    assert payload["results"][0]["url"] == "/knowledge/rna-qc"
    compiled = str(db.statement)
    assert "kb_documents.status" in compiled


@pytest.mark.unit
async def test_knowledge_search_requires_db_and_query():
    missing_db = await execute_studio_tool(
        "knowledge_search", {"query": "RNA"}, "sess-1"
    )
    assert missing_db["success"] is False
    missing_query = await execute_studio_tool(
        "knowledge_search", {"query": ""}, "sess-1", db=_KnowledgeDb([])  # type: ignore[arg-type]
    )
    assert missing_query["success"] is False


@pytest.mark.unit
async def test_unknown_tool_rejected():
    result = await execute_studio_tool("not_a_tool", {}, "sess-1")
    assert result["success"] is False
    assert "未知 Studio 工具" in result["result"]["llm_payload"]["error"]


# ===== 流式包装 =====


@pytest.mark.unit
async def test_stream_studio_tool_yields_output_then_result(fake_manager: _FakeManager):
    """stream_studio_tool：先 tool_output ChatChunk，最后一项为结果信封"""
    fake_manager.exec_events = [
        {"type": "stdout", "data": "line1"},
        {"type": "stdout", "data": "line2"},
        {"type": "result", "exit_code": 0, "duration_ms": 3, "artifacts": []},
    ]
    items = [
        item
        async for item in stream_studio_tool(
            "sandbox_execute", {"language": "bash", "code": "echo hi"}, "sess-1"
        )
    ]

    chunks = [i for i in items if isinstance(i, ChatChunk)]
    results = [i for i in items if isinstance(i, dict)]
    assert len(chunks) == 2
    assert all(c.type == "tool_output" for c in chunks)
    assert chunks[0].metadata == {
        "tool": "sandbox_execute",
        "tool_call_id": "",
        "stream": "stdout",
        "data": "line1",
    }
    assert len(results) == 1
    assert results[0]["success"] is True
    assert results[0]["result"]["llm_payload"]["stdout"] == "line1\nline2"


@pytest.mark.unit
async def test_stream_studio_tool_non_exec_has_no_output_events(fake_manager: _FakeManager):
    """非 sandbox_execute 工具只产出结果信封，无 tool_output"""
    items = [
        item
        async for item in stream_studio_tool(
            "workspace_write", {"path": "a.py", "content": "1"}, "sess-1"
        )
    ]
    assert len(items) == 1
    assert isinstance(items[0], dict)
    assert items[0]["success"] is True


# ===== ask_user 参数归一化 =====


@pytest.mark.unit
def test_normalize_ask_questions_multi():
    """questions[] 多问题原样保留，过滤空问题与非字符串选项"""
    from cygnusx.application.services.chat_service import _normalize_ask_questions

    result = _normalize_ask_questions(
        {
            "questions": [
                {"question": "过滤标准？", "options": ["bcftools 推荐阈值", "自定义", ""]},
                {"question": ""},
                "not-a-dict",
                {"question": "输出格式？"},
            ]
        }
    )
    assert result == [
        {"question": "过滤标准？", "options": ["bcftools 推荐阈值", "自定义"]},
        {"question": "输出格式？", "options": []},
    ]


@pytest.mark.unit
def test_normalize_ask_questions_json_string():
    """模型把 questions 数组序列化成 JSON 字符串传来时，解析还原为问题列表"""
    from cygnusx.application.services.chat_service import _normalize_ask_questions

    result = _normalize_ask_questions(
        {
            "questions": '\n[{"question": "数据在哪里？", "options": ["工作区已有文件", "现在上传", "用平台示例数据演示（推荐）"]}, {"question": "数据格式？"}]\n'
        }
    )
    assert result == [
        {"question": "数据在哪里？", "options": ["工作区已有文件", "现在上传", "用平台示例数据演示（推荐）"]},
        {"question": "数据格式？", "options": []},
    ]


@pytest.mark.unit
def test_normalize_ask_questions_json_string_with_trailing_junk():
    """回归（2026-08-09）：模型在字符串化 JSON 尾部多塞引号/换行时，raw_decode
    取第一个完整 JSON 值、忽略尾部垃圾；此前 json.loads 直接失败，问题与选项
    全部丢失，前端降级成没有选项的自由输入卡。"""
    from cygnusx.application.services.chat_service import _normalize_ask_questions

    # 生产实录载荷：前导 \n + 合法 JSON 数组 + 尾部多余 " 与 \n\n
    result = _normalize_ask_questions(
        {
            "questions": '\n[{"question": "火山图需要逐基因的差异表达结果文件。你的数据在哪里？", "options": ["工作区里有逐基因结果文件（帮我找一下）", "我来上传逐基因的 edgeR/DESeq2 结果表", "没有逐基因数据，先用示例数据演示火山图"]}]"\n\n'
        }
    )
    assert result == [
        {
            "question": "火山图需要逐基因的差异表达结果文件。你的数据在哪里？",
            "options": [
                "工作区里有逐基因结果文件（帮我找一下）",
                "我来上传逐基因的 edgeR/DESeq2 结果表",
                "没有逐基因数据，先用示例数据演示火山图",
            ],
        }
    ]


@pytest.mark.unit
def test_normalize_ask_questions_legacy_single():
    """兼容旧单问题 question+options"""
    from cygnusx.application.services.chat_service import _normalize_ask_questions

    result = _normalize_ask_questions({"question": "物种？", "options": ["人", "小鼠"]})
    assert result == [{"question": "物种？", "options": ["人", "小鼠"]}]


@pytest.mark.unit
def test_normalize_ask_questions_empty_fallback():
    """模型未给出有效问题时兜底一个空问题（前端渲染自由输入，保证用户可回复）"""
    from cygnusx.application.services.chat_service import _normalize_ask_questions

    assert _normalize_ask_questions({}) == [{"question": "", "options": []}]
    assert _normalize_ask_questions({"question": "  "}) == [{"question": "", "options": []}]
    assert _normalize_ask_questions({"questions": "not-a-list"}) == [
        {"question": "", "options": []}
    ]


@pytest.mark.unit
def test_normalize_ask_questions_capped_at_five():
    """问题数量上限 5 个"""
    from cygnusx.application.services.chat_service import _normalize_ask_questions

    result = _normalize_ask_questions(
        {"questions": [{"question": f"q{i}"} for i in range(8)]}
    )
    assert len(result) == 5
