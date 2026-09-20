# CygnusX 沙箱增强实施方案：sandbox_tools

## 一、总体架构：与现有 Studio 的对接方式

```
┌─────────────────────────────────────────────────────────────────┐
│                        你的平台（控制平面）                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  Vue3 前端   │  │ FastAPI 后端 │  │  MCP Adapter (新增)      │  │
│  │  ToolPanel  │←→│  Studio API  │←→│  /api/v1/mcp/sandbox    │  │
│  └─────────────┘  │  JWT 鉴权    │  │  工具路由 + 审计日志       │  │
│                   │  Celery/Redis│  └─────────────────────────┘  │
│                   └──────┬──────┘              │                  │
│                          │  Unix Socket        │                  │
│                   ┌──────┴──────┐             │                  │
│                   │ Studio 会话  │             │                  │
│                   │ 编排管理器   │             │                  │
│                   └──────┬──────┘             │                  │
└──────────────────────────┼────────────────────┼──────────────────┘
                           │ 容器创建参数         │ 工具调用转发
                           │ (image/capability) │
              ┌────────────┴────────────┐       │
              │                         │       │
    ┌─────────▼──────────┐   ┌──────────▼───────┴──┐
    │ cygnusx-sandbox-   │   │ cygnusx-sandbox-    │
    │ bio (现有数据分析)  │   │ browser-office (新增)│
    │                    │   │                     │
    │ • Python/R/Bash    │   │ • Python/R/Bash     │
    │ • Bioinfo 工具链    │   │ • Chromium + Playwright
    │ • 只读平台目录      │   │ • LibreOffice (轻量) │
    │                    │   │ • sandbox-agent     │
    │ capability: code   │   │ capability: browser │
    └────────────────────┘   │          document   │
                             └─────────────────────┘
```

**核心设计原则**：

1. **不改造现有镜像**：`cygnusx-sandbox-bio` 保持原样，新增 `cygnusx-sandbox-browser-office` 独立镜像
2. **复用 Studio 编排**：会话创建、生命周期、网络策略、文件挂载全部复用 `StudioSandboxManager`
3. **Capability 授权**：创建会话时通过 `capability` 字段声明需要浏览器/文档能力，平台只分配对应镜像
4. **工具路由而非容器内 MCP**：AI 调用 `sandbox_tools` 时，请求先到平台 MCP Adapter，平台根据 capability 决定是否转发到 Studio 工具路由执行
5. **安全前置**：P0 安全基线（CPU quota、PID limit、cap_drop、no-new-privileges）必须在浏览器能力上线前完成

---

## 二、sandbox_tools MCP 工具集完整 Schema

命名空间：`sandbox_tools`（所有工具前缀均为 `sandbox_tools.`）

### 2.1 浏览器工具（Browser Tools）

```json
{
  "name": "sandbox_tools.browser_navigate",
  "description": "导航到指定 URL，返回页面文本摘要和可交互元素列表",
  "inputSchema": {
    "type": "object",
    "properties": {
      "url": {
        "type": "string",
        "description": "目标 URL，必须以 http:// 或 https:// 开头"
      },
      "wait_for": {
        "type": "string",
        "description": "等待加载完成的选择器",
        "default": "body"
      },
      "timeout": {
        "type": "integer",
        "description": "页面加载超时（秒）",
        "default": 30,
        "maximum": 120
      }
    },
    "required": ["url"]
  }
}
```

```json
{
  "name": "sandbox_tools.browser_screenshot",
  "description": "截取当前页面或指定元素的截图，返回 base64 编码的 PNG",
  "inputSchema": {
    "type": "object",
    "properties": {
      "selector": {
        "type": "string",
        "description": "CSS 选择器，为空则截取整个页面",
        "default": ""
      },
      "full_page": {
        "type": "boolean",
        "description": "是否截取完整页面（含滚动区域）",
        "default": false
      }
    }
  }
}
```

```json
{
  "name": "sandbox_tools.browser_click",
  "description": "点击页面上匹配选择器的元素",
  "inputSchema": {
    "type": "object",
    "properties": {
      "selector": {
        "type": "string",
        "description": "CSS 选择器"
      },
      "wait_for_navigation": {
        "type": "boolean",
        "description": "是否等待导航完成",
        "default": false
      },
      "timeout": {
        "type": "integer",
        "default": 10
      }
    },
    "required": ["selector"]
  }
}
```

```json
{
  "name": "sandbox_tools.browser_fill",
  "description": "在表单输入框中填写内容",
  "inputSchema": {
    "type": "object",
    "properties": {
      "selector": {
        "type": "string",
        "description": "input/textarea 的 CSS 选择器"
      },
      "value": {
        "type": "string",
        "description": "要填写的内容"
      }
    },
    "required": ["selector", "value"]
  }
}
```

```json
{
  "name": "sandbox_tools.browser_scroll",
  "description": "滚动页面",
  "inputSchema": {
    "type": "object",
    "properties": {
      "direction": {
        "type": "string",
        "enum": ["up", "down", "left", "right"],
        "description": "滚动方向"
      },
      "amount": {
        "type": "integer",
        "description": "滚动像素数",
        "default": 500
      }
    },
    "required": ["direction"]
  }
}
```

```json
{
  "name": "sandbox_tools.browser_evaluate",
  "description": "在页面上下文中执行 JavaScript 并返回结果",
  "inputSchema": {
    "type": "object",
    "properties": {
      "script": {
        "type": "string",
        "description": "要执行的 JavaScript 代码"
      }
    },
    "required": ["script"]
  }
}
```

```json
{
  "name": "sandbox_tools.browser_get_text",
  "description": "提取当前页面的可见文本内容",
  "inputSchema": {
    "type": "object",
    "properties": {
      "selector": {
        "type": "string",
        "description": "限制提取范围的选择器，为空则提取整个页面",
        "default": ""
      }
    }
  }
}
```

```json
{
  "name": "sandbox_tools.browser_download",
  "description": "下载页面上的文件到工作区",
  "inputSchema": {
    "type": "object",
    "properties": {
      "url": {
        "type": "string",
        "description": "文件下载链接"
      },
      "filename": {
        "type": "string",
        "description": "保存到工作区的文件名"
      }
    },
    "required": ["url", "filename"]
  }
}
```

### 2.2 文档工具（Document Tools）

```json
{
  "name": "sandbox_tools.document_create",
  "description": "创建新的 Office 文档（docx/xlsx/pptx）",
  "inputSchema": {
    "type": "object",
    "properties": {
      "type": {
        "type": "string",
        "enum": ["docx", "xlsx", "pptx"],
        "description": "文档类型"
      },
      "filename": {
        "type": "string",
        "description": "文件名，不含路径"
      },
      "content": {
        "type": "object",
        "description": "初始内容（可选）",
        "default": {}
      }
    },
    "required": ["type", "filename"]
  }
}
```

```json
{
  "name": "sandbox_tools.document_read",
  "description": "读取文档内容并返回结构化文本",
  "inputSchema": {
    "type": "object",
    "properties": {
      "filename": {
        "type": "string",
        "description": "工作区内的文件路径"
      },
      "sheet_name": {
        "type": "string",
        "description": "Excel 工作表名（仅 xlsx）",
        "default": ""
      }
    },
    "required": ["filename"]
  }
}
```

```json
{
  "name": "sandbox_tools.document_edit",
  "description": "编辑文档内容（替换/插入/删除/样式）",
  "inputSchema": {
    "type": "object",
    "properties": {
      "filename": {
        "type": "string",
        "description": "目标文档路径"
      },
      "operations": {
        "type": "array",
        "description": "编辑操作列表",
        "items": {
          "type": "object",
          "properties": {
            "action": {
              "type": "string",
              "enum": ["replace", "insert", "delete", "style", "append"],
              "description": "操作类型"
            },
            "target": {
              "type": "string",
              "description": "目标位置（段落索引、表格单元格、或搜索文本）"
            },
            "value": {
              "type": "string",
              "description": "新内容或样式定义"
            }
          },
          "required": ["action", "target"]
        }
      }
    },
    "required": ["filename", "operations"]
  }
}
```

```json
{
  "name": "sandbox_tools.document_convert",
  "description": "转换文档格式（如 docx → pdf）",
  "inputSchema": {
    "type": "object",
    "properties": {
      "input": {
        "type": "string",
        "description": "输入文件路径"
      },
      "output_format": {
        "type": "string",
        "enum": ["pdf", "txt", "html", "docx", "xlsx", "pptx"],
        "description": "输出格式"
      },
      "output_filename": {
        "type": "string",
        "description": "输出文件名（可选，默认同输入文件名改后缀）"
      }
    },
    "required": ["input", "output_format"]
  }
}
```

```json
{
  "name": "sandbox_tools.document_template_fill",
  "description": "基于模板批量生成文档（模板变量替换）",
  "inputSchema": {
    "type": "object",
    "properties": {
      "template": {
        "type": "string",
        "description": "模板文件路径（docx）"
      },
      "data": {
        "type": "object",
        "description": "变量映射表，如 {\"name\": \"张三\", \"date\": \"2026-08-23\"}"
      },
      "output_filename": {
        "type": "string",
        "description": "输出文件名"
      }
    },
    "required": ["template", "data", "output_filename"]
  }
}
```

### 2.3 文件与 Shell 工具（复用现有能力，标准化命名）

```json
{
  "name": "sandbox_tools.file_read",
  "description": "读取工作区文件内容",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "相对于 /workspace 的文件路径"
      },
      "offset": {
        "type": "integer",
        "default": 0
      },
      "limit": {
        "type": "integer",
        "default": 10000
      }
    },
    "required": ["path"]
  }
}
```

```json
{
  "name": "sandbox_tools.file_write",
  "description": "写入或覆盖工作区文件",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string"
      },
      "content": {
        "type": "string"
      }
    },
    "required": ["path", "content"]
  }
}
```

```json
{
  "name": "sandbox_tools.file_list",
  "description": "列出工作区目录内容",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "default": "."
      }
    }
  }
}
```

```json
{
  "name": "sandbox_tools.shell_exec",
  "description": "执行 shell 命令",
  "inputSchema": {
    "type": "object",
    "properties": {
      "command": {
        "type": "string",
        "description": "要执行的命令"
      },
      "timeout": {
        "type": "integer",
        "default": 60,
        "maximum": 600
      },
      "working_dir": {
        "type": "string",
        "default": "/workspace"
      }
    },
    "required": ["command"]
  }
}
```

### 2.4 会话管理工具

```json
{
  "name": "sandbox_tools.session_info",
  "description": "获取当前沙箱会话信息和可用能力",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

```json
{
  "name": "sandbox_tools.session_artifact",
  "description": "将工作区文件注册为产物，返回下载链接",
  "inputSchema": {
    "type": "object",
    "properties": {
      "filename": {
        "type": "string",
        "description": "要注册的文件路径"
      },
      "description": {
        "type": "string",
        "description": "产物描述"
      }
    },
    "required": ["filename"]
  }
}
```

---

## 三、平台侧代码实现

### 3.1 Studio 会话创建增强（Capability 模型）

```python
# src/cygnusx/api/v1/studio/schemas.py
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class SandboxCapability(str, Enum):
    CODE = "code"           # 代码执行（所有镜像都有）
    BROWSER = "browser"     # 浏览器自动化
    DOCUMENT = "document"   # 文档编辑/转换
    DESKTOP = "desktop"     # VNC 桌面可视化（未来）

class StudioSessionCreate(BaseModel):
    """创建 Studio 会话请求（增强版）"""
    name: Optional[str] = Field(default="Untitled Session")
    image_tag: Optional[str] = Field(
        default=None,
        description="指定镜像标签，如 'browser-office-v1.2'"
    )
    capabilities: List[SandboxCapability] = Field(
        default=[SandboxCapability.CODE],
        description="请求的会话能力，平台根据能力选择镜像"
    )
    network_mode: str = Field(
        default="none",
        description="网络模式: none | whitelist"
    )
    network_whitelist: Optional[List[str]] = Field(
        default=None,
        description="白名单域名列表（network_mode=whitelist 时生效）"
    )
    resources: Optional[dict] = Field(
        default=None,
        description="自定义资源限制，如 {'cpu': 2, 'memory': '4g', 'timeout': 600}"
    )
    workspace_init: Optional[List[dict]] = Field(
        default=None,
        description="初始化文件列表，如 [{'path': 'data.csv', 'content': '...'}]"
    )

class StudioSessionResponse(BaseModel):
    session_id: str
    status: str
    capabilities: List[SandboxCapability]
    image_used: str
    endpoints: dict  # 各能力端点
```

### 3.2 StudioSandboxManager 增强（安全基线 + Capability 路由）

```python
# src/cygnusx/services/studio/manager.py
import docker
import redis
import json
import os
from typing import List, Optional, Dict
from datetime import datetime, timedelta

from cygnusx.core.config import settings
from cygnusx.services.studio.schemas import SandboxCapability

# 镜像映射表：能力 -> 镜像
CAPABILITY_IMAGE_MAP = {
    (SandboxCapability.CODE,): "cygnusx-sandbox-bio:latest",
    (SandboxCapability.CODE, SandboxCapability.BROWSER): "cygnusx-sandbox-browser-office:latest",
    (SandboxCapability.CODE, SandboxCapability.BROWSER, SandboxCapability.DOCUMENT): "cygnusx-sandbox-browser-office:latest",
    # 未来可扩展
    (SandboxCapability.CODE, SandboxCapability.DESKTOP): "cygnusx-sandbox-desktop:latest",
}

class StudioSandboxManager:
    def __init__(self):
        self.docker = docker.from_env()
        self.redis = redis.Redis.from_url(settings.REDIS_URL)
        self.network_name = settings.STUDIO_NETWORK_NAME or "studio-sandbox-net"
    
    def _resolve_image(self, capabilities: List[SandboxCapability], requested_tag: Optional[str]) -> str:
        """根据请求的能力解析镜像"""
        if requested_tag:
            # 用户显式指定镜像，验证能力兼容
            # TODO: 增加镜像 capability 元数据校验
            return f"cygnusx-sandbox-{requested_tag}"
        
        # 按能力组合匹配镜像
        caps_tuple = tuple(sorted(set(capabilities)))
        if caps_tuple in CAPABILITY_IMAGE_MAP:
            return CAPABILITY_IMAGE_MAP[caps_tuple]
        
        # 默认回退到基础镜像
        return CAPABILITY_IMAGE_MAP[(SandboxCapability.CODE,)]
    
    def _build_security_opts(self, network_mode: str) -> Dict:
        """构建 Docker 安全选项（P0 基线）"""
        security_opts = [
            "no-new-privileges:true",
        ]
        
        # 资源硬限制
        ulimits = [
            docker.types.Ulimit(name="nproc", soft=1024, hard=2048),
            docker.types.Ulimit(name="nofile", soft=4096, hard=8192),
        ]
        
        # 容器能力：只保留必要能力，其余全部丢弃
        cap_drop = ["ALL"]
        cap_add = ["CHOWN", "SETGID", "SETUID"]  # sandbox-agent 运行所需最小集合
        
        # 如果启用浏览器，可能需要额外能力（需安全评审）
        # cap_add.append("SYS_ADMIN")  # Chromium sandbox 可能需要，建议用 --no-sandbox 替代
        
        return {
            "security_opt": security_opts,
            "cap_drop": cap_drop,
            "cap_add": cap_add,
            "ulimits": ulimits,
            "pids_limit": 512,  # 防止 fork 炸弹
            "read_only": True,  # 只读根文件系统
            "tmpfs": {
                "/tmp": "rw,noexec,nosuid,size=500m",
                "/var/tmp": "rw,noexec,nosuid,size=100m",
            },
        }
    
    async def create_session(
        self,
        user_id: str,
        name: str,
        capabilities: List[SandboxCapability],
        image_tag: Optional[str] = None,
        network_mode: str = "none",
        network_whitelist: Optional[List[str]] = None,
        resources: Optional[dict] = None,
    ) -> dict:
        """创建增强型 Studio 会话"""
        
        # 1. 解析镜像
        image = self._resolve_image(capabilities, image_tag)
        
        # 2. 资源限制
        default_resources = {
            "cpu_period": 100000,
            "cpu_quota": 200000,    # 2 核硬限制（替代 cpu_shares）
            "mem_limit": "4g",
            "memswap_limit": "4g",  # 禁用 swap
        }
        if resources:
            default_resources.update(resources)
        
        # 3. 网络配置
        if network_mode == "none":
            network_config = {"network_mode": "none"}
        elif network_mode == "whitelist":
            # 使用预配置的代理网络
            network_config = {
                "network": self.network_name,
                "environment": {
                    "HTTP_PROXY": settings.STUDIO_HTTP_PROXY,
                    "HTTPS_PROXY": settings.STUDIO_HTTPS_PROXY,
                    "NO_PROXY": "localhost,127.0.0.1",
                    "NETWORK_WHITELIST": ",".join(network_whitelist or []),
                }
            }
        else:
            raise ValueError(f"不支持的网络模式: {network_mode}")
        
        # 4. 卷挂载
        user_dir = f"{settings.STORAGE_PATH}/users/{user_id}"
        workspace_dir = f"{settings.STORAGE_PATH}/workspaces/{user_id}"
        os.makedirs(workspace_dir, exist_ok=True)
        
        volumes = {
            user_dir: {"bind": "/data/platform", "mode": "ro"},
            workspace_dir: {"bind": "/workspace", "mode": "rw"},
        }
        
        # 5. 安全选项
        security = self._build_security_opts(network_mode)
        
        # 6. 容器标签（用于审计和清理）
        labels = {
            "app": "cygnusx-studio",
            "user_id": user_id,
            "capabilities": ",".join(c.value for c in capabilities),
            "network_mode": network_mode,
            "created_at": datetime.utcnow().isoformat(),
        }
        
        # 7. 创建容器
        container = self.docker.containers.run(
            image=image,
            detach=True,
            name=f"studio-{user_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            labels=labels,
            volumes=volumes,
            **default_resources,
            **network_config,
            **security,
            environment={
                "SANDBOX_USER_ID": user_id,
                "SANDBOX_CAPABILITIES": ",".join(c.value for c in capabilities),
                "SANDBOX_TIMEOUT": str(default_resources.get("timeout", 600)),
                "WORKSPACE_DIR": "/workspace",
                "PLATFORM_DIR": "/data/platform",
            },
            stdout=True,
            stderr=True,
        )
        
        # 8. 记录到 Redis（活跃会话追踪）
        session_key = f"studio:sessions:{container.id[:12]}"
        self.redis.hset(session_key, mapping={
            "user_id": user_id,
            "container_id": container.id,
            "image": image,
            "capabilities": json.dumps([c.value for c in capabilities]),
            "network_mode": network_mode,
            "created_at": datetime.utcnow().isoformat(),
            "last_active": datetime.utcnow().timestamp(),
        })
        self.redis.zadd("studio:active_sessions", {container.id[:12]: datetime.utcnow().timestamp()})
        
        # 9. 返回会话信息
        endpoints = {
            "agent": f"unix:///var/run/docker.sock/.../studio-{container.id[:12]}.sock",  # 内部 UDS
            "files": f"/api/v1/studio/sessions/{container.id[:12]}/files",
            "run": f"/api/v1/studio/sessions/{container.id[:12]}/run",
        }
        
        if SandboxCapability.BROWSER in capabilities:
            endpoints["browser"] = f"/api/v1/studio/sessions/{container.id[:12]}/tools/browser"
        
        if SandboxCapability.DOCUMENT in capabilities:
            endpoints["document"] = f"/api/v1/studio/sessions/{container.id[:12]}/tools/document"
        
        return {
            "session_id": container.id[:12],
            "status": "running",
            "capabilities": [c.value for c in capabilities],
            "image_used": image,
            "endpoints": endpoints,
            "security": {
                "network_mode": network_mode,
                "cpu_quota": default_resources["cpu_quota"],
                "mem_limit": default_resources["mem_limit"],
                "pids_limit": security["pids_limit"],
                "read_only_root": security["read_only"],
            }
        }
    
    async def execute_tool(
        self,
        session_id: str,
        tool_name: str,
        params: dict,
        user_id: str
    ) -> dict:
        """执行沙箱工具（通过 sandbox-agent UDS）"""
        # 1. 验证会话归属
        session_key = f"studio:sessions:{session_id}"
        session_data = self.redis.hgetall(session_key)
        if not session_data or session_data.get(b"user_id").decode() != user_id:
            raise PermissionError("会话不存在或无权访问")
        
        # 2. 验证能力
        caps = json.loads(session_data.get(b"capabilities", b"[]").decode())
        capability_map = {
            "browser_navigate": "browser",
            "browser_screenshot": "browser",
            "browser_click": "browser",
            "browser_fill": "browser",
            "browser_scroll": "browser",
            "browser_evaluate": "browser",
            "browser_get_text": "browser",
            "browser_download": "browser",
            "document_create": "document",
            "document_read": "document",
            "document_edit": "document",
            "document_convert": "document",
            "document_template_fill": "document",
            "file_read": "code",
            "file_write": "code",
            "file_list": "code",
            "shell_exec": "code",
        }
        
        required_cap = capability_map.get(tool_name)
        if required_cap and required_cap not in caps:
            raise PermissionError(f"会话缺少能力: {required_cap}")
        
        # 3. 转发到 sandbox-agent
        # 实际实现：通过 UDS HTTP 调用容器内的 sandbox-agent
        # 这里简化展示
        result = await self._call_agent(session_id, tool_name, params)
        
        # 4. 更新活跃时间
        self.redis.zadd("studio:active_sessions", {session_id: datetime.utcnow().timestamp()})
        
        # 5. 审计日志
        await self._audit_log(session_id, user_id, tool_name, params, result)
        
        return result
    
    async def _call_agent(self, session_id: str, tool_name: str, params: dict) -> dict:
        """通过 UDS 调用 sandbox-agent"""
        import aiohttp
        
        # UDS 路径由 Docker volume 或 host path 映射
        uds_path = f"/var/run/cygnusx/studio/{session_id}/agent.sock"
        
        connector = aiohttp.UnixConnector(path=uds_path)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                "http://localhost/tools/execute",
                json={"tool": tool_name, "params": params},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                return await resp.json()
    
    async def _audit_log(self, session_id: str, user_id: str, tool: str, params: dict, result: dict):
        """记录审计日志"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "user_id": user_id,
            "tool": tool,
            "params": self._sanitize_params(tool, params),
            "success": result.get("success", False),
            "duration_ms": result.get("duration_ms", 0),
        }
        # 写入日志系统或消息队列
        # await log_service.write(log_entry)
        print(f"[AUDIT] {json.dumps(log_entry)}")
    
    def _sanitize_params(self, tool: str, params: dict) -> dict:
        """脱敏：隐藏敏感参数"""
        sensitive_tools = {"browser_fill", "shell_exec"}
        if tool in sensitive_tools and "value" in params:
            sanitized = params.copy()
            sanitized["value"] = "***"
            return sanitized
        return params
```

### 3.3 MCP Adapter（平台侧 MCP Server）

```python
# src/cygnusx/api/v1/mcp/sandbox_adapter.py
"""
sandbox_tools MCP Adapter
将外部 MCP 客户端的工具调用转换为 Studio 内部工具调用
"""

import asyncio
import json
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel,
)

from cygnusx.services.studio.manager import StudioSandboxManager
from cygnusx.core.security import verify_mcp_token  # 你需要实现

# 工具定义（与第二节 Schema 对应）
SANDBOX_TOOLS = [
    # === 浏览器工具 ===
    Tool(
        name="sandbox_tools.browser_navigate",
        description="导航到指定 URL，返回页面文本摘要",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "wait_for": {"type": "string", "default": "body"},
                "timeout": {"type": "integer", "default": 30}
            },
            "required": ["url"]
        }
    ),
    Tool(
        name="sandbox_tools.browser_screenshot",
        description="截取页面截图，返回 base64 PNG",
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "default": ""},
                "full_page": {"type": "boolean", "default": False}
            }
        }
    ),
    Tool(
        name="sandbox_tools.browser_click",
        description="点击页面元素",
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "wait_for_navigation": {"type": "boolean", "default": False},
                "timeout": {"type": "integer", "default": 10}
            },
            "required": ["selector"]
        }
    ),
    Tool(
        name="sandbox_tools.browser_fill",
        description="在表单中填写内容",
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "value": {"type": "string"}
            },
            "required": ["selector", "value"]
        }
    ),
    Tool(
        name="sandbox_tools.browser_scroll",
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
        name="sandbox_tools.browser_evaluate",
        description="执行 JavaScript",
        inputSchema={
            "type": "object",
            "properties": {
                "script": {"type": "string"}
            },
            "required": ["script"]
        }
    ),
    Tool(
        name="sandbox_tools.browser_get_text",
        description="提取页面文本",
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "default": ""}
            }
        }
    ),
    Tool(
        name="sandbox_tools.browser_download",
        description="下载文件到工作区",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "filename": {"type": "string"}
            },
            "required": ["url", "filename"]
        }
    ),
    # === 文档工具 ===
    Tool(
        name="sandbox_tools.document_create",
        description="创建 Office 文档",
        inputSchema={
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["docx", "xlsx", "pptx"]},
                "filename": {"type": "string"},
                "content": {"type": "object", "default": {}}
            },
            "required": ["type", "filename"]
        }
    ),
    Tool(
        name="sandbox_tools.document_read",
        description="读取文档内容",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "sheet_name": {"type": "string", "default": ""}
            },
            "required": ["filename"]
        }
    ),
    Tool(
        name="sandbox_tools.document_edit",
        description="编辑文档",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["replace", "insert", "delete", "style", "append"]},
                            "target": {"type": "string"},
                            "value": {"type": "string"}
                        },
                        "required": ["action", "target"]
                    }
                }
            },
            "required": ["filename", "operations"]
        }
    ),
    Tool(
        name="sandbox_tools.document_convert",
        description="转换文档格式",
        inputSchema={
            "type": "object",
            "properties": {
                "input": {"type": "string"},
                "output_format": {"type": "string", "enum": ["pdf", "txt", "html", "docx", "xlsx", "pptx"]},
                "output_filename": {"type": "string"}
            },
            "required": ["input", "output_format"]
        }
    ),
    Tool(
        name="sandbox_tools.document_template_fill",
        description="模板批量生成",
        inputSchema={
            "type": "object",
            "properties": {
                "template": {"type": "string"},
                "data": {"type": "object"},
                "output_filename": {"type": "string"}
            },
            "required": ["template", "data", "output_filename"]
        }
    ),
    # === 文件/Shell 工具 ===
    Tool(
        name="sandbox_tools.file_read",
        description="读取文件",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 10000}
            },
            "required": ["path"]
        }
    ),
    Tool(
        name="sandbox_tools.file_write",
        description="写入文件",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    ),
    Tool(
        name="sandbox_tools.file_list",
        description="列出目录",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."}
            }
        }
    ),
    Tool(
        name="sandbox_tools.shell_exec",
        description="执行命令",
        inputSchema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 60},
                "working_dir": {"type": "string", "default": "/workspace"}
            },
            "required": ["command"]
        }
    ),
    # === 会话工具 ===
    Tool(
        name="sandbox_tools.session_info",
        description="获取会话信息",
        inputSchema={"type": "object", "properties": {}}
    ),
    Tool(
        name="sandbox_tools.session_artifact",
        description="注册产物",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "description": {"type": "string"}
            },
            "required": ["filename"]
        }
    ),
]

class SandboxMCPAdapter:
    """sandbox_tools MCP 适配器"""
    
    def __init__(self):
        self.server = Server("sandbox_tools")
        self.manager = StudioSandboxManager()
        self.active_sessions: Dict[str, str] = {}  # mcp_session -> studio_session_id
        
        self._register_handlers()
    
    def _register_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return SANDBOX_TOOLS
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[Any]:
            # 解析工具名
            if not name.startswith("sandbox_tools."):
                return [TextContent(type="text", text=f"未知工具命名空间: {name}")]
            
            tool_name = name.replace("sandbox_tools.", "")
            
            # 获取当前绑定的 Studio 会话
            studio_session_id = self._get_current_session()
            if not studio_session_id:
                return [TextContent(type="text", text="错误: 未绑定 Studio 会话。请先创建会话。")]
            
            # 转发到 Studio 执行
            try:
                result = await self.manager.execute_tool(
                    session_id=studio_session_id,
                    tool_name=tool_name,
                    params=arguments,
                    user_id=self._get_current_user()  # 从 MCP 上下文获取
                )
                
                # 格式化返回
                if tool_name == "browser_screenshot" and result.get("screenshot"):
                    return [ImageContent(
                        type="image",
                        data=result["screenshot"],
                        mimeType="image/png"
                    )]
                
                return [TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, indent=2)
                )]
                
            except PermissionError as e:
                return [TextContent(type="text", text=f"权限错误: {str(e)}")]
            except Exception as e:
                return [TextContent(type="text", text=f"执行错误: {str(e)}")]
    
    def _get_current_session(self) -> Optional[str]:
        """从 MCP 会话上下文获取绑定的 Studio 会话 ID"""
        # 实际实现：通过 MCP session metadata 或请求头传递
        return getattr(self, "_current_studio_session", None)
    
    def _get_current_user(self) -> str:
        """获取当前用户 ID"""
        return getattr(self, "_current_user_id", "anonymous")
    
    async def bind_session(self, studio_session_id: str, user_id: str):
        """绑定 Studio 会话到 MCP 会话"""
        self._current_studio_session = studio_session_id
        self._current_user_id = user_id
    
    async def run(self):
        """运行 MCP Server"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="sandbox_tools",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities()
                )
            )


# FastAPI 路由：暴露 MCP 端点
# src/cygnusx/api/v1/mcp/router.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from cygnusx.core.auth import get_current_user
from cygnusx.services.studio.manager import StudioSandboxManager
from cygnusx.api.v1.mcp.sandbox_adapter import SandboxMCPAdapter

router = APIRouter(prefix="/mcp", tags=["MCP"])

@router.post("/sandbox/sessions")
async def create_mcp_sandbox_session(
    request: dict,
    user_id: str = Depends(get_current_user)
):
    """
    创建绑定到 MCP 的 Studio 会话
    请求体: {
        "capabilities": ["code", "browser", "document"],
        "network_mode": "whitelist",
        "network_whitelist": ["example.com", "api.github.com"]
    }
    """
    manager = StudioSandboxManager()
    
    # 创建会话
    session = await manager.create_session(
        user_id=user_id,
        name=request.get("name", "MCP Sandbox Session"),
        capabilities=request.get("capabilities", ["code"]),
        network_mode=request.get("network_mode", "none"),
        network_whitelist=request.get("network_whitelist"),
        resources=request.get("resources")
    )
    
    return {
        "session_id": session["session_id"],
        "capabilities": session["capabilities"],
        "mcp_endpoint": f"/api/v1/mcp/sandbox/{session['session_id']}/stream",
        "endpoints": session["endpoints"]
    }

@router.get("/sandbox/{session_id}/stream")
async def mcp_sandbox_stream(
    session_id: str,
    user_id: str = Depends(get_current_user)
):
    """
    MCP Server-Sent Events 端点
    客户端通过 SSE 接收 MCP 消息
    """
    # 验证会话归属
    manager = StudioSandboxManager()
    # ... 验证逻辑 ...
    
    adapter = SandboxMCPAdapter()
    await adapter.bind_session(session_id, user_id)
    
    # 返回 SSE 流
    async def event_stream():
        # MCP 消息流
        async for message in adapter.message_stream():
            yield f"data: {json.dumps(message)}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

---

## 四、独立能力镜像 Dockerfile

```dockerfile
# deploy/studio/Dockerfile.browser-office
# cygnusx-sandbox-browser-office:latest

# =============================================================================
# 阶段 1：基础层（复用现有 bio 镜像的基础）
# =============================================================================
FROM cygnusx-sandbox-bio:latest AS base

# =============================================================================
# 阶段 2：浏览器层
# =============================================================================
FROM base AS browser-layer

USER root

# 安装 Chromium 和依赖（Debian/Ubuntu）
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    xdg-utils \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 Playwright Python 依赖
RUN pip install --no-cache-dir playwright==1.45.0 && \
    playwright install chromium

# Playwright 缓存清理（减小镜像体积）
RUN rm -rf /root/.cache/ms-playwright/ffmpeg-* \
    /root/.cache/ms-playwright/webkit-* \
    /root/.cache/ms-playwright/firefox-*

# =============================================================================
# 阶段 3：文档处理层
# =============================================================================
FROM browser-layer AS document-layer

# 轻量文档处理：python-docx + openpyxl + python-pptx + LibreOffice
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    libreoffice-common \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN pip install --no-cache-dir \
    python-docx==1.1.2 \
    openpyxl==3.1.5 \
    python-pptx==1.0.2 \
    pdf2image==1.17.0 \
    Pillow==10.4.0

# =============================================================================
# 阶段 4：Sandbox Agent 增强
# =============================================================================
FROM document-layer AS final

# 复制增强版 sandbox-agent（支持 browser/document 工具）
COPY studio/agent-enhanced.py /app/sandbox-agent.py
COPY studio/tools/ /app/tools/

# 工具路由配置
COPY studio/tool_schemas.json /app/config/tool_schemas.json

# 启动脚本
COPY studio/start-browser-office.sh /app/start.sh
RUN chmod +x /app/start.sh

# 创建必要的可写目录（因为根文件系统是只读的）
RUN mkdir -p /tmp/chromium /tmp/downloads /workspace /var/tmp && \
    chmod 1777 /tmp /var/tmp

# 非 root 用户运行（安全加固）
RUN useradd -m -s /bin/bash sandbox && \
    chown -R sandbox:sandbox /workspace /tmp/chromium /tmp/downloads
USER sandbox

ENV CHROME_BIN=/usr/bin/chromium \
    CHROMIUM_FLAGS="--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage --disable-gpu --disable-web-security" \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright \
    PYTHONPATH=/app

EXPOSE 8080

CMD ["/app/start.sh"]
```

```bash
#!/bin/bash
# studio/start-browser-office.sh

set -e

# 启动 sandbox-agent（增强版，监听 UDS）
python /app/sandbox-agent.py \
    --socket-path /tmp/agent.sock \
    --tools-dir /app/tools \
    --workspace /workspace \
    --capabilities "${SANDBOX_CAPABILITIES:-code}" &

AGENT_PID=$!

# 启动 Chromium 调试端口（仅 browser 能力时）
if [[ "${SANDBOX_CAPABILITIES}" == *"browser"* ]]; then
    # 预启动 Chromium 以加速首次导航
    chromium ${CHROMIUM_FLAGS} \
        --remote-debugging-port=9222 \
        --user-data-dir=/tmp/chromium \
        --headless=new \
        --window-size=1280,800 \
        about:blank &
    CHROME_PID=$!
fi

# 健康检查
healthcheck() {
    while true; do
        if ! kill -0 $AGENT_PID 2>/dev/null; then
            echo "Agent 进程已退出，容器终止"
            exit 1
        fi
        sleep 10
    done
}

healthcheck &
wait $AGENT_PID
```

---

## 五、前端能力开关（Vue3）

```typescript
// frontend/src/composables/useStudioCapabilities.ts
import { ref, computed } from 'vue';
import { useStudioStore } from '@/stores/studio';

export interface SandboxCapabilities {
  code: boolean;
  browser: boolean;
  document: boolean;
  desktop: boolean;
}

export function useStudioCapabilities() {
  const store = useStudioStore();
  
  const capabilities = computed<SandboxCapabilities>(() => {
    const caps = store.currentSession?.capabilities || ['code'];
    return {
      code: caps.includes('code'),
      browser: caps.includes('browser'),
      document: caps.includes('document'),
      desktop: caps.includes('desktop'),
    };
  });

  const hasCapability = (cap: keyof SandboxCapabilities) => capabilities.value[cap];

  return {
    capabilities,
    hasCapability,
  };
}
```

```vue
<!-- frontend/src/components/Studio/ToolPanel.vue -->
<template>
  <div class="tool-panel">
    <!-- 浏览器工具栏 -->
    <BrowserToolbar
      v-if="hasCapability('browser')"
      :session-id="sessionId"
      @navigate="handleBrowserNavigate"
      @screenshot="handleBrowserScreenshot"
      @click="handleBrowserClick"
      @fill="handleBrowserFill"
    />
    
    <!-- 文档工具栏 -->
    <DocumentToolbar
      v-if="hasCapability('document')"
      :session-id="sessionId"
      @create="handleDocumentCreate"
      @convert="handleDocumentConvert"
      @template-fill="handleTemplateFill"
    />
    
    <!-- 文件浏览器（已有） -->
    <FileExplorer :session-id="sessionId" />
    
    <!-- 代码编辑器（已有） -->
    <CodeEditor :session-id="sessionId" />
  </div>
</template>

<script setup lang="ts">
import { useStudioCapabilities } from '@/composables/useStudioCapabilities';

const props = defineProps<{ sessionId: string }>();
const { hasCapability } = useStudioCapabilities();

// Browser 工具调用
async function handleBrowserNavigate(url: string) {
  await callTool('sandbox_tools.browser_navigate', { url });
}

async function handleBrowserScreenshot(selector?: string) {
  const result = await callTool('sandbox_tools.browser_screenshot', { 
    selector: selector || '',
    full_page: !selector 
  });
  // result 中包含 base64 截图，展示在预览区
  previewStore.setImage(result.screenshot);
}

async function handleBrowserClick(selector: string) {
  await callTool('sandbox_tools.browser_click', { selector });
}

async function handleBrowserFill(payload: { selector: string; value: string }) {
  await callTool('sandbox_tools.browser_fill', payload);
}

// Document 工具调用
async function handleDocumentCreate(type: 'docx' | 'xlsx' | 'pptx') {
  const filename = `new_document.${type}`;
  await callTool('sandbox_tools.document_create', { type, filename });
  fileStore.refresh();
}

async function handleDocumentConvert(input: string, format: string) {
  await callTool('sandbox_tools.document_convert', { 
    input, 
    output_format: format 
  });
  fileStore.refresh();
}

async function handleTemplateFill(template: string, data: Record<string, string>) {
  await callTool('sandbox_tools.document_template_fill', {
    template,
    data,
    output_filename: `filled_${Date.now()}.docx`
  });
  fileStore.refresh();
}

// 通用工具调用封装
async function callTool(tool: string, params: Record<string, any>) {
  // 通过 SSE 或 WebSocket 发送到后端
  return await studioApi.callTool(props.sessionId, tool, params);
}
</script>
```

```vue
<!-- frontend/src/components/Studio/BrowserToolbar.vue -->
<template>
  <div class="browser-toolbar">
    <div class="url-bar">
      <input 
        v-model="url" 
        placeholder="输入 URL..."
        @keyup.enter="emit('navigate', url)"
      />
      <button @click="emit('navigate', url)">导航</button>
      <button @click="emit('screenshot')">截图</button>
    </div>
    
    <div class="browser-actions">
      <button @click="emit('scroll', { direction: 'up', amount: 500 })">↑</button>
      <button @click="emit('scroll', { direction: 'down', amount: 500 })">↓</button>
      <button @click="showClickModal = true">点击元素</button>
      <button @click="showFillModal = true">填写表单</button>
    </div>
    
    <!-- 截图预览区 -->
    <div v-if="screenshot" class="screenshot-preview">
      <img :src="`data:image/png;base64,${screenshot}`" />
    </div>
  </div>
</template>
```

---

## 六、实施路线图（修订版）

### Phase 0：安全基线（2 周）—— 浏览器能力上线的前置条件

| 任务 | 代码位置 | 验收标准 |
|------|---------|---------|
| Studio 容器创建加入硬 CPU quota | `manager.py` `create_session()` | `cpu_quota` 生效，单容器 CPU 不超过 200% |
| 加入 PID limit (512)、cap_drop ALL、no-new-privileges | `manager.py` `_build_security_opts()` | `docker inspect` 验证参数 |
| 根文件系统只读 + tmpfs | `manager.py` | 容器内 `touch /etc/test` 失败，`touch /tmp/test` 成功 |
| 网络模式端到端测试 | 测试用例 | `none` 模式无外网；`whitelist` 仅允许名单域名 |
| 审计日志覆盖工具调用 | `_audit_log()` | 每条工具调用记录用户、会话、工具、结果 |

### Phase 1：浏览器能力 MVP（3 周）

| 周次 | 任务 | 产出 |
|------|------|------|
| W1 | 构建 `cygnusx-sandbox-browser-office` 镜像 | Dockerfile、镜像构建 CI |
| W2 | 实现 sandbox-agent 浏览器工具（Playwright） | `tools/browser.py`、UDS 接口测试 |
| W3 | 平台侧 MCP Adapter + 前端 BrowserToolbar | `/api/v1/mcp/sandbox/*`、Vue 组件 |

### Phase 2：文档能力（2 周）

| 周次 | 任务 | 产出 |
|------|------|------|
| W4 | 文档工具实现（python-docx/openpyxl/LibreOffice） | `tools/document.py` |
| W5 | 前端 DocumentToolbar + 模板功能 | Vue 组件、模板示例 |

### Phase 3：灰度与优化（2 周）

- 种子用户测试（5-10 人）
- 性能调优（镜像预热、Chromium 复用）
- 安全渗透测试

---

## 七、关键设计决策总结

| 决策 | 选择 | 理由 |
|------|------|------|
| **镜像策略** | 独立 `browser-office` 镜像，不改造 `bio` | 避免所有会话承担浏览器攻击面和体积 |
| **工具协议** | Studio UDS 路由，非容器内 MCP Server | 复用现有鉴权、审计、生命周期管理 |
| **MCP 位置** | 平台侧 Adapter，非沙箱内 | 密钥不过沙箱边界，符合审计要求 |
| **文档方案** | LibreOffice Headless + python-docx | 轻量、无需常驻 OnlyOffice 服务 |
| **安全前置** | P0 基线必须先完成 | Docker 不是 VM，浏览器能力扩大攻击面 |
\\