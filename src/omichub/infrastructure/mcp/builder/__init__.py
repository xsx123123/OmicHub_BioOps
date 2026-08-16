"""MCP Builder — AI 自生成 MCP Server 框架.

模块组成:
- safety: AST 静态安全检查器（import 白名单 + 危险调用检测 + 结构验证）
- versioning: SemVer 版本号判定与版本链工具
- generator: LLM 代码生成器（ProviderManager 封装）
- doc_generator: 构建文档 / 架构文档生成
- （沙箱部署与注册编排位于 application/services/mcp_builder_service.py）

注意：generator 和 doc_generator 有较重的依赖（litellm 等），使用 lazy import
避免在仅需 safety/versioning 时加载全部依赖。
"""

from .safety import SafetyReport, StaticSafetyChecker
from .versioning import determine_version, is_valid_semver

# Lazy imports for modules with heavy dependencies
def __getattr__(name: str):
    """Lazy import for generator and doc_generator modules."""
    if name in ("GenerationResult", "MCPCodeGenerator", "extract_python_code"):
        from .generator import GenerationResult, MCPCodeGenerator, extract_python_code
        return locals()[name]
    elif name in ("generate_build_doc", "generate_architecture_doc"):
        from .doc_generator import generate_architecture_doc, generate_build_doc
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "SafetyReport",
    "StaticSafetyChecker",
    "determine_version",
    "is_valid_semver",
    "GenerationResult",
    "MCPCodeGenerator",
    "extract_python_code",
    "generate_build_doc",
    "generate_architecture_doc",
]
