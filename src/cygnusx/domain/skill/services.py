"""Skill 域服务"""

from cygnusx.domain.skill.entities import Skill
from cygnusx.infrastructure.config.prompt_loader import render_prompt

USE_SKILL_TOOL_NAME = "use_skill"
SKILL_RESOURCE_TOOL_NAME = "skill_resource"
SKILL_TOOL_NAMES = frozenset({USE_SKILL_TOOL_NAME, SKILL_RESOURCE_TOOL_NAME})


def build_skill_tools(skills: list[Skill]) -> list[dict]:
    """L2/L3 内部工具 schema：use_skill（加载正文）+ skill_resource（读资源）"""
    if not skills:
        return []
    id_enum = [skill.skill_id for skill in skills]
    id_desc = "；".join(f"{s.skill_id}={s.name}" for s in skills)
    return [
        {
            "type": "function",
            "function": {
                "name": USE_SKILL_TOOL_NAME,
                "description": (
                    "加载已挂载技能的完整指令（SKILL.md 正文）。"
                    "任务命中某技能描述时必须先调用本工具获取执行步骤，不要猜测技能内容。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_id": {
                            "type": "string",
                            "description": f"技能唯一 ID（{id_desc}）",
                            "enum": id_enum,
                        }
                    },
                    "required": ["skill_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": SKILL_RESOURCE_TOOL_NAME,
                "description": (
                    "按需读取技能文件夹内 references/ 或 assets/ 下的资源文件内容。"
                    "仅在技能正文要求查阅某份参考资料时调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string", "enum": id_enum},
                        "path": {
                            "type": "string",
                            "description": "技能文件夹内相对路径，如 references/guide.md",
                        },
                    },
                    "required": ["skill_id", "path"],
                },
            },
        },
    ]


class SkillDomainService:
    """技能域服务 — 纯领域逻辑"""

    @staticmethod
    def build_prompt(skills: list[Skill]) -> str:
        """将启用技能组装为 system prompt 注入文本（全量，legacy / Studio 兼容）"""
        if not skills:
            return ""
        content = "\n\n".join(
            f"## {skill.name}\n{skill.description}\n{skill.prompt}" for skill in skills
        )
        return render_prompt("skills.wrapper", skills=content)

    @staticmethod
    def build_index(skills: list[Skill]) -> str:
        """L1：仅注入 name + description 元数据索引（每技能约 100 tokens）"""
        if not skills:
            return ""
        lines = [
            f"- **{skill.name}**（skill_id: `{skill.skill_id}`）：{skill.description}"
            for skill in skills
        ]
        return render_prompt("skills.index", skills="\n".join(lines))
