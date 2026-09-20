#!/usr/bin/env python3
"""存量 JSON 配置型技能 → SKILL.md 标准文件夹 一次性迁移脚本

对每个 skills 表记录：
  - 生成 data/ai/skills/<skill_id>/SKILL.md（元信息 → frontmatter，prompt → 正文）
  - 回填 source_type（builtin/json）——仅当仍为默认值时

默认 dry-run，只打印差异报告；加 --apply 才写盘写库。
建议在 `alembic upgrade head`（含 c9d0e1f2a3b4）之后执行。

用法:
    python scripts/migrate_skills_to_skillmd.py            # dry-run
    python scripts/migrate_skills_to_skillmd.py --apply    # 实际迁移
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.skill import SkillModel
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.infrastructure.skills.skillmd import ParsedSkill, render_skill_md
from cygnusx.infrastructure.skills.skill_store import skills_root, write_skill_folder


def _to_parsed(m: SkillModel) -> ParsedSkill:
    return ParsedSkill(
        skill_id=m.skill_id,
        name=m.name,
        description=m.description or f"{m.name} 技能",
        body=m.prompt or "",
        frontmatter={"migrated_from": "json", "skill_pk": str(m.id)},
        icon=m.icon or "\U0001f527",
        category=m.category or "general",
        version=m.version or "",
        author=m.author or "",
    )


async def migrate(session: AsyncSession, apply: bool) -> None:
    result = await session.execute(select(SkillModel).order_by(SkillModel.created_at))
    rows = result.scalars().all()
    root = skills_root()
    print(f"技能库目录: {root.resolve()}")
    print(f"共 {len(rows)} 条技能记录\n")

    changed = 0
    for m in rows:
        parsed = _to_parsed(m)
        folder = root / m.skill_id
        folder_exists = (folder / "SKILL.md").is_file()

        # 已有磁盘文件夹且内容一致 → 跳过
        if folder_exists:
            try:
                from cygnusx.infrastructure.skills.skillmd import split_frontmatter

                _, existing_body = split_frontmatter(
                    (folder / "SKILL.md").read_text(encoding="utf-8")
                )
                if existing_body.strip() == parsed.body.strip():
                    print(f"[跳过] {m.skill_id}: SKILL.md 已存在且正文一致")
                    continue
            except Exception:  # noqa: BLE001
                pass

        new_source_type = m.source_type
        if m.source_type == "json" and m.is_builtin:
            new_source_type = "builtin"

        print(f"[{'写入' if apply else '预览'}] {m.skill_id} ({m.name})")
        print(f"    frontmatter: name/description/icon={m.icon}/category={m.category}")
        print(f"    正文长度: {len(parsed.body)} 字符")
        print(f"    文件夹: {'已存在(将覆盖)' if folder_exists else '新建'}")
        if new_source_type != m.source_type:
            print(f"    source_type: {m.source_type} -> {new_source_type}")

        if apply:
            write_skill_folder(parsed)
            if new_source_type != m.source_type:
                m.source_type = new_source_type
            changed += 1

    if apply:
        await session.commit()
        print(f"\n迁移完成：写入/更新 {changed} 个技能文件夹")
    else:
        print("\n以上为 dry-run 预览。确认无误后加 --apply 执行。")


async def main() -> None:
    parser = argparse.ArgumentParser(description="存量技能迁移到 SKILL.md 标准文件夹")
    parser.add_argument("--apply", action="store_true", help="实际写盘写库（默认 dry-run）")
    args = parser.parse_args()

    factory = get_session_factory()
    async with factory() as session:
        await migrate(session, apply=args.apply)


if __name__ == "__main__":
    asyncio.run(main())
