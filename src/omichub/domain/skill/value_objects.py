"""Skill 域值对象"""

from enum import StrEnum


class SkillCategory(StrEnum):
    """技能分类"""

    GENERAL = "general"
    ANALYSIS = "analysis"
    CODE = "code"
    VISUALIZATION = "visualization"
    SEARCH = "search"
