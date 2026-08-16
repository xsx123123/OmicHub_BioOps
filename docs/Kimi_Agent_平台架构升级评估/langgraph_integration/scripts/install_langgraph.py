#!/usr/bin/env python3
"""
LangGraph 一键安装脚本
======================
自动完成 LangGraph 与 OmicHub 的集成安装。

步骤:
    1. 检查 Python 环境和依赖
    2. 安装 Python 包 (langgraph, langchain-core, etc.)
    3. 复制后端代码到正确位置
    4. 执行 Alembic 迁移
    5. 更新 registry.py 注册 LangGraphExecutor
    6. 更新 main.py 生命周期
    7. 复制前端代码
    8. 验证安装

用法:
    cd /path/to/omichub
    python scripts/install_langgraph.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


# ── 配置 ──

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
INTEGRATION_DIR = Path(__file__).parent.parent.resolve()

REQUIRED_PACKAGES = [
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",
    "langgraph-checkpoint>=1.0.0",
]

BACKEND_FILES = {
    "domain/execution/agent_state.py": "src/omichub/domain/execution/",
    "domain/execution/hitl_models.py": "src/omichub/domain/execution/",
    "infrastructure/execution/langgraph_nodes.py": "src/omichub/infrastructure/execution/",
    "infrastructure/execution/langgraph_executor.py": "src/omichub/infrastructure/execution/",
    "infrastructure/execution/langgraph_runtime.py": "src/omichub/infrastructure/execution/",
    "infrastructure/checkpoint/postgres_checkpoint.py": "src/omichub/infrastructure/checkpoint/",
    "application/services/hitl_service.py": "src/omichub/application/services/",
    "application/services/stream_adapter.py": "src/omichub/application/services/",
    "api/v1/agent.py": "src/omichub/api/v1/",
}

FRONTEND_FILES = {
    "composables/useLangGraphStream.ts": "src/composables/",
    "components/HITLDialog.vue": "src/components/",
}

MIGRATION_FILE = "backend/alembic/versions/add_langgraph_checkpoint.py"


# ── 步骤 1: 检查环境 ──

def check_environment() -> bool:
    """检查 Python 环境和项目结构"""
    print("🔍 检查环境...")

    # 检查 Python 版本
    if sys.version_info < (3, 10):
        print("❌ Python 版本需 >= 3.10")
        return False

    # 检查项目结构
    required_dirs = [
        PROJECT_ROOT / "src" / "omichub",
        PROJECT_ROOT / "frontend" / "src",
        PROJECT_ROOT / "alembic",
    ]
    for d in required_dirs:
        if not d.exists():
            print(f"❌ 未找到目录: {d}")
            print("   请在 OmicHub 项目根目录运行此脚本")
            return False

    # 检查关键文件
    required_files = [
        PROJECT_ROOT / "src" / "omichub" / "infrastructure" / "execution" / "base.py",
        PROJECT_ROOT / "src" / "omichub" / "infrastructure" / "execution" / "registry.py",
        PROJECT_ROOT / "src" / "omichub" / "main.py",
    ]
    for f in required_files:
        if not f.exists():
            print(f"❌ 未找到关键文件: {f}")
            return False

    print("✅ 环境检查通过")
    return True


# ── 步骤 2: 安装依赖 ──

def install_dependencies() -> bool:
    """安装 Python 依赖"""
    print("📦 安装依赖...")

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "-q"] + REQUIRED_PACKAGES,
            check=True,
            capture_output=True,
        )
        print("✅ 依赖安装完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 依赖安装失败: {e}")
        return False


# ── 步骤 3: 复制后端文件 ──

def copy_backend_files() -> bool:
    """复制后端代码到项目目录"""
    print("📁 复制后端代码...")

    src_base = INTEGRATION_DIR / "backend" / "src" / "omichub"
    dst_base = PROJECT_ROOT / "src" / "omichub"

    for src_rel, dst_rel in BACKEND_FILES.items():
        src = src_base / src_rel
        dst = dst_base / dst_rel / Path(src_rel).name

        if not src.exists():
            print(f"⚠️ 源文件不存在: {src}")
            continue

        # 确保目标目录存在
        dst.parent.mkdir(parents=True, exist_ok=True)

        # 备份原文件
        if dst.exists():
            backup = dst.with_suffix(dst.suffix + ".backup")
            shutil.copy2(dst, backup)
            print(f"   💾 已备份: {dst.name}")

        shutil.copy2(src, dst)
        print(f"   ✅ {dst.name}")

    print("✅ 后端代码复制完成")
    return True


# ── 步骤 4: 执行 Alembic 迁移 ──

def run_migration() -> bool:
    """执行数据库迁移"""
    print("🗄️ 执行数据库迁移...")

    migration_src = INTEGRATION_DIR / MIGRATION_FILE
    migration_dst = PROJECT_ROOT / "alembic" / "versions" / "lg1_langgraph_20260706.py"

    if migration_src.exists():
        shutil.copy2(migration_src, migration_dst)
        print(f"   ✅ 迁移文件已复制")

    try:
        subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        )
        print("✅ 数据库迁移完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 迁移失败: {e}")
        print(f"   请手动运行: alembic upgrade head")
        return False


# ── 步骤 5: 更新 registry.py ──

def update_registry() -> bool:
    """在执行器注册表中添加 LangGraphExecutor"""
    print("🔧 更新 registry.py...")

    registry_file = PROJECT_ROOT / "src" / "omichub" / "infrastructure" / "execution" / "registry.py"

    with open(registry_file) as f:
        content = f.read()

    # 检查是否已注册
    if "langgraph" in content:
        print("   ℹ️ LangGraphExecutor 已注册，跳过")
        return True

    # 在 _EXECUTORS 字典中添加 langgraph
    if "_EXECUTORS = {" in content:
        content = content.replace(
            "_EXECUTORS = {",
            "_EXECUTORS = {\n    \"langgraph\": None,  # 由 LangGraphRuntimeService 注入",
        )
    elif "_EXECUTORS=" in content:
        content = content.replace(
            "_EXECUTORS=",
            "_EXECUTORS={\"langgraph\": None},  # 占位，由运行时注入\n",
        )
    else:
        print("⚠️ 无法自动修改 registry.py，请手动添加:")
        print('    "langgraph": None,  # 由 LangGraphRuntimeService 注入')
        return False

    # 添加导入
    if "from omichub.infrastructure.execution.langgraph_executor import register_langgraph_executor" not in content:
        content = (
            "# LangGraph 注册\n"
            "from omichub.infrastructure.execution.langgraph_executor import register_langgraph_executor\n\n"
            + content
        )

    with open(registry_file, "w") as f:
        f.write(content)

    print("✅ registry.py 已更新")
    return True


# ── 步骤 6: 更新 main.py ──

def update_main_py() -> bool:
    """更新 main.py 生命周期，初始化 LangGraph 服务"""
    print("🔧 更新 main.py...")

    main_file = PROJECT_ROOT / "src" / "omichub" / "main.py"

    with open(main_file) as f:
        content = f.read()

    # 检查是否已更新
    if "LangGraphRuntimeService" in content:
        print("   ℹ️ main.py 已包含 LangGraph 初始化，跳过")
        return True

    # 添加导入
    import_block = """
# LangGraph 集成
from omichub.infrastructure.execution.langgraph_runtime import LangGraphRuntimeService
from omichub.infrastructure.execution.langgraph_nodes import NodeDeps
from omichub.infrastructure.execution.langgraph_executor import register_langgraph_executor, LangGraphExecutor
from omichub.infrastructure.checkpoint.postgres_checkpoint import OmicHubCheckpointSaver
from omichub.application.services.hitl_service import HITLService
from omichub.api.v1.agent import set_langgraph_services
"""

    if "from contextlib import asynccontextmanager" in content:
        content = content.replace(
            "from contextlib import asynccontextmanager",
            f"from contextlib import asynccontextmanager{import_block}",
        )
    else:
        content = import_block + "\n" + content

    # 在 lifespan 中添加初始化
    init_code = """
    # ── LangGraph 初始化 ──
    try:
        node_deps = NodeDeps(
            agent_service=app.state.agent_service,
            provider_manager=app.state.provider_manager,
            mcp_client=app.state.mcp_client,
            task_service=app.state.task_service,
            chat_service=app.state.chat_service,
        )
        checkpoint_saver = OmicHubCheckpointSaver()
        langgraph_runtime = LangGraphRuntimeService(
            node_deps=node_deps,
            checkpoint_saver=checkpoint_saver,
        )
        await langgraph_runtime.initialize()

        hitl_service = HITLService(langgraph_runtime)

        # 注册到执行器注册表
        from omichub.infrastructure.execution.registry import _EXECUTORS
        _EXECUTORS["langgraph"] = LangGraphExecutor(langgraph_runtime)

        # 注入到 API 路由
        set_langgraph_services(langgraph_runtime, hitl_service)

        app.state.langgraph_runtime = langgraph_runtime
        app.state.hitl_service = hitl_service

        logger.info("✅ LangGraph 运行时初始化完成")
    except Exception as e:
        logger.warning(f"⚠️ LangGraph 初始化失败: {e}，AI 助手将使用原有模式")
"""

    # 在 lifespan 的 yield 前插入
    if "yield" in content:
        content = content.replace(
            "    yield",
            f"{init_code}\n    yield",
        )

    # 在 shutdown 中添加清理
    shutdown_code = """
    # ── LangGraph 关闭 ──
    if hasattr(app.state, 'langgraph_runtime'):
        await app.state.langgraph_runtime.shutdown()
"""

    if "finally:" in content or "# 关闭" in content:
        content = content.replace(
            "finally:",
            f"{shutdown_code}\n    finally:",
        )

    with open(main_file, "w") as f:
        f.write(content)

    print("✅ main.py 已更新")
    return True


# ── 步骤 7: 复制前端文件 ──

def copy_frontend_files() -> bool:
    """复制前端代码"""
    print("📁 复制前端代码...")

    src_base = INTEGRATION_DIR / "frontend" / "src"
    dst_base = PROJECT_ROOT / "frontend" / "src"

    for src_rel, dst_rel in FRONTEND_FILES.items():
        src = src_base / src_rel
        dst = dst_base / dst_rel / Path(src_rel).name

        if not src.exists():
            print(f"⚠️ 源文件不存在: {src}")
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            backup = dst.with_suffix(dst.suffix + ".backup")
            shutil.copy2(dst, backup)

        shutil.copy2(src, dst)
        print(f"   ✅ {dst.name}")

    print("✅ 前端代码复制完成")
    return True


# ── 步骤 8: 验证 ──

def verify_installation() -> bool:
    """验证安装是否成功"""
    print("🔍 验证安装...")

    checks = []

    # 检查 Python 包
    try:
        import langgraph
        checks.append(("langgraph", True, langgraph.__version__))
    except ImportError:
        checks.append(("langgraph", False, ""))

    try:
        import langchain_core
        checks.append(("langchain_core", True, langchain_core.__version__))
    except ImportError:
        checks.append(("langchain_core", False, ""))

    # 检查文件
    for src_rel in BACKEND_FILES:
        dst = PROJECT_ROOT / "src" / "omichub" / BACKEND_FILES[src_rel] / Path(src_rel).name
        checks.append((dst.name, dst.exists(), ""))

    # 打印结果
    all_pass = True
    for name, ok, detail in checks:
        status = "✅" if ok else "❌"
        extra = f" ({detail})" if detail else ""
        print(f"   {status} {name}{extra}")
        if not ok:
            all_pass = False

    if all_pass:
        print("\n🎉 LangGraph 集成安装完成！")
        print("\n下一步:")
        print("   1. 重启 OmicHub 服务")
        print("   2. 在 flows/*.yaml 中设置 engine: langgraph 启用")
        print("   3. 前端 AgentWorkspace 中引入 useLangGraphStream 和 HITLDialog")
    else:
        print("\n⚠️ 部分检查未通过，请查看上方日志")

    return all_pass


# ── 主函数 ──

def main():
    print("=" * 60)
    print("LangGraph + OmicHub 集成安装")
    print("=" * 60)
    print(f"项目路径: {PROJECT_ROOT}")
    print()

    steps = [
        ("环境检查", check_environment),
        ("安装依赖", install_dependencies),
        ("复制后端代码", copy_backend_files),
        ("数据库迁移", run_migration),
        ("更新 registry.py", update_registry),
        ("更新 main.py", update_main_py),
        ("复制前端代码", copy_frontend_files),
        ("验证安装", verify_installation),
    ]

    for name, step_func in steps:
        print(f"\n{'─' * 50}")
        print(f"步骤: {name}")
        print("─" * 50)

        try:
            success = step_func()
            if not success:
                print(f"\n⚠️ 步骤 '{name}' 未完成，是否继续? (y/n): ", end="")
                choice = input().strip().lower()
                if choice != "y":
                    print("安装已中止")
                    return
        except Exception as e:
            print(f"❌ 步骤 '{name}' 异常: {e}")
            import traceback
            traceback.print_exc()
            return

    print("\n" + "=" * 60)
    print("安装流程全部完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
