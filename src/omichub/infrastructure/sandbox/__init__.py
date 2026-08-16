"""沙盒编排与执行基础设施"""

from __future__ import annotations

from functools import lru_cache

from omichub.infrastructure.sandbox.pool import SandboxPool


@lru_cache
def get_sandbox_pool() -> SandboxPool:
    """沙盒容器池单例"""
    return SandboxPool()
