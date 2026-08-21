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
import io
import json
import shutil
import tarfile
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from omichub.core.config import get_settings

_ECHARTS_PREFIX = "%%ECHARTS%%"
_IMAGE_PREFIX = "%%IMAGE%%"
_PLOTLY_PREFIX = "%%PLOTLY%%"
_SENTINEL = object()
_TIMEOUT = object()


class SandboxUnavailableError(Exception):
    """沙盒不可用（Docker 未就绪或镜像缺失）"""


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
                    all=True, filters={"label": "omicshub.sandbox=warm"}
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
        mem_limit = self._settings.sandbox_default_memory
        cpu_shares = int(self._settings.sandbox_default_cpu * 1024)

        def _run() -> str:
            network = None
            network_mode = None
            if self._settings.sandbox_network_isolated:
                network_mode = "none"
            else:
                network = self._settings.sandbox_docker_network
            container = client.containers.run(
                image=self._settings.sandbox_image,
                command=["sleep", "infinity"],
                detach=True,
                name=name or None,
                mem_limit=mem_limit,
                cpu_shares=cpu_shares,
                network=network,
                network_mode=network_mode,
                labels={"omicshub.sandbox": "warm"},
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

    async def destroy(self, container_id: str | None) -> None:
        if not container_id:
            return
        client = self._get_client()

        def _destroy() -> None:
            try:
                container = client.containers.get(container_id)
                container.stop(timeout=5)
                container.remove(force=True)
            except Exception:
                pass

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
            # get_archive 的 tar 以目录 basename 为顶层，上提一层方便调用方直接使用
            for child in nested.iterdir():
                target = host_dest / child.name
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                child.replace(target)
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
