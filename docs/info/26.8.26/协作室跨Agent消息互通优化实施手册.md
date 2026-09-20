# 协作室跨 Agent 消息互通优化实施手册

> 版本：v1（2026-08-26）
> 依据：《协作室跨 Agent 消息不可见排查报告》（2026-08-26，三断点定案）、
> 《AgentTeams 多智能体协作聊天优化报告》第八章（活文档）。
> 本文档给编码 Agent（Codex / Kimi Code）施工用：三个阶段各一份 paste-ready
> 提示词，验收标准写死，**验收权在平台方，不接受编码 Agent 自报通过**。

## 一、目标与背景

**目标**：让协作室内各 Agent 能获取同房间其他 Agent 的回复正文——
"MinIO Shared File System 的 Agent 间信息交换"从"写入侧存在"补全为
"读取侧实际可用"。

**排查定案的三层断点**（编码 Agent 施工前必读，均有代码证据）：

1. **工具面缺口**：直达会诊调用 `requested_tools=[]`，领域 Agent 没有任何
   读取房间消息的工具（`agentteams_room_response_service.py:786-797`）。
2. **room 命名空间死路**：未立项房间使用 `room-<room_id>` 命名空间
   （`agentteams_service.py:1432-1447`、`agentteams_room_response_service.py:312-328`），
   自省接口要求正式 Case，Agent 自查房间事件被拒。
3. **MinIO 读取侧未接线**：MinIO 保存了 LLM turn 记录（含 `reasoning_text`，
   `agentteams_turn_recorder.py:101-140`），但读取只服务 artifact/file
   （`agentteams_data_tool_service.py:71-112`），无按 room 命名空间读消息正文的通道。

**写入侧是好的，不要动**：用户消息入口（`agentteams.py:1056-1099`）、
Agent 回复写入（`agentteams_room_response_service.py:654-670、803-823`）、
Bridge AuditStore 持久化（`audit.py:227-245、331-350`）。

## 二、关键设计决策（施工前必读，不得偏离）

1. **上下文注入优先于工具**：阶段 0 在编排层上下文组装处直接注入房间历史
   正文——不依赖 Agent "想起要调工具"，100% 生效，是止血点；阶段 1 的工具
   是按需深挖（翻更早历史、读思考过程）的补充，两者都做。
2. **不放开 `case_facts_query` 的 Case-only 契约**：Bridge 刻意将 room
   命名空间排除在 Case 运营指标外（`audit.py:460-480`），这是刻意设计，
   三个阶段的施工都不得改变该指标口径。room 命名空间的查询走**对等只读
   通道**（阶段 2），不走放开限制。
3. **思考过程共享策略**：回复**正文默认共享**（进上下文、进工具返回）；
   **思考过程默认不进上下文**（token 成本高），由配置项
   `room_context_include_thinking`（默认 false）和工具参数
   `include_thinking`（默认 false）按需开启，数据源是 MinIO turn 记录的
   `reasoning_text`。注意 `room.agent_stream` 的思考增量本来就不进 MinIO
   （`audit.py:233-245`），本次不改动这个行为。
4. **数据源选型**：消息正文主数据源 = DB 房间消息存储
   （`room.user_message` / `room.agent_message`，结构化、便宜）；MinIO
   turn 记录仅作为思考过程的补充源。
5. **权限边界**：任何读取路径都只允许读取调用方**当前绑定的房间**，
   跨房间访问直接拒绝并返回明确错误码。
6. **每阶段端到端验收**：不接受只跑单测；凡"通了"的结论以后端物证
   （注入上下文日志 / 工具调用日志 / DB 与 MinIO 对象）为准。

## 三、施工顺序

| 阶段 | 内容 | 优先级 | 依赖 |
|---|---|---|---|
| 0 | 上下文组装注入房间消息历史（止血） | P0 | 无，可独立先上 |
| 1 | `room_messages_read` 只读工具 + 注册进会诊工具面 | P0 | 与阶段 0 可并行 |
| 2 | room 命名空间对等只读查询通道 | P1 | 建议阶段 1 之后 |

阶段 0 与 1 并行不冲突（一个改上下文组装、一个加工具）；阶段 2 的
room 事件时间线查询可复用阶段 1 工具的数据访问层。

---

## 四、阶段 0 提示词：上下文注入房间消息历史（整段复制）

```text
你是一名资深后端工程师。在现有多智能体协作平台（AgentTeams 协作室）基础上
做最小侵入修复，禁止重构无关模块。前置调查报告已定案断点位置，先读代码再动手。

## 背景

直达领域 Agent 的会诊上下文（agentteams_room_response_service.py:757-768）
当前只包含：Case 目标、Case 状态、最近 8 条房间事件
（_recent_event_context，920-935）、当前用户点名消息。事件 payload 不含
其他 Agent 的回复正文，导致 Agent 之间互相看不到对方回复。写入侧是好的：
room.agent_message 已持久化（654-670、803-823），本次不改写入侧。

## 任务：上下文组装处注入"房间消息历史"段

1. 在会诊上下文组装链路（757-768、920-935、2108-2240）中新增
   "房间消息历史"段：从房间消息存储（room.user_message /
   room.agent_message）读取当前房间最近 N 条消息（N 默认 20，可配置），
   按时间升序拼入 prompt，每条标注角色（用户 / Agent 名称）与内容正文。
2. 排除当前正在处理的这条点名消息，避免与现有"当前用户点名消息"段重复；
   与 _recent_event_context 的事件段并存，职责区分：事件段管状态流转，
   消息历史段管对话正文。
3. 思考过程默认不进上下文：仅在配置项
   room_context_include_thinking=true 时注入；默认 false。
4. Token 预算保护：历史段设总长度上限（默认约 4000 tokens，可配置），
   超出时从最早的消息开始截断，并保留一行"更早的 N 条消息已省略"占位；
   无历史时该段整体省略，不留空标题。
5. 对立项与未立项房间一视同仁：数据源是房间消息存储，不依赖正式 Case，
   不得走 case_facts_query。

## 验收（端到端，不接受只跑单测）

重放场景：@Agent-A 对话 → @Agent-B 对话 → 再 @Agent-A 问
"B 刚刚说了什么"。在上下文组装处加临时日志，打印实际注入的历史段，
确认：注入内容含 B 的回复正文、不含重复点名消息、无思考过程（默认配置）。
Agent-A 能正确复述 B 的内容。提交注入上下文样例（脱敏）与 A 的回复截图
/日志作为证据。

## 交付

改动文件清单、配置项说明（N、token 上限、include_thinking 的默认值与
配置位置）、端到端验证证据、回滚方式（配置开关可关闭该注入）。
```

---

## 五、阶段 1 提示词：room_messages_read 工具（整段复制）

```text
你是一名资深后端工程师。在现有多智能体协作平台（AgentTeams 协作室）基础上
做最小侵入改造，禁止重构无关模块。前置调查报告已定案断点位置，先读代码再动手。

## 背景

调查报告定案：直达会诊调用 requested_tools=[]
（agentteams_room_response_service.py:786-797），领域 Agent 无任何读取
房间消息的工具；MinIO 读取只服务 artifact/file
（agentteams_data_tool_service.py:71-112），无按 room 命名空间读消息
正文的通道；MinIO turn 记录含 reasoning_text
（agentteams_turn_recorder.py:101-140）。

## 任务

1. 新增只读工具 room_messages_read：
   - 参数：limit（默认 20，上限与服务端硬限对齐并显式校验）、before/after
     分页游标、include_thinking（默认 false）；
   - 数据源：房间消息存储（room.user_message / room.agent_message）；
     include_thinking=true 时按 room 命名空间从 MinIO turn 记录
     （agentteams_turn_recorder.py:101-140 写入的对象）补 reasoning_text；
   - 返回：消息数组（角色、Agent 标识、正文、时间戳、消息 id）+ 分页游标；
   - 权限：只允许读取调用方当前绑定的房间；传入其他 room_id 直接拒绝，
     返回明确错误码（不得返回空列表冒充"没有消息"）。
2. 读取层扩展：在 agentteams_data_tool_service.py:71-112 新增按 room
   命名空间读取消息/turn 记录的路径，与既有 artifact 读取并存，不改动
   artifact 读取行为。
3. 注册进工具面：修复 agentteams_room_response_service.py:786-797 的
   requested_tools=[]，为会诊调用的领域 Agent 注入 room_messages_read
   （只读工具，不触碰审批门禁）；同时检查工具注册表与角色过滤逻辑，
   确认该工具不会被角色白名单过滤掉——把过滤链路读一遍并说明结论。
4. 契约一致性：分页上限、字段枚举、错误码语义在调用方/服务方两侧一致；
   非 2xx 不得被抹平成"暂时不可用"之类的模糊文案。

## 验收（端到端，不接受只跑单测）

重放三 Agent 场景：@Agent-A、@Agent-B 各对话一轮后，@Agent-C 问
"A 和 B 分别说了什么"——C 应通过 room_messages_read 拿到两者正文并
正确复述。另需验证：跨房间读取被拒且错误码明确；include_thinking=true
能取到 turn 的 reasoning_text；limit 超上限被显式拦截。提交工具调用
日志与返回样例作为证据。

## 交付

改动文件清单、工具 schema 说明、注册链路说明（含角色过滤链路的阅读结论）、
端到端验证证据、回滚方式。
```

---

## 六、阶段 2 提示词：room 命名空间对等只读通道（整段复制）

```text
你是一名资深后端工程师。在现有多智能体协作平台（AgentTeams 协作室）基础上
做最小侵入改造，禁止重构无关模块。前置调查报告已定案位置，先读代码再动手。

## 背景

未立项房间使用 room-<room_id> 命名空间（agentteams_service.py:1432-1447、
agentteams_room_response_service.py:312-328），自省接口要求正式 Case，
Agent 查询房间事件被拒（"scope 必须是正式 Case"）。注意：Bridge 刻意将
room 命名空间排除在 Case 运营指标外（audit.py:460-480）——这是刻意设计，
本次施工不得改变该指标口径。

## 任务

1. 自省/事件查询层新增 room 命名空间对等只读路径：scope=room 时不走
   拒绝分支，路由到房间事件流（Bridge audit 的 room 事件 + 房间消息
   记录）的只读查询；返回结构与 Case 查询对齐（事件时间线、消息列表），
   数据访问层尽量复用 room_messages_read 的既有实现。
2. 锁定刻意设计：在 audit.py:460-480 附近补注释说明"room 命名空间查询
   不计入 Case 运营指标"是有意约束，并加回归测试锁定该口径。
3. 拒绝文案可行动化：case_facts_query 遇到 room 命名空间时，错误文案
   从死路提示改为引导（如"房间未立项，请使用 room 命名空间查询
   room_facts / room_messages_read"）。
4. 立项衔接：房间立项为正式 Case 后，历史 room 事件在新 Case 视角下
   可追溯。先给方案（只读投影 vs 一次性迁移）经确认后再实现。

## 验收（端到端）

未立项房间内 Agent 查询自身房间事件/消息成功；Case 运营指标不含 room
数据（回归测试通过）；立项后历史 room 事件可追溯；不再出现
"必须是正式 Case"的死路文案。提交查询日志、回归测试结果与立项前后
对照证据。

## 交付

改动文件清单、room 查询路径与 Case 查询路径的关系图、立项衔接方案
（含选择理由）、回归测试清单、端到端验证证据。
```

---

## 七、人工验收 checklist（平台方执行）

**阶段 0：上下文注入**

| 操作 | 期望现象 | 不通过时的处理 |
|---|---|---|
| @A 对话 → @B 对话 → @A 问"B 说了什么"（用户手测） | A 正确复述 B 的回复内容 | 要注入上下文日志，确认断在读取还是拼接 |
| 检查注入日志（编码 Agent 提供） | 历史段含 B 正文、无思考过程、无重复点名消息 | 退回阶段 0 任务 2/3 |
| 长房间（>20 条消息）再测一次（用户手测） | 出现"更早的 N 条已省略"占位，回复仍正常 | 检查 token 预算截断逻辑 |

**阶段 1：room_messages_read 工具**

| 操作 | 期望现象 | 不通过时的处理 |
|---|---|---|
| @C 问"A 和 B 分别说了什么"（用户手测） | C 正确复述两者内容，工具卡片可见 room_messages_read 调用 | 查 requested_tools 注册与角色过滤链路 |
| 让 Agent 读思考过程（用户手测） | include_thinking=true 时能给出对方思考摘要 | 查 MinIO turn 记录读取路径 |
| 跨房间读取（编码 Agent 构造测试） | 明确错误码，非空列表 | 退回权限校验实现 |

**阶段 2：room 命名空间查询**

| 操作 | 期望现象 | 不通过时的处理 |
|---|---|---|
| 未立项房间让 Agent 自查房间事件（用户手测） | 查询成功，不再报"必须是正式 Case" | 查 room 对等路径路由 |
| 立项后再查历史（用户手测） | 立项前的事件在新 Case 视角可追溯 | 查立项衔接方案落地 |
| 运营指标核对（编码 Agent 跑回归测试） | room 数据不进 Case 指标 | 不得通过，刻意设计被破坏 |

**端到端总验收**

- [ ] 完整复现原始故障场景（三 Agent 互相复述），全部通过——即本手册
      要解决的最小闭环

## 八、与既有文档的关系

- 排查依据与核对 checklist：《AgentTeams 多智能体协作聊天优化报告》第八章
  （含 H1~H4 假设，本手册对应 H1/H3 被证实后的施工方案）；
- 关联手册：《L4 协作室 × 文件系统融合优化实施手册》的 Case 绑定项目改造
  与本手册阶段 2 的"立项衔接"有交集，施工时交叉对齐，避免两边各修一半；
- 完成本手册后：协作室具备"写得出（已有）、读得回（阶段 0/1）、查得到
  （阶段 2）"的完整 Agent 间信息交换闭环。
