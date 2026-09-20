"""AI 助手沙箱文件挂载：附件自动引入工作区并以文件系统路径提示模型（任务 1/2）。

覆盖点：
- ``_build_multimodal_messages`` 命中 studio_sandbox_paths 时改用工作区路径提示；
- 未命中时保持原 file_id / workspace_read_file 提示（非 Studio 行为不变）；
- ``_collect_session_file_context`` 在提供映射时用沙盒路径描述历史文件。
"""

from typing import Any

import pytest

from cygnusx.application.services.chat_service import ChatService


@pytest.fixture
def no_attachment_text(monkeypatch):
    async def _empty(att: dict[str, Any]) -> str:
        return ""

    monkeypatch.setattr(ChatService, "_read_attachment_text", staticmethod(_empty))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_multimodal_uses_workspace_path_when_mounted(no_attachment_text):
    messages = [{"role": "user", "content": "帮我分析这个文件"}]
    attachments = [
        {
            "type": "file",
            "url": "/api/v1/files/chat-upload/uid/x.csv",
            "name": "x.csv",
            "mime_type": "text/csv",
            "file_id": "upload://abc123",
        }
    ]
    sandbox_paths = {"upload://abc123": "/workspace/input/x.csv"}

    result = await ChatService._build_multimodal_messages(messages, attachments, sandbox_paths)
    content = result[-1]["content"]
    assert isinstance(content, str)
    assert "/workspace/input/x.csv" in content
    # 命中挂载后不应再引导模型用 file:// / workspace_read_file(file_id=…)
    assert "workspace_read_file" not in content
    assert "不要使用 file://" in content or "沙盒内无法解析" in content


@pytest.mark.unit
@pytest.mark.asyncio
async def test_multimodal_falls_back_to_file_id_when_not_mounted(no_attachment_text):
    messages = [{"role": "user", "content": "帮我分析这个文件"}]
    attachments = [
        {
            "type": "file",
            "url": "/api/v1/files/chat-upload/uid/x.csv",
            "name": "x.csv",
            "mime_type": "text/csv",
            "file_id": "abc123",  # 无 scheme → 规范化为 upload://abc123
        }
    ]

    # 未提供映射（非 Studio）→ 保持原 file_id 提示
    result = await ChatService._build_multimodal_messages(messages, attachments, None)
    content = result[-1]["content"]
    assert "upload://abc123" in content
    assert "workspace_read_file" in content


@pytest.mark.unit
@pytest.mark.asyncio
async def test_multimodal_bare_file_id_normalized_for_mapping_lookup(no_attachment_text):
    """attachment 裸 file_id 与映射键（upload://…）应能对上。"""
    messages = [{"role": "user", "content": "分析"}]
    attachments = [
        {
            "type": "file",
            "url": "/api/v1/files/chat-upload/uid/y.tsv",
            "name": "y.tsv",
            "mime_type": "text/tab-separated-values",
            "file_id": "abc123",
        }
    ]
    sandbox_paths = {"upload://abc123": "/workspace/input/y.tsv"}

    result = await ChatService._build_multimodal_messages(messages, attachments, sandbox_paths)
    content = result[-1]["content"]
    assert "/workspace/input/y.tsv" in content


# ===== 历史文件回退措辞按模式分叉（修复 2） =====


def _fake_db_with_history_upload() -> Any:
    """构造只含一条带附件历史用户消息的伪 db。"""
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    message = SimpleNamespace(
        role="user",
        metadata_json={"attachments": [{"file_id": "abc123", "name": "x.csv"}]},
        created_at=datetime(2026, 9, 3, tzinfo=UTC),
        message_id="m1",
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [message]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.unit
@pytest.mark.asyncio
async def test_history_file_context_studio_wording_no_chat_sandbox():
    """Studio 模式未挂载文件的回退措辞不得再提 chat_sandbox_execute（该工具不挂载），
    应引导 datahub_import 引入沙盒。"""
    service = ChatService(_fake_db_with_history_upload())

    text = await service._collect_session_file_context(
        "session-1", user_id=None, studio_sandbox_paths=None, studio_mode=True
    )
    assert "upload://abc123" in text
    assert "chat_sandbox_execute" not in text
    assert "datahub_import" in text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_history_file_context_chat_wording_kept():
    """普通聊天保持原有措辞：chat_sandbox_execute 执行时自动注入。"""
    service = ChatService(_fake_db_with_history_upload())

    text = await service._collect_session_file_context(
        "session-1", user_id=None, studio_sandbox_paths=None, studio_mode=False
    )
    assert "chat_sandbox_execute" in text
    assert "datahub_import" not in text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_history_file_context_studio_mounted_uses_sandbox_path():
    """Studio 模式已挂载的历史文件仍按沙盒路径描述（不受分叉影响）。"""
    service = ChatService(_fake_db_with_history_upload())

    text = await service._collect_session_file_context(
        "session-1",
        user_id=None,
        studio_sandbox_paths={"upload://abc123": "/workspace/input/x.csv"},
        studio_mode=True,
    )
    assert "/workspace/input/x.csv" in text
    assert "workspace_read_file" not in text
