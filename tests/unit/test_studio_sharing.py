"""Studio 分享令牌、快照与打印报告测试。"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cygnusx.application.schemas.studio import (
    SharedStudioMessageDTO,
    SharedStudioSessionDTO,
)
from cygnusx.application.services.studio_sharing import (
    create_share,
    render_printable_report,
    resolve_shared_artifact,
    revoke_share,
    share_is_active,
    share_token_hash,
)
from cygnusx.core.exceptions import NotFoundError
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.studio import manager as manager_module


def _session() -> ChatSessionModel:
    return ChatSessionModel(
        id=uuid.uuid4(),
        session_id="share-session-1",
        user_id="user-1",
        model_id=uuid.uuid4(),
        title="火山图优化",
        status="active",
        mode="studio",
        message_count=2,
        total_tokens=0,
        sandbox_meta={},
    )


@pytest.mark.unit
def test_share_stores_only_hash_and_can_be_revoked():
    session = _session()
    token, expires_at = create_share(session, 24)

    assert len(token) >= 32
    assert session.share_token_hash == share_token_hash(token)
    assert token not in session.share_token_hash
    assert session.share_expires_at == expires_at
    assert share_is_active(session)

    revoke_share(session)
    assert session.share_token_hash is None
    assert session.share_expires_at is None
    assert not share_is_active(session)


@pytest.mark.unit
def test_expired_share_is_inactive():
    session = _session()
    session.share_token_hash = share_token_hash("a" * 40)
    session.share_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not share_is_active(session)


@pytest.mark.unit
def test_printable_report_escapes_message_and_artifact_markup():
    snapshot = SharedStudioSessionDTO(
        title="<unsafe>",
        agent_id="agent-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        messages=[
            SharedStudioMessageDTO(
                role="assistant",
                content='<script>alert("x")</script>\n**safe text**',
                created_at=datetime.now(UTC),
            )
        ],
        artifacts=[{"path": 'output/<img>.png', "size": 12}],
    )

    report = render_printable_report(snapshot)

    assert "<script>alert" not in report
    assert "&lt;script&gt;" in report
    assert "output/&lt;img&gt;.png" in report
    assert 'onclick="window.print()"' in report


@pytest.mark.unit
def test_shared_artifact_resolution_is_output_only(tmp_path: Path, monkeypatch):
    session = _session()
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager,
        "workspace_dir",
        lambda session_id: tmp_path,
    )
    output = tmp_path / "output"
    output.mkdir()
    target = output / "plot.png"
    target.write_bytes(b"png")
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "secret.txt").write_text("secret", encoding="utf-8")

    assert resolve_shared_artifact(session, "output/plot.png") == target
    with pytest.raises(NotFoundError):
        resolve_shared_artifact(session, "input/secret.txt")
    with pytest.raises(NotFoundError):
        resolve_shared_artifact(session, "output/../input/secret.txt")


# ===== R4（WP3 任务 4）：分享快照补 metadata_json / 产物 sha256 / 打印版工具卡 =====


@pytest.mark.unit
def test_share_message_metadata_whitelist_and_passthrough():
    from cygnusx.application.services.studio_sharing import _share_message_metadata

    meta = {
        "tool_invocations": [
            {
                "tool_call_id": "tc-1",
                "tool_name": "sandbox_execute",
                "arguments": {"language": "python", "code": "print(1)"},
                "success": True,
                "result": {"exit_code": 0},
                "payload_hash": "h" * 64,
            }
        ],
        "timeline": [{"ts": 1, "event": "tool_start"}],
        "usage": {"input": 1, "output": 2, "total": 3},
        # 非白名单键不得外泄
        "senderAgent": "internal-only",
        "model": "internal-only",
    }
    shared = _share_message_metadata(meta)
    assert shared is not None
    assert shared["tool_invocations"][0]["tool_name"] == "sandbox_execute"
    assert shared["tool_invocations"][0]["arguments"]["code"] == "print(1)"
    assert shared["timeline"] == [{"ts": 1, "event": "tool_start"}]
    assert shared["usage"]["total"] == 3
    assert "senderAgent" not in shared and "model" not in shared
    # 无执行历史 → None（DTO 不挂空对象）
    assert _share_message_metadata({"model": "x"}) is None


@pytest.mark.unit
def test_share_message_metadata_truncation_marker():
    """复用 WP0 200KB 护栏：超限整体替换为截断标记并带 truncation 元信息。"""
    from cygnusx.application.services.studio_sharing import _share_message_metadata

    big_invocations = [{"tool_name": "sandbox_execute", "result": "x" * 500_000}]
    shared = _share_message_metadata({"tool_invocations": big_invocations})
    assert shared is not None
    assert shared["tool_invocations"] == {"_cygnusx_payload_truncated": True}
    assert shared["tool_invocations_truncation"]["payload_truncated"] is True
    assert shared["tool_invocations_truncation"]["original_bytes"] > 200_000


@pytest.mark.unit
def test_printable_report_contains_tool_cards_and_sha256():
    snapshot = SharedStudioSessionDTO(
        title="火山图优化",
        agent_id="agent-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        messages=[
            SharedStudioMessageDTO(
                role="assistant",
                content="已完成绘图",
                created_at=datetime.now(UTC),
                metadata_json={
                    "tool_invocations": [
                        {
                            "tool_name": "sandbox_execute",
                            "success": True,
                            "arguments": {"language": "python", "code": "import matplotlib"},
                            "result": {"exit_code": 0, "artifacts": ["output/volcano.png"]},
                        },
                        {
                            "tool_name": "knowledge_search",
                            "success": False,
                            "arguments": {"query": "tp53"},
                            "result_truncation": {"payload_truncated": True},
                        },
                    ]
                },
            )
        ],
        artifacts=[{"path": "output/volcano.png", "size": 123, "sha256": "ab" * 32}],
    )

    report = render_printable_report(snapshot)

    # 工具卡摘要：代码 + 成功/失败 + 截断标记
    assert "sandbox_execute" in report
    assert "import matplotlib" in report
    assert "knowledge_search" in report
    assert "已截断" in report
    # 产物 sha256 摘要
    assert "sha256:abababababababab…" in report


@pytest.mark.unit
async def test_artifact_checksums_indexed_by_name_and_size(monkeypatch):
    from cygnusx.application.services import studio_sharing
    from cygnusx.infrastructure.database.models.file import FileRecordModel

    record = FileRecordModel(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        original_name="volcano.png",
        storage_path="users/u/projects/p/runs/r/output/volcano.png",
        size=123,
        checksum="cd" * 32,
        source="studio",
    )

    class _Scalars:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return _Scalars(self._rows)

    class _Db:
        async def execute(self, _stmt):
            return _Result([record])

    async def _run():
        session = _session()
        session.user_id = str(record.user_id)
        return await studio_sharing._artifact_checksums(_Db(), session)

    indexed = await _run()
    assert indexed == {("volcano.png", 123): "cd" * 32}
