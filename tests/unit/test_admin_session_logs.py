from types import SimpleNamespace

from cygnusx.api.v1.admin.session_logs import _execution_mode


def _session(
    *,
    mode: str = "chat",
    workspace_id: str | None = None,
    sandbox_meta: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        mode=mode,
        workspace_id=workspace_id,
        sandbox_meta=sandbox_meta or {},
    )


def test_execution_mode_prefers_overdrive_runtime_over_studio_shell() -> None:
    session = _session(mode="studio", sandbox_meta={"overdrive": True})

    assert _execution_mode(session) == "overdrive"


def test_execution_mode_keeps_historical_overdrive_after_toggle_is_disabled() -> None:
    session = _session(
        sandbox_meta={"overdrive": False, "overdrive_used": True},
    )

    assert _execution_mode(session) == "overdrive"


def test_execution_mode_detects_existing_overdrive_run_history() -> None:
    session = _session(
        sandbox_meta={"overdrive": False, "overdrive_runs": [{"run_id": "run-1"}]},
    )

    assert _execution_mode(session) == "overdrive"


def test_execution_mode_detects_legacy_overdrive_messages() -> None:
    session = _session(sandbox_meta={"overdrive": False})

    assert _execution_mode(session, has_overdrive_messages=True) == "overdrive"


def test_execution_mode_preserves_studio_and_standard_chat_categories() -> None:
    assert _execution_mode(_session(mode="studio")) == "studio"
    assert _execution_mode(_session(workspace_id="legacy-studio-workspace")) == "studio"
    assert _execution_mode(_session()) == "chat"
