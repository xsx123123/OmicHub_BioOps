"""StudioSandboxManager 单元测试（不依赖 Docker，mock docker client）"""

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from omichub.infrastructure.config.storage_config import StorageConfig
from omichub.infrastructure.config.studio_loader import StudioConfigManager
from omichub.infrastructure.storage.path_factory import StoragePathFactory
from omichub.infrastructure.studio import manager as manager_module
from omichub.infrastructure.studio.manager import (
    StudioSandboxManager,
    StudioSandboxUnavailableError,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.expirations: dict[str, int] = {}

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        target = self.sorted_sets.setdefault(key, {})
        target.update(mapping)
        return len(mapping)

    async def zrem(self, key: str, *members: str) -> int:
        target = self.sorted_sets.setdefault(key, {})
        removed = 0
        for member in members:
            removed += int(target.pop(member, None) is not None)
        return removed

    async def zrangebyscore(self, key: str, min: float, max: float) -> list[str]:
        return [
            member
            for member, score in self.sorted_sets.get(key, {}).items()
            if min <= score <= max
        ]

    async def zscore(self, key: str, member: str) -> float | None:
        return self.sorted_sets.get(key, {}).get(member)

    async def zremrangebyscore(self, key: str, min: float, max: float) -> int:
        target = self.sorted_sets.setdefault(key, {})
        members = [member for member, score in target.items() if min <= score <= max]
        for member in members:
            target.pop(member, None)
        return len(members)

    async def zcard(self, key: str) -> int:
        return len(self.sorted_sets.get(key, {}))

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True

    async def delete(self, key: str) -> int:
        existed = int(key in self.sorted_sets)
        self.sorted_sets.pop(key, None)
        self.expirations.pop(key, None)
        return existed


@pytest.fixture
def fake_redis(monkeypatch) -> _FakeRedis:
    redis = _FakeRedis()
    monkeypatch.setattr(manager_module, "get_redis", lambda: redis)
    return redis


def _make_manager(tmp_path: Path) -> StudioSandboxManager:
    """构造工作区指向 tmp_path 的 manager（配置走内存 YAML）"""
    yaml_path = tmp_path / "studio.yaml"
    yaml_path.write_text(
        f'studio:\n  mounts:\n    workspace: "{tmp_path}/ws"\n',
        encoding="utf-8",
    )
    return StudioSandboxManager(_config_manager=StudioConfigManager(config_path=yaml_path))


@pytest.mark.unit
def test_workspace_dir_under_root(tmp_path: Path):
    """会话工作区为 {workspace_root}/{session_id}"""
    manager = _make_manager(tmp_path)
    workspace = manager.workspace_dir("sess-abc123")
    assert workspace == (tmp_path / "ws" / "sess-abc123").resolve()


@pytest.mark.unit
def test_workspace_dir_rejects_traversal(tmp_path: Path):
    """session_id 路径逃逸被拒绝"""
    manager = _make_manager(tmp_path)
    with pytest.raises(StudioSandboxUnavailableError):
        manager.workspace_dir("../evil")
    with pytest.raises(StudioSandboxUnavailableError):
        manager.workspace_dir("a/../../evil")


@pytest.mark.unit
def test_remove_user_root_only_removes_user_directory(tmp_path: Path):
    factory = StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )
    user_root = factory.user_root("user-1")
    user_root.mkdir(parents=True)
    (user_root / "workspace").mkdir()
    (user_root / "workspace" / "marker.txt").write_text("x")

    assert factory.remove_user_root("user-1") is True
    assert not user_root.exists()
    assert (tmp_path / "users").exists()
    assert factory.remove_user_root("user-1") is False


@pytest.mark.unit
def test_container_name_uses_session_prefix():
    """容器命名 studio-{session_id[:8]}"""
    assert StudioSandboxManager.container_name("abcdefgh-ijkl") == "studio-abcdefgh"


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["none", "whitelist"])
def test_validate_isolated_network_accepts_supported_modes(tmp_path: Path, mode: str):
    manager = _make_manager(tmp_path)
    config = manager._config()
    config.sandbox.network.mode = mode

    manager._validate_isolated_network(MagicMock(), config)


@pytest.mark.unit
def test_validate_isolated_network_rejects_unknown_mode(tmp_path: Path):
    manager = _make_manager(tmp_path)
    config = manager._config()
    config.sandbox.network.mode = "host"

    with pytest.raises(StudioSandboxUnavailableError, match="网络模式尚未实现"):
        manager._validate_isolated_network(MagicMock(), config)


@pytest.mark.unit
def test_validate_container_network_accepts_none_mode(tmp_path: Path):
    manager = _make_manager(tmp_path)
    config = manager._config()
    container = MagicMock()
    container.attrs = {"HostConfig": {"NetworkMode": "none"}}

    manager._validate_container_network(container, config, "sess-1")


@pytest.mark.unit
def test_validate_container_network_rejects_none_mode_on_bridge(tmp_path: Path):
    manager = _make_manager(tmp_path)
    config = manager._config()
    container = MagicMock()
    container.attrs = {"HostConfig": {"NetworkMode": "bridge"}}

    with pytest.raises(StudioSandboxUnavailableError, match="network_mode=none"):
        manager._validate_container_network(container, config, "sess-1")


@pytest.mark.unit
def test_session_network_name_is_stable_and_hides_session_id(tmp_path: Path):
    manager = _make_manager(tmp_path)
    config = manager._config()
    config.sandbox.network.docker_network = "studio-egress"

    first = manager.session_network_name("sensitive-session-id", config)
    second = manager.session_network_name("sensitive-session-id", config)

    assert first == second
    assert first.startswith("studio-egress-")
    assert "sensitive-session-id" not in first


@pytest.mark.unit
def test_whitelist_network_requires_allow_domains(tmp_path: Path):
    manager = _make_manager(tmp_path)
    config = manager._config()
    config.sandbox.network.mode = "whitelist"

    with pytest.raises(StudioSandboxUnavailableError, match="至少声明一个域名"):
        manager._ensure_whitelist_network(MagicMock(), "sess-1", config)


@pytest.mark.unit
def test_whitelist_setup_removes_new_network_when_proxy_missing(tmp_path: Path):
    manager = _make_manager(tmp_path)
    config = manager._config()
    config.sandbox.network.mode = "whitelist"
    config.sandbox.network.allow = ["pypi.org"]
    client = MagicMock()
    client.networks.get.side_effect = Exception("not found")
    network = MagicMock()
    network.attrs = {"Internal": True, "Containers": {}}
    client.networks.create.return_value = network
    client.containers.get.side_effect = Exception("proxy missing")

    with pytest.raises(StudioSandboxUnavailableError, match="出站代理不可用"):
        manager._ensure_whitelist_network(client, "sess-1", config)

    network.remove.assert_called_once_with()


@pytest.mark.unit
def test_whitelist_container_rejects_extra_network(tmp_path: Path):
    manager = _make_manager(tmp_path)
    config = manager._config()
    config.sandbox.network.mode = "whitelist"
    expected = manager.session_network_name("sess-1", config)
    container = MagicMock()
    container.attrs = {
        "HostConfig": {"NetworkMode": expected},
        "NetworkSettings": {"Networks": {expected: {}, "bridge": {}}},
    }

    with pytest.raises(StudioSandboxUnavailableError, match="网络不安全"):
        manager._validate_container_network(container, config, "sess-1")


@pytest.mark.unit
def test_ensure_workspace_dirs_creates_subdirs(tmp_path: Path):
    """工作区预建 input/output/ref/.logs 子目录"""
    workspace = tmp_path / "ws" / "sess1"
    StudioSandboxManager.ensure_workspace_dirs(workspace)
    for sub in ("input", "output", "ref", ".logs"):
        assert (workspace / sub).is_dir()


@pytest.mark.unit
async def test_recycle_idle_stops_expired_containers(tmp_path: Path, fake_redis: _FakeRedis):
    """空闲超 TTL 的容器被 stop + remove，活跃容器保留"""
    manager = _make_manager(tmp_path)
    fake_client = MagicMock()
    fake_container = MagicMock()
    fake_client.containers.get.return_value = fake_container
    manager._client = fake_client

    manager._last_activity["expired-sess"] = time.time() - 3600  # 1 小时前
    manager._last_activity["active-sess"] = time.time()

    recycled = await manager.recycle_idle()

    assert recycled == 1
    fake_container.stop.assert_called_once()
    fake_container.remove.assert_called_once_with(force=True)
    # 活跃会话记录保留，过期会话记录清除
    assert "active-sess" in manager._last_activity
    assert "expired-sess" not in manager._last_activity


@pytest.mark.unit
async def test_recycle_idle_ignores_missing_container(tmp_path: Path, fake_redis: _FakeRedis):
    """容器已不存在时回收不报错"""
    manager = _make_manager(tmp_path)
    fake_client = MagicMock()
    fake_client.containers.get.side_effect = Exception("No such container")
    manager._client = fake_client

    manager._last_activity["ghost-sess"] = time.time() - 3600
    assert await manager.recycle_idle() == 0
    assert "ghost-sess" not in manager._last_activity


@pytest.mark.unit
async def test_touch_writes_cross_process_activity(tmp_path: Path, fake_redis: _FakeRedis):
    manager = _make_manager(tmp_path)

    await manager._touch("remote-sess")

    score = fake_redis.sorted_sets[manager_module._ACTIVITY_KEY]["remote-sess"]
    assert score == manager._last_activity["remote-sess"]


@pytest.mark.unit
async def test_recycle_idle_reads_redis_activity_from_other_process(
    tmp_path: Path, fake_redis: _FakeRedis
):
    manager = _make_manager(tmp_path)
    fake_client = MagicMock()
    fake_client.containers.get.return_value = MagicMock()
    manager._client = fake_client
    await fake_redis.zadd(
        manager_module._ACTIVITY_KEY,
        {"remote-expired": time.time() - 3600},
    )

    assert await manager.recycle_idle() == 1
    assert "remote-expired" not in fake_redis.sorted_sets[manager_module._ACTIVITY_KEY]


@pytest.mark.unit
async def test_recycle_idle_skips_any_active_concurrent_lease(
    tmp_path: Path, fake_redis: _FakeRedis
):
    manager = _make_manager(tmp_path)
    manager._client = MagicMock()
    manager._last_activity["busy-sess"] = time.time() - 3600
    first = await manager._set_busy("busy-sess", 600)
    second = await manager._set_busy("busy-sess", 60)

    await manager._clear_busy("busy-sess", first)
    assert await manager.recycle_idle() == 0
    manager._client.containers.get.assert_not_called()

    await manager._clear_busy("busy-sess", second)
    manager._client.containers.get.side_effect = Exception("No such container")
    assert await manager.recycle_idle() == 0


@pytest.mark.unit
async def test_stop_clears_local_and_redis_activity(tmp_path: Path, fake_redis: _FakeRedis):
    manager = _make_manager(tmp_path)
    manager._client = MagicMock()
    manager._client.containers.get.side_effect = Exception("No such container")
    await manager._touch("gone-sess")
    lease = await manager._set_busy("gone-sess", 60)

    assert await manager.stop("gone-sess") is False
    assert "gone-sess" not in manager._last_activity
    assert "gone-sess" not in manager._busy_leases
    assert "gone-sess" not in fake_redis.sorted_sets[manager_module._ACTIVITY_KEY]
    assert lease not in fake_redis.sorted_sets.get(
        f"{manager_module._BUSY_KEY_PREFIX}gone-sess", {}
    )

@pytest.mark.unit
async def test_hibernate_refuses_busy_session(tmp_path: Path, monkeypatch):
    manager = _make_manager(tmp_path)

    async def busy(_session_id: str) -> bool:
        return True

    stop = MagicMock()
    monkeypatch.setattr(manager, "_is_busy", busy)
    monkeypatch.setattr(manager, "stop", stop)

    assert await manager.hibernate("sess-busy") == "busy"
    stop.assert_not_called()


@pytest.mark.unit
async def test_hibernate_removes_container_but_preserves_workspace(tmp_path: Path, monkeypatch):
    manager = _make_manager(tmp_path)
    workspace = manager.workspace_dir("sess-idle")
    workspace.mkdir(parents=True)
    marker = workspace / "scripts" / "analysis.py"
    marker.parent.mkdir()
    marker.write_text("print(1)\n", encoding="utf-8")

    async def idle(_session_id: str) -> bool:
        return False

    async def running(_session_id: str) -> str:
        return "running"

    async def stop(_session_id: str) -> bool:
        return True

    monkeypatch.setattr(manager, "_is_busy", idle)
    monkeypatch.setattr(manager, "status", running)
    monkeypatch.setattr(manager, "stop", stop)

    assert await manager.hibernate("sess-idle") == "hibernated"
    assert marker.read_text(encoding="utf-8") == "print(1)\n"


@pytest.mark.unit
async def test_purge_workspace_refuses_busy_session(tmp_path: Path, monkeypatch):
    manager = _make_manager(tmp_path)
    workspace = manager.workspace_dir("sess-busy")
    workspace.mkdir(parents=True)

    async def busy(_session_id: str) -> bool:
        return True

    stop = MagicMock()
    monkeypatch.setattr(manager, "_is_busy", busy)
    monkeypatch.setattr(manager, "stop", stop)

    assert await manager.purge_workspace("sess-busy") == "busy"
    assert workspace.exists()
    stop.assert_not_called()


@pytest.mark.unit
async def test_purge_workspace_stops_container_then_removes_files(tmp_path: Path, monkeypatch):
    manager = _make_manager(tmp_path)
    workspace = manager.workspace_dir("sess-expired")
    workspace.mkdir(parents=True)
    (workspace / "output.txt").write_text("temporary", encoding="utf-8")

    async def idle(_session_id: str) -> bool:
        return False

    stop = AsyncMock(return_value=True)
    monkeypatch.setattr(manager, "_is_busy", idle)
    monkeypatch.setattr(manager, "stop", stop)

    assert await manager.purge_workspace("sess-expired") == "removed"
    assert not workspace.exists()
    stop.assert_awaited_once_with("sess-expired")
