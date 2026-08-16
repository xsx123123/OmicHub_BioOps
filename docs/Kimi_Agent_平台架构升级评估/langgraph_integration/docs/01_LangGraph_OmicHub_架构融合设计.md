# LangGraph 与 OmicHub 深度融合架构设计

> 版本: v1.0  
> 日期: 2026-07-06  
> 目标: 将 LangGraph 作为 OmicHub 的 Agent 调度中枢，实现状态持久化、容错重试、HITL 人工在环

## 一、融合架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        前端层 (Vue3)                                 │
│  ┌────────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │ AgentWorkspace.vue │  │ TaskDashboard    │  │ HITLDialog.vue  │  │
│  │ (对话 + 流式渲染)   │  │ (任务状态面板)    │  │ (人工确认弹窗)   │  │
│  └─────────┬──────────┘  └──────────────────┘  └─────────────────┘  │
│            │  SSE Stream (兼容现有格式)                              │
└────────────┼────────────────────────────────────────────────────────┘
             │
┌────────────┼────────────────────────────────────────────────────────┐
│            ▼             API 层 (FastAPI)                            │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  POST /api/v1/chat/stream (现有端点，内部路由到 LangGraph)      │   │
│  │  POST /api/v1/agent/hitl/resume (新增: HITL 恢复)              │   │
│  │  GET  /api/v1/agent/checkpoints/{thread_id} (新增: 状态查询)    │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────┼───────────────────────────────────┐   │
│  │                     应用层                                │   │
│  │  ┌───────────────────────▼─────────────────────────────┐ │   │
│  │  │        LangGraphRuntimeService (新增)                  │ │   │
│  │  │  - 管理 StateGraph 生命周期                            │ │   │
│  │  │  - 线程池 + 并发控制                                    │ │   │
│  │  │  - 事件流转换 (LangGraph事件 → OmicHub SSE格式)         │ │   │
│  │  └───────────────────────┬─────────────────────────────┘ │   │
│  │                          │                                 │   │
│  │  ┌───────────────────────▼─────────────────────────────┐ │   │
│  │  │        HITLService (新增)                             │ │   │
│  │  │  - 中断点管理                                          │ │   │
│  │  │  - 人工确认/修改/拒绝                                   │ │   │
│  │  │  - 恢复执行                                            │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                     领域层                                │   │
│  │  ┌─────────────────────┐  ┌───────────────────────────┐ │   │
│  │  │  AgentState (Pydantic)│  │  HITLRequest/HITLResponse  │ │   │
│  │  │  - 消息历史            │  │  - interrupt_for          │ │   │
│  │  │  - 工具调用记录         │  │  - human_input            │ │   │
│  │  │  - 任务上下文           │  │  - resume_action          │ │   │
│  │  │  - 执行元数据           │  │  - modified_params        │ │   │
│  │  └─────────────────────┘  └───────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   基础设施层                              │   │
│  │  ┌─────────────────────┐  ┌───────────────────────────┐ │   │
│  │  │ OmicHubCheckpointSaver│  │   LangGraphExecutor      │ │   │
│  │  │ (PostgreSQL + Redis)  │  │   (extends BaseExecutor) │ │   │
│  │  │ - 状态持久化           │  │   - 注册到 registry.py    │ │   │
│  │  │ - 断点恢复             │  │   - 替代 8轮自研循环       │ │   │
│  │  │ - 历史查询             │  │   - 容错重试              │ │   │
│  │  └─────────────────────┘  └───────────────────────────┘ │   │
│  │                          复用现有组件:                     │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐│   │
│  │  │MCPClient │ │ProviderMn│ │TaskServic│ │Celery App    ││   │
│  │  │(现有)    │ │ager(现有)│ │e(现有)   │ │(现有)        ││   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘│   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 二、核心设计理念

### 2.1 渐进式融合（非推倒重来）

| 现有组件 | 融合方式 | 改动量 |
|----------|----------|--------|
| `BaseExecutor` + `registry.py` | 新增 `LangGraphExecutor` 子类注册 | 低 |
| `AgentService.assemble_context` | 提取为 LangGraph 的 `assemble` 节点 | 中 |
| `ChatService.stream_agent_chat` | 替换为 LangGraphRuntimeService 编排 | 高 |
| `MCPClient.call_tool` | 直接复用，包装为 `tool_exec` 节点 | 低 |
| `ProviderManager.chat_stream` | 复用，包装为 `llm_call` 节点 | 低 |
| 前端 `useAgentChatStream.ts` | 适配事件类型，SSE 格式保持兼容 | 中 |
| Celery 任务队列 | LangGraph 执行器内部仍投递 Celery 做重计算 | 低 |

### 2.2 状态驱动（State-Driven）

LangGraph 的核心是 `AgentState` —— 所有节点通过状态传递数据，状态自动持久化：

```python
class AgentState(BaseModel):
    """LangGraph 状态定义 —— 贯穿所有节点的状态载体"""
    messages: List[BaseMessage]          # 对话历史
    tool_calls: List[ToolCallRecord]     # 工具调用记录
    task_context: Optional[TaskContext]  # 任务上下文（提交分析时填充）
    hitl_status: HITLStatus              # HITL 状态: pending/resumed/rejected
    metadata: Dict[str, Any]             # 执行元数据（轮次、耗时、token数）
    next_node: Optional[str]             # 路由目标（条件边使用）
```

### 2.3 HITL 中断点设计

在关键决策点插入 `interrupt`，等待人工输入：

| 中断点 | 触发条件 | 人工操作 |
|--------|----------|----------|
| `param_confirm` | AI 推荐分析参数后 | 确认 / 修改参数 / 取消 |
| `task_submit` | 参数确认后提交任务前 | 确认提交 / 暂存草稿 |
| `result_review` | 分析完成后 | 审核通过 / 重新分析 / 下载报告 |

## 三、StateGraph 节点定义

```
                    ┌─────────────┐
         ┌─────────►│  __start__  │◄────────────────────────┐
         │          └──────┬──────┘                         │
         │                 │                                │
         │                 ▼                                │
         │          ┌─────────────┐   有任务上下文           │
         │          │   assemble  │──────────────────┐     │
         │          │ (收集上下文)  │                  │     │
         │          └──────┬──────┘                  │     │
         │                 │ 无任务上下文              │     │
         │                 ▼                        ▼     │
         │          ┌─────────────┐          ┌─────────────┐
         │          │   llm_call  │◄─────────│ task_builder│
         │          │ (LLM 调用)   │          │ (构建任务)   │
         │          └──────┬──────┘          └─────────────┘
         │                 │
         │         ┌───────┴───────┐
         │         │  条件边判断     │
         │         ▼               ▼
         │  ┌──────────┐    ┌──────────┐
         │  │tool_call?│    │  done?   │
         │  └────┬─────┘    └────┬─────┘
         │       │ 是            │ 是
         │       ▼               ▼
         │  ┌──────────┐    ┌──────────┐
         │  │tool_exec │    │  __end__ │
         │  │(MCP执行)  │    └──────────┘
         │  └────┬─────┘
         │       │
         │       └────────────────┐
         │                        │
         │          ┌─────────────▼─┐
         │          │  hitl_check   │
         │          │ (HITL中断检查) │
         │          └──────┬───────┘
         │                 │ 需要HITL
         │                 ▼
         │          ┌─────────────┐
         │          │   interrupt │
         │          │ (等待人工)   │
         │          └──────┬──────┘
         │                 │ 人工恢复
         └─────────────────┘
```

## 四、文件清单

```
langgraph_integration/
├── docs/
│   ├── 01_架构融合设计.md              # 本文档
│   ├── 02_后端实现详解.md              # 后端代码说明
│   ├── 03_前端适配指南.md              # 前端改动说明
│   └── 04_部署与迁移.md                # 部署步骤
├── backend/
│   └── src/omichub/
│       ├── domain/execution/
│       │   ├── agent_state.py          # AgentState 状态定义
│       │   ├── hitl_models.py          # HITL 相关模型
│       │   └── checkpoint_models.py    # 检查点模型
│       ├── application/services/
│       │   ├── langgraph_runtime.py    # LangGraph 运行时服务
│       │   ├── hitl_service.py         # HITL 管理服务
│       │   └── stream_adapter.py       # 事件流适配器
│       ├── infrastructure/execution/
│       │   └── langgraph_executor.py   # LangGraphExecutor
│       ├── infrastructure/checkpoint/
│       │   └── postgres_checkpoint.py  # PostgreSQL 检查点实现
│       └── api/v1/
│           └── agent.py                # HITL 相关 API 路由
├── backend/alembic/versions/
│   └── add_langgraph_checkpoint.py     # Alembic 迁移
├── backend/tests/
│   ├── test_langgraph_executor.py      # 执行器测试
│   ├── test_hitl_flow.py               # HITL 流程测试
│   └── test_checkpoint.py              # 检查点测试
├── frontend/
│   └── src/composables/
│       └── useLangGraphStream.ts       # 前端流式适配
└── scripts/
    ├── install_langgraph.py            # 一键安装脚本
    └── migrate_to_langgraph.py         # 迁移脚本
```

## 五、关键技术决策

### 5.1 为什么 LangGraph 胜过自研循环

| 能力 | 自研 8 轮循环 | LangGraph | 对 OmicHub 的价值 |
|------|-------------|-----------|-----------------|
| 状态持久化 | ❌ 内存中 | ✅ PostgreSQL + Redis | Worker 崩溃不丢执行状态 |
| 断点续跑 | ❌ 从头重跑 | ✅ 任意节点恢复 | 生信分析几小时任务不白费 |
| 容错重试 | ❌ 手动 | ✅ 节点级自动重试 | MCP 调用失败自动重试 |
| HITL | ❌ 无 | ✅ 内置 interrupt | 参数确认、结果审核 |
| 可视化调试 | ❌ 无 | ✅ LangSmith | 复杂 Agent 调试 |
| 子图复用 | ❌ 无 | ✅ Subgraph | 多 Agent 编排 |

### 5.2 与现有架构的兼容策略

**向后兼容**：`LangGraphExecutor` 继承 `BaseExecutor`，`registry.py` 注册后，
`flows/*.yaml` 可通过 `engine: langgraph` 启用，不启用则走原有 `LocalSnakemakeExecutor`。

**前端兼容**：SSE 事件格式保持与现有 `useAgentChatStream.ts` 一致，
仅新增 `hitl_request` / `hitl_resumed` 两种事件类型。

**数据库兼容**：新增 `langgraph_checkpoints` 表，不影响现有表结构。

## 六、升级路线

| 阶段 | 时间 | 目标 | 交付物 |
|------|------|------|--------|
| 1 | 3天 | 核心 StateGraph + 检查点 | `AgentState` / `OmicHubCheckpointSaver` / `LangGraphExecutor` |
| 2 | 2天 | HITL 中断与恢复 | `HITLService` / `interrupt` 节点 / 前端弹窗 |
| 3 | 2天 | 事件流适配 | `StreamAdapter` / 前端 `useLangGraphStream.ts` |
| 4 | 2天 | 集成测试 + 灰度 | 测试用例 / 双引擎并存 / 逐步切流 |
| 5 | 1天 | 监控 + 文档 | LangSmith 接入 / 运维文档 |

**总工期**: ~10天（单人全栈）
