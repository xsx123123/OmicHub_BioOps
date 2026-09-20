"""声明式环境还原（WP2 任务 3）单元测试。

覆盖：
- workspace_env_restore_service：文件检测优先级、还原脚本生成、超时约定、
  失败摘要、missing_env_snapshot 审计查询、audit_logs 写入；
- StudioSandboxManager 还原钩子：每容器生命周期一次、跳过路径、失败降级
  不阻断、容器重建后重新检测、stop 清理状态。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cygnusx.application.services import workspace_env_restore_service as svc
from cygnusx.application.services.workspace_env_restore_service import (
    EnvRestoreResult,
    build_restore_script,
    detect_restore_file,
    restore_timeout_seconds,
    summarize_failure,
)
from cygnusx.infrastructure.studio.manager import SandboxHandle, StudioSandboxManager


def _workspace(tmp_path: Path, session_id: str = "sess-env") -> Path:
    workspace = tmp_path / "ws" / session_id
    workspace.mkdir(parents=True)
    return workspace


# ------------------------------------------------------------------
# service 纯逻辑
# ------------------------------------------------------------------


@pytest.mark.unit
def test_detect_restore_file_explicit_first(tmp_path: Path):
    workspace = _workspace(tmp_path)
    assert detect_restore_file(workspace) is None
    (workspace / "environment.yml").write_text("dependencies: []\n", encoding="utf-8")
    assert detect_restore_file(workspace) == "environment.yml"
    (workspace / "conda-explicit.txt").write_text("@EXPLICIT\n", encoding="utf-8")
    assert detect_restore_file(workspace) == "conda-explicit.txt"


@pytest.mark.unit
def test_build_restore_script_explicit():
    script = build_restore_script("conda-explicit.txt")
    assert "micromamba install --yes --name base --file /workspace/conda-explicit.txt" in script


@pytest.mark.unit
def test_build_restore_script_yml_strips_name_prefix():
    script = build_restore_script("environment.yml")
    assert "sed -e '/^name:/d' -e '/^prefix:/d'" in script
    assert "micromamba install --yes --name base --file /tmp/cygnusx-env-restore.yml" in script


@pytest.mark.unit
def test_build_restore_script_rejects_unknown():
    with pytest.raises(ValueError):
        build_restore_script("pip-freeze.txt")


@pytest.mark.unit
def test_restore_timeout_convention():
    """下限 900s（默认 exec 600s 会被抬高），封顶 3600s（agent 上限）"""
    assert restore_timeout_seconds(600) == 900
    assert restore_timeout_seconds(1200) == 1200
    assert restore_timeout_seconds(99999) == 3600


@pytest.mark.unit
def test_summarize_failure_single_line_bounded():
    summary = summarize_failure("line1\nline2 " + "x" * 1000, 1)
    assert summary.startswith("exit_code=1:")
    assert "\n" not in summary
    assert len(summary) <= 320
    assert summarize_failure("", 3) == "exit_code=3"


# ------------------------------------------------------------------
# service DB 访问（mock session factory）
# ------------------------------------------------------------------


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return iter(self._rows)


class _FakeDb:
    """记录 add 的模型并 commit；execute 返回预置行。"""

    def __init__(self, rows=None):
        self.added = []
        self.committed = False
        self._rows = rows or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, _stmt):
        return _FakeResult(self._rows)

    def add(self, model):
        self.added.append(model)

    async def commit(self):
        self.committed = True


def _packed_audit_row(missing):
    row = MagicMock()
    row.detail = {
        "event": "workspace_archive_packed",
        "missing_env_snapshot": missing,
    }
    return row


@pytest.mark.unit
async def test_latest_missing_env_snapshot_from_pack_audit(monkeypatch):
    db = _FakeDb([_packed_audit_row(["conda-explicit.txt", "pip-freeze.txt"])])
    monkeypatch.setattr(svc, "get_session_factory", lambda: (lambda: db))
    missing = await svc.latest_missing_env_snapshot("sess-1")
    assert missing == ["conda-explicit.txt", "pip-freeze.txt"]


@pytest.mark.unit
async def test_latest_missing_env_snapshot_none_when_no_audit(monkeypatch):
    db = _FakeDb([])
    monkeypatch.setattr(svc, "get_session_factory", lambda: (lambda: db))
    assert await svc.latest_missing_env_snapshot("sess-1") is None


@pytest.mark.unit
async def test_latest_missing_env_snapshot_db_error_swallowed(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "get_session_factory", _boom)
    assert await svc.latest_missing_env_snapshot("sess-1") is None


@pytest.mark.unit
async def test_write_restore_audit_success_row(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(svc, "get_session_factory", lambda: (lambda: db))
    result = EnvRestoreResult(
        status="restored", file="environment.yml", duration_ms=1234,
        reason=None, container_id="cid-1",
    )
    await svc.write_restore_audit(session_id="sess-1", user_id=str(uuid.uuid4()), result=result)
    assert db.committed and len(db.added) == 1
    row = db.added[0]
    assert row.resource_type == "workspace_env_restore"
    assert row.resource_id == "sess-1"
    assert row.status_code == 200
    assert row.detail["success"] is True
    assert row.detail["file"] == "environment.yml"
    assert row.detail["duration_ms"] == 1234


@pytest.mark.unit
async def test_write_restore_audit_failed_and_skipped_status(monkeypatch):
    rows = []
    for status in ("failed", "skipped"):
        db = _FakeDb()
        monkeypatch.setattr(svc, "get_session_factory", lambda d=db: (lambda: d))
        result = EnvRestoreResult(
            status=status, file=None, duration_ms=0,
            reason="r", container_id="cid-1",
        )
        await svc.write_restore_audit(session_id="sess-1", user_id=None, result=result)
        rows.append((db, result))
    assert rows[0][0].added[0].status_code == 500
    assert rows[0][0].added[0].detail["reason"] == "r"
    assert rows[1][0].added[0].status_code == 204


@pytest.mark.unit
async def test_write_restore_audit_db_error_swallowed(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "get_session_factory", _boom)
    result = EnvRestoreResult("restored", "environment.yml", 1, None, "cid-1")
    await svc.write_restore_audit(session_id="sess-1", user_id=None, result=result)


# ------------------------------------------------------------------
# manager 还原钩子
# ------------------------------------------------------------------


def _manager(tmp_path: Path) -> StudioSandboxManager:
    from cygnusx.infrastructure.config.studio_loader import StudioConfigManager

    yaml_path = tmp_path / "studio.yaml"
    yaml_path.write_text(
        f'studio:\n  mounts:\n    workspace: "{tmp_path}/ws"\n',
        encoding="utf-8",
    )
    return StudioSandboxManager(_config_manager=StudioConfigManager(config_path=yaml_path))


def _handle(workspace: Path, container_id: str = "cid-1") -> SandboxHandle:
    return SandboxHandle(
        session_id=workspace.name,
        container_id=container_id,
        container_name=f"studio-{workspace.name[:8]}",
        agent_url="http://studio-agent",
        agent_socket=workspace / ".agent.sock",
        image="img",
        workspace_dir=workspace,
    )


def _noop_audit(monkeypatch):
    monkeypatch.setattr(
        "cygnusx.application.services.workspace_env_restore_service.write_restore_audit",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.workspace_env_restore_service.latest_missing_env_snapshot",
        AsyncMock(return_value=None),
    )
    # WP3 任务 3 门控：这些用例验证还原执行链路本身，固定为"科研模式开启"放行
    monkeypatch.setattr(
        "cygnusx.application.services.workspace_env_restore_service.research_restore_gate_enabled",
        AsyncMock(return_value=(True, None)),
    )


@pytest.mark.unit
async def test_restore_skipped_without_files(tmp_path: Path, monkeypatch):
    _noop_audit(monkeypatch)
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    await manager._maybe_restore_environment(_handle(workspace))
    state = manager.env_restore_status(workspace.name)
    assert state is not None
    assert state["status"] == "skipped"
    assert "跳过" in state["reason"]
    # 同容器生命周期内不重复检测/审计
    svc.write_restore_audit.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.unit
async def test_restore_skipped_cites_missing_env_snapshot(tmp_path: Path, monkeypatch):
    _noop_audit(monkeypatch)
    svc.latest_missing_env_snapshot.return_value = [  # type: ignore[attr-defined]
        "conda-explicit.txt", "environment.yml"
    ]
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    await manager._maybe_restore_environment(_handle(workspace))
    state = manager.env_restore_status(workspace.name)
    assert state["status"] == "skipped"
    assert "missing_env_snapshot" in state["reason"] or "缺失环境四件套" in state["reason"]


@pytest.mark.unit
async def test_restore_runs_once_per_container_lifecycle(tmp_path: Path, monkeypatch):
    _noop_audit(monkeypatch)
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    (workspace / "environment.yml").write_text("dependencies: [tqdm]\n", encoding="utf-8")
    exec_mock = AsyncMock(return_value=(0, "", 5000))
    monkeypatch.setattr(manager, "_exec_env_restore", exec_mock)

    await manager._maybe_restore_environment(_handle(workspace, "cid-1"))
    await manager._maybe_restore_environment(_handle(workspace, "cid-1"))
    assert exec_mock.await_count == 1
    state = manager.env_restore_status(workspace.name)
    assert state["status"] == "restored"
    assert state["file"] == "environment.yml"
    assert state["duration_ms"] >= 0

    # 容器重建（新 container_id）后重新检测并再次执行
    await manager._maybe_restore_environment(_handle(workspace, "cid-2"))
    assert exec_mock.await_count == 2


@pytest.mark.unit
async def test_restore_failure_degrades_not_raises(tmp_path: Path, monkeypatch):
    _noop_audit(monkeypatch)
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    (workspace / "conda-explicit.txt").write_text("@EXPLICIT\n", encoding="utf-8")
    exec_mock = AsyncMock(return_value=(1, "PackagesNotFoundError: nope", 100))
    monkeypatch.setattr(manager, "_exec_env_restore", exec_mock)

    await manager._maybe_restore_environment(_handle(workspace))  # 不得抛异常
    state = manager.env_restore_status(workspace.name)
    assert state["status"] == "failed"
    assert "PackagesNotFoundError" in state["reason"]
    assert state["file"] == "conda-explicit.txt"
    # 失败后同容器不重试
    await manager._maybe_restore_environment(_handle(workspace))
    assert exec_mock.await_count == 1


@pytest.mark.unit
async def test_restore_hook_exception_degrades_not_raises(tmp_path: Path, monkeypatch):
    _noop_audit(monkeypatch)
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    (workspace / "environment.yml").write_text("dependencies: [tqdm]\n", encoding="utf-8")
    monkeypatch.setattr(
        manager, "_exec_env_restore", AsyncMock(side_effect=RuntimeError("agent socket down"))
    )
    await manager._maybe_restore_environment(_handle(workspace))
    state = manager.env_restore_status(workspace.name)
    assert state["status"] == "failed"
    assert "agent socket down" in state["reason"]


@pytest.mark.unit
async def test_explicit_takes_priority_over_yml(tmp_path: Path, monkeypatch):
    _noop_audit(monkeypatch)
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    (workspace / "environment.yml").write_text("dependencies: [tqdm]\n", encoding="utf-8")
    (workspace / "conda-explicit.txt").write_text("@EXPLICIT\n", encoding="utf-8")
    exec_mock = AsyncMock(return_value=(0, "", 1))
    monkeypatch.setattr(manager, "_exec_env_restore", exec_mock)
    await manager._maybe_restore_environment(_handle(workspace))
    assert manager.env_restore_status(workspace.name)["file"] == "conda-explicit.txt"
    script = exec_mock.await_args.args[1]
    assert "micromamba install" in script


@pytest.mark.unit
async def test_stop_clears_env_restore_state(tmp_path: Path, monkeypatch):
    _noop_audit(monkeypatch)
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    (workspace / "environment.yml").write_text("dependencies: [tqdm]\n", encoding="utf-8")
    monkeypatch.setattr(manager, "_exec_env_restore", AsyncMock(return_value=(0, "", 1)))
    monkeypatch.setattr(manager, "last_activity_at", AsyncMock(return_value=None))

    handle = _handle(workspace)
    await manager._maybe_restore_environment(handle)
    assert manager.env_restore_status(workspace.name) is not None

    stopped = MagicMock()
    stopped.status = "running"
    client = MagicMock()
    client.containers.get.return_value = stopped
    monkeypatch.setattr(manager, "_get_client", lambda: client)
    monkeypatch.setattr(manager, "_scratch_volumes", {})
    assert await manager.stop(workspace.name) is True
    assert manager.env_restore_status(workspace.name) is None


# ------------------------------------------------------------------
# WP3 任务 3 科研模式门控
# ------------------------------------------------------------------


@pytest.mark.unit
async def test_gate_skips_restore_when_research_mode_off(tmp_path: Path, monkeypatch):
    """开关关闭 + 声明文件存在：不执行还原、不落审计，状态透出 research_mode_off。"""
    monkeypatch.setattr(
        "cygnusx.application.services.workspace_env_restore_service.write_restore_audit",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.workspace_env_restore_service.research_restore_gate_enabled",
        AsyncMock(return_value=(False, "research_mode 未开启")),
    )
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    (workspace / "environment.yml").write_text("dependencies: [tqdm]\n", encoding="utf-8")
    exec_mock = AsyncMock(return_value=(0, "", 1))
    monkeypatch.setattr(manager, "_exec_env_restore", exec_mock)

    await manager._maybe_restore_environment(_handle(workspace))
    assert exec_mock.await_count == 0
    state = manager.env_restore_status(workspace.name)
    assert state["status"] == "skipped"
    assert state["reason"] == svc.RESTORE_SKIP_RESEARCH_MODE_OFF
    svc.write_restore_audit.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.unit
async def test_gate_executes_restore_when_research_mode_on(tmp_path: Path, monkeypatch):
    """开关开启（enabled + workspace_protocol=research）：走既有还原执行与审计链路。"""
    _noop_audit(monkeypatch)
    manager = _manager(tmp_path)
    workspace = _workspace(tmp_path)
    (workspace / "environment.yml").write_text("dependencies: [tqdm]\n", encoding="utf-8")
    exec_mock = AsyncMock(return_value=(0, "", 1))
    monkeypatch.setattr(manager, "_exec_env_restore", exec_mock)

    await manager._maybe_restore_environment(_handle(workspace))
    assert exec_mock.await_count == 1
    state = manager.env_restore_status(workspace.name)
    assert state["status"] == "restored"
    svc.write_restore_audit.assert_awaited_once()  # type: ignore[attr-defined]


class _GateDb:
    """research_restore_gate_enabled 的假 DB：execute 返回预置 sandbox_meta。"""

    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, _stmt):
        return _GateResult(self._rows)


class _GateResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


@pytest.mark.unit
async def test_gate_function_reads_session_research_mode(monkeypatch):
    meta = {"research_mode": {"enabled": True, "workspace_protocol": "research"}}
    monkeypatch.setattr(
        svc, "get_session_factory", lambda: (lambda: _GateDb([meta]))
    )
    assert await svc.research_restore_gate_enabled("sess-1") == (True, None)

    meta_off = {"research_mode": {"enabled": True, "workspace_protocol": "standard"}}
    monkeypatch.setattr(
        svc, "get_session_factory", lambda: (lambda: _GateDb([meta_off]))
    )
    on, reason = await svc.research_restore_gate_enabled("sess-1")
    assert on is False and "workspace_protocol" in (reason or "")

    monkeypatch.setattr(svc, "get_session_factory", lambda: (lambda: _GateDb([None])))
    on, reason = await svc.research_restore_gate_enabled("sess-1")
    assert on is False and "research_mode" in (reason or "")


@pytest.mark.unit
async def test_gate_function_db_error_defaults_off(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "get_session_factory", _boom)
    on, _reason = await svc.research_restore_gate_enabled("sess-1")
    assert on is False
