---
name: MCP Server 构建工作台
skill_id: mcp-server-builder
description: 当需要把自然语言需求实现为一个新的 MCP Server 时使用。承载 MCP 构建师的完整工作流：需求规划、技术选型、两种代码模板（本地计算 / 外部 API）、沙箱 AST 自检、功能测试、build/architecture 文档生成与交付清单。只覆盖"生成并沙箱验证代码"，不含提交与发布（提交决策权属于用户）。
version: 1.0.0
author: zj
icon: 🔧
category: development
---

# MCP Server 构建工作台（mcp-server-builder）

## 何时使用（Trigger）

- 用户要求"做一个 MCP / 工具 / Server"来查询外部 API、处理文件或提供某种计算能力；
- 需要修改、迭代一个已生成的实验性 MCP Server；
- **不适用**：平台已有工具能直接满足的需求（先用现有工具回答）；需要持久化状态、GUI、长驻后台进程的需求（超出 MCP 能力，说明后建议替代方案）。

## 运行环境契约（生成代码必须满足）

- **运行时**：Docker 隔离容器，Python 3.12；容器内预装 `mcp>=1.2.0`、`pydantic>=2.6.0`、`fastapi`、`uvicorn`、`pandas`、`numpy`、`scipy`、`scikit-learn`、`statsmodels`、`httpx`、`requests`。
- **传输方式：仅 STDIO**。由 `sandbox-agent`（FastAPI，Unix Socket）以 `mcp.client.stdio.stdio_client` 把生成的 server 拉启为子进程；不支持 SSE / Streamable HTTP。
- **文件边界**：非 root 用户（uid 10001），工作区 `/workspace`；生成物写入 `mcp-builds/{mcp_name}/`（目录由平台预建，`workspace_write` 也会自动补父目录）。
- **网络隔离**：出站流量经 egress proxy 白名单，当前仅含包源域名（`conda.anaconda.org`、`pypi.org`、`files.pythonhosted.org`、`mirrors.aliyun.com`、`mirrors.ustc.edu.cn`）。外部 API（NCBI、OpenWeather 等）**不可直达**；需要外部 API 时必须：
  1. 代码中显式声明 `ALLOWED_DOMAINS`；
  2. 告知用户联系管理员扩展 `data/ai/studio.yaml` → `sandbox.network.allow`；
  3. 测试阶段改用纯计算/本地数据或 mock 验证逻辑。

## 安全检查器契约（AST 静态分析）

平台对生成代码执行 `StaticSafetyChecker.analyze()`（`infrastructure/mcp/builder/safety.py`）：

- **violation（硬性失败）**：禁止的 import、危险函数调用、系统路径访问、缺少生成标记或 MCP handler；
- **warning（记录不阻断）**：白名单外的 import、内网 IP 字符串。

硬性红线（违反即被拒）：

- 禁止 `os.system`、`subprocess`、`eval`、`exec`、`compile`、`open`、`getattr`；
- 禁止 `pickle`、`marshal`、`ctypes`、`importlib`、`socket`、`shutil`、`threading`；
- 禁止访问 `/etc`、`/proc`、`/sys`、`/root`、`/dev`；禁止相对导入；
- 代码顶部必须有 `__exp_mcp_generated__ = True` 生成标记；
- 必须实现 `tools/list` 与 `tools/call` handler；网络请求必须设超时且域名列入 `ALLOWED_DOMAINS`。

## 工作流程（六阶段，严格按顺序）

### Phase 1 需求理解与规划

1. 需求模糊时用 `ask_user` 提 1-3 个澄清问题；
2. 能力映射定类型：外部 API 调用（需 egress 白名单）/ 文件操作（仅 `/workspace`）/ 纯计算（**优先推荐**）；
3. 技术选型固定为：Python 3.12 + STDIO + `mcp>=1.2.0`（低层 `mcp.server.Server` 推荐，或高层 `FastMCP`）+ 仅沙箱预装依赖；
4. 向用户输出规划摘要：需求总结、工具清单（名称/描述/参数）、技术选型、网络需求与风险点。

### Phase 2 信息搜索

涉及外部 API 或不熟悉领域时用 `web_search`：官方 API 文档、Python SDK 文档、MCP 规范（modelcontextprotocol.io）、开源参考实现。搜索后总结端点、认证方式、限流、返回格式作为编码依据。

### Phase 3 代码生成

按需求类型选择模板，**模板全文见 references/**：

- `references/template_local_computation.py` —— 模板 A：本地数据处理（推荐，无网络依赖），以 CSV 统计为完整示例；
- `references/template_external_api.py` —— 模板 B：外部 API 调用（需 egress 白名单），以 NCBI E-utilities 基因搜索为完整示例。

两个模板都演示了必须遵守的结构：生成标记、`Tool` + JSON Schema 定义、业务函数与协议 handler 分离、错误以 JSON 包进 `TextContent` 返回（不抛出）、STDIO 入口。生成时用 `workspace_write` 写入 `mcp-builds/{mcp_name}/server.py`。

### Phase 4 沙箱测试

1. **AST 自检**：用 `sandbox_execute` 对 server.py 做语法解析、生成标记与 handler 结构断言（测试脚本本身不受安全检查器约束，可用 `open`）；
2. **容器内启动验证**：语法通过后提示用户——平台后端会以 STDIO 子进程方式拉起 server 完成协议握手、列出 `tools/list`、逐个 `tools/call` 验证（由平台执行，非 LLM 工具）；
3. **功能测试**：业务函数可独立调用时，用 `sandbox_execute` 构造模拟输入逐个验证，记录 `{input, expected, actual, passed}`；
4. **测试数据**：用户未提供时用 `ask_user` 请求测试用例；外部 API 工具在域名未入白名单时用 mock 数据验证逻辑。

### Phase 5 文档生成

测试通过后用 `workspace_write` 在 `mcp-builds/{mcp_name}/` 生成：

- `build.md`：需求原文、实现方案、工具清单表格、测试记录、依赖列表、网络需求（域名白名单）、生成信息（模型/时间）；
- `architecture.md`：组件关系（LLM tool_call → MCPClient → sandbox-agent UDS → STDIO 子进程 → Server → 外部API/本地计算）、安全边界（Docker 沙箱 + egress 白名单 + AST 检查 + TTL）、版本历史。

### Phase 6 交付

- 产物汇总：`server.py`、`build.md`、`architecture.md` + 测试结果摘要；
- 说明平台提交时会跑同样的 AST 检查，本代码按其规则编写；
- 指引用户自行下载、本地测试、决定是否经管理后台或 CLI 提交；域名白名单扩展找管理员；
- 版本迭代时说明变更类型（feature/fix/breaking/refactor），提交时平台按 SemVer 自动推导版本号：breaking → major+1，feature → minor+1，fix/refactor → patch+1。
