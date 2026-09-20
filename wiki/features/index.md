# 功能特性

本章节介绍 CygnusX 面向终端用户的核心功能，包括 AI 助手、分析流程、数据下载、知识库、沙盒终端与各类生信工具。

## 内容导航

- [AI 助手与工作台](ai-chat) — 流式对话、专家路由、知识检索、工具与技能
- [AI 多 Agent 协作与超频模式](ai-collaboration) — 受控规划、分工、审批与交付
- [分析流程与工作流](workflows) — YAML 声明式流程与新增流程方法
- [数据下载](downloads) — EBI/NCBI 公共数据库下载与云存储直拉
- [实验室知识库](knowledge-base) — Markdown 源内容、数据库版本与检索索引
- [云端沙盒终端](sandbox-terminal) — 浏览器交互式隔离容器终端
- [参考基因组与数据库](reference-database) — JBrowse 2 基因组浏览器与参考数据
- [系统发育树构建](phylogenetic-tree) — 多序列比对与系统发育树工具
- [流程监控面板](workflow-monitor) — Snakemake 工作流实时监控
- [RNA-seq 分析](rna-seq) — RNA-seq 流程说明
- [ATAC-seq 分析](atac-seq) — ATAC-seq 流程说明

## 功能扩展入口

| 扩展类型 | 配置文件/位置 | 说明 |
|---|---|---|
| 新增分析流程 | `flows/*.yaml` | 声明式 YAML，热重载 |
| 新增生信工具 | `tool_configs/tools_setting.yaml`、`tools_schema.yaml` + `tool_configs/<tool>/` | 前端卡片、AI schema 与专属配置 |
| 新增知识库文档 | `docs/knowledge/*.md` + `meta.yaml` 或 `wiki/` | 先更新源文档，再同步到数据库索引 |
| 新增参考基因组 | `tool_configs/jbrowse/jbrowse_config.yaml` | JBrowse 2 配置 |
