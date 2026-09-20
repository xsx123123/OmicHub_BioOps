# 部署与运维

本章节介绍 CygnusX 的 Docker 部署方式、生产环境检查清单以及日常更新回滚操作。

## 内容导航

- [Docker 部署](docker-deployment) — 主栈 + Worker 栈、跨机与生产部署入口
- [代码更新与回滚](update-rollback) — 日常刷新、镜像重建与回退策略
- [生产环境检查清单](production-checklist) — 安全、网络、密钥、SSL 等生产必填项
- [开启 Multi-Agent 与 AgentTeams](agentteams-enablement) — 意图路由、会诊、Bridge 令牌与预检

## 部署目录拓扑（deploy/）

```
deploy/
├── docker/            主栈与 Worker 栈：docker-compose.yml / .worker / .prod / .pgvector /
│                      cross-web / cross-worker 覆盖、各 Dockerfile、nginx、rocketmq 配置
├── agentteams/        AgentTeams 栈：Bridge/Gateway/Worker compose、bridge.env|worker.env
│                      模板、matrix-dev 开发栈、check_setup.sh 与各项验证脚本、kubernetes/
├── runtime-images/    Studio 分析运行时三件套（core/plot/scrna Dockerfile + build.sh）
├── studio/            OmicStudio 沙箱镜像（base/bio）、出站白名单代理、sandbox_agent
├── sandbox/           AI Copilot 代码执行沙盒镜像（cygnusx-sandbox-copilot）
├── mas/               MAS Apptainer Worker（systemd unit + env 模板）
└── logrotate/         宿主机日志轮转配置（cygnusx-logs）
```

## 部署模式

CygnusX 采用**双栈分离**部署：

- **主栈**（`deploy/docker/docker-compose.yml`）：Web、数据库、缓存、入口与调度服务
- **Worker 栈**（`deploy/docker/docker-compose.worker.yml`）：分析 Worker 与运行时镜像，可水平扩展

两栈通过外部网络 `cygnusx_net` 共享 Redis，并挂载同一宿主目录 `/data/cygnusx`。

## 常用运维入口

| 操作 | 命令 |
|---|---|
| 启动主栈 | `make docker-up` |
| 启动 Worker 栈 | `make docker-up-worker` |
| 一键启动全部 | `make docker-up-all` |
| 日常代码改动刷新 | `make docker-dev-refresh` |
| 前端改动后完整重载 | `make docker-reload` |
| 彻底重建环境 | `make docker-start` |
| 启动 AgentTeams 栈 | `make docker-up-agentteams` |
| 修复权限事故 | `make docker-fix-permissions` |
