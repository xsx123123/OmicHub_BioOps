#!/usr/bin/env python3
"""离线验证 Agent → Studio 运行时镜像选择契约。

这个脚本只读取仓库内的 YAML 和 Python 配置，不连接数据库、不启动 Docker、
不修改工作区。它用于在修改 Agent 配置、Studio 会话入口或运行时注册表后，
快速确认以下防回归契约：

* 所有 ``CygnusX.yaml`` 中启用的 Agent 都声明了可解析的 Studio 镜像；
* ``agent-viz`` 固定使用已构建的 ``analysis-plot`` 镜像；
* 单细胞画像使用当前的 ``scrna-v0.0.3dev``，不会回到旧版；
* 没有显式 Agent 画像时才返回 ``None``，不在公共解析函数中偷偷套用 core；
* browser-office 只在显式请求 browser/document 能力时被能力匹配选中。

用法：

    python scripts/test_studio_agent_runtime.py

退出码为 0 表示全部检查通过；非 0 表示发现配置漂移。脚本设计成可在 CI
或提交前运行，若需要修改这些契约，应先向用户说明影响范围并获得确认。
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cygnusx.infrastructure.config.agent_loader import load_agent_configs
from cygnusx.infrastructure.config.runtime_image_loader import (
    get_runtime_images,
    resolve_studio_image,
)
from cygnusx.infrastructure.config.studio_loader import StudioConfigManager


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> int:
    configs = load_agent_configs()
    if not configs:
        fail("没有加载到任何启用的 Agent")

    registry = get_runtime_images()
    images = StudioConfigManager().get_config()
    resolved: dict[str, tuple[str, str]] = {}

    for config in configs:
        agent_id = str(config.get("agent_id") or "")
        studio = config.get("studio")
        if not agent_id or not isinstance(studio, dict):
            fail(f"Agent {agent_id or '<unknown>'} 缺少 studio 配置")

        image = resolve_studio_image(studio)
        if not image:
            fail(f"Agent {agent_id} 没有可解析的 Studio 镜像")
        profile = registry.profile_for_image(image)
        if profile is None:
            fail(f"Agent {agent_id} 的镜像未注册: {image}")
        resolved[agent_id] = (str(studio.get("runtime_profile") or ""), image)

    viz_profile, viz_image = resolved.get("agent-viz", ("", ""))
    if viz_profile != "analysis-plot":
        fail(f"agent-viz profile 错误: {viz_profile!r}")
    if viz_image != "cygnusx-analysis:plot-v0.0.2dev":
        fail(f"agent-viz 镜像错误: {viz_image!r}")

    scrna_image = registry.resolved_profile("analysis-scrna").image
    if scrna_image != "cygnusx-analysis:scrna-v0.0.3dev":
        fail(f"analysis-scrna 不是当前版本: {scrna_image!r}")
    if any("scrna-v0.0.2dev" in image for _, image in resolved.values()):
        fail("发现已移除的 scrna-v0.0.2dev 引用")

    if resolve_studio_image({}) is not None:
        fail("无 Agent 画像时不应由公共解析函数静默返回 core")
    if images.image_for_capabilities(["code", "browser", "document"]) != (
        "cygnusx-sandbox-browser-office:v0.0.2dev"
    ):
        fail("显式 browser/document 能力未选择 browser-office")
    if images.image_for_capabilities(["code"]) != "cygnusx-analysis:core-v0.0.2dev":
        fail("仅 code 能力未选择 analysis-core")

    print(f"PASS: audited {len(resolved)} enabled agents")
    for agent_id in sorted(resolved):
        profile, image = resolved[agent_id]
        print(f"  {agent_id:24} {profile:16} {image}")
    print("PASS: visualization, scrna version, fallback, and capability-selection checks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, LookupError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
