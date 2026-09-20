# AI 助手前端实现详解

> 文档范围：CygnusX 前端 AI 助手模块（`/ai` 路由）。
> 技术栈：Vue 3 + Vite + TypeScript + Naive UI + Pinia + SSE（ReadableStream）。
> 更新日期：2026-07-02

---

## 1. 概述

AI 助手页面是平台的核心交互入口之一。当前实现采用 **Agent-first（智能体优先）** 架构：用户先选择智能体，再进入对话。旧的 **Model-first（模型优先）** 布局（`KimiLayout.vue`）仍保留在代码库中，但其底层组件（消息列表、输入框、Markdown 渲染等）已被新工作区复用。

主要特点：

- 全屏沉浸式布局，铺满视口。
- 基于 SSE 的流式输出，支持文本、推理过程、工具调用、图表。
- 智能体由后端 YAML 配置驱动，支持 system_prompt、模型绑定、MCP 工具、技能注入。
- 已接入全局主题系统，深色/浅色模式统一。

---

## 2. 入口与路由

### 2.1 路由配置

文件：`frontend/src/router/index.ts`

```ts
{
  path: 'ai',
  name: 'ai',
  component: () => import('@/views/AIChatView.vue'),
  meta: { title: 'AI 助手', requiresAuth: true, fullscreen: true }
}
```

说明：

- `requiresAuth: true` 表示需要登录。
- `fullscreen: true` 是关键标记，告诉 `DefaultLayout.vue`：
  - 移除内容区内边距（`padding: 0`）。
  - 使用原生滚动条（`:native-scrollbar="true"`），让 AI 页面能够铺满整个视口。

### 2.2 顶层视图

文件：`frontend/src/views/AIChatView.vue`

- 仅是一个绝对定位的 flex 容器。
- 内部渲染 `<AgentWorkspace />`。

### 2.3 布局外壳

文件：`frontend/src/layouts/DefaultLayout.vue`

- 负责全局顶部导航栏和左侧边栏。
- 当 `route.meta.fullscreen === true` 时，内容区完全交给子组件控制。
- AI 助手菜单位于侧边栏「分析中心」下方。

---

## 3. 布局架构

### 3.1 当前 Agent-first 工作区

文件：`frontend/src/components/agent-workspace/AgentWorkspace.vue`

视觉结构：

```
┌──────────────────────────────────────────────────────┐
│ AgentSidebar │          workspace-main               │
│              │  ┌─────────────────────────────────┐  │
│  - 新建对话   │  │  AgentHub（无会话时：选智能体）  │  │
│  - 历史会话   │  │           或                     │  │
│  - 用户信息   │  │  AgentSandbox（会话中：对话区）  │  │
│              │  └─────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

组件职责：

| 组件 | 路径 | 职责 |
|------|------|------|
| `AgentSidebar.vue` | `components/agent-workspace/AgentSidebar.vue` | 左侧可折叠边栏：新建对话、按时间分组的历史会话、删除会话、底部用户头像 |
| `AgentHub.vue` | `components/agent-workspace/AgentHub.vue` | 智能体大厅，以卡片网格展示可用智能体 |
| `AgentCard.vue` | `components/agent-workspace/AgentCard.vue` | 单个智能体卡片：头像、名称、描述、分类、挂载的 MCP/技能数量 |
| `AgentSandbox.vue` | `components/agent-workspace/AgentSandbox.vue` | 实际对话区：顶部智能体身份栏 + `KimiMessageList` + `KimiChatInput` |

### 3.2 遗留 Model-first 布局

目录：`frontend/src/components/ai-chat/legacy/`

文件：

| 组件 | 路径 | 说明 |
|------|------|------|
| `KimiLayout.vue` | `components/ai-chat/legacy/KimiLayout.vue` | 旧版模型优先布局根组件 |
| `KimiSidebar.vue` | `components/ai-chat/legacy/KimiSidebar.vue` | 旧版侧边栏 |
| `KimiEmptyState.vue` | `components/ai-chat/legacy/KimiEmptyState.vue` | 旧版空状态 |
| `ModelNavBar.vue` | `components/ai-chat/legacy/ModelNavBar.vue` | 旧版模型/助手/设置栏 |

视觉结构：

```
┌──────────────────────────────────────────────────────┐
│ KimiSidebar  │  kimi-main                            │
│              │  - 配置警告条                        │
│              │  - ModelNavBar（模型/助手选择栏）     │
│              │  - KimiEmptyState（空状态）          │
│              │  - KimiMessageList（消息列表）        │
│              │  - KimiChatInput（输入框）            │
└──────────────────────────────────────────────────────┘
```

说明：

- 该布局目前不被 `/ai` 路由直接渲染。
- 其拆出的子组件（`KimiMessageList`、`KimiChatInput` 等）被 `AgentSandbox` 复用。
- 已集中到 `legacy/` 目录并添加保留说明注释，避免新成员与当前组件混淆。
- 当 Agent-first 模式完全覆盖模型优先能力后，可整体移除该目录及 `chatSession` / `chatAssistant` Store。

---

## 4. 可复用的聊天基础组件

这些组件位于 `frontend/src/components/ai-chat/`，是当前和旧布局共用的核心 UI 单元。

| 组件 | 职责 |
|------|------|
| `KimiMessageList.vue` | 消息滚动容器，自动滚动到底部，显示"回到底部"按钮 |
| `KimiMessageItem.vue` | 渲染单条消息：用户气泡、助手头像/名称、推理过程折叠、Markdown 正文、工具调用卡片、图表 |
| `KimiChatInput.vue` | 自动增高文本框、`/` 斜杠命令菜单、提示词侧边栏、工具栏 |
| `MessageActionBar.vue` | 消息悬停操作：复制（纯文本/Markdown/引用）、重新生成、换模型重试、翻译、删除 |
| `ModelNavBar.vue` | 会话标题编辑、模型芯片、模型下拉选择、助手选择、对话设置（温度/最大 token/上下文长度） |
| `KimiEmptyState.vue` | 空会话时的欢迎页 + 快捷提示卡片 |
| `PromptSidebar.vue` | 生信提示词模板侧抽屉 |
| `SlashCommandMenu.vue` | `/` 命令面板 |
| `setup.ts` | 配置 `markdown-it` + `highlight.js` + 注册 `vue-echarts`（VChart） |

---

## 5. 状态管理

所有 Store 均使用 Pinia + Composition API。

### 5.1 `agentHub` — 当前主 Store

文件：`frontend/src/stores/agentHub.ts`

- 管理智能体列表、MCP 服务、技能、客户端会话。
- 维护 `currentSessionId`、`isStreaming`、`streamingContent`、`streamingThought`。
- 提供 `sendMessage(content)`：push 用户消息 → push 助手占位 → 构建上下文 → 调用 `useAgentChatStream`。
- 关键 computed：`currentSession`、`currentAgent`、`groupedSessions`。

### 5.2 `chatSession` — 后端会话 Store

文件：`frontend/src/stores/chatSession.ts`

- 被 `KimiLayout`（旧布局）使用。
- 拉取 `/chat/models`、`/chat/sessions`、单会话消息。
- 提供 `sendMessage()`，通过 `useChatStream` 与后端 SSE 交互。
- **@deprecated**：仅服务于旧版 Model-first 布局；Agent-first 模式下由 `agentHub` 接管。

### 5.3 `chatAssistant` — 助手 Store

文件：`frontend/src/stores/chatAssistant.ts`

- 加载 `/chat/assistants`。
- 跟踪 `currentAssistantId`。
- 被 `ModelNavBar` 使用。
- **@deprecated**：仅服务于旧版 Model-first 布局；助手能力已下沉为后端 Agent 配置。

### 5.4 `chat` — UI/设置 Store

文件：`frontend/src/stores/chat.ts`

- 现在主要作为 UI 和设置 Store：
  - `sidebarCollapsed`
  - `deepThinking`（深度思考开关）
  - `conversationSettings`（temperature、maxTokens、contextLength）
  - `favoriteModels`、`quickPrompts`、`availableModels`、`availablePlugins`
- 持久化设置/收藏/会话到 `localStorage`。
- **收敛计划**：Agent-first 模式稳定后，建议将 UI 状态剥离到独立的 `uiSettingsStore`，模型优先相关状态随旧布局移除。

### 5.5 `theme` — 主题 Store

文件：`frontend/src/stores/theme.ts`

- 管理全局主题 `dark/light`。
- 持久化到 `localStorage`，key 为 `cygnusx-theme`。
- 设置 `<html data-theme="dark|light">` 和 `.dark` class。

---

## 6. 流式输出与 SSE

前端使用 `fetch + ReadableStream`（不是 Axios）消费后端 `POST /api/v1/chat/stream` 返回的 SSE 流。

### 6.1 `useChatStream.ts` — 模型优先 SSE

文件：`frontend/src/composables/useChatStream.ts`

Payload 字段：

```ts
{
  messages: [{ role, content }],
  model_id: string,
  session_id?: string,
  assistant_id?: string,
  system_prompt?: string,
  temperature?: number,
  max_tokens?: number
}
```

事件：`text`、`error`、`done`。  
回调：`onText`、`onSessionCreated`、`onError`、`onDone`。

### 6.2 `useAgentChatStream.ts` — 智能体 SSE

文件：`frontend/src/composables/useAgentChatStream.ts`

Payload 字段：

```ts
{
  agent_id: string,
  session_id?: string,
  messages: [{ role, content }],
  stream: true,
  temperature?: number,
  max_tokens?: number,
  deep_thinking?: boolean
}
```

- `temperature` / `max_tokens` / `deep_thinking` 从 `chatStore.conversationSettings` 读取，在 `agentHubStore.sendMessage()` 构造 payload 时合并，确保 UI 调整真实生效。
- 内部已绑定 `AbortController.signal`，切换会话/智能体或点击停止时会立即 `abort()`。

额外事件：

- `tool_call` → `onToolCall({ tool_call_id, tool_name, arguments })`
- `tool_result` → `onToolResult({ tool_call_id, tool_name, success, result })`

### 6.3 调用流程

1. 用户在 `AgentSandbox` 输入框发送消息。
2. `agentHubStore.sendMessage(content)`：
   - 若当前会话还是临时 `sess-` ID 且正在解析为真实 ID，会等待锁释放，避免重复创建会话。
   - push 一条用户 `ChatMessage`。
   - push 一条空的助手占位消息。
   - 从 `chatStore.conversationSettings.contextLength` 构建上下文窗口（默认 20 条）。
   - 调用 `useAgentChatStream.streamChat({ agentId, messages, sessionId, temperature, maxTokens, deepThinking })`。
3. SSE 回调更新状态：
   - `onText` → 追加到 `streamingContent` / `streamingThought`。
   - `onSessionCreated` → 把临时 `sess-` ID 替换为后端真实 `session_id`，并释放会话 ID 锁。
   - `onToolCall` / `onToolResult` → 填充 `aiMsg.toolCalls`。
   - `onDone` → 提交最终内容，清空流式状态。
4. `AgentSandbox` 把 `session.messages`、`streamingContent`、`streamingThought` 传给 `KimiMessageList` 渲染。

---

## 7. 消息渲染

### 7.1 `KimiMessageList.vue`

文件：`frontend/src/components/ai-chat/KimiMessageList.vue`

- 接收 `messages`、`isTyping`、`streamingContent`、`streamingThought`、`modelName`。
- 基于 `vue-virtual-scroller` 的 `DynamicScroller` 实现虚拟滚动，仅渲染可视区域内的消息节点与图表，降低长对话的内存与重排开销。
- 监听消息数量和流式内容，自动滚动到底部（使用 `scrollToBottom()`）。
- 计算 `streamingMessageId`（最后一条 assistant 消息的 id）。
- 流式开始但尚无内容时显示"输入中"指示器。

### 7.2 `KimiMessageItem.vue`

文件：`frontend/src/components/ai-chat/KimiMessageItem.vue`

- **用户消息**：右对齐气泡，使用 `--chat-user-bubble` 背景。
- **助手消息**：左侧头像 + "CygnusX AI" 名称，包含：
  - 可选的 reasoning/thought 折叠区
  - Markdown 正文
  - 工具调用卡片
  - ECharts 图表
  - 悬停操作栏
- **系统消息**：居中、浅色的提示文本。
- 流式消息渲染 Markdown 时通过 `requestAnimationFrame` 批量执行，避免高频 chunk 触发 `markdown-it` + `highlight.js` 反复阻塞主线程。

### 7.3 Markdown 与代码高亮

文件：`frontend/src/components/ai-chat/setup.ts`

- 使用 `markdown-it` + `highlight.js`。
- 代码块顶部显示语言标签和复制按钮。
- 导出预注册了 line/bar/pie 等图表的 `VChart`（vue-echarts）。

### 7.4 样式变量

文件：`frontend/src/styles/chat-theme.css`

提供全局样式：

- `.kimi-message-item .message-body`：正文样式
- `.hljs`：代码高亮暗色主题
- `.thought-section`：推理过程折叠区
- `.tool-card` / `.chart-container`：工具结果和图表容器

所有颜色都由 `--chat-*` CSS 变量驱动。

---

## 8. 模型与智能体选择

### 8.1 当前 Agent 工作流

选择发生在 `AgentHub.vue`：

1. `AgentCard.vue` 渲染每个激活智能体。
2. 用户点击卡片 → `AgentHub` 触发 `select` 事件。
3. `AgentWorkspace.handleSelectAgent(agentId)` 调用 `agentHubStore.startSessionFromAgent(agentId)`。
4. Store 创建一个客户端会话，预填充智能体的 `welcome_message`，并打开 `AgentSandbox`。

### 8.2 旧版模型工作流

选择发生在 `ModelNavBar.vue`：

- 显示可编辑的会话标题。
- 模型芯片 + 能力标签（`longContext`、`code`、`multimodal`、`bio`）。
- 标签逻辑来自 `frontend/src/components/ai-chat/modelCapabilities.ts`，按模型 ID/名称/provider 关键字启发式判断。
- 分组下拉：收藏、通用模型、生信模型。
- 助手选择下拉（绑定 `chatAssistantStore.currentAssistantId`）。
- 对话设置浮层：温度、最大 token、上下文长度。

---

## 9. 主题统一

### 9.1 主题 Store

文件：`frontend/src/stores/theme.ts`

- 初始化时从 `localStorage` 读取主题偏好。
- 设置 `data-theme="dark|light"` 和 `.dark` class。

### 9.2 CSS 变量

文件：`frontend/src/styles/chat-theme.css`

- 为 `dark` 和 `light` 分别定义完整的 `--chat-*` 变量。

文件：`frontend/src/styles/global.css`

- 新增 `:root[data-theme="dark"] .kimi-layout { ... }` 覆盖。
- 把 AI 助手的深色变量映射到平台统一中性色，实现 AI 助手和平台夜间模式一致。

### 9.3 组件使用

- `KimiLayout.vue` 根元素绑定 `:data-theme="themeStore.theme"`。
- 用户通过顶部用户下拉菜单切换主题时，所有聊天组件颜色立即切换（纯 CSS 变量驱动）。

---

## 10. 关键数据流总结

### 10.1 当前 Agent 工作流

```
/ai 路由
  → AIChatView.vue
    → AgentWorkspace.vue
      → onMounted: agentHubStore.initAssets()  // 拉智能体/MCP/技能
      → AgentHub.vue 展示智能体卡片
        → 用户点击 AgentCard
          → AgentWorkspace.startSessionFromAgent(agentId)
            → agentHubStore 创建客户端会话 + welcome_message
              → AgentSandbox.vue 渲染对话区
                → 用户输入 → KimiChatInput send
                  → agentHubStore.sendMessage(content)
                    → push 用户消息 + 助手占位
                    → useAgentChatStream.streamChat({ agentId, messages })
                      → SSE 推送 text / tool_call / tool_result / done
                        → KimiMessageList + KimiMessageItem 渲染
```

### 10.2 旧版模型工作流

```
KimiLayout.vue
  → onMounted: 拉 models / sessions / assistants
  → ModelNavBar.vue 选择模型和助手
  → KimiChatInput send
    → KimiLayout.handleSend
      → chatSessionStore.createSession(modelId, assistantId) // 如无会话
      → chatSessionStore.sendMessage(content, settings)
        → useChatStream.streamChat({ model_id, messages, ... })
          → SSE 更新 streamingContent / streamingReasoning
            → KimiMessageList 渲染
```

---

## 11. 关键文件索引

| 用途 | 路径 |
|------|------|
| 路由定义 | `frontend/src/router/index.ts` |
| AI 顶层视图 | `frontend/src/views/AIChatView.vue` |
| 当前工作区 | `frontend/src/components/agent-workspace/AgentWorkspace.vue` |
| 智能体大厅 | `frontend/src/components/agent-workspace/AgentHub.vue` |
| 智能体卡片 | `frontend/src/components/agent-workspace/AgentCard.vue` |
| 对话沙盒 | `frontend/src/components/agent-workspace/AgentSandbox.vue` |
| 左侧边栏 | `frontend/src/components/agent-workspace/AgentSidebar.vue` |
| 旧版布局 | `frontend/src/components/ai-chat/legacy/KimiLayout.vue` |
| 旧版侧边栏 | `frontend/src/components/ai-chat/legacy/KimiSidebar.vue` |
| 旧版空状态 | `frontend/src/components/ai-chat/legacy/KimiEmptyState.vue` |
| 旧版模型导航栏 | `frontend/src/components/ai-chat/legacy/ModelNavBar.vue` |
| 消息列表 | `frontend/src/components/ai-chat/KimiMessageList.vue` |
| 单条消息 | `frontend/src/components/ai-chat/KimiMessageItem.vue` |
| 输入框 | `frontend/src/components/ai-chat/KimiChatInput.vue` |
| Markdown/图表配置 | `frontend/src/components/ai-chat/setup.ts` |
| 聊天类型定义 | `frontend/src/components/ai-chat/types.ts` |
| 模型能力标签 | `frontend/src/components/ai-chat/modelCapabilities.ts` |
| 聊天主题变量 | `frontend/src/styles/chat-theme.css` |
| 全局主题/覆盖 | `frontend/src/styles/global.css` |
| 主题 Store | `frontend/src/stores/theme.ts` |
| Agent Store | `frontend/src/stores/agentHub.ts` |
| 后端会话 Store | `frontend/src/stores/chatSession.ts` |
| 助手 Store | `frontend/src/stores/chatAssistant.ts` |
| UI/设置 Store | `frontend/src/stores/chat.ts` |
| 模型 SSE | `frontend/src/composables/useChatStream.ts` |
| Agent SSE | `frontend/src/composables/useAgentChatStream.ts` |

---

## 12. 已知注意事项

1. **旧布局 `KimiLayout.vue` 未被挂载**：如果未来想切回模型优先模式，需要修改 `AIChatView.vue` 或路由配置；该组件及其特有子组件已迁移到 `components/ai-chat/legacy/`。
2. **会话 ID 的临时/真实切换**：Agent 工作流先创建客户端临时 `sess-` ID，等 SSE 返回 `onSessionCreated` 后再替换为后端真实 `session_id`。`agentHubStore` 中已加入临时会话 ID 解析锁，避免回填前重复创建会话。
