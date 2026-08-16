"""Studio 脚本提炼 Skill 的安全边界测试。"""

import uuid
from pathlib import Path

import pytest

from omichub.application.schemas.studio import ExtractStudioSkillRequest
from omichub.application.services.studio_skill_service import extract_skill_from_workspace
from omichub.core.exceptions import BusinessError
from omichub.infrastructure.database.models.chat import ChatSessionModel
from omichub.infrastructure.studio import manager as manager_module


def _session() -> ChatSessionModel:
    return ChatSessionModel(
        id=uuid.uuid4(),
        session_id="skill-session-1",
        user_id="admin-1",
        model_id=uuid.uuid4(),
        title="Skill 工作台",
        status="active",
        mode="studio",
        sandbox_meta={},
    )


class _FakeSkillService:
    def __init__(self) -> None:
        self.request = None

    async def create_skill(self, request):
        self.request = request
        return request


def _request(**overrides) -> ExtractStudioSkillRequest:
    payload = {
        "path": "scripts/volcano.py",
        "skill_id": "volcano-plot",
        "name": "火山图绘制",
        "description": "复现并优化火山图",
        "usage_instructions": "先读取 input/de_result.csv，再输出到 output/。",
        "confirm_no_secrets": True,
    }
    payload.update(overrides)
    return ExtractStudioSkillRequest(**payload)


@pytest.mark.unit
async def test_extract_skill_packages_script_with_provenance(tmp_path: Path, monkeypatch):
    script = tmp_path / "scripts" / "volcano.py"
    script.parent.mkdir()
    script.write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setattr(manager_module.studio_sandbox_manager, "workspace_dir", lambda _: tmp_path)
    service = _FakeSkillService()

    result = await extract_skill_from_workspace(_session(), _request(), service)

    assert result.skill_id == "volcano-plot"
    assert "print('hello')" in result.prompt
    assert "skill-session-1" in result.prompt
    assert "scripts/volcano.py" in result.prompt
    assert result.is_active is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"confirm_no_secrets": False}, "必须确认"),
        ({"path": "input/data.csv"}, "仅允许提炼"),
        ({"path": "../secret.py"}, "越出工作区"),
    ],
)
async def test_extract_skill_rejects_unsafe_requests(
    tmp_path: Path, monkeypatch, overrides: dict[str, object], expected: str
):
    script = tmp_path / "scripts" / "volcano.py"
    script.parent.mkdir()
    script.write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setattr(manager_module.studio_sandbox_manager, "workspace_dir", lambda _: tmp_path)

    with pytest.raises(BusinessError, match=expected):
        await extract_skill_from_workspace(_session(), _request(**overrides), _FakeSkillService())


@pytest.mark.unit
async def test_extract_skill_rejects_detected_secret(tmp_path: Path, monkeypatch):
    script = tmp_path / "scripts" / "volcano.py"
    script.parent.mkdir()
    script.write_text("API_KEY = 'sk-1234567890abcdef'\n", encoding="utf-8")
    monkeypatch.setattr(manager_module.studio_sandbox_manager, "workspace_dir", lambda _: tmp_path)

    with pytest.raises(BusinessError, match="疑似包含密钥"):
        await extract_skill_from_workspace(_session(), _request(), _FakeSkillService())


@pytest.mark.unit
async def test_extract_skill_rejects_oversized_script(tmp_path: Path, monkeypatch):
    script = tmp_path / "scripts" / "volcano.py"
    script.parent.mkdir()
    script.write_bytes(b"x" * (256 * 1024 + 1))
    monkeypatch.setattr(manager_module.studio_sandbox_manager, "workspace_dir", lambda _: tmp_path)

    with pytest.raises(BusinessError, match="超过 256KB"):
        await extract_skill_from_workspace(_session(), _request(), _FakeSkillService())
