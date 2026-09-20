"""Request-local AgentTeams execution context used by process-record capture."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any


agentteams_ctx_var: ContextVar[dict[str, Any] | None] = ContextVar(
    "agentteams_ctx", default=None
)
