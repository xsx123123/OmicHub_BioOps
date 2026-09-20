"""AST 静态安全检查器 — 对 AI 生成的 MCP Server 代码做上线前安全门禁.

检查维度:
1. 语法合法性（能否被 ``ast.parse``）
2. import 白名单（仅允许沙箱镜像预装 + 协议必需的包）
3. 危险调用（eval/exec/subprocess/pickle/__import__ 等，含 ``f = eval`` 别名调用；
   os/shutil/subprocess 等白名单或禁用模块的危险属性按接收者模块名拦截）
4. 危险字符串（访问 /etc, /proc, /sys, /root 等系统路径；拼接链先做常量折叠再查，
   防 ``"/et" + "c/passwd"`` 分段绕过）
5. 结构验证（MCP 协议 handler + 生成标记 ``__exp_mcp_generated__``，按行精确匹配）

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
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "spawnl",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "fork",
        "forkpty",
        "kill",
        "killpg",
        "dlopen",
        "unlink",  # os.unlink / Path.unlink —— 生成代码不应删除文件
        "rmdir",
        "rmtree",  # shutil.rmtree
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

#: 白名单模块（os/shutil 等本身可导入）的「模块限定」危险属性：仅当属性访问
#: 的接收者模块名命中时才违规——``remove``/``rename`` 等在 pandas/list 上常见，
#: 全局禁用会误伤，``os.remove``/``df.rename`` 必须靠接收者区分。
#: 调用与非调用形式（如 ``os.environ`` 下标读取、``fn = os.remove`` 别名）均拦。
MODULE_SCOPED_FORBIDDEN_ATTRIBUTES: dict[str, frozenset[str]] = {
    "os": frozenset(
        {
            "remove",
            "rename",
            "replace",  # os.replace（Path.replace 由 _receiver_name 天然放行）
            "removedirs",
            "environ",
            "environb",
        }
    ),
    "posix": frozenset(
        {
            "remove",
            "rename",
            "replace",
            "removedirs",
            "environ",
            "environb",
        }
    ),
    "nt": frozenset(
        {
            "remove",
            "rename",
            "replace",
            "removedirs",
            "environ",
            "environb",
            "startfile",
        }
    ),
    "shutil": frozenset({"move", "copytree"}),
    # subprocess 已整体禁止导入；此处兜底防御别名/注入后的直接调用形态，
    # 与既有「subprocess 一律违规」的策略保持一致，不新增放行行为。
    "subprocess": frozenset(
        {
            "run",
            "call",
            "check_call",
            "check_output",
            "getoutput",
            "getstatusoutput",
            "Popen",
        }
    ),
}

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
            # 嵌套拼接链（a + b + c）会经外层/内层 BinOp 各折叠一次，
            # 去重保持消息唯一（顺序不变）。
            violations=list(dict.fromkeys(violations)),
            warnings=list(dict.fromkeys(warnings)),
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
        # 别名追踪：`f = eval` 后 `f(...)` 与直接 `eval(...)` 同等禁止。
        aliases = self._collect_forbidden_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # 裸名调用: eval(...), exec(...), open(...)
                if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALL_NAMES:
                    violations.append(
                        f"行 {node.lineno}: 禁止调用 '{func.id}()'"
                    )
                # 别名调用: f = eval; f(...)
                elif isinstance(func, ast.Name) and func.id in aliases:
                    violations.append(
                        f"行 {node.lineno}: 禁止通过别名调用 '{func.id}()'"
                        f"（别名指向危险函数 '{aliases[func.id]}'）"
                    )
                # 属性调用: os.system(...) / pickle.loads(...) / os.remove(...)
                elif isinstance(func, ast.Attribute):
                    receiver = self._receiver_name(func.value)
                    scoped = MODULE_SCOPED_FORBIDDEN_ATTRIBUTES.get(receiver)
                    if func.attr in FORBIDDEN_ATTRIBUTES:
                        violations.append(
                            f"行 {node.lineno}: 禁止调用方法 '.{func.attr}()'"
                        )
                    elif (
                        func.attr in SERIALIZER_CALLS
                        and receiver in SERIALIZER_MODULES
                    ):
                        violations.append(
                            f"行 {node.lineno}: 禁止调用反序列化方法 "
                            f"'{receiver}.{func.attr}()'"
                        )
                    elif scoped is not None and func.attr in scoped:
                        violations.append(
                            f"行 {node.lineno}: 禁止调用危险模块属性 "
                            f"'{receiver}.{func.attr}()'"
                        )
            # 非调用形式的危险属性访问: x.__globals__ / os.environ / fn = os.remove
            elif isinstance(node, ast.Attribute):
                receiver = self._receiver_name(node.value)
                scoped = MODULE_SCOPED_FORBIDDEN_ATTRIBUTES.get(receiver)
                if node.attr in FORBIDDEN_ATTRIBUTES and node.attr.startswith("__"):
                    violations.append(
                        f"行 {node.lineno}: 禁止访问危险属性 '.{node.attr}'"
                    )
                elif scoped is not None and node.attr in scoped:
                    violations.append(
                        f"行 {node.lineno}: 禁止访问危险模块属性 "
                        f"'{receiver}.{node.attr}'"
                    )

    @staticmethod
    def _collect_forbidden_aliases(tree: ast.AST) -> dict[str, str]:
        """收集把危险内置名赋给变量的别名映射 ``{别名: 原名}``（简单一层）.

        覆盖形态：``f = eval`` / ``f = x = eval`` / ``f, g = eval, exec`` /
        ``(f := eval)`` / ``f: Callable = eval`` / ``for f in (eval, exec)``。
        仅当右值为 FORBIDDEN_CALL_NAMES 的裸 Name 时记别名，属性赋值等更深的
        间接形态交由审核与沙箱兜底。
        """
        aliases: dict[str, str] = {}

        def bind(target: ast.expr, value: ast.expr) -> None:
            if not isinstance(value, ast.Name) or value.id not in FORBIDDEN_CALL_NAMES:
                return
            if isinstance(target, ast.Name):
                aliases[target.id] = value.id
            elif isinstance(target, (ast.Tuple, ast.List)):
                for element in target.elts:
                    if isinstance(element, ast.Name):
                        aliases[element.id] = value.id

        def bind_pairwise(targets: list[ast.expr], value: ast.expr) -> None:
            # `f, x = eval, 1` —— 按位置配对元组元素
            if not isinstance(value, (ast.Tuple, ast.List)):
                return
            for target, element in zip(targets, value.elts):
                bind(target, element)

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    bind(target, node.value)
                    bind_pairwise(
                        target.elts if isinstance(target, (ast.Tuple, ast.List)) else [],
                        node.value,
                    )
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                bind(node.target, node.value)
            elif isinstance(node, ast.NamedExpr):
                bind(node.target, node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(
                node.target, ast.Name
            ):
                source = node.iter
                elements = (
                    source.elts
                    if isinstance(source, (ast.Tuple, ast.List, ast.Set))
                    else [source]
                )
                for element in elements:
                    if (
                        isinstance(element, ast.Name)
                        and element.id in FORBIDDEN_CALL_NAMES
                    ):
                        aliases[node.target.id] = element.id
                        break
        return aliases

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
            elif (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Add)
                and (segments := self._flatten_concat(node))
            ):
                # 字符串拼接常量折叠：把拼接链中相邻的字符串常量折叠后再查，
                # 防止 "/et" + "c/passwd" 这类分段绕过；折叠不了（含动态片段）
                # 时，参与拼接的每个常量片段命中敏感前缀同样报违规——单片段
                # 由下方 Constant 分支逐个检查，此处只补折叠产生的跨片段命中。
                for run_value in self._fold_concat_runs(segments):
                    if len(run_value) < 2:
                        continue  # 单个常量片段交给 Constant 分支，避免重复
                    self._check_path_value(
                        run_value, node.lineno, violations, warnings,
                        prefix="字符串拼接折叠后",
                    )
                continue
            if not value:
                continue
            self._check_path_value(value, node.lineno, violations, warnings)

    def _check_path_value(
        self,
        value: str,
        lineno: int,
        violations: list[str],
        warnings: list[str],
        *,
        prefix: str = "代码中",
    ) -> bool:
        """检查一个（可能由片段折叠而成的）字符串值，返回是否命中违规。"""
        hit = False
        for pattern in FORBIDDEN_PATH_PATTERNS:
            if pattern in value:
                violations.append(
                    f"行 {lineno}: {prefix}出现受保护路径 '{pattern}'"
                )
                hit = True
        # 内网 / 元数据地址提示（不硬拦，egress proxy 会拦，但提示审核）
        if re.search(r"\b169\.254\.169\.254\b", value) or re.search(
            r"\b10\.\d+\.\d+\.\d+\b", value
        ):
            warnings.append(
                f"行 {lineno}: 字符串包含内网/元数据 IP，请确认用途"
            )
        return hit

    @staticmethod
    def _flatten_concat(node: ast.BinOp) -> list[ast.expr]:
        """把 ``a + b + c`` 的 BinOp(Add) 链摊平为操作数序列（含动态片段）。"""
        if not isinstance(node.op, ast.Add):
            return []
        segments: list[ast.expr] = []
        for side in (node.left, node.right):
            if isinstance(side, ast.BinOp) and isinstance(side.op, ast.Add):
                segments.extend(StaticSafetyChecker._flatten_concat(side))
            else:
                segments.append(side)
        return segments

    @staticmethod
    def _fold_concat_runs(segments: list[ast.expr]) -> list[str]:
        """折叠拼接链中相邻的字符串常量段；动态片段（Name/Call/格式化值）断开."""
        runs: list[str] = []
        current: list[str] = []
        for segment in segments:
            if isinstance(segment, ast.Constant) and isinstance(segment.value, str):
                current.append(segment.value)
                continue
            if isinstance(segment, ast.JoinedStr):
                # f-string 静态部分作为一个可折叠片段参与拼接
                current.append(
                    "".join(
                        v.value
                        for v in segment.values
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)
                    )
                )
                continue
            if current:
                runs.append("".join(current))
                current = []
        if current:
            runs.append("".join(current))
        return runs

    def _check_marker_and_structure(
        self, code: str, violations: list[str], warnings: list[str]
    ) -> None:
        # 按行精确匹配（strip 后等值比较），防止把伪造注释/字符串里的子串
        # （如 ``# 参见 __exp_mcp_generated__ = True``）误认为合法生成标记。
        if self.require_marker and not any(
            line.strip() == f"{GENERATED_MARKER} = True" for line in code.splitlines()
        ):
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
