
# 现有平台与 AI 沙箱兼容性调查与升级方案文档

**版本**: v2.0 审计修订版  
**文档日期**: 2026-08-22  
**审计范围**: 当前 CygnusX 工作树  
**状态**: 已完成代码级审计；浏览器、Office 和桌面可视化仍未实现

> 文件位于 `docs/info/26.8.23/`，但当前基准日期为 2026-08-22；目录名属于未来日期，建议在提交前改为 `docs/info/26.8.22/`，或明确这是预创建文档。

## 审计结论

当前仓库不是“待从零接入沙箱”的平台，而是已经存在两套沙箱能力：

1. **旧版代码执行沙箱**：`/api/v1/sandbox`，由数据库会话、Docker warm pool 和 WebSocket/REST 执行接口组成，支持 Python、R、Bash。
2. **OmicStudio 会话沙箱**：`/api/v1/studio`，每个 Studio 会话对应一个 Docker 容器，容器内运行 `sandbox-agent`，宿主通过工作区 Unix Socket 访问，支持文件操作、代码执行、产物和计划流。

因此，原文“在现有镜像中直接叠加 Browser + Office + MCP”不能作为当前事实或首选实施路径：Studio 已有独立镜像和工具路由，但当前镜像没有浏览器、OnlyOffice、VNC/noVNC 或浏览器/文档 MCP 工具。正确的下一步是先补齐安全基线和能力边界，再按独立镜像/独立会话类型增量接入浏览器或文档能力。

---

## 第一部分：现有平台资产审计结果

### 1.1 平台基础架构

| 审计项 | 当前状态 | 备注 |
|--------|---------|------|
| 前端技术栈 | [x] Vue 3 + TypeScript | `frontend/package.json` 使用 Vue 3.4；沙箱/Studio 页面位于 `frontend/src/views/` |
| 后端技术栈 | [x] Python + FastAPI | API 路由位于 `src/cygnusx/api/v1/` |
| 部署架构 | [x] Docker Compose；[ ] Kubernetes 主路径 | `deploy/docker/docker-compose.yml` 是主部署方式，Kubernetes 目录主要用于 AgentTeams |
| 通信协议 | [x] REST + WebSocket + SSE | 旧沙箱执行使用 WebSocket/REST；Studio Agent 使用宿主工作区 Unix Socket；聊天/工具流使用 SSE |
| 数据库 | [x] PostgreSQL（含 pgvector 镜像） | 配置和 Compose 均指向 PostgreSQL |
| 消息队列/缓存 | [x] Redis + Celery | Studio 活跃状态和执行租约使用 Redis；任务调度使用 Celery |
| 用户认证 | [x] JWT access token | REST 依赖 `CurrentUserId`；旧沙箱 WebSocket 从 query 参数校验 access JWT |
| 是否多租户 | [x] 是（应用层用户隔离） | Studio 新容器只读挂载当前用户目录 `storage_path/users/{user_id}`，不是整根 storage |

### 1.2 现有沙箱能力审计

| 审计项 | 当前状态 | 备注 |
|--------|---------|------|
| 沙箱类型 | [x] Docker 容器；[ ] Firecracker MicroVM；[ ] gVisor | 旧版使用 warm pool；Studio 使用每会话一个容器，未发现 VM 级隔离 |
| 当前支持语言 | [x] Python、R、Bash；[ ] Node.js | 旧版 `SandboxService` 明确拒绝其他语言；Studio 由工具参数和镜像能力共同决定 |
| 文件系统访问 | [x] 会话工作区读写 + 当前用户平台目录只读 | Studio 工作区挂载 `/workspace`；平台目录挂载 `/data/platform`（仅用户目录） |
| 网络权限 | [x] 默认完全隔离；[x] 可选白名单代理 | `studio.sandbox.network.mode` 支持 `none` / `whitelist`；白名单模式通过每会话网络和代理环境变量实现 |
| 当前接口协议 | [x] REST + WebSocket + UDS；[ ] 沙箱内 MCP | `sandbox-agent` 是 UDS HTTP 服务；MCP 是平台侧工具体系，不等于沙箱内已运行 MCP Server |
| 生命周期管理 | [x] 懒启动、复用、预热、空闲回收 | Studio 默认允许创建后预热，Redis ZSET 记录活跃时间；旧版另有数据库回收逻辑 |
| 资源限制 | [x] Studio 默认 CPU shares≈2 核、内存 4 GB、执行超时 600 秒 | 当前代码设置 `cpu_shares` 和 `mem_limit`；未发现严格 CPU quota、PID 上限或并发配额实现 |
| 是否支持浏览器 | [ ] 否（镜像未安装） | 未发现 Chromium、Playwright、浏览器工具或浏览器会话管理实现 |
| 是否支持文档编辑 | [ ] 否（OnlyOffice/VNC 未接入） | `openpyxl`/`pyarrow` 属于文件处理依赖，不是交互式 Office 编辑器 |
| 是否支持 MCP | [x] 平台侧支持；[ ] 沙箱内 MCP | `/api/v1/mcp` 和 Studio 内置工具存在；当前 Studio 工具为 `sandbox_execute`、`workspace_*` 等，不含原文列出的浏览器/文档工具 |

### 1.3 现有 API 接口清单（请列出核心端点）

**旧版代码执行沙箱**（前缀 `/api/v1/sandbox`）：

- `GET /sessions` — 当前用户沙盒会话列表
- `POST /sessions` — 创建或复用沙盒会话
- `GET /sessions/{session_id}` — 查询会话
- `POST /sessions/{session_id}/execute` — 收集式执行代码
- `WS /sessions/{session_id}/ws?token=<JWT>` — 流式执行代码
- `DELETE /sessions/{session_id}` — 销毁会话

**Studio 沙箱**（前缀 `/api/v1/studio`）：

- `POST /sessions`、`GET /sessions`、`GET /sessions/{id}` — Studio 会话生命周期与状态
- `GET /sessions/{id}/files`、`GET /sessions/{id}/files/read` — 文件列表和读取
- `POST /sessions/{id}/run` — SSE 代码执行流
- `POST /sessions/{id}/files/write`、`/files/edit`、`/files/mkdir` — 工作区写入/编辑
- `GET /sessions/{id}/artifacts`、`GET /sessions/{id}/artifacts/download` — 产物列表和下载
- `POST /sessions/{id}/artifacts/register` — 登记报告产物

**边界**：文档中原先的 `/create`、`/{id}/exec`、`/{id}/files`、`/{id}/upload`、`/{id}` 不是仓库当前路由，不能作为接口契约。

### 1.4 安全与合规模型

| 审计项 | 当前状态 | 备注 |
|--------|---------|------|
| 沙箱隔离级别 | [x] 容器级；[ ] VM 级 | Studio 以 Docker 容器为边界；不应宣传为 Firecracker/Kata 等强隔离 |
| 密钥存储位置 | [x] 平台配置/环境变量 | 不应把平台密钥作为容器环境变量或工作区文件传入；需继续核验部署密钥注入策略 |
| API 密钥是否进沙箱 | [ ] 代码未显示注入 | Studio 容器创建参数未注入平台 API key；应增加回归测试防止后续误注入 |
| 是否有审计日志 | [x] 工具调用/平台日志；[ ] 完整沙箱系统审计 | 工具结果和服务日志存在，但容器级 syscall、网络、文件审计尚未形成完整闭环 |
| 是否有资源配额系统 | [ ] 完整配额；[x] 单容器内存/CPU 基础限制 | 未发现租户并发、磁盘、PID、CPU quota 等硬配额 |
| 是否有网络白名单 | [x] Studio 配置支持域名白名单代理 | 默认 `none`；白名单模式必须验证代理本身和 DNS/IPv6 等旁路 |
| 容器加固 | [ ] 未完成 | 当前代码未设置 `pids_limit`、`read_only`、`cap_drop`、`no-new-privileges`、seccomp/AppArmor 等显式参数 |

### 1.5 业务场景与用户需求

| 审计项 | 当前状态 | 期望状态 |
|--------|---------|---------|
| 当前主要用途 | 生信/数据分析、代码执行、工作区产物管理 | 浏览器自动化、Office 编辑需单独立项 |
| 目标用户类型 | 开发者、生信分析用户、企业内部用户 | 仍需产品侧确认具体租户规模 |
| 并发沙箱需求 | 仓库未提供压测基线 | 先建立按租户/节点的并发和队列指标 |
| 单次任务平均时长 | Studio 默认执行上限 600 秒 | 长任务需结合 Celery、租约和前端流式体验定义 |
| 是否需要可视化 | 当前为 Studio 工作台和代码/产物面板 | noVNC/桌面流尚未实现 |
| 是否需要持久化存储 | [x] 工作区/产物持久化 | 需继续确认保留周期、磁盘配额和清理失败告警 |
| 预算范围 | 未在代码或部署配置中定义 | 需要部署环境、镜像大小和并发目标后估算 |

---

## 第二部分：兼容性映射与升级方案

### 2.1 兼容性分析框架

根据仓库实现，CygnusX 同时落在以下两种模式：旧版沙箱接近模式 A，Studio 接近模式 B；平台另有独立 MCP 管理能力。下面的模式仅用于比较，不是当前架构的待填写问卷。

#### 模式 A：轻量代码执行平台（如早期 Replit-like）

**特征**：基于 Docker，支持 Python/Node 代码执行，REST API 管理沙箱，无浏览器能力  
**兼容性**：⭐⭐⭐⭐⭐（最容易升级）  
**升级路径**：若未来需要浏览器能力，应使用独立能力镜像和 Studio capability 路由，不要直接改造所有现有镜像。

#### 模式 B：AI 对话平台（如 ChatGPT-like + 代码解释器）

**特征**：前端聊天界面，后端调用 OpenAI API，有独立的 Code Interpreter 沙箱  
**兼容性**：⭐⭐⭐⭐  
**升级路径**：Studio 已提供会话工作区、代码执行和 Agent 工具路由；浏览器/Office 仍需以受权工具的形式单独实现。

#### 模式 C：API 服务平台（如提供 Sandboxing-as-a-Service）

**特征**：纯后端服务，对外暴露沙箱 API，多租户，已有配额计费系统  
**兼容性**：⭐⭐⭐⭐  
**升级路径**：增加新的沙箱模板（`browser-office` 类型），保持现有 API 兼容，通过 API Versioning 引入新能力

#### 模式 D：企业内网平台（高安全要求）

**特征**：私有化部署，严格网络隔离，已有堡垒机/零信任架构  
**兼容性**：⭐⭐⭐  
**升级路径**：需要额外安全评估，建议采用 Kata Containers / Firecracker 增强隔离，浏览器流量走专用代理

---

### 2.2 三种兼容升级方案对比

| 维度 | 方案一：渐进增强（推荐） | 方案二：沙箱池并行 | 方案三：完全重构 |
|------|----------------------|------------------|----------------|
| **核心思路** | 在现有沙箱镜像中增量安装 Browser + Office，接口层做适配 | 保留现有沙箱，新增独立的 Browser/Office 沙箱池，平台统一调度 | 推翻现有架构，采用 AIO Sandbox / Agent-Sandbox 等成熟方案重建 |
| **对现有代码影响** | 低（修改 Dockerfile + 增加接口适配层） | 中（增加调度路由逻辑） | 高（完全替换） |
| **开发周期** | 2-4 周 | 4-8 周 | 8-16 周 |
| **风险等级** | 低 | 中 | 高 |
| **适合场景** | 现有平台稳定，希望快速验证新能力 | 现有平台负载高，需要能力隔离 | 现有架构老旧，正好借机重构 |
| **长期维护成本** | 中（需要维护复合镜像） | 高（维护多套沙箱体系） | 低（使用社区方案） |
| **扩展性** | 中 | 高 | 高 |

**仓库修订后的推荐**：不要在现有 `cygnusx-sandbox-base` / `cygnusx-sandbox-bio` 镜像中直接叠加 OnlyOffice、VNC 和浏览器服务。应采用“Studio 编排复用 + 独立受限能力镜像”的渐进方案。

1. 先加固既有 Studio 容器创建参数并补回归测试；这是浏览器能力上线的前置门槛。
2. 以新 image id / session capability 区分浏览器和文档能力，保留普通数据分析镜像，避免所有会话承担 Chromium/Office 的体积和攻击面。
3. 浏览器自动化优先使用无头 Playwright，先通过受控工具 API 返回截图和结构化结果；只有明确需要人工查看 GUI 时才评估 noVNC。
4. 文档生成优先采用 `python-docx`、`openpyxl`、`python-pptx` 和受控格式转换；OnlyOffice Document Server 是独立服务，不应作为普通沙箱容器内的 `service` 常驻进程。
5. 沙箱内工具不必强行实现 MCP Server：现有 Studio `stream_studio_tool` 已经是 Agent 调度入口。若外部客户端需要 MCP，再在平台边界实现受鉴权、可审计的 adapter。

### 2.3 已确认缺口与整改顺序

| 优先级 | 缺口 | 代码证据 | 整改要求 |
| --- | --- | --- | --- |
| P0 | Studio CPU 仅使用 `cpu_shares`，不是硬 CPU 上限 | `StudioSandboxManager.ensure_running()` | 采用 Docker 支持的硬 CPU 限制，并为内存/CPU/OOM 场景增加集成测试 |
| P0 | 容器缺少显式 PID、能力、只读根文件系统与 no-new-privileges 限制 | Studio `containers.run()` 参数 | 加入 `pids_limit`、`cap_drop=["ALL"]`、`security_opt=["no-new-privileges:true"]`、只读根文件系统和显式 tmpfs；验证 sandbox-agent 与工具仍可运行 |
| P0 | 白名单代理模式只配置代理环境变量，端到端出口/DNS/IPv6 约束未验证 | `studio_loader.py` + `manager.py` | 为 `none` 和 `whitelist` 加容器级验证；白名单模式必须由代理强制执行域名规则 |
| P0 | 用户工作区可写且会持久化，未看到磁盘配额或归档清理告警 | Studio workspace/scratch 逻辑 | 定义每会话容量、保留期、清理重试和管理员告警 |
| P1 | 浏览器、Office、VNC/noVNC 与相应工具均未实现 | Studio Dockerfile 和 `STUDIO_TOOL_SCHEMAS` | 单独设计、实现并测试，不得在文档中标记为已有功能 |
| P1 | 旧 `/sandbox` 与 Studio 两套生命周期并存 | 两个 API 路由和不同管理器 | 明确产品入口和迁移策略；不要让新浏览器能力同时接入两套实现 |
| P1 | 审计日志不覆盖容器网络、文件和策略拒绝 | 当前仅见应用/工具层日志 | 统一记录会话、镜像、调用者、工具、策略结果、资源峰值和回收原因 |

**安全门槛**：在 P0 未完成前，不应把网络浏览器、VNC 或文档服务暴露给真实租户；Docker 容器不是 VM 安全边界，涉及不可信代码或高敏数据时应评估 gVisor、Kata 或 MicroVM 运行时。

---

### 2.4 方案一详细设计：渐进增强路径（未来设计，非现有实现）

#### 阶段 1：沙箱镜像增强（Week 1-2）

**目标**：让现有沙箱拥有 Browser + Office 能力

```dockerfile
# 基于你现有的沙箱镜像
FROM your-existing-sandbox:latest

# 1. 安装 Chromium + Playwright
RUN apt-get update && apt-get install -y \
    chromium-browser \
    chromium-chromedriver \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxss1 \
    xdg-utils \
    --no-install-recommends

# 2. 安装 Playwright Python 依赖
RUN pip install playwright && playwright install chromium

# 3. 安装 OnlyOffice Document Server
# 方式 A：独立服务（推荐，资源充足时）
RUN apt-get install -y onlyoffice-documentserver

# 方式 B：轻量替代（资源紧张时）
# RUN apt-get install -y libreoffice-writer libreoffice-calc libreoffice-impress

# 4. 安装 MCP Server 框架
RUN pip install mcp

# 5. 启动脚本：同时启动沙箱原有服务 + Browser + Office
COPY start-services.sh /start-services.sh
RUN chmod +x /start-services.sh
CMD ["/start-services.sh"]
```

**关键启动脚本 `start-services.sh`：**

```bash
#!/bin/bash
set -e

# 启动你现有的沙箱服务（如果有常驻服务）
# python /app/your_existing_server.py &

# 启动 OnlyOffice Document Server（如选择方式A）
service onlyoffice-documentserver start

# 启动 MCP Server（新增）
python /app/mcp_server.py &

# 保持容器运行
tail -f /dev/null
```

#### 阶段 2：MCP 接口适配层（Week 2-3）

**目标**：让 AI 可以通过标准 MCP 协议操作沙箱

```python
# mcp_server.py — 沙箱内运行的 MCP Server
from mcp.server import Server
from mcp.types import Tool, TextContent
import asyncio
import subprocess
import json
import os
from playwright.async_api import async_playwright

app = Server("sandbox-mcp")

# 工具注册表
TOOLS = [
    Tool(
        name="browser_navigate",
        description="导航到指定 URL 并返回页面内容摘要",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "目标 URL"},
                "wait_for": {"type": "string", "description": "等待加载的选择器", "default": "body"}
            },
            "required": ["url"]
        }
    ),
    Tool(
        name="browser_screenshot",
        description="截取当前页面截图并返回 base64",
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "截图元素选择器", "default": "body"},
                "full_page": {"type": "boolean", "default": False}
            }
        }
    ),
    Tool(
        name="browser_click",
        description="在页面上点击指定元素",
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS 选择器"},
                "wait_for_navigation": {"type": "boolean", "default": False}
            },
            "required": ["selector"]
        }
    ),
    Tool(
        name="browser_fill",
        description="在表单字段中填写内容",
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "输入框选择器"},
                "value": {"type": "string", "description": "填写内容"}
            },
            "required": ["selector", "value"]
        }
    ),
    Tool(
        name="browser_scroll",
        description="滚动页面",
        inputSchema={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "integer", "default": 500}
            },
            "required": ["direction"]
        }
    ),
    Tool(
        name="browser_evaluate",
        description="在页面上下文中执行 JavaScript 并返回结果",
        inputSchema={
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "JavaScript 代码"}
            },
            "required": ["script"]
        }
    ),
    Tool(
        name="document_create",
        description="创建新文档（docx/xlsx/pptx）",
        inputSchema={
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["docx", "xlsx", "pptx"], "description": "文档类型"},
                "filename": {"type": "string", "description": "文件名"},
                "template": {"type": "string", "description": "可选模板路径"}
            },
            "required": ["type", "filename"]
        }
    ),
    Tool(
        name="document_edit",
        description="编辑文档内容（通过 OnlyOffice API 或 python-docx）",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "目标文档路径"},
                "operations": {
                    "type": "array",
                    "description": "编辑操作列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["replace", "insert", "delete", "style"]},
                            "target": {"type": "string", "description": "目标位置/选择器"},
                            "value": {"type": "string", "description": "新内容"}
                        }
                    }
                }
            },
            "required": ["filename", "operations"]
        }
    ),
    Tool(
        name="document_convert",
        description="转换文档格式（如 docx -> pdf）",
        inputSchema={
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "输入文件路径"},
                "output_format": {"type": "string", "enum": ["pdf", "txt", "html", "docx", "xlsx"]}
            },
            "required": ["input", "output_format"]
        }
    ),
    Tool(
        name="shell_exec",
        description="执行 shell 命令（保留你现有能力）",
        inputSchema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "命令"},
                "timeout": {"type": "integer", "default": 30},
                "working_dir": {"type": "string", "default": "/workspace"}
            },
            "required": ["command"]
        }
    ),
    Tool(
        name="file_read",
        description="读取文件内容",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 1000}
            },
            "required": ["path"]
        }
    ),
    Tool(
        name="file_write",
        description="写入文件内容",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    )
]

# Playwright 浏览器实例（单例模式）
browser = None
page = None

async def ensure_browser():
    global browser, page
    if browser is None:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process"
            ]
        )
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
    return page

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    await ensure_browser()

    if name == "browser_navigate":
        url = arguments["url"]
        await page.goto(url, wait_until="networkidle")
        content = await page.evaluate('''() => {
            const text = document.body.innerText;
            return text.substring(0, 2000) + (text.length > 2000 ? '...' : '');
        }''')
        return [TextContent(type="text", text=f"已导航至 {url} 页面内容摘要：{content}")]

    elif name == "browser_screenshot":
        selector = arguments.get("selector", "body")
        full_page = arguments.get("full_page", False)
        element = await page.query_selector(selector)
        if element:
            screenshot = await element.screenshot(full_page=full_page)
        else:
            screenshot = await page.screenshot(full_page=full_page)
        import base64
        b64 = base64.b64encode(screenshot).decode()
        return [TextContent(type="text", text=f"data:image/png;base64,{b64}")]

    elif name == "browser_click":
        selector = arguments["selector"]
        wait_nav = arguments.get("wait_for_navigation", False)
        if wait_nav:
            async with page.expect_navigation():
                await page.click(selector)
        else:
            await page.click(selector)
        return [TextContent(type="text", text=f"已点击元素: {selector}")]

    elif name == "browser_fill":
        selector = arguments["selector"]
        value = arguments["value"]
        await page.fill(selector, value)
        return [TextContent(type="text", text=f"已在 {selector} 填写内容")]

    elif name == "browser_scroll":
        direction = arguments["direction"]
        amount = arguments.get("amount", 500)
        if direction == "down":
            await page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            await page.evaluate(f"window.scrollBy(0, -{amount})")
        return [TextContent(type="text", text=f"已向{direction}滚动{amount}px")]

    elif name == "browser_evaluate":
        script = arguments["script"]
        result = await page.evaluate(script)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

    elif name == "document_create":
        doc_type = arguments["type"]
        filename = arguments["filename"]
        filepath = f"/workspace/{filename}"
        if doc_type == "docx":
            from docx import Document
            doc = Document()
            doc.save(filepath)
        elif doc_type == "xlsx":
            from openpyxl import Workbook
            wb = Workbook()
            wb.save(filepath)
        return [TextContent(type="text", text=f"已创建文档: {filepath}")]

    elif name == "document_convert":
        input_path = arguments["input"]
        output_format = arguments["output_format"]
        cmd = f"libreoffice --headless --convert-to {output_format} --outdir /workspace {input_path}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return [TextContent(type="text", text=f"转换完成: {result.stdout}")]

    elif name == "shell_exec":
        cmd = arguments["command"]
        timeout = arguments.get("timeout", 30)
        cwd = arguments.get("working_dir", "/workspace")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        output = result.stdout + ("错误: " + result.stderr if result.stderr else "")
        return [TextContent(type="text", text=output)]

    elif name in ["file_read", "file_write"]:
        # 保留你现有的文件操作逻辑
        pass

    else:
        return [TextContent(type="text", text=f"未知工具: {name}")]

async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

#### 阶段 3：平台侧适配层（Week 3-4）

**目标**：让你的平台能够创建「增强型沙箱」并路由 MCP 消息

```python
# 平台侧：沙箱管理器增强
class EnhancedSandboxManager:
    def __init__(self):
        self.sandboxes = {}
        self.mcp_clients = {}

    async def create_enhanced_sandbox(self, user_id: str, task_type: str = "browser-office") -> dict:
        """
        创建增强型沙箱
        task_type 可选:
          - "code-only": 仅代码执行（兼容旧版）
          - "browser-office": 代码 + 浏览器 + 文档（新版）
        """
        if task_type == "browser-office":
            image = "your-registry/sandbox-enhanced:latest"
            resources = {"cpu": 2, "memory": "4g", "timeout": 3600}
        else:
            image = "your-registry/sandbox-base:latest"
            resources = {"cpu": 1, "memory": "1g", "timeout": 300}

        # 创建容器（复用你现有的编排逻辑）
        container = await self.docker_client.containers.run(
            image=image,
            detach=True,
            mem_limit=resources["memory"],
            cpu_quota=resources["cpu"] * 100000,
            network_mode="sandbox-net",  # 受限网络
            volumes={f"/data/workspace/{user_id}": {"bind": "/workspace", "mode": "rw"}},
            environment={
                "MCP_TRANSPORT": "stdio",  # 或 "sse"
                "SANDBOX_USER_ID": user_id,
                "SANDBOX_TIMEOUT": str(resources["timeout"])
            }
        )

        sandbox_id = container.id[:12]
        self.sandboxes[sandbox_id] = {
            "user_id": user_id,
            "container": container,
            "created_at": datetime.now(),
            "task_type": task_type
        }

        # 初始化 MCP 连接
        if task_type == "browser-office":
            mcp_client = await MCPClient.connect(container)
            self.mcp_clients[sandbox_id] = mcp_client

        return {
            "sandbox_id": sandbox_id,
            "status": "ready",
            "capabilities": ["shell", "file", "browser", "document"] if task_type == "browser-office" else ["shell", "file"],
            "mcp_endpoint": f"/mcp/{sandbox_id}"
        }

    async def execute_task(self, sandbox_id: str, tool_name: str, params: dict):
        """执行 MCP 工具调用"""
        if sandbox_id not in self.mcp_clients:
            raise ValueError(f"沙箱 {sandbox_id} 未初始化 MCP 连接")

        client = self.mcp_clients[sandbox_id]
        result = await client.call_tool(tool_name, params)
        return result

    async def get_sandbox_stream(self, sandbox_id: str):
        """获取沙箱的 VNC/浏览器实时画面流（用于前端展示）"""
        container = self.sandboxes[sandbox_id]["container"]
        return f"wss://your-platform.com/vnc/{sandbox_id}"
```

#### 阶段 4：前端能力开关（Week 4）

```typescript
// 前端：根据沙箱能力动态显示工具栏
interface SandboxCapabilities {
  shell: boolean;
  file: boolean;
  browser: boolean;
  document: boolean;
  vnc: boolean;
}

const ToolPanel: React.FC<{ sandboxId: string }> = ({ sandboxId }) => {
  const [caps, setCaps] = useState<SandboxCapabilities | null>(null);

  useEffect(() => {
    fetch(`/api/sandbox/${sandboxId}/capabilities`)
      .then(r => r.json())
      .then(setCaps);
  }, [sandboxId]);

  if (!caps) return <Loading />;

  return (
    <div className="tool-panel">
      {caps.browser && (
        <BrowserToolbar 
          onNavigate={(url) => callTool(sandboxId, 'browser_navigate', { url })}
          onScreenshot={() => callTool(sandboxId, 'browser_screenshot', {})}
          onClick={(selector) => callTool(sandboxId, 'browser_click', { selector })}
        />
      )}
      {caps.document && (
        <DocumentToolbar
          onCreate={(type) => callTool(sandboxId, 'document_create', { type, filename: 'new.docx' })}
          onConvert={(input, fmt) => callTool(sandboxId, 'document_convert', { input, output_format: fmt })}
        />
      )}
      {/* 保留你现有的代码编辑器 */}
      <CodeEditor sandboxId={sandboxId} />
    </div>
  );
};
```

---

### 2.5 方案二：沙箱池并行（高并发场景，未来设计）

如果你的现有平台已经承载大量用户，直接修改镜像风险较高，可以采用「沙箱池并行」架构：

```
┌─────────────────────────────────────────────┐
│              你的平台（API Gateway）           │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │
│  │ 路由层   │  │ 调度器   │  │ 会话管理    │  │
│  └────┬────┘  └────┬────┘  └──────┬──────┘  │
└───────┼────────────┼──────────────┼─────────┘
        │            │              │
   ┌────┴────────┐   ┌┴─────────────┐  ┌┴──────────────┐
   │  现有沙箱池  │   │ 浏览器沙箱池   │  │ 文档沙箱池     │
   │ (代码执行)   │   │ (Playwright)  │  │ (OnlyOffice)  │
   │  稳定运行    │   │   按需扩容     │  │   按需扩容     │
   └─────────────┘   └──────────────┘  └───────────────┘
```

**路由策略**：
- 用户请求仅含代码 → 现有沙箱池
- 用户请求含浏览器操作 → 浏览器沙箱池
- 用户请求含文档编辑 → 文档沙箱池
- 复杂任务 → 组合调用（通过编排层协调多个沙箱）

**优点**：风险隔离、独立扩缩容、灰度发布  
**缺点**：维护成本翻倍、跨沙箱文件同步复杂

---

### 2.6 方案三：完全重构（长期候选）

如果现有架构已运行 2 年以上，技术债较重，建议直接采用成熟开源方案：

| 组件 | 推荐方案 | 理由 |
|------|---------|------|
| 沙箱运行时 | **Agent-Sandbox** (K8s) | 原生支持 Browser/Code/Desktop 三类沙箱，E2B 协议兼容 |
| 浏览器自动化 | **Browser Use** + Playwright | 社区活跃，Unikraft 版本安全隔离 |
| 文档编辑 | **OnlyOffice Document Server** | 最成熟的自托管方案 |
| MCP 框架 | **AIO Sandbox MCP Hub**（候选） | 候选组件；当前仓库未集成，需在许可证、维护状态和鉴权边界审查后决定 |
| 前端展示 | **noVNC** + 自定义 UI | 标准 VNC 协议，浏览器内嵌 |
| 网络隔离 | **Istio/Envoy** | 服务网格级别的 egress 控制 |

**迁移策略**：
1. 并行运行新旧系统 3-6 个月
2. 逐步将用户流量从旧沙箱切到新沙箱
3. 旧系统只维护不新增功能
4. 完全切流后下线旧系统

---

## 第三部分：功能扩展详细设计

### 3.1 AI 浏览器能力清单（共 20+ 项）

| 能力 | 工具名 | 描述 | 优先级 |
|------|--------|------|--------|
| 页面导航 | `browser_navigate` | 访问 URL，等待加载完成 | P0 |
| 元素点击 | `browser_click` | 点击按钮/链接 | P0 |
| 表单填写 | `browser_fill` | 在 input/textarea 中输入内容 | P0 |
| 页面截图 | `browser_screenshot` | 截取可见区域或全页 | P0 |
| 文本提取 | `browser_extract_text` | 提取页面纯文本内容 | P0 |
| 元素定位 | `browser_find_element` | 通过文本/CSS/XPath 定位元素 | P0 |
| 页面滚动 | `browser_scroll` | 上下左右滚动 | P1 |
| JavaScript 执行 | `browser_evaluate` | 在页面上下文运行 JS | P1 |
| 等待元素 | `browser_wait_for` | 等待元素出现/消失 | P1 |
| 下拉选择 | `browser_select` | 操作 select 元素 | P1 |
| 文件上传 | `browser_upload` | 通过文件选择器上传文件 | P1 |
| 多标签页 | `browser_new_tab` | 打开新标签页 | P1 |
| 返回/前进 | `browser_go_back` / `browser_go_forward` | 浏览器历史导航 | P1 |
| Cookie 操作 | `browser_get_cookies` / `browser_set_cookie` | 管理 Cookie | P2 |
| LocalStorage | `browser_local_storage` | 读写本地存储 | P2 |
| 请求拦截 | `browser_intercept_requests` | 拦截/修改 HTTP 请求 | P2 |
| 移动端模拟 | `browser_set_viewport` | 切换为移动端视口 | P2 |
| 验证码处理 | `browser_solve_captcha` | 集成验证码识别服务 | P2 |
| PDF 导出 | `browser_pdf` | 将页面导出为 PDF | P2 |
| 性能监控 | `browser_get_metrics` | 获取页面性能指标 | P3 |
| 录屏 | `browser_record_video` | 录制操作视频 | P3 |

### 3.2 文档编辑能力清单

| 能力 | 工具名 | 描述 | 优先级 |
|------|--------|------|--------|
| 创建文档 | `document_create` | 创建 docx/xlsx/pptx | P0 |
| 读取内容 | `document_read` | 提取文档文本/表格内容 | P0 |
| 文本替换 | `document_replace` | 全文替换或按段落替换 | P0 |
| 插入内容 | `document_insert` | 在指定位置插入文本/图片/表格 | P0 |
| 格式设置 | `document_style` | 设置字体、颜色、对齐等 | P1 |
| 表格操作 | `document_table` | 创建/修改表格 | P1 |
| 图片插入 | `document_insert_image` | 插入图片到文档 | P1 |
| 页眉页脚 | `document_header_footer` | 设置页眉页脚 | P1 |
| 目录生成 | `document_toc` | 自动生成目录 | P2 |
| 批注添加 | `document_comment` | 添加批注 | P2 |
| 格式转换 | `document_convert` | docx <-> pdf <-> html 等 | P0 |
| 合并文档 | `document_merge` | 合并多个文档 | P2 |
| 模板填充 | `document_template` | 基于模板批量生成 | P1 |

### 3.3 轻量桌面能力（VNC 模式）

当用户需要「看到」沙箱内的浏览器或 Office 界面时，启用 VNC 模式：

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   用户浏览器  │ <-> │  noVNC 前端  │ <-> │  VNC Server │
│  (Canvas)   │     │  (WebSocket)│     │  (沙箱内)   │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                       ┌──┴──┐
                                       │Xvfb │ <-- 虚拟显示缓冲区
                                       └──┬──┘
                                          │
                                       ┌──┴──────────┐
                                       │Chromium/    │
                                       │OnlyOffice   │
                                       └─────────────┘
```

**实现要点**：
1. 沙箱内安装 `Xvfb`（虚拟显示）+ `x11vnc`（VNC 服务）
2. 浏览器/Office 运行在虚拟显示器 `:99` 上
3. 通过 noVNC（HTML5 VNC 客户端）在浏览器中呈现
4. AI 操作与 VNC 画面同步：AI 执行 click 后，前端自动刷新 Canvas

**资源开销**：Xvfb + x11vnc 约增加 100-200MB 内存，对现代服务器可忽略。

---

## 第四部分：实施路线图与里程碑

### Phase 1：安全基线与最小能力验证（4-6 周）

**目标**：验证核心能力，不影响现有用户

- [x] Week 1: 完成仓库代码级资产审计并确认两套沙箱边界
- [ ] Week 2: 修复 Studio 容器安全基线（硬 CPU/PID/能力/只读根文件系统）并为 `none`/`whitelist` 网络加测试
- [ ] Week 3: 构建独立浏览器或文档镜像；定义镜像选择和 capability 授权模型
- [ ] Week 4: 在既有 Studio 工具路由中实现最小工具集（截图、受控导航、文档生成/转换），而非新建未鉴权容器内 MCP 服务
- [ ] Week 5: 前端仅展示经授权的工具调用、截图和产物；不默认接入 noVNC
- [ ] Week 6: 执行隔离、越权、网络出口、资源耗尽和多租户回归测试

**交付物**：
- 经安全审查的独立能力镜像
- Studio 工具/API 的权限与审计实现
- 网络、资源、多租户隔离测试报告
- 性能基线与回滚方案

### Phase 2：灰度发布（4 周）

**目标**：小范围用户试用，收集反馈

- [ ] 选择 5-10 个种子用户
- [ ] A/B 测试：旧沙箱 vs 增强型沙箱
- [ ] 监控资源消耗、错误率、用户满意度
- [ ] 迭代优化（增加工具、修复 bug）

**成功标准**：
- 沙箱启动时间 < 10 秒
- 浏览器操作成功率 > 95%
- 文档转换成功率 > 98%
- 用户 NPS > 50

### Phase 3：全面上线（4 周）

**目标**：所有用户可用，旧系统逐步下线

- [ ] 全量切换至增强型沙箱
- [ ] 完善监控告警（Prometheus + Grafana）
- [ ] 编写用户文档与示例
- [ ] 旧系统进入维护模式

### Phase 4：高级功能（持续迭代）

- [ ] 多标签页浏览器会话
- [ ] 协同编辑（多人同时操作同一文档）
- [ ] AI 自动工作流（预设任务模板）
- [ ] 浏览器指纹随机化（反检测）
- [ ] 移动端浏览器模拟

---

## 第五部分：风险与应对

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|---------|
| 沙箱镜像体积过大（>5GB） | 启动慢、存储成本高 | 中 | 多阶段构建，分离基础层与业务层；使用镜像预热池 |
| 浏览器内存泄漏 | 沙箱崩溃 | 中 | 设置浏览器实例最大生命周期（如 30 分钟强制重启） |
| OnlyOffice 启动慢 | 首次文档编辑延迟高 | 高 | 预启动 OnlyOffice 服务；或使用 LibreOffice 做轻量替代 |
| 网络隔离绕过 | 安全风险 | 中 | 默认 `network_mode=none`；白名单代理实施端到端验证；补齐 no-new-privileges、cap drop、PID/CPU 限制与运行时策略 |
| 把规划误当成功能 | 错误上线/错误接口契约 | 高 | 以本文件第一部分审计表为准；所有浏览器/Office/noVNC 功能在测试和镜像落地前标记为“未实现” |
| 用户并发突增 | 资源耗尽 | 中 | 实现排队机制 + 自动扩缩容 + 资源配额硬限制 |

---

## 附录 A：仍需产品与运维确认的信息

仓库已足以完成代码级审计；以下问题不能从代码可靠推断，需在实施前由产品、运维和安全负责人确认：

1. **实际生产镜像与运行时版本**是否与 `deploy/studio/` 一致。
2. **生产资源限制**（Docker daemon、cgroup、节点规格、并发上限）及是否启用 rootless Docker。
3. **用户主要场景和数据分级**：是否允许网页抓取、外部上传、受监管人类数据或受限参考数据进入浏览器会话。
4. **并发、任务时长和工作区容量目标**，用于设计队列、磁盘配额和清理策略。
5. **网络出口规范**：允许域名、DNS 解析方式、代理审计、IPv6 和下载文件大小限制。
6. **安全与合规要求**：等保、SOC 2、数据驻留、审计留存和事件响应要求。
7. **是否具备 Kubernetes/专用节点条件**；仅在需要强隔离或大规模弹性时评估迁移。
8. **浏览器/Office 的验收场景**，据此确定是否真的需要 noVNC 和 OnlyOffice。

---

## 附录 B：参考资源

- [AIO Sandbox](https://github.com/agent-infra/sandbox) — 开箱即用的 AI 沙箱
- [Agent-Sandbox](https://github.com/All-Hands-AI/agent-sandbox) — K8s 原生 Agent 沙箱
- [MCP Protocol](https://modelcontextprotocol.io/) — 模型上下文协议规范
- [Browser Use](https://github.com/browser-use/browser-use) — AI 浏览器自动化
- [OnlyOffice Document Server](https://www.onlyoffice.com/document-server.aspx) — 自托管文档编辑
- [Playwright](https://playwright.dev/) — 浏览器自动化框架
- [noVNC](https://github.com/novnc/noVNC) — 浏览器内 VNC 客户端
