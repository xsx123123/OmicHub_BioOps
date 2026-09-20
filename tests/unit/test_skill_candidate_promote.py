"""Skill 候选包晋升脚本回归测试。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from cygnusx.infrastructure.skills.skillmd import SkillParseError

PROMOTE_SCRIPT = Path("scripts/promote_skill_candidate.py")


@pytest.fixture
def candidate_dir(tmp_path: Path) -> Path:
    """构造一个最小但合规的 Skill 候选包。"""
    root = tmp_path / "my-candidate"
    root.mkdir()
    skill_md = """---
name: 测试候选技能
skill_id: test-candidate-skill
description: 当用户提供一个 CSV 文件且要求计算基础统计时触发。
version: 0.9.0
author: test
category: analysis
---

# 测试候选技能

## 何时使用

- 用户上传 CSV 且要求均值/标准差/中位数/最值统计。

## 输入契约

| 参数 | 必填 | 说明 |
|---|---|---|
| file_path | 是 | CSV 文件路径（相对 /workspace） |
| columns | 否 | 列名列表，留空统计全部数值列 |

## 执行步骤

1. 读取 CSV；
2. 对指定列计算统计量；
3. 返回 JSON 结果。

## 输出契约

- `summary.json`：包含统计结果。

## 质控与限制

- 文件不存在时返回 error；仅处理数值列。
"""
    (root / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (root / "references").mkdir()
    (root / "references" / "guide.md").write_text("guide", encoding="utf-8")
    (root / "CANDIDATE_MANIFEST.json").write_text(
        json.dumps(
            {
                "skill_id": "test-candidate-skill",
                "name": "测试候选技能",
                "status": "candidate",
                "pending_review_items": ["未跑端到端冒烟"],
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def marketplace_root(tmp_path: Path) -> Path:
    return tmp_path / "marketplace"


def _run_promote(candidate: Path, marketplace: Path, *, dry_run: bool = False) -> int:
    import subprocess

    cmd = [
        "python3",
        str(PROMOTE_SCRIPT),
        "--candidate",
        str(candidate),
        "--admin-user-id",
        "00000000-0000-0000-0000-000000000000",
        "--marketplace-root",
        str(marketplace),
    ]
    if dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode


def test_promote_copies_package(candidate_dir: Path, marketplace_root: Path) -> None:
    ret = _run_promote(candidate_dir, marketplace_root)
    assert ret == 0
    target = marketplace_root / "test-candidate-skill"
    assert target.exists()
    assert (target / "SKILL.md").exists()
    assert (target / "references" / "guide.md").exists()


def test_promote_dry_run_does_not_copy(candidate_dir: Path, marketplace_root: Path) -> None:
    ret = _run_promote(candidate_dir, marketplace_root, dry_run=True)
    assert ret == 0
    assert not (marketplace_root / "test-candidate-skill").exists()


def test_promote_refuses_existing_skill(candidate_dir: Path, marketplace_root: Path) -> None:
    existing = marketplace_root / "test-candidate-skill"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("---\nskill_id: test-candidate-skill\n---\n")

    ret = _run_promote(candidate_dir, marketplace_root)
    assert ret != 0


def test_promote_replace_overwrites(candidate_dir: Path, marketplace_root: Path) -> None:
    existing = marketplace_root / "test-candidate-skill"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("---\nskill_id: test-candidate-skill\n---\n")

    import subprocess

    cmd = [
        "python3",
        str(PROMOTE_SCRIPT),
        "--candidate",
        str(candidate_dir),
        "--admin-user-id",
        "00000000-0000-0000-0000-000000000000",
        "--marketplace-root",
        str(marketplace_root),
        "--replace",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0
    # 确认被覆盖
    assert "测试候选技能" in (existing / "SKILL.md").read_text(encoding="utf-8")


def test_promote_rejects_oversized_package(tmp_path: Path, marketplace_root: Path) -> None:
    root = tmp_path / "big-candidate"
    root.mkdir()
    skill_md = "---\nskill_id: big-skill\nname: Big\ncategory: analysis\n---\n# x\n"
    (root / "SKILL.md").write_text(skill_md, encoding="utf-8")
    # 放一个大文件让包超过 1MiB
    (root / "big.bin").write_bytes(b"x" * (1024 * 1024 + 1))

    ret = _run_promote(root, marketplace_root)
    assert ret != 0


def test_promote_rejects_missing_skill_md(tmp_path: Path, marketplace_root: Path) -> None:
    root = tmp_path / "bad-candidate"
    root.mkdir()
    (root / "README.md").write_text("no skill", encoding="utf-8")

    ret = _run_promote(root, marketplace_root)
    assert ret != 0
