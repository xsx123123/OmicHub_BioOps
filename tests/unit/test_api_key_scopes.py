from omichub.middleware.auth import (
    SELF_AUTHENTICATED_PATHS,
    api_key_allows_scope,
    required_api_key_scope,
)


def test_bridge_task_routes_require_explicit_api_key_scopes() -> None:
    assert required_api_key_scope("GET", "/api/v1/flows") == "flows:read"
    assert required_api_key_scope("GET", "/api/v1/flows/rna_seq/schema") == "flows:read"
    assert required_api_key_scope("POST", "/api/v1/tasks") == "tasks:submit"
    assert required_api_key_scope("GET", "/api/v1/tasks/task-1") == "tasks:read"
    assert required_api_key_scope("POST", "/api/v1/tasks/task-1/cancel") == "tasks:cancel"


def test_restricted_api_key_only_allows_declared_scope() -> None:
    scopes = frozenset({"flows:read", "tasks:read"})

    assert api_key_allows_scope(scopes, "flows:read")
    assert not api_key_allows_scope(scopes, "tasks:submit")
    assert not api_key_allows_scope(scopes, None)
    assert api_key_allows_scope(frozenset({"*"}), "tasks:submit")
    assert api_key_allows_scope(frozenset({"*"}), None)


def test_agentteams_capabilities_uses_its_integration_token_guard() -> None:
    assert "/api/v1/agent-teams/capabilities" in SELF_AUTHENTICATED_PATHS
