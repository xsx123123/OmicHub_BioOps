# OmicHub MCP Server 架构与扩展指南

## 目录结构

```
mcp-server/
├── config.yaml          # 服务配置 (连接、工具组开关、限制)
├── tools.yaml           # 工具注册表 (元数据声明，供文档和校验用)
├── pyproject.toml       # 依赖管理
├── main.py              # 入口: FastMCP 实例 + 注册
├── start.sh             # 启动脚本
├── core/
│   ├── config.py        # 配置加载 (YAML + 环境变量覆盖)
│   └── logger.py        # 日志
├── client/
│   └── api_client.py    # 平台 REST API 客户端 (httpx)
├── tools/               # 工具模块 (每组一个文件)
│   ├── __init__.py      # 按 config.yaml 开关注册
│   ├── tasks.py
│   ├── flows.py
│   ├── analysis.py
│   ├── downloads.py
│   ├── files.py
│   ├── reports.py
│   ├── sandbox.py
│   └── platform.py
├── resources/           # MCP Resources (只读数据源)
│   └── catalog.py
├── prompts/             # MCP Prompts (工作流引导)
│   └── workflows.py
└── models/              # Pydantic 模型 (可选)
```

## 配置体系

### config.yaml

```yaml
server:        # 服务元数据 + 传输模式
connection:    # 平台 API 连接 (base_url, api_key, timeout)
limits:        # 输出限制 (行数、超时)
tool_groups:   # 工具组开关 (true/false)
```

**优先级**: 环境变量 (`OMICSHUB_BASE_URL`) > `config.yaml` > 代码默认值

### tools.yaml

声明式工具注册表，记录每个工具的元数据（名称、描述、是否只读、是否需确认）。
当前作为文档和校验参考，运行时注册由 `tools/__init__.py` 的 `_GROUP_REGISTRY` 驱动。

## 扩展新工具组 (3 步)

### 1. 创建工具模块 `tools/<group>.py`

```python
"""<group> 工具"""

from fastmcp import FastMCP
from client.api_client import OmicHubAPIClient, OmicHubAPIError


def register(mcp: FastMCP, api: OmicHubAPIClient) -> None:

    @mcp.tool()
    async def omichub_<group>_<action>(param: str) -> dict:
        """工具描述（AI 助手看到的说明）。"""
        try:
            data = await api.get(f"/<endpoint>", params={"param": param})
            return {
                "success": True,
                "summary": "人类可读的摘要",
                "data": data,
                "next_steps": ["建议的后续操作"],
            }
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"失败: {e.detail}"}
```

### 2. 注册到 `tools/__init__.py`

```python
_GROUP_REGISTRY: dict[str, str] = {
    ...
    "<group>": "tools.<group>",  # 新增这行
}
```

### 3. 在 config.yaml 和 tools.yaml 中声明

```yaml
# config.yaml
tool_groups:
  <group>: true

# tools.yaml
groups:
  - id: <group>
    module: tools.<group>
    description: "..."
    tools:
      - name: omichub_<group>_<action>
        description: "..."
        read_only: true
```

## 扩展新 Resource

在 `resources/catalog.py` 的 `register()` 中添加:

```python
@mcp.resource("omichub://<domain>/<id>")
async def my_resource(id: str) -> str:
    """资源描述"""
    data = await api.get(f"/<endpoint>/{id}")
    return json.dumps(data, ensure_ascii=False, indent=2)
```

## 扩展新 Prompt

在 `prompts/workflows.py` 的 `register()` 中添加:

```python
@mcp.prompt()
def my_workflow(param: str = "default") -> str:
    """工作流描述"""
    return f"""引导文本...
1. 步骤一
2. 步骤二
"""
```

## 扩展平台 API 客户端

在 `client/api_client.py` 的 `OmicHubAPIClient` 类中添加方法:

```python
async def my_endpoint(self, param: str) -> dict:
    return await self.get("/my-endpoint", params={"param": param})
```

## 设计约定

| 约定 | 说明 |
|------|------|
| 工具命名 | `omichub_<group>_<action>`，全小写下划线 |
| 确认门 | 破坏性操作 (提交/取消/删除) 必须有 `user_confirmed: bool = False` 参数 |
| 返回格式 | `{"success": bool, "summary": str, "data": Any, "next_steps"?: list[str]}` |
| 错误处理 | 捕获 `OmicHubAPIError`，返回 `{"success": False, "summary": "..."}` |
| 文件大小 | `read_file_content` 最多 500 行，超出截断并标注 |
| 认证 | 所有请求通过 `X-API-Key` 头，由 `api_client.py` 统一注入 |

## 平台侧对应关系

| MCP 工具组 | 平台 API 路由 | 服务层 |
|-----------|-------------|--------|
| tasks | `/api/v1/tasks` | `TaskService` |
| flows | `/api/v1/flows` | `FlowService` |
| analysis | `/api/v1/tasks` (POST) | `TaskService.submit()` |
| downloads | `/api/v1/downloads` | `DownloadService` |
| files | `/api/v1/files` | `FileService` |
| reports | `/api/v1/reports` | `ReportService` |
| sandbox | `/api/v1/sandbox` | `SandboxService` |
| platform | `/api/v1/auth/me` + `/api/v1/stats` | — |

## 内部 Builtin Preset

平台内部 AI (Copilot/Studio) 通过 `src/omichub/infrastructure/mcp/presets.py` 中的
`omichub-platform` preset 获得相同能力（直接调用 application services，零网络开销）。

新增内部工具时同步更新 `PLATFORM_PRESET_TOOLS` 和 `PLATFORM_HANDLERS`。
