"""沙盒容器池管理 - Docker 预热容器池 + 代码执行

设计（轻量版，符合 1 人运维 / 单机部署原则）：
- warm pool 维护若干常驻容器（base image，sleep 保持存活）
- 会话亲和性：会话绑定一个 container_id，复用直至超时回收
- 代码执行：Docker SDK exec 在容器内跑 `python -c <base64 包裹>`，stdout/stderr 流式回传
  （web 容器内无 docker CLI，只有 /var/run/docker.sock，不能走 `docker exec` 子进程）
- 图表协议：脚本输出 `%%ECHARTS%%<json>` / `%%IMAGE%%<base64>` 标记行，由池解析为结构化输出
- Docker 不可用时优雅降级：is_available() 返回 False，调用方给出友好错误
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import os
import shutil
import stat as statlib
import tarfile
import tempfile
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from cygnusx.core.config import get_settings

_ECHARTS_PREFIX = "%%ECHARTS%%"
_IMAGE_PREFIX = "%%IMAGE%%"
_PLOTLY_PREFIX = "%%PLOTLY%%"
_SENTINEL = object()
_TIMEOUT = object()
_SANDBOX_UID = 10001
_SANDBOX_GID = 10001
_MOUNT_DESTINATIONS = frozenset(
    {"/tmp/chat_output", "/workspace/output", "/workspace/input"}
)


def _authorize_mount_dir(path: Path) -> None:
    """授权沙盒运行身份访问 bind mount，权限不足时保留单机兼容回退。"""
    try:
        os.chown(path, _SANDBOX_UID, _SANDBOX_GID)
        path.chmod(0o770)
    except (PermissionError, OSError):
        # 非 root 的本地开发进程无法修改宿主属主时，避免容器再次得到 0755 root 目录。
        path.chmod(0o777)


def _seccomp_security_opt(profile: str) -> str | None:
    """把 seccomp_profile 配置转换为 Docker security_opt 条目。

    与 Studio 基线（infrastructure/studio/manager.py 同名函数）语义一致：
    Docker daemon 的 seccomp 选项只接受 ``unconfined`` 或字面 JSON profile 内容；
    ``default`` 不是合法值。省略 seccomp 选项时 daemon 自动应用其内置默认
    profile，语义即“default”，因此该配置返回 None（不追加 security_opt 条目）。
    """
    normalized = (profile or "").strip()
    if normalized.lower() in {"", "default"}:
        return None
    if normalized.lower() == "unconfined":
        return "seccomp=unconfined"
    return f"seccomp={normalized}"


def _pool_host_base(settings: Any) -> str | None:
    """warm pool bind mount 宿主机基目录；空值仅用于本地测试回退。"""
    base = str(getattr(settings, "sandbox_pool_host_dir", "") or "").strip()
    return base or None


class SandboxUnavailableError(Exception):
    """沙盒不可用（Docker 未就绪或镜像缺失）"""


def _merge_into_host(src: Path, dst: Path) -> None:
    """把 src 合并移动到 dst：目录递归合并，文件直接覆盖。

    与"先 rmtree 再 replace"不同，目录对目录时只覆盖同名文件、
    保留 dst 里 src 没有的产物——同一 host_dest 会被多次 copy_dir_out
    平铺写入（/tmp/chat_output 与 /workspace/output 并行收集）。
    """
    if src.is_dir() and dst.is_dir():
        for item in src.iterdir():
            _merge_into_host(item, dst / item.name)
        src.rmdir()
        return
    if dst.is_dir() and not dst.is_symlink():
        # 类型冲突（src 是文件、dst 是目录）：目录让位给文件
        shutil.rmtree(dst)
    elif dst.exists() or dst.is_symlink():
        dst.unlink()
    src.replace(dst)


class SandboxPool:
    """Docker 沙盒容器池"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: Any = None
        self._warm_pool: asyncio.Queue[str] = asyncio.Queue(
            maxsize=self._warm_pool_target()
        )
        self._managed_container_ids: set[str] = set()
        self._available: bool | None = None
        self._init_lock = asyncio.Lock()
        self._container_lock = asyncio.Lock()

    def _max_pool_size(self) -> int:
        return max(self._settings.sandbox_max_pool_size, 0)

    def _warm_pool_target(self) -> int:
        return min(max(self._settings.sandbox_warm_pool_size, 0), self._max_pool_size())

    # ------------------------------------------------------------------
    # Docker 客户端 & 可用性
    # ------------------------------------------------------------------
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
            logger.warning(f"沙盒 Docker 不可用: {e}")
            self._available = False
        return self._available

    async def initialize(self, keep_container_ids: set[str] | None = None) -> None:
        """预热容器池；启动时先治理上一轮进程遗留的孤儿容器。

        keep_container_ids: 数据库中仍活跃会话绑定的容器 id（仅登记计数，不进 warm 队列）。
        其余 warm 标签容器：warm 队列有位子则收养复用，超出 max_pool_size 的销毁。
        """
        if not await self.is_available():
            logger.info("沙盒 Docker 不可用，跳过预热")
            return
        keep = keep_container_ids or set()
        async with self._init_lock:
            await self._reconcile_orphans(keep)
            while self._warm_pool.qsize() < self._warm_pool_target():
                try:
                    container_id = await self._warm_one()
                    if container_id:
                        await self._warm_pool.put(container_id)
                    else:
                        break
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"预热容器失败: {e}")
                    break
        logger.info(f"沙盒预热完成，池内 {self._warm_pool.qsize()} 个容器")

    async def _reconcile_orphans(self, keep: set[str]) -> None:
        """收养/收割带 warm 标签的存量容器（web 重启后内存态丢失，容器变孤儿）"""
        client = self._get_client()

        def _list() -> list[Any]:
            try:
                return client.containers.list(
                    all=True, filters={"label": "cygnusx.sandbox=warm"}
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"列举存量沙盒容器失败: {e}")
                return []

        containers = await asyncio.to_thread(_list)
        adopted = destroyed = 0
        for container in containers:
            cid = str(container.id)
            if cid in keep:
                async with self._container_lock:
                    self._managed_container_ids.add(cid)
                continue
            if container.status != "running":
                await self.destroy(cid)
                destroyed += 1
                continue
            # list() 返回的摘要对象 attrs 不含 HostConfig，reload 取完整 inspect
            reload_fn = getattr(container, "reload", None)
            if reload_fn is not None:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(reload_fn)
            if not self._container_meets_security_baseline(container):
                # 安全基线升级前创建的存量容器（无 cap_drop/只读 rootfs 等）
                # 不允许收养复用，直接销毁由新基线重建（对齐 Studio 重建策略）
                logger.info(f"沙盒孤儿容器不符合安全基线，销毁重建: {cid}")
                await self.destroy(cid)
                destroyed += 1
                continue
            if not self._container_mounts_are_writable(container):
                # 镜像中的 chown 不会覆盖 bind mount；旧容器可能仍挂着 root:root
                # 目录，即使容器的安全参数已经符合，也必须销毁后按新挂载契约重建。
                logger.info(f"沙盒孤儿容器挂载目录不可写，销毁重建: {cid}")
                await self.destroy(cid)
                destroyed += 1
                continue
            async with self._container_lock:
                if len(self._managed_container_ids) >= self._max_pool_size():
                    room = False
                else:
                    self._managed_container_ids.add(cid)
                    room = True
            if not room:
                await self.destroy(cid)
                destroyed += 1
                continue
            try:
                self._warm_pool.put_nowait(cid)
                adopted += 1
            except asyncio.QueueFull:
                await self.destroy(cid)
                destroyed += 1
        if adopted or destroyed:
            logger.info(f"沙盒孤儿容器治理：收养 {adopted} 个，销毁 {destroyed} 个")

    # ------------------------------------------------------------------
    # 容器生命周期
    # ------------------------------------------------------------------
    async def get_or_create_container(self, container_name: str = "") -> str:
        if not await self.is_available():
            raise SandboxUnavailableError("沙盒 Docker 不可用")
        try:
            container_id = self._warm_pool.get_nowait()
            asyncio.create_task(self._warm_and_put())
            return container_id
        except asyncio.QueueEmpty:
            container_id = await self._warm_one(container_name)
            if container_id:
                return container_id
            raise SandboxUnavailableError("沙盒容器池已达到最大容量") from None

    async def _warm_and_put(self) -> None:
        try:
            cid = await self._warm_one()
            if cid:
                try:
                    self._warm_pool.put_nowait(cid)
                except asyncio.QueueFull:
                    await self.destroy(cid)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"补充预热失败: {e}")

    async def _warm_one(self, name: str = "") -> str | None:
        client = self._get_client()
        settings = self._settings
        mem_limit = settings.sandbox_default_memory
        cpu_shares = int(settings.sandbox_default_cpu * 1024)

        def _run() -> str:
            network = None
            network_mode = None
            if settings.sandbox_network_isolated:
                network_mode = "none"
            else:
                network = settings.sandbox_docker_network
            # 安全基线对齐 Studio（studio/manager.py _ensure 容器创建）：
            # cap_drop ALL + no-new-privileges + seccomp + 只读 rootfs +
            # 非 root 用户 + pids/mem 限制。
            security_opt = ["no-new-privileges:true"]
            seccomp_opt = _seccomp_security_opt(settings.sandbox_seccomp_profile)
            if seccomp_opt is not None:
                security_opt.append(seccomp_opt)
            read_only = bool(settings.sandbox_read_only_rootfs)
            tmpfs: dict[str, str] | None = None
            volumes: dict[str, dict[str, str]] | None = None
            if read_only:
                # /tmp：通用可写区（nosuid,nodev,noexec，同 Studio 基线）。
                tmpfs = {"/tmp": f"rw,nosuid,nodev,noexec,size={settings.sandbox_tmpfs_size}"}
                # /tmp/chat_output、/workspace/output、/workspace/input：聊天沙盒
                # 交付/输入目录。不用 tmpfs 而用 per-container 宿主机 bind mount：
                # 本机 Docker daemon 对 tmpfs 路径的 get_archive（copy-out 依赖）
                # 取不到内容，bind mount 在 daemon 与容器两侧视图一致。
                # 容器内路径与协议约定保持不变，copy-out / 附件注入 / R7 重置机制不受影响。
                host_base = _pool_host_base(settings)
                if host_base:
                    # 该路径必须位于 Web 与 Docker daemon 共同可见的 bind mount
                    # 中；如果创建失败直接让本次预热失败，禁止回退到 Web 私有 /tmp。
                    Path(host_base).mkdir(parents=True, exist_ok=True)
                host_dir = Path(
                    tempfile.mkdtemp(prefix="cygnusx-sandbox-", dir=host_base)
                )
                volumes = {}
                for sub, container_path in (
                    ("chat_output", "/tmp/chat_output"),
                    ("output", "/workspace/output"),
                    ("input", "/workspace/input"),
                ):
                    sub_dir = host_dir / sub
                    sub_dir.mkdir()
                    _authorize_mount_dir(sub_dir)
                    volumes[str(sub_dir)] = {"bind": container_path, "mode": "rw"}
            container = client.containers.run(
                image=settings.sandbox_image,
                command=["sleep", "infinity"],
                detach=True,
                name=name or None,
                mem_limit=mem_limit,
                cpu_shares=cpu_shares,
                pids_limit=settings.sandbox_pids_limit,
                cap_drop=["ALL"],
                user=settings.sandbox_container_user,
                security_opt=security_opt,
                read_only=read_only,
                tmpfs=tmpfs,
                volumes=volumes,
                # 镜像 HOME=/root，非 root 运行时必须指向可写位置，
                # 否则 python/R 的用户级缓存写入失败
                environment={"HOME": "/tmp"},
                network=network,
                network_mode=network_mode,
                labels={"cygnusx.sandbox": "warm"},
                # 覆盖镜像内重量级 HEALTHCHECK（每 60s import scanpy 等，满 CPU 数秒），
                # 否则几十个 warm 容器会让后台持续出现 import 进程。
                healthcheck={
                    "Test": ["CMD-SHELL", "python -c \"print('sandbox OK')\""],
                    "Interval": 60000000000,
                    "Timeout": 15000000000,
                    "StartPeriod": 120000000000,
                    "Retries": 3,
                },
                tty=True,
            )
            return str(container.id)

        async with self._container_lock:
            if len(self._managed_container_ids) >= self._max_pool_size():
                return None
            container_id = await asyncio.to_thread(_run)
            self._managed_container_ids.add(container_id)
            return container_id

    def _container_meets_security_baseline(self, container: Any) -> bool:
        """校验存量容器是否满足当前沙盒安全基线（对齐 Studio _validate_container_security）。

        HostConfig 缺失（无法核验）视为不符合，走销毁重建，保证基线收敛。
        """
        settings = self._settings
        attrs = getattr(container, "attrs", None) or {}
        host_config = attrs.get("HostConfig") or {}
        if not host_config:
            return False
        if int(host_config.get("PidsLimit") or 0) != int(settings.sandbox_pids_limit):
            return False
        if settings.sandbox_read_only_rootfs and not host_config.get("ReadonlyRootfs"):
            return False
        cap_drop = {str(item).upper() for item in host_config.get("CapDrop") or []}
        if "ALL" not in cap_drop:
            return False
        security_opts = {str(item).lower() for item in host_config.get("SecurityOpt") or []}
        if "no-new-privileges:true" not in security_opts:
            return False
        actual_user = str((attrs.get("Config") or {}).get("User", ""))
        if actual_user != str(settings.sandbox_container_user):
            return False
        seccomp_opt = _seccomp_security_opt(settings.sandbox_seccomp_profile)
        return not (
            seccomp_opt is not None and seccomp_opt.lower() not in security_opts
        )

    @staticmethod
    def _container_mounts_are_writable(container: Any) -> bool:
        """Reject warm containers whose bind-mount sources cannot be written by the sandbox user.

        Image-layer ownership does not survive a bind mount.  Docker inspect includes the
        host source paths, so validate them before adopting a container left by an older
        worker process.  Some unit-test doubles do not expose ``Mounts``; those retain the
        previous adoption behavior.
        """
        mounts = (getattr(container, "attrs", None) or {}).get("Mounts")
        if not mounts:
            return True
        by_destination = {
            str(mount.get("Destination") or ""): mount for mount in mounts
        }
        if not _MOUNT_DESTINATIONS.issubset(by_destination):
            return False
        for destination in _MOUNT_DESTINATIONS:
            source = Path(str(by_destination[destination].get("Source") or ""))
            try:
                mode = source.stat()
            except (FileNotFoundError, OSError):
                return False
            if mode.st_uid == _SANDBOX_UID:
                if not (mode.st_mode & statlib.S_IWUSR):
                    return False
            elif mode.st_gid == _SANDBOX_GID:
                if not (mode.st_mode & statlib.S_IWGRP):
                    return False
            elif not (mode.st_mode & statlib.S_IWOTH):
                # Non-root pool processes may only use the documented 0777 fallback.
                return False
        return True

    async def container_is_usable(self, container_id: str | None) -> bool:
        """检查会话复用的容器，避免旧坏挂载绕过 warm-pool 治理。"""
        if not container_id:
            return False
        client = self._get_client()

        def _check() -> bool:
            try:
                container = client.containers.get(container_id)
                reload_fn = getattr(container, "reload", None)
                if reload_fn is not None:
                    reload_fn()
                return (
                    container.status == "running"
                    and self._container_meets_security_baseline(container)
                    and self._container_mounts_are_writable(container)
                )
            except Exception:
                return False

        return await asyncio.to_thread(_check)

    async def destroy(self, container_id: str | None) -> None:
        if not container_id:
            return
        client = self._get_client()

        def _destroy() -> None:
            host_dirs: list[Path] = []
            try:
                container = client.containers.get(container_id)
                # 回收前记下 bind mount 的宿主机目录（孤儿容器无内存映射，从 Mounts 发现）
                for mount in (container.attrs.get("Mounts") or []):
                    if str(mount.get("Destination") or "") in {
                        "/tmp/chat_output",
                        "/workspace/output",
                        "/workspace/input",
                    }:
                        host_dirs.append(Path(str(mount.get("Source"))))
                if container.status == "running":
                    # bind 目录内容的属主是容器用户，宿主机进程未必有权删除；
                    # 先在容器内以容器用户清空（mountpoint 本身删不掉不影响），
                    # 再回收容器，最后清宿主机目录树
                    with contextlib.suppress(Exception):
                        exec_id = client.api.exec_create(
                            container_id,
                            cmd=["rm", "-rf", "/tmp/chat_output", "/workspace/output", "/workspace/input"],
                        )["Id"]
                        client.api.exec_start(exec_id)
                container.stop(timeout=5)
                container.remove(force=True)
            except Exception:
                pass
            for host_dir in host_dirs:
                shutil.rmtree(host_dir.parent, ignore_errors=True)

        await asyncio.to_thread(_destroy)
        async with self._container_lock:
            self._managed_container_ids.discard(container_id)

    async def release(self, container_id: str | None) -> None:
        if not container_id:
            return
        if not self._warm_pool.full():
            await self._warm_pool.put(container_id)
        else:
            await self.destroy(container_id)

    # ------------------------------------------------------------------
    # 产物收集
    # ------------------------------------------------------------------
    async def copy_dir_out(
        self,
        container_id: str,
        container_path: str,
        host_dest: Path,
    ) -> list[dict[str, Any]]:
        """把容器内目录整体复制到宿主机目录，返回文件清单（相对路径/大小/mtime）。

        容器内目录不存在或复制失败时返回空列表；用于聊天沙盒产物的持久化收集。
        复制后 host_dest 下直接是目录内容（剥掉 basename 这一层）。
        """
        client = self._get_client()
        base = container_path.rstrip("/").rsplit("/", 1)[-1]

        def _copy() -> list[dict[str, Any]]:
            try:
                stream, _stat = client.api.get_archive(container_id, container_path)
            except Exception:
                return []
            data = b"".join(stream)
            host_dest.mkdir(parents=True, exist_ok=True)
            dest_root = host_dest.resolve()
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                for member in tar.getmembers():
                    # 防目录穿越：仅提取常规文件/目录，且目标必须落在 host_dest 内
                    target = (host_dest / member.name).resolve()
                    if target != dest_root and dest_root not in target.parents:
                        continue
                    if member.isfile() or member.isdir():
                        tar.extract(member, host_dest)
            nested = host_dest / base
            if not nested.is_dir():
                return []
            # get_archive 的 tar 以目录 basename 为顶层，上提一层方便调用方直接使用。
            # 多个容器目录（/tmp/chat_output、/workspace/output）会平铺到同一
            # host_dest，必须合并而不是整体替换：否则后一次复制的空 figures/
            # results 子目录会把前一次已落盘的同名目录连同产物一起删掉。
            for child in nested.iterdir():
                _merge_into_host(child, host_dest / child.name)
            nested.rmdir()
            items: list[dict[str, Any]] = []
            for file in sorted(host_dest.rglob("*")):
                if not file.is_file():
                    continue
                stat = file.stat()
                items.append(
                    {
                        "path": file.relative_to(host_dest).as_posix(),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
            return items

        return await asyncio.to_thread(_copy)

    async def copy_files_in(
        self,
        container_id: str,
        files: list[tuple[Path, str]],
        container_dir: str,
    ) -> list[str]:
        """把宿主机文件复制进容器目录（copy_dir_out 的反向操作）。

        files: [(宿主机路径, 容器内文件名)]，容器内文件名只取 basename 防目录穿越。
        返回实际写入的文件名列表；容器/目录不可用时抛异常由调用方兜底。
        """
        if not files:
            return []
        client = self._get_client()
        api = client.api

        def _put() -> list[str]:
            exec_id = api.exec_create(
                container_id, cmd=["mkdir", "-p", container_dir], tty=False
            )["Id"]
            api.exec_start(exec_id)
            buf = io.BytesIO()
            written: list[str] = []
            with tarfile.open(fileobj=buf, mode="w") as tar:
                for src, arcname in files:
                    name = Path(arcname).name
                    if not name:
                        continue
                    tar.add(str(src), arcname=name)
                    written.append(name)
            try:
                ok = api.put_archive(container_id, container_dir, buf.getvalue())
            except Exception:
                return []
            return written if ok else []

        return await asyncio.to_thread(_put)

    # ------------------------------------------------------------------
    # 代码执行（流式）
    # ------------------------------------------------------------------
    @staticmethod
    def _build_exec_command(language: str, code: str) -> list[str]:
        """构建以 base64 投递源码的容器执行命令。"""
        encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
        if language == "python":
            wrapper = (
                "import base64;"
                f"exec(compile(base64.b64decode('{encoded}').decode('utf-8'),'<sandbox>','exec'))"
            )
            return ["python", "-c", wrapper]
        if language == "r":
            return ["/bin/sh", "-lc", f"printf '%s' '{encoded}' | base64 -d | Rscript -"]
        if language == "bash":
            return ["/bin/sh", "-lc", f"printf '%s' '{encoded}' | base64 -d | bash -s"]
        raise ValueError(f"不支持的沙盒语言: {language}")

    async def stream_execute(
        self,
        container_id: str,
        code: str,
        timeout_sec: int | None = None,
        language: str = "python",
    ) -> AsyncIterator[dict[str, Any]]:
        """流式执行 Python、R 或 Bash 代码。

        注意：web 容器内没有 docker CLI 二进制（只有 /var/run/docker.sock），
        不能走 `docker exec` 子进程；base64 包裹是为了避开 stdin 投递。
        """
        timeout = timeout_sec or self._settings.sandbox_exec_timeout
        started = datetime.now()
        client = self._get_client()
        api = client.api

        command = self._build_exec_command(language, code)

        exec_id = await asyncio.to_thread(
            lambda: api.exec_create(
                container_id, cmd=command, tty=False
            )["Id"]
        )

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        def _pump() -> None:
            """阻塞线程：按 demux 流读取 stdout/stderr 块，按行切分后投递到 asyncio 队列"""
            buffers = {"stdout": "", "stderr": ""}
            try:
                stream = api.exec_start(exec_id, stream=True, demux=True)
                for out_chunk, err_chunk in stream:
                    for channel, chunk in (("stdout", out_chunk), ("stderr", err_chunk)):
                        if not chunk:
                            continue
                        buffers[channel] += chunk.decode("utf-8", errors="replace")
                        while "\n" in buffers[channel]:
                            line, buffers[channel] = buffers[channel].split("\n", 1)
                            loop.call_soon_threadsafe(queue.put_nowait, (channel, line))
                for channel, rest in buffers.items():
                    if rest:
                        loop.call_soon_threadsafe(queue.put_nowait, (channel, rest))
            except Exception as e:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, ("__error__", f"{e}"))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        async def _kill_exec() -> None:
            """杀掉容器内本次执行（超时兜底，best-effort）。

            exec_inspect 的 Pid 是宿主机 PID，容器命名空间内对不上，
            所以按 wrapper 命令行特征 pkill（镜像内有 /usr/bin/pkill）。
            """
            try:
                process_pattern = {
                    "python": "python -c import base64",
                    "r": "Rscript -",
                    "bash": "bash -s",
                }.get(language, "")
                kill_id = await asyncio.to_thread(
                    lambda: api.exec_create(
                        container_id,
                        cmd=["pkill", "-9", "-f", process_pattern],
                    )["Id"]
                )
                await asyncio.to_thread(api.exec_start, kill_id)
            except Exception:  # noqa: BLE001
                pass

        pump = asyncio.create_task(asyncio.to_thread(_pump))
        timed_out = False

        async def _timeout_guard() -> None:
            nonlocal timed_out
            await asyncio.sleep(timeout)
            timed_out = True
            await _kill_exec()
            await queue.put(_TIMEOUT)

        guard = asyncio.create_task(_timeout_guard())

        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL or item is _TIMEOUT:
                    break
                channel, line = item
                if channel == "__error__":
                    yield {"type": "error", "detail": f"代码执行异常：{line}"}
                    continue
                event = self._parse_line(channel, line)
                if event is not None:
                    yield event
        finally:
            guard.cancel()
            if not pump.done():
                await _kill_exec()
                try:
                    await asyncio.wait_for(asyncio.shield(pump), timeout=5)
                except TimeoutError:
                    logger.warning(f"沙盒执行线程未能随超时退出: container={container_id}")
            else:
                await pump
            exit_code = -1
            if not timed_out:
                try:
                    info = await asyncio.to_thread(api.exec_inspect, exec_id)
                    exit_code = int(info.get("ExitCode") or 0)
                except Exception:  # noqa: BLE001
                    pass
            duration = int((datetime.now() - started).total_seconds() * 1000)
            if timed_out:
                yield {"type": "error", "detail": f"代码执行超时（{timeout}s）"}
            yield {"type": "done", "exit_code": exit_code, "duration_ms": duration}

    @staticmethod
    def _parse_line(channel: str, line: str) -> dict[str, Any] | None:
        if channel == "stdout":
            if line.startswith(_ECHARTS_PREFIX):
                try:
                    option = json.loads(line[len(_ECHARTS_PREFIX) :].strip())
                    return {"type": "echarts", "option": option}
                except json.JSONDecodeError:
                    return {"type": "stdout", "data": line}
            if line.startswith(_IMAGE_PREFIX):
                return {"type": "image", "data": line[len(_IMAGE_PREFIX) :].strip()}
            if line.startswith(_PLOTLY_PREFIX):
                try:
                    figure = json.loads(line[len(_PLOTLY_PREFIX) :].strip())
                    return {"type": "plotly", "data": figure}
                except json.JSONDecodeError:
                    return {"type": "stdout", "data": line}
            return {"type": "stdout", "data": line}
        return {"type": "stderr", "data": line}
