# 快速开始

本章节帮助你在本地或服务器上快速跑通 CygnusX，并完成首位管理员注册。

## 内容导航

- [快速开始指南](quickstart) — 本地开发与 Docker 部署的最小可行路径
- [首次部署与管理员注册](first-time-setup) — `/setup` 页面、管理员账号初始化与注意事项

## 环境要求

- Python >= 3.11
- Node.js >= 20
- Docker >= 24.0
- uv（Python 包管理器）

## 一分钟了解部署方式

| 场景 | 推荐方式 | 关键命令 |
|---|---|---|
| 本地开发 | 源码 + Docker（DB/Redis） | `make dev`、`make frontend-dev` |
| 单服务器生产 | Docker Compose 主栈 + Worker 栈 | `make docker-up-all` |
| 多 Worker 扩展 | Worker 栈通过项目包装器扩展 | `./scripts/worker-compose.sh --scale worker=2 up -d` |

完成部署后，访问 `http://localhost:5173`（开发）或 `http://<服务器IP>:8888`（Docker）。
