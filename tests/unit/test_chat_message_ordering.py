from datetime import UTC, datetime
from types import SimpleNamespace

from omichub.application.services.chat_service import ChatService


def test_same_timestamp_places_user_before_assistant() -> None:
    created_at = datetime(2026, 8, 3, 11, 30, 38, tzinfo=UTC)
    assistant = SimpleNamespace(message_id="f-response", role="assistant", created_at=created_at)
    user = SimpleNamespace(message_id="a-request", role="user", created_at=created_at)

    messages = ChatService._order_messages([assistant, user])

    assert [message.message_id for message in messages] == ["a-request", "f-response"]


def test_message_ordering_keeps_distinct_timestamps_chronological() -> None:
    messages = ChatService._order_messages(
        [
            SimpleNamespace(
                message_id="later",
                role="user",
                created_at=datetime(2026, 8, 3, 11, 31, tzinfo=UTC),
            ),
            SimpleNamespace(
                message_id="earlier",
                role="assistant",
                created_at=datetime(2026, 8, 3, 11, 30, tzinfo=UTC),
            ),
        ]
    )

    assert [message.message_id for message in messages] == ["earlier", "later"]
