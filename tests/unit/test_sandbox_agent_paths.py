"""sandbox-agent 路径防护单元测试（无需 Docker，直接导入纯函数）"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_AGENT_PATH = Path(__file__).resolve().parents[2] / "deploy" / "studio" / "sandbox_agent.py"
_spec = importlib.util.spec_from_file_location("sandbox_agent", _AGENT_PATH)
assert _spec is not None and _spec.loader is not None
sandbox_agent = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("sandbox_agent", sandbox_agent)
_spec.loader.exec_module(sandbox_agent)

resolve_workspace_path = sandbox_agent.resolve_workspace_path
PathEscapeError = sandbox_agent.PathEscapeError


@pytest.mark.unit
def test_relative_path_resolves_inside_root(tmp_path: Path):
    """普通相对路径解析到工作区内"""
    resolved = resolve_workspace_path("output/plot.png", root=tmp_path)
    assert resolved == tmp_path / "output" / "plot.png"


@pytest.mark.unit
def test_dotdot_escape_rejected(tmp_path: Path):
    """../ 逃逸被拒绝"""
    with pytest.raises(PathEscapeError):
        resolve_workspace_path("../etc/passwd", root=tmp_path)
    with pytest.raises(PathEscapeError):
        resolve_workspace_path("a/../../outside", root=tmp_path)


@pytest.mark.unit
def test_absolute_path_outside_root_rejected(tmp_path: Path):
    """工作区外的绝对路径被拒绝"""
    with pytest.raises(PathEscapeError):
        resolve_workspace_path("/etc/passwd", root=tmp_path)


@pytest.mark.unit
def test_absolute_path_inside_root_allowed(tmp_path: Path):
    """工作区内的绝对路径允许"""
    resolved = resolve_workspace_path(str(tmp_path / "input" / "data.csv"), root=tmp_path)
    assert resolved == tmp_path / "input" / "data.csv"


@pytest.mark.unit
def test_symlink_escape_rejected(tmp_path: Path):
    """软链解析后越界同样被拒绝"""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    try:
        link = tmp_path / "evil-link"
        link.symlink_to(outside)
        with pytest.raises(PathEscapeError):
            resolve_workspace_path("evil-link/secret.txt", root=tmp_path)
    finally:
        (tmp_path / "evil-link").unlink(missing_ok=True)
        outside.rmdir()


@pytest.mark.unit
def test_root_itself_allowed(tmp_path: Path):
    """工作区根目录本身合法"""
    assert resolve_workspace_path(".", root=tmp_path) == tmp_path


@pytest.mark.unit
def test_protected_write_prefixes_rejected(tmp_path: Path, monkeypatch):
    """input/ 与 ref/ 前缀的写、编辑、删除、重命名、创建目录统一返回 403。"""
    monkeypatch.setattr(sandbox_agent, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(sandbox_agent, "PLATFORM_MOUNT_ROOT", tmp_path / "platform")
    (tmp_path / "input").mkdir()
    (tmp_path / "ref").mkdir()
    (tmp_path / "output").mkdir()

    client = TestClient(sandbox_agent.app)

    # write
    assert client.post("/files/write", json={"path": "input/foo.txt", "content": "x"}).status_code == 403
    assert client.post("/files/write", json={"path": "ref/foo.txt", "content": "x"}).status_code == 403
    assert client.post("/files/write", json={"path": "output/foo.txt", "content": "x"}).status_code == 200

    # mkdir
    assert client.post("/files/mkdir", json={"path": "input/sub"}).status_code == 403
    assert client.post("/files/mkdir", json={"path": "ref/sub"}).status_code == 403
    assert client.post("/files/mkdir", json={"path": "output/sub"}).status_code == 200

    # edit
    (tmp_path / "output" / "editable.txt").write_text("hello", encoding="utf-8")
    edit_payload = {"path": "input/foo.txt", "old_string": "a", "new_string": "b"}
    assert client.post("/files/edit", json=edit_payload).status_code == 403
    edit_payload["path"] = "ref/foo.txt"
    assert client.post("/files/edit", json=edit_payload).status_code == 403
    assert (
        client.post(
            "/files/edit",
            json={"path": "output/editable.txt", "old_string": "hello", "new_string": "world"},
        ).status_code
        == 200
    )

    # rename
    (tmp_path / "output" / "src.txt").write_text("x", encoding="utf-8")
    assert (
        client.post("/files/rename", json={"path": "input/foo.txt", "new_path": "output/x.txt"}).status_code
        == 403
    )
    assert (
        client.post("/files/rename", json={"path": "output/src.txt", "new_path": "input/x.txt"}).status_code
        == 403
    )
    assert (
        client.post("/files/rename", json={"path": "output/src.txt", "new_path": "output/dst.txt"}).status_code
        == 200
    )

    # delete
    assert client.delete("/files/delete", params={"path": "input/foo.txt"}).status_code == 403
    assert client.delete("/files/delete", params={"path": "ref/foo.txt"}).status_code == 403
    assert client.delete("/files/delete", params={"path": "output/dst.txt"}).status_code == 200


# ===== 读路径放行（P1 数据不搬家：input/ 软链 → /data/platform 只读挂载） =====

resolve_workspace_read_path = sandbox_agent.resolve_workspace_read_path
PLATFORM_MOUNT_ROOT = sandbox_agent.PLATFORM_MOUNT_ROOT


@pytest.mark.unit
def test_read_path_inside_workspace_not_via_platform(tmp_path: Path):
    """工作区内读路径照常放行，via_platform=False"""
    resolved, via_platform = resolve_workspace_read_path("output/a.png", root=tmp_path)
    assert resolved == tmp_path / "output" / "a.png"
    assert via_platform is False


@pytest.mark.unit
def test_read_path_platform_symlink_allowed(tmp_path: Path):
    """input/ 下指向平台挂载的软链：读放行，返回容器内 /data/platform 路径"""
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "x.csv").symlink_to(str(PLATFORM_MOUNT_ROOT / "raw/x.csv"))
    resolved, via_platform = resolve_workspace_read_path("input/x.csv", root=tmp_path)
    assert via_platform is True
    assert resolved == PLATFORM_MOUNT_ROOT / "raw/x.csv"


@pytest.mark.unit
def test_read_path_direct_platform_absolute_rejected(tmp_path: Path):
    """直接拼平台挂载绝对路径被拒绝（只允许经工作区内软链跳转）"""
    with pytest.raises(PathEscapeError):
        resolve_workspace_read_path(str(PLATFORM_MOUNT_ROOT / "raw/x.csv"), root=tmp_path)


@pytest.mark.unit
def test_read_path_write_guard_unaffected(tmp_path: Path):
    """写守卫 resolve_workspace_path 对平台软链依然拒绝"""
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "x.csv").symlink_to(str(PLATFORM_MOUNT_ROOT / "raw/x.csv"))
    with pytest.raises(PathEscapeError):
        resolve_workspace_path("input/x.csv", root=tmp_path)

# ===== 执行输出边界 =====


@pytest.mark.unit
async def test_exec_stream_caps_output_and_persists_full_log(tmp_path: Path, monkeypatch):
    """流式 data 严格不超过 10KB，截断时 .logs 保存完整原始输出。"""
    monkeypatch.setattr(sandbox_agent, "WORKSPACE_ROOT", tmp_path)
    (tmp_path / "output").mkdir()
    payload = "x" * 30000
    request = sandbox_agent.ExecRequest(
        language="python", code=f'print("{payload}")', timeout=10
    )

    events = [
        json.loads(chunk.decode("utf-8"))
        async for chunk in sandbox_agent._stream_exec(request)
    ]

    streamed = "".join(
        event.get("data", "") for event in events if event.get("type") == "stdout"
    )
    result = next(event for event in events if event.get("type") == "result")
    assert len(streamed.encode("utf-8")) <= sandbox_agent.STREAM_CAP_BYTES
    assert result["exit_code"] == 0
    assert result["truncated_output_files"]
    log_path = tmp_path / result["truncated_output_files"][0]
    assert log_path.read_text(encoding="utf-8") == payload + "\n"


@pytest.mark.unit
async def test_exec_stream_termination_kills_process_group_when_consumer_disconnects(
    tmp_path: Path, monkeypatch
):
    """关闭 NDJSON 消费者时，执行进程组必须立即被终止。"""
    monkeypatch.setattr(sandbox_agent, "WORKSPACE_ROOT", tmp_path)
    (tmp_path / "output").mkdir()
    observed_signals: list[int] = []
    original_killpg = sandbox_agent.os.killpg

    def track_killpg(pid: int, sig: int) -> None:
        observed_signals.append(sig)
        original_killpg(pid, sig)

    monkeypatch.setattr(sandbox_agent.os, "killpg", track_killpg)
    stream = sandbox_agent._stream_exec(
        sandbox_agent.ExecRequest(
            language="python",
            code="import time\nprint('ready', flush=True)\ntime.sleep(60)",
            timeout=120,
        )
    )

    first_event = json.loads((await anext(stream)).decode("utf-8"))
    assert first_event == {"type": "stdout", "data": "ready\n"}
    await asyncio.wait_for(stream.aclose(), timeout=5)

    assert sandbox_agent.signal.SIGKILL in observed_signals


# ===== workspace_edit 反向上下文 =====

_reverse_edit_payload = sandbox_agent._reverse_edit_payload


@pytest.mark.unit
def test_reverse_edit_payload_uses_context_for_repeated_replacement():
    old = "alpha\nvalue = 1\nomega\nvalue = 2\n"
    old_string = "value = 1"
    new_string = "value = 2"
    index = old.index(old_string)
    new = old.replace(old_string, new_string, 1)

    reverse = _reverse_edit_payload(old, new, index, old_string, new_string)

    assert reverse is not None
    assert new.count(reverse["old_string"]) == 1
    assert new.replace(reverse["old_string"], reverse["new_string"], 1) == old


@pytest.mark.unit
def test_reverse_edit_payload_supports_deletion():
    old = "before\nremove me\nafter\n"
    old_string = "remove me\n"
    index = old.index(old_string)
    new = old.replace(old_string, "", 1)

    reverse = _reverse_edit_payload(old, new, index, old_string, "")

    assert reverse is not None
    assert reverse["old_string"]
    assert new.replace(reverse["old_string"], reverse["new_string"], 1) == old


@pytest.mark.unit
def test_reverse_edit_payload_returns_none_for_empty_result():
    assert _reverse_edit_payload("all", "", 0, "all", "") is None

@pytest.mark.unit
def test_workspace_quota_rejects_excess_write(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_agent, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(sandbox_agent, "WORKSPACE_QUOTA_BYTES", 4)
    (tmp_path / "existing.txt").write_text("1234", encoding="utf-8")

    with pytest.raises(sandbox_agent.HTTPException) as exc_info:
        sandbox_agent._check_workspace_quota(1)

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail["code"] == "quota_exceeded"


@pytest.mark.unit
async def test_document_text_create_inspect_and_edit(tmp_path: Path, monkeypatch):
    """文档工具在无 Docker 的情况下完成文本文档的创建、检查和编辑。"""
    monkeypatch.setattr(sandbox_agent, "WORKSPACE_ROOT", tmp_path)
    created = await sandbox_agent.document_create(
        sandbox_agent.DocumentCreateRequest(
            path="output/report.md", title="Report", content="before\nvalue"
        )
    )
    assert created["format"] == "md"

    inspected = await sandbox_agent.document_inspect(
        sandbox_agent.DocumentInspectRequest(path="output/report.md")
    )
    assert "before" in inspected["preview"]

    edited = await sandbox_agent.document_edit(
        sandbox_agent.DocumentEditRequest(
            path="output/report.md", operations=[{"old": "before", "new": "after"}]
        )
    )
    assert edited["changed"] == 1
    assert "after" in (tmp_path / "output/report.md").read_text(encoding="utf-8")


@pytest.mark.unit
async def test_document_pptx_create_inspect_and_edit(tmp_path: Path, monkeypatch):
    pytest.importorskip("pptx")
    monkeypatch.setattr(sandbox_agent, "WORKSPACE_ROOT", tmp_path)
    created = await sandbox_agent.document_create(
        sandbox_agent.DocumentCreateRequest(
            path="output/report.pptx", title="Report", content="before"
        )
    )
    assert created["format"] == "pptx"

    inspected = await sandbox_agent.document_inspect(
        sandbox_agent.DocumentInspectRequest(path="output/report.pptx")
    )
    assert inspected["slides"] == 1
    assert "before" in inspected["preview"]

    edited = await sandbox_agent.document_edit(
        sandbox_agent.DocumentEditRequest(
            path="output/report.pptx", operations=[{"old": "before", "new": "after"}]
        )
    )
    assert edited["changed"] == 1
