"""产物 manifest 对账 — 执行完成时对所声明产物做 sha256 实测。

契约借鉴 OpenAI4S ``compute/manifest.py``（只借鉴"manifest（path/size/sha256）
+ 声明 glob 对账"的语义，不涉及其传输层与进程模型）：

  * 每个实测文件一条 ``{"path", "size", "sha256"}`` 记录；读取失败的文件
    记入 manifest 并标 ``error``（size/sha256 为 None），不抛异常阻断登记主流程。
  * ``reconcile_declared`` 把 manifest 与声明的 glob 对账：只有实测成功
    （有 sha256）的文件才能兑现声明；声明了但落空的 glob 返回 missing —
    "exit 0 即成功"的静默假成功由此显形。
  * glob 同时匹配相对路径与 basename（声明 ``*.csv`` 意为任何 csv）。

path 一律为相对路径（产物收集根 / run 目录），不落绝对路径，保持记录可移植。
"""

from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

#: 流式读取块大小；产物可能是大文件，绝不整读进内存。
_CHUNK_SIZE = 1024 * 1024


def sha256_stream(path: Path) -> str:
    """流式计算本地文件 sha256（分块读取）；失败返回空串。

    与 project_archive_service.md5_stream 同款非抛出语义，供"尽量记录、不阻断"路径使用。
    """
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def build_file_entry(root: Path, path: Path) -> dict[str, Any]:
    """实测单个文件，产出一条 manifest 记录；读取失败标 error 不抛出。"""
    entry: dict[str, Any] = {"path": Path(path).relative_to(root).as_posix()}
    try:
        entry["size"] = Path(path).stat().st_size
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                digest.update(block)
        entry["sha256"] = digest.hexdigest()
    except OSError as exc:
        # 读不了的文件不能为其内容背书：记录它、带上原因、保持可见，
        # 而不是从"交付了什么"的记录里悄悄消失。
        entry["size"] = None
        entry["sha256"] = None
        entry["error"] = f"{type(exc).__name__}: {exc}"
    return entry


def build_manifest(root: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    """对 ``root`` 下给定文件逐条实测（path/size/sha256），按 path 排序。

    排序保证同一批字节产出可复现的 manifest，与文件系统枚举顺序无关。
    """
    root = Path(root)
    entries = [build_file_entry(root, p) for p in paths]
    return sorted(entries, key=lambda item: str(item.get("path")))


def verified_paths(entries: Iterable[dict[str, Any]]) -> list[str]:
    """manifest 中实测成功（有 sha256）的相对路径。"""
    return [str(e.get("path") or "") for e in entries if e.get("sha256")]


def unverified_paths(entries: Iterable[dict[str, Any]]) -> list[str]:
    """manifest 中没有内容 hash 的路径（读取失败，不能被当作已交付产物）。"""
    return [str(e.get("path") or "") for e in entries if not e.get("sha256")]


def reconcile_declared(
    entries: list[dict[str, Any]], declared: Iterable[str] | None
) -> tuple[list[str], list[str]]:
    """manifest 与声明 glob 对账，返回 (featured, missing)。

    featured: 命中声明的实测成功路径（manifest 顺序去重）；
    missing: 声明了但没有实测成功文件兑现的 glob（含声明原文）。

    只有 verified 条目能兑现声明 —— 路径本身不是证据：一个读不出内容的文件
    不能替它名字所承诺的产物作证（OpenAI4S 同款语义）。
    """
    patterns = [str(p).strip() for p in (declared or []) if str(p or "").strip()]
    paths = verified_paths(entries)
    if not patterns:
        return (paths, [])
    featured: list[str] = []
    missing: list[str] = []
    for pattern in patterns:
        matches = [
            path
            for path in paths
            if fnmatch.fnmatch(path, pattern)
            or fnmatch.fnmatch(Path(path).name, pattern)
        ]
        if matches:
            featured.extend(matches)
        else:
            missing.append(pattern)
    featured_set = set(featured)
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path in featured_set and path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered, missing
