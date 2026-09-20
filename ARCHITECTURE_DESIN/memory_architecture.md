# CygnusX AI 记忆系统当前架构

> 更新时间：2026-08-22  
> 文档定位：记录仓库当前已经落地的 AI 记忆系统架构、数据流、开关和回滚边界。  
> 相关实施计划：`docs/info/26.8.18/CygnusX记忆系统优化实施计划.md`  
> 最新变更（2026-08-22）：`docs/info/26.8.22/CygnusX记忆模块优化实施手册.md`（M0 settle 泄漏面封堵 / M1 v2 共享分区召回修复 / M2 L4 读取面接入 / M3 L4 写入纪律）；终验收口：`docs/info/26.8.22/记忆系统终验与收口待办-2026-08-22.md`（`memory.settle_skipped` 升级 OTel 计数器、新增 `memory.l4_inject_degraded` 降级计数、M0–M3 单测证据清单补齐，见 §11）

## 1. 一页结论

CygnusX 的记忆系统目前采用**自研 PostgreSQL + pgvector 薄层**，不依赖
mem0。系统处于 v2 灰度阶段：

- `memory_v2_enabled=False`：保留 `agent_memories` 旧链路，作为兼容和回滚路径。
- `memory_v2_enabled=True`：使用 `memory_blocks` 常驻记忆块、`memory_facts` 事实召回和
  增量 settle 任务。
- Studio 工作区记忆采用文件正统：`MEMORY.md` 是索引，`.memory/` 保存正文，正文通过
  `workspace_read` 懒加载。
- 事实读写通过 `FactStore` 抽象，当前实现为 `PostgresFactStore`，为未来切换其他向量
  存储保留逃生口。
- 用户记忆和工作区记忆都以不可信用户上下文注入，不能覆盖系统提示词、安全策略或工具权限。
- scope 语义定型：`profile`/`preference` 属于跨 Agent 共享分区（写入归一为
  `agent_id=""`）；`project`/`summary`/`memory_block` 属于当前 Agent 分区（隔离）。
  召回侧两路合并：共享分区 + 当前 Agent 分区，共享结果优先、按 id 去重（2026-08-22 M1 修复，
  此前召回侧按当前 Agent 精确匹配，共享层永远查不到）。
- AgentTeams 协作室（L4）已接入记忆：Manager 主回路与 tool_execute 分支注入
  共享层 + Manager 分区记忆；会诊 prompt 追加 L4 版写入纪律；AgentTeams 合成会话
  不进入 settle 通道（2026-08-22 M0/M2/M3）。

当前不是“所有入口统一 Runtime”的架构。普通聊天、Studio 和 AgentTeams 仍由各自的
执行路径装配上下文；记忆能力通过服务层和提示词装配点接入这些入口。

## 2. 当前拓扑

```text
用户消息
   │
   ├─ ChatService
   │    ├─ AgentMemoryService.build_prompt_context()
   │    │    ├─ v2 off → agent_memories 旧召回
   │    │    └─ v2 on  → memory_blocks + memory_facts（共享分区 + 当前 Agent 两路合并）
   │    ├─ 系统提示词装配
   │    │    └─ v2 on 追加“记忆写入纪律”
   │    └─ 会话消息达到阈值/删除会话
   │         └─ Celery settle_session_memory
   │              （AgentTeams 合成会话在入口与任务体双重排除）
   │
   ├─ AgentMemoryToolService
   │    ├─ cygnusx_save_memory
   │    ├─ cygnusx_update_memory_block（v2 乐观锁）
   │    ├─ cygnusx_search_memory
   │    └─ cygnusx_forget_memory
   │
   ├─ AgentTeams 协作室（L4）
   │    ├─ Manager 主回路 / tool_execute 分支
   │    │    └─ v2 on → build_prompt_context_v2 注入共享层 + Manager 分区
   │    │       （@专家直答与会诊子 Agent 不注入）
   │    └─ 会诊 system prompt
   │         └─ v2 on 追加 L4 版“记忆写入纪律”三条
   │
   └─ OmicStudio
        ├─ MEMORY.md → 每轮系统提示词注入索引
        ├─ .memory/*.md → workspace_read 按需读取
        ├─ cygnusx_workspace_remember → 正文 + 索引
        └─ Git checkpoint → 工作区版本恢复
```

## 3. 代码职责边界

| 层 | 主要文件 | 职责 |
| --- | --- | --- |
| 应用服务 | `src/cygnusx/application/services/agent_memory_service.py` | 记忆校验、旧/v2 读写分流、提示词上下文组装、敏感信息过滤 |
| 工具服务 | `src/cygnusx/application/services/agent_memory_tool_service.py` | 将模型工具调用映射到应用服务和命名记忆块更新 |
| 存储抽象 | `src/cygnusx/infrastructure/memory/fact_store.py` | `FactStore` 协议与 PostgreSQL 实现 |
| 数据模型 | `src/cygnusx/infrastructure/database/models/agent_memory.py` | 旧表、`memory_blocks`、`memory_facts`、settlement 模型 |
| 异步沉淀 | `src/cygnusx/infrastructure/celery_app/tasks/memory.py` | 旧数据迁移、向量回填、增量事实抽取与幂等 settle |
| 聊天装配 | `src/cygnusx/application/services/chat_service.py` | 记忆提示词、写入纪律、settle 任务投递（含 AgentTeams 合成会话排除） |
| L4 房间装配 | `src/cygnusx/application/services/agentteams_room_response_service.py` | Manager 问题装配时注入共享层 + Manager 分区记忆（v2 on） |
| L4 会诊装配 | `src/cygnusx/application/services/agent_consultation_service.py` | 会诊 system prompt 追加 L4 版记忆写入纪律（v2 on） |
| Studio 上下文 | `src/cygnusx/application/services/studio_context_service.py` | `AGENTS.md`、`MEMORY.md` 读取与不可信包装 |
| Studio 工具 | `src/cygnusx/application/services/studio_tools.py` | `cygnusx_workspace_remember` 和工作区文件操作 |
| Studio 检查点 | `src/cygnusx/application/services/studio_checkpoints.py` | Git 快照、密钥排除、单文件大小限制、恢复 |
| 工具授权 | `data/ai/tools/memory.yaml` | Agent 可用的跨会话记忆工具包 |
| 数据迁移 | `alembic/versions/m5n6o7p8q9r0_add_memory_v2_tables.py` | v2 表与 HNSW 索引 |
| 数据迁移 | `alembic/versions/n6o7p8q9r0s1_add_memory_settlement_cursor.py` | 增量游标与 settle 幂等表 |

## 4. 数据分层

### 4.1 旧归档层：`agent_memories`

旧表保留用于 v2 灰度期间的兼容和回滚。v2 关闭时，`AgentMemoryService` 继续使用旧表的
关键词/语义降级召回和旧的使用频次排序；v2 打开后，新的保存和搜索走 `memory_facts`。

旧表不应再作为 v2 新功能的直接写入目标。阶段 4 完成前不删除，以便：

1. 灰度期间快速关闭 `memory_v2_enabled`；
2. 旧用户数据迁移失败时重新执行迁移；
3. 对照新旧召回结果排查质量问题。

### 4.2 常驻层：`memory_blocks`

`memory_blocks` 保存 Agent 策展后的短小、稳定记忆。唯一键为：

```text
(user_id, agent_id, block_name)
```

当前块名称和容量约定：

| 块名 | 用途 | 默认容量 |
| --- | --- | ---: |
| `profile` | 用户身份、研究背景、稳定能力偏好 | 1500 字符（仅迁移初始化时生效；ORM 列默认 `char_limit=2000`，见 `agent_memory.py` 模型定义） |
| `preferences` | 工具、分析方法、输出格式等持久偏好 | 2000 字符 |
| `current_focus` | 当前项目或近期持续任务焦点 | 已预留，当前无创建路径 |

> `current_focus` 仅出现在 `update_memory_block` 的块名白名单中
> （`agent_memory_service.py:330`、`agent_memory_tool_service.py:135`），存量数据迁移
> （`tasks/memory.py:157-174`）只创建 `profile`/`preferences` 两块；对其调用更新永远命中
> `NotFoundError("记忆块不存在，请先完成记忆迁移")`。

块使用 `version` 做乐观锁。更新工具必须携带 `expected_version`，并使用条件更新：

```sql
UPDATE memory_blocks
SET content = :content, version = :expected_version + 1
WHERE id = :id AND version = :expected_version;
```

更新冲突时返回最新内容和版本，模型基于最新内容重试，而不是覆盖并发修改。

### 4.3 召回层：`memory_facts`

`memory_facts` 保存可语义召回的事实，核心字段包括：

- `user_id`、`agent_id`：数据隔离边界（分区语义见下）；
- `scope`：`profile`、`preference`、`project`、`summary`；
- `content`、`keywords`：事实正文和辅助检索词；
- `embedding vector(1024)`：pgvector 向量；
- `status`：`active`、`superseded`、`archived`；
- `source_session_id`、`source_message_ids`：来源溯源；
- `content_hash`：幂等去重键；
- `superseded_by`：事实修正关系；
- `created_at`、`last_recalled_at`：时间排序和召回观测字段（`last_recalled_at` 当前未接线——
  `PostgresFactStore.touch_recalled` 已定义于 `fact_store.py:135`，但全仓无调用点，
  v2 召回路径从不写该字段）。

当前迁移创建 HNSW cosine 索引，并在 `(user_id, agent_id, content_hash)` 上建立唯一约束。

**分区语义（2026-08-22 定型）**：

| scope | 分区 | 说明 |
| --- | --- | --- |
| `profile` / `preference` | 共享分区 `agent_id=""` | 跨 Agent 共享；保存工具传 `agent_id=None`，写入归一为 `""` |
| `project` / `summary` | 当前 Agent 分区 | 按执行 Agent 隔离，不被其他 Agent 召回 |

`memory_blocks` 遵循同一约定：`profile`/`preferences` 块在共享分区，Agent 策展块
（如 `current_focus`）在各自 Agent 分区。

## 5. 记忆读取链路

### 5.1 v2 关闭：兼容路径

```text
build_prompt_context()
   ├─ profile + preference
   │    └─ 旧表按 use_count / updated_at 取最多 10 条
   ├─ project + summary
   │    └─ 旧表关键词或语义降级召回最多 5 条
   ├─ 去重
   ├─ 标记旧表使用状态
   └─ 3200 字节预算内拼接
```

该路径的目的不是继续扩展旧架构，而是保证 v2 灰度期间可以无损回退。

### 5.2 v2 打开：常驻块 + 事实召回（两路合并）

```text
build_prompt_context_v2(user_id, agent_id, message)
   │
   ├─ 查询该用户的 memory_blocks
   │    └─ 共享分区（agent_id=""）+ 当前 Agent 分区，共享层块排前，全量注入非空块
   │
   ├─ 对当前消息生成 embedding
   │    └─ _search_facts_merged() 两路召回：
   │         共享分区（agent_id=""，profile/preference 优先）+ 当前 Agent 分区
   │         同一事实两路命中时按 id 去重
   │
   ├─ 对每条事实计算：
   │    similarity × exp(-lambda × age_days)
   │
   ├─ 取排序前 5 条
   │    └─ 添加“记于 N 天前”时效标记
   │
   ├─ 包裹在 <user_memory> 不可信边界
   └─ 3200 字节预算内截断
```

`search_memory` 工具同样走两路合并召回（共享分区结果在前，截断到 limit）。
写入侧不变：profile/preference 归一写入共享分区，其余 scope 写入当前 Agent 分区。

注入内容的优先级永远低于当前用户消息、系统提示词、安全规则和工具权限。记忆正文中的
XML、HTML、代码和比较符号必须原样保留，不进行字符替换。

### 5.3 AgentTeams 协作室（L4）读取面

```text
房间用户消息
   │
   ├─ Manager 主回路 / tool_execute 分支
   │    └─ _build_memory_context()
   │         ├─ v2 off → 返回空串，行为与接入前一致
   │         └─ v2 on  → build_prompt_context_v2(requester, manager_agent_id, 消息)
   │              注入共享层 + Manager 分区，装配进 _build_question，
   │              位于“请求人最新发言”之前；装配异常降级为空注入，不阻断房间回复
   │
   └─ @专家直答 / 会诊子 Agent
        └─ 不注入（purpose-shaped 裁剪，专家按四段契约干活）
```

Case 事实源永远是事件流 + 血缘；长期记忆只承载“关于人的软偏好”。Case 临时事实
（样本/分组/路径/中间决策）永不进 `memory_facts`。

## 6. 记忆写入链路

### 6.1 模型主动保存

`memory.yaml` 当前授权以下工具：

| 工具 | v2 行为 |
| --- | --- |
| `cygnusx_save_memory` | 写入 `memory_facts`，使用 `FactStore.insert` 去重 |
| `cygnusx_update_memory` | v2 下拒绝旧式整条更新，引导使用事实新增或记忆块更新 |
| `cygnusx_update_memory_block` | 对命名块执行容量校验和乐观锁更新 |
| `cygnusx_search_memory` | v2 下通过 embedding 检索 `memory_facts` |
| `cygnusx_forget_memory` | 将事实或旧记忆标记为 archived，不物理删除 |

写入前执行：

1. scope、长度、关键词和置信度校验；
2. API Key、Token、密码、Bearer 凭据等敏感信息拦截；
3. v2 开关分流；
4. 事实通过内容哈希做幂等去重。

### 6.2 会话异步沉淀

```text
消息累计达到 memory_settle_min_new_messages / 删除会话
   │
   ├─ 入口排除（2026-08-22 M0）：AgentTeams 合成会话不投递
   │    └─ mode=="agentteams" 或 status=="system"
   │       或 session_id 前缀 "agentteams:" 任一命中即跳过
   │
   └─ enqueue settle_session_memory(session_id)
          │
          ├─ 任务体双保险：命中同一判定（is_agentteams_synthetic_session）
          │    → 幂等返回 skipped_agentteams + 落 memory.settle_skipped 日志，
          │      不写 settlement、不动游标（防御未来新投递点绕过入口）
          ├─ 读取 last_settled_message_id 之后的新消息
          ├─ 少于阈值 → 不调用模型
          ├─ 生成 range_key(session_id:start_id:end_id)
          ├─ memory_settlements 已存在 → 幂等返回
          ├─ LLM 仅抽取持久事实 JSON 数组
          ├─ embedding + FactStore.insert
          ├─ 识别“改成/不再/以后别”等修正语义
          │    └─ 旧事实 superseded，新事实 active
          └─ 更新 chat_sessions.last_settled_message_id
```

闲聊或抽取失败时不应凭空写入事实。settle 任务只处理游标之后的消息，不重复全量扫描会话。
AgentTeams 合成会话（`agentteams_usage_service` 为扣费落账创建，`mode=agentteams`、
`status=system`、`agent_id=NULL`）承载的是 Case 过程对话，其事实源是事件流与血缘，
任何标记命中都不允许进入长期记忆 settle 通道。

### 6.3 记忆写入纪律

v2 开启时，ChatService 会把以下规则追加到系统提示词（`chat/configuration.py:190-195`
`MEMORY_V2_WRITE_DISCIPLINE`，共 3 条）：

- 只记录用户明确陈述的持久偏好、纠错或长期项目事实；
- 不记录一次性任务、临时上下文、未经确认的推测、凭据和隐私；
- 更新命名块前先读取当前内容，增量修改并携带版本。

第 4 条语义“用户当前对话与旧记忆冲突时，以当前对话为准”不在写入纪律常量中，
实际位于 `<user_memory>` 注入头（`agent_memory_service.py:442`，v1 兼容路径见
`agent_memory_service.py:431`），随记忆上下文一并注入。

L4 会诊另有独立的三条纪律（2026-08-22 M3，装配于
`agent_consultation_service._build_instruction`，v2 off 不追加），与 ChatService 版
各自维护、不互相照搬：

- 只记录甲方明确陈述的持久偏好与纠错——一次性任务细节、临时上下文、未经确认的
  推测不进长期记忆，因为它们只对当前 Case 有意义；
- Case 事实（样本/分组/文件路径/中间决策）禁止写入长期记忆——要查历史用血缘与
  `case_facts_query`，因为记忆会漂移、血缘与事件流不会；
- 写入前先 `cygnusx_search_memory` 查重，避免同一事实多版本漂移。

## 7. Studio 文件型工作区记忆

### 7.1 文件契约

```text
/workspace/
├── AGENTS.md       # 项目约定，现有逻辑保持不变
├── MEMORY.md       # 记忆索引，最多 200 条、最多注入 8000 字符
└── .memory/
    ├── 2026-08-18-rnaseq-normalization.md
    └── 2026-08-18-sample-batch-effect.md
```

`MEMORY.md` 每轮注入 Studio 系统提示词，并包裹为 `<workspace_memory>` 语义下的用户上下文。
`.memory/` 正文不自动注入；模型必须通过 `workspace_read` 按需读取。

### 7.2 写入事务

`cygnusx_workspace_remember(title, summary, content)` 执行：

1. 创建 `.memory/`；
2. 根据日期和标题生成 slug 文件名；同名文件追加序号，避免覆盖；
3. 写入 Markdown 正文；
4. 追加 `MEMORY.md` 索引行；
5. 任一步失败则恢复正文和索引原状。

索引达到 200 条后拒绝继续追加，并提示模型先合并精简。工具写入正文时保留 HTML、代码和
比较表达式，不做安全字符替换；文件路径由工具固定生成，不接受模型传入任意绝对路径。

### 7.3 Git 检查点

Studio 工作区使用 Git 作为文件型记忆的版本检查点：

- 检查点前确保 `.gitignore` 排除 `input/`、`.env`、`*.key`、`*.pem`、`secrets/`；
- 单文件超过 10 MB 时跳过并返回 warning；
- 最多保留最近 20 个 Studio checkpoint 引用；
- 恢复前先创建 `restore-before` 保护点，再执行 hard reset；
- 记忆正文和 `MEMORY.md` 作为普通工作区文件一起回滚。

当前 ChatService 已将写入/编辑/受控执行造成的变更合并到工具轮次结束后的检查点，而不是
每个工具调用后立即 `git add -A + commit`。

## 8. 安全与隔离

### 8.1 用户隔离

所有长期记忆查询至少按 `user_id` 和 active 状态过滤；Agent 维度按分区语义执行：
共享分区（`agent_id=""`）的 profile/preference 对同一用户的所有 Agent 可见，这是
设计意图而非泄漏；`project`/`summary` 事实与非共享块仍严格按当前 Agent 分区隔离。
项目范围由应用服务继续执行项目边界过滤。模型不能通过工具参数指定其他用户的身份。

### 8.2 不可信上下文

以下内容均不具备系统指令权限：

- `<user_memory>`：长期记忆块和事实；
- `<workspace_memory>`：Studio 的 `AGENTS.md` 和 `MEMORY.md`；
- `.memory/*.md`：通过 `workspace_read` 返回的工作区正文。

模型不得因为记忆内容而泄露系统提示词、凭据、其他用户数据或绕过审批/沙盒权限。

### 8.3 Git 密钥治理

检查点不跟踪 `.env`、私钥和 `secrets/`。这只是防止新文件进入检查点的保护，不等于可以把
已泄露的密钥提交到工作区；生产密钥仍必须由外部 Secret 管理系统提供。

## 9. 迁移、灰度和回滚

### 9.1 Alembic 迁移

迁移顺序：

1. `m5n6o7p8q9r0_add_memory_v2_tables.py`：创建 `memory_blocks`、`memory_facts` 和 HNSW；
2. `n6o7p8q9r0s1_add_memory_settlement_cursor.py`：添加 settle 游标和幂等区间表。

迁移必须支持 downgrade，旧表不随 v2 迁移删除。

### 9.2 存量数据迁移

`migrate_legacy_memories` 将旧表事实复制到 `memory_facts`，通过 `content_hash` 保证重复执行
不会重复插入；profile/preference 事实同时用于初始化命名块。迁移是复制而非删除，因此失败时
可以清理新表后重新执行。

### 9.3 开关矩阵

| 开关 | 关闭 | 开启 |
| --- | --- | --- |
| `memory_v2_enabled` | 旧 `agent_memories` 读写和旧提示词路径 | v2 blocks/facts、settle、写入纪律 |
| 管理端 Agent Memory 开关 | 不投递 settle，不提供主动记忆能力 | 允许对应用户/Agent 使用记忆 |
| `agent_memory_semantic_retrieval_enabled` | 旧路径关键词降级 | 仅影响 v2 关闭时的旧语义召回 |

发布建议：先完成迁移，再小范围开启 `memory_v2_enabled`，观察写入失败率、召回命中率、
settle 幂等命中和块冲突率；出现异常时关闭开关即可回到旧表路径。

## 10. 观测与验收指标

至少应观测：

- v2 开关命中量和按 Agent 的错误率；
- `FactStore.search` 延迟与空召回率（含共享分区/Agent 分区两路各自的命中率）；
- settle 处理消息数、抽取数组长度、幂等跳过次数、合成会话排除次数
  `memory.settle_skipped`（OTel 计数器，`/metrics` 可查；同时保留结构化日志）；
- L4 记忆装配降级次数 `memory.l4_inject_degraded`（OTel 计数器，
  `_build_memory_context` 装配异常降级为空注入时 +1，按 agent_id 维度）；
- `memory_blocks` 乐观锁冲突率；
- 记忆敏感信息拦截次数；
- 记忆注入字节超限率（3200 字节预算截断触发次数）；
- Studio checkpoint 数量、跳过文件数量和 restore 成功率；
- 旧路径与 v2 路径的提示词字节预算是否超限。

验收重点：

1. v2 关闭时旧行为可用；
2. v2 开启时块内容原样注入、事实带时效标注；
3. 同一区间 settle 重试不新增重复事实；
4. 用户纠正事实后旧事实 superseded、新事实 active；
5. Studio 的 `MEMORY.md` 和 `.memory/` 可写入、可检查点、可恢复；
6. 记忆中含 HTML/代码时不发生字符污染。

## 11. 当前实现状态与后续边界

### 已落地

- pgvector `vector(1024)` 新表和 HNSW 索引；
- `FactStore` 抽象及 PostgreSQL 实现；
- v2 常驻记忆块、事实召回、时间衰减排序；
- 增量 settle 游标、区间幂等和事实 superseded；
- `cygnusx_update_memory_block` 乐观锁；
- Studio `MEMORY.md` / `.memory/` 和工作区记忆工具；
- 检查点密钥排除、10 MB 文件限制和恢复保护点；
- mem0 引擎文件及依赖已从当前代码路径移除；
- （2026-08-22 M0）AgentTeams 合成会话 settle 排除：入口双点 + 任务体双保险 +
  operational 级口径（`memory.settle_skipped` OTel 指标计数 + 结构化日志）；
- （2026-08-22 M1）v2 共享分区召回两路合并：`search_memory` 与 `build_prompt_context_v2`
  的 facts、memory_blocks 均纳入共享层，去重且共享优先；
- （2026-08-22 M2）L4 房间读取面：Manager 主回路与 tool_execute 分支注入共享层 +
  Manager 分区记忆，专家分支零注入；装配异常降级为空注入并计
  `memory.l4_inject_degraded`（OTel 计数器，按 agent_id 维度）；
- （2026-08-22 M3）L4 会诊 system prompt 三条记忆写入纪律（v2 on 时追加）。

### 单测证据（2026-08-22 收口；数字为 2026-09-11 实测复跑）

命令：`pytest tests/unit/test_agent_memory_tasks.py tests/unit/test_agent_memory_service.py tests/unit/test_agentteams_room_response_service.py tests/unit/test_agent_consultation_service.py -q`，
结果 **118 passed / 5 failed**（5 个失败均在 `test_agent_consultation_service.py`，与本模块无关：
3 个为 HEAD 上即红的 evidence_projection 系列；新增 2 个 `test_workspace_consultation_*` 失败，
即 `test_workspace_consultation_uses_scoped_workdir` 与
`test_workspace_consultation_allowed_for_declared_expert`）。
2026-08-22 收口时点快照为 97 passed / 3 failed。

- M0（`test_agent_memory_tasks.py`）：入口排除 3 例参数化
  `test_settle_entries_skip_agentteams_synthetic_sessions`、任务体双保险
  `test_settle_task_body_skips_agentteams_synthetic`、回归
  `test_normal_session_settle_behavior_unchanged` 与 `test_v2_off_never_enqueues_settle`；
- M1（`test_agent_memory_service.py`）：两路合并
  `test_v2_search_merges_shared_partition_across_agents`、分区隔离
  `test_v2_search_keeps_agent_partition_isolated`、共享去重
  `test_v2_search_dedupes_when_current_agent_is_shared_partition`、上下文合并
  `test_v2_prompt_context_merges_shared_blocks_and_facts`；
- M2（`test_agentteams_room_response_service.py`）：共享 + Manager 分区装配
  `test_memory_context_uses_shared_plus_manager_partition`、不含其他 agent 分区
  `test_memory_context_excludes_other_agent_partitions`、v2 关零注入
  `test_memory_context_empty_when_v2_off`、降级不阻断
  `test_memory_context_failure_does_not_break_room_reply`、装配点
  `test_build_question_injects_memory_context_when_provided`；
- M3（`test_agent_consultation_service.py`）：v2 on 追加纪律
  `test_build_instruction_includes_l4_memory_write_discipline_when_v2_on`、v2 off 不追加
  `test_build_instruction_omits_memory_discipline_when_v2_off`。

### 尚未完全收口

- `memory_v2_enabled` 默认仍为关闭，需要经过实际灰度后再调整默认值；
- 旧 `agent_memories` 表和部分 legacy 配置仍保留，等待阶段 4 清理窗口；
- `last_recalled_at` 的生产级 Redis 缓冲/批量 flush 还需要独立完成和压测；
- 迁移任务和真实 Postgres/pgvector 环境的升级、降级演练需要在部署环境执行；
- 记忆质量指标和召回对照实验尚未形成完整监控面板（敏感拦截次数、注入字节超限率
  待接入面板）；
- M4 总验收（E2E-18：跨层召回贯通手测、Case 事实零泄漏核查、settle 排除审计、
  专家零注入取证）需在 staging 环境执行，验收权在用户。

## 12. 修改指南

新增记忆功能时遵守以下顺序：

1. 先判断属于命名块、语义事实还是 Studio 文件记忆；
2. 业务层只依赖 `AgentMemoryService` 或 `FactStore`，不要直接操作新表；
3. 新数据库字段必须增加可 downgrade 的 Alembic 迁移；
4. 所有注入内容必须经过不可信上下文包装；
5. 不要在请求路径逐条更新召回统计；
6. 保留 `memory_v2_enabled=False` 时的回滚行为，直到阶段 4 明确关闭旧链路；
7. 同步更新本文件、`docs/adr/0001-memory-storage.md` 和相关测试。

