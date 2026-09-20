"""OmicStudio AI 分析工作台 —— 沙盒会话编排与产物管理。"""

from cygnusx.infrastructure.studio.manager import (
    SandboxHandle,
    StudioSandboxManager,
    StudioSandboxUnavailableError,
    studio_sandbox_manager,
)
from cygnusx.infrastructure.studio.paths import PathEscapeError, resolve_workspace_path

__all__ = [
    "PathEscapeError",
    "SandboxHandle",
    "StudioSandboxManager",
    "StudioSandboxUnavailableError",
    "resolve_workspace_path",
    "studio_sandbox_manager",
]
