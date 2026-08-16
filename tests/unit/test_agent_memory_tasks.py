"""长期记忆异步摘要任务的无外部依赖契约测试。"""

from types import SimpleNamespace

from omichub.infrastructure.celery_app.tasks.memory import _conversation_text, _summary_content


def test_conversation_text_excludes_empty_and_non_chat_messages() -> None:
    messages = [
        SimpleNamespace(role="user", content="我使用 GRCh38"),
        SimpleNamespace(role="tool", content="不应进入摘要"),
        SimpleNamespace(role="assistant", content="收到"),
        SimpleNamespace(role="assistant", content="  "),
    ]

    assert _conversation_text(messages) == "user: 我使用 GRCh38\nassistant: 收到"


def test_summary_content_is_single_line_and_bounded() -> None:
    response = {
        "choices": [
            {"message": {"content": "  用户使用\nGRCh38 作为参考基因组。  "}}
        ]
    }

    assert _summary_content(response) == "用户使用 GRCh38 作为参考基因组。"
    assert _summary_content({"choices": []}) == ""
