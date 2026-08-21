# 架构与设计文档索引

本目录集中存放 OmicHub 的项目级架构、设计规范和实施方案。修改相关功能前，请先阅读对应文档，确保实现与既有约束保持一致。

| 文件 | 内容说明 |
| --- | --- |
| `LOG_ARCHITECTURE.md` | 统一日志架构说明，定义应用、Celery、Nginx、Snakemake 与审计日志的目录、格式、挂载和容量保护策略。 |
| `omichub_design.md` | 项目级模块设计与接入指南，规定平台功能、分析流程、AI/Agent、异步任务及外部服务集成的分层与契约基线。 |
| `omichub_studio.md` | OmicStudio AI 分析工作台的实施进度与交接文档，记录沙盒、Agent、API、前端、验证状态、运维注意事项和待办事项。 |
| `fontend.md` | 前端视觉与交互规范，涵盖设计令牌、页面层级、组件状态、动效、响应式设计和可访问性要求。 |
| `plan_ai.md` | 多智能体编排、共享工作区与 A2A 架构实施方案，说明目标架构、状态管理、数据模型、事件协议和落地路径。 |
| `agent_architecture_and_extension_guide.md` | 当前 Agent 运行架构、P1–P3 实施状态、灰度条件，以及修改提示词和新增内置/MCP 工具的操作指南。 |
| `agent_framework_final_baseline.md` | 2026-07-26 最终 AI 助手基线：Agent 装配、提示词与工具契约、路由、Studio、Handoff、MAS 边界及发布验收清单。 |
| `agent_current_execution_framework_2026-08.md` | 2026-08-18 当前 Agent 执行框架：Legacy/LangGraph/Studio/Worker 闭环、AgentTeams 房间路由、统一生命周期事件、loop guard、前端投影和扩展约束。 |
| `agent_execution_loop_observability_2026-08.md` | 2026-08-18 Agent 思考—工具闭环可观测性升级：执行路径、统一事件、协助室只读工具路由、Worker 追溯字段、Guard、前端技术事件模式与验证基线。 |
| `agentteams_department_collaboration_architecture_2026-08.md` | 生物信息协作部门评审稿：用户—Manager—领域 Agent—并行 Worker 的组织模型、`@` 点名群聊协议、任务冻结/变更决策状态机、交接事件与分阶段实施建议。 |
| `agentteams_department_collaboration_architecture.md` | 生物信息协作部门当前规范：用户—Manager—领域 Agent—并行 Worker 的组织模型、`@` 点名群聊协议、任务冻结/变更决策状态机、交接事件与实施边界。 |
| `memory_architecture.md` | 2026-08-18 AI 记忆系统当前架构：v2 灰度拓扑、memory blocks/facts、FactStore、settle、Studio 文件记忆、检查点、安全和回滚边界。 |
| `worker_images_plan.md` | Worker 轻量镜像与 Workspace 动态安装计划，定义 Worker 镜像边界、运行时挂载、Conda 环境缓存及实施步骤。 |
| `mcp_architecture.md` | MCP 子系统完整架构（三层体系、注册/发现/调用、安全验证、沙箱隔离、AI 模型接入），以及 Agent 自生成 MCP 的可行性分析与分阶段实施方案。 |
| `mcp_builder_agent.md` | MCP 构建师（agent-mcp-builder）实现架构：六阶段生成流水线、AST 安全检查器规则表、沙箱 STDIO 执行层、mcp_builds/versions/reviews 数据模型、12 条 Builder API、TTL/配额/审核生命周期与运维要点。 |

## 相关文档（目录外）

- `docs/26.7.22/ai_assistant_single_entry_architecture.md`：AI 助手模块详细架构（统一入口「智能助手」、双引擎分流 LangGraph/手写循环、智能路由、MCP preset、Studio HITL、SSE 事件协议、前后端组件链）及优化待办清单与落地记录。
- 开发环境热刷新约定见根目录 `README.md`「Docker 部署」一节：日常改代码/YAML/前端用 `make docker-dev-refresh`（秒级，bind mount 免重建镜像），仅依赖（`uv.lock`/Dockerfile）变更才用 `make docker-reload`。
