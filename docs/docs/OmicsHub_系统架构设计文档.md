# OmicsHub 系统架构设计文档

## 组内多组学分析云平台 — 完整技术方案

> **项目代号**：OmicsHub  
> **版本**：v1.0  
> **日期**：2025年6月24日  
> **目标读者**：系统架构师、全栈开发工程师、生信维护人员  
> **设计原则**：DDD领域驱动设计、极简运维、未来可扩展  

---

## 项目概要

**OmicsHub** 是为华中农业大学园艺林学学院课题组设计的私有化多组学分析线上平台。平台旨在替代传统的命令行提交分析任务方式，为组内成员（预计并发用户 < 20人）提供图形化、可视化的多组学数据分析能力。

### 核心特性

| 特性 | 说明 |
|------|------|
| **YAML驱动工作流** | 外置YAML配置动态加载分析流程，前端自动渲染表单 |
| **AI对话助手** | 常驻AI对话面板，上下文感知，支持工具调用与MCP扩展 |
| **混合执行模式** | `EXECUTION_MODE=local/remote` 一键切换，零代码改动 |
| **Snakemake复用** | 复用组内已有Snakefile流程资产，不重构脚本逻辑 |
| **极简运维** | Docker Compose单文件一键部署，适合单人维护 |

### 技术栈概览

| 层级 | 选型 |
|------|------|
| 前端 | Vue 3 + TypeScript + Vite + Naive UI + Pinia |
| 后端 | FastAPI + Python 3.11 + Pydantic v2 |
| 数据库 | PostgreSQL 14+ (JSONB) |
| 缓存/队列 | Redis 7+ + Celery + Flower |
| 流程执行 | Snakemake (本地subprocess / 远程HTTP) |
| AI对话 | Kimi API / OpenAI API (预留) |
| MCP集成 | Python MCP SDK |
| 部署 | Docker + Docker Compose + Nginx |

---

## 文档目录

### 6.1 系统架构总览

系统全景Mermaid架构图、DDD模块划分图、分层架构说明、核心架构重点总结

### 6.2 数据库Schema设计

6大域14张核心表完整建表SQL、95个索引、13个触发器、14个RLS策略、JSONB字段详细说明、ER关系、数据隔离策略

### 6.3 API接口设计（REST + WebSocket）

46个REST端点、40+ Pydantic v2 DTO模型、3个WebSocket端点、20+事件类型、Snakemake进度解析

### 6.4 YAML配置规范（Schema）

完整Pydantic Model定义、RNA-seq YAML示例、11种条件运算符、前后端协同校验、动态表单渲染架构

### 6.5 前端路由与页面结构

14+路由定义、3种布局、核心页面组件、10个Pinia Store、AI对话面板架构、暗黑模式

### 6.6 Docker Compose部署方案

local/remote双模式、完整docker-compose.yml、Nginx配置、初始化脚本、WMS执行引擎、安全策略

### 6.7 开发里程碑（MVP → v1.0）

3阶段里程碑、甘特图、23项功能点、验收标准、风险与应对、技术债务管理



---

# OmicsHub 系统架构总览与核心架构重点

> **文档版本**：v1.0  
> **项目**：OmicsHub — 私有化多组学分析平台  
> **目标读者**：系统架构师、全栈开发工程师、生信维护人员  
> **技术约束**：Vue 3 + FastAPI + PostgreSQL 14+ + Redis 7+ + Celery + Snakemake + Docker Compose + MCP SDK

---

## 1. 系统全景架构图

以下架构图展示了 OmicsHub 的完整数据流，覆盖从用户浏览器请求到后端各子系统、数据持久化、异步任务队列、AI对话通道、MCP服务连接及Snakemake流程执行的全链路。

```mermaid
flowchart TB
    subgraph Client["🖥️ 客户端层"]
        Browser["浏览器 (Vue 3 + TypeScript + Vite)"]
    end

    subgraph Gateway["🌐 网关与静态资源层"]
        Nginx["Nginx 反向代理"]
        Static["静态资源 (dist/)"]
    end

    subgraph Platform["⚡ FastAPI Web 平台 (Docker Compose)"]
        subgraph API["API 服务层"]
            FastAPI["FastAPI Application (Pydantic v2)"]
            RouterUser["/api/v1/users"]
            RouterFlow["/api/v1/flows"]
            RouterTask["/api/v1/tasks"]
            RouterFile["/api/v1/files"]
            RouterAI["/api/v1/ai"]
            RouterMCP["/api/v1/mcp"]
        end

        subgraph Service["应用服务层 (Application Service)"]
            UserService["UserService"]
            FlowService["FlowService"]
            TaskService["TaskService"]
            FileService["FileService"]
            AIService["AIService"]
            MCPService["MCPService"]
        end

        subgraph Domain["领域层 (Domain Layer)"]
            UserDomain["👤 用户域"]
            FlowDomain["📋 流程域"]
            TaskDomain["⚙️ 任务域"]
            FileDomain["📁 文件域"]
            AIDomain["🤖 AI域"]
            MCPDomain["🔌 MCP域"]
        end
    end

    subgraph Infra["🛠️ 基础设施层"]
        PostgreSQL[("PostgreSQL 14+\n(JSONB)")]
        Redis[("Redis 7+")]
        Celery["Celery Workers"]
        Flower["Flower 监控"]
        FileStorage[("共享存储\n(NFS/本地卷)")]
    end

    subgraph Execution["🧬 流程执行层"]
        subgraph LocalExec["本地执行模式"]
            LocalSnakemake["Snakemake Subprocess\n(本地Python调用)"]
            LocalConda["Conda Env /\nSingularity"]
        end

        subgraph RemoteExec["远程执行模式"]
            HTTPExecutor["HTTP Executor API\n(FastAPI副进程)"]
            RemoteSnakemake["远程 Snakemake Master"]
            Slurm["Slurm /\nSGE集群"]
        end
    end

    subgraph External["🌍 外部服务层"]
        KimiAPI["Kimi API / OpenAI API"]
        subgraph MCPServers["MCP Servers"]
            MCP_Literature["文献检索 MCP"]
            MCP_Genome["基因组数据库 MCP"]
            MCP_Code["代码解释 MCP"]
            MCP_KB["组内知识库 MCP"]
        end
    end

    %% === 主数据流 ===
    Browser -->|"HTTPS / WebSocket"| Nginx
    Nginx -->|"/api/* 代理"| FastAPI
    Nginx -->|"静态资源"| Static

    FastAPI --> RouterUser & RouterFlow & RouterTask & RouterFile & RouterAI & RouterMCP
    RouterUser --> UserService
    RouterFlow --> FlowService
    RouterTask --> TaskService
    RouterFile --> FileService
    RouterAI --> AIService
    RouterMCP --> MCPService

    UserService --> UserDomain
    FlowService --> FlowDomain
    TaskService --> TaskDomain
    FileService --> FileDomain
    AIService --> AIDomain
    MCPService --> MCPDomain

    %% === 基础设施连接 ===
    UserDomain -->|"CRUD / JSONB"| PostgreSQL
    FlowDomain -->|"CRUD / JSONB"| PostgreSQL
    TaskDomain -->|"CRUD / JSONB"| PostgreSQL
    FileDomain -->|"元数据"| PostgreSQL
    AIDomain -->|"会话持久化"| PostgreSQL
    MCPDomain -->|"Server注册信息"| PostgreSQL

    TaskDomain -->|"任务发布"| Redis
    Redis -->|"任务消费"| Celery
    Celery -->|"执行监控"| Flower
    Flower -->|"监控数据"| FastAPI

    FileDomain -->|"读写"| FileStorage
    TaskDomain -->|"工作目录"| FileStorage

    %% === Snakemake 执行流 ===
    Celery -->|"本地模式: subprocess调用"| LocalSnakemake
    LocalSnakemake -->|"环境隔离"| LocalConda
    LocalConda -->|"结果产出"| FileStorage

    Celery -->|"远程模式: HTTP调用"| HTTPExecutor
    HTTPExecutor -->|"SSH/HTTP"| RemoteSnakemake
    RemoteSnakemake -->|"作业调度"| Slurm
    RemoteSnakemake -->|"结果回传"| FileStorage

    %% === AI 对话 WebSocket 流 ===
    Browser -.->|"wss:// /api/v1/ai/ws\nWebSocket全双工"| RouterAI
    AIService -.->|"SSE / HTTP"| KimiAPI
    AIService -.->|"Tool Use 调用"| MCPService

    %% === MCP 连接 ===
    MCPService -.->|"MCP Protocol (stdio/sse)"| MCP_Literature
    MCPService -.->|"MCP Protocol"| MCP_Genome
    MCPService -.->|"MCP Protocol"| MCP_Code
    MCPService -.->|"MCP Protocol"| MCP_KB

    %% === WebSocket 实时推送 ===
    Celery -.->|"Pub/Sub"| Redis
    Redis -.->|"WebSocket推送\n任务状态/日志"| RouterTask

    %% === 样式 ===
    style Client fill:#e1f5fe
    style Gateway fill:#fff3e0
    style Platform fill:#e8f5e9
    style Infra fill:#fce4ec
    style Execution fill:#f3e5f5
    style External fill:#fff9c4
    style API fill:#c8e6c9
    style Service fill:#a5d6a7
    style Domain fill:#81c784
    style LocalExec fill:#e1bee7
    style RemoteExec fill:#ce93d8
    style MCPServers fill:#fff59d
```

### 1.1 数据流说明

| 数据流 | 路径 | 协议 | 说明 |
|--------|------|------|------|
| **用户请求流** | Browser → Nginx → FastAPI → Service → Domain → PostgreSQL | HTTP/HTTPS | 标准CRUD请求链路 |
| **异步任务流** | FastAPI → Redis → Celery → Snakemake → FileStorage | Redis Pub/Sub | 耗时分析任务异步执行 |
| **WebSocket AI流** | Browser ↔ FastAPI WebSocket ↔ AIService ↔ KimiAPI | WSS/SSE | 全双工AI对话，支持上下文记忆 |
| **MCP工具流** | AIService → MCPService → MCP Servers | MCP Protocol | Tool Use协议调用外部MCP服务 |
| **任务监控流** | Celery → Redis → WebSocket → Browser | Pub/Sub + WSS | 实时推送任务状态与日志 |
| **本地执行流** | Celery → LocalSnakemake(subprocess) → FileStorage | Local subprocess | 组内服务器本地执行 |
| **远程执行流** | Celery → HTTPExecutor → RemoteSnakemake → Slurm | HTTP/SSH | 远程集群执行，结果回传 |

---

## 2. DDD 模块划分

OmicsHub 采用领域驱动设计（DDD）的模块化架构，将业务领域划分为六个核心域，每个域内含独立的聚合根、实体、值对象和领域服务。

```mermaid
flowchart TB
    subgraph BoundedContexts["🧩 OmicsHub 限界上下文 (Bounded Contexts)"]
        subgraph UserCtx["👤 用户域 (User Domain)"]
            User["👤 User\n[Aggregate Root]\n- id: UUID\n- username: str\n- email: str\n- role: Role\n- created_at: datetime"]
            Role["🔖 Role\n[Value Object]\n- ADMIN / USER"]
            Workspace["🏠 Workspace\n[Entity]\n- id: UUID\n- owner_id: UUID\n- name: str\n- storage_quota: int"]
            User -->|"has role"| Role
            User -->|"owns"| Workspace
        end

        subgraph FlowCtx["📋 流程域 (Flow Domain)"]
            FlowDef["📋 FlowDefinition\n[Aggregate Root]\n- id: UUID\n- name: str\n- yaml_config: JSONB\n- category: str\n- version: str"]
            FlowParam["⚙️ FlowParameter\n[Entity]\n- name: str\n- type: ParamType\n- default: Any\n- required: bool\n- ui_schema: JSONB"]
            FlowStep["🔀 FlowStep\n[Entity]\n- order: int\n- tool: str\n- inputs: JSONB\n- outputs: JSONB"]
            FlowDef -->|"contains"| FlowParam
            FlowDef -->|"ordered steps"| FlowStep
        end

        subgraph TaskCtx["⚙️ 任务域 (Task Domain)"]
            Task["⚙️ Task\n[Aggregate Root]\n- id: UUID\n- flow_id: UUID\n- user_id: UUID\n- status: TaskStatus\n- work_dir: Path\n- created_at: datetime"]
            TaskStatusEnum["📊 TaskStatus\n[Value Object]\nPENDING / QUEUED /\nRUNNING / SUCCESS /\nFAILED / CANCELLED"]
            TaskLog["📝 TaskLog\n[Entity]\n- timestamp: datetime\n- level: LogLevel\n- message: str"]
            ExecutionMode["🔧 ExecutionMode\n[Value Object]\nLOCAL / REMOTE"]
            Task -->|"has status"| TaskStatusEnum
            Task -->|"generates"| TaskLog
            Task -->|"executed via"| ExecutionMode
        end

        subgraph FileCtx["📁 文件域 (File Domain)"]
            Sample["🧬 Sample\n[Aggregate Root]\n- id: UUID\n- name: str\n- user_id: UUID\n- metadata: JSONB\n- file_ids: UUID[]"]
            DataFile["📄 DataFile\n[Entity]\n- id: UUID\n- path: str\n- size: int\n- checksum: str\n- file_type: FileType"]
            FileTypeEnum["📂 FileType\n[Value Object]\nFASTQ / BAM / VCF /\nCOUNT_MATRIX / META"]
            ResultArchive["📦 ResultArchive\n[Entity]\n- task_id: UUID\n- archive_path: Path\n- expires_at: datetime"]
            Sample -->|"contains"| DataFile
            DataFile -->|"has type"| FileTypeEnum
            Sample -->|"produces"| ResultArchive
        end

        subgraph AICtx["🤖 AI域 (AI Domain)"]
            Conversation["💬 Conversation\n[Aggregate Root]\n- id: UUID\n- user_id: UUID\n- title: str\n- model: str\n- created_at: datetime"]
            Message["✉️ Message\n[Entity]\n- role: RoleType\n- content: str\n- tool_calls: JSONB\n- timestamp: datetime"]
            RoleTypeEnum["🎭 RoleType\n[Value Object]\nSYSTEM / USER /\nASSISTANT / TOOL"]
            ContextWindow["🪟 ContextWindow\n[Value Object]\n- max_tokens: int\n- messages: Message[]\n- summary: str"]
            Conversation -->|"contains"| Message
            Message -->|"has role"| RoleTypeEnum
            Conversation -->|"managed by"| ContextWindow
        end

        subgraph MCPCtx["🔌 MCP域 (MCP Domain)"]
            MCPServerReg["🔌 MCPServer\n[Aggregate Root]\n- id: UUID\n- name: str\n- transport: Transport\n- command: str\n- env: JSONB\n- status: ServerStatus"]
            MCPTransport["📡 Transport\n[Value Object]\nSTDIO / SSE"]
            MCPToolRegistry["🛠️ MCPToolRegistry\n[Entity]\n- tool_name: str\n- schema: JSONB\n- server_id: UUID"]
            ServerStatusEnum["🔋 ServerStatus\n[Value Object]\nONLINE / OFFLINE /\nERROR"]
            MCPServerReg -->|"uses"| MCPTransport
            MCPServerReg -->|"registers"| MCPToolRegistry
            MCPServerReg -->|"has status"| ServerStatusEnum
        end
    end

    %% === 跨域关系 ===
    UserCtx -.->|"提交"| TaskCtx
    FlowCtx -.->|"实例化"| TaskCtx
    TaskCtx -.->|"读写"| FileCtx
    FileCtx -.->|"作为输入"| TaskCtx
    AICtx -.->|"调用内部功能"| TaskCtx
    AICtx -.->|"调用工具"| MCPCtx
    MCPCtx -.->|"查询"| FileCtx
    UserCtx -.->|"隔离数据"| FileCtx

    style UserCtx fill:#e3f2fd
    style FlowCtx fill:#e8f5e9
    style TaskCtx fill:#fff3e0
    style FileCtx fill:#fce4ec
    style AICtx fill:#f3e5f5
    style MCPCtx fill:#fff9c4
```

### 2.1 各域职责与聚合根说明

| 域 | 聚合根 | 核心职责 | 关键实体 |
|----|--------|----------|----------|
| **用户域** | `User` | 账户注册/登录、角色权限、工作空间隔离 | User, Workspace, Role |
| **流程域** | `FlowDefinition` | YAML配置解析、流程定义管理、参数模式生成 | FlowParameter, FlowStep |
| **任务域** | `Task` | 任务生命周期管理、调度策略、执行监控、日志聚合 | TaskLog, ExecutionMode |
| **文件域** | `Sample` | 样本元数据管理、批量上传、结果归档与过期策略 | DataFile, ResultArchive |
| **AI域** | `Conversation` | 对话会话管理、上下文窗口、消息历史、Tool Use编排 | Message, ContextWindow |
| **MCP域** | `MCPServer` | MCP Server注册、工具发现、连接管理、错误隔离 | MCPToolRegistry, Transport |

---

## 3. 分层架构说明

OmicsHub 严格遵循分层架构模式，自上而下划分为四层，每层具有明确的职责边界和依赖方向（上层依赖下层，禁止跨层调用）。

```mermaid
flowchart TB
    subgraph Presentation["🎨 表示层 (Presentation Layer)"]
        Vue3["Vue 3 + TypeScript"]
        Vite["Vite (构建工具)"]
        NaiveUI["Naive UI (组件库)"]
        Pinia["Pinia (状态管理)"]
        ECharts["ECharts / Plotly\n(图表可视化)"]
        AIChat["AIChat组件\n(常驻对话窗口)"]
        DynamicForm["DynamicForm组件\n(YAML驱动表单)"]
        Vue3 --> NaiveUI
        Vue3 --> Pinia
        Vue3 --> ECharts
        Vue3 --> AIChat
        Vue3 --> DynamicForm
    end

    subgraph Application["⚙️ 应用层 (Application Layer)"]
        subgraph RouterLayer["FastAPI Router 层"]
            RUser["UserRouter\n(/api/v1/users)"]
            RFlow["FlowRouter\n(/api/v1/flows)"]
            RTask["TaskRouter\n(/api/v1/tasks)"]
            RFile["FileRouter\n(/api/v1/files)"]
            RAI["AIRouter\n(/api/v1/ai)"]
            RMCP["MCPRouter\n(/api/v1/mcp)"]
        end

        subgraph ServiceLayer["Application Service 层"]
            SUser["UserAppService"]
            SFlow["FlowAppService"]
            STask["TaskAppService"]
            SFile["FileAppService"]
            SAI["AIAppService"]
            SMCP["MCPAppService"]
        end

        subgraph DTO["DTO / Schema (Pydantic v2)"]
            DUser["UserDTO / UserCreate / UserResponse"]
            DFlow["FlowDTO / FlowConfigDTO"]
            DTask["TaskDTO / TaskSubmitDTO / TaskStatusDTO"]
            DFile["FileDTO / SampleDTO / UploadDTO"]
            DAI["ChatDTO / MessageDTO / ContextDTO"]
            DMCP["MCPDTO / ToolCallDTO"]
        end

        RUser --> SUser
        RFlow --> SFlow
        RTask --> STask
        RFile --> SFile
        RAI --> SAI
        RMCP --> SMCP

        SUser --> DUser
        SFlow --> DFlow
        STask --> DTask
        SFile --> DFile
        SAI --> DAI
        SMCP --> DMCP
    end

    subgraph DomainLayer["🧠 领域层 (Domain Layer)"]
        subgraph Entities["实体 (Entity)"]
            EUser["User (聚合根)"]
            EFlow["FlowDefinition (聚合根)"]
            ETask["Task (聚合根)"]
            ESample["Sample (聚合根)"]
            EConv["Conversation (聚合根)"]
            EMCPS["MCPServer (聚合根)"]
        end

        subgraph ValueObjects["值对象 (Value Object)"]
            VRole["Role"]
            VStatus["TaskStatus"]
            VFileType["FileType"]
            VExecMode["ExecutionMode"]
            VCtxWindow["ContextWindow"]
            VTransport["Transport"]
        end

        subgraph DomainServices["领域服务 (Domain Service)"]
            DSAuth["AuthDomainService\n(JWT签发/验证)"]
            DSFlow["FlowDomainService\n(YAML解析/校验)"]
            DSTask["TaskDomainService\n(状态机/调度)"]
            DSAI["AIDomainService\n(上下文压缩/Token管理)"]
            DSMCP["MCPDomainService\n(工具路由/错误隔离)"]
        end

        subgraph Repositories["仓储接口 (Repository Interface)"]
            REUser["IUserRepository"]
            REFlow["IFlowRepository"]
            RETask["ITaskRepository"]
            RESample["ISampleRepository"]
            REConv["IConversationRepository"]
            REMCP["IMCPServerRepository"]
        end
    end

    subgraph Infrastructure["🛠️ 基础设施层 (Infrastructure Layer)"]
        subgraph RepositoriesImpl["仓储实现 (Repository Impl)"]
            RIUser["UserRepositoryImpl\n(SQLAlchemy)"]
            RIFlow["FlowRepositoryImpl"]
            RITask["TaskRepositoryImpl"]
            RISample["SampleRepositoryImpl"]
            RIConv["ConversationRepositoryImpl"]
            RIMCP["MCPServerRepositoryImpl"]
        end

        subgraph ExternalAdapters["外部适配器"]
            DBAdapter[("PostgreSQL Adapter\n(SQLAlchemy + asyncpg)")]
            CacheAdapter[("Redis Adapter\n(redis-py-async)")]
            CeleryAdapter["Celery Adapter\n(任务发布/监控)"]
            FileStorageAdapter[("文件存储适配器\n(aiofiles)")]
            AIAdapter["AI Provider Adapter\n(Kimi/OpenAI)")
            MCPClientAdapter["MCP Client Adapter\n(Python MCP SDK)")]
            SnakemakeAdapter["Snakemake Executor Adapter\n(subprocess / HTTP)"]
        end

        subgraph Security["安全与中间件"]
            JWT["JWT Middleware\n(py-jwt)"]
            RBAC["RBAC Middleware"]
            CORS["CORS Middleware"]
            RateLimit["Rate Limit\n(Redis-based)"]
        end

        RepositoriesImpl --> ExternalAdapters
    end

    %% === 依赖方向 ===
    Presentation -->|"HTTP / WebSocket"| Application
    Application -->|"调用"| DomainLayer
    DomainLayer -.->|"依赖抽象"| Infrastructure
    Infrastructure -->|"实现接口"| DomainLayer

    style Presentation fill:#e1f5fe
    style Application fill:#e8f5e9
    style DomainLayer fill:#fff3e0
    style Infrastructure fill:#fce4ec
```

### 3.1 各层职责详解

#### 🎨 表示层（Presentation Layer）

| 组件 | 技术选型 | 职责 |
|------|----------|------|
| UI框架 | Vue 3 + TypeScript | 声明式组件化UI开发 |
| 构建工具 | Vite | 快速HMR与生产构建 |
| 组件库 | Naive UI | 一致的UI设计与交互 |
| 状态管理 | Pinia | 跨组件状态共享与持久化 |
| 可视化 | ECharts / Plotly | 交互式科学图表渲染 |
| AI对话 | AIChat组件 | 常驻浮动对话窗口，支持Markdown渲染 |
| 动态表单 | DynamicForm组件 | 基于JSON Schema的YAML驱动表单自动渲染 |

表示层**不包含任何业务逻辑**，仅负责：
- 用户界面渲染与交互响应
- API请求的发起与响应处理
- WebSocket连接的建立与消息处理
- 表单校验（前端级，仅UX优化）
- 图表数据的可视化呈现

#### ⚙️ 应用层（Application Layer）

应用层是系统的"编排器"，负责协调领域对象完成用例：

| 职责 | 说明 |
|------|------|
| **请求路由** | FastAPI Router 接收HTTP/WebSocket请求，进行路径分发 |
| **参数校验** | Pydantic v2 DTO 进行请求/响应数据建模与校验 |
| **用例编排** | Application Service 调用领域对象完成业务用例 |
| **事务管理** | 通过 Unit of Work 模式管理数据库事务边界 |
| **权限检查** | 在Service层进行RBAC权限校验（装饰器模式） |
| **DTO转换** | 领域对象与DTO之间的映射转换 |

**关键原则**：应用层不包含业务规则，业务规则位于领域层。应用层只负责"怎么做"（编排），不负责"是什么"（业务定义）。

#### 🧠 领域层（Domain Layer）

领域层是系统的核心，包含所有业务规则和业务逻辑：

| 概念 | 说明 | 示例 |
|------|------|------|
| **聚合根 (Aggregate Root)** | 事务一致性边界内的入口实体 | `Task` 聚合根管理 TaskLog、ExecutionMode |
| **实体 (Entity)** | 有唯一标识且状态可变的对象 | `Message`、`FlowStep`、`DataFile` |
| **值对象 (Value Object)** | 无唯一标识，不可变，通过属性判等 | `TaskStatus`、`Role`、`ContextWindow` |
| **领域服务 (Domain Service)** | 跨实体的业务逻辑封装 | `TaskDomainService` 负责任务状态机转换 |
| **仓储接口 (Repository Interface)** | 领域对象持久化的抽象，定义在领域层 | `ITaskRepository` 接口 |

领域层的**关键原则**：
- 领域层不依赖任何其他层（依赖倒置原则）
- 领域层不依赖基础设施的具体实现
- 通过仓储接口抽象持久化操作
- 业务规则集中在领域服务中，确保单一事实来源

#### 🛠️ 基础设施层（Infrastructure Layer）

基础设施层提供领域层所需的技术能力实现：

| 组件 | 技术实现 | 职责 |
|------|----------|------|
| 数据库 | SQLAlchemy 2.0 + asyncpg | PostgreSQL异步ORM操作 |
| 缓存 | redis-py (async) | Redis连接与会话缓存 |
| 任务队列 | Celery + Redis Broker | 异步任务发布与结果存储 |
| 文件存储 | aiofiles | 异步文件读写操作 |
| AI适配器 | 自定义Adapter | 统一封装Kimi/OpenAI API调用 |
| MCP客户端 | Python MCP SDK | MCP协议实现，Server连接管理 |
| Snakemake执行器 | subprocess / httpx | 本地子进程或远程HTTP调用 |
| 安全中间件 | py-jwt / FastAPI中间件 | JWT签发验证、RBAC、限流 |

---

## 4. 核心架构重点总结

### 4.1 YAML配置中心与动态表单架构要点

OmicsHub 的核心设计理念之一是**"配置即代码"**——所有生信分析流程通过外置YAML文件进行声明式定义，无需修改前端代码即可新增或调整分析流程。这一架构的要点包括：

**YAML配置结构规范**：每个流程由一个独立的YAML文件定义，包含四大核心区块：`metadata`（流程元信息，如名称、描述、类别、版本）、`parameters`（参数定义，每个参数声明名称、类型、默认值、是否必填、UI控件类型如select/slider/file等）、`steps`（分析步骤的Snakemake规则引用与输入输出映射）以及`ui_schema`（前端表单布局描述，支持分组、条件显示、级联依赖）。

**动态表单渲染引擎**：前端 `DynamicForm` 组件通过 `/api/v1/flows/{id}/schema` 接口获取流程的JSON Schema描述，利用Naive UI的表单组件库实现动态渲染。当用户选择不同流程时，前端自动拉取对应YAML解析后的参数定义，生成完整的表单界面。参数类型系统覆盖生信场景常见类型：文本输入、数值输入、下拉选择、文件上传（支持批量）、样本选择器（关联样本库）、布尔开关。

**后端YAML解析与缓存**：后端 `FlowDomainService` 在启动时扫描配置的YAML目录，解析所有流程定义并写入PostgreSQL（JSONB字段存储灵活参数结构），同时将解析后的JSON Schema缓存到Redis。当YAML文件变更时，提供管理接口触发热重载，无需重启服务。解析过程包含严格校验：参数类型校验、步骤依赖图校验（确保DAG无环）、Snakemake规则存在性校验。

**版本管理与兼容性**：每个流程定义支持版本号管理，历史版本保留在数据库中。任务提交时锁定当前流程版本，确保已提交任务使用稳定的参数定义，不受后续流程更新的影响。管理员可通过Web界面在线编辑YAML并预览表单效果，降低维护门槛——这对于仅1名生信维护人员的团队至关重要。

---

### 4.2 AI对话窗口与业务系统融合架构要点

AI对话助手是 OmicsHub 的**常驻功能模块**，以浮动窗口形式嵌入所有页面，实现AI能力与平台业务功能的无缝融合：

**WebSocket全双工通信**：AI对话采用WebSocket协议（`/api/v1/ai/ws`）实现真正的全双工通信，相比SSE具有更低的延迟和更好的实时性。对话消息通过WebSocket双向传输：用户发送消息 → 后端组装上下文 → 调用AI API → 流式响应通过WebSocket实时推送至前端。连接管理采用心跳保活机制，断线后支持自动重连与消息补发。

**上下文记忆与窗口管理**：`Conversation` 聚合根管理完整的对话历史，每个会话独立存储于PostgreSQL。`ContextWindow` 值对象负责管理发送到LLM的上下文窗口——包括消息截断策略（保留最近N轮）、Token预估与限制、长对话自动摘要压缩。系统支持多会话并行，用户可在历史会话间切换。AI域服务内置平台知识注入：每次请求自动附加当前页面的上下文信息（如正在查看的任务ID、样本列表），使AI能够理解用户当前操作场景。

**Tool Use协议与平台功能调用**：AI助手不仅限于问答，更可以通过Tool Use协议**调用平台内部功能**。后端 `AIDomainService` 维护一组平台工具定义（如`submit_task`、`query_task_status`、`list_samples`、`search_knowledge_base`），这些工具以JSON Schema形式注册到LLM的function calling接口。当用户说"帮我提交一个RNA-seq分析任务，样本用昨天上传的"时，LLM识别意图并调用对应的平台工具，实现自然语言驱动操作。工具调用结果经校验后返回LLM，由LLM生成自然语言反馈给用户，形成完整的"理解-行动-反馈"闭环。

**前端组件设计**：`AIChat` 组件基于Naive UI的Drawer/Modal组件封装，支持全局快捷键呼出（如 `Ctrl+K`）、拖拽调整大小、Markdown消息渲染（含代码高亮）、流式打字机效果、工具调用过程可视化（折叠展开）。组件状态通过Pinia全局管理，确保切换页面时对话状态不丢失。

---

### 4.3 MCP集成架构要点

MCP（Model Context Protocol）集成使OmicsHub的AI助手能够安全、标准化地连接多个外部智能服务，极大扩展了平台的数据访问和计算能力：

**MCP Client架构**：后端 `MCPAppService` 基于Python MCP SDK实现MCP Client，负责与多个MCP Server的Lifecycle管理（启动、连接、心跳检测、异常重启）、工具发现（动态拉取各Server的工具列表与Schema）、调用路由（根据工具名路由到对应Server）以及错误隔离（单个Server故障不影响其他Server和主系统）。MCP Client支持两种传输模式：stdio（本地子进程模式，适用于部署在同一服务器的MCP服务）和SSE（Server-Sent Events模式，适用于远程MCP服务）。

**MCP Server注册管理**：通过 `/api/v1/mcp/servers` 管理接口，管理员可以动态注册、配置、启用/禁用MCP Server。每个Server的配置包括：名称、传输类型、启动命令/URL、环境变量、超时设置。注册信息持久化到PostgreSQL，系统启动时自动初始化所有标记为启用的Server连接。`MCPServer` 聚合根管理Server的全生命周期状态：`ONLINE`（正常）、`OFFLINE`（未启动）、`ERROR`（故障）。

**四大预设MCP服务**：

| MCP服务 | 职责 | 数据源 |
|---------|------|--------|
| **文献检索MCP** | PubMed/arXiv文献语义检索、摘要生成 | NCBI E-utilities / Europe PMC |
| **基因组数据库MCP** | 基因注释查询、通路分析、GO/KEGG富集 | Ensembl / KEGG / NCBI |
| **代码解释MCP** | 生信代码生成与解释（R/Python） | 内置代码执行环境 |
| **组内知识库MCP** | 组内实验方案、SOP、历史项目经验检索 | 私有化向量数据库 |

**错误隔离与降级策略**：每个MCP Server运行在独立的进程中，通过 `MCPDomainService` 的错误隔离机制确保：单个MCP Server崩溃不会导致AI对话功能整体不可用；MCP调用超时时自动降级（返回预设的错误提示而非阻塞）；AI助手在工具不可用时自动切换为纯文本问答模式。所有MCP调用记录审计日志，便于排查问题。

---

### 4.4 工作流执行引擎（WMS）混合模式要点

OmicsHub的工作流执行引擎支持**本地/远程混合模式**，灵活适配不同计算场景——从单台服务器的小规模分析到高性能计算集群的大规模任务：

**统一任务模型**：`Task` 聚合根抽象了统一的任务模型，与执行位置解耦。每个Task记录：关联的流程定义ID、参数快照（JSONB，锁定提交时的参数值）、执行模式（`LOCAL` 或 `REMOTE`）、工作目录路径、目标状态机。任务状态采用严格的状态机设计：`PENDING` → `QUEUED` → `RUNNING` → (`SUCCESS` | `FAILED` | `CANCELLED`)，状态转换由 `TaskDomainService` 统一管理，确保一致性。

**Celery异步队列**：所有分析任务通过Celery异步执行，避免阻塞Web请求。任务提交后进入Redis队列，由Celery Worker消费执行。系统设计两种队列：`analysis.local`（本地执行队列）和 `analysis.remote`（远程执行队列），根据流程配置和用户选择自动路由。Flower提供Web界面实时监控队列深度、Worker状态、任务执行历史。Celery Beat用于定时任务：清理过期结果归档、扫描YAML配置变更、生成系统用量报告。

**本地执行模式（Local Mode）**：适用于组内服务器直接运行。Celery Worker通过 `subprocess` 模块调用Snakemake CLI命令，直接在Worker所在服务器执行分析流程。本地模式配置简单，无需额外基础设施，适合快速验证和小规模分析。Snakemake运行在独立的Conda环境中，通过 `--use-conda` 或 `--use-singularity` 实现环境隔离。执行日志通过Redis Pub/Sub实时推送到前端WebSocket。

**远程执行模式（Remote Mode）**：适用于高性能计算集群（Slurm/SGE）。Celery Worker通过HTTP调用远程的Snakemake Executor服务（一个轻量级的FastAPI副进程），该服务部署在集群头节点上，负责将Snakemake作业翻译为集群调度命令（`sbatch`/`qsub`）并监控执行状态。远程模式的优势在于：充分利用集群的并行计算能力；OmicsHub主服务与计算集群解耦；支持大规模样本的并行处理。执行完成后，结果文件通过rsync/HTTP回传到OmicsHub的共享存储中。

**实时监控与日志流**：无论本地或远程模式，任务执行过程中的状态变更和日志输出均通过 **Redis Pub/Sub → WebSocket → 前端** 的链路实时推送。用户在任务详情页可以：查看实时更新的执行日志（WebSocket流式推送）、监控Snakemake的DAG可视化进度、下载中间结果和最终报告、在任务失败时获取错误诊断与AI辅助排查建议。

---

### 4.5 安全与数据隔离要点

安全设计贯穿OmicsHub的所有层次，特别针对**私有化部署**和**课题组数据敏感性**的需求：

**身份认证与授权**：系统采用JWT（JSON Web Token）认证机制。用户注册/登录后获得Access Token（短有效期，默认30分钟）和Refresh Token（长有效期，默认7天），通过HttpOnly Cookie存储增强安全性。角色系统分为 `ADMIN`（管理员，可管理用户、配置流程、管理系统设置）和 `USER`（普通用户，仅能操作自己的数据和任务）。RBAC中间件在应用层进行细粒度权限控制，每个API端点通过装饰器声明所需角色。工作空间（Workspace）机制实现数据硬隔离——每个用户的数据（样本、任务、结果）完全隔离，数据库查询自动附加 `user_id` / `workspace_id` 过滤条件。

**数据安全与隐私**：所有数据库连接使用SSL/TLS加密。敏感配置（数据库密码、API Key、JWT Secret）通过Docker Secrets或环境变量注入，绝不硬编码在代码中。PostgreSQL中用户密码使用 `bcrypt` 算法哈希存储。文件上传支持完整性校验（MD5/SHA256），防止传输损坏。结果归档支持设置过期时间，自动清理策略防止存储无限膨胀。AI对话内容中的敏感信息（如样本名称可能涉及品种名）在传输至外部AI API前进行脱敏处理。

**网络安全**：Nginx作为反向代理提供：SSL/TLS终端加密、静态资源缓存、请求速率限制（防止暴力破解）、请求体大小限制（防止超大文件攻击）。FastAPI内置的CORS中间件限制允许的源域名。WebSocket连接同样经过Nginx反向代理，支持WSS加密。API端点全局启用Rate Limiting（基于Redis的滑动窗口算法），防止API滥用。

**Docker Compose安全**：所有服务运行在非root用户容器中。PostgreSQL和Redis数据卷通过Docker Volume挂载，设置适当的文件权限。容器间网络通过Docker Compose的自定义网络隔离，仅暴露必要的端口到宿主机。Celery Worker容器与Web应用容器分离，限制Worker容器的网络访问（仅允许访问Redis和共享存储）。定期更新基础镜像和依赖包，修复已知安全漏洞。

**审计与可观测性**：系统记录完整的操作审计日志（用户登录、任务提交、文件下载、配置变更），存储于PostgreSQL审计表中，保留180天。管理员可通过管理面板查看系统用量统计、活跃用户、任务成功率等指标。所有API请求记录访问日志（IP、用户ID、端点、响应时间），便于安全事件追溯。

---

## 5. 部署拓扑（Docker Compose）

```mermaid
flowchart LR
    subgraph Host["🖥️ 宿主机 (组内服务器)"]
        Nginx["nginx\n(:80/:443)"]

        subgraph AppNetwork["Docker Network: omicshub_app"]
            Web["web\n(FastAPI + Celery Beat)"]
            Worker["worker\n(Celery Workers)"]
            FlowerUI["flower\n(:5555)"]
        end

        subgraph DataNetwork["Docker Network: omicshub_data"]
            DB["db\n(PostgreSQL 14 :5432)"]
            Cache["cache\n(Redis 7 :6379)"]
        end

        subgraph StorageVolume["Docker Volumes"]
            PGData[("pg_data")]
            RedisData[("redis_data")]
            SharedStorage[("shared_storage\n上传文件/结果/日志")]
            YAMLConfigs[("yaml_configs\n流程定义YAML")]
        end

        Nginx -->|"/api/*"| Web
        Nginx -->|"/flower/*"| FlowerUI
        Nginx -->|"静态资源"| Web

        Web --> DB & Cache
        Worker --> DB & Cache
        FlowerUI --> Cache

        DB --> PGData
        Cache --> RedisData
        Web --> SharedStorage & YAMLConfigs
        Worker --> SharedStorage & YAMLConfigs
    end

    Browser["🌐 用户浏览器"] --> Nginx

    style Host fill:#e3f2fd
    style AppNetwork fill:#e8f5e9
    style DataNetwork fill:#fce4ec
    style StorageVolume fill:#fff3e0
```

### 5.1 Docker Compose 服务定义概览

| 服务名 | 镜像/构建 | 端口 | 职责 |
|--------|-----------|------|------|
| `nginx` | `nginx:alpine` | 80, 443 | 反向代理、SSL终端、静态资源 |
| `web` | 构建 `Dockerfile` | 8000 | FastAPI主应用 + Celery Beat定时器 |
| `worker` | 构建 `Dockerfile` | — | Celery Worker进程（可水平扩展） |
| `flower` | `mher/flower` | 5555 | Celery监控Web界面 |
| `db` | `postgres:14-alpine` | 5432 | PostgreSQL主数据库 |
| `cache` | `redis:7-alpine` | 6379 | Redis缓存 + 消息代理 |

---

## 6. 技术选型汇总

| 层次 | 组件 | 技术选型 | 版本约束 |
|------|------|----------|----------|
| 前端框架 | Vue 3 + TypeScript | `vue@^3.4` + `typescript@^5.3` | LTS |
| 构建工具 | Vite | `vite@^5.0` | LTS |
| UI组件库 | Naive UI | `naive-ui@^2.35` | LTS |
| 状态管理 | Pinia | `pinia@^2.1` | LTS |
| 后端框架 | FastAPI | `fastapi@^0.110` | LTS |
| 数据校验 | Pydantic v2 | `pydantic@^2.5` | v2必需 |
| ORM | SQLAlchemy 2.0 | `sqlalchemy@^2.0` | 2.0+支持async |
| 数据库 | PostgreSQL | `postgres:14-alpine` | 14+ |
| 缓存 | Redis | `redis:7-alpine` | 7+ |
| 任务队列 | Celery + Flower | `celery@^5.3` | LTS |
| 流程引擎 | Snakemake | `snakemake@^8.0` | 8.0+ |
| AI对话 | Kimi API / OpenAI API | HTTP SSE/Stream | 预留接口 |
| MCP协议 | Python MCP SDK | `mcp@latest` | 跟随官方 |
| 容器化 | Docker Compose | `docker compose v2` | v2+ |
| 反向代理 | Nginx | `nginx:alpine` | stable |
| 图表库 | ECharts / Plotly.js | `echarts@^5.4` | LTS |

---

> **文档结束**  
> 本文档为OmicsHub系统架构的顶层设计蓝图，后续模块文档将基于本架构展开各子系统的详细设计。


---

# 6.2 OmicsHub 数据库 Schema 设计

> **文档版本**: v1.0  
> **数据库**: PostgreSQL 14+  
> **设计日期**: 2025年  
> **设计目标**: 华中农业大学园艺林学学院 - 组内多组学分析平台  
> **预期规模**: 并发用户 < 20 人，单人生信维护  

---

## 目录

- [1. 设计概述与约定](#1-设计概述与约定)
- [2. 核心表结构](#2-核心表结构)
  - [2.1 用户域 (users, workspaces)](#21-用户域)
  - [2.2 流程域 (flow_categories, flow_definitions)](#22-流程域)
  - [2.3 项目与文件域 (projects, samples, file_records)](#23-项目与文件域)
  - [2.4 任务域 (tasks, task_logs, task_events)](#24-任务域)
  - [2.5 AI 对话域 (chat_sessions, chat_messages)](#25-ai-对话域)
  - [2.6 MCP 域 (mcp_servers, mcp_tool_invocations)](#26-mcp-域)
- [3. 索引设计](#3-索引设计)
- [4. JSONB 字段详细说明](#4-jsonb-字段详细说明)
- [5. 数据库 ER 关系描述](#5-数据库-er-关系描述)
- [6. 数据隔离策略](#6-数据隔离策略)
- [7. 完整 SQL 执行顺序](#7-完整-sql-执行顺序)

---

## 1. 设计概述与约定

### 1.1 命名规范

| 项目 | 约定 |
|------|------|
| 表名 | 小写蛇形命名，复数形式（如 `users`, `flow_definitions`） |
| 字段名 | 小写蛇形命名（如 `created_at`, `flow_key`） |
| 主键 | 统一使用 `id`（BIGINT, GENERATED ALWAYS AS IDENTITY） |
| 外键 | 引用表名单数 + `_id`（如 `user_id`, `project_id`） |
| 时间戳 | `created_at`, `updated_at` 使用 `timestamptz` |
| UUID | 对外暴露的标识使用 `uuid` 类型（如 `task.task_id`） |
| 布尔值 | 使用 `BOOLEAN` 类型，默认 `TRUE` |
| JSONB | 灵活参数统一使用 `JSONB`，非 `JSON` |
| 注释 | 所有表和字段必须加 `COMMENT ON` |

### 1.2 时区处理

- 数据库服务器时区设置为 `Asia/Shanghai`
- 所有时间字段使用 `timestamptz`（带时区存储）
- 应用层统一使用 UTC 传输，前端做本地化显示

### 1.3 核心设计决策

1. **单数据库 + 单 Schema**: 组内小团队，无需复杂多租户，通过 `user_id` 做行级隔离
2. **JSONB 优先**: 组学流程参数多变，JSONB 提供灵活性，同时配合 GIN 索引保证查询性能
3. **任务状态机**: tasks.status 严格定义为有限状态，通过 CHECK 约束保证
4. **日志存储**: task_logs.content 为 TEXT 类型，大日志（>10MB）建议转文件存储，表中保留摘要
5. **UUID 暴露**: 所有外部接口使用 UUID 而非自增 ID，防止枚举攻击

---

## 2. 核心表结构

### 2.1 用户域

#### 2.1.1 users — 用户表

```sql
-- ============================================================
-- 用户表: 存储系统用户信息，支持管理员和普通用户两种角色
-- ============================================================
CREATE TABLE users (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username            VARCHAR(50) NOT NULL,
    email               VARCHAR(255) NOT NULL,
    hashed_password     VARCHAR(255) NOT NULL,

    -- 角色: admin(管理员) / user(普通用户)
    role                VARCHAR(20) NOT NULL DEFAULT 'user',

    -- 账户状态: TRUE=活跃, FALSE=禁用
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- 头像 URL（可选）
    avatar_url          VARCHAR(500),

    -- 用户配置偏好（JSONB：主题、通知设置、默认工作区等）
    preferences         JSONB DEFAULT '{}',

    -- 最后登录时间
    last_login_at       TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 唯一约束
    CONSTRAINT uk_users_username UNIQUE (username),
    CONSTRAINT uk_users_email UNIQUE (email),

    -- 角色校验
    CONSTRAINT chk_users_role CHECK (role IN ('admin', 'user'))
);

-- 注释
COMMENT ON TABLE users IS '用户表：存储系统注册用户的基本信息和认证信息';
COMMENT ON COLUMN users.id IS '自增主键，内部使用';
COMMENT ON COLUMN users.username IS '用户名，全局唯一，用于登录和显示';
COMMENT ON COLUMN users.email IS '邮箱地址，全局唯一';
COMMENT ON COLUMN users.hashed_password IS 'bcrypt 哈希后的密码';
COMMENT ON COLUMN users.role IS '用户角色：admin 为管理员，user 为普通用户';
COMMENT ON COLUMN users.is_active IS '账户是否激活';
COMMENT ON COLUMN users.avatar_url IS '头像图片 URL';
COMMENT ON COLUMN users.preferences IS '用户偏好设置（JSONB）';
COMMENT ON COLUMN users.last_login_at IS '最后登录时间';
COMMENT ON COLUMN users.created_at IS '创建时间';
COMMENT ON COLUMN users.updated_at IS '更新时间';

-- 更新时间触发器
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.1.2 workspaces — 工作空间表

```sql
-- ============================================================
-- 工作空间表: 支持多级目录结构，用户可组织项目到不同工作空间
-- 使用路径枚举模型（path_enum）实现树形结构
-- ============================================================
CREATE TABLE workspaces (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 所属用户
    user_id             BIGINT NOT NULL,

    -- 工作空间名称
    name                VARCHAR(100) NOT NULL,

    -- 描述
    description         VARCHAR(500),

    -- 父工作空间ID（NULL 表示根级）
    parent_id           BIGINT,

    -- 路径枚举（如 /1/5/12/，加速子树查询）
    path                VARCHAR(1000) NOT NULL DEFAULT '/',

    -- 层级深度（根级=0）
    depth               INTEGER NOT NULL DEFAULT 0,

    -- 排序权重
    sort_order          INTEGER NOT NULL DEFAULT 0,

    -- 工作空间配置（JSONB：颜色标记、图标、默认参数等）
    config              JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_workspaces_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_workspaces_parent_id
        FOREIGN KEY (parent_id) REFERENCES workspaces(id)
        ON DELETE CASCADE,

    -- 层级深度校验
    CONSTRAINT chk_workspaces_depth CHECK (depth >= 0),

    -- 同一父级下名称唯一
    CONSTRAINT uk_workspaces_name_per_parent 
        UNIQUE (user_id, parent_id, name)
);

-- 注释
COMMENT ON TABLE workspaces IS '工作空间表：支持多级目录的树形结构，用于组织项目';
COMMENT ON COLUMN workspaces.user_id IS '所属用户ID';
COMMENT ON COLUMN workspaces.name IS '工作空间名称';
COMMENT ON COLUMN workspaces.parent_id IS '父工作空间ID，NULL 表示根级';
COMMENT ON COLUMN workspaces.path IS '路径枚举，格式如 /1/5/12/';
COMMENT ON COLUMN workspaces.depth IS '层级深度，根级为0';
COMMENT ON COLUMN workspaces.config IS '工作空间配置（JSONB）';

CREATE TRIGGER trg_workspaces_updated_at
    BEFORE UPDATE ON workspaces
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 防止循环引用的触发器
CREATE OR REPLACE FUNCTION check_workspace_cycle()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.parent_id IS NOT NULL THEN
        IF NEW.path LIKE '%/' || NEW.parent_id || '/%' THEN
            RAISE EXCEPTION 'Workspace cycle detected';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_workspaces_no_cycle
    BEFORE INSERT OR UPDATE ON workspaces
    FOR EACH ROW
    EXECUTE FUNCTION check_workspace_cycle();
```


---

### 2.2 流程域

#### 2.2.1 flow_categories — 流程分类表

```sql
-- ============================================================
-- 流程分类表: 对流程定义进行分类管理（如 RNA-seq, ChIP-seq, 基因组等）
-- 支持多级分类
-- ============================================================
CREATE TABLE flow_categories (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 分类名称
    name                VARCHAR(100) NOT NULL,

    -- 分类标识（URL-friendly）
    slug                VARCHAR(100) NOT NULL,

    -- 父分类ID（NULL 表示顶级分类）
    parent_id           BIGINT,

    -- 描述
    description         VARCHAR(500),

    -- 图标（前端使用的图标名称）
    icon                VARCHAR(50),

    -- 颜色标记
    color               VARCHAR(20) DEFAULT '#1890ff',

    -- 排序权重
    sort_order          INTEGER NOT NULL DEFAULT 0,

    -- 是否激活
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- 分类元数据（JSONB：如所属领域、常用物种等）
    metadata            JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_flow_categories_parent_id
        FOREIGN KEY (parent_id) REFERENCES flow_categories(id)
        ON DELETE SET NULL,

    -- 同一父级下 slug 唯一
    CONSTRAINT uk_flow_categories_slug 
        UNIQUE (parent_id, slug)
);

COMMENT ON TABLE flow_categories IS '流程分类表：对组学分析流程进行分类管理';
COMMENT ON COLUMN flow_categories.name IS '分类名称，如转录组分析';
COMMENT ON COLUMN flow_categories.slug IS '分类标识，URL友好，如 rna-seq';
COMMENT ON COLUMN flow_categories.parent_id IS '父分类ID，支持多级分类';
COMMENT ON COLUMN flow_categories.metadata IS '分类元数据（JSONB）';

CREATE TRIGGER trg_flow_categories_updated_at
    BEFORE UPDATE ON flow_categories
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.2.2 flow_definitions — 流程定义表

```sql
-- ============================================================
-- 流程定义表: 存储 YAML 解析后的结构化流程配置
-- 这是系统的核心表之一，定义了一个分析流程的完整配置
-- ============================================================
CREATE TABLE flow_definitions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 流程唯一标识（如 rna-seq-star-dese2）
    flow_key            VARCHAR(100) NOT NULL,

    -- 流程名称（如 "RNA-seq 差异表达分析"）
    name                VARCHAR(200) NOT NULL,

    -- 所属分类
    category_id         BIGINT,

    -- 版本号（语义化版本，如 1.0.2）
    version             VARCHAR(20) NOT NULL DEFAULT '1.0.0',

    -- 描述
    description         TEXT,

    -- 原始 YAML 文本（完整保留，便于回溯）
    yaml_content        TEXT NOT NULL,

    -- 解析后的配置（JSONB：参数定义、步骤定义、条件规则等）
    parsed_config       JSONB NOT NULL DEFAULT '{}',

    -- 样本表必填列定义（JSONB 数组）
    sample_sheet_columns JSONB DEFAULT '[]',

    -- 执行配置（JSONB：engine、snakefile 路径、resources 等）
    execution_config    JSONB DEFAULT '{}',

    -- 是否激活（可禁用旧版本）
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- 是否公开（所有用户可见，否则仅创建者和管理员可见）
    is_public           BOOLEAN NOT NULL DEFAULT FALSE,

    -- 创建者
    created_by          BIGINT NOT NULL,

    -- 使用统计（减少 JOIN 查询）
    usage_count         INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_flow_definitions_category_id
        FOREIGN KEY (category_id) REFERENCES flow_categories(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_flow_definitions_created_by
        FOREIGN KEY (created_by) REFERENCES users(id)
        ON DELETE RESTRICT,

    -- flow_key + version 唯一
    CONSTRAINT uk_flow_definitions_key_version 
        UNIQUE (flow_key, version)
);

COMMENT ON TABLE flow_definitions IS '流程定义表：存储 YAML 解析后的结构化分析流程配置';
COMMENT ON COLUMN flow_definitions.flow_key IS '流程唯一标识，如 rna-seq-star-deseq2';
COMMENT ON COLUMN flow_definitions.name IS '流程显示名称';
COMMENT ON COLUMN flow_definitions.category_id IS '所属分类ID';
COMMENT ON COLUMN flow_definitions.version IS '语义化版本号';
COMMENT ON COLUMN flow_definitions.yaml_content IS '原始 YAML 文本内容';
COMMENT ON COLUMN flow_definitions.parsed_config IS '解析后的结构化配置（JSONB）';
COMMENT ON COLUMN flow_definitions.sample_sheet_columns IS '样本表必填列定义（JSONB 数组）';
COMMENT ON COLUMN flow_definitions.execution_config IS '执行引擎配置（JSONB）';
COMMENT ON COLUMN flow_definitions.is_active IS '是否激活';
COMMENT ON COLUMN flow_definitions.is_public IS '是否对所有用户公开';
COMMENT ON COLUMN flow_definitions.created_by IS '创建者用户ID';
COMMENT ON COLUMN flow_definitions.usage_count IS '使用次数统计';

CREATE TRIGGER trg_flow_definitions_updated_at
    BEFORE UPDATE ON flow_definitions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

---

### 2.3 项目与文件域

#### 2.3.1 projects — 项目表

```sql
-- ============================================================
-- 项目表: 存储用户创建的组学分析项目
-- 项目是样本、任务、文件的顶层容器
-- ============================================================
CREATE TABLE projects (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 项目ID（对外暴露的 UUID）
    project_uuid        UUID NOT NULL DEFAULT gen_random_uuid(),

    -- 项目名稱
    name                VARCHAR(200) NOT NULL,

    -- 描述
    description         TEXT,

    -- 所属用户
    user_id             BIGINT NOT NULL,

    -- 所属工作空间（NULL 表示未分类）
    workspace_id        BIGINT,

    -- 项目存储路径（服务器上的绝对路径）
    storage_path        VARCHAR(1000) NOT NULL,

    -- 项目配置（JSONB：物种、参考基因组、默认参数等）
    config              JSONB DEFAULT '{}',

    -- 项目标签（TEXT 数组，便于快速筛选）
    tags                TEXT[] DEFAULT '{}',

    -- 项目状态
    status              VARCHAR(20) NOT NULL DEFAULT 'active',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_projects_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_projects_workspace_id
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
        ON DELETE SET NULL,

    -- UUID 唯一
    CONSTRAINT uk_projects_uuid UNIQUE (project_uuid),

    -- 状态校验
    CONSTRAINT chk_projects_status 
        CHECK (status IN ('active', 'archived', 'deleted'))
);

COMMENT ON TABLE projects IS '项目表：组学分析项目的顶层容器';
COMMENT ON COLUMN projects.project_uuid IS '对外暴露的项目 UUID';
COMMENT ON COLUMN projects.name IS '项目名称';
COMMENT ON COLUMN projects.user_id IS '项目所有者用户ID';
COMMENT ON COLUMN projects.workspace_id IS '所属工作空间ID';
COMMENT ON COLUMN projects.storage_path IS '项目文件存储路径';
COMMENT ON COLUMN projects.config IS '项目配置（JSONB：物种、参考基因组等）';
COMMENT ON COLUMN projects.tags IS '项目标签数组';
COMMENT ON COLUMN projects.status IS '项目状态：active/归档/已删除';

CREATE TRIGGER trg_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.3.2 samples — 样本表

```sql
-- ============================================================
-- 样本表: 存储项目中的生物样本信息和文件映射
-- 支持样本表（sample sheet）解析后的结构化数据存储
-- ============================================================
CREATE TABLE samples (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 所属项目
    project_id          BIGINT NOT NULL,

    -- 样本名称
    name                VARCHAR(200) NOT NULL,

    -- 样本别名/显示名称
    display_name        VARCHAR(200),

    -- 文件类型（fastq/csv/mtx/bed/bam/gtf/etc）
    file_type           VARCHAR(50),

    -- 文件路径（服务器上的绝对路径）
    file_path           VARCHAR(1000),

    -- 配对文件路径（如 paired-end FASTQ 的 R2）
    pair_file_path      VARCHAR(1000),

    -- 文件大小（字节）
    file_size           BIGINT,

    -- 样本元数据（JSONB：read_length、platform、library_prep 等）
    metadata            JSONB DEFAULT '{}',

    -- 样本表结构化数据（JSONB：样本表解析后的完整列数据）
    sample_sheet_data   JSONB DEFAULT '{}',

    -- 样本分组信息（JSONB：condition、replicate、batch 等）
    grouping            JSONB DEFAULT '{}',

    -- 质量评估结果（JSONB：QC 统计、FastQC 结果等）
    qc_results          JSONB DEFAULT '{}',

    -- 描述
    description         TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_samples_project_id
        FOREIGN KEY (project_id) REFERENCES projects(id)
        ON DELETE CASCADE,

    -- 同一项目下样本名称唯一
    CONSTRAINT uk_samples_name_per_project 
        UNIQUE (project_id, name)
);

COMMENT ON TABLE samples IS '样本表：存储项目中的生物样本信息和文件映射';
COMMENT ON COLUMN samples.project_id IS '所属项目ID';
COMMENT ON COLUMN samples.name IS '样本名称（通常是文件名或样本ID）';
COMMENT ON COLUMN samples.file_type IS '文件类型：fastq/csv/mtx/bed/bam 等';
COMMENT ON COLUMN samples.file_path IS '样本文件绝对路径';
COMMENT ON COLUMN samples.pair_file_path IS '配对文件路径（PE测序R2）';
COMMENT ON COLUMN samples.file_size IS '文件大小（字节）';
COMMENT ON COLUMN samples.metadata IS '样本元数据（JSONB）';
COMMENT ON COLUMN samples.sample_sheet_data IS '样本表完整列数据（JSONB）';
COMMENT ON COLUMN samples.grouping IS '样本分组信息（JSONB）';
COMMENT ON COLUMN samples.qc_results IS '质量评估结果（JSONB）';

CREATE TRIGGER trg_samples_updated_at
    BEFORE UPDATE ON samples
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.3.3 file_records — 文件记录表

```sql
-- ============================================================
-- 文件记录表: 通用文件管理，跟踪系统中的所有文件
-- 包括输入文件、输出结果、参考基因组、日志文件等
-- ============================================================
CREATE TABLE file_records (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 所属用户
    user_id             BIGINT NOT NULL,

    -- 所属项目（NULL 表示全局文件）
    project_id          BIGINT,

    -- 文件名称
    file_name           VARCHAR(255) NOT NULL,

    -- 文件路径（服务器上的绝对路径）
    file_path           VARCHAR(1000) NOT NULL,

    -- 文件大小（字节）
    file_size           BIGINT NOT NULL DEFAULT 0,

    -- MIME 类型
    mime_type           VARCHAR(100),

    -- 文件分类：input/output/reference/log/temp/report
    category            VARCHAR(20) NOT NULL DEFAULT 'output',

    -- 文件校验和（SHA-256）
    checksum            VARCHAR(64),

    -- 文件描述
    description         VARCHAR(500),

    -- 关联的任务ID（NULL 表示非任务产出）
    task_id             BIGINT,

    -- 关联的流程步骤名称
    flow_step_name      VARCHAR(200),

    -- 是否可见（隐藏临时文件）
    is_visible          BOOLEAN NOT NULL DEFAULT TRUE,

    -- 额外元数据（JSONB：如压缩格式、索引文件路径等）
    metadata            JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_file_records_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_file_records_project_id
        FOREIGN KEY (project_id) REFERENCES projects(id)
        ON DELETE CASCADE,

    -- 分类校验
    CONSTRAINT chk_file_records_category 
        CHECK (category IN ('input', 'output', 'reference', 'log', 'temp', 'report'))
);

COMMENT ON TABLE file_records IS '文件记录表：通用文件管理，跟踪系统中所有文件';
COMMENT ON COLUMN file_records.user_id IS '文件所有者用户ID';
COMMENT ON COLUMN file_records.project_id IS '所属项目ID，NULL 为全局文件';
COMMENT ON COLUMN file_records.file_name IS '文件名称';
COMMENT ON COLUMN file_records.file_path IS '文件绝对路径';
COMMENT ON COLUMN file_records.file_size IS '文件大小（字节）';
COMMENT ON COLUMN file_records.mime_type IS 'MIME 类型';
COMMENT ON COLUMN file_records.category IS '文件分类：input/output/reference/log/temp/report';
COMMENT ON COLUMN file_records.checksum IS 'SHA-256 校验和';
COMMENT ON COLUMN file_records.task_id IS '产生该文件的任务ID';
COMMENT ON COLUMN file_records.flow_step_name IS '产生该文件的流程步骤';
COMMENT ON COLUMN file_records.metadata IS '文件元数据（JSONB）';
```


---

### 2.4 任务域

#### 2.4.1 tasks — 任务表

```sql
-- ============================================================
-- 任务表: 存储用户提交的分析任务，是系统的核心实体
-- 记录了任务从提交到完成的完整生命周期
-- ============================================================
CREATE TABLE tasks (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 任务 UUID（对外暴露的唯一标识）
    task_id             UUID NOT NULL DEFAULT gen_random_uuid(),

    -- 任务名称（用户自定义或系统生成）
    name                VARCHAR(255) NOT NULL,

    -- 描述
    description         TEXT,

    -- 提交者
    user_id             BIGINT NOT NULL,

    -- 所属项目
    project_id          BIGINT NOT NULL,

    -- 使用的流程定义
    flow_definition_id  BIGINT NOT NULL,

    -- 任务状态（严格状态机）
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',

    -- 用户提交的参数值（JSONB：用户填写的表单参数）
    parameters          JSONB NOT NULL DEFAULT '{}',

    -- 执行模式：local（本地）/ remote（远程集群）
    execution_mode      VARCHAR(20) NOT NULL DEFAULT 'local',

    -- 执行后端：snakemake / nextflow / cromwell
    execution_backend   VARCHAR(20) NOT NULL DEFAULT 'snakemake',

    -- 工作目录（任务执行的绝对路径）
    working_directory   VARCHAR(1000),

    -- 配置文件路径
    config_file_path    VARCHAR(1000),

    -- Snakefile / 主流程文件路径
    snakefile_path      VARCHAR(1000),

    -- 资源请求（JSONB：cores, memory_gb, runtime_hours, queue 等）
    resources           JSONB DEFAULT '{}',

    -- 进度百分比（0-100）
    progress_percent    INTEGER NOT NULL DEFAULT 0,

    -- 当前执行步骤名称
    current_step        VARCHAR(200),

    -- 总步骤数
    total_steps         INTEGER DEFAULT 0,

    -- 当前步骤序号
    current_step_index  INTEGER DEFAULT 0,

    -- 结果摘要（JSONB：结果文件列表、统计信息等）
    results_summary     JSONB DEFAULT '{}',

    -- 错误信息（失败时记录）
    error_message       TEXT,

    -- 开始执行时间
    started_at          TIMESTAMPTZ,

    -- 完成时间（成功或失败）
    completed_at        TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_tasks_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_tasks_project_id
        FOREIGN KEY (project_id) REFERENCES projects(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_tasks_flow_definition_id
        FOREIGN KEY (flow_definition_id) REFERENCES flow_definitions(id)
        ON DELETE RESTRICT,

    -- UUID 唯一
    CONSTRAINT uk_tasks_task_id UNIQUE (task_id),

    -- 状态机校验
    CONSTRAINT chk_tasks_status 
        CHECK (status IN ('pending', 'submitted', 'running', 'completed', 'failed', 'cancelled')),

    -- 执行模式校验
    CONSTRAINT chk_tasks_execution_mode 
        CHECK (execution_mode IN ('local', 'remote')),

    -- 执行后端校验
    CONSTRAINT chk_tasks_execution_backend 
        CHECK (execution_backend IN ('snakemake', 'nextflow', 'cromwell')),

    -- 进度百分比范围校验
    CONSTRAINT chk_tasks_progress 
        CHECK (progress_percent >= 0 AND progress_percent <= 100)
);

COMMENT ON TABLE tasks IS '任务表：存储用户提交的组学分析任务';
COMMENT ON COLUMN tasks.task_id IS '任务 UUID，对外暴露的唯一标识';
COMMENT ON COLUMN tasks.name IS '任务名称';
COMMENT ON COLUMN tasks.user_id IS '任务提交者用户ID';
COMMENT ON COLUMN tasks.project_id IS '所属项目ID';
COMMENT ON COLUMN tasks.flow_definition_id IS '使用的流程定义ID';
COMMENT ON COLUMN tasks.status IS '任务状态：pending/submitted/running/completed/failed/cancelled';
COMMENT ON COLUMN tasks.parameters IS '用户提交的参数值（JSONB）';
COMMENT ON COLUMN tasks.execution_mode IS '执行模式：local 或 remote';
COMMENT ON COLUMN tasks.execution_backend IS '执行后端：snakemake/nextflow/cromwell';
COMMENT ON COLUMN tasks.working_directory IS '任务工作目录绝对路径';
COMMENT ON COLUMN tasks.resources IS '资源请求配置（JSONB）';
COMMENT ON COLUMN tasks.progress_percent IS '执行进度百分比 0-100';
COMMENT ON COLUMN tasks.current_step IS '当前执行步骤名称';
COMMENT ON COLUMN tasks.results_summary IS '结果摘要（JSONB）';
COMMENT ON COLUMN tasks.error_message IS '错误信息（失败时）';
COMMENT ON COLUMN tasks.started_at IS '开始执行时间';
COMMENT ON COLUMN tasks.completed_at IS '完成时间';

CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.4.2 task_logs — 任务日志表

```sql
-- ============================================================
-- 任务日志表: 存储任务执行过程中的日志输出
-- 设计说明: 对于大日志（>10MB），建议存文件，表中保留摘要和文件路径
-- ============================================================
CREATE TABLE task_logs (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 关联任务
    task_id             BIGINT NOT NULL,

    -- 日志类型
    log_type            VARCHAR(20) NOT NULL DEFAULT 'stdout',

    -- 日志内容（TEXT，适合中小日志；大日志建议存文件，此字段存摘要）
    content             TEXT,

    -- 日志文件路径（内容过大时，日志存文件，此字段指向文件）
    log_file_path       VARCHAR(1000),

    -- 内容大小（字节，用于判断是否在表中存储）
    content_size        BIGINT DEFAULT 0,

    -- 所属步骤名称
    step_name           VARCHAR(200),

    -- 步骤序号
    step_index          INTEGER,

    -- 日志级别：DEBUG/INFO/WARNING/ERROR/CRITICAL
    log_level           VARCHAR(20) DEFAULT 'INFO',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_task_logs_task_id
        FOREIGN KEY (task_id) REFERENCES tasks(id)
        ON DELETE CASCADE,

    -- 日志类型校验
    CONSTRAINT chk_task_logs_type 
        CHECK (log_type IN ('stdout', 'stderr', 'system', 'progress', 'debug')),

    -- 日志级别校验
    CONSTRAINT chk_task_logs_level 
        CHECK (log_level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'))
);

-- 为日志表设置表级注释和策略
COMMENT ON TABLE task_logs IS '任务日志表：存储任务执行过程的日志输出';
COMMENT ON COLUMN task_logs.task_id IS '关联任务ID';
COMMENT ON COLUMN task_logs.log_type IS '日志类型：stdout/stderr/system/progress/debug';
COMMENT ON COLUMN task_logs.content IS '日志内容文本（中小日志）';
COMMENT ON COLUMN task_logs.log_file_path IS '日志文件路径（大日志存文件）';
COMMENT ON COLUMN task_logs.content_size IS '内容大小（字节）';
COMMENT ON COLUMN task_logs.step_name IS '产生日志的流程步骤名称';
COMMENT ON COLUMN task_logs.step_index IS '步骤序号';
COMMENT ON COLUMN task_logs.log_level IS '日志级别';

-- 大日志存储建议触发器
CREATE OR REPLACE FUNCTION handle_large_log()
RETURNS TRIGGER AS $$
BEGIN
    -- 如果内容超过 1MB（约 1,048,576 字节），标记为大日志
    IF LENGTH(COALESCE(NEW.content, '')) > 1048576 THEN
        NEW.content_size = LENGTH(NEW.content);
        -- 保留前 10000 字符作为摘要，剩余部分应通过应用层写入文件
        NEW.content = LEFT(NEW.content, 10000) || E'\n... [日志过大，完整内容已保存到文件]';
    ELSE
        NEW.content_size = LENGTH(COALESCE(NEW.content, ''));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_task_logs_handle_large
    BEFORE INSERT ON task_logs
    FOR EACH ROW
    EXECUTE FUNCTION handle_large_log();
```

#### 2.4.3 task_events — 任务事件表

```sql
-- ============================================================
-- 任务事件表: 记录任务状态变更历史和重要事件
-- 用于审计追踪和状态机回放
-- ============================================================
CREATE TABLE task_events (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 关联任务
    task_id             BIGINT NOT NULL,

    -- 事件类型
    event_type          VARCHAR(50) NOT NULL,

    -- 变更前状态
    from_status         VARCHAR(20),

    -- 变更后状态
    to_status           VARCHAR(20),

    -- 事件消息
    message             TEXT,

    -- 事件详情（JSONB：额外上下文信息）
    details             JSONB DEFAULT '{}',

    -- 触发者（用户ID 或 system）
    triggered_by        VARCHAR(100) DEFAULT 'system',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_task_events_task_id
        FOREIGN KEY (task_id) REFERENCES tasks(id)
        ON DELETE CASCADE,

    -- 事件类型校验
    CONSTRAINT chk_task_events_type 
        CHECK (event_type IN (
            'status_changed',      -- 状态变更
            'step_started',        -- 步骤开始
            'step_completed',      -- 步骤完成
            'step_failed',         -- 步骤失败
            'resource_allocated',  -- 资源分配
            'resource_released',   -- 资源释放
            'user_cancelled',      -- 用户取消
            'system_error',        -- 系统错误
            'retry_attempted',     -- 重试尝试
            'notification_sent'    -- 通知发送
        ))
);

COMMENT ON TABLE task_events IS '任务事件表：记录任务状态变更历史和重要事件';
COMMENT ON COLUMN task_events.task_id IS '关联任务ID';
COMMENT ON COLUMN task_events.event_type IS '事件类型';
COMMENT ON COLUMN task_events.from_status IS '变更前状态';
COMMENT ON COLUMN task_events.to_status IS '变更后状态';
COMMENT ON COLUMN task_events.message IS '事件描述消息';
COMMENT ON COLUMN task_events.details IS '事件详情（JSONB）';
COMMENT ON COLUMN task_events.triggered_by IS '触发者：用户ID 或 system';
```


---

### 2.5 AI 对话域

#### 2.5.1 chat_sessions — 对话会话表

```sql
-- ============================================================
-- 对话会话表: 存储用户与 AI 的对话会话
-- 每个会话包含一组连续的消息，支持上下文快照
-- ============================================================
CREATE TABLE chat_sessions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 会话 UUID（对外暴露）
    session_id          UUID NOT NULL DEFAULT gen_random_uuid(),

    -- 所属用户
    user_id             BIGINT NOT NULL,

    -- 会话标题（自动生成或用户编辑）
    title               VARCHAR(255),

    -- 上下文快照（JSONB：当前项目ID、流程ID、任务ID等）
    context_snapshot    JSONB DEFAULT '{}',

    -- 使用的 AI 模型
    model_used          VARCHAR(50) DEFAULT 'gpt-4',

    -- 系统提示词（可为特定会话定制）
    system_prompt       TEXT,

    -- 会话状态
    status              VARCHAR(20) NOT NULL DEFAULT 'active',

    -- 会话配置（JSONB：温度、最大token、是否流式等）
    config              JSONB DEFAULT '{}',

    -- 消息数量统计（减少 JOIN）
    message_count       INTEGER NOT NULL DEFAULT 0,

    -- 总 token 消耗统计
    total_tokens        INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_chat_sessions_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    -- UUID 唯一
    CONSTRAINT uk_chat_sessions_session_id UNIQUE (session_id),

    -- 状态校验
    CONSTRAINT chk_chat_sessions_status 
        CHECK (status IN ('active', 'archived', 'deleted'))
);

COMMENT ON TABLE chat_sessions IS '对话会话表：用户与 AI 的对话会话';
COMMENT ON COLUMN chat_sessions.session_id IS '会话 UUID';
COMMENT ON COLUMN chat_sessions.user_id IS '所属用户ID';
COMMENT ON COLUMN chat_sessions.title IS '会话标题';
COMMENT ON COLUMN chat_sessions.context_snapshot IS '上下文快照（JSONB：项目ID、流程ID、任务ID等）';
COMMENT ON COLUMN chat_sessions.model_used IS '使用的 AI 模型';
COMMENT ON COLUMN chat_sessions.system_prompt IS '系统提示词';
COMMENT ON COLUMN chat_sessions.status IS '会话状态：active/archived/deleted';
COMMENT ON COLUMN chat_sessions.config IS '会话配置（JSONB）';
COMMENT ON COLUMN chat_sessions.message_count IS '消息数量';
COMMENT ON COLUMN chat_sessions.total_tokens IS '总 token 消耗';

CREATE TRIGGER trg_chat_sessions_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.5.2 chat_messages — 对话消息表

```sql
-- ============================================================
-- 对话消息表: 存储会话中的单条消息
-- 支持普通对话、工具调用、MCP 工具调用等多种消息类型
-- ============================================================
CREATE TABLE chat_messages (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 所属会话
    session_id          BIGINT NOT NULL,

    -- 消息角色：user/assistant/system/tool
    role                VARCHAR(20) NOT NULL,

    -- 消息内容
    content             TEXT NOT NULL DEFAULT '',

    -- AI 调用的工具列表（JSONB：function calling / tool_calls）
    tool_calls          JSONB DEFAULT '[]',

    -- 工具执行结果（JSONB：tool 返回的数据）
    tool_results        JSONB DEFAULT '[]',

    -- MCP Server ID（如为 MCP 工具调用）
    mcp_server_id       BIGINT,

    -- MCP 工具名称
    mcp_tool_name       VARCHAR(200),

    -- 引用的上下文（JSONB：引用的文件、任务结果等）
    references_context  JSONB DEFAULT '[]',

    -- Token 计数（JSONB：prompt_tokens, completion_tokens, total_tokens）
    token_count         JSONB DEFAULT '{}',

    -- 消息元数据（JSONB：如思考过程、评分等）
    metadata            JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_chat_messages_session_id
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_chat_messages_mcp_server_id
        FOREIGN KEY (mcp_server_id) REFERENCES mcp_servers(id)
        ON DELETE SET NULL,

    -- 角色校验
    CONSTRAINT chk_chat_messages_role 
        CHECK (role IN ('user', 'assistant', 'system', 'tool')),

    -- MCP 工具调用的约束：如果 mcp_tool_name 不为空，则 mcp_server_id 也不能为空
    CONSTRAINT chk_chat_messages_mcp_consistency 
        CHECK (
            (mcp_tool_name IS NULL AND mcp_server_id IS NULL) OR
            (mcp_tool_name IS NOT NULL AND mcp_server_id IS NOT NULL)
        )
);

COMMENT ON TABLE chat_messages IS '对话消息表：会话中的单条消息';
COMMENT ON COLUMN chat_messages.session_id IS '所属会话ID';
COMMENT ON COLUMN chat_messages.role IS '消息角色：user/assistant/system/tool';
COMMENT ON COLUMN chat_messages.content IS '消息内容文本';
COMMENT ON COLUMN chat_messages.tool_calls IS 'AI 调用的工具列表（JSONB）';
COMMENT ON COLUMN chat_messages.tool_results IS '工具执行结果（JSONB）';
COMMENT ON COLUMN chat_messages.mcp_server_id IS 'MCP Server ID（MCP工具调用时）';
COMMENT ON COLUMN chat_messages.mcp_tool_name IS 'MCP 工具名称';
COMMENT ON COLUMN chat_messages.token_count IS 'Token 计数（JSONB）';
COMMENT ON COLUMN chat_messages.metadata IS '消息元数据（JSONB）';

-- 消息插入后自动更新会话统计的触发器
CREATE OR REPLACE FUNCTION update_chat_session_stats()
RETURNS TRIGGER AS $$
DECLARE
    total_tokens_sum INTEGER;
BEGIN
    -- 更新消息计数
    UPDATE chat_sessions
    SET message_count = message_count + 1
    WHERE id = NEW.session_id;

    -- 更新 token 统计
    SELECT COALESCE(SUM((COALESCE(token_count->>'total_tokens', '0'))::INTEGER), 0)
    INTO total_tokens_sum
    FROM chat_messages
    WHERE session_id = NEW.session_id;

    UPDATE chat_sessions
    SET total_tokens = total_tokens_sum
    WHERE id = NEW.session_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_chat_messages_update_stats
    AFTER INSERT ON chat_messages
    FOR EACH ROW
    EXECUTE FUNCTION update_chat_session_stats();
```

---

### 2.6 MCP 域

#### 2.6.1 mcp_servers — MCP Server 注册表

```sql
-- ============================================================
-- MCP Server 注册表: 存储外部 MCP (Model Context Protocol) 服务器信息
-- 支持 SSE 和 stdio 两种传输方式
-- ============================================================
CREATE TABLE mcp_servers (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Server 名称（显示用）
    name                VARCHAR(100) NOT NULL,

    -- Server 描述
    description         VARCHAR(500),

    -- Server URL 或命令（sse 为 URL，stdio 为命令路径）
    server_url          VARCHAR(1000) NOT NULL,

    -- 传输类型：sse (Server-Sent Events) / stdio (标准输入输出)
    transport_type      VARCHAR(20) NOT NULL DEFAULT 'sse',

    -- 工具目录（JSONB：注册时自动拉取的工具列表）
    tools_catalog       JSONB DEFAULT '[]',

    -- 是否激活
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- 认证配置（JSONB：API key、token、header 等）
    auth_config         JSONB DEFAULT '{}',

    -- 健康状态：healthy / unhealthy / unknown
    health_status       VARCHAR(20) DEFAULT 'unknown',

    -- 最后心跳时间
    last_heartbeat_at   TIMESTAMPTZ,

    -- Server 配置（JSONB：超时、重试、环境变量等）
    server_config       JSONB DEFAULT '{}',

    -- 创建者
    created_by          BIGINT NOT NULL,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_mcp_servers_created_by
        FOREIGN KEY (created_by) REFERENCES users(id)
        ON DELETE RESTRICT,

    -- 传输类型校验
    CONSTRAINT chk_mcp_servers_transport 
        CHECK (transport_type IN ('sse', 'stdio')),

    -- 健康状态校验
    CONSTRAINT chk_mcp_servers_health 
        CHECK (health_status IN ('healthy', 'unhealthy', 'unknown')),

    -- 名称唯一
    CONSTRAINT uk_mcp_servers_name UNIQUE (name)
);

COMMENT ON TABLE mcp_servers IS 'MCP Server 注册表：外部 MCP 服务器的配置和状态';
COMMENT ON COLUMN mcp_servers.name IS 'Server 名称';
COMMENT ON COLUMN mcp_servers.server_url IS 'Server URL（sse）或命令路径（stdio）';
COMMENT ON COLUMN mcp_servers.transport_type IS '传输类型：sse 或 stdio';
COMMENT ON COLUMN mcp_servers.tools_catalog IS '工具目录（JSONB，注册时自动拉取）';
COMMENT ON COLUMN mcp_servers.is_active IS '是否激活';
COMMENT ON COLUMN mcp_servers.auth_config IS '认证配置（JSONB）';
COMMENT ON COLUMN mcp_servers.health_status IS '健康状态';
COMMENT ON COLUMN mcp_servers.last_heartbeat_at IS '最后心跳时间';
COMMENT ON COLUMN mcp_servers.server_config IS 'Server 配置（JSONB）';

CREATE TRIGGER trg_mcp_servers_updated_at
    BEFORE UPDATE ON mcp_servers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.6.2 mcp_tool_invocations — MCP 工具调用记录

```sql
-- ============================================================
-- MCP 工具调用记录表: 记录每次 MCP 工具调用的详细信息
-- 用于审计、调试和性能分析
-- ============================================================
CREATE TABLE mcp_tool_invocations (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 调用的 MCP Server
    mcp_server_id       BIGINT NOT NULL,

    -- 调用的工具名称
    tool_name           VARCHAR(200) NOT NULL,

    -- 请求载荷（JSONB：传递给工具的参数）
    request_payload     JSONB NOT NULL DEFAULT '{}',

    -- 响应载荷（JSONB：工具返回的结果）
    response_payload    JSONB DEFAULT '{}',

    -- 调用状态
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',

    -- 错误信息
    error_message       TEXT,

    -- 执行耗时（毫秒）
    duration_ms         INTEGER,

    -- 关联的任务 ID（如工具调用触发了任务）
    task_id             BIGINT,

    -- 关联的对话消息 ID
    chat_message_id     BIGINT,

    -- 调用者用户 ID
    user_id             BIGINT,

    -- 调用元数据（JSONB：如重试次数、超时设置等）
    metadata            JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMPTZ,

    -- 外键约束
    CONSTRAINT fk_mcp_tool_invocations_server_id
        FOREIGN KEY (mcp_server_id) REFERENCES mcp_servers(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_mcp_tool_invocations_task_id
        FOREIGN KEY (task_id) REFERENCES tasks(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_mcp_tool_invocations_chat_message_id
        FOREIGN KEY (chat_message_id) REFERENCES chat_messages(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_mcp_tool_invocations_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE SET NULL,

    -- 状态校验
    CONSTRAINT chk_mcp_tool_invocations_status 
        CHECK (status IN ('pending', 'running', 'success', 'error', 'timeout', 'cancelled'))
);

COMMENT ON TABLE mcp_tool_invocations IS 'MCP 工具调用记录表：每次 MCP 工具调用的详细信息';
COMMENT ON COLUMN mcp_tool_invocations.mcp_server_id IS 'MCP Server ID';
COMMENT ON COLUMN mcp_tool_invocations.tool_name IS '调用的工具名称';
COMMENT ON COLUMN mcp_tool_invocations.request_payload IS '请求参数（JSONB）';
COMMENT ON COLUMN mcp_tool_invocations.response_payload IS '响应结果（JSONB）';
COMMENT ON COLUMN mcp_tool_invocations.status IS '调用状态';
COMMENT ON COLUMN mcp_tool_invocations.duration_ms IS '执行耗时（毫秒）';
COMMENT ON COLUMN mcp_tool_invocations.task_id IS '关联的任务ID';
COMMENT ON COLUMN mcp_tool_invocations.chat_message_id IS '关联的对话消息ID';
COMMENT ON COLUMN mcp_tool_invocations.user_id IS '调用者用户ID';
COMMENT ON COLUMN mcp_tool_invocations.metadata IS '调用元数据（JSONB）';
```


---

## 3. 索引设计

### 3.1 索引设计原则

1. **所有外键自动创建索引**：加速 JOIN 和级联删除
2. **所有 JSONB 字段创建 GIN 索引**：支持灵活查询
3. **常用查询条件字段创建 B-tree 索引**：如 status、created_at
4. **唯一标识字段创建唯一索引**：如 UUID 字段
5. **部分索引**：仅索引活跃记录，减少索引大小
6. **复合索引**：多条件查询场景
7. **全文搜索索引**：名称、描述字段的搜索

### 3.2 用户域索引

```sql
-- ============================================================
-- users 表索引
-- ============================================================

-- 主键索引 (自动生成)
-- PRIMARY KEY (id)

-- 唯一索引 (自动生成)
-- UNIQUE (username), UNIQUE (email)

-- 角色 + 状态索引（查询活跃用户列表）
CREATE INDEX idx_users_role_active ON users(role, is_active);

-- 创建时间索引（排序查询）
CREATE INDEX idx_users_created_at ON users(created_at DESC);

-- 全文搜索索引（用户名和邮箱搜索）
CREATE INDEX idx_users_search ON users 
    USING GIN(to_tsvector('simple', COALESCE(username, '') || ' ' || COALESCE(email, '')));

-- ============================================================
-- workspaces 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_workspaces_user_id ON workspaces(user_id);
CREATE INDEX idx_workspaces_parent_id ON workspaces(parent_id);

-- 路径索引（子树查询：查找某路径下的所有工作空间）
CREATE INDEX idx_workspaces_path ON workspaces USING GIN(path gin_trgm_ops);

-- 用户 + 父级索引（查询某用户的顶层工作空间）
CREATE INDEX idx_workspaces_user_parent ON workspaces(user_id, parent_id);

-- 排序查询
CREATE INDEX idx_workspaces_sort ON workspaces(user_id, sort_order);
```

### 3.3 流程域索引

```sql
-- ============================================================
-- flow_categories 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_flow_categories_parent_id ON flow_categories(parent_id);

-- 父级 + slug 唯一索引（自动生成）
-- UNIQUE (parent_id, slug)

-- 激活状态索引（只查询活跃分类）
CREATE INDEX idx_flow_categories_active ON flow_categories(is_active) 
    WHERE is_active = TRUE;

-- ============================================================
-- flow_definitions 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_flow_definitions_category_id ON flow_definitions(category_id);
CREATE INDEX idx_flow_definitions_created_by ON flow_definitions(created_by);

-- 流程 key 查询（不区分版本）
CREATE INDEX idx_flow_definitions_flow_key ON flow_definitions(flow_key);

-- 激活 + 公开索引（查询用户可见的流程列表）
CREATE INDEX idx_flow_definitions_visible ON flow_definitions(is_active, is_public, created_by) 
    WHERE is_active = TRUE;

-- GIN 索引：parsed_config 中的参数搜索
CREATE INDEX idx_flow_definitions_parsed_config ON flow_definitions 
    USING GIN(parsed_config jsonb_path_ops);

-- GIN 索引：sample_sheet_columns 查询
CREATE INDEX idx_flow_definitions_sample_sheet ON flow_definitions 
    USING GIN(sample_sheet_columns jsonb_path_ops);

-- GIN 索引：execution_config 查询
CREATE INDEX idx_flow_definitions_exec_config ON flow_definitions 
    USING GIN(execution_config jsonb_path_ops);

-- 全文搜索索引（流程名称和描述搜索）
CREATE INDEX idx_flow_definitions_search ON flow_definitions 
    USING GIN(to_tsvector('chinese', COALESCE(name, '') || ' ' || COALESCE(description, '')));

-- 使用次数排序索引
CREATE INDEX idx_flow_definitions_usage ON flow_definitions(usage_count DESC) 
    WHERE is_active = TRUE;

-- 创建时间索引
CREATE INDEX idx_flow_definitions_created_at ON flow_definitions(created_at DESC);
```

### 3.4 项目与文件域索引

```sql
-- ============================================================
-- projects 表索引
-- ============================================================

-- UUID 唯一索引（自动生成）
-- UNIQUE (project_uuid)

-- 外键索引
CREATE INDEX idx_projects_user_id ON projects(user_id);
CREATE INDEX idx_projects_workspace_id ON projects(workspace_id);

-- 用户 + 状态索引（查询用户的活跃项目）
CREATE INDEX idx_projects_user_status ON projects(user_id, status) 
    WHERE status = 'active';

-- 标签 GIN 索引（标签筛选）
CREATE INDEX idx_projects_tags ON projects USING GIN(tags);

-- GIN 索引：config 查询
CREATE INDEX idx_projects_config ON projects USING GIN(config jsonb_path_ops);

-- 全文搜索索引（项目名称和描述）
CREATE INDEX idx_projects_search ON projects 
    USING GIN(to_tsvector('chinese', COALESCE(name, '') || ' ' || COALESCE(description, '')));

-- 创建时间索引
CREATE INDEX idx_projects_created_at ON projects(created_at DESC);

-- ============================================================
-- samples 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_samples_project_id ON samples(project_id);

-- 文件类型索引（按类型筛选样本）
CREATE INDEX idx_samples_file_type ON samples(file_type);

-- GIN 索引：metadata 查询
CREATE INDEX idx_samples_metadata ON samples USING GIN(metadata jsonb_path_ops);

-- GIN 索引：sample_sheet_data 查询
CREATE INDEX idx_samples_sheet_data ON samples USING GIN(sample_sheet_data jsonb_path_ops);

-- GIN 索引：grouping 查询
CREATE INDEX idx_samples_grouping ON samples USING GIN(grouping jsonb_path_ops);

-- 全文搜索索引（样本名称）
CREATE INDEX idx_samples_name_search ON samples 
    USING GIN(to_tsvector('simple', COALESCE(name, '') || ' ' || COALESCE(display_name, '')));

-- 创建时间索引
CREATE INDEX idx_samples_created_at ON samples(created_at DESC);

-- ============================================================
-- file_records 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_file_records_user_id ON file_records(user_id);
CREATE INDEX idx_file_records_project_id ON file_records(project_id);

-- 分类索引（按文件类型筛选）
CREATE INDEX idx_file_records_category ON file_records(category);

-- 用户 + 分类索引
CREATE INDEX idx_file_records_user_category ON file_records(user_id, category);

-- MIME 类型索引
CREATE INDEX idx_file_records_mime_type ON file_records(mime_type);

-- GIN 索引：metadata 查询
CREATE INDEX idx_file_records_metadata ON file_records USING GIN(metadata jsonb_path_ops);

-- 是否可见索引（隐藏临时文件）
CREATE INDEX idx_file_records_visible ON file_records(is_visible) 
    WHERE is_visible = TRUE;

-- 创建时间索引
CREATE INDEX idx_file_records_created_at ON file_records(created_at DESC);
```

### 3.5 任务域索引

```sql
-- ============================================================
-- tasks 表索引
-- ============================================================

-- UUID 唯一索引（自动生成）
-- UNIQUE (task_id)

-- 外键索引
CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_project_id ON tasks(project_id);
CREATE INDEX idx_tasks_flow_definition_id ON tasks(flow_definition_id);

-- 状态索引（最常见的查询条件）
CREATE INDEX idx_tasks_status ON tasks(status);

-- 用户 + 状态索引（查询某用户的特定状态任务）
CREATE INDEX idx_tasks_user_status ON tasks(user_id, status);

-- 项目 + 状态索引
CREATE INDEX idx_tasks_project_status ON tasks(project_id, status);

-- 执行模式 + 后端索引（调度器查询）
CREATE INDEX idx_tasks_execution ON tasks(execution_mode, execution_backend, status) 
    WHERE status IN ('submitted', 'running');

-- GIN 索引：parameters 查询
CREATE INDEX idx_tasks_parameters ON tasks USING GIN(parameters jsonb_path_ops);

-- GIN 索引：resources 查询
CREATE INDEX idx_tasks_resources ON tasks USING GIN(resources jsonb_path_ops);

-- GIN 索引：results_summary 查询
CREATE INDEX idx_tasks_results ON tasks USING GIN(results_summary jsonb_path_ops);

-- 进度索引（查询进行中的任务）
CREATE INDEX idx_tasks_progress ON tasks(progress_percent, status) 
    WHERE status = 'running';

-- 时间范围索引（查询时间段内的任务）
CREATE INDEX idx_tasks_time_range ON tasks(created_at DESC);
CREATE INDEX idx_tasks_started_at ON tasks(started_at DESC);

-- 全文搜索索引（任务名称搜索）
CREATE INDEX idx_tasks_name_search ON tasks 
    USING GIN(to_tsvector('chinese', COALESCE(name, '') || ' ' || COALESCE(description, '')));

-- ============================================================
-- task_logs 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_task_logs_task_id ON task_logs(task_id);

-- 日志类型索引
CREATE INDEX idx_task_logs_type ON task_logs(log_type);

-- 步骤索引（查询某步骤的日志）
CREATE INDEX idx_task_logs_step ON task_logs(task_id, step_index);

-- 日志级别索引
CREATE INDEX idx_task_logs_level ON task_logs(log_level);

-- 创建时间索引（日志时间排序）
CREATE INDEX idx_task_logs_created_at ON task_logs(created_at DESC);

-- 复合索引：任务 + 类型 + 时间（最常用的日志查询模式）
CREATE INDEX idx_task_logs_task_type_time ON task_logs(task_id, log_type, created_at DESC);

-- ============================================================
-- task_events 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_task_events_task_id ON task_events(task_id);

-- 事件类型索引
CREATE INDEX idx_task_events_type ON task_events(event_type);

-- 创建时间索引
CREATE INDEX idx_task_events_created_at ON task_events(created_at DESC);

-- 复合索引：任务 + 时间（查询某任务的事件历史）
CREATE INDEX idx_task_events_task_time ON task_events(task_id, created_at DESC);
```

### 3.6 AI 对话域索引

```sql
-- ============================================================
-- chat_sessions 表索引
-- ============================================================

-- UUID 唯一索引（自动生成）
-- UNIQUE (session_id)

-- 外键索引
CREATE INDEX idx_chat_sessions_user_id ON chat_sessions(user_id);

-- 状态索引
CREATE INDEX idx_chat_sessions_status ON chat_sessions(status) 
    WHERE status = 'active';

-- GIN 索引：context_snapshot 查询
CREATE INDEX idx_chat_sessions_context ON chat_sessions 
    USING GIN(context_snapshot jsonb_path_ops);

-- 创建时间索引
CREATE INDEX idx_chat_sessions_created_at ON chat_sessions(created_at DESC);

-- 用户 + 状态索引（查询某用户的活跃会话）
CREATE INDEX idx_chat_sessions_user_status ON chat_sessions(user_id, status);

-- ============================================================
-- chat_messages 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX idx_chat_messages_mcp_server_id ON chat_messages(mcp_server_id);

-- 角色索引
CREATE INDEX idx_chat_messages_role ON chat_messages(role);

-- MCP 工具查询索引
CREATE INDEX idx_chat_messages_mcp_tool ON chat_messages(mcp_tool_name) 
    WHERE mcp_tool_name IS NOT NULL;

-- GIN 索引：tool_calls 查询
CREATE INDEX idx_chat_messages_tool_calls ON chat_messages 
    USING GIN(tool_calls jsonb_path_ops);

-- GIN 索引：tool_results 查询
CREATE INDEX idx_chat_messages_tool_results ON chat_messages 
    USING GIN(tool_results jsonb_path_ops);

-- 创建时间索引
CREATE INDEX idx_chat_messages_created_at ON chat_messages(created_at DESC);

-- 会话 + 时间索引（查询某会话的消息列表）
CREATE INDEX idx_chat_messages_session_time ON chat_messages(session_id, created_at DESC);
```

### 3.7 MCP 域索引

```sql
-- ============================================================
-- mcp_servers 表索引
-- ============================================================

-- 名称唯一索引（自动生成）
-- UNIQUE (name)

-- 外键索引
CREATE INDEX idx_mcp_servers_created_by ON mcp_servers(created_by);

-- 激活状态索引
CREATE INDEX idx_mcp_servers_active ON mcp_servers(is_active) 
    WHERE is_active = TRUE;

-- 健康状态索引
CREATE INDEX idx_mcp_servers_health ON mcp_servers(health_status);

-- GIN 索引：tools_catalog 查询
CREATE INDEX idx_mcp_servers_tools ON mcp_servers 
    USING GIN(tools_catalog jsonb_path_ops);

-- GIN 索引：auth_config 查询
CREATE INDEX idx_mcp_servers_auth ON mcp_servers 
    USING GIN(auth_config jsonb_path_ops);

-- 最后心跳时间索引（健康检查）
CREATE INDEX idx_mcp_servers_heartbeat ON mcp_servers(last_heartbeat_at);

-- ============================================================
-- mcp_tool_invocations 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_mcp_invocations_server_id ON mcp_tool_invocations(mcp_server_id);
CREATE INDEX idx_mcp_invocations_task_id ON mcp_tool_invocations(task_id);
CREATE INDEX idx_mcp_invocations_chat_msg_id ON mcp_tool_invocations(chat_message_id);
CREATE INDEX idx_mcp_invocations_user_id ON mcp_tool_invocations(user_id);

-- 状态索引
CREATE INDEX idx_mcp_invocations_status ON mcp_tool_invocations(status);

-- 工具名称索引
CREATE INDEX idx_mcp_invocations_tool ON mcp_tool_invocations(tool_name);

-- Server + 工具索引（查询某 Server 的某工具调用）
CREATE INDEX idx_mcp_invocations_server_tool ON mcp_tool_invocations(mcp_server_id, tool_name);

-- GIN 索引：request_payload 查询
CREATE INDEX idx_mcp_invocations_request ON mcp_tool_invocations 
    USING GIN(request_payload jsonb_path_ops);

-- 创建时间索引
CREATE INDEX idx_mcp_invocations_created_at ON mcp_tool_invocations(created_at DESC);

-- 复合索引：Server + 状态 + 时间（查询某 Server 的最近调用）
CREATE INDEX idx_mcp_invocations_server_status_time 
    ON mcp_tool_invocations(mcp_server_id, status, created_at DESC);
```


---

## 4. JSONB 字段详细说明

### 4.1 设计原则

1. **类型安全**：JSONB 字段在应用层通过 Pydantic v2 模型验证
2. **文档化**：每个 JSONB 字段都有明确的数据结构定义
3. **查询优化**：所有 JSONB 字段都建有 GIN 索引
4. **迁移友好**：JSONB 结构变更不需要数据库迁移

### 4.2 users.preferences — 用户偏好设置

**数据结构示例：**

```json
{
  "theme": "dark",
  "language": "zh-CN",
  "notifications": {
    "email_on_task_complete": true,
    "email_on_task_fail": true,
    "browser_notify": true
  },
  "default_workspace_id": 5,
  "page_size": 20,
  "default_flow_parameters": {
    "species": "Arabidopsis thaliana",
    "genome_version": "TAIR10"
  }
}
```

**Pydantic v2 模型（应用层验证）：**

```python
from pydantic import BaseModel, Field
from typing import Optional

class NotificationSettings(BaseModel):
    email_on_task_complete: bool = True
    email_on_task_fail: bool = True
    browser_notify: bool = True

class UserPreferences(BaseModel):
    theme: str = "light"  # "light" | "dark" | "auto"
    language: str = "zh-CN"
    notifications: NotificationSettings = NotificationSettings()
    default_workspace_id: Optional[int] = None
    page_size: int = Field(default=20, ge=5, le=100)
    default_flow_parameters: dict = {}
```

**GIN 索引查询示例：**

```sql
-- 查询使用深色主题的用户
SELECT id, username FROM users 
WHERE preferences @> '{"theme": "dark"}';

-- 查询开启了任务完成邮件通知的用户
SELECT id, username FROM users 
WHERE preferences @> '{"notifications": {"email_on_task_complete": true}}';
```

---

### 4.3 workspaces.config — 工作空间配置

**数据结构示例：**

```json
{
  "color": "#52c41a",
  "icon": "ExperimentOutlined",
  "default_flow_key": "rna-seq-star-deseq2",
  "auto_cleanup_days": 30,
  "storage_quota_gb": 100
}
```

**GIN 索引查询示例：**

```sql
-- 查询标记为特定颜色的工作空间
SELECT * FROM workspaces WHERE config @> '{"color": "#52c41a"}';
```

---

### 4.4 flow_categories.metadata — 分类元数据

**数据结构示例：**

```json
{
  "domain": "transcriptomics",
  "common_species": ["Arabidopsis thaliana", "Oryza sativa"],
  "typical_runtime_hours": 4,
  "required_resources": {
    "min_cores": 4,
    "min_memory_gb": 16
  }
}
```

---

### 4.5 flow_definitions.parsed_config — 解析后的流程配置

**数据结构示例：**

```json
{
  "params": {
    "genome": {
      "type": "select",
      "label": "参考基因组",
      "options": ["TAIR10", "Col-0_Ens",
"t2t"],
      "required": true,
      "default": "TAIR10"
    },
    "threads": {
      "type": "integer",
      "label": "线程数",
      "min": 1,
      "max": 64,
      "default": 8
    },
    "p_value_cutoff": {
      "type": "float",
      "label": "P值阈值",
      "min": 0.001,
      "max": 0.1,
      "default": 0.05,
      "step": 0.001
    },
    "skip_qc": {
      "type": "boolean",
      "label": "跳过质控",
      "default": false
    }
  },
  "steps": [
    {
      "name": "fastqc",
      "label": "FastQC 质控",
      "order": 1,
      "enabled_by_default": true,
      "dependencies": [],
      "output_files": ["*_fastqc.html", "*_fastqc.zip"]
    },
    {
      "name": "trimming",
      "label": "接头修剪",
      "order": 2,
      "enabled_by_default": true,
      "dependencies": ["fastqc"],
      "condition": "params.skip_qc == false"
    },
    {
      "name": "star_alignment",
      "label": "STAR 比对",
      "order": 3,
      "enabled_by_default": true,
      "dependencies": ["trimming"],
      "resources": {"cores": 16, "memory_gb": 64}
    },
    {
      "name": "deseq2_analysis",
      "label": "DESeq2 差异分析",
      "order": 4,
      "enabled_by_default": true,
      "dependencies": ["star_alignment"],
      "resources": {"cores": 4, "memory_gb": 16}
    }
  ],
  "conditions": [
    {
      "if": "params.skip_qc",
      "then": {"skip_steps": ["fastqc"]}
    }
  ],
  "outputs": {
    "reports": ["multiqc_report.html", "deseq2_results.xlsx"],
    "data_files": ["counts_matrix.csv", "normalized_counts.csv"],
    "plots": ["pca_plot.pdf", "volcano_plot.pdf", "heatmap.pdf"]
  }
}
```

**Pydantic v2 模型（部分）：**

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Union

class SelectParam(BaseModel):
    type: Literal["select"]
    label: str
    options: List[str]
    required: bool = False
    default: Optional[str] = None

class IntegerParam(BaseModel):
    type: Literal["integer"]
    label: str
    min: Optional[int] = None
    max: Optional[int] = None
    default: int = 0

class FloatParam(BaseModel):
    type: Literal["float"]
    label: str
    min: Optional[float] = None
    max: Optional[float] = None
    default: float = 0.0
    step: Optional[float] = None

class BooleanParam(BaseModel):
    type: Literal["boolean"]
    label: str
    default: bool = False

ParamDefinition = Union[SelectParam, IntegerParam, FloatParam, BooleanParam]

class FlowStep(BaseModel):
    name: str
    label: str
    order: int
    enabled_by_default: bool = True
    dependencies: List[str] = []
    condition: Optional[str] = None
    resources: Optional[dict] = None
    output_files: List[str] = []

class ParsedConfig(BaseModel):
    params: dict[str, ParamDefinition] = {}
    steps: List[FlowStep] = []
    conditions: List[dict] = []
    outputs: dict = {}
```

**GIN 索引查询示例：**

```sql
-- 查询包含特定参数的流程
SELECT id, flow_key, name FROM flow_definitions 
WHERE parsed_config @> '{"params": {"genome": {"type": "select"}}}';

-- 查询包含特定步骤的流程
SELECT id, flow_key, name FROM flow_definitions 
WHERE parsed_config @> '{"steps": [{"name": "deseq2_analysis"}]}';

-- 查询输出包含特定报告文件的流程
SELECT id, flow_key, name FROM flow_definitions 
WHERE parsed_config @> '{"outputs": {"reports": ["multiqc_report.html"]}}';

-- 使用 jsonb_path_query 提取所有流程的参数列表
SELECT flow_key, name,
    jsonb_object_keys(parsed_config->'params') AS param_name
FROM flow_definitions 
WHERE parsed_config ? 'params';
```

---

### 4.6 flow_definitions.sample_sheet_columns — 样本表必填列

**数据结构示例：**

```json
[
  {
    "name": "sample_id",
    "label": "样本ID",
    "type": "string",
    "required": true,
    "description": "唯一的样本标识符"
  },
  {
    "name": "group",
    "label": "分组",
    "type": "string",
    "required": true,
    "description": "实验分组，如 WT, KO, OE"
  },
  {
    "name": "replicate",
    "label": "生物学重复",
    "type": "integer",
    "required": true,
    "default": 1
  },
  {
    "name": "fq1",
    "label": "R1文件路径",
    "type": "file",
    "required": true,
    "pattern": "*.fq.gz;*.fastq.gz"
  },
  {
    "name": "fq2",
    "label": "R2文件路径",
    "type": "file",
    "required": false,
    "pattern": "*.fq.gz;*.fastq.gz",
    "description": "双端测序的R2文件，单端测序留空"
  },
  {
    "name": "batch",
    "label": "批次",
    "type": "string",
    "required": false,
    "description": "测序批次，用于批次效应校正"
  }
]
```

---

### 4.7 flow_definitions.execution_config — 执行配置

**数据结构示例：**

```json
{
  "engine": "snakemake",
  "snakefile": "workflows/rna-seq/Snakefile",
  "conda_env": "envs/rna-seq.yaml",
  "default_resources": {
    "cores": 8,
    "memory_gb": 32,
    "runtime_hours": 24
  },
  "cluster_config": {
    "partition": "normal",
    "qos": "batch",
    "account": "omics"
  },
  "singularity": {
    "enabled": true,
    "image": "docker://evolobiorna/omicshub-rna-seq:latest"
  },
  "environment_variables": {
    "OMP_NUM_THREADS": "8"
  }
}
```

---

### 4.8 projects.config — 项目配置

**数据结构示例：**

```json
{
  "species": {
    "scientific_name": "Arabidopsis thaliana",
    "common_name": "拟南芥",
    "taxid": 3702
  },
  "reference_genome": {
    "version": "TAIR10",
    "fasta_path": "/ref/ath/TAIR10.fa",
    "gtf_path": "/ref/ath/TAIR10.gtf",
    "annotation_source": "Araport11"
  },
  "sequencing": {
    "platform": "Illumina NovaSeq 6000",
    "read_length": 150,
    "layout": "paired-end",
    "strand_specificity": "reverse"
  },
  "default_parameters": {
    "threads": 16,
    "p_value_cutoff": 0.05,
    "log2fc_cutoff": 1.0
  },
  "contacts": [
    {"name": "张教授", "role": "PI", "email": "zhang@hzau.edu.cn"}
  ]
}
```

---

### 4.9 samples.metadata — 样本元数据

**数据结构示例：**

```json
{
  "platform": "Illumina NovaSeq 6000",
  "read_length": 150,
  "layout": "paired-end",
  "library_prep": "TruSeq Stranded mRNA",
  " sequencing_date": "2024-01-15",
  "sequencing_center": "BGI",
  "lane": "L001",
  "barcode": "ATCGATCG",
  "concentration_ng_ul": 12.5,
  "rin_score": 8.2,
  "organism": "Arabidopsis thaliana",
  "tissue": "leaf",
  "treatment": "drought_stress_7d",
  "biological_replicate": 1,
  "technical_replicate": 1
}
```

---

### 4.10 samples.sample_sheet_data — 样本表结构化数据

**数据结构示例：**

```json
{
  "sample_id": "WT_Rep1",
  "group": "WT",
  "replicate": 1,
  "fq1": "/data/proj1/raw/WT_Rep1_R1.fq.gz",
  "fq2": "/data/proj1/raw/WT_Rep1_R2.fq.gz",
  "batch": "Batch_20240115",
  "notes": "生长条件：22°C，16h光照"
}
```

---

### 4.11 samples.grouping — 样本分组信息

**数据结构示例：**

```json
{
  "condition": "wild_type",
  "contrast_group": "control",
  "batch": "batch_1",
  "batch_corrected": false,
  "group_color": "#1890ff",
  "paired_sample": null
}
```

---

### 4.12 samples.qc_results — 质量评估结果

**数据结构示例：**

```json
{
  "fastqc": {
    "total_reads": 28500000,
    "gc_content": 0.36,
    "q30_rate": 0.94,
    "adapter_contamination": false,
    "per_base_quality": "PASS",
    "per_sequence_quality": "PASS",
    "report_path": "/data/proj1/qc/WT_Rep1_fastqc.html"
  },
  "trimming": {
    "input_reads": 28500000,
    "surviving_reads": 27200000,
    "survival_rate": 0.954,
    "trimmed_bases": 43200000
  },
  "alignment": {
    "total_reads": 27200000,
    "mapped_reads": 25800000,
    "mapping_rate": 0.949,
    "unique_mapped": 24100000,
    "multi_mapped": 1700000,
    "unmapped": 1400000
  }
}
```

---

### 4.13 tasks.parameters — 用户提交的参数值

**数据结构示例：**

```json
{
  "genome": "TAIR10",
  "threads": 16,
  "p_value_cutoff": 0.05,
  "log2fc_cutoff": 1.0,
  "skip_qc": false,
  "contrast_groups": ["WT", "drought_7d"],
  "batch_correction": true,
  "gsea_analysis": true,
  "gsea_gene_sets": ["GO_BP", "KEGG", "Reactome"]
}
```

**GIN 索引查询示例：**

```sql
-- 查询使用了特定基因组的任务
SELECT t.task_id, t.name, t.status 
FROM tasks t
WHERE t.parameters @> '{"genome": "TAIR10"}';

-- 查询启用了 GSEA 分析的任务
SELECT t.task_id, t.name 
FROM tasks t
WHERE t.parameters @> '{"gsea_analysis": true}';

-- 查询参数中包含特定对比组的任务
SELECT t.task_id, t.name, t.parameters->'contrast_groups' AS groups
FROM tasks t
WHERE t.parameters->'contrast_groups' @> '["WT"]'
   OR t.parameters->'contrast_groups' @> '["drought_7d"]';
```

---

### 4.14 tasks.resources — 资源请求

**数据结构示例：**

```json
{
  "cores": 16,
  "memory_gb": 64,
  "runtime_hours": 24,
  "gpu_count": 0,
  "partition": "normal",
  "queue": "batch",
  "scratch_gb": 200
}
```

---

### 4.15 tasks.results_summary — 结果摘要

**数据结构示例：**

```json
{
  "status": "success",
  "completed_steps": 4,
  "total_steps": 4,
  "output_files": [
    {"path": "results/multiqc_report.html", "size": 2458000, "category": "report"},
    {"path": "results/counts_matrix.csv", "size": 15600000, "category": "data"},
    {"path": "results/deseq2_results.xlsx", "size": 3200000, "category": "data"},
    {"path": "results/pca_plot.pdf", "size": 450000, "category": "plot"},
    {"path": "results/volcano_plot.pdf", "size": 380000, "category": "plot"},
    {"path": "results/heatmap.pdf", "size": 520000, "category": "plot"}
  ],
  "statistics": {
    "total_genes": 33602,
    "differentially_expressed": 1847,
    "up_regulated": 923,
    "down_regulated": 924,
    "significant_go_terms": 156,
    "significant_kegg_pathways": 42
  },
  "execution_summary": {
    "wall_time_hours": 3.2,
    "cpu_hours": 51.2,
    "peak_memory_gb": 45.3,
    "snakemake_version": "7.32.4"
  }
}
```

---

### 4.16 task_events.details — 事件详情

**数据结构示例：**

```json
{
  "step_name": "star_alignment",
  "step_index": 3,
  "exit_code": 0,
  "signal": null,
  "resource_usage": {
    "cpu_percent": 98.5,
    "memory_gb": 42.3,
    "runtime_minutes": 45
  }
}
```

---

### 4.17 chat_sessions.context_snapshot — 上下文快照

**数据结构示例：**

```json
{
  "current_project_id": 12,
  "current_project_name": "拟南芥干旱胁迫转录组",
  "current_flow_id": 5,
  "current_flow_name": "RNA-seq STAR-DESeq2",
  "current_task_id": 89,
  "current_task_status": "completed",
  "selected_samples": [101, 102, 103, 104],
  "active_tab": "results",
  "browser_info": {
    "page": "/projects/12/tasks/89/results",
    "timestamp": "2024-01-20T14:30:00+08:00"
  }
}
```

---

### 4.18 chat_messages.tool_calls — AI 工具调用

**数据结构示例：**

```json
[
  {
    "id": "call_abc123",
    "type": "function",
    "function": {
      "name": "query_task_results",
      "arguments": {
        "task_id": "89",
        "result_type": "differential_expression"
      }
    }
  }
]
```

---

### 4.19 chat_messages.tool_results — 工具执行结果

**数据结构示例：**

```json
[
  {
    "tool_call_id": "call_abc123",
    "role": "tool",
    "content": {
      "total_de_genes": 1847,
      "top_genes": [
        {"gene_id": "AT1G01010", "log2FoldChange": 2.34, "padj": 0.001},
        {"gene_id": "AT1G01020", "log2FoldChange": -1.87, "padj": 0.003}
      ]
    }
  }
]
```

---

### 4.20 chat_messages.token_count — Token 计数

**数据结构示例：**

```json
{
  "prompt_tokens": 2456,
  "completion_tokens": 892,
  "total_tokens": 3348,
  "prompt_tokens_details": {
    "cached_tokens": 1800,
    "audio_tokens": 0
  }
}
```

---

### 4.21 mcp_servers.tools_catalog — 工具目录

**数据结构示例：**

```json
[
  {
    "name": "genome_browser_navigate",
    "description": "在基因组浏览器中导航到指定位置",
    "parameters": {
      "type": "object",
      "properties": {
        "chromosome": {"type": "string", "description": "染色体名称"},
        "start": {"type": "integer", "description": "起始位置"},
        "end": {"type": "integer", "description": "终止位置"}
      },
      "required": ["chromosome", "start", "end"]
    }
  },
  {
    "name": "run_enrichment_analysis",
    "description": "对基因列表进行功能富集分析",
    "parameters": {
      "type": "object",
      "properties": {
        "gene_list": {"type": "array", "items": {"type": "string"}},
        "ontology": {"type": "string", "enum": ["GO_BP", "GO_MF", "GO_CC", "KEGG"]},
        "p_value_cutoff": {"type": "number", "default": 0.05}
      },
      "required": ["gene_list", "ontology"]
    }
  }
]
```

---

### 4.22 mcp_servers.auth_config — 认证配置

**数据结构示例：**

```json
{
  "type": "bearer",
  "token": "sk-mcp-xxxxxxxxx",
  "header_name": "Authorization",
  "refresh_interval_hours": 24
}
```

```json
{
  "type": "api_key",
  "key_name": "X-API-Key",
  "key_value": "ak-xxxxxxxxx",
  "location": "header"
}
```

---

### 4.23 mcp_tool_invocations.request_payload / response_payload

**request_payload 示例：**

```json
{
  "chromosome": "Chr1",
  "start": 1234567,
  "end": 1235567,
  "tracks": ["genes", "expression", "variants"]
}
```

**response_payload 示例：**

```json
{
  "navigation_url": "https://jbrowse.hzau.edu.cn/?loc=Chr1:1234567..1235567",
  "visible_genes": [
    {"name": "AT1G04500", "start": 1234600, "end": 1235200, "strand": "+"},
    {"name": "AT1G04510", "start": 1235300, "end": 1235500, "strand": "-"}
  ],
  "expression_data": {
    "AT1G04500": {"WT": 45.2, "drought_7d": 128.7},
    "AT1G04510": {"WT": 12.1, "drought_7d": 8.3}
  }
}
```

---

### 4.24 file_records.metadata — 文件元数据

**数据结构示例：**

```json
{
  "compression": "gzip",
  "index_file": "/data/proj1/results/alignment.sorted.bam.bai",
  "column_names": ["gene_id", "baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj"],
  "row_count": 33602,
  "delimiter": "\t",
  "encoding": "UTF-8"
}
```


---

## 5. 数据库 ER 关系描述

### 5.1 实体关系总览

```
users (1) ────────< (*) workspaces          一个用户有多个工作空间
users (1) ────────< (*) projects            一个用户有多个项目
users (1) ────────< (*) tasks               一个用户提交多个任务
users (1) ────────< (*) chat_sessions       一个用户有多个对话会话
users (1) ────────< (*) file_records        一个用户有多个文件记录
users (1) ────────< (*) flow_definitions    一个用户可创建多个流程（created_by）
users (1) ────────< (*) mcp_servers         一个用户可注册多个 MCP Server

workspaces (1) ───< (*) workspaces          自引用：父工作空间 → 子工作空间
workspaces (1) ───< (*) projects            一个工作空间包含多个项目

flow_categories (1) ─< (*) flow_categories  自引用：父分类 → 子分类
flow_categories (1) ─< (*) flow_definitions 一个分类下有多个流程定义

flow_definitions (1) ─< (*) tasks           一个流程定义被多个任务使用

projects (1) ─────< (*) samples             一个项目有多个样本
projects (1) ─────< (*) tasks               一个项目有多个任务
projects (1) ─────< (*) file_records        一个项目有多个文件

samples (1) ──────< (*) file_records (间接) 样本文件通过 file_path 关联

tasks (1) ────────< (*) task_logs           一个任务有多条日志
tasks (1) ────────< (*) task_events         一个任务有多个事件
tasks (1) ────────< (*) file_records        一个任务产生多个文件

chat_sessions (1) ─< (*) chat_messages      一个会话有多条消息

mcp_servers (1) ──< (*) chat_messages       一个 MCP Server 被多条消息引用
mcp_servers (1) ──< (*) mcp_tool_invocations 一个 MCP Server 有多次工具调用

chat_messages (1) ─< (*) mcp_tool_invocations 一条消息可能触发多次工具调用
tasks (1) ────────< (*) mcp_tool_invocations  一个任务可能由 MCP 工具触发
```

### 5.2 关系详情与级联策略

#### 5.2.1 用户域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `users` | `workspaces` | 一对多 | `ON DELETE CASCADE` | 删除用户时级联删除其工作空间 |
| `users` | `projects` | 一对多 | `ON DELETE CASCADE` | 删除用户时级联删除其项目 |
| `users` | `tasks` | 一对多 | `ON DELETE RESTRICT` | 有任务的用户禁止删除 |
| `users` | `chat_sessions` | 一对多 | `ON DELETE CASCADE` | 删除用户时级联删除会话 |
| `users` | `file_records` | 一对多 | `ON DELETE CASCADE` | 删除用户时级联删除文件记录 |
| `users` | `flow_definitions` | 一对多 | `ON DELETE RESTRICT` | 有流程的用户禁止删除 |
| `users` | `mcp_servers` | 一对多 | `ON DELETE RESTRICT` | 有MCP Server的用户禁止删除 |

**workspaces 自引用关系：**

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `workspaces` | `workspaces` (parent_id) | 一对多 | `ON DELETE CASCADE` | 删除父工作空间级联删除子空间 |

#### 5.2.2 流程域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `flow_categories` | `flow_categories` (parent_id) | 一对多 | `ON DELETE SET NULL` | 删除父分类，子分类变为顶级 |
| `flow_categories` | `flow_definitions` | 一对多 | `ON DELETE SET NULL` | 删除分类，流程变为未分类 |
| `flow_definitions` | `tasks` | 一对多 | `ON DELETE RESTRICT` | 有任务的流程定义禁止删除 |

#### 5.2.3 项目与文件域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `workspaces` | `projects` | 一对多 | `ON DELETE SET NULL` | 删除工作空间，项目变为未分类 |
| `projects` | `samples` | 一对多 | `ON DELETE CASCADE` | 删除项目级联删除样本 |
| `projects` | `tasks` | 一对多 | `ON DELETE CASCADE` | 删除项目级联删除任务 |
| `projects` | `file_records` | 一对多 | `ON DELETE CASCADE` | 删除项目级联删除文件记录 |

#### 5.2.4 任务域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `tasks` | `task_logs` | 一对多 | `ON DELETE CASCADE` | 删除任务级联删除日志 |
| `tasks` | `task_events` | 一对多 | `ON DELETE CASCADE` | 删除任务级联删除事件 |
| `tasks` | `file_records` | 一对多 | `ON DELETE SET NULL` | 删除任务，文件记录保留但解绑 |

#### 5.2.5 AI 对话域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `chat_sessions` | `chat_messages` | 一对多 | `ON DELETE CASCADE` | 删除会话级联删除消息 |

#### 5.2.6 MCP 域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `mcp_servers` | `chat_messages` | 一对多 | `ON DELETE SET NULL` | 删除 Server，消息保留但解绑 |
| `mcp_servers` | `mcp_tool_invocations` | 一对多 | `ON DELETE CASCADE` | 删除 Server 级联删除调用记录 |
| `chat_messages` | `mcp_tool_invocations` | 一对多 | `ON DELETE SET NULL` | 删除消息，调用记录保留 |
| `tasks` | `mcp_tool_invocations` | 一对多 | `ON DELETE SET NULL` | 删除任务，调用记录保留 |
| `users` | `mcp_tool_invocations` | 一对多 | `ON DELETE SET NULL` | 删除用户，调用记录保留 |

### 5.3 ER 关系图（文字描述）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           OmicsHub ER 关系图                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────┐       ┌──────────────┐       ┌─────────────────────┐     │
│  │  users   │◄──────┤  workspaces  │◄──────┤     projects        │     │
│  │          │  1:*  │  (self-ref)  │  1:*  │                     │     │
│  └────┬─────┘       └──────────────┘       └──────────┬──────────┘     │
│       │  ▲                                            │                  │
│       │  │ 1:*                                        │ 1:*              │
│       │  │                                            ▼                  │
│       │  │                                  ┌─────────────────────┐      │
│       │  │                                  │      samples        │      │
│       │  │                                  │                     │      │
│       │  │                                  └─────────────────────┘      │
│       │  │                                                               │
│       │  │                                1:*                            │
│       │  └────────────────────────────────┐                             │
│       │                                   ▼                             │
│       │                          ┌─────────────────────┐                │
│       │                          │       tasks         │◄──────┐        │
│       │                          │                     │       │        │
│       │                          └──────────┬──────────┘       │        │
│       │                                     │                  │        │
│       │                          1:*        │        1:*       │        │
│       │                          ▼          │         ▼        │        │
│       │               ┌──────────────────┐  │  ┌──────────────┐│        │
│       │               │    task_logs     │  │  │ task_events  ││        │
│       │               │                  │  │  │              ││        │
│       │               └──────────────────┘  │  └──────────────┘│        │
│       │                                     │                  │        │
│       │                    ┌────────────────┘                  │        │
│       │                    │                                   │        │
│       │                    ▼ 1:*                               │        │
│       │           ┌─────────────────────┐                      │        │
│       │           │   file_records      │                      │        │
│       │           │                     │                      │        │
│       │           └─────────────────────┘                      │        │
│       │                                                        │        │
│       │       ┌──────────────────────┐                         │        │
│       │       │  flow_categories     │◄─────────┐              │        │
│       │       │  (self-ref)          │          │ 1:*          │        │
│       │       └──────────────────────┘          │              │        │
│       │                                         ▼              │        │
│       │                              ┌─────────────────────┐   │        │
│       │                              │  flow_definitions   │───┘        │
│       │                              │                     │            │
│       │                              └─────────────────────┘            │
│       │                                                                 │
│       │  ┌──────────────────────┐      ┌──────────────────────┐         │
│       └──┤   chat_sessions    │◄─────┤   chat_messages      │         │
│          │                    │ 1:*  │                      │         │
│          └────────────────────┘      └──────────┬───────────┘         │
│                                                 │                       │
│                                                 ▼                       │
│          ┌──────────────────────┐      ┌──────────────────────┐         │
│          │    mcp_servers       │◄─────┤ mcp_tool_invocations │         │
│          │                    │ 1:*  │                      │         │
│          └────────────────────┘      └──────────────────────┘         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.4 级联删除决策矩阵

| 删除操作 | 级联影响 | 设计理由 |
|----------|----------|----------|
| 删除用户 | 工作空间、项目、会话、文件记录 级联删除；任务、流程、MCP Server 禁止删除 | 保留历史记录完整性 |
| 删除工作空间 | 子工作空间级联删除；项目变为未分类 | 保护项目数据 |
| 删除项目 | 样本、任务、文件记录 级联删除 | 项目为顶层容器 |
| 删除任务 | 日志、事件 级联删除；文件记录解绑 | 保留文件但解绑来源 |
| 删除流程定义 | 有任务时禁止删除 | 保护历史任务记录 |
| 删除会话 | 消息级联删除 | 消息为会话的子实体 |
| 删除 MCP Server | 调用记录级联删除；消息解绑 | 保留消息但解绑工具 |
| 删除样本 | 无直接级联（file_records 通过 path 软关联） | 样本删除不影响已产生的文件 |


---

## 6. 数据隔离策略

### 6.1 策略选择：应用层过滤 + 行级安全（RLS）双重保障

考虑到 OmicsHub 的使用场景（组内平台，<20 并发用户，单人生信维护），我们采用以下策略：

| 层级 | 策略 | 说明 |
|------|------|------|
| **应用层** | 主要隔离手段 | FastAPI 在每个请求中注入当前用户 ID，所有查询自动附加 WHERE user_id = current_user_id |
| **数据库层（RLS）** | 安全兜底 | PostgreSQL RLS 策略作为第二道防线，防止应用层漏洞导致的数据泄露 |
| **数据库层（外键约束）** | 完整性保障 | 通过外键确保数据关联关系的有效性 |

### 6.2 为什么不采用完整的多租户方案

对于组内小团队（<20人），以下多租户方案不适用：

| 方案 | 适用场景 | 不适用理由 |
|------|----------|------------|
| 单数据库多 Schema | 中等规模 SaaS | 维护复杂，权限管理开销大 |
| 多数据库 | 大规模多租户 | 资源浪费，备份复杂 |
| 共享表 + 租户ID | 通用 SaaS | 索引膨胀，查询需带租户过滤 |

我们的方案：**单数据库 + 单 Schema + user_id 字段隔离 + RLS 兜底**

### 6.3 行级安全（RLS）策略实现

```sql
-- ============================================================
-- 启用行级安全（RLS）
-- ============================================================
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE samples ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE file_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE flow_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcp_servers ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcp_tool_invocations ENABLE ROW LEVEL SECURITY;

-- 创建当前用户 ID 配置函数
CREATE OR REPLACE FUNCTION set_current_user_id(user_id BIGINT)
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_user_id', user_id::TEXT, FALSE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION get_current_user_id()
RETURNS BIGINT AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_user_id', TRUE), '')::BIGINT;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION is_current_user_admin()
RETURNS BOOLEAN AS $$
DECLARE
    user_role VARCHAR(20);
    current_uid BIGINT;
BEGIN
    current_uid := get_current_user_id();
    IF current_uid IS NULL THEN
        RETURN FALSE;
    END IF;
    SELECT role INTO user_role FROM users WHERE id = current_uid;
    RETURN user_role = 'admin';
END;
$$ LANGUAGE plpgsql STABLE;

-- users 表 RLS 策略
CREATE POLICY users_select_self ON users
    FOR SELECT USING (id = get_current_user_id() OR is_current_user_admin());

CREATE POLICY users_update_self ON users
    FOR UPDATE USING (id = get_current_user_id())
    WITH CHECK (id = get_current_user_id());

-- workspaces 表 RLS 策略
CREATE POLICY workspaces_isolation ON workspaces
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- projects 表 RLS 策略
CREATE POLICY projects_isolation ON projects
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- samples 表 RLS 策略
CREATE POLICY samples_isolation ON samples
    FOR ALL USING (
        project_id IN (
            SELECT id FROM projects 
            WHERE user_id = get_current_user_id() OR is_current_user_admin()
        )
    );

-- tasks 表 RLS 策略
CREATE POLICY tasks_isolation ON tasks
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- task_logs 表 RLS 策略
CREATE POLICY task_logs_isolation ON task_logs
    FOR ALL USING (
        task_id IN (
            SELECT id FROM tasks 
            WHERE user_id = get_current_user_id() OR is_current_user_admin()
        )
    );

-- task_events 表 RLS 策略
CREATE POLICY task_events_isolation ON task_events
    FOR ALL USING (
        task_id IN (
            SELECT id FROM tasks 
            WHERE user_id = get_current_user_id() OR is_current_user_admin()
        )
    );

-- file_records 表 RLS 策略
CREATE POLICY file_records_isolation ON file_records
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- chat_sessions 表 RLS 策略
CREATE POLICY chat_sessions_isolation ON chat_sessions
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- chat_messages 表 RLS 策略
CREATE POLICY chat_messages_isolation ON chat_messages
    FOR ALL USING (
        session_id IN (
            SELECT id FROM chat_sessions 
            WHERE user_id = get_current_user_id() OR is_current_user_admin()
        )
    );

-- flow_definitions 表 RLS 策略
CREATE POLICY flow_definitions_isolation ON flow_definitions
    FOR ALL USING (
        is_public = TRUE 
        OR created_by = get_current_user_id() 
        OR is_current_user_admin()
    );

-- mcp_servers 表 RLS 策略
CREATE POLICY mcp_servers_isolation ON mcp_servers
    FOR ALL USING (
        is_public = TRUE 
        OR created_by = get_current_user_id() 
        OR is_current_user_admin()
    );

-- mcp_tool_invocations 表 RLS 策略
CREATE POLICY mcp_invocations_isolation ON mcp_tool_invocations
    FOR ALL USING (
        user_id = get_current_user_id() 
        OR is_current_user_admin()
        OR mcp_server_id IN (
            SELECT id FROM mcp_servers 
            WHERE is_public = TRUE OR created_by = get_current_user_id()
        )
    );
```

### 6.4 应用层隔离实现

在 FastAPI 中，通过依赖注入自动附加用户过滤条件：

```python
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

async def get_current_user(request, db):
    token = request.cookies.get("session_token")
    user = db.execute(
        text("SELECT * FROM users WHERE session_token = :token"),
        {"token": token}
    ).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

async def set_db_user_context(db, user_id):
    db.execute(text("SELECT set_current_user_id(:uid)"), {"uid": user_id})

class UserScopedService:
    def __init__(self, db, current_user):
        self.db = db
        self.current_user = current_user
        set_db_user_context(db, current_user.id)

    def query_projects(self, status=None):
        query = "SELECT * FROM projects"
        params = {}
        if status:
            query += " WHERE status = :status"
            params["status"] = status
        return self.db.execute(text(query), params).fetchall()

    def query_tasks(self, project_id=None, status=None):
        conditions = []
        params = {}
        if project_id:
            conditions.append("project_id = :pid")
            params["pid"] = project_id
        if status:
            conditions.append("status = :status")
            params["status"] = status
        query = "SELECT * FROM tasks"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        return self.db.execute(text(query), params).fetchall()
```

### 6.5 文件系统隔离

```
/data/omicshub/
├── users/
│   ├── {user_id_1}/
│   │   ├── projects/
│   │   │   ├── {project_uuid_1}/
│   │   │   │   ├── raw/
│   │   │   │   ├── processed/
│   │   │   │   ├── results/
│   │   │   │   ├── logs/
│   │   │   │   └── temp/
│   │   │   └── {project_uuid_2}/
│   │   └── uploads/
│   └── {user_id_2}/
├── shared/
│   ├── reference_genomes/
│   ├── conda_envs/
│   └── flow_templates/
└── system/
    ├── logs/
    └── backups/
```

| 存储位置 | 归属 | 说明 |
|----------|------|------|
| /data/omicshub/users/{user_id}/ | 用户私有 | 用户只能访问自己的目录 |
| /data/omicshub/shared/reference_genomes/ | 共享只读 | 管理员维护，所有用户可读 |
| /data/omicshub/shared/conda_envs/ | 共享只读 | 管理员维护的 Conda 环境 |
| /data/omicshub/system/ | 系统 | 仅系统进程可访问 |

### 6.6 管理员权限

```sql
-- 管理员专属视图
CREATE VIEW admin_all_tasks AS
SELECT 
    t.*,
    u.username AS owner_username,
    u.email AS owner_email,
    p.name AS project_name
FROM tasks t
JOIN users u ON t.user_id = u.id
JOIN projects p ON t.project_id = p.id
WHERE is_current_user_admin();

-- 管理员仪表盘统计
CREATE VIEW admin_dashboard_stats AS
SELECT 
    (SELECT COUNT(*) FROM users) AS total_users,
    (SELECT COUNT(*) FROM users WHERE is_active = TRUE) AS active_users,
    (SELECT COUNT(*) FROM projects) AS total_projects,
    (SELECT COUNT(*) FROM tasks) AS total_tasks,
    (SELECT COUNT(*) FROM tasks WHERE status = 'running') AS running_tasks,
    (SELECT COUNT(*) FROM tasks WHERE status = 'failed') AS failed_tasks,
    (SELECT COUNT(*) FROM tasks WHERE status = 'completed') AS completed_tasks,
    (SELECT COALESCE(SUM(file_size), 0) FROM file_records) AS total_storage_bytes
WHERE is_current_user_admin();
```

### 6.7 安全最佳实践

1. 数据库连接: 应用使用非超级用户连接数据库，仅授予必要的表权限
2. 参数化查询: 所有用户输入通过参数化查询传递，防止 SQL 注入
3. 审计日志: 所有数据修改操作记录到 task_events 和审计日志表
4. 敏感数据: users.hashed_password 和 mcp_servers.auth_config 需要额外保护
5. 定期备份: 使用 pg_dump 每日备份，保留 30 天

```sql
-- 创建应用数据库用户（最小权限原则）
CREATE ROLE omicshub_app WITH LOGIN PASSWORD 'strong_password';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO omicshub_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO omicshub_app;
REVOKE DELETE ON users, flow_definitions, mcp_servers FROM omicshub_app;
```

---

## 7. 完整 SQL 执行顺序

```sql
-- ============================================================
-- Step 1: 1_extensions.sql
-- 扩展和基础设置
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
SET timezone = 'Asia/Shanghai';

-- ============================================================
-- Step 2: 2_functions.sql
-- 通用函数和触发器
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION set_current_user_id(user_id BIGINT)
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_user_id', user_id::TEXT, FALSE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION get_current_user_id()
RETURNS BIGINT AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_user_id', TRUE), '')::BIGINT;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION is_current_user_admin()
RETURNS BOOLEAN AS $$
DECLARE
    user_role VARCHAR(20);
    current_uid BIGINT;
BEGIN
    current_uid := get_current_user_id();
    IF current_uid IS NULL THEN
        RETURN FALSE;
    END IF;
    SELECT role INTO user_role FROM users WHERE id = current_uid;
    RETURN user_role = 'admin';
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION check_workspace_cycle()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.parent_id IS NOT NULL THEN
        IF NEW.path LIKE '%/' || NEW.parent_id || '/%' THEN
            RAISE EXCEPTION 'Workspace cycle detected';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION handle_large_log()
RETURNS TRIGGER AS $$
BEGIN
    IF LENGTH(COALESCE(NEW.content, '')) > 1048576 THEN
        NEW.content_size = LENGTH(NEW.content);
        NEW.content = LEFT(NEW.content, 10000) 
            || E'
... [Log truncated, full content saved to file]';
    ELSE
        NEW.content_size = LENGTH(COALESCE(NEW.content, ''));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_chat_session_stats()
RETURNS TRIGGER AS $$
DECLARE
    total_tokens_sum INTEGER;
BEGIN
    UPDATE chat_sessions
    SET message_count = message_count + 1
    WHERE id = NEW.session_id;

    SELECT COALESCE(SUM(
        (COALESCE(token_count->>'total_tokens', '0'))::INTEGER
    ), 0)
    INTO total_tokens_sum
    FROM chat_messages
    WHERE session_id = NEW.session_id;

    UPDATE chat_sessions
    SET total_tokens = total_tokens_sum
    WHERE id = NEW.session_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Step 3: 3_tables.sql
-- 建表语句（按依赖顺序）
-- ============================================================
-- 执行顺序:
-- 1. users (no dependencies)
-- 2. flow_categories (no deps, self-ref at INSERT)
-- 3. mcp_servers (depends on users)
-- 4. workspaces (depends on users, self-ref)
-- 5. projects (depends on users, workspaces)
-- 6. flow_definitions (depends on flow_categories, users)
-- 7. samples (depends on projects)
-- 8. tasks (depends on users, projects, flow_definitions)
-- 9. task_logs (depends on tasks)
-- 10. task_events (depends on tasks)
-- 11. file_records (depends on users, projects, tasks optional)
-- 12. chat_sessions (depends on users)
-- 13. chat_messages (depends on chat_sessions, mcp_servers optional)
-- 14. mcp_tool_invocations (depends on mcp_servers, tasks opt,
--                           chat_messages opt, users opt)

-- ============================================================
-- Step 4: 4_indexes.sql
-- 创建索引（所有表创建完成后）
-- ============================================================
-- All index statements (see Section 3)

-- ============================================================
-- Step 5: 5_triggers.sql
-- 创建触发器（所有表创建完成后）
-- ============================================================
-- All CREATE TRIGGER statements

-- ============================================================
-- Step 6: 6_rls_policies.sql
-- 启用 RLS 并创建策略
-- ============================================================
-- All RLS policy statements (see Section 6.3)
```

### 快速初始化脚本

```bash
#!/bin/bash
# init_db.sh - Database initialization script
DB_NAME="omicshub"
DB_USER="omicshub_admin"

psql -U $DB_USER -d $DB_NAME -f 1_extensions.sql
psql -U $DB_USER -d $DB_NAME -f 2_functions.sql
psql -U $DB_USER -d $DB_NAME -f 3_tables.sql
psql -U $DB_USER -d $DB_NAME -f 4_indexes.sql
psql -U $DB_USER -d $DB_NAME -f 5_triggers.sql
psql -U $DB_USER -d $DB_NAME -f 6_rls_policies.sql

echo "OmicsHub database initialized successfully!"
```

---

## 附录 A: 表统计汇总

| 表名 | 核心字段数 | JSONB 字段数 | 外键数 | 索引数 | 说明 |
|------|-----------|-------------|--------|--------|------|
| `users` | 10 | 1 | 0 | 5 | 用户管理 |
| `workspaces` | 11 | 1 | 2 | 5 | 多级工作空间 |
| `flow_categories` | 11 | 1 | 1 | 3 | 流程分类 |
| `flow_definitions` | 16 | 3 | 2 | 9 | 流程定义（核心） |
| `projects` | 12 | 2 | 2 | 7 | 项目管理 |
| `samples` | 14 | 4 | 1 | 7 | 样本管理 |
| `file_records` | 14 | 1 | 3 | 7 | 文件管理 |
| `tasks` | 24 | 3 | 3 | 12 | 任务管理（核心） |
| `task_logs` | 10 | 0 | 1 | 5 | 任务日志 |
| `task_events` | 8 | 1 | 1 | 4 | 任务事件 |
| `chat_sessions` | 12 | 3 | 1 | 5 | 对话会话 |
| `chat_messages` | 11 | 5 | 2 | 6 | 对话消息 |
| `mcp_servers` | 14 | 4 | 1 | 6 | MCP Servers |
| `mcp_tool_invocations` | 12 | 3 | 4 | 7 | MCP 工具调用 |
| **合计** | **159** | **32** | **24** | **89** | |

## 附录 B: 字段类型统计

| 字段类型 | 数量 | 占比 |
|----------|------|------|
| BIGINT | 24 | 15.1% |
| INTEGER | 8 | 5.0% |
| VARCHAR | 35 | 22.0% |
| TEXT | 6 | 3.8% |
| BOOLEAN | 6 | 3.8% |
| JSONB | 32 | 20.1% |
| TIMESTAMPTZ | 12 | 7.5% |
| UUID | 2 | 1.3% |
| TEXT[] (数组) | 1 | 0.6% |
| 约束/其他 | 33 | 20.8% |

## 附录 C: Pydantic v2 集成建议

```python
from pydantic import BaseModel
from sqlalchemy import Column, BigInteger, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Task(Base):
    __tablename__ = "tasks"

    id = Column(BigInteger, primary_key=True)
    parameters = Column(JSON)
    resources = Column(JSON)
    results_summary = Column(JSON)

    class ParameterModel(BaseModel):
        genome: str
        threads: int = 8
        p_value_cutoff: float = 0.05

    class ResourceModel(BaseModel):
        cores: int = 4
        memory_gb: int = 16

    def get_parameters(self):
        return self.ParameterModel(**(self.parameters or {}))

    def set_parameters(self, params):
        self.parameters = params.model_dump()
```

---

*文档结束 - OmicsHub 数据库 Schema 设计 v1.0*


---

# 6.3 OmicsHub 完整 API 接口设计（REST + WebSocket）

> **文档版本**: v1.0  
> **项目**: OmicsHub — 私有化多组学分析平台  
> **目标读者**: 全栈开发工程师、前端开发工程师  
> **技术约束**: FastAPI + Pydantic v2 + Python 3.10+ + WebSocket  

---

## 目录

- [1. 全局设计约定](#1-全局设计约定)
- [2. 枚举类型定义](#2-枚举类型定义)
- [3. REST API 路由设计](#3-rest-api-路由设计)
- [4. Pydantic v2 DTO 模型定义](#4-pydantic-v2-dto-模型定义)
- [5. WebSocket 事件协议设计](#5-websocket-事件协议设计)
- [6. Snakemake 进度解析说明](#6-snakemake-进度解析说明)

---

## 1. 全局设计约定

### 1.1 统一响应包装器 `ResponseModel[T]`

所有 REST API 响应统一包装为以下结构，确保前端处理逻辑的一致性：

```python
from typing import TypeVar, Generic, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict

T = TypeVar("T")


class ResponseModel(BaseModel, Generic[T]):
    """统一响应包装器，所有 API 响应均以此结构返回"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": 200,
                "message": "success",
                "data": None,
                "timestamp": "2025-01-01T12:00:00Z"
            }
        }
    )

    code: int = Field(default=200, description="业务状态码：200成功，4xx客户端错误，5xx服务端错误")
    message: str = Field(default="success", description="人类可读的状态说明")
    data: Optional[T] = Field(default=None, description="业务数据载荷")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        description="UTC 时间戳（ISO 8601 格式）"
    )


# ============ 快捷构造函数 ============

def success(data: T, message: str = "success") -> ResponseModel[T]:
    """构造成功响应"""
    return ResponseModel(code=200, message=message, data=data)


def created(data: T, message: str = "created") -> ResponseModel[T]:
    """构造创建成功响应（HTTP 201）"""
    return ResponseModel(code=201, message=message, data=data)


def error(message: str, code: int = 400) -> ResponseModel[None]:
    """构造错误响应"""
    return ResponseModel(code=code, message=message, data=None)


def paginated(
    items: list[T],
    total: int,
    page: int,
    page_size: int,
    message: str = "success"
) -> ResponseModel["PageModel[T]"]:
    """构造分页响应"""
    pages = (total + page_size - 1) // page_size
    page_model = PageModel(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages
    )
    return ResponseModel(code=200, message=message, data=page_model)
```

**响应示例**：

```json
// 成功响应（单对象）
{
  "code": 200,
  "message": "success",
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "zhangsan",
    "role": "user"
  },
  "timestamp": "2025-01-01T12:00:00Z"
}

// 成功响应（列表）
{
  "code": 200,
  "message": "success",
  "data": [
    {"id": "xxx", "name": "RNA-Seq分析"},
    {"id": "yyy", "name": "差异表达分析"}
  ],
  "timestamp": "2025-01-01T12:00:00Z"
}

// 错误响应
{
  "code": 422,
  "message": "参数校验失败：field 'email' is not a valid email address",
  "data": null,
  "timestamp": "2025-01-01T12:00:00Z"
}
```

---

### 1.2 统一分页模型 `PageModel[T]`

```python
from typing import TypeVar, Generic, List
from pydantic import BaseModel, Field, ConfigDict

T = TypeVar("T")


class PageModel(BaseModel, Generic[T]):
    """统一分页模型，所有列表查询接口的 data 字段使用此结构"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [],
                "total": 100,
                "page": 1,
                "page_size": 20,
                "pages": 5
            }
        }
    )

    items: List[T] = Field(default_factory=list, description="当前页数据列表")
    total: int = Field(ge=0, description="总记录数")
    page: int = Field(ge=1, description="当前页码（从1开始）")
    page_size: int = Field(ge=1, le=200, description="每页条数（上限200）")
    pages: int = Field(ge=0, description="总页数")
```

**分页请求约定**：

所有支持分页的列表接口，通过 **Query 参数** 接收分页信息：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `page` | int | 否 | 1 | 页码，从1开始 |
| `page_size` | int | 否 | 20 | 每页条数，最大200 |
| `sort_by` | str | 否 | `created_at` | 排序字段 |
| `sort_order` | str | 否 | `desc` | 排序方向：`asc` / `desc` |

---

### 1.3 全局异常处理

```python
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging

logger = logging.getLogger(__name__)


class OmicsHubException(Exception):
    """业务异常基类"""
    def __init__(self, message: str, code: int = 400, details: dict | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


class NotFoundException(OmicsHubException):
    """资源不存在异常"""
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            message=f"{resource} not found: {identifier}",
            code=404
        )


class PermissionDeniedException(OmicsHubException):
    """权限不足异常"""
    def __init__(self, message: str = "Permission denied"):
        super().__init__(message=message, code=403)


class ConflictException(OmicsHubException):
    """资源冲突异常（如重复注册）"""
    def __init__(self, message: str):
        super().__init__(message=message, code=409)


# ============ FastAPI 全局异常处理器 ============

async def omicshub_exception_handler(request: Request, exc: OmicsHubException) -> JSONResponse:
    """捕获所有 OmicsHubException 及其子类"""
    logger.warning(f"Business exception [{exc.code}]: {exc.message} | path={request.url.path}")
    return JSONResponse(
        status_code=200,  # HTTP 状态码始终 200，业务状态码在 body 中
        content=ResponseModel(
            code=exc.code,
            message=exc.message,
            data=exc.details if exc.details else None
        ).model_dump(mode="json")
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """捕获 FastAPI HTTPException（如 401 未认证）"""
    return JSONResponse(
        status_code=200,
        content=ResponseModel(
            code=exc.status_code,
            message=exc.detail,
            data=None
        ).model_dump(mode="json")
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """捕获请求参数校验失败（Pydantic ValidationError）"""
    errors = []
    for err in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "type": err["type"]
        })
    return JSONResponse(
        status_code=200,
        content=ResponseModel(
            code=422,
            message=f"参数校验失败: {errors[0]['message']}" if errors else "参数校验失败",
            data={"errors": errors} if len(errors) > 1 else None
        ).model_dump(mode="json")
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """捕获未处理的异常（兜底）"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=200,
        content=ResponseModel(
            code=500,
            message="Internal server error",
            data=None
        ).model_dump(mode="json")
    )


# ============ 在 FastAPI 应用实例上注册 ============
# app = FastAPI()
# app.add_exception_handler(OmicsHubException, omicshub_exception_handler)
# app.add_exception_handler(StarletteHTTPException, http_exception_handler)
# app.add_exception_handler(RequestValidationError, validation_exception_handler)
# app.add_exception_handler(Exception, unhandled_exception_handler)
```

---

### 1.4 JWT 认证依赖

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional

# JWT 配置（从环境变量读取）
JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
REFRESH_TOKEN_EXPIRE_DAYS: int = 7

# OAuth2 密码模式 Bearer Token
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    scheme_name="JWT"
)


class TokenPayload(BaseModel):
    """JWT Token 载荷"""
    sub: str = Field(description="用户 UUID")
    username: str = Field(description="用户名")
    role: str = Field(description="用户角色")
    exp: Optional[int] = Field(default=None, description="过期时间（Unix timestamp）")
    iat: Optional[int] = Field(default=None, description="签发时间（Unix timestamp）")
    type: str = Field(default="access", description="token 类型: access / refresh")


class CurrentUser(BaseModel):
    """注入到路由处理函数中的当前用户对象"""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="用户 UUID")
    username: str = Field(description="用户名")
    email: str = Field(description="邮箱")
    role: str = Field(description="角色: admin / user")
    is_active: bool = Field(description="账户是否激活")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """
    从 JWT Token 解析当前用户。
    注入方式: `current_user: CurrentUser = Depends(get_current_user)`
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        role: str = payload.get("role")
        if user_id is None or username is None:
            raise credentials_exception

        # 检查 token 是否过期
        exp = payload.get("exp")
        if exp and datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 检查 token 类型
        token_type = payload.get("type", "access")
        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type: expected access token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    except JWTError:
        raise credentials_exception

    # 从数据库获取用户（实际实现中使用异步 ORM 查询）
    # user = await user_repository.get_by_uuid(user_id)
    # if user is None or not user.is_active:
    #     raise credentials_exception
    # return CurrentUser.model_validate(user)

    # 示例返回
    return CurrentUser(
        id=user_id,
        username=username,
        email=f"{username}@example.com",
        role=role,
        is_active=True
    )


async def get_current_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """
    仅管理员可访问的依赖。
    注入方式: `current_user: CurrentUser = Depends(get_current_admin)`
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required",
        )
    return current_user


class TokenResponse(BaseModel):
    """Token 响应体"""
    access_token: str = Field(description="访问令牌（短期有效，默认30分钟）")
    refresh_token: str = Field(description="刷新令牌（长期有效，默认7天）")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(description="访问令牌过期时间（秒）")
    user: "UserResponse" = Field(description="用户信息")
```

---

### 1.5 API 路由注册规范

```python
from fastapi import FastAPI, APIRouter

app = FastAPI(
    title="OmicsHub API",
    description="OmicsHub 多组学分析平台 RESTful API",
    version="1.0.0",
    docs_url="/api/docs",           # Swagger UI
    redoc_url="/api/redoc",         # ReDoc
    openapi_url="/api/openapi.json"
)

# ============ 版本前缀与路由注册 ============
# 各域路由在独立模块中定义，此处展示注册方式：
#
# from app.api.v1.auth import router as auth_router
# from app.api.v1.users import router as users_router
# from app.api.v1.projects import router as projects_router
# from app.api.v1.flows import router as flows_router
# from app.api.v1.tasks import router as tasks_router
# from app.api.v1.chat import router as chat_router
# from app.api.v1.mcp import router as mcp_router
# from app.api.v1.internal import router as internal_router
# from app.api.ws import ws_router
#
# app.include_router(auth_router,       prefix="/api/v1")
# app.include_router(users_router,      prefix="/api/v1")
# app.include_router(projects_router,   prefix="/api/v1")
# app.include_router(flows_router,      prefix="/api/v1")
# app.include_router(tasks_router,      prefix="/api/v1")
# app.include_router(chat_router,       prefix="/api/v1")
# app.include_router(mcp_router,        prefix="/api/v1")
# app.include_router(internal_router,   prefix="")
# app.include_router(ws_router,         prefix="")
```

---

## 2. 枚举类型定义

所有枚举类型统一放置在 `app/core/enums.py` 中，供 DTO 模型和领域层共用。

```python
from enum import Enum


class RoleEnum(str, Enum):
    """用户角色枚举"""
    ADMIN = "admin"
    USER = "user"


class TaskStatusEnum(str, Enum):
    """任务状态枚举（严格状态机）"""
    PENDING = "pending"       # 待提交（参数已保存，未进入队列）
    QUEUED = "queued"         # 已入队（等待Worker消费）
    RUNNING = "running"       # 执行中
    SUCCESS = "success"       # 成功完成
    FAILED = "failed"         # 执行失败
    CANCELLED = "cancelled"   # 用户取消

    @classmethod
    def terminal_states(cls) -> set[str]:
        """终止状态集合（不可再变更）"""
        return {cls.SUCCESS.value, cls.FAILED.value, cls.CANCELLED.value}

    @classmethod
    def running_states(cls) -> set[str]:
        """可取消的状态集合"""
        return {cls.PENDING.value, cls.QUEUED.value, cls.RUNNING.value}


class ExecutionModeEnum(str, Enum):
    """任务执行模式枚举"""
    LOCAL = "local"    # 本地Snakemake子进程执行
    REMOTE = "remote"  # 远程集群执行（Slurm/SGE）


class FlowCategoryEnum(str, Enum):
    """流程分类枚举"""
    TRANSCRIPTOMICS = "transcriptomics"    # 转录组学
    GENOMICS = "genomics"                  # 基因组学
    EPIGENETICS = "epigenetics"            # 表观遗传学
    METABOLOMICS = "metabolomics"          # 代谢组学
    PROTEOMICS = "proteomics"              # 蛋白质组学
    INTEGRATIVE = "integrative"            # 整合分析
    CUSTOM = "custom"                      # 自定义流程


class FileTypeEnum(str, Enum):
    """文件类型枚举"""
    FASTQ = "fastq"
    BAM = "bam"
    VCF = "vcf"
    COUNT_MATRIX = "count_matrix"
    META = "meta"
    GFF = "gff"
    BED = "bed"
    CSV = "csv"
    TSV = "tsv"
    PDF = "pdf"
    PNG = "png"
    JPG = "jpg"
    ZIP = "zip"
    OTHER = "other"


class MessageRoleEnum(str, Enum):
    """AI 对话消息角色枚举"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TransportEnum(str, Enum):
    """MCP Server 传输协议枚举"""
    STDIO = "stdio"
    SSE = "sse"


class ServerStatusEnum(str, Enum):
    """MCP Server 健康状态枚举"""
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class LogLevelEnum(str, Enum):
    """日志级别枚举"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
```

---

## 3. REST API 路由设计

以下按域分组列出完整路由表，每个路由包含：方法、路径、认证要求、核心功能描述、请求/响应类型。

### 3.1 认证域（/api/v1/auth）

| 方法 | 路径 | 认证 | 功能 | 请求体 | 响应体 |
|------|------|------|------|--------|--------|
| POST | `/auth/login` | 公开 | OAuth2 密码登录，返回 JWT Token | `OAuth2PasswordRequestForm` | `ResponseModel[TokenResponse]` |
| POST | `/auth/register` | 公开 | 用户注册（默认 role=user） | `UserRegisterRequest` | `ResponseModel[UserResponse]` |
| POST | `/auth/refresh` | 公开 | 使用 Refresh Token 换取新 Access Token | `RefreshTokenRequest` | `ResponseModel[TokenResponse]` |
| GET | `/auth/me` | JWT | 获取当前登录用户信息 | - | `ResponseModel[UserResponse]` |

```python
# app/api/v1/auth.py
from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=ResponseModel[TokenResponse],
    summary="用户登录",
    description="OAuth2 Password Bearer 方式登录，成功后返回 Access Token 和 Refresh Token"
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    **请求示例**:
    ```bash
    curl -X POST "https://omicshub.hzau.edu.cn/api/v1/auth/login" \\
      -H "Content-Type: application/x-www-form-urlencoded" \\
      -d "username=zhangsan&password=secret123"
    ```

    **响应示例**:
    ```json
    {
      "code": 200,
      "message": "Login successful",
      "data": {
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
        "token_type": "bearer",
        "expires_in": 1800,
        "user": {
          "id": "550e8400-e29b-41d4-a716-446655440000",
          "username": "zhangsan",
          "email": "zhangsan@hzau.edu.cn",
          "role": "user",
          "is_active": true,
          "created_at": "2025-01-01T12:00:00Z"
        }
      },
      "timestamp": "2025-01-01T12:00:00Z"
    }
    ```
    """
    ...


@router.post(
    "/register",
    response_model=ResponseModel[UserResponse],
    status_code=status.HTTP_201_CREATED,
    summary="用户注册"
)
async def register(req: UserRegisterRequest):
    ...


@router.post(
    "/refresh",
    response_model=ResponseModel[TokenResponse],
    summary="刷新 Token"
)
async def refresh(req: RefreshTokenRequest):
    ...


@router.get(
    "/me",
    response_model=ResponseModel[UserResponse],
    summary="获取当前用户信息"
)
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    ...
```

---

### 3.2 用户域（/api/v1/users）

| 方法 | 路径 | 认证 | 功能 | 请求体 | 响应体 |
|------|------|------|------|--------|--------|
| GET | `/users/` | Admin | 用户列表（分页+搜索） | Query: `page`, `page_size`, `q`, `role`, `is_active` | `ResponseModel[PageModel[UserResponse]]` |
| GET | `/users/{user_id}` | JWT | 用户详情 | - | `ResponseModel[UserResponse]` |
| PUT | `/users/{user_id}` | JWT | 更新用户信息 | `UserUpdateRequest` | `ResponseModel[UserResponse]` |
| DELETE | `/users/{user_id}` | Admin | 禁用用户（软删除） | - | `ResponseModel[None]` |

```python
# app/api/v1/users.py
from fastapi import APIRouter, Depends, Query
from typing import Optional

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/",
    response_model=ResponseModel[PageModel[UserResponse]],
    summary="用户列表（管理员）",
    dependencies=[Depends(get_current_admin)]
)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: Optional[str] = Query(None, description="搜索关键词（用户名/邮箱）"),
    role: Optional[RoleEnum] = Query(None),
    is_active: Optional[bool] = Query(None)
):
    ...


@router.get(
    "/{user_id}",
    response_model=ResponseModel[UserResponse],
    summary="用户详情"
)
async def get_user(
    user_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    # 普通用户只能查看自己，管理员可查看所有
    ...


@router.put(
    "/{user_id}",
    response_model=ResponseModel[UserResponse],
    summary="更新用户信息"
)
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.delete(
    "/{user_id}",
    response_model=ResponseModel[None],
    summary="禁用用户",
    dependencies=[Depends(get_current_admin)]
)
async def deactivate_user(user_id: str):
    ...
```

---

### 3.3 项目域（/api/v1/projects）

| 方法 | 路径 | 认证 | 功能 | 请求/Query | 响应体 |
|------|------|------|------|------------|--------|
| GET | `/projects/` | JWT | 当前用户的项目列表 | `page`, `page_size`, `q`, `workspace_id` | `ResponseModel[PageModel[ProjectResponse]]` |
| POST | `/projects/` | JWT | 创建项目 | `ProjectCreateRequest` | `ResponseModel[ProjectResponse]` |
| GET | `/projects/{project_id}` | JWT | 项目详情 | - | `ResponseModel[ProjectDetailResponse]` |
| PUT | `/projects/{project_id}` | JWT | 更新项目 | `ProjectUpdateRequest` | `ResponseModel[ProjectResponse]` |
| DELETE | `/projects/{project_id}` | JWT | 删除项目 | - | `ResponseModel[None]` |
| GET | `/projects/{project_id}/samples` | JWT | 项目下样本列表 | `page`, `page_size` | `ResponseModel[PageModel[SampleResponse]]` |
| POST | `/projects/{project_id}/upload` | JWT | 批量上传文件 | `multipart/form-data` | `ResponseModel[FileUploadResponse]` |

```python
# app/api/v1/projects.py
from fastapi import APIRouter, Depends, Query, UploadFile, File
from typing import Optional, List

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("/", response_model=ResponseModel[PageModel[ProjectResponse]], summary="项目列表")
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: Optional[str] = Query(None, description="项目名称搜索"),
    workspace_id: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.post(
    "/",
    response_model=ResponseModel[ProjectResponse],
    status_code=201,
    summary="创建项目"
)
async def create_project(
    req: ProjectCreateRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.get("/{project_id}", response_model=ResponseModel[ProjectDetailResponse], summary="项目详情")
async def get_project(project_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ...


@router.put("/{project_id}", response_model=ResponseModel[ProjectResponse], summary="更新项目")
async def update_project(
    project_id: str,
    req: ProjectUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.delete("/{project_id}", response_model=ResponseModel[None], summary="删除项目")
async def delete_project(project_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ...


@router.get(
    "/{project_id}/samples",
    response_model=ResponseModel[PageModel[SampleResponse]],
    summary="项目下样本列表"
)
async def list_project_samples(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.post(
    "/{project_id}/upload",
    response_model=ResponseModel[FileUploadResponse],
    summary="批量上传文件"
)
async def upload_files(
    project_id: str,
    files: List[UploadFile] = File(..., description="要上传的文件列表"),
    sample_name: Optional[str] = Query(None, description="关联的样本名称"),
    file_type: Optional[FileTypeEnum] = Query(None),
    current_user: CurrentUser = Depends(get_current_user)
):
    ...
```

---

### 3.4 流程域（/api/v1/flows）

| 方法 | 路径 | 认证 | 功能 | 请求/Query | 响应体 |
|------|------|------|------|------------|--------|
| GET | `/flows/` | JWT | 流程列表（分类筛选、搜索） | `category`, `q`, `page`, `page_size` | `ResponseModel[PageModel[FlowListItem]]` |
| GET | `/flows/{flow_id}` | JWT | 流程详情（含参数定义） | - | `ResponseModel[FlowDetailResponse]` |
| GET | `/flows/{flow_id}/schema` | JWT | 获取 JSON Schema（前端表单渲染） | - | `ResponseModel[dict]` |
| GET | `/flows/{flow_id}/validate` | JWT | 参数预校验 | `Query: parameters` (JSON字符串) | `ResponseModel[ValidationResult]` |
| POST | `/flows/` | Admin | 创建流程（上传YAML） | `FlowCreateRequest` | `ResponseModel[FlowDetailResponse]` |
| PUT | `/flows/{flow_id}` | Admin | 更新流程 | `FlowUpdateRequest` | `ResponseModel[FlowDetailResponse]` |
| DELETE | `/flows/{flow_id}` | Admin | 禁用流程 | - | `ResponseModel[None]` |

```python
# app/api/v1/flows.py
from fastapi import APIRouter, Depends, Query
from typing import Optional

router = APIRouter(prefix="/flows", tags=["Flows"])


@router.get("/", response_model=ResponseModel[PageModel[FlowListItem]], summary="流程列表")
async def list_flows(
    category: Optional[FlowCategoryEnum] = Query(None),
    q: Optional[str] = Query(None, description="流程名称搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.get("/{flow_id}", response_model=ResponseModel[FlowDetailResponse], summary="流程详情")
async def get_flow(flow_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ...


@router.get(
    "/{flow_id}/schema",
    response_model=ResponseModel[dict],
    summary="获取流程参数的 JSON Schema"
)
async def get_flow_schema(flow_id: str, current_user: CurrentUser = Depends(get_current_user)):
    """
    返回 JSON Schema 用于前端 DynamicForm 组件渲染表单。
    Schema 包含每个参数的类型、默认值、校验规则、UI控件类型。
    """
    ...


@router.get(
    "/{flow_id}/validate",
    response_model=ResponseModel[ValidationResult],
    summary="预校验用户参数"
)
async def validate_parameters(
    flow_id: str,
    parameters: str = Query(..., description="用户填写的参数字典（JSON字符串）"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    在正式提交任务前，对用户填写的参数进行校验，
    返回详细的校验结果（哪些参数合法、哪些有问题）。
    """
    ...


@router.post(
    "/",
    response_model=ResponseModel[FlowDetailResponse],
    status_code=201,
    summary="创建流程（管理员）",
    dependencies=[Depends(get_current_admin)]
)
async def create_flow(req: FlowCreateRequest):
    ...


@router.put(
    "/{flow_id}",
    response_model=ResponseModel[FlowDetailResponse],
    summary="更新流程（管理员）",
    dependencies=[Depends(get_current_admin)]
)
async def update_flow(flow_id: str, req: FlowUpdateRequest):
    ...


@router.delete(
    "/{flow_id}",
    response_model=ResponseModel[None],
    summary="禁用流程（管理员）",
    dependencies=[Depends(get_current_admin)]
)
async def deactivate_flow(flow_id: str):
    ...
```

---

### 3.5 任务域（/api/v1/tasks）

任务域是 OmicsHub 的核心业务域，涵盖任务提交、状态查询、日志获取、结果下载与预览。

| 方法 | 路径 | 认证 | 功能 | 请求/Query | 响应体 |
|------|------|------|------|------------|--------|
| POST | `/tasks/` | JWT | **提交任务** | `TaskCreateRequest` | `ResponseModel[TaskResponse]` |
| GET | `/tasks/` | JWT | 任务列表 | `status`, `flow_type`, `date_from`, `date_to`, `page` | `ResponseModel[PageModel[TaskListItem]]` |
| GET | `/tasks/{task_id}` | JWT | 任务详情 | - | `ResponseModel[TaskDetailResponse]` |
| DELETE | `/tasks/{task_id}/cancel` | JWT | 取消任务 | - | `ResponseModel[TaskResponse]` |
| GET | `/tasks/{task_id}/logs` | JWT | 获取日志 | `offset`, `limit`, `level` | `ResponseModel[TaskLogResponse]` |
| GET | `/tasks/{task_id}/results` | JWT | 获取结果文件列表 | - | `ResponseModel[ResultFileListResponse]` |
| GET | `/tasks/{task_id}/results/{file_path}` | JWT | 下载结果文件 | - | `FileResponse` (streaming) |
| GET | `/tasks/{task_id}/preview/{file_path}` | JWT | 预览结果 | `format` | `ResponseModel[PreviewResponse]` |

```python
# app/api/v1/tasks.py
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from typing import Optional

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post(
    "/",
    response_model=ResponseModel[TaskResponse],
    status_code=201,
    summary="提交分析任务"
)
async def submit_task(
    req: TaskCreateRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    **核心接口**：接收流程ID + 用户参数 + 项目ID，创建并提交分析任务。

    任务提交流程：
    1. 校验流程定义是否存在且启用
    2. 校验用户参数是否通过流程的 JSON Schema 校验
    3. 创建任务记录（状态: PENDING）
    4. 根据流程配置选择执行模式（LOCAL/REMOTE）
    5. 发布任务到 Celery 队列
    6. 返回任务信息（前端可立即连接 WebSocket 监控）

    **请求示例**:
    ```json
    {
      "flow_id": "f1a2b3c4-d5e6-7890-abcd-ef1234567890",
      "project_id": "p9a8b7c6-d5e4-3210-fedc-ba0987654321",
      "name": "RNA-Seq 差异表达分析 - 拟南芥盐胁迫",
      "parameters": {
        "genome": "Arabidopsis_thaliana.TAIR10",
        "samples": ["sample_001", "sample_002", "sample_003"],
        "treatment_group": ["sample_001"],
        "control_group": ["sample_002", "sample_003"],
        "fc_threshold": 2.0,
        "pvalue_threshold": 0.05,
        "run_go_enrichment": true
      },
      "execution_mode": "local",
      "description": "盐胁迫处理 vs 对照组差异表达分析"
    }
    ```
    """
    ...


@router.get("/", response_model=ResponseModel[PageModel[TaskListItem]], summary="任务列表")
async def list_tasks(
    status: Optional[TaskStatusEnum] = Query(None),
    flow_type: Optional[str] = Query(None, description="流程类型/分类筛选"),
    date_from: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.get("/{task_id}", response_model=ResponseModel[TaskDetailResponse], summary="任务详情")
async def get_task(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ...


@router.delete(
    "/{task_id}/cancel",
    response_model=ResponseModel[TaskResponse],
    summary="取消任务"
)
async def cancel_task(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    """
    取消处于 PENDING / QUEUED / RUNNING 状态的任务。
    已终止的任务（SUCCESS/FAILED/CANCELLED）不可取消。
    """
    ...


@router.get(
    "/{task_id}/logs",
    response_model=ResponseModel[TaskLogResponse],
    summary="获取任务日志"
)
async def get_task_logs(
    task_id: str,
    offset: int = Query(0, ge=0, description="日志起始偏移"),
    limit: int = Query(500, ge=1, le=5000, description="返回条数上限"),
    level: Optional[LogLevelEnum] = Query(None, description="日志级别筛选"),
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.get(
    "/{task_id}/results",
    response_model=ResponseModel[ResultFileListResponse],
    summary="获取结果文件列表"
)
async def list_result_files(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ...


@router.get(
    "/{task_id}/results/{file_path:path}",
    summary="下载结果文件",
    response_class=StreamingResponse
)
async def download_result_file(
    task_id: str,
    file_path: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    file_path 为任务工作目录内的相对路径。
    使用 URL 编码处理路径分隔符（如 `%2F`）。
    返回 streaming 响应，支持大文件下载。
    """
    ...


@router.get(
    "/{task_id}/preview/{file_path:path}",
    response_model=ResponseModel[PreviewResponse],
    summary="预览结果文件"
)
async def preview_result_file(
    task_id: str,
    file_path: str,
    format: Optional[str] = Query(None, description="指定预览格式: auto/table/image/pdf"),
    max_rows: int = Query(100, ge=1, le=1000, description="表格最大行数"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    智能预览结果文件：
    - `.csv/.tsv/.txt` → 表格预览（返回结构化数据）
    - `.png/.jpg/.jpeg` → 图片预览（返回图片 URL）
    - `.pdf` → PDF 预览（返回可嵌入 URL）
    - 其他 → 返回文件元信息
    """
    ...
```

---

### 3.6 AI 对话域（/api/v1/chat）

| 方法 | 路径 | 认证 | 功能 | 请求体 | 响应体 |
|------|------|------|------|--------|--------|
| GET | `/chat/sessions` | JWT | 会话列表 | Query: `page`, `page_size` | `ResponseModel[PageModel[ChatSessionListItem]]` |
| POST | `/chat/sessions` | JWT | 创建会话 | `ChatSessionCreateRequest` | `ResponseModel[ChatSessionResponse]` |
| GET | `/chat/sessions/{session_id}` | JWT | 会话详情（含消息） | - | `ResponseModel[ChatSessionDetailResponse]` |
| DELETE | `/chat/sessions/{session_id}` | JWT | 删除会话 | - | `ResponseModel[None]` |
| GET | `/chat/sessions/{session_id}/messages` | JWT | 获取消息历史 | `page`, `page_size` | `ResponseModel[PageModel[ChatMessageResponse]]` |
| POST | `/chat` | JWT | 发送消息（SSE 流式返回） | `ChatRequest` | `StreamingResponse (application/x-ndjson)` |
| POST | `/chat/tool-confirm` | JWT | 确认执行 AI 提议的工具调用 | `ToolConfirmRequest` | `ResponseModel[ChatMessageResponse]` |

```python
# app/api/v1/chat.py
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from typing import Optional

router = APIRouter(prefix="/chat", tags=["AI Chat"])


@router.get(
    "/sessions",
    response_model=ResponseModel[PageModel[ChatSessionListItem]],
    summary="会话列表"
)
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.post(
    "/sessions",
    response_model=ResponseModel[ChatSessionResponse],
    status_code=201,
    summary="创建会话"
)
async def create_session(
    req: ChatSessionCreateRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.get(
    "/sessions/{session_id}",
    response_model=ResponseModel[ChatSessionDetailResponse],
    summary="会话详情"
)
async def get_session(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.delete(
    "/sessions/{session_id}",
    response_model=ResponseModel[None],
    summary="删除会话"
)
async def delete_session(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ResponseModel[PageModel[ChatMessageResponse]],
    summary="获取消息历史"
)
async def get_messages(
    session_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.post(
    "/chat",
    summary="发送消息（SSE 流式）",
    response_class=StreamingResponse
)
async def chat(
    req: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    **SSE 流式接口**，返回 `application/x-ndjson` 格式。

    每行一个 JSON 对象（以 `\n` 分隔），流式推送 AI 的回复片段：

    ```ndjson
    {"type": "chunk", "content": "根据"}
    {"type": "chunk", "content": "你的样本"}
    {"type": "chunk", "content": "数据，"}
    {"type": "tool_call", "tool_call": {"call_id": "call_abc", "tool_name": "submit_task", "arguments": {"flow_id": "xxx", "parameters": {...}}}}
    {"type": "done", "message_id": "msg_xyz"}
    ```

    **事件类型说明**：
    | type | 说明 |
    |------|------|
    | `chunk` | 文本片段（delta） |
    | `tool_call` | AI 请求调用工具 |
    | `tool_result` | 工具执行结果 |
    | `mcp_result` | MCP 工具调用结果 |
    | `error` | 对话错误 |
    | `done` | 流结束 |
    """
    ...


@router.post(
    "/tool-confirm",
    response_model=ResponseModel[ChatMessageResponse],
    summary="确认执行 AI 提议的工具调用"
)
async def confirm_tool_call(
    req: ToolConfirmRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    当 AI 通过 `tool_call` 事件请求调用工具时，前端展示工具调用意图，
    用户确认后调用此接口执行实际工具调用。
    """
    ...
```

---

### 3.7 MCP 域（/api/v1/mcp）

| 方法 | 路径 | 认证 | 功能 | 请求体 | 响应体 |
|------|------|------|------|--------|--------|
| GET | `/mcp/servers` | JWT | MCP Server 列表 | - | `ResponseModel[list[MCPServerListItem]]` |
| POST | `/mcp/servers` | Admin | 注册 MCP Server | `MCPServerCreateRequest` | `ResponseModel[MCPServerResponse]` |
| GET | `/mcp/servers/{server_id}` | JWT | Server 详情 | - | `ResponseModel[MCPServerDetailResponse]` |
| DELETE | `/mcp/servers/{server_id}` | Admin | 注销 Server | - | `ResponseModel[None]` |
| GET | `/mcp/servers/{server_id}/tools` | JWT | 获取工具列表 | - | `ResponseModel[list[MCPToolInfo]]` |
| POST | `/mcp/invoke` | JWT | 手动调用 MCP 工具 | `MCPInvokeRequest` | `ResponseModel[MCPInvokeResponse]` |
| GET | `/mcp/servers/{server_id}/health` | Admin | 健康检查 | - | `ResponseModel[HealthCheckResponse]` |

```python
# app/api/v1/mcp.py
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/mcp", tags=["MCP"])


@router.get(
    "/servers",
    response_model=ResponseModel[list[MCPServerListItem]],
    summary="MCP Server 列表"
)
async def list_servers(current_user: CurrentUser = Depends(get_current_user)):
    ...


@router.post(
    "/servers",
    response_model=ResponseModel[MCPServerResponse],
    status_code=201,
    summary="注册 MCP Server（管理员）",
    dependencies=[Depends(get_current_admin)]
)
async def create_server(req: MCPServerCreateRequest):
    ...


@router.get(
    "/servers/{server_id}",
    response_model=ResponseModel[MCPServerDetailResponse],
    summary="Server 详情"
)
async def get_server(server_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ...


@router.delete(
    "/servers/{server_id}",
    response_model=ResponseModel[None],
    summary="注销 Server（管理员）",
    dependencies=[Depends(get_current_admin)]
)
async def delete_server(server_id: str):
    ...


@router.get(
    "/servers/{server_id}/tools",
    response_model=ResponseModel[list[MCPToolInfo]],
    summary="获取 Server 的工具列表"
)
async def list_tools(server_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ...


@router.post(
    "/invoke",
    response_model=ResponseModel[MCPInvokeResponse],
    summary="手动调用 MCP 工具"
)
async def invoke_tool(
    req: MCPInvokeRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    ...


@router.get(
    "/servers/{server_id}/health",
    response_model=ResponseModel[HealthCheckResponse],
    summary="MCP Server 健康检查",
    dependencies=[Depends(get_current_admin)]
)
async def health_check(server_id: str):
    ...
```

---

### 3.8 内部回调域（/internal）

**安全设计**：此域的路由 **不对外暴露**，仅允许来自 Master 节点的内部 IP 访问。

| 方法 | 路径 | 认证 | 功能 | 请求体 | 响应体 |
|------|------|------|------|--------|--------|
| POST | `/internal/callback/task-complete` | IP白名单 | Master 节点任务完成回调 | `TaskCompleteCallback` | `ResponseModel[None]` |
| POST | `/internal/callback/task-progress` | IP白名单 | Master 节点进度推送（备用） | `TaskProgressCallback` | `ResponseModel[None]` |

```python
# app/api/v1/internal.py
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import ipaddress

router = APIRouter(prefix="/internal", tags=["Internal Callbacks"])

# Master 节点 IP 白名单（从配置读取）
MASTER_IP_WHITELIST = ["10.0.0.0/8", "172.16.0.0/12", "127.0.0.1/32"]


async def verify_internal_ip(request: Request):
    """IP 白名单校验依赖"""
    client_ip = request.client.host if request.client else ""
    for network in MASTER_IP_WHITELIST:
        if ipaddress.ip_address(client_ip) in ipaddress.ip_network(network):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied: IP not in whitelist"
    )


@router.post(
    "/callback/task-complete",
    response_model=ResponseModel[None],
    summary="任务完成回调（Master 节点）",
    dependencies=[Depends(verify_internal_ip)]
)
async def task_complete_callback(req: TaskCompleteCallback):
    """
    Snakemake Master 节点（本地或远程）在任务完成后调用此接口回传结果。

    回调信息包括：
    - 任务最终状态（SUCCESS / FAILED）
    - 结果文件路径列表
    - 执行摘要（耗时、资源使用等）
    - 错误信息（如失败）

    收到回调后，系统：
    1. 更新任务状态和元信息
    2. 扫描结果文件目录，构建结果索引
    3. 通过 WebSocket 推送 `task.completed` 事件
    4. 触发结果归档（异步）
    """
    ...


@router.post(
    "/callback/task-progress",
    response_model=ResponseModel[None],
    summary="任务进度回调（Master 节点，备用）",
    dependencies=[Depends(verify_internal_ip)]
)
async def task_progress_callback(req: TaskProgressCallback):
    """
    当 WebSocket 通道不可用时，Master 节点可通过此 REST 接口推送进度。
    收到后系统转发到 WebSocket 通道。
    """
    ...
```

---

## 4. Pydantic v2 DTO 模型定义

所有 DTO 模型放置在 `app/schemas/` 目录下，按域分文件组织。

### 4.1 基础模型与通用 DTO

```python
# app/schemas/base.py
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class OmicsHubBaseSchema(BaseModel):
    """所有 Schema 的基类"""
    model_config = ConfigDict(
        from_attributes=True,        # 支持从 ORM 对象自动转换
        populate_by_name=True,       # 允许通过字段名赋值
        str_strip_whitespace=True,   # 自动去除字符串首尾空格
        use_enum_values=True,        # 枚举序列化为值而非名称
    )


class TimestampMixin(BaseModel):
    """时间戳混入类"""
    created_at: datetime = Field(description="创建时间（UTC）")
    updated_at: datetime = Field(description="更新时间（UTC）")


class PaginationParams(OmicsHubBaseSchema):
    """分页参数基类"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    sort_by: Optional[str] = Field(default="created_at")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")
```

---

### 4.2 认证域 DTO

```python
# app/schemas/auth.py
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional
import re


class UserRegisterRequest(OmicsHubBaseSchema):
    """用户注册请求"""
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$",
        description="用户名：字母/数字/下划线，3-50字符"
    )
    email: str = Field(
        ...,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
        description="邮箱地址"
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="密码：至少8位字符"
    )

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """密码强度校验"""
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class RefreshTokenRequest(OmicsHubBaseSchema):
    """刷新 Token 请求"""
    refresh_token: str = Field(..., description="Refresh Token")


class UserResponse(OmicsHubBaseSchema):
    """用户响应（脱敏，不包含密码）"""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="用户 UUID")
    username: str = Field(description="用户名")
    email: str = Field(description="邮箱")
    role: RoleEnum = Field(description="角色")
    is_active: bool = Field(description="账户状态")
    avatar_url: Optional[str] = Field(default=None, description="头像 URL")
    preferences: dict = Field(default_factory=dict, description="用户偏好")
    last_login_at: Optional[datetime] = Field(default=None, description="最后登录时间")
    created_at: datetime = Field(description="创建时间")
```

---

### 4.3 用户域 DTO

```python
# app/schemas/user.py
from pydantic import Field, field_validator
from typing import Optional


class UserUpdateRequest(OmicsHubBaseSchema):
    """用户更新请求"""
    username: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$"
    )
    email: Optional[str] = Field(
        default=None,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    )
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    preferences: Optional[dict] = Field(default=None, description="用户偏好设置")

    @field_validator("preferences")
    @classmethod
    def validate_preferences(cls, v: Optional[dict]) -> Optional[dict]:
        if v is not None and not isinstance(v, dict):
            raise ValueError("Preferences must be a JSON object")
        return v


class UserListItem(OmicsHubBaseSchema):
    """用户列表项（精简字段，减少传输量）"""
    id: str
    username: str
    email: str
    role: RoleEnum
    is_active: bool
    created_at: datetime


class UserListParams(PaginationParams):
    """用户列表查询参数"""
    q: Optional[str] = Field(default=None, description="搜索关键词")
    role: Optional[RoleEnum] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)
```

---

### 4.4 项目域 DTO

```python
# app/schemas/project.py
from pydantic import Field, field_validator, model_validator
from typing import Optional, List
from datetime import datetime


class ProjectCreateRequest(OmicsHubBaseSchema):
    """创建项目请求"""
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="项目名称"
    )
    description: Optional[str] = Field(default=None, max_length=2000)
    workspace_id: Optional[str] = Field(
        default=None,
        description="所属工作空间 UUID（为空则放入默认空间）"
    )
    metadata: Optional[dict] = Field(
        default_factory=dict,
        description="项目元信息（JSON）：物种、测序平台、参考文献等"
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Project name cannot be empty")
        return v.strip()


class ProjectUpdateRequest(OmicsHubBaseSchema):
    """更新项目请求"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    workspace_id: Optional[str] = Field(default=None)
    metadata: Optional[dict] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)


class ProjectResponse(OmicsHubBaseSchema):
    """项目响应"""
    id: str
    name: str
    description: Optional[str]
    owner_id: str
    workspace_id: Optional[str]
    metadata: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectDetailResponse(ProjectResponse):
    """项目详情（含关联统计）"""
    sample_count: int = Field(description="样本数量")
    task_count: int = Field(description="关联任务数量")
    recent_tasks: List["TaskListItem"] = Field(default_factory=list, description="最近任务")


class SampleCreateRequest(OmicsHubBaseSchema):
    """创建样本请求"""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    metadata: Optional[dict] = Field(
        default_factory=dict,
        description="样本元信息：物种、组织类型、处理方式等"
    )


class SampleResponse(OmicsHubBaseSchema):
    """样本响应"""
    id: str
    name: str
    description: Optional[str]
    project_id: str
    metadata: dict
    file_count: int = Field(description="关联文件数量")
    created_at: datetime
    updated_at: datetime


class FileUploadResponse(OmicsHubBaseSchema):
    """文件上传响应"""
    uploaded_files: List["FileInfo"] = Field(description="已上传文件列表")
    failed_files: List[dict] = Field(default_factory=list, description="上传失败的文件及原因")


class FileInfo(OmicsHubBaseSchema):
    """文件信息"""
    id: str
    filename: str
    file_type: FileTypeEnum
    size: int = Field(description="文件大小（字节）")
    path: str = Field(description="存储路径")
    checksum: Optional[str] = Field(default=None, description="SHA256 校验值")
    created_at: datetime
```

---

### 4.5 流程域 DTO

```python
# app/schemas/flow.py
from pydantic import Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime


class FlowListItem(OmicsHubBaseSchema):
    """流程列表项"""
    id: str
    name: str
    description: Optional[str]
    category: FlowCategoryEnum
    version: str
    author: Optional[str]
    tags: List[str] = Field(default_factory=list)
    is_active: bool
    created_at: datetime


class FlowParameter(OmicsHubBaseSchema):
    """流程参数定义（用于流程详情）"""
    name: str = Field(description="参数名（英文标识符）")
    label: str = Field(description="参数显示名（中文）")
    param_type: str = Field(description="参数类型: string/number/integer/boolean/select/file/array")
    required: bool = Field(default=False, description="是否必填")
    default: Optional[Any] = Field(default=None, description="默认值")
    description: Optional[str] = Field(default=None, description="参数说明")
    enum_values: Optional[List[dict]] = Field(
        default=None,
        description="枚举选项（select类型）: [{label, value}]"
    )
    validation: Optional[dict] = Field(
        default=None,
        description="校验规则: {min, max, pattern, max_file_size, allowed_extensions}"
    )
    ui_config: Optional[dict] = Field(
        default=None,
        description="UI渲染配置: {component, placeholder, help_text, col_span}"
    )


class FlowStepInfo(OmicsHubBaseSchema):
    """流程步骤信息"""
    name: str
    order: int
    description: Optional[str]
    tool: str = Field(description="使用的 Snakemake 规则名")
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)


class FlowDetailResponse(OmicsHubBaseSchema):
    """流程详情响应"""
    id: str
    name: str
    description: Optional[str]
    category: FlowCategoryEnum
    version: str
    author: Optional[str]
    tags: List[str] = Field(default_factory=list)
    parameters: List[FlowParameter] = Field(description="参数定义列表")
    steps: List[FlowStepInfo] = Field(description="分析步骤列表")
    ui_schema: dict = Field(description="前端表单布局 Schema")
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FlowCreateRequest(OmicsHubBaseSchema):
    """创建流程请求（管理员上传YAML）"""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    category: FlowCategoryEnum
    yaml_content: str = Field(..., min_length=10, description="流程 YAML 内容")
    tags: List[str] = Field(default_factory=list)

    @field_validator("yaml_content")
    @classmethod
    def validate_yaml_syntax(cls, v: str) -> str:
        """校验 YAML 语法合法性"""
        try:
            import yaml
            yaml.safe_load(v)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML syntax: {e}")
        return v


class FlowUpdateRequest(OmicsHubBaseSchema):
    """更新流程请求"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    category: Optional[FlowCategoryEnum] = Field(default=None)
    yaml_content: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)

    @field_validator("yaml_content")
    @classmethod
    def validate_yaml_syntax(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            import yaml
            yaml.safe_load(v)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML syntax: {e}")
        return v


class ValidationResult(OmicsHubBaseSchema):
    """参数校验结果"""
    valid: bool = Field(description="是否全部通过")
    errors: List[dict] = Field(default_factory=list, description="错误列表: [{field, message, type}]")
    warnings: List[dict] = Field(default_factory=list, description="警告列表")
```

---

### 4.6 任务域 DTO

```python
# app/schemas/task.py
from pydantic import Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime


class TaskCreateRequest(OmicsHubBaseSchema):
    """提交任务请求（核心接口）"""
    flow_id: str = Field(..., description="流程定义 UUID")
    project_id: Optional[str] = Field(
        default=None,
        description="关联项目 UUID（可选）"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="任务名称（用户自定义）"
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="流程参数字典（键为参数名，值为用户输入）"
    )
    execution_mode: ExecutionModeEnum = Field(
        default=ExecutionModeEnum.LOCAL,
        description="执行模式"
    )
    description: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_task_name(self) -> "TaskCreateRequest":
        if not self.name or not self.name.strip():
            raise ValueError("Task name is required")
        self.name = self.name.strip()
        return self


class TaskResponse(OmicsHubBaseSchema):
    """任务响应（基本信息）"""
    id: str = Field(description="任务 UUID")
    name: str
    flow_id: str
    project_id: Optional[str]
    user_id: str
    status: TaskStatusEnum
    execution_mode: ExecutionModeEnum
    description: Optional[str]
    progress_percent: int = Field(default=0, ge=0, le=100, description="进度百分比")
    current_step: Optional[str] = Field(default=None, description="当前执行步骤")
    work_dir: Optional[str] = Field(default=None, description="工作目录路径")
    created_at: datetime
    started_at: Optional[datetime] = Field(default=None, description="开始执行时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")


class TaskListItem(TaskResponse):
    """任务列表项（精简）"""
    flow_name: str = Field(description="关联流程名称")
    duration_seconds: Optional[int] = Field(
        default=None,
        description="执行时长（秒）"
    )


class TaskDetailResponse(TaskResponse):
    """任务详情"""
    parameters_snapshot: dict = Field(description="提交时的参数快照（JSONB）")
    logs_summary: Optional[dict] = Field(
        default=None,
        description="日志摘要: {total_lines, error_count, warning_count}"
    )
    resource_usage: Optional[dict] = Field(
        default=None,
        description="资源使用: {cpu_hours, memory_gb, disk_gb}"
    )
    error_info: Optional[str] = Field(
        default=None,
        description="失败时的错误信息"
    )


class TaskLogEntry(OmicsHubBaseSchema):
    """单条日志条目"""
    timestamp: datetime
    level: LogLevelEnum
    step: Optional[str] = Field(default=None, description="产生日志的步骤")
    message: str


class TaskLogResponse(OmicsHubBaseSchema):
    """日志查询响应"""
    entries: List[TaskLogEntry]
    total: int = Field(description="日志总条数")
    offset: int
    limit: int


class ResultFileInfo(OmicsHubBaseSchema):
    """结果文件信息"""
    path: str = Field(description="相对于任务工作目录的路径")
    name: str
    size: int = Field(description="文件大小（字节）")
    file_type: str = Field(description="文件类型")
    modified_at: datetime


class ResultFileListResponse(OmicsHubBaseSchema):
    """结果文件列表响应"""
    files: List[ResultFileInfo]
    total_size: int = Field(description="总大小（字节）")


class PreviewResponse(OmicsHubBaseSchema):
    """文件预览响应"""
    file_type: str = Field(description="检测到的文件类型")
    file_size: int
    preview_type: str = Field(description="预览类型: table/image/pdf/text/unsupported")

    # 表格预览
    headers: Optional[List[str]] = Field(default=None)
    rows: Optional[List[List[Any]]] = Field(default=None)
    total_rows: Optional[int] = Field(default=None)

    # 图片预览
    image_url: Optional[str] = Field(default=None, description="图片访问 URL")

    # PDF 预览
    pdf_url: Optional[str] = Field(default=None, description="PDF 访问 URL")
    page_count: Optional[int] = Field(default=None)

    # 文本预览
    text_content: Optional[str] = Field(default=None, description="文本内容预览")


class TaskCancelResponse(OmicsHubBaseSchema):
    """任务取消响应"""
    id: str
    previous_status: TaskStatusEnum = Field(description="取消前的状态")
    current_status: TaskStatusEnum = Field(default=TaskStatusEnum.CANCELLED)
    cancelled_at: datetime


class TaskCompleteCallback(OmicsHubBaseSchema):
    """任务完成回调（内部接口，Master 节点调用）"""
    task_id: str = Field(..., description="任务 UUID")
    status: str = Field(..., pattern="^(success|failed)$", description="最终状态")
    result_files: List[str] = Field(default_factory=list, description="结果文件路径列表")
    summary: Optional[dict] = Field(
        default=None,
        description="执行摘要: {total_time, steps_completed, peak_memory_gb}"
    )
    error_message: Optional[str] = Field(default=None, description="失败时的错误信息")
    exit_code: Optional[int] = Field(default=None, description="Snakemake 进程退出码")


class TaskProgressCallback(OmicsHubBaseSchema):
    """任务进度回调（内部接口，备用）"""
    task_id: str
    percent: int = Field(ge=0, le=100)
    current_step: str
    step_index: int
    total_steps: int
    message: Optional[str] = Field(default=None, description="进度消息")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

---

### 4.7 AI 对话域 DTO

```python
# app/schemas/chat.py
from pydantic import Field, field_validator, model_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime


class ChatSessionCreateRequest(OmicsHubBaseSchema):
    """创建会话请求"""
    title: Optional[str] = Field(
        default=None,
        max_length=200,
        description="会话标题（为空则自动生成）"
    )
    model: Optional[str] = Field(default="kimi-latest", description="使用的模型")
    context: Optional[dict] = Field(
        default=None,
        description="上下文信息: {current_page, task_id, project_id, selected_samples}"
    )


class ChatSessionResponse(OmicsHubBaseSchema):
    """会话响应"""
    id: str
    title: str
    model: str
    user_id: str
    context: dict
    message_count: int = Field(description="消息数量")
    created_at: datetime
    updated_at: datetime


class ChatSessionListItem(ChatSessionResponse):
    """会话列表项"""
    last_message_preview: Optional[str] = Field(
        default=None,
        description="最后一条消息预览"
    )


class ChatSessionDetailResponse(ChatSessionResponse):
    """会话详情（含最近消息）"""
    recent_messages: List["ChatMessageResponse"] = Field(default_factory=list)


class ChatMessageResponse(OmicsHubBaseSchema):
    """消息响应"""
    id: str
    session_id: str
    role: MessageRoleEnum
    content: str
    tool_calls: Optional[List[dict]] = Field(
        default=None,
        description="工具调用信息"
    )
    tool_results: Optional[List[dict]] = Field(
        default=None,
        description="工具执行结果"
    )
    metadata: Optional[dict] = Field(
        default=None,
        description="元信息: {token_usage, latency_ms, model}"
    )
    created_at: datetime


class ChatRequest(OmicsHubBaseSchema):
    """发送消息请求"""
    session_id: str = Field(..., description="会话 UUID")
    message: str = Field(..., min_length=1, max_length=20000, description="用户消息")
    context_override: Optional[dict] = Field(
        default=None,
        description="临时覆盖上下文"
    )
    stream: bool = Field(default=True, description="是否流式返回（SSE）")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v


class ToolConfirmRequest(OmicsHubBaseSchema):
    """工具确认请求"""
    session_id: str
    call_id: str = Field(..., description="tool_call 的 call_id")
    confirmed: bool = Field(description="是否确认执行")
    argument_overrides: Optional[Dict[str, Any]] = Field(
        default=None,
        description="用户修改后的参数（可选）"
    )


# ============ SSE 流式事件 DTO ============

class ChatStreamEvent(OmicsHubBaseSchema):
    """SSE 流式事件基类"""
    type: str = Field(description="事件类型")


class ChatChunkEvent(ChatStreamEvent):
    """文本片段事件"""
    type: Literal["chunk"] = "chunk"
    content: str = Field(description="增量文本")


class ChatToolCallEvent(ChatStreamEvent):
    """工具调用请求事件"""
    type: Literal["tool_call"] = "tool_call"
    tool_call: dict = Field(description="{call_id, tool_name, arguments, description}")


class ChatToolResultEvent(ChatStreamEvent):
    """工具执行结果事件"""
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    result: Any = Field(description="工具执行结果")
    success: bool


class ChatMCPResultEvent(ChatStreamEvent):
    """MCP 工具调用结果事件"""
    type: Literal["mcp_result"] = "mcp_result"
    server_name: str
    tool_name: str
    result: Any
    render_type: str = Field(
        default="text",
        description="渲染类型: text/table/image/error"
    )


class ChatErrorEvent(ChatStreamEvent):
    """对话错误事件"""
    type: Literal["error"] = "error"
    error_code: str
    message: str


class ChatDoneEvent(ChatStreamEvent):
    """流结束事件"""
    type: Literal["done"] = "done"
    message_id: str
    usage: Optional[dict] = Field(
        default=None,
        description="Token 用量: {prompt_tokens, completion_tokens, total_tokens}"
    )
```

---

### 4.8 MCP 域 DTO

```python
# app/schemas/mcp.py
from pydantic import Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime


class MCPServerCreateRequest(OmicsHubBaseSchema):
    """注册 MCP Server 请求"""
    name: str = Field(..., min_length=1, max_length=100, description="Server 名称")
    description: Optional[str] = Field(default=None, max_length=1000)
    transport: TransportEnum = Field(description="传输协议")
    command: Optional[str] = Field(
        default=None,
        description="启动命令（stdio 模式）"
    )
    url: Optional[str] = Field(
        default=None,
        description="连接 URL（sse 模式）"
    )
    env: Dict[str, str] = Field(
        default_factory=dict,
        description="环境变量"
    )
    timeout_seconds: int = Field(default=60, ge=5, le=600)
    enabled: bool = Field(default=True)

    @model_validator(mode="after")
    def validate_transport_config(self) -> "MCPServerCreateRequest":
        if self.transport == TransportEnum.STDIO and not self.command:
            raise ValueError("'command' is required for stdio transport")
        if self.transport == TransportEnum.SSE and not self.url:
            raise ValueError("'url' is required for sse transport")
        return self


class MCPServerResponse(OmicsHubBaseSchema):
    """MCP Server 响应"""
    id: str
    name: str
    description: Optional[str]
    transport: TransportEnum
    status: ServerStatusEnum
    enabled: bool
    timeout_seconds: int
    last_heartbeat_at: Optional[datetime]
    created_at: datetime


class MCPServerListItem(MCPServerResponse):
    """MCP Server 列表项"""
    tool_count: int = Field(description="注册的工具数量")


class MCPServerDetailResponse(MCPServerResponse):
    """MCP Server 详情"""
    command: Optional[str]
    url: Optional[str]
    env: Dict[str, str]
    tools: List["MCPToolInfo"] = Field(default_factory=list)
    error_log: Optional[str] = Field(default=None)


class MCPToolInfo(OmicsHubBaseSchema):
    """MCP 工具信息"""
    name: str = Field(description="工具名")
    description: Optional[str]
    server_id: str
    server_name: str
    input_schema: dict = Field(description="工具输入参数的 JSON Schema")


class MCPInvokeRequest(OmicsHubBaseSchema):
    """调用 MCP 工具请求"""
    server_id: str
    tool_name: str = Field(..., min_length=1)
    arguments: Dict[str, Any] = Field(default_factory=dict, description="工具参数")
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=300)


class MCPInvokeResponse(OmicsHubBaseSchema):
    """MCP 工具调用响应"""
    server_id: str
    tool_name: str
    success: bool
    result: Any = Field(description="工具返回结果")
    execution_time_ms: int
    error_message: Optional[str] = Field(default=None)


class HealthCheckResponse(OmicsHubBaseSchema):
    """健康检查响应"""
    server_id: str
    status: ServerStatusEnum
    latency_ms: Optional[int]
    tool_count: int
    last_error: Optional[str]
    checked_at: datetime
```

---

## 5. WebSocket 事件协议设计

WebSocket 用于三个场景：任务实时监控、AI 对话、全局通知。所有消息采用统一的 JSON 格式。

### 5.1 统一消息格式

```json
{
  "type": "event_type",
  "timestamp": "2025-01-01T12:00:00.000Z",
  "payload": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 事件类型标识符（小写 + 点号分隔的命名空间） |
| `timestamp` | string | ISO 8601 UTC 时间戳 |
| `payload` | object | 事件载荷（根据事件类型不同而不同） |

---

### 5.2 WebSocket 连接端点

| 端点 | 认证 | 用途 | 连接限制 |
|------|------|------|----------|
| `/ws/v1/tasks/{task_id}` | JWT (Query Param) | 任务状态/日志/进度实时监控 | 每任务最多 5 个并发连接 |
| `/ws/v1/chat/{session_id}` | JWT (Query Param) | AI 对话实时消息 | 每会话最多 2 个并发连接 |
| `/ws/v1/notifications` | JWT (Query Param) | 全局通知推送 | 每用户最多 3 个并发连接 |

**JWT 传递方式**：WebSocket 连接时通过 Query 参数传递 Token：
```
wss://omicshub.hzau.edu.cn/ws/v1/tasks/{task_id}?token=eyJhbGciOiJIUzI1NiIs...
```

---

### 5.3 任务监控 WebSocket (`/ws/v1/tasks/{task_id}`)

#### 5.3.1 服务器 → 客户端事件

```python
# ============ task.status_changed ============
# 任务状态发生变更时推送

{
  "type": "task.status_changed",
  "timestamp": "2025-01-15T08:30:00.000Z",
  "payload": {
    "task_id": "task-uuid-123",
    "previous_status": "queued",
    "current_status": "running",
    "changed_at": "2025-01-15T08:30:00.000Z"
  }
}

# ============ task.progress_updated ============
# 执行进度更新（从 Snakemake stdout 解析）

{
  "type": "task.progress_updated",
  "timestamp": "2025-01-15T08:35:12.000Z",
  "payload": {
    "task_id": "task-uuid-123",
    "percent": 45,
    "current_step": "star_align",
    "step_index": 3,
    "total_steps": 8,
    "message": "3 of 8 steps (45%) done",
    "eta_seconds": 600
  }
}

# ============ task.log_output ============
# 实时日志输出（逐行或按块推送）

{
  "type": "task.log_output",
  "timestamp": "2025-01-15T08:35:12.500Z",
  "payload": {
    "task_id": "task-uuid-123",
    "chunk": "[2025-01-15T08:35:12] Rule star_align: input: samples/sample_001.fastq",
    "is_stderr": false,
    "level": "INFO",
    "step": "star_align"
  }
}

# ============ task.step_changed ============
# 分析步骤切换时推送

{
  "type": "task.step_changed",
  "timestamp": "2025-01-15T08:40:00.000Z",
  "payload": {
    "task_id": "task-uuid-123",
    "previous_step": "fastqc",
    "current_step": "star_align",
    "step_index": 3,
    "total_steps": 8,
    "step_description": "RNA-seq reads alignment using STAR"
  }
}

# ============ task.completed ============
# 任务完成（成功/失败/取消）时推送

{
  "type": "task.completed",
  "timestamp": "2025-01-15T09:15:00.000Z",
  "payload": {
    "task_id": "task-uuid-123",
    "status": "success",
    "results_summary": {
      "total_time_seconds": 2700,
      "steps_completed": 8,
      "result_files_count": 15,
      "peak_memory_gb": 32.5
    },
    "result_files": [
      {"path": "results/gene_counts.csv", "size": 1048576, "type": "csv"},
      {"path": "results/deg_volcano.png", "size": 524288, "type": "png"},
      {"path": "results/report.html", "size": 2097152, "type": "html"}
    ],
    "error_message": null
  }
}
```

#### 5.3.2 客户端 → 服务器消息

```python
# ============ task.subscribe ============
# 客户端连接后发送订阅消息（可选，也可自动订阅）

{
  "type": "task.subscribe",
  "payload": {
    "task_id": "task-uuid-123",
    "subscribe_logs": true,
    "subscribe_progress": true
  }
}

# ============ task.unsubscribe ============
# 取消订阅（不再接收推送，但连接保持）

{
  "type": "task.unsubscribe",
  "payload": {
    "task_id": "task-uuid-123"
  }
}

# ============ task.ping ============
# 心跳保活

{
  "type": "task.ping",
  "timestamp": "2025-01-15T08:30:00.000Z"
}
```

**服务器 pong 响应**：
```json
{
  "type": "task.pong",
  "timestamp": "2025-01-15T08:30:00.100Z"
}
```

---

### 5.4 AI 对话 WebSocket (`/ws/v1/chat/{session_id}`)

#### 5.4.1 服务器 → 客户端事件

```python
# ============ chat.message_chunk ============
# AI 回复的流式文本片段

{
  "type": "chat.message_chunk",
  "timestamp": "2025-01-15T10:20:05.200Z",
  "payload": {
    "session_id": "session-uuid-456",
    "message_id": "msg-uuid-789",
    "role": "assistant",
    "delta": "根据你的样本数据",
    "finish_reason": null
  }
}

# 最后一条 chunk，finish_reason 标记结束原因
{
  "type": "chat.message_chunk",
  "timestamp": "2025-01-15T10:20:08.000Z",
  "payload": {
    "session_id": "session-uuid-456",
    "message_id": "msg-uuid-789",
    "role": "assistant",
    "delta": "",
    "finish_reason": "stop"
  }
}

# ============ chat.tool_call_request ============
# AI 请求调用工具（需用户确认）

{
  "type": "chat.tool_call_request",
  "timestamp": "2025-01-15T10:22:00.000Z",
  "payload": {
    "session_id": "session-uuid-456",
    "message_id": "msg-uuid-790",
    "call_id": "call_abc123",
    "tool_name": "submit_task",
    "tool_display_name": "提交分析任务",
    "description": "AI 想要为你提交一个 RNA-Seq 差异表达分析任务",
    "arguments": {
      "flow_id": "f1a2b3c4-...",
      "name": "RNA-Seq DEG 分析",
      "parameters": {
        "genome": "Arabidopsis_thaliana.TAIR10",
        "samples": ["sample_001", "sample_002"]
      }
    },
    "editable_arguments": ["name"]
  }
}

# ============ chat.tool_result ============
# 工具（平台内部功能）执行结果

{
  "type": "chat.tool_result",
  "timestamp": "2025-01-15T10:22:15.000Z",
  "payload": {
    "session_id": "session-uuid-456",
    "call_id": "call_abc123",
    "tool_name": "submit_task",
    "success": true,
    "result": {
      "task_id": "task-uuid-999",
      "status": "queued",
      "message": "任务已成功提交，ID: task-uuid-999"
    }
  }
}

# ============ chat.mcp_result ============
# MCP 工具（外部服务）调用结果

{
  "type": "chat.mcp_result",
  "timestamp": "2025-01-15T10:25:00.000Z",
  "payload": {
    "session_id": "session-uuid-456",
    "call_id": "call_def456",
    "server_name": "文献检索 MCP",
    "tool_name": "search_pubmed",
    "success": true,
    "render_type": "table",
    "result": {
      "columns": ["title", "authors", "journal", "year", "pmid"],
      "rows": [
        ["Salt stress response in Arabidopsis...", "Zhang et al.", "Plant Cell", 2024, "38012345"]
      ]
    }
  }
}

# ============ chat.error ============
# 对话过程中的错误

{
  "type": "chat.error",
  "timestamp": "2025-01-15T10:30:00.000Z",
  "payload": {
    "session_id": "session-uuid-456",
    "error_code": "MODEL_TIMEOUT",
    "message": "AI 模型响应超时，请重试",
    "recoverable": true
  }
}
```

#### 5.4.2 客户端 → 服务器消息

```python
# ============ chat.send_message ============
# 用户发送消息（支持文本 + 上下文覆盖）

{
  "type": "chat.send_message",
  "payload": {
    "session_id": "session-uuid-456",
    "content": "帮我查看 task-uuid-123 的分析结果",
    "context_override": {
      "current_task_id": "task-uuid-123"
    }
  }
}

# ============ chat.confirm_tool ============
# 用户确认/拒绝工具调用

{
  "type": "chat.confirm_tool",
  "payload": {
    "session_id": "session-uuid-456",
    "call_id": "call_abc123",
    "confirmed": true,
    "argument_overrides": {
      "name": "用户修改后的任务名称"
    }
  }
}

# 拒绝示例
{
  "type": "chat.confirm_tool",
  "payload": {
    "session_id": "session-uuid-456",
    "call_id": "call_abc123",
    "confirmed": false,
    "reason": "我想修改样本选择"
  }
}

# ============ chat.ping ============
# 心跳保活

{
  "type": "chat.ping",
  "timestamp": "2025-01-15T10:20:00.000Z"
}
```

---

### 5.5 全局通知 WebSocket (`/ws/v1/notifications`)

#### 5.5.1 服务器 → 客户端事件

```python
# ============ notification.task_status ============
# 用户任务状态变更通知（跨所有任务聚合推送）

{
  "type": "notification.task_status",
  "timestamp": "2025-01-15T09:15:00.000Z",
  "payload": {
    "task_id": "task-uuid-123",
    "task_name": "RNA-Seq 差异表达分析",
    "status": "success",
    "message": "任务已完成，点击查看结果",
    "link": "/tasks/task-uuid-123"
  }
}

# ============ notification.system ============
# 系统级通知

{
  "type": "notification.system",
  "timestamp": "2025-01-15T12:00:00.000Z",
  "payload": {
    "level": "info",
    "title": "系统维护通知",
    "message": "系统将于今晚 22:00 进行例行维护，预计持续 30 分钟",
    "dismissible": true,
    "expires_at": "2025-01-15T22:30:00.000Z"
  }
}

# ============ notification.mcp_status ============
# MCP Server 状态变更通知

{
  "type": "notification.mcp_status",
  "timestamp": "2025-01-15T14:00:00.000Z",
  "payload": {
    "server_id": "mcp-server-uuid",
    "server_name": "文献检索 MCP",
    "previous_status": "online",
    "current_status": "offline",
    "message": "MCP Server 连接断开，AI 文献检索功能暂时不可用"
  }
}
```

---

### 5.6 WebSocket 连接管理规范

```python
# app/api/ws/task_ws.py
from fastapi import WebSocket, WebSocketDisconnect, Query, Depends
from typing import Optional
import asyncio
import json


class TaskWebSocketManager:
    """任务 WebSocket 连接管理器"""

    def __init__(self):
        # task_id -> set[WebSocket] 映射
        self._connections: dict[str, set[WebSocket]] = {}
        self._max_connections_per_task = 5

    async def connect(
        self,
        websocket: WebSocket,
        task_id: str,
        token: str
    ) -> bool:
        """
        建立 WebSocket 连接。
        返回 True 表示连接成功，False 表示被拒绝。
        """
        # 1. 验证 JWT Token
        try:
            user = await self._authenticate(token)
        except Exception:
            await websocket.close(code=4001, reason="Authentication failed")
            return False

        # 2. 校验任务存在且用户有权限
        task = await self._get_task(task_id)
        if not task or task.user_id != user.id:
            await websocket.close(code=4004, reason="Task not found or access denied")
            return False

        # 3. 检查连接数限制
        existing = self._connections.get(task_id, set())
        if len(existing) >= self._max_connections_per_task:
            await websocket.close(code=4008, reason="Too many connections for this task")
            return False

        # 4. 接受连接
        await websocket.accept()
        if task_id not in self._connections:
            self._connections[task_id] = set()
        self._connections[task_id].add(websocket)

        # 5. 发送初始状态
        await self._send_initial_state(websocket, task)

        return True

    async def disconnect(self, websocket: WebSocket, task_id: str):
        """断开连接清理"""
        if task_id in self._connections:
            self._connections[task_id].discard(websocket)
            if not self._connections[task_id]:
                del self._connections[task_id]

    async def broadcast(self, task_id: str, message: dict):
        """向任务的所有连接广播消息"""
        if task_id not in self._connections:
            return

        dead_connections = set()
        for ws in self._connections[task_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.add(ws)

        # 清理死亡连接
        for ws in dead_connections:
            await self.disconnect(ws, task_id)

    async def _send_initial_state(self, websocket: WebSocket, task: "Task"):
        """新连接时推送当前任务状态"""
        await websocket.send_json({
            "type": "task.status_changed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "task_id": str(task.id),
                "current_status": task.status,
                "progress_percent": task.progress_percent,
                "current_step": task.current_step
            }
        })


# 全局管理器实例
task_ws_manager = TaskWebSocketManager()


# ============ FastAPI WebSocket 路由 ============

from fastapi import APIRouter
ws_router = APIRouter()

@ws_router.websocket("ws/v1/tasks/{task_id}")
async def task_websocket(
    websocket: WebSocket,
    task_id: str,
    token: str = Query(..., description="JWT Token")
):
    """任务实时监控 WebSocket 端点"""
    connected = await task_ws_manager.connect(websocket, task_id, token)
    if not connected:
        return

    try:
        while True:
            # 接收客户端消息（心跳、订阅控制）
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "task.ping":
                    await websocket.send_json({
                        "type": "task.pong",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                elif msg_type == "task.subscribe":
                    # 处理订阅配置变更
                    pass
                elif msg_type == "task.unsubscribe":
                    # 处理取消订阅
                    pass
                else:
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"message": f"Unknown message type: {msg_type}"}
                    })
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "payload": {"message": "Invalid JSON"}
                })

    except WebSocketDisconnect:
        await task_ws_manager.disconnect(websocket, task_id)
    except Exception as e:
        await task_ws_manager.disconnect(websocket, task_id)
```

---

## 6. Snakemake 进度解析说明

### 6.1 Snakemake 标准输出格式

Snakemake 在执行过程中向 stdout 输出进度信息，典型格式如下：

```
Building DAG of jobs...
Using shell: /usr/bin/bash
Provided cores: 8
Rules claiming more threads will be scaled down.
Job stats:
job                 count    min threads    max threads
----------------  -------  -------------  -------------
all                     1              1              1
fastqc                  3              1              1
star_align              3              1              1
feature_counts          3              1              1
deseq2_analysis         1              1              1
multiqc                 1              1              1
total                  12              1              1

Select jobs to execute...
Execute 3 jobs...

[Fri Jan 10 08:30:00 2025]
rule fastqc:
    input: data/sample_001.fastq
    output: results/fastqc/sample_001_fastqc.html
    jobid: 1
    reason: Missing output files
    wildcards: sample=sample_001
    resources: tmpdir=/tmp

3 of 12 steps (25%) done

[Fri Jan 10 08:32:15 2025]
rule star_align:
    input: data/sample_001.fastq, index/STAR
    output: results/align/sample_001.bam
    jobid: 4

6 of 12 steps (50%) done

[Fri Jan 10 08:45:30 2025]
Finished job 10.
12 of 12 steps (100%) done
Complete log: .snakemake/log/2025-01-10T083000.snakemake.log
```

### 6.2 进度正则表达式提取

```python
import re
from dataclasses import dataclass
from typing import Optional, Pattern


@dataclass
class SnakemakeProgress:
    """解析后的 Snakemake 进度信息"""
    current_step: int      # 当前完成的步数
    total_steps: int       # 总步数
    percent: int           # 完成百分比
    raw_message: str       # 原始日志行


class SnakemakeProgressParser:
    """Snakemake 进度解析器"""

    # 核心进度正则：匹配 "X of Y steps (Z%) done"
    PROGRESS_PATTERN: Pattern = re.compile(
        r"^(\d+)\s+of\s+(\d+)\s+steps\s+\((\d+)%\)\s+done",
        re.IGNORECASE
    )

    # 规则开始正则：匹配 "rule <rule_name>:"
    RULE_START_PATTERN: Pattern = re.compile(
        r"^rule\s+(\w+):",
        re.IGNORECASE
    )

    # 任务完成正则：匹配 "Finished job N."
    JOB_FINISHED_PATTERN: Pattern = re.compile(
        r"^Finished job\s+(\d+)\."
    )

    # DAG 构建完成正则
    DAG_READY_PATTERN: Pattern = re.compile(
        r"^Building DAG of jobs\.\.\.\s*done"
    )

    @classmethod
    def parse_progress(cls, log_line: str) -> Optional[SnakemakeProgress]:
        """
        从单行日志中解析进度信息。

        Args:
            log_line: Snakemake 输出的一行日志

        Returns:
            SnakemakeProgress 对象，如果不匹配则返回 None

        Example:
            >>> parser = SnakemakeProgressParser()
            >>> result = parser.parse_progress("3 of 12 steps (25%) done")
            >>> print(result)
            SnakemakeProgress(current_step=3, total_steps=12, percent=25, raw_message="3 of 12 steps (25%) done")
        """
        match = cls.PROGRESS_PATTERN.search(log_line.strip())
        if not match:
            return None

        current = int(match.group(1))
        total = int(match.group(2))
        percent = int(match.group(3))

        return SnakemakeProgress(
            current_step=current,
            total_steps=total,
            percent=percent,
            raw_message=log_line.strip()
        )

    @classmethod
    def extract_rule_name(cls, log_line: str) -> Optional[str]:
        """从日志行中提取正在执行的规则名"""
        match = cls.RULE_START_PATTERN.match(log_line.strip())
        return match.group(1) if match else None

    @classmethod
    def is_job_finished(cls, log_line: str) -> bool:
        """判断是否为任务完成行"""
        return bool(cls.JOB_FINISHED_PATTERN.match(log_line.strip()))

    @classmethod
    def is_dag_ready(cls, log_line: str) -> bool:
        """判断 DAG 是否构建完成"""
        return bool(cls.DAG_READY_PATTERN.match(log_line.strip()))
```

### 6.3 进度解析到 WebSocket 事件映射

```python
from datetime import datetime, timezone


class ProgressEventMapper:
    """将 Snakemake 日志解析结果映射为 WebSocket 事件"""

    def __init__(self, task_ws_manager: TaskWebSocketManager):
        self.ws_manager = task_ws_manager
        self._current_rule: Optional[str] = None

    async def process_log_line(self, task_id: str, log_line: str, is_stderr: bool = False):
        """
        处理单条日志行，解析进度并推送 WebSocket 事件。

        处理流程：
        1. 尝试解析进度信息
        2. 尝试提取规则名
        3. 构建对应的事件并广播
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # 1. 推送日志输出事件（原始日志始终推送）
        log_event = {
            "type": "task.log_output",
            "timestamp": timestamp,
            "payload": {
                "task_id": task_id,
                "chunk": log_line,
                "is_stderr": is_stderr,
                "level": "ERROR" if is_stderr else "INFO",
                "step": self._current_rule
            }
        }
        await self.ws_manager.broadcast(task_id, log_event)

        # 2. 解析进度信息
        progress = SnakemakeProgressParser.parse_progress(log_line)
        if progress:
            progress_event = {
                "type": "task.progress_updated",
                "timestamp": timestamp,
                "payload": {
                    "task_id": task_id,
                    "percent": progress.percent,
                    "current_step": self._current_rule or "unknown",
                    "step_index": progress.current_step,
                    "total_steps": progress.total_steps,
                    "message": progress.raw_message,
                    "eta_seconds": None  # 可由历史数据估算
                }
            }
            await self.ws_manager.broadcast(task_id, progress_event)

        # 3. 提取规则名（步骤变更）
        rule_name = SnakemakeProgressParser.extract_rule_name(log_line)
        if rule_name and rule_name != self._current_rule:
            previous_rule = self._current_rule
            self._current_rule = rule_name

            step_event = {
                "type": "task.step_changed",
                "timestamp": timestamp,
                "payload": {
                    "task_id": task_id,
                    "previous_step": previous_rule,
                    "current_step": rule_name,
                    "step_index": progress.current_step if progress else 0,
                    "total_steps": progress.total_steps if progress else 0,
                    "step_description": f"Executing rule: {rule_name}"
                }
            }
            await self.ws_manager.broadcast(task_id, step_event)

        # 4. 检测 DAG 就绪（任务从 PENDING 变为 RUNNING）
        if SnakemakeProgressParser.is_dag_ready(log_line):
            status_event = {
                "type": "task.status_changed",
                "timestamp": timestamp,
                "payload": {
                    "task_id": task_id,
                    "previous_status": "queued",
                    "current_status": "running",
                    "changed_at": timestamp
                }
            }
            await self.ws_manager.broadcast(task_id, status_event)
```

### 6.4 进度解析时序图

```mermaid
sequenceDiagram
    participant S as Snakemake 进程
    participant C as Celery Worker
    participant P as ProgressEventMapper
    participant R as Redis Pub/Sub
    participant W as WebSocket 服务
    participant B as 浏览器前端

    S->>C: stdout: "Building DAG of jobs..."
    S->>C: stdout: "3 of 12 steps (25%) done"
    C->>P: process_log_line()
    P->>P: parse_progress() → (3, 12, 25%)
    P->>R: PUBLISH task:{task_id}:progress
    R->>W: SUBSCRIBE 收到消息
    W->>B: task.progress_updated 事件
    W->>B: task.log_output 事件

    S->>C: stdout: "rule star_align:"
    C->>P: process_log_line()
    P->>P: extract_rule_name() → "star_align"
    P->>R: PUBLISH task:{task_id}:step_changed
    R->>W: SUBSCRIBE 收到消息
    W->>B: task.step_changed 事件

    S->>C: stdout: "12 of 12 steps (100%) done"
    C->>P: process_log_line()
    P->>R: PUBLISH task:{task_id}:completed
    R->>W: SUBSCRIBE 收到消息
    W->>B: task.completed 事件
```

### 6.5 Celery Worker 集成代码

```python
# app/tasks/snakemake_runner.py
import asyncio
import subprocess
from celery import shared_task
from datetime import datetime, timezone


@shared_task(bind=True, max_retries=2)
def run_snakemake_task(self, task_id: str, work_dir: str, snakefile: str, config: dict):
    """
    Celery 任务：执行 Snakemake 流程。
    stdout/stderr 实时解析并推送进度。
    """
    from app.api.ws.task_ws import task_ws_manager
    from app.services.task_service import TaskService

    mapper = ProgressEventMapper(task_ws_manager)

    # 构建 Snakemake 命令
    cmd = [
        "snakemake",
        "--snakefile", snakefile,
        "--directory", work_dir,
        "--configfile", f"{work_dir}/config.yaml",
        "--cores", str(config.get("cores", 4)),
        "--use-conda",
        "--printshellcmds",
        "--reason",
        "--latency-wait", "60",
    ]

    # 启动子进程
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # 合并 stderr 到 stdout
        text=True,
        bufsize=1,  # 行缓冲
        cwd=work_dir
    )

    # 逐行读取输出
    for line in process.stdout:
        line = line.rstrip('\n')

        # 异步推送进度事件
        asyncio.run(mapper.process_log_line(
            task_id=task_id,
            log_line=line,
            is_stderr=False
        ))

    # 等待进程结束
    exit_code = process.wait()

    # 根据退出码判断结果
    if exit_code == 0:
        # 任务成功：调用内部回调
        asyncio.run(TaskService.on_task_completed(
            task_id=task_id,
            status="success"
        ))
    else:
        # 任务失败
        asyncio.run(TaskService.on_task_completed(
            task_id=task_id,
            status="failed",
            error_message=f"Snakemake exited with code {exit_code}"
        ))
        raise self.retry(countdown=60)
```

---

## 附录：完整路由汇总表

### A.1 REST API 路由总览

| 域 | 前缀 | 路由数 | 核心接口 |
|------|------|--------|----------|
| Authentication | `/api/v1/auth` | 4 | `POST /login`, `POST /register` |
| Users | `/api/v1/users` | 4 | `GET /`, `GET /{id}`, `PUT /{id}` |
| Projects | `/api/v1/projects` | 7 | `POST /`, `GET /{id}/samples`, `POST /{id}/upload` |
| Flows | `/api/v1/flows` | 7 | `GET /`, `GET /{id}/schema`, `POST /` |
| Tasks | `/api/v1/tasks` | 8 | `POST /` (核心), `GET /{id}/logs`, `GET /{id}/preview` |
| AI Chat | `/api/v1/chat` | 7 | `POST /chat` (SSE), `POST /tool-confirm` |
| MCP | `/api/v1/mcp` | 7 | `POST /servers`, `POST /invoke` |
| Internal | `/internal` | 2 | `POST /callback/task-complete` |
| **合计** | | **46** | |

### A.2 WebSocket 端点总览

| 端点 | 路径模式 | 方向 | 主要事件 |
|------|----------|------|----------|
| 任务监控 | `/ws/v1/tasks/{task_id}` | 双向 | `task.*` 系列事件 |
| AI 对话 | `/ws/v1/chat/{session_id}` | 双向 | `chat.*` 系列事件 |
| 全局通知 | `/ws/v1/notifications` | 服务器→客户端 | `notification.*` 系列事件 |

### A.3 状态码约定

| HTTP 状态码 | 业务码 | 含义 |
|-------------|--------|------|
| 200 | 200 | 成功 |
| 200 | 201 | 创建成功 |
| 200 | 400 | 业务逻辑错误 |
| 200 | 401 | 未认证 / Token 过期 |
| 200 | 403 | 权限不足 |
| 200 | 404 | 资源不存在 |
| 200 | 409 | 资源冲突 |
| 200 | 422 | 参数校验失败 |
| 200 | 500 | 服务器内部错误 |

> **设计说明**：所有 HTTP 响应的状态码统一返回 200，实际的业务状态通过 ResponseModel 的 `code` 字段表达。这种设计简化了前端的错误处理逻辑——无需区分 HTTP 状态码和业务码，统一从响应体中读取即可。

---

> **文档结束**  
> 本文档定义了 OmicsHub 平台完整的 REST API 接口（46 个端点）和 WebSocket 实时通信协议（3 个端点、20+ 事件类型），所有 DTO 模型均使用 Pydantic v2 严格类型定义，配合 `field_validator` 和 `model_validator` 进行业务级校验。


---

# 6.4 OmicsHub YAML 配置规范与动态表单架构

> 本文档定义 OmicsHub 分析流程的 YAML 配置规范、Pydantic v2 数据模型、动态表单渲染架构及前后端协同校验策略。

---

## 目录

1. [Pydantic Model 定义](#1-pydantic-model-定义)
2. [完整 YAML 配置示例](#2-完整-yaml-配置示例)
3. [参数联动与条件渲染设计](#3-参数联动与条件渲染设计)
4. [前后端协同校验策略](#4-前后端协同校验策略)
5. [动态表单渲染架构](#5-动态表单渲染架构)
6. [JSON Schema 导出](#6-json-schema-导出)

---

## 1. Pydantic Model 定义

### 1.1 完整 Python 模型代码

以下所有模型使用 **Pydantic v2** 编写，可直接用于 FastAPI 请求体校验。

```python
"""
OmicsHub Flow Configuration Schema - Pydantic v2 Models
完整定义分析流程配置的声明式数据结构
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# ============================================================
# 1. 枚举定义
# ============================================================

class ParameterTypeEnum(str, Enum):
    """参数类型枚举 — 前端据此选择渲染组件"""
    STRING = "string"      # 文本输入框
    INT = "int"            # 整数输入框 / 步进器
    FLOAT = "float"        # 浮点数输入框 / 滑块
    SELECT = "select"      # 下拉选择（单/多选）
    FILE = "file"          # 文件上传
    BOOLEAN = "boolean"    # 开关 / 复选框
    GROUP = "group"        # 可重复参数组（动态增减）
    SECTION = "section"    # 折叠区域（高级参数）


class ConditionOperatorEnum(str, Enum):
    """条件运算符枚举"""
    EQ = "eq"              # 等于
    NE = "ne"              # 不等于
    GT = "gt"              # 大于
    LT = "lt"              # 小于
    GTE = "gte"            # 大于等于
    LTE = "lte"            # 小于等于
    IN = "in"              # 包含于（value 为列表）
    NOT_IN = "not_in"      # 不包含于
    CONTAINS = "contains"  # 包含（字符串或列表）
    EXISTS = "exists"      # 字段存在且非空
    REGEX = "regex"        # 正则匹配


class FileAcceptType(str, Enum):
    """文件上传接受的 MIME 类型分组"""
    FASTQ = ".fastq,.fastq.gz,.fq,.fq.gz"
    BAM = ".bam"
    VCF = ".vcf,.vcf.gz"
    GTF = ".gtf,.gff,.gff3"
    CSV = ".csv,.tsv,.txt"
    ANY = "*"


# ============================================================
# 2. 配置子模型（类型特定属性）
# ============================================================

class SelectOption(BaseModel):
    """下拉选项定义"""
    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., description="显示标签")
    value: Any = Field(..., description="选项值")
    help_text: str = Field(default="", description="选项说明提示")


class StringConfig(BaseModel):
    """STRING 类型专属配置"""
    model_config = ConfigDict(extra="forbid")

    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    regex_pattern: str | None = Field(default=None, description="正则校验模式")
    multiline: bool = Field(default=False, description="是否多行文本")
    rows: int = Field(default=3, ge=1, description="多行文本行数")


class NumberConfig(BaseModel):
    """INT / FLOAT 类型专属配置"""
    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None
    step: float = 1.0
    use_slider: bool = Field(default=False, description="是否使用滑块组件")
    slider_marks: dict[str, str] | None = None
    precision: int = Field(default=2, ge=0, le=10, description="小数精度(FLOAT)")


class SelectConfig(BaseModel):
    """SELECT 类型专属配置"""
    model_config = ConfigDict(extra="forbid")

    options: list[SelectOption] = Field(default=[], description="选项列表")
    multi: bool = Field(default=False, description="是否多选")
    allow_clear: bool = Field(default=True, description="允许清除")
    searchable: bool = Field(default=True, description="允许搜索")


class FileConfig(BaseModel):
    """FILE 类型专属配置"""
    model_config = ConfigDict(extra="forbid")

    accept: str = Field(default="*", description="接受的文件扩展名，如 .fastq.gz")
    max_size: int | None = Field(default=None, description="最大文件大小（字节）")
    multiple: bool = Field(default=False, description="是否允许多文件")
    directory: bool = Field(default=False, description="是否为目录选择")
    show_file_list: bool = Field(default=True, description="是否显示文件列表")


class GroupConfig(BaseModel):
    """GROUP 类型专属配置 — 可重复参数组"""
    model_config = ConfigDict(extra="forbid")

    min_items: int = Field(default=1, ge=0, description="最少组数")
    max_items: int | None = Field(default=None, ge=1, description="最多组数")
    item_label: str = Field(default="条目", description="单组显示标签")
    add_button_text: str = Field(default="+ 添加", description="添加按钮文案")
    parameters: list[Parameter] = Field(
        default=[], description="组内参数定义（递归）"
    )


class SectionConfig(BaseModel):
    """SECTION 类型专属配置 — 折叠区域"""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="高级设置", description="折叠区域标题")
    default_expanded: bool = Field(default=False, description="默认展开")
    description: str = Field(default="", description="区域说明")
    parameters: list[Parameter] = Field(
        default=[], description="区域内参数定义（递归）"
    )


# ============================================================
# 3. 条件渲染规则（核心）
# ============================================================

class ConditionRule(BaseModel):
    """
    条件渲染规则 — 支持简单条件和复合条件（and / or 嵌套）

    使用方式：
      - 简单条件: ConditionRule(field="aligner", operator="eq", value="STAR")
      - AND 复合: ConditionRule(and_rules=[rule1, rule2])
      - OR 复合:  ConditionRule(or_rules=[rule1, rule2])
      - 混合嵌套: ConditionRule(and_rules=[rule1, ConditionRule(or_rules=[r2, r3])])
    """
    model_config = ConfigDict(extra="forbid")

    field: str | None = Field(default=None, description="依赖的字段名")
    operator: ConditionOperatorEnum | None = Field(
        default=None, description="比较运算符"
    )
    value: Any = Field(default=None, description="比较值")

    # 复合条件支持
    and_rules: list["ConditionRule"] | None = Field(
        default=None, description="AND 复合条件"
    )
    or_rules: list["ConditionRule"] | None = Field(
        default=None, description="OR 复合条件"
    )

    @model_validator(mode="after")
    def validate_condition_structure(self):
        """校验条件结构合法性"""
        has_simple = self.field is not None and self.operator is not None
        has_and = self.and_rules is not None
        has_or = self.or_rules is not None

        if has_simple and (has_and or has_or):
            raise ValueError(
                "简单条件（field+operator）不能与复合条件（and_rules/or_rules）同时使用"
            )
        if not has_simple and not has_and and not has_or:
            raise ValueError(
                "条件规则必须包含简单条件（field+operator）或复合条件（and_rules/or_rules）"
            )
        if has_and and has_or:
            raise ValueError("不能同时设置 and_rules 和 or_rules")
        return self


# ============================================================
# 4. 参数模型（核心）
# ============================================================

class Parameter(BaseModel):
    """
    单个参数定义 — 前端据此渲染表单控件

    设计原则：
      - type 决定使用哪个 _config 子模型
      - condition 决定参数是否显示（前端 v-if / 后端条件校验）
      - name 作为表单值的键名，必须全局唯一
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$", description="参数ID")
    label: str = Field(..., min_length=1, description="显示标签")
    type: ParameterTypeEnum = Field(..., description="参数类型")
    required: bool = Field(default=False, description="是否必填")
    default: Any = Field(default=None, description="默认值")
    help_text: str = Field(default="", description="帮助文本（悬浮提示）")
    placeholder: str | None = Field(default=None, description="占位文本")
    order: int = Field(default=0, description="显示顺序权重（越小越靠前）")

    # 条件渲染规则
    condition: ConditionRule | None = Field(
        default=None, description="条件渲染规则"
    )

    # 类型专属配置（根据 type 选择对应的 config）
    string_config: StringConfig | None = None
    number_config: NumberConfig | None = None
    select_config: SelectConfig | None = None
    file_config: FileConfig | None = None
    group_config: GroupConfig | None = None
    section_config: SectionConfig | None = None

    @model_validator(mode="after")
    def validate_type_specific_config(self):
        """校验类型专属配置的一致性"""
        config_map = {
            ParameterTypeEnum.STRING: ("string_config", StringConfig),
            ParameterTypeEnum.INT: ("number_config", NumberConfig),
            ParameterTypeEnum.FLOAT: ("number_config", NumberConfig),
            ParameterTypeEnum.SELECT: ("select_config", SelectConfig),
            ParameterTypeEnum.FILE: ("file_config", FileConfig),
            ParameterTypeEnum.BOOLEAN: (None, None),  # boolean 无专属配置
            ParameterTypeEnum.GROUP: ("group_config", GroupConfig),
            ParameterTypeEnum.SECTION: ("section_config", SectionConfig),
        }

        expected_attr, _ = config_map.get(self.type, (None, None))

        # 检查是否使用了正确的 config
        all_configs = {
            "string_config": self.string_config,
            "number_config": self.number_config,
            "select_config": self.select_config,
            "file_config": self.file_config,
            "group_config": self.group_config,
            "section_config": self.section_config,
        }

        for attr_name, config_value in all_configs.items():
            if config_value is not None and attr_name != expected_attr:
                raise ValueError(
                    f"type='{self.type.value}' 不应设置 {attr_name}，"
                    f"期望: {expected_attr}"
                )

        # GROUP/SECTION 必须有对应的 config 且包含子参数
        if self.type == ParameterTypeEnum.GROUP:
            if self.group_config is None:
                raise ValueError("type='group' 必须设置 group_config")
            if not self.group_config.parameters:
                raise ValueError("group_config.parameters 不能为空")

        if self.type == ParameterTypeEnum.SECTION:
            if self.section_config is None:
                raise ValueError("type='section' 必须设置 section_config")
            if not self.section_config.parameters:
                raise ValueError("section_config.parameters 不能为空")

        return self

    @field_validator("default")
    @classmethod
    def validate_default_type(cls, v, info):
        """校验 default 值与 type 一致"""
        param_type = info.data.get("type")
        if v is None or param_type is None:
            return v

        type_checks = {
            ParameterTypeEnum.STRING: (str, "string"),
            ParameterTypeEnum.INT: (int, "integer"),
            ParameterTypeEnum.FLOAT: ((int, float), "number"),
            ParameterTypeEnum.BOOLEAN: (bool, "boolean"),
            ParameterTypeEnum.SELECT: (None, "any"),  # select 允许任意类型值
        }

        if param_type in type_checks:
            expected_type, _ = type_checks[param_type]
            if expected_type is not None and not isinstance(v, expected_type):
                raise ValueError(
                    f"type='{param_type.value}' 的 default 必须是 {expected_type}"
                )

        return v


# 解决递归类型引用（GroupConfig / SectionConfig 中包含 Parameter）
ConditionRule.model_rebuild()
GroupConfig.model_rebuild()
SectionConfig.model_rebuild()


# ============================================================
# 5. 执行配置模型
# ============================================================

class ResourcesConfig(BaseModel):
    """计算资源配置"""
    model_config = ConfigDict(extra="forbid")

    cores: int = Field(default=4, ge=1, le=128, description="CPU核心数")
    memory: str = Field(default="8G", pattern=r"^\d+[GMT]B?$", description="内存")
    time: str = Field(
        default="2h", pattern=r"^\d+[smhd]$", description="运行时间限制"
    )


class ExecutionConfig(BaseModel):
    """流程执行配置"""
    model_config = ConfigDict(extra="forbid")

    engine: Literal["snakemake", "nextflow"] = Field(
        default="snakemake", description="执行引擎"
    )
    snakefile: str = Field(
        ..., description="Snakefile 路径（相对于项目根目录）"
    )
    conda_env: str | None = Field(
        default=None, description="Conda 环境名"
    )
    default_resources: ResourcesConfig = Field(
        default_factory=ResourcesConfig, description="默认计算资源"
    )
    sample_sheet_format: Literal["csv", "excel", "json"] = Field(
        default="csv", description="样本表格式"
    )
    extra_args: list[str] = Field(
        default=[], description="额外传给 Snakemake 的参数"
    )


# ============================================================
# 6. 样本表配置模型
# ============================================================

class SampleSheetColumn(BaseModel):
    """样本表列定义"""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$", description="列名")
    required: bool = Field(default=True, description="是否必填")
    type: Literal["string", "int", "float", "boolean"] = Field(
        default="string", description="列数据类型"
    )
    description: str = Field(default="", description="列说明")
    example: str | None = Field(default=None, description="示例值")
    unique: bool = Field(default=False, description="是否唯一")
    allowed_values: list[str] | None = Field(
        default=None, description="允许的枚举值"
    )


class ValidationRule(BaseModel):
    """样本表自定义校验规则"""
    model_config = ConfigDict(extra="forbid")

    type: Literal["unique_combination", "mutual_exclusive", "regex"] = Field(
        ..., description="规则类型"
    )
    columns: list[str] = Field(..., description="涉及的列名")
    message: str = Field(default="校验失败", description="失败提示信息")
    regex_pattern: str | None = Field(default=None, description="正则模式（regex类型）")


class SampleSheetConfig(BaseModel):
    """样本表整体配置"""
    model_config = ConfigDict(extra="forbid")

    columns: list[SampleSheetColumn] = Field(
        ..., min_length=1, description="列定义列表"
    )
    validation_rules: list[ValidationRule] = Field(
        default=[], description="自定义校验规则"
    )


# ============================================================
# 7. 元信息模型
# ============================================================

class FlowMeta(BaseModel):
    """流程元信息"""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ..., pattern=r"^[a-z][a-z0-9_]*$", description="唯一标识符"
    )
    name: str = Field(..., min_length=1, description="显示名称")
    category: str = Field(..., description="分类")
    version: str = Field(
        ..., pattern=r"^\d+\.\d+\.\d+(-\w+)?$", description="语义化版本"
    )
    description: str = Field(..., min_length=1, description="流程描述")
    author: str | None = Field(default=None, description="作者")
    tags: list[str] = Field(default=[], description="标签列表")
    icon: str | None = Field(default=None, description="图标类名")
    docs_url: str | None = Field(default=None, description="文档链接")


# ============================================================
# 8. 顶层模型
# ============================================================

class FlowConfig(BaseModel):
    """完整流程配置 — 顶层模型"""
    model_config = ConfigDict(extra="forbid")

    meta: FlowMeta = Field(..., description="流程元信息")
    parameters: list[Parameter] = Field(
        ..., min_length=1, description="参数定义列表"
    )
    execution: ExecutionConfig = Field(..., description="执行配置")
    sample_sheet: SampleSheetConfig | None = Field(
        default=None, description="样本表配置（如流程需要样本表）"
    )

    @field_validator("parameters")
    @classmethod
    def validate_unique_param_names(cls, v: list[Parameter]):
        """校验参数 name 全局唯一"""
        names = []

        def collect_names(params: list[Parameter], prefix: str = ""):
            for p in params:
                full_name = f"{prefix}{p.name}"
                if full_name in names:
                    raise ValueError(f"参数名 '{full_name}' 重复定义")
                names.append(full_name)

                if p.type == ParameterTypeEnum.GROUP and p.group_config:
                    collect_names(p.group_config.parameters, f"{full_name}[].")
                elif p.type == ParameterTypeEnum.SECTION and p.section_config:
                    collect_names(p.section_config.parameters, f"{full_name}.")

        collect_names(v)
        return v

    @model_validator(mode="after")
    def validate_condition_references(self):
        """校验 condition 中引用的 field 存在于已定义的参数中"""
        all_fields = set()

        def collect_fields(params: list[Parameter]):
            for p in params:
                all_fields.add(p.name)
                if p.type == ParameterTypeEnum.GROUP and p.group_config:
                    collect_fields(p.group_config.parameters)
                elif p.type == ParameterTypeEnum.SECTION and p.section_config:
                    collect_fields(p.section_config.parameters)

        collect_fields(self.parameters)

        def check_rule(rule: ConditionRule | None, path: str):
            if rule is None:
                return
            if rule.field and rule.field not in all_fields:
                raise ValueError(
                    f"参数 '{path}' 的 condition 引用了未定义的字段: '{rule.field}'"
                )
            if rule.and_rules:
                for r in rule.and_rules:
                    check_rule(r, path)
            if rule.or_rules:
                for r in rule.or_rules:
                    check_rule(r, path)

        def check_params(params: list[Parameter], path: str = ""):
            for p in params:
                current_path = f"{path}{p.name}"
                check_rule(p.condition, current_path)
                if p.type == ParameterTypeEnum.GROUP and p.group_config:
                    check_params(p.group_config.parameters, f"{current_path}[].")
                elif p.type == ParameterTypeEnum.SECTION and p.section_config:
                    check_params(p.section_config.parameters, f"{current_path}.")

        check_params(self.parameters)
        return self
```

---

### 1.2 条件规则评估器（后端条件计算逻辑）

```python
"""
条件规则评估器 — 后端根据表单值计算参数是否应显示
"""

import re
from typing import Any

from .models import ConditionOperatorEnum, ConditionRule, ParameterTypeEnum


class ConditionEvaluator:
    """条件规则评估器"""

    @staticmethod
    def evaluate(rule: ConditionRule, form_values: dict[str, Any]) -> bool:
        """
        评估条件规则是否满足

        Args:
            rule: 条件规则
            form_values: 当前表单所有字段的值字典 {field_name: value}

        Returns:
            bool: 条件是否满足
        """
        # 复合条件：AND
        if rule.and_rules is not None:
            return all(
                ConditionEvaluator.evaluate(r, form_values) for r in rule.and_rules
            )

        # 复合条件：OR
        if rule.or_rules is not None:
            return any(
                ConditionEvaluator.evaluate(r, form_values) for r in rule.or_rules
            )

        # 简单条件
        if rule.field is None or rule.operator is None:
            return True

        actual_value = form_values.get(rule.field)

        return ConditionEvaluator._compare(
            actual_value, rule.operator, rule.value
        )

    @staticmethod
    def _compare(actual: Any, operator: ConditionOperatorEnum, expected: Any) -> bool:
        """单次比较运算"""
        op = operator

        if op == ConditionOperatorEnum.EXISTS:
            return actual is not None and actual != ""

        if op == ConditionOperatorEnum.EQ:
            return actual == expected

        if op == ConditionOperatorEnum.NE:
            return actual != expected

        # 数值比较 — 要求 actual 不为 None
        if actual is None:
            return False

        if op == ConditionOperatorEnum.GT:
            return actual > expected
        if op == ConditionOperatorEnum.LT:
            return actual < expected
        if op == ConditionOperatorEnum.GTE:
            return actual >= expected
        if op == ConditionOperatorEnum.LTE:
            return actual <= expected

        if op == ConditionOperatorEnum.IN:
            return actual in expected if expected is not None else False

        if op == ConditionOperatorEnum.NOT_IN:
            return actual not in expected if expected is not None else False

        if op == ConditionOperatorEnum.CONTAINS:
            if isinstance(actual, str):
                return expected in actual
            if isinstance(actual, (list, tuple)):
                return expected in actual
            return False

        if op == ConditionOperatorEnum.REGEX:
            if isinstance(actual, str) and isinstance(expected, str):
                return bool(re.search(expected, actual))
            return False

        return False


class ConditionalValidator:
    """
    条件参数校验器 — 仅校验当前可见（condition满足）的必填参数
    """

    @staticmethod
    def get_visible_params(
        parameters: list[Any],  # list[Parameter]
        form_values: dict[str, Any],
    ) -> list[str]:
        """
        获取当前条件下所有可见参数的名称列表

        返回值中的 GROUP 参数展开为内部参数名（带 [N]. 前缀）
        """
        visible = []

        def check(param: Any, prefix: str = ""):
            full_name = f"{prefix}{param.name}"

            # 检查条件
            if param.condition is not None:
                if not ConditionEvaluator.evaluate(param.condition, form_values):
                    return  # 条件不满足，参数不可见

            visible.append(full_name)

            # 递归处理 GROUP / SECTION
            if param.type == ParameterTypeEnum.GROUP and param.group_config:
                # 获取当前组数量
                group_value = form_values.get(param.name, [])
                num_items = len(group_value) if isinstance(group_value, list) else 1
                num_items = max(num_items, param.group_config.min_items)
                for i in range(num_items):
                    for sub_param in param.group_config.parameters:
                        check(sub_param, f"{full_name}[{i}].")

            elif param.type == ParameterTypeEnum.SECTION and param.section_config:
                for sub_param in param.section_config.parameters:
                    check(sub_param, f"{full_name}.")

        for p in parameters:
            check(p)

        return visible

    @staticmethod
    def validate_required(
        parameters: list[Any],
        form_values: dict[str, Any],
    ) -> list[dict]:
        """
        校验可见的必填参数是否已填写

        Returns:
            list[dict]: 错误列表，每项包含 field 和 message
        """
        errors = []
        visible = set(
            ConditionalValidator.get_visible_params(parameters, form_values)
        )

        def check(param: Any, prefix: str = ""):
            full_name = f"{prefix}{param.name}"

            # 跳过不可见参数
            if full_name not in visible:
                return

            # 检查必填
            if param.required:
                value = form_values.get(param.name)
                if value is None or value == "":
                    errors.append({
                        "field": full_name,
                        "message": f"'{param.label}' 是必填项",
                    })

            # 递归
            if param.type == ParameterTypeEnum.GROUP and param.group_config:
                group_value = form_values.get(param.name, [])
                if isinstance(group_value, list):
                    for i, item in enumerate(group_value):
                        item_prefix = f"{full_name}[{i}]."
                        # 将 item 的值合并到 form_values 中进行子参数检查
                        merged = {**form_values, **{
                            sp.name: item.get(sp.name) for sp in param.group_config.parameters
                        }}
                        for sub_param in param.group_config.parameters:
                            sub_full = f"{item_prefix}{sub_param.name}"
                            if sub_full not in visible:
                                continue
                            if sub_param.required:
                                v = item.get(sub_param.name)
                                if v is None or v == "":
                                    errors.append({
                                        "field": sub_full,
                                        "message": f"'{sub_param.label}' 是必填项",
                                    })

            elif param.type == ParameterTypeEnum.SECTION and param.section_config:
                for sub_param in param.section_config.parameters:
                    check(sub_param, f"{full_name}.")

        for p in parameters:
            check(p)

        return errors
```

---

### 1.3 模型文件结构

```
backend/
  app/
    schemas/
      __init__.py
      enums.py          # 所有枚举定义
      config_models.py  # 基础配置子模型
      condition.py      # 条件规则 + 评估器
      parameter.py      # Parameter 模型
      sample_sheet.py   # SampleSheet 相关模型
      execution.py      # ExecutionConfig + ResourcesConfig
      flow_config.py    # FlowConfig 顶层模型（含 validators）
      json_schema.py    # JSON Schema 导出工具
```

---

## 2. 完整 YAML 配置示例

### 2.1 RNA-seq 差异表达分析流程

```yaml
# ============================================================
# RNA-seq 差异表达分析流程配置
# 展示所有参数类型、条件渲染、可重复 Group、折叠 Section
# ============================================================

meta:
  id: rna_seq
  name: "RNA-seq 差异表达分析"
  category: transcriptomics
  version: "2.1.0"
  description: "基于 STAR + featureCounts + DESeq2 的标准 RNA-seq 差异表达分析流程，支持多组差异比较和高级质控参数。"
  author: "OmicsHub Team"
  tags: ["rnaseq", "differential-expression", "STAR", "DESeq2", "featureCounts"]
  icon: "rna"
  docs_url: "https://docs.omicshub.org/workflows/rna_seq"

parameters:
  # ----------------------------------------------------------
  # 一、基本参数
  # ----------------------------------------------------------
  - name: genome
    label: "参考基因组"
    type: select
    required: true
    default: "hg38"
    help_text: "选择比对使用的参考基因组版本"
    select_config:
      options:
        - label: "人类 GRCh38 (hg38)"
          value: "hg38"
          help_text: "UCSC GRCh38 完整基因组"
        - label: "人类 GRCh37 (hg19)"
          value: "hg19"
          help_text: "UCSC GRCh37 参考基因组"
        - label: "小鼠 GRCm39 (mm39)"
          value: "mm39"
          help_text: "小鼠最新参考基因组"
        - label: "小鼠 mm10"
          value: "mm10"
          help_text: "小鼠 mm10 参考基因组"
      multi: false
      searchable: true

  - name: aligner
    label: "比对工具"
    type: select
    required: true
    default: "STAR"
    help_text: "选择序列比对工具"
    select_config:
      options:
        - label: "STAR (推荐，速度快)"
          value: "STAR"
        - label: "HISAT2 (拼接友好)"
          value: "HISAT2"
        - label: "Bowtie2"
          value: "bowtie2"

  # ---- 条件渲染：仅当 aligner == "STAR" 时显示 ----
  - name: star_index
    label: "STAR 索引路径"
    type: string
    required: true
    default: "/data/ref/hg38/STAR_index"
    help_text: "STAR 基因组索引目录路径（仅 STAR 模式需要）"
    placeholder: "/path/to/STAR_index"
    condition:
      field: "aligner"
      operator: "eq"
      value: "STAR"

  - name: star_threads
    label: "STAR 比对线程数"
    type: int
    required: false
    default: 8
    help_text: "STAR 比对使用的线程数"
    condition:
      field: "aligner"
      operator: "eq"
      value: "STAR"
    number_config:
      min: 1
      max: 64
      step: 1

  # ---- 条件渲染：仅当 aligner == "HISAT2" 时显示 ----
  - name: hisat2_index
    label: "HISAT2 索引前缀"
    type: string
    required: true
    default: "/data/ref/hg38/hisat2_index/genome"
    help_text: "HISAT2 索引文件前缀路径"
    placeholder: "/path/to/hisat2_index/genome"
    condition:
      field: "aligner"
      operator: "eq"
      value: "HISAT2"

  - name: strandness
    label: "链特异性"
    type: select
    required: true
    default: "unstranded"
    help_text: "文库链特异性类型"
    select_config:
      options:
        - label: "非链特异性 (unstranded)"
          value: "unstranded"
        - label: "正向链 (forward)"
          value: "forward"
          help_text: "second-strand synthesis, e.g. TruSeq Stranded"
        - label: "反向链 (reverse)"
          value: "reverse"
          help_text: "first-strand synthesis, e.g. dUTP method"

  # ----------------------------------------------------------
  # 二、差异比较设置（可重复 Group）
  # ----------------------------------------------------------
  - name: comparisons
    label: "差异比较组"
    type: group
    required: true
    help_text: "定义需要比较的分组，每组指定对照组和实验组"
    group_config:
      min_items: 1
      max_items: 10
      item_label: "比较组"
      add_button_text: "+ 添加差异比较组"
      parameters:
        - name: comparison_name
          label: "比较名称"
          type: string
          required: true
          help_text: "为该差异比较命名，如 'Tumor_vs_Normal'"
          placeholder: "Tumor_vs_Normal"
          string_config:
            regex_pattern: "^[A-Za-z][A-Za-z0-9_]*$"

        - name: control_group
          label: "对照组"
          type: string
          required: true
          help_text: "对照组名称（需与样本表中 group 列一致）"
          placeholder: "control"

        - name: treatment_group
          label: "实验组"
          type: string
          required: true
          help_text: "实验组名称（需与样本表中 group 列一致）"
          placeholder: "treatment"

        - name: fdr_threshold
          label: "FDR 阈值"
          type: float
          required: false
          default: 0.05
          help_text: "差异表达基因的 FDR 显著性阈值"
          number_config:
            min: 0.001
            max: 1.0
            step: 0.001
            use_slider: true
            precision: 3

        - name: log2fc_threshold
          label: "log2FC 阈值"
          type: float
          required: false
          default: 1.0
          help_text: "最小 log2 倍数变化阈值"
          number_config:
            min: 0.0
            max: 10.0
            step: 0.5
            use_slider: true

  # ----------------------------------------------------------
  # 三、定量参数
  # ----------------------------------------------------------
  - name: quantifier
    label: "定量工具"
    type: select
    required: true
    default: "featureCounts"
    select_config:
      options:
        - label: "featureCounts"
          value: "featureCounts"
        - label: "HTSeq-count"
          value: "htseq"
        - label: "Salmon (alignment-free)"
          value: "salmon"

  # ---- 复合条件：quantifier == "featureCounts" AND aligner != "bowtie2" ----
  - name: fc_count_multimapping
    label: "允许多重比对计数"
    type: boolean
    required: false
    default: false
    help_text: "featureCounts 是否对多重比对 reads 进行计数分配"
    condition:
      and_rules:
        - field: "quantifier"
          operator: "eq"
          value: "featureCounts"
        - field: "aligner"
          operator: "ne"
          value: "bowtie2"

  - name: gtf_annotation
    label: "GTF 注释文件"
    type: file
    required: true
    help_text: "基因注释 GTF 文件"
    file_config:
      accept: ".gtf,.gtf.gz,.gff3"
      max_size: 536870912   # 512 MB
      multiple: false

  # ----------------------------------------------------------
  # 四、高级参数（折叠 Section）
  # ----------------------------------------------------------
  - name: advanced_params
    label: "高级参数"
    type: section
    section_config:
      title: "高级分析参数"
      default_expanded: false
      description: "包含质控阈值、归一化方法等高级设置，一般无需修改"
      parameters:
        - name: min_read_quality
          label: "最小碱基质量值"
          type: int
          required: false
          default: 20
          help_text: "FastQC 质控最小碱基质量阈值（Phred score）"
          number_config:
            min: 0
            max: 40
            step: 1

        - name: min_read_length
          label: "最小 read 长度"
          type: int
          required: false
          default: 36
          help_text: "过滤后最小 read 长度"
          number_config:
            min: 10
            max: 150
            step: 1

        - name: normalization_method
          label: "归一化方法"
          type: select
          required: false
          default: "rlog"
          help_text: "DESeq2 数据归一化方法"
          select_config:
            options:
              - label: "rlog (推荐)"
                value: "rlog"
              - label: "vst (方差稳定变换)"
                value: "vst"
              - label: "TPM"
                value: "tpm"

        - name: cook_cutoff
          label: "Cook 距离截断值"
          type: float
          required: false
          default: 0.99
          help_text: "DESeq2 离群样本检测 Cook 距离分位数阈值"
          number_config:
            min: 0.5
            max: 1.0
            step: 0.01
            precision: 2

        - name: independent_filtering
          label: "启用独立过滤"
          type: boolean
          required: false
          default: true
          help_text: "DESeq2 独立过滤，提高检测功效"

        - name: batch_correction
          label: "批次效应校正"
          type: select
          required: false
          default: "none"
          help_text: "是否进行批次效应校正"
          select_config:
            options:
              - label: "不进行校正"
                value: "none"
              - label: "ComBat (sva)"
                value: "combat"
              - label: "RUVSeq"
                value: "ruvseq"

        # ---- 条件渲染：仅当 batch_correction != "none" ----
        - name: batch_column
          label: "批次列名"
          type: string
          required: true
          help_text: "样本表中标识批次的列名"
          placeholder: "batch"
          condition:
            field: "batch_correction"
            operator: "ne"
            value: "none"

  # ----------------------------------------------------------
  # 五、资源参数
  # ----------------------------------------------------------
  - name: use_gpu
    label: "使用 GPU 加速"
    type: boolean
    required: false
    default: false
    help_text: "启用 GPU 加速（如支持）"

  # ---- OR 复合条件示例：use_gpu == true OR aligner == "STAR" ----
  - name: max_memory_gb
    label: "最大内存 (GB)"
    type: int
    required: false
    default: 32
    help_text: "流程最大可用内存"
    number_config:
      min: 8
      max: 256
      step: 4

# ============================================================
# 执行配置
# ============================================================
execution:
  engine: snakemake
  snakefile: "workflows/rna_seq/Snakefile"
  conda_env: "rna_seq_env"
  default_resources:
    cores: 8
    memory: "32G"
    time: "4h"
  sample_sheet_format: csv
  extra_args:
    - "--use-conda"
    - "--latency-wait 60"
    - "--rerun-incomplete"

# ============================================================
# 样本表配置
# ============================================================
sample_sheet:
  columns:
    - name: sample_id
      required: true
      type: string
      description: "样本唯一标识符"
      example: "S001_Tumor"
      unique: true

    - name: group
      required: true
      type: string
      description: "分组信息（用于差异比较）"
      example: "Tumor"

    - name: fastq_1
      required: true
      type: string
      description: "R1 FASTQ 文件路径"
      example: "/data/fastq/S001_Tumor_R1.fastq.gz"

    - name: fastq_2
      required: false
      type: string
      description: "R2 FASTQ 文件路径（双端测序）"
      example: "/data/fastq/S001_Tumor_R2.fastq.gz"

    - name: batch
      required: false
      type: string
      description: "批次信息（用于批次效应校正）"
      example: "batch_1"

    - name: replicate
      required: false
      type: int
      description: "生物学重复编号"
      example: "1"

  validation_rules:
    - type: unique_combination
      columns: ["sample_id"]
      message: "sample_id 必须唯一"

    - type: mutual_exclusive
      columns: ["fastq_2"]
      message: "双端测序样本必须提供 R2 文件"
```

---

### 2.2 YAML 示例参数说明

| 参数区域 | 展示内容 | 对应参数类型 |
|---------|---------|------------|
| 基本参数 | genome, aligner, strandness | select |
| 条件渲染 | star_index/star_threads（aligner==STAR）| string, int + condition |
| 条件渲染 | hisat2_index（aligner==HISAT2）| string + condition |
| 可重复组 | comparisons（差异比较）| group |
| 复合条件 | fc_count_multimapping（AND 条件）| boolean + and_rules |
| 文件上传 | gtf_annotation | file |
| 折叠区域 | advanced_params 内含 6 个子参数 | section |
| 嵌套条件 | batch_column（section 内条件参数）| string + condition |
| 布尔开关 | use_gpu, independent_filtering | boolean |
| 数值参数 | max_memory_gb, fdr_threshold, log2fc_threshold | int/float + number_config |

---

## 3. 参数联动与条件渲染设计

### 3.1 条件渲染规则完整说明

#### 3.1.1 运算符语义表

| 运算符 | 语义 | 适用类型 | value 类型 | 示例 |
|-------|------|---------|-----------|------|
| `eq` | 等于 | 任意 | 与字段同类型 | `{"field":"aligner","operator":"eq","value":"STAR"}` |
| `ne` | 不等于 | 任意 | 与字段同类型 | `{"field":"aligner","operator":"ne","value":"bowtie2"}` |
| `gt` | 大于 | int, float | 数值 | `{"field":"fdr","operator":"gt","value":0.01}` |
| `lt` | 小于 | int, float | 数值 | `{"field":"threads","operator":"lt","value":32}` |
| `gte` | 大于等于 | int, float | 数值 | `{"field":"cores","operator":"gte","value":4}` |
| `lte` | 小于等于 | int, float | 数值 | `{"field":"memory","operator":"lte","value":64}` |
| `in` | 包含于 | select(multi) | list | `{"field":"tags","operator":"in","value":["QC","DE"]}` |
| `not_in` | 不包含于 | select(multi) | list | `{"field":"method","operator":"not_in","value":["old"]}` |
| `contains` | 包含 | string, select(multi) | 任意 | `{"field":"genome","operator":"contains","value":"hg"}` |
| `exists` | 存在且非空 | 任意 | 不需要 | `{"field":"batch_column","operator":"exists"}` |
| `regex` | 正则匹配 | string | pattern | `{"field":"sample_id","operator":"regex","value":"^S[0-9]+"}` |

#### 3.1.2 复合条件逻辑

```yaml
# AND 条件 — 所有子条件必须同时满足
condition:
  and_rules:
    - field: "quantifier"
      operator: "eq"
      value: "featureCounts"
    - field: "aligner"
      operator: "ne"
      value: "bowtie2"

# OR 条件 — 任一子条件满足即可
condition:
  or_rules:
    - field: "use_gpu"
      operator: "eq"
      value: true
    - field: "aligner"
      operator: "eq"
      value: "STAR"

# 嵌套条件 — AND 中包含 OR
condition:
  and_rules:
    - field: "batch_correction"
      operator: "ne"
      value: "none"
    - or_rules:
        - field: "tool_version"
          operator: "gte"
          value: "2.0"
        - field: "force_run"
          operator: "eq"
          value: true
```

---

### 3.2 前端条件渲染实现

#### 3.2.1 Vue 3 条件渲染组件

```typescript
// composables/useConditionEvaluator.ts
// 条件规则评估器（前端复刻版）

import { type ConditionRule, type ConditionOperator } from "@/types/schema";

export function useConditionEvaluator() {
  /**
   * 评估条件规则
   */
  function evaluate(
    rule: ConditionRule,
    formValues: Record<string, any>
  ): boolean {
    // 复合条件：AND
    if (rule.and_rules && rule.and_rules.length > 0) {
      return rule.and_rules.every((r) => evaluate(r, formValues));
    }

    // 复合条件：OR
    if (rule.or_rules && rule.or_rules.length > 0) {
      return rule.or_rules.some((r) => evaluate(r, formValues));
    }

    // 简单条件
    if (!rule.field || !rule.operator) return true;

    const actual = formValues[rule.field];
    return compare(actual, rule.operator, rule.value);
  }

  /**
   * 单次比较
   */
  function compare(
    actual: any,
    operator: ConditionOperator,
    expected: any
  ): boolean {
    switch (operator) {
      case "exists":
        return actual !== null && actual !== undefined && actual !== "";
      case "eq":
        return actual === expected;
      case "ne":
        return actual !== expected;
      case "gt":
        return actual !== null && actual > expected;
      case "lt":
        return actual !== null && actual < expected;
      case "gte":
        return actual !== null && actual >= expected;
      case "lte":
        return actual !== null && actual <= expected;
      case "in":
        return Array.isArray(expected) && expected.includes(actual);
      case "not_in":
        return Array.isArray(expected) && !expected.includes(actual);
      case "contains":
        if (typeof actual === "string") return actual.includes(expected);
        if (Array.isArray(actual)) return actual.includes(expected);
        return false;
      case "regex":
        if (typeof actual === "string" && typeof expected === "string") {
          return new RegExp(expected).test(actual);
        }
        return false;
      default:
        return false;
    }
  }

  return { evaluate, compare };
}
```

#### 3.2.2 动态表单渲染组件

```vue
<!-- components/FlowForm.vue -->
<template>
  <n-form
    ref="formRef"
    :model="formValues"
    :rules="activeRules"
    label-placement="left"
    label-width="auto"
  >
    <template v-for="param in sortedParameters" :key="param.name">
      <DynamicFormItem
        v-if="isVisible(param)"
        :parameter="param"
        v-model:value="formValues[param.name]"
        @update:value="onParamChange(param.name, $event)"
      />
    </template>
  </n-form>
</template>

<script setup lang="ts">
import { ref, computed, watch, reactive } from "vue";
import type { Parameter, FlowConfig } from "@/types/schema";
import { useConditionEvaluator } from "@/composables/useConditionEvaluator";
import DynamicFormItem from "./DynamicFormItem.vue";

const props = defineProps<{
  config: FlowConfig;
}>();

const formRef = ref();
const formValues = reactive<Record<string, any>>({});
const { evaluate } = useConditionEvaluator();

// 按 order 排序的参数
const sortedParameters = computed(() =>
  [...props.config.parameters].sort((a, b) => a.order - b.order)
);

// 判断参数是否可见
function isVisible(param: Parameter): boolean {
  if (!param.condition) return true;
  return evaluate(param.condition, formValues);
}

// 收集所有可见参数的规则
const activeRules = computed(() => {
  const rules: Record<string, any> = {};

  function collectRules(params: Parameter[], prefix = "") {
    for (const p of params) {
      const visible = isVisible(p);
      if (!visible) continue;

      if (p.required) {
        rules[`${prefix}${p.name}`] = {
          required: true,
          message: `'${p.label}' 是必填项`,
          trigger: ["blur", "change"],
        };
      }

      // 递归收集 GROUP / SECTION 内规则
      if (p.type === "group" && p.group_config) {
        const arr = (formValues[p.name] as any[]) || [];
        arr.forEach((_, i) => {
          collectRules(p.group_config!.parameters, `${p.name}[${i}].`);
        });
      }
      if (p.type === "section" && p.section_config) {
        collectRules(p.section_config.parameters, `${p.name}.`);
      }
    }
  }

  collectRules(props.config.parameters);
  return rules;
});

// 参数值变化时，触发条件重新评估
function onParamChange(name: string, value: any) {
  formValues[name] = value;
  // 条件依赖已自动通过响应式追踪（formValues 是 reactive 对象）
}

// 收集表单值（提交用）
function collectValues(): Record<string, any> {
  return JSON.parse(JSON.stringify(formValues));
}

defineExpose({
  collectValues,
  validate: () => formRef.value?.validate(),
});
</script>
```

#### 3.2.3 单个动态参数组件映射

```vue
<!-- components/DynamicFormItem.vue -->
<template>
  <n-form-item :label="parameter.label" :path="parameter.name">
    <!-- STRING -->
    <n-input
      v-if="parameter.type === 'string'"
      v-model:value="localValue"
      :placeholder="parameter.placeholder"
      :maxlength="parameter.string_config?.max_length"
      :type="parameter.string_config?.multiline ? 'textarea' : 'text'"
      :rows="parameter.string_config?.rows"
    />

    <!-- INT / FLOAT -->
    <template v-else-if="parameter.type === 'int' || parameter.type === 'float'">
      <n-slider
        v-if="parameter.number_config?.use_slider"
        v-model:value="localValue"
        :min="parameter.number_config.min"
        :max="parameter.number_config.max"
        :step="parameter.number_config.step"
        :marks="parameter.number_config.slider_marks"
      />
      <n-input-number
        v-else
        v-model:value="localValue"
        :min="parameter.number_config?.min"
        :max="parameter.number_config?.max"
        :step="parameter.number_config?.step"
        :precision="parameter.type === 'float' ? parameter.number_config?.precision : 0"
        :placeholder="parameter.placeholder"
      />
    </template>

    <!-- SELECT -->
    <n-select
      v-else-if="parameter.type === 'select'"
      v-model:value="localValue"
      :options="selectOptions"
      :multiple="parameter.select_config?.multi"
      :clearable="parameter.select_config?.allow_clear"
      :filterable="parameter.select_config?.searchable"
      :placeholder="parameter.placeholder || '请选择'"
    />

    <!-- FILE -->
    <n-upload
      v-else-if="parameter.type === 'file'"
      v-model:file-list="fileList"
      :accept="parameter.file_config?.accept"
      :max-size="parameter.file_config?.max_size"
      :multiple="parameter.file_config?.multiple"
      :directory-dnd="parameter.file_config?.directory"
      @update:file-list="onFileChange"
    >
      <n-button>选择文件</n-button>
    </n-upload>

    <!-- BOOLEAN -->
    <n-switch
      v-else-if="parameter.type === 'boolean'"
      v-model:value="localValue"
    />

    <!-- GROUP（可重复） -->
    <RepeatableGroup
      v-else-if="parameter.type === 'group'"
      :config="parameter.group_config!"
      v-model:items="localValue"
    />

    <!-- SECTION（折叠区域） -->
    <CollapsibleSection
      v-else-if="parameter.type === 'section'"
      :config="parameter.section_config!"
      v-model:values="localValue"
    />

    <!-- help_text 提示 -->
    <template #feedback v-if="parameter.help_text">
      <n-tooltip>
        <template #trigger>
          <n-icon><HelpCircleOutline /></n-icon>
        </template>
        {{ parameter.help_text }}
      </n-tooltip>
    </template>
  </n-form-item>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { Parameter } from "@/types/schema";

const props = defineProps<{
  parameter: Parameter;
  value: any;
}>();

const emit = defineEmits<{
  "update:value": [value: any];
}>();

const localValue = computed({
  get: () => props.value,
  set: (v) => emit("update:value", v),
});

// SELECT 选项转换
const selectOptions = computed(() => {
  if (!props.parameter.select_config) return [];
  return props.parameter.select_config.options.map((opt) => ({
    label: opt.label,
    value: opt.value,
    // help 可在 render-option 中展示
  }));
});

// 文件列表
const fileList = computed({
  get: () => (props.value ? [props.value] : []),
  set: (list) => emit("update:value", list?.[0] || null),
});

function onFileChange(list: any[]) {
  emit("update:value", list?.[0] || null);
}
</script>
```

---

### 3.3 可重复 Group 设计

#### 3.3.1 前端渲染（动态增删）

```vue
<!-- components/RepeatableGroup.vue -->
<template>
  <div class="repeatable-group">
    <div
      v-for="(item, index) in items"
      :key="index"
      class="group-item"
    >
      <n-card :title="`${config.item_label} #${index + 1}`" size="small">
        <template #header-extra>
          <n-button
            v-if="items.length > config.min_items"
            text
            type="error"
            @click="removeItem(index)"
          >
            删除
          </n-button>
        </template>

        <!-- 组内参数渲染 -->
        <template v-for="param in config.parameters" :key="param.name">
          <DynamicFormItem
            v-if="isGroupParamVisible(param, item)"
            :parameter="param"
            v-model:value="item[param.name]"
          />
        </template>
      </n-card>
    </div>

    <n-button
      v-if="!config.max_items || items.length < config.max_items"
      dashed
      block
      @click="addItem"
    >
      {{ config.add_button_text }}
    </n-button>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { GroupConfig, Parameter } from "@/types/schema";
import { useConditionEvaluator } from "@/composables/useConditionEvaluator";
import DynamicFormItem from "./DynamicFormItem.vue";

const props = defineProps<{
  config: GroupConfig;
  items: Record<string, any>[];
}>();

const emit = defineEmits<{
  "update:items": [items: Record<string, any>[]];
}>();

const items = computed({
  get: () => props.items,
  set: (v) => emit("update:items", v),
});

const { evaluate } = useConditionEvaluator();

// 创建空条目模板
function createEmptyItem(): Record<string, any> {
  const item: Record<string, any> = {};
  for (const p of props.config.parameters) {
    item[p.name] = p.default ?? null;
  }
  return item;
}

function addItem() {
  if (props.config.max_items && items.value.length >= props.config.max_items) {
    return;
  }
  items.value = [...items.value, createEmptyItem()];
}

function removeItem(index: number) {
  if (items.value.length <= props.config.min_items) return;
  items.value = items.value.filter((_, i) => i !== index);
}

// 组内参数可见性（基于当前组的局部值 + 全局值）
function isGroupParamVisible(param: Parameter, itemValues: Record<string, any>): boolean {
  if (!param.condition) return true;
  // 组内条件评估使用组内值
  return evaluate(param.condition, itemValues);
}
</script>
```

#### 3.3.2 后端数据结构处理

```python
# 可重复 Group 的数据结构示例
{
    "comparisons": [
        {
            "comparison_name": "Tumor_vs_Normal",
            "control_group": "Normal",
            "treatment_group": "Tumor",
            "fdr_threshold": 0.05,
            "log2fc_threshold": 1.0,
        },
        {
            "comparison_name": "Metastatic_vs_Primary",
            "control_group": "Primary",
            "treatment_group": "Metastatic",
            "fdr_threshold": 0.01,
            "log2fc_threshold": 1.5,
        },
    ]
}

# Snakemake config 生成时展开为列表
comparisons = config["comparisons"]  # -> Python list[dict]
```

#### 3.3.3 命名唯一性保证

| 层级 | 命名策略 | 示例 |
|------|---------|------|
| 顶层参数 | 直接 name | `aligner`, `genome` |
| Section 内参数 | section.name + `.` + param.name | `advanced_params.min_read_quality` |
| Group 内参数 | group.name + `[N].` + param.name | `comparisons[0].comparison_name` |

> Pydantic 的 `validate_unique_param_names` validator 在配置加载时递归检查所有层级的命名唯一性。

---

### 3.4 参数联动：数值滑块与输入框双向绑定

```vue
<!-- components/SliderInputPair.vue -->
<!-- 滑块与输入框双向绑定，用于 FLOAT/INT 类型参数 -->
<template>
  <div class="slider-input-pair">
    <n-slider
      v-model:value="localValue"
      :min="config.min"
      :max="config.max"
      :step="config.step"
      :marks="config.slider_marks"
      style="flex: 1"
    />
    <n-input-number
      v-model:value="localValue"
      :min="config.min"
      :max="config.max"
      :step="config.step"
      :precision="precision"
      style="width: 120px; margin-left: 12px"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { NumberConfig } from "@/types/schema";

const props = defineProps<{
  value: number;
  config: NumberConfig;
  isFloat: boolean;
}>();

const emit = defineEmits<{ "update:value": [value: number] }>();

const localValue = computed({
  get: () => props.value,
  set: (v) => emit("update:value", v),
});

const precision = computed(() =>
  props.isFloat ? (props.config.precision ?? 2) : 0
);
</script>

<style scoped>
.slider-input-pair {
  display: flex;
  align-items: center;
}
</style>
```

---

## 4. 前后端协同校验策略

### 4.1 前端校验（JSON Schema）

#### 4.1.1 Pydantic 转 JSON Schema

```python
# schemas/json_schema.py

from pydantic import TypeAdapter

from .flow_config import FlowConfig


def export_json_schema() -> dict:
    """
    导出 FlowConfig 的 JSON Schema (Draft 2020-12)
    供前端组件在编译时导入使用
    """
    adapter = TypeAdapter(FlowConfig)
    return adapter.json_schema()


def export_parameter_schema() -> dict:
    """
    导出 Parameter 的独立 JSON Schema
    供前端动态表单在运行时校验使用
    """
    from .parameter import Parameter
    adapter = TypeAdapter(Parameter)
    return adapter.json_schema()
```

#### 4.1.2 前端 Naive UI Form Rules 生成

```typescript
// utils/schemaToRules.ts
import type { Parameter, StringConfig, NumberConfig } from "@/types/schema";
import type { FormItemRule } from "naive-ui";

/**
 * 将 Parameter 定义转换为 Naive UI 的 FormItemRule[]
 */
export function parameterToRules(param: Parameter): FormItemRule[] {
  const rules: FormItemRule[] = [];

  // 必填校验
  if (param.required) {
    rules.push({
      required: true,
      message: `'${param.label}' 是必填项`,
      trigger: ["blur", "change"],
    });
  }

  // 类型专属校验
  switch (param.type) {
    case "string":
      if (param.string_config) {
        rules.push(...stringRules(param.string_config));
      }
      break;
    case "int":
    case "float":
      if (param.number_config) {
        rules.push(...numberRules(param.number_config, param.type));
      }
      break;
    case "select":
      if (param.select_config?.multi === false && param.select_config?.options) {
        const validValues = param.select_config.options.map((o) => o.value);
        rules.push({
          validator: (_rule: any, value: any) => {
            if (value === null || value === undefined) return true;
            return validValues.includes(value);
          },
          message: `请选择有效的选项`,
          trigger: "change",
        });
      }
      break;
    case "file":
      if (param.file_config?.max_size) {
        rules.push({
          validator: (_rule: any, value: any) => {
            if (!value) return true;
            const file = value.file || value;
            return file.size <= param.file_config!.max_size!;
          },
          message: `文件大小不能超过 ${formatBytes(param.file_config.max_size)}`,
          trigger: "change",
        });
      }
      break;
  }

  return rules;
}

function stringRules(config: StringConfig): FormItemRule[] {
  const rules: FormItemRule[] = [];
  if (config.min_length !== undefined) {
    rules.push({
      min: config.min_length,
      message: `最少 ${config.min_length} 个字符`,
      trigger: "blur",
    });
  }
  if (config.max_length !== undefined) {
    rules.push({
      max: config.max_length,
      message: `最多 ${config.max_length} 个字符`,
      trigger: "blur",
    });
  }
  if (config.regex_pattern) {
    const regex = new RegExp(config.regex_pattern);
    rules.push({
      pattern: regex,
      message: "格式不符合要求",
      trigger: "blur",
    });
  }
  return rules;
}

function numberRules(
  config: NumberConfig,
  type: "int" | "float"
): FormItemRule[] {
  const rules: FormItemRule[] = [];

  rules.push({
    type: type === "int" ? "integer" : "number",
    message: `必须是${type === "int" ? "整数" : "数值"}`,
    trigger: ["blur", "change"],
  });

  if (config.min !== undefined) {
    rules.push({
      validator: (_rule: any, value: any) => {
        if (value === null || value === undefined) return true;
        return value >= config.min!;
      },
      message: `不能小于 ${config.min}`,
      trigger: ["blur", "change"],
    });
  }
  if (config.max !== undefined) {
    rules.push({
      validator: (_rule: any, value: any) => {
        if (value === null || value === undefined) return true;
        return value <= config.max!;
      },
      message: `不能大于 ${config.max}`,
      trigger: ["blur", "change"],
    });
  }
  return rules;
}
```

---

### 4.2 后端校验（Pydantic）

#### 4.2.1 完整后端校验流程

```python
# services/task_validation.py

from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from app.schemas.flow_config import FlowConfig
from app.schemas.condition import ConditionalValidator
from app.schemas.enums import ParameterTypeEnum


class TaskValidationService:
    """任务提交校验服务"""

    @staticmethod
    async def validate_task_submission(
        config: FlowConfig,
        form_values: dict[str, Any],
        sample_sheet_df: pd.DataFrame | None = None,
    ) -> dict:
        """
        完整校验任务提交数据

        Returns:
            {"valid": bool, "errors": list[dict], "warnings": list[str]}
        """
        result = {"valid": True, "errors": [], "warnings": []}

        # 1. 校验条件参数必填项（仅校验可见参数）
        cond_errors = ConditionalValidator.validate_required(
            config.parameters, form_values
        )
        result["errors"].extend(cond_errors)

        # 2. 校验参数类型
        type_errors = await TaskValidationService._validate_types(
            config.parameters, form_values
        )
        result["errors"].extend(type_errors)

        # 3. 校验 GROUP 条目数
        group_errors = TaskValidationService._validate_group_counts(
            config.parameters, form_values
        )
        result["errors"].extend(group_errors)

        # 4. 校验样本表（如果需要）
        if config.sample_sheet and sample_sheet_df is not None:
            sheet_errors = TaskValidationService._validate_sample_sheet(
                config.sample_sheet, sample_sheet_df
            )
            result["errors"].extend(sheet_errors)
        elif config.sample_sheet and sample_sheet_df is None:
            result["errors"].append({
                "field": "sample_sheet",
                "message": "此流程需要上传样本表",
            })

        # 5. 校验文件参数（文件存在性）
        file_errors = await TaskValidationService._validate_files(
            config.parameters, form_values
        )
        result["errors"].extend(file_errors)

        result["valid"] = len(result["errors"]) == 0
        return result

    @staticmethod
    def _validate_types(
        parameters: list[Any], form_values: dict[str, Any], prefix: str = ""
    ) -> list[dict]:
        """校验参数类型一致性"""
        errors = []
        from app.schemas.condition import ConditionEvaluator

        for p in parameters:
            # 跳过不可见参数
            if p.condition and not ConditionEvaluator.evaluate(
                p.condition, form_values
            ):
                continue

            value = form_values.get(p.name)
            if value is None:
                continue

            # 类型校验
            if p.type == ParameterTypeEnum.INT and not isinstance(value, int):
                errors.append({
                    "field": f"{prefix}{p.name}",
                    "message": f"'{p.label}' 必须是整数",
                })
            elif p.type == ParameterTypeEnum.FLOAT and not isinstance(value, (int, float)):
                errors.append({
                    "field": f"{prefix}{p.name}",
                    "message": f"'{p.label}' 必须是数值",
                })
            elif p.type == ParameterTypeEnum.STRING and not isinstance(value, str):
                errors.append({
                    "field": f"{prefix}{p.name}",
                    "message": f"'{p.label}' 必须是字符串",
                })
            elif p.type == ParameterTypeEnum.BOOLEAN and not isinstance(value, bool):
                errors.append({
                    "field": f"{prefix}{p.name}",
                    "message": f"'{p.label}' 必须是布尔值",
                })

            # GROUP 递归校验
            if p.type == ParameterTypeEnum.GROUP and isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        sub_errors = TaskValidationService._validate_types(
                            p.group_config.parameters, item, f"{p.name}[{i}]."
                        )
                        errors.extend(sub_errors)

            # SECTION 递归校验
            if p.type == ParameterTypeEnum.SECTION and isinstance(value, dict):
                sub_errors = TaskValidationService._validate_types(
                    p.section_config.parameters, value, f"{p.name}."
                )
                errors.extend(sub_errors)

        return errors

    @staticmethod
    def _validate_group_counts(
        parameters: list[Any], form_values: dict[str, Any]
    ) -> list[dict]:
        """校验 GROUP 条目数是否在允许范围内"""
        errors = []

        for p in parameters:
            if p.type != ParameterTypeEnum.GROUP or not p.group_config:
                continue

            items = form_values.get(p.name, [])
            count = len(items) if isinstance(items, list) else 0

            if count < p.group_config.min_items:
                errors.append({
                    "field": p.name,
                    "message": f"'{p.label}' 至少需要 {p.group_config.min_items} 组",
                })

            if p.group_config.max_items and count > p.group_config.max_items:
                errors.append({
                    "field": p.name,
                    "message": f"'{p.label}' 最多允许 {p.group_config.max_items} 组",
                })

        return errors

    @staticmethod
    def _validate_sample_sheet(
        config: Any,  # SampleSheetConfig
        df: pd.DataFrame,
    ) -> list[dict]:
        """根据 YAML 样本表定义校验上传的样本表"""
        errors = []

        # 1. 检查必填列
        for col in config.columns:
            if col.required and col.name not in df.columns:
                errors.append({
                    "field": f"sample_sheet.{col.name}",
                    "message": f"样本表缺少必填列: '{col.name}'",
                })

        # 2. 检查列类型
        type_map = {"string": object, "int": "Int64", "float": float, "boolean": bool}
        for col in config.columns:
            if col.name not in df.columns:
                continue
            expected_dtype = type_map.get(col.type, object)
            try:
                if col.type == "int":
                    df[col.name] = pd.to_numeric(df[col.name], errors="coerce")
                    if df[col.name].isna().any():
                        errors.append({
                            "field": f"sample_sheet.{col.name}",
                            "message": f"列 '{col.name}' 包含非整数数据",
                        })
            except Exception as e:
                errors.append({
                    "field": f"sample_sheet.{col.name}",
                    "message": f"列 '{col.name}' 类型转换失败: {str(e)}",
                })

        # 3. 唯一性校验
        for col in config.columns:
            if col.unique and col.name in df.columns:
                if df[col.name].duplicated().any():
                    dupes = df[df[col.name].duplicated(keep=False)][col.name].unique()
                    errors.append({
                        "field": f"sample_sheet.{col.name}",
                        "message": f"列 '{col.name}' 存在重复值: {list(dupes)}",
                    })

        # 4. 自定义校验规则
        for rule in config.validation_rules:
            if rule.type == "unique_combination":
                subset = [c for c in rule.columns if c in df.columns]
                if subset and df[subset].duplicated().any():
                    errors.append({
                        "field": f"sample_sheet.{'.'.join(subset)}",
                        "message": rule.message,
                    })

        return errors

    @staticmethod
    async def _validate_files(
        parameters: list[Any], form_values: dict[str, Any]
    ) -> list[dict]:
        """校验文件参数：存在性、大小、扩展名"""
        errors = []

        for p in parameters:
            if p.type != ParameterTypeEnum.FILE or not p.file_config:
                continue

            value = form_values.get(p.name)
            if not value:
                continue

            files = value if isinstance(value, list) else [value]
            for file_info in files:
                if isinstance(file_info, str):
                    # 校验路径存在性
                    path = Path(file_info)
                    if not path.exists():
                        errors.append({
                            "field": p.name,
                            "message": f"文件不存在: {file_info}",
                        })

                if isinstance(file_info, dict) and "size" in file_info:
                    # 校验文件大小
                    if (
                        p.file_config.max_size
                        and file_info["size"] > p.file_config.max_size
                    ):
                        max_mb = p.file_config.max_size / (1024 * 1024)
                        errors.append({
                            "field": p.name,
                            "message": (
                                f"文件 '{file_info.get('name', 'unknown')}' "
                                f"大小超过限制 ({max_mb:.1f} MB)"
                            ),
                        })

                if isinstance(file_info, dict) and "name" in file_info:
                    # 校验扩展名
                    if p.file_config.accept and p.file_config.accept != "*":
                        accepted = [
                            ext.strip() for ext in p.file_config.accept.split(",")
                        ]
                        file_name = file_info["name"]
                        if not any(
                            file_name.endswith(ext) for ext in accepted
                        ):
                            errors.append({
                                "field": p.name,
                                "message": (
                                    f"文件 '{file_name}' 格式不符合要求，"
                                    f"允许: {p.file_config.accept}"
                                ),
                            })

        return errors
```

---

### 4.3 样本表校验流程（完整时序）

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   用户上传   │ ──▶ │  后端接收     │ ──▶ │  根据 YAML 定义  │ ──▶ │ 校验通过？   │
│  CSV/Excel   │     │  保存临时文件  │     │  校验样本表      │     │              │
└─────────────┘     └──────────────┘     └─────────────────┘     └──────┬───────┘
                                                                         │
                                                          ┌── 否 ──▶ 返回错误列表
                                                          │
                                                          ▼ 是
                                              ┌─────────────────────┐
                                              │  校验通过后写入任务   │
                                              │  目录的 samples.csv   │
                                              └─────────────────────┘
                                                         │
                                                         ▼
                                              ┌─────────────────────┐
                                              │  返回校验成功 +       │
                                              │  预览数据（前5行）    │
                                              └─────────────────────┘
```

**后端样本表处理接口：**

```python
# routers/sample_sheet.py

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
import pandas as pd
import io

from app.schemas.flow_config import FlowConfig
from app.services.task_validation import TaskValidationService

router = APIRouter(prefix="/api/v1/sample-sheets", tags=["sample-sheet"])


@router.post("/validate/{flow_id}")
async def validate_sample_sheet(
    flow_id: str,
    file: UploadFile = File(...),
):
    """
    校验上传的样本表文件
    """
    # 1. 加载流程配置
    config = await load_flow_config(flow_id)
    if not config.sample_sheet:
        raise HTTPException(400, "此流程不需要样本表")

    # 2. 读取文件
    content = await file.read()
    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.StringIO(content.decode("utf-8")))
        elif file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise HTTPException(400, "仅支持 CSV 和 Excel 格式")
    except Exception as e:
        raise HTTPException(400, f"文件解析失败: {str(e)}")

    # 3. 校验
    result = TaskValidationService._validate_sample_sheet(
        config.sample_sheet, df
    )

    if result:
        return {
            "valid": False,
            "errors": result,
            "columns": list(df.columns),
            "row_count": len(df),
        }

    # 4. 返回预览
    return {
        "valid": True,
        "columns": list(df.columns),
        "row_count": len(df),
        "preview": df.head(5).to_dict("records"),
    }
```

---

## 5. 动态表单渲染架构

### 5.1 组件映射表

| 参数类型 (type) | Vue 组件 | Naive UI 组件 | 说明 |
|----------------|---------|--------------|------|
| `string` | `StringInput` | `n-input` | 文本/多行文本 |
| `int` | `NumberInput` | `n-input-number` / `n-slider` | 整数输入/滑块 |
| `float` | `NumberInput` | `n-input-number` / `n-slider` | 浮点数输入/滑块 |
| `select` | `SelectInput` | `n-select` | 单/多选下拉 |
| `file` | `FileUpload` | `n-upload` | 文件上传 |
| `boolean` | `BooleanInput` | `n-switch` | 开关 |
| `group` | `RepeatableGroup` | `n-card` + `n-button` | 可重复卡片组 |
| `section` | `CollapsibleSection` | `n-collapse` | 折叠区域 |

### 5.2 条件渲染响应式架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        响应式依赖图                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   formValues (reactive Proxy)                                   │
│       │                                                         │
│       ├── aligner = "STAR" ──────▶ star_index (visible=true)    │
│       │                    ──────▶ star_threads (visible=true)  │
│       │                                                         │
│       ├── aligner = "HISAT2" ────▶ hisat2_index (visible=true)  │
│       │                    ──────▶ star_index (visible=false)   │
│       │                                                         │
│       ├── quantifier = "featureCounts" ──┐                      │
│       │   AND aligner != "bowtie2"       ├──▶ fc_count_...      │
│       │                                  │    (visible=eval)     │
│       │                                  │                      │
│       └── batch_correction = "none" ────▶ batch_column           │
│                                          (visible=false)         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

> 关键设计：所有参数的 `v-if` 绑定到 `isVisible()` 函数，该函数读取 `formValues` 响应式对象。
> Vue 3 的自动依赖追踪会确保当 `formValues.xxx` 变化时，所有依赖该字段的条件参数自动重新评估。

### 5.3 表单值收集与提交

#### 5.3.1 表单值结构

```typescript
// 提交的表单值结构示例
interface TaskSubmission {
  flow_id: string;
  parameters: {
    genome: "hg38";
    aligner: "STAR";
    star_index: "/data/ref/hg38/STAR_index";
    star_threads: 8;
    strandness: "unstranded";
    comparisons: [
      {
        comparison_name: "Tumor_vs_Normal";
        control_group: "Normal";
        treatment_group: "Tumor";
        fdr_threshold: 0.05;
        log2fc_threshold: 1.0;
      },
      {
        comparison_name: "Metastatic_vs_Primary";
        control_group: "Primary";
        treatment_group: "Metastatic";
        fdr_threshold: 0.01;
        log2fc_threshold: 1.5;
      }
    ];
    quantifier: "featureCounts";
    fc_count_multimapping: false;
    gtf_annotation: { name: "genes.gtf"; size: 156000000; path: "/tmp/..." };
    advanced_params: {
      min_read_quality: 20;
      min_read_length: 36;
      normalization_method: "rlog";
      cook_cutoff: 0.99;
      independent_filtering: true;
      batch_correction: "none";
    };
    use_gpu: false;
    max_memory_gb: 32;
  };
  sample_sheet: "/uploads/task_001/samples.csv";
  resources: {
    cores: 8;
    memory: "32G";
    time: "4h";
  };
}
```

#### 5.3.2 提交 API

```python
# routers/task.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.schemas.flow_config import FlowConfig

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


class TaskCreateRequest(BaseModel):
    flow_id: str
    parameters: dict[str, Any]  # 动态表单值
    sample_sheet_path: str | None = None  # 已校验的样本表路径


@router.post("/")
async def create_task(
    request: TaskCreateRequest,
):
    """
    创建新分析任务
    """
    # 1. 加载流程配置
    config = await load_flow_config(request.flow_id)

    # 2. 完整校验（条件参数 + 类型 + 样本表）
    from app.services.task_validation import TaskValidationService

    sample_df = None
    if request.sample_sheet_path:
        sample_df = pd.read_csv(request.sample_sheet_path)

    validation = await TaskValidationService.validate_task_submission(
        config, request.parameters, sample_df
    )

    if not validation["valid"]:
        raise HTTPException(422, {
            "detail": "参数校验失败",
            "errors": validation["errors"],
        })

    # 3. 构建 Snakemake config
    snake_config = build_snakemake_config(config, request.parameters)

    # 4. 创建任务目录并写入配置
    task_dir = await create_task_directory(request.flow_id)
    await write_config_yaml(task_dir, snake_config)
    if request.sample_sheet_path:
        await copy_sample_sheet(request.sample_sheet_path, task_dir / "samples.csv")

    # 5. 提交到执行引擎
    task_id = await submit_to_engine(config.execution, task_dir)

    return {"task_id": task_id, "status": "queued"}


def build_snakemake_config(
    flow_config: FlowConfig,
    form_values: dict[str, Any],
) -> dict[str, Any]:
    """
    将表单值转换为 Snakemake 配置字典
    """
    config = dict(form_values)

    # 展开 Section 参数（将 section.name.value 扁平化）
    for param in flow_config.parameters:
        if param.type == ParameterTypeEnum.SECTION and param.section_config:
            section_values = config.get(param.name, {})
            if isinstance(section_values, dict):
                # 将 section 内的值提升到顶层（或保持嵌套，视 Snakefile 约定）
                for key, value in section_values.items():
                    config[f"{param.name}_{key}"] = value

    # 处理 GROUP 参数（Snakemake 直接接收列表）
    for param in flow_config.parameters:
        if param.type == ParameterTypeEnum.GROUP and param.group_config:
            group_values = config.get(param.name, [])
            if isinstance(group_values, list):
                config[param.name] = group_values

    return config
```

---

## 6. JSON Schema 导出

### 6.1 导出脚本

```python
# scripts/export_schema.py

"""
导出 JSON Schema 供前端 TypeScript 类型生成使用
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas.json_schema import export_json_schema, export_parameter_schema


def main():
    # 导出完整配置 Schema
    schema = export_json_schema()
    output_path = Path("frontend/src/types/flow-config.schema.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"Schema exported to {output_path}")

    # 导出独立参数 Schema
    param_schema = export_parameter_schema()
    param_output = Path("frontend/src/types/parameter.schema.json")
    with open(param_output, "w", encoding="utf-8") as f:
        json.dump(param_schema, f, indent=2, ensure_ascii=False)
    print(f"Parameter schema exported to {param_output}")


if __name__ == "__main__":
    main()
```

### 6.2 前端类型生成

```bash
# package.json scripts
{
  "scripts": {
    "generate:types": "json2ts src/types/flow-config.schema.json > src/types/schema.d.ts"
  }
}

# 生成的 TypeScript 类型可直接用于表单组件
```

---

## 附录 A：条件渲染规则完整示例集

```yaml
# A1. 简单等于
condition:
  field: "aligner"
  operator: "eq"
  value: "STAR"

# A2. 简单不等于
condition:
  field: "batch_correction"
  operator: "ne"
  value: "none"

# A3. 数值范围
condition:
  field: "threads"
  operator: "gte"
  value: 4

# A4. 包含于列表
condition:
  field: "genome"
  operator: "in"
  value: ["hg38", "mm39", "rn6"]

# A5. 正则匹配
condition:
  field: "sample_id_pattern"
  operator: "regex"
  value: "^[A-Z]{2}[0-9]{3}$"

# A6. AND 复合
condition:
  and_rules:
    - field: "aligner"
      operator: "eq"
      value: "STAR"
    - field: "two_pass"
      operator: "eq"
      value: true

# A7. OR 复合
condition:
  or_rules:
    - field: "quantifier"
      operator: "eq"
      value: "salmon"
    - field: "aligner"
      operator: "eq"
      value: "bowtie2"

# A8. 嵌套复合（AND 中包含 OR）
condition:
  and_rules:
    - field: "run_qc"
      operator: "eq"
      value: true
    - or_rules:
        - field: "qc_tool"
          operator: "eq"
          value: "fastqc"
        - field: "qc_tool"
          operator: "eq"
          value: "multiqc"
```

---

## 附录 B：快速参考

### B.1 新增流程 YAML 的 checklist

- [ ] `meta.id` 全局唯一（小写下划线命名）
- [ ] `meta.version` 符合语义化版本规范
- [ ] 所有 `parameters[].name` 全局唯一（含 group/section 内参数）
- [ ] `condition` 引用的 field 存在于已定义的参数中
- [ ] `group_config.parameters` 非空
- [ ] `section_config.parameters` 非空
- [ ] 必填参数设置 `required: true`
- [ ] 样本表 `columns` 包含至少一列
- [ ] `snakefile` 路径相对于项目根目录

### B.2 文件上传大小参考

| 文件类型 | 典型大小 | 建议 max_size |
|---------|---------|-------------|
| GTF 注释 | 50-500 MB | 536870912 (512 MB) |
| 参考基因组 FASTA | 1-5 GB | 6442450944 (6 GB) |
| FASTQ 样本 | 1-10 GB | 直接使用路径而非上传 |
| 配置文件 | < 1 MB | 1048576 (1 MB) |

### B.3 命名规范

| 对象 | 规范 | 示例 |
|------|------|------|
| flow id | `^[a-z][a-z0-9_]*$` | `rna_seq`, `chip_seq_peak_calling` |
| 参数 name | `^[a-zA-Z_][a-zA-Z0-9_]*$` | `aligner`, `star_index`, `minQuality` |
| 版本号 | SemVer | `1.0.0`, `2.1.0-beta` |
| 列名 | `^[a-zA-Z_][a-zA-Z0-9_]*$` | `sample_id`, `fastq_1` |


---

# 6.5 OmicsHub 前端路由、页面结构与 AI 对话面板架构

> **文档版本**: v1.0  
> **技术栈**: Vue 3.4+ / TypeScript 5.0+ / Vite 5+ / Naive UI 2.38+ / Element Plus 2.5+ / Pinia 2.1+ / Vue Router 4+ / Axios 1.6+  
> **作者**: 前端架构组  
> **日期**: 2025-06-09

---

## 目录

1. [完整路由表设计](#1-完整路由表设计)
2. [页面布局架构](#2-页面布局架构)
3. [核心页面组件设计](#3-核心页面组件设计)
4. [Pinia Store 设计](#4-pinia-store-设计)
5. [AI 对话面板架构](#5-ai-对话面板架构)
6. [暗黑模式实现](#6-暗黑模式实现)
7. [文件目录结构总览](#7-文件目录结构总览)

---

## 1. 完整路由表设计

### 1.1 路由类型定义

```typescript
// src/router/types.ts
import type { RouteRecordRaw } from 'vue-router'

/** 布局类型 */
export type LayoutType = 'blank' | 'main' | 'admin'

/** 路由元信息 */
export interface RouteMeta {
  /** 页面标题 */
  title: string
  /** 是否需要认证 */
  requiresAuth: boolean
  /** 是否需要管理员权限 */
  requiresAdmin?: boolean
  /** 布局类型 */
  layout: LayoutType
  /** 左侧菜单图标 */
  icon?: string
  /** 是否在侧边栏菜单中隐藏 */
  hideInMenu?: boolean
  /** 面包屑父级路由名 */
  breadcrumbParent?: string
  /** 页面缓存名称（keep-alive） */
  keepAlive?: string
  /** 当前激活的菜单项（用于子路由高亮父菜单） */
  activeMenu?: string
}

// 扩展 Vue Router 的 RouteRecordRaw 类型声明
declare module 'vue-router' {
  interface RouteMeta {
    title: string
    requiresAuth: boolean
    requiresAdmin?: boolean
    layout: LayoutType
    icon?: string
    hideInMenu?: boolean
    breadcrumbParent?: string
    keepAlive?: string
    activeMenu?: string
  }
}
```

### 1.2 完整路由表

```typescript
// src/router/routes.ts
import type { RouteRecordRaw } from 'vue-router'

// ─────────────────────────────────────────
// 布局组件（懒加载）
// ─────────────────────────────────────────
const BlankLayout = () => import('@/layouts/BlankLayout.vue')
const MainLayout = () => import('@/layouts/MainLayout.vue')
const AdminLayout = () => import('@/layouts/AdminLayout.vue')

// ─────────────────────────────────────────
// 页面组件（懒加载）
// ─────────────────────────────────────────
// 认证
const LoginView = () => import('@/views/auth/LoginView.vue')
const RegisterView = () => import('@/views/auth/RegisterView.vue')

// 仪表盘
const DashboardView = () => import('@/views/dashboard/DashboardView.vue')

// 项目
const ProjectsView = () => import('@/views/project/ProjectsView.vue')
const ProjectDetailView = () => import('@/views/project/ProjectDetailView.vue')
const ProjectSamplesView = () => import('@/views/project/ProjectSamplesView.vue')
const ProjectFilesView = () => import('@/views/project/ProjectFilesView.vue')

// 流程市场
const FlowMarketView = () => import('@/views/flow/FlowMarketView.vue')
const FlowDetailView = () => import('@/views/flow/FlowDetailView.vue')

// 任务（核心）
const TaskListView = () => import('@/views/task/TaskListView.vue')
const TaskSubmitView = () => import('@/views/task/TaskSubmitView.vue')
const TaskDetailView = () => import('@/views/task/TaskDetailView.vue')

// 管理后台
const AdminFlowManager = () => import('@/views/admin/AdminFlowManager.vue')
const AdminUserManager = () => import('@/views/admin/AdminUserManager.vue')
const AdminMCPManager = () => import('@/views/admin/AdminMCPManager.vue')
const AdminSystemSettings = () => import('@/views/admin/AdminSystemSettings.vue')

// 个人设置
const ProfileView = () => import('@/views/profile/ProfileView.vue')

// 404
const NotFoundView = () => import('@/views/error/NotFoundView.vue')

// ═════════════════════════════════════════
// 路由表定义
// ═════════════════════════════════════════
export const routes: RouteRecordRaw[] = [
  // ─────────────────────────────────────
  // 1. 认证路由（Blank 布局）
  // ─────────────────────────────────────
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: {
      title: '登录',
      requiresAuth: false,
      layout: 'blank',
    },
  },
  {
    path: '/register',
    name: 'Register',
    component: RegisterView,
    meta: {
      title: '注册',
      requiresAuth: false,
      layout: 'blank',
    },
  },

  // ─────────────────────────────────────
  // 2. 主工作区路由（Main 布局）
  // ─────────────────────────────────────
  {
    path: '/',
    component: MainLayout,
    meta: {
      title: 'OmicsHub',
      requiresAuth: true,
      layout: 'main',
    },
    children: [
      // 仪表盘
      {
        path: '',
        name: 'Dashboard',
        component: DashboardView,
        meta: {
          title: '仪表盘',
          requiresAuth: true,
          layout: 'main',
          icon: 'DashboardOutlined',
          keepAlive: 'DashboardView',
        },
      },

      // ── 项目管理 ──
      {
        path: 'projects',
        name: 'Projects',
        component: ProjectsView,
        meta: {
          title: '项目管理',
          requiresAuth: true,
          layout: 'main',
          icon: 'FolderOutlined',
          keepAlive: 'ProjectsView',
        },
      },
      {
        path: 'projects/:id',
        name: 'ProjectDetail',
        component: ProjectDetailView,
        meta: {
          title: '项目详情',
          requiresAuth: true,
          layout: 'main',
          icon: 'FolderOpenOutlined',
          activeMenu: 'Projects',
          hideInMenu: true,
        },
        redirect: (to) => `/projects/${to.params.id}/samples`,
        children: [
          {
            path: 'samples',
            name: 'ProjectSamples',
            component: ProjectSamplesView,
            meta: {
              title: '样本管理',
              requiresAuth: true,
              layout: 'main',
              hideInMenu: true,
            },
          },
          {
            path: 'files',
            name: 'ProjectFiles',
            component: ProjectFilesView,
            meta: {
              title: '文件列表',
              requiresAuth: true,
              layout: 'main',
              hideInMenu: true,
            },
          },
        ],
      },

      // ── 流程市场 ──
      {
        path: 'flows',
        name: 'FlowMarket',
        component: FlowMarketView,
        meta: {
          title: '流程市场',
          requiresAuth: true,
          layout: 'main',
          icon: 'ApartmentOutlined',
          keepAlive: 'FlowMarketView',
        },
      },
      {
        path: 'flows/:id',
        name: 'FlowDetail',
        component: FlowDetailView,
        meta: {
          title: '流程详情',
          requiresAuth: true,
          layout: 'main',
          hideInMenu: true,
          activeMenu: 'FlowMarket',
        },
      },

      // ── 任务管理（核心） ──
      {
        path: 'tasks',
        name: 'TaskList',
        component: TaskListView,
        meta: {
          title: '任务列表',
          requiresAuth: true,
          layout: 'main',
          icon: 'ExperimentOutlined',
          keepAlive: 'TaskListView',
        },
      },
      {
        path: 'tasks/new',
        name: 'TaskSubmit',
        component: TaskSubmitView,
        meta: {
          title: '新建任务',
          requiresAuth: true,
          layout: 'main',
          hideInMenu: true,
          icon: 'PlusOutlined',
        },
      },
      {
        path: 'tasks/:id',
        name: 'TaskDetail',
        component: TaskDetailView,
        meta: {
          title: '任务详情',
          requiresAuth: true,
          layout: 'main',
          hideInMenu: true,
          activeMenu: 'TaskList',
        },
      },

      // ── 个人设置 ──
      {
        path: 'profile',
        name: 'Profile',
        component: ProfileView,
        meta: {
          title: '个人设置',
          requiresAuth: true,
          layout: 'main',
          icon: 'UserOutlined',
          hideInMenu: true,
        },
      },
    ],
  },

  // ─────────────────────────────────────
  // 3. 管理后台路由（Admin 布局）
  // ─────────────────────────────────────
  {
    path: '/admin',
    component: AdminLayout,
    meta: {
      title: '管理后台',
      requiresAuth: true,
      requiresAdmin: true,
      layout: 'admin',
    },
    redirect: '/admin/flows',
    children: [
      {
        path: 'flows',
        name: 'AdminFlowManager',
        component: AdminFlowManager,
        meta: {
          title: '流程管理',
          requiresAuth: true,
          requiresAdmin: true,
          layout: 'admin',
          icon: 'CodeOutlined',
        },
      },
      {
        path: 'users',
        name: 'AdminUserManager',
        component: AdminUserManager,
        meta: {
          title: '用户管理',
          requiresAuth: true,
          requiresAdmin: true,
          layout: 'admin',
          icon: 'TeamOutlined',
        },
      },
      {
        path: 'mcp',
        name: 'AdminMCPManager',
        component: AdminMCPManager,
        meta: {
          title: 'MCP Server 管理',
          requiresAuth: true,
          requiresAdmin: true,
          layout: 'admin',
          icon: 'CloudServerOutlined',
        },
      },
      {
        path: 'system',
        name: 'AdminSystemSettings',
        component: AdminSystemSettings,
        meta: {
          title: '系统设置',
          requiresAuth: true,
          requiresAdmin: true,
          layout: 'admin',
          icon: 'SettingOutlined',
        },
      },
    ],
  },

  // ─────────────────────────────────────
  // 4. 404 与重定向
  // ─────────────────────────────────────
  {
    path: '/404',
    name: 'NotFound',
    component: NotFoundView,
    meta: {
      title: '页面不存在',
      requiresAuth: false,
      layout: 'blank',
    },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/404',
    meta: {
      title: '重定向',
      requiresAuth: false,
      layout: 'blank',
    },
  },
]
```

### 1.3 路由守卫与导航逻辑

```typescript
// src/router/guard.ts
import type { Router, NavigationGuardNext } from 'vue-router'
import { useAuthStore } from '@/stores/modules/auth'
import { useThemeStore } from '@/stores/modules/theme'
import { message } from '@/utils/naiveMessage'

export function setupRouterGuard(router: Router) {
  // ── 全局前置守卫 ──
  router.beforeEach(
    async (to, _from, next: NavigationGuardNext) => {
      const authStore = useAuthStore()
      const themeStore = useThemeStore()

      // 1. 动态设置页面标题
      const baseTitle = 'OmicsHub'
      document.title = to.meta.title
        ? `${to.meta.title} | ${baseTitle}`
        : baseTitle

      // 2. 同步主题（避免闪烁）
      themeStore.applyThemeImmediately()

      // 3. 无需认证的路由直接放行
      if (!to.meta.requiresAuth) {
        return next()
      }

      // 4. 未登录 → 跳转登录页
      if (!authStore.isLoggedIn) {
        // 尝试静默刷新 token
        const refreshed = await authStore.tryRefreshToken()
        if (!refreshed) {
          message.warning('请先登录')
          return next({
            name: 'Login',
            query: { redirect: to.fullPath },
          })
        }
      }

      // 5. 需要管理员权限但未满足
      if (to.meta.requiresAdmin && !authStore.isAdmin) {
        message.error('无权访问该页面')
        return next({ name: 'Dashboard' })
      }

      // 6. 放行
      next()
    }
  )

  // ── 全局后置钩子 ──
  router.afterEach((to) => {
    // 滚动到顶部
    window.scrollTo({ top: 0, behavior: 'smooth' })

    // 记录最近访问路由（用于返回功能）
    const authStore = useAuthStore()
    if (to.meta.requiresAuth) {
      authStore.setLastVisitedRoute(to.path)
    }
  })

  // ── 全局错误处理 ──
  router.onError((error) => {
    console.error('[Router Error]', error)
    message.error('页面加载失败，请刷新重试')
  })
}
```

### 1.4 路由入口

```typescript
// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from './routes'
import { setupRouterGuard } from './guard'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

setupRouterGuard(router)

export default router
```

---

## 2. 页面布局架构

### 2.1 三种布局类型概览

| 布局 | 路径 | 用途 | 特征 |
|------|------|------|------|
| `BlankLayout` | `/login`, `/register`, `/404` | 认证 & 错误页 | 无导航，纯白/暗色背景 |
| `MainLayout` | `/`, `/projects`, `/flows`, `/tasks/*` | 主工作区 | 左侧导航 + 顶部 Header + 内容区 + **右侧 AI 面板** |
| `AdminLayout` | `/admin/*` | 管理后台 | 独立侧边栏 + 内容区（无 AI 面板） |

### 2.2 BlankLayout.vue — 空布局（登录/注册）

```vue
<!-- src/layouts/BlankLayout.vue -->
<template>
  <n-config-provider :theme="themeStore.naiveTheme" :locale="zhCN">
    <n-loading-bar-provider>
      <n-dialog-provider>
        <n-notification-provider>
          <n-message-provider>
            <div class="blank-layout" :class="{ dark: themeStore.isDark }">
              <!-- 装饰性背景 -->
              <div class="blank-layout__bg">
                <div class="blob blob-1"></div>
                <div class="blob blob-2"></div>
                <div class="blob blob-3"></div>
              </div>

              <!-- 左侧品牌展示区（仅宽屏） -->
              <div class="blank-layout__brand" v-if="!isMobile">
                <div class="brand-content">
                  <img src="/logo.svg" alt="OmicsHub" class="brand-logo" />
                  <h1 class="brand-title">OmicsHub</h1>
                  <p class="brand-subtitle">多组学智能分析平台</p>
                  <div class="brand-features">
                    <div class="feature-item">
                      <n-icon size="20"><DnaOutlined /></n-icon>
                      <span>基因组 / 转录组 / 蛋白质组</span>
                    </div>
                    <div class="feature-item">
                      <n-icon size="20"><RobotOutlined /></n-icon>
                      <span>AI 助手全流程辅助</span>
                    </div>
                    <div class="feature-item">
                      <n-icon size="20"><ThunderboltOutlined /></n-icon>
                      <span>可视化流程编排</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 右侧表单区 -->
              <div class="blank-layout__form">
                <div class="form-card">
                  <router-view v-slot="{ Component }">
                    <transition name="fade-slide" mode="out-in">
                      <component :is="Component" />
                    </transition>
                  </router-view>
                </div>
              </div>
            </div>
          </n-message-provider>
        </n-notification-provider>
      </n-dialog-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useWindowSize } from '@vueuse/core'
import { NConfigProvider, NLoadingBarProvider, NDialogProvider, NNotificationProvider, NMessageProvider, NIcon } from 'naive-ui'
import { zhCN } from 'naive-ui'
import { DnaOutlined, RobotOutlined, ThunderboltOutlined } from '@vicons/antd'
import { useThemeStore } from '@/stores/modules/theme'

const themeStore = useThemeStore()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)
</script>

<style scoped lang="scss">
.blank-layout {
  min-height: 100vh;
  display: flex;
  position: relative;
  overflow: hidden;

  &__bg {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;

    .blob {
      position: absolute;
      border-radius: 50%;
      filter: blur(80px);
      opacity: 0.35;
      animation: float 20s ease-in-out infinite;

      &-1 {
        width: 400px; height: 400px;
        background: #6366f1;
        top: -100px; left: -100px;
        animation-delay: 0s;
      }
      &-2 {
        width: 300px; height: 300px;
        background: #8b5cf6;
        bottom: -50px; right: 10%;
        animation-delay: -7s;
      }
      &-3 {
        width: 250px; height: 250px;
        background: #ec4899;
        top: 40%; left: 30%;
        animation-delay: -14s;
      }
    }
  }

  &__brand {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    z-index: 1;
    background: linear-gradient(135deg, rgba(99,102,241,0.08) 0%, rgba(139,92,246,0.05) 100%);

    .brand-content {
      text-align: center;
      padding: 48px;

      .brand-logo { width: 72px; height: 72px; margin-bottom: 16px; }
      .brand-title { font-size: 32px; font-weight: 700; margin-bottom: 8px; color: var(--text-primary); }
      .brand-subtitle { font-size: 16px; color: var(--text-secondary); margin-bottom: 40px; }

      .brand-features {
        display: flex;
        flex-direction: column;
        gap: 16px;

        .feature-item {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          font-size: 14px;
          color: var(--text-secondary);
        }
      }
    }
  }

  &__form {
    width: 480px;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    z-index: 1;
    padding: 32px;

    .form-card {
      width: 100%;
      max-width: 400px;
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 16px;
      padding: 40px 32px;
      backdrop-filter: blur(12px);
      box-shadow: 0 8px 32px rgba(0,0,0,0.08);
    }
  }

  // 移动端适配
  @media (max-width: 768px) {
    .blank-layout__form {
      width: 100%;
      padding: 16px;

      .form-card {
        border-radius: 12px;
        padding: 32px 24px;
      }
    }
  }
}

@keyframes float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -30px) scale(1.05); }
  66% { transform: translate(-20px, 20px) scale(0.95); }
}

.fade-slide-enter-active, .fade-slide-leave-active {
  transition: all 0.3s ease;
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateX(20px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}
</style>
```

### 2.3 MainLayout.vue — 主布局（核心）

```vue
<!-- src/layouts/MainLayout.vue -->
<template>
  <n-config-provider
    :theme="themeStore.naiveTheme"
    :theme-overrides="themeStore.naiveThemeOverrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <n-loading-bar-provider>
      <n-dialog-provider>
        <n-notification-provider>
          <n-message-provider>
            <n-layout class="main-layout" has-sider>
              <!-- 左侧导航栏 -->
              <n-layout-sider
                class="main-layout__sider"
                :collapsed="siderCollapsed"
                :collapsed-width="64"
                :width="220"
                :native-scrollbar="false"
                bordered
                collapse-mode="width"
                show-trigger
                @update:collapsed="siderCollapsed = $event"
              >
                <AppSidebar :collapsed="siderCollapsed" />
              </n-layout-sider>

              <!-- 右侧主区域 -->
              <n-layout class="main-layout__right">
                <!-- 顶部 Header -->
                <n-layout-header class="main-layout__header" bordered>
                  <AppHeader
                    :sider-collapsed="siderCollapsed"
                    @toggle-sider="siderCollapsed = !siderCollapsed"
                  />
                </n-layout-header>

                <!-- 内容区 + AI 面板 -->
                <n-layout class="main-layout__body" has-sider sider-placement="right">
                  <!-- 主内容区 -->
                  <n-layout-content
                    class="main-layout__content"
                    :style="contentStyle"
                    :native-scrollbar="false"
                  >
                    <AppBreadcrumb />
                    <div class="main-layout__content-inner">
                      <router-view v-slot="{ Component, route }">
                        <transition name="fade" mode="out-in">
                          <keep-alive :include="cachedViews">
                            <component :is="Component" :key="route.path" />
                          </keep-alive>
                        </transition>
                      </router-view>
                    </div>
                  </n-layout-content>

                  <!-- AI 对话面板 -->
                  <n-layout-sider
                    class="main-layout__ai-sider"
                    :width="380"
                    :collapsed-width="0"
                    :collapsed="!chatStore.panelVisible"
                    collapse-mode="transform"
                    show-trigger="bar"
                    trigger-style=""
                    @update:collapsed="chatStore.togglePanel"
                  >
                    <AIChatPanel />
                  </n-layout-sider>
                </n-layout>
              </n-layout>
            </n-layout>

            <!-- AI 面板折叠时的浮动按钮 -->
            <AIChatFab v-if="!chatStore.panelVisible" />
          </n-message-provider>
        </n-notification-provider>
      </n-dialog-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NConfigProvider, NLoadingBarProvider, NDialogProvider,
  NNotificationProvider, NMessageProvider,
  NLayout, NLayoutSider, NLayoutHeader, NLayoutContent,
} from 'naive-ui'
import { zhCN, dateZhCN } from 'naive-ui'

import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppBreadcrumb from '@/components/layout/AppBreadcrumb.vue'
import AIChatPanel from '@/components/ai-chat/AIChatPanel.vue'
import AIChatFab from '@/components/ai-chat/AIChatFab.vue'

import { useThemeStore } from '@/stores/modules/theme'
import { useChatStore } from '@/stores/modules/chat'
import { useTabStore } from '@/stores/modules/tab'

// ── stores ──
const themeStore = useThemeStore()
const chatStore = useChatStore()
const tabStore = useTabStore()
const route = useRoute()

// ── 侧边栏折叠 ──
const siderCollapsed = ref(false)

// ── 缓存视图列表（keep-alive） ──
const cachedViews = computed(() => tabStore.cachedViews)

// ── 内容区样式（根据 AI 面板状态自适应宽度） ──
const contentStyle = computed(() => {
  return {
    transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
  }
})

// ── 路由变化时自动收集 AI 上下文 ──
watch(
  () => route.path,
  (newPath) => {
    chatStore.collectRouteContext(newPath, route.params, route.query)
  },
  { immediate: true }
)
</script>

<style scoped lang="scss">
.main-layout {
  height: 100vh;

  &__sider {
    z-index: 100;
    :deep(.n-layout-sider-scroll-container) {
      display: flex;
      flex-direction: column;
    }
  }

  &__right {
    display: flex;
    flex-direction: column;
  }

  &__header {
    height: 56px;
    padding: 0 16px;
    display: flex;
    align-items: center;
    z-index: 99;
  }

  &__body {
    flex: 1;
    overflow: hidden;
  }

  &__content {
    flex: 1;
    overflow: auto;
    background: var(--content-bg);

    &-inner {
      padding: 20px;
      min-height: calc(100% - 40px);
    }
  }

  &__ai-sider {
    z-index: 98;
    :deep(.n-layout-sider-scroll-container) {
      border-left: 1px solid var(--border-color);
    }
  }
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
```

### 2.4 AdminLayout.vue — 管理后台布局

```vue
<!-- src/layouts/AdminLayout.vue -->
<template>
  <n-config-provider
    :theme="themeStore.naiveTheme"
    :theme-overrides="themeStore.naiveThemeOverrides"
    :locale="zhCN"
  >
    <n-loading-bar-provider>
      <n-dialog-provider>
        <n-notification-provider>
          <n-message-provider>
            <n-layout class="admin-layout" has-sider>
              <!-- 管理后台侧边栏 -->
              <n-layout-sider
                class="admin-layout__sider"
                :collapsed="collapsed"
                :collapsed-width="64"
                :width="240"
                bordered
                collapse-mode="width"
                show-trigger
                @update:collapsed="collapsed = $event"
              >
                <!-- Logo -->
                <div class="admin-logo">
                  <img src="/logo.svg" alt="" class="admin-logo__icon" />
                  <span v-if="!collapsed" class="admin-logo__text">OmicsHub Admin</span>
                </div>

                <!-- 管理菜单 -->
                <n-menu
                  :value="activeMenuKey"
                  :collapsed="collapsed"
                  :collapsed-width="64"
                  :options="adminMenuOptions"
                  @update:value="handleMenuSelect"
                />
              </n-layout-sider>

              <!-- 内容区 -->
              <n-layout class="admin-layout__main">
                <n-layout-header class="admin-layout__header" bordered>
                  <div class="header-left">
                    <n-button text @click="$router.push({ name: 'Dashboard' })">
                      <template #icon><n-icon><ArrowLeftOutlined /></n-icon></template>
                      返回工作台
                    </n-button>
                  </div>
                  <div class="header-right">
                    <ThemeToggle />
                    <UserDropdown />
                  </div>
                </n-layout-header>

                <n-layout-content class="admin-layout__content" :native-scrollbar="false">
                  <div class="admin-layout__content-inner">
                    <router-view />
                  </div>
                </n-layout-content>
              </n-layout>
            </n-layout>
          </n-message-provider>
        </n-notification-provider>
      </n-dialog-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, ref, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NConfigProvider, NLoadingBarProvider, NDialogProvider,
  NNotificationProvider, NMessageProvider,
  NLayout, NLayoutSider, NLayoutHeader, NLayoutContent,
  NMenu, NButton, NIcon,
} from 'naive-ui'
import { zhCN } from 'naive-ui'
import {
  CodeOutlined, TeamOutlined, CloudServerOutlined, SettingOutlined, ArrowLeftOutlined,
} from '@vicons/antd'
import { useThemeStore } from '@/stores/modules/theme'
import ThemeToggle from '@/components/common/ThemeToggle.vue'
import UserDropdown from '@/components/layout/UserDropdown.vue'

const themeStore = useThemeStore()
const route = useRoute()
const router = useRouter()

const collapsed = ref(false)
const activeMenuKey = computed(() => route.name as string)

const adminMenuOptions = [
  {
    label: '流程管理',
    key: 'AdminFlowManager',
    icon: renderIcon(CodeOutlined),
    path: '/admin/flows',
  },
  {
    label: '用户管理',
    key: 'AdminUserManager',
    icon: renderIcon(TeamOutlined),
    path: '/admin/users',
  },
  {
    label: 'MCP Server',
    key: 'AdminMCPManager',
    icon: renderIcon(CloudServerOutlined),
    path: '/admin/mcp',
  },
  {
    label: '系统设置',
    key: 'AdminSystemSettings',
    icon: renderIcon(SettingOutlined),
    path: '/admin/system',
  },
]

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

function handleMenuSelect(key: string) {
  const item = adminMenuOptions.find(o => o.key === key)
  if (item) router.push(item.path)
}
</script>

<style scoped lang="scss">
.admin-layout {
  height: 100vh;

  &__sider {
    .admin-logo {
      height: 56px;
      display: flex;
      align-items: center;
      padding: 0 20px;
      gap: 12px;
      border-bottom: 1px solid var(--border-color);

      &__icon { width: 28px; height: 28px; }
      &__text {
        font-size: 16px;
        font-weight: 600;
        white-space: nowrap;
        color: var(--text-primary);
      }
    }
  }

  &__main {
    display: flex;
    flex-direction: column;
  }

  &__header {
    height: 56px;
    padding: 0 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__content {
    flex: 1;
    overflow: auto;
    background: var(--content-bg);

    &-inner {
      padding: 24px;
      max-width: 1200px;
      margin: 0 auto;
    }
  }
}
</style>
```

### 2.5 AppSidebar.vue — 左侧导航组件

```vue
<!-- src/components/layout/AppSidebar.vue -->
<template>
  <div class="app-sidebar">
    <!-- Logo 区 -->
    <div class="app-sidebar__logo" @click="$router.push('/')">
      <img src="/logo.svg" alt="OmicsHub" class="logo-img" />
      <span v-if="!collapsed" class="logo-text">OmicsHub</span>
    </div>

    <!-- 主导航菜单 -->
    <n-menu
      class="app-sidebar__menu"
      :value="activeKey"
      :collapsed="collapsed"
      :collapsed-width="64"
      :options="mainMenuOptions"
      :render-label="renderMenuLabel"
      @update:value="handleMenuSelect"
    />

    <!-- 底部操作区 -->
    <div class="app-sidebar__footer" v-if="!collapsed">
      <n-divider style="margin: 8px 0" />
      <n-button text block @click="$router.push('/profile')">
        <template #icon><n-icon><SettingOutlined /></n-icon></template>
        设置
      </n-button>
    </div>

    <!-- 折叠时的底部图标 -->
    <div class="app-sidebar__footer-collapsed" v-else>
      <n-button text circle @click="$router.push('/profile')">
        <template #icon><n-icon><SettingOutlined /></n-icon></template>
      </n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NMenu, NButton, NIcon, NDivider } from 'naive-ui'
import {
  DashboardOutlined,
  FolderOutlined,
  ApartmentOutlined,
  ExperimentOutlined,
  SettingOutlined,
  SafetyCertificateOutlined,
} from '@vicons/antd'
import type { MenuOption } from 'naive-ui'
import { useAuthStore } from '@/stores/modules/auth'

const props = defineProps<{ collapsed: boolean }>()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const activeKey = computed(() => {
  // 如果当前路由有 activeMenu 元信息，使用它高亮父菜单
  const activeMenu = route.meta?.activeMenu
  return (activeMenu as string) || (route.name as string)
})

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

function renderMenuLabel(option: MenuOption) {
  return h('span', {}, option.label as string)
}

const mainMenuOptions = computed<MenuOption[]>(() => {
  const items: MenuOption[] = [
    {
      label: '仪表盘',
      key: 'Dashboard',
      icon: renderIcon(DashboardOutlined),
      path: '/',
    },
    {
      label: '项目管理',
      key: 'Projects',
      icon: renderIcon(FolderOutlined),
      path: '/projects',
    },
    {
      label: '流程市场',
      key: 'FlowMarket',
      icon: renderIcon(ApartmentOutlined),
      path: '/flows',
    },
    {
      label: '任务中心',
      key: 'TaskList',
      icon: renderIcon(ExperimentOutlined),
      path: '/tasks',
    },
  ]

  // 管理员额外显示管理后台入口
  if (authStore.isAdmin) {
    items.push({
      label: '管理后台',
      key: 'AdminFlowManager',
      icon: renderIcon(SafetyCertificateOutlined),
      path: '/admin',
    })
  }

  return items
})

function handleMenuSelect(key: string) {
  const item = mainMenuOptions.value.find(o => o.key === key)
  if (item && item.path) {
    router.push(item.path)
  }
}
</script>

<style scoped lang="scss">
.app-sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;

  &__logo {
    height: 56px;
    display: flex;
    align-items: center;
    padding: 0 16px;
    gap: 10px;
    cursor: pointer;
    border-bottom: 1px solid var(--border-color);
    transition: background 0.2s;

    &:hover { background: var(--hover-bg); }

    .logo-img { width: 28px; height: 28px; flex-shrink: 0; }
    .logo-text {
      font-size: 16px;
      font-weight: 600;
      white-space: nowrap;
      color: var(--text-primary);
    }
  }

  &__menu {
    flex: 1;
    padding: 8px 0;
  }

  &__footer {
    padding: 0 12px 12px;
  }

  &__footer-collapsed {
    padding: 12px 0;
    display: flex;
    justify-content: center;
  }
}
</style>
```

### 2.6 AppHeader.vue — 顶部 Header 组件

```vue
<!-- src/components/layout/AppHeader.vue -->
<template>
  <div class="app-header">
    <!-- 左侧：面包屑 + 页面标题 -->
    <div class="app-header__left">
      <n-breadcrumb separator="/">
        <n-breadcrumb-item v-for="item in breadcrumbs" :key="item.path">
          <router-link v-if="item.to" :to="item.to">{{ item.title }}</router-link>
          <span v-else>{{ item.title }}</span>
        </n-breadcrumb-item>
      </n-breadcrumb>
    </div>

    <!-- 右侧：操作区 -->
    <div class="app-header__right">
      <!-- AI 面板开关 -->
      <n-tooltip placement="bottom">
        <template #trigger>
          <n-badge :value="chatStore.unreadCount" :max="99" processing>
            <n-button
              text
              circle
              :type="chatStore.panelVisible ? 'primary' : 'default'"
              @click="chatStore.togglePanel()"
            >
              <template #icon>
                <n-icon size="20"><RobotOutlined /></n-icon>
              </template>
            </n-button>
          </n-badge>
        </template>
        {{ chatStore.panelVisible ? '收起 AI 助手' : '展开 AI 助手' }}
      </n-tooltip>

      <!-- 通知中心 -->
      <NotificationBell />

      <!-- 主题切换 -->
      <ThemeToggle />

      <!-- 用户下拉 -->
      <UserDropdown />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NBreadcrumb, NBreadcrumbItem, NButton, NIcon, NTooltip, NBadge } from 'naive-ui'
import { RobotOutlined } from '@vicons/antd'

import ThemeToggle from '@/components/common/ThemeToggle.vue'
import UserDropdown from '@/components/layout/UserDropdown.vue'
import NotificationBell from '@/components/layout/NotificationBell.vue'

import { useChatStore } from '@/stores/modules/chat'

const route = useRoute()
const chatStore = useChatStore()

// ── 面包屑计算 ──
interface BreadcrumbItem {
  title: string
  path: string
  to?: string
}

const breadcrumbs = computed<BreadcrumbItem[]>(() => {
  const items: BreadcrumbItem[] = []
  const matched = route.matched

  for (let i = 0; i < matched.length; i++) {
    const m = matched[i]
    if (m.meta?.title) {
      items.push({
        title: m.meta.title as string,
        path: m.path,
        to: i < matched.length - 1 ? m.path : undefined,
      })
    }
  }

  return items
})
</script>

<style scoped lang="scss">
.app-header {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;

  &__left {
    flex: 1;
    min-width: 0;
  }

  &__right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
}
</style>
```

### 2.7 AIChatFab.vue — AI 面板折叠时的浮动按钮

```vue
<!-- src/components/ai-chat/AIChatFab.vue -->
<template>
  <div
    class="ai-chat-fab"
    :class="{ pulsing: chatStore.unreadCount > 0 }"
    @click="chatStore.togglePanel(true)"
  >
    <n-badge :value="chatStore.unreadCount" :max="99" :show="chatStore.unreadCount > 0">
      <div class="ai-chat-fab__btn">
        <n-icon size="24"><RobotOutlined /></n-icon>
        <span class="fab-label">AI 助手</span>
      </div>
    </n-badge>
  </div>
</template>

<script setup lang="ts">
import { NIcon, NBadge } from 'naive-ui'
import { RobotOutlined } from '@vicons/antd'
import { useChatStore } from '@/stores/modules/chat'

const chatStore = useChatStore()
</script>

<style scoped lang="scss">
.ai-chat-fab {
  position: fixed;
  right: 24px;
  bottom: 32px;
  z-index: 999;
  cursor: pointer;
  transition: transform 0.3s ease;

  &:hover {
    transform: scale(1.05);
  }

  &__btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 12px 20px;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    color: #fff;
    border-radius: 28px;
    box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4);
    font-weight: 500;
    font-size: 14px;

    .fab-label {
      white-space: nowrap;
    }
  }

  &.pulsing {
    animation: pulse-ring 2s ease-in-out infinite;
  }
}

@keyframes pulse-ring {
  0%, 100% { box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.4); }
  50% { box-shadow: 0 0 0 12px rgba(99, 102, 241, 0); }
}
</style>
```

---

## 3. 核心页面组件设计

### 3.1 仪表盘页（DashboardView.vue）

```vue
<!-- src/views/dashboard/DashboardView.vue -->
<template>
  <div class="dashboard-view">
    <!-- 欢迎语 -->
    <div class="dashboard-welcome">
      <h2>{{ welcomeText }}，{{ authStore.user?.display_name || '研究员' }}</h2>
      <p class="text-secondary">这是您今天的工作概览</p>
    </div>

    <!-- 统计卡片 -->
    <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
      <n-grid-item span="4 s:2 l:1">
        <StatCard
          title="进行中任务"
          :value="stats.runningTasks"
          icon="LoadingOutlined"
          color="#6366f1"
          :to="{ name: 'TaskList', query: { status: 'running' } }"
        />
      </n-grid-item>
      <n-grid-item span="4 s:2 l:1">
        <StatCard
          title="已完成任务"
          :value="stats.completedTasks"
          icon="CheckCircleOutlined"
          color="#10b981"
          :to="{ name: 'TaskList', query: { status: 'completed' } }"
        />
      </n-grid-item>
      <n-grid-item span="4 s:2 l:1">
        <StatCard
          title="项目总数"
          :value="stats.projectCount"
          icon="FolderOutlined"
          color="#f59e0b"
          :to="{ name: 'Projects' }"
        />
      </n-grid-item>
      <n-grid-item span="4 s:2 l:1">
        <StatCard
          title="待处理通知"
          :value="stats.notifications"
          icon="BellOutlined"
          color="#ef4444"
        />
      </n-grid-item>
    </n-grid>

    <!-- 快速开始 + 最近任务 -->
    <n-grid :cols="3" :x-gap="16" :y-gap="16" style="margin-top: 20px" responsive="screen">
      <!-- 快速开始 -->
      <n-grid-item span="3 m:1">
        <n-card title="快速开始" class="dashboard-card">
          <n-space vertical>
            <QuickStartItem
              v-for="flow in popularFlows"
              :key="flow.id"
              :flow="flow"
              @click="handleQuickStart(flow)"
            />
          </n-space>
        </n-card>
      </n-grid-item>

      <!-- 最近任务 -->
      <n-grid-item span="3 m:2">
        <n-card title="最近任务" class="dashboard-card">
          <TaskTableLite
            :tasks="recentTasks"
            :loading="loading"
            @row-click="handleTaskClick"
          />
          <template #header-extra>
            <n-button text type="primary" @click="$router.push({ name: 'TaskList' })">
              查看全部
              <template #icon><n-icon><ArrowRightOutlined /></n-icon></template>
            </n-button>
          </template>
        </n-card>
      </n-grid-item>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NGrid, NGridItem, NCard, NSpace, NButton, NIcon } from 'naive-ui'
import {
  LoadingOutlined, CheckCircleOutlined, FolderOutlined, BellOutlined, ArrowRightOutlined,
} from '@vicons/antd'

import StatCard from '@/components/dashboard/StatCard.vue'
import QuickStartItem from '@/components/dashboard/QuickStartItem.vue'
import TaskTableLite from '@/components/task/TaskTableLite.vue'

import { useAuthStore } from '@/stores/modules/auth'
import { useTaskStore } from '@/stores/modules/task'
import { useFlowStore } from '@/stores/modules/flow'
import type { FlowSummary } from '@/types/flow'

const router = useRouter()
const authStore = useAuthStore()
const taskStore = useTaskStore()
const flowStore = useFlowStore()

const loading = ref(false)
const stats = ref({
  runningTasks: 0,
  completedTasks: 0,
  projectCount: 0,
  notifications: 0,
})

const recentTasks = computed(() => taskStore.recentTasks)
const popularFlows = computed<FlowSummary[]>(() => flowStore.popularFlows)

const welcomeText = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 9) return '早上好'
  if (hour < 12) return '上午好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

async function loadDashboardData() {
  loading.value = true
  try {
    await Promise.all([
      taskStore.fetchStats().then(s => { stats.value = s }),
      taskStore.fetchRecentTasks(5),
      flowStore.fetchPopularFlows(),
    ])
  } finally {
    loading.value = false
  }
}

function handleQuickStart(flow: FlowSummary) {
  router.push({
    name: 'TaskSubmit',
    query: { flow: flow.id },
  })
}

function handleTaskClick(taskId: string) {
  router.push({ name: 'TaskDetail', params: { id: taskId } })
}

onMounted(loadDashboardData)
</script>

<style scoped lang="scss">
.dashboard-view {
  .dashboard-welcome {
    margin-bottom: 20px;

    h2 { font-size: 22px; font-weight: 600; margin-bottom: 4px; }
    .text-secondary { color: var(--text-secondary); font-size: 14px; }
  }

  .dashboard-card {
    height: 100%;
  }
}
</style>
```

### 3.2 任务提交页（TaskSubmitView.vue）— 核心页面

```vue
<!-- src/views/task/TaskSubmitView.vue -->
<template>
  <div class="task-submit-view">
    <!-- 步骤条 -->
    <n-steps :current="currentStep" size="small" style="margin-bottom: 24px">
      <n-step title="选择流程" description="选择分析流程" />
      <n-step title="配置参数" description="填写分析参数" />
      <n-step title="确认提交" description="检查并提交" />
    </n-steps>

    <!-- Step 1: 选择流程 & 项目 -->
    <div v-if="currentStep === 1" class="step-panel">
      <n-grid :cols="2" :x-gap="16">
        <n-grid-item>
          <FlowSelector
            v-model="selectedFlowId"
            :flows="flowStore.flowList"
            @select="onFlowSelect"
          />
        </n-grid-item>
        <n-grid-item>
          <ProjectSelector
            v-model="selectedProjectId"
            :projects="projectStore.projectList"
            @select="onProjectSelect"
            @create="showCreateProject = true"
          />
        </n-grid-item>
      </n-grid>

      <div class="step-actions">
        <n-button type="primary" size="large" :disabled="!canNextStep1" @click="currentStep = 2">
          下一步 <template #icon><n-icon><ArrowRightOutlined /></n-icon></template>
        </n-button>
      </div>
    </div>

    <!-- Step 2: 动态表单 -->
    <div v-if="currentStep === 2" class="step-panel">
      <n-spin :show="parsingYaml">
        <template #description>正在解析流程参数...</template>

        <DynamicForm
          v-if="flowSchema"
          ref="dynamicFormRef"
          :schema="flowSchema"
          :project-id="selectedProjectId!"
          :flow-id="selectedFlowId!"
          v-model="formValues"
        />

        <n-empty v-else description="请先选择流程" />
      </n-spin>

      <div class="step-actions">
        <n-button size="large" @click="currentStep = 1">上一步</n-button>
        <n-button type="primary" size="large" :disabled="!flowSchema" @click="handlePreview">
          下一步 <template #icon><n-icon><ArrowRightOutlined /></n-icon></template>
        </n-button>
      </div>
    </div>

    <!-- Step 3: 确认提交 -->
    <div v-if="currentStep === 3" class="step-panel">
      <TaskSubmitPreview
        :flow="selectedFlow"
        :project="selectedProject"
        :params="formValues"
        @edit="currentStep = 2"
      />

      <div class="step-actions">
        <n-button size="large" @click="currentStep = 2">上一步</n-button>
        <n-button
          type="primary"
          size="large"
          :loading="submitting"
          @click="handleSubmit"
        >
          确认提交 <template #icon><n-icon><SendOutlined /></n-icon></template>
        </n-button>
      </div>
    </div>

    <!-- 创建项目弹窗 -->
    <CreateProjectModal v-model:show="showCreateProject" @created="onProjectCreated" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NSteps, NStep, NGrid, NGridItem, NButton, NIcon, NSpin, NEmpty } from 'naive-ui'
import { ArrowRightOutlined, SendOutlined } from '@vicons/antd'

import FlowSelector from '@/components/task/submit/FlowSelector.vue'
import ProjectSelector from '@/components/task/submit/ProjectSelector.vue'
import DynamicForm from '@/components/dynamic-form/DynamicForm.vue'
import TaskSubmitPreview from '@/components/task/submit/TaskSubmitPreview.vue'
import CreateProjectModal from '@/components/project/CreateProjectModal.vue'

import { useFlowStore } from '@/stores/modules/flow'
import { useProjectStore } from '@/stores/modules/project'
import { useTaskStore } from '@/stores/modules/task'
import type { FlowSchema } from '@/types/flow'
import { message } from '@/utils/naiveMessage'

const route = useRoute()
const router = useRouter()
const flowStore = useFlowStore()
const projectStore = useProjectStore()
const taskStore = useTaskStore()

// ── 步骤控制 ──
const currentStep = ref(1)
const submitting = ref(false)
const parsingYaml = ref(false)
const showCreateProject = ref(false)
const dynamicFormRef = ref<InstanceType<typeof DynamicForm>>()

// ── 选择状态 ──
const selectedFlowId = ref<string | null>(
  (route.query.flow as string) || null
)
const selectedProjectId = ref<string | null>(
  (route.query.project as string) || null
)
const flowSchema = ref<FlowSchema | null>(null)
const formValues = ref<Record<string, any>>({})

// ── 计算属性 ──
const selectedFlow = computed(() =>
  flowStore.flowList.find(f => f.id === selectedFlowId.value)
)
const selectedProject = computed(() =>
  projectStore.projectList.find(p => p.id === selectedProjectId.value)
)
const canNextStep1 = computed(() =>
  Boolean(selectedFlowId.value && selectedProjectId.value)
)

// ── 方法 ──
async function onFlowSelect(flowId: string) {
  selectedFlowId.value = flowId
  parsingYaml.value = true
  try {
    flowSchema.value = await flowStore.fetchFlowSchema(flowId)
    // 初始化表单默认值
    formValues.value = flowStore.getDefaultValues(flowSchema.value)
  } catch (err: any) {
    message.error('流程参数解析失败: ' + err.message)
  } finally {
    parsingYaml.value = false
  }
}

function onProjectSelect(projectId: string) {
  selectedProjectId.value = projectId
}

function onProjectCreated(projectId: string) {
  selectedProjectId.value = projectId
  projectStore.fetchProjectList()
}

function handlePreview() {
  const valid = dynamicFormRef.value?.validate()
  if (!valid) {
    message.warning('请检查表单填写是否正确')
    return
  }
  currentStep.value = 3
}

async function handleSubmit() {
  if (!selectedFlowId.value || !selectedProjectId.value) return

  submitting.value = true
  try {
    const taskId = await taskStore.submitTask({
      flow_id: selectedFlowId.value,
      project_id: selectedProjectId.value,
      params: formValues.value,
    })
    message.success('任务提交成功！')
    router.push({ name: 'TaskDetail', params: { id: taskId } })
  } catch (err: any) {
    message.error('提交失败: ' + err.message)
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  flowStore.fetchFlowList()
  projectStore.fetchProjectList()
  // URL 中已指定流程时自动加载
  if (selectedFlowId.value) {
    onFlowSelect(selectedFlowId.value)
  }
})
</script>

<style scoped lang="scss">
.task-submit-view {
  max-width: 1200px;
  margin: 0 auto;

  .step-panel {
    animation: slideIn 0.3s ease;
  }

  .step-actions {
    display: flex;
    justify-content: center;
    gap: 12px;
    margin-top: 32px;
    padding-top: 20px;
    border-top: 1px solid var(--border-color);
  }
}

@keyframes slideIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
```

### 3.3 DynamicForm.vue — 动态表单渲染器（核心组件）

```vue
<!-- src/components/dynamic-form/DynamicForm.vue -->
<template>
  <div class="dynamic-form">
    <!-- 表单头部：流程信息 -->
    <div class="dynamic-form__header" v-if="schema">
      <h3>{{ schema.title || '参数配置' }}</h3>
      <p class="text-secondary">{{ schema.description }}</p>
    </div>

    <!-- 按 Section 渲染 -->
    <n-form
      v-if="schema"
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-placement="top"
      size="medium"
    >
      <template v-for="section in schema.sections" :key="section.key">
        <SectionCollapsible
          :title="section.title"
          :description="section.description"
          :default-collapsed="section.collapsed"
        >
          <!-- Section 内的字段 -->
          <template v-for="field in section.fields" :key="field.key">
            <ConditionRenderer
              :field="field"
              :form-data="formData"
              :context="{ projectId, flowId }"
            >
              <FormFieldRenderer
                v-model="formData[field.key]"
                :field="field"
                :form-data="formData"
                @update:model-value="onFieldChange(field.key, $event)"
              />
            </ConditionRenderer>
          </template>

          <!-- 可重复的 Group -->
          <template v-if="section.repeatable">
            <GroupRepeater
              v-model="formData[section.key]"
              :section="section"
              :context="{ projectId, flowId }"
            />
          </template>
        </SectionCollapsible>

        <n-divider style="margin: 8px 0" />
      </template>
    </n-form>

    <!-- 空状态 -->
    <n-empty v-else description="暂无可配置参数" />
  </div>
</template>

<script setup lang="ts">
import { computed, watch, ref } from 'vue'
import { NForm, NDivider, NEmpty } from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'

import SectionCollapsible from './SectionCollapsible.vue'
import FormFieldRenderer from './FormFieldRenderer.vue'
import ConditionRenderer from './ConditionRenderer.vue'
import GroupRepeater from './GroupRepeater.vue'

import type { FlowSchema, FormField } from '@/types/flow'
import { buildValidationRules } from './validation'
import { getDefaultValuesFromSchema } from './utils'

const props = defineProps<{
  schema: FlowSchema | null
  projectId: string
  flowId: string
  modelValue: Record<string, any>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: Record<string, any>): void
}>()

const formRef = ref<FormInst>()

// ── 表单数据（本地副本 + 同步父组件） ──
const formData = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

// ── 校验规则 ──
const formRules = computed<FormRules>(() => {
  if (!props.schema) return {}
  return buildValidationRules(props.schema)
})

// ── schema 变化时重置默认值 ──
watch(
  () => props.schema,
  (newSchema) => {
    if (newSchema) {
      const defaults = getDefaultValuesFromSchema(newSchema)
      emit('update:modelValue', { ...defaults, ...props.modelValue })
    }
  },
  { immediate: true }
)

// ── 字段变更回调（用于联动） ──
function onFieldChange(key: string, value: any) {
  // 触发条件渲染重新计算
  // 由 ConditionRenderer 内部通过 watch formData 处理
}

// ── 公开方法：校验 ──
async function validate(): Promise<boolean> {
  try {
    await formRef.value?.validate()
    return true
  } catch {
    return false
  }
}

// ── 公开方法：获取纯净数据 ──
function getCleanValues(): Record<string, any> {
  // 移除内部辅助字段
  const cleaned: Record<string, any> = {}
  if (!props.schema) return cleaned

  for (const section of props.schema.sections) {
    for (const field of section.fields) {
      if (field.key in formData.value) {
        cleaned[field.key] = formData.value[field.key]
      }
    }
  }
  return cleaned
}

defineExpose({ validate, getCleanValues })
</script>

<style scoped lang="scss">
.dynamic-form {
  &__header {
    margin-bottom: 20px;

    h3 { font-size: 18px; font-weight: 600; margin-bottom: 4px; }
    .text-secondary { color: var(--text-secondary); font-size: 14px; }
  }
}
</style>
```

### 3.4 FormFieldRenderer.vue — 字段渲染器（根据 type 分发）

```typescript
// src/components/dynamic-form/FormFieldRenderer.vue
// 该组件根据字段类型自动分发到对应的渲染组件

import type { FormField } from '@/types/flow'

// 支持的字段类型映射
export const FIELD_TYPE_MAP: Record<string, string> = {
  // 基础输入
  'string': 'StringField',
  'text': 'TextField',          // 多行文本
  'number': 'NumberField',
  'integer': 'IntegerField',
  'float': 'FloatField',
  'boolean': 'BooleanField',     // 开关

  // 选择类
  'select': 'SelectField',       // 单选下拉
  'multi-select': 'MultiSelectField',
  'radio': 'RadioField',         // 单选按钮组
  'checkbox': 'CheckboxField',   // 多选框组

  // 文件/样本
  'file': 'FileField',           // 文件选择（从项目文件中选）
  'file-upload': 'FileUploadField', // 本地上传
  'sample': 'SampleField',       // 样本选择
  'sample-sheet': 'SampleSheetField', // 样本表上传/编辑

  // 范围/数组
  'range': 'RangeField',         // 数值范围
  'array': 'ArrayField',         // 字符串数组

  // 特殊
  'ref': 'RefField',             // 引用其他参数
  'group': 'GroupField',         // 嵌套组（内联）
  'divider': 'DividerField',     // 仅显示分隔线
  'info': 'InfoField',           // 仅显示提示文本
}
```

```vue
<!-- src/components/dynamic-form/FormFieldRenderer.vue -->
<template>
  <div class="form-field-renderer">
    <!-- 动态分发到具体组件 -->
    <component
      :is="fieldComponent"
      v-model="modelValue"
      :field="field"
      :form-data="formData"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { FormField } from '@/types/flow'

import StringField from './fields/StringField.vue'
import TextField from './fields/TextField.vue'
import NumberField from './fields/NumberField.vue'
import BooleanField from './fields/BooleanField.vue'
import SelectField from './fields/SelectField.vue'
import MultiSelectField from './fields/MultiSelectField.vue'
import RadioField from './fields/RadioField.vue'
import CheckboxField from './fields/CheckboxField.vue'
import FileField from './fields/FileField.vue'
import FileUploadField from './fields/FileUploadField.vue'
import SampleField from './fields/SampleField.vue'
import SampleSheetField from './fields/SampleSheetField.vue'
import RangeField from './fields/RangeField.vue'
import ArrayField from './fields/ArrayField.vue'
import RefField from './fields/RefField.vue'
import GroupField from './fields/GroupField.vue'
import DividerField from './fields/DividerField.vue'
import InfoField from './fields/InfoField.vue'

const props = defineProps<{
  modelValue: any
  field: FormField
  formData: Record<string, any>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: any): void
}>()

// v-model 双向绑定
const modelValue = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

// 根据字段类型分发组件
const fieldComponent = computed(() => {
  const map: Record<string, any> = {
    'string': StringField,
    'text': TextField,
    'number': NumberField,
    'integer': NumberField,
    'float': NumberField,
    'boolean': BooleanField,
    'select': SelectField,
    'multi-select': MultiSelectField,
    'radio': RadioField,
    'checkbox': CheckboxField,
    'file': FileField,
    'file-upload': FileUploadField,
    'sample': SampleField,
    'sample-sheet': SampleSheetField,
    'range': RangeField,
    'array': ArrayField,
    'ref': RefField,
    'group': GroupField,
    'divider': DividerField,
    'info': InfoField,
  }
  return map[props.field.type] || StringField
})
</script>
```

### 3.5 任务详情页（TaskDetailView.vue）— 核心页面

```vue
<!-- src/views/task/TaskDetailView.vue -->
<template>
  <div class="task-detail-view">
    <!-- 页面加载中 -->
    <n-spin v-if="loading" size="large" style="display: block; text-align: center; padding: 60px">
      <template #description>加载任务信息...</template>
    </n-spin>

    <template v-else-if="task">
      <!-- 任务头部 -->
      <TaskDetailHeader
        :task="task"
        @cancel="handleCancel"
        @retry="handleRetry"
        @delete="handleDelete"
      />

      <!-- 进度条（运行中时显示） -->
      <TaskProgressBar
        v-if="['queued', 'running', 'cancelling'].includes(task.status)"
        :status="task.status"
        :progress="task.progress"
        :step="task.current_step"
        :total-steps="task.total_steps"
        :start-time="task.started_at"
      />

      <!-- 标签页 -->
      <n-tabs v-model:value="activeTab" type="line" animated class="task-tabs">
        <!-- 概览 -->
        <n-tab-pane name="overview" tab="概览">
          <TaskOverviewTab :task="task" />
        </n-tab-pane>

        <!-- 日志（WebSocket 实时） -->
        <n-tab-pane name="logs" tab="日志">
          <TaskLogViewer :task-id="taskId" :status="task.status" />
        </n-tab-pane>

        <!-- 结果 -->
        <n-tab-pane name="results" tab="结果">
          <TaskResultViewer
            :task-id="taskId"
            :output-dir="task.output_dir"
            :status="task.status"
          />
        </n-tab-pane>

        <!-- 参数 -->
        <n-tab-pane name="params" tab="参数">
          <TaskParamsTab
            :params="task.params"
            :flow-id="task.flow_id"
          />
        </n-tab-pane>
      </n-tabs>
    </template>

    <!-- 错误状态 -->
    <n-result
      v-else
      status="404"
      title="任务不存在"
      description="该任务可能已被删除或您无权查看"
    >
      <template #footer>
        <n-button @click="$router.push({ name: 'TaskList' })">返回任务列表</n-button>
      </template>
    </n-result>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NTabs, NTabPane, NSpin, NResult, NButton } from 'naive-ui'

import TaskDetailHeader from '@/components/task/detail/TaskDetailHeader.vue'
import TaskProgressBar from '@/components/task/detail/TaskProgressBar.vue'
import TaskOverviewTab from '@/components/task/detail/TaskOverviewTab.vue'
import TaskLogViewer from '@/components/task/detail/TaskLogViewer.vue'
import TaskResultViewer from '@/components/task/detail/TaskResultViewer.vue'
import TaskParamsTab from '@/components/task/detail/TaskParamsTab.vue'

import { useTaskStore } from '@/stores/modules/task'
import { useChatStore } from '@/stores/modules/chat'
import { message } from '@/utils/naiveMessage'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const chatStore = useChatStore()

const taskId = computed(() => route.params.id as string)
const task = computed(() => taskStore.currentTask)
const loading = ref(false)
const activeTab = ref('overview')

// ── 轮询状态（运行中时） ──
let pollTimer: ReturnType<typeof setInterval> | null = null

function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => {
    if (['running', 'queued', 'cancelling'].includes(task.value?.status || '')) {
      taskStore.fetchTaskDetail(taskId.value)
    } else {
      stopPolling()
    }
  }, 3000) // 3 秒轮询
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ── 操作 ──
async function handleCancel() {
  try {
    await taskStore.cancelTask(taskId.value)
    message.success('任务已取消')
  } catch (err: any) {
    message.error('取消失败: ' + err.message)
  }
}

async function handleRetry() {
  try {
    const newTaskId = await taskStore.retryTask(taskId.value)
    message.success('已重新提交任务')
    router.push({ name: 'TaskDetail', params: { id: newTaskId } })
  } catch (err: any) {
    message.error('重试失败: ' + err.message)
  }
}

async function handleDelete() {
  try {
    await taskStore.deleteTask(taskId.value)
    message.success('任务已删除')
    router.push({ name: 'TaskList' })
  } catch (err: any) {
    message.error('删除失败: ' + err.message)
  }
}

// ── 生命周期 ──
onMounted(async () => {
  loading.value = true
  try {
    await taskStore.fetchTaskDetail(taskId.value)
    // 设置 AI 上下文
    chatStore.setCurrentTask(taskId.value)
    // 启动轮询
    startPolling()
  } catch (err: any) {
    message.error('加载失败: ' + err.message)
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  stopPolling()
  taskStore.clearCurrentTask()
  chatStore.clearCurrentTask()
})
</script>

<style scoped lang="scss">
.task-detail-view {
  .task-tabs {
    margin-top: 16px;
  }
}
</style>
```

### 3.6 TaskLogViewer.vue — 实时日志查看器

```vue
<!-- src/components/task/detail/TaskLogViewer.vue -->
<template>
  <div class="task-log-viewer">
    <!-- 工具栏 -->
    <div class="log-toolbar">
      <n-space>
        <!-- 日志级别筛选 -->
        <n-select
          v-model:value="levelFilter"
          :options="levelOptions"
          size="small"
          style="width: 120px"
          placeholder="日志级别"
          clearable
        />
        <!-- 搜索 -->
        <n-input
          v-model:value="searchKeyword"
          size="small"
          placeholder="搜索日志..."
          clearable
          style="width: 200px"
        >
          <template #prefix><n-icon><SearchOutlined /></n-icon></template>
        </n-input>
      </n-space>

      <n-space>
        <!-- 自动滚动开关 -->
        <n-tooltip>
          <template #trigger>
            <n-button
              text
              :type="autoScroll ? 'primary' : 'default'"
              @click="autoScroll = !autoScroll"
            >
              <template #icon><n-icon><ToBottomOutlined /></n-icon></template>
            </n-button>
          </template>
          自动滚动
        </n-tooltip>

        <!-- 清空 -->
        <n-tooltip>
          <template #trigger>
            <n-button text @click="logs = []">
              <template #icon><n-icon><DeleteOutlined /></n-icon></template>
            </n-button>
          </template>
          清空
        </n-tooltip>

        <!-- 下载 -->
        <n-tooltip>
          <template #trigger>
            <n-button text @click="downloadLogs">
              <template #icon><n-icon><DownloadOutlined /></n-icon></template>
            </n-button>
          </template>
          下载日志
        </n-tooltip>
      </n-space>
    </div>

    <!-- 日志内容区 -->
    <div ref="logContainerRef" class="log-container" @scroll="handleScroll">
      <!-- WebSocket 连接状态 -->
      <div v-if="!wsConnected" class="log-status-bar" :class="wsStatusClass">
        <n-icon size="14"><WifiOutlined /></n-icon>
        <span>{{ wsStatusText }}</span>
        <n-button text size="tiny" @click="reconnect">重连</n-button>
      </div>

      <!-- 日志行 -->
      <div
        v-for="(log, index) in filteredLogs"
        :key="index"
        class="log-line"
        :class="`log-level-${log.level}`"
      >
        <span class="log-timestamp">{{ formatTime(log.timestamp) }}</span>
        <span class="log-level-tag" :class="`tag-${log.level}`">{{ log.level }}</span>
        <span class="log-message" v-html="renderAnsi(log.message)" />
      </div>

      <!-- 空状态 -->
      <n-empty v-if="filteredLogs.length === 0" description="暂无日志" />

      <!-- 实时指示器 -->
      <div v-if="isReceiving" class="log-live-indicator">
        <span class="live-dot"></span>
        实时接收中...
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import {
  NSelect, NInput, NButton, NIcon, NTooltip, NSpace, NEmpty,
} from 'naive-ui'
import {
  SearchOutlined, ToBottomOutlined, DeleteOutlined,
  DownloadOutlined, WifiOutlined,
} from '@vicons/antd'
import { useTaskLogWebSocket } from '@/composables/useTaskLogWebSocket'
import { formatTime } from '@/utils/time'
import { renderAnsi } from '@/utils/ansi'

const props = defineProps<{
  taskId: string
  status: string
}>()

// ── 状态 ──
const logContainerRef = ref<HTMLDivElement>()
const logs = ref<LogEntry[]>([])
const levelFilter = ref<string | null>(null)
const searchKeyword = ref('')
const autoScroll = ref(true)
const isReceiving = ref(false)
let receiveTimer: ReturnType<typeof setTimeout> | null = null

// ── WebSocket ──
const { connect, disconnect, connected: wsConnected, status: wsStatus } = useTaskLogWebSocket({
  onMessage: (entry: LogEntry) => {
    logs.value.push(entry)
    isReceiving.value = true
    // 防抖显示接收指示器
    if (receiveTimer) clearTimeout(receiveTimer)
    receiveTimer = setTimeout(() => { isReceiving.value = false }, 500)
  },
  onOpen: () => {
    // 连接成功后发送订阅消息
    sendSubscribe()
  },
})

function sendSubscribe() {
  const ws = (useTaskLogWebSocket as any)._ws
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'subscribe', task_id: props.taskId }))
  }
}

function reconnect() {
  disconnect()
  connect(`/api/v1/ws/tasks/${props.taskId}/logs`)
}

// ── 筛选 ──
const levelOptions = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
  { label: 'CRITICAL', value: 'CRITICAL' },
]

const filteredLogs = computed(() => {
  let result = logs.value
  if (levelFilter.value) {
    result = result.filter(l => l.level === levelFilter.value)
  }
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    result = result.filter(l => l.message.toLowerCase().includes(kw))
  }
  return result
})

// ── WebSocket 状态文本 ──
const wsStatusText = computed(() => {
  if (wsConnected.value) return '已连接'
  if (wsStatus.value === 'connecting') return '连接中...'
  return '连接断开'
})

const wsStatusClass = computed(() => ({
  'status-connected': wsConnected.value,
  'status-connecting': wsStatus.value === 'connecting',
  'status-disconnected': !wsConnected.value && wsStatus.value !== 'connecting',
}))

// ── 自动滚动 ──
watch(filteredLogs, async () => {
  if (autoScroll.value) {
    await nextTick()
    scrollToBottom()
  }
}, { deep: true })

function scrollToBottom() {
  const el = logContainerRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function handleScroll() {
  const el = logContainerRef.value
  if (!el) return
  // 用户手动滚动时暂停自动滚动
  const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
  autoScroll.value = isAtBottom
}

// ── 下载 ──
function downloadLogs() {
  const content = logs.value.map(l =>
    `[${l.timestamp}] [${l.level}] ${l.message}`
  ).join('\n')
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `task-${props.taskId}-logs.txt`
  a.click()
  URL.revokeObjectURL(url)
}

// ── 生命周期 ──
onMounted(() => {
  connect(`/api/v1/ws/tasks/${props.taskId}/logs`)
})

onUnmounted(() => {
  disconnect()
  if (receiveTimer) clearTimeout(receiveTimer)
})

// ── 类型 ──
interface LogEntry {
  timestamp: string
  level: string
  message: string
  source?: string
}
</script>

<style scoped lang="scss">
.task-log-viewer {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 280px);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;

  .log-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color);
    background: var(--toolbar-bg);
    flex-shrink: 0;
  }

  .log-container {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.7;
    background: var(--log-bg, #0d1117);
  }

  .log-status-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    margin: -12px -12px 8px;
    font-size: 12px;

    &.status-connected { background: rgba(16, 185, 129, 0.1); color: #10b981; }
    &.status-connecting { background: rgba(245, 158, 11, 0.1); color: #f59e0b; }
    &.status-disconnected { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
  }

  .log-line {
    display: flex;
    gap: 10px;
    padding: 2px 0;
    border-bottom: 1px solid rgba(255,255,255,0.03);

    .log-timestamp {
      color: #6b7280;
      flex-shrink: 0;
      width: 84px;
    }

    .log-level-tag {
      flex-shrink: 0;
      width: 60px;
      text-align: center;
      border-radius: 3px;
      font-size: 11px;
      font-weight: 600;
      padding: 0 4px;

      &.tag-DEBUG { background: rgba(107, 114, 128, 0.2); color: #9ca3af; }
      &.tag-INFO { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }
      &.tag-WARNING { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
      &.tag-ERROR { background: rgba(239, 68, 68, 0.2); color: #f87171; }
      &.tag-CRITICAL { background: rgba(185, 28, 28, 0.3); color: #fca5a5; }
    }

    .log-message {
      flex: 1;
      word-break: break-all;
      color: #e5e7eb;
    }
  }

  .log-live-indicator {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 0;
    color: #10b981;
    font-size: 12px;

    .live-dot {
      width: 8px; height: 8px;
      background: #10b981;
      border-radius: 50%;
      animation: pulse 1.5s ease infinite;
    }
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
```

### 3.7 TaskResultViewer.vue — 结果查看器

```vue
<!-- src/components/task/detail/TaskResultViewer.vue -->
<template>
  <div class="task-result-viewer">
    <!-- 文件浏览器侧边栏 + 预览区 -->
    <n-split direction="horizontal" :max="0.5" :min="0.2" default-size="0.28">
      <!-- 文件树 -->
      <template #1>
        <div class="file-tree-panel">
          <n-input
            v-model:value="fileSearch"
            size="small"
            placeholder="搜索文件..."
            clearable
          >
            <template #prefix><n-icon><SearchOutlined /></n-icon></template>
          </n-input>

          <n-spin :show="loadingFiles">
            <n-tree
              :data="fileTree"
              :pattern="fileSearch"
              :render-prefix="renderFileIcon"
              selectable
              block-line
              @update:selected-keys="onFileSelect"
            />
          </n-spin>
        </div>
      </template>

      <!-- 预览区 -->
      <template #2>
        <div class="preview-panel">
          <template v-if="selectedFile">
            <!-- 工具栏 -->
            <div class="preview-toolbar">
              <span class="file-name">{{ selectedFile.name }}</span>
              <n-space>
                <n-button size="small" @click="copyPath">复制路径</n-button>
                <n-button size="small" type="primary" @click="downloadFile">
                  <template #icon><n-icon><DownloadOutlined /></n-icon></template>
                  下载
                </n-button>
              </n-space>
            </div>

            <!-- 根据类型选择预览组件 -->
            <div class="preview-content">
              <CsvTablePreview
                v-if="isCsvFile"
                :task-id="taskId"
                :file-path="selectedFile.path"
              />
              <ImagePreview
                v-else-if="isImageFile"
                :task-id="taskId"
                :file-path="selectedFile.path"
              />
              <HtmlReportPreview
                v-else-if="isHtmlFile"
                :task-id="taskId"
                :file-path="selectedFile.path"
              />
              <TextPreview
                v-else-if="isTextFile"
                :task-id="taskId"
                :file-path="selectedFile.path"
              />
              <n-empty v-else description="该文件类型暂不支持在线预览">
                <template #extra>
                  <n-button @click="downloadFile">下载查看</n-button>
                </template>
              </n-empty>
            </div>
          </template>

          <n-empty v-else description="请选择左侧文件进行预览" />
        </div>
      </template>
    </n-split>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NSplit, NInput, NIcon, NTree, NSpin, NButton, NSpace, NEmpty,
} from 'naive-ui'
import { SearchOutlined, DownloadOutlined } from '@vicons/antd'
import CsvTablePreview from './previews/CsvTablePreview.vue'
import ImagePreview from './previews/ImagePreview.vue'
import HtmlReportPreview from './previews/HtmlReportPreview.vue'
import TextPreview from './previews/TextPreview.vue'
import { useTaskResult } from '@/composables/useTaskResult'

const props = defineProps<{
  taskId: string
  outputDir: string
  status: string
}>()

const fileSearch = ref('')
const selectedFile = ref<ResultFile | null>(null)
const { fileTree, loading: loadingFiles, fetchFileList } = useTaskResult()

// ── 文件类型判断 ──
const fileExt = computed(() => selectedFile.value?.name.split('.').pop()?.toLowerCase() || '')
const isCsvFile = computed(() => ['csv', 'tsv', 'txt'].includes(fileExt.value))
const isImageFile = computed(() => ['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(fileExt.value))
const isHtmlFile = computed(() => ['html', 'htm'].includes(fileExt.value))
const isTextFile = computed(() => ['log', 'md', 'json', 'yaml', 'yml'].includes(fileExt.value))

// ── 方法 ──
function onFileSelect(keys: string[]) {
  const key = keys[0]
  if (!key) { selectedFile.value = null; return }
  // 从 fileTree 中查找文件节点
  selectedFile.value = findFileByKey(fileTree.value, key)
}

function findFileByKey(nodes: FileTreeNode[], key: string): ResultFile | null {
  for (const node of nodes) {
    if (node.key === key && node.isLeaf) {
      return { name: node.label, path: node.key, size: node.size }
    }
    if (node.children) {
      const found = findFileByKey(node.children, key)
      if (found) return found
    }
  }
  return null
}

function renderFileIcon({ option }: { option: FileTreeNode }) {
  // 根据文件类型返回不同图标
}

function copyPath() {
  if (!selectedFile.value) return
  navigator.clipboard.writeText(selectedFile.value.path)
}

function downloadFile() {
  if (!selectedFile.value) return
  // 调用下载 API
}

onMounted(() => {
  fetchFileList(props.taskId)
})

// ── 类型 ──
interface FileTreeNode {
  key: string
  label: string
  isLeaf?: boolean
  children?: FileTreeNode[]
  size?: number
}
interface ResultFile {
  name: string
  path: string
  size?: number
}
</script>

<style scoped lang="scss">
.task-result-viewer {
  height: calc(100vh - 280px);

  .file-tree-panel {
    height: 100%;
    padding: 12px;
    overflow: auto;
  }

  .preview-panel {
    height: 100%;
    display: flex;
    flex-direction: column;

    .preview-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 12px;
      border-bottom: 1px solid var(--border-color);

      .file-name {
        font-weight: 500;
        font-family: monospace;
      }
    }

    .preview-content {
      flex: 1;
      overflow: auto;
      padding: 12px;
    }
  }
}
</style>
```

### 3.8 流程市场页（FlowMarketView.vue）

```vue
<!-- src/views/flow/FlowMarketView.vue -->
<template>
  <div class="flow-market-view">
    <!-- 搜索与筛选 -->
    <div class="flow-market-toolbar">
      <n-input
        v-model:value="searchQuery"
        placeholder="搜索流程名称、描述..."
        clearable
        style="width: 320px"
      >
        <template #prefix><n-icon><SearchOutlined /></n-icon></template>
      </n-input>

      <n-space>
        <n-select
          v-model:value="categoryFilter"
          :options="categoryOptions"
          placeholder="全部分类"
          clearable
          style="width: 160px"
        />
        <n-select
          v-model:value="sortBy"
          :options="sortOptions"
          style="width: 140px"
        />
      </n-space>
    </div>

    <!-- 流程卡片网格 -->
    <n-spin :show="loading">
      <n-empty v-if="filteredFlows.length === 0" description="暂无匹配的流程" />

      <n-grid v-else :cols="3" :x-gap="16" :y-gap="16" responsive="screen">
        <n-grid-item v-for="flow in filteredFlows" :key="flow.id">
          <FlowCard
            :flow="flow"
            @click="$router.push({ name: 'FlowDetail', params: { id: flow.id } })"
            @use="handleUseFlow(flow)"
          />
        </n-grid-item>
      </n-grid>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NInput, NSelect, NSpace, NSpin, NEmpty, NGrid, NGridItem, NIcon } from 'naive-ui'
import { SearchOutlined } from '@vicons/antd'
import FlowCard from '@/components/flow/FlowCard.vue'
import { useFlowStore } from '@/stores/modules/flow'
import type { FlowSummary } from '@/types/flow'

const router = useRouter()
const flowStore = useFlowStore()

const searchQuery = ref('')
const categoryFilter = ref<string | null>(null)
const sortBy = ref('popular')
const loading = ref(false)

const categoryOptions = [
  { label: '基因组学', value: 'genomics' },
  { label: '转录组学', value: 'transcriptomics' },
  { label: '蛋白质组学', value: 'proteomics' },
  { label: '代谢组学', value: 'metabolomics' },
  { label: '表观遗传学', value: 'epigenomics' },
  { label: '宏基因组学', value: 'metagenomics' },
  { label: '单细胞', value: 'single-cell' },
  { label: '数据预处理', value: 'preprocessing' },
]

const sortOptions = [
  { label: '最热', value: 'popular' },
  { label: '最新', value: 'newest' },
  { label: '名称', value: 'name' },
]

const filteredFlows = computed(() => {
  let result = [...flowStore.flowList]

  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(f =>
      f.name.toLowerCase().includes(q) ||
      f.description?.toLowerCase().includes(q)
    )
  }

  if (categoryFilter.value) {
    result = result.filter(f => f.category === categoryFilter.value)
  }

  switch (sortBy.value) {
    case 'popular': result.sort((a, b) => b.use_count - a.use_count); break
    case 'newest': result.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()); break
    case 'name': result.sort((a, b) => a.name.localeCompare(b.name)); break
  }

  return result
})

function handleUseFlow(flow: FlowSummary) {
  router.push({
    name: 'TaskSubmit',
    query: { flow: flow.id },
  })
}

onMounted(() => {
  flowStore.fetchFlowList()
})
</script>

<style scoped lang="scss">
.flow-market-view {
  .flow-market-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
  }
}
</style>
```

### 3.9 项目管理页（ProjectsView.vue）

```vue
<!-- src/views/project/ProjectsView.vue -->
<template>
  <div class="projects-view">
    <!-- 工具栏 -->
    <div class="projects-toolbar">
      <n-button type="primary" @click="showCreateModal = true">
        <template #icon><n-icon><PlusOutlined /></n-icon></template>
        新建项目
      </n-button>

      <n-input
        v-model:value="searchQuery"
        placeholder="搜索项目..."
        clearable
        style="width: 280px"
      >
        <template #prefix><n-icon><SearchOutlined /></n-icon></template>
      </n-input>
    </div>

    <!-- 项目列表 -->
    <n-data-table
      :columns="columns"
      :data="filteredProjects"
      :loading="loading"
      :pagination="pagination"
      @update:page="pagination.page = $event"
    />

    <!-- 创建项目弹窗 -->
    <CreateProjectModal v-model:show="showCreateModal" @created="onProjectCreated" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NInput, NDataTable, NIcon, NSpace, NPopconfirm, NTag,
} from 'naive-ui'
import { PlusOutlined, SearchOutlined, DeleteOutlined, EnterOutlined } from '@vicons/antd'
import type { DataTableColumns } from 'naive-ui'
import CreateProjectModal from '@/components/project/CreateProjectModal.vue'
import { useProjectStore } from '@/stores/modules/project'
import { useAuthStore } from '@/stores/modules/auth'
import type { Project } from '@/types/project'
import { formatDate } from '@/utils/time'
import { message } from '@/utils/naiveMessage'

const router = useRouter()
const projectStore = useProjectStore()
const authStore = useAuthStore()

const searchQuery = ref('')
const loading = ref(false)
const showCreateModal = ref(false)
const pagination = ref({ page: 1, pageSize: 10 })

const filteredProjects = computed(() => {
  if (!searchQuery.value) return projectStore.projectList
  const q = searchQuery.value.toLowerCase()
  return projectStore.projectList.filter(p =>
    p.name.toLowerCase().includes(q) ||
    p.description?.toLowerCase().includes(q)
  )
})

const columns: DataTableColumns<Project> = [
  { title: '项目名称', key: 'name', sorter: 'default' },
  { title: '描述', key: 'description', ellipsis: { tooltip: true } },
  {
    title: '样本数',
    key: 'sample_count',
    width: 90,
    render: (row) => row.sample_count ?? '-',
  },
  {
    title: '任务数',
    key: 'task_count',
    width: 90,
    render: (row) => row.task_count ?? '-',
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 170,
    render: (row) => formatDate(row.created_at),
  },
  {
    title: '操作',
    key: 'actions',
    width: 180,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, {
          size: 'small', type: 'primary', ghost: true,
          onClick: () => router.push({ name: 'ProjectDetail', params: { id: row.id } }),
        }, { default: () => '进入', icon: () => h(EnterOutlined) }),
        h(NPopconfirm, {
          onPositiveClick: () => handleDelete(row.id),
        }, {
          trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, {
            default: () => '删除',
            icon: () => h(DeleteOutlined),
          }),
          default: () => '确定删除此项目？项目下的所有数据将被删除！',
        }),
      ],
    }),
  },
]

async function handleDelete(id: string) {
  try {
    await projectStore.deleteProject(id)
    message.success('项目已删除')
  } catch (err: any) {
    message.error('删除失败: ' + err.message)
  }
}

function onProjectCreated() {
  projectStore.fetchProjectList()
}

onMounted(() => {
  projectStore.fetchProjectList()
})
</script>

<style scoped lang="scss">
.projects-view {
  .projects-toolbar {
    display: flex;
    justify-content: space-between;
    margin-bottom: 20px;
  }
}
</style>
```



---

## 4. Pinia Store 设计

### 4.1 目录结构

```
src/stores/
├── index.ts              # Pinia 实例创建 & 模块导出
├── types.ts              # Store 共享类型定义
└── modules/
    ├── auth.ts           # 认证状态（token, user, login, logout）
    ├── user.ts           # 用户信息
    ├── project.ts        # 项目数据（列表、当前项目、CRUD）
    ├── flow.ts           # 流程数据（列表、当前流程定义、YAML 解析缓存）
    ├── task.ts           # 任务数据（列表、当前任务、提交、取消）
    ├── chat.ts           # AI 对话状态（会话列表、当前会话、消息、WebSocket 连接）
    ├── mcp.ts            # MCP 状态（Server 列表、工具目录）
    ├── notification.ts   # 全局通知（Toast、消息中心）
    ├── theme.ts          # 主题状态（暗黑/亮色模式）
    └── tab.ts            # 标签页/缓存视图管理
```

### 4.2 Store 入口（index.ts）

```typescript
// src/stores/index.ts
import { createPinia } from 'pinia'

// 导出 Pinia 实例
export const pinia = createPinia()

// ── 模块导出 ──
export { useAuthStore } from './modules/auth'
export { useUserStore } from './modules/user'
export { useProjectStore } from './modules/project'
export { useFlowStore } from './modules/flow'
export { useTaskStore } from './modules/task'
export { useChatStore } from './modules/chat'
export { useMCPStore } from './modules/mcp'
export { useNotificationStore } from './modules/notification'
export { useThemeStore } from './modules/theme'
export { useTabStore } from './modules/tab'

export default pinia
```

### 4.3 Auth Store — 认证状态

```typescript
// src/stores/modules/auth.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '@/api/auth'
import { useThemeStore } from './theme'

/** 用户信息 */
export interface UserInfo {
  id: string
  username: string
  email: string
  display_name: string
  avatar?: string
  role: 'user' | 'admin'
  created_at: string
}

/** Token 对 */
interface TokenPair {
  access_token: string
  refresh_token: string
  expires_in: number
}

export const useAuthStore = defineStore('auth', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const accessToken = ref<string>(localStorage.getItem('access_token') || '')
  const refreshToken = ref<string>(localStorage.getItem('refresh_token') || '')
  const user = ref<UserInfo | null>(null)
  const lastVisitedRoute = ref<string>(localStorage.getItem('last_route') || '/')

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const isLoggedIn = computed(() => Boolean(accessToken.value && user.value))
  const isAdmin = computed(() => user.value?.role === 'admin')
  const tokenHeader = computed(() => ({
    Authorization: `Bearer ${accessToken.value}`,
  }))

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  /** 登录 */
  async function login(credentials: { username: string; password: string }) {
    const resp: TokenPair = await authApi.login(credentials)
    setTokens(resp)
    // 获取用户信息
    await fetchUserInfo()
    return true
  }

  /** 注册 */
  async function register(data: {
    username: string; password: string; email: string; display_name?: string
  }) {
    await authApi.register(data)
    return true
  }

  /** 登出 */
  async function logout() {
    try {
      if (refreshToken.value) {
        await authApi.logout(refreshToken.value)
      }
    } catch {
      // 忽略登出 API 错误
    } finally {
      clearTokens()
      user.value = null
      // 重置主题
      const themeStore = useThemeStore()
      themeStore.$reset()
      // 跳转到登录页
      const router = useRouter()
      router.push({ name: 'Login' })
    }
  }

  /** 获取用户信息 */
  async function fetchUserInfo() {
    try {
      const info = await authApi.getMe()
      user.value = info
      return info
    } catch {
      // Token 失效，尝试刷新
      const refreshed = await tryRefreshToken()
      if (refreshed) {
        return fetchUserInfo()
      }
      throw new Error('获取用户信息失败')
    }
  }

  /** 尝试刷新 Token */
  async function tryRefreshToken(): Promise<boolean> {
    if (!refreshToken.value) return false
    try {
      const resp: TokenPair = await authApi.refreshToken(refreshToken.value)
      setTokens(resp)
      return true
    } catch {
      clearTokens()
      return false
    }
  }

  /** 更新用户资料 */
  async function updateProfile(data: Partial<UserInfo>) {
    const updated = await authApi.updateProfile(data)
    user.value = { ...user.value, ...updated } as UserInfo
    return updated
  }

  /** 设置最后访问路由 */
  function setLastVisitedRoute(path: string) {
    lastVisitedRoute.value = path
    localStorage.setItem('last_route', path)
  }

  // ── 私有方法 ──
  function setTokens(tokens: TokenPair) {
    accessToken.value = tokens.access_token
    refreshToken.value = tokens.refresh_token
    localStorage.setItem('access_token', tokens.access_token)
    localStorage.setItem('refresh_token', tokens.refresh_token)
  }

  function clearTokens() {
    accessToken.value = ''
    refreshToken.value = ''
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  // ═══════════════════════════════════
  // 导出
  // ═══════════════════════════════════
  return {
    accessToken, refreshToken, user, lastVisitedRoute,
    isLoggedIn, isAdmin, tokenHeader,
    login, register, logout, fetchUserInfo, tryRefreshToken,
    updateProfile, setLastVisitedRoute,
  }
})
```

### 4.4 Task Store — 任务数据（核心 Store）

```typescript
// src/stores/modules/task.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { taskApi } from '@/api/task'
import type { Task, TaskStatus, TaskListParams, TaskStats } from '@/types/task'

export const useTaskStore = defineStore('task', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const taskList = ref<Task[]>([])
  const currentTask = ref<Task | null>(null)
  const taskStats = ref<TaskStats>({
    runningTasks: 0, completedTasks: 0, failedTasks: 0, queuedTasks: 0,
  })
  const listLoading = ref(false)
  const detailLoading = ref(false)
  const submitLoading = ref(false)

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const recentTasks = computed(() =>
    [...taskList.value].sort((a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    ).slice(0, 10)
  )

  const tasksByStatus = computed(() => (status: TaskStatus) =>
    taskList.value.filter(t => t.status === status)
  )

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  /** 获取任务列表 */
  async function fetchTaskList(params?: TaskListParams) {
    listLoading.value = true
    try {
      const resp = await taskApi.list(params)
      taskList.value = resp.items
      return resp
    } finally {
      listLoading.value = false
    }
  }

  /** 获取任务详情 */
  async function fetchTaskDetail(taskId: string) {
    detailLoading.value = true
    try {
      const task = await taskApi.getDetail(taskId)
      currentTask.value = task
      // 同步更新列表中的该任务
      const idx = taskList.value.findIndex(t => t.id === taskId)
      if (idx >= 0) {
        taskList.value[idx] = task
      }
      return task
    } finally {
      detailLoading.value = false
    }
  }

  /** 提交任务 */
  async function submitTask(data: {
    flow_id: string
    project_id: string
    params: Record<string, any>
    description?: string
  }): Promise<string> {
    submitLoading.value = true
    try {
      const resp = await taskApi.submit(data)
      // 乐观更新：添加到列表头部
      taskList.value.unshift(resp)
      return resp.id
    } finally {
      submitLoading.value = false
    }
  }

  /** 取消任务 */
  async function cancelTask(taskId: string) {
    await taskApi.cancel(taskId)
    if (currentTask.value?.id === taskId) {
      currentTask.value.status = 'cancelled'
    }
  }

  /** 重试任务 */
  async function retryTask(taskId: string): Promise<string> {
    const resp = await taskApi.retry(taskId)
    return resp.id
  }

  /** 删除任务 */
  async function deleteTask(taskId: string) {
    await taskApi.delete(taskId)
    taskList.value = taskList.value.filter(t => t.id !== taskId)
    if (currentTask.value?.id === taskId) {
      currentTask.value = null
    }
  }

  /** 获取统计数据 */
  async function fetchStats(): Promise<TaskStats> {
    const stats = await taskApi.getStats()
    taskStats.value = stats
    return stats
  }

  /** 清除当前任务 */
  function clearCurrentTask() {
    currentTask.value = null
  }

  // ═══════════════════════════════════
  return {
    taskList, currentTask, taskStats,
    listLoading, detailLoading, submitLoading,
    recentTasks, tasksByStatus,
    fetchTaskList, fetchTaskDetail, submitTask,
    cancelTask, retryTask, deleteTask, fetchStats,
    clearCurrentTask,
  }
})
```

### 4.5 Flow Store — 流程数据

```typescript
// src/stores/modules/flow.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { flowApi } from '@/api/flow'
import type { Flow, FlowSummary, FlowSchema, FlowCategory } from '@/types/flow'

export const useFlowStore = defineStore('flow', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const flowList = ref<FlowSummary[]>([])
  const currentFlow = ref<Flow | null>(null)
  const currentSchema = ref<FlowSchema | null>(null)
  const schemaCache = ref<Map<string, FlowSchema>>(new Map()) // YAML 解析缓存
  const categories = ref<FlowCategory[]>([])
  const loading = ref(false)

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const popularFlows = computed(() =>
    [...flowList.value].sort((a, b) => b.use_count - a.use_count).slice(0, 5)
  )

  const flowsByCategory = computed(() => (category: string) =>
    flowList.value.filter(f => f.category === category)
  )

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  /** 获取流程列表 */
  async function fetchFlowList() {
    loading.value = true
    try {
      const resp = await flowApi.list()
      flowList.value = resp.items
      return resp
    } finally {
      loading.value = false
    }
  }

  /** 获取流程详情 */
  async function fetchFlowDetail(flowId: string) {
    const flow = await flowApi.getDetail(flowId)
    currentFlow.value = flow
    return flow
  }

  /** 获取流程 Schema（带缓存） */
  async function fetchFlowSchema(flowId: string): Promise<FlowSchema> {
    // 先查缓存
    const cached = schemaCache.value.get(flowId)
    if (cached) {
      currentSchema.value = cached
      return cached
    }

    const schema = await flowApi.getSchema(flowId)
    schemaCache.value.set(flowId, schema)
    currentSchema.value = schema
    return schema
  }

  /** 从 Schema 提取默认值 */
  function getDefaultValues(schema: FlowSchema): Record<string, any> {
    const values: Record<string, any> = {}
    for (const section of schema.sections) {
      for (const field of section.fields) {
        if (field.default !== undefined) {
          values[field.key] = field.default
        } else if (field.type === 'boolean') {
          values[field.key] = false
        } else if (field.type === 'multi-select' || field.type === 'checkbox') {
          values[field.key] = []
        } else if (field.type === 'number' || field.type === 'integer' || field.type === 'float') {
          values[field.key] = field.min ?? 0
        } else {
          values[field.key] = ''
        }
      }
    }
    return values
  }

  /** 清除 Schema 缓存 */
  function clearSchemaCache(flowId?: string) {
    if (flowId) {
      schemaCache.value.delete(flowId)
    } else {
      schemaCache.value.clear()
    }
  }

  /** 获取分类列表 */
  async function fetchCategories() {
    const cats = await flowApi.getCategories()
    categories.value = cats
    return cats
  }

  // ═══════════════════════════════════
  return {
    flowList, currentFlow, currentSchema, categories, loading,
    popularFlows, flowsByCategory,
    fetchFlowList, fetchFlowDetail, fetchFlowSchema,
    getDefaultValues, clearSchemaCache, fetchCategories,
  }
})
```

### 4.6 Project Store — 项目数据

```typescript
// src/stores/modules/project.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { projectApi } from '@/api/project'
import type { Project, ProjectCreateParams, Sample } from '@/types/project'

export const useProjectStore = defineStore('project', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const projectList = ref<Project[]>([])
  const currentProject = ref<Project | null>(null)
  const currentSamples = ref<Sample[]>([])
  const loading = ref(false)

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const projectOptions = computed(() =>
    projectList.value.map(p => ({
      label: p.name,
      value: p.id,
    }))
  )

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  async function fetchProjectList() {
    loading.value = true
    try {
      const resp = await projectApi.list()
      projectList.value = resp.items
      return resp
    } finally {
      loading.value = false
    }
  }

  async function fetchProjectDetail(projectId: string) {
    const project = await projectApi.getDetail(projectId)
    currentProject.value = project
    return project
  }

  async function createProject(params: ProjectCreateParams) {
    const project = await projectApi.create(params)
    projectList.value.unshift(project)
    return project
  }

  async function deleteProject(projectId: string) {
    await projectApi.delete(projectId)
    projectList.value = projectList.value.filter(p => p.id !== projectId)
    if (currentProject.value?.id === projectId) {
      currentProject.value = null
    }
  }

  async function fetchSamples(projectId: string) {
    const samples = await projectApi.getSamples(projectId)
    currentSamples.value = samples
    return samples
  }

  async function uploadSampleSheet(projectId: string, file: File) {
    const result = await projectApi.uploadSampleSheet(projectId, file)
    await fetchSamples(projectId)
    return result
  }

  function setCurrentProject(projectId: string | null) {
    if (!projectId) {
      currentProject.value = null
      return
    }
    const p = projectList.value.find(p => p.id === projectId)
    currentProject.value = p || null
  }

  // ═══════════════════════════════════
  return {
    projectList, currentProject, currentSamples, loading,
    projectOptions,
    fetchProjectList, fetchProjectDetail, createProject,
    deleteProject, fetchSamples, uploadSampleSheet,
    setCurrentProject,
  }
})
```

### 4.7 Chat Store — AI 对话状态（核心 Store）

```typescript
// src/stores/modules/chat.ts
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { chatApi } from '@/api/chat'
import { useAuthStore } from './auth'
import type {
  ChatSession, ChatMessage, WebSocketMessage,
  ChatContext, ToolCall, AIModelConfig,
} from '@/types/chat'

/** 消息角色类型 */
type MessageRole = 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result' | 'mcp_result'

export const useChatStore = defineStore('chat', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const panelVisible = ref(true)
  const unreadCount = ref(0)
  const isLoading = ref(false)          // AI 正在响应
  const isStreaming = ref(false)        // 流式接收中
  const streamingContent = ref('')      // 流式累积内容
  const wsStatus = ref<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle')
  const currentModel = ref<string>('gpt-4')
  const availableModels = ref<AIModelConfig[]>([])

  // 上下文感知
  const currentContext = ref<ChatContext>({
    page: '',
    routeParams: {},
    routeQuery: {},
    projectId: null,
    flowId: null,
    taskId: null,
  })

  // WebSocket 实例
  let ws: WebSocket | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  const MAX_RECONNECT = 5

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const currentSession = computed(() =>
    sessions.value.find(s => s.id === currentSessionId.value) || null
  )

  const currentMessages = computed(() => messages.value)

  const isPanelOpen = computed(() => panelVisible.value)

  const wsConnected = computed(() => wsStatus.value === 'connected')

  // ═══════════════════════════════════
  // Actions — 会话管理
  // ═══════════════════════════════════

  /** 获取会话列表 */
  async function fetchSessions() {
    const resp = await chatApi.listSessions()
    sessions.value = resp.items
    return resp
  }

  /** 创建新会话 */
  async function createSession(title?: string): Promise<string> {
    const session = await chatApi.createSession({
      title: title || '新会话',
      model: currentModel.value,
    })
    sessions.value.unshift(session)
    currentSessionId.value = session.id
    messages.value = []
    return session.id
  }

  /** 切换当前会话 */
  async function switchSession(sessionId: string) {
    currentSessionId.value = sessionId
    // 加载历史消息
    const resp = await chatApi.getMessages(sessionId)
    messages.value = resp.items
  }

  /** 删除会话 */
  async function deleteSession(sessionId: string) {
    await chatApi.deleteSession(sessionId)
    sessions.value = sessions.value.filter(s => s.id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
    }
  }

  /** 重命名会话 */
  async function renameSession(sessionId: string, title: string) {
    await chatApi.updateSession(sessionId, { title })
    const s = sessions.value.find(s => s.id === sessionId)
    if (s) s.title = title
  }

  // ═══════════════════════════════════
  // Actions — 消息发送
  // ═══════════════════════════════════

  /** 发送消息 */
  async function sendMessage(content: string) {
    if (!currentSessionId.value) {
      await createSession()
    }
    const sessionId = currentSessionId.value!

    // 1. 添加用户消息到本地
    const userMessage: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: sessionId,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMessage)

    // 2. 发送给后端（通过 WebSocket）
    isLoading.value = true
    isStreaming.value = false
    streamingContent.value = ''

    try {
      sendWsMessage({
        type: 'chat.message',
        session_id: sessionId,
        content,
        context: { ...currentContext.value },
        model: currentModel.value,
      })
    } catch (err: any) {
      // 降级到 HTTP API
      await sendViaHttp(sessionId, content)
    }
  }

  /** HTTP 降级发送 */
  async function sendViaHttp(sessionId: string, content: string) {
    try {
      const resp = await chatApi.sendMessage(sessionId, {
        content,
        context: currentContext.value,
      })
      appendAssistantMessage(resp)
    } catch (err: any) {
      appendErrorMessage(err.message)
    } finally {
      isLoading.value = false
    }
  }

  /** 追加助手消息 */
  function appendAssistantMessage(data: { content: string; tool_calls?: ToolCall[] }) {
    const msg: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'assistant',
      content: data.content,
      tool_calls: data.tool_calls,
      created_at: new Date().toISOString(),
    }
    messages.value.push(msg)
    isLoading.value = false
    isStreaming.value = false
  }

  /** 追加错误消息 */
  function appendErrorMessage(errorText: string) {
    const msg: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'assistant',
      content: `❌ **错误**: ${errorText}`,
      is_error: true,
      created_at: new Date().toISOString(),
    }
    messages.value.push(msg)
    isLoading.value = false
  }

  // ═══════════════════════════════════
  // Actions — 工具调用确认
  // ═══════════════════════════════════

  /** 确认执行工具调用 */
  async function confirmToolCall(toolCall: ToolCall) {
    // 添加 "用户已确认" 消息
    messages.value.push({
      id: `local-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'tool_result',
      content: `已确认执行: ${toolCall.function.name}`,
      tool_call_id: toolCall.id,
      created_at: new Date().toISOString(),
    })

    // 发送确认到后端
    sendWsMessage({
      type: 'chat.tool_confirm',
      session_id: currentSessionId.value,
      tool_call_id: toolCall.id,
      confirmed: true,
    })
  }

  /** 拒绝工具调用 */
  async function rejectToolCall(toolCall: ToolCall) {
    messages.value.push({
      id: `local-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'tool_result',
      content: `已拒绝执行: ${toolCall.function.name}`,
      tool_call_id: toolCall.id,
      created_at: new Date().toISOString(),
    })

    sendWsMessage({
      type: 'chat.tool_confirm',
      session_id: currentSessionId.value,
      tool_call_id: toolCall.id,
      confirmed: false,
    })
  }

  // ═══════════════════════════════════
  // Actions — WebSocket 管理
  // ═══════════════════════════════════

  /** 连接 WebSocket */
  function connectWebSocket() {
    if (ws?.readyState === WebSocket.OPEN) return

    wsStatus.value = 'connecting'
    const authStore = useAuthStore()
    const token = authStore.accessToken
    const wsUrl = `${import.meta.env.VITE_WS_BASE_URL}/ws/chat?token=${token}`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      wsStatus.value = 'connected'
      reconnectAttempts = 0
      startHeartbeat()
    }

    ws.onmessage = (event) => {
      try {
        const msg: WebSocketMessage = JSON.parse(event.data)
        handleWsMessage(msg)
      } catch {
        console.warn('[Chat WS] Invalid message:', event.data)
      }
    }

    ws.onclose = () => {
      wsStatus.value = 'disconnected'
      stopHeartbeat()
      attemptReconnect()
    }

    ws.onerror = (err) => {
      console.error('[Chat WS] Error:', err)
      wsStatus.value = 'disconnected'
    }
  }

  /** 断开 WebSocket */
  function disconnectWebSocket() {
    stopHeartbeat()
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    ws?.close()
    ws = null
    wsStatus.value = 'idle'
  }

  /** 重连 */
  function attemptReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) {
      console.warn('[Chat WS] Max reconnect attempts reached')
      return
    }
    reconnectAttempts++
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)
    reconnectTimer = setTimeout(() => {
      console.log(`[Chat WS] Reconnecting... (attempt ${reconnectAttempts})`)
      connectWebSocket()
    }, delay)
  }

  /** 心跳 */
  function startHeartbeat() {
    heartbeatTimer = setInterval(() => {
      sendWsMessage({ type: 'ping' })
    }, 30000)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  /** 发送 WS 消息 */
  function sendWsMessage(msg: Record<string, any>) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    } else {
      throw new Error('WebSocket not connected')
    }
  }

  /** 处理收到的 WS 消息 */
  function handleWsMessage(msg: WebSocketMessage) {
    switch (msg.type) {
      case 'pong':
        // 心跳响应，无需处理
        break

      case 'chat.message_chunk':
        // 流式消息片段
        if (!isStreaming.value) {
          isStreaming.value = true
          streamingContent.value = ''
        }
        streamingContent.value += msg.chunk || ''
        break

      case 'chat.message_end':
        // 流式消息结束
        appendAssistantMessage({
          content: streamingContent.value || msg.content || '',
          tool_calls: msg.tool_calls,
        })
        streamingContent.value = ''
        isStreaming.value = false
        isLoading.value = false
        break

      case 'chat.tool_call_request':
        // AI 请求工具调用 → 渲染确认卡片
        messages.value.push({
          id: `local-${Date.now()}`,
          session_id: currentSessionId.value!,
          role: 'tool_call',
          content: '',
          tool_calls: msg.tool_calls,
          created_at: new Date().toISOString(),
        })
        isLoading.value = false
        break

      case 'chat.tool_result':
        // 工具执行结果
        messages.value.push({
          id: `local-${Date.now()}`,
          session_id: currentSessionId.value!,
          role: 'tool_result',
          content: msg.content || JSON.stringify(msg.result),
          tool_call_id: msg.tool_call_id,
          created_at: new Date().toISOString(),
        })
        break

      case 'chat.mcp_result':
        // MCP 工具结果
        messages.value.push({
          id: `local-${Date.now()}`,
          session_id: currentSessionId.value!,
          role: 'mcp_result',
          content: msg.content || '',
          mcp_server: msg.mcp_server,
          tool_name: msg.tool_name,
          result: msg.result,
          created_at: new Date().toISOString(),
        })
        break

      case 'error':
        appendErrorMessage(msg.message || '未知错误')
        break

      default:
        console.warn('[Chat WS] Unknown message type:', msg.type)
    }
  }

  // ═══════════════════════════════════
  // Actions — 上下文管理
  // ═══════════════════════════════════

  /** 从路由自动收集上下文 */
  function collectRouteContext(
    path: string,
    params: Record<string, string>,
    query: Record<string, string>,
  ) {
    const context: ChatContext = {
      page: path,
      routeParams: params,
      routeQuery: query,
    }

    // 路由 → 上下文推断
    if (path.startsWith('/projects/') && params.id) {
      context.projectId = params.id
    }
    if (path.startsWith('/flows/') && params.id) {
      context.flowId = params.id
    }
    if (path.startsWith('/tasks/') && params.id) {
      context.taskId = params.id
    }
    // 新建任务页从 query 获取
    if (path === '/tasks/new') {
      if (query.flow) context.flowId = query.flow
      if (query.project) context.projectId = query.project
    }

    currentContext.value = context
  }

  /** 手动设置上下文 */
  function setContext(updates: Partial<ChatContext>) {
    currentContext.value = { ...currentContext.value, ...updates }
  }

  function setCurrentProject(projectId: string | null) {
    currentContext.value.projectId = projectId
  }
  function setCurrentFlow(flowId: string | null) {
    currentContext.value.flowId = flowId
  }
  function setCurrentTask(taskId: string | null) {
    currentContext.value.taskId = taskId
  }
  function clearCurrentTask() {
    currentContext.value.taskId = null
  }

  // ═══════════════════════════════════
  // Actions — 面板控制
  // ═══════════════════════════════════

  function togglePanel(force?: boolean) {
    panelVisible.value = force !== undefined ? force : !panelVisible.value
  }

  /** 获取可用模型列表 */
  async function fetchModels() {
    const resp = await chatApi.listModels()
    availableModels.value = resp.items
    if (!availableModels.value.find(m => m.id === currentModel.value)) {
      currentModel.value = availableModels.value[0]?.id || 'gpt-4'
    }
    return resp
  }

  // ═══════════════════════════════════
  // Watch — 自动连接/断开 WebSocket
  // ═══════════════════════════════════
  watch(
    () => panelVisible.value,
    (visible) => {
      if (visible) {
        connectWebSocket()
      } else {
        disconnectWebSocket()
      }
    }
  )

  // ═══════════════════════════════════
  return {
    sessions, currentSessionId, messages,
    panelVisible, unreadCount, isLoading, isStreaming,
    streamingContent, wsStatus, currentModel, availableModels,
    currentContext, currentSession, currentMessages,
    isPanelOpen, wsConnected,
    fetchSessions, createSession, switchSession, deleteSession, renameSession,
    sendMessage, confirmToolCall, rejectToolCall,
    connectWebSocket, disconnectWebSocket,
    collectRouteContext, setContext,
    setCurrentProject, setCurrentFlow, setCurrentTask, clearCurrentTask,
    togglePanel, fetchModels,
  }
})
```

### 4.8 MCP Store — MCP Server 管理

```typescript
// src/stores/modules/mcp.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { mcpApi } from '@/api/mcp'
import type { MCPServer, MCPTool } from '@/types/mcp'

export const useMCPStore = defineStore('mcp', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const servers = ref<MCPServer[]>([])
  const currentServer = ref<MCPServer | null>(null)
  const toolCatalog = ref<MCPTool[]>([])
  const loading = ref(false)

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const activeServers = computed(() => servers.value.filter(s => s.status === 'active'))
  const activeTools = computed(() => toolCatalog.value.filter(t => t.available))

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  async function fetchServers() {
    loading.value = true
    try {
      const resp = await mcpApi.listServers()
      servers.value = resp.items
      return resp
    } finally {
      loading.value = false
    }
  }

  async function fetchServerDetail(serverId: string) {
    const server = await mcpApi.getServerDetail(serverId)
    currentServer.value = server
    return server
  }

  async function fetchToolCatalog() {
    const resp = await mcpApi.listTools()
    toolCatalog.value = resp.items
    return resp
  }

  /** 创建 MCP Server */
  async function createServer(data: {
    name: string; url: string; description?: string; icon?: string
  }) {
    const server = await mcpApi.createServer(data)
    servers.value.push(server)
    return server
  }

  /** 删除 MCP Server */
  async function deleteServer(serverId: string) {
    await mcpApi.deleteServer(serverId)
    servers.value = servers.value.filter(s => s.id !== serverId)
    if (currentServer.value?.id === serverId) {
      currentServer.value = null
    }
  }

  /** 测试连接 */
  async function testConnection(serverId: string) {
    return mcpApi.testConnection(serverId)
  }

  // ═══════════════════════════════════
  return {
    servers, currentServer, toolCatalog, loading,
    activeServers, activeTools,
    fetchServers, fetchServerDetail, fetchToolCatalog,
    createServer, deleteServer, testConnection,
  }
})
```

### 4.9 Theme Store — 主题状态

```typescript
// src/stores/modules/theme.ts
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { darkTheme, lightTheme } from 'naive-ui'
import type { GlobalTheme } from 'naive-ui'

export type ThemeMode = 'dark' | 'light' | 'system'

export const useThemeStore = defineStore('theme', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const themeMode = ref<ThemeMode>(
    (localStorage.getItem('theme_mode') as ThemeMode) || 'system'
  )

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const isDark = computed(() => {
    if (themeMode.value === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches
    }
    return themeMode.value === 'dark'
  })

  const naiveTheme = computed<GlobalTheme | null>(() =>
    isDark.value ? darkTheme : null // null = light (default)
  )

  const naiveThemeOverrides = computed(() => ({
    common: {
      primaryColor: '#6366f1',
      primaryColorHover: '#818cf8',
      primaryColorPressed: '#4f46e5',
      primaryColorSuppl: '#818cf8',
    },
  }))

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  function setTheme(mode: ThemeMode) {
    themeMode.value = mode
    localStorage.setItem('theme_mode', mode)
    applyTheme()
  }

  function toggleTheme() {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  function applyTheme() {
    const root = document.documentElement
    if (isDark.value) {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }

  /** 立即应用主题（防止闪烁，在路由守卫中调用） */
  function applyThemeImmediately() {
    const saved = (localStorage.getItem('theme_mode') as ThemeMode) || 'system'
    const dark = saved === 'dark' || (saved === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
    const root = document.documentElement
    if (dark) root.classList.add('dark')
    else root.classList.remove('dark')
  }

  // ── 监听系统主题变化 ──
  if (window.matchMedia) {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener('change', () => {
      if (themeMode.value === 'system') {
        applyTheme()
      }
    })
  }

  // ── 监听 store 变化 ──
  watch(() => themeMode.value, applyTheme, { immediate: true })

  // ═══════════════════════════════════
  return {
    themeMode, isDark, naiveTheme, naiveThemeOverrides,
    setTheme, toggleTheme, applyTheme, applyThemeImmediately,
  }
})
```

### 4.10 Notification Store — 全局通知

```typescript
// src/stores/modules/notification.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { NotificationType } from 'naive-ui'

export interface AppNotification {
  id: string
  type: NotificationType
  title: string
  content: string
  read: boolean
  created_at: string
  link?: string
}

export const useNotificationStore = defineStore('notification', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const notifications = ref<AppNotification[]>([])
  const unreadCount = ref(0)

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  /** 添加通知 */
  function add(notification: Omit<AppNotification, 'id' | 'created_at' | 'read'>) {
    const item: AppNotification = {
      ...notification,
      id: `notif-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      read: false,
      created_at: new Date().toISOString(),
    }
    notifications.value.unshift(item)
    unreadCount.value++
    return item.id
  }

  /** 标记已读 */
  function markAsRead(id: string) {
    const n = notifications.value.find(x => x.id === id)
    if (n && !n.read) {
      n.read = true
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
  }

  /** 标记全部已读 */
  function markAllRead() {
    notifications.value.forEach(n => { n.read = true })
    unreadCount.value = 0
  }

  /** 清除所有 */
  function clearAll() {
    notifications.value = []
    unreadCount.value = 0
  }

  /** 从 WebSocket 推送接收 */
  function handlePush(data: { title: string; content: string; type?: NotificationType; link?: string }) {
    add({
      type: data.type || 'info',
      title: data.title,
      content: data.content,
      link: data.link,
    })
  }

  // ═══════════════════════════════════
  return {
    notifications, unreadCount,
    add, markAsRead, markAllRead, clearAll, handlePush,
  }
})
```

### 4.11 Tab Store — 标签页与缓存管理

```typescript
// src/stores/modules/tab.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface TabItem {
  name: string
  title: string
  path: string
  keepAlive?: boolean
}

export const useTabStore = defineStore('tab', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const tabs = ref<TabItem[]>([])
  const activeTab = ref<string>('')

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const cachedViews = computed(() =>
    tabs.value.filter(t => t.keepAlive).map(t => t.name)
  )

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  function addTab(tab: TabItem) {
    const exists = tabs.value.find(t => t.path === tab.path)
    if (!exists) {
      tabs.value.push(tab)
    }
    activeTab.value = tab.path
  }

  function removeTab(path: string) {
    tabs.value = tabs.value.filter(t => t.path !== path)
    if (activeTab.value === path && tabs.value.length > 0) {
      activeTab.value = tabs.value[tabs.value.length - 1].path
    }
  }

  function setActiveTab(path: string) {
    activeTab.value = path
  }

  // ═══════════════════════════════════
  return {
    tabs, activeTab, cachedViews,
    addTab, removeTab, setActiveTab,
  }
})
```



---

## 5. AI 对话面板架构（重点）

### 5.1 总体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MainLayout 主布局                                    │
│  ┌────────────────┐  ┌──────────────────────────────────┐  ┌──────────────┐ │
│  │                │  │                                  │  │  AIChatPanel  │ │
│  │  AppSidebar    │  │         主内容区                  │  │   (380px)    │ │
│  │   (220px)      │  │                                  │  │              │ │
│  │                │  │   RouterView                     │  │  ChatHeader  │ │
│  │  仪表盘         │  │   ┌─────────────────────────┐   │  │  ChatMsgList │ │
│  │  项目管理       │  │   │ DashboardView /         │   │  │  ChatInput   │ │
│  │  流程市场       │  │   │ TaskDetailView / ...    │   │  │  ContextBar  │ │
│  │  任务中心       │  │   │                         │   │  │              │ │
│  │                │  │   │                         │   │  └──────────────┘ │
│  │                │  │   │                         │   │                  │
│  │                │  │   └─────────────────────────┘   │                  │
│  │                │  │                                  │                  │
│  └────────────────┘  └──────────────────────────────────┘                  │
│                                                                             │
│  (折叠时显示 AIChatFab 浮动按钮)                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 AIChatPanel.vue — 主面板容器

```vue
<!-- src/components/ai-chat/AIChatPanel.vue -->
<template>
  <div class="ai-chat-panel" :class="{ dark: themeStore.isDark }">
    <!-- 头部 -->
    <ChatHeader
      :current-model="chatStore.currentModel"
      :models="chatStore.availableModels"
      :current-session="chatStore.currentSession"
      @model-change="chatStore.currentModel = $event"
      @new-session="chatStore.createSession()"
      @toggle-panel="chatStore.togglePanel(false)"
      @show-sessions="showSessionDrawer = true"
    />

    <!-- 上下文指示条 -->
    <ChatContextBar
      :context="chatStore.currentContext"
      :project-name="currentProjectName"
      :flow-name="currentFlowName"
      :task-status="currentTask?.status"
      @clear-context="clearContext"
    />

    <!-- 消息列表 -->
    <div ref="messageListRef" class="ai-chat-panel__messages">
      <ChatMessageList
        :messages="displayMessages"
        :is-streaming="chatStore.isStreaming"
        :streaming-content="chatStore.streamingContent"
        :is-loading="chatStore.isLoading"
        @confirm-tool="chatStore.confirmToolCall"
        @reject-tool="chatStore.rejectToolCall"
      />
    </div>

    <!-- 快捷操作栏（可展开） -->
    <ChatQuickActions
      :context="chatStore.currentContext"
      @action="handleQuickAction"
    />

    <!-- 输入区 -->
    <ChatInputArea
      :disabled="chatStore.isLoading"
      :placeholder="inputPlaceholder"
      @send="handleSendMessage"
      @stop="handleStopGeneration"
    />

    <!-- 会话列表面板 -->
    <SessionDrawer
      v-model:show="showSessionDrawer"
      :sessions="chatStore.sessions"
      :current-id="chatStore.currentSessionId"
      @select="chatStore.switchSession"
      @delete="chatStore.deleteSession"
      @rename="chatStore.renameSession"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'

import ChatHeader from './ChatHeader.vue'
import ChatContextBar from './ChatContextBar.vue'
import ChatMessageList from './ChatMessageList.vue'
import ChatQuickActions from './ChatQuickActions.vue'
import ChatInputArea from './ChatInputArea.vue'
import SessionDrawer from './SessionDrawer.vue'

import { useChatStore } from '@/stores/modules/chat'
import { useProjectStore } from '@/stores/modules/project'
import { useFlowStore } from '@/stores/modules/flow'
import { useTaskStore } from '@/stores/modules/task'
import { useThemeStore } from '@/stores/modules/theme'

const chatStore = useChatStore()
const projectStore = useProjectStore()
const flowStore = useFlowStore()
const taskStore = useTaskStore()
const themeStore = useThemeStore()

const messageListRef = ref<HTMLDivElement>()
const showSessionDrawer = ref(false)

// ── 显示的消息（合并流式内容） ──
const displayMessages = computed(() => {
  const msgs = [...chatStore.currentMessages]
  if (chatStore.isStreaming && chatStore.streamingContent) {
    // 追加一个临时的流式消息
    msgs.push({
      id: 'streaming',
      session_id: chatStore.currentSessionId || '',
      role: 'assistant',
      content: chatStore.streamingContent,
      is_streaming: true,
      created_at: new Date().toISOString(),
    } as any)
  }
  return msgs
})

// ── 上下文名称解析 ──
const currentProjectName = computed(() => {
  const ctx = chatStore.currentContext
  if (!ctx.projectId) return null
  const p = projectStore.projectList.find(x => x.id === ctx.projectId)
  return p?.name || null
})

const currentFlowName = computed(() => {
  const ctx = chatStore.currentContext
  if (!ctx.flowId) return null
  const f = flowStore.flowList.find(x => x.id === ctx.flowId)
  return f?.name || null
})

const currentTask = computed(() => {
  const ctx = chatStore.currentContext
  if (!ctx.taskId) return null
  return taskStore.taskList.find(t => t.id === ctx.taskId) || null
})

// ── 输入框占位符 ──
const inputPlaceholder = computed(() => {
  const ctx = chatStore.currentContext
  if (ctx.taskId) return '询问关于此任务的问题...'
  if (ctx.flowId) return '询问关于此流程的问题...'
  if (ctx.projectId) return '询问关于此项目的问题...'
  return '给 AI 助手发送消息...'
})

// ── 发送消息 ──
async function handleSendMessage(content: string) {
  await chatStore.sendMessage(content)
}

// ── 停止生成 ──
function handleStopGeneration() {
  chatStore.sendWsMessage({
    type: 'chat.stop',
    session_id: chatStore.currentSessionId,
  })
  chatStore.isLoading = false
  chatStore.isStreaming = false
}

// ── 快捷操作 ──
function handleQuickAction(action: string) {
  const ctx = chatStore.currentContext
  switch (action) {
    case 'explain_task':
      if (ctx.taskId) {
        chatStore.sendMessage(`请解释这个任务当前的状态和进度`)
      }
      break
    case 'check_errors':
      if (ctx.taskId) {
        chatStore.sendMessage(`请帮我分析任务日志中的错误`)
      }
      break
    case 'view_results':
      if (ctx.taskId) {
        chatStore.sendMessage(`请总结这个结果文件的内容`)
      }
      break
    case 'flow_params':
      if (ctx.flowId) {
        chatStore.sendMessage(`请解释这个流程的参数配置`)
      }
      break
    default:
      break
  }
}

function clearContext() {
  chatStore.setContext({
    projectId: null,
    flowId: null,
    taskId: null,
  })
}

// ── 自动滚动到最新消息 ──
watch(
  () => displayMessages.value.length,
  async () => {
    await nextTick()
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  }
)

// ── 初始化 ──
chatStore.fetchModels()
chatStore.connectWebSocket()
</script>

<style scoped lang="scss">
.ai-chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--chat-bg);
  position: relative;

  &__messages {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 12px;
  }
}
</style>
```

### 5.3 ChatHeader.vue — 面板头部

```vue
<!-- src/components/ai-chat/ChatHeader.vue -->
<template>
  <div class="chat-header">
    <!-- 左侧：会话标题 + 模型选择 -->
    <div class="chat-header__left">
      <div class="chat-title" @click="$emit('show-sessions')">
        <n-icon size="18" class="title-icon"><MessageOutlined /></n-icon>
        <span class="title-text">{{ currentSession?.title || 'AI 助手' }}</span>
        <n-icon size="14" class="chevron-icon"><DownOutlined /></n-icon>
      </div>

      <n-dropdown
        :options="modelOptions"
        trigger="click"
        @select="handleModelSelect"
      >
        <n-tag size="small" :bordered="false" type="info" class="model-tag">
          {{ currentModelLabel }}
          <n-icon size="12"><DownOutlined /></n-icon>
        </n-tag>
      </n-dropdown>
    </div>

    <!-- 右侧操作 -->
    <div class="chat-header__right">
      <n-tooltip placement="bottom">
        <template #trigger>
          <n-button text circle size="small" @click="$emit('new-session')">
            <template #icon><n-icon><PlusOutlined /></n-icon></template>
          </n-button>
        </template>
        新会话
      </n-tooltip>

      <n-tooltip placement="bottom">
        <template #trigger>
          <n-button text circle size="small" @click="$emit('toggle-panel')">
            <template #icon><n-icon><RightOutlined /></n-icon></template>
          </n-button>
        </template>
        收起面板
      </n-tooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NIcon, NTag, NDropdown, NTooltip } from 'naive-ui'
import { MessageOutlined, DownOutlined, PlusOutlined, RightOutlined } from '@vicons/antd'
import type { ChatSession, AIModelConfig } from '@/types/chat'
import type { DropdownOption } from 'naive-ui'

const props = defineProps<{
  currentModel: string
  models: AIModelConfig[]
  currentSession: ChatSession | null
}>()

defineEmits<{
  (e: 'model-change', modelId: string): void
  (e: 'new-session'): void
  (e: 'toggle-panel'): void
  (e: 'show-sessions'): void
}>()

const modelOptions = computed<DropdownOption[]>(() =>
  props.models.map(m => ({
    label: m.name,
    key: m.id,
  }))
)

const currentModelLabel = computed(() => {
  const m = props.models.find(x => x.id === props.currentModel)
  return m?.name || props.currentModel
})

function handleModelSelect(key: string) {
  emitModelChange(key)
}

function emitModelChange(key: string) {
  // handled via template $emit
}
</script>

<style scoped lang="scss">
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;

  &__left {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;

    .chat-title {
      display: flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 6px;
      transition: background 0.2s;

      &:hover { background: var(--hover-bg); }

      .title-text {
        font-weight: 600;
        font-size: 14px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 140px;
      }

      .title-icon { color: var(--primary-color); }
      .chevron-icon { color: var(--text-secondary); }
    }

    .model-tag {
      cursor: pointer;
      font-size: 11px;
    }
  }

  &__right {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }
}
</style>
```

### 5.4 ChatMessageList.vue — 消息列表（虚拟滚动优化）

```vue
<!-- src/components/ai-chat/ChatMessageList.vue -->
<template>
  <div class="chat-message-list">
    <!-- 欢迎语（无消息时显示） -->
    <ChatWelcome v-if="messages.length === 0" />

    <!-- 消息列表 -->
    <template v-for="(msg, index) in messages" :key="msg.id">
      <!-- 日期分隔线 -->
      <div v-if="showDateDivider(index)" class="date-divider">
        <span>{{ formatDateDivider(msg.created_at) }}</span>
      </div>

      <!-- 用户消息 -->
      <ChatMessageUser
        v-if="msg.role === 'user'"
        :content="msg.content"
        :timestamp="msg.created_at"
      />

      <!-- 助手消息 -->
      <ChatMessageAssistant
        v-else-if="msg.role === 'assistant'"
        :content="msg.content"
        :timestamp="msg.created_at"
        :is-error="msg.is_error"
        :is-streaming="msg.is_streaming"
      />

      <!-- 工具调用确认卡片 -->
      <ChatMessageToolCall
        v-else-if="msg.role === 'tool_call' && msg.tool_calls"
        :tool-calls="msg.tool_calls"
        :timestamp="msg.created_at"
        @confirm="$emit('confirm-tool', $event)"
        @reject="$emit('reject-tool', $event)"
      />

      <!-- 工具结果 -->
      <ChatMessageToolResult
        v-else-if="msg.role === 'tool_result'"
        :content="msg.content"
        :tool-call-id="msg.tool_call_id"
        :timestamp="msg.created_at"
      />

      <!-- MCP 工具结果 -->
      <ChatMessageMCPResult
        v-else-if="msg.role === 'mcp_result'"
        :content="msg.content"
        :mcp-server="msg.mcp_server"
        :tool-name="msg.tool_name"
        :result="msg.result"
        :timestamp="msg.created_at"
      />
    </template>

    <!-- 输入中动画 -->
    <TypingIndicator v-if="isLoading && !isStreaming" />

    <!-- 底部占位 -->
    <div ref="bottomAnchor" style="height: 1px"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

import ChatWelcome from './ChatWelcome.vue'
import ChatMessageUser from './ChatMessageUser.vue'
import ChatMessageAssistant from './ChatMessageAssistant.vue'
import ChatMessageToolCall from './ChatMessageToolCall.vue'
import ChatMessageToolResult from './ChatMessageToolResult.vue'
import ChatMessageMCPResult from './ChatMessageMCPResult.vue'
import TypingIndicator from './TypingIndicator.vue'

import type { ChatMessage, ToolCall } from '@/types/chat'
import { formatDateDivider, shouldShowDateDivider } from '@/utils/time'

const props = defineProps<{
  messages: ChatMessage[]
  isStreaming: boolean
  streamingContent: string
  isLoading: boolean
}>()

defineEmits<{
  (e: 'confirm-tool', toolCall: ToolCall): void
  (e: 'reject-tool', toolCall: ToolCall): void
}>()

const bottomAnchor = ref<HTMLDivElement>()

function showDateDivider(index: number): boolean {
  if (index === 0) return true
  return shouldShowDateDivider(
    props.messages[index - 1].created_at,
    props.messages[index].created_at,
  )
}

// 自动滚动到底部
watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    bottomAnchor.value?.scrollIntoView({ behavior: 'smooth' })
  }
)
</script>

<style scoped lang="scss">
.chat-message-list {
  display: flex;
  flex-direction: column;
  gap: 16px;

  .date-divider {
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 8px 0;

    span {
      font-size: 11px;
      color: var(--text-tertiary);
      background: var(--divider-bg);
      padding: 2px 12px;
      border-radius: 10px;
    }
  }
}
</style>
```

### 5.5 ChatMessageAssistant.vue — AI 消息渲染（Markdown + 代码高亮）

```vue
<!-- src/components/ai-chat/ChatMessageAssistant.vue -->
<template>
  <div class="chat-message-assistant" :class="{ 'is-error': isError, 'is-streaming': isStreaming }">
    <!-- AI 头像 -->
    <div class="assistant-avatar">
      <div class="avatar-ring">
        <n-icon size="16"><RobotOutlined /></n-icon>
      </div>
    </div>

    <!-- 消息内容 -->
    <div class="assistant-content">
      <!-- Markdown 渲染 -->
      <div class="markdown-body" v-html="renderedContent" />

      <!-- 操作栏 -->
      <div class="assistant-actions">
        <n-tooltip v-for="action in actions" :key="action.key">
          <template #trigger>
            <n-button text size="tiny" @click="action.handler">
              <template #icon><n-icon size="14"><component :is="action.icon" /></n-icon></template>
            </n-button>
          </template>
          {{ action.tooltip }}
        </n-tooltip>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NIcon, NTooltip } from 'naive-ui'
import { RobotOutlined, CopyOutlined, SyncOutlined, ThumbsUpOutlined, ThumbsDownOutlined } from '@vicons/antd'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'

const props = defineProps<{
  content: string
  timestamp: string
  isError?: boolean
  isStreaming?: boolean
}>()

// ── Markdown 渲染 ──
const renderedContent = computed(() => {
  if (!props.content) return ''

  // 配置 marked
  marked.setOptions({
    breaks: true,
    gfm: true,
  })

  const rawHtml = marked.parse(props.content)
  return DOMPurify.sanitize(rawHtml as string)
})

// ── 操作按钮 ──
const actions = [
  {
    key: 'copy',
    icon: CopyOutlined,
    tooltip: '复制内容',
    handler: () => {
      navigator.clipboard.writeText(props.content)
    },
  },
  {
    key: 'regenerate',
    icon: SyncOutlined,
    tooltip: '重新生成',
    handler: () => { /* 重新生成 */ },
  },
  {
    key: 'like',
    icon: ThumbsUpOutlined,
    tooltip: '有帮助',
    handler: () => { /* 反馈 */ },
  },
  {
    key: 'dislike',
    icon: ThumbsDownOutlined,
    tooltip: '无帮助',
    handler: () => { /* 反馈 */ },
  },
]
</script>

<style scoped lang="scss">
.chat-message-assistant {
  display: flex;
  gap: 10px;
  align-items: flex-start;

  &.is-error {
    .markdown-body { color: #ef4444; }
  }

  &.is-streaming {
    .markdown-body::after {
      content: '▊';
      animation: blink 1s infinite;
      margin-left: 2px;
      color: var(--primary-color);
    }
  }

  .assistant-avatar {
    flex-shrink: 0;

    .avatar-ring {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
    }
  }

  .assistant-content {
    flex: 1;
    min-width: 0;

    .markdown-body {
      font-size: 13.5px;
      line-height: 1.7;
      color: var(--text-primary);

      :deep(h1, h2, h3, h4) {
        margin: 12px 0 8px;
        font-weight: 600;
      }
      :deep(p) { margin: 6px 0; }
      :deep(code) {
        background: var(--code-bg);
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 12px;
        font-family: 'JetBrains Mono', monospace;
      }
      :deep(pre) {
        background: var(--code-block-bg);
        padding: 12px;
        border-radius: 8px;
        overflow-x: auto;
        margin: 8px 0;

        code {
          background: none;
          padding: 0;
          font-size: 12px;
        }
      }
      :deep(ul, ol) {
        margin: 6px 0;
        padding-left: 20px;
      }
      :deep(li) { margin: 2px 0; }
      :deep(table) {
        border-collapse: collapse;
        margin: 8px 0;
        font-size: 12px;

        th, td {
          border: 1px solid var(--border-color);
          padding: 6px 10px;
        }
        th {
          background: var(--table-header-bg);
          font-weight: 600;
        }
      }
      :deep(a) {
        color: var(--primary-color);
        text-decoration: none;

        &:hover { text-decoration: underline; }
      }
    }

    .assistant-actions {
      display: flex;
      gap: 4px;
      margin-top: 6px;
      opacity: 0;
      transition: opacity 0.2s;
    }

    &:hover .assistant-actions {
      opacity: 1;
    }
  }
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
```

### 5.6 ChatMessageToolCall.vue — 工具调用确认卡片

```vue
<!-- src/components/ai-chat/ChatMessageToolCall.vue -->
<template>
  <div class="chat-message-tool-call">
    <div class="tool-call-card">
      <!-- 头部 -->
      <div class="tool-call-header">
        <n-icon size="16" class="tool-icon"><ToolOutlined /></n-icon>
        <span class="tool-title">工具调用请求</span>
        <n-tag size="tiny" type="warning" :bordered="false">待确认</n-tag>
      </div>

      <!-- 工具列表 -->
      <div class="tool-list">
        <div v-for="tc in toolCalls" :key="tc.id" class="tool-item">
          <div class="tool-name">
            <n-icon size="14"><ApiOutlined /></n-icon>
            <code>{{ tc.function.name }}</code>
          </div>
          <pre class="tool-args">{{ formatArgs(tc.function.arguments) }}</pre>
        </div>
      </div>

      <!-- 提示 -->
      <n-alert type="warning" :show-icon="true" size="small" style="margin-top: 8px">
        <template #header>权限确认</template>
        此操作将调用后端 API 并可能修改数据。请确认是否允许执行？
      </n-alert>

      <!-- 操作按钮 -->
      <div class="tool-actions">
        <n-button size="small" @click="handleRejectAll">
          <template #icon><n-icon><CloseOutlined /></n-icon></template>
          拒绝
        </n-button>
        <n-button size="small" type="primary" @click="handleConfirmAll">
          <template #icon><n-icon><CheckOutlined /></n-icon></template>
          确认执行
        </n-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { NIcon, NTag, NAlert, NButton } from 'naive-ui'
import { ToolOutlined, ApiOutlined, CheckOutlined, CloseOutlined } from '@vicons/antd'
import type { ToolCall } from '@/types/chat'

const props = defineProps<{
  toolCalls: ToolCall[]
  timestamp: string
}>()

const emit = defineEmits<{
  (e: 'confirm', toolCall: ToolCall): void
  (e: 'reject', toolCall: ToolCall): void
}>()

function formatArgs(args: string): string {
  try {
    const parsed = JSON.parse(args)
    return JSON.stringify(parsed, null, 2)
  } catch {
    return args
  }
}

function handleConfirmAll() {
  props.toolCalls.forEach(tc => emit('confirm', tc))
}

function handleRejectAll() {
  props.toolCalls.forEach(tc => emit('reject', tc))
}
</script>

<style scoped lang="scss">
.chat-message-tool-call {
  display: flex;
  gap: 10px;
  align-items: flex-start;

  &::before {
    content: '';
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: #f59e0b;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .tool-call-card {
    flex: 1;
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 12px;

    .tool-call-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;

      .tool-icon { color: #f59e0b; }
      .tool-title { font-weight: 600; font-size: 13px; flex: 1; }
    }

    .tool-list {
      display: flex;
      flex-direction: column;
      gap: 8px;

      .tool-item {
        background: var(--code-bg);
        border-radius: 6px;
        padding: 8px 10px;

        .tool-name {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-bottom: 4px;

          code {
            font-weight: 600;
            font-size: 13px;
          }
        }

        .tool-args {
          margin: 0;
          padding: 6px 8px;
          background: var(--code-block-bg);
          border-radius: 4px;
          font-size: 11px;
          font-family: monospace;
          overflow-x: auto;
          white-space: pre-wrap;
          word-break: break-all;
        }
      }
    }

    .tool-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 10px;
    }
  }
}
</style>
```

### 5.7 ChatInputArea.vue — 输入区域

```vue
<!-- src/components/ai-chat/ChatInputArea.vue -->
<template>
  <div class="chat-input-area">
    <!-- 附件预览 -->
    <div v-if="attachments.length > 0" class="attachments-bar">
      <n-tag
        v-for="(file, i) in attachments"
        :key="i"
        closable
        size="small"
        @close="removeAttachment(i)"
      >
        {{ file.name }}
      </n-tag>
    </div>

    <!-- 输入框 -->
    <div class="input-row">
      <n-input
        ref="inputRef"
        v-model:value="inputText"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 6 }"
        :placeholder="placeholder"
        :disabled="disabled"
        @keydown.enter.prevent="handleEnter"
      />

      <div class="input-actions">
        <!-- 附件按钮 -->
        <n-tooltip>
          <template #trigger>
            <n-button text circle size="small" :disabled="disabled">
              <template #icon><n-icon><PaperClipOutlined /></n-icon></template>
            </n-button>
          </template>
          添加附件
        </n-tooltip>

        <!-- 发送/停止按钮 -->
        <n-button
          v-if="!disabled"
          type="primary"
          circle
          size="small"
          :disabled="!canSend"
          @click="handleSend"
        >
          <template #icon><n-icon><SendOutlined /></n-icon></template>
        </n-button>

        <n-button
          v-else
          type="error"
          circle
          size="small"
          @click="$emit('stop')"
        >
          <template #icon><n-icon><StopOutlined /></n-icon></template>
        </n-button>
      </div>
    </div>

    <!-- 底部提示 -->
    <div class="input-footer">
      <span class="hint-text">Enter 发送 / Shift+Enter 换行</span>
      <span class="context-hint" v-if="contextHint">
        <n-icon size="10"><LinkOutlined /></n-icon>
        {{ contextHint }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NInput, NButton, NIcon, NTag, NTooltip } from 'naive-ui'
import {
  SendOutlined, StopOutlined, PaperClipOutlined, LinkOutlined,
} from '@vicons/antd'

const props = defineProps<{
  disabled: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'send', content: string): void
  (e: 'stop'): void
}>()

const inputText = ref('')
const inputRef = ref<InstanceType<typeof NInput>>()
const attachments = ref<File[]>([])
const contextHint = ref('') // 上下文提示

const canSend = computed(() => inputText.value.trim().length > 0)

function handleSend() {
  const content = inputText.value.trim()
  if (!content) return
  emit('send', content)
  inputText.value = ''
}

function handleEnter(e: KeyboardEvent) {
  if (e.shiftKey) {
    // Shift+Enter = 换行（默认行为）
    return
  }
  // Enter = 发送
  handleSend()
}

function removeAttachment(index: number) {
  attachments.value.splice(index, 1)
}
</script>

<style scoped lang="scss">
.chat-input-area {
  border-top: 1px solid var(--border-color);
  padding: 10px 12px;
  flex-shrink: 0;
  background: var(--chat-bg);

  .attachments-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }

  .input-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;

    :deep(.n-input) {
      flex: 1;
      min-width: 0;
    }

    .input-actions {
      display: flex;
      align-items: center;
      gap: 4px;
      flex-shrink: 0;
    }
  }

  .input-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 6px;

    .hint-text {
      font-size: 10px;
      color: var(--text-tertiary);
    }

    .context-hint {
      font-size: 10px;
      color: var(--primary-color);
      display: flex;
      align-items: center;
      gap: 4px;
    }
  }
}
</style>
```

### 5.8 ChatContextBar.vue — 上下文指示器

```vue
<!-- src/components/ai-chat/ChatContextBar.vue -->
<template>
  <div v-if="hasContext" class="chat-context-bar">
    <div class="context-items">
      <n-tag
        v-if="context.projectId"
        size="tiny"
        type="success"
        closable
        @close="$emit('clear-context', 'project')"
      >
        <template #icon><n-icon><FolderOutlined /></n-icon></template>
        {{ projectName || '项目' }}
      </n-tag>

      <n-tag
        v-if="context.flowId"
        size="tiny"
        type="info"
        closable
        @close="$emit('clear-context', 'flow')"
      >
        <template #icon><n-icon><ApartmentOutlined /></n-icon></template>
        {{ flowName || '流程' }}
      </n-tag>

      <n-tag
        v-if="context.taskId"
        size="tiny"
        :type="taskTagType"
        closable
        @close="$emit('clear-context', 'task')"
      >
        <template #icon><n-icon><ExperimentOutlined /></n-icon></template>
        任务 {{ context.taskId.slice(0, 8) }}
        <span v-if="taskStatus" class="status-dot">{{ taskStatus }}</span>
      </n-tag>
    </div>

    <n-tooltip placement="top">
      <template #trigger>
        <n-icon size="12" class="context-info-icon"><InfoCircleOutlined /></n-icon>
      </template>
      AI 助手已自动获取当前页面上下文，可据此提供精准回答
    </n-tooltip>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NTag, NIcon, NTooltip } from 'naive-ui'
import { FolderOutlined, ApartmentOutlined, ExperimentOutlined, InfoCircleOutlined } from '@vicons/antd'
import type { ChatContext } from '@/types/chat'

const props = defineProps<{
  context: ChatContext
  projectName: string | null
  flowName: string | null
  taskStatus: string | undefined
}>()

const emit = defineEmits<{
  (e: 'clear-context', type: 'project' | 'flow' | 'task' | 'all'): void
}>()

const hasContext = computed(() =>
  props.context.projectId || props.context.flowId || props.context.taskId
)

const taskTagType = computed(() => {
  switch (props.taskStatus) {
    case 'completed': return 'success'
    case 'failed': return 'error'
    case 'running': return 'warning'
    default: return 'default'
  }
})
</script>

<style scoped lang="scss">
.chat-context-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: var(--context-bar-bg);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;

  .context-items {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;

    .status-dot {
      margin-left: 4px;
      opacity: 0.8;
    }
  }

  .context-info-icon {
    color: var(--text-tertiary);
    cursor: help;
  }
}
</style>
```

### 5.9 AI Agent 内部工具定义

```typescript
// src/types/chat.ts — 工具定义类型

/** Tool Call 结构 */
export interface ToolCall {
  id: string
  type: 'function'
  function: {
    name: string
    arguments: string // JSON 字符串
  }
}

/** 前端可调用的内部 API 工具定义 */
export interface InternalTool {
  name: string
  description: string
  parameters: Record<string, {
    type: string
    description: string
    required?: boolean
    enum?: string[]
  }>
  handler: (args: Record<string, any>) => Promise<any>
}

/** 前端内部工具注册表 */
export const INTERNAL_TOOLS: InternalTool[] = [
  {
    name: 'submit_job',
    description: '提交一个分析任务',
    parameters: {
      flow_id: { type: 'string', description: '流程 ID', required: true },
      project_id: { type: 'string', description: '项目 ID', required: true },
      params: { type: 'object', description: '任务参数', required: true },
      description: { type: 'string', description: '任务描述' },
    },
    handler: async (args) => {
      const { taskApi } = await import('@/api/task')
      return taskApi.submit(args)
    },
  },
  {
    name: 'query_samples',
    description: '查询项目中的样本列表',
    parameters: {
      project_id: { type: 'string', description: '项目 ID', required: true },
    },
    handler: async (args) => {
      const { projectApi } = await import('@/api/project')
      return projectApi.getSamples(args.project_id)
    },
  },
  {
    name: 'list_projects',
    description: '列出当前用户可访问的项目',
    parameters: {
      keyword: { type: 'string', description: '搜索关键词' },
    },
    handler: async (args) => {
      const { projectApi } = await import('@/api/project')
      return projectApi.list(args)
    },
  },
  {
    name: 'get_task_status',
    description: '获取任务的详细状态和进度',
    parameters: {
      task_id: { type: 'string', description: '任务 ID', required: true },
    },
    handler: async (args) => {
      const { taskApi } = await import('@/api/task')
      return taskApi.getDetail(args.task_id)
    },
  },
  {
    name: 'query_flow_params',
    description: '查询流程的参数说明',
    parameters: {
      flow_id: { type: 'string', description: '流程 ID', required: true },
    },
    handler: async (args) => {
      const { flowApi } = await import('@/api/flow')
      return flowApi.getSchema(args.flow_id)
    },
  },
  {
    name: 'preview_result',
    description: '预览结果文件的内容',
    parameters: {
      task_id: { type: 'string', description: '任务 ID', required: true },
      file_path: { type: 'string', description: '文件路径', required: true },
      max_lines: { type: 'integer', description: '最大行数', required: false },
    },
    handler: async (args) => {
      const { taskApi } = await import('@/api/task')
      return taskApi.previewResult(args.task_id, args.file_path, args.max_lines)
    },
  },
]

/** 工具调用确认中间件 */
export async function executeWithConfirmation(
  toolCall: ToolCall,
  onConfirm: () => void,
  onReject: () => void,
): Promise<any> {
  // 所有工具调用都必须经过用户确认
  // 此函数由前端 UI 调用（在用户点击确认按钮后）
  const tool = INTERNAL_TOOLS.find(t => t.name === toolCall.function.name)
  if (!tool) {
    throw new Error(`未知工具: ${toolCall.function.name}`)
  }

  let args: Record<string, any>
  try {
    args = JSON.parse(toolCall.function.arguments)
  } catch {
    throw new Error('工具参数解析失败')
  }

  return tool.handler(args)
}
```

### 5.10 WebSocket 消息处理流程图

```
┌──────────────────┐
│  WebSocket 收到消息 │
└────────┬─────────┘
         │
    ┌────▼────┐
    │ 解析 type  │
    └────┬────┘
         │
    ┌────▼────────────┐
    │ chat.message_chunk │ ──→ 追加到 streamingContent，触发 UI 更新
    └─────────────────┘
         │
    ┌────▼────────────┐
    │ chat.message_end   │ ──→ 组装完整消息，添加到 messages 列表
    └─────────────────┘
         │
    ┌────▼────────────────┐
    │ chat.tool_call_request │ ──→ 渲染 ToolConfirmCard.vue，等待用户确认
    └─────────────────────┘
         │
    ┌────▼────────────────┐
    │ chat.tool_result       │ ──→ 渲染工具执行结果卡片
    └─────────────────────┘
         │
    ┌────▼────────────────┐
    │ chat.mcp_result        │ ──→ 渲染 MCP 工具结果特殊卡片
    └─────────────────────┘
         │
    ┌────▼────┐
    │    error   │ ──→ 渲染错误消息
    └─────────┘
         │
    ┌────▼────┐
    │    pong    │ ──→ 心跳响应（无 UI 操作）
    └─────────┘
```



---

## 6. 暗黑模式实现

### 6.1 Naive UI ConfigProvider 配置

Naive UI 的暗黑模式通过 `ConfigProvider` 的 `theme` 属性控制：

```typescript
// Naive UI 主题切换逻辑
import { darkTheme, lightTheme } from 'naive-ui'

// Dark: 传入 darkTheme 对象
<n-config-provider :theme="darkTheme">

// Light: 传入 null（默认就是亮色）
<n-config-provider :theme="null">
```

已在 `MainLayout.vue`、`AdminLayout.vue`、`BlankLayout.vue` 中通过 `themeStore.naiveTheme` 统一注入。

### 6.2 CSS 变量切换方案

```scss
// src/styles/variables.scss
// ═══════════════════════════════════════════
// 亮色模式（默认）
// ═══════════════════════════════════════════
:root {
  // 主色
  --primary-color: #6366f1;
  --primary-hover: #818cf8;
  --primary-pressed: #4f46e5;

  // 背景
  --bg-base: #ffffff;
  --bg-elevated: #fafafa;
  --content-bg: #f5f5f7;
  --chat-bg: #ffffff;
  --card-bg: #ffffff;
  --hover-bg: rgba(0, 0, 0, 0.04);
  --code-bg: rgba(0, 0, 0, 0.05);
  --code-block-bg: #1e1e2e;
  --context-bar-bg: #fafafa;
  --table-header-bg: #f0f0f0;
  --toolbar-bg: #fafafa;

  // 文字
  --text-primary: #1f2937;
  --text-secondary: #6b7280;
  --text-tertiary: #9ca3af;

  // 边框
  --border-color: #e5e7eb;
  --divider-bg: #f0f0f0;

  // 日志
  --log-bg: #0d1117;

  // 状态色
  --success-color: #10b981;
  --warning-color: #f59e0b;
  --error-color: #ef4444;
  --info-color: #3b82f6;
}

// ═══════════════════════════════════════════
// 暗黑模式
// ═══════════════════════════════════════════
.dark {
  // 主色（保持不变，primary 是品牌色）
  --primary-color: #818cf8;
  --primary-hover: #a5b4fc;
  --primary-pressed: #6366f1;

  // 背景
  --bg-base: #0f0f23;
  --bg-elevated: #1a1a2e;
  --content-bg: #13131f;
  --chat-bg: #16162a;
  --card-bg: #1e1e32;
  --hover-bg: rgba(255, 255, 255, 0.05);
  --code-bg: rgba(255, 255, 255, 0.08);
  --code-block-bg: #13131f;
  --context-bar-bg: #1a1a2e;
  --table-header-bg: #252540;
  --toolbar-bg: #1a1a2e;

  // 文字
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-tertiary: #64748b;

  // 边框
  --border-color: #2e2e4a;
  --divider-bg: #2e2e4a;

  // 日志
  --log-bg: #0a0a14;

  // 状态色（提高暗色下饱和度）
  --success-color: #34d399;
  --warning-color: #fbbf24;
  --error-color: #f87171;
  --info-color: #60a5fa;
}

// ═══════════════════════════════════════════
// 平滑过渡
// ═══════════════════════════════════════════
*, *::before, *::after {
  transition: background-color 0.3s ease,
              border-color 0.3s ease,
              color 0.3s ease;
}

// 排除不需要动画的元素
.no-theme-transition,
.no-theme-transition * {
  transition: none !important;
}
```

### 6.3 ThemeToggle.vue — 主题切换按钮

```vue
<!-- src/components/common/ThemeToggle.vue -->
<template>
  <n-tooltip placement="bottom">
    <template #trigger>
      <n-button text circle size="small" @click="themeStore.toggleTheme()">
        <template #icon>
          <n-icon size="18">
            <SunnyOutlined v-if="themeStore.isDark" />
            <MoonOutlined v-else />
          </n-icon>
        </template>
      </n-button>
    </template>
    {{ themeStore.isDark ? '切换到亮色模式' : '切换到暗黑模式' }}
  </n-tooltip>
</template>

<script setup lang="ts">
import { NButton, NIcon, NTooltip } from 'naive-ui'
import { SunnyOutlined, MoonOutlined } from '@vicons/antd'
import { useThemeStore } from '@/stores/modules/theme'

const themeStore = useThemeStore()
</script>
```

### 6.4 防止 FOUC（Flash of Unstyled Content）

```html
<!-- index.html —— 在 head 中添加内联脚本，在页面渲染前执行 -->
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" href="/favicon.ico" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>OmicsHub</title>

    <!-- 主题防闪烁脚本（必须在最前面执行） -->
    <script>
      (function() {
        const saved = localStorage.getItem('theme_mode') || 'system'
        const isDark = saved === 'dark' || (saved === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
        if (isDark) {
          document.documentElement.classList.add('dark')
        }
      })()
    </script>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

### 6.5 main.ts — 应用入口

```typescript
// src/main.ts
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import pinia from './stores'

// Naive UI 全局样式
import 'naive-ui/es/message/style/css'
import 'naive-ui/es/dialog/style/css'
import 'naive-ui/es/notification/style/css'
import 'naive-ui/es/loading-bar/style/css'

// 全局样式
import '@/styles/variables.scss'
import '@/styles/global.scss'

const app = createApp(App)

app.use(pinia)
app.use(router)

app.mount('#app')
```

---

## 7. 文件目录结构总览

### 7.1 完整目录树

```
src/
├── App.vue                          # 根组件（仅挂载 RouterView）
├── main.ts                          # 入口
├── env.d.ts                         # 环境类型声明
│
├── api/                             # API 请求层
│   ├── request.ts                   # Axios 封装（拦截器、错误处理）
│   ├── auth.ts                      # 认证 API
│   ├── task.ts                      # 任务 API
│   ├── flow.ts                      # 流程 API
│   ├── project.ts                   # 项目 API
│   ├── chat.ts                      # AI 对话 API
│   ├── mcp.ts                       # MCP API
│   └── types.ts                     # API 类型
│
├── assets/                          # 静态资源
│   ├── logo.svg
│   └── icons/
│
├── components/                      # 组件
│   ├── ai-chat/                     # AI 对话面板
│   │   ├── AIChatPanel.vue          # 主面板容器
│   │   ├── AIChatFab.vue            # 折叠浮动按钮
│   │   ├── ChatHeader.vue           # 面板头部
│   │   ├── ChatContextBar.vue       # 上下文指示器
│   │   ├── ChatMessageList.vue      # 消息列表
│   │   ├── ChatMessageUser.vue      # 用户消息
│   │   ├── ChatMessageAssistant.vue # AI 消息（Markdown）
│   │   ├── ChatMessageToolCall.vue  # 工具调用确认卡片
│   │   ├── ChatMessageToolResult.vue# 工具结果卡片
│   │   ├── ChatMessageMCPResult.vue # MCP 结果卡片
│   │   ├── ChatInputArea.vue        # 输入区域
│   │   ├── ChatQuickActions.vue     # 快捷操作
│   │   ├── ChatWelcome.vue          # 欢迎界面
│   │   ├── TypingIndicator.vue      # 输入中动画
│   │   └── SessionDrawer.vue        # 会话列表面板
│   │
│   ├── common/                      # 通用组件
│   │   ├── ThemeToggle.vue          # 主题切换
│   │   ├── StatCard.vue             # 统计卡片
│   │   └── EmptyState.vue           # 空状态
│   │
│   ├── dashboard/                   # 仪表盘
│   │   ├── StatCard.vue
│   │   └── QuickStartItem.vue
│   │
│   ├── dynamic-form/                # 动态表单（核心）
│   │   ├── DynamicForm.vue          # 动态表单主组件
│   │   ├── FormFieldRenderer.vue    # 字段渲染分发器
│   │   ├── ConditionRenderer.vue    # 条件渲染控制器
│   │   ├── GroupRepeater.vue        # 可重复组
│   │   ├── SectionCollapsible.vue   # 折叠区域
│   │   ├── validation.ts            # 校验规则构建
│   │   ├── utils.ts                 # 工具函数
│   │   └── fields/                  # 具体字段组件
│   │       ├── StringField.vue
│   │       ├── TextField.vue
│   │       ├── NumberField.vue
│   │       ├── BooleanField.vue
│   │       ├── SelectField.vue
│   │       ├── MultiSelectField.vue
│   │       ├── RadioField.vue
│   │       ├── CheckboxField.vue
│   │       ├── FileField.vue
│   │       ├── FileUploadField.vue
│   │       ├── SampleField.vue
│   │       ├── SampleSheetField.vue
│   │       ├── RangeField.vue
│   │       ├── ArrayField.vue
│   │       ├── RefField.vue
│   │       ├── GroupField.vue
│   │       ├── DividerField.vue
│   │       └── InfoField.vue
│   │
│   ├── flow/                        # 流程市场
│   │   ├── FlowCard.vue             # 流程卡片
│   │   └── FlowDetailModal.vue      # 流程详情弹窗
│   │
│   ├── layout/                      # 布局组件
│   │   ├── AppSidebar.vue           # 左侧导航
│   │   ├── AppHeader.vue            # 顶部 Header
│   │   ├── AppBreadcrumb.vue        # 面包屑
│   │   ├── UserDropdown.vue         # 用户下拉菜单
│   │   └── NotificationBell.vue     # 通知铃铛
│   │
│   ├── project/                     # 项目
│   │   ├── CreateProjectModal.vue   # 创建项目弹窗
│   │   ├── FileManager.vue          # 文件管理器
│   │   └── SampleTable.vue          # 样本表
│   │
│   └── task/                        # 任务
│       ├── TaskTableLite.vue        # 精简任务表格
│       ├── submit/                  # 任务提交
│       │   ├── FlowSelector.vue     # 流程选择器
│       │   ├── ProjectSelector.vue  # 项目选择器
│       │   └── TaskSubmitPreview.vue# 提交预览
│       ├── detail/                  # 任务详情
│       │   ├── TaskDetailHeader.vue # 任务头部
│       │   ├── TaskProgressBar.vue  # 进度条
│       │   ├── TaskOverviewTab.vue  # 概览标签
│       │   ├── TaskLogViewer.vue    # 日志查看器
│       │   ├── TaskResultViewer.vue # 结果查看器
│       │   ├── TaskParamsTab.vue    # 参数标签
│       │   └── previews/            # 预览组件
│       │       ├── CsvTablePreview.vue
│       │       ├── ImagePreview.vue
│       │       ├── HtmlReportPreview.vue
│       │       └── TextPreview.vue
│       └── detail.ts                # 详情页类型
│
├── composables/                     # 组合式函数
│   ├── useTaskLogWebSocket.ts       # 任务日志 WebSocket
│   ├── useTaskResult.ts             # 任务结果获取
│   ├── useChatWebSocket.ts          # 聊天 WebSocket
│   ├── useTheme.ts                  # 主题 Hook
│   └── usePermission.ts             # 权限 Hook
│
├── layouts/                         # 布局
│   ├── BlankLayout.vue              # 空布局（登录/注册）
│   ├── MainLayout.vue               # 主布局（工作区 + AI 面板）
│   └── AdminLayout.vue              # 管理后台布局
│
├── router/                          # 路由
│   ├── index.ts                     # 路由实例
│   ├── routes.ts                    # 路由表定义
│   ├── guard.ts                     # 路由守卫
│   └── types.ts                     # 路由类型扩展
│
├── stores/                          # Pinia 状态管理
│   ├── index.ts                     # Pinia 实例
│   └── modules/
│       ├── auth.ts                  # 认证
│       ├── user.ts                  # 用户
│       ├── project.ts               # 项目
│       ├── flow.ts                  # 流程
│       ├── task.ts                  # 任务
│       ├── chat.ts                  # AI 对话
│       ├── mcp.ts                   # MCP
│       ├── notification.ts          # 通知
│       ├── theme.ts                 # 主题
│       └── tab.ts                   # 标签页
│
├── styles/                          # 样式
│   ├── variables.scss               # CSS 变量
│   ├── global.scss                  # 全局样式
│   ├── naive-overrides.scss         # Naive UI 样式覆盖
│   └── markdown.scss                # Markdown 渲染样式
│
├── types/                           # 全局类型
│   ├── auth.ts
│   ├── task.ts
│   ├── flow.ts
│   ├── project.ts
│   ├── chat.ts
│   ├── mcp.ts
│   └── common.ts
│
├── utils/                           # 工具函数
│   ├── time.ts                      # 时间格式化
│   ├── ansi.ts                      # ANSI 颜色解析
│   ├── naiveMessage.ts             # Naive UI message 封装
│   ├── validators.ts               # 表单校验
│   └── file.ts                     # 文件操作
│
└── views/                           # 页面视图
    ├── auth/                        # 认证
    │   ├── LoginView.vue
    │   └── RegisterView.vue
    ├── dashboard/                   # 仪表盘
    │   └── DashboardView.vue
    ├── project/                     # 项目
    │   ├── ProjectsView.vue
    │   ├── ProjectDetailView.vue
    │   ├── ProjectSamplesView.vue
    │   └── ProjectFilesView.vue
    ├── flow/                        # 流程市场
    │   ├── FlowMarketView.vue
    │   └── FlowDetailView.vue
    ├── task/                        # 任务
    │   ├── TaskListView.vue
    │   ├── TaskSubmitView.vue
    │   └── TaskDetailView.vue
    ├── admin/                       # 管理后台
    │   ├── AdminFlowManager.vue
    │   ├── AdminUserManager.vue
    │   ├── AdminMCPManager.vue
    │   └── AdminSystemSettings.vue
    ├── profile/                     # 个人设置
    │   └── ProfileView.vue
    └── error/                       # 错误页
        └── NotFoundView.vue
```

### 7.2 组件依赖关系图

```
App.vue
  └─ <router-view>
      ├─ BlankLayout
      │   └─ LoginView / RegisterView / NotFoundView
      │
      ├─ MainLayout
      │   ├─ AppSidebar
      │   ├─ AppHeader (ThemeToggle, UserDropdown, NotificationBell)
      │   ├─ AppBreadcrumb
      │   ├─ <router-view>
      │   │   ├─ DashboardView (StatCard, QuickStartItem, TaskTableLite)
      │   │   ├─ ProjectsView (CreateProjectModal)
      │   │   ├─ ProjectDetailView (SampleTable, FileManager)
      │   │   ├─ FlowMarketView (FlowCard)
      │   │   ├─ TaskListView (TaskTableLite)
      │   │   ├─ TaskSubmitView ── DynamicForm ── FormFieldRenderer
      │   │   │                      │               └─ *Field.vue x 18
      │   │   │                      ├─ ConditionRenderer
      │   │   │                      ├─ GroupRepeater
      │   │   │                      └─ SectionCollapsible
      │   │   └─ TaskDetailView
      │   │       ├─ TaskDetailHeader
      │   │       ├─ TaskProgressBar
      │   │       ├─ TaskOverviewTab
      │   │       ├─ TaskLogViewer (WebSocket)
      │   │       ├─ TaskResultViewer
      │   │       │   ├─ CsvTablePreview
      │   │       │   ├─ ImagePreview
      │   │       │   ├─ HtmlReportPreview
      │   │       │   └─ TextPreview
      │   │       └─ TaskParamsTab
      │   │
      │   ├─ AIChatPanel
      │   │   ├─ ChatHeader
      │   │   ├─ ChatContextBar
      │   │   ├─ ChatMessageList
      │   │   │   ├─ ChatWelcome
      │   │   │   ├─ ChatMessageUser
      │   │   │   ├─ ChatMessageAssistant (Markdown)
      │   │   │   ├─ ChatMessageToolCall (确认卡片)
      │   │   │   ├─ ChatMessageToolResult
      │   │   │   ├─ ChatMessageMCPResult
      │   │   │   └─ TypingIndicator
      │   │   ├─ ChatQuickActions
      │   │   ├─ ChatInputArea
      │   │   └─ SessionDrawer
      │   │
      │   └─ AIChatFab (折叠时)
      │
      └─ AdminLayout
          ├─ AdminSidebar (menu)
          └─ <router-view>
              ├─ AdminFlowManager
              ├─ AdminUserManager
              ├─ AdminMCPManager
              └─ AdminSystemSettings
```

---

## 附录 A：技术决策记录

### A.1 为什么选择 Naive UI 为主？

| 特性 | Naive UI | Element Plus | 结论 |
|------|----------|--------------|------|
| Vue 3 原生支持 | 优 | 良 | Naive 从 0 开始为 Vue 3 设计 |
| TypeScript 体验 | 优 | 良 | Naive 的类型推断更完善 |
| 暗黑模式 | 内置 ConfigProvider | 需手动配置 | Naive 一行代码切换 |
| 样式定制 | CSS Variables + Theme Editor | SCSS 变量 | Naive 更灵活 |
| 组件丰富度 | 良 | 优 | Element Plus 组件更多，但 Naive 覆盖核心场景 |
| 体积 | 较小（tree-shaking） | 较大 | Naive 按需引入更轻量 |
| 社区生态 | 国内活跃 | 全球更大 | 两者都足够 |

**决策**：以 Naive UI 为主，仅在 Naive UI 不满足需求时使用 Element Plus 补充（如 Complex Table、Cascader 等）。

### A.2 WebSocket 连接策略

| 页面 | 连接时机 | 断开时机 | 说明 |
|------|----------|----------|------|
| AI 对话面板 | 面板展开时 | 面板折叠时 | 用户不需要 AI 时不浪费连接 |
| 任务日志 | 进入任务详情页时 | 离开页面时 | 仅运行中任务需要实时日志 |
| 全局通知 | 登录后 | 登出时 | 全局推送，始终保持 |

### A.3 状态管理策略

| Store 模块 | 数据持久化 | 实时同步 | 说明 |
|-----------|-----------|---------|------|
| auth | localStorage（token） | 无 | token 需持久化 |
| theme | localStorage | 无 | 主题偏好持久化 |
| chat | 无（纯内存） | WebSocket | 会话数据后端存储 |
| task | 无（纯内存） | 轮询 + WS | 每次进入页面重新获取 |
| flow | 无（纯内存） | 无 | Schema 有内存缓存 |
| project | 无（纯内存） | 无 | 每次获取最新列表 |

---

## 附录 B：关键接口类型定义

```typescript
// ═══════════════════════════════════════════
// src/types/flow.ts — 流程相关类型
// ═══════════════════════════════════════════

export interface FlowSummary {
  id: string
  name: string
  description?: string
  category: string
  version: string
  use_count: number
  icon?: string
  created_at: string
}

export interface Flow extends FlowSummary {
  yaml_content: string
  author: string
  params_schema: FlowSchema
  input_types: string[]
  output_types: string[]
}

export interface FlowSchema {
  title: string
  description?: string
  sections: FlowSection[]
}

export interface FlowSection {
  key: string
  title: string
  description?: string
  collapsed?: boolean
  repeatable?: boolean
  fields: FormField[]
}

export interface FormField {
  key: string
  label: string
  type: string
  description?: string
  required?: boolean
  default?: any
  options?: Array<{ label: string; value: any }>
  min?: number
  max?: number
  step?: number
  placeholder?: string
  // 条件渲染
  condition?: {
    field: string
    operator: 'eq' | 'ne' | 'gt' | 'lt' | 'contains' | 'in'
    value: any
  }
  // 验证规则
  validation?: {
    pattern?: string
    minLength?: number
    maxLength?: number
    custom?: string
  }
}

// ═══════════════════════════════════════════
// src/types/task.ts — 任务相关类型
// ═══════════════════════════════════════════

export type TaskStatus =
  | 'pending' | 'queued' | 'running'
  | 'completed' | 'failed' | 'cancelled' | 'cancelling'

export interface Task {
  id: string
  flow_id: string
  project_id: string
  status: TaskStatus
  progress: number          // 0-100
  current_step?: string
  total_steps?: number
  params: Record<string, any>
  description?: string
  output_dir?: string
  error_message?: string
  created_at: string
  started_at?: string
  finished_at?: string
  created_by: string
}

export interface TaskStats {
  runningTasks: number
  completedTasks: number
  failedTasks: number
  queuedTasks: number
}

// ═══════════════════════════════════════════
// src/types/chat.ts — AI 对话相关类型
// ═══════════════════════════════════════════

export interface ChatSession {
  id: string
  title: string
  model: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result' | 'mcp_result'
  content: string
  tool_calls?: ToolCall[]
  tool_call_id?: string
  mcp_server?: string
  tool_name?: string
  result?: any
  is_error?: boolean
  is_streaming?: boolean
  created_at: string
}

export interface ChatContext {
  page: string
  routeParams: Record<string, string>
  routeQuery: Record<string, string>
  projectId: string | null
  flowId: string | null
  taskId: string | null
}

export interface WebSocketMessage {
  type: string
  [key: string]: any
}

export interface AIModelConfig {
  id: string
  name: string
  description?: string
  max_tokens: number
}

// ═══════════════════════════════════════════
// src/types/project.ts — 项目相关类型
// ═══════════════════════════════════════════

export interface Project {
  id: string
  name: string
  description?: string
  sample_count?: number
  task_count?: number
  created_by: string
  created_at: string
}

export interface Sample {
  id: string
  project_id: string
  name: string
  type: string
  metadata: Record<string, any>
  file_path?: string
  created_at: string
}

// ═══════════════════════════════════════════
// src/types/mcp.ts — MCP 相关类型
// ═══════════════════════════════════════════

export interface MCPServer {
  id: string
  name: string
  url: string
  description?: string
  icon?: string
  status: 'active' | 'inactive' | 'error'
  tool_count: number
  created_at: string
}

export interface MCPTool {
  name: string
  server_id: string
  server_name: string
  description: string
  parameters: Record<string, any>
  available: boolean
}
```

---

> **本文档结束** — 以上涵盖了 OmicsHub 前端架构的完整路由设计、三种布局系统、核心页面组件（动态表单、任务详情/日志/结果）、9 个 Pinia Store 模块、AI 对话面板的完整组件树与交互协议、以及暗黑模式实现方案。



---

# 6. OmicsHub 部署运维手册

> **文档版本**: v1.0  
> **适用环境**: 华中农业大学园艺林学学院内网服务器（Linux + Docker）  
> **维护模式**: 单人生信维护，极简运维，一键部署  
> **技术栈**: FastAPI + PostgreSQL 14 + Redis 7 + Celery + Nginx + Snakemake

---

## 6.1 概述

OmicsHub 采用 Docker Compose 进行容器化部署，支持两种运行模式：

| 模式 | 适用场景 | 架构特点 |
|------|----------|----------|
| **local** | 单机部署，计算量适中 | Web应用与计算Worker在同一宿主机，共享Docker网络 |
| **remote** | 多机部署，计算密集型 | Web平台与Master计算节点分离，通过HTTP/WebSocket通信 |

**目录结构**:

```
omichub/
├── docker-compose.yml              # local模式主文件 / remote模式Web平台
├── docker-compose.master.yml       # remote模式Master计算节点
├── docker-compose.override.yml     # 本地开发覆盖（可选）
├── .env                            # 环境变量（不提交Git）
├── .env.example                    # 环境变量模板
├── init.sh                         # 一键初始化脚本
├── backend/
│   ├── Dockerfile                  # Web + Celery Worker镜像
│   ├── requirements.txt
│   ├── alembic/                    # 数据库迁移
│   └── app/                        # FastAPI应用
├── master/
│   ├── Dockerfile                  # Master节点独立镜像
│   ├── requirements.txt
│   └── app/                        # Master Executor Service
├── nginx/
│   ├── nginx.conf                  # Nginx主配置
│   └── ssl/                        # SSL证书（生产环境）
├── frontend/dist/                  # 前端构建产物
├── workflows/                      # Snakefile存放
│   ├── rna_seq/
│   ├── atac_seq/
│   └── scRNA_seq/
└── scripts/
    ├── backup.sh                   # 数据备份脚本
    └── health_check.sh             # 健康检查脚本
```

---

## 6.2 Local 模式 — docker-compose.yml（单机部署）

local模式适用于单台物理机部署，所有服务运行在同一Docker网络中。Celery Worker与Web应用复用同一镜像，直接通过`asyncio.subprocess`执行Snakemake任务。

```yaml
# =============================================================================
# OmicsHub Docker Compose - Local Mode
# 单机部署：Web + DB + Redis + Celery Worker/Beat + Flower + Nginx
# =============================================================================
version: "3.8"

x-backend-env: &backend-env
  # --- 执行模式 ---
  EXECUTION_MODE: local
  SNAKEMAKE_CORES: ${SNAKEMAKE_CORES:-8}
  CONDA_ENV_PATH: /opt/conda/envs

  # --- 数据库 ---
  DATABASE_URL: postgresql://${POSTGRES_USER:-omicshub}:${POSTGRES_PASSWORD:-changeme}@db:5432/${POSTGRES_DB:-omicshub}
  POSTGRES_USER: ${POSTGRES_USER:-omicshub}
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
  POSTGRES_DB: ${POSTGRES_DB:-omicshub}
  POSTGRES_HOST: db
  POSTGRES_PORT: 5432

  # --- Redis ---
  REDIS_URL: redis://:${REDIS_PASSWORD:-}@redis:6379/0
  REDIS_HOST: redis
  REDIS_PORT: 6379
  REDIS_PASSWORD: ${REDIS_PASSWORD:-}

  # --- Celery ---
  CELERY_BROKER_URL: redis://:${REDIS_PASSWORD:-}@redis:6379/0
  CELERY_RESULT_BACKEND: redis://:${REDIS_PASSWORD:-}@redis:6379/1

  # --- 安全密钥 ---
  SECRET_KEY: ${SECRET_KEY:-your-super-secret-jwt-key-change-in-production}
  INTERNAL_TOKEN: ${INTERNAL_TOKEN:-internal-token-change-me}

  # --- API密钥（可选）---
  KIMI_API_KEY: ${KIMI_API_KEY:-}
  OPENAI_API_KEY: ${OPENAI_API_KEY:-}

  # --- 存储路径 ---
  SHARED_STORAGE_PATH: /data
  WORKFLOW_PATH: /workflows

  # --- 应用配置 ---
  LOG_LEVEL: ${LOG_LEVEL:-INFO}
  MAX_UPLOAD_SIZE: ${MAX_UPLOAD_SIZE:-1073741824}
  ADMIN_EMAIL: ${ADMIN_EMAIL:-admin@example.com}
  ADMIN_PASSWORD: ${ADMIN_PASSWORD:-admin123}

x-backend-volumes: &backend-volumes
  - ${DATA_PATH:-/data/omicshub}:/data
  - ${WORKFLOW_PATH:-./workflows}:/workflows:ro
  - ${REFERENCE_PATH:-/data/omicshub/references}:/references:ro
  - ${CONDA_ENV_PATH:-/opt/conda/envs}:/opt/conda/envs
  - backend_logs:/app/logs

services:
  # =========================================================================
  # web: FastAPI主应用
  # =========================================================================
  web:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-web
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"  # 仅本地回环，通过Nginx代理
    volumes: *backend-volumes
    environment:
      <<: *backend-env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 256M

  # =========================================================================
  # db: PostgreSQL 14
  # =========================================================================
  db:
    image: postgres:14-alpine
    container_name: omicshub-db
    restart: unless-stopped
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sh:/docker-entrypoint-initdb.d/init-db.sh:ro
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-omicshub}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
      POSTGRES_DB: ${POSTGRES_DB:-omicshub}
      PGDATA: /var/lib/postgresql/data/pgdata
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-omicshub} -d ${POSTGRES_DB:-omicshub}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.25'
          memory: 128M

  # =========================================================================
  # redis: Redis 7
  # =========================================================================
  redis:
    image: redis:7-alpine
    container_name: omicshub-redis
    restart: unless-stopped
    command: >
      sh -c 'redis-server 
      --appendonly yes 
      --appendfsync everysec 
      --maxmemory 512mb 
      --maxmemory-policy allkeys-lru 
      --requirepass "${REDIS_PASSWORD:-}"'
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.1'
          memory: 64M

  # =========================================================================
  # celery_worker: Celery Worker（含Snakemake执行环境）
  # =========================================================================
  celery_worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-celery-worker
    restart: unless-stopped
    command: >
      celery -A app.celery_app worker
      -l ${LOG_LEVEL:-info}
      -Q snakemake,default
      -n worker-local@%h
      --concurrency 2
      --prefetch-multiplier 1
      -Ofair
    volumes: *backend-volumes
    environment:
      <<: *backend-env
      C_FORCE_ROOT: "true"  # 允许root运行Celery（容器内必需）
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "celery -A app.celery_app inspect ping --destination worker-local@$$HOSTNAME || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: ${WORKER_CPU_LIMIT:-8.0}
          memory: ${WORKER_MEM_LIMIT:-16G}
        reservations:
          cpus: '1.0'
          memory: 1G
    # 本地模式下Worker承载Snakemake计算，资源限制根据实际硬件调整
    # 建议：Worker内存 >= 16G，CPU核心数 >= 8

  # =========================================================================
  # celery_beat: Celery Beat（定时任务调度）
  # =========================================================================
  celery_beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-celery-beat
    restart: unless-stopped
    command: >
      celery -A app.celery_app beat
      -l ${LOG_LEVEL:-info}
      --scheduler django_celery_beat.schedulers:DatabaseScheduler
      --max-interval 300
    volumes:
      - ${DATA_PATH:-/data/omicshub}:/data
      - backend_logs:/app/logs
    environment:
      <<: *backend-env
    depends_on:
      - db
      - redis
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  # =========================================================================
  # flower: Celery监控面板
  # =========================================================================
  flower:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-flower
    restart: unless-stopped
    command: >
      celery -A app.celery_app flower
      --port=5555
      --broker=redis://:${REDIS_PASSWORD:-}@redis:6379/0
      --basic-auth=${FLOWER_USER:-admin}:${FLOWER_PASSWORD:-flower123}
      --url-prefix=flower
    environment:
      <<: *backend-env
    depends_on:
      - redis
      - celery_worker
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  # =========================================================================
  # nginx: 反向代理
  # =========================================================================
  nginx:
    image: nginx:alpine
    container_name: omicshub-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/dist:/usr/share/nginx/html:ro
      - ${DATA_PATH:-/data/omicshub}:/data:ro  # 文件下载
      - ./nginx/ssl:/etc/nginx/ssl:ro  # SSL证书（可选）
    depends_on:
      - web
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/api/v1/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M

# =============================================================================
# 数据卷定义
# =============================================================================
volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  backend_logs:
    driver: local

# =============================================================================
# 网络定义
# =============================================================================
networks:
  omicshub_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
    internal: false
```

---

### 6.2.1 Local 模式环境变量完整列表

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `EXECUTION_MODE` | `local` | 执行模式：local 或 remote |
| `SNAKEMAKE_CORES` | `8` | Snakemake默认使用CPU核心数 |
| `CONDA_ENV_PATH` | `/opt/conda/envs` | Conda环境路径 |
| `POSTGRES_USER` | `omicshub` | PostgreSQL用户名 |
| `POSTGRES_PASSWORD` | `changeme` | PostgreSQL密码（**生产环境必须修改**） |
| `POSTGRES_DB` | `omicshub` | PostgreSQL数据库名 |
| `REDIS_PASSWORD` | `` | Redis密码（建议设置） |
| `SECRET_KEY` | `your-super-secret-jwt-key` | JWT签名密钥（**生产环境必须修改**） |
| `INTERNAL_TOKEN` | `internal-token` | Master回调认证令牌（remote模式必需） |
| `KIMI_API_KEY` | `` | Kimi AI API密钥（可选） |
| `OPENAI_API_KEY` | `` | OpenAI API密钥（可选） |
| `DATA_PATH` | `/data/omicshub` | 数据持久化路径（宿主机） |
| `WORKFLOW_PATH` | `./workflows` | Snakefile存放路径（宿主机） |
| `REFERENCE_PATH` | `/data/omicshub/references` | 参考基因组路径（宿主机） |
| `LOG_LEVEL` | `INFO` | 日志级别：DEBUG/INFO/WARNING/ERROR |
| `MAX_UPLOAD_SIZE` | `1073741824` | 最大上传文件大小（字节，默认1GB） |
| `ADMIN_EMAIL` | `admin@example.com` | 默认管理员邮箱 |
| `ADMIN_PASSWORD` | `admin123` | 默认管理员密码（**首次登录后必须修改**） |
| `FLOWER_USER` | `admin` | Flower监控面板用户名 |
| `FLOWER_PASSWORD` | `flower123` | Flower监控面板密码 |
| `WORKER_CPU_LIMIT` | `8.0` | Celery Worker CPU限制 |
| `WORKER_MEM_LIMIT` | `16G` | Celery Worker内存限制 |

---

### 6.2.2 Local 模式卷挂载规划

| 挂载点 | 说明 | 权限 |
|--------|------|------|
| `${DATA_PATH}:/data` | 任务数据、上传文件、结果持久化 | 读写 |
| `${WORKFLOW_PATH}:/workflows` | Snakefile存放（只读挂载） | 只读 |
| `${REFERENCE_PATH}:/references` | 参考基因组、索引文件（只读） | 只读 |
| `${CONDA_ENV_PATH}:/opt/conda/envs` | Conda环境复用（宿主机预装） | 只读 |
| `backend_logs:/app/logs` | 应用日志持久化 | 读写 |

**目录权限要求**：
- `/data` 目录需要 `1000:1000` (UID:GID) 权限，对应容器内非root用户
- Conda环境目录需要对容器用户可读

---

## 6.3 Remote 模式 — 分离部署

remote模式适用于**Web平台**与**计算节点**分离部署的场景。Web平台负责API请求和业务逻辑，Master节点专用于执行Snakemake计算任务。

### 6.3.1 docker-compose.yml（Web平台）

```yaml
# =============================================================================
# OmicsHub Docker Compose - Remote Mode: Web Platform
# Web平台：API + DB + Redis + 轻量Worker + Beat + Flower + Nginx
# =============================================================================
version: "3.8"

x-backend-env: &backend-env
  EXECUTION_MODE: remote
  MASTER_API_URL: ${MASTER_API_URL:-http://master:8001}
  MASTER_INTERNAL_TOKEN: ${MASTER_INTERNAL_TOKEN:-master-token-change-me}

  # --- 数据库（同local模式）---
  DATABASE_URL: postgresql://${POSTGRES_USER:-omicshub}:${POSTGRES_PASSWORD:-changeme}@db:5432/${POSTGRES_DB:-omicshub}
  POSTGRES_USER: ${POSTGRES_USER:-omicshub}
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
  POSTGRES_DB: ${POSTGRES_DB:-omicshub}
  POSTGRES_HOST: db
  POSTGRES_PORT: 5432

  # --- Redis（同local模式）---
  REDIS_URL: redis://:${REDIS_PASSWORD:-}@redis:6379/0
  REDIS_HOST: redis
  REDIS_PORT: 6379
  REDIS_PASSWORD: ${REDIS_PASSWORD:-}

  # --- Celery ---
  CELERY_BROKER_URL: redis://:${REDIS_PASSWORD:-}@redis:6379/0
  CELERY_RESULT_BACKEND: redis://:${REDIS_PASSWORD:-}@redis:6379/1

  # --- 安全密钥 ---
  SECRET_KEY: ${SECRET_KEY:-your-super-secret-jwt-key-change-in-production}
  INTERNAL_TOKEN: ${INTERNAL_TOKEN:-internal-token-change-me}

  # --- API密钥 ---
  KIMI_API_KEY: ${KIMI_API_KEY:-}
  OPENAI_API_KEY: ${OPENAI_API_KEY:-}

  # --- 存储 ---
  SHARED_STORAGE_PATH: /data
  WORKFLOW_PATH: /workflows

  # --- 应用配置 ---
  LOG_LEVEL: ${LOG_LEVEL:-INFO}
  MAX_UPLOAD_SIZE: ${MAX_UPLOAD_SIZE:-1073741824}
  ADMIN_EMAIL: ${ADMIN_EMAIL:-admin@example.com}
  ADMIN_PASSWORD: ${ADMIN_PASSWORD:-admin123}

x-backend-volumes: &backend-volumes
  - ${DATA_PATH:-/data/omicshub}:/data
  - ${WORKFLOW_PATH:-./workflows}:/workflows:ro
  - ${NFS_MOUNT_PATH:-/data/omicshub}:/data  # NFS共享存储挂载点
  - backend_logs:/app/logs

services:
  web:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-web
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
    volumes: *backend-volumes
    environment:
      <<: *backend-env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G

  db:
    image: postgres:14-alpine
    container_name: omicshub-db
    restart: unless-stopped
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-omicshub}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
      POSTGRES_DB: ${POSTGRES_DB:-omicshub}
      PGDATA: /var/lib/postgresql/data/pgdata
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-omicshub} -d ${POSTGRES_DB:-omicshub}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G

  redis:
    image: redis:7-alpine
    container_name: omicshub-redis
    restart: unless-stopped
    command: >
      sh -c 'redis-server
      --appendonly yes
      --appendfsync everysec
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --requirepass "${REDIS_PASSWORD:-}"'
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M

  # =========================================================================
  # celery_worker: 轻量Worker（仅处理非Snakemake任务）
  # =========================================================================
  celery_worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-celery-worker
    restart: unless-stopped
    command: >
      celery -A app.celery_app worker
      -l ${LOG_LEVEL:-info}
      -Q default,notifications,email
      -n worker-web@%h
      --concurrency 4
      -Ofair
    volumes:
      - ${DATA_PATH:-/data/omicshub}:/data
      - backend_logs:/app/logs
    environment:
      <<: *backend-env
      C_FORCE_ROOT: "true"
    depends_on:
      - db
      - redis
    healthcheck:
      test: ["CMD-SHELL", "celery -A app.celery_app inspect ping --destination worker-web@$$HOSTNAME || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
    # 注意：remote模式下Worker不执行Snakemake，仅处理轻量任务

  celery_beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-celery-beat
    restart: unless-stopped
    command: >
      celery -A app.celery_app beat
      -l ${LOG_LEVEL:-info}
      --scheduler django_celery_beat.schedulers:DatabaseScheduler
    volumes:
      - ${DATA_PATH:-/data/omicshub}:/data
      - backend_logs:/app/logs
    environment:
      <<: *backend-env
    depends_on:
      - db
      - redis
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  flower:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-flower
    restart: unless-stopped
    command: >
      celery -A app.celery_app flower
      --port=5555
      --broker=redis://:${REDIS_PASSWORD:-}@redis:6379/0
      --basic-auth=${FLOWER_USER:-admin}:${FLOWER_PASSWORD:-flower123}
      --url-prefix=flower
    environment:
      <<: *backend-env
    depends_on:
      - redis
      - celery_worker
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  nginx:
    image: nginx:alpine
    container_name: omicshub-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/dist:/usr/share/nginx/html:ro
      - ${NFS_MOUNT_PATH:-/data/omicshub}:/data:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      - web
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  backend_logs:
    driver: local

networks:
  omicshub_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

---

### 6.3.2 docker-compose.master.yml（Master计算节点）

```yaml
# =============================================================================
# OmicsHub Docker Compose - Remote Mode: Master Compute Node
# Master节点：专用于执行Snakemake计算任务
# 不暴露公网，仅内网Web平台访问
# =============================================================================
version: "3.8"

services:
  # =========================================================================
  # master: FastAPI Executor Service
  # =========================================================================
  master:
    build:
      context: ./master
      dockerfile: Dockerfile
    container_name: omicshub-master
    restart: unless-stopped
    ports:
      # 仅暴露给内网Web平台，不绑定0.0.0.0
      - "127.0.0.1:8001:8001"
    volumes:
      # 共享存储：与Web平台使用相同的NFS/Docker Volume
      - ${DATA_PATH:-/data/omicshub}:/data
      - ${WORKFLOW_PATH:-./workflows}:/workflows:ro
      - ${REFERENCE_PATH:-/data/omicshub/references}:/references:ro
      - ${CONDA_ENV_PATH:-/opt/conda/envs}:/opt/conda/envs
      - master_logs:/app/logs
    environment:
      # --- Master服务配置 ---
      MASTER_HOST: 0.0.0.0
      MASTER_PORT: 8001

      # --- 回调配置 ---
      CALLBACK_URL: ${CALLBACK_URL:-http://web:8000/internal/callback/task-complete}
      WEBSOCKET_URL: ${WEBSOCKET_URL:-ws://web:8000/internal/ws/task-log}
      INTERNAL_TOKEN: ${INTERNAL_TOKEN:-internal-token-change-me}

      # --- 存储路径 ---
      SHARED_STORAGE_PATH: /data
      WORKFLOW_PATH: /workflows

      # --- Snakemake配置 ---
      SNAKEMAKE_CORES: ${SNAKEMAKE_CORES:-16}
      CONDA_ENV_PATH: /opt/conda/envs
      MAX_CONCURRENT_JOBS: ${MAX_CONCURRENT_JOBS:-4}

      # --- 日志 ---
      LOG_LEVEL: ${LOG_LEVEL:-INFO}

      # --- CORS（仅允许Web平台域名）---
      ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-http://localhost,http://web:8000}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    networks:
      - omicshub_master_net
    deploy:
      resources:
        limits:
          cpus: ${MASTER_CPU_LIMIT:-16.0}
          memory: ${MASTER_MEM_LIMIT:-64G}
        reservations:
          cpus: '4.0'
          memory: 8G
    # Master节点承载所有Snakemake计算，资源配置应充足
    # 建议：CPU >= 16核，内存 >= 64G，存储 >= 1TB SSD

  # =========================================================================
  # master_exporter: 节点资源监控（可选，Prometheus node_exporter）
  # =========================================================================
  node_exporter:
    image: prom/node-exporter:latest
    container_name: omicshub-master-exporter
    restart: unless-stopped
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.rootfs=/rootfs'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "127.0.0.1:9100:9100"
    networks:
      - omicshub_master_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M

volumes:
  master_logs:
    driver: local

networks:
  omicshub_master_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.21.0.0/16
    # 该网络仅内网使用，可与Web平台的omicshub_net通过docker network connect互联
    # 或通过宿主机的docker0网桥访问
```

---

### 6.3.3 Remote 模式网络互联方案

**方案一：Docker Network Connect（推荐，同机房）**

```bash
# 1. 在Web平台服务器创建共享网络
docker network create --driver bridge --subnet 172.30.0.0/16 omicshub_shared

# 2. Web平台加入共享网络
docker network connect omicshub_shared omicshub-web

# 3. Master节点加入共享网络
docker network connect omicshub_shared omicshub-master

# 4. 更新环境变量，使用共享网络通信
# MASTER_API_URL=http://omicshub-master:8001
```

**方案二：宿主机IP直连**

```bash
# Web平台通过Master宿主机IP访问
# MASTER_API_URL=http://<master_host_ip>:8001

# 需要在Master节点暴露端口到宿主机
docker-compose -f docker-compose.master.yml up -d
```

**方案三：Overlay网络（多Docker Host）**

```bash
# 创建Docker Swarm overlay网络（需初始化Swarm）
docker swarm init
docker network create --driver overlay --attachable omicshub_overlay

# 两个stack使用同一overlay网络
docker stack deploy -c docker-compose.yml omicshub-web
docker stack deploy -c docker-compose.master.yml omicshub-master
```

**Master节点启动命令**：

```bash
#!/bin/bash
# start_master.sh - Master节点启动脚本

set -e

echo "=== OmicsHub Master Node Startup ==="

# 检查环境变量
if [ -z "$INTERNAL_TOKEN" ]; then
    echo "ERROR: INTERNAL_TOKEN environment variable is required"
    exit 1
fi

# 创建必要目录
mkdir -p /data/omicshub/tasks /data/omicshub/uploads /data/omicshub/logs
chmod 755 /data/omicshub

# 拉取最新镜像
docker-compose -f docker-compose.master.yml pull

# 启动服务
docker-compose -f docker-compose.master.yml up -d

# 等待服务就绪
echo "Waiting for Master service to be ready..."
sleep 5

# 健康检查
for i in {1..30}; do
    if curl -sf http://localhost:8001/health > /dev/null 2>&1; then
        echo "Master node is healthy!"
        docker-compose -f docker-compose.master.yml ps
        exit 0
    fi
    echo "Health check attempt $i/30..."
    sleep 2
done

echo "ERROR: Master node failed health check"
docker-compose -f docker-compose.master.yml logs master
exit 1
```

---

## 6.4 共享存储设计

### 6.4.1 方案对比

| 方案 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **Docker Volume（本地）** | 单机部署 | 简单、性能好、无需额外配置 | 无法跨主机共享 |
| **NFS** | 多机同机房 | 成熟、简单挂载 | 性能一般、单点故障 |
| **Ceph/GlusterFS** | 多机大规模 | 高可用、可扩展 | 运维复杂、需专业知识 |

**推荐**：单机用Docker Volume，多机用NFS。

### 6.4.2 NFS共享存储方案

```bash
# =============================================================================
# NFS服务器配置（存储服务器或Master节点）
# =============================================================================

# 1. 安装NFS服务器
sudo apt-get update
sudo apt-get install -y nfs-kernel-server

# 2. 创建共享目录
sudo mkdir -p /data/omicshub
sudo chown -R 1000:1000 /data/omicshub
sudo chmod 755 /data/omicshub

# 3. 配置NFS导出
# /etc/exports
cat << 'EOF' | sudo tee /etc/exports
# OmicsHub 共享存储
/data/omicshub  172.20.0.0/16(rw,sync,no_subtree_check,no_root_squash)
/data/omicshub  172.21.0.0/16(rw,sync,no_subtree_check,no_root_squash)
EOF

# 4. 启动NFS服务
sudo exportfs -ra
sudo systemctl restart nfs-kernel-server
sudo systemctl enable nfs-kernel-server

# 5. 客户端挂载（Web平台服务器）
sudo apt-get install -y nfs-common
sudo mkdir -p /data/omicshub
sudo mount -t nfs <nfs_server_ip>:/data/omicshub /data/omicshub

# 6. 开机自动挂载（/etc/fstab）
echo "<nfs_server_ip>:/data/omicshub /data/omicshub nfs defaults,_netdev 0 0" | sudo tee -a /etc/fstab

# 7. Docker中使用NFS Volume
docker volume create --driver local \
  --opt type=nfs \
  --opt o=addr=<nfs_server_ip>,rw,nfsvers=4 \
  --opt device=:/data/omicshub \
  omicshub_nfs_data
```

### 6.4.3 目录结构规范

```
/data/omicshub/                          # 根目录
├── docker-compose.yml -> /opt/omicshub/ # 软链接到实际部署位置
├── .env                                 # 环境变量
│
├── tasks/                               # 任务执行目录
│   └── {task_id}/                       # 每个任务独立目录（UUID格式）
│       ├── config.yaml                  # Snakemake任务配置
│       ├── samples.csv                  # 样本信息表
│       ├── metadata.json                # 任务元数据（Web平台写入）
│       ├── snakemake.log                # 实时执行日志
│       ├── stderr.log                   # 标准错误输出
│       ├── stdout.log                   # 标准输出
│       ├── progress.json                # 进度追踪（实时更新）
│       ├── status.json                  # 状态文件（pending/running/completed/failed）
│       └── results/                     # 结果目录
│           ├── output_files/            # 输出文件
│           ├── reports/                 # 报告文件
│           ├── plots/                   # 图表
│           └── summary.json             # 结果摘要
│
├── uploads/                             # 用户上传文件
│   └── {user_id}/                       # 按用户ID隔离
│       ├── raw_data/                    # 原始数据
│       ├── samples/                     # 样本文件
│       └── temp/                        # 临时文件
│
├── workflows/                           # Snakefile存放（版本控制）
│   ├── rna_seq/
│   │   ├── Snakefile                    # 主工作流
│   │   ├── config_template.yaml         # 配置模板
│   │   ├── schema.json                  # 参数校验模式
│   │   ├── envs/                        # Conda环境定义
│   │   │   └── rna_seq.yaml
│   │   ├── scripts/                     # 辅助脚本
│   │   └── README.md
│   ├── atac_seq/
│   │   ├── Snakefile
│   │   └── ...
│   └── scRNA_seq/
│       ├── Snakefile
│       └── ...
│
├── references/                          # 参考基因组和索引
│   ├── hg38/
│   │   ├── genome.fa
│   │   ├── genome.fa.fai
│   │   ├── gtf/
│   │   │   └── genes.gtf
│   │   └── indexes/
│   │       ├── star/
│   │       ├── bwa/
│   │       └── salmon/
│   ├── mm10/
│   │   └── ...
│   └── annotation/
│       └── gene_annotations.json
│
├── conda_envs/                          # Conda环境（预装）
│   ├── rna_seq/                         # 每个流程独立环境
│   │   └── ...                          # 避免依赖冲突
│   ├── atac_seq/
│   └── scRNA_seq/
│
├── logs/                                # 应用日志
│   ├── web/
│   ├── celery/
│   ├── nginx/
│   └── master/
│
├── backups/                             # 自动备份
│   └── {date}/
│       ├── db_backup.sql.gz
│       └── data_backup.tar.gz
│
└── tmp/                                 # 临时目录
    └── cleanup_daily.sh                 # 每日清理脚本
```

### 6.4.4 目录初始化与权限设置

```bash
#!/bin/bash
# init_storage.sh - 共享存储初始化脚本

DATA_ROOT="${1:-/data/omicshub}"
USER_ID="${2:-1000}"  # 容器内运行用户的UID
GROUP_ID="${3:-1000}" # 容器内运行用户的GID

echo "=== Initializing OmicsHub Storage ==="
echo "Data root: $DATA_ROOT"
echo "Owner: $USER_ID:$GROUP_ID"

# 创建目录结构
mkdir -p "$DATA_ROOT"/{tasks,uploads,workflows,references,conda_envs,logs/{web,celery,nginx,master},backups,tmp}

# 设置权限
chown -R "$USER_ID:$GROUP_ID" "$DATA_ROOT"
chmod -R u+rwx "$DATA_ROOT"
chmod -R g+rx "$DATA_ROOT"

# tasks目录需要所有用户可写（多容器写入）
chmod 777 "$DATA_ROOT/tasks"

# uploads目录按用户隔离，应用层控制权限
chmod 755 "$DATA_ROOT/uploads"

# workflows和references只读
chmod -R 755 "$DATA_ROOT/workflows"
chmod -R 755 "$DATA_ROOT/references"
chmod -R 755 "$DATA_ROOT/conda_envs"

# logs目录可写
chmod -R 755 "$DATA_ROOT/logs"

echo "=== Storage initialization complete ==="
echo "Directory structure:"
find "$DATA_ROOT" -maxdepth 2 -type d | head -30
```

---

## 6.5 Nginx 配置

### 6.5.1 nginx.conf 完整配置

```nginx
# =============================================================================
# OmicsHub Nginx Configuration
# 功能：静态文件服务、API反向代理、WebSocket支持、Flower监控、安全防护
# =============================================================================

user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # --- 日志格式 ---
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'rt=$request_time uct=$upstream_connect_time '
                    'uht=$upstream_header_time urt=$upstream_response_time';

    access_log /var/log/nginx/access.log main;

    # --- 性能优化 ---
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 2G;  # 最大上传文件大小
    client_body_buffer_size 16K;
    client_header_buffer_size 1K;
    large_client_header_buffers 4 8K;

    # --- Gzip压缩 ---
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml application/json
               application/javascript application/rss+xml
               application/atom+xml image/svg+xml;

    # --- 上游服务器定义 ---
    upstream web_backend {
        server web:8000 max_fails=3 fail_timeout=30s;
        keepalive 32;
    }

    upstream flower_backend {
        server flower:5555 max_fails=3 fail_timeout=30s;
    }

    # --- 限速配置（防止大文件下载占用全部带宽） ---
    limit_conn_zone $binary_remote_addr zone=addr:10m;
    limit_rate_after 10m;
    limit_rate 5m;

    # =================================================================
    # HTTP Server (80端口，重定向到HTTPS或反向代理)
    # =================================================================
    server {
        listen 80;
        server_name _;  # 接受任意域名

        # 如果配置了SSL，重定向到HTTPS
        # return 301 https://$host$request_uri;

        # 未配置SSL时直接服务
        include /etc/nginx/conf.d/omicshub.conf;
    }

    # =================================================================
    # HTTPS Server (443端口，生产环境启用)
    # =================================================================
    # server {
    #     listen 443 ssl http2;
    #     server_name omicshub.example.com;
    #
    #     ssl_certificate /etc/nginx/ssl/omicshub.crt;
    #     ssl_certificate_key /etc/nginx/ssl/omicshub.key;
    #     ssl_protocols TLSv1.2 TLSv1.3;
    #     ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';
    #     ssl_prefer_server_ciphers on;
    #
    #     include /etc/nginx/conf.d/omicshub.conf;
    # }
}
```

### 6.5.2 omicshub.conf（站点配置）

```nginx
# =============================================================================
# OmicsHub 站点配置 - 包含在 server 块中
# =============================================================================

# --- 静态文件服务（前端dist） ---
location / {
    root /usr/share/nginx/html;
    index index.html index.htm;
    try_files $uri $uri/ /index.html;  # SPA路由支持

    # 静态文件缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # HTML文件不缓存
    location ~* \.html$ {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        expires 0;
    }
}

# --- API代理到Web后端 ---
location /api/ {
    proxy_pass http://web_backend;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
}

# --- WebSocket升级支持（实时日志推送） ---
location /ws/ {
    proxy_pass http://web_backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_connect_timeout 60s;
    proxy_send_timeout 3600s;  # WebSocket长连接
    proxy_read_timeout 3600s;
}

# --- Flower监控面板 ---
location /flower/ {
    proxy_pass http://flower_backend/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Script-Name /flower;
    proxy_redirect off;

    # IP白名单限制（仅允许内网访问Flower）
    # allow 10.0.0.0/8;
    # allow 172.16.0.0/12;
    # allow 192.168.0.0/16;
    # allow 127.0.0.1;
    # deny all;

    # 基本认证（双重保护）
    # auth_basic "Flower Monitoring";
    # auth_basic_user_file /etc/nginx/.htpasswd;
}

# --- 内部回调接口（严格IP白名单限制） ---
location /internal/ {
    # 仅允许Docker网络内部和Master节点IP访问
    allow 172.20.0.0/16;   # omicshub_web 网络
    allow 172.21.0.0/16;   # omicshub_master 网络
    allow 127.0.0.1;
    deny all;              # 拒绝其他所有IP

    proxy_pass http://web_backend;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_connect_timeout 30s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;

    # 记录内部访问日志（安全审计）
    access_log /var/log/nginx/internal_access.log main;
}

# --- 文件下载服务 ---
location /downloads/ {
    alias /data/;  # 对应宿主机 DATA_PATH
    autoindex off;

    # 限速
    limit_conn addr 5;
    limit_rate 10m;

    # 仅允许已认证用户（通过X-Download-Token验证）
    proxy_pass http://web_backend;
    proxy_set_header X-Download-Path $request_uri;
}

# --- 任务结果文件直接访问（带Token验证） ---
location /results/ {
    alias /data/tasks/;
    autoindex off;

    # 文件下载限速
    limit_conn addr 3;
    limit_rate 5m;

    # 安全头
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
}

# --- 健康检查端点（负载均衡器使用） ---
location /health {
    proxy_pass http://web_backend/api/v1/health;
    proxy_connect_timeout 5s;
    proxy_read_timeout 5s;
    access_log off;  # 不记录健康检查日志
}

# --- 安全头配置 ---
add_header X-Content-Type-Options nosniff always;
add_header X-Frame-Options SAMEORIGIN always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy strict-origin-when-cross-origin always;
# add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';" always;

# --- 禁止访问敏感文件 ---
location ~ /\. {
    deny all;
    access_log off;
    log_not_found off;
}

location ~* \.(env|git|gitignore|ini|log|sh|sql)$ {
    deny all;
    access_log off;
    log_not_found off;
}

# --- 错误页面 ---
error_page 500 502 503 504 /50x.html;
location = /50x.html {
    root /usr/share/nginx/html;
    internal;
}
```

---

## 6.6 Dockerfile 设计

### 6.6.1 Backend Dockerfile（Web + Celery Worker）

```dockerfile
# =============================================================================
# OmicsHub Backend Dockerfile
# 多阶段构建：构建阶段 + 运行阶段
# 包含：Python 3.11 + FastAPI + Celery + Snakemake + Miniforge(Conda)
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: 构建阶段
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# 构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 创建虚拟环境
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: 运行阶段
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL maintainer="OmicsHub Team" \
      description="OmicsHub Backend - FastAPI + Celery + Snakemake"

# --- 系统依赖 ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 数据库
    libpq5 \
    # 网络工具（健康检查等）
    curl wget \
    # 文件处理
    unzip gzip tar \
    # 版本控制（Snakemake可能用到）
    git \
    # 通用工具
    procps \
    && rm -rf /var/lib/apt/lists/*

# --- 创建非root用户 ---
RUN groupadd -r -g 1000 omicshub && \
    useradd -r -u 1000 -g omicshub -d /app -s /bin/bash omicshub

# --- 复制虚拟环境 ---
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# --- 安装Miniforge（Conda）---
ENV CONDA_DIR=/opt/conda
ENV PATH="$CONDA_DIR/bin:$PATH"

RUN wget --quiet https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p $CONDA_DIR && \
    rm /tmp/miniforge.sh && \
    conda clean -afy && \
    echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /etc/bash.bashrc

# --- 安装Snakemake（在基础环境中）---
RUN pip install --no-cache-dir snakemake==7.32.4

# --- 创建工作目录 ---
WORKDIR /app
RUN chown -R omicshub:omicshub /app

# --- 复制应用代码 ---
COPY --chown=omicshub:omicshub ./app ./app
COPY --chown=omicshub:omicshub ./alembic ./alembic
COPY --chown=omicshub:omicshub alembic.ini .

# --- 创建日志目录 ---
RUN mkdir -p /app/logs && chown -R omicshub:omicshub /app/logs

# --- 健康检查 ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# --- 暴露端口 ---
EXPOSE 8000

# --- 切换到非root用户 ---
USER omicshub

# --- 启动命令 ---
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 6.6.2 Master Dockerfile（计算节点）

```dockerfile
# =============================================================================
# OmicsHub Master Node Dockerfile
# 专用于执行Snakemake计算任务
# 需要更多系统工具和生物信息学依赖
# =============================================================================

FROM python:3.11-slim

LABEL maintainer="OmicsHub Team" \
      description="OmicsHub Master Executor - Snakemake Compute Node"

# --- 系统依赖（生物信息学工具链） ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 基础构建工具
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    # 数据库客户端
    libpq-dev \
    # 压缩工具
    pigz \
    pbzip2 \
    lbzip2 \
    xz-utils \
    zlib1g-dev \
    libbz2-dev \
    liblzma-dev \
    # 网络工具
    curl wget \
    # 文件处理
    unzip \
    # 版本控制
    git \
    # 进程管理
    procps \
    psmisc \
    # 存储工具（NFS客户端）
    nfs-common \
    # 监控工具
    htop \
    # 其他常用
    jq \
    && rm -rf /var/lib/apt/lists/*

# --- 创建非root用户 ---
RUN groupadd -r -g 1000 omicshub && \
    useradd -r -u 1000 -g omicshub -d /app -s /bin/bash omicshub

# --- 安装Miniforge（Conda）---
ENV CONDA_DIR=/opt/conda
ENV PATH="$CONDA_DIR/bin:$PATH"

RUN wget --quiet https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p $CONDA_DIR && \
    rm /tmp/miniforge.sh && \
    conda clean -afy && \
    echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /etc/bash.bashrc

# --- 安装Snakemake ---
RUN pip install --no-cache-dir \
    snakemake==7.32.4 \
    httpx==0.27.0 \
    websockets==12.0

# --- 安装Python依赖 ---
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# --- 创建工作目录 ---
WORKDIR /app
RUN chown -R omicshub:omicshub /app

# --- 复制Master应用代码 ---
COPY --chown=omicshub:omicshub ./app ./app
COPY --chown=omicshub:omicshub ./scripts ./scripts

# --- 创建日志和临时目录 ---
RUN mkdir -p /app/logs /tmp/snakemake && \
    chown -R omicshub:omicshub /app/logs /tmp/snakemake

# --- 数据卷挂载点 ---
VOLUME ["/data", "/workflows", "/references", "/opt/conda/envs"]

# --- 健康检查 ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# --- 暴露端口 ---
EXPOSE 8001

# --- 切换到非root用户 ---
USER omicshub

# --- 启动命令 ---
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
```

### 6.6.3 requirements.txt

```txt
# =============================================================================
# OmicsHub Python Dependencies
# =============================================================================

# --- Web Framework ---
fastapi==0.111.0
uvicorn[standard]==0.30.0
python-multipart==0.0.9

# --- Database ---
asyncpg==0.29.0
alembic==1.13.0
sqlalchemy[asyncio]==2.0.30

# --- Redis & Celery ---
redis==5.0.0
celery==5.4.0
django-celery-beat==2.7.0

# --- Authentication ---
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-dotenv==1.0.0

# --- HTTP Client ---
httpx==0.27.0
aiohttp==3.9.0

# --- Validation ---
pydantic==2.7.0
pydantic-settings==2.2.0
email-validator==2.1.0

# --- Utils ---
pyyaml==6.0.1
python-dateutil==2.9.0
shortuuid==1.0.13
aiofiles==23.2.0

# --- WebSocket ---
websockets==12.0

# --- Monitoring ---
prometheus-client==0.20.0

# --- Testing (dev only) ---
pytest==8.2.0
pytest-asyncio==0.23.0
httpx==0.27.0
```

---

## 6.7 初始化脚本设计

### 6.7.1 init.sh（一键初始化）

```bash
#!/bin/bash
# =============================================================================
# OmicsHub 一键初始化脚本
# 功能：目录创建、权限设置、数据库迁移、管理员创建、流程导入
# 用法: ./init.sh [--skip-migration] [--reset-db]
# =============================================================================

set -euo pipefail

# --- 颜色定义 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- 日志函数 ---
log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
log_step()  { echo -e "\n${BLUE}=== $1 ===${NC}"; }

# --- 配置 ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_PATH="${DATA_PATH:-/data/omicshub}"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
ENV_FILE="${SCRIPT_DIR}/.env"
SKIP_MIGRATION=false
RESET_DB=false

# --- 参数解析 ---
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-migration) SKIP_MIGRATION=true; shift ;;
        --reset-db)       RESET_DB=true; shift ;;
        --data-path)      DATA_PATH="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --skip-migration   Skip database migration"
            echo "  --reset-db         Reset database (WARNING: destroys all data)"
            echo "  --data-path PATH   Set data directory path (default: /data/omicshub)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- 前置检查 ---
log_step "Step 1: Environment Checks"

# 检查Docker
docker info > /dev/null 2>&1 || {
    log_error "Docker is not running or not installed"
    exit 1
}
log_info "Docker is running"

# 检查Docker Compose
if docker compose version > /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif docker-compose version > /dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    log_error "Docker Compose is not installed"
    exit 1
fi
log_info "Docker Compose found: $COMPOSE_CMD"

# 检查.env文件
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "${ENV_FILE}.example" ]; then
        log_warn ".env not found, copying from .env.example"
        cp "${ENV_FILE}.example" "$ENV_FILE"
        log_warn "Please review and update the .env file before proceeding"
        read -p "Press Enter to continue or Ctrl+C to abort..."
    else
        log_error ".env file not found"
        exit 1
    fi
fi

# 检查docker-compose.yml
if [ ! -f "$COMPOSE_FILE" ]; then
    log_error "docker-compose.yml not found at $COMPOSE_FILE"
    exit 1
fi

log_info "All checks passed"

# --- 创建目录结构 ---
log_step "Step 2: Create Directory Structure"

mkdir -p "$DATA_PATH"/{tasks,uploads,workflows,references,conda_envs,logs/{web,celery,nginx,master},backups,tmp}
chmod 755 "$DATA_PATH"
chmod 777 "$DATA_PATH/tasks"  # 多容器写入
chmod 755 "$DATA_PATH/uploads"
chmod 755 "$DATA_PATH/workflows"
chmod 755 "$DATA_PATH/references"

log_info "Directory structure created at $DATA_PATH"

# --- 设置目录权限 ---
log_step "Step 3: Set Directory Permissions"

# 检测容器运行用户UID（默认1000）
CONTAINER_UID=$(grep "^omicshub" /etc/passwd 2>/dev/null | cut -d: -f3 || echo "1000")
chown -R "${CONTAINER_UID}:${CONTAINER_UID}" "$DATA_PATH" 2>/dev/null || {
    log_warn "Could not chown $DATA_PATH (may need sudo)"
    log_warn "Please run: sudo chown -R ${CONTAINER_UID}:${CONTAINER_UID} $DATA_PATH"
}

log_info "Permissions set (UID: $CONTAINER_UID)"

# --- 启动基础服务 ---
log_step "Step 4: Start Infrastructure Services"

$COMPOSE_CMD -f "$COMPOSE_FILE" up -d db redis

# 等待数据库就绪
log_info "Waiting for PostgreSQL to be ready..."
for i in {1..60}; do
    if $COMPOSE_CMD -f "$COMPOSE_FILE" exec -T db pg_isready -U "${POSTGRES_USER:-omicshub}" > /dev/null 2>&1; then
        log_info "PostgreSQL is ready"
        break
    fi
    if [ $i -eq 60 ]; then
        log_error "PostgreSQL failed to start within 60 seconds"
        $COMPOSE_CMD -f "$COMPOSE_FILE" logs db
        exit 1
    fi
    sleep 1
done

# 等待Redis就绪
log_info "Waiting for Redis to be ready..."
for i in {1..30}; do
    if $COMPOSE_CMD -f "$COMPOSE_FILE" exec -T redis redis-cli ping > /dev/null 2>&1; then
        log_info "Redis is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Redis failed to start within 30 seconds"
        exit 1
    fi
    sleep 1
done

# --- 数据库迁移 ---
if [ "$SKIP_MIGRATION" = false ]; then
    log_step "Step 5: Database Migration"

    if [ "$RESET_DB" = true ]; then
        log_warn "Resetting database - ALL DATA WILL BE LOST!"
        read -p "Are you sure? Type 'yes' to continue: " confirm
        if [ "$confirm" = "yes" ]; then
            $COMPOSE_CMD -f "$COMPOSE_FILE" exec -T db dropdb -U "${POSTGRES_USER:-omicshub}" "${POSTGRES_DB:-omicshub}" 2>/dev/null || true
            $COMPOSE_CMD -f "$COMPOSE_FILE" exec -T db createdb -U "${POSTGRES_USER:-omicshub}" "${POSTGRES_DB:-omicshub}"
            log_info "Database reset"
        else
            log_info "Database reset cancelled"
        fi
    fi

    # 执行Alembic迁移
    $COMPOSE_CMD -f "$COMPOSE_FILE" run --rm web alembic upgrade head || {
        log_error "Database migration failed"
        exit 1
    }
    log_info "Database migration completed"
else
    log_warn "Skipping database migration"
fi

# --- 创建默认管理员账户 ---
log_step "Step 6: Create Default Admin Account"

ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin123}"

$COMPOSE_CMD -f "$COMPOSE_FILE" run --rm web python -c "
import asyncio
import os
from app.core.database import async_session
from app.models.user import User
from app.core.security import get_password_hash
from app.core.config import settings

async def create_admin():
    async with async_session() as db:
        # 检查是否已有管理员
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.is_superuser == True))
        admin = result.scalar_one_or_none()

        if admin:
            print(f'Admin user already exists: {admin.email}')
            return

        # 创建管理员
        admin = User(
            email='${ADMIN_EMAIL}',
            hashed_password=get_password_hash('${ADMIN_PASSWORD}'),
            full_name='System Administrator',
            is_active=True,
            is_superuser=True,
        )
        db.add(admin)
        await db.commit()
        print(f'Admin user created: ${ADMIN_EMAIL}')

asyncio.run(create_admin())
" || log_warn "Admin account creation may have failed (check logs)"

# --- 导入示例流程 ---
log_step "Step 7: Import Workflow Definitions"

WORKFLOW_DIR="${DATA_PATH}/workflows"
if [ -d "$WORKFLOW_DIR" ]; then
    # 扫描并导入所有 workflow.yaml 文件
    $COMPOSE_CMD -f "$COMPOSE_FILE" run --rm web python -c "
import asyncio
import os
import yaml
from pathlib import Path

async def import_workflows():
    workflow_dir = Path('${WORKFLOW_DIR}')
    if not workflow_dir.exists():
        print(f'Workflow directory not found: {workflow_dir}')
        return

    imported = 0
    for wf_file in workflow_dir.rglob('*.yaml'):
        try:
            with open(wf_file) as f:
                wf_def = yaml.safe_load(f)

            if wf_def and isinstance(wf_def, dict):
                # 这里调用实际的导入API或函数
                print(f'Found workflow: {wf_def.get(\"name\", wf_file.name)}')
                imported += 1
        except Exception as e:
            print(f'Warning: Failed to parse {wf_file}: {e}')

    print(f'Scanned {imported} workflow files')

asyncio.run(import_workflows())
" || log_warn "Workflow import may have failed (non-critical)"
else
    log_warn "Workflow directory not found at $WORKFLOW_DIR"
fi

# --- 启动所有服务 ---
log_step "Step 8: Start All Services"

$COMPOSE_CMD -f "$COMPOSE_FILE" up -d --build

# --- 等待服务就绪 ---
log_info "Waiting for services to be ready..."
sleep 5

# 健康检查
HEALTHY=0
TOTAL=0
for service in web celery_worker celery_beat; do
    TOTAL=$((TOTAL + 1))
    if $COMPOSE_CMD -f "$COMPOSE_FILE" ps "$service" | grep -q "healthy"; then
        log_info "$service is healthy"
        HEALTHY=$((HEALTHY + 1))
    elif $COMPOSE_CMD -f "$COMPOSE_FILE" ps "$service" | grep -q "Up"; then
        log_warn "$service is running (healthcheck pending)"
        HEALTHY=$((HEALTHY + 1))
    else
        log_error "$service failed to start"
    fi
done

# --- 完成 ---
log_step "Initialization Complete"

echo ""
echo "========================================"
echo "  OmicsHub Initialization Summary"
echo "========================================"
echo "  Services:     $HEALTHY/$TOTAL running"
echo "  Data path:    $DATA_PATH"
echo "  Admin email:  $ADMIN_EMAIL"
echo "  Compose file: $COMPOSE_FILE"
echo ""
echo "  Access URLs:"
echo "    - Web App:    http://localhost/"
echo "    - API Docs:   http://localhost/api/v1/docs"
echo "    - Flower:     http://localhost/flower/"
echo ""
echo "  Useful commands:"
echo "    - View logs:  $COMPOSE_CMD -f $COMPOSE_FILE logs -f"
echo "    - Stop:       $COMPOSE_CMD -f $COMPOSE_FILE down"
echo "    - Restart:    $COMPOSE_CMD -f $COMPOSE_FILE restart"
echo "========================================"

if [ "$HEALTHY" -lt "$TOTAL" ]; then
    log_warn "Some services may not be fully ready. Check logs with:"
    echo "  $COMPOSE_CMD -f $COMPOSE_FILE logs"
    exit 1
fi

exit 0
```

### 6.7.2 每日备份脚本 backup.sh

```bash
#!/bin/bash
# =============================================================================
# OmicsHub 每日备份脚本
# 用法: 添加到 crontab: 0 2 * * * /opt/omicshub/scripts/backup.sh
# =============================================================================

set -euo pipefail

BACKUP_DIR="/data/omicshub/backups/$(date +%Y%m%d)"
DATA_ROOT="/data/omicshub"
RETENTION_DAYS=30
COMPOSE_CMD="docker-compose"
COMPOSE_FILE="/opt/omicshub/docker-compose.yml"

mkdir -p "$BACKUP_DIR"

# --- 数据库备份 ---
echo "[$(date)] Backing up database..."
$COMPOSE_CMD -f "$COMPOSE_FILE" exec -T db pg_dump \
    -U "${POSTGRES_USER:-omicshub}" \
    "${POSTGRES_DB:-omicshub}" | gzip > "$BACKUP_DIR/db_backup.sql.gz"

# --- 应用数据备份（排除临时文件） ---
echo "[$(date)] Backing up application data..."
tar -czf "$BACKUP_DIR/data_backup.tar.gz" \
    --exclude='*/tmp/*' \
    --exclude='*/.snakemake/*' \
    -C "$DATA_ROOT" tasks uploads workflows

# --- 清理旧备份 ---
echo "[$(date)] Cleaning up old backups (> $RETENTION_DAYS days)..."
find "$DATA_ROOT/backups" -type d -mtime +$RETENTION_DAYS -exec rm -rf {} + 2>/dev/null || true

echo "[$(date)] Backup completed: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"
```

---

## 6.8 工作流执行引擎（WMS）架构详细设计

### 6.8.1 架构概述

OmicsHub 的工作流执行引擎采用**策略模式（Strategy Pattern）**设计，通过 `ExecutionBackend` 抽象层统一接口，支持本地执行和远程执行两种模式的无缝切换。

```
+---------------------------------------------------------------------+
|                        Web Platform (FastAPI)                        |
|                                                                      |
|  +-----------------+    +--------------+    +------------------+    |
|  |  TaskService    |--->|BackendFactory|--->| ExecutionBackend |    |
|  |                 |    |              |    |   (abstract)     |    |
|  +-----------------+    +--------------+    +--------+---------+    |
|                                                      |              |
|                              +-----------------------+----------+   |
|                              |                       |          |   |
|                              v                       v          |   |
|                    +------------------+  +------------------+  |   |
|                    |LocalSnakemake    |  | RemoteMasterBackend  |  |   |
|                    |   Backend        |  |                  |  |   |
|                    +--------+---------+  +--------+---------+  |   |
|                             |                     |            |   |
+-----------------------------+---------------------+------------+   |
                              |                     |                |
                              v                     v                |
                    +------------------+  +------------------+      |
                    | asyncio.subprocess|  | HTTP/WebSocket   |      |
                    |                  |  |   to Master      |      |
                    +------------------+  +--------+---------+      |
                                                   |                |
                              +--------------------+                |
                              v                                     |
                    +------------------+                            |
                    |   Master Node    |                            |
                    | FastAPI Executor |                            |
                    +------------------+                            |
+---------------------------------------------------------------------+
```

---

### 6.8.2 ExecutionBackend 抽象层

```python
# app/core/execution/base.py
# =============================================================================
# ExecutionBackend abstract base class
# Defines the unified interface for workflow execution engines
# =============================================================================

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional
from enum import Enum
import asyncio


class TaskStatus(str, Enum):
    """Task status enumeration"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class ExecutionBackend(ABC):
    """
    Workflow execution backend abstract base class.
    
    All concrete backends (local Snakemake, remote Master, etc.) must implement this interface.
    Strategy pattern enables switching execution modes without modifying business code.
    """
    
    engine: str = "unknown"
    
    @abstractmethod
    async def submit(
        self,
        task_id: str,
        snakefile: str,
        config: dict,
        workdir: str,
        cores: int = 8,
        extra_args: Optional[list[str]] = None
    ) -> str:
        """
        Submit a task to the execution backend.
        
        Args:
            task_id: Unique task identifier (UUID)
            snakefile: Path to Snakefile
            config: Snakemake configuration dict, will be written to config.yaml
            workdir: Task working directory
            cores: Number of CPU cores to use
            extra_args: Additional Snakemake command line arguments
            
        Returns:
            backend_job_id: Backend-assigned job ID for subsequent queries and cancellation
        """
        pass
    
    @abstractmethod
    async def get_status(self, backend_job_id: str) -> TaskStatus:
        """
        Query task execution status.
        
        Args:
            backend_job_id: Backend job ID returned by submit()
            
        Returns:
            TaskStatus: Current task status
        """
        pass
    
    @abstractmethod
    async def cancel(self, backend_job_id: str, timeout: int = 5) -> bool:
        """
        Cancel a running task.
        
        Strategy: SIGTERM -> wait 5 seconds -> SIGKILL (ensure termination)
        
        Args:
            backend_job_id: Backend job ID
            timeout: SIGTERM wait time (seconds)
            
        Returns:
            bool: Whether cancellation succeeded
        """
        pass
    
    @abstractmethod
    async def stream_logs(self, task_id: str) -> AsyncGenerator[str, None]:
        """
        Stream read task logs.
        
        Args:
            task_id: Task ID
            
        Yields:
            str: Log line
        """
        pass
    
    @abstractmethod
    async def get_results(self, task_id: str, workdir: str) -> dict:
        """
        Get task execution results.
        
        Args:
            task_id: Task ID
            workdir: Task working directory
            
        Returns:
            dict: Result summary, including output file list, statistics, etc.
        """
        pass


class BackendFactory:
    """
    Execution backend factory class.
    
    Creates corresponding backend instances based on configuration,
    implementing runtime switching of strategy pattern.
    """
    
    _backends: dict[str, type[ExecutionBackend]] = {}
    _instances: dict[str, ExecutionBackend] = {}
    
    @classmethod
    def register(cls, mode: str, backend_class: type[ExecutionBackend]) -> None:
        """Register execution backend type"""
        cls._backends[mode] = backend_class
        
    @classmethod
    def create(cls, mode: str, **kwargs) -> ExecutionBackend:
        """
        Create execution backend instance (singleton pattern).
        
        Args:
            mode: Execution mode, "local" or "remote"
            **kwargs: Parameters passed to backend constructor
            
        Returns:
            ExecutionBackend: Execution backend instance
            
        Raises:
            ValueError: Unknown execution mode
        """
        if mode not in cls._instances:
            if mode not in cls._backends:
                raise ValueError(
                    f"Unknown execution mode: '{mode}'. "
                    f"Available modes: {list(cls._backends.keys())}"
                )
            cls._instances[mode] = cls._backends[mode](**kwargs)
        return cls._instances[mode]
    
    @classmethod
    def reset(cls) -> None:
        """Reset all instances (mainly for testing)"""
        cls._instances.clear()
```

---

### 6.8.3 LocalSnakemakeBackend Implementation

```python
# app/core/execution/local_backend.py
# =============================================================================
# LocalSnakemakeBackend - Local execution mode
# Execute Snakemake directly via asyncio.subprocess
# =============================================================================

import asyncio
import os
import re
import json
import signal
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

import yaml

from .base import ExecutionBackend, TaskStatus, BackendFactory

logger = logging.getLogger(__name__)

# Progress parsing regex
PROGRESS_PATTERN = re.compile(r'(\d+) of (\d+) steps \((\d+)%\) done')
ERROR_PATTERN = re.compile(r'(?:Error|ERROR|Exception|FAILED).*')


class LocalSnakemakeBackend(ExecutionBackend):
    """
    Local Snakemake execution backend.
    
    Features:
    - Start Snakemake process directly via asyncio.subprocess
    - Execute within Celery Worker container
    - Maintain in-memory process dict for task management
    - Real-time parse stdout/stderr, extract progress info
    - WebSocket push logs to frontend
    """
    
    engine: str = "snakemake"
    
    # Process dict: {task_id: asyncio.subprocess.Process}
    _processes: dict[str, asyncio.subprocess.Process] = {}
    
    # Process lock to prevent concurrent operations
    _lock: asyncio.Lock = asyncio.Lock()
    
    # Cleanup hook registered flag
    _cleanup_registered: bool = False
    
    def __init__(self, conda_env_path: str = "/opt/conda/envs"):
        self.conda_env_path = conda_env_path
        self._register_cleanup()
    
    def _register_cleanup(self) -> None:
        """Register process cleanup hook, ensure all child processes are terminated on exit"""
        if not self._cleanup_registered:
            import atexit
            atexit.register(self._cleanup_all_processes)
            self._cleanup_registered = True
    
    def _cleanup_all_processes(self) -> None:
        """Clean up all running processes (called on program exit)"""
        for task_id, process in list(self._processes.items()):
            try:
                if process.returncode is None:
                    process.send_signal(signal.SIGTERM)
                    logger.warning(f"Cleanup: sent SIGTERM to task {task_id}")
            except Exception as e:
                logger.error(f"Cleanup failed for task {task_id}: {e}")
    
    async def submit(
        self,
        task_id: str,
        snakefile: str,
        config: dict,
        workdir: str,
        cores: int = 8,
        extra_args: Optional[list[str]] = None
    ) -> str:
        """
        Submit Snakemake task.
        
        Execution flow:
        1. Create task working directory
        2. Write config.yaml
        3. Build snakemake command
        4. Start subprocess
        5. Store process reference
        6. Start log reading and progress monitoring tasks
        """
        workdir_path = Path(workdir)
        workdir_path.mkdir(parents=True, exist_ok=True)
        
        # 1. Write config.yaml
        config_path = workdir_path / "config.yaml"
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        # Write task metadata
        metadata_path = workdir_path / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump({
                "task_id": task_id,
                "snakefile": snakefile,
                "config": config,
                "cores": cores,
                "status": "submitted",
                "workdir": workdir
            }, f, indent=2)
        
        # 2. Build snakemake command
        log_path = workdir_path / "snakemake.log"
        
        cmd = [
            "snakemake",
            "--snakefile", str(snakefile),
            "--configfile", str(config_path),
            "--directory", str(workdir_path),
            "--cores", str(cores),
            "--nolock",                    # Avoid Snakemake concurrent lock conflicts
            "--latency-wait", "60",        # Wait for filesystem sync (needed for NFS)
            "--keep-going",                # Complete as many steps as possible
            "--rerun-incomplete",          # Re-run incomplete tasks
            "--printshellcmds",            # Print executed commands
            "--stats", str(workdir_path / "stats.json"),
        ]
        
        if extra_args:
            cmd.extend(extra_args)
        
        # 3. Start subprocess
        logger.info(f"Starting Snakemake task {task_id}: {' '.join(cmd)}")
        
        log_file = open(log_path, 'w')
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(workdir_path),
            start_new_session=True,
        )
        
        # 4. Store process reference
        async with self._lock:
            self._processes[task_id] = process
        
        # Write status file
        self._write_status_file(workdir_path, TaskStatus.RUNNING)
        
        # 5. Start background tasks: log reading and process monitoring
        asyncio.create_task(
            self._monitor_task(task_id, process, workdir_path, log_file),
            name=f"monitor-{task_id}"
        )
        
        return task_id  # In local mode, backend_job_id is the task_id
    
    async def _monitor_task(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
        workdir_path: Path,
        log_file
    ) -> None:
        """
        Monitor task execution: read logs, parse progress, wait for completion.
        This is a background task started by submit().
        """
        try:
            await self._read_logs(task_id, process, workdir_path, log_file)
            
            returncode = await process.wait()
            
            if returncode == 0:
                status = TaskStatus.COMPLETED
                logger.info(f"Task {task_id} completed successfully")
            elif returncode == -signal.SIGTERM or returncode == -signal.SIGKILL:
                status = TaskStatus.CANCELLED
                logger.info(f"Task {task_id} was cancelled")
            else:
                status = TaskStatus.FAILED
                logger.error(f"Task {task_id} failed with return code {returncode}")
            
            self._write_status_file(workdir_path, status)
            await self._on_task_complete(task_id, status, workdir_path)
            
        except asyncio.CancelledError:
            logger.warning(f"Monitor task for {task_id} was cancelled")
        except Exception as e:
            logger.exception(f"Error monitoring task {task_id}: {e}")
            self._write_status_file(workdir_path, TaskStatus.FAILED)
        finally:
            async with self._lock:
                self._processes.pop(task_id, None)
            try:
                log_file.close()
            except:
                pass
    
    async def _read_logs(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
        workdir_path: Path,
        log_file
    ) -> None:
        """
        Non-blocking read stdout, parse progress, write log file, WebSocket push.
        
        Parsing content:
        - Progress: 'X of Y steps (Z%) done'
        - Errors: Lines containing Error/ERROR/Exception
        - Normal logs: All other output
        """
        if process.stdout is None:
            return
        
        progress_path = workdir_path / "progress.json"
        
        async for line in process.stdout:
            line_str = line.decode().rstrip()
            
            # 1. Write to log file
            log_file.write(line_str + "\n")
            log_file.flush()
            
            # 2. Try parsing progress
            progress_update = None
            if match := PROGRESS_PATTERN.search(line_str):
                current, total, percent = match.groups()
                progress_update = {
                    "current_step": int(current),
                    "total_steps": int(total),
                    "percent": int(percent),
                    "task_id": task_id
                }
                with open(progress_path, 'w') as f:
                    json.dump(progress_update, f)
            
            # 3. Detect errors
            is_error = bool(ERROR_PATTERN.search(line_str))
            
            # 4. WebSocket push (via Redis Pub/Sub or memory queue)
            await self._broadcast_log(task_id, line_str, progress_update, is_error)
    
    async def _broadcast_log(
        self,
        task_id: str,
        line: str,
        progress: Optional[dict],
        is_error: bool
    ) -> None:
        """
        Broadcast logs to WebSocket (via Redis Pub/Sub).
        
        Celery Worker and Web app are not in the same process,
        use Redis as message broker.
        """
        try:
            import redis.asyncio as redis
            from app.core.config import settings
            
            r = redis.from_url(settings.REDIS_URL)
            
            message = {
                "type": "task.log_output",
                "task_id": task_id,
                "payload": {
                    "chunk": line,
                    "is_error": is_error,
                    "timestamp": asyncio.get_event_loop().time()
                }
            }
            
            if progress:
                message["payload"]["progress"] = progress
            
            await r.publish(f"task:logs:{task_id}", json.dumps(message))
            await r.close()
            
        except Exception as e:
            logger.debug(f"Failed to broadcast log for task {task_id}: {e}")
    
    async def _on_task_complete(
        self,
        task_id: str,
        status: TaskStatus,
        workdir_path: Path
    ) -> None:
        """
        Task completion callback.
        
        Notify Celery task status change, trigger subsequent processing
        (email notification, result archiving, etc.).
        """
        try:
            from celery import current_app
            current_app.send_task(
                'app.tasks.on_task_complete',
                kwargs={
                    'task_id': task_id,
                    'status': status.value,
                    'results_dir': str(workdir_path / "results")
                }
            )
        except Exception as e:
            logger.error(f"Task completion callback failed for {task_id}: {e}")
    
    def _write_status_file(self, workdir_path: Path, status: TaskStatus) -> None:
        """Write status to file for external queries"""
        status_path = workdir_path / "status.json"
        with open(status_path, 'w') as f:
            json.dump({"status": status.value}, f)
    
    async def get_status(self, backend_job_id: str) -> TaskStatus:
        """
        Query task status.
        
        Query from in-memory process dict first, then read from file if process ended.
        """
        process = self._processes.get(backend_job_id)
        if process and process.returncode is None:
            return TaskStatus.RUNNING
        
        status_path = Path(f"/data/tasks/{backend_job_id}/status.json")
        if status_path.exists():
            with open(status_path) as f:
                data = json.load(f)
                return TaskStatus(data.get("status", "unknown"))
        
        return TaskStatus.PENDING
    
    async def cancel(self, backend_job_id: str, timeout: int = 5) -> bool:
        """
        Cancel task.
        
        Strategy:
        1. Send SIGTERM (graceful termination)
        2. Wait for specified timeout
        3. If process still running, send SIGKILL (force kill)
        """
        process = self._processes.get(backend_job_id)
        if not process:
            logger.warning(f"No running process found for task {backend_job_id}")
            return False
        
        if process.returncode is not None:
            logger.info(f"Task {backend_job_id} already finished")
            return False
        
        try:
            pgid = os.getpgid(process.pid)
            os.killpg(pgid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to task {backend_job_id} (PGID: {pgid})")
            
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
                logger.info(f"Task {backend_job_id} terminated gracefully")
                return True
            except asyncio.TimeoutError:
                logger.warning(f"Task {backend_job_id} did not terminate, sending SIGKILL")
                try:
                    os.killpg(pgid, signal.SIGKILL)
                    await process.wait()
                except ProcessLookupError:
                    pass
                return True
                
        except ProcessLookupError:
            logger.info(f"Task {backend_job_id} process already gone")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel task {backend_job_id}: {e}")
            return False
    
    async def stream_logs(self, task_id: str) -> AsyncGenerator[str, None]:
        """
        Stream read task logs.
        
        If task is running, real-time read log file;
        If task is completed, read complete log file.
        """
        log_path = Path(f"/data/tasks/{task_id}/snakemake.log")
        
        if not log_path.exists():
            yield f"[Log file not found: {log_path}]"
            return
        
        with open(log_path, 'r') as f:
            for line in f:
                yield line.rstrip()
        
        process = self._processes.get(task_id)
        if process and process.returncode is None:
            with open(log_path, 'r') as f:
                f.seek(0, 2)
                while process.returncode is None:
                    line = f.readline()
                    if line:
                        yield line.rstrip()
                    else:
                        await asyncio.sleep(0.5)
    
    async def get_results(self, task_id: str, workdir: str) -> dict:
        """
        Get task execution results.
        
        Scan results directory, collect output file list and statistics.
        """
        results_dir = Path(workdir) / "results"
        output_files = []
        
        if results_dir.exists():
            for file_path in results_dir.rglob("*"):
                if file_path.is_file():
                    output_files.append({
                        "path": str(file_path.relative_to(results_dir)),
                        "size": file_path.stat().st_size,
                        "modified": file_path.stat().st_mtime
                    })
        
        stats_path = Path(workdir) / "stats.json"
        stats = {}
        if stats_path.exists():
            try:
                with open(stats_path) as f:
                    stats = json.load(f)
            except:
                pass
        
        return {
            "task_id": task_id,
            "output_files": output_files,
            "total_size": sum(f["size"] for f in output_files),
            "file_count": len(output_files),
            "stats": stats
        }


# Register to factory
BackendFactory.register("local", LocalSnakemakeBackend)
```

---

### 6.8.4 RemoteMasterBackend Implementation

```python
# app/core/execution/remote_backend.py
# =============================================================================
# RemoteMasterBackend - Remote execution mode
# Call Master compute node via HTTP/WebSocket
# =============================================================================

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional
from pathlib import Path

import httpx
import websockets
import yaml

from .base import ExecutionBackend, TaskStatus, BackendFactory
from app.core.config import settings

logger = logging.getLogger(__name__)


class RemoteMasterBackend(ExecutionBackend):
    """
    Remote Master execution backend.
    
    Features:
    - Submit tasks to Master node via HTTP API
    - Receive real-time logs via WebSocket
    - Web platform itself does not execute Snakemake, only schedules
    - Suitable for compute-intensive scenarios, separation of web and compute
    """
    
    engine: str = "snakemake"
    
    def __init__(
        self,
        master_api_url: str = None,
        internal_token: str = None
    ):
        self.master_api_url = master_api_url or settings.MASTER_API_URL
        self.internal_token = internal_token or settings.INTERNAL_TOKEN
        self.headers = {
            "Content-Type": "application/json",
            "X-Internal-Token": self.internal_token
        }
    
    async def submit(
        self,
        task_id: str,
        snakefile: str,
        config: dict,
        workdir: str,
        cores: int = 8,
        extra_args: Optional[list[str]] = None
    ) -> str:
        """
        Submit task to Master node via HTTP.
        
        Flow:
        1. Ensure working directory and config file are created
        2. HTTP POST /api/v1/execute to Master
        3. Return Master-assigned job_id
        """
        workdir_path = Path(workdir)
        workdir_path.mkdir(parents=True, exist_ok=True)
        
        config_path = workdir_path / "config.yaml"
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        metadata = {
            "task_id": task_id,
            "snakefile": snakefile,
            "configfile": str(config_path),
            "workdir": workdir,
            "cores": cores,
            "callback_url": f"{settings.CALLBACK_URL}/task-complete",
            "websocket_url": f"{settings.WEBSOCKET_URL}/task-log",
            "extra_args": extra_args or []
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.master_api_url}/api/v1/execute",
                json=metadata,
                headers=self.headers
            )
            response.raise_for_status()
            result = response.json()
        
        master_job_id = result["job_id"]
        logger.info(f"Task {task_id} submitted to Master, job_id: {master_job_id}")
        
        return master_job_id
    
    async def get_status(self, backend_job_id: str) -> TaskStatus:
        """HTTP GET query task status on Master node"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.master_api_url}/api/v1/tasks/{backend_job_id}/status",
                    headers=self.headers
                )
                response.raise_for_status()
                result = response.json()
                return TaskStatus(result.get("status", "unknown"))
        except httpx.HTTPError as e:
            logger.error(f"Failed to get status for job {backend_job_id}: {e}")
            return TaskStatus.FAILED
    
    async def cancel(self, backend_job_id: str, timeout: int = 5) -> bool:
        """HTTP DELETE request Master to cancel task"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(
                    f"{self.master_api_url}/api/v1/tasks/{backend_job_id}",
                    headers=self.headers,
                    params={"timeout": timeout}
                )
                response.raise_for_status()
                result = response.json()
                return result.get("cancelled", False)
        except httpx.HTTPError as e:
            logger.error(f"Failed to cancel job {backend_job_id}: {e}")
            return False
    
    async def stream_logs(self, task_id: str) -> AsyncGenerator[str, None]:
        """
        WebSocket connect to Master node, receive log stream in real-time.
        
        Auto-reconnect on disconnect (up to 3 times).
        """
        ws_url = f"{self.master_api_url}/ws/v1/tasks/{task_id}/logs"
        ws_url = ws_url.replace("http://", "ws://").replace("https://", "wss://")
        
        reconnect_count = 0
        max_reconnect = 3
        
        while reconnect_count < max_reconnect:
            try:
                async with websockets.connect(
                    ws_url,
                    extra_headers={"X-Internal-Token": self.internal_token}
                ) as websocket:
                    logger.info(f"WebSocket connected for task {task_id} logs")
                    reconnect_count = 0
                    
                    async for message in websocket:
                        data = json.loads(message)
                        
                        if data.get("type") == "log":
                            yield data.get("payload", "")
                        elif data.get("type") == "progress":
                            progress = data.get("payload", {})
                            yield f"[Progress: {progress.get('current_step', 0)}/{progress.get('total_steps', 0)} ({progress.get('percent', 0)}%)]"
                        elif data.get("type") == "complete":
                            yield "[Task completed]"
                            return
                        elif data.get("type") == "error":
                            yield f"[Error: {data.get('payload', '')}]"
                            return
            except websockets.exceptions.ConnectionClosed:
                reconnect_count += 1
                if reconnect_count < max_reconnect:
                    logger.warning(f"WebSocket disconnected, reconnecting ({reconnect_count}/{max_reconnect})...")
                    await asyncio.sleep(2 ** reconnect_count)
                else:
                    yield "[WebSocket connection lost, log stream ended]"
                    return
            except Exception as e:
                logger.error(f"WebSocket error for task {task_id}: {e}")
                yield f"[Log stream error: {e}]"
                return
    
    async def get_results(self, task_id: str, workdir: str) -> dict:
        """
        Get task results from Master.
        
        Results are already written to shared storage via callback, read locally.
        """
        results_dir = Path(workdir) / "results"
        output_files = []
        
        if results_dir.exists():
            for file_path in results_dir.rglob("*"):
                if file_path.is_file():
                    output_files.append({
                        "path": str(file_path.relative_to(results_dir)),
                        "size": file_path.stat().st_size
                    })
        
        return {
            "task_id": task_id,
            "output_files": output_files,
            "total_size": sum(f["size"] for f in output_files),
            "file_count": len(output_files)
        }


# Register to factory
BackendFactory.register("remote", RemoteMasterBackend)
```



---

### 6.8.5 Master Node FastAPI Service Design

```python
# master/app/main.py
# =============================================================================
# Master Executor Service - Standalone FastAPI application
# Dedicated to executing Snakemake compute tasks
# =============================================================================

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configuration
MASTER_HOST = os.getenv("MASTER_HOST", "0.0.0.0")
MASTER_PORT = int(os.getenv("MASTER_PORT", "8001"))
CALLBACK_URL = os.getenv("CALLBACK_URL", "http://web:8000/internal/callback/task-complete")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "internal-token-change-me")
SNAKEMAKE_CORES = int(os.getenv("SNAKEMAKE_CORES", "16"))
CONDA_ENV_PATH = os.getenv("CONDA_ENV_PATH", "/opt/conda/envs")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# Logging setup
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("master")

# Global state
running_jobs: dict[str, dict] = {}
job_counter = 0
lock = asyncio.Lock()


# Pydantic models
class ExecuteRequest(BaseModel):
    """Task execution request"""
    task_id: str = Field(..., description="Web platform task ID")
    snakefile: str = Field(..., description="Snakefile path")
    configfile: str = Field(..., description="Config file path")
    workdir: str = Field(..., description="Working directory")
    cores: int = Field(default=SNAKEMAKE_CORES, ge=1, le=64)
    callback_url: Optional[str] = None
    websocket_url: Optional[str] = None
    extra_args: list[str] = Field(default_factory=list)


class StatusResponse(BaseModel):
    """Status response"""
    job_id: str
    task_id: str
    status: str
    progress: Optional[dict] = None


class CancelResponse(BaseModel):
    """Cancel response"""
    job_id: str
    cancelled: bool
    message: str


# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle"""
    logger.info("Master Executor starting...")
    yield
    logger.info("Master Executor shutting down, cleaning up jobs...")
    for job_id, job in list(running_jobs.items()):
        process = job.get("process")
        if process and process.poll() is None:
            logger.warning(f"Terminating job {job_id} on shutdown")
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass


app = FastAPI(
    title="OmicsHub Master Executor",
    description="Dedicated execution node for running Snakemake workflows",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency: internal token verification
async def verify_token(x_internal_token: str = ""):
    """Verify internal call token"""
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    return True


def generate_job_id() -> str:
    """Generate job ID"""
    global job_counter
    job_counter += 1
    return f"master-{job_counter:06d}"


async def write_status_file(workdir: str, status: str) -> None:
    """Write status file"""
    status_path = Path(workdir) / "status.json"
    with open(status_path, 'w') as f:
        json.dump({"status": status, "node": "master"}, f)


async def callback_web_platform(task_id: str, status: str, results: dict) -> None:
    """Callback Web platform to notify task completion"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                CALLBACK_URL,
                json={
                    "task_id": task_id,
                    "status": status,
                    "node": "master",
                    **results
                },
                headers={"X-Internal-Token": INTERNAL_TOKEN}
            )
            if response.status_code == 200:
                logger.info(f"Callback successful for task {task_id}")
            else:
                logger.error(f"Callback failed: {response.status_code}")
    except Exception as e:
        logger.error(f"Callback error for task {task_id}: {e}")


# API Endpoints

@app.get("/health")
async def health_check():
    """Health check"""
    return {
        "status": "healthy",
        "running_jobs": len(running_jobs),
        "node": "master"
    }


@app.post("/api/v1/execute", dependencies=[Depends(verify_token)])
async def execute_task(req: ExecuteRequest, background_tasks: BackgroundTasks):
    """
    Receive task, start Snakemake subprocess.
    
    Flow:
    1. Validate parameters
    2. Start subprocess
    3. Background task: monitor process, write logs, callback Web platform
    4. Return job_id
    """
    if not Path(req.snakefile).exists():
        raise HTTPException(status_code=400, detail=f"Snakefile not found: {req.snakefile}")
    if not Path(req.configfile).exists():
        raise HTTPException(status_code=400, detail=f"Configfile not found: {req.configfile}")
    
    workdir_path = Path(req.workdir)
    workdir_path.mkdir(parents=True, exist_ok=True)
    
    job_id = generate_job_id()
    
    log_path = workdir_path / "snakemake.log"
    
    cmd = [
        "snakemake",
        "--snakefile", req.snakefile,
        "--configfile", req.configfile,
        "--directory", str(workdir_path),
        "--cores", str(req.cores),
        "--nolock",
        "--latency-wait", "60",
        "--keep-going",
        "--rerun-incomplete",
        "--printshellcmds",
        "--stats", str(workdir_path / "stats.json"),
    ]
    cmd.extend(req.extra_args)
    
    logger.info(f"[{job_id}] Starting: {' '.join(cmd)}")
    
    log_file = open(log_path, 'w')
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(workdir_path),
        start_new_session=True,
        text=False
    )
    
    running_jobs[job_id] = {
        "task_id": req.task_id,
        "process": process,
        "status": "running",
        "workdir": req.workdir,
        "log_file": log_file,
    }
    
    await write_status_file(req.workdir, "running")
    
    background_tasks.add_task(
        monitor_job,
        job_id=job_id,
        task_id=req.task_id,
        process=process,
        workdir=req.workdir,
        log_file=log_file
    )
    
    return {
        "job_id": job_id,
        "task_id": req.task_id,
        "status": "running",
        "message": "Task submitted successfully"
    }


@app.get("/api/v1/tasks/{job_id}/status", dependencies=[Depends(verify_token)])
async def get_job_status(job_id: str):
    """Query task status"""
    job = running_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    process = job.get("process")
    status = job.get("status", "unknown")
    
    if process and process.poll() is not None and status == "running":
        status = "completed" if process.returncode == 0 else "failed"
        job["status"] = status
    
    progress_path = Path(job.get("workdir", "")) / "progress.json"
    progress = None
    if progress_path.exists():
        with open(progress_path) as f:
            progress = json.load(f)
    
    return StatusResponse(
        job_id=job_id,
        task_id=job.get("task_id", ""),
        status=status,
        progress=progress
    )


@app.delete("/api/v1/tasks/{job_id}", dependencies=[Depends(verify_token)])
async def cancel_job(job_id: str, timeout: int = 5):
    """
    Cancel task.
    
    Strategy: SIGTERM -> wait -> SIGKILL
    """
    job = running_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    process = job.get("process")
    if not process or process.poll() is not None:
        return CancelResponse(
            job_id=job_id, cancelled=True, message="Job already finished"
        )
    
    try:
        pgid = os.getpgid(process.pid)
        os.killpg(pgid, signal.SIGTERM)
        
        try:
            process.wait(timeout=timeout)
            job["status"] = "cancelled"
            await write_status_file(job.get("workdir", ""), "cancelled")
            return CancelResponse(
                job_id=job_id, cancelled=True, message="Job cancelled gracefully"
            )
        except subprocess.TimeoutExpired:
            os.killpg(pgid, signal.SIGKILL)
            process.wait()
            job["status"] = "cancelled"
            return CancelResponse(
                job_id=job_id, cancelled=True, message="Job force-killed"
            )
    except ProcessLookupError:
        return CancelResponse(
            job_id=job_id, cancelled=True, message="Process already gone"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cancel failed: {str(e)}")


@app.websocket("/ws/v1/tasks/{task_id}/logs")
async def stream_logs(websocket: WebSocket, task_id: str):
    """
    WebSocket log stream.
    
    Push task logs to Web platform in real-time.
    """
    await websocket.accept()
    
    job = None
    for j in running_jobs.values():
        if j.get("task_id") == task_id:
            job = j
            break
    
    if not job:
        await websocket.send_json({"type": "error", "payload": "Task not found"})
        await websocket.close()
        return
    
    workdir = job.get("workdir", "")
    log_path = Path(workdir) / "snakemake.log"
    process = job.get("process")
    
    PROGRESS_RE = re.compile(r'(\d+) of (\d+) steps \((\d+)%\) done')
    
    try:
        with open(log_path, 'r') as f:
            for line in f:
                await websocket.send_json({"type": "log", "payload": line.rstrip()})
            
            while process and process.poll() is None:
                line = f.readline()
                if line:
                    line_str = line.rstrip()
                    
                    if match := PROGRESS_RE.search(line_str):
                        current, total, pct = match.groups()
                        await websocket.send_json({
                            "type": "progress",
                            "payload": {
                                "current_step": int(current),
                                "total_steps": int(total),
                                "percent": int(pct)
                            }
                        })
                    
                    await websocket.send_json({"type": "log", "payload": line_str})
                else:
                    await asyncio.sleep(0.5)
            
            returncode = process.poll() if process else -1
            if returncode == 0:
                await websocket.send_json({"type": "complete"})
            else:
                await websocket.send_json({
                    "type": "error",
                    "payload": f"Process exited with code {returncode}"
                })
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for task {task_id}")
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}")
        try:
            await websocket.send_json({"type": "error", "payload": str(e)})
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass


# Background monitoring function
async def monitor_job(
    job_id: str,
    task_id: str,
    process: subprocess.Popen,
    workdir: str,
    log_file
):
    """
    Background monitoring of task execution.
    
    - Read log output
    - Monitor process status
    - Callback Web platform after process ends
    """
    logger.info(f"[{job_id}] Monitor started for task {task_id}")
    
    PROGRESS_RE = re.compile(r'(\d+) of (\d+) steps \((\d+)%\) done')
    progress_path = Path(workdir) / "progress.json"
    
    try:
        if process.stdout:
            while True:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    await asyncio.sleep(0.5)
                    continue
                
                line_str = line.decode().rstrip()
                
                log_file.write(line_str + "\n")
                log_file.flush()
                
                if match := PROGRESS_RE.search(line_str):
                    current, total, pct = match.groups()
                    with open(progress_path, 'w') as pf:
                        json.dump({
                            "current_step": int(current),
                            "total_steps": int(total),
                            "percent": int(pct)
                        }, pf)
        
        returncode = process.wait()
        
        if returncode == 0:
            status = "completed"
        elif returncode in [-signal.SIGTERM, -signal.SIGKILL]:
            status = "cancelled"
        else:
            status = "failed"
        
        logger.info(f"[{job_id}] Task {task_id} finished: {status} (code: {returncode})")
        
    except Exception as e:
        logger.exception(f"[{job_id}] Monitor error: {e}")
        status = "failed"
    finally:
        running_jobs[job_id]["status"] = status
        await write_status_file(workdir, status)
        try:
            log_file.close()
        except:
            pass
        
        results = {
            "returncode": process.returncode if process else -1,
            "results_dir": str(Path(workdir) / "results")
        }
        await callback_web_platform(task_id, status, results)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=MASTER_HOST, port=MASTER_PORT)
```

---

### 6.8.6 Task Directory Isolation and Snakemake Lock-free Execution

```python
# app/core/execution/task_isolation.py
# =============================================================================
# Task directory isolation utility
# Ensure each task has an independent workspace to avoid conflicts
# =============================================================================

import os
import json
import shutil
import csv
from pathlib import Path
from datetime import datetime
import uuid


class TaskWorkspace:
    """
    Task workspace manager.
    
    Each task has an independent directory containing:
    - config.yaml: Snakemake configuration
    - samples.csv: Sample information
    - metadata.json: Task metadata
    - snakemake.log: Execution log
    - status.json: Status file
    - progress.json: Progress file
    - results/: Results directory
    """
    
    def __init__(self, task_id: str, base_path: str = "/data/tasks"):
        self.task_id = task_id
        self.base_path = Path(base_path)
        self.workspace = self.base_path / task_id
    
    def create(self, config: dict, samples: list = None, metadata: dict = None) -> Path:
        """Create workspace"""
        self.workspace.mkdir(parents=True, exist_ok=True)
        
        (self.workspace / "results").mkdir(exist_ok=True)
        (self.workspace / "temp").mkdir(exist_ok=True)
        
        import yaml
        with open(self.workspace / "config.yaml", 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        if samples:
            with open(self.workspace / "samples.csv", 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=samples[0].keys())
                writer.writeheader()
                writer.writerows(samples)
        
        meta = {
            "task_id": self.task_id,
            "created_at": datetime.utcnow().isoformat(),
            **(metadata or {})
        }
        with open(self.workspace / "metadata.json", 'w') as f:
            json.dump(meta, f, indent=2)
        
        with open(self.workspace / "status.json", 'w') as f:
            json.dump({"status": "pending"}, f)
        
        return self.workspace
    
    def get_results_path(self) -> Path:
        """Get results directory path"""
        return self.workspace / "results"
    
    def get_log_path(self) -> Path:
        """Get log file path"""
        return self.workspace / "snakemake.log"
    
    def get_status(self) -> str:
        """Read status"""
        status_file = self.workspace / "status.json"
        if status_file.exists():
            with open(status_file) as f:
                return json.load(f).get("status", "unknown")
        return "not_found"
    
    def cleanup(self, keep_results: bool = True) -> None:
        """
        Clean up workspace.
        
        Args:
            keep_results: Whether to keep results directory
        """
        if keep_results:
            for pattern in ["temp/*", ".snakemake", "*.tmp"]:
                for path in self.workspace.glob(pattern):
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        path.unlink(missing_ok=True)
        else:
            shutil.rmtree(self.workspace, ignore_errors=True)
    
    @staticmethod
    def generate_task_id() -> str:
        """Generate unique task ID"""
        return str(uuid.uuid4())


def build_snakemake_args(workspace: Path, snakefile: str, cores: int) -> list[str]:
    """
    Build Snakemake command line arguments.
    
    Key parameters:
    - --nolock: Disable file lock (required for multi-task concurrency)
    - --directory: Specify working directory
    - --configfile: Specify configuration file
    """
    return [
        "--snakefile", snakefile,
        "--configfile", str(workspace / "config.yaml"),
        "--directory", str(workspace),
        "--cores", str(cores),
        "--nolock",
        "--latency-wait", "60",
        "--keep-going",
        "--rerun-incomplete",
        "--printshellcmds",
        "--stats", str(workspace / "stats.json"),
    ]
```

---

### 6.8.7 Celery Task Integration

```python
# app/tasks/workflow_tasks.py
# =============================================================================
# Celery task definitions - workflow execution
# =============================================================================

import asyncio
import logging
from celery import shared_task
from app.core.execution.base import BackendFactory
from app.core.config import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def execute_workflow(self, task_id: str, workflow_type: str, config: dict, user_id: str):
    """
    Celery task: Execute workflow.
    
    This is the task received by Celery Worker, responsible for calling
    ExecutionBackend to execute Snakemake.
    
    Args:
        task_id: Task ID
        workflow_type: Workflow type (rna_seq, atac_seq, scRNA_seq)
        config: Snakemake configuration
        user_id: User ID
    """
    logger.info(f"Executing workflow task {task_id}, type={workflow_type}")
    
    loop = asyncio.get_event_loop()
    backend = BackendFactory.create(settings.EXECUTION_MODE)
    
    snakefile = f"/workflows/{workflow_type}/Snakefile"
    workdir = f"/data/tasks/{task_id}"
    cores = config.get("cores", settings.SNAKEMAKE_CORES)
    
    try:
        backend_job_id = loop.run_until_complete(backend.submit(
            task_id=task_id,
            snakefile=snakefile,
            config=config,
            workdir=workdir,
            cores=cores
        ))
        
        import time
        while True:
            time.sleep(5)
            status = loop.run_until_complete(backend.get_status(backend_job_id))
            
            if status in ("completed", "failed", "cancelled"):
                break
        
        results = loop.run_until_complete(backend.get_results(task_id, workdir))
        
        return {
            "task_id": task_id,
            "status": status,
            "results": results
        }
        
    except Exception as exc:
        logger.exception(f"Workflow execution failed: {exc}")
        self.retry(exc=exc)


@shared_task
def cancel_workflow_task(task_id: str):
    """Cancel running workflow"""
    loop = asyncio.get_event_loop()
    backend = BackendFactory.create(settings.EXECUTION_MODE)
    success = loop.run_until_complete(backend.cancel(task_id))
    return {"task_id": task_id, "cancelled": success}


@shared_task
def on_task_complete(task_id: str, status: str, results_dir: str):
    """
    Task completion callback.
    
    Trigger subsequent processing:
    - Send email notification
    - Update task status
    - Archive results
    """
    logger.info(f"Task {task_id} completed with status: {status}")
    
    from app.services.notification import notify_task_complete
    loop = asyncio.get_event_loop()
    loop.run_until_complete(notify_task_complete(task_id, status))
    
    return {"task_id": task_id, "status": status}
```



---

## 6.9 安全与数据隔离

### 6.9.1 安全架构总览

```
+-----------------------------------------------------------------------------+
|                              Security Architecture                           |
+-----------------------------------------------------------------------------+
|                                                                             |
|  [Client] --HTTPS--> [Nginx] --HTTP--> [Web:8000]                         |
|                          |                                                  |
|                          |--/flower/ (Basic Auth + IP whitelist)          |
|                          |--/internal/ (IP whitelist only)                 |
|                                                                             |
|  [Web] --Docker Network--> [DB:5432] [Redis:6379]                         |
|                                                                             |
|  [Web] --HTTP + Token--> [Master:8001] (internal only)                    |
|                                                                             |
|  [Master] --Callback + Token--> [Web:/internal/callback]                  |
|                                                                             |
|  File System: /data/uploads/{user_id}/ (app-layer isolation)              |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

### 6.9.2 用户文件系统隔离

#### 方案选择

| 方案 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **Docker Volume bind** (推荐) | 内网小团队 | 简单、直接、性能好 | 依赖宿主机文件系统 |
| **MinIO对象存储** | 大规模/公网 | 标准S3 API、高可用 | 增加复杂度、需要维护 |

**推荐方案**：文件系统隔离（适合内网小团队，单维护者可管理）。

#### 实现代码

```python
# app/core/security/file_access.py
# =============================================================================
# File access control - user file system isolation
# =============================================================================

import os
import re
from pathlib import Path
from fastapi import HTTPException, Depends
from app.core.config import settings

# Dangerous characters that should not appear in paths
DANGEROUS_CHARS = re.compile(r'[;|&$`\\]')
# Path traversal pattern
PATH_TRAVERSAL = re.compile(r'\.\.(?:/|\\)')


class FileAccessController:
    """
    File access controller.
    
    Ensure users can only access their own files,
    preventing unauthorized access and path traversal attacks.
    """
    
    def __init__(self, base_upload_path: str = "/data/uploads"):
        self.base_upload_path = Path(base_upload_path)
    
    def get_user_directory(self, user_id: str) -> Path:
        """Get user upload directory"""
        user_dir = self.base_upload_path / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def validate_path(self, user_id: str, requested_path: str) -> Path:
        """
        Validate and resolve file path.
        
        Checks:
        1. Path does not contain dangerous characters
        2. No path traversal (..)
        3. Resolved path is within user directory
        """
        # Check dangerous characters
        if DANGEROUS_CHARS.search(requested_path):
            raise HTTPException(status_code=400, detail="Invalid characters in path")
        
        # Check path traversal
        if PATH_TRAVERSAL.search(requested_path):
            raise HTTPException(status_code=400, detail="Path traversal not allowed")
        
        # Resolve absolute path
        user_dir = self.get_user_directory(user_id)
        resolved = (user_dir / requested_path).resolve()
        
        # Ensure path is within user directory
        try:
            resolved.relative_to(user_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")
        
        return resolved
    
    def list_user_files(self, user_id: str) -> list[dict]:
        """List files in user directory"""
        user_dir = self.get_user_directory(user_id)
        files = []
        
        for file_path in user_dir.rglob("*"):
            if file_path.is_file():
                files.append({
                    "path": str(file_path.relative_to(user_dir)),
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime,
                    "name": file_path.name
                })
        
        return files


# Global instance
file_controller = FileAccessController()


# FastAPI dependency
def get_file_controller():
    return file_controller
```

#### 应用层权限控制

```python
# app/api/deps.py
# =============================================================================
# API dependencies - user verification
# =============================================================================

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.user import User
from app.core.security import verify_token

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """Get current user from JWT token"""
    token = credentials.credentials
    user_id = verify_token(token)
    
    user = await User.get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Get current active user"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_superuser(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Get current superuser (admin)"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Not enough privileges"
        )
    return current_user
```

---

### 6.9.3 敏感信息管理

#### Docker Secrets方案（推荐用于生产环境）

```yaml
# docker-compose.secrets.yml - Docker Secrets configuration
version: "3.8"

services:
  web:
    secrets:
      - postgres_password
      - secret_key
      - internal_token
      - kimi_api_key
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
      SECRET_KEY_FILE: /run/secrets/secret_key
      INTERNAL_TOKEN_FILE: /run/secrets/internal_token
      KIMI_API_KEY_FILE: /run/secrets/kimi_api_key

  db:
    secrets:
      - postgres_password
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password

  master:
    secrets:
      - internal_token
    environment:
      INTERNAL_TOKEN_FILE: /run/secrets/internal_token

secrets:
  postgres_password:
    file: ./secrets/postgres_password.txt
  secret_key:
    file: ./secrets/secret_key.txt
  internal_token:
    file: ./secrets/internal_token.txt
  kimi_api_key:
    file: ./secrets/kimi_api_key.txt
```

#### 创建Secrets脚本

```bash
#!/bin/bash
# create_secrets.sh - Create Docker secrets directory

SECRETS_DIR="./secrets"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

# PostgreSQL password
if [ ! -f "$SECRETS_DIR/postgres_password.txt" ]; then
    openssl rand -base64 32 > "$SECRETS_DIR/postgres_password.txt"
    echo "Created postgres_password.txt"
fi

# JWT Secret key
if [ ! -f "$SECRETS_DIR/secret_key.txt" ]; then
    openssl rand -base64 64 > "$SECRETS_DIR/secret_key.txt"
    echo "Created secret_key.txt"
fi

# Internal token
if [ ! -f "$SECRETS_DIR/internal_token.txt" ]; then
    openssl rand -base64 32 > "$SECRETS_DIR/internal_token.txt"
    echo "Created internal_token.txt"
fi

chmod 600 "$SECRETS_DIR"/*.txt
echo "All secrets created in $SECRETS_DIR"
```

#### 配置加载器（支持从文件读取Secrets）

```python
# app/core/config.py
# =============================================================================
# Configuration - support reading from Docker secrets files
# =============================================================================

import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings


def read_secret(secret_name: str, default: str = "") -> str:
    """
    Read Docker secret from file.
    
    In Docker Swarm, secrets are mounted at /run/secrets/.
    Falls back to environment variable or default value.
    """
    # Priority: Docker secret file > environment variable > default
    secret_path = Path(f"/run/secrets/{secret_name}")
    if secret_path.exists():
        return secret_path.read_text().strip()
    
    env_value = os.getenv(secret_name.upper())
    if env_value:
        return env_value
    
    # Check for _FILE suffix (Docker Compose secrets)
    env_file = os.getenv(f"{secret_name.upper()}_FILE")
    if env_file and Path(env_file).exists():
        return Path(env_file).read_text().strip()
    
    return default


class Settings(BaseSettings):
    """Application settings"""
    
    # Execution mode
    EXECUTION_MODE: str = "local"
    SNAKEMAKE_CORES: int = 8
    
    # Database
    POSTGRES_USER: str = "omicshub"
    POSTGRES_PASSWORD: str = "changeme"
    POSTGRES_DB: str = "omicshub"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    
    DATABASE_URL: str = ""
    
    # Redis
    REDIS_PASSWORD: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Celery
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    
    # Security
    SECRET_KEY: str = "change-me-in-production"
    INTERNAL_TOKEN: str = "internal-token"
    
    # Master node (remote mode)
    MASTER_API_URL: str = "http://master:8001"
    CALLBACK_URL: str = "http://web:8000/internal/callback"
    WEBSOCKET_URL: str = "ws://web:8000/internal/ws"
    
    # API keys
    KIMI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    
    # Paths
    SHARED_STORAGE_PATH: str = "/data"
    WORKFLOW_PATH: str = "/workflows"
    
    # App config
    LOG_LEVEL: str = "INFO"
    MAX_UPLOAD_SIZE: int = 1073741824  # 1GB
    
    def model_post_init(self, __context):
        """Post-initialization, construct DATABASE_URL"""
        if not self.DATABASE_URL:
            password = self.POSTGRES_PASSWORD
            self.DATABASE_URL = (
                f"postgresql://{self.POSTGRES_USER}:{password}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}"
                f"/{self.POSTGRES_DB}"
            )
        
        redis_auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        if not self.REDIS_URL or "localhost" in self.REDIS_URL:
            self.REDIS_URL = f"redis://{redis_auth}redis:6379/0"
        if not self.CELERY_BROKER_URL:
            self.CELERY_BROKER_URL = self.REDIS_URL
        if not self.CELERY_RESULT_BACKEND:
            self.CELERY_RESULT_BACKEND = f"redis://{redis_auth}redis:6379/1"


@lru_cache()
def get_settings() -> Settings:
    """Get settings singleton"""
    return Settings()
```

---

### 6.9.4 脚本执行安全

#### 命令注入防护

```python
# app/core/security/command_safety.py
# =============================================================================
# Command execution safety - prevent command injection
# =============================================================================

import re
import os
from pathlib import Path
from typing import Optional
from fastapi import HTTPException

# Dangerous shell characters
DANGEROUS_SHELL_CHARS = set(';|&$`\\<>!{}[]\n\r')
# Path traversal patterns
PATH_TRAVERSAL_PATTERNS = [
    re.compile(r'\.\./'),
    re.compile(r'\.\.\\'),
    re.compile(r'^/'),
    re.compile(r'^~'),
]


class CommandSafetyChecker:
    """
    Command safety checker.
    
    Prevent command injection and path traversal attacks.
    """
    
    @staticmethod
    def validate_param(value: str, param_name: str = "parameter") -> str:
        """
        Validate user parameter.
        
        Check:
        1. No dangerous shell characters
        2. Not empty
        3. Reasonable length
        """
        if not value or not value.strip():
            raise HTTPException(status_code=400, detail=f"{param_name} cannot be empty")
        
        if len(value) > 1024:
            raise HTTPException(status_code=400, detail=f"{param_name} too long")
        
        for char in value:
            if char in DANGEROUS_SHELL_CHARS:
                raise HTTPException(
                    status_code=400,
                    detail=f"{param_name} contains dangerous character: '{char}'"
                )
        
        return value.strip()
    
    @staticmethod
    def validate_path(path: str, base_dir: str, param_name: str = "path") -> str:
        """
        Validate file path.
        
        Check:
        1. No path traversal
        2. Resolves within base directory
        3. Absolute path
        """
        # Check path traversal patterns
        for pattern in PATH_TRAVERSAL_PATTERNS:
            if pattern.search(path):
                raise HTTPException(
                    status_code=400,
                    detail=f"{param_name} contains path traversal"
                )
        
        # Resolve absolute path
        base = Path(base_dir).resolve()
        requested = (base / path).resolve()
        
        try:
            requested.relative_to(base)
        except ValueError:
            raise HTTPException(
                status_code=403,
                detail=f"{param_name} is outside allowed directory"
            )
        
        return str(requested)
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize filename.
        
        Remove dangerous characters, ensure safe filename.
        """
        # Remove dangerous characters
        safe = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        # Remove leading dots (hide files)
        safe = safe.lstrip('.')
        # Limit length
        safe = safe[:255]
        return safe or "unnamed"


# Global checker instance
safety = CommandSafetyChecker()
```

#### Pydantic输入校验

```python
# app/schemas/workflow.py
# =============================================================================
# Workflow request schemas - strict input validation
# =============================================================================

from pydantic import BaseModel, Field, validator
from typing import Optional, Literal


class WorkflowSubmitRequest(BaseModel):
    """Workflow submission request"""
    
    workflow_type: Literal["rna_seq", "atac_seq", "scRNA_seq"] = Field(
        ...,
        description="Workflow type"
    )
    
    genome: str = Field(
        ...,
        min_length=2,
        max_length=50,
        pattern=r'^[a-zA-Z0-9_]+$',
        description="Reference genome, e.g., hg38, mm10"
    )
    
    samples: list[dict] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Sample list"
    )
    
    cores: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Number of CPU cores"
    )
    
    memory_gb: int = Field(
        default=32,
        ge=4,
        le=256,
        description="Memory size (GB)"
    )
    
    extra_params: Optional[dict] = Field(
        default=None,
        description="Extra Snakemake parameters"
    )
    
    @validator('genome')
    def validate_genome(cls, v):
        allowed = {'hg38', 'hg19', 'mm10', 'mm9', 'dm6', 'ce11'}
        if v not in allowed:
            raise ValueError(f"genome must be one of: {allowed}")
        return v
    
    @validator('samples')
    def validate_samples(cls, v):
        if not v:
            raise ValueError("samples list cannot be empty")
        required_keys = {'sample_id', 'fastq_1'}
        for i, sample in enumerate(v):
            missing = required_keys - set(sample.keys())
            if missing:
                raise ValueError(f"Sample {i} missing required fields: {missing}")
        return v


class TaskCancelRequest(BaseModel):
    """Task cancellation request"""
    
    task_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        pattern=r'^[0-9a-f-]{36}$',
        description="Task UUID"
    )
    
    force: bool = Field(
        default=False,
        description="Force kill (SIGKILL)"
    )
```

---

### 6.9.5 Master Node Internal Network Isolation

#### Network隔离策略

```yaml
# docker-compose.master.yml - Network isolation section
networks:
  omicshub_master_net:
    driver: bridge
    internal: true  # Block external access, only internal Docker communication
    ipam:
      config:
        - subnet: 172.21.0.0/16
```

> **Note**: Setting `internal: true` completely blocks external network access.
> If Master needs to callback to the Web platform, use a shared network or host mode.

#### iptables防火墙规则（宿主机层面）

```bash
#!/bin/bash
# firewall_rules.sh - Master node firewall rules

# Clear existing rules
iptables -F
iptables -X

# Default policy: deny all
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

# Allow loopback
iptables -A INPUT -i lo -j ACCEPT

# Allow established connections
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow SSH (if needed for maintenance)
iptables -A INPUT -p tcp --dport 22 -s 10.0.0.0/8 -j ACCEPT

# Allow Web platform to access Master API (port 8001)
# Web platform container IP range
iptables -A INPUT -p tcp --dport 8001 -s 172.20.0.0/16 -j ACCEPT

# Allow internal Docker network
iptables -A INPUT -s 172.21.0.0/16 -j ACCEPT

# Log and drop other connections
iptables -A INPUT -j LOG --log-prefix "[OMICSHUB DROP] "
iptables -A INPUT -j DROP

# Save rules
iptables-save > /etc/iptables/rules.v4

echo "Firewall rules applied"
```

---

### 6.9.6 Callback Interface Security

#### Web平台回调端点

```python
# app/api/internal/callback.py
# =============================================================================
# Internal callback endpoints - only accessible by Master node
# =============================================================================

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from app.core.config import settings

router = APIRouter(prefix="/internal/callback", tags=["internal"])


async def verify_internal_token(x_internal_token: str = Header(...)):
    """Verify internal callback token"""
    if x_internal_token != settings.INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    return True


async def verify_internal_ip(request: Request):
    """Verify request comes from internal network"""
    client_ip = request.client.host
    allowed_prefixes = ("172.20.", "172.21.", "127.0.")
    if not any(client_ip.startswith(p) for p in allowed_prefixes):
        raise HTTPException(status_code=403, detail="Access denied")
    return True


@router.post("/task-complete", dependencies=[Depends(verify_internal_token)])
async def task_complete_callback(
    data: dict,
    request: Request,
    _ip=Depends(verify_internal_ip)
):
    """
    Task completion callback - only accessible by Master node.
    
    Security:
    - Nginx layer IP whitelist
    - Header token verification
    - Not exposed on public network
    """
    task_id = data.get("task_id")
    status = data.get("status")
    
    # Update task status
    from app.services.task import update_task_status
    await update_task_status(task_id, status)
    
    # Send notification to user
    await notify_user_task_complete(task_id, status)
    
    return {"status": "ok"}
```

---

### 6.9.7 安全策略总结

| 层级 | 措施 | 说明 |
|------|------|------|
| **网络层** | Docker internal network | Master节点不暴露公网 |
| | Nginx IP whitelist | /internal/仅允许Docker内网IP |
| | iptables防火墙 | 宿主机层面限制入站连接 |
| **应用层** | JWT认证 | API请求携带有效令牌 |
| | RBAC权限控制 | 超级用户/普通用户角色区分 |
| | 文件系统隔离 | /data/uploads/{user_id}/ |
| **数据层** | Docker Secrets | 密钥不存储在环境变量 |
| | PostgreSQL密码 | 强密码，通过Secret注入 |
| | Redis密码 | 可选，建议设置 |
| **执行层** | 参数校验 | Pydantic严格校验所有输入 |
| | 命令注入防护 | 用户参数写入config.yaml |
| | 路径校验 | os.path.abspath，禁止..穿越 |
| | 进程隔离 | start_new_session=True，killpg终止 |
| **通信层** | Internal Token | Master回调需携带X-Internal-Token |
| | HTTPS | 生产环境启用SSL/TLS |

---

## 6.10 运维操作手册

### 6.10.1 常用操作命令

```bash
# === 一键部署 ===
./init.sh

# === 查看服务状态 ===
docker-compose ps
docker-compose logs -f web
docker-compose logs -f celery_worker
docker-compose logs -f master  # remote mode

# === 重启服务 ===
docker-compose restart web
docker-compose restart celery_worker

# === 数据库迁移 ===
docker-compose exec web alembic revision --autogenerate -m "add new table"
docker-compose exec web alembic upgrade head
docker-compose exec web alembic downgrade -1

# === 备份 ===
./scripts/backup.sh

# === 更新部署 ===
git pull
docker-compose pull
docker-compose up -d --build

# === 查看资源使用 ===
docker stats

# === 清理旧数据 ===
docker system prune -f  # 清理未使用的镜像和容器
docker volume prune -f  # 清理未使用的卷（谨慎！）
```

### 6.10.2 故障排查

| 现象 | 可能原因 | 解决方案 |
|------|----------|----------|
| Web无法启动 | 数据库未就绪 | 检查db健康状态 `docker-compose ps` |
| 任务提交失败 | Worker未运行 | `docker-compose ps` 检查celery_worker |
| 权限错误 | UID/GID不匹配 | `chown -R 1000:1000 /data/omicshub` |
| 存储空间不足 | 日志或结果文件过大 | 清理 `/data/omicshub/tmp/` 和日志 |
| Master连接失败 | 网络不通 | 检查Docker网络互联配置 |
| WebSocket断开 | Nginx配置问题 | 检查nginx.conf proxy设置 |

### 6.10.3 监控与健康检查

```bash
# 系统健康检查脚本
#!/bin/bash
# health_check.sh

echo "=== OmicsHub Health Check ==="

# Check all services
echo "--- Services ---"
docker-compose ps

# Check database
echo "--- Database ---"
docker-compose exec -T db pg_isready -U omicshub

# Check Redis
echo "--- Redis ---"
docker-compose exec -T redis redis-cli ping

# Check Web API
echo "--- Web API ---"
curl -sf http://localhost/api/v1/health && echo "OK" || echo "FAILED"

# Check disk usage
echo "--- Disk Usage ---"
df -h /data/omicshub

# Check memory
echo "--- Memory ---"
free -h

echo "=== Check Complete ==="
```

---

## 6.11 总结

OmicsHub的部署运维体系围绕以下核心原则设计：

1. **极简运维**：单维护者可管理，一键部署（`./init.sh`），所有配置集中管理
2. **双模式支持**：Local模式适合单机，Remote模式支持计算扩展，通过 `EXECUTION_MODE` 环境变量切换
3. **安全隔离**：多层安全策略（网络隔离、文件隔离、参数校验、Token认证）
4. **策略模式**：`ExecutionBackend` 抽象层实现执行引擎的无缝切换
5. **无锁执行**：每个任务独立目录 + `--nolock` 参数确保多任务并发安全
6. **优雅取消**：SIGTERM -> 等待 -> SIGKILL 的进程终止策略
7. **实时监控**：WebSocket日志流 + 进度解析 + Flower监控面板

> **部署建议**：组内服务器资源有限的情况下，建议先用Local模式部署，当计算需求增长时再迁移到Remote模式。两个模式共享相同的业务逻辑，迁移只需修改环境变量即可。



---

# 6.7 开发里程碑（MVP → v1.0）

> **项目背景**：OmicsHub 是组内多组学分析平台，当前维护者仅 1 人（全栈开发），组内无专业前端/UI 设计师。核心诉求是尽快替代命令行提交任务的方式，让组内成员通过 Web 界面即可提交和监控分析任务。
>
> **技术栈**：前端 Vue 3 + TypeScript + Naive UI；后端 FastAPI + Pydantic v2 + PostgreSQL + Redis + Celery；执行层 Snakemake（本地/远程混合模式）；部署 Docker + Docker Compose。

---

## 目录

- [里程碑时间线总览（甘特图）](#里程碑时间线总览甘特图)
- [Phase 1: MVP — 可实际使用的 RNA-seq 分析平台](#phase-1-mvp--minimum-viable-product)
- [Phase 2: v0.8 — 平台化扩展](#phase-2-v08--平台化扩展)
- [Phase 3: v1.0 — 生产就绪](#phase-3-v10--生产就绪)
- [风险与应对](#风险与应对)
- [技术债务管理](#技术债务管理)

---

## 里程碑时间线总览（甘特图）

假设开发起始日为 **Week 1 周一**，总计 **10-14 周**（约 2.5-3.5 个月）。

```mermaid
gantt
    title OmicsHub 开发里程碑
    dateFormat YYYY-MM-DD
    axisFormat W%W
    tickInterval 1week

    section Phase 1 MVP
    P1-1 基础设施搭建           :p1_infra, 2025-01-06, 5d
    P1-2 用户认证模块            :p1_auth, after p1_infra, 3d
    P1-3 YAML 配置与动态表单     :p1_yaml, after p1_auth, 5d
    P1-4 样本表上传与解析        :p1_sample, after p1_yaml, 3d
    P1-5 Snakemake 本地执行      :p1_exec, after p1_sample, 5d
    P1-6 任务列表与状态监控      :p1_monitor, after p1_exec, 4d
    P1-7 日志实时推送(WebSocket) :p1_ws, after p1_monitor, 3d
    P1-8 结果文件浏览与下载      :p1_result, after p1_ws, 3d
    P1-9 Docker Compose 部署     :p1_docker, after p1_result, 4d
    P1-10 集成测试与修复         :p1_test, after p1_docker, 5d
    P1 里程碑评审               :milestone, after p1_test, 0d

    section Phase 2 v0.8
    P2-1 流程配置中心(多流程)    :p2_flow, 2025-02-17, 5d
    P2-2 YAML校验与版本管理      :p2_val, after p2_flow, 3d
    P2-3 高级动态表单(条件渲染)  :p2_form, after p2_val, 4d
    P2-4 AI对话助手(基础版)      :p2_ai, after p2_form, 4d
    P2-5 MCP服务集成             :p2_mcp, after p2_ai, 4d
    P2-6 任务管理增强            :p2_task, after p2_mcp, 3d
    P2-7 集成测试与修复          :p2_test, after p2_task, 4d
    P2 里程碑评审               :milestone, after p2_test, 0d

    section Phase 3 v1.0
    P3-1 远程执行模式(Remote)    :p3_remote, 2025-03-17, 5d
    P3-2 结果可视化(ECharts)      :p3_viz, after p3_remote, 5d
    P3-3 项目管理(样本层级)      :p3_proj, after p3_viz, 4d
    P3-4 AI增强(工具调用)        :p3_ai2, after p3_proj, 4d
    P3-5 管理后台               :p3_admin, after p3_ai2, 3d
    P3-6 安全与运维加固          :p3_sec, after p3_admin, 3d
    P3-7 完整文档               :p3_doc, after p3_sec, 3d
    P3-8 生产环境部署与压测       :p3_prod, after p3_doc, 4d
    P3 里程碑评审(v1.0 发布)     :milestone, after p3_prod, 0d
```

**时间线说明**：

| 阶段 | 预计工期 | 日历时间 | 关键交付物 |
|------|----------|----------|-----------|
| Phase 1 MVP | 4-6 周 | Week 1-6 | 可提交 RNA-seq 任务的完整平台 |
| Phase 2 v0.8 | 3-4 周 | Week 7-10 | 多流程支持 + AI 对话 + MCP |
| Phase 3 v1.0 | 3-4 周 | Week 11-14 | 远程模式 + 可视化 + 生产就绪 |

> **缓冲策略**：每个阶段预留 1 周缓冲时间用于 Bug 修复和意外问题处理。

---

## Phase 1: MVP — Minimum Viable Product

### 目标

一个可实际使用的 RNA-seq 分析流程提交平台。组内成员完全告别命令行，通过 Web 界面即可完成 RNA-seq 分析任务的全生命周期管理。

### 开发优先级排序（按依赖关系）

| 优先级 | 功能点 | 预估工时 | 前置依赖 | 可演示时间点 |
|--------|--------|----------|----------|-------------|
| P0 | 项目脚手架与基础设施 | 5d | 无 | Week 1 第 5 天 |
| P0 | 数据库模型与 Alembic 迁移 | 2d | 基础设施 | Week 1 第 7 天 |
| P0 | 用户注册/登录（JWT + 组内邮箱） | 3d | 数据库模型 | Week 2 第 3 天 |
| P0 | YAML 流程配置解析引擎 | 4d | 数据库模型 | Week 2 第 7 天 |
| P0 | 动态表单渲染系统（字符串/数值/选择/布尔/文件） | 4d | YAML 解析引擎 | Week 3 第 4 天 |
| P0 | 样本表上传与自动解析（CSV/Excel） | 3d | 动态表单 | Week 3 第 7 天 |
| P0 | Snakemake 本地执行引擎（subprocess） | 4d | 样本表 | Week 4 第 4 天 |
| P0 | 任务目录隔离与文件管理 | 1d | 执行引擎 | Week 4 第 5 天 |
| P0 | 任务数据库模型与 CRUD API | 2d | 用户认证 | Week 4 第 7 天 |
| P1 | 任务列表页面与状态监控 | 3d | 任务 CRUD | Week 5 第 3 天 |
| P1 | WebSocket 日志实时推送 | 3d | 执行引擎 | Week 5 第 6 天 |
| P1 | 进度解析（X of Y steps done） | 2d | WebSocket | Week 5 第 8 天 |
| P1 | 结果文件列表与下载 | 3d | 任务目录 | Week 6 第 3 天 |
| P1 | Docker Compose 一键部署 | 4d | 所有功能 | Week 6 第 7 天 |
| P2 | 初始化脚本（DB/Admin/示例流程） | 2d | Docker | Week 6 第 9 天 |
| P2 | 集成测试与 Bug 修复 | 5d | 全部完成 | Week 7 第 5 天 |

**MVP 总工时：约 46 天（~9 周 person-days，考虑单维护者，日历时间约 5-6 周）**

### 详细功能说明

#### 1. 用户注册/登录（简单实现）

**需求描述**：组内使用，不需要复杂的权限管理。支持邮箱注册、登录、JWT Token 刷新。

**技术实现**：
- FastAPI + `python-jose` + `passlib`
- 邮箱域名白名单限制（如 `@lab.university.edu.cn`）
- 前端 `localStorage` 存储 JWT，Axios 拦截器自动刷新

**API 设计**：
```python
POST /api/v1/auth/register  # 注册（邮箱+密码+姓名）
POST /api/v1/auth/login     # 登录（邮箱+密码）
POST /api/v1/auth/refresh   # 刷新 Token
GET  /api/v1/auth/me        # 获取当前用户信息
```

**预估工时**：3 天

**可演示标准**：可以在前端完成注册和登录，登录后可以看到个人信息。

---

#### 2. RNA-seq 流程的 YAML 配置

**需求描述**：定义一套完整的 RNA-seq 分析流程配置规范，支持动态表单渲染。这是整个平台的核心基石。

**YAML 规范定义**：

```yaml
# /server/workflows/rnaseq.yaml
meta:
  id: rnaseq-v1
  name: "RNA-seq 差异表达分析"
  version: "1.0.0"
  description: "从原始 FASTQ 到差异表达基因的完整 RNA-seq 分析流程"
  category: "转录组学"
  author: "OmicsHub"
  docker_image: "omicshub/rnaseq:1.0"
  entrypoint: "Snakefile"

parameters:
  # === 输入参数 Section ===
  - section: "输入数据"
    description: "原始测序数据与参考基因组"
    collapsed: false
    fields:
      - name: raw_data_dir
        label: "原始数据目录"
        type: string
        required: true
        default: ""
        help: "存放 FASTQ.gz 文件的目录绝对路径"
        placeholder: "/data/raw/rnaseq/"
      
      - name: genome
        label: "参考基因组"
        type: select
        required: true
        options:
          - value: hg38
            label: "人类 (GRCh38/hg38)"
          - value: mm39
            label: "小鼠 (GRCm39/mm39)"
          - value: rn7
            label: "大鼠 (mRatBN7.2/rn7)"
        help: "选择比对参考基因组版本"
      
      - name: annotation
        label: "注释文件"
        type: select
        required: true
        options:
          - value: gencode_v43
            label: "GENCODE v43"
          - value: ensembl_v110
            label: "Ensembl v110"
        help: "基因注释文件版本"
  
  # === 比对参数 Section ===
  - section: "比对参数"
    description: "序列比对工具与参数"
    collapsed: true
    fields:
      - name: aligner
        label: "比对工具"
        type: select
        required: true
        default: "star"
        options:
          - value: star
            label: "STAR（推荐，速度快）"
          - value: hisat2
            label: "HISAT2（内存占用低）"
        help: "选择 reads 比对到参考基因组的工具"
      
      - name: star_threads
        label: "STAR 线程数"
        type: integer
        required: false
        default: 8
        min: 1
        max: 64
        condition:
          field: aligner
          equals: "star"
        help: "STAR 比对使用的 CPU 线程数"
      
      - name: hisat2_threads
        label: "HISAT2 线程数"
        type: integer
        required: false
        default: 8
        min: 1
        max: 64
        condition:
          field: aligner
          equals: "hisat2"
        help: "HISAT2 比对使用的 CPU 线程数"
  
  # === 差异分析参数 Section ===
  - section: "差异表达分析"
    description: "DESeq2 差异分析参数"
    collapsed: false
    fields:
      - name: padj_threshold
        label: "校正 p 值阈值"
        type: float
        required: false
        default: 0.05
        min: 0.001
        max: 1.0
        step: 0.001
        help: "差异表达基因的 BH 校正 p 值阈值"
      
      - name: log2fc_threshold
        label: "log2 倍数变化阈值"
        type: float
        required: false
        default: 1.0
        min: 0.0
        max: 5.0
        step: 0.1
        help: "差异表达基因的 log2(FoldChange) 绝对值阈值"
      
      - name: run_gsea
        label: "执行 GSEA 富集分析"
        type: boolean
        required: false
        default: true
        help: "是否执行基因集富集分析 (GSEA)"

  # === 高级参数 Section ===
  - section: "高级参数"
    description: "通常不需要修改的高级参数"
    collapsed: true
    fields:
      - name: fastp_options
        label: "fastp 附加参数"
        type: string
        required: false
        default: "--detect_adapter_for_pe"
        help: "传递给 fastp 质控工具的附加参数"
      
      - name: save_intermediates
        label: "保存中间文件"
        type: boolean
        required: false
        default: false
        help: "是否保留比对 BAM 等中间文件（占用大量存储空间）"
```

**动态表单渲染规则**：

| 参数类型 | Vue 组件 | 校验规则 | 特殊行为 |
|----------|----------|----------|----------|
| `string` | NInput | 必填校验、正则 | placeholder 提示 |
| `integer` | NInputNumber | min/max 范围 | step 步进 |
| `float` | NInputNumber | min/max、精度 | step 步进 |
| `select` | NSelect | 必选 | 支持 search/filter |
| `boolean` | NSwitch | 无 | 默认开关样式 |
| `file` | NUpload | 文件大小、类型 | 多文件支持 |

**预估工时**：5 天（YAML 规范设计 2d + 解析引擎 1.5d + 前端表单渲染 1.5d）

**可演示标准**：上传 YAML 后可以正确渲染出分组、折叠的表单，各字段类型正确显示。

---

#### 3. 样本表上传与自动解析

**需求描述**：用户上传 CSV/Excel 格式的样本表，系统自动解析列名、校验格式、检测分组信息。

**样本表格式规范**：

```csv
sample_name,fastq_1,fastq_2,group
WT_1,/data/raw/WT_1_R1.fastq.gz,/data/raw/WT_1_R2.fastq.gz,WT
WT_2,/data/raw/WT_2_R1.fastq.gz,/data/raw/WT_2_R2.fastq.gz,WT
KO_1,/data/raw/KO_1_R1.fastq.gz,/data/raw/KO_1_R2.fastq.gz,KO
KO_2,/data/raw/KO_2_R1.fastq.gz,/data/raw/KO_2_R2.fastq.gz,KO
```

**解析逻辑**：
1. 读取 CSV/Excel（pandas）
2. 列名校验（必须有 `sample_name`、`fastq_1`、`group`）
3. 文件路径存在性校验
4. 自动检测分组数量（用于差异分析对比组）
5. 重复样本名检测
6. 预览表格渲染（前端）

**预估工时**：3 天

**可演示标准**：上传样本表 CSV 后，前端显示解析预览，错误行高亮提示。

---

#### 4. 本地 Snakemake 执行模式

**需求描述**：通过 subprocess 调用 Snakemake，实现任务目录隔离、日志捕获、进度解析。

**执行引擎架构**：

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐
│   Frontend   │◄───►│  FastAPI WS  │◄───►│   Snakemake Runner   │
│  (Task Page) │ WS  │  (Celery)    │     │  (subprocess + log)  │
└──────────────┘     └──────────────┘     └──────────────────────┘
                           │                        │
                           ▼                        ▼
                    ┌──────────────┐       ┌──────────────────────┐
                    │  PostgreSQL  │       │  /data/tasks/{id}/   │
                    │  (Task Meta) │       │  (任务目录隔离)       │
                    └──────────────┘       └──────────────────────┘
```

**任务目录结构**：

```
/data/tasks/
└── {task_id}/                    # UUID v4
    ├── config.yaml               # Snakemake 配置文件（自动生成）
    ├── samples.csv               # 样本表（用户上传）
    ├── Snakefile -> /workflows/rnaseq/Snakefile  # 流程文件软链接
    ├── log/
    │   └── snakemake.log         # 完整执行日志
    ├── results/                  # 分析结果输出目录
    │   ├── 01_fastqc/
    │   ├── 02_fastp/
    │   ├── 03_align/
    │   ├── 04_count/
    │   ├── 05_deseq2/
    │   └── 06_gsea/
    └── status.json               # 任务状态文件（实时更新）
```

**执行核心代码**：

```python
# server/core/executor/local.py
import asyncio
import json
import subprocess
from pathlib import Path
from typing import AsyncGenerator

from celery import shared_task
from celery.signals import task_revoked


@shared_task(bind=True)
def run_snakemake_task(self, task_id: str, workflow_id: str, config: dict):
    """
    Celery 任务：执行 Snakemake 流程
    """
    task_dir = Path(f"/data/tasks/{task_id}")
    log_file = task_dir / "log" / "snakemake.log"
    status_file = task_dir / "status.json"
    
    # 更新任务状态为 running
    update_task_status(task_id, "running", progress=0)
    
    # 构建 Snakemake 命令
    cmd = [
        "snakemake",
        "--snakefile", str(task_dir / "Snakefile"),
        "--configfile", str(task_dir / "config.yaml"),
        "--directory", str(task_dir),
        "--cores", str(config.get("threads", 8)),
        "--use-conda",
        "--conda-prefix", "/opt/conda/envs/snakemake",
        "--latency-wait", "60",
        "--keep-going",
        "--rerun-incomplete",
    ]
    
    # 启动 subprocess，实时捕获输出
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    
    # 日志消费循环
    total_steps = estimate_total_steps(workflow_id)
    completed_steps = 0
    
    for line in process.stdout:
        # 写入日志文件
        log_file.write_text(line, append=True)
        
        # 解析进度
        if "Steps done" in line or " of " in line:
            completed_steps = parse_step_progress(line, total_steps)
            progress = int(completed_steps / total_steps * 100)
            update_task_status(task_id, "running", progress=progress)
            
            # 发送 WebSocket 更新
            broadcast_log(task_id, {
                "type": "progress",
                "completed": completed_steps,
                "total": total_steps,
                "progress": progress,
                "line": line.strip(),
            })
        else:
            broadcast_log(task_id, {
                "type": "log",
                "line": line.strip(),
            })
    
    # 等待进程结束
    return_code = process.wait()
    
    if return_code == 0:
        update_task_status(task_id, "completed", progress=100)
        broadcast_log(task_id, {"type": "status", "status": "completed"})
    else:
        update_task_status(task_id, "failed", error=f"Exit code: {return_code}")
        broadcast_log(task_id, {"type": "status", "status": "failed"})


def parse_step_progress(line: str, total: int) -> int:
    """解析 Snakemake 进度输出"""
    # 匹配 "X of Y steps (Z%) done" 或 "Finished job N."
    import re
    
    # Pattern 1: "5 of 23 steps (22%) done"
    match = re.search(r'(\d+)\s+of\s+(\d+)\s+steps', line)
    if match:
        return int(match.group(1))
    
    # Pattern 2: "Finished job N."
    match = re.search(r'Finished job (\d+)\.', line)
    if match:
        return int(match.group(1))
    
    return 0
```

**WebSocket 实时推送**：

```python
# server/api/ws.py
from fastapi import WebSocket, WebSocketDisconnect
from server.core.redis import redis_client

class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
    
    async def connect(self, task_id: str, websocket: WebSocket):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)
    
    def disconnect(self, task_id: str, websocket: WebSocket):
        self.active_connections[task_id].remove(websocket)
    
    async def broadcast(self, task_id: str, message: dict):
        """广播消息到所有关注该任务的客户端"""
        if task_id in self.active_connections:
            for ws in self.active_connections[task_id]:
                await ws.send_json(message)


manager = ConnectionManager()

@router.websocket("/ws/tasks/{task_id}/log")
async def task_log_websocket(websocket: WebSocket, task_id: str):
    await manager.connect(task_id, websocket)
    try:
        while True:
            # 保持连接，等待客户端发送心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(task_id, websocket)
```

**预估工时**：5 天（执行引擎 2d + WebSocket 1.5d + 进度解析 1d + 目录管理 0.5d）

**可演示标准**：提交任务后，前端实时滚动显示 Snakemake 日志，进度条随步骤推进。

---

#### 5. 任务列表与状态监控

**需求描述**：任务的全生命周期管理——创建、查看状态、查看日志、下载结果。

**任务状态机**：

```
        ┌──────────┐
        │ pending  │  提交成功，等待调度
        └────┬─────┘
             │ Celery Worker 接收
             ▼
        ┌──────────┐
   ┌───►│ running  │◄──────┐  正在执行 Snakemake
   │    └────┬─────┘       │
   │         │              │
   │    success          failed (可重试)
   │         │              │
   │         ▼              │
   │    ┌──────────┐        │
   │    │completed │────────┘  执行成功，结果可用
   │    └────┬─────┘
   │         │
   │    failed (不可恢复)
   │         │
   │         ▼
   │    ┌──────────┐
   └───►│  failed  │  执行失败，可查看错误日志
        └──────────┘
```

**API 设计**：

```python
# 任务管理 API
POST   /api/v1/tasks              # 创建任务
GET    /api/v1/tasks              # 任务列表（分页、筛选、排序）
GET    /api/v1/tasks/{id}         # 任务详情
GET    /api/v1/tasks/{id}/log     # 获取任务日志（支持 offset 分页）
GET    /api/v1/tasks/{id}/results # 获取结果文件列表
GET    /api/v1/tasks/{id}/download/{path}  # 下载结果文件
DELETE /api/v1/tasks/{id}         # 删除任务（仅 pending/failed）
```

**前端页面**：

```
┌─────────────────────────────────────────────────────┐
│  OmicsHub                              [用户头像 ▼] │
├────────────┬────────────────────────────────────────┤
│            │  任务管理                              │
│  仪表盘     ├────────────────────────────────────────┤
│  新建任务   │  [+ 新建任务]  [搜索...] [状态 ▼]     │
│  任务列表 ► │                                        │
│  结果浏览   │  ┌──────────────────────────────────┐  │
│            │  │ ■ 任务 #20250106-001             │  │
│            │  │ RNA-seq 差异表达分析               │  │
│            │  │ 状态: ● running  进度: 68%        │  │
│            │  │ 提交: 2025-01-06 14:32            │  │
│            │  │ [查看详情] [查看日志] [取消]      │  │
│            │  └──────────────────────────────────┘  │
│            │                                        │
│            │  ┌──────────────────────────────────┐  │
│            │  │ ■ 任务 #20250105-003             │  │
│            │  │ RNA-seq 差异表达分析               │  │
│            │  │ 状态: ✓ completed  进度: 100%   │  │
│            │  │ 提交: 2025-01-05 09:15            │  │
│            │  │ [查看详情] [查看结果] [下载全部]  │  │
│            │  └──────────────────────────────────┘  │
│            │                                        │
├────────────┤  分页: [1] [2] [3] ... [10]           │
│            │                                        │
└────────────┴────────────────────────────────────────┘
```

**预估工时**：4 天（后端 API 2d + 前端页面 2d）

---

#### 6. Docker Compose 一键部署

**目录结构**：

```
omichub/
├── docker-compose.yml              # 主部署文件
├── docker-compose.override.yml     # 本地开发覆盖
├── .env.example                    # 环境变量模板
├── init/
│   ├── init-db.sql                 # 数据库初始化
│   ├── init-admin.py               # 创建默认管理员
│   └── init-workflows.py           # 导入示例流程
├── server/
│   ├── Dockerfile
│   ├── entrypoint.sh               # 启动脚本（迁移+启动）
│   └── ...
├── web/
│   ├── Dockerfile
│   └── ...
├── nginx/
│   └── nginx.conf                  # 反向代理配置
├── redis/
│   └── redis.conf
└── postgres/
    └── Dockerfile
```

**docker-compose.yml**：

```yaml
version: "3.8"

services:
  web:
    build: ./web
    container_name: omicshub-web
    ports:
      - "80:80"
    depends_on:
      - server
    networks:
      - omicshub-net

  server:
    build: ./server
    container_name: omicshub-server
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@postgres:5432/omicshub
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - SECRET_KEY=${SECRET_KEY:-change-me-in-production}
      - EXECUTION_MODE=local
      - TASK_DATA_DIR=/data/tasks
      - WORKFLOW_DIR=/workflows
    volumes:
      - ${TASK_DATA_HOST:-./data/tasks}:/data/tasks
      - ${WORKFLOW_HOST:-./workflows}:/workflows
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - omicshub-net

  worker:
    build: ./server
    container_name: omicshub-worker
    command: celery -A server.core.celery worker --loglevel=info --concurrency=2
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@postgres:5432/omicshub
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - TASK_DATA_DIR=/data/tasks
      - WORKFLOW_DIR=/workflows
    volumes:
      - ${TASK_DATA_HOST:-./data/tasks}:/data/tasks
      - ${WORKFLOW_HOST:-./workflows}:/workflows
    depends_on:
      - redis
      - postgres
    networks:
      - omicshub-net

  postgres:
    image: postgres:16-alpine
    container_name: omicshub-postgres
    environment:
      - POSTGRES_DB=omicshub
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=${DB_PASSWORD:-postgres}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init/init-db.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - omicshub-net

  redis:
    image: redis:7-alpine
    container_name: omicshub-redis
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - omicshub-net

volumes:
  postgres_data:
  redis_data:

networks:
  omicshub-net:
    driver: bridge
```

**预估工时**：4 天（Dockerfile 编写 1d + Compose 编排 1d + 初始化脚本 1d + 测试调优 1d）

---

### Phase 1 验收标准

| 验收项 | 标准 | 测试方法 |
|--------|------|----------|
| 用户注册/登录 | 组内邮箱可以注册并登录 | 手动测试：注册 → 登录 → 查看用户信息 |
| RNA-seq 任务提交 | 通过 Web 表单完成参数配置并提交 | 手动测试：填写表单 → 上传样本表 → 提交 → 验证 DB |
| 任务正常执行 | Snakemake 能跑完整个流程 | 使用测试数据集（ yeast 或小鼠公开数据）完整跑通 |
| 实时日志查看 | 前端页面实时滚动显示日志，无断连 | 提交任务 → 打开任务详情 → 观察日志实时更新 |
| 进度显示 | 进度条与 Snakemake 步骤同步 | 对比日志中的 "X of Y" 与前端进度条 |
| 结果文件下载 | 可以列出结果文件并下载 | 任务完成后 → 结果页面 → 点击下载 |
| 一键部署 | `docker-compose up -d` 后所有服务正常 | 全新环境执行，验证所有容器 healthy |

### Phase 1 技术债务（允许范围）

| 债务项 | 原因 | 偿还时间 |
|--------|------|----------|
| 用户权限只有 admin/user 两种角色 | 组内使用，不需要 RBAC | Phase 3 |
| 样本表不上传到服务器，只传路径 | MVP 快速实现，无文件存储管理 | Phase 2 |
| YAML 流程硬编码在前端或后端 | 快速实现单流程支持 | Phase 2（流程配置中心） |
| WebSocket 连接不做断线重连 | 组内局域网稳定 | Phase 2 |
| 没有任务取消功能 | Celery revoke 实现复杂度 | Phase 2 |
| 日志不做持久化归档 | 本地存储，任务目录即日志 | Phase 3 |

---

## Phase 2: v0.8 — 平台化扩展

### 目标

从单流程工具升级为真正的多组学分析平台。支持管理员动态上传流程，集成 AI 对话助手和 MCP 服务，提供更丰富的交互体验。

### 开发优先级排序

| 优先级 | 功能点 | 预估工时 | 前置依赖 | 可演示时间点 |
|--------|--------|----------|----------|-------------|
| P0 | 流程 YAML 配置中心（数据库模型 + CRUD API） | 3d | Phase 1 DB | Week 7 第 3 天 |
| P0 | 管理员上传/编辑 YAML 流程（前端） | 2d | CRUD API | Week 7 第 5 天 |
| P0 | YAML 校验引擎（schema 校验 + 语义校验） | 2d | 上传功能 | Week 7 第 7 天 |
| P0 | 多流程切换与动态加载 | 2d | 校验引擎 | Week 8 第 2 天 |
| P0 | 高级动态表单（条件渲染 + 可重复 Group + 折叠 Section） | 4d | 多流程加载 | Week 8 第 6 天 |
| P1 | AI 对话助手（基础版：常驻面板 + 基础问答） | 4d | 无 | Week 9 第 3 天 |
| P1 | MCP Server 注册（管理员后台） | 2d | AI 助手 | Week 9 第 5 天 |
| P1 | MCP 工具调用与结果渲染 | 2d | MCP 注册 | Week 9 第 7 天 |
| P1 | 任务取消功能（Celery revoke + 清理） | 2d | 无 | Week 10 第 2 天 |
| P1 | 任务优先级 + 邮件通知 | 2d | 取消功能 | Week 10 第 4 天 |
| P2 | 集成测试与修复 | 4d | 全部功能 | Week 10 第 8 天 |

**Phase 2 总工时：约 29 天（~6 周 person-days，日历时间约 3-4 周）**

### 详细功能说明

#### 1. 流程 YAML 配置中心

**需求描述**：管理员可以在 Web 界面上传、编辑、管理分析流程 YAML，支持多流程（RNA-seq、ATAC-seq、scRNA-seq 等）。

**数据库设计**：

```python
# server/models/workflow.py
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from server.models.base import BaseModel


class Workflow(BaseModel):
    """分析流程定义"""
    __tablename__ = "workflows"
    
    id = Column(String(32), primary_key=True)           # 如 "rnaseq-v1"
    name = Column(String(128), nullable=False)           # 显示名称
    version = Column(String(16), nullable=False)         # 语义化版本
    description = Column(Text)
    category = Column(String(64), index=True)            # "转录组学"/"表观组学"
    author = Column(String(64), default="OmicsHub")
    
    # YAML 配置内容（完整存储）
    yaml_content = Column(Text, nullable=False)
    
    # 解析后的元数据（冗余存储，加速查询）
    meta_json = Column(JSON)                             # meta 部分
    parameters_schema = Column(JSON)                     # parameters 部分
    docker_image = Column(String(256))
    entrypoint = Column(String(256), default="Snakefile")
    
    # 状态管理
    is_active = Column(Boolean, default=True)
    is_builtin = Column(Boolean, default=False)          # 内置流程不可删除
    
    # 版本控制
    parent_id = Column(String(32), ForeignKey("workflows.id"), nullable=True)
    changelog = Column(Text)
    
    # 统计
    task_count = Column(Integer, default=0)
    
    # 关联
    tasks = relationship("Task", back_populates="workflow")
    versions = relationship("Workflow", backref="parent", remote_side=[id])
```

**API 设计**：

```python
# 流程管理 API（管理员）
POST   /api/v1/admin/workflows              # 上传新流程 YAML
PUT    /api/v1/admin/workflows/{id}         # 编辑流程
POST   /api/v1/admin/workflows/{id}/clone   # 克隆流程（创建新版本）
DELETE /api/v1/admin/workflows/{id}         # 删除流程（仅非内置）
POST   /api/v1/admin/workflows/{id}/validate # 校验 YAML

# 流程浏览 API（普通用户）
GET    /api/v1/workflows                    # 流程列表（支持分类筛选、搜索）
GET    /api/v1/workflows/{id}               # 流程详情
GET    /api/v1/workflows/{id}/parameters    # 获取参数 schema（用于渲染表单）
GET    /api/v1/workflows/{id}/versions      # 获取版本历史
```

**前端页面**：

```
┌────────────────────────────────────────────────────────────┐
│  流程管理（管理员）                                        │
├────────────────────────────────────────────────────────────┤
│  [+ 新建流程]  [搜索...]  [分类 ▼]  [仅显示内置 □]        │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  🔬 RNA-seq 差异表达分析          转录组学 | v1.2.0   │  │
│  │  内置流程 | 任务数: 156 | 最后更新: 2025-01-15        │  │
│  │  [查看参数] [编辑 YAML] [克隆] [查看版本]             │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  🧬 ATAC-seq 染色质可及性分析      表观组学 | v0.9.0  │  │
│  │  用户上传 | 任务数: 23 | 最后更新: 2025-01-20         │  │
│  │  [查看参数] [编辑 YAML] [克隆] [删除] [查看版本]      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  🧪 scRNA-seq 单细胞分析          单细胞组学 | v1.0.0 │  │
│  │  用户上传 | 任务数: 8 | 最后更新: 2025-01-22          │  │
│  │  [查看参数] [编辑 YAML] [克隆] [删除] [查看版本]      │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

**预估工时**：5 天（数据库 1d + API 1.5d + 前端 2d + 版本管理 0.5d）

---

#### 2. YAML 校验引擎

**校验层次**：

```python
# server/core/workflow/validator.py
from pydantic import BaseModel, Field, validator
from typing import Literal, Any
import yaml


class FieldSchema(BaseModel):
    """参数字段 schema 校验"""
    name: str = Field(..., regex=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    label: str
    type: Literal['string', 'integer', 'float', 'select', 'boolean', 'file', 'group']
    required: bool = True
    default: Any = None
    help: str = ""
    placeholder: str = ""
    
    # 条件渲染
    condition: dict | None = None  # {field: str, equals: Any}
    
    # 数值范围
    min: float | None = None
    max: float | None = None
    step: float | None = None
    
    # select 选项
    options: list[dict] | None = None  # [{value, label}]
    
    # group（可重复组）
    repeatable: bool = False
    fields: list['FieldSchema'] | None = None  # 嵌套字段


class ParameterSection(BaseModel):
    """参数分组 Section 校验"""
    section: str
    description: str = ""
    collapsed: bool = False
    fields: list[FieldSchema]


class WorkflowMeta(BaseModel):
    """Meta 部分校验"""
    id: str = Field(..., regex=r'^[a-z0-9-]+$')
    name: str
    version: str = Field(..., regex=r'^\d+\.\d+\.\d+$')
    description: str
    category: str
    docker_image: str | None = None
    entrypoint: str = "Snakefile"


class WorkflowSchema(BaseModel):
    """完整 YAML 校验"""
    meta: WorkflowMeta
    parameters: list[ParameterSection]
    
    @validator('parameters')
    def check_unique_field_names(cls, v):
        """检查字段名全局唯一"""
        names = set()
        for section in v:
            for field in section.fields:
                if field.name in names:
                    raise ValueError(f"Duplicate field name: {field.name}")
                names.add(field.name)
        return v


def validate_workflow_yaml(yaml_content: str) -> tuple[bool, list[str]]:
    """
    校验 YAML 流程配置
    返回: (是否通过, 错误信息列表)
    """
    errors = []
    
    # Layer 1: YAML 语法校验
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return False, [f"YAML 语法错误: {e}"]
    
    # Layer 2: Schema 结构校验
    try:
        WorkflowSchema(**data)
    except Exception as e:
        return False, [f"Schema 校验失败: {e}"]
    
    # Layer 3: 语义校验
    meta = data.get('meta', {})
    params = data.get('parameters', [])
    
    # 3.1 检查 condition 引用的字段存在
    for section in params:
        for field in section.get('fields', []):
            if condition := field.get('condition'):
                ref_field = condition.get('field')
                if not any(f['name'] == ref_field 
                          for s in params 
                          for f in s.get('fields', [])):
                    errors.append(f"条件渲染引用了不存在的字段: {ref_field}")
    
    # 3.2 检查 select 选项非空
    for section in params:
        for field in section.get('fields', []):
            if field.get('type') == 'select' and not field.get('options'):
                errors.append(f"Select 字段 {field['name']} 缺少 options")
    
    # 3.3 检查 docker_image 格式（如果提供）
    if docker_image := meta.get('docker_image'):
        if ':' not in docker_image:
            errors.append(f"docker_image 应包含 tag: {docker_image}")
    
    return len(errors) == 0, errors
```

**预估工时**：3 天

---

#### 3. 高级动态表单

**条件渲染实现**：

```vue
<!-- web/components/DynamicForm.vue -->
<script setup lang="ts">
import { computed, watch } from 'vue'
import type { FieldSchema, FormValues } from '@/types/workflow'

interface Props {
  schema: FieldSchema[]
  modelValue: FormValues
}

const props = defineProps<Props>()
const emit = defineEmits<['update:modelValue']>()

// 计算字段可见性
const isFieldVisible = (field: FieldSchema): boolean => {
  if (!field.condition) return true
  const { field: refField, equals } = field.condition
  return props.modelValue[refField] === equals
}

// 当条件字段变化时，重置被隐藏字段的值
watch(() => props.modelValue, (newVal, oldVal) => {
  for (const field of props.schema) {
    if (field.condition && !isFieldVisible(field)) {
      emit('update:modelValue', {
        ...props.modelValue,
        [field.name]: field.default ?? null
      })
    }
  }
}, { deep: true })
</script>

<template>
  <div class="dynamic-form">
    <template v-for="field in schema" :key="field.name">
      <n-form-item
        v-if="isFieldVisible(field)"
        :label="field.label"
        :path="field.name"
        :required="field.required"
      >
        <!-- String -->
        <n-input
          v-if="field.type === 'string'"
          v-model:value="modelValue[field.name]"
          :placeholder="field.placeholder"
        />
        
        <!-- Integer / Float -->
        <n-input-number
          v-else-if="field.type === 'integer' || field.type === 'float'"
          v-model:value="modelValue[field.name]"
          :min="field.min"
          :max="field.max"
          :step="field.step"
          :precision="field.type === 'float' ? 2 : 0"
        />
        
        <!-- Select -->
        <n-select
          v-else-if="field.type === 'select'"
          v-model:value="modelValue[field.name]"
          :options="field.options?.map(o => ({ label: o.label, value: o.value }))"
          filterable
        />
        
        <!-- Boolean -->
        <n-switch
          v-else-if="field.type === 'boolean'"
          v-model:value="modelValue[field.name]"
        />
        
        <!-- File Upload -->
        <n-upload
          v-else-if="field.type === 'file'"
          v-model:file-list="modelValue[field.name]"
          :max="field.repeatable ? undefined : 1"
        />
        
        <!-- Repeatable Group -->
        <RepeatableGroup
          v-else-if="field.type === 'group' && field.repeatable"
          v-model="modelValue[field.name]"
          :fields="field.fields"
        />
        
        <!-- Help tooltip -->
        <template #feedback v-if="field.help">
          <n-tooltip>
            <template #trigger>
              <n-icon :component="HelpCircleOutline" />
            </template>
            {{ field.help }}
          </n-tooltip>
        </template>
      </n-form-item>
    </template>
  </div>
</template>
```

**可重复 Group 组件**：

```vue
<!-- web/components/RepeatableGroup.vue -->
<script setup lang="ts">
interface Props {
  modelValue: Record<string, any>[]
  fields: FieldSchema[]
}

const props = defineProps<Props>()
const emit = defineEmits<['update:modelValue']>()

const addGroup = () => {
  const newItem: Record<string, any> = {}
  for (const field of props.fields) {
    newItem[field.name] = field.default ?? null
  }
  emit('update:modelValue', [...props.modelValue, newItem])
}

const removeGroup = (index: number) => {
  const newValue = [...props.modelValue]
  newValue.splice(index, 1)
  emit('update:modelValue', newValue)
}
</script>

<template>
  <div class="repeatable-group">
    <n-card
      v-for="(item, index) in modelValue"
      :key="index"
      :title="`对比组 ${index + 1}`"
      closable
      @close="removeGroup(index)"
    >
      <DynamicForm
        :schema="fields"
        v-model="modelValue[index]"
      />
    </n-card>
    
    <n-button dashed @click="addGroup" block>
      <template #icon><n-icon :component="AddOutline" /></template>
      添加对比组
    </n-button>
  </div>
</template>
```

**预估工时**：4 天

---

#### 4. AI 对话助手（基础版）

**需求描述**：常驻右侧边栏的 AI 对话面板，支持基础问答、流程选择建议、参数解释。

**架构设计**：

```
┌──────────────────────────────────────────────────────────────┐
│  OmicsHub                                        [AI助手 ▶] │
├───────────────────────────────┬──────────────────────────────┤
│                               │  🤖 OmicsHub AI 助手         │
│  主内容区                      ├──────────────────────────────┤
│  （表单/任务列表等）             │                              │
│                               │  AI: 你好！我是 OmicsHub     │
│                               │  AI 助手，可以帮你：          │
│                               │  • 选择合适的分析流程         │
│                               │  • 解释参数含义               │
│                               │  • 分析结果解读               │
│                               │                              │
│                               │  ────────────────────────    │
│                               │  你: RNA-seq 和 scRNA-seq    │
│                               │  有什么区别？                 │
│                               │                              │
│                               │  AI: 两者的主要区别在于...    │
│                               │  [关键区别: 1. 样本处理 ...]  │
│                               │                              │
│                               ├──────────────────────────────┤
│                               │  [🎤] [输入问题...     ] [↑] │
│                               │  [📎 附件]                   │
└───────────────────────────────┴──────────────────────────────┘
```

**后端实现**：

```python
# server/api/ai.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/ai")


class ChatRequest(BaseModel):
    message: str
    context: dict | None = None  # 当前页面上下文
    history: list[dict] = []     # 对话历史


class ChatResponse(BaseModel):
    reply: str
    suggested_actions: list[dict] | None = None


@router.post("/chat", response_model=ChatResponse)
async def ai_chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    AI 对话接口
    支持上下文感知和基础问答
    """
    # 构建系统提示词
    system_prompt = build_system_prompt(request.context)
    
    # 构建消息列表
    messages = [
        {"role": "system", "content": system_prompt},
        *request.history[-10:],  # 保留最近 10 轮
        {"role": "user", "content": request.message},
    ]
    
    # 调用 LLM
    reply = await call_llm(messages)
    
    # 解析建议操作
    suggested_actions = parse_suggested_actions(reply)
    
    return ChatResponse(
        reply=reply,
        suggested_actions=suggested_actions,
    )


def build_system_prompt(context: dict | None) -> str:
    """根据上下文构建系统提示词"""
    base_prompt = """你是 OmicsHub 的 AI 助手，一个专业的生物信息学分析平台助手。
    
你可以帮助用户：
1. 选择合适的分析流程（RNA-seq、ATAC-seq、scRNA-seq 等）
2. 解释各流程参数的含义和推荐设置
3. 解读分析结果（差异表达基因、富集分析等）
4. 推荐下游分析策略
5. 解答生物信息学常见问题

回答原则：
- 专业但易懂，假设用户有生物学背景但编程经验有限
- 参数推荐要给出具体数值和理由
- 涉及统计方法时简要说明假设条件
"""
    
    if context:
        page = context.get('page')
        if page == 'workflow_submit':
            workflow_id = context.get('workflow_id')
            base_prompt += f"\n当前用户正在提交 {workflow_id} 流程任务。"
            base_prompt += "可以帮助用户理解参数含义和推荐设置。"
        elif page == 'task_detail':
            task_id = context.get('task_id')
            base_prompt += f"\n当前用户正在查看任务 {task_id} 的详情。"
            base_prompt += "可以帮助解读分析结果或排查问题。"
    
    return base_prompt
```

**预估工时**：4 天（后端 API 1d + LLM 集成 1d + 前端面板 1.5d + 提示词调优 0.5d）

---

#### 5. MCP 服务集成（基础版）

**MCP (Model Context Protocol) 集成**：让 AI 助手可以调用外部工具（如 PubMed 文献检索）。

**MCP Server 注册**：

```python
# server/models/mcp.py
class MCPServer(BaseModel):
    """MCP Server 配置"""
    __tablename__ = "mcp_servers"
    
    id = Column(String(32), primary_key=True)
    name = Column(String(64), nullable=False)
    description = Column(Text)
    
    # 连接配置
    transport: Literal["stdio", "sse", "http"] = Column(String(16))
    command: str | None = Column(String(256))  # stdio 模式命令
    args: list[str] = Column(JSON, default=list)
    url: str | None = Column(String(256))      # sse/http 模式 URL
    
    # 认证
    auth_type: str | None = Column(String(32))
    auth_config: dict = Column(JSON, default=dict)
    
    # 状态
    is_active = Column(Boolean, default=True)
    last_connected_at = Column(DateTime, nullable=True)
    
    # 可用工具（运行时缓存）
    tools: list[dict] = Column(JSON, default=list)
```

**PubMed MCP Server 示例**：

```python
# server/core/mcp/servers/pubmed.py
class PubMedMCPServer:
    """PubMed 文献检索 MCP Server"""
    
    def __init__(self):
        self.name = "pubmed-search"
        self.description = "搜索 PubMed 生物医学文献数据库"
    
    def get_tools(self) -> list[dict]:
        return [
            {
                "name": "search_pubmed",
                "description": "使用关键词搜索 PubMed 文献",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "PubMed 搜索查询词"
                        },
                        "max_results": {
                            "type": "integer",
                            "default": 10,
                            "description": "返回的最大结果数"
                        },
                        "sort": {
                            "type": "string",
                            "enum": ["relevance", "date"],
                            "default": "relevance"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_article_details",
                "description": "获取指定 PMID 的文献详细信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pmid": {
                            "type": "string",
                            "description": "PubMed ID"
                        }
                    },
                    "required": ["pmid"]
                }
            }
        ]
    
    async def execute(self, tool_name: str, params: dict) -> dict:
        if tool_name == "search_pubmed":
            return await self._search(params)
        elif tool_name == "get_article_details":
            return await self._get_details(params)
        raise ValueError(f"Unknown tool: {tool_name}")
    
    async def _search(self, params: dict) -> dict:
        """调用 NCBI E-utilities API"""
        import aiohttp
        
        query = params["query"]
        max_results = params.get("max_results", 10)
        
        # ESearch
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params={
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": params.get("sort", "relevance")
            }) as resp:
                data = await resp.json()
                pmids = data["esearchresult"]["idlist"]
                
        return {
            "count": data["esearchresult"]["count"],
            "pmids": pmids,
            "query_translation": data["esearchresult"].get("querytranslation", "")
        }
```

**预估工时**：4 天（MCP Server 框架 1.5d + PubMed 接入 1d + 管理员页面 1d + 前端渲染 0.5d）

---

#### 6. 任务管理增强

**任务取消实现**：

```python
# server/api/tasks.py
@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """取消任务"""
    task = await Task.get_by_id(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    
    # 只有 pending 或 running 的任务可以取消
    if task.status not in ["pending", "running"]:
        raise HTTPException(400, f"Cannot cancel task with status {task.status}")
    
    # Celery revoke
    if task.celery_task_id:
        from celery import Celery
        celery_app = Celery('omicshub')
        celery_app.control.revoke(task.celery_task_id, terminate=True)
    
    # 终止 subprocess（如果是本地执行）
    if task.execution_mode == "local" and task.pid:
        import os, signal
        try:
            os.kill(task.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    
    # 更新状态
    await task.update(status="cancelled", ended_at=datetime.utcnow())
    
    # 清理资源（异步）
    from server.core.cleanup import cleanup_task_resources
    cleanup_task_resources.delay(task_id)
    
    return {"message": "Task cancelled successfully"}
```

**邮件通知**（使用 Celery beat 定时任务）：

```python
# server/core/notifications/email.py
from celery import shared_task
from server.core.email import send_email

@shared_task
def send_task_notification(task_id: str, event: str):
    """发送任务状态通知邮件"""
    task = Task.get_by_id(task_id)
    user = User.get_by_id(task.user_id)
    
    subject_map = {
        "completed": f"[OmicsHub] 任务 #{task.id} 已完成",
        "failed": f"[OmicsHub] 任务 #{task.id} 执行失败",
        "cancelled": f"[OmicsHub] 任务 #{task.id} 已取消",
    }
    
    template_map = {
        "completed": "task_completed.html",
        "failed": "task_failed.html",
        "cancelled": "task_cancelled.html",
    }
    
    send_email(
        to=user.email,
        subject=subject_map.get(event, f"[OmicsHub] 任务 #{task.id} 状态更新"),
        template=template_map.get(event),
        context={
            "user_name": user.name,
            "task_id": task.id,
            "task_name": task.name,
            "workflow_name": task.workflow_name,
            "detail_url": f"{settings.FRONTEND_URL}/tasks/{task.id}",
        }
    )
```

**预估工时**：3 天（取消功能 1.5d + 优先级 0.5d + 邮件通知 1d）

### Phase 2 验收标准

| 验收项 | 标准 | 测试方法 |
|--------|------|----------|
| 流程上传 | 管理员可以上传新 YAML 流程 | 上传 ATAC-seq YAML → 前端正确渲染表单 → 可提交任务 |
| YAML 校验 | 错误 YAML 给出明确错误信息 | 上传缺少必填字段的 YAML → 看到具体错误提示 |
| 条件渲染 | 参数联动正常工作 | 选择不同 aligner → 只显示对应线程数参数 |
| 可重复 Group | 可以动态添加/删除对比组 | 差异分析页面添加多个对比组 → 提交验证参数结构 |
| AI 对话 | AI 可以回答流程相关问题 | 提问 "RNA-seq 用什么比对器好" → 得到有意义的回答 |
| MCP PubMed | 可以通过 AI 查询 PubMed | 提问 "搜索 p53 相关文献" → 返回文献列表 |
| 任务取消 | 可以取消正在运行的任务 | 提交任务 → 点击取消 → 状态变为 cancelled |
| 邮件通知 | 任务完成时收到邮件 | 提交短任务 → 完成后检查邮箱 |

### Phase 2 技术债务

| 债务项 | 原因 | 偿还时间 |
|--------|------|----------|
| AI 对话不做持久化存储 | Phase 3 增强时再完善 | Phase 3 |
| MCP Server 只有 PubMed | 先验证架构可行性 | Phase 3 |
| 不做复杂的用户权限 | 仅 admin/user 角色 | Phase 3 |
| 邮件使用同步发送 | Celery 异步足够 | Phase 3 |

---

## Phase 3: v1.0 — 生产就绪

### 目标

平台达到生产环境部署标准。支持远程执行模式、结果可视化、AI 工具调用、完整管理后台和安全加固。

### 开发优先级排序

| 优先级 | 功能点 | 预估工时 | 前置依赖 | 可演示时间点 |
|--------|--------|----------|----------|-------------|
| P0 | 远程执行模式（Master 节点 FastAPI Executor） | 4d | Phase 2 | Week 11 第 4 天 |
| P0 | Web 与 Master 分离部署 + HTTP API | 2d | Executor | Week 11 第 6 天 |
| P0 | WebSocket 日志流（跨节点） | 2d | HTTP API | Week 11 第 8 天 |
| P0 | EXECUTION_MODE 环境变量切换 | 1d | 远程日志 | Week 12 第 1 天 |
| P0 | 结果可视化（差异表达表格 + 火山图 + 热图） | 4d | 远程模式 | Week 12 第 5 天 |
| P0 | UMAP/t-SNE（scRNA-seq） | 2d | ECharts | Week 12 第 7 天 |
| P1 | 项目管理（项目-样本层级） | 3d | 无 | Week 13 第 2 天 |
| P1 | 批量样本上传与校验 | 2d | 项目管理 | Week 13 第 4 天 |
| P1 | AI 工具调用（提交任务、查询样本） | 3d | Phase 2 AI | Week 13 第 7 天 |
| P1 | 确认机制（草稿 → 用户确认 → 执行） | 2d | 工具调用 | Week 14 第 2 天 |
| P1 | 管理后台（用户/MCP/监控） | 3d | 无 | Week 14 第 5 天 |
| P2 | 安全加固（文件隔离、IP 白名单） | 2d | 管理后台 | Week 14 第 7 天 |
| P2 | 完整文档 | 3d | 全部功能 | Week 15 第 3 天 |
| P2 | 生产环境部署与压测 | 3d | 文档 | Week 15 第 6 天 |

**Phase 3 总工时：约 38 天（~7.5 周 person-days，日历时间约 3-4 周）**

### 详细功能说明

#### 1. 远程执行模式（Remote Mode）

**架构设计**：

```
┌─────────────────────────────────────────────────────────────────┐
│                          远程模式架构                             │
│                                                                 │
│  ┌──────────────┐         HTTP API + WS        ┌──────────────┐ │
│  │  Web 节点     │◄────────────────────────────►│ Master 节点   │ │
│  │  (FastAPI)    │    任务提交/状态查询/日志流    │  (Executor)  │ │
│  │              │                              │              │ │
│  │  - REST API  │                              │  - 任务调度   │ │
│  │  - WebSocket │                              │  - Snakemake │ │
│  │  - 结果存储   │                              │    执行      │ │
│  │  - 数据库    │                              │  - 日志转发   │ │
│  │              │                              │  - 结果回调   │ │
│  └──────────────┘                              └──────────────┘ │
│         │                                              │        │
│         │         ┌──────────────┐                    │        │
│         └────────►│  PostgreSQL  │◄───────────────────┘        │
│                   │    Redis     │    共享状态存储                │
│                   └──────────────┘                             │
│                                                                 │
│  EXECUTION_MODE=remote                                         │
└─────────────────────────────────────────────────────────────────┘
```

**Master 节点 Executor Service**：

```python
# executor-service/main.py (独立 FastAPI 应用)
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse

app = FastAPI(title="OmicsHub Executor Service")


@app.post("/execute")
async def execute_task(request: ExecuteRequest):
    """
    接收任务执行请求
    """
    task_dir = prepare_task_directory(request.task_id)
    
    # 下载任务配置
    await download_task_config(request.task_id, task_dir)
    
    # 启动 Snakemake
    process = await start_snakemake(
        task_dir=task_dir,
        config=request.config,
        cores=request.cores,
    )
    
    # 返回任务 PID
    return JSONResponse({
        "task_id": request.task_id,
        "pid": process.pid,
        "status": "started",
    })


@app.websocket("/ws/log/{task_id}")
async def log_websocket(websocket: WebSocket, task_id: str):
    """
    WebSocket 日志流：将 Snakemake 日志实时转发给 Web 节点
    """
    await websocket.accept()
    
    # 订阅 Redis 日志频道
    async for message in redis.subscribe(f"task:{task_id}:log"):
        await websocket.send_json(message)


@app.post("/cancel/{task_id}")
async def cancel_task(task_id: str):
    """取消任务"""
    process = running_tasks.get(task_id)
    if process:
        process.terminate()
        return {"status": "cancelled"}
    return {"status": "not_found"}


@app.post("/callback/complete")
async def task_complete_callback(request: CompleteCallback):
    """
    任务完成回调：Master 节点通知 Web 节点
    """
    # 验证回调签名
    verify_callback_signature(request)
    
    # 更新任务状态
    await update_task_status(
        task_id=request.task_id,
        status="completed",
        results=request.results,
    )
    
    # 触发通知
    await send_notification(request.task_id, "completed")
    
    return {"status": "ok"}
```

**执行模式切换**：

```python
# server/core/executor/factory.py
from server.config import settings

class ExecutorFactory:
    @staticmethod
    def get_executor():
        if settings.EXECUTION_MODE == "local":
            from .local import LocalExecutor
            return LocalExecutor()
        elif settings.EXECUTION_MODE == "remote":
            from .remote import RemoteExecutor
            return RemoteExecutor(
                master_url=settings.MASTER_URL,
                api_key=settings.MASTER_API_KEY,
            )
        else:
            raise ValueError(f"Unknown execution mode: {settings.EXECUTION_MODE}")
```

**预估工时**：5 天（Executor Service 2d + Web-Master 通信 1.5d + WS 日志流 1d + 环境切换 0.5d）

---

#### 2. 结果可视化

**差异表达表格预览**：

```vue
<!-- web/components/results/DEGTable.vue -->
<template>
  <n-data-table
    :columns="columns"
    :data="degData"
    :pagination="pagination"
    :row-key="row => row.gene_id"
    @update:filters="handleFilterChange"
  />
</template>

<script setup>
const columns = [
  { title: 'Gene ID', key: 'gene_id', sorter: 'default', filter: true },
  { title: 'Gene Name', key: 'gene_name', filter: true },
  { title: 'Base Mean', key: 'baseMean', sorter: 'default' },
  { title: 'log2FoldChange', key: 'log2FoldChange', sorter: 'default' },
  { title: 'pvalue', key: 'pvalue', sorter: 'default' },
  { 
    title: 'padj', 
    key: 'padj', 
    sorter: 'default',
    render(row) {
      return h('span', {
        style: { color: row.padj < 0.05 ? '#18a058' : '#999' }
      }, row.padj?.toExponential(2) || 'NA')
    }
  },
  {
    title: 'Significant',
    key: 'significant',
    render(row) {
      if (row.padj < 0.05 && Math.abs(row.log2FoldChange) >= 1) {
        return h(NTag, { type: 'success' }, () => 'Yes')
      }
      return h(NTag, { type: 'default' }, () => 'No')
    }
  }
]
</script>
```

**火山图（ECharts）**：

```vue
<!-- web/components/results/VolcanoPlot.vue -->
<template>
  <v-chart class="chart" :option="option" autoresize />
</template>

<script setup>
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

const props = defineProps({ degData: Array })

const option = computed(() => {
  const up = props.degData.filter(d => d.padj < 0.05 && d.log2FoldChange > 1)
  const down = props.degData.filter(d => d.padj < 0.05 && d.log2FoldChange < -1)
  const ns = props.degData.filter(d => d.padj >= 0.05 || Math.abs(d.log2FoldChange) < 1)
  
  return {
    title: { text: 'Volcano Plot', subtext: `${up.length} up / ${down.length} down` },
    xAxis: { 
      name: 'log2(FoldChange)', 
      nameLocation: 'center',
      nameGap: 30 
    },
    yAxis: { 
      name: '-log10(padj)', 
      nameLocation: 'center',
      nameGap: 40 
    },
    tooltip: {
      formatter: (params) => {
        const d = params.data
        return `${d.gene_name}<br/>log2FC: ${d.log2FoldChange.toFixed(2)}<br/>padj: ${d.padj.toExponential(2)}`
      }
    },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    series: [
      {
        name: 'Up-regulated',
        type: 'scatter',
        data: up.map(d => ({ ...d, value: [d.log2FoldChange, -Math.log10(d.padj)] })),
        itemStyle: { color: '#d03050' },
        symbolSize: 6,
      },
      {
        name: 'Down-regulated',
        type: 'scatter',
        data: down.map(d => ({ ...d, value: [d.log2FoldChange, -Math.log10(d.padj)] })),
        itemStyle: { color: '#18a058' },
        symbolSize: 6,
      },
      {
        name: 'Not significant',
        type: 'scatter',
        data: ns.map(d => ({ ...d, value: [d.log2FoldChange, -Math.log10(d.padj)] })),
        itemStyle: { color: '#999999', opacity: 0.5 },
        symbolSize: 3,
      }
    ],
    legend: { data: ['Up-regulated', 'Down-regulated', 'Not significant'] }
  }
})
</script>
```

**UMAP/t-SNE（scRNA-seq）**：

```vue
<!-- web/components/results/UmapPlot.vue -->
<script setup>
// 使用 ECharts 散点图 + 不同颜色表示 cluster
data: umapData.map(d => ({
  value: [d.UMAP_1, d.UMAP_2],
  cluster: d.cluster,
  cell_type: d.cell_type,
  n_genes: d.n_genes
})),
itemStyle: {
  color: (params) => clusterColors[params.data.cluster]
}
</script>
```

**预估工时**：5 天（差异表达表格 1d + 火山图 1.5d + 热图 1.5d + UMAP/t-SNE 1d）

---

#### 3. AI 工具调用增强

**工具协议定义**：

```python
# server/core/ai/tools/registry.py
class AIToolRegistry:
    """AI 可用工具注册表"""
    
    TOOLS = [
        {
            "name": "submit_task",
            "description": "提交一个分析任务到 OmicsHub",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "流程 ID"},
                    "task_name": {"type": "string"},
                    "parameters": {"type": "object", "description": "流程参数"},
                    "samples": {"type": "array", "description": "样本表数据"}
                },
                "required": ["workflow_id", "parameters", "samples"]
            }
        },
        {
            "name": "query_tasks",
            "description": "查询当前用户的任务列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "running", "completed", "failed"]},
                    "limit": {"type": "integer", "default": 10}
                }
            }
        },
        {
            "name": "get_task_results",
            "description": "获取任务的分析结果",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"}
                },
                "required": ["task_id"]
            }
        },
        {
            "name": "search_workflows",
            "description": "搜索可用的分析流程",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "keyword": {"type": "string"}
                }
            }
        },
        {
            "name": "query_pubmed",
            "description": "搜索 PubMed 文献",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        }
    ]
```

**确认机制流程**：

```
用户: "帮我提交一个 RNA-seq 任务，对比 WT 和 KO 组"

AI: 
  1. 调用 search_workflows → 找到 rnaseq-v1
  2. 调用 submit_task（草稿模式，不真正提交）
  
AI → 用户:
  "我已为你准备好任务草稿，请确认：
  
  📋 任务草稿
  流程: RNA-seq 差异表达分析 (rnaseq-v1)
  样本: 4 个 (WT: 2, KO: 2)
  比对: STAR (hg38)
  参数: padj=0.05, log2FC=1.0
  
  [确认提交]  [修改参数]  [取消]"

用户: "确认提交"

AI:
  1. 真正调用 submit_task
  2. 返回任务 ID
  
AI → 用户:
  "✅ 任务已提交！任务 ID: #20250201-001
  你可以在任务列表页面查看进度。"
```

**预估工时**：5 天（工具注册 1.5d + 调用实现 1.5d + 确认机制 UI 1.5d + 测试调优 0.5d）

---

#### 4. 管理后台

```
┌──────────────────────────────────────────────────────────────┐
│  管理后台                                                     │
├──────────────┬───────────────────────────────────────────────┤
│              │                                               │
│  📊 概览     │  系统概览                                      │
│  👥 用户管理  │  ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  🔧 流程管理  │  │ 用户 15 │ │ 任务 156│ │ 流程 8  │       │
│  🔌 MCP管理  │  └─────────┘ └─────────┘ └─────────┘       │
│  📈 监控     │                                               │
│  ⚙️ 设置     │  ┌─────────────────────────────────────────┐  │
│              │  │ 任务趋势 (近30天)                        │  │
│              │  │                                         │  │
│              │  │  ▲ 完成  ████████████  142              │  │
│              │  │  │ 失败  ██              8              │  │
│              │  │  │ 取消  █               6              │  │
│              │  │  └───────────────────────────────        │  │
│              │  └─────────────────────────────────────────┘  │
│              │                                               │
├──────────────┤  ┌─────────────────────────────────────────┐  │
│              │  │ 最近任务                                  │  │
│              │  │ #20250201-005 ✓ completed  2分钟前      │  │
│              │  │ #20250201-004 ✗ failed     15分钟前     │  │
│              │  │ #20250201-003 ✓ completed  1小时前      │  │
│              │  └─────────────────────────────────────────┘  │
│              │                                               │
└──────────────┴───────────────────────────────────────────────┘
```

**Flower 集成（Celery 监控）**：

```yaml
# docker-compose.yml (追加)
  flower:
    image: mher/flower:latest
    container_name: omicshub-flower
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/1
      - FLOWER_BASIC_AUTH=${FLOWER_AUTH:-admin:admin}
    ports:
      - "5555:5555"
    depends_on:
      - redis
    networks:
      - omicshub-net
```

**预估工时**：3 天

---

#### 5. 安全与运维

**文件系统隔离**：

```python
# server/core/security/isolation.py
import os
from pathlib import Path

class TaskDirectoryIsolator:
    """任务目录隔离器"""
    
    BASE_DIR = Path("/data/tasks")
    ALLOWED_PREFIXES = ["/data/raw/", "/data/ref/", "/data/public/"]
    
    @classmethod
    def create_task_dir(cls, task_id: str) -> Path:
        """创建隔离的任务目录"""
        task_dir = cls.BASE_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建子目录
        for subdir in ["log", "results", "temp"]:
            (task_dir / subdir).mkdir(exist_ok=True)
        
        return task_dir
    
    @classmethod
    def validate_path(cls, path: str) -> bool:
        """校验文件路径是否在允许范围内"""
        resolved = Path(path).resolve()
        return any(
            str(resolved).startswith(prefix)
            for prefix in cls.ALLOWED_PREFIXES
        )
    
    @classmethod
    def cleanup_task_dir(cls, task_id: str):
        """清理任务目录"""
        import shutil
        task_dir = cls.BASE_DIR / task_id
        if task_dir.exists():
            shutil.rmtree(task_dir)
```

**回调接口安全**：

```python
# server/api/callback.py
import hmac
import hashlib
from fastapi import Header, HTTPException

async def verify_callback(
    request: Request,
    x_signature: str = Header(None),
    x_task_id: str = Header(None),
):
    """验证回调请求签名"""
    if not x_signature:
        raise HTTPException(401, "Missing signature")
    
    # IP 白名单校验
    client_ip = request.client.host
    if client_ip not in settings.MASTER_IP_WHITELIST:
        raise HTTPException(403, "IP not whitelisted")
    
    # HMAC 签名校验
    body = await request.body()
    expected = hmac.new(
        settings.CALLBACK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(401, "Invalid signature")
```

**预估工时**：3 天（文件隔离 1d + 回调安全 0.5d + 文档 1.5d）

### Phase 3 验收标准

| 验收项 | 标准 | 测试方法 |
|--------|------|----------|
| 远程模式切换 | `EXECUTION_MODE=remote` 正常执行 | 设置环境变量 → 提交任务 → 在 Master 节点看到执行 |
| Web-Master 分离 | Web 和 Master 可以独立部署 | 分别启动两个服务 → 任务正常提交和回调 |
| 火山图渲染 | 差异基因正确分类显示 | 打开 completed 任务 → 火山图红绿点分布合理 |
| 热图渲染 | 聚类热图正确显示 | 查看热图 → 样本按分组聚类 |
| AI 提交任务 | AI 可以辅助提交任务（带确认） | 对话 "帮我提交 RNA-seq 任务" → 看到草稿 → 确认 → 成功提交 |
| 管理后台 | 用户/MCP/监控页面正常 | 登录管理员 → 各管理页面功能正常 |
| 文件隔离 | 任务只能访问自己的目录 | 尝试跨目录访问 → 被拒绝 |
| 文档完整 | 部署/使用/API 文档齐全 | 检查文档覆盖度 |

### Phase 3 技术债务

| 债务项 | 原因 | 偿还时间 |
|--------|------|----------|
| 不做分布式任务队列（只用单 Celery Worker） | 组内使用量可控 | v1.1 |
| 不做高级缓存策略 | Redis 基础缓存足够 | v1.1 |
| AI 对话历史只保留最近 30 天 | 存储限制 | v1.1 |
| 结果可视化只有基础图表 | 满足核心需求 | v1.1 |

---

## 风险与应对

### 风险矩阵

| 阶段 | 风险类别 | 风险描述 | 可能性 | 影响 | 应对策略 |
|------|----------|----------|--------|------|----------|
| P1 | 技术风险 | Snakemake 进度解析不准确 | 中 | 中 | 多模式解析（正则匹配多种输出格式）+ 兜底方案（按时间估算） |
| P1 | 技术风险 | WebSocket 连接不稳定 | 低 | 中 | 实现自动重连机制（指数退避）+ 日志 fallback 到轮询 |
| P1 | 资源风险 | 维护者时间不足（课程/实验冲突） | 高 | 高 | 功能严格按优先级排序，P0 必须完成，P1/P2 可裁剪 |
| P1 | 依赖风险 | Snakemake 与 Conda 环境兼容性 | 中 | 高 | Docker 镜像锁定版本 + 预构建 Conda 环境 |
| P1 | 依赖风险 | Naive UI 组件不满足需求 | 低 | 中 | 预留自定义组件开发时间，或引入 Element Plus 补充 |
| P2 | 技术风险 | AI 对话质量不稳定 | 中 | 中 | 设计好 fallback 机制（无法回答时引导用户查看文档） |
| P2 | 技术风险 | MCP Server 协议变更 | 低 | 中 | 抽象 MCP 层，协议变更时只改适配器 |
| P2 | 资源风险 | 高级动态表单开发复杂 | 中 | 中 | 条件渲染优先，可重复 Group 次之，折叠 Section 最后 |
| P3 | 技术风险 | 远程模式网络延迟影响体验 | 中 | 高 | WebSocket 连接池 + 日志批量推送 + 本地缓存 |
| P3 | 技术风险 | 结果可视化大数据量性能 | 中 | 中 | 后端预计算 + 前端虚拟滚动 + 数据分页 |
| P3 | 安全风险 | 文件系统隔离被绕过 | 低 | 高 | 路径校验 + chroot jail + 定期安全审计 |

### 风险应对详细方案

#### 风险 1：维护者时间不足（最重要）

**应对策略**：
1. **严格 MVP 优先**：Phase 1 的 P0 功能必须全部完成，P1 尽量完成，P2 可推迟
2. **功能可裁剪**：每个阶段定义"最小可接受范围"和"理想范围"
3. **自动化优先**：优先做自动化测试和部署，减少手动测试时间
4. **每周站会**：每周五下午 30 分钟回顾进度，调整优先级

**裁剪优先级（万不得已时）**：
```
Phase 1: 先砍 Docker 优化（用简单配置）→ 再砍进度解析（只显示日志）
Phase 2: 先砍 MCP → 再砍邮件通知 → AI 用简单实现
Phase 3: 先砍 UMAP → 再砍管理后台 → 保留远程模式+可视化
```

#### 风险 2：Snakemake 进度解析

**多模式解析方案**：

```python
def parse_progress(line: str) -> tuple[int, int] | None:
    """多模式进度解析"""
    import re
    
    patterns = [
        # Pattern 1: Snakemake 默认 "5 of 23 steps (22%) done"
        r'(\d+)\s+of\s+(\d+)\s+steps',
        # Pattern 2: "Finished job N."
        r'Finished job\s+(\d+)',
        # Pattern 3: DRMAA "Submitted job N"
        r'Submitted job\s+(\d+)',
        # Pattern 4: 规则完成计数
        r'(\d+)\s+jobs\s+finished',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            # 根据模式返回不同的进度计算方式
            ...
    
    return None  # 无法解析


class ProgressTracker:
    """进度追踪器（兜底方案）"""
    
    def __init__(self, total_steps: int):
        self.total = total_steps
        self.completed = 0
        self.start_time = time.time()
        # 预估总时间（用于时间-based 进度）
        self.estimated_duration = self._estimate_duration()
    
    def get_progress(self, log_line: str) -> int:
        """获取当前进度（0-100）"""
        # 优先用步骤解析
        if result := parse_progress(log_line):
            completed, total = result
            return int(completed / total * 100)
        
        # 兜底：按时间估算（平滑增长）
        elapsed = time.time() - self.start_time
        time_progress = min(int(elapsed / self.estimated_duration * 100), 99)
        return time_progress
```

---

## 技术债务管理

### 技术债务登记册

| 阶段 | 债务项 | 严重程度 | 产生原因 | 偿还计划 | 估算偿还工时 |
|------|--------|----------|----------|----------|-------------|
| P1 | 简单两角色权限（admin/user） | 低 | 快速实现 | P3 管理后台重构 | 2d |
| P1 | 样本表只传路径不上传文件 | 中 | 避免文件存储复杂度 | P3 项目-样本管理 | 3d |
| P1 | YAML 流程硬编码 | 高 | 快速实现单流程 | P2 流程配置中心 | 已偿还 |
| P1 | WebSocket 无断线重连 | 中 | 局域网稳定假设 | P2 增强 | 1d |
| P1 | 无任务取消功能 | 高 | Celery revoke 复杂度 | P2 增强 | 已偿还 |
| P1 | 日志无归档策略 | 低 | 本地存储 | P3 运维完善 | 1d |
| P2 | AI 对话不做持久化 | 中 | 优先可用性 | P3 AI 增强 | 2d |
| P2 | MCP 只有 PubMed | 低 | 验证架构 | P3 扩展更多 Server | 3d |
| P2 | 邮件同步发送 | 低 | Celery 足够 | P3 无需改 | - |
| P3 | 单 Celery Worker | 中 | 组内量可控 | v1.1 分布式队列 | 5d |
| P3 | 无高级缓存策略 | 低 | Redis 基础够用 | v1.1 缓存优化 | 3d |
| P3 | AI 历史 30 天限制 | 低 | 存储考虑 | v1.1 持久化方案 | 2d |

### 债务偿还策略

1. **每个阶段预留 10% 时间偿还上一阶段债务**
   - Phase 2 第一周：偿还 Phase 1 债务（约 1-2 天）
   - Phase 3 第一周：偿还 Phase 2 债务（约 1-2 天）

2. **债务可视化**
   - 在每个阶段开始时，列出未偿还债务
   - 在代码中用 `TODO(tech-debt)` 标记债务点

3. **债务上限**
   - 任一时刻未偿还债务不超过 5 项
   - 单一项债务工时不超过 3 天
   - 总债务工时不超过 10 天

---

## 总结

### 三个阶段的演进路线

```
Phase 1 (MVP)                    Phase 2 (v0.8)                  Phase 3 (v1.0)
  [RNA-seq]                       [多流程平台]                     [生产就绪]
     │                                │                               │
     ▼                                ▼                               ▼
┌──────────┐                    ┌──────────┐                    ┌──────────┐
│ 单流程    │ ──► YAML 配置中心 ──►│ 多流程    │ ──► 远程模式 ────►│ 分布式    │
│ 本地执行  │ ──► AI 对话 ────────►│ 智能助手  │ ──► 可视化 ──────►│ 结果展示  │
│ 基础表单  │ ──► 高级表单 ───────►│ 复杂交互  │ ──► AI 工具调用 ──►│ 自动化    │
│ 命令替代  │ ──► MCP 扩展 ───────►│ 开放生态  │ ──► 安全加固 ────►│ 企业级    │
└──────────┘                    └──────────┘                    └──────────┘
   ~5 周                           ~3-4 周                        ~3-4 周
```

### 关键成功因素

1. **MVP 必须可用**：Phase 1 完成后，组内成员 100% 可以通过 Web 提交 RNA-seq 任务
2. **快速迭代**：每完成一个功能点即演示，及时调整方向
3. **技术债务可控**：每个阶段预留时间偿还债务，避免积重难返
4. **文档先行**：每个阶段结束后更新文档，降低维护成本

### 最终交付物

| 交付物 | 路径 | 说明 |
|--------|------|------|
| 平台源码 | `/mnt/agents/output/` | 完整前后端代码 |
| 部署文档 | `docs/deployment.md` | Docker Compose 部署指南 |
| 使用手册 | `docs/user-guide.md` | 面向组内用户 |
| API 文档 | `/api/docs` (Swagger) | 自动生成 |
| 开发文档 | `docs/development.md` | 面向后续维护者 |


---

