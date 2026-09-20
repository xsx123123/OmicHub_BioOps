"""OmicStudio 沙盒管理器 —— 每会话一个容器，经 sandbox-agent HTTP 交互。

设计（架构设计 §5/§6，按仓库现状适配：纯 docker SDK，无 Swarm）：
- 懒启动：会话首次执行时 ensure_running 拉起容器，UUID 会话名 studio-{session_id[:8]}，
  非 UUID 会话 ID（如 agentteams:{case_id}）用哈希后缀避免前缀碰撞共享容器；
- 交互：Web 通过共享工作区 Unix Socket 直连 sandbox-agent，不依赖沙盒网络、不发布端口、不 docker exec；
- 工作区：bind-mount {workspace_root}/{session_id} -> /workspace，预建 input/output/ref/.logs；
- 平台数据（P1 数据不搬家）：新建容器时把 {storage_path}/users/{user_id} 只读挂到
  /data/platform，input/ 软链经它解析；按用户目录挂载是多租户隔离红线
  （整根挂载会让沙盒内代码可读全部用户数据）。复用旧容器时校验该挂载，
  缺失或源不匹配（如挂载功能上线前创建的陈旧容器）即自动重建；
- 回收：Redis ZSET 记录跨进程 last_activity，Celery beat 每 5 分钟回收超 TTL 容器；
  每次执行/文件请求持有独立 Redis 租约，避免长任务或并发请求被误回收。
- 预热：会话创建后后台启动其专属容器；plain Docker 无法安全重绑 per-user bind mount，
  因此不复用跨用户通用 standby，保留一会话一容器隔离。

网络安全：agent 控制通道使用工作区 Unix Socket；none 模式使用 Docker network_mode=none，
  whitelist 模式将通过每会话 internal 网络与受控代理出站；
- Redis 不可用时活跃态和执行租约自动降级为进程内记录；此时仅保证单进程回收正确。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from cygnusx.core.config import get_settings
from cygnusx.core.telemetry import get_meter, get_tracer
from cygnusx.domain.file.value_objects import FileSource
from cygnusx.infrastructure.cache.redis_client import get_redis
from cygnusx.infrastructure.config.deployment_config import get_deployment_config
from cygnusx.infrastructure.config.studio_loader import (
    StudioConfig,
    StudioConfigManager,
    studio_config_manager,
)
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.infrastructure.storage.scratch_volume import ScratchVolumeManager
from cygnusx.infrastructure.studio.audit import emit as emit_audit
from cygnusx.infrastructure.studio.paths import PLATFORM_CONTAINER_MOUNT

_AGENT_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
_ACTIVITY_KEY = "studio:sandbox:last_activity"
_BUSY_KEY_PREFIX = "studio:sandbox:busy:"
_AGENT_SOCKET_NAME = ".agent.sock"
_AGENT_BASE_URL = "http://studio-agent"

# ===== Studio 沙箱 MCP 调用遥测指标（全局代理 meter，未初始化时为 noop）=====
_studio_meter = get_meter("cygnusx.studio")
_studio_mcp_duration = _studio_meter.create_histogram(
    "mcp.sandbox.call.duration", unit="ms", description="Studio 沙箱 MCP 工具调用耗时"
)
_studio_mcp_count = _studio_meter.create_counter(
    "mcp.sandbox.call.count", description="Studio 沙箱 MCP 工具调用次数"
)


class StudioSandboxUnavailableError(Exception):
    """沙盒不可用（Docker 未就绪 / Studio 未启用 / 镜像缺失）"""


def _seccomp_security_opt(profile: str) -> str | None:
    """把 seccomp_profile 配置转换为 Docker security_opt 条目。

    Docker daemon 的 seccomp 选项只接受 ``unconfined`` 或字面 JSON profile 内容；
    ``default`` 不是合法值（daemon 会尝试按 JSON 解码并拒绝启动容器）。
    省略 seccomp 选项时 daemon 自动应用其内置默认 profile，语义即“default”，
    因此该配置返回 None（不追加 security_opt 条目）。
    """
    normalized = (profile or "").strip()
    if normalized.lower() in {"", "default"}:
        return None
    if normalized.lower() == "unconfined":
        return "seccomp=unconfined"
    return f"seccomp={normalized}"


def _tmpfs_mounts(config: StudioConfig) -> dict[str, str]:
    """只读根文件系统下的可写 tmpfs 挂载表。

    除 /tmp 外，按容器用户属主挂载 agent 缓存目录（micromamba 进程锁等）。
    """
    tmpfs = {"/tmp": f"rw,nosuid,nodev,noexec,size={config.sandbox.tmpfs_size}"}
    cache_dir = config.sandbox.agent_cache_dir.strip()
    if cache_dir:
        uid, _, gid = config.sandbox.container_user.partition(":")
        tmpfs[cache_dir] = f"rw,uid={uid},gid={gid or uid},size=256m"
    return tmpfs


@dataclass
class SandboxHandle:
    """沙盒容器句柄"""

    session_id: str
    container_id: str
    container_name: str
    agent_url: str  # UDS client base URL（保留字段名兼容已有调用方）
    agent_socket: Path
    image: str
    workspace_dir: Path


@dataclass
class StudioSandboxManager:
    """Studio 沙盒管理器（进程内单例）"""

    _config_manager: StudioConfigManager = studio_config_manager
    _client: Any = None
    _available: bool | None = None
    # Redis 是跨 web/celery 进程的权威状态；内存字典作为 Redis 不可用时的降级。
    _last_activity: dict[str, float] = field(default_factory=dict)
    _busy_leases: dict[str, dict[str, float]] = field(default_factory=dict)
    _scratch_volumes: dict[str, ScratchVolumeManager] = field(default_factory=dict)
    # 声明式环境还原（WP2 任务 3）：session_id -> container_id，标记该容器
    # 生命周期内已做过还原检测/执行；容器重建（新 container_id）后自动重新检测。
    _env_restore_done: dict[str, str] = field(default_factory=dict)
    # session_id -> 最近一次还原结果（成功/失败/跳过 + 原因），供详情接口
    # 透传给前端做一次性 warning 提示；失败不阻断会话。
    _env_restore_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    _env_restore_lock: asyncio.Lock | None = field(default=None, init=False, repr=False)

    def _restore_lock(self) -> asyncio.Lock:
        if self._env_restore_lock is None:
            self._env_restore_lock = asyncio.Lock()
        return self._env_restore_lock

    # ------------------------------------------------------------------
    # 配置 & Docker 客户端
    # ------------------------------------------------------------------
    def _config(self) -> StudioConfig:
        return self._config_manager.get_config()

    def _get_client(self) -> Any:
        if self._client is None:
            import docker  # 延迟导入

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
            logger.warning(f"[Studio] 沙盒 Docker 不可用: {e}")
            self._available = False
        return self._available

    # ------------------------------------------------------------------
    # 工作区（纯路径逻辑，可单测）
    # ------------------------------------------------------------------
    def workspace_dir(self, session_id: str) -> Path:
        """会话工作区宿主目录：{workspace_root}/{session_id}（防路径逃逸）"""
        root = self._config().workspace_root.resolve()
        candidate = (root / session_id).resolve()
        if candidate.parent != root:
            raise StudioSandboxUnavailableError(f"非法 session_id: {session_id!r}")
        return candidate

    @staticmethod
    def ensure_workspace_dirs(workspace: Path) -> None:
        """预建工作区子目录并放权给容器内 uid 10001。

        布局与「沙盒目录使用规范」提示词一致：input/ref 只读数据、scripts 脚本、
        output/{results,figures,logs,tmp} 产物、.logs 执行溢出日志、
        mcp-builds MCP Builder 生成代码约定目录。
        容器以非 root（uid 10001）运行，宿主目录默认 root 所有会导致写失败；
        优先 chown 10001，无权限时退化 chmod 0777（P0 单机部署可接受）。
        """
        subs = (
            "",
            "input",
            "ref",
            "scripts",
            "output",
            "output/results",
            "output/figures",
            "output/logs",
            "output/tmp",
            ".logs",
            "mcp-builds",  # MCP Builder 生成代码约定目录
        )
        for sub in subs:
            (workspace / sub).mkdir(parents=True, exist_ok=True)
        try:
            import os

            for sub in subs:
                os.chown(workspace / sub, 10001, 10001)
        except (AttributeError, PermissionError, OSError):
            for sub in subs:
                with contextlib.suppress(OSError):
                    (workspace / sub).chmod(0o777)

    @staticmethod
    def container_name(session_id: str) -> str:
        """容器命名：UUID 会话沿用前 8 位（兼容存量容器）；非 UUID 会话 ID
        （如 agentteams:{case_id}）改用哈希后缀——其短前缀恒相同
        （"agentteams:"[:8]="agenttea"），直接用前缀会让多会话共享同一容器。"""
        try:
            uuid.UUID(session_id)
        except ValueError:
            suffix = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
            return f"studio-{suffix}"
        return f"studio-{session_id[:8]}"

    @staticmethod
    def session_network_name(session_id: str, config: StudioConfig) -> str:
        """生成不暴露会话 ID、可稳定回收的每会话 internal 网络名。"""
        suffix = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
        prefix = config.sandbox.network.docker_network.strip().rstrip("-")
        return f"{prefix}-{suffix}"

    @classmethod
    def _ensure_whitelist_network(
        cls, client: Any, session_id: str, config: StudioConfig
    ) -> str | None:
        network_config = config.sandbox.network
        if network_config.mode.strip().lower() == "none":
            return None
        if not network_config.allow:
            raise StudioSandboxUnavailableError(
                "Studio whitelist 模式要求 sandbox.network.allow 至少声明一个域名"
            )
        network_name = cls.session_network_name(session_id, config)
        created = False
        try:
            try:
                network = client.networks.get(network_name)
            except Exception:  # noqa: BLE001 - 不存在时创建
                network = client.networks.create(
                    network_name,
                    driver="bridge",
                    internal=True,
                    labels={
                        "cygnusx.studio.egress": "1",
                        "cygnusx.studio.session": session_id,
                    },
                )
                created = True
            network.reload()
            if not bool(network.attrs.get("Internal")):
                raise StudioSandboxUnavailableError(
                    f"Studio whitelist 网络必须为 Docker internal: {network_name}"
                )
            try:
                proxy = client.containers.get(network_config.proxy_container)
                proxy.reload()
            except Exception as exc:  # noqa: BLE001
                raise StudioSandboxUnavailableError(
                    f"Studio 出站代理不可用: {network_config.proxy_container}"
                ) from exc
            if proxy.status != "running":
                raise StudioSandboxUnavailableError(
                    f"Studio 出站代理未运行: {network_config.proxy_container}"
                )
            allowed_names = {
                network_config.proxy_container,
                "onlyoffice-documentserver",
                cls.container_name(session_id),
            }
            attached_names = {
                str(item.get("Name", ""))
                for item in network.attrs.get("Containers", {}).values()
                if item.get("Name")
            }
            unexpected = attached_names - allowed_names
            if unexpected:
                raise StudioSandboxUnavailableError(
                    f"Studio whitelist 网络存在未授权容器: {sorted(unexpected)}"
                )
            proxy_networks = proxy.attrs.get("NetworkSettings", {}).get("Networks", {})
            aliases = proxy_networks.get(network_name, {}).get("Aliases") or []
            if network_name not in proxy_networks or network_config.proxy_host not in aliases:
                if network_name in proxy_networks:
                    network.disconnect(proxy, force=True)
                network.connect(proxy, aliases=[network_config.proxy_host])
                network.reload()
            # OnlyOffice is an optional, explicitly named internal peer. It is never
            # exposed to the host and is connected only to this session network.
            with contextlib.suppress(Exception):
                onlyoffice = client.containers.get("onlyoffice-documentserver")
                onlyoffice.reload()
                if onlyoffice.status == "running":
                    office_networks = onlyoffice.attrs.get("NetworkSettings", {}).get("Networks", {})
                    office_aliases = office_networks.get(network_name, {}).get("Aliases") or []
                    if network_name not in office_networks or "onlyoffice-documentserver" not in office_aliases:
                        if network_name in office_networks:
                            network.disconnect(onlyoffice, force=True)
                        network.connect(onlyoffice, aliases=["onlyoffice-documentserver"])
                        network.reload()
            return network_name
        except Exception:
            if created:
                with contextlib.suppress(Exception):
                    network.remove()
            raise

    @classmethod
    def _cleanup_whitelist_network(
        cls, client: Any, session_id: str, config: StudioConfig
    ) -> None:
        """按安全标签清理会话临时网络，配置热切换后也不会泄漏。"""
        networks: list[Any] = []
        with contextlib.suppress(Exception):
            networks.extend(
                client.networks.list(
                    filters={"label": f"cygnusx.studio.session={session_id}"}
                )
            )
        with contextlib.suppress(Exception):
            configured = client.networks.get(cls.session_network_name(session_id, config))
            if all(getattr(item, "id", None) != configured.id for item in networks):
                networks.append(configured)
        for network in networks:
            with contextlib.suppress(Exception):
                network.reload()
            for endpoint in network.attrs.get("Containers", {}).values():
                name = endpoint.get("Name")
                if not name:
                    continue
                with contextlib.suppress(Exception):
                    network.disconnect(client.containers.get(name), force=True)
            with contextlib.suppress(Exception):
                network.remove()

    async def _touch(self, session_id: str) -> None:
        now = time.time()
        self._last_activity[session_id] = now
        try:
            redis_client = get_redis()
            await redis_client.zadd(_ACTIVITY_KEY, {session_id: now})
            await redis_client.expire(_ACTIVITY_KEY, 60 * 60 * 24 * 8)
        except Exception as exc:  # noqa: BLE001 - Redis 不可用时继续单进程降级
            logger.debug("[Studio] Redis 活跃态写入失败，使用进程内降级: {}", exc)

    async def _remove_activity(self, session_id: str) -> None:
        self._last_activity.pop(session_id, None)
        self._busy_leases.pop(session_id, None)
        try:
            redis_client = get_redis()
            await redis_client.zrem(_ACTIVITY_KEY, session_id)
            await redis_client.delete(f"{_BUSY_KEY_PREFIX}{session_id}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Studio] Redis 活跃态/租约删除失败: {}", exc)

    async def _set_busy(self, session_id: str, timeout_sec: int) -> str:
        lease_seconds = max(300, min(timeout_sec, 3600) + 120)
        lease_token = uuid.uuid4().hex
        expires_at = time.time() + lease_seconds
        self._busy_leases.setdefault(session_id, {})[lease_token] = expires_at
        try:
            redis_client = get_redis()
            key = f"{_BUSY_KEY_PREFIX}{session_id}"
            await redis_client.zadd(key, {lease_token: expires_at})
            await redis_client.expire(key, lease_seconds + 60)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Studio] Redis 执行租约写入失败，使用进程内降级: {}", exc)
        return lease_token

    async def _clear_busy(self, session_id: str, lease_token: str) -> None:
        leases = self._busy_leases.get(session_id)
        if leases is not None:
            leases.pop(lease_token, None)
            if not leases:
                self._busy_leases.pop(session_id, None)
        try:
            await get_redis().zrem(f"{_BUSY_KEY_PREFIX}{session_id}", lease_token)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Studio] Redis 执行租约删除失败: {}", exc)

    async def _is_busy(self, session_id: str) -> bool:
        now = time.time()
        leases = self._busy_leases.get(session_id, {})
        active = {token: expiry for token, expiry in leases.items() if expiry > now}
        if active:
            self._busy_leases[session_id] = active
            return True
        self._busy_leases.pop(session_id, None)
        try:
            redis_client = get_redis()
            key = f"{_BUSY_KEY_PREFIX}{session_id}"
            await redis_client.zremrangebyscore(key, min=0, max=now)
            return bool(await redis_client.zcard(key))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Studio] Redis 执行租约读取失败: {}", exc)
            return False

    async def _activity_candidates(self, cutoff: float) -> set[str]:
        candidates = {sid for sid, last in self._last_activity.items() if last <= cutoff}
        try:
            remote = await get_redis().zrangebyscore(_ACTIVITY_KEY, min=0, max=cutoff)
            candidates.update(str(item) for item in remote)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Studio] Redis 活跃态读取失败，使用进程内降级: {}", exc)
        return candidates

    async def last_activity_at(self, session_id: str) -> float | None:
        """返回跨进程可见的最近活动时间；无活动记录时返回 None。"""
        local = self._last_activity.get(session_id)
        try:
            remote = await get_redis().zscore(_ACTIVITY_KEY, session_id)
        except Exception as exc:  # noqa: BLE001 - Redis unavailable uses local fallback
            logger.debug("[Studio] Redis 最近活动读取失败，使用进程内降级: {}", exc)
            remote = None
        values = [float(value) for value in (local, remote) if value is not None]
        return max(values) if values else None

    # ------------------------------------------------------------------
    # 容器生命周期
    # ------------------------------------------------------------------
    async def ensure_running(
        self,
        session_id: str,
        image: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        capabilities_requested: list[str] | None = None,
    ) -> SandboxHandle:
        """确保会话容器运行中（懒启动 + 复用），返回句柄。

        user_id 决定 /data/platform 只读挂载的宿主源目录
        （{storage_path}/users/{user_id}）；复用已运行容器时会校验该挂载，
        缺失或源不匹配（如陈旧容器无此挂载）即重建容器。
        """
        config = self._config()
        if not config.enabled:
            raise StudioSandboxUnavailableError("Studio 功能未启用（studio.enabled=false）")
        if not await self.is_available():
            raise StudioSandboxUnavailableError("沙盒 Docker 不可用")

        image = image or config.default_image
        capabilities_granted = config.capabilities_for_image(image)
        name = self.container_name(session_id)
        persistent_workspace = self.workspace_dir(session_id)
        self.ensure_workspace_dirs(persistent_workspace)

        deployment_cfg = get_deployment_config()
        scratch_mgr: ScratchVolumeManager | None = None
        if deployment_cfg.scratch_volume_enabled:
            if not user_id:
                raise StudioSandboxUnavailableError(
                    "cloud 模式下启动 Studio 沙盒必须提供 user_id"
                )
            async with get_session_factory()() as db_session:
                scratch_mgr = ScratchVolumeManager(
                    session_id, user_id, db_session
                )
                await scratch_mgr.allocate()
                await scratch_mgr.materialize_workspace_inputs(persistent_workspace)
                self._scratch_volumes[session_id] = scratch_mgr
            workspace = scratch_mgr.volume.workspace
            volumes = scratch_mgr.volumes_for_container()
            # cloud scratch 卷自行管理挂载，平台只读挂载基线校验不适用
            expected_platform_source: str | None = None
        else:
            workspace = persistent_workspace
            volumes: dict[str, dict[str, str]] = {
                str(workspace): {"bind": "/workspace", "mode": "rw"}
            }
            # P1 数据不搬家：当前用户数据目录只读挂入容器，input/ 软链经它解析。
            # 多租户红线：只挂 users/{user_id}，绝不整根挂 storage_path。
            expected_platform_source = None
            if user_id:
                user_root = Path(get_settings().storage_path) / "users" / str(user_id)
                if user_root.is_dir():
                    volumes[str(user_root)] = {
                        "bind": PLATFORM_CONTAINER_MOUNT,
                        "mode": "ro",
                    }
                    expected_platform_source = str(user_root)
                else:
                    logger.warning(
                        f"[Studio] 用户数据目录不存在，跳过平台只读挂载: {user_root}"
                    )

        try:

            def _ensure() -> Any:
                client = self._get_client()
                self._validate_isolated_network(client, config)
                network_name = self._ensure_whitelist_network(client, session_id, config)
                try:
                    container = client.containers.get(name)
                except Exception:  # noqa: BLE001 - NotFound 时走创建分支
                    container = None
                if container is not None:
                    configured_image = str(
                        ((getattr(container, "attrs", {}) or {}).get("Config") or {}).get("Image") or ""
                    )
                    if configured_image and configured_image != image:
                        logger.info(
                            "[Studio] 会话 {} 镜像从 {} 切换到 {}，重建沙箱",
                            session_id[:8], configured_image, image,
                        )
                        with contextlib.suppress(Exception):
                            container.stop(timeout=5)
                        with contextlib.suppress(Exception):
                            container.remove(force=True)
                        container = None
                if container is not None and not self._container_mounts_match(
                    container, expected_platform_source
                ):
                    # 挂载功能上线前创建的陈旧容器没有 /data/platform 挂载，
                    # 或其源指向其他用户目录；复用会让 input/ 软链不可读，直接重建。
                    logger.warning(
                        "[Studio] 旧容器平台只读挂载缺失或源不匹配，重建沙箱 {}", name
                    )
                    with contextlib.suppress(Exception):
                        container.stop(timeout=5)
                    with contextlib.suppress(Exception):
                        container.remove(force=True)
                    container = None
                if container is not None:
                    if container.status != "running":
                        container.start()
                    container.reload()
                    self._validate_container_network(container, config, session_id)
                    try:
                        self._validate_container_security(container, config)
                        emit_audit(
                            "sandbox.reuse",
                            session_id=session_id,
                            container_id=str(container.id),
                            baseline_check={
                                "network": True,
                                "cpu": True,
                                "pids": True,
                                "readonly_rootfs": True,
                                "cap_drop": True,
                                "no_new_privileges": True,
                                "user": True,
                                "seccomp": True,
                            },
                        )
                        return container
                    except StudioSandboxUnavailableError as exc:
                        logger.warning(
                            "[Studio] 发现不符合安全基线的旧容器，重建 {}: {}", name, exc
                        )
                        emit_audit(
                            "sandbox.rebuild",
                            session_id=session_id,
                            user_id=user_id,
                            agent_id=agent_id,
                            capabilities_requested=capabilities_requested or ["code"],
                            capabilities_granted=capabilities_granted,
                            image=image,
                            container_id=str(container.id),
                            rebuild_reason=str(exc),
                        )
                        with contextlib.suppress(Exception):
                            container.stop(timeout=5)
                        with contextlib.suppress(Exception):
                            container.remove(force=True)

                # agent 通过共享工作区 UDS 访问；none 模式的沙盒完全不加入 Docker 网络。
                socket_path = workspace / _AGENT_SOCKET_NAME
                with contextlib.suppress(OSError):
                    socket_path.unlink()
                capabilities = config.capabilities_for_image(image)
                security_opt = ["no-new-privileges:true"]
                seccomp_opt = _seccomp_security_opt(config.sandbox.seccomp_profile)
                if seccomp_opt is not None:
                    security_opt.append(seccomp_opt)
                tmpfs = _tmpfs_mounts(config)
                run_kwargs: dict[str, Any] = {
                    "image": image,
                    "name": name,
                    "detach": True,
                    "auto_remove": False,
                    "mem_limit": config.sandbox.memory,
                    "nano_cpus": int(config.sandbox.cpu * 1_000_000_000),
                    "pids_limit": config.sandbox.pids_limit,
                    "cap_drop": ["ALL"],
                    "user": config.sandbox.container_user,
                    "security_opt": security_opt,
                    "read_only": config.sandbox.read_only_rootfs,
                    "tmpfs": tmpfs,
                    "volumes": volumes,
                    "labels": {"cygnusx.studio": "1", "cygnusx.studio.session": session_id},
                    "environment": {
                        "SANDBOX_CAPABILITIES": ",".join(capabilities),
                        "SANDBOX_WORKSPACE_QUOTA_BYTES": str(
                            config.sandbox.workspace_quota_bytes
                        ),
                        "SANDBOX_WORKSPACE_QUOTA_CHECK_INTERVAL_SECONDS": str(
                            config.sandbox.workspace_quota_check_interval_seconds
                        ),
                    },
                }
                if config.sandbox.network.mode.strip().lower() == "none":
                    run_kwargs["network_mode"] = "none"
                else:
                    assert network_name is not None
                    proxy_url = (
                        f"http://{config.sandbox.network.proxy_host}:"
                        f"{config.sandbox.network.proxy_port}"
                    )
                    run_kwargs["network"] = network_name
                    run_kwargs["environment"].update({
                        "HTTP_PROXY": proxy_url,
                        "HTTPS_PROXY": proxy_url,
                        "http_proxy": proxy_url,
                        "https_proxy": proxy_url,
                        "NO_PROXY": "localhost,127.0.0.1",
                        "no_proxy": "localhost,127.0.0.1",
                    })
                created_container = client.containers.run(**run_kwargs)
                emit_audit(
                    "sandbox.create",
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    capabilities_requested=capabilities_requested or ["code"],
                    capabilities_granted=capabilities_granted,
                    image=image,
                    container_id=str(created_container.id),
                    limits={
                        "cpu": config.sandbox.cpu,
                        "memory": config.sandbox.memory,
                        "pids": config.sandbox.pids_limit,
                    },
                    network_mode=config.sandbox.network.mode,
                )
                return created_container

            container = await asyncio.to_thread(_ensure)
        except StudioSandboxUnavailableError:
            if scratch_mgr is not None:
                await scratch_mgr.cleanup()
                self._scratch_volumes.pop(session_id, None)
            raise
        except Exception as e:  # noqa: BLE001
            if scratch_mgr is not None:
                await scratch_mgr.cleanup()
                self._scratch_volumes.pop(session_id, None)
            raise StudioSandboxUnavailableError(f"沙盒容器启动失败: {e}") from e

        await asyncio.to_thread(container.reload)
        agent_socket = workspace / _AGENT_SOCKET_NAME
        agent_url = _AGENT_BASE_URL
        # 容器进程就绪不代表 sandbox-agent 已监听，轮询 UDS 健康检查后再放行
        await self._wait_ready(agent_socket)
        await self._touch(session_id)
        logger.info(f"[Studio] 会话 {session_id[:8]} 沙盒就绪: {name} -> unix://{agent_socket}")
        handle = SandboxHandle(
            session_id=session_id,
            container_id=str(container.id),
            container_name=name,
            agent_url=agent_url,
            agent_socket=agent_socket,
            image=image,
            workspace_dir=workspace,
        )
        # 还原钩子（WP2 任务 3）：容器新建/重建后的首次激活，在工作区声明文件
        # 存在时于容器内跑一次一次性安装；失败仅降级 + 记日志/审计，不阻断启动。
        await self._maybe_restore_environment(handle, user_id=user_id)
        return handle

    @staticmethod
    def _validate_isolated_network(client: Any, config: StudioConfig) -> None:
        """none 模式必须使用 Docker network_mode=none；whitelist 由代理网络处理。"""
        mode = config.sandbox.network.mode.strip().lower()
        if mode not in {"none", "whitelist"}:
            raise StudioSandboxUnavailableError(
                f"Studio 沙盒网络模式尚未实现: {config.sandbox.network.mode}"
            )

    @classmethod
    def _validate_container_network(
        cls, container: Any, config: StudioConfig, session_id: str
    ) -> None:
        """复用容器必须匹配当前网络模式，且不能额外挂载平台网络。"""
        mode = config.sandbox.network.mode.strip().lower()
        host_mode = str(container.attrs.get("HostConfig", {}).get("NetworkMode", ""))
        if mode == "none":
            if host_mode != "none":
                raise StudioSandboxUnavailableError(
                    f"Studio 沙盒网络不安全: expected network_mode=none, actual={host_mode}"
                )
            return
        expected = cls.session_network_name(session_id, config)
        attached = set(
            container.attrs.get("NetworkSettings", {}).get("Networks", {}).keys()
        )
        if attached != {expected}:
            raise StudioSandboxUnavailableError(
                f"Studio 沙盒网络不安全: expected={expected}, attached={sorted(attached)}"
            )

    @staticmethod
    def _container_mounts_match(container: Any, expected_platform_source: str | None) -> bool:
        """复用前校验挂载基线：期望的平台只读挂载必须存在且源为当前用户数据目录。

        expected_platform_source 为 None（无用户上下文或 cloud scratch 模式）时不强制。
        """
        if expected_platform_source is None:
            return True
        mounts = (getattr(container, "attrs", {}) or {}).get("Mounts") or []
        return any(
            str(mount.get("Destination")) == PLATFORM_CONTAINER_MOUNT
            and str(mount.get("Source")) == expected_platform_source
            for mount in mounts
        )

    @staticmethod
    def _validate_container_security(container: Any, config: StudioConfig) -> None:
        """拒绝复用不满足当前 Studio 安全基线的旧容器。"""
        host_config = container.attrs.get("HostConfig", {})
        if int(host_config.get("NanoCpus") or 0) < int(config.sandbox.cpu * 1_000_000_000):
            raise StudioSandboxUnavailableError("Studio 沙盒未设置有效硬 CPU 限制")
        if int(host_config.get("PidsLimit") or 0) != config.sandbox.pids_limit:
            raise StudioSandboxUnavailableError("Studio 沙盒 PID 限制不符合当前配置")
        if config.sandbox.read_only_rootfs and not host_config.get("ReadonlyRootfs"):
            raise StudioSandboxUnavailableError("Studio 沙盒根文件系统不是只读")
        cap_drop = {str(item).upper() for item in host_config.get("CapDrop") or []}
        if "ALL" not in cap_drop:
            raise StudioSandboxUnavailableError("Studio 沙盒未丢弃 Linux capabilities")
        security_opts = {str(item).lower() for item in host_config.get("SecurityOpt") or []}
        if "no-new-privileges:true" not in security_opts:
            raise StudioSandboxUnavailableError("Studio 沙盒未启用 no-new-privileges")
        actual_user = str(container.attrs.get("Config", {}).get("User", ""))
        if actual_user != config.sandbox.container_user:
            raise StudioSandboxUnavailableError("Studio 沙盒运行用户不是固定非 root 用户")
        seccomp_opt = _seccomp_security_opt(config.sandbox.seccomp_profile)
        if seccomp_opt is not None and seccomp_opt.lower() not in security_opts:
            raise StudioSandboxUnavailableError("Studio 沙盒未显式启用 seccomp profile")

    @staticmethod
    def _agent_client(socket_path: Path, timeout: httpx.Timeout) -> httpx.AsyncClient:
        """构造经工作区 Unix Socket 访问 agent 的 HTTP 客户端。"""
        transport = httpx.AsyncHTTPTransport(uds=str(socket_path))
        return httpx.AsyncClient(
            transport=transport,
            base_url=_AGENT_BASE_URL,
            timeout=timeout,
        )

    @classmethod
    async def _wait_ready(cls, socket_path: Path, timeout_sec: float = 30.0) -> None:
        """轮询 sandbox-agent UDS /healthz，直到服务就绪或超时。"""
        deadline = asyncio.get_running_loop().time() + timeout_sec
        while True:
            try:
                async with cls._agent_client(socket_path, httpx.Timeout(2.0)) as client:
                    resp = await client.get("/healthz")
                    if resp.status_code == 200:
                        return
            except Exception:  # noqa: BLE001 - socket 尚在创建，等待重试
                pass
            if asyncio.get_running_loop().time() > deadline:
                raise StudioSandboxUnavailableError("沙盒 agent UDS 服务就绪超时")
            await asyncio.sleep(0.3)

    # ------------------------------------------------------------------
    # 声明式环境还原（WP2 任务 3，替代容器快照）
    # ------------------------------------------------------------------
    async def _maybe_restore_environment(
        self, handle: SandboxHandle, user_id: str | None = None
    ) -> None:
        """容器生命周期内只做一次还原检测/执行；失败降级，绝不向上抛。

        幂等：``_env_restore_done[session_id] == container_id`` 即跳过；
        容器重建后 container_id 变化自动重新检测。并发 ensure_running 共用
        本进程的 asyncio.Lock（跨进程由既有执行租约兜底，重复执行安装命令
        本身也是幂等的）。
        """
        session_id = handle.session_id
        if self._env_restore_done.get(session_id) == handle.container_id:
            return
        async with self._restore_lock():
            if self._env_restore_done.get(session_id) == handle.container_id:
                return
            # 先标记再执行：即使过程异常也保证同一容器生命周期不重复还原。
            self._env_restore_done[session_id] = handle.container_id
            from cygnusx.application.services.workspace_env_restore_service import (
                EnvRestoreResult,
                RESTORE_SKIP_RESEARCH_MODE_OFF,
                build_restore_script,
                detect_restore_file,
                latest_missing_env_snapshot,
                research_restore_gate_enabled,
                restore_timeout_seconds,
                summarize_failure,
                write_restore_audit,
            )

            log = logger.bind(session_id=session_id, component="workspace_env_restore")
            # WP3 任务 3 门控：仅科研模式（enabled + workspace_protocol=research）放行还原。
            # 开关关闭时的跳过不落审计（避免每次激活一条 204 噪音）：
            # 检测到声明文件存在（本该还原）记 info 并透出状态，否则只记 debug。
            gate_on, gate_reason = await research_restore_gate_enabled(session_id)
            if not gate_on:
                declared = detect_restore_file(handle.workspace_dir)
                if declared is not None:
                    log.info(
                        "环境还原跳过（科研模式未开启）: 声明文件 {} 存在但不还原 — {}",
                        declared, gate_reason,
                    )
                    self._env_restore_state[session_id] = EnvRestoreResult(
                        status="skipped",
                        file=None,
                        duration_ms=0,
                        reason=RESTORE_SKIP_RESEARCH_MODE_OFF,
                        container_id=handle.container_id,
                    ).as_dict()
                else:
                    log.debug("环境还原跳过（科研模式未开启，且无声明文件）: {}", gate_reason)
                return

            result = EnvRestoreResult(
                status="skipped", file=None, duration_ms=0,
                reason=None, container_id=handle.container_id,
            )
            try:
                restore_file = detect_restore_file(handle.workspace_dir)
                if restore_file is None:
                    missing = await latest_missing_env_snapshot(session_id)
                    result.reason = "工作区无 conda-explicit.txt / environment.yml，跳过环境还原"
                    if missing:
                        result.reason += (
                            f"（WP1 打包 manifest 标记缺失环境四件套: {', '.join(missing)}）"
                        )
                    log.info("环境还原跳过: {}", result.reason)
                else:
                    result.file = restore_file
                    timeout = restore_timeout_seconds(
                        self._config().sandbox.exec_timeout_seconds
                    )
                    started = time.monotonic()
                    exit_code, stderr_tail, _ = await self._exec_env_restore(
                        handle, build_restore_script(restore_file), timeout
                    )
                    result.duration_ms = int((time.monotonic() - started) * 1000)
                    if exit_code == 0:
                        result.status = "restored"
                        log.info(
                            "环境还原成功 file={} duration_ms={}", restore_file, result.duration_ms
                        )
                    else:
                        result.status = "failed"
                        result.reason = summarize_failure(stderr_tail, exit_code)
                        log.warning(
                            "环境还原失败（降级为基础环境，不阻断会话）file={} duration_ms={} {}",
                            restore_file, result.duration_ms, result.reason,
                        )
            except Exception as exc:  # noqa: BLE001 - 还原失败绝不阻断会话启动
                result.status = "failed"
                result.reason = summarize_failure(f"还原执行异常: {exc}", -1)
                log.warning("环境还原异常（降级为基础环境）: {}", result.reason)
            self._env_restore_state[session_id] = result.as_dict()
            await write_restore_audit(session_id=session_id, user_id=user_id, result=result)

    async def _exec_env_restore(
        self, handle: SandboxHandle, code: str, timeout_sec: int
    ) -> tuple[int, str, int]:
        """在容器内经 sandbox-agent /exec 非交互执行还原脚本（bash，一次性进程）。

        返回 (exit_code, stderr 尾部, duration_ms)；持有执行租约防止空闲回收。
        """
        lease_token = await self._set_busy(handle.session_id, timeout_sec)
        payload = {"language": "bash", "code": code, "timeout": timeout_sec}
        stderr_tail = ""
        exit_code = -1
        duration_ms = 0
        try:
            async with (
                self._agent_client(handle.agent_socket, _AGENT_TIMEOUT) as client,
                client.stream("POST", "/exec", json=payload) as resp,
            ):
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type")
                    if etype == "stderr":
                        stderr_tail = (stderr_tail + str(event.get("data", "")))[-2000:]
                    elif etype == "result":
                        exit_code = int(event.get("exit_code", -1))
                        duration_ms = int(event.get("duration_ms", 0) or 0)
        finally:
            await self._clear_busy(handle.session_id, lease_token)
            await self._touch(handle.session_id)
        return exit_code, stderr_tail, duration_ms

    def env_restore_status(self, session_id: str) -> dict[str, Any] | None:
        """最近一次环境还原结果（含失败原因），供会话详情接口透传给前端。"""
        return self._env_restore_state.get(session_id)

    async def _handle(
        self, session_id: str, image: str | None = None, user_id: str | None = None
    ) -> SandboxHandle:
        """ensure_running 并续约活跃时间。"""
        handle = await self.ensure_running(session_id, image=image, user_id=user_id)
        await self._touch(session_id)
        return handle

    async def status(self, session_id: str) -> str:
        """探测会话沙盒容器状态（只读，不触发懒启动）。

        返回 running / stopped / absent / unavailable（Studio 未启用或 Docker 不可用）。
        """
        if not self._config().enabled:
            return "unavailable"
        if not await self.is_available():
            return "unavailable"
        name = self.container_name(session_id)

        def _probe() -> str:
            try:
                container = self._get_client().containers.get(name)
            except Exception:  # noqa: BLE001 - 容器不存在视为 absent
                return "absent"
            return "running" if container.status == "running" else "stopped"

        return await asyncio.to_thread(_probe)

    async def metrics(self, session_id: str) -> dict[str, float | int]:
        """读取运行中容器的轻量 CPU/内存快照；未运行时返回零值。"""
        if await self.status(session_id) != "running":
            return {"cpu_percent": 0.0, "memory_percent": 0.0, "memory_used": 0, "memory_limit": 0}
        name = self.container_name(session_id)

        def _read() -> dict[str, float | int]:
            container = self._get_client().containers.get(name)
            stats = container.stats(stream=False)
            cpu = stats.get("cpu_stats") or {}
            previous = stats.get("precpu_stats") or {}
            cpu_total = float((cpu.get("cpu_usage") or {}).get("total_usage") or 0)
            previous_total = float((previous.get("cpu_usage") or {}).get("total_usage") or 0)
            system_total = float(cpu.get("system_cpu_usage") or 0)
            previous_system = float(previous.get("system_cpu_usage") or 0)
            online = int(cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or []) or 1)
            cpu_delta = cpu_total - previous_total
            system_delta = system_total - previous_system
            cpu_percent = (cpu_delta / system_delta * online * 100) if cpu_delta > 0 and system_delta > 0 else 0.0
            memory = stats.get("memory_stats") or {}
            memory_stats = memory.get("stats") or {}
            memory_used = max(0, int(memory.get("usage") or 0) - int(memory_stats.get("cache") or 0))
            memory_limit = int(memory.get("limit") or 0)
            memory_percent = memory_used / memory_limit * 100 if memory_limit > 0 else 0.0
            return {
                "cpu_percent": round(min(cpu_percent, 100.0), 1),
                "memory_percent": round(min(memory_percent, 100.0), 1),
                "memory_used": memory_used,
                "memory_limit": memory_limit,
            }

        try:
            return await asyncio.to_thread(_read)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Studio] 容器指标读取失败: {}", exc)
            return {"cpu_percent": 0.0, "memory_percent": 0.0, "memory_used": 0, "memory_limit": 0}

    def scratch_volume(self, session_id: str) -> ScratchVolumeManager | None:
        """返回 cloud 模式下当前会话的 scratch 卷管理器（local 模式返回 None）。"""
        return self._scratch_volumes.get(session_id)

    async def finalize_outputs(self, session_id: str) -> list[Any] | None:
        """cloud 模式下把 scratch output 产物回传对象存储并注册到 file_records。"""
        existing = self._scratch_volumes.get(session_id)
        if existing is None:
            return None
        async with get_session_factory()() as db_session:
            scratch = ScratchVolumeManager(
                session_id, existing.user_id, db_session
            )
            # 复用已分配的卷路径，不再重新分配
            scratch.volume = existing.volume
            scratch._root = existing._root
            return await scratch.register_outputs(source=FileSource.STUDIO)

    async def stop(self, session_id: str) -> bool:
        """停止并移除会话容器，返回是否实际回收了容器。"""
        name = self.container_name(session_id)
        last_active_at = await self.last_activity_at(session_id)
        await self._remove_activity(session_id)
        scratch = self._scratch_volumes.get(session_id)
        # 容器回收后还原标记/结果随之失效；重建容器会以新 container_id 重新检测。
        self._env_restore_state.pop(session_id, None)
        self._env_restore_done.pop(session_id, None)

        def _stop() -> bool:
            client = self._get_client()
            removed = False
            try:
                container = client.containers.get(name)
            except Exception:  # noqa: BLE001 - 容器不存在也继续清理会话网络
                container = None
            if container is not None:
                with contextlib.suppress(Exception):
                    container.stop(timeout=5)
                container.remove(force=True)
                removed = True
            workspace_root = (
                scratch.volume.workspace if scratch else self.workspace_dir(session_id)
            )
            with contextlib.suppress(OSError):
                (workspace_root / _AGENT_SOCKET_NAME).unlink()
            self._cleanup_whitelist_network(client, session_id, self._config())
            return removed

        removed = await asyncio.to_thread(_stop)
        if scratch is not None:
            await self.finalize_outputs(session_id)
            await scratch.cleanup()
            self._scratch_volumes.pop(session_id, None)
        if removed:
            logger.info(f"[Studio] 会话 {session_id[:8]} 沙盒已回收")
            emit_audit(
                "sandbox.reclaim",
                session_id=session_id,
                container_id=name,
                reclaim_reason="manual",
                last_active_at=last_active_at,
                resource_peak=None,
            )
        return removed

    async def hibernate(self, session_id: str) -> str:
        """安全休眠会话沙盒：忙碌时拒绝，空闲时移除容器并保留 bind-mount 工作区。"""
        if await self._is_busy(session_id):
            return "busy"
        status = await self.status(session_id)
        if status in {"absent", "unavailable"}:
            await self._remove_activity(session_id)
            return status
        await self.stop(session_id)
        return "hibernated"

    def remove_workspace(self, session_id: str) -> bool:
        """删除已过保留期的 Studio 工作区，不影响独立结果中心产物。"""
        workspace = self.workspace_dir(session_id)
        if not workspace.exists():
            return False
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)
        return not workspace.exists()

    async def purge_workspace(self, session_id: str) -> str:
        """复核 busy 状态后释放容器并删除工作区。"""
        if await self._is_busy(session_id):
            return "busy"
        await self.stop(session_id)
        return "removed" if self.remove_workspace(session_id) else "missing"

    async def recycle_idle(self) -> int:
        """回收跨进程可见且空闲超 TTL 的会话容器。"""
        ttl = self._config().session.idle_ttl_minutes * 60
        cutoff = time.time() - ttl
        expired = await self._activity_candidates(cutoff)
        recycled = 0
        for session_id in expired:
            if await self._is_busy(session_id):
                continue
            try:
                if await self.stop(session_id):
                    recycled += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[Studio] 回收会话 {session_id[:8]} 沙盒失败: {exc}")
        if recycled:
            logger.info(f"[Studio] 空闲沙盒回收 {recycled} 个")
        return recycled

    # ------------------------------------------------------------------
    # 代码执行（NDJSON 流式）
    # ------------------------------------------------------------------
    async def exec(
        self,
        session_id: str,
        language: str,
        code: str,
        timeout_sec: int | None = None,
        image: str | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式执行代码，逐条产出 sandbox-agent 的 NDJSON 事件。

        事件形态：{"type":"stdout"|"stderr","data":...}
        终止事件：{"type":"result","exit_code":N,"duration_ms":...,"artifacts":[...]}
        """
        effective_timeout = timeout_sec or self._config().sandbox.exec_timeout_seconds
        lease_token = await self._set_busy(session_id, effective_timeout)
        payload = {
            "language": language,
            "code": code,
            "timeout": effective_timeout,
        }
        try:
            handle = await self._handle(session_id, image=image, user_id=user_id)
            async with (
                self._agent_client(handle.agent_socket, _AGENT_TIMEOUT) as client,
                client.stream("POST", "/exec", json=payload) as resp,
            ):
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(f"[Studio] 无法解析的 agent 输出: {line[:200]}")
        finally:
            await self._clear_busy(session_id, lease_token)
            await self._touch(session_id)

    # ------------------------------------------------------------------
    # 文件操作（/files/* 薄封装）
    # ------------------------------------------------------------------
    async def list_files(
        self, session_id: str, path: str = "", image: str | None = None, user_id: str | None = None
    ) -> dict[str, Any]:
        """列出工作区目录（含名称/类型/大小/mtime）。"""
        return await self._agent_call(
            session_id, "GET", "/files/list", params={"path": path}, image=image, user_id=user_id
        )

    async def read_file(
        self,
        session_id: str,
        path: str,
        offset: int = 0,
        limit: int = 200,
        image: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """分页读取文本文件，返回 {content, total_lines, truncated}。"""
        return await self._agent_call(
            session_id,
            "GET",
            "/files/read",
            params={"path": path, "offset": offset, "limit": limit},
            image=image,
            user_id=user_id,
        )

    async def write_file(
        self,
        session_id: str,
        path: str,
        content: str,
        image: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """创建 / 覆盖工作区文件。"""
        return await self._agent_call(
            session_id,
            "POST",
            "/files/write",
            json={"path": path, "content": content},
            image=image,
            user_id=user_id,
        )

    async def make_directory(self, session_id: str, path: str, image: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        return await self._agent_call(session_id, "POST", "/files/mkdir", json={"path": path}, image=image, user_id=user_id)

    async def rename_file(self, session_id: str, path: str, new_path: str, image: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        return await self._agent_call(session_id, "POST", "/files/rename", json={"path": path, "new_path": new_path}, image=image, user_id=user_id)

    async def delete_file(self, session_id: str, path: str, image: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        return await self._agent_call(session_id, "DELETE", "/files/delete", params={"path": path}, image=image, user_id=user_id)

    async def edit_file(
        self,
        session_id: str,
        path: str,
        old_string: str,
        new_string: str,
        image: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """精确替换并返回 unified diff。"""
        return await self._agent_call(
            session_id,
            "POST",
            "/files/edit",
            json={"path": path, "old_string": old_string, "new_string": new_string},
            image=image,
            user_id=user_id,
        )

    async def browser_navigate(
        self, session_id: str, url: str, wait_until: str = "domcontentloaded",
        timeout: int = 30, image: str | None = None, user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._agent_call(
            session_id, "POST", "/browser/navigate",
            json={"url": url, "wait_until": wait_until, "timeout": timeout},
            image=image, user_id=user_id,
        )

    async def browser_screenshot(
        self, session_id: str, path: str = "output/browser-screenshot.png",
        selector: str = "", full_page: bool = False, timeout: int = 30,
        image: str | None = None, user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._agent_call(
            session_id, "POST", "/browser/screenshot",
            json={"path": path, "selector": selector, "full_page": full_page, "timeout": timeout},
            image=image, user_id=user_id,
        )

    async def browser_click(
        self, session_id: str, selector: str, button: str = "left", click_count: int = 1,
        timeout: int = 30, image: str | None = None, user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._agent_call(
            session_id, "POST", "/browser/click",
            json={"selector": selector, "button": button, "click_count": click_count, "timeout": timeout},
            image=image, user_id=user_id,
        )

    async def browser_type(
        self, session_id: str, selector: str, text: str, clear: bool = True,
        timeout: int = 30, image: str | None = None, user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._agent_call(
            session_id, "POST", "/browser/type",
            json={"selector": selector, "text": text, "clear": clear, "timeout": timeout},
            image=image, user_id=user_id,
        )

    async def browser_press(
        self, session_id: str, selector: str, key: str, timeout: int = 30,
        image: str | None = None, user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._agent_call(
            session_id, "POST", "/browser/press",
            json={"selector": selector, "key": key, "timeout": timeout},
            image=image, user_id=user_id,
        )

    async def browser_close(
        self, session_id: str, image: str | None = None, user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._agent_call(
            session_id, "POST", "/browser/close", image=image, user_id=user_id
        )

    async def document_call(
        self, session_id: str, endpoint: str, payload: dict[str, Any],
        image: str | None = None, user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._agent_call(
            session_id, "POST", endpoint, json=payload, image=image, user_id=user_id
        )

    async def onlyoffice_status(
        self, session_id: str, image: str | None = None, user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._agent_call(
            session_id, "GET", "/onlyoffice/status", image=image, user_id=user_id
        )

    # ------------------------------------------------------------------
    # MCP Builder（/mcp/* 薄封装）
    # 在会话沙箱容器内以 STDIO 子进程运行 AI 生成的实验 MCP Server，
    # 宿主侧经 UDS 代理完成 tools/list 与 tools/call，不暴露任何 TCP 端口。
    # ------------------------------------------------------------------
    async def start_mcp_server(
        self,
        session_id: str,
        path: str,
        server_id: str | None = None,
        timeout: int | None = None,
        image: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """容器内启动实验 MCP Server 并握手，返回 {server_id, path, tools}。"""
        payload: dict[str, Any] = {"path": path}
        if server_id:
            payload["server_id"] = server_id
        if timeout:
            payload["timeout"] = timeout
        return await self._agent_call(
            session_id, "POST", "/mcp/start", json=payload, image=image, user_id=user_id
        )

    async def stop_mcp_server(
        self,
        session_id: str,
        server_id: str,
        image: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """停止容器内指定实验 MCP Server。"""
        return await self._agent_call(
            session_id,
            "POST",
            "/mcp/stop",
            json={"server_id": server_id},
            image=image,
            user_id=user_id,
        )

    async def list_mcp_servers(
        self,
        session_id: str,
        image: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """列出容器内运行中的实验 MCP Server。"""
        return await self._agent_call(
            session_id, "GET", "/mcp/list", image=image, user_id=user_id
        )

    async def mcp_list_tools(
        self,
        session_id: str,
        server_id: str,
        image: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """获取实验 MCP 的工具清单。"""
        return await self._agent_call(
            session_id,
            "GET",
            "/mcp/tools",
            params={"server_id": server_id},
            image=image,
            user_id=user_id,
        )

    async def mcp_call_tool(
        self,
        session_id: str,
        server_id: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        timeout: int | None = None,
        image: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """调用实验 MCP 的工具，返回 {content, is_error}（带 Trace/Log/Metrics 埋点）。"""
        payload: dict[str, Any] = {
            "server_id": server_id,
            "tool": tool,
            "arguments": arguments or {},
        }
        if timeout:
            payload["timeout"] = timeout
        tracer = get_tracer("cygnusx.studio")
        with tracer.start_as_current_span(
            "mcp.sandbox.call_tool",
            attributes={"mcp.server_id": server_id, "mcp.tool": tool},
        ) as span:
            start = time.perf_counter()
            status = "success"
            try:
                result = await self._agent_call(
                    session_id, "POST", "/mcp/call", json=payload, image=image, user_id=user_id
                )
                if result.get("is_error"):
                    status = "error"
                return result
            except Exception as exc:  # noqa: BLE001
                status = "error"
                span.record_exception(exc)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                attrs = {
                    "mcp.server_id": server_id,
                    "mcp.tool": tool,
                    "mcp.status": status,
                }
                span.set_attribute("mcp.status", status)
                span.set_attribute("mcp.duration_ms", round(duration_ms, 2))
                try:
                    _studio_mcp_duration.record(duration_ms, attrs)
                    _studio_mcp_count.add(1, attrs)
                except Exception:  # noqa: BLE001
                    pass
                logger.bind(
                    event="mcp.sandbox.call_tool",
                    server_id=server_id,
                    tool=tool,
                    status=status,
                    duration_ms=round(duration_ms, 2),
                ).info("mcp.sandbox.call_tool completed")

    async def _agent_call(
        self,
        session_id: str,
        method: str,
        endpoint: str,
        image: str | None = None,
        user_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        lease_token = await self._set_busy(session_id, 60)
        try:
            handle = await self._handle(session_id, image=image, user_id=user_id)
            async with self._agent_client(handle.agent_socket, _AGENT_TIMEOUT) as client:
                resp = await client.request(method, endpoint, **kwargs)
                resp.raise_for_status()
                result: dict[str, Any] = resp.json()
                return result
        finally:
            await self._clear_busy(session_id, lease_token)
            await self._touch(session_id)


# 进程内单例；活跃态与执行租约通过 Redis 跨 web/celery 共享。
studio_sandbox_manager = StudioSandboxManager()
