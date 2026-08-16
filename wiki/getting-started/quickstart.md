# 快速开始

本页给出本地开发和单机 Docker 部署的最短可用路径。完整配置项、跨机部署和生产加固以根目录
`README.md`、`.env.example` 和部署章节为准。

## 环境要求

| 组件 | 建议 |
| --- | --- |
| Python | 3.11+ |
| Node.js | 20+ |
| Docker / Docker Compose | Docker 24+ |
| Git | 当前稳定版 |

## 本地开发

```bash
# 1. 配置本地环境变量
cp .env.example .env

# 2. 安装后端与前端依赖
uv sync
make frontend-install

# 3. 启动 PostgreSQL 和 Redis 等主栈依赖
make docker-up

# 4. 迁移数据库并初始化管理员
make migrate
make init-admin

# 5. 分别启动后端和前端开发服务
make dev
make frontend-dev
```

默认开发前端地址为 `http://localhost:5173`。首次没有管理员时，也可以访问 `/setup` 创建首位管理员。

## Docker 一键部署

```bash
cp .env.example .env
# 编辑 .env，替换所有示例密钥与管理员密码

make docker-up-all
make wait-web
make migrate
make init-admin
```

部署后从 `.env` 中配置的 HTTP 地址访问平台。第一次编辑仓库知识文档后，执行 `make sync-knowledge`
将 Markdown 同步到数据库检索索引。

## 下一步

- [首次部署与管理员注册](first-time-setup)
- [Docker 部署](../deployment/docker-deployment)
- [实验室知识库](../features/knowledge-base)
- [常用命令](../operations/common-commands)
