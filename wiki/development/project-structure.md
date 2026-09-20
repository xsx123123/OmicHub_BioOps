# 项目结构

CygnusX 采用前后端分离 + DDD 分层 + 配置外置的目录组织方式。

## 顶层目录

```text
CygnusX/
├── src/cygnusx/            # 后端 Python 包 (DDD 分层)
├── frontend/               # 前端 Vue 3 项目
├── deploy/docker/          # Docker 部署配置
├── flows/                  # Snakemake 流程 YAML
├── tool_configs/           # 生信工具箱配置
├── pipelines/              # 流程代码（RNAFlow / ATACFlow / EBIDownload / jbrowse2）
├── data/                   # AI Provider YAML 等运行时配置
├── docs/                   # 架构设计文档
│   └── knowledge/          # 实验室知识库 Markdown
├── tests/                  # 单元测试与集成测试
├── alembic/                # 数据库迁移
├── scripts/                # 管理脚本与 cygnusxtools CLI
└── wiki/                   # 本 Wiki
```

## 后端结构 (`src/cygnusx/`)

```text
src/cygnusx/
├── api/v1/                 # 表示层 - FastAPI 路由
│   ├── admin/              # 管理员路由
│   └── ...                 # 业务路由
├── application/            # 应用层
│   ├── services/           # 应用服务
│   └── schemas/            # Pydantic DTO
├── domain/                 # 领域层
│   ├── user/
│   ├── flow/
│   ├── task/
│   ├── file/
│   ├── ai/
│   ├── mcp/
│   └── skill/
├── infrastructure/         # 基础设施层
│   ├── ai_provider/        # LLM Provider 适配器
│   ├── database/           # SQLAlchemy ORM + 仓储
│   ├── celery_app/         # Celery 配置与任务
│   ├── execution/          # Snakemake 执行器
│   ├── terminal/           # 沙盒终端 Docker 管理
│   └── download/           # 下载进度解析
├── core/                   # 核心配置
│   ├── config.py
│   ├── security.py
│   ├── logging.py
│   └── exceptions.py
├── middleware/             # 中间件
│   ├── auth.py
│   ├── rbac.py
│   ├── audit.py
│   ├── cookie.py
│   └── rate_limit.py
└── tools/                  # 相对独立的生信工具模块
    ├── jbrowse/
    ├── enrichments/
    ├── registry/
    └── terminal/
```

## 前端结构 (`frontend/src/`)

```text
frontend/src/
├── api/                    # 类型化 HTTP 调用
├── types/                  # TypeScript DTO / 领域类型
├── views/                  # 页面与路由入口
├── components/             # 可复用组件
│   ├── ai-chat/
│   ├── admin/
│   ├── sandbox/
│   ├── knowledge/
│   ├── bio-tools/
│   └── task/
├── composables/            # 可复用状态与副作用
├── stores/                 # Pinia 全局状态
├── router/                 # 路由配置
├── layouts/                # 页面布局
├── styles/                 # 全局样式与 CSS 变量
└── utils/                  # 纯函数工具与图表处理器
```

## 配置外置目录

| 目录 | 用途 |
|---|---|
| `tool_configs/` | 生信工具注册表、工具专属配置、终端/JBrowse/富集物种配置 |
| `flows/` | 分析流程 YAML，支持热重载 |
| `data/` | AI Provider、平台运行时 YAML |
| `docs/knowledge/` | 实验室知识库 Markdown |

## 关键设计约定

- 路由层只负责参数解析、依赖注入、认证/权限调用和 HTTP 状态码映射。
- 应用服务负责用例编排、事务边界和跨领域协作。
- 领域层负责复杂业务规则与状态机。
- 基础设施层负责具体的技术实现（ORM、Redis、文件、Docker、第三方 API）。
