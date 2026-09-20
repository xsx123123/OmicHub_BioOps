from cygnusx.application.services.chat_service import _active_agentteams_case_id


def test_active_agentteams_case_prefers_latest_open_binding() -> None:
    assert _active_agentteams_case_id(
        {
            "agentteams_case_ids": ["case-closed", "case-running"],
            "agentteams_case_status": {
                "case-closed": "closed",
                "case-running": "executing",
            },
        }
    ) == "case-running"


def test_active_agentteams_case_ignores_terminal_bindings() -> None:
    assert _active_agentteams_case_id(
        {
            "agentteams_case_ids": ["case-closed", "case-cancelled"],
            "agentteams_case_status": {
                "case-closed": "closed",
                "case-cancelled": "cancelled",
            },
        }
    ) is None
