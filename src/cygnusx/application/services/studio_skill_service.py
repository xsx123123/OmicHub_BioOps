"""从 Studio 工作区脚本提炼可复用 Skill。"""

from __future__ import annotations

import re
from pathlib import Path

from cygnusx.application.schemas.skill import CreateSkillDTO, SkillDTO
from cygnusx.application.schemas.studio import ExtractStudioSkillRequest
from cygnusx.application.services.skill_service import SkillService
from cygnusx.infrastructure.config.prompt_loader import render_prompt
from cygnusx.core.exceptions import BusinessError
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.studio.manager import studio_sandbox_manager
from cygnusx.infrastructure.studio.paths import PathEscapeError, resolve_workspace_path

_ALLOWED_EXTENSIONS = {".py", ".r", ".R", ".sh", ".bash"}
_MAX_SCRIPT_BYTES = 256 * 1024
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|password|passwd|access[_-]?token)\s*[:=]"),
    re.compile(r"(?i)\bsk-[a-z0-9]{16,}\b"),
)


async def extract_skill_from_workspace(
    session: ChatSessionModel,
    req: ExtractStudioSkillRequest,
    skill_service: SkillService,
    *,
    owner_id: str,
    visibility: str,
) -> SkillDTO:
    """读取工作区脚本并通过现有 SkillService 持久化，拒绝越界/二进制/未确认内容。"""
    if not req.confirm_no_secrets:
        raise BusinessError("提炼前必须确认脚本不包含密钥、密码或用户隐私数据")
    path = req.path.strip()
    suffix = Path(path).suffix
    if suffix not in _ALLOWED_EXTENSIONS:
        raise BusinessError("仅允许提炼 .py、.R、.r、.sh 或 .bash 脚本")
    workspace = studio_sandbox_manager.workspace_dir(session.session_id)
    try:
        target = resolve_workspace_path(path, root=workspace)
    except PathEscapeError as exc:
        raise BusinessError(str(exc)) from exc
    if not target.is_file():
        raise BusinessError("脚本文件不存在")
    try:
        if target.stat().st_size > _MAX_SCRIPT_BYTES:
            raise BusinessError("脚本超过 256KB，无法提炼为 Skill")
        source = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BusinessError("脚本必须是 UTF-8 文本") from exc
    except OSError as exc:
        raise BusinessError(f"读取脚本失败: {exc}") from exc
    if not source.strip():
        raise BusinessError("脚本内容为空")
    # 这是额外防线，不替代管理员确认；命中时直接阻止误把凭据沉淀到全局 Skill。
    if any(pattern.search(source) for pattern in _SECRET_PATTERNS):
        raise BusinessError("脚本疑似包含密钥/密码赋值，请清理后再提炼")

    language = {".py": "python", ".r": "r", ".R": "r", ".sh": "bash", ".bash": "bash"}[suffix]
    prompt = render_prompt(
        "skills.extracted_skill",
        name=req.name,
        description=req.description.strip(),
        usage_instructions=(
            req.usage_instructions.strip()
            or "请先阅读脚本并根据当前数据路径调整参数。"
        ),
        language=language,
        source=source.rstrip(),
        session_id=session.session_id,
        path=path,
    )
    skill = await skill_service.create_skill(
        CreateSkillDTO(
            skill_id=req.skill_id,
            name=req.name,
            description=req.description,
            prompt=prompt,
            category=req.category,
            icon=req.icon,
            is_active=True,
        ),
        studio_owner_id=owner_id,
        studio_visibility=visibility,
    )
    meta = dict(session.sandbox_meta or {})
    commands = list(meta.get("skill_commands") or [])
    commands = [item for item in commands if item.get("skill_id") != skill.skill_id]
    commands.append(
        {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "description": skill.description,
            "visibility": visibility,
            "command": f"/skill:{skill.skill_id}",
        }
    )
    meta["skill_commands"] = commands[-100:]
    session.sandbox_meta = meta
    return skill
