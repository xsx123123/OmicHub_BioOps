# Manager 人格分层实施手册：通用助手与部门经理共存

> 日期：2026-08-20
> 来源：拆自《AgentTeams部门协作架构评估与实现计划》Part 6，独立自包含，可直接交给编码 Agent（kimi code / Claude Code / CODEX 等）施工。
> 配套评估稿：`manager_role_bioinfo_department_manager_2026-08.md`
> 本手册回答：如何让 Manager 在 `/api/v1/chat`、`/api/v1/studio` 保持通用助手身份，同时在 `/api/v1/agent-teams` 协作室中以「生物信息部门经理」角色运行。

---

## 1. 评估结论（verdict）

**方向对，可以落地；核心机制是"共享底座不动 + 场景层注入角色"，与业界约定一致。**

- 三模式入口、API 前缀、服务类完全分离：`/api/v1/chat` → ChatService、`/api/v1/studio` → Studio 会话、`/api/v1/agent-teams` → AgentTeamsService + room_response_service。Manager 改动天然被约束在协作室链路内。
- 业界对应约定：CrewAI / AutoGen / MetaGPT 等主流多智能体框架的标准形态是**同一底座模型 + 每角色独立 system prompt**（role/goal/backstory），不为角色配独立模型；分层 prompt 架构（共享基座指令 + persona 层 + 运行时上下文，逐级覆盖带 fallback）也是平台级产品的通行做法。本手册的「展示层/称呼层/话术层/人格层」改动分层与之同构。
- **红线重申**：`data/ai/general.yaml` 与 `data/ai/prompts/general.md` 是三模式共享配置源，任何 Manager 个性化禁止落在这两个文件上。`bioops-manager` 安全/审计身份（token 配置、`require_role` 校验、Matrix 镜像身份）不改名。

## 2. 现状事实（改动锚点）

| 项 | 位置 | 说明 |
| --- | --- | --- |
| Manager LLM 人格 | `agentteams_room_response_service.py:66` `_PREFERRED_MANAGER_AGENT_ID = "agent-general"`（硬编码） | Manager 回复实际由 agent-general 生成 |
| 回退逻辑 | 同文件 `:1057-1068` | fallback 到 agent-general 时无降级行为定义 |
| Manager 房间话术 | 同文件 `:1153-1176` `_build_question()`（"扮演 Manager……"） | 仅协作室链路生效 |
| 称呼注入 | 同文件 `:1140` 「称呼自己为 {manager_name}」 | 后端兜底名 |
| 前端默认名 | `frontend/src/stores/agentTeamsPreferences.ts:21`（默认 `'Manager'`） | 与后端、展示后缀三处各自维护 |
| 展示后缀 | `AgentTeamsRoomView.vue:1508,1539`「· 生物信息部门经理」 | 已上线 |
| 共享配置源（禁区） | `data/ai/general.yaml`、`data/ai/prompts/general.md` | chat/studio/协作室三模式共用 |
| 安全身份 | `bioops-manager`（token 配置、`require_role`、Matrix 镜像） | 非 LLM agent，不改名 |

> 注意：以上行号基于 2026-08-20 的代码快照，施工前必须先确认仍然有效。

## 3. 三项必做补强（spec）

### 3.1 人格层独立 YAML（"部门经理化"成立的关键，非可选深化）

现状下 Manager 的 LLM 人格 = `agent-general`（archetype「好奇而结构化的研究顾问」），只有展示后缀与话术层在喊"扮演 Manager"——口吻、职责描述、自我认知仍是通用助手，用户在协作室长对话中会感知到人格分裂（话术说"我是部门经理"，行为像研究顾问）。

Spec：

- 新建 `data/ai/agentteams_manager.yaml`：`name: 生物信息部门经理`，archetype 改写为「客户经理/项目协调人」（对应 `AgentTeams_VISION_FINAL.md` §4.2 的编排者职责：接单、说明触发理由、选规划专家、审核计划、协调专家、点评结果、汇总交付）；`prompt_file` 指向新建的 `data/ai/prompts/agentteams_manager.md`，**禁止复用** `prompts/general.md`。
- 显式声明 `recruitable: false`——`general.yaml:42-50` 的通用助手是可招募专家，Manager YAML 若不声明，"部门经理"可能被招募进自己的团队当 Worker，造成角色混乱。
- capability registry 声明 `planner_eligible`（保持 Manager 作为规划入口的能力）。
- `agentteams_room_response_service.py:66` 的 `_PREFERRED_MANAGER_AGENT_ID = "agent-general"` 硬编码改为配置项（如 `agentteams.manager_agent_id`，默认 `agentteams-manager`）。
- **回退降级行为必须显式定义**（`:1057-1068` 现状无定义）：fallback 到 `agent-general` 时，话术层（`_build_question()` 的 Manager 身份段）继续生效、展示名不变，仅能力与人格底座降级；写审计事件 `room.manager_persona_fallback`（含原因与目标 agent_id），**禁止静默漂移**。

### 3.2 Manager 命名收敛为单一来源

现状三处各自维护：前端 `agentTeamsPreferences.ts:21` 默认 `'Manager'`、后端 `room_response_service.py:1140` 兜底名、前端 `AgentTeamsRoomView.vue:1508,1539` 展示后缀「· 生物信息部门经理」。三处漂移只是时间问题。

Spec：以后端 agent YAML 的 `display_name` 为唯一权威来源，通过协作室配置接口下发；前端 store 只存**用户手动覆盖值**（用户改名偏好），无覆盖时透传后端值；后端 `:1140` 兜底名与展示层后缀从同一字段派生，禁止第三处硬编码。

### 3.3 红线升级为 CI 守卫

文档级红线挡不住后续施工。增加快照回归测试：对 `/api/v1/chat` 与 `/api/v1/studio` 各固定一条最小请求，断言组装后的 system prompt 中**不含**任何 Manager/部门经理相关片段（「部门经理」「客户经理」「协作室」「扮演 Manager」等关键词表），且 persona 段与基线快照一致。任何 PR 修改 `general.yaml` 的 name/persona/prompt_file 或 `prompts/general.md` 导致 chat/studio 人格变化时，测试失败即拦截。

## 4. 编码 Agent 提示词（可直接粘贴）

```text
【任务性质】在现有代码基础上增量修改，禁止重构无关模块；先读代码再动手，
所有改动落点见下，改动前先确认这些行号仍然有效（若已漂移，找到新位置并说明）。

【目标】让协作室 Manager 拥有独立的「生物信息部门经理」LLM 人格，
同时保证 /api/v1/chat 与 /api/v1/studio 中的通用助手（agent-general）
行为与人格完全不变。

【实现内容】
1. 新建 data/ai/agentteams_manager.yaml：
   - name: 生物信息部门经理；recruitable: false（显式声明）；
   - archetype/职责描述对齐 AgentTeams_VISION_FINAL.md §4.2 的编排者职责；
   - prompt_file 指向新建的 data/ai/prompts/agentteams_manager.md，
     禁止复用或 include prompts/general.md；
   - 在 capability registry 中声明 planner_eligible。
2. src/omichub/application/services/agentteams_room_response_service.py：
   - :66 _PREFERRED_MANAGER_AGENT_ID 硬编码改为配置项
     agentteams.manager_agent_id（默认 agentteams-manager），配置加载失败时
     报错而非静默回退；
   - :1057-1068 回退逻辑补充降级行为：fallback 到 agent-general 时，
     _build_question() 的 Manager 身份话术继续生效、房间展示名不变，
     并写审计事件 room.manager_persona_fallback（payload 含原因、
     目标 agent_id、case_id）；
   - :1140 称呼注入改为读取 agent YAML 的 display_name，不再单独硬编码。
3. 命名单一来源：
   - 协作室配置接口下发 manager display_name；
   - frontend/src/stores/agentTeamsPreferences.ts:21 默认值改为 null
     （null = 透传后端值，非 null = 用户手动覆盖）；
   - AgentTeamsRoomView.vue:1508,1539 的展示后缀从同一字段派生。
4. CI 守卫：新增快照回归测试，对 /api/v1/chat 与 /api/v1/studio 各发一条
   固定最小请求，断言组装的 system prompt 不含 Manager/部门经理相关片段
   （关键词表：「部门经理」「客户经理」「协作室」「扮演 Manager」），
   且 persona 段与基线快照逐字一致。
5. 禁止事项：不得修改 data/ai/general.yaml 的 name/persona/prompt_file，
   不得修改 data/ai/prompts/general.md，不得给 bioops-manager 安全身份改名。

【交付要求】
- 每完成一项说明改了哪些文件、为什么；
- 验收权在用户手里，不接受自报通过；按下面的验收表逐条给出证据。
```

## 5. 验收表（用户可手工执行）

| # | 操作 | 期望现象 | 不通过时的处理 |
| --- | --- | --- | --- |
| 1 | 在 AI 助手（/ai）问「你是谁」 | 仍回答通用助手身份，无部门经理措辞 | 检查是否误改 general.yaml，回滚后重跑 |
| 2 | 在 AI 工作台发起会话 | system prompt 与改版前快照逐字一致 | 查看 CI 快照测试 diff，定位污染源 |
| 3 | 在协作室问 Manager「你的职责是什么」 | 以生物信息部门经理口吻回答（接单/协调/审核/汇总），无「研究顾问」人格残留 | 检查 agentteams_manager.yaml 是否被正确加载、prompt_file 是否指向新文件 |
| 4 | 临时把 agentteams.manager_agent_id 指向不存在的 agent | 触发 fallback：房间显示名不变、话术仍是 Manager，审计出现 room.manager_persona_fallback | 检查降级分支是否被静默吞掉 |
| 5 | 打开协作室招募专家面板 | 不出现「生物信息部门经理」选项 | 检查 recruitable: false 是否生效 |
| 6 | 修改 manager display_name 后刷新 | 房间头部、回复称呼、后端注入三处同步变化 | 检查是否仍有第三处硬编码 |
| 7 | 跑 CI 快照测试（编码 Agent 执行） | chat/studio 两条用例通过 | 不允许跳过测试合并 |

> 分工：#1–#6 由用户手测，#7 由编码 Agent 跑测试并给出输出。

## 6. 总 Checklist

- [ ] chat/studio 通用助手人格零变化（快照测试 + 手工「你是谁」）
- [ ] 协作室 Manager 口吻/职责真正部门经理化（人格层，非仅展示层）
- [ ] fallback 有降级行为 + `room.manager_persona_fallback` 审计，无静默漂移
- [ ] Manager 命名单一来源，前端覆盖机制可用
- [ ] `recruitable: false` 生效，Manager 不出现在可招募专家列表
- [ ] `general.yaml` / `prompts/general.md` 零改动（CI 守卫拦截验证）

## 7. 风险登记

| 风险 | 缓解 |
| --- | --- |
| 新 YAML 加载失败导致 Manager 无人格 | 配置加载失败直接报错 + fallback 审计事件 |
| 关键词表漏掉未来新增的 Manager 措辞 | CI 断言同时包含「persona 段逐字快照」兜底 |
| 用户已存的前端 managerName 偏好与新来源冲突 | 迁移期把非默认值视为用户覆盖，保留生效 |
| 行号漂移导致提示词锚点失效 | 施工前逐项确认位置，漂移则找新位置并在报告中说明 |
