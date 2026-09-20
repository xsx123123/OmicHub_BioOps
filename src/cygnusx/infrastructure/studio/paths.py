"""OmicStudio 工作区路径防护 —— 与 sandbox-agent 同源的纯函数守卫。

deploy/studio/sandbox_agent.py 按自包含设计随镜像烘焙进容器，无法被宿主包直接 import；
此处按同一套规则最小复刻，供宿主侧（Studio API 磁盘回退、产物下载）复用，
两侧规则必须保持一致：相对路径基于 root 拼接，realpath 解析软链后必须落在 root 内。

P1 数据不搬家：工作区 input/ 下的软链指向容器内平台只读挂载 /data/platform
（宿主侧对应 {storage_path}/users/{user_id}）。读操作（read/list）允许经此类软链
解析到平台挂载内，写操作（write/edit）仍严格限制在工作区内。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 容器内平台数据只读挂载点（宿主侧按用户翻译，见 resolve_workspace_read_path）
PLATFORM_CONTAINER_MOUNT = "/data/platform"


class PathEscapeError(ValueError):
    """路径逃逸工作区根目录"""


def workspace_realpath(root: Path) -> Path:
    """工作区根目录的 realpath（软链解析后的基准）"""
    return Path(os.path.realpath(root))


def resolve_workspace_path(user_path: str, root: Path) -> Path:
    """将用户路径归一化为 root 内的绝对路径。

    - 相对路径基于 root 拼接；绝对路径必须本身位于 root 内；
    - realpath 解析软链后再校验，防止经符号链接逃逸；
    - 越界抛出 PathEscapeError。
    """
    root_real = workspace_realpath(root)
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = root_real / candidate
    resolved = Path(os.path.realpath(candidate))
    if resolved != root_real and root_real not in resolved.parents:
        raise PathEscapeError(f"路径越出工作区: {user_path}")
    return resolved


@dataclass(frozen=True)
class ResolvedReadPath:
    """读路径解析结果。

    path 为当前一侧可直接读取的实际路径；via_platform=True 表示经平台只读
    挂载解析而来（调用方绝不可用于写/改/删）。
    """

    path: Path
    via_platform: bool


def resolve_workspace_read_path(
    user_path: str,
    root: Path,
    platform_host_root: Path | None = None,
) -> ResolvedReadPath:
    """读路径归一化：工作区内照常放行，另允许经 input/ 软链落到平台只读挂载。

    - 相对路径基于 root 拼接；realpath 解析软链后落在 root 内 → 正常放行；
    - realpath 落在平台挂载 /data/platform 内 → 仅当「词法路径本身在工作区内」
      （即逃逸完全由工作区内的软链跳转造成）才放行，防止直接拼绝对路径越权读
      其他用户数据；返回路径按 platform_host_root 翻译到当前一侧：
      宿主侧传 {storage_path}/users/{user_id}，容器内不传（挂载本地即是）；
    - 翻译后再做一次 realpath 包含校验，堵住平台数据区内二级软链外跳；
    - 其余一律抛 PathEscapeError。
    """
    root_real = workspace_realpath(root)
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = root_real / candidate
    # 词法归一（不解析软链）：判定用户给出的路径本身是否在工作区内
    lexical = Path(os.path.normpath(candidate))
    lexical_inside = lexical == root_real or root_real in lexical.parents

    resolved = Path(os.path.realpath(lexical))
    if resolved == root_real or root_real in resolved.parents:
        return ResolvedReadPath(resolved, via_platform=False)

    mount_real = Path(os.path.realpath(PLATFORM_CONTAINER_MOUNT))
    if not lexical_inside or (resolved != mount_real and mount_real not in resolved.parents):
        raise PathEscapeError(f"路径越出工作区: {user_path}")

    host_root = Path(platform_host_root) if platform_host_root is not None else mount_real
    host_root_real = Path(os.path.realpath(host_root))
    rel = resolved.relative_to(mount_real)
    translated = Path(os.path.realpath(host_root_real / rel))
    if translated != host_root_real and host_root_real not in translated.parents:
        raise PathEscapeError(f"路径越出平台数据区: {user_path}")
    return ResolvedReadPath(translated, via_platform=True)


def relative_workspace_path(path: Path, root: Path) -> str:
    """转为相对工作区根的 POSIX 路径（root 本身返回空串）"""
    root_real = workspace_realpath(root)
    if path == root_real:
        return ""
    return path.relative_to(root_real).as_posix()
