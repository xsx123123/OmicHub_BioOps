# LangGraph + OmicHub 深度融合方案

> 将 LangGraph 作为 OmicHub 的 Agent 调度中枢，实现状态持久化、容错重试、HITL 人工在环。

## 方案概述

本方案将 LangGraph 与 OmicHub 平台进行深度融合，保留 OmicHub 现有架构（DDD 分层、BaseExecutor 抽象、MCP 客户端、Celery 任务队列）的基础上，引入 LangGraph 的先进能力：

| 能力 | 原有自研循环 | LangGraph 融合后 |
|------|-------------|-----------------|
| 状态持久化 | 内存中，Worker 崩溃即丢失 | PostgreSQL + Redis 自动持久化 |
| 断点续跑 | 从头重跑 | 任意节点恢复 |
| 容错重试 | 无 | 节点级自动重试 |
| HITL 人工在环 | 无 | 内置 interrupt + 恢复 |
| 可视化调试 | 无 | LangSmith 支持 |
| 子图复用 | 无 | Subgraph 支持多 Agent 编排 |

## 生成文件清单（15 个）

### 架构文档（2 个）

| 文件 | 说明 |
|------|------|
| `docs/01_LangGraph_OmicHub_架构融合设计.md` | 完整架构设计文档，含 StateGraph 图定义和升级路线 |
| `docs/04_部署与迁移.md` | 部署指南，含一键安装、手动安装、配置说明、验证步骤 |

### 后端核心代码（10 个）

| 文件 | 行数 | 说明 |
|------|------|------|
| `domain/execution/agent_state.py` | ~400 | AgentState 状态定义，兼容 OmicHub 现有 AgentContext |
| `domain/execution/hitl_models.py` | ~150 | HITL 领域模型（Request/Response/HistoryRecord） |
| `infrastructure/execution/langgraph_nodes.py` | ~300 | 5 个节点函数（assemble/llm_call/tool_exec/hitl_check/task_builder）+ 条件边 |
| `infrastructure/execution/langgraph_runtime.py` | ~350 | LangGraphRuntimeService，核心编排器，SSE 事件生成 |
| `infrastructure/execution/langgraph_executor.py` | ~150 | LangGraphExecutor，继承 BaseExecutor，注册到 registry |
| `infrastructure/checkpoint/postgres_checkpoint.py` | ~350 | OmicHubCheckpointSaver，PostgreSQL + Redis 持久化 |
| `application/services/hitl_service.py` | ~300 | HITLService，中断管理 + 人工响应处理 |
| `application/services/stream_adapter.py` | ~150 | StreamAdapter，LangGraph 事件 → OmicHub SSE 格式 |
| `api/v1/agent.py` | ~200 | HITL 相关 API 路由（resume/pending/cancel/status/checkpoints） |
| `alembic/versions/add_langgraph_checkpoint.py` | ~120 | 5 张表的 Alembic 迁移定义 |

### 前端代码（2 个）

| 文件 | 行数 | 说明 |
|------|------|------|
| `frontend/src/composables/useLangGraphStream.ts` | ~300 | SSE 流式适配组合式函数，兼容现有 useAgentChatStream |
| `frontend/src/components/HITLDialog.vue` | ~400 | HITL 确认弹窗组件，支持 param_confirm/task_submit/result_review |

### 工具脚本（1 个）

| 文件 | 说明 |
|------|------|
| `scripts/install_langgraph.py` | 一键安装脚本，自动完成所有集成步骤 |

### 测试代码（1 个）

| 文件 | 说明 |
|------|------|
| `backend/tests/test_langgraph_executor.py` | 执行器 + AgentState + HITL 模型的完整测试用例 |

## 架构融合要点

### 与现有架构的兼容性

```
OmicHub 现有架构（保留）:
  DDD 四层分层  ────────────────────────────→  不变
  BaseExecutor + registry.py  ──────────────→  新增 LangGraphExecutor 子类
  AgentService.assemble_context  ───────────→  提取为 assemble 节点
  ProviderManager.chat_stream  ─────────────→  复用，包装为 llm_call 节点
  MCPClient.call_tool  ─────────────────────→  复用，包装为 tool_exec 节点
  Celery + Snakemake 任务队列  ─────────────→  复用，LangGraph 内部投递
  PostgreSQL + Redis  ──────────────────────→  复用，新增检查点表
  前端 SSE 流式  ───────────────────────────→  兼容，新增 hitl_request 事件
```

### StateGraph 节点流程

```
__start__ → assemble → llm_call → [条件边]
  [有 tool_calls] → tool_exec → llm_call (循环)
  [无 tool_calls] → hitl_check
    [需 HITL] → interrupt (等待人工)
    [需构建任务] → task_builder → llm_call
    [正常完成] → __end__
```

### HITL 中断点

| 中断点 | 触发时机 | 人工操作 |
|--------|----------|----------|
| `param_confirm` | AI 推荐分析参数后 | 确认 / 修改参数 / 取消 |
| `task_submit` | 参数确认后、任务提交前 | 确认提交 / 暂存草稿 |
| `result_review` | 分析完成后 | 审核通过 / 重新分析 |

## 快速安装

```bash
cd /path/to/omichub
python langgraph_integration/scripts/install_langgraph.py
```

## 手动安装要点

1. **安装依赖**: `pip install langgraph>=0.2.0 langchain-core>=0.3.0`
2. **复制代码**: 将 backend/ 和 frontend/ 下的文件复制到对应位置
3. **数据库迁移**: `alembic upgrade head`（新增 5 张表）
4. **注册执行器**: 在 `registry.py` 的 `_EXECUTORS` 中添加 `"langgraph": LangGraphExecutor`
5. **生命周期初始化**: 在 `main.py` 的 `lifespan` 中创建 LangGraphRuntimeService
6. **添加路由**: 在 `router.py` 中引入 `agent_router`
7. **前端集成**: AgentWorkspace 中使用 `useLangGraphStream` + `HITLDialog`

## 启用 LangGraph

在 `flows/*.yaml` 中设置 `engine: langgraph`:

```yaml
execution:
  engine: langgraph       # 启用 LangGraph（默认 snakemake）
  snakefile: "/workflow/Snakefile"
  langgraph:
    max_rounds: 8
    hitl_enabled: true
    hitl_timeout: 600
```

## 技术选型决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 框架 | LangGraph（非 Dify/CrewAI） | 状态管理 + HITL + MCP 原生支持，与 OmicHub 任务状态管理天然匹配 |
| 持久化 | PostgreSQL + Redis | 复用 OmicHub 现有基础设施，无需引入新中间件 |
| 前端模式 | 对话驱动 + 面板展示（非纯 ChatOps） | 生信场景需要可视化（文件浏览、报告查看、日志追踪） |
| 部署方式 | 渐进式融合（非推倒重来） | 保持向后兼容，engine 配置切换，风险可控 |

## 升级路线

| 阶段 | 时间 | 目标 |
|------|------|------|
| 1 | 3天 | 核心 StateGraph + 检查点持久化 |
| 2 | 2天 | HITL 中断与恢复（前后端） |
| 3 | 2天 | 事件流适配 + 前端弹窗 |
| 4 | 2天 | 集成测试 + 灰度发布 |
| 5 | 1天 | LangSmith 监控 + 文档 |

**总工期**: ~10天（单人全栈）

## 注意事项

1. **向后兼容**: 不启用 `engine: langgraph` 的流程完全不受影响
2. **数据库**: 新增 5 张表，不影响现有表结构和数据
3. **前端**: SSE 事件格式保持兼容，仅新增 `hitl_request` / `hitl_resumed` 两种事件
4. **回滚**: 修改 `flows/*.yaml` 的 `engine` 字段即可回滚到原有模式
5. **监控**: 建议接入 LangSmith 进行 Agent 执行轨迹追踪

## 联系与支持

- OmicHub 项目: https://github.com/your-org/omichub
- LangGraph 文档: https://langchain-ai.github.io/langgraph/
- 问题反馈: 在 OmicHub 仓库提交 Issue
