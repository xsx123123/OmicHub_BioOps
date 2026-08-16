"""EBIDownload 进度轮询器 — 定时拉取、解密、写 Redis、回调聚合进度

Celery 下载任务启动后，创建一个 ProgressPoller 协程：
- 每 2s 轮询 http://127.0.0.1:{port}/progress
- AES-256-GCM 解密
- 写入 Redis（TTL 60s）供 FastAPI 端点读取
- 聚合 overall_percent 回调更新 task.progress
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from omichub.infrastructure.cache.redis_client import get_redis
from omichub.infrastructure.download.progress_crypto import (
    DecryptionError,
    decrypt_progress,
)

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "download_progress:"
REDIS_TTL = 60  # 秒
POLL_INTERVAL = 2.0  # 秒


class ProgressPoller:
    """轮询 EBIDownload HTTP Progress API 并写入 Redis。"""

    def __init__(
        self,
        task_id: str,
        port: int,
        key: bytes,
        on_overall_progress: callable | None = None,
    ):
        self._task_id = task_id
        self._port = port
        self._key = key
        self._url = f"http://127.0.0.1:{port}/progress"
        self._on_overall = on_overall_progress
        self._client: httpx.AsyncClient | None = None

    async def poll_once(self) -> dict | None:
        """单次轮询：GET /progress → 解密 → 返回 run dict。失败返回 None。"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5.0)
        try:
            resp = await self._client.get(self._url)
            resp.raise_for_status()
            data = resp.json()
            return decrypt_progress(data["ciphertext"], data["nonce"], self._key)
        except DecryptionError:
            logger.warning("任务 %s 进度解密失败", self._task_id)
            return None
        except Exception:
            # 连接拒绝、超时等 — 二进制可能还没启动好
            return None

    async def run(self, cancel_event: asyncio.Event) -> None:
        """主循环：每 POLL_INTERVAL 秒轮询一次，直到 cancel_event 被设置。"""
        redis = get_redis()
        redis_key = f"{REDIS_KEY_PREFIX}{self._task_id}"

        try:
            while not cancel_event.is_set():
                runs = await self.poll_once()
                if runs is not None:
                    # 写 Redis
                    payload = json.dumps(runs, ensure_ascii=False)
                    await redis.set(redis_key, payload, ex=REDIS_TTL)

                    # 聚合 overall progress 并回调
                    if self._on_overall and runs:
                        overall = _compute_overall(runs)
                        try:
                            if asyncio.iscoroutinefunction(self._on_overall):
                                await self._on_overall(overall)
                            else:
                                self._on_overall(overall)
                        except Exception:
                            logger.exception("进度回调异常")

                await asyncio.sleep(POLL_INTERVAL)
        finally:
            if self._client is not None:
                await self._client.aclose()


def _compute_overall(runs: dict) -> float:
    """从 per-run 进度计算加权总进度（0.0 ~ 1.0）。"""
    if not runs:
        return 0.0
    total = 0.0
    count = 0
    for run in runs.values():
        pct = run.get("overall_percent", 0.0)
        total += pct
        count += 1
    if count == 0:
        return 0.0
    return min(1.0, total / count / 100.0)
