#!/usr/bin/env python3
"""批量导入 scrna skills 到平台

从 pipelines/scrna/skills/ 目录读取所有技能，调用 skill_import_service.py 进行导入。
"""

import asyncio
import sys
from pathlib import Path
from typing import List

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from cygnusx.application.services.skill_import_service import SkillImportService
from cygnusx.infrastructure.skills.skillmd import parse_skill_folder
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


async def import_skills():
    """批量导入所有 scrna skills"""
    
    # 技能目录
    skills_dir = Path(__file__).parent.parent / "pipelines" / "scrna" / "skills"
    
    if not skills_dir.exists():
        print(f"❌ 技能目录不存在：{skills_dir}")
        return
    
    # 获取所有技能文件夹
    skill_folders: List[Path] = []
    for item in skills_dir.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            skill_folders.append(item)
    
    print(f"📂 找到 {len(skill_folders)} 个技能文件夹")
    
    # 解析每个技能
    parsed_skills = []
    for folder in skill_folders:
        print(f"\n🔍 解析技能：{folder.name}")
        try:
            # 读取 SKILL.md
            skill_md = folder / "SKILL.md"
            if not skill_md.exists():
                print(f"  ⚠️ 缺少 SKILL.md，跳过")
                continue
            
            with open(skill_md, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 解析技能元数据
            parsed = parse_skill_folder({f"SKILL.md": content}, source_type="markdown")
            parsed.source_path = str(folder)
            parsed_skills.append((folder.name, parsed))
            print(f"  ✅ {parsed.skill_id} v{parsed.version}")
            
        except Exception as e:
            print(f"  ❌ 解析失败：{e}")
            continue
    
    print(f"\n📊 共解析 {len(parsed_skills)} 个技能")
    
    # 显示技能列表
    print("\n📋 待导入技能列表:")
    for name, parsed in parsed_skills:
        print(f"  - {parsed.skill_id} v{parsed.version}: {parsed.description[:60]}...")
    
    # 询问是否继续
    print("\n⚠️  下一步操作:")
    print("  1. 在数据库中创建这些技能记录")
    print("  2. 将技能文件复制到 data/ai/skills/<skill_id>/")
    print("  3. 更新 agent-scrna.yaml 的 skill_ids")
    
    choice = input("\n是否继续导入？(y/N): ").strip().lower()
    if choice != "y":
        print("❌ 已取消")
        return
    
    # TODO: 实际导入逻辑需要数据库连接
    print("\n💡 提示：实际导入需要配置数据库连接和调用 SkillImportService")
    print("   请运行：python scripts/import_scrna_skills.py --db-url <database_url>")


if __name__ == "__main__":
    asyncio.run(import_skills())
