# Manager 角色定位评估：生物信息部门经理

> 日期：2026-08-20
> 结论：**契合现有架构，可以落地；且只要改动落在正确的层，通用助手在 AI 助手 & AI 工作台模式下的运行完全不受影响。**

## 1. 评估结论

将 AgentTeams 协作室中的 Manager agent 定位为「生物信息部门经理」**不是新方向，而是既定架构方向的措辞落地**：

- `agentteams_department_collaboration_architecture_2026-08.md`（部门协作评审稿）本就提出：用户是甲方，Manager 是客户经理/项目协调人，领域 Agent 是部门负责人。
- `data/ai/update/AgentTeams_VISION_FINAL.md` §4.2 明确：Manager 是编排者——接单、说明触发理由、选规划专家、审核计划、协调专家、点评结果、汇总交付。

「生物信息部门经理」准确描述了 Manager 的实际职能（分解生信任务、组建 Worker 团队、把关节键步骤），优于泛化的「管家」。

## 2. 现状事实：Manager 的两层身份

### 2.1 安全/审计身份 `bioops-manager`（非 LLM agent）

- `integrations/agentteams/teams/bioops-delivery.yaml:10-13` 声明 manager 身份与 skills 边界（该文件为描述性文档，无代码加载）。
- `integrations/agentteams/bridge/omichub_agentteams_bridge/config.py:39` token 配置；`app.py` 多处 `require_role(identity, "bioops-manager")` 权限控制。
- `bridge/room_mirror.py:31,134` Manager 回复以 `bioops-manager` 身份镜像到 Matrix 房间。

**建议：此身份不改名。** 它散落在 token 配置与权限校验中，改名无收益、改动面大。

### 2.2 LLM 人格（Manager 回复的实际生成者 = `agent-general`）

- `src/omichub/application/services/agentteams_room_response_service.py:66` `_PREFERRED_MANAGER_AGENT_ID = "agent-general"`（硬编码）；`:1057-1068` 回退逻辑。
- Manager 房间话术硬编码在同文件 `:1153-1176` `_build_question()`（"扮演 Manager……澄清协议……"）。
- 名称偏好链路：前端 `frontend/src/stores/agentTeamsPreferences.ts:21`（默认 `'Manager'`）→ 后端 `:1140` 注入 prompt「称呼自己为 {manager_name}」→ 前端 `AgentTeamsRoomView.vue` 用 `managerLabel` 展示。
- 前端角色后缀：2026-08-20 已将 `AgentTeamsRoomView.vue:1508,1539` 的 ` · 管家` 改为 ` · 生物信息部门经理`（展示层，已上线）。

## 3. 模式隔离：为什么通用助手不受影响

| 模式 | 前端入口 | 后端 API | 服务链路 |
|---|---|---|---|
| AI 助手 | `/ai` → AIChatView | `/api/v1/chat` | ChatService → agent 运行时 |
| AI 工作台 | `/studio/:sessionId?` → StudioView | `/api/v1/studio` | Studio 会话 + 沙盒执行 |
| AgentTeams 协作室 | `/agent-teams/room` | `/api/v1/agent-teams` | AgentTeamsService + Bridge + room_response_service |

三种模式入口、API 前缀、服务类**完全分离**；Manager 相关逻辑只在协作室链路内被调用。

**唯一共享点**：Manager 回复复用 `agent-general` 的 system prompt + persona（`agent_consultation_service.py:301` → `agent_service.py:763-798` `_append_persona_prompt`）。`data/ai/general.yaml`（`name: 通用助手`，archetype「好奇而结构化的研究顾问」）同时是：

- AI 助手/AI 工作台里的通用助手；
- 协作室 Manager 的 LLM 人格；
- 可招募专家（`general.yaml:42-50` `recruitable: true`）。

## 4. 改动分层与影响面

| 层级 | 改动内容 | 位置 | 对通用助手影响 |
|---|---|---|---|
| 展示层（已完成） | 角色后缀「管家」→「生物信息部门经理」 | `AgentTeamsRoomView.vue:1508,1539` | 无 |
| 称呼层 | 默认 `managerName`、后端兜底名 | `agentTeamsPreferences.ts:21`、`room_response_service.py:1140` | 无 |
| 话术层 | Manager 房间 prompt（"扮演 Manager"段） | `room_response_service.py:1153-1176` | 无（仅协作室） |
| 人格层（推荐） | Manager 独立 agent YAML + 可配置选择 | 新建 `data/ai/agentteams_manager.yaml`；`:66` 改配置项；capability registry 声明 `planner_eligible` | 无（与 agent-general 解耦） |
| ⚠️ 禁区 | 直接改 `general.yaml` 的 name/persona/prompt_file 或 `prompts/general.md` | `data/ai/general.yaml` | **三个模式一起变，禁止** |

## 5. 建议与红线

1. **保持现状即可成立**：展示层改动已让 Manager 以「生物信息部门经理」身份呈现，通用助手在 AI 助手 & AI 工作台运行模式不变。
2. **若需深化人设**（如让 Manager 的口吻、职责描述真正"部门经理化"）：改 `room_response_service.py` 话术层，或做独立 Manager agent YAML（人格层），不要动 `general.yaml`。
3. **红线**：`data/ai/general.yaml` 与 `data/ai/prompts/general.md` 是三模式共享配置源，任何针对 Manager 的个性化都不得落在这两个文件上。
4. `bioops-manager` 安全身份保持不变（见 §2.1）。

## 6. 参考文档

- `ARCHITECTURE_DESIN/agentteams_department_collaboration_architecture_2026-08.md` — 部门协作模型（Manager = 客户经理/项目协调人）
- `data/ai/update/AgentTeams_VISION_FINAL.md` §4.2 — Manager 编排者职责的现行权威口径
- `ARCHITECTURE_DESIN/agent_architecture_and_extension_guide.md` — Agent 配置体系与提示词修改流程
