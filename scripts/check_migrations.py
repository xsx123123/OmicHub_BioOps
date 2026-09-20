#!/usr/bin/env python3
"""检查 Alembic 迁移链的健康状况。

运行方式：
    python scripts/check_migrations.py

检查项：
1. 所有迁移文件都能解析 revision / down_revision / depends_on。
2. 所有 down_revision / depends_on 指向的 revision 都存在。
3. 迁移链只有一个 root、拓扑连通。
4. （可选）通过 alembic 命令验证 heads 唯一。
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def parse_revision(p: Path) -> dict | None:
    """解析单个迁移文件中的关键变量。"""
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError as e:
        print(f"❌ {p.name}: Python 语法错误 - {e}")
        return None

    info: dict = {"file": p.name}
    for node in ast.walk(tree):
        # 同时兼容注解写法（revision: str = "..."）与裸赋值（revision = "..."），
        # alembic 两种模板都合法，漏掉裸赋值会产生假的"依赖不存在/孤岛"级联报错。
        targets: list[str] = []
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        if value is None:
            continue
        for name in targets:
            if name not in ("revision", "down_revision", "depends_on"):
                continue
            if isinstance(value, ast.Constant):
                info[name] = value.value
            elif isinstance(value, ast.Tuple):
                info[name] = tuple(ast.literal_eval(elt) for elt in value.elts)
    return info if "revision" in info else None


def check_migrations(versions_dir: Path) -> bool:
    """检查迁移链完整性，返回是否通过。"""
    files = sorted(p for p in versions_dir.glob("*.py") if p.stem != "__init__")
    if not files:
        print("⚠️  未找到任何迁移文件。")
        return True

    revs: dict[str, dict] = {}
    parse_errors = []
    for p in files:
        info = parse_revision(p)
        if info is None:
            parse_errors.append(f"{p.name}: 无法解析 revision")
            continue
        revs[info["revision"]] = info

    if parse_errors:
        print("❌ 以下迁移文件解析失败：")
        for e in parse_errors:
            print(f"   - {e}")

    ok = not parse_errors

    # 检查依赖是否存在
    dep_errors = []
    for rev, info in revs.items():
        downs = info.get("down_revision")
        downs = downs if isinstance(downs, tuple) else (downs,) if downs else ()
        for d in downs:
            if d not in revs:
                dep_errors.append(
                    f"{info['file']} (revision={rev}) down_revision={d} 不存在"
                )

        deps = info.get("depends_on")
        deps = deps if isinstance(deps, tuple) else (deps,) if deps else ()
        for d in deps:
            if d not in revs:
                dep_errors.append(
                    f"{info['file']} (revision={rev}) depends_on={d} 不存在"
                )

    if dep_errors:
        print("❌ 发现迁移依赖错误：")
        for e in dep_errors:
            print(f"   - {e}")
        ok = False
    else:
        print("✅ 迁移文件内部依赖检查通过。")

    # 拓扑检查
    roots = [r for r, info in revs.items() if not info.get("down_revision")]
    if len(roots) != 1:
        print(f"❌ 期望只有一个 root，实际发现 {len(roots)} 个: {roots}")
        ok = False

    children: dict[str, list[str]] = defaultdict(list)
    for rev, info in revs.items():
        downs = info.get("down_revision")
        downs = downs if isinstance(downs, tuple) else (downs,) if downs else ()
        for d in downs:
            children[d].append(rev)

    visited: set[str] = set()

    def walk(r: str) -> None:
        if r in visited:
            return
        visited.add(r)
        for c in children[r]:
            walk(c)

    for root in roots:
        walk(root)

    missing = set(revs) - visited
    if missing:
        print("❌ 以下迁移无法从 root 到达（可能形成孤岛）：")
        for m in sorted(missing):
            print(f"   - {revs[m]['file']} (revision={m})")
        ok = False
    else:
        print("✅ 迁移链拓扑连通。")

    # 可选：调用 alembic heads 验证唯一 head
    try:
        result = subprocess.run(
            ["alembic", "heads"],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path(__file__).resolve().parents[1],
        )
        head_count = result.stdout.count("(head)")
        if head_count > 1:
            print(f"❌ Alembic 存在多个 head ({head_count})：\n{result.stdout}")
            ok = False
        elif head_count == 1:
            print("✅ Alembic head 唯一。")
        else:
            print("⚠️  未能通过 alembic heads 检测到 head 数量（可能环境未就绪）。")
    except FileNotFoundError:
        print("⚠️  未找到 alembic 命令，跳过 head 数量检查。")

    return ok


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    versions_dir = project_root / "alembic" / "versions"
    if not check_migrations(versions_dir):
        sys.exit(1)
    print("\n🎉 迁移链健康检查全部通过。")
