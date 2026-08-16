"""Shared application-level project-boundary checks."""

from __future__ import annotations

from omichub.core.exceptions import BusinessError


def resolve_agent_project_scope(
    *, agent_project_id: str | None, session_project_id: str | None
) -> str | None:
    """Validate a project-scoped Agent and return the effective session project.

    Global Agents (``agent_project_id is None``) may serve global and project
    sessions. A project-bound Agent may only serve the same project; when a new
    session omits its project, it inherits the Agent's project boundary.
    """
    if agent_project_id is None:
        return session_project_id
    if session_project_id is not None and session_project_id != agent_project_id:
        raise BusinessError("项目专属 Agent 不能绑定到其他项目会话")
    return agent_project_id
