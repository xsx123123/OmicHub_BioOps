"""EBIDownload 进度 API 解密工具

EBIDownload 的 HTTP Progress API 返回 AES-256-GCM 加密的 JSON。
密钥由二进制编译时写入 work_dir/progress.key（hex 编码），本模块负责读取和解密。
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ProgressKeyTimeout(TimeoutError):
    """progress.key 在超时时间内未出现"""


class DecryptionError(ValueError):
    """AES-GCM 解密失败"""


def load_progress_key(work_dir: str, timeout: float = 15.0) -> bytes:
    """等待 progress.key 出现并读取 AES-256 密钥。

    EBIDownload 启动后将编译时的 32-byte 密钥以 hex 编码写入 work_dir/progress.key。
    轮询等待文件出现（二进制需要时间启动），超时抛 ProgressKeyTimeout。

    Returns:
        32-byte AES 密钥
    """
    key_path = Path(work_dir) / "progress.key"
    elapsed = 0.0
    interval = 0.5

    while elapsed < timeout:
        if key_path.exists():
            try:
                hex_str = key_path.read_text(encoding="utf-8").strip()
                return bytes.fromhex(hex_str)
            except (ValueError, OSError) as exc:
                raise DecryptionError(f"无法读取 progress.key: {exc}") from exc
        time_remaining = timeout - elapsed
        sleep_time = min(interval, time_remaining)
        if sleep_time <= 0:
            break
        # 同步 sleep（在 Celery 协程中由调用方用 asyncio.to_thread 包装）
        import time

        time.sleep(sleep_time)
        elapsed += sleep_time
        interval = min(interval * 1.5, 2.0)

    raise ProgressKeyTimeout(f"progress.key 在 {timeout}s 内未出现于 {work_dir}")


async def load_progress_key_async(work_dir: str, timeout: float = 15.0) -> bytes:
    """异步版本的 load_progress_key，避免阻塞事件循环。"""
    return await asyncio.to_thread(load_progress_key, work_dir, timeout)


def decrypt_progress(ciphertext_b64: str, nonce_b64: str, key: bytes) -> dict:
    """解密 AES-256-GCM 加密的进度 JSON。

    Args:
        ciphertext_b64: Base64 编码的密文
        nonce_b64: Base64 编码的 12-byte nonce
        key: 32-byte AES 密钥

    Returns:
        解密后的进度 dict（run_id → RunProgress）

    Raises:
        DecryptionError: 解密失败
    """
    try:
        ciphertext = base64.b64decode(ciphertext_b64)
        nonce = base64.b64decode(nonce_b64)
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext)
    except Exception as exc:
        raise DecryptionError(f"进度解密失败: {exc}") from exc
