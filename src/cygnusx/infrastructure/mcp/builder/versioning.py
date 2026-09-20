"""MCP Builder 版本管理工具 — SemVer 扩展.

版本号格式: ``{major}.{minor}.{patch}[-{prerelease}]``

- 1.0.0        初始发布
- 1.1.0        新增工具 (feature)
- 1.1.1        Bug 修复 (fix) / 重构 (refactor)
- 2.0.0        破坏性变更 (breaking)
- 1.2.0-beta   实验版本
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cygnusx.domain.mcp.entities import MCPServer

#: 合法变更类型 → 版本段递进规则
CHANGE_TYPES = ("feature", "fix", "breaking", "refactor")

#: config_snapshot 覆盖的配置字段（与 MCPServer 实体属性同名，transport 存枚举值）
CONFIG_SNAPSHOT_FIELDS = (
    "name",
    "description",
    "transport",
    "command",
    "args",
    "url",
    "env",
    "registry",
    "working_dir",
    "version",
    "timeout",
    "auto_restart",
    "is_enabled",
)


def extract_config_snapshot(server: MCPServer) -> dict[str, Any]:
    """提取 MCP Server 当前连接/行为配置快照（供版本行完整归档）.

    admin 手工更新、builder 构建发布、回滚、转正四条路径共用，
    保证任意来源的版本行都能被完整还原。
    """
    data: dict[str, Any] = {}
    for field in CONFIG_SNAPSHOT_FIELDS:
        value = getattr(server, field)
        if field == "transport":
            value = value.value if hasattr(value, "value") else str(value)
        elif isinstance(value, (list, dict)):
            value = type(value)(value)
        data[field] = value
    return data

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?$"
)


def is_valid_semver(version: str) -> bool:
    """判断字符串是否为合法 SemVer 版本号."""
    return bool(version) and _SEMVER_RE.match(version.strip()) is not None


def parse_semver(version: str) -> tuple[int, int, int, str | None]:
    """解析版本号为 (major, minor, patch, prerelease).

    非法版本号抛 ``ValueError``。
    """
    m = _SEMVER_RE.match((version or "").strip())
    if not m:
        raise ValueError(f"非法 SemVer 版本号: {version!r}")
    return (
        int(m.group("major")),
        int(m.group("minor")),
        int(m.group("patch")),
        m.group("pre"),
    )


def determine_version(parent_version: str, change_type: str) -> str:
    """根据变更类型自动推导下一个版本号.

    Args:
        parent_version: 上一个版本号，如 ``"1.2.3"`` 或 ``"1.2.0-beta"``
        change_type: ``feature`` | ``fix`` | ``breaking`` | ``refactor``

    Returns:
        新版本号（不含 prerelease 后缀）。

    Raises:
        ValueError: parent_version 非法或 change_type 未知。
    """
    if change_type not in CHANGE_TYPES:
        raise ValueError(
            f"未知变更类型 {change_type!r}，可选: {', '.join(CHANGE_TYPES)}"
        )
    major, minor, patch, _pre = parse_semver(parent_version)

    if change_type == "breaking":
        return f"{major + 1}.0.0"
    if change_type == "feature":
        return f"{major}.{minor + 1}.0"
    # fix / refactor → patch 递增
    return f"{major}.{minor}.{patch + 1}"


def compare_versions(a: str, b: str) -> int:
    """比较两个 SemVer 版本号.

    Returns:
        -1 / 0 / 1（a < b / a == b / a > b）。
        预发布版本 < 同三段数的正式版本（1.0.0-beta < 1.0.0）。
    """
    ma, mia, pa, prea = parse_semver(a)
    mb, mib, pb, preb = parse_semver(b)
    core_a, core_b = (ma, mia, pa), (mb, mib, pb)
    if core_a != core_b:
        return -1 if core_a < core_b else 1
    if prea == preb:
        return 0
    if prea is None:
        return 1  # 无预发布标记 > 有预发布标记
    if preb is None:
        return -1
    return -1 if prea < preb else 1
