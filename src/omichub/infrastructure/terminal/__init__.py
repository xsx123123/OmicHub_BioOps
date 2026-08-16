"""终端基础设施"""

from __future__ import annotations

from functools import lru_cache

from omichub.infrastructure.terminal.docker_manager import TerminalDockerManager


@lru_cache
def get_terminal_docker_manager() -> TerminalDockerManager:
    """终端 Docker 管理器单例"""
    return TerminalDockerManager()
