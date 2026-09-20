from datetime import UTC, datetime

from cygnusx.application.services.chat_service import ChatService
from cygnusx.infrastructure.ai_provider.openai_compatible import (
    merge_token_usage,
    normalize_token_usage,
)
from cygnusx.infrastructure.database.models.chat import ChatMessageModel


def test_normalize_qwen_input_output_tokens():
    usage = normalize_token_usage({"input_tokens": 120, "output_tokens": 30})

    assert usage is not None
    assert usage["prompt_tokens"] == 120
    assert usage["completion_tokens"] == 30
    assert usage["total_tokens"] == 150


def test_normalize_nested_token_usage():
    usage = normalize_token_usage(
        {"token_usage": {"input_tokens": "80", "output_tokens": "20", "total": "100"}}
    )

    assert usage is not None
    assert usage["prompt_tokens"] == 80
    assert usage["completion_tokens"] == 20
    assert usage["total_tokens"] == 100


def test_merge_usage_accumulates_studio_model_rounds():
    usage = merge_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        {"input_tokens": 180, "output_tokens": 25},
    )

    assert usage == {
        "prompt_tokens": 280,
        "completion_tokens": 35,
        "total_tokens": 315,
        "cached_tokens": 0,
    }


def test_normalize_extracts_openai_cached_tokens():
    usage = normalize_token_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 800},
        }
    )

    assert usage is not None
    assert usage["cached_tokens"] == 800


def test_normalize_extracts_anthropic_cache_read_tokens():
    usage = normalize_token_usage(
        {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 700}
    )

    assert usage is not None
    assert usage["cached_tokens"] == 700


def test_merge_usage_accumulates_cached_tokens():
    usage = merge_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110, "cached_tokens": 40},
        {
            "prompt_tokens": 1000,
            "completion_tokens": 25,
            "total_tokens": 1025,
            "prompt_tokens_details": {"cached_tokens": 800},
        },
    )

    assert usage is not None
    assert usage["cached_tokens"] == 840


def test_message_dto_reads_historical_qwen_usage_fields():
    message = ChatMessageModel(
        message_id="msg-usage",
        session_id="session-usage",
        role="assistant",
        content="ok",
        content_type="text",
        metadata_json={"usage": {"input_tokens": 42, "output_tokens": 8}},
        status="complete",
        created_at=datetime.now(UTC),
    )

    dto = ChatService._to_msg_dto(message)

    assert dto.tokens == {"input": 42, "output": 8, "total": 50, "cached": 0}


def test_message_dto_does_not_expose_usage_on_user_message():
    message = ChatMessageModel(
        message_id="msg-user-usage",
        session_id="session-usage",
        role="user",
        content="question",
        content_type="text",
        metadata_json={"usage": {"input_tokens": 2526, "output_tokens": 0}},
        status="complete",
        created_at=datetime.now(UTC),
    )

    dto = ChatService._to_msg_dto(message)

    assert dto.tokens == {"input": 0, "output": 0, "total": 0, "cached": 0}

