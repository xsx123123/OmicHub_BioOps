# CygnusX AI 助手与工具联动架构设计

> 目标：让 AI 助手能够发现当前可用的生信工具，并在对话中直接调用这些工具产出结果。
> 本文档基于 2026-07-12 的代码现状，并结合可行性评审结论给出可落地的架构与分阶段实现建议。
> 输出日期：2026-07-12 | 修订：同日（按代码评审更新）

---

## 〇、可行性结论（摘要）

| 维度 | 评分 | 说明 |
|------|------|------|
| 现状分析 | 9/10 | Agent/MCP/工具箱路径与职责判断准确 |
| 架构设计 | 8/10 | Schema + Bridge 正确；大结果回灌与异步策略需约束 |
| 与代码契合 | 9/10 | 可插在现有 `stream_agent_chat` / builtin MCP 上 |
| 工期估计 | 7/10 | Phase 1 合理；全覆盖偏紧 |
| 安全设计 | 8/10 | 与现有 user 隔离一致；需补配额与确认 |

**总体：可行，且与现有代码契合度高（约 8/10）。**

最大坑不是「能不能调工具」，而是：

1. **大结果回灌**：`chat_service.py` 把 `tool_result` 截断到 **4000 字符**，Plotly figure 会碎。
2. **前后端双实现**：`volcanoProcessor.ts` 等纯前端逻辑重，后端 shim 易漂移。
3. **长任务占 SSE**：异步工具若在 Bridge 内同步轮询，会拖死流式连接、占 worker。

**推荐主线**：builtin MCP `cygnusx-tools` + ToolBridge（进程内调 service）+ **摘要回灌 / 完整结果走前端 metadata**；落地顺序 **先 KEGG → 再轻量绘图 shim → 异步只 submit**。

---

## 一、现状概览

### 1.1 AI 助手现状

CygnusX 已经具备一套现代的 **Agentic 对话流**：

- **前端入口**：`frontend/src/views/AIChatView.vue` 挂载 `AgentWorkspace`，最终由 `AgentSandbox` 渲染 `KimiMessageList` + `KimiChatInput`。
- **通信协议**：前端通过 `POST /api/v1/chat/stream` 发起 **Server-Sent Events (SSE)** 流式请求；后端返回 `text` / `tool_call` / `tool_result` / `error` / `done` 事件（`frontend/src/composables/useAgentChatStream.ts`）。
- **后端编排**：`src/cygnusx/application/services/chat_service.py:436` 的 `stream_agent_chat()` 实现了最多 **8 轮**的工具调用闭环：
  1. 调用 `AgentService.assemble_context(agent_id)` 组装模型、系统提示词、MCP 工具列表；
  2. 把工具转成 OpenAI `tools` 格式传给 LLM；
  3. LLM 返回 `tool_calls` 后，在绑定的 MCP server 中查找并 `mcp_client.call_tool()`；
  4. 将 `tool_result` **截断到 4000 字符**后回灌 LLM 上下文并继续生成（`:688`）。
- **MCP 生态**：领域层（`src/cygnusx/domain/mcp/`）、客户端（`src/cygnusx/infrastructure/mcp/client.py`）支持 **builtin / stdio / sse**。4 个内置 preset（`presets.py`：literature、genome、code、knowledge）通过 `handlers` 在进程内执行。Agent 经 `mcp_ids` 挂载 server。
- **结果渲染**：`KimiMessageItem.vue` 已展示 `message.toolCalls` 卡片；`message.charts` 当前类型为 **`echarts` only**（`frontend/src/components/ai-chat/types.ts:45`），**尚无 Plotly 渲染路径**。

### 1.2 工具箱现状

工具箱注册在 `tool_configs/tools_setting.yaml`，由 `src/cygnusx/tools/registry/config.py` 按 mtime 热加载，`GET /api/v1/tools` 返回。字段只有展示元数据：`key`、`title`、`description`、`icon`、`gradient`、`route`、`group`、`enabled`、`order`、`config_dir`。

现有工具可按执行位置分为三类：

| 类型 | 代表工具 | 执行方式 | 输入/输出特点 |
|------|---------|---------|--------------|
| **纯前端工具** | volcano、manhattan、gene-expression-explorer、seq-manipulator、format-converter、plot | 数据解析 + 计算 + 绘图在 `frontend/src/utils/*Processor.ts` | 输入：CSV/TSV + 配置；输出：Plotly figure JSON + 统计 |
| **后端同步工具** | kegg-enrichment | `POST /enrichment/submit` 同步返回；实现在 `src/cygnusx/tools/enrichments/`（service/runner） | 输入：物种、基因列表；输出：Plotly JSON + 表格；结果落用户目录 |
| **后端异步工具** | phylogenetic-tree、RNA-seq / ATAC-seq flows | `POST .../submit` → `task_id`，再 status/result | 输入：文件/参数；输出：任务状态、结果文件、统计 |

### 1.3 当前 disconnect

**AI 助手和工具箱目前没有连接**：

- `tools_setting.yaml` 只告诉前端「有哪些工具卡片」，没有参数 schema、执行端点、返回格式。
- `assemble_context()` 只从 Agent 绑定的 MCP 拿 tools；工具箱对 LLM 不可见。
- 纯前端工具只能在各自 Vue 页运行，Agent 无法触发。
- 后端工具虽有 service/API，但 Agent 没有统一适配层去调用并把结果以 LLM 友好方式回灌。
- 聊天附件已可注入多模态（`_build_multimodal_messages`），但尚未作为工具入参的标准 `upload://` 引用。

---

## 二、目标架构

### 2.1 核心思路

把工具箱升级为 **「可被 LLM 理解和调用」的工具集合**，复用现有 Agent/MCP 闭环，**优先走 builtin MCP**，避免在 `stream_agent_chat` 里再开一套并行分发（除非调试需要）。

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AI 助手对话前端                                │
│  AgentSandbox → useAgentChatStream → SSE /api/v1/chat/stream       │
│  渲染：toolCalls 卡 + Plotly/ECharts + 任务卡 + 下载链接              │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     ChatService.stream_agent_chat()                 │
│  1. assemble_context() 组装 tools（含 cygnusx-tools）                │
│  2. provider_manager.chat_stream() 调用 LLM                         │
│  3. tool_calls → MCPClient.call_tool()（builtin → ToolBridge）      │
│  4. 回灌 LLM：仅摘要 / result_ref（≤4000 安全）；完整载荷走 SSE metadata │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              builtin MCP: cygnusx-tools  +  Tool Schema Registry    │
│  tools_schema.yaml → OpenAI function schema + invocation_mode       │
│  ToolBridgeService：校验参数 → 按 mode 分发 → 摘要化输出              │
└─────────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────────────┐
              ▼               ▼                       ▼
   ┌─────────────────┐ ┌──────────────┐ ┌──────────────────────────┐
   │ backend_shim    │ │ backend_sync │ │ backend_async            │
   │ volcano 等      │ │ 直接调       │ │ 仅 submit，返回 task_id  │
   │ pandas/plotly   │ │ Enrichment   │ │ 不在 SSE 内长轮询        │
   │ 核心路径即可    │ │ Service      │ │ 前端/任务中心看进度      │
   └─────────────────┘ └──────────────┘ └──────────────────────────┘
              │
              ▼（非核心 / 未 shim 的纯前端工具）
   ┌─────────────────────────────────────┐
   │ open_tool_page fallback             │
   │ 返回 route + 预填参数提示，引导用户 │
   └─────────────────────────────────────┘
```

### 2.2 关键组件

#### 2.2.1 Tool Schema Registry（工具模式注册表）

**双文件方案**，不破坏现有卡片语义：

- `tool_configs/tools_setting.yaml`：前端 ToolsHub 卡片（保持现状）。
- `tool_configs/tools_schema.yaml`：LLM 可调用的 schema（新建，支持 mtime 热重载，与 registry 一致）。

**命名约定**：工具 function `name` 统一加前缀 `cygnusx_`，避免与 MCP preset（如 `lookup_gene`）或 web_search 撞名。

```yaml
tools:
  - key: kegg-enrichment
    name: cygnusx_run_kegg_enrichment
    description: >
      对基因列表进行 KEGG 通路富集分析。需要物种 ID 与每行一个基因的列表。
    invocation_mode: backend_sync   # backend_shim | backend_sync | backend_async | open_page
    # 优先进程内调 service，不强制 HTTP 自调用
    service: cygnusx.tools.enrichments.service.EnrichmentService
    method: submit   # 或具体 service 方法名
    requires_confirm: false
    input_schema:
      type: object
      properties:
        species_id:
          type: string
          description: 物种 ID，如 human、mouse（以后端 YAML 为准）
        gene_text:
          type: string
          description: 每行一个基因符号；也可传 upload://file_id 引用已上传文本
      required: [species_id, gene_text]
    # 回灌 LLM 的字段白名单（大字段禁止进 content）
    llm_result_fields: [task_id, stats, top_pathways, success, error]
    # 给前端渲染的完整字段（经 SSE tool_result.metadata 下发，不截断进 LLM）
    ui_result_fields: [plotly_json, table_data, download_urls]

  - key: volcano
    name: cygnusx_plot_volcano
    description: >
      根据差异表达结果绘制交互式火山图。数据请用 upload://file_id 或短 CSV 文本。
    invocation_mode: backend_shim
    shim_module: cygnusx.tools.shims.volcano
    requires_confirm: false
    input_schema:
      type: object
      properties:
        data_ref:
          type: string
          description: upload://<file_id> 或聊天附件引用；禁止超大 CSV 直接塞入 arguments
        data:
          type: string
          description: 可选，短 CSV/TSV 文本（有行数/字节上限）
        pval_cutoff: { type: number, default: 0.05 }
        lfc_cutoff: { type: number, default: 1.0 }
      required: []   # data_ref 与 data 至少一个，由 Bridge 校验
    llm_result_fields: [stats, top_up_genes, top_down_genes, success, error]
    ui_result_fields: [plotly_figure, result_ref]

  - key: phylogenetic-tree
    name: cygnusx_build_phylogenetic_tree
    description: 提交系统发育树构建任务（异步）。返回 task_id，不在本轮等待完成。
    invocation_mode: backend_async
    service: cygnusx.tools.phylogenetic_tree.service.PhyloService  # 以实际类名为准
    requires_confirm: true   # 消耗算力，执行前确认
    input_schema:
      type: object
      properties:
        file_id:
          type: string
          description: 用户已上传序列文件的 file_id（须属当前用户）
        method:
          type: string
          enum: [NJ, UPGMA, ML, Bayesian]
      required: [file_id, method]
    llm_result_fields: [task_id, status, status_url, message, success, error]
    ui_result_fields: [task_id, status, progress_url, result_url]
```

设计理由：

- 与 `tools_setting.yaml` 解耦，卡片元数据与 LLM schema 不互相污染。
- `invocation_mode` 明确执行策略；`llm_result_fields` / `ui_result_fields` 从协议层解决 4000 截断问题。
- `input_schema` 直接对应 OpenAI function parameters。
- **大数据入参禁止进 function args**：优先 `upload://` / 聊天附件 file_id。

#### 2.2.2 Tool Execution Bridge（工具执行桥）

新增 `src/cygnusx/application/services/tool_bridge_service.py`（也可被 MCP preset handler 直接调用），职责：

1. 加载/热重载 `tools_schema.yaml`，按 `name` 查找 schema。
2. **JSON Schema 校验** LLM 参数；拒绝越界、缺必填、超大 `data` 字符串。
3. **身份**：始终带 `user_id`（来自 `stream_agent_chat` 的 JWT 用户），写路径限制在用户目录。
4. **文件引用**：解析 `upload://<file_id>` / 聊天附件路径，校验归属后读入。
5. 按 `invocation_mode` 分发：
   - `backend_sync` / `backend_shim`：进程内调 service 或 shim，**禁止**默认 HTTP 回环自调用（少 hop、复用鉴权上下文）。
   - `backend_async`：**只 submit**，立即返回 `task_id` + 状态/结果 URL；**禁止在 Bridge 内长轮询到任务结束**。
   - `open_page`：返回前端 `route` + 建议预填参数，由 LLM 引导用户打开工具页。
6. **结果双通道**（关键）：
   - `llm_payload`：仅摘要字段，JSON 序列化后进 `role=tool` 的 content（适配现有 4000 截断，目标控制在 2–3KB 内）。
   - `ui_payload`：完整 figure / 表 / 下载链接，经 SSE `tool_result` 的 metadata 下发前端；可选落盘 `result_ref` 供二次拉取。

伪代码：

```python
class ToolBridgeService:
    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> dict:
        schema = self.registry.get(tool_name)
        if schema is None:
            return {"success": False, "error": f"未知工具: {tool_name}"}

        args = self._validate_and_resolve_refs(user_id, schema, arguments)

        if schema.requires_confirm and not arguments.get("_confirmed"):
            return {
                "success": True,
                "llm_payload": {
                    "needs_confirm": True,
                    "tool_name": tool_name,
                    "summary": "该操作会提交计算任务，请用户确认后再执行",
                    "preview_args": self._safe_preview(args),
                },
                "ui_payload": {"confirm_card": True, "tool_name": tool_name, "args": args},
            }

        if schema.invocation_mode == "backend_shim":
            raw = await self._run_shim(schema, user_id, args)
        elif schema.invocation_mode == "backend_sync":
            raw = await self._run_service_sync(schema, user_id, args)
        elif schema.invocation_mode == "backend_async":
            raw = await self._submit_async_only(schema, user_id, args)
        elif schema.invocation_mode == "open_page":
            raw = self._open_page_payload(schema, args)
        else:
            raw = {"success": False, "error": f"不支持的 mode: {schema.invocation_mode}"}

        return {
            "success": bool(raw.get("success", True)),
            "llm_payload": self._pick(raw, schema.llm_result_fields),
            "ui_payload": self._pick(raw, schema.ui_result_fields),
        }
```

**与 chat_service 的衔接**：若走 builtin MCP，handler 返回值应保证 `result` 里给 LLM 的是 `llm_payload`；同时 chat 层需把 `ui_payload` 放进 SSE `tool_result` metadata（可小改 `call_tool` 返回结构或约定 `result` 为 `{"llm":..., "ui":...}`）。

#### 2.2.3 纯前端工具策略（修订）

| 方式 | 说明 | 何时用 |
|------|------|--------|
| **A. 后端 Shim** | Python 实现核心计算 + 简化 Plotly JSON，不 1:1 复刻 `*Processor.ts` | 高频、参数少、适合对话内出图（volcano、manhattan） |
| **B. open_page fallback** | 不执行，返回 `/tools/xxx` + 参数说明 | 交互重、样式复杂、暂未 shim 的工具 |
| **C. 前端 Executor** | SSE 透传 tool_call → 浏览器跑 TS → 再 POST 回灌 | **不作为主路径**（破坏后端闭环，中间状态难管） |

**MVP 不做 100% 复刻前端样式**；shim 只保证：列识别、阈值分组、TopN 标注、可交互散点。完整样式仍引导用户打开工具页微调。

#### 2.2.4 挂载方式：优先 builtin MCP `cygnusx-tools`

**推荐（主路径）**：

1. 在 `presets.py` 增加 `cygnusx-tools` preset：`transport: builtin`，tools 列表由 `tools_schema.yaml` 生成，handlers 统一委托 `ToolBridgeService.execute`。
2. 在 `AgentService.assemble_context()` 中，**自动把 cygnusx-tools 并入** `mcp_servers` / `tools`（可配置开关，默认开），无需每个 Agent 手动勾选。
3. `stream_agent_chat` 继续走现有 `mcp_client.call_tool()`，核心闭环几乎不动。

**备选（调试/非 MCP）**：

- 在 `assemble_context` 直接 append OpenAI tools；
- 在 `chat_service.py:653-671` 分发顺序：`MCP → ToolBridge → web_search`。

两者可并存：MCP 为主，Bridge 也可被 `POST /api/v1/tools/invoke` 调试接口直接调用。

#### 2.2.5 结果渲染（修订）

现有能力：`toolCalls` 卡 + **ECharts** `charts`。

需要扩展：

| 类型 | 来源 | 前端行为 |
|------|------|----------|
| Plotly 图 | `ui_payload.plotly_figure` / `plotly_json` | `ChartData.type` 扩展为 `'echarts' \| 'plotly'`，消息内 `Plotly.react` |
| 表格 | `table_data`（可截断行数） | Naive UI `NDataTable` 或折叠 JSON |
| 任务卡 | `task_id` + status/result URL | 展示进度入口，「去任务中心」链接；**不在聊天 SSE 里替用户长轮询** |
| 确认卡 | `needs_confirm` | 用户点确认后带 `_confirmed: true` 再调一次 |
| 下载 | `download_urls` / `result_ref` | 按钮下载 |
| open_page | `route` + hints | 一键跳转工具页 |

**禁止**把完整 Plotly JSON 放进回灌 LLM 的 `content`。

---

## 三、让 AI 助手「知道有哪些工具」

### 3.1 系统提示词注入

在 `assemble_context()` 组装 `system_prompt` 时追加自然语言清单（与 function tools 互补，降低漏调）：

```
你是 CygnusX 生信平台的 AI 助手。当前可调用平台工具（function 名以 cygnusx_ 开头）：

1. cygnusx_run_kegg_enrichment — KEGG 通路富集（物种 + 基因列表）
2. cygnusx_plot_volcano — 火山图（差异表达表，优先 upload://）
3. cygnusx_build_phylogenetic_tree — 提交建树任务（异步，需确认）
...

规则：
- 需要计算/出图时优先调用工具，不要只给操作说明。
- 大文件用 upload://file_id，不要把整表 CSV 塞进参数。
- 异步工具只负责提交；完成后引导用户根据 task_id / 任务中心查看。
- 标注 requires_confirm 的工具须先说明影响并等待用户确认。
```

### 3.2 function schema 注入

将 `tools_schema.yaml` 的 `input_schema` 转为 OpenAI `tools[]`，经 cygnusx-tools MCP 或直接 append 到 `ctx.tools`。

### 3.3 体验增强（可选，Phase 2+）

- ToolsHub 卡片「问问 AI」→ 跳转 AIChat 预填提示词。
- 输入框 `/tool` 列出可用工具。
- 聊天附件自动映射为 `upload://` 供下一轮 tool 使用。

---

## 四、安全与权限

1. **身份传递**：Bridge / service 调用一律使用 JWT 解析的 `user_id`，与 enrichment API 一致（不信任 LLM 传入的 user_id）。
2. **路径隔离**：结果只写用户目录（如 `/data/cygnusx/users/{user_id}/...`）；禁止 LLM 指定绝对路径。
3. **文件引用**：仅 `upload://` / 受控 chat-upload 路径；校验归属后再读。
4. **参数校验**：JSON Schema + 字符串长度/行数上限 + 枚举白名单。
5. **执行沙箱**：重计算继续 Docker/Celery 等现有策略。
6. **执行前确认**：`requires_confirm: true` 的工具（流程提交、建树、终端类）必须二次确认。
7. **配额与滥用**：单会话 `max_rounds=8` 已有；建议对 sync/async 工具增加每用户速率限制，防止 LLM 循环刷任务。
8. **工具名隔离**：`cygnusx_` 前缀 + registry 唯一性校验。

---

## 五、分阶段实现建议（修订顺序）

### Phase 1：打通闭环（约 2 周）— 先同步后端，再轻量 shim

**目标**：验证「发现 → 调用 → 摘要回灌 → 前端出图/表格」。

1. 新建 `tool_configs/tools_schema.yaml`，先只注册：
   - `cygnusx_run_kegg_enrichment`（`backend_sync`，进程内调 `EnrichmentService`）
   - `cygnusx_plot_volcano`（`backend_shim`，核心路径）
2. 实现 `schema_loader` + `ToolBridgeService`（校验、分发、`llm_payload`/`ui_payload`）。
3. 新增 builtin MCP `cygnusx-tools`，`assemble_context` 自动注入。
4. 小改 `chat_service`：tool 回灌用 `llm_payload`；SSE `tool_result` 携带 `ui_payload`（若 MCP 返回结构已含双通道，改动可极小）。
5. 前端：`ChartData` 支持 `plotly`；`KimiMessageItem` 渲染 Plotly；表格/下载可选。
6. **明确不在本阶段做**：异步长轮询、全量前端工具 shim、前端 Executor。

**验证标准**：

- 「对这组基因做人类 KEGG 富集」→ 调用 enrichment → 聊天内出现通路表/图摘要 + 可交互图。
- 「用这份差异表画火山图」+ 附件/upload → 出图 + LLM 能概括上下调数量。

### Phase 2：覆盖与异步（约 3 周）

1. `cygnusx_plot_manhattan` 等第二批 shim；其余纯前端工具用 `open_page`。
2. `backend_async`：phylo / flows **只 submit**；任务卡 + 任务中心链接；`requires_confirm`。
3. 统一 `upload://` 与聊天附件解析。
4. ToolsHub「问问 AI」入口；系统提示词补全示例。

### Phase 3：体验与外露（约 2 周）

1. 确认卡产品化、调用历史与可复现参数导出。
2. 速率限制与审计日志。
3. `cygnusx-tools` 作为稳定 MCP 契约，可被外部 Agent 调用（若需要）。
4. 评估是否值得把部分 TS processor 抽成共享算法（或接受长期 shim 简化版）。

---

## 六、需要新增/修改的文件

| 文件 | 动作 | 说明 |
|------|------|------|
| `tool_configs/tools_schema.yaml` | 新建 | LLM schema + mode + 字段白名单 |
| `src/cygnusx/tools/schema_loader.py` | 新建 | 加载/校验/热重载 |
| `src/cygnusx/application/services/tool_bridge_service.py` | 新建 | 校验、分发、摘要化、async 仅 submit |
| `src/cygnusx/tools/shims/volcano.py`（等） | 新建 | 轻量后端 shim |
| `src/cygnusx/infrastructure/mcp/presets.py` | 修改 | 注册 `cygnusx-tools` builtin |
| `src/cygnusx/application/services/agent_service.py` | 修改 | 自动注入 cygnusx-tools |
| `src/cygnusx/application/services/chat_service.py` | 小改 | 双通道 result：LLM 摘要 + SSE ui_payload |
| `src/cygnusx/api/...` 可选 `POST /tools/invoke` | 可选 | 调试 Bridge |
| `frontend/src/components/ai-chat/types.ts` | 修改 | `ChartData.type` 增加 `plotly` |
| `frontend/src/components/ai-chat/KimiMessageItem.vue` | 修改 | Plotly / 表格 / 任务卡 / 确认卡 |
| `frontend/src/views/BioTools/ToolsHubView.vue` | 可选 | 「问问 AI」 |

---

## 七、关键设计决策（修订）

| 决策点 | 推荐方案 | 理由 |
|--------|---------|------|
| 工具 schema 放哪 | `tools_schema.yaml` 独立文件 | 不污染卡片注册表；可热重载 |
| 与 Agent 集成 | **优先 builtin MCP `cygnusx-tools`** | 复用 `call_tool` 路径，少改编排核心 |
| 纯前端工具 | 高频 **轻量 shim** + 其余 **open_page** | 兼容闭环，控制双实现成本 |
| 异步工具 | **只 submit**，不在 Bridge/SSE 内长轮询 | 避免占 worker、超时、坏体验 |
| 大结果 | **llm 摘要 + ui 完整载荷 / result_ref** | 适配现有 4000 截断，前端仍可出图 |
| 大数据入参 | **upload:// / 附件**，禁止大 CSV 进 args | 保护 context 与费用 |
| 工具命名 | **`cygnusx_` 前缀** | 避免与 MCP/web_search 冲突 |
| 后端调用 | **进程内 service**，非 HTTP 自调用 | 少 hop、鉴权上下文清晰 |
| 身份与权限 | 复用 JWT `user_id` + 用户目录 | 与 enrichment 等现有工具一致 |
| 结果渲染 | 扩展 charts 支持 plotly + 任务/确认卡 | 复用消息组件，补齐缺口 |

---

## 八、风险与规避

| 风险 | 规避 |
|------|------|
| LLM 参数错误 | JSON Schema 校验 + 明确 error 回灌，允许模型下一轮修正 |
| tool_result 4000 截断导致图/表丢失 | 强制 `llm_result_fields`；完整数据走 `ui_payload` |
| 聊天侧仅 ECharts | Phase 1 同步做 Plotly 渲染，否则 shim 白做 |
| 前后端实现漂移 | shim 只覆盖核心路径；完整交互仍走工具页 |
| 异步任务拖死 SSE | 禁止 Bridge 内长轮询；任务卡 + 任务中心 |
| LLM 刷重计算 | `requires_confirm` + 速率限制 + `max_rounds` |
| 工具名冲突 | `cygnusx_` 前缀 + 启动时唯一性检查 |
| Schema 维护成本 | 新增工具 PR checklist：卡片 yaml + schema yaml +（可选）shim |
| 用户数据泄露 | 文件归属校验；禁止绝对路径；日志不落敏感全量数据 |

---

## 九、与代码的关键锚点（实现时对照）

| 能力 | 位置 |
|------|------|
| Agent 工具闭环 | `chat_service.py` → `stream_agent_chat`（约 436–718 行） |
| 工具列表组装 | `agent_service.py` → `assemble_context`（约 309 行） |
| MCP 调用 / builtin handler | `infrastructure/mcp/client.py`、`presets.py` |
| tool_result 截断 | `chat_service.py` 约 686–688 行 `[:4000]` |
| 工具卡片注册 | `tool_configs/tools_setting.yaml`、`tools/registry/` |
| KEGG 同步实现 | `src/cygnusx/tools/enrichments/`（api/service/runner） |
| 建树异步 | `src/cygnusx/tools/phylogenetic_tree/` |
| 前端火山逻辑 | `frontend/src/utils/volcanoProcessor.ts` |
| 聊天图表类型 | `frontend/src/components/ai-chat/types.ts`（当前仅 echarts） |

---

## 十、结语

CygnusX 已具备 Agentic 基础设施（SSE、MCP builtin、多轮 tool 闭环）。联动工作的本质，是把工具箱从「前端卡片注册表」升级为 **「LLM 可消费的 schema + 进程内执行桥」**，并处理好 **结果体积、异步生命周期、双实现边界**。

**推荐实施主线**：

1. **builtin MCP `cygnusx-tools` + ToolBridge**  
2. **先 KEGG（零双实现）→ 再 volcano 轻量 shim**  
3. **摘要回灌 LLM，完整图/表给前端**  
4. **异步只提交，确认后再跑重任务**

按此路径推进，可在较少改动现有编排的前提下验证闭环，再逐步扩大工具覆盖面。
