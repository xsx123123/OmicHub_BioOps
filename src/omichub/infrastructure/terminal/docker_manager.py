"""终端容器管理 - Docker 沙盒终端生命周期

所有配置项从 tool_configs/terminal/terminal_config.yaml 读取（经 ConfigManager mtime 热重载），
不再依赖 core/config.py 的 Pydantic Settings。
"""

from __future__ import annotations

import asyncio
import random
import shutil
from pathlib import Path
from typing import Any

from loguru import logger

from omichub.infrastructure.config.deployment_config import get_deployment_config
from omichub.infrastructure.database.session import get_session_factory
from omichub.infrastructure.storage.scratch_volume import ScratchVolumeManager
from omichub.tools.terminal.config import TerminalImage, get_terminal_config


class TerminalDockerError(Exception):
    """终端容器操作异常"""


class TerminalDockerManager:
    """终端 Docker 容器管理器"""

    def __init__(self) -> None:
        self._client: Any = None
        self._available: bool | None = None
        self._allocated_ports: set[int] = set()
        self._scratch_volumes: dict[str, ScratchVolumeManager] = {}

    @property
    def _cfg(self):
        return get_terminal_config()

    def _get_client(self) -> Any:
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    async def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            client = self._get_client()
            await asyncio.to_thread(client.ping)
            self._available = True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"终端 Docker 不可用: {e}")
            self._available = False
        return self._available

    def _allocate_port(self) -> int:
        port_range = self._cfg.port_range
        for _ in range(100):
            port = random.randint(port_range.base, port_range.max)
            if port not in self._allocated_ports:
                self._allocated_ports.add(port)
                return port
        raise TerminalDockerError("端口池已耗尽")

    def _release_port(self, port: int | None) -> None:
        if port is not None:
            self._allocated_ports.discard(port)

    async def create_container(
        self,
        user_id: str,
        session_id: str,
        image: TerminalImage,
        registry_prefix: str = "",
        memory_mb: int | None = None,
        cpu_cores: float | None = None,
        pid_limit: int | None = None,
    ) -> tuple[str, int]:
        """创建终端容器，返回 (container_id, host_port)"""
        if not await self.is_available():
            raise TerminalDockerError("终端 Docker 不可用")

        cfg = self._cfg
        client = self._get_client()
        port = self._allocate_port()

        image_resources = image.resources
        defaults = cfg.default_resources
        limits = cfg.max_resources

        def _clamp(value: float, lower: float, upper: float) -> float:
            normalized_upper = max(lower, upper)
            return min(max(value, lower), normalized_upper)

        mem = int(
            _clamp(
                memory_mb or image_resources.memory_mb or defaults.memory_mb, 1, limits.memory_mb
            )
        )
        cpu = _clamp(
            cpu_cores or image_resources.cpu_cores or defaults.cpu_cores,
            0.1,
            limits.cpu_cores,
        )
        pids = int(
            _clamp(
                pid_limit or image_resources.pid_limit or defaults.pid_limit, 1, limits.pid_limit
            )
        )
        tmpfs_mb = int(_clamp(defaults.tmpfs_size_mb, 1, limits.tmpfs_size_mb))

        deployment_cfg = get_deployment_config()
        system_mounts = {
            "workspace": "/home/omichub/workspace",
            "raw_data": "/home/omichub/raw_data",
            "temp": "/home/omichub/temp",
        }
        volumes: dict[str, dict[str, str]] = {}
        scratch_mgr: ScratchVolumeManager | None = None

        if deployment_cfg.scratch_volume_enabled:
            # cloud 模式：使用临时 POSIX scratch 卷，不直接 bind-mount 用户持久目录
            async with get_session_factory()() as db_session:
                scratch_mgr = ScratchVolumeManager(
                    session_id, user_id, db_session
                )
                await scratch_mgr.allocate()
                for name, container_path in system_mounts.items():
                    host_path = scratch_mgr.volume.workspace / name
                    if name != "workspace":
                        host_path = scratch_mgr.volume.root / name
                    await asyncio.to_thread(host_path.mkdir, parents=True, exist_ok=True)
                    volumes[str(host_path)] = {"bind": container_path, "mode": "rw"}
        else:
            # local 模式：保留原有 bind-mount 行为
            user_root = f"{cfg.storage.workspace_base}/{user_id}"
            for name, container_path in system_mounts.items():
                host_path = f"{user_root}/{name}"
                await asyncio.to_thread(Path(host_path).mkdir, parents=True, exist_ok=True)
                try:
                    await asyncio.to_thread(shutil.chown, host_path, user=1000, group=1000)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"沙盒目录权限调整失败 {host_path}: {e}，将尝试继续启动容器")
                volumes[host_path] = {"bind": container_path, "mode": "rw"}

        container_name = f"omichub-term-{user_id[:8]}-{session_id}"
        image_name = image.full_image_name(registry_prefix)

        security = cfg.security
        cap_drop = ["ALL"] if security.cap_drop_all else []
        security_opt = ["no-new-privileges:true"] if security.no_new_privileges else []

        # 镜像特定环境变量
        env_vars = {item.name: item.value for item in image.env}
        env_vars.update(
            {
                "USER_ID": user_id,
                "SESSION_ID": session_id,
                "HOME": "/home/omichub",
                "ZDOTDIR": "/home/omichub",
                "XDG_CACHE_HOME": "/home/omichub/.cache",
                "OMP_CACHE_DIR": "/home/omichub/.cache",
                "ZSH_CACHE_DIR": "/home/omichub/.cache/oh-my-zsh",
            }
        )

        def _run() -> str:
            container = client.containers.run(
                image=image_name,
                detach=True,
                auto_remove=True,
                read_only=security.read_only_root,
                mem_limit=f"{mem}m",
                memswap_limit=f"{mem}m",
                cpu_quota=int(cpu * 100000),
                cpu_period=100000,
                pids_limit=pids,
                cap_drop=cap_drop,
                security_opt=security_opt,
                tmpfs={
                    "/tmp": f"rw,noexec,nosuid,size={tmpfs_mb}m",
                    "/home/omichub/.cache": "rw,noexec,nosuid,size=50m",
                },
                volumes=volumes,
                ports={"7681/tcp": port},
                network=cfg.network.name,
                hostname="sandbox",
                user="1000:1000",
                environment=env_vars,
                working_dir="/home/omichub/workspace",
                name=container_name,
                labels={
                    "app": "omichub-terminal",
                    "user_id": user_id,
                    "session_id": session_id,
                    "image_id": image.id,
                },
                healthcheck={
                    "test": [
                        "CMD",
                        "wget",
                        "--quiet",
                        "--tries=1",
                        "--spider",
                        "http://localhost:7681",
                    ],
                    "interval": 30_000_000_000,
                    "timeout": 10_000_000_000,
                    "retries": 3,
                },
            )
            return str(container.id)

        try:
            container_id = await asyncio.to_thread(_run)
            if scratch_mgr is not None:
                self._scratch_volumes[container_id] = scratch_mgr
            logger.info(f"终端容器已创建: {container_name} image={image_name} port={port}")
            return container_id, port
        except Exception as e:
            if scratch_mgr is not None:
                await scratch_mgr.cleanup()
            self._release_port(port)
            raise TerminalDockerError(f"容器启动失败: {e}") from e

    async def destroy_container(self, container_id: str | None, port: int | None = None) -> None:
        if not container_id:
            return

        def _destroy() -> None:
            try:
                client = self._get_client()
                container = client.containers.get(container_id)
                container.stop(timeout=5)
            except Exception:  # noqa: BLE001
                pass

        await asyncio.to_thread(_destroy)
        scratch_mgr = self._scratch_volumes.pop(container_id, None)
        if scratch_mgr is not None:
            await scratch_mgr.cleanup()
        self._release_port(port)

    async def get_container_stats(self, container_id: str | None) -> dict[str, Any] | None:
        """获取容器实时资源占用（CPU / 内存）。返回 None 表示容器不存在或已停止。"""
        if not container_id:
            return None

        def _stats() -> dict[str, Any] | None:
            try:
                client = self._get_client()
                container = client.containers.get(container_id)
                # stream=False 返回一个快照字典
                stats = container.stats(stream=False)
                cpu_stats = stats.get("cpu_stats", {})
                precpu_stats = stats.get("precpu_stats", {})

                # 内存
                memory_stats = stats.get("memory_stats", {})
                mem_usage = memory_stats.get("usage", 0)
                mem_limit = memory_stats.get("limit", 1)
                mem_percent = (mem_usage / mem_limit * 100) if mem_limit else 0

                # CPU 百分比计算（与 docker stats CLI 一致）
                cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get(
                    "cpu_usage", {}
                ).get("total_usage", 0)
                system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get(
                    "system_cpu_usage", 0
                )
                cpu_percent = 0.0
                if system_delta > 0 and cpu_delta > 0:
                    cpu_percent = (
                        (cpu_delta / system_delta)
                        * len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [1]))
                        * 100
                    )

                return {
                    "cpu_percent": round(cpu_percent, 2),
                    "memory_usage": mem_usage,
                    "memory_usage_mb": round(mem_usage / 1024 / 1024, 2),
                    "memory_limit": mem_limit,
                    "memory_limit_mb": round(mem_limit / 1024 / 1024, 2),
                    "memory_percent": round(mem_percent, 2),
                    "pids": stats.get("pids_stats", {}).get("current", 0),
                }
            except Exception:  # noqa: BLE001
                return None

        return await asyncio.to_thread(_stats)
