# 生物信息部门 MAS 最小实现 · 阶段 0-4 完成报告

> 实施日期：2026-09-20 ~ 2026-09-21。按《生物信息部门页面_MAS最小实现实施手册》完成阶段 0-4，验收证据以本报告为准。

## 交付清单

### 新增文件（全部独立，不碰既有链路）

| 文件 | 说明 |
| --- | --- |
| `src/cygnusx/domain/execution/mas_state.py` | MASState TypedDict（对齐 AgentState 风格） |
| `src/cygnusx/domain/mas/worker_policy.py` | 工具剥离/上下文裁剪纯函数（含 9 个单测） |
| `src/cygnusx/application/services/mas/mas_graph.py` | Supervisor-Worker 图（interrupt/resume + 熔断） |
| `src/cygnusx/application/services/mas/mas_worker_executor.py` | Worker 执行器（委托 LangGraphChatRuntime） |
| `src/cygnusx/application/services/mas/mas_supervisor.py` | Supervisor 决策 LLM 适配（多 provider 容错） |
| `src/cygnusx/application/services/mas/mas_room_service.py` | 房间消息/run 账本/SSE 广播/plan 决议 |
| `src/cygnusx/api/v1/mas_rooms.py` | 4 个 endpoint（messages/stream/plan-decision） |
| `src/cygnusx/infrastructure/database/models/mas_room.py` | 3 张新表 ORM |
| `alembic/versions/masroom0001_add_mas_room_tables.py` | 迁移（down=cacheprice0001，已应用） |
| `frontend/src/views/DepartmentView.vue` | 部门页面（成员列表 + 时间线 + 输入区） |
| `frontend/src/stores/masRoom.ts` | Pinia store（fetch-stream SSE + 指数退避） |
| `tests/unit/test_mas_worker_policy.py` | worker_policy 单测 |

### 接线改动（调用点级别最小接线）

- `src/cygnusx/api/v1/router.py`：+2 行（import + include_router）
- `src/cygnusx/infrastructure/database/models/__init__.py`：+8 行（模型注册）
- `frontend/src/router/index.ts`：`/department` 路由
- `frontend/src/layouts/DefaultLayout.vue`：侧栏导航项

**隔离总验收**：受保护文件（chat_service/langgraph_runtime/request_preparation/agent_service/agent_context_builder/orchestrator_graph/langgraph_nodes/chat_sessions/chat_messages）在本会话**零改动**（git diff 中这些文件仅存施工前已有的 artifact_manifest 相关改动，grep MAS 代码 = 0）；既有 chat 链路 `tests/unit/chat/` **119 passed 全绿、零修改**。

## 各阶段验收证据

### 阶段 0：差异清单
`docs/info/26.9.21/MAS实施_阶段0差异清单.md`（3 项差异均已按手册上报处理）。

### 阶段 1：房间消息 + API + 前端骨架
- 3 表迁移应用（`masroom0001`）
- 3 个 endpoint 经 openapi 验证；消息落库/查询容器内冒烟通过（独立会话写库，DATA_OK msgs=55 runs=20）
- 前端 build 通过，`DepartmentView-*.js/css` chunk 编出；nginx 已重启

### 阶段 2：MAS 图核心（后端事件表为准）
- 完整 run：`run_started → mas_trace(派工，含理由) → assistant(agent-rnaseq 回复落库) → run_finished`，`mas_room_events` 表有全链路事件
- 熔断：max_rounds=3 测试中 supervisor 3 次派工后触顶强制收尾（ROUNDS 4 NEXT __finish__）
- 施工中发现并修复的坑：Supervisor 提示词 `{}` 未转义（KeyError）、解析器需容忍推理文本混 JSON（raw_decode 逐 `{` 尝试）、mas_trace role 需映射为 system（deepseek 只认 system/user/assistant）、worker 产出须显式落库

### 阶段 3：人工判断点（三分支全部通过）
- 触发：run 进入 `awaiting_review` + `plan_interrupted` 事件 + plan_card 落库（含查重防 interrupt 重放重复）
- **批准**：`plan_resumed → 按计划派工 → run_finished`（assistant 回复落库）
- **驳回**：`plan_resumed → 计划已驳回 trace → run_finished`，无执行
- **修改**：edited_plan 被采纳（"步骤A：质控（用户修改）"出现在派工 trace），按新计划执行
- checkpoint 挂 AsyncPostgresSaver（thread_id=run_id）；web 重启后可从 checkpoint 恢复（resume 时 build_mas_graph 显式挂同一 checkpointer）

### 阶段 4：打磨
- 故障注入：Worker 返回错误信封 → Supervisor 反复尝试 → 熔断收尾，run 不落死
- 并发红线：两个并发 POST 只新建 1 个 run、另一个正确复用（乐观锁生效）
- token usage：第一条 assistant 消息 metadata 带 `{total_tokens, prompt_tokens, completion_tokens, cached_tokens}`（TODO：并发 worker turn 的 per-turn 归属，阶段 5 改为返回值传递）

## 已知限制（阶段 5 范围）

1. Worker turn 并发时 token usage 归属为进程内单变量（注释标注）
2. SSE 多进程广播一致性（单 web 进程内 Queue 广播 + DB 轮询兜底）
3. 房间硬编码 `bioinfo-dept`（MVP 单房间）
4. 部分既有单测失败（76 个）源于施工前已存在的未提交改动（artifact_manifest 等）与环境差异（/data/omichu 路径、YAML prompts），与 MAS 建设零关联（全部失败文件不引用 MAS 代码）
5. 期间 cygnusx live 栈容器曾整体消失（非本会话操作，本会话只执行过 `docker restart cygnusx-web`），已用 `make docker-up` 恢复，数据无损

## 运维备忘

- 改 mas_* 后端代码后须 `docker restart cygnusx-web`
- 前端改动走 `make docker-dev-refresh`（nginx bind mount 的 dist inode）
- 页面入口：`/department`（侧栏"生物信息部门"）
