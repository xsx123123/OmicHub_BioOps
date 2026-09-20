# CygnusX BioOps 复赛 Backlog

> 以下条目在初赛提交阶段明确不实施，仅作为后续迭代规划记录，避免与初赛已完成代码混淆。

## 1. contracts.yaml → MCP tool schema 自动转换层

- 现状：`contracts.yaml` 是人类可读的 Bridge 契约，缺少 MCP / OpenAI function schema 直接需要的 `name`、`description`、JSON Schema `parameters`、`required` 字段。
- 目标：新增一个轻量转换器（如 `integrations/agentteams/skills/contract_to_mcp.py`），把 `request` URI、`requires` 列表、`boundary`/`failure_handling` 文本编译成标准 MCP tool schema；供 `mcp-server` 在启动时可选加载。
- 依赖：保持 `contracts.yaml` 作为唯一事实源，不破坏现有 Bridge contract test。

## 2. agent-data / agent-qc / agent-delivery 的专用可执行 Skill 与完整业务提示词

- 现状：三个 Agent 的身份、协作边界、MAS 能力表已存在，但 YAML 顶部注释明确为“骨架”；当前仅挂载 `md5`、`fastq-screen`、`genome-tools` 等通用 Skill。
- 目标：
  - 为 `agent-data` 实现 `project-preflight` 可执行 Skill（样本表校验、分组对比、输入完整性）。
  - 为 `agent-qc` 实现 `quality-gate` 可执行 Skill（指标解析、阈值判决、证据链生成）。
  - 为 `agent-delivery` 实现 `delivery-pack` 可执行 Skill（产物汇总、manifest 生成、风险说明）。
  - 补齐对应提示词文件中的业务章节，使其达到与 `agent-rnaseq` 同等的完整度。
- 依赖：保持 Bridge 契约层 `delivery-pack` 名称不变，避免破坏既有 Case 记录与审计历史。

## 3. 结构化 SOP/QC 规则向量库（rule_search）

- 现状：平台已有通用领域知识库 RAG（pgvector + `kb_chunks`），但 QC/SOP 规则仍分散在 Flow YAML、工具配置、协议文档和 Agent 提示词中，没有独立的向量化规则集合。
- 目标：
  - 新建规则源格式（`rule_id`、`rule_version`、`domain`、`stage`、`artifact_type`、`metric_name`、`threshold_value`、`comparator`、`severity`、`reference_path`）。
  - 将 `data/ai/flows/*.yaml`、`tool_configs/*/config.yaml`、`Protocol/Skill_design.md`、`data/ai/prompts/qc.md` 中的规则抽取并索引到专用集合。
  - 提供 `rule_search(query, domain, stage, artifact_type)` 工具，供 `agent-qc` 在做 `PASSED/WARNING/BLOCKED` 判决时引用。
- 依赖：复用现有 `VectorRetrievalService` 与 `KnowledgeIndexService`，不新建存储引擎。

## 4. LoongSuite / AgentScope / 阿里云 ARMS 接入

- 现状：可观测性已接入 OpenTelemetry 通用 OTLP gRPC / Prometheus 导出；LoongSuite、AgentScope、阿里云 ARMS / SLS Trace 仅在架构文档中作为名词提及，无代码级接入。
- 目标：
  - 评估 LoongSuite / AgentScope 与现有 LangGraph + AgentTeams Bridge 的集成点（可选替代或补充运行时）。
  - 增加阿里云 ARMS / SLS Trace Exporter 配置，使 trace/span 可投递到阿里云可观测套件。
- 依赖：保持通用 OTLP 接入作为默认路径，云厂商接入通过配置开关启用。
