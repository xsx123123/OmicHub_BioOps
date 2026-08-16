# 模块 09：AI Copilot 与交互式代码执行沙盒 架构设计

> **版本**: v1.0  
> **状态**: 架构设计阶段  
> **关联模块**: 前端(Vue3)、FastAPI主服务、MCP Client、Docker基础设施  
> **设计目标**: 提供类似 Claude Artifacts 的 AI 生成代码 → 交互式编辑 → 沙盒执行 → 实时渲染的闭环体验

---

## 目录

1. [系统架构总览](#1-系统架构总览)
2. [模块整体架构图](#图1模块整体架构图)
3. [代码执行数据流图](#图2代码执行数据流图)
4. [沙盒会话生命周期状态图](#图3沙盒会话生命周期状态图)
5. [组件详细设计](#2-组件详细设计)
6. [WebSocket 事件协议](#3-websocket-事件协议)
7. [数据库表设计](#4-数据库表设计)
8. [关键接口定义](#5-关键接口定义)
9. [安全设计](#6-安全设计)
10. [部署与运维](#7-部署与运维)
11. [性能与扩展性考量](#8-性能与扩展性考量)

---

## 1. 系统架构总览

### 1.1 设计哲学

本模块遵循 **"AI 生成即服务，执行即沙盒，结果即响应"** 的架构哲学：

- **Artifact 为中心**: 所有 AI 生成的代码以 Artifact（制品）为一级实体，关联代码、元数据、执行记录、结果输出
- **无状态服务 + 有状态沙盒**: Copilot Service 与 Sandbox Orchestrator 保持无状态，沙盒容器承载有状态的 Kernel 执行环境
- **流式一切**: 从 AI 思考步骤到代码生成，从 stdout 到图表渲染，全部流式传输
- **极速响应**: 容器预热池、镜像分层、连接复用，目标代码提交到首次输出 < 2 秒

### 1.2 架构分层

```
┌─────────────────────────────────────────────────────────────────┐
│                     用户交互层 (Browser)                          │
│  ┌─────────────────┐  ┌──────────────────────┐  ┌─────────────┐ │
│  │ Copilot对话面板  │  │   Artifact工作台      │  │ 主工作区     │ │
│  │  (Vue3 380px)   │  │ (Monaco+结果渲染)     │  │ (ECharts)   │ │
│  └────────┬────────┘  └──────────┬───────────┘  └──────┬──────┘ │
│           │ WebSocket            │ WebSocket           │        │
└───────────┼──────────────────────┼─────────────────────┼────────┘
            │                      │                     │
┌───────────▼──────────────────────▼─────────────────────▼────────┐
│                   API 网关层 (Nginx/FastAPI)                     │
│              路由 / 认证 / 限流 / WebSocket 代理                  │
└───────────┬──────────────────────┬─────────────────────┬────────┘
            │                      │                     │
┌───────────▼──────────────────────▼─────────────────────▼────────┐
│                   服务层 (FastAPI)                               │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ │
│  │  Copilot Service  │ │ Sandbox          │ │ Main Web Service │ │
│  │  (Agent Router +  │ │ Orchestrator     │ │ (已有)           │ │
│  │   Code Generator +│ │ (Pool + Engine + │ │                  │ │
│  │   Artifact Mgr)   │ │  Result Coll.)   │ │                  │ │
│  └────────┬─────────┘ └────────┬─────────┘ └──────────────────┘ │
│           │                    │                                  │
│           │         ┌──────────▼──────────┐                      │
│           │         │    MCP Client       │                      │
│           │         │  (Workflow Server)  │                      │
│           │         └──────────┬──────────┘                      │
└───────────┼────────────────────┼──────────────────────────────────┘
            │                    │
┌───────────▼────────────────────▼──────────────────────────────────┐
│                   沙盒集群 (Docker)                                │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐  │
│  │   Sandbox Pool       │  │   Image Registry                 │  │
│  │  ┌────────────────┐  │  │  ├─ omicshub/sandbox-base        │  │
│  │  │ sandbox-{sid}  │  │  │  ├─ omicshub/sandbox-{user}     │  │
│  │  │ ┌────────────┐ │  │  │  └─ omicshub/snf-worker         │  │
│  │  │ │Jupyter     │ │  │  └──────────────────────────────────┘  │
│  │  │ │Kernel      │ │  │                                        │
│  │  │ └────────────┘ │  │  ┌──────────────────────────────────┐  │
│  │  │ ┌────────────┐ │  │  │   Data Volumes                   │  │
│  │  │ │Bioinfo     │ │  │  │  ├─ /data/users/{user_id}        │  │
│  │  │ │Toolchain   │ │  │  │  ├─ /tmp/execution/{session_id}  │  │
│  │  │ └────────────┘ │  │  │  └─ /shared/ref-genomes          │  │
│  │  │ ┌────────────┐ │  │  └──────────────────────────────────┘  │
│  │  │ │Mounted     │ │  │                                        │
│  │  │ │Data Volumes│ │  │  ┌──────────────────────────────────┐  │
│  │  │ └────────────┘ │  │  │   Redis / PostgreSQL             │  │
│  │  └────────────────┘  │  │  ├─ Session State                │  │
│  │  ┌────────────────┐  │  │  ├─ Execution Cache               │  │
│  │  │ sandbox-{sid2} │  │  │  ├─ Artifact Storage             │  │
│  │  │   ...          │  │  │  └─ Celery Task Queue            │  │
│  │  └────────────────┘  │  └──────────────────────────────────┘  │
│  └──────────────────────┘                                          │
└────────────────────────────────────────────────────────────────────┘
```

---

## 图1：模块整体架构图

```mermaid
graph TB
    subgraph "用户浏览器"
        direction TB
        A1["Copilot 对话面板<br/>Vue3 / 380px 侧边栏"]
        A2["Artifact 工作台<br/>Monaco Editor + 结果面板"]
        A3["主工作区<br/>任务管理 / ECharts 渲染"]

        subgraph "对话面板内部"
            A1 --> M1["对话消息流<br/>Markdown + 代码块高亮"]
            A1 --> M2["MCP 工具调用卡片<br/>流程调度状态展示"]
            A1 --> M3["Agent Thinking 步骤<br/>流式显示推理过程"]
        end

        subgraph "Artifact 工作台内部"
            A2 --> M4["代码编辑器<br/>Monaco Editor / LSP"]
            A2 --> M5["执行控制栏<br/>Run / Stop / Install"]
            A2 --> M6["结果渲染区<br/>ECharts / Plotly / DataFrame"]
        end
    end

    subgraph "FastAPI 后端服务"
        direction TB
        B1["Copilot Service<br/>新服务"]
        B2["Sandbox Orchestrator<br/>新服务"]
        B3["Main Web Service<br/>已有"]
        B4["MCP Client<br/>已有"]

        subgraph "Copilot Service 内部"
            B1 --> S1["Agent Router<br/>意图识别与路由"]
            B1 --> S2["Code Generator<br/>LLM 代码生成 / 流式输出"]
            B1 --> S3["Artifact Manager<br/>Artifact CRUD / 版本管理"]
            B1 --> S4["Session Manager<br/>沙盒会话生命周期管理"]
        end

        subgraph "Sandbox Orchestrator 内部"
            B2 --> T1["Sandbox Pool<br/>容器池管理 / 预热 / 回收"]
            B2 --> T2["Kernel Manager<br/>Jupyter Kernel 生命周期"]
            B2 --> T3["Execution Engine<br/>代码执行调度 / 超时控制"]
            B2 --> T4["Result Collector<br/>结果收集与序列化"]
        end

        subgraph "MCP Client 内部"
            B4 --> U1["Snakemake MCP Server<br/>流程调度"]
            B4 --> U2["Nextflow MCP Server<br/>流程调度"]
            B4 --> U3["File MCP Server<br/>文件操作"]
        end
    end

    subgraph "数据持久化层"
        D1["PostgreSQL<br/>artifacts / sessions / executions"]
        D2["Redis<br/>session state / cache / locks"]
        D3["对象存储<br/>MinIO / S3<br/>执行输出图表/文件"]
    end

    subgraph "沙盒集群 Docker"
        direction TB
        E0["镜像仓库"]
        E0 --> E1["omicshub/sandbox-base:latest<br/>基础生信镜像"]
        E0 --> E2["omicshub/sandbox-{user}:latest<br/>用户自定义镜像"]

        E3["sandbox-{session_id}<br/>用户会话容器"]
        E4["sandbox-{session_id2}<br/>用户会话容器"]

        subgraph "单个沙盒容器内部"
            E3 --> F1["Jupyter Kernel<br/>IPython / IRkernel"]
            E3 --> F2["预装工具链<br/>Scanpy / Seurat / Bioconda"]
            E3 --> F3["数据卷挂载<br/>/data/user_{id}/ :ro"]
            E3 --> F4["临时执行空间<br/>/tmp/execution/ :rw"]
            E3 --> F5["Conda/Pip 持久化层<br/>用户包安装持久化"]
        end
    end

    A1 <-->|"WebSocket<br/>流式通信"| B1
    A2 <-->|"WebSocket<br/>代码/执行/结果"| B1
    B1 -->|"HTTP/gRPC<br/>调度指令"| B2
    B1 -->|"HTTP<br/>MCP 调用"| B4
    B2 -->|"Docker API<br/>容器 CRUD"| E3
    B2 -->|"ZMQ/HTTP<br/>Kernel 通信"| F1
    B2 -->|"HTTP<br/>结果上传"| D3
    S3 -.->|"SQLAlchemy<br/>Artifact 存储"| D1
    S4 -.->|"Redis<br/>Session 状态"| D2
    T4 -.->|"SQLAlchemy<br/>Execution 记录"| D1
    T1 -.->|"查询镜像"| E0

    style A2 fill:#e1f5fe,stroke:#01579b
    style B1 fill:#e8f5e9,stroke:#1b5e20
    style B2 fill:#e8f5e9,stroke:#1b5e20
    style E3 fill:#fff3e0,stroke:#e65100
    style F1 fill:#fce4ec,stroke:#880e4f
```

---

## 图2：代码执行数据流图

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant Frontend as 前端 Vue3
    participant CopilotWS as Copilot WebSocket
    participant Agent as Agent Router
    participant CodeGen as Code Generator
    participant LLM as Kimi API
    participant ArtMgr as Artifact Manager
    participant SandboxSvc as Sandbox Orchestrator
    participant Pool as Sandbox Pool
    participant Kernel as Jupyter Kernel
    participant ResultColl as Result Collector
    participant DB as PostgreSQL
    participant Redis as Redis

    User->>+Frontend: 输入："帮我做一个UMAP可视化"
    Frontend->>+CopilotWS: copilot.message (WebSocket)
    CopilotWS->>+Agent: 路由分析用户意图
    Agent->>Agent: 意图识别：code_generation
    Agent->>+CodeGen: 请求生成代码
    CodeGen->>+LLM: 发送 prompt（含上下文）

    Note over LLM,CodeGen: 流式代码生成
    loop 流式 token 返回
        LLM-->>CodeGen: token chunk
        CodeGen-->>CopilotWS: copilot.thinking_step
        CopilotWS-->>Frontend: 显示思考步骤
    end
    LLM-->>-CodeGen: 完整代码 + metadata

    CodeGen->>+ArtMgr: create_artifact(code, title, lang)
    ArtMgr->>DB: INSERT artifacts
    ArtMgr-->>-CodeGen: artifact_id

    CodeGen-->>CopilotWS: copilot.artifact_create
    CopilotWS-->>Frontend: 渲染 Artifact 工作台
    Frontend-->>User: 展示 Monaco 编辑器 + 代码

    User->>Frontend: 编辑代码（可选）
    Frontend->>CopilotWS: copilot.artifact_update
    CopilotWS->>ArtMgr: update_artifact
    ArtMgr->>DB: UPDATE artifacts

    User->>Frontend: 点击 Run 执行
    Frontend->>CopilotWS: copilot.artifact_execute
    CopilotWS->>+SandboxSvc: execute_code(session_id, code)

    SandboxSvc->>+Pool: get_or_create_sandbox(user_id)
    Pool->>Pool: 检查预热池 / 创建新容器
    Pool-->>-SandboxSvc: sandbox container ref

    SandboxSvc->>SandboxSvc: 建立 Kernel 连接
    SandboxSvc->>+Kernel: execute_request(code)

    Note over Kernel,SandboxSvc: 代码执行中
    Kernel-->>SandboxSvc: stream: stdout chunk
    SandboxSvc-->>CopilotWS: sandbox.output_stream
    CopilotWS-->>Frontend: 实时显示输出

    alt 生成图表
        Kernel-->>SandboxSvc: display_data: image/png
        SandboxSvc->>+ResultColl: collect_display_data(data)
        ResultColl->>ResultColl: 序列化为 JSON/PNG
        ResultColl->>DB: INSERT execution_outputs
        ResultColl-->>-SandboxSvc: serialized_result
        SandboxSvc-->>CopilotWS: copilot.artifact_result
        CopilotWS-->>Frontend: 渲染 ECharts/Plotly 图表
    else 输出表格
        Kernel-->>SandboxSvc: display_data: dataframe
        SandboxSvc->>ResultColl: collect_dataframe(df)
        ResultColl-->>CopilotWS: copilot.artifact_result
        CopilotWS-->>Frontend: 渲染交互式表格
    else 输出错误
        Kernel-->>SandboxSvc: error: traceback
        SandboxSvc-->>CopilotWS: copilot.artifact_error
        CopilotWS-->>Frontend: 显示错误信息 + Traceback
    end

    Kernel-->>-SandboxSvc: execute_reply (完成)
    SandboxSvc->>DB: UPDATE executions SET status=done
    SandboxSvc->>Redis: 更新会话状态 idle
    SandboxSvc-->>-CopilotWS: sandbox.execution_complete
    CopilotWS-->>-Frontend: 执行完成，显示结果汇总
    Frontend-->>User: 查看/下载结果
```

---

## 图3：沙盒会话生命周期状态图

```mermaid
stateDiagram-v2
    [*] --> creating: SessionManager.create_session()
    creating --> ready: 容器启动完成<br/>Kernel 连接成功
    creating --> failed: 容器启动失败<br/>超时 / 镜像错误
    failed --> [*]: 清理资源<br/>释放配额

    ready --> executing: ExecutionEngine.submit_code()
    executing --> idle: 执行完成<br/>正常结束
    executing --> executing: 新代码提交<br/>（队列执行）
    executing --> error: 执行错误<br/>Kernel 崩溃

    idle --> executing: 新代码提交
    idle --> paused: 心跳超时<br/>10分钟无活动
    idle --> saving: 用户请求<br/>保存镜像

    paused --> ready: 心跳恢复<br/>预热线程唤醒
    paused --> destroyed: 超时回收<br/>30分钟无活动

    saving --> idle: 镜像保存完成
    saving --> error: 保存失败<br/>存储空间不足

    error --> ready: Kernel 重启成功
    error --> destroyed: 连续重启失败<br/>3次

    ready --> destroyed: SessionManager.destroy_session()
    idle --> destroyed: 用户主动关闭
    destroyed --> [*]: 容器删除<br/>资源释放

    note right of creating
        容器创建阶段：
        - Docker create & start
        - 健康检查探针
        - Kernel 连接建立
        - 挂载数据卷
        超时：60秒
    end note

    note right of executing
        执行阶段约束：
        - 默认超时：5分钟
        - 最大并发：1（单 Kernel）
        - 队列深度：10
        - 资源监控：CPU/内存
    end note

    note left of paused
        暂停阶段：
        - 容器不停止，
          回收 CPU 份额
        - 保留内存状态
        - 预热池候选
    end note

    note right of destroyed
        销毁阶段：
        - 优雅关闭 Kernel
        - 保存执行历史到 DB
        - 删除临时卷
        - 释放池配额
        - 异步镜像 GC
    end note
```

---

## 2. 组件详细设计

### 2.1 Copilot Service（FastAPI 子模块）

```python
# app/copilot/__init__.py
"""Copilot Service - AI Copilot 与 Artifact 管理主模块

职责：
- Agent 意图识别与路由
- LLM 代码生成（流式）
- Artifact 生命周期管理（CRUD + 版本）
- 沙盒会话管理（创建/回收/心跳）
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, Dict, List, Any
from datetime import datetime
import uuid
import asyncio
from pydantic import BaseModel, Field


# ──────────────────────────────
# 领域模型 (Pydantic)
# ──────────────────────────────

class IntentType(str, Enum):
    """用户意图类型"""
    CHAT = "chat"              # 闲聊/咨询
    CODE_GENERATION = "code_generation"   # 代码生成请求
    CODE_EXPLANATION = "code_explanation" # 代码解释
    WORKFLOW_SCHEDULE = "workflow_schedule" # 流程调度（MCP）
    DATA_ANALYSIS = "data_analysis"       # 数据分析请求
    EXECUTE = "execute"        # 执行已有代码
    DEBUG = "debug"            # 调试请求
    GENERAL = "general"        # 通用（需进一步识别）


class ArtifactLanguage(str, Enum):
    """Artifact 支持的编程语言"""
    PYTHON = "python"
    R = "r"
    BASH = "bash"
    SQL = "sql"
    JULIA = "julia"


class ArtifactStatus(str, Enum):
    """Artifact 状态"""
    DRAFT = "draft"           # 草稿（AI 生成中）
    EDITING = "editing"       # 用户编辑中
    EXECUTING = "executing"   # 执行中
    SUCCESS = "success"       # 执行成功
    ERROR = "error"           # 执行出错
    OUTDATED = "outdated"     # 代码已更新，结果过期


class SandboxStatus(str, Enum):
    """沙盒会话状态"""
    CREATING = "creating"
    READY = "ready"
    EXECUTING = "executing"
    IDLE = "idle"
    PAUSED = "paused"
    ERROR = "error"
    DESTROYED = "destroyed"


class Artifact(BaseModel):
    """代码 Artifact 模型"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    session_id: str
    title: str
    description: Optional[str] = None
    language: ArtifactLanguage = ArtifactLanguage.PYTHON
    code: str = ""
    status: ArtifactStatus = ArtifactStatus.DRAFT
    version: int = 1
    parent_id: Optional[str] = None  # 版本链
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    auto_execute: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SandboxSession(BaseModel):
    """沙盒会话模型"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    container_id: Optional[str] = None
    container_name: str = ""
    status: SandboxStatus = SandboxStatus.CREATING
    kernel_id: Optional[str] = None
    kernel_connection_info: Optional[Dict[str, Any]] = None
    language: ArtifactLanguage = ArtifactLanguage.PYTHON
    resource_limits: Dict[str, Any] = Field(default_factory=dict)
    mounted_volumes: List[Dict[str, str]] = Field(default_factory=list)
    packages: List[str] = Field(default_factory=list)  # 已安装包
    last_activity: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None


# ──────────────────────────────
# 核心类设计
# ──────────────────────────────

class CopilotAgent:
    """主 Agent - 负责意图识别和路由
    
    路由决策逻辑：
    1. 先通过 LLM/规则引擎识别意图
    2. 根据意图分发到对应处理器
    3. 维护多轮对话上下文
    """
    
    def __init__(
        self,
        code_generator: "CodeGenerator",
        artifact_manager: "ArtifactManager",
        session_manager: "SessionManager",
        mcp_client: Optional[Any] = None,
    ):
        self.code_generator = code_generator
        self.artifact_manager = artifact_manager
        self.session_manager = session_manager
        self.mcp_client = mcp_client
        self._context_store: Dict[str, List[Dict]] = {}  # user_id -> context
    
    async def process_message(
        self,
        user_id: str,
        message: str,
        current_artifact_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """处理用户消息，流式返回事件
        
        Yields:
            事件字典，包含 type 和 payload
        """
        # 1. 识别意图
        intent = await self._classify_intent(user_id, message)
        
        # 2. 路由处理
        if intent == IntentType.CODE_GENERATION:
            async for event in self._handle_code_generation(
                user_id, message, current_artifact_id
            ):
                yield event
        elif intent == IntentType.WORKFLOW_SCHEDULE:
            async for event in self._handle_workflow_schedule(user_id, message):
                yield event
        elif intent == IntentType.EXECUTE:
            async for event in self._handle_execute(user_id, current_artifact_id):
                yield event
        else:
            # 闲聊/咨询：直接通过 LLM 回复
            async for event in self._handle_chat(user_id, message):
                yield event
    
    async def _classify_intent(
        self, user_id: str, message: str
    ) -> IntentType:
        """意图识别 - 结合规则引擎和轻量 LLM 调用"""
        # 规则快速匹配
        code_keywords = ["写代码", "画个图", "可视化", "分析", "plot", "UMAP", "热图"]
        workflow_keywords = ["流程", "pipeline", "跑", "运行流程"]
        execute_keywords = ["运行", "执行", "Run", "execute"]
        
        msg_lower = message.lower()
        if any(k in message for k in code_keywords):
            return IntentType.CODE_GENERATION
        if any(k in message for k in execute_keywords) and user_id:
            return IntentType.EXECUTE
        if any(k in message for k in workflow_keywords):
            return IntentType.WORKFLOW_SCHEDULE
        
        # 轻量 LLM 意图分类（可缓存）
        return await self._llm_classify_intent(message)
    
    async def _handle_code_generation(
        self,
        user_id: str,
        message: str,
        artifact_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """处理代码生成请求"""
        # 获取或创建 Artifact
        if artifact_id:
            artifact = await self.artifact_manager.get_artifact(artifact_id)
        else:
            artifact = await self.artifact_manager.create_artifact(
                user_id=user_id,
                title=message[:50],  # 用消息前50字符作为标题
                language=ArtifactLanguage.PYTHON,
            )
        
        # 流式代码生成
        code_buffer = []
        async for chunk in self.code_generator.generate(
            prompt=message,
            language=artifact.language,
            context=self._get_context(user_id),
        ):
            if chunk["type"] == "thinking":
                yield {"type": "copilot.thinking_step", "payload": chunk}
            elif chunk["type"] == "code":
                code_buffer.append(chunk["content"])
                yield {"type": "copilot.artifact_stream", "payload": chunk}
        
        # 保存完整代码
        full_code = "".join(code_buffer)
        await self.artifact_manager.update_code(artifact.id, full_code)
        
        yield {
            "type": "copilot.artifact_create",
            "payload": {
                "artifact_id": artifact.id,
                "code": full_code,
                "language": artifact.language.value,
                "title": artifact.title,
            },
        }
    
    def _get_context(self, user_id: str) -> List[Dict]:
        """获取用户对话上下文"""
        return self._context_store.get(user_id, [])[-10:]  # 最近10轮


class CodeGenerator:
    """代码生成器 - 调用 LLM 生成代码，支持流式输出
    
    特性：
    - 流式返回（thinking + code 分段）
    - 多语言支持（Python/R/Bash）
    - 上下文感知（对话历史 + 已有 Artifact）
    - 代码质量后处理（格式化、安全检查）
    """
    
    SYSTEM_PROMPT_TEMPLATE = """你是一个专业的生物信息学分析助手。请根据用户需求生成高质量的{language}代码。

要求：
1. 代码必须可直接执行，包含必要的 import 语句
2. 使用 Scanpy/Seurat 等标准生信库
3. 添加必要的注释说明关键步骤
4. 图表使用英文标签，适配学术发表标准
5. 数据路径使用 /data/user_{user_id}/ 前缀
6. 输出图表保存到 /tmp/execution/ 目录
7. 危险操作检测：禁止 rm -rf /、禁止系统调用

思考过程用 <thinking> 标签包裹，代码用 ```{language} 包裹。"""
    
    def __init__(self, llm_client: Any, safety_checker: "CodeSafetyChecker"):
        self.llm_client = llm_client
        self.safety = safety_checker
    
    async def generate(
        self,
        prompt: str,
        language: ArtifactLanguage = ArtifactLanguage.PYTHON,
        context: Optional[List[Dict]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式生成代码
        
        Yields:
            {"type": "thinking", "content": str}
            {"type": "code", "content": str}
        """
        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(
            language=language.value,
            user_id="{user_id}",  # 占位，实际替换
        )
        
        full_response = []
        current_section = None  # 'thinking' | 'code' | None
        buffer = []
        
        async for token in self.llm_client.stream_chat(
            system=system_prompt,
            messages=context or [],
            user_prompt=prompt,
        ):
            full_response.append(token)
            
            # 解析 section 切换
            if "<thinking>" in token:
                current_section = "thinking"
                continue
            elif "</thinking>" in token:
                if buffer:
                    yield {"type": "thinking", "content": "".join(buffer)}
                    buffer = []
                current_section = None
                continue
            elif f"```{language.value}" in token:
                current_section = "code"
                continue
            elif "```" in token and current_section == "code":
                if buffer:
                    code = "".join(buffer)
                    safe_code = self.safety.scan(code)
                    yield {"type": "code", "content": safe_code}
                    buffer = []
                current_section = None
                continue
            
            if current_section:
                buffer.append(token)
                # 代码段实时流式（每10个token或遇到换行）
                if current_section == "code" and (len(buffer) >= 10 or "\n" in token):
                    code = "".join(buffer)
                    buffer = []
                    yield {"type": "code", "content": code}
    
    async def explain_code(self, code: str, language: ArtifactLanguage) -> str:
        """解释已有代码的功能"""
        prompt = f"请详细解释以下 {language.value} 代码的功能和关键步骤:\n\n```{language.value}\n{code}\n```"
        return await self.llm_client.chat(prompt=prompt)


class ArtifactManager:
    """Artifact 管理器 - 管理代码-执行-结果的关联
    
    职责：
    - Artifact CRUD（创建/读取/更新/删除）
    - 版本链管理（支持回溯）
    - 与执行记录的关联查询
    """
    
    def __init__(self, db_session: Any, object_store: Any):
        self.db = db_session
        self.store = object_store
    
    async def create_artifact(
        self,
        user_id: str,
        title: str,
        language: ArtifactLanguage = ArtifactLanguage.PYTHON,
        code: str = "",
        description: Optional[str] = None,
    ) -> Artifact:
        """创建新 Artifact"""
        artifact = Artifact(
            user_id=user_id,
            session_id=await self._get_active_session(user_id),
            title=title,
            description=description,
            language=language,
            code=code,
            status=ArtifactStatus.DRAFT,
        )
        # 持久化到数据库
        await self._persist_artifact(artifact)
        return artifact
    
    async def update_code(self, artifact_id: str, code: str) -> Artifact:
        """更新 Artifact 代码（创建新版本）"""
        old = await self.get_artifact(artifact_id)
        
        # 创建新版本
        new_artifact = Artifact(
            user_id=old.user_id,
            session_id=old.session_id,
            title=old.title,
            description=old.description,
            language=old.language,
            code=code,
            status=ArtifactStatus.EDITING,
            version=old.version + 1,
            parent_id=old.id,
        )
        await self._persist_artifact(new_artifact)
        
        # 标记旧版本为过期
        old.status = ArtifactStatus.OUTDATED
        await self._persist_artifact(old)
        
        return new_artifact
    
    async def record_execution(
        self,
        artifact_id: str,
        execution_id: str,
        status: str,
    ) -> None:
        """记录执行关联"""
        await self.db.execute(
            "UPDATE artifacts SET last_execution_id = :eid, status = :st WHERE id = :aid",
            {"eid": execution_id, "st": status, "aid": artifact_id},
        )
    
    async def get_artifact(self, artifact_id: str) -> Artifact:
        """获取 Artifact"""
        row = await self.db.fetch_one(
            "SELECT * FROM artifacts WHERE id = :id", {"id": artifact_id}
        )
        return Artifact(**row) if row else None
    
    async def list_artifacts(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Artifact]:
        """列出用户的 Artifacts"""
        query = "SELECT * FROM artifacts WHERE user_id = :uid"
        params = {"uid": user_id}
        if session_id:
            query += " AND session_id = :sid"
            params["sid"] = session_id
        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit
        
        rows = await self.db.fetch_all(query, params)
        return [Artifact(**r) for r in rows]
    
    async def _get_active_session(self, user_id: str) -> str:
        """获取用户活跃的沙盒会话 ID"""
        # 委托给 SessionManager
        row = await self.db.fetch_one(
            "SELECT id FROM sandbox_sessions WHERE user_id = :uid AND status IN ('ready', 'idle', 'executing') ORDER BY last_activity DESC LIMIT 1",
            {"uid": user_id},
        )
        return row["id"] if row else ""
    
    async def _persist_artifact(self, artifact: Artifact) -> None:
        """持久化 Artifact 到数据库"""
        await self.db.execute(
            """
            INSERT INTO artifacts (id, user_id, session_id, title, description, language, code, status, version, parent_id, created_at, updated_at, auto_execute, metadata)
            VALUES (:id, :user_id, :session_id, :title, :description, :language, :code, :status, :version, :parent_id, :created_at, :updated_at, :auto_execute, :metadata)
            ON CONFLICT (id) DO UPDATE SET
                code = EXCLUDED.code,
                status = EXCLUDED.status,
                version = EXCLUDED.version,
                updated_at = EXCLUDED.updated_at,
                metadata = EXCLUDED.metadata
            """,
            artifact.model_dump(),
        )


class SessionManager:
    """沙盒会话管理器 - 管理用户沙盒会话的生命周期
    
    职责：
    - 会话创建/销毁
    - 心跳检测与自动回收
    - 会话状态持久化（Redis）
    - 资源配额控制（每用户最大会话数）
    """
    
    HEARTBEAT_INTERVAL = 30       # 心跳间隔（秒）
    IDLE_TIMEOUT = 600            # 空闲超时（10分钟）
    PAUSED_TIMEOUT = 1800         # 暂停超时（30分钟）
    MAX_SESSIONS_PER_USER = 3     # 每用户最大会话数
    
    def __init__(
        self,
        db: Any,
        redis: Any,
        sandbox_pool: "SandboxPool",
    ):
        self.db = db
        self.redis = redis
        self.pool = sandbox_pool
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}
    
    async def create_session(
        self,
        user_id: str,
        language: ArtifactLanguage = ArtifactLanguage.PYTHON,
    ) -> SandboxSession:
        """创建新的沙盒会话"""
        # 检查配额
        active_count = await self._count_active_sessions(user_id)
        if active_count >= self.MAX_SESSIONS_PER_USER:
            # 回收最老的会话
            await self._recycle_oldest_session(user_id)
        
        session = SandboxSession(
            user_id=user_id,
            container_name=f"omicshub-sandbox-{user_id}-{uuid.uuid4().hex[:8]}",
            language=language,
            resource_limits={
                "cpu": "4.0",
                "memory": "8g",
                "disk": "20g",
                "shm_size": "2g",  # PyTorch 共享内存
            },
        )
        
        # 持久化
        await self._persist_session(session)
        
        # 异步创建容器
        asyncio.create_task(self._provision_container(session))
        
        return session
    
    async def get_or_create_session(
        self, user_id: str
    ) -> SandboxSession:
        """获取已有活跃会话，或创建新会话"""
        session = await self._get_active_session(user_id)
        if session and session.status in (SandboxStatus.READY, SandboxStatus.IDLE):
            await self._update_activity(session.id)
            return session
        return await self.create_session(user_id)
    
    async def destroy_session(self, session_id: str) -> None:
        """销毁会话"""
        session = await self._get_session(session_id)
        if not session:
            return
        
        # 停止心跳
        if session_id in self._heartbeat_tasks:
            self._heartbeat_tasks[session_id].cancel()
        
        # 销毁容器
        await self.pool.destroy_sandbox(session.container_id)
        
        # 更新状态
        session.status = SandboxStatus.DESTROYED
        await self._persist_session(session)
        await self.redis.delete(f"session:{session_id}")
    
    async def heartbeat(self, session_id: str) -> SandboxStatus:
        """会话心跳"""
        session = await self._get_session(session_id)
        if not session:
            return SandboxStatus.DESTROYED
        
        await self._update_activity(session_id)
        
        # 从 paused 恢复
        if session.status == SandboxStatus.PAUSED:
            session.status = SandboxStatus.READY
            await self.pool.resume_sandbox(session.container_id)
            await self._persist_session(session)
        
        return session.status
    
    async def _provision_container(self, session: SandboxSession) -> None:
        """异步预配容器"""
        try:
            container_id = await self.pool.create_sandbox(session)
            session.container_id = container_id
            session.status = SandboxStatus.READY
        except Exception as e:
            session.status = SandboxStatus.ERROR
            session.metadata["error"] = str(e)
        
        await self._persist_session(session)
        
        # 启动心跳监控
        self._heartbeat_tasks[session.id] = asyncio.create_task(
            self._heartbeat_monitor(session.id)
        )
    
    async def _heartbeat_monitor(self, session_id: str) -> None:
        """心跳监控协程 - 检测空闲超时"""
        while True:
            try:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                
                session = await self._get_session(session_id)
                if not session or session.status == SandboxStatus.DESTROYED:
                    break
                
                idle_time = (datetime.utcnow() - session.last_activity).total_seconds()
                
                if session.status == SandboxStatus.IDLE and idle_time > self.IDLE_TIMEOUT:
                    # 进入暂停状态
                    session.status = SandboxStatus.PAUSED
                    await self.pool.pause_sandbox(session.container_id)
                    await self._persist_session(session)
                
                elif session.status == SandboxStatus.PAUSED and idle_time > self.PAUSED_TIMEOUT:
                    # 超时销毁
                    await self.destroy_session(session_id)
                    break
                    
            except asyncio.CancelledError:
                break
            except Exception:
                # 记录异常但继续监控
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
    
    async def _count_active_sessions(self, user_id: str) -> int:
        """统计用户活跃会话数"""
        result = await self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM sandbox_sessions WHERE user_id = :uid AND status NOT IN ('destroyed', 'error')",
            {"uid": user_id},
        )
        return result["cnt"] if result else 0
    
    async def _recycle_oldest_session(self, user_id: str) -> None:
        """回收最老的会话"""
        row = await self.db.fetch_one(
            "SELECT id FROM sandbox_sessions WHERE user_id = :uid ORDER BY last_activity ASC LIMIT 1",
            {"uid": user_id},
        )
        if row:
            await self.destroy_session(row["id"])
    
    async def _get_active_session(self, user_id: str) -> Optional[SandboxSession]:
        """获取用户最新活跃会话"""
        row = await self.db.fetch_one(
            "SELECT * FROM sandbox_sessions WHERE user_id = :uid AND status IN ('ready', 'idle') ORDER BY last_activity DESC LIMIT 1",
            {"uid": user_id},
        )
        return SandboxSession(**row) if row else None
    
    async def _get_session(self, session_id: str) -> Optional[SandboxSession]:
        """获取会话（优先 Redis 缓存）"""
        cached = await self.redis.get(f"session:{session_id}")
        if cached:
            return SandboxSession.parse_raw(cached)
        
        row = await self.db.fetch_one(
            "SELECT * FROM sandbox_sessions WHERE id = :id", {"id": session_id}
        )
        return SandboxSession(**row) if row else None
    
    async def _persist_session(self, session: SandboxSession) -> None:
        """持久化会话"""
        await self.db.execute(
            """
            INSERT INTO sandbox_sessions (id, user_id, container_id, container_name, status, kernel_id, language, resource_limits, mounted_volumes, packages, last_activity, created_at, expires_at)
            VALUES (:id, :user_id, :container_id, :container_name, :status, :kernel_id, :language, :resource_limits, :mounted_volumes, :packages, :last_activity, :created_at, :expires_at)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                container_id = EXCLUDED.container_id,
                kernel_id = EXCLUDED.kernel_id,
                last_activity = EXCLUDED.last_activity,
                packages = EXCLUDED.packages
            """,
            session.model_dump(),
        )
        await self.redis.setex(
            f"session:{session.id}",
            self.PAUSED_TIMEOUT,
            session.model_dump_json(),
        )
    
    async def _update_activity(self, session_id: str) -> None:
        """更新会话活动时间"""
        now = datetime.utcnow()
        await self.db.execute(
            "UPDATE sandbox_sessions SET last_activity = :t WHERE id = :id",
            {"t": now, "id": session_id},
        )
        await self.redis.hset(f"session:{session_id}", "last_activity", now.isoformat())
```

---

### 2.2 Sandbox Orchestrator（FastAPI 子模块）

```python
# app/sandbox/__init__.py
"""Sandbox Orchestrator - 沙盒编排与执行引擎

职责：
- 容器池管理（预热、分配、回收）
- Jupyter Kernel 生命周期管理
- 代码执行调度（提交、超时控制、流式输出）
- 结果收集与序列化
"""

import asyncio
import json
import base64
import tempfile
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any, AsyncIterator, Callable
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import docker
from docker.errors import NotFound, APIError
import aiohttp


logger = logging.getLogger(__name__)


# ──────────────────────────────
# 执行相关模型
# ──────────────────────────────

class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"       # 队列中等待
    RUNNING = "running"       # 执行中
    SUCCESS = "success"       # 成功
    ERROR = "error"           # 错误
    TIMEOUT = "timeout"       # 超时
    CANCELLED = "cancelled"   # 用户取消


@dataclass
class ExecutionRequest:
    """执行请求"""
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    artifact_id: str = ""
    code: str = ""
    language: str = "python"
    timeout: int = 300        # 默认5分钟
    priority: int = 0
    dependencies: List[str] = field(default_factory=list)
    submitted_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionResult:
    """执行结果"""
    execution_id: str = ""
    artifact_id: str = ""
    status: ExecutionStatus = ExecutionStatus.PENDING
    stdout: List[str] = field(default_factory=list)
    stderr: List[str] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)  # display_data
    error_info: Optional[Dict[str, str]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: int = 0


# ──────────────────────────────
# 核心类设计
# ──────────────────────────────

class SandboxPool:
    """沙盒容器池管理
    
    职责：
    - 容器预热（维护 warm pool）
    - 容器分配（从 pool 获取或新建）
    - 容器回收（回到 pool 或销毁）
    - 镜像管理（基础镜像 + 用户自定义镜像）
    
    性能目标：
    - warm pool 命中：获取容器 < 500ms
    - cold start：创建容器 < 10s
    """
    
    WARM_POOL_SIZE = 5          # 预热池大小
    MAX_POOL_SIZE = 20          # 最大池大小
    CONTAINER_TTL = 3600        # 容器最大存活时间（秒）
    
    def __init__(
        self,
        docker_client: docker.DockerClient,
        redis: Any,
        image_registry: str = "omicshub",
        base_image: str = "omicshub/sandbox-base:latest",
    ):
        self.docker = docker_client
        self.redis = redis
        self.registry = image_registry
        self.base_image = base_image
        self._warm_pool: asyncio.Queue = asyncio.Queue(maxsize=self.MAX_POOL_SIZE)
        self._active_containers: Dict[str, Dict] = {}  # container_id -> metadata
        self._pool_lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """初始化：预热容器池"""
        logger.info("Initializing sandbox warm pool...")
        tasks = [self._warm_container() for _ in range(self.WARM_POOL_SIZE)]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Warm pool initialized with {self._warm_pool.qsize()} containers")
    
    async def get_sandbox(
        self,
        user_id: str,
        session: SandboxSession,
    ) -> str:
        """获取沙盒容器（优先从预热池分配）"""
        async with self._pool_lock:
            # 尝试从预热池获取
            try:
                container_info = self._warm_pool.get_nowait()
                container_id = container_info["container_id"]
                
                # 重新配置容器（挂载用户数据卷）
                await self._configure_for_user(container_id, user_id, session)
                
                self._active_containers[container_id] = {
                    "user_id": user_id,
                    "session_id": session.id,
                    "acquired_at": datetime.utcnow(),
                }
                
                # 补充预热池
                asyncio.create_task(self._warm_container())
                
                logger.info(f"Sandbox {container_id[:12]} assigned from warm pool")
                return container_id
                
            except asyncio.QueueEmpty:
                # 冷启动：创建新容器
                return await self._create_cold(session)
    
    async def create_sandbox(self, session: SandboxSession) -> str:
        """创建新的沙盒容器（供 SessionManager 调用）"""
        return await self._create_cold(session)
    
    async def release_sandbox(self, container_id: str) -> None:
        """释放沙盒容器（回到预热池或销毁）"""
        if container_id not in self._active_containers:
            return
        
        metadata = self._active_containers.pop(container_id)
        
        # 检查容器状态
        try:
            container = self.docker.containers.get(container_id)
            if container.status != "running":
                container.remove(force=True)
                return
        except NotFound:
            return
        
        # 尝试回到预热池
        if self._warm_pool.qsize() < self.WARM_POOL_SIZE:
            await self._reset_container(container_id)
            await self._warm_pool.put({"container_id": container_id, "warmed_at": datetime.utcnow()})
        else:
            # 销毁
            try:
                container.remove(force=True)
            except APIError:
                pass
    
    async def destroy_sandbox(self, container_id: Optional[str]) -> None:
        """销毁沙盒容器"""
        if not container_id:
            return
        
        self._active_containers.pop(container_id, None)
        
        try:
            container = self.docker.containers.get(container_id)
            container.stop(timeout=10)
            container.remove(force=True)
            logger.info(f"Container {container_id[:12]} destroyed")
        except NotFound:
            pass
        except APIError as e:
            logger.error(f"Failed to destroy container {container_id[:12]}: {e}")
    
    async def pause_sandbox(self, container_id: str) -> None:
        """暂停沙盒（CPU 节流，保留内存）"""
        try:
            container = self.docker.containers.get(container_id)
            # 使用 cgroup 限制 CPU 份额而非 pause
            container.update(cpu_shares=10, mem_limit="256m")
            logger.info(f"Container {container_id[:12]} paused")
        except APIError as e:
            logger.error(f"Failed to pause container: {e}")
    
    async def resume_sandbox(self, container_id: str) -> None:
        """恢复沙盒"""
        try:
            container = self.docker.containers.get(container_id)
            session = self._active_containers.get(container_id, {})
            limits = session.get("resource_limits", {})
            container.update(
                cpu_shares=int(float(limits.get("cpu", "4.0")) * 1024),
                mem_limit=limits.get("memory", "8g"),
            )
            logger.info(f"Container {container_id[:12]} resumed")
        except APIError as e:
            logger.error(f"Failed to resume container: {e}")
    
    async def _warm_container(self) -> None:
        """预热单个容器"""
        try:
            container = self.docker.containers.run(
                image=self.base_image,
                command=["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--port=8888"],
                detach=True,
                mem_limit="512m",
                cpu_shares=512,
                network="omicshub-sandbox",
                labels={"omicshub.pool": "warm", "omicshub.version": "1.0"},
                healthcheck={
                    "test": ["CMD", "curl", "-f", "http://localhost:8888/api"],
                    "interval": 5000000000,  # 5s
                    "timeout": 3000000000,   # 3s
                    "retries": 3,
                },
            )
            
            # 等待健康检查通过
            await self._wait_healthy(container.id, timeout=30)
            
            await self._warm_pool.put({
                "container_id": container.id,
                "warmed_at": datetime.utcnow(),
            })
            
        except Exception as e:
            logger.error(f"Failed to warm container: {e}")
    
    async def _create_cold(self, session: SandboxSession) -> str:
        """冷启动创建容器"""
        # 检查用户自定义镜像
        image = await self._resolve_image(session.user_id, session.language)
        
        volumes = self._build_volume_mounts(session)
        
        container = self.docker.containers.run(
            image=image,
            name=session.container_name,
            hostname=session.container_name,
            command=[
                "jupyter", "kernelgateway",
                "--KernelGatewayApp.ip=0.0.0.0",
                "--KernelGatewayApp.port=8888",
                "--KernelGatewayApp.auth_token=''",
                "--JupyterWebsocketPersonality.list_kernels=True",
            ],
            detach=True,
            mem_limit=session.resource_limits.get("memory", "8g"),
            cpu_count=int(float(session.resource_limits.get("cpu", "4.0"))),
            shm_size=session.resource_limits.get("shm_size", "2g"),
            storage_opt={"size": session.resource_limits.get("disk", "20g")},
            network="omicshub-sandbox",
            volumes=volumes,
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            cap_add=["CHOWN", "SETUID", "SETGID"],  # 最小权限
            read_only=True,  # 根文件系统只读
            tmpfs={"/tmp": "rw,noexec,nosuid,size=2g"},
            labels={
                "omicshub.session_id": session.id,
                "omicshub.user_id": session.user_id,
                "omicshub.version": "1.0",
            },
        )
        
        # 等待健康检查
        await self._wait_healthy(container.id, timeout=60)
        
        self._active_containers[container.id] = {
            "user_id": session.user_id,
            "session_id": session.id,
            "resource_limits": session.resource_limits,
            "acquired_at": datetime.utcnow(),
        }
        
        logger.info(f"Cold start container {container.id[:12]} in {container.attrs['State']['StartedAt']}")
        return container.id
    
    async def _resolve_image(
        self, user_id: str, language: ArtifactLanguage
    ) -> str:
        """解析用户镜像（优先使用用户自定义镜像）"""
        user_image = f"{self.registry}/sandbox-{user_id}:latest"
        try:
            self.docker.images.get(user_image)
            return user_image
        except NotFound:
            return self.base_image
    
    def _build_volume_mounts(self, session: SandboxSession) -> Dict[str, Dict]:
        """构建数据卷挂载配置"""
        volumes = {}
        
        # 用户数据目录（只读）
        user_data_path = f"/data/users/{session.user_id}"
        volumes[user_data_path] = {
            "bind": "/data/user",
            "mode": "ro",
        }
        
        # 临时执行空间（读写）
        exec_path = f"/tmp/execution/{session.id}"
        volumes[exec_path] = {
            "bind": "/tmp/execution",
            "mode": "rw",
        }
        
        # 参考基因组（只读）
        volumes["/shared/ref-genomes"] = {
            "bind": "/data/ref",
            "mode": "ro",
        }
        
        # 包持久化层（读写）
        pkg_path = f"/data/packages/{session.user_id}"
        volumes[pkg_path] = {
            "bind": "/opt/conda/envs/user",
            "mode": "rw",
        }
        
        return volumes
    
    async def _wait_healthy(self, container_id: str, timeout: int = 60) -> None:
        """等待容器健康检查通过"""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                container = self.docker.containers.get(container_id)
                health = container.attrs.get("State", {}).get("Health", {})
                status = health.get("Status", "")
                if status == "healthy":
                    return
                if container.status != "running":
                    raise RuntimeError(f"Container exited: {container.attrs['State']}")
            except NotFound:
                raise RuntimeError("Container not found")
            await asyncio.sleep(1)
        raise TimeoutError(f"Container health check timeout after {timeout}s")
    
    async def _configure_for_user(
        self, container_id: str, user_id: str, session: SandboxSession
    ) -> None:
        """为特定用户配置容器（挂载用户卷）"""
        # 更新卷挂载（Docker 不支持运行时修改卷，此处通过 symlink 或重新创建实现）
        # 实际实现：预热池容器只预热基础环境，用户特定配置在获取后通过 API 设置
        pass
    
    async def _reset_container(self, container_id: str) -> None:
        """重置容器状态（清理执行痕迹）"""
        try:
            container = self.docker.containers.get(container_id)
            # 清理 /tmp/execution 下的文件
            container.exec_run("rm -rf /tmp/execution/*", user="jovyan")
            # 重置资源限制
            container.update(cpu_shares=512, mem_limit="512m")
        except APIError as e:
            logger.warning(f"Failed to reset container: {e}")


class KernelClient:
    """Jupyter Kernel 客户端
    
    通信方式：
    - 通过 Kernel Gateway REST API 创建/管理 Kernel
    - 通过 WebSocket 发送执行请求和接收输出
    """
    
    def __init__(self, gateway_url: str = "http://localhost:8888"):
        self.gateway_url = gateway_url
        self._kernels: Dict[str, str] = {}  # session_id -> kernel_id
        self._sessions: Dict[str, aiohttp.ClientSession] = {}
    
    async def start_kernel(self, session_id: str) -> str:
        """启动新的 Kernel"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.gateway_url}/api/kernels",
                json={"name": "python3", "env": {"PYTHONPATH": "/opt/conda/envs/user/lib/python3.11/site-packages"}},
            ) as resp:
                data = await resp.json()
                kernel_id = data["id"]
                self._kernels[session_id] = kernel_id
                return kernel_id
    
    async def execute(
        self,
        session_id: str,
        code: str,
        timeout: int = 300,
    ) -> AsyncIterator[Dict[str, Any]]:
        """执行代码，流式返回输出
        
        Yields:
            {"type": "stream", "name": "stdout", "text": str}
            {"type": "display_data", "data": {"image/png": "...", "text/plain": "..."}}
            {"type": "error", "ename": str, "evalue": str, "traceback": List[str]}
            {"type": "status", "execution_state": "busy" | "idle"}
            {"type": "execute_reply", "execution_count": int, "status": "ok" | "error"}
        """
        kernel_id = self._kernels.get(session_id)
        if not kernel_id:
            kernel_id = await self.start_kernel(session_id)
        
        ws_url = f"ws://{self.gateway_url.replace('http://', '').replace('https://', '')}/api/kernels/{kernel_id}/channels"
        
        msg_id = f"execute_{uuid.uuid4().hex[:8]}"
        execute_msg = {
            "header": {
                "msg_id": msg_id,
                "username": "omicshub",
                "session": session_id,
                "msg_type": "execute_request",
                "version": "5.3",
            },
            "parent_header": {},
            "metadata": {},
            "content": {
                "code": code,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": False,
                "stop_on_error": True,
            },
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url) as ws:
                await ws.send_json(execute_msg)
                
                deadline = asyncio.get_event_loop().time() + timeout
                
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        msg = await asyncio.wait_for(
                            ws.receive_json(), timeout=min(30, deadline - asyncio.get_event_loop().time())
                        )
                        
                        msg_type = msg.get("msg_type", "")
                        content = msg.get("content", {})
                        
                        if msg_type == "stream":
                            yield {
                                "type": "stream",
                                "name": content.get("name", "stdout"),
                                "text": content.get("text", ""),
                            }
                        elif msg_type == "display_data":
                            yield {
                                "type": "display_data",
                                "data": content.get("data", {}),
                                "metadata": content.get("metadata", {}),
                            }
                        elif msg_type == "execute_result":
                            yield {
                                "type": "execute_result",
                                "data": content.get("data", {}),
                                "execution_count": content.get("execution_count", 0),
                            }
                        elif msg_type == "error":
                            yield {
                                "type": "error",
                                "ename": content.get("ename", ""),
                                "evalue": content.get("evalue", ""),
                                "traceback": content.get("traceback", []),
                            }
                        elif msg_type == "status":
                            yield {
                                "type": "status",
                                "execution_state": content.get("execution_state", ""),
                            }
                            if content.get("execution_state") == "idle":
                                # 执行完成
                                break
                        elif msg_type == "execute_reply":
                            yield {
                                "type": "execute_reply",
                                "status": content.get("status", "ok"),
                                "execution_count": content.get("execution_count", 0),
                            }
                            break
                            
                    except asyncio.TimeoutError:
                        yield {
                            "type": "error",
                            "ename": "TimeoutError",
                            "evalue": f"Execution timed out after {timeout}s",
                            "traceback": [],
                        }
                        break
    
    async def interrupt(self, session_id: str) -> None:
        """中断当前执行"""
        kernel_id = self._kernels.get(session_id)
        if not kernel_id:
            return
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.gateway_url}/api/kernels/{kernel_id}/interrupt"
            ):
                pass
    
    async def restart(self, session_id: str) -> None:
        """重启 Kernel"""
        kernel_id = self._kernels.get(session_id)
        if not kernel_id:
            return
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.gateway_url}/api/kernels/{kernel_id}/restart"
            ):
                pass
    
    async def shutdown(self, session_id: str) -> None:
        """关闭 Kernel"""
        kernel_id = self._kernels.pop(session_id, None)
        if not kernel_id:
            return
        
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{self.gateway_url}/api/kernels/{kernel_id}"
            ):
                pass


class ExecutionEngine:
    """代码执行引擎
    
    职责：
    - 执行队列管理（优先级、并发控制）
    - 代码提交与超时控制
    - 输出流式转发
    - 执行结果聚合
    """
    
    MAX_CONCURRENT = 3          # 单容器最大并发
    QUEUE_DEPTH = 10            # 队列深度
    
    def __init__(
        self,
        kernel_client: KernelClient,
        result_collector: "ResultCollector",
        db: Any,
    ):
        self.kernel = kernel_client
        self.collector = result_collector
        self.db = db
        self._semaphores: Dict[str, asyncio.Semaphore] = {}  # session_id -> semaphore
        self._queues: Dict[str, asyncio.Queue] = {}          # session_id -> queue
        self._cancel_flags: Dict[str, bool] = {}             # execution_id -> cancelled
    
    async def submit(self, request: ExecutionRequest) -> str:
        """提交执行请求到队列"""
        # 初始化会话队列
        if request.session_id not in self._queues:
            self._queues[request.session_id] = asyncio.Queue(maxsize=self.QUEUE_DEPTH)
            self._semaphores[request.session_id] = asyncio.Semaphore(self.MAX_CONCURRENT)
        
        queue = self._queues[request.session_id]
        
        if queue.full():
            raise QueueFullError(f"Execution queue full for session {request.session_id}")
        
        # 持久化执行记录
        await self._persist_execution(request)
        
        await queue.put(request)
        
        # 启动队列处理器（每个会话一个）
        asyncio.create_task(self._process_queue(request.session_id))
        
        return request.execution_id
    
    async def stream_output(
        self, execution_id: str
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式获取执行输出"""
        # 从 Redis 流中读取
        stream_key = f"execution:{execution_id}:stream"
        
        while True:
            # 使用 Redis Stream 或轮询
            chunk = await self._get_next_chunk(execution_id)
            if chunk is None:
                await asyncio.sleep(0.1)
                continue
            
            yield chunk
            
            if chunk.get("type") in ("execute_reply", "error"):
                break
    
    async def cancel(self, execution_id: str) -> None:
        """取消执行"""
        self._cancel_flags[execution_id] = True
        
        # 从队列中移除（如果还在等待）
        for session_id, queue in self._queues.items():
            # 注：asyncio.Queue 不支持安全移除，通过 cancel flag 跳过
            pass
    
    async def _process_queue(self, session_id: str) -> None:
        """队列处理器 - 按顺序执行队列中的请求"""
        queue = self._queues.get(session_id)
        semaphore = self._semaphores.get(session_id)
        
        if not queue or not semaphore:
            return
        
        while True:
            try:
                request = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # 队列为空，检查是否需要清理
                if queue.empty():
                    del self._queues[session_id]
                    del self._semaphores[session_id]
                    break
                continue
            
            async with semaphore:
                if self._cancel_flags.get(request.execution_id):
                    await self._update_status(request.execution_id, ExecutionStatus.CANCELLED)
                    continue
                
                await self._execute_single(request)
    
    async def _execute_single(self, request: ExecutionRequest) -> ExecutionResult:
        """执行单个请求"""
        start_time = datetime.utcnow()
        result = ExecutionResult(
            execution_id=request.execution_id,
            artifact_id=request.artifact_id,
            status=ExecutionStatus.RUNNING,
            started_at=start_time,
        )
        
        await self._update_status(request.execution_id, ExecutionStatus.RUNNING)
        
        try:
            async for msg in self.kernel.execute(
                session_id=request.session_id,
                code=request.code,
                timeout=request.timeout,
            ):
                # 检查取消标志
                if self._cancel_flags.get(request.execution_id):
                    await self.kernel.interrupt(request.session_id)
                    result.status = ExecutionStatus.CANCELLED
                    break
                
                # 处理消息
                if msg["type"] == "stream":
                    if msg["name"] == "stdout":
                        result.stdout.append(msg["text"])
                    else:
                        result.stderr.append(msg["text"])
                    
                    # 流式转发到 WebSocket
                    await self._stream_to_websocket(request, msg)
                
                elif msg["type"] in ("display_data", "execute_result"):
                    processed = await self.collector.process_display_data(
                        request.execution_id, msg["data"]
                    )
                    result.outputs.append(processed)
                    
                    # 流式转发处理后的结果
                    await self._stream_to_websocket(request, {
                        "type": "display_data",
                        "data": processed,
                    })
                
                elif msg["type"] == "error":
                    result.status = ExecutionStatus.ERROR
                    result.error_info = {
                        "ename": msg["ename"],
                        "evalue": msg["evalue"],
                        "traceback": "\n".join(msg["traceback"]),
                    }
                    await self._stream_to_websocket(request, msg)
                
                elif msg["type"] == "execute_reply":
                    if result.status != ExecutionStatus.ERROR:
                        result.status = ExecutionStatus.SUCCESS
            
        except asyncio.TimeoutError:
            result.status = ExecutionStatus.TIMEOUT
            result.error_info = {"ename": "TimeoutError", "evalue": f"Timeout after {request.timeout}s", "traceback": ""}
            await self.kernel.interrupt(request.session_id)
        
        except Exception as e:
            result.status = ExecutionStatus.ERROR
            result.error_info = {"ename": type(e).__name__, "evalue": str(e), "traceback": ""}
        
        finally:
            result.finished_at = datetime.utcnow()
            result.duration_ms = int((result.finished_at - start_time).total_seconds() * 1000)
            
            # 持久化结果
            await self._persist_result(result)
            
            # 发送完成事件
            await self._stream_to_websocket(request, {
                "type": "execution_complete",
                "status": result.status.value,
                "duration_ms": result.duration_ms,
            })
        
        return result
    
    async def _stream_to_websocket(self, request: ExecutionRequest, msg: Dict) -> None:
        """将输出流式转发到 WebSocket"""
        # 发布到 Redis Pub/Sub
        channel = f"ws:session:{request.session_id}"
        await self.redis.publish(channel, json.dumps({
            "type": "sandbox.output_stream",
            "execution_id": request.execution_id,
            "payload": msg,
        }))
    
    async def _persist_execution(self, request: ExecutionRequest) -> None:
        """持久化执行记录"""
        await self.db.execute(
            """
            INSERT INTO executions (id, session_id, artifact_id, code, language, status, timeout, submitted_at)
            VALUES (:id, :sid, :aid, :code, :lang, :status, :timeout, :submitted)
            """,
            {
                "id": request.execution_id,
                "sid": request.session_id,
                "aid": request.artifact_id,
                "code": request.code,
                "lang": request.language,
                "status": ExecutionStatus.PENDING.value,
                "timeout": request.timeout,
                "submitted": request.submitted_at,
            },
        )
    
    async def _update_status(self, execution_id: str, status: ExecutionStatus) -> None:
        """更新执行状态"""
        await self.db.execute(
            "UPDATE executions SET status = :status WHERE id = :id",
            {"status": status.value, "id": execution_id},
        )
    
    async def _persist_result(self, result: ExecutionResult) -> None:
        """持久化执行结果"""
        await self.db.execute(
            """
            UPDATE executions SET
                status = :status,
                stdout = :stdout,
                stderr = :stderr,
                error_info = :error,
                started_at = :started,
                finished_at = :finished,
                duration_ms = :duration
            WHERE id = :id
            """,
            {
                "status": result.status.value,
                "stdout": "\n".join(result.stdout),
                "stderr": "\n".join(result.stderr),
                "error": json.dumps(result.error_info) if result.error_info else None,
                "started": result.started_at,
                "finished": result.finished_at,
                "duration": result.duration_ms,
                "id": result.execution_id,
            },
        )
        
        # 持久化输出
        for output in result.outputs:
            await self.db.execute(
                """
                INSERT INTO execution_outputs (id, execution_id, output_type, mime_type, data, metadata, created_at)
                VALUES (:id, :eid, :otype, :mime, :data, :meta, :created)
                """,
                {
                    "id": str(uuid.uuid4()),
                    "eid": result.execution_id,
                    "otype": output.get("output_type", "display_data"),
                    "mime": output.get("mime_type", "application/json"),
                    "data": json.dumps(output.get("data", {})),
                    "meta": json.dumps(output.get("metadata", {})),
                    "created": datetime.utcnow(),
                },
            )
    
    async def _get_next_chunk(self, execution_id: str) -> Optional[Dict]:
        """从 Redis 流获取下一个输出块"""
        # 简化为从 Redis List 中 pop
        key = f"execution:{execution_id}:chunks"
        chunk = await self.redis.lpop(key)
        return json.loads(chunk) if chunk else None


class ResultCollector:
    """结果收集器与序列化器
    
    职责：
    - 处理 Jupyter display_data 消息
    - 序列化图表（PNG/JPEG/SVG → JSON 或文件）
    - DataFrame 序列化（CSV/JSON/HTML）
    - 结果元数据提取
    """
    
    def __init__(self, object_store: Any, max_inline_size: int = 1024 * 1024):
        """
        Args:
            object_store: MinIO/S3 客户端，用于存储大文件
            max_inline_size: 内联传输的最大大小（默认 1MB）
        """
        self.store = object_store
        self.max_inline = max_inline_size
    
    async def process_display_data(
        self,
        execution_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """处理 display_data，序列化输出
        
        支持的 MIME 类型：
        - image/png, image/jpeg, image/svg+xml → 上传对象存储，返回 URL
        - application/vnd.plotly.v1+json → 直接透传
        - application/vnd.vega.v5+json → 直接透传
        - text/html → 清理后返回
        - text/csv, application/json → 直接返回
        """
        result = {
            "execution_id": execution_id,
            "timestamp": datetime.utcnow().isoformat(),
            "formats": [],
        }
        
        for mime_type, content in data.items():
            if mime_type == "application/vnd.plotly.v1+json":
                result["formats"].append({
                    "type": "plotly",
                    "mime_type": mime_type,
                    "data": content if isinstance(content, dict) else json.loads(content),
                })
            
            elif mime_type == "image/png":
                # 解码 base64
                image_bytes = base64.b64decode(content) if isinstance(content, str) else content
                
                if len(image_bytes) > self.max_inline:
                    # 上传对象存储
                    url = await self._upload_to_store(
                        f"executions/{execution_id}/output.png",
                        image_bytes,
                        "image/png",
                    )
                    result["formats"].append({
                        "type": "image",
                        "mime_type": "image/png",
                        "url": url,
                        "size": len(image_bytes),
                    })
                else:
                    result["formats"].append({
                        "type": "image",
                        "mime_type": "image/png",
                        "data": base64.b64encode(image_bytes).decode(),
                        "inline": True,
                    })
            
            elif mime_type == "text/html":
                # 清理 HTML（XSS 防护）
                cleaned = self._sanitize_html(content)
                result["formats"].append({
                    "type": "html",
                    "mime_type": "text/html",
                    "data": cleaned,
                })
            
            elif mime_type == "text/plain":
                result["text"] = content
                result["formats"].append({
                    "type": "text",
                    "mime_type": "text/plain",
                    "data": content,
                })
        
        return result
    
    async def process_dataframe(
        self,
        execution_id: str,
        df_json: str,
    ) -> Dict[str, Any]:
        """处理 DataFrame 输出"""
        df_data = json.loads(df_json)
        
        return {
            "type": "dataframe",
            "execution_id": execution_id,
            "columns": df_data.get("columns", []),
            "index": df_data.get("index", []),
            "data": df_data.get("data", []),
            "shape": df_data.get("shape", [0, 0]),
        }
    
    def _sanitize_html(self, html: str) -> str:
        """清理 HTML，移除危险标签和属性"""
        import bleach
        
        allowed_tags = [
            "div", "span", "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
            "table", "thead", "tbody", "tr", "td", "th", "pre", "code",
            "strong", "em", "b", "i", "u", "a", "img", "style",
        ]
        allowed_attrs = {
            "*": ["class", "id", "style"],
            "a": ["href", "title"],
            "img": ["src", "alt", "width", "height"],
            "table": ["border", "cellpadding", "cellspacing"],
        }
        allowed_styles = [
            "color", "background-color", "font-size", "font-weight",
            "text-align", "margin", "padding", "border", "width", "height",
        ]
        
        return bleach.clean(
            html,
            tags=allowed_tags,
            attributes=allowed_attrs,
            styles=allowed_styles,
            strip=True,
        )
    
    async def _upload_to_store(
        self,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        """上传数据到对象存储"""
        # MinIO/S3 上传
        bucket = "omicshub-executions"
        await self.store.put_object(
            bucket_name=bucket,
            object_name=key,
            data=data,
            length=len(data),
            content_type=content_type,
        )
        return f"/api/v1/files/executions/{key}"
```

---

### 2.3 代码安全扫描器

```python
# app/copilot/security.py

class CodeSafetyChecker:
    """代码安全检查器
    
    检测范围：
    - 危险系统调用（rm -rf /, mkfs, dd 等）
    - 网络操作（curl/wget 外部 URL）
    - 文件系统越界访问（/etc, /proc 等）
    - 敏感信息泄露（API Key、密码）
    - Python 危险模块（os.system, subprocess, eval, exec）
    """
    
    DANGEROUS_PATTERNS = [
        # 文件系统破坏
        r"rm\s+-rf\s+/[\s;]",
        r"mkfs\.\w+",
        r"dd\s+if=.*of=/dev/[sh]d",
        r">\s*/dev/[sh]d[a-z]",
        r":\(\)\{\s*:\|:\&\s*\};:",  # fork bomb
        
        # 系统调用
        r"os\.system\s*\(",
        r"subprocess\.\w+\s*\(",
        r"eval\s*\(",
        r"exec\s*\(",
        r"__import__\s*\(",
        r"compile\s*\(",
        
        # 网络操作
        r"urllib\.request\.urlopen",
        r"requests\.(get|post|put|delete)\s*\(\s*['\"]https?://",
        r"socket\.(socket|connect)",
        
        # 文件越界
        r"open\s*\(\s*['\"]/etc/",
        r"open\s*\(\s*['\"]/proc/",
        r"open\s*\(\s*['\"]/sys/",
        
        # 敏感信息
        r"(api[_-]?key|password|secret|token)\s*=\s*['\"][\w-]+",
        r"os\.environ\[.*\]",
        r"environ\.get\s*\(",
    ]
    
    # 允许的安全模式（白名单）
    SAFE_PATTERNS = [
        r"rm\s+-rf\s+/tmp/execution/",  # 允许清理自己的临时目录
        r"os\.path\.(join|exists|isdir|isfile)",  # 安全的 os.path 操作
    ]
    
    def __init__(self):
        import re
        self.dangerous_patterns = [re.compile(p, re.IGNORECASE) for p in self.DANGEROUS_PATTERNS]
        self.safe_patterns = [re.compile(p, re.IGNORECASE) for p in self.SAFE_PATTERNS]
    
    def scan(self, code: str) -> str:
        """扫描代码，返回处理后的代码
        
        发现危险操作时：
        - 如果匹配白名单，允许通过
        - 否则注释掉危险行并添加警告
        """
        lines = code.split("\n")
        processed = []
        
        for i, line in enumerate(lines, 1):
            is_safe = any(p.search(line) for p in self.safe_patterns)
            if is_safe:
                processed.append(line)
                continue
            
            is_dangerous = any(p.search(line) for p in self.dangerous_patterns)
            if is_dangerous:
                processed.append(f"# [SECURITY] Line {i} blocked by safety checker: {line.strip()}")
                processed.append(f'raise SecurityError("Dangerous operation detected at line {i}")')
            else:
                processed.append(line)
        
        return "\n".join(processed)
    
    def validate(self, code: str) -> Dict[str, Any]:
        """验证代码安全性，返回详细报告"""
        violations = []
        lines = code.split("\n")
        
        for i, line in enumerate(lines, 1):
            is_safe = any(p.search(line) for p in self.safe_patterns)
            if is_safe:
                continue
            
            for pattern in self.dangerous_patterns:
                if pattern.search(line):
                    violations.append({
                        "line": i,
                        "code": line.strip(),
                        "pattern": pattern.pattern,
                        "severity": "critical",
                    })
        
        return {
            "is_safe": len(violations) == 0,
            "violations": violations,
            "total_lines": len(lines),
        }


class SecurityError(Exception):
    """安全检查异常"""
    pass


class QueueFullError(Exception):
    """执行队列已满"""
    pass
```

---

## 3. WebSocket 事件协议

### 3.1 事件类型总览

在已有 WebSocket 协议（`chat.message`, `chat.stream` 等）基础上，新增以下 Copilot 和沙盒相关事件：

| 事件类型 | 方向 | 描述 |
|---|---|---|
| `copilot.artifact_create` | S→C | 创建新 Artifact |
| `copilot.artifact_update` | C→S | 用户更新 Artifact 代码 |
| `copilot.artifact_execute` | C→S | 请求执行 Artifact |
| `copilot.artifact_result` | S→C | 执行结果（图表/表格/文本） |
| `copilot.artifact_error` | S→C | 执行错误（Traceback） |
| `copilot.sandbox_status` | S→C | 沙盒状态变更通知 |
| `copilot.thinking_step` | S→C | Agent 思考步骤流式展示 |
| `sandbox.output_stream` | S→C | stdout/stderr 流式输出 |
| `sandbox.execution_start` | S→C | 执行开始通知 |
| `sandbox.execution_complete` | S→C | 执行完成通知 |
| `sandbox.package_install` | C→S / S→C | 包安装请求/结果 |
| `sandbox.kernel_restart` | C→S | 请求重启 Kernel |
| `sandbox.interrupt` | C→S | 中断当前执行 |

> **方向说明**：C→C = Client→Server，S→C = Server→Client

### 3.2 事件消息格式

```json
// copilot.artifact_create — Server → Client
{
  "type": "copilot.artifact_create",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "artifact_id": "uuid",
    "code": "import scanpy as sc\nadata = sc.read_h5ad('/data/user/sample.h5ad')\nsc.pp.neighbors(adata)\nsc.tl.umap(adata)\nsc.pl.umap(adata, save='/tmp/execution/umap.png')",
    "language": "python",
    "title": "单细胞UMAP可视化",
    "description": "基于Scanpy的UMAP降维与可视化",
    "auto_execute": false,
    "version": 1,
    "metadata": {
      "model": "kimi-k2",
      "prompt_tokens": 256,
      "completion_tokens": 128
    }
  }
}

// copilot.artifact_update — Client → Server
{
  "type": "copilot.artifact_update",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "artifact_id": "uuid",
    "code": "修改后的代码...",
    "cursor_position": 150,
    "version": 2
  }
}

// copilot.artifact_execute — Client → Server
{
  "type": "copilot.artifact_execute",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "artifact_id": "uuid",
    "code": "要执行的代码（可选，不填则用当前artifact的code）",
    "timeout": 300,
    "priority": 0,
    "language": "python"
  }
}

// copilot.artifact_result — Server → Client（图表结果）
{
  "type": "copilot.artifact_result",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "artifact_id": "uuid",
    "execution_id": "uuid",
    "status": "success",
    "outputs": [
      {
        "type": "plotly",
        "mime_type": "application/vnd.plotly.v1+json",
        "data": {
          "data": [{"x": [1,2,3], "y": [4,5,6], "type": "scatter"}],
          "layout": {"title": "UMAP Visualization"}
        }
      },
      {
        "type": "image",
        "mime_type": "image/png",
        "url": "/api/v1/files/executions/uuid/output.png",
        "size": 45231
      }
    ],
    "text": "UMAP computation finished in 2.3s",
    "execution_time_ms": 2300
  }
}

// copilot.artifact_result — Server → Client（DataFrame结果）
{
  "type": "copilot.artifact_result",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "artifact_id": "uuid",
    "execution_id": "uuid",
    "status": "success",
    "outputs": [
      {
        "type": "dataframe",
        "shape": [100, 5],
        "columns": ["cell_type", "n_genes", "n_counts", "percent_mito", "leiden"],
        "preview": [
          {"cell_type": "T_cell", "n_genes": 3000, "n_counts": 15000, "percent_mito": 0.05, "leiden": "0"},
          {"cell_type": "B_cell", "n_genes": 2500, "n_counts": 12000, "percent_mito": 0.03, "leiden": "1"}
        ]
      }
    ]
  }
}

// copilot.artifact_error — Server → Client
{
  "type": "copilot.artifact_error",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "artifact_id": "uuid",
    "execution_id": "uuid",
    "error": {
      "type": "ImportError",
      "message": "No module named 'scanpy'",
      "traceback": [
        "Traceback (most recent call last):",
        "  File \"<ipython-input-1>\", line 1, in <module>",
        "    import scanpy as sc",
        "ImportError: No module named 'scanpy'"
      ],
      "suggestion": "请尝试安装 scanpy: pip install scanpy"
    }
  }
}

// copilot.sandbox_status — Server → Client
{
  "type": "copilot.sandbox_status",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "session_id": "uuid",
    "status": "ready",
    "container_id": "abc123...",
    "kernel_id": "kernel-uuid",
    "resource_usage": {
      "cpu_percent": 15.2,
      "memory_mb": 512,
      "memory_limit_mb": 8192
    },
    "packages": ["scanpy==1.9.6", "anndata==0.9.2"],
    "last_activity": "2024-01-01T00:00:00Z"
  }
}

// copilot.thinking_step — Server → Client（流式）
{
  "type": "copilot.thinking_step",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "step_id": "uuid",
    "step_type": "analysis | planning | code_generation | reflection",
    "content": "用户需要做一个UMAP可视化。我需要：1. 加载单细胞数据 2. 预处理 3. 计算邻居图 4. UMAP降维 5. 绘制图表",
    "is_final": false
  }
}

// sandbox.output_stream — Server → Client（流式）
{
  "type": "sandbox.output_stream",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "execution_id": "uuid",
    "stream": "stdout",
    "text": "Computing neighbors...\n",
    "is_partial": true
  }
}

// sandbox.execution_start — Server → Client
{
  "type": "sandbox.execution_start",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "execution_id": "uuid",
    "artifact_id": "uuid",
    "session_id": "uuid",
    "queued_duration_ms": 150,
    "estimated_duration_ms": 5000
  }
}

// sandbox.execution_complete — Server → Client
{
  "type": "sandbox.execution_complete",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "execution_id": "uuid",
    "artifact_id": "uuid",
    "status": "success",
    "duration_ms": 3200,
    "output_count": 2,
    "stdout_lines": 15,
    "stderr_lines": 0
  }
}

// sandbox.package_install — Client → Server
{
  "type": "sandbox.package_install",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "session_id": "uuid",
    "packages": ["scanpy==1.9.6", "scvi-tools"],
    "channel": "conda-forge",
    "timeout": 300
  }
}

// sandbox.package_install — Server → Client（结果）
{
  "type": "sandbox.package_install",
  "timestamp": "2024-01-01T00:00:00Z",
  "payload": {
    "session_id": "uuid",
    "status": "success",
    "installed": ["scanpy==1.9.6", "scvi-tools==1.0.4"],
    "failed": [],
    "duration_ms": 45000
  }
}
```

---

## 4. 数据库表设计

### 4.1 新增表

```sql
-- ============================================================
-- 表 1：artifacts — 代码 Artifact 存储
-- ============================================================
CREATE TABLE IF NOT EXISTS artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id      UUID REFERENCES sandbox_sessions(id),
    
    -- 基本信息
    title           VARCHAR(255) NOT NULL,
    description     TEXT,
    language        VARCHAR(20) NOT NULL DEFAULT 'python' 
                    CHECK (language IN ('python', 'r', 'bash', 'sql', 'julia')),
    
    -- 代码内容（限制 100KB，超过建议用对象存储）
    code            TEXT NOT NULL DEFAULT '',
    code_size       INT NOT NULL DEFAULT 0,
    
    -- 状态管理
    status          VARCHAR(30) NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'editing', 'executing', 'success', 'error', 'outdated')),
    
    -- 版本管理（链表结构）
    version         INT NOT NULL DEFAULT 1,
    parent_id       UUID REFERENCES artifacts(id),
    
    -- 执行关联
    last_execution_id UUID,
    
    -- 配置
    auto_execute    BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- 元数据（JSONB 灵活存储）
    metadata        JSONB NOT NULL DEFAULT '{}',
    
    -- 时间戳
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 索引
    CONSTRAINT code_size_check CHECK (code_size <= 102400)
);

-- 索引
CREATE INDEX idx_artifacts_user_id ON artifacts(user_id, created_at DESC);
CREATE INDEX idx_artifacts_session_id ON artifacts(session_id);
CREATE INDEX idx_artifacts_status ON artifacts(status) WHERE status IN ('draft', 'editing', 'executing');
CREATE INDEX idx_artifacts_version_chain ON artifacts(parent_id);

-- ============================================================
-- 表 2：sandbox_sessions — 沙盒会话管理
-- ============================================================
CREATE TABLE IF NOT EXISTS sandbox_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- 容器信息
    container_id    VARCHAR(128),          -- Docker container ID
    container_name  VARCHAR(255) NOT NULL,
    
    -- 状态
    status          VARCHAR(30) NOT NULL DEFAULT 'creating'
                    CHECK (status IN ('creating', 'ready', 'executing', 'idle', 'paused', 'error', 'destroyed')),
    
    -- Kernel 信息
    kernel_id       VARCHAR(128),
    kernel_connection_info JSONB,
    
    -- 语言环境
    language        VARCHAR(20) NOT NULL DEFAULT 'python',
    
    -- 资源限制（JSONB 灵活配置）
    resource_limits JSONB NOT NULL DEFAULT '{
        "cpu": "4.0",
        "memory": "8g",
        "disk": "20g",
        "shm_size": "2g"
    }',
    
    -- 挂载卷配置
    mounted_volumes JSONB NOT NULL DEFAULT '[]',
    
    -- 已安装包列表
    packages        TEXT[] NOT NULL DEFAULT '{}',
    
    -- 活动时间戳
    last_activity   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    
    -- 元数据
    metadata        JSONB NOT NULL DEFAULT '{}'
);

-- 索引
CREATE INDEX idx_sandbox_sessions_user_id ON sandbox_sessions(user_id, status);
CREATE INDEX idx_sandbox_sessions_status ON sandbox_sessions(status) WHERE status NOT IN ('destroyed', 'error');
CREATE INDEX idx_sandbox_sessions_activity ON sandbox_sessions(last_activity) WHERE status IN ('idle', 'paused');

-- ============================================================
-- 表 3：executions — 代码执行记录
-- ============================================================
CREATE TABLE IF NOT EXISTS executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sandbox_sessions(id) ON DELETE CASCADE,
    artifact_id     UUID REFERENCES artifacts(id),
    
    -- 执行的代码（完整记录，便于审计）
    code            TEXT NOT NULL,
    language        VARCHAR(20) NOT NULL DEFAULT 'python',
    
    -- 执行状态
    status          VARCHAR(30) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'success', 'error', 'timeout', 'cancelled')),
    
    -- 超时配置
    timeout         INT NOT NULL DEFAULT 300,  -- 秒
    
    -- 输出摘要
    stdout          TEXT DEFAULT '',
    stderr          TEXT DEFAULT '',
    error_info      JSONB,
    
    -- 性能指标
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_ms     INT,
    
    -- 资源使用峰值
    peak_memory_mb  NUMERIC(10, 2),
    peak_cpu_percent NUMERIC(5, 2),
    
    -- 时间戳
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 元数据
    metadata        JSONB NOT NULL DEFAULT '{}'
);

-- 索引
CREATE INDEX idx_executions_session_id ON executions(session_id, submitted_at DESC);
CREATE INDEX idx_executions_artifact_id ON executions(artifact_id);
CREATE INDEX idx_executions_status ON executions(status) WHERE status IN ('pending', 'running');
CREATE INDEX idx_executions_submitted ON executions(submitted_at);

-- ============================================================
-- 表 4：execution_outputs — 执行输出结果
-- ============================================================
CREATE TABLE IF NOT EXISTS execution_outputs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id    UUID NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    
    -- 输出类型
    output_type     VARCHAR(50) NOT NULL
                    CHECK (output_type IN ('display_data', 'execute_result', 'stream', 'error', 'dataframe', 'image', 'plotly', 'html')),
    
    -- MIME 类型
    mime_type       VARCHAR(100) NOT NULL,
    
    -- 数据存储策略：
    -- 1. 小数据（< 64KB）直接存储在 data_json
    -- 2. 大数据存储在对象存储，data_json 存 URL 和元数据
    data_json       JSONB NOT NULL,
    
    -- 对象存储引用（可选）
    object_key      VARCHAR(512),
    object_size     INT,
    
    -- 元数据
    metadata        JSONB NOT NULL DEFAULT '{}',
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_execution_outputs_execution_id ON execution_outputs(execution_id);
CREATE INDEX idx_execution_outputs_type ON execution_outputs(output_type);

-- ============================================================
-- 表 5：artifact_versions — Artifact 版本历史（可选，如果用链表足够可省略）
-- ============================================================
CREATE TABLE IF NOT EXISTS artifact_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id     UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    version         INT NOT NULL,
    code            TEXT NOT NULL,
    code_diff       TEXT,                    -- 与上一版本的 diff
    changed_by      VARCHAR(50) NOT NULL DEFAULT 'ai',  -- 'ai' | 'user'
    change_reason   TEXT,                    -- 变更原因
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(artifact_id, version)
);

CREATE INDEX idx_artifact_versions_artifact_id ON artifact_versions(artifact_id, version DESC);
```

### 4.2 数据库迁移脚本

```sql
-- migration: V009__add_copilot_sandbox_tables.sql
-- 创建 Copilot 和沙盒相关表

BEGIN;

-- 先创建依赖扩展
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 创建表
\i artifacts.sql
\i sandbox_sessions.sql
\i executions.sql
\i execution_outputs.sql
\i artifact_versions.sql

-- 添加 comments 说明
COMMENT ON TABLE artifacts IS 'AI 生成的代码 Artifact，包含代码、元数据和执行关联';
COMMENT ON TABLE sandbox_sessions IS '用户沙盒会话，映射到 Docker 容器';
COMMENT ON TABLE executions IS '代码执行记录，每次执行一条记录';
COMMENT ON TABLE execution_outputs IS '执行输出的具体结果（图表、表格、文本）';
COMMENT ON TABLE artifact_versions IS 'Artifact 版本历史（可选优化表）';

-- 添加触发器：自动更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER artifacts_updated_at
    BEFORE UPDATE ON artifacts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER sandbox_sessions_updated_at
    BEFORE UPDATE ON sandbox_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMIT;
```

---

## 5. 关键接口定义

### 5.1 REST API

```yaml
# Copilot Service REST API
openapi: 3.0.3
info:
  title: OmicHub Copilot API
  version: 1.0.0
  description: AI Copilot 与沙盒管理接口

paths:
  # ──────────────────────────────────────────
  # Artifact 管理
  # ──────────────────────────────────────────
  /api/v1/copilot/artifacts:
    get:
      summary: 列出用户的 Artifacts
      parameters:
        - name: session_id
          in: query
          schema:
            type: string
            format: uuid
        - name: limit
          in: query
          schema:
            type: integer
            default: 50
            maximum: 100
        - name: status
          in: query
          schema:
            type: string
            enum: [draft, editing, executing, success, error, outdated]
      responses:
        200:
          description: Artifact 列表
          content:
            application/json:
              schema:
                type: object
                properties:
                  items:
                    type: array
                    items:
                      $ref: '#/components/schemas/Artifact'
                  total:
                    type: integer

    post:
      summary: 创建新 Artifact
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [title, language, code]
              properties:
                title:
                  type: string
                  maxLength: 255
                description:
                  type: string
                language:
                  type: string
                  enum: [python, r, bash, sql, julia]
                code:
                  type: string
                  maxLength: 102400
                auto_execute:
                  type: boolean
                  default: false
                metadata:
                  type: object
      responses:
        201:
          description: Artifact 创建成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Artifact'

  /api/v1/copilot/artifacts/{artifact_id}:
    get:
      summary: 获取 Artifact 详情
      parameters:
        - name: artifact_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        200:
          description: Artifact 详情
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Artifact'

    put:
      summary: 更新 Artifact 代码（创建新版本）
      parameters:
        - name: artifact_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [code]
              properties:
                code:
                  type: string
                  maxLength: 102400
                title:
                  type: string
      responses:
        200:
          description: 更新成功，返回新版本 Artifact
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Artifact'

    delete:
      summary: 删除 Artifact（及关联版本和执行记录）
      parameters:
        - name: artifact_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        204:
          description: 删除成功

  /api/v1/copilot/artifacts/{artifact_id}/execute:
    post:
      summary: 执行 Artifact
      parameters:
        - name: artifact_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                code:
                  type: string
                  description: 可选的覆盖代码
                timeout:
                  type: integer
                  default: 300
                  maximum: 3600
                priority:
                  type: integer
                  default: 0
      responses:
        202:
          description: 执行已提交
          content:
            application/json:
              schema:
                type: object
                properties:
                  execution_id:
                    type: string
                    format: uuid
                  status:
                    type: string
                    enum: [pending, running]
                  estimated_wait_ms:
                    type: integer

  /api/v1/copilot/artifacts/{artifact_id}/executions/{execution_id}:
    get:
      summary: 获取执行详情和结果
      parameters:
        - name: artifact_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: execution_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: include_outputs
          in: query
          schema:
            type: boolean
            default: true
      responses:
        200:
          description: 执行详情
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Execution'

  /api/v1/copilot/artifacts/{artifact_id}/versions:
    get:
      summary: 获取 Artifact 版本历史
      parameters:
        - name: artifact_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        200:
          description: 版本列表

  # ──────────────────────────────────────────
  # 沙盒会话管理
  # ──────────────────────────────────────────
  /api/v1/copilot/sandbox/status:
    get:
      summary: 获取当前用户的沙盒状态
      responses:
        200:
          description: 沙盒状态
          content:
            application/json:
              schema:
                type: object
                properties:
                  session_id:
                    type: string
                    format: uuid
                  status:
                    type: string
                    enum: [creating, ready, executing, idle, paused, error, destroyed]
                  container:
                    type: object
                    properties:
                      id:
                        type: string
                      name:
                        type: string
                      health:
                        type: string
                  resource_usage:
                    type: object
                    properties:
                      cpu_percent:
                        type: number
                      memory_mb:
                        type: number
                      memory_limit_mb:
                        type: number
                  packages:
                    type: array
                    items:
                      type: string

  /api/v1/copilot/sandbox/sessions:
    post:
      summary: 创建新沙盒会话
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                language:
                  type: string
                  enum: [python, r]
                  default: python
      responses:
        201:
          description: 会话创建成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SandboxSession'

    get:
      summary: 列出用户沙盒会话
      responses:
        200:
          description: 会话列表
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/SandboxSession'

  /api/v1/copilot/sandbox/sessions/{session_id}:
    delete:
      summary: 销毁沙盒会话
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        204:
          description: 销毁成功

  /api/v1/copilot/sandbox/packages:
    post:
      summary: 安装包
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [packages]
              properties:
                session_id:
                  type: string
                packages:
                  type: array
                  items:
                    type: string
                  example: ["scanpy==1.9.6", "scvi-tools"]
                channel:
                  type: string
                  default: "conda-forge"
                manager:
                  type: string
                  enum: [conda, pip]
                  default: conda
                timeout:
                  type: integer
                  default: 300
      responses:
        202:
          description: 安装任务已提交
          content:
            application/json:
              schema:
                type: object
                properties:
                  task_id:
                    type: string
                  status:
                    type: string

  /api/v1/copilot/sandbox/packages/{session_id}:
    get:
      summary: 获取已安装包列表
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        200:
          description: 包列表
          content:
            application/json:
              schema:
                type: array
                items:
                  type: string

  /api/v1/copilot/sandbox/heartbeat:
    post:
      summary: 沙盒会话心跳
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [session_id]
              properties:
                session_id:
                  type: string
                artifact_count:
                  type: integer
      responses:
        200:
          description: 心跳响应
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  ttl_remaining:
                    type: integer

  /api/v1/copilot/sandbox/interrupt/{session_id}:
    post:
      summary: 中断当前执行
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
      responses:
        200:
          description: 中断信号已发送

  /api/v1/copilot/sandbox/restart/{session_id}:
    post:
      summary: 重启 Kernel
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
      responses:
        200:
          description: Kernel 已重启

  # ──────────────────────────────────────────
  # 执行记录
  # ──────────────────────────────────────────
  /api/v1/copilot/executions:
    get:
      summary: 列出执行记录
      parameters:
        - name: session_id
          in: query
          schema:
            type: string
        - name: artifact_id
          in: query
          schema:
            type: string
        - name: status
          in: query
          schema:
            type: string
        - name: limit
          in: query
          schema:
            type: integer
            default: 50
      responses:
        200:
          description: 执行记录列表

  /api/v1/copilot/executions/{execution_id}/outputs:
    get:
      summary: 获取执行输出
      parameters:
        - name: execution_id
          in: path
          required: true
          schema:
            type: string
      responses:
        200:
          description: 输出列表
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/ExecutionOutput'

  /api/v1/copilot/executions/{execution_id}/cancel:
    post:
      summary: 取消执行
      parameters:
        - name: execution_id
          in: path
          required: true
          schema:
            type: string
      responses:
        200:
          description: 取消请求已处理

components:
  schemas:
    Artifact:
      type: object
      properties:
        id:
          type: string
          format: uuid
        user_id:
          type: string
        session_id:
          type: string
        title:
          type: string
        description:
          type: string
        language:
          type: string
        code:
          type: string
        status:
          type: string
        version:
          type: integer
        parent_id:
          type: string
        auto_execute:
          type: boolean
        metadata:
          type: object
        created_at:
          type: string
          format: date-time
        updated_at:
          type: string
          format: date-time

    SandboxSession:
      type: object
      properties:
        id:
          type: string
        user_id:
          type: string
        container_id:
          type: string
        container_name:
          type: string
        status:
          type: string
        kernel_id:
          type: string
        language:
          type: string
        resource_limits:
          type: object
        packages:
          type: array
          items:
            type: string
        last_activity:
          type: string
          format: date-time

    Execution:
      type: object
      properties:
        id:
          type: string
        session_id:
          type: string
        artifact_id:
          type: string
        code:
          type: string
        language:
          type: string
        status:
          type: string
        stdout:
          type: string
        stderr:
          type: string
        error_info:
          type: object
        started_at:
          type: string
        finished_at:
          type: string
        duration_ms:
          type: integer

    ExecutionOutput:
      type: object
      properties:
        id:
          type: string
        execution_id:
          type: string
        output_type:
          type: string
        mime_type:
          type: string
        data_json:
          type: object
        object_key:
          type: string
        created_at:
          type: string
```

### 5.2 WebSocket 消息格式规范

```typescript
// WebSocket 消息通用接口
interface WebSocketMessage {
  type: string;           // 事件类型
  timestamp: string;      // ISO 8601 时间戳
  payload: unknown;       // 事件负载（根据类型不同）
}

// ──────────────────────────────────────────
// Client → Server 消息
// ──────────────────────────────────────────

// 发送对话消息（触发 AI 响应）
interface CopilotMessage {
  type: "copilot.message";
  payload: {
    content: string;           // 用户消息内容
    artifact_id?: string;      // 当前关联的 Artifact（可选）
    context_files?: string[];  // 引用的文件路径
  };
}

// 更新 Artifact 代码
interface ArtifactUpdate {
  type: "copilot.artifact_update";
  payload: {
    artifact_id: string;
    code: string;
    from_version: number;
  };
}

// 请求执行
interface ArtifactExecute {
  type: "copilot.artifact_execute";
  payload: {
    artifact_id: string;
    override_code?: string;    // 覆盖执行代码（可选）
    timeout?: number;          // 覆盖超时（可选）
  };
}

// 包安装请求
interface PackageInstall {
  type: "sandbox.package_install";
  payload: {
    session_id: string;
    packages: string[];
    manager?: "conda" | "pip";
  };
}

// 心跳
interface Heartbeat {
  type: "sandbox.heartbeat";
  payload: {
    session_id: string;
  };
}

// ──────────────────────────────────────────
// Server → Client 消息
// ──────────────────────────────────────────

// AI 思考步骤（流式）
interface ThinkingStep {
  type: "copilot.thinking_step";
  payload: {
    step_id: string;
    step_type: "analysis" | "planning" | "code_generation" | "reflection" | "tool_call";
    content: string;
    is_final: boolean;
  };
}

// Artifact 创建通知
interface ArtifactCreate {
  type: "copilot.artifact_create";
  payload: {
    artifact_id: string;
    code: string;
    language: "python" | "r" | "bash";
    title: string;
    auto_execute: boolean;
    metadata?: Record<string, unknown>;
  };
}

// 代码流式片段（增量更新）
interface ArtifactStream {
  type: "copilot.artifact_stream";
  payload: {
    artifact_id: string;
    chunk: string;            // 增量代码片段
    is_complete: boolean;     // 是否完成
  };
}

// 执行结果
interface ArtifactResult {
  type: "copilot.artifact_result";
  payload: {
    artifact_id: string;
    execution_id: string;
    status: "success" | "error";
    outputs: OutputFormat[];
    text?: string;
    execution_time_ms: number;
  };
}

// 输出格式联合类型
type OutputFormat =
  | PlotlyOutput
  | ImageOutput
  | DataFrameOutput
  | HtmlOutput
  | TextOutput;

interface PlotlyOutput {
  type: "plotly";
  mime_type: "application/vnd.plotly.v1+json";
  data: {
    data: unknown[];
    layout: Record<string, unknown>;
  };
}

interface ImageOutput {
  type: "image";
  mime_type: "image/png" | "image/jpeg" | "image/svg+xml";
  data?: string;            // base64 编码（小图内联）
  url?: string;             // 对象存储 URL（大图）
  size?: number;
  inline: boolean;
}

interface DataFrameOutput {
  type: "dataframe";
  shape: [number, number];   // [rows, columns]
  columns: string[];
  preview: Record<string, unknown>[];  // 前N行预览
}

interface HtmlOutput {
  type: "html";
  mime_type: "text/html";
  data: string;             // 清理后的 HTML
}

interface TextOutput {
  type: "text";
  mime_type: "text/plain";
  data: string;
}

// 执行错误
interface ArtifactError {
  type: "copilot.artifact_error";
  payload: {
    artifact_id: string;
    execution_id: string;
    error: {
      type: string;
      message: string;
      traceback: string[];
      suggestion?: string;
    };
  };
}

// 沙盒状态变更
interface SandboxStatus {
  type: "copilot.sandbox_status";
  payload: {
    session_id: string;
    status: "creating" | "ready" | "executing" | "idle" | "paused" | "error" | "destroyed";
    resource_usage?: {
      cpu_percent: number;
      memory_mb: number;
      memory_limit_mb: number;
    };
  };
}

// stdout/stderr 流式输出
interface OutputStream {
  type: "sandbox.output_stream";
  payload: {
    execution_id: string;
    stream: "stdout" | "stderr";
    text: string;
    is_partial: boolean;
  };
}

// 执行开始
interface ExecutionStart {
  type: "sandbox.execution_start";
  payload: {
    execution_id: string;
    artifact_id: string;
    queued_duration_ms: number;
  };
}

// 执行完成
interface ExecutionComplete {
  type: "sandbox.execution_complete";
  payload: {
    execution_id: string;
    artifact_id: string;
    status: "success" | "error" | "timeout" | "cancelled";
    duration_ms: number;
  };
}

// 包安装结果
interface PackageInstallResult {
  type: "sandbox.package_install";
  payload: {
    session_id: string;
    status: "in_progress" | "success" | "failed";
    current_package?: string;
    progress?: number;        // 0-100
    installed?: string[];
    failed?: Array<{ package: string; error: string }>;
  };
}
```

---

## 6. 安全设计

### 6.1 沙盒容器安全

```yaml
# docker-compose.sandbox.yml 安全配置
services:
  sandbox-base:
    build:
      context: ./docker/sandbox
      dockerfile: Dockerfile.sandbox
    security_opt:
      - no-new-privileges:true    # 禁止提升权限
    cap_drop:
      - ALL                       # 丢弃所有 capability
    cap_add:
      - CHOWN                     # 允许修改文件所有者
      - SETUID
      - SETGID
    read_only: true                # 根文件系统只读
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=2g
    sysctls:
      - net.ipv4.ip_forward=0     # 禁止 IP 转发
      - net.ipv4.conf.all.send_redirects=0
    network_mode: "omicshub-sandbox"  # 隔离网络（桥接，无外网）
    ulimits:
      nproc: 1024                  # 最大进程数
      nofile:
        soft: 4096
        hard: 4096
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 8G
        reservations:
          cpus: '0.5'
          memory: 256M
```

### 6.2 网络安全

```python
# app/sandbox/network_policy.py

SANDBOX_NETWORK_POLICY = {
    # 容器网络配置
    "network_name": "omicshub-sandbox",
    "driver": "bridge",
    "internal": True,  # 禁止外部访问
    
    # 出站规则（默认 DENY ALL）
    "egress_rules": [
        {
            "description": "允许访问内部 API 服务",
            "destinations": ["omicshub-api", "omicshub-redis", "omicshub-postgres"],
            "ports": [8000, 6379, 5432],
            "action": "ALLOW",
        },
        {
            "description": "允许访问对象存储",
            "destinations": ["omicshub-minio"],
            "ports": [9000],
            "action": "ALLOW",
        },
        {
            "description": "允许访问内部镜像仓库",
            "destinations": ["omicshub-registry"],
            "ports": [5000],
            "action": "ALLOW",
        },
        {
            "description": "允许 DNS 解析",
            "protocol": "udp",
            "destinations": ["127.0.0.11"],  # Docker 内置 DNS
            "ports": [53],
            "action": "ALLOW",
        },
        {
            "description": "默认拒绝所有出站",
            "destinations": ["0.0.0.0/0"],
            "action": "DENY",
        },
    ],
    
    # 入站规则
    "ingress_rules": [
        {
            "description": "仅允许 API 服务访问 Kernel Gateway",
            "sources": ["omicshub-api"],
            "ports": [8888],
            "action": "ALLOW",
        },
        {
            "description": "默认拒绝所有入站",
            "sources": ["0.0.0.0/0"],
            "action": "DENY",
        },
    ],
}
```

### 6.3 文件系统安全

```python
# app/sandbox/fs_policy.py

class FilesystemPolicy:
    """文件系统访问策略"""
    
    # 只读挂载路径（容器内）
    READONLY_PATHS = [
        "/data/user",        # 用户数据
        "/data/ref",         # 参考基因组
        "/opt/conda",        # 基础 conda 环境
        "/usr",              # 系统目录
        "/lib", "/lib64",
        "/etc",
    ]
    
    # 读写挂载路径
    READWRITE_PATHS = [
        "/tmp/execution",    # 执行输出
        "/tmp",              # 临时文件
        "/home/jovyan",      # 用户 home
        "/opt/conda/envs/user",  # 用户 conda 环境
    ]
    
    # 禁止访问路径
    DENIED_PATHS = [
        "/proc",             # 进程信息
        "/sys",              # 内核参数
        "/dev",              # 设备文件
        "/etc/shadow",       # 密码文件
        "/etc/passwd",
        "/var/run/docker.sock",  # Docker socket
        "../../",            # 路径穿越
        "~/../",             # 家目录穿越
    ]
    
    @classmethod
    def validate_path(cls, path: str) -> bool:
        """验证路径是否允许访问"""
        import os
        real_path = os.path.realpath(path)
        
        for denied in cls.DENIED_PATHS:
            if real_path.startswith(denied):
                return False
        
        return True
    
    @classmethod
    def get_mount_config(cls) -> list:
        """获取 Docker 挂载配置"""
        mounts = []
        
        for path in cls.READONLY_PATHS:
            mounts.append({
                "type": "bind",
                "source": path,
                "target": path,
                "read_only": True,
            })
        
        for path in cls.READWRITE_PATHS:
            mounts.append({
                "type": "bind",
                "source": path,
                "target": path,
                "read_only": False,
            })
        
        return mounts
```

### 6.4 执行安全策略

| 策略项 | 配置值 | 说明 |
|---|---|---|
| 默认执行超时 | 300 秒 | 可通过 API 参数覆盖，最大 3600 秒 |
| 最大内存 | 8 GB | 超出 OOM Killer 终止 |
| 最大 CPU | 4 核 | cgroup cpu.cfs_quota_us |
| 最大磁盘 | 20 GB | overlayfs 大小限制 |
| 最大进程数 | 1024 | ulimit nproc |
| 最大并发执行 | 1（单 Kernel） | 队列深度 10 |
| 代码大小限制 | 100 KB | 防止超大代码 |
| 输出大小限制 | 10 MB | 超出截断 |
| 图表尺寸限制 | 4096×4096 | 防止内存炸弹 |

### 6.5 敏感信息过滤

```python
# app/copilot/sensitive_filter.py

import re
from typing import Dict, List, Optional

SENSITIVE_PATTERNS = {
    "api_key": [
        r"(?i)(api[_-]?key\s*[:=]\s*)['\"]?([a-zA-Z0-9_-]{16,})['\"]?",
        r"(?i)(x-api-key\s*:\s*)([a-zA-Z0-9_-]{16,})",
    ],
    "password": [
        r"(?i)(password\s*[:=]\s*)['\"]([^'\"]+)['\"]",
        r"(?i)(passwd\s*[:=]\s*)['\"]([^'\"]+)['\"]",
        r"(?i)(pwd\s*[:=]\s*)['\"]([^'\"]+)['\"]",
    ],
    "token": [
        r"(?i)(token\s*[:=]\s*)['\"]?([a-zA-Z0-9_-]{20,})['\"]?",
        r"(?i)(bearer\s+)([a-zA-Z0-9_-]{20,})",
    ],
    "secret": [
        r"(?i)(secret\s*[:=]\s*)['\"]([^'\"]+)['\"]",
        r"(?i)(aws_secret_access_key\s*[:=]\s*)['\"]([^'\"]+)['\"]",
    ],
    "private_key": [
        r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    ],
}

class SensitiveInfoFilter:
    """敏感信息过滤器"""
    
    MASK = "***REDACTED***"
    
    @classmethod
    def filter(cls, text: str) -> str:
        """过滤文本中的敏感信息"""
        filtered = text
        
        for category, patterns in SENSITIVE_PATTERNS.items():
            for pattern in patterns:
                def replace_match(m):
                    # 保留 key 名，替换 value
                    if len(m.groups()) >= 2:
                        return f"{m.group(1)}{cls.MASK}"
                    return cls.MASK
                
                filtered = re.sub(pattern, replace_match, filtered)
        
        return filtered
    
    @classmethod
    def scan(cls, text: str) -> List[Dict]:
        """扫描敏感信息，返回发现列表（用于审计日志）"""
        findings = []
        
        for category, patterns in SENSITIVE_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text):
                    findings.append({
                        "category": category,
                        "pattern": pattern,
                        "position": (match.start(), match.end()),
                        "matched": match.group()[:50] + "..." if len(match.group()) > 50 else match.group(),
                    })
        
        return findings
```

### 6.6 代码静态分析

```python
# app/copilot/code_analyzer.py

import ast
from typing import List, Dict, Optional

class PythonCodeAnalyzer:
    """Python 代码静态分析器"""
    
    DANGEROUS_MODULES = [
        "os.system", "os.popen", "os.spawn", "os.exec",
        "subprocess.call", "subprocess.run", "subprocess.Popen",
        "eval", "exec", "compile",
        "__import__", "importlib.import_module",
        "socket", "urllib.request", "ftplib", "telnetlib",
        "pickle", "shelve", "marshal",
        "ctypes", "ffi",
    ]
    
    DANGEROUS_BUILTINS = [
        "eval", "exec", "compile", "open", "input",
        "__import__", "breakpoint",
    ]
    
    def analyze(self, code: str) -> Dict:
        """分析代码安全性"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {
                "is_valid": False,
                "syntax_error": str(e),
                "violations": [],
            }
        
        violations = []
        
        for node in ast.walk(tree):
            # 检测危险导入
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ["os", "subprocess", "socket", "ctypes"]:
                        violations.append({
                            "type": "dangerous_import",
                            "module": alias.name,
                            "line": getattr(node, "lineno", 0),
                            "severity": "high",
                        })
            
            # 检测 from ... import ...
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in ["os", "subprocess", "socket"]:
                    for alias in node.names:
                        if alias.name in ["system", "popen", "call", "run", "Popen"]:
                            violations.append({
                                "type": "dangerous_function_import",
                                "function": f"{module}.{alias.name}",
                                "line": getattr(node, "lineno", 0),
                                "severity": "critical",
                            })
            
            # 检测危险函数调用
            if isinstance(node, ast.Call):
                func_name = self._get_func_name(node.func)
                if func_name in self.DANGEROUS_MODULES:
                    violations.append({
                        "type": "dangerous_call",
                        "function": func_name,
                        "line": getattr(node, "lineno", 0),
                        "severity": "critical",
                    })
        
        return {
            "is_valid": True,
            "is_safe": len(violations) == 0,
            "violations": violations,
            "total_lines": code.count("\n") + 1,
        }
    
    def _get_func_name(self, node) -> str:
        """获取函数调用名"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_func_name(node.value)}.{node.attr}"
        return ""
```

---

## 7. 部署与运维

### 7.1 Docker Compose 配置

```yaml
# docker-compose.copilot.yml
version: "3.8"

networks:
  omicshub-sandbox:
    name: omicshub-sandbox
    driver: bridge
    internal: true  # 无外网访问
    ipam:
      config:
        - subnet: 172.28.0.0/16

volumes:
  sandbox-packages:
    driver: local
  sandbox-execution-tmp:
    driver: local

services:
  # ──────────────────────────────
  # Copilot Service
  # ──────────────────────────────
  copilot-service:
    build:
      context: .
      dockerfile: docker/copilot/Dockerfile
    container_name: omicshub-copilot
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/omicshub
      - REDIS_URL=redis://redis:6379/0
      - KIMI_API_KEY=${KIMI_API_KEY}
      - KIMI_API_BASE=${KIMI_API_BASE}
      - SANDBOX_NETWORK=omicshub-sandbox
      - SANDBOX_BASE_IMAGE=omicshub/sandbox-base:latest
      - WARM_POOL_SIZE=5
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro  # Docker API 访问
      - ./app:/app:ro
    depends_on:
      - postgres
      - redis
    networks:
      - default
      - omicshub-sandbox
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G

  # ──────────────────────────────
  # Sandbox Pool Manager
  # ──────────────────────────────
  sandbox-manager:
    build:
      context: .
      dockerfile: docker/sandbox/Dockerfile.manager
    container_name: omicshub-sandbox-manager
    restart: unless-stopped
    environment:
      - REDIS_URL=redis://redis:6379/1
      - DOCKER_NETWORK=omicshub-sandbox
      - WARM_POOL_SIZE=5
      - MAX_POOL_SIZE=20
      - IDLE_TIMEOUT=600
      - PAUSED_TIMEOUT=1800
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - sandbox-packages:/data/packages
      - sandbox-execution-tmp:/tmp/execution
    depends_on:
      - redis
    networks:
      - default
      - omicshub-sandbox

  # ──────────────────────────────
  # Sandbox Base Image（构建目标）
  # ──────────────────────────────
  # 注：这不是运行时服务，而是构建目标
  # docker build -t omicshub/sandbox-base:latest -f docker/sandbox/Dockerfile.base .

# 核心服务已经在主 docker-compose.yml 中定义
# - postgres, redis, nginx, main-api, celery, etc.
```

### 7.2 沙盒基础镜像 Dockerfile

```dockerfile
# docker/sandbox/Dockerfile.base
# ──────────────────────────────
# 基础生信沙盒镜像
# ──────────────────────────────
FROM jupyter/scipy-notebook:hub-4.1.0

USER root

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libhdf5-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libpng-dev \
    libjpeg-dev \
    libbz2-dev \
    liblzma-dev \
    libffi-dev \
    libsqlite3-dev \
    zlib1g-dev \
    curl \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

# 安装 mamba（更快的 conda）
RUN conda install -n base -c conda-forge mamba -y

# 创建用户 conda 环境（持久化层）
RUN mamba create -n user -c conda-forge -c bioconda \
    python=3.11 \
    pip \
    && mamba clean -afy

# 安装生信核心包
RUN mamba install -n user -c conda-forge -c bioconda \
    scanpy==1.9.6 \
    anndata==0.9.2 \
    mudata==0.2.3 \
    muon==0.1.5 \
    scvi-tools==1.0.4 \
    scikit-misc \
    leidenalg \
    igraph \
    harmonypy \
    scikit-learn \
    statsmodels \
    seaborn \
    matplotlib-venn \
    upsetplot \
    bioinfokit \
    gseapy \
    mygene \
    biopython \
    pysam \
    bedtools \
    samtools \
    htslib \
    bcftools \
    tabix \
    vcftools \
    plink \
    bwa \
    bowtie2 \
    star \
    hisat2 \
    stringtie \
    subread \
    featurecounts \
    deseq2 \
    bioconductor-deseq2 \
    bioconductor-edger \
    bioconductor-limma \
    bioconductor-clusterprofiler \
    bioconductor-org.hs.eg.db \
    bioconductor-org.mm.eg.db \
    && mamba clean -afy

# 安装 Jupyter Kernel Gateway（无界面 Kernel 服务）
RUN /opt/conda/envs/user/bin/pip install \
    jupyter_kernel_gateway==2.5.2 \
    jupyter_client \
    ipykernel

# 注册 IPython Kernel
RUN /opt/conda/envs/user/bin/python -m ipykernel install \
    --name user \
    --display-name "Python (Bioinfo)" \
    --prefix=/opt/conda

# 安装 R 及 IRkernel（可选）
RUN mamba install -n user -c conda-forge -c bioconda \
    r-base=4.3 \
    r-irkernel \
    r-seurat \
    r-seuratobject \
    r-monocle3 \
    bioconductor-singlecellexperiment \
    bioconductor-scater \
    bioconductor-scran \
    bioconductor-complexheatmap \
    && mamba clean -afy

# 安全加固
RUN useradd -m -s /bin/bash -u 1000 jovyan && \
    mkdir -p /tmp/execution && \
    chown -R jovyan:jovyan /tmp/execution && \
    chmod 755 /tmp/execution

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8888/api || exit 1

USER jovyan

EXPOSE 8888

CMD ["jupyter", "kernelgateway", \
     "--KernelGatewayApp.ip=0.0.0.0", \
     "--KernelGatewayApp.port=8888", \
     "--KernelGatewayApp.auth_token=''", \
     "--JupyterWebsocketPersonality.list_kernels=True"]
```

### 7.3 健康检查与监控

```python
# app/sandbox/health.py

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List

class SandboxHealthChecker:
    """沙盒健康检查器"""
    
    CHECK_INTERVAL = 30  # 秒
    
    async def run(self) -> None:
        """持续运行健康检查"""
        while True:
            await self._check_all_sandboxes()
            await asyncio.sleep(self.CHECK_INTERVAL)
    
    async def _check_all_sandboxes(self) -> None:
        """检查所有沙盒容器健康状态"""
        # 获取所有 running 容器
        containers = await self._list_sandbox_containers()
        
        for container in containers:
            health = await self._check_container(container)
            
            if health["status"] == "unhealthy":
                await self._handle_unhealthy(container, health)
    
    async def _check_container(self, container: Dict) -> Dict:
        """检查单个容器"""
        import docker
        client = docker.from_env()
        
        try:
            c = client.containers.get(container["id"])
            
            # 检查容器状态
            if c.status != "running":
                return {"status": "unhealthy", "reason": f"Container status: {c.status}"}
            
            # 检查资源使用
            stats = c.stats(stream=False)
            memory_usage = stats["memory_stats"].get("usage", 0)
            memory_limit = stats["memory_stats"].get("limit", 1)
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"] -
                stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            
            memory_percent = memory_usage / memory_limit * 100 if memory_limit > 0 else 0
            
            # 检查 Kernel 响应
            kernel_healthy = await self._check_kernel(container["kernel_url"])
            
            return {
                "status": "healthy" if kernel_healthy else "degraded",
                "memory_percent": round(memory_percent, 2),
                "cpu_delta": cpu_delta,
                "kernel_healthy": kernel_healthy,
            }
            
        except Exception as e:
            return {"status": "unhealthy", "reason": str(e)}
    
    async def _handle_unhealthy(self, container: Dict, health: Dict) -> None:
        """处理不健康容器"""
        logger.warning(f"Unhealthy sandbox {container['id'][:12]}: {health['reason']}")
        
        # 策略：尝试重启，连续3次失败则销毁
        restart_count = container.get("restart_count", 0)
        
        if restart_count < 3:
            await self._restart_container(container)
        else:
            await self._destroy_container(container)
            # 通知用户
            await self._notify_user(container["user_id"], "sandbox_crashed")


# Prometheus 指标暴露
from prometheus_client import Counter, Histogram, Gauge

sandbox_metrics = {
    "execution_total": Counter(
        "sandbox_execution_total",
        "Total code executions",
        ["language", "status"],
    ),
    "execution_duration": Histogram(
        "sandbox_execution_duration_seconds",
        "Code execution duration",
        ["language"],
        buckets=[1, 5, 10, 30, 60, 120, 300, 600],
    ),
    "active_sessions": Gauge(
        "sandbox_active_sessions",
        "Number of active sandbox sessions",
        ["status"],
    ),
    "pool_size": Gauge(
        "sandbox_pool_size",
        "Sandbox pool metrics",
        ["type"],  # warm, active, total
    ),
    "container_startup": Histogram(
        "sandbox_container_startup_seconds",
        "Container startup time",
        ["type"],  # warm, cold
    ),
}
```

---

## 8. 性能与扩展性考量

### 8.1 性能指标目标

| 指标 | 目标值 | 优化策略 |
|---|---|---|
| 沙盒冷启动 | < 10 秒 | 镜像预热、分层缓存 |
| 沙盒热启动 | < 500 ms | 预热池命中 |
| 代码提交→首次输出 | < 2 秒 | Kernel 连接复用 |
| 图表渲染（前端） | < 500 ms | 增量渲染、虚拟化 |
| AI 代码生成首 token | < 3 秒 | LLM 连接池、prompt 缓存 |
| 单容器并发执行 | 1（队列10） | 单 Kernel 串行 |
| 单机最大容器数 | 50 | 资源规划、cgroup 限制 |

### 8.2 水平扩展策略

```
单节点架构（当前）:
┌─────────────────────────────────────┐
│  Docker Host                        │
│  ├── Copilot Service (容器)          │
│  ├── Sandbox Manager (容器)          │
│  ├── sandbox-xxx (最多50个)          │
│  └── 共享存储 (/data)                │
└─────────────────────────────────────┘

多节点扩展（未来）:
┌─────────────────────────────────────┐
│  K8s Cluster / Docker Swarm         │
│                                     │
│  Control Plane                      │
│  ├── Copilot Service (多副本)        │
│  ├── Sandbox Scheduler              │
│  └── Redis Cluster                  │
│                                     │
│  Worker Nodes (沙盒专用)             │
│  ├── Node-1: sandbox × 50           │
│  ├── Node-2: sandbox × 50           │
│  └── Node-N: sandbox × 50           │
│                                     │
│  Storage: Ceph / NFS                │
└─────────────────────────────────────┘
```

### 8.3 扩展接口

```python
# app/sandbox/scheduler.py（未来扩展）

class SandboxScheduler:
    """沙盒调度器接口（当前单节点，未来可扩展为 K8s）"""
    
    async def schedule(self, request: ExecutionRequest) -> str:
        """选择最优 Worker 节点执行"""
        # 当前实现：本地 Docker
        # 未来实现：K8s Pod 调度
        pass
    
    async def scale_pool(self, target_size: int) -> None:
        """自动扩缩容"""
        # 基于队列长度和等待时间自动调整预热池
        pass
```

---

## 附录

### A. 术语表

| 术语 | 说明 |
|---|---|
| **Artifact** | AI 生成的可交互代码制品，包含代码、元数据和执行历史 |
| **Kernel** | Jupyter Kernel，代码执行的底层进程 |
| **Sandbox** | Docker 容器化的隔离执行环境 |
| **Warm Pool** | 预热的容器池，用于加速沙盒启动 |
| **MCP** | Model Context Protocol，AI 模型与工具的通信协议 |
| **Agent** | 智能代理，负责意图识别和任务路由 |

### B. 相关文档索引

- [模块 01：系统整体架构](./01_system_architecture.md)
- [模块 02：前端架构设计](./02_frontend_architecture.md)
- [模块 03：FastAPI 后端架构](./03_backend_architecture.md)
- [模块 04：数据库设计](./04_database_design.md)
- [模块 05：MCP 协议实现](./05_mcp_protocol.md)
- [模块 06：Docker 基础设施](./06_docker_infrastructure.md)
- [模块 07：工作流引擎集成](./07_workflow_engine.md)
- [模块 08：AI 对话系统设计](./08_ai_chat_system.md)

### C. 变更日志

| 版本 | 日期 | 变更内容 |
|---|---|---|
| v1.0 | 2024-01 | 初始架构设计 |

---

> **文档结束**  
> OmicHub 架构设计文档 — 模块 09：AI Copilot 与交互式代码执行沙盒
