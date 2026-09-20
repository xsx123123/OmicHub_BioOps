"""E2E：chat warm pool 沙盒安全基线对齐 Studio（R6）真实 Docker 验证。

验收项：
a) 真实起 warm pool 容器，docker inspect 关键字段与 Studio 基线逐项一致；
b) 容器内产出文件 → copy_dir_out 到宿主机（copy-out 不回归）；
c) 跨会话 reset 后交付目录清空（无跨会话串扰，R7）；
d) 非 root 冒烟：网络隔离生效、tmpfs 可写、rootfs 只读拒绝写入。

需要本机 Docker 与 sandbox_image 镜像；不满足时整文件 skip。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cygnusx.infrastructure.sandbox.pool import SandboxPool


def _inspect_fields(container_id: str) -> dict:
    out = subprocess.run(
        ["docker", "inspect", container_id],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    info = json.loads(out)[0]
    host_config = info["HostConfig"]
    return {
        "CapDrop": host_config.get("CapDrop"),
        "SecurityOpt": host_config.get("SecurityOpt"),
        "ReadonlyRootfs": host_config.get("ReadonlyRootfs"),
        "Tmpfs": host_config.get("Tmpfs"),
        "Binds": host_config.get("Binds"),
        "User": (info.get("Config") or {}).get("User"),
        "PidsLimit": host_config.get("PidsLimit"),
        "Memory": host_config.get("Memory"),
        "NetworkMode": host_config.get("NetworkMode"),
    }


def _collect_stdout(pool: SandboxPool, cid: str, code: str, language: str = "python") -> str:
    async def _run() -> str:
        parts: list[str] = []
        async for event in pool.stream_execute(cid, code, timeout_sec=120, language=language):
            if event.get("type") == "stdout":
                parts.append(str(event.get("data", "")))
            if event.get("type") == "error":
                raise AssertionError(f"执行出错: {event.get('detail')}")
        return "\n".join(parts)

    return asyncio.run(_run())


try:
    _client = __import__("docker").from_env()
    _client.ping()
    _DOCKER_OK = True
    _client.close()
except Exception:  # noqa: BLE001
    _DOCKER_OK = False

pytestmark = pytest.mark.skipif(not _DOCKER_OK, reason="需要本机 Docker daemon")


@pytest.fixture
def pool_container():
    """用真实 SandboxPool 起一个 hardened warm 容器，用后销毁。"""
    pool = SandboxPool()
    assert asyncio.run(pool.is_available())

    async def _warm() -> str:
        cid = await pool._warm_one()
        assert cid
        return cid

    cid = asyncio.run(_warm())
    yield SimpleNamespace(pool=pool, cid=cid)
    asyncio.run(pool.destroy(cid))


@pytest.mark.e2e
def test_warm_container_matches_studio_security_baseline(pool_container) -> None:
    """a) chat warm pool 容器与 Studio 基线容器 docker inspect 逐项一致。"""
    cid = pool_container.cid
    fields = _inspect_fields(cid)

    # 用 Studio manager 同款 run_kwargs 起一个基线参照容器做逐项 diff
    import docker

    client = docker.from_env()
    ref = client.containers.run(
        image=pool_container.pool._settings.sandbox_image,
        command=["sleep", "infinity"],
        detach=True,
        mem_limit="4g",
        pids_limit=512,
        cap_drop=["ALL"],
        user="10001:10001",
        security_opt=["no-new-privileges:true"],
        read_only=True,
        tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=512m"},
        network_mode="none",
    )
    try:
        ref_fields = _inspect_fields(ref.id)
    finally:
        ref.stop(timeout=5)
        ref.remove(force=True)

    # 逐项对齐（Studio 基线 ←→ chat warm pool）
    for key in (
        "CapDrop",
        "SecurityOpt",
        "ReadonlyRootfs",
        "User",
        "PidsLimit",
        "NetworkMode",
    ):
        assert fields[key] == ref_fields[key], f"{key}: chat={fields[key]} studio={ref_fields[key]}"

    # Memory：Studio 4g == 4294967296；chat 用 settings.sandbox_default_memory
    assert fields["Memory"] == ref_fields["Memory"] == 4 * 1024**3
    # Tmpfs：/tmp 条目与 Studio 基线一致
    assert fields["Tmpfs"] == ref_fields["Tmpfs"]
    # 交付/输入目录：per-container 宿主机 bind mount（容器内路径不变，copy-out 兼容）
    binds = {b.split(":")[1] for b in fields["Binds"]}
    assert {"/tmp/chat_output", "/workspace/output", "/workspace/input"} <= binds


@pytest.mark.e2e
def test_copy_out_and_non_root_smoke(pool_container, tmp_path: Path) -> None:
    """b)+d) 产出文件 copy-out 到宿主机；非 root / 网络隔离 / 只读 rootfs 冒烟。"""
    pool, cid = pool_container.pool, pool_container.cid

    # 与 chat_sandbox_tools._ARTIFACT_DIR_RESET_CMD 同语义（重置交付/输入目录）
    reset_cmd = (
        "rm -rf /tmp/chat_output /workspace/output /workspace/input 2>/dev/null; "
        "mkdir -p /tmp/chat_output/figures /tmp/chat_output/results "
        "/workspace/output/figures /workspace/output/results /workspace/input"
    )
    _collect_stdout(pool, cid, reset_cmd, language="bash")

    # 容器内以非 root 产出交付文件（chat copy-out 场景双目录）
    code = (
        "import os, pathlib\n"
        "assert os.getuid() == 10001, f'unexpected uid {os.getuid()}'\n"
        "pathlib.Path('/tmp/chat_output/results/summary.csv').write_text('a,b\\n1,2\\n')\n"
        "pathlib.Path('/workspace/output/figures/plot.txt').write_text('fake-png')\n"
        "print('artifact write OK')\n"
    )
    out = _collect_stdout(pool, cid, code)
    assert "artifact write OK" in out

    # copy-out：两个容器目录平铺复制到宿主机
    import asyncio

    host_dest = tmp_path / "chat-output"
    items_chat = asyncio.run(pool.copy_dir_out(cid, "/tmp/chat_output", host_dest))
    items_ws = asyncio.run(pool.copy_dir_out(cid, "/workspace/output", host_dest))
    paths = {str(i["path"]) for i in items_chat + items_ws}
    assert "results/summary.csv" in paths
    assert "figures/plot.txt" in paths
    assert (host_dest / "results" / "summary.csv").read_text() == "a,b\n1,2\n"
    assert (host_dest / "figures" / "plot.txt").read_text() == "fake-png"

    # 网络隔离：无网络模式下连接外网必须失败
    net_code = (
        "import socket\n"
        "s = socket.socket(); s.settimeout(3)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 80))\n"
        "    print('NETWORK_OPEN')\n"
        "except OSError:\n"
        "    print('NETWORK_BLOCKED')\n"
    )
    assert "NETWORK_BLOCKED" in _collect_stdout(pool, cid, net_code)

    # 只读 rootfs：tmpfs 之外写入必须失败
    ro_code = (
        "import pathlib\n"
        "try:\n"
        "    pathlib.Path('/workspace/evil.txt').write_text('x')\n"
        "    print('ROOTFS_WRITABLE')\n"
        "except OSError as e:\n"
        "    print('ROOTFS_READONLY', e.errno)\n"
    )
    out = _collect_stdout(pool, cid, ro_code)
    assert "ROOTFS_READONLY" in out

    # no-new-privileges：setuid 提升必须被拒绝（cap_setuid 已随 cap_drop ALL 丢弃）
    priv_code = (
        "import os\n"
        "try:\n"
        "    os.setuid(0)\n"
        "    print('PRIV_ESCAPED', os.getuid())\n"
        "except OSError:\n"
        "    print('PRIV_DENIED')\n"
    )
    assert "PRIV_DENIED" in _collect_stdout(pool, cid, priv_code)


@pytest.mark.e2e
def test_cross_session_reset_clears_artifacts(pool_container) -> None:
    """c) 模拟另一会话接管同一容器：reset 后旧产物必须清空（R7 无串扰）。"""
    pool, cid = pool_container.pool, pool_container.cid

    reset_cmd = (
        "rm -rf /tmp/chat_output /workspace/output /workspace/input 2>/dev/null; "
        "mkdir -p /tmp/chat_output/figures /tmp/chat_output/results "
        "/workspace/output/figures /workspace/output/results /workspace/input"
    )
    _collect_stdout(pool, cid, reset_cmd, language="bash")

    marker = (
        "import pathlib\n"
        "pathlib.Path('/tmp/chat_output/results/session_a_secret.csv').write_text('SECRET-A')\n"
        "print('A written')\n"
    )
    assert "A written" in _collect_stdout(pool, cid, marker)

    # 会话 B 接管同一容器（chat_sandbox_tools 的 _artifact_dir_owner 机制会再次 reset）
    _collect_stdout(pool, cid, reset_cmd, language="bash")

    check = (
        "import os\n"
        "leftover = os.path.exists('/tmp/chat_output/results/session_a_secret.csv')\n"
        "print('LEFTOVER' if leftover else 'CLEAN')\n"
    )
    assert "CLEAN" in _collect_stdout(pool, cid, check)
