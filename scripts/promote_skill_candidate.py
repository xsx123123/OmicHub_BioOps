#!/usr/bin/env python3
"""Skill 候选包晋升脚本。

把 agent-skill-builder 在沙箱工作区生成的候选包复制到
`data/ai/skill_marketplace/`，完成文件级校验，但不自动修改任何 Agent YAML 或数据库。
晋升后需要管理员在目标 Agent 的 skill_ids 中声明并运行 sync_builtin_agents.py。

用法：
    uv run python scripts/promote_skill_candidate.py \
        --candidate /workspace/skill-candidates/my-skill \
        --admin-user-id '<UUID>'

    # 仅预览
    uv run python scripts/promote_skill_candidate.py \
        --candidate /workspace/skill-candidates/my-skill \
        --admin-user-id '<UUID>' --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from cygnusx.infrastructure.skills.skillmd import (
    SkillParseError,
    parse_skill_folder,
)

MAX_TOTAL_BYTES = 1024 * 1024  # OSDP 包总量红线


def _read_candidate_files(candidate_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in candidate_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(candidate_dir).as_posix()
        files[rel] = path.read_bytes()
    if "SKILL.md" not in files:
        raise SkillParseError("候选包缺少 SKILL.md")
    return files


def _copy_candidate(src: Path, dst: Path, replace: bool) -> None:
    if dst.exists():
        if not replace:
            raise FileExistsError(
                f"marketplace 已存在 {dst.name}；如需覆盖请使用 --replace"
            )
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> int:
    parser = argparse.ArgumentParser(description="晋升 Skill 候选包到 marketplace")
    parser.add_argument("--candidate", required=True, help="候选包目录路径（沙箱内绝对路径或本地路径）")
    parser.add_argument("--admin-user-id", required=True, help="执行晋升的管理员用户 UUID")
    parser.add_argument("--marketplace-root", default="data/ai/skill_marketplace", help="marketplace 根目录")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不复制")
    parser.add_argument("--replace", action="store_true", help="允许覆盖已存在的 marketplace skill")
    args = parser.parse_args()

    candidate_dir = Path(args.candidate).expanduser().resolve()
    if not candidate_dir.exists():
        print(f"错误：候选目录不存在: {candidate_dir}", file=sys.stderr)
        return 1

    # 1. 读取并校验 OSDP 结构
    try:
        files = _read_candidate_files(candidate_dir)
        parsed = parse_skill_folder(files)
    except SkillParseError as exc:
        print(f"解析失败：{exc}", file=sys.stderr)
        return 1

    skill_id = parsed.skill_id
    name = parsed.name or skill_id
    total_size = sum(len(content) for content in files.values())

    # 2. 包大小红线
    if total_size > MAX_TOTAL_BYTES:
        print(
            f"错误：候选包 {total_size} 字节，超过 OSDP 包总量 {MAX_TOTAL_BYTES} 字节红线",
            file=sys.stderr,
        )
        return 1

    # 3. 目标位置检查
    marketplace_root = Path(args.marketplace_root).resolve()
    target_dir = marketplace_root / skill_id
    if target_dir.exists() and not args.replace:
        print(
            f"错误：marketplace 已存在 {skill_id}；如需覆盖请加 --replace",
            file=sys.stderr,
        )
        return 1

    # 4. 预览输出
    print("=" * 60)
    print("Skill 候选包晋升预览")
    print("=" * 60)
    print(f"skill_id:    {skill_id}")
    print(f"name:        {name}")
    print(f"version:     {parsed.version or '未指定'}")
    print(f"category:    {parsed.category or '未指定'}")
    print(f"包大小:      {total_size} / {MAX_TOTAL_BYTES} 字节")
    print(f"文件数:      {len(files)}")
    print(f"来源:        {candidate_dir}")
    print(f"目标:        {target_dir}")
    print(f"管理员:      {args.admin_user_id}")
    print(f"覆盖模式:    {'是' if args.replace else '否'}")
    print(f"演练模式:    {'是' if args.dry_run else '否'}")

    manifest_path = candidate_dir / "CANDIDATE_MANIFEST.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            pending = manifest.get("pending_review_items") or []
            if pending:
                print("\n待评审项（CANDIDATE_MANIFEST.json）：")
                for item in pending:
                    print(f"  - {item}")
        except json.JSONDecodeError:
            print("\n警告：CANDIDATE_MANIFEST.json 不是有效 JSON", file=sys.stderr)

    if args.dry_run:
        print("\n[DRY-RUN] 未执行复制。通过校验，可正式晋升。")
        return 0

    # 5. 复制到 marketplace
    try:
        _copy_candidate(candidate_dir, target_dir, args.replace)
    except Exception as exc:  # noqa: BLE001
        print(f"复制失败：{exc}", file=sys.stderr)
        return 1

    print(f"\n已晋升到 {target_dir}")
    print("后续步骤：")
    print(f"  1. 在目标 Agent YAML 的 skill_ids 中加入 '{skill_id}'")
    print("  2. 运行 uv run python scripts/sync_builtin_agents.py")
    print("  3. 验证前台 Skill 已挂载并可被 use_skill 触发")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
