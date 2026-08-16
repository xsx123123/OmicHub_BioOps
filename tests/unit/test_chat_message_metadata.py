"""受控聊天消息 metadata 的持久化白名单测试。"""

from omichub.application.services.chat_service import _extract_user_message_metadata


def test_confirmation_marker_metadata_is_preserved() -> None:
    marker = _extract_user_message_metadata(
        {
            "metadata": {
                "agentteams_case_confirmation": {
                    "key": "case-key",
                    "token": "random-token",
                    "confirmed": True,
                }
            }
        }
    )

    assert marker == {
        "agentteams_case_confirmation": {
            "key": "case-key",
            "token": "random-token",
            "confirmed": True,
        }
    }


def test_untrusted_metadata_is_not_persisted() -> None:
    assert (
        _extract_user_message_metadata(
            {
                "metadata": {
                    "arbitrary": "must-not-persist",
                    "agentteams_case_confirmation": {"key": "case-key", "confirmed": True},
                }
            }
        )
        == {}
    )
