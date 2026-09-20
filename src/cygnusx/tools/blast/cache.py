"""BLAST 查询结果缓存。

Redis 只保存结果文件与摘要的定位信息；结果文件仍存放在共享存储。Redis 不可用时
所有操作静默降级，不影响正常查询。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from pathlib import Path
from typing import Any

from cygnusx.infrastructure.cache.redis_client import get_redis

CACHE_PREFIX = "blast:result:"
DEFAULT_TTL_SECONDS = 24 * 60 * 60


def _normalize_query_sequence(query_sequence: str) -> str:
    sequence_lines = [
        "".join(line.split())
        for line in query_sequence.splitlines()
        if line.strip() and not line.lstrip().startswith(">")
    ]
    if sequence_lines:
        return "".join(sequence_lines).upper()
    return "".join(query_sequence.split()).upper()


def build_result_cache_key(
    *,
    db_id: str,
    db_version: str,
    program: str,
    query_sequence: str,
    evalue: float,
    max_target_seqs: int,
    word_size: int | None,
    gapopen: int | None,
    gapextend: int | None,
) -> str:
    normalized = {
        "db_id": db_id,
        "db_version": db_version,
        "program": program,
        "query_sequence": _normalize_query_sequence(query_sequence),
        "evalue": evalue,
        "max_target_seqs": max_target_seqs,
        "word_size": word_size,
        "gapopen": gapopen,
        "gapextend": gapextend,
    }
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"{CACHE_PREFIX}{digest}"


async def get_cached_result(cache_key: str) -> dict[str, Any] | None:
    with contextlib.suppress(Exception):
        raw = await get_redis().get(cache_key)
        if raw:
            payload = json.loads(raw)
            result_path = Path(str(payload.get("result_path", "")))
            if await asyncio.to_thread(result_path.is_file):
                return payload
            await get_redis().delete(cache_key)
    return None


async def set_cached_result(
    cache_key: str, payload: dict[str, Any], ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> None:
    with contextlib.suppress(Exception):
        await get_redis().setex(
            cache_key,
            ttl_seconds,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
