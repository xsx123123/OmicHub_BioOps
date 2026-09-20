"""内置单细胞注释 Skill 包校验。"""

from pathlib import Path

import pytest

from cygnusx.infrastructure.skills.skillmd import parse_skill_folder
from cygnusx.application.services.skill_import_service import _builtin_category_map


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


@pytest.mark.unit
def test_builtin_bioskills_keep_source_category_taxonomy():
    category_map = _builtin_category_map(Path("data/ai/skill_marketplace"))

    assert len(category_map) == 561
    assert len(set(category_map.values())) == 63
    assert category_map["bio-alignment-alignment-io"] == "alignment"
    assert category_map["bio-alignment-files-bam-statistics"] == "alignment-files"
