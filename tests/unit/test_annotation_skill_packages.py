"""内置单细胞注释 Skill 包校验。"""

from pathlib import Path

import pytest

from omichub.infrastructure.skills.skillmd import parse_skill_folder


@pytest.mark.unit
@pytest.mark.parametrize(
    ("skill_id", "expected_name"),
    [
        ("human-mouse-cell-annotation", "人/小鼠单细胞注释"),
        ("plant-cell-annotation", "植物单细胞注释"),
    ],
)
def test_annotation_skills_are_valid_marketplace_packages(skill_id: str, expected_name: str):
    skill_path = Path("data/ai/skill_marketplace") / skill_id / "SKILL.md"

    parsed = parse_skill_folder(
        {"SKILL.md": skill_path.read_bytes()}, source_type="market", source_ref=skill_id
    )

    assert parsed.skill_id
    assert parsed.name == expected_name
    assert "注释" in parsed.description
    assert parsed.body
