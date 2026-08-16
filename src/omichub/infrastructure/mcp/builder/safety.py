"""AST 静态安全检查器 — 对 AI 生成的 MCP Server 代码做上线前安全门禁.

检查维度:
1. 语法合法性（能否被 ``ast.parse``）
2. import 白名单（仅允许沙箱镜像预装 + 协议必需的包）
3. 危险调用（eval/exec/subprocess/pickle/__import__ 等）
4. 危险字符串（访问 /etc, /proc, /sys, /root 等系统路径）
5. 结构验证（MCP 协议 handler + 生成标记 ``__exp_mcp_generated__``）

设计原则:
- 违规 (violation) → 硬性失败，代码不得部署
- 警告 (warning) → 记录但不阻断（如 requests 库的网络访问，受 egress proxy 白名单约束）
- 检查器是纯函数式的，不执行任何被测代码
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 策略表
# ---------------------------------------------------------------------------

#: 绝对禁止导入的模块（顶层包名）。出现即 violation。
FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "subprocess",
        "ctypes",
        "cffi",
        "pickle",
        "marshal",
        "shelve",
        "importlib",
        "socket",
        "shutil",
        "signal",
        "multiprocessing",
        "threading",
        "sys",  # sys.modules 操控 / 退出
        "code",
        "codeop",
        "pty",
        "fcntl",
        "termios",
        "resource",
        "grp",
        "pwd",
        "builtins",
        "__builtin__",
        "webbrowser",
        "antigravity",
    }
)

#: 白名单顶层包。不在白名单也不在禁止列表的 → warning（保守放行，人工审核兜底）。
ALLOWED_PACKAGES: frozenset[str] = frozenset(
    {
        # MCP 协议
        "mcp",
        "fastmcp",
        # 数据 / 校验
        "pydantic",
        # 标准库（安全子集）
        "json",
        "re",
        "datetime",
        "typing",
        "typing_extensions",
        "collections",
        "itertools",
        "functools",
        "math",
        "statistics",
        "hashlib",
        "base64",
        "uuid",
        "string",
        "pathlib",
        "urllib",  # 仅 parse 子模块常用；网络访问受 egress 约束
        "html",
        "xml",
        "csv",
        "io",
        "os",  # 仅允许白名单属性（见 FORBIDDEN_ATTRIBUTES），禁止 system/exec*
        "asyncio",
        "logging",
        "argparse",
        "enum",
        "dataclasses",
        "abc",
        "copy",
        "random",
        "time",
        "textwrap",
        "traceback",
        "contextlib",
        "warnings",
        # 三方 HTTP（网络受 egress proxy 域名白名单约束）
        "httpx",
        "requests",
        "aiohttp",
        # 科学计算（沙箱镜像预装）
        "numpy",
        "pandas",
    }
)

#: 禁止的「裸函数调用」名。
FORBIDDEN_CALL_NAMES: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "input",
        "memoryview",
        "open",  # 生成代码不应直接读写任意文件；需要文件操作走 workspace 工具
        "getattr",  # 可绕过属性检查动态取 os.system
        "setattr",
        "delattr",
    }
)

#: 禁止的属性访问 / 方法调用（``值.属性`` 形式的属性名，任何接收者均禁止）。
FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "system",  # os.system
        "popen",
        "exec",
        "execl",
        "execle",
        "execlp",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "spawnl",
        "spawnv",
        "fork",
        "forkpty",
        "kill",
        "killpg",
        "dlopen",
        "__import__",
        "__subclasses__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__class__",
        "__bases__",
        "__mro__",
        "__dict__",
        "__getattr__",
        "__getattribute__",
    }
)

#: 序列化方法名 — 仅当接收者为危险序列化模块时禁止（避免误伤 json.dumps）。
SERIALIZER_CALLS: frozenset[str] = frozenset({"loads", "load", "dumps", "dump"})

#: 危险序列化模块（pickle.loads 可执行任意代码）。
SERIALIZER_MODULES: frozenset[str] = frozenset(
    {"pickle", "cpickle", "_pickle", "marshal", "shelve"}
)

#: 出现在字符串字面量中即 violation 的危险路径 / 模式。
FORBIDDEN_PATH_PATTERNS: tuple[str, ...] = (
    "/etc/",
    "/proc/",
    "/sys/",
    "/root/",
    "/var/run/docker.sock",
    "/dev/",
)

#: 生成代码必须携带的来源标记（Prompt 规范 Phase 3 要求）。
GENERATED_MARKER = "__exp_mcp_generated__"

#: 结构验证：代码中必须出现下列任一组标记，证明实现了 MCP 协议 handler。
STRUCTURAL_MARKERS: tuple[tuple[str, ...], ...] = (
    # 低层 mcp.server.Server 风格
    ("list_tools", "call_tool"),
    # FastMCP 风格
    ("@mcp.tool", "FastMCP"),
    ("@app.tool", "FastMCP"),
    ("@server.tool", "FastMCP"),
)


# ---------------------------------------------------------------------------
# 报告模型
# ---------------------------------------------------------------------------


@dataclass
class SafetyReport:
    """AST 检查结果.

    ``passed`` 为 True 当且仅当 ``violations`` 为空。
    ``dependencies`` 为代码实际 import 的顶层包列表（用于沙箱镜像核对）。
    """

    passed: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "warnings": self.warnings,
            "dependencies": self.dependencies,
        }


# ---------------------------------------------------------------------------
# 检查器
# ---------------------------------------------------------------------------


class StaticSafetyChecker:
    """基于 Python AST 的生成代码安全分析器（纯静态，不执行代码）."""

    def __init__(
        self,
        *,
        allowed_packages: frozenset[str] | None = None,
        require_marker: bool = True,
        require_structure: bool = True,
        max_code_bytes: int = 512 * 1024,
    ) -> None:
        self.allowed_packages = allowed_packages or ALLOWED_PACKAGES
        self.require_marker = require_marker
        self.require_structure = require_structure
        self.max_code_bytes = max_code_bytes

    # -- public API ---------------------------------------------------------

    def analyze(self, code: str) -> SafetyReport:
        """分析代码字符串，返回 :class:`SafetyReport`."""
        violations: list[str] = []
        warnings: list[str] = []
        dependencies: set[str] = set()

        if not code or not code.strip():
            return SafetyReport(
                passed=False, violations=["代码为空"], warnings=[], dependencies=[]
            )

        if len(code.encode("utf-8")) > self.max_code_bytes:
            return SafetyReport(
                passed=False,
                violations=[
                    f"代码超过大小上限 {self.max_code_bytes} bytes"
                ],
                warnings=[],
                dependencies=[],
            )

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return SafetyReport(
                passed=False,
                violations=[f"语法错误: {exc.msg} (行 {exc.lineno})"],
                warnings=[],
                dependencies=[],
            )

        self._check_imports(tree, violations, warnings, dependencies)
        self._check_calls(tree, violations)
        self._check_string_literals(tree, violations, warnings)
        self._check_marker_and_structure(code, violations, warnings)

        return SafetyReport(
            passed=not violations,
            violations=violations,
            warnings=warnings,
            dependencies=sorted(dependencies),
        )

    # -- 各维度检查 ----------------------------------------------------------

    def _check_imports(
        self,
        tree: ast.AST,
        violations: list[str],
        warnings: list[str],
        dependencies: set[str],
    ) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    dependencies.add(top)
                    self._classify_import(top, node.lineno, violations, warnings)
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # 相对导入：生成代码应为单文件，不允许
                    violations.append(
                        f"行 {node.lineno}: 禁止相对导入 (level={node.level})"
                    )
                    continue
                top = (node.module or "").split(".")[0]
                if top:
                    dependencies.add(top)
                    self._classify_import(top, node.lineno, violations, warnings)

    def _classify_import(
        self,
        top: str,
        lineno: int,
        violations: list[str],
        warnings: list[str],
    ) -> None:
        if top in FORBIDDEN_IMPORTS:
            violations.append(f"行 {lineno}: 禁止导入模块 '{top}'")
        elif top not in self.allowed_packages:
            warnings.append(
                f"行 {lineno}: 导入 '{top}' 不在白名单中，需人工审核确认沙箱镜像已预装"
            )

    def _check_calls(self, tree: ast.AST, violations: list[str]) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # 裸名调用: eval(...), exec(...), open(...)
                if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALL_NAMES:
                    violations.append(
                        f"行 {node.lineno}: 禁止调用 '{func.id}()'"
                    )
                # 属性调用: os.system(...) / pickle.loads(...)
                elif isinstance(func, ast.Attribute):
                    if func.attr in FORBIDDEN_ATTRIBUTES:
                        violations.append(
                            f"行 {node.lineno}: 禁止调用方法 '.{func.attr}()'"
                        )
                    elif (
                        func.attr in SERIALIZER_CALLS
                        and self._receiver_name(func.value) in SERIALIZER_MODULES
                    ):
                        receiver = self._receiver_name(func.value)
                        violations.append(
                            f"行 {node.lineno}: 禁止调用反序列化方法 "
                            f"'{receiver}.{func.attr}()'"
                        )
            # 非调用形式的危险属性访问: x.__globals__ 等
            elif isinstance(node, ast.Attribute):
                if node.attr in FORBIDDEN_ATTRIBUTES and node.attr.startswith("__"):
                    violations.append(
                        f"行 {node.lineno}: 禁止访问危险属性 '.{node.attr}'"
                    )

    @staticmethod
    def _receiver_name(node: ast.expr) -> str:
        """解析属性调用接收者名称: ``pickle.loads`` → ``pickle``."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            # module.sub.attr 形式取最内层属性名（如 _compat.pickle.loads）
            return node.attr
        return ""

    def _check_string_literals(
        self, tree: ast.AST, violations: list[str], warnings: list[str]
    ) -> None:
        for node in ast.walk(tree):
            value: str | None = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
            elif isinstance(node, ast.JoinedStr):  # f-string 的静态部分
                parts = [
                    v.value
                    for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                ]
                value = "".join(parts)
            if not value:
                continue
            for pattern in FORBIDDEN_PATH_PATTERNS:
                if pattern in value:
                    violations.append(
                        f"行 {node.lineno}: 代码中出现受保护路径 '{pattern}'"
                    )
            # 内网 / 元数据地址提示（不硬拦，egress proxy 会拦，但提示审核）
            if re.search(r"\b169\.254\.169\.254\b", value) or re.search(
                r"\b10\.\d+\.\d+\.\d+\b", value
            ):
                warnings.append(
                    f"行 {node.lineno}: 字符串包含内网/元数据 IP，请确认用途"
                )

    def _check_marker_and_structure(
        self, code: str, violations: list[str], warnings: list[str]
    ) -> None:
        if self.require_marker and GENERATED_MARKER not in code:
            violations.append(
                f"缺少生成标记 '{GENERATED_MARKER} = True'（无法识别为 Builder 产物）"
            )

        if self.require_structure:
            matched = any(
                all(marker in code for marker in group) for group in STRUCTURAL_MARKERS
            )
            if not matched:
                violations.append(
                    "未检测到 MCP 协议 handler（需要 list_tools/call_tool "
                    "或 FastMCP @tool 注册）"
                )
