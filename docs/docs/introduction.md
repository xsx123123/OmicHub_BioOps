# CygnusX 平台介绍

CygnusX 是面向生命科学研究的私有化多组学分析平台，旨在帮助研究团队高效、可复现地完成各类组学数据分析。

## 核心能力

- **多组学流程**：RNA-seq、ATAC-seq、ChIP-seq、scRNA-seq、WGS、宏基因组等
- **工作流引擎**：基于 Snakemake 实现自动化、可扩展、可复现的分析
- **任务管理**：实时监控任务状态、日志和 DAG 可视化
- **资源调度**：支持本地执行与集群调度
- **账户体系**：基于饼干积分的资源计量与权限控制

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + TypeScript + Naive UI |
| 后端 | FastAPI + SQLAlchemy + Celery |
| 工作流 | Snakemake |
| 数据库 | PostgreSQL |
| 缓存 | Redis |

## 部署方式

CygnusX 支持 Docker Compose 一键部署，适合实验室私有化部署，确保数据不出内网。
