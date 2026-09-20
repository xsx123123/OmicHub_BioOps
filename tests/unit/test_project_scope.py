"""Project-bound Agent/session compatibility contracts."""

import pytest

from cygnusx.application.services.project_scope import resolve_agent_project_scope
from cygnusx.core.exceptions import BusinessError


def test_global_agent_preserves_requested_session_project() -> None:
    assert (
        resolve_agent_project_scope(agent_project_id=None, session_project_id="project-a")
        == "project-a"
    )


def test_project_agent_inherits_project_for_new_session() -> None:
    assert (
        resolve_agent_project_scope(agent_project_id="project-a", session_project_id=None)
        == "project-a"
    )


def test_project_agent_rejects_another_project_session() -> None:
    with pytest.raises(BusinessError, match="项目专属 Agent"):
        resolve_agent_project_scope(agent_project_id="project-a", session_project_id="project-b")
