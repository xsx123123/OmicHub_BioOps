"""Studio 分享令牌、快照与打印报告测试。"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from omichub.application.schemas.studio import (
    SharedStudioMessageDTO,
    SharedStudioSessionDTO,
)
from omichub.application.services.studio_sharing import (
    create_share,
    render_printable_report,
    resolve_shared_artifact,
    revoke_share,
    share_is_active,
    share_token_hash,
)
from omichub.core.exceptions import NotFoundError
from omichub.infrastructure.database.models.chat import ChatSessionModel
from omichub.infrastructure.studio import manager as manager_module


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
