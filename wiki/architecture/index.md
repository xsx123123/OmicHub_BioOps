# 架构与数据

本章节介绍 OmicHub 的整体架构、数据目录布局、日志体系与核心设计约定。

## 内容导航

- [系统架构总览](overview) — 技术栈、DDD 分层、核心领域与数据流
- [数据目录结构](data-directory) — `/data/omichub` 目录布局与挂载说明
- [日志架构与排障](logging) — 统一日志目录、各服务写入方式、容量保护与排障

## 设计关键词

- **前后端分离**：Vue 3 + FastAPI，Nginx 作为入口与静态资源代理。
- **DDD 分层**：`api/` → `application/` → `domain/` → `infrastructure/`。
- **控制面与计算面分离**：主栈运行 Web / DB / Redis / Nginx / Beat / Flower；Worker 栈独立运行计算任务。
- **声明式流程**：`flows/*.yaml` + `GenericFlowBuilder` 支持新增流程无需改后端代码。
- **配置外置**：可运营配置进 `tool_configs/` 或数据库；密钥进环境变量。
