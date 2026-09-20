# MCP Builder 测试套件

本目录包含 MCP Builder Agent 的完整测试套件，覆盖 AST 安全检查器、版本管理工具和 Agent 配置加载验证。

## 测试概览

| 测试文件 | 覆盖模块 | 用例数 | 说明 |
|----------|----------|--------|------|
| `test_builder_safety.py` | StaticSafetyChecker | 29 | AST 安全检查器单元测试 |
| `test_builder_versioning.py` | versioning | 20 | SemVer 版本管理工具测试 |
| `test_builder_docs_and_generator.py` | docs/generator | 3 | 文档生成和代码生成器测试 |

**总计：52 个测试用例**

> 注：Agent loader 冒烟测试（7 cases）位于 `tests/unit/test_agent_loader_studio.py::test_mcp_builder_agent_loads_successfully`

## 快速开始

### 运行所有 MCP Builder 测试

```bash
cd /home/zj/zj_code_libarary/CygnusX
PYTHONPATH=src python -m pytest tests/unit/mcp/ -v --noconftest
```

### 运行单个测试文件

```bash
# AST 安全检查器测试
PYTHONPATH=src python -m pytest tests/unit/mcp/test_builder_safety.py -v --noconftest

# 版本管理工具测试
PYTHONPATH=src python -m pytest tests/unit/mcp/test_builder_versioning.py -v --noconftest

# 文档和生成器测试
PYTHONPATH=src python -m pytest tests/unit/mcp/test_builder_docs_and_generator.py -v --noconftest
```

### 运行特定测试用例

```bash
# 运行单个测试
PYTHONPATH=src python -m pytest tests/unit/mcp/test_builder_safety.py::test_clean_code_passes -v --noconftest

# 运行参数化测试的特定参数
PYTHONPATH=src python -m pytest "tests/unit/mcp/test_builder_safety.py::test_forbidden_imports[import subprocess]" -v --noconftest
```

## 测试详情

### 1. test_builder_safety.py（29 cases）

测试 `cygnusx.infrastructure.mcp.builder.safety.StaticSafetyChecker` 的 AST 安全检查逻辑。

#### 测试覆盖

**基础验证（3 cases）**
- `test_clean_code_passes` - 干净的 MCP Server 代码应通过检查
- `test_empty_code_fails` - 空代码应失败
- `test_syntax_error_fails` - 语法错误应失败

**禁止导入检测（7 cases）**
- `test_forbidden_imports[import subprocess]` - 禁止 subprocess
- `test_forbidden_imports[import ctypes]` - 禁止 ctypes
- `test_forbidden_imports[import pickle]` - 禁止 pickle
- `test_forbidden_imports[import socket]` - 禁止 socket
- `test_forbidden_imports[import shutil]` - 禁止 shutil
- `test_from_import_forbidden` - 禁止 from ... import 形式
- `test_relative_import_forbidden` - 禁止相对导入

**禁止调用检测（8 cases）**
- `test_forbidden_calls[eval('1+1')]` - 禁止 eval
- `test_forbidden_calls[exec('x=1')]` - 禁止 exec
- `test_forbidden_calls[compile('x', '', 'exec')]` - 禁止 compile
- `test_forbidden_calls[__import__('os')]` - 禁止 __import__
- `test_os_system_attribute_call` - 禁止 os.system()
- `test_pickle_loads_call` - 禁止 pickle.loads()
- `test_open_call_forbidden` - 禁止 open()
- `test_dunder_attribute_access` - 禁止危险属性访问（__bases__等）

**禁止路径检测（4 cases）**
- `test_protected_paths_in_strings[/etc/passwd]`
- `test_protected_paths_in_strings[/proc/self/environ]`
- `test_protected_paths_in_strings[/sys/kernel]`
- `test_protected_paths_in_strings[/root/.ssh]`

**警告和边界情况（4 cases）**
- `test_internal_ip_warns_but_not_blocks` - 内网 IP 产生警告但不失败
- `test_non_whitelist_import_warns` - 非白名单导入产生警告但不失败
- `test_report_to_dict` - SafetyReport.to_dict() 方法
- `test_code_size_limit` - 代码大小限制

**结构验证（3 cases）**
- `test_missing_marker_fails` - 缺少生成标记应失败
- `test_missing_structure_fails` - 缺少 MCP 结构应失败
- `test_fastmcp_style_passes` - FastMCP 风格应通过

#### 关键断言

```python
# 检查通过
assert report.passed is True
assert len(report.violations) == 0

# 检查失败
assert report.passed is False
assert "import" in report.violations[0].lower()

# 警告检查
assert len(report.warnings) > 0
```

### 2. test_builder_versioning.py（20 cases）

测试 `cygnusx.infrastructure.mcp.builder.versioning` 的 SemVer 版本管理工具。

#### 测试覆盖

**SemVer 格式验证（11 cases）**
```python
@pytest.mark.parametrize("version,expected", [
    ("1.0.0", True),
    ("0.1.0", True),
    ("12.34.56", True),
    ("1.2.0-beta", True),
    ("2.0.0-rc.1", True),
    ("1.0", False),
    ("v1.0.0", False),
    ("1.0.0.0", False),
    ("01.0.0", False),
    ("", False),
    ("abc", False),
])
def test_is_valid_semver(version, expected):
    from cygnusx.infrastructure.mcp.builder.versioning import is_valid_semver
    assert is_valid_semver(version) is expected
```

**版本号推导（5 cases）**
- `test_determine_version_feature` - feature → minor+1
- `test_determine_version_fix` - fix → patch+1
- `test_determine_version_refactor` - refactor → patch+1
- `test_determine_version_breaking` - breaking → major+1
- `test_determine_version_strips_prerelease` - 预发布版本处理

**错误处理（2 cases）**
- `test_determine_version_invalid_parent` - 非法父版本号抛异常
- `test_determine_version_invalid_change_type` - 非法变更类型抛异常

**版本比较和解析（2 cases）**
- `test_compare_versions` - 版本号比较（5 个子 case）
- `test_parse_semver` - SemVer 解析

#### 版本推导规则

| 变更类型 | 输入 | 输出 | 说明 |
|----------|------|------|------|
| `feature` | 1.2.3 | 1.3.0 | 新功能，minor+1 |
| `fix` | 1.2.3 | 1.2.4 | Bug 修复，patch+1 |
| `refactor` | 1.2.3 | 1.2.4 | 重构，patch+1 |
| `breaking` | 1.2.3 | 2.0.0 | 破坏性变更，major+1 |

### 3. test_builder_docs_and_generator.py（3 cases）

测试文档生成和代码生成器功能。

#### 测试覆盖

- `test_generate_build_doc` - 构建文档生成
- `test_generate_architecture_doc` - 架构文档生成
- `test_extract_python_code` - Python 代码提取

## 特殊说明

### 为什么需要 `--noconftest`？

项目根目录的 `tests/conftest.py` 会导入完整的 `cygnusx.main.app`，这需要安装所有生产依赖（bcrypt、litellm 等）。

MCP Builder 的核心模块（safety、versioning）是独立的，不需要这些重依赖，因此使用 `--noconftest` 标志跳过 conftest.py 的加载。

```bash
# 推荐：跳过 conftest
PYTHONPATH=src python -m pytest tests/unit/mcp/ -v --noconftest

# 不推荐：会因缺少依赖而失败
PYTHONPATH=src python -m pytest tests/unit/mcp/ -v
```

### 测试依赖

本测试套件仅依赖：
- `pytest` - 测试框架
- `pytest-asyncio` - 异步测试支持（部分测试使用）
- Python 标准库（`ast`、`dataclasses` 等）

无需安装 `bcrypt`、`litellm`、`fastapi` 等生产依赖。

### 测试数据

所有测试使用内联代码字符串，无需外部测试数据文件：

```python
code = f'''{GENERATED_MARKER} = True
from mcp.server import Server

server = Server("test")

@server.list_tools()
async def list_tools() -> list:
    return []

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    return []
'''
```

## 持续集成

在 CI/CD 流水线中运行测试：

```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行测试
PYTHONPATH=src python -m pytest tests/unit/mcp/ -v --noconftest --tb=short

# 生成覆盖率报告（可选）
pip install pytest-cov
PYTHONPATH=src python -m pytest tests/unit/mcp/ --cov=cygnusx.infrastructure.mcp.builder --cov-report=term-missing --noconftest
```

## 故障排查

### 问题：ModuleNotFoundError: No module named 'cygnusx'

**解决方案**：设置 PYTHONPATH
```bash
export PYTHONPATH=/home/zj/zj_code_libarary/CygnusX/src
# 或在命令中指定
PYTHONPATH=src python -m pytest tests/unit/mcp/ -v --noconftest
```

### 问题：ImportError while loading conftest

**解决方案**：添加 `--noconftest` 标志
```bash
PYTHONPATH=src python -m pytest tests/unit/mcp/ -v --noconftest
```

### 问题：pytest: command not found

**解决方案**：安装 pytest
```bash
pip install pytest pytest-asyncio
# 或使用 Python 模块方式
python -m pytest tests/unit/mcp/ -v --noconftest
```

## 相关文档

- [MCP Builder 系统架构](../../../docs/mcp_builder/ARCHITECTURE.md)
- [AST 安全检查器规范](../../../src/cygnusx/infrastructure/mcp/builder/safety.py)
- [版本管理工具](../../../src/cygnusx/infrastructure/mcp/builder/versioning.py)
- [Agent 配置指南](../../../data/ai/mcp_builder.yaml)

## 维护者

- CygnusX 开发团队
- 最后更新：2026-07-29
