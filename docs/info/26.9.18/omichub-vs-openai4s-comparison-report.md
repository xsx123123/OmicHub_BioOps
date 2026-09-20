# OmicHub（CygnusX）× OpenAI4S 对比报告 — 远程连接 / Agent 执行 / Notebook 机制

> 调查日期：2026-09-18。
> 左侧代码基线：OmicHub 当前工作区 `/home/zj/zj_code_libarary/OmicHub`（src/cygnusx + frontend + mcp-server + deploy）。
> 右侧代码基线：OpenAI4S `main`（a6955de4），依据《remote-and-notebook-run-map.md》与仓库 AGENTS.md 双源核对。
> 对照框架沿用调查文档的 A（远程连接）/ B（Agent 运行科学代码）/ C（Notebook 前端）/ D（结论）四节。

---

## 0. 一句话总览

| 维度 | OpenAI4S | OmicHub（CygnusX） |
|---|---|---|
| 核心范式 | **Code-as-Action**：代码是引擎原生动作，跑在**持久 kernel 进程**里 | **Tool-as-Code**：代码是普通 function tool，跑在 **Docker 容器内一次性进程**里 |
| 会话形态 | Notebook 是**不可变执行历史的实时投影**，可确定性导出 .ipynb | 消息流 + tool 卡片 + 文件产物面板，历史是**落库快照重建** |
| 远程能力 | 出站 WSS 分享隧道 + 用户自有机器远程计算（SSH/BYOC） | 平台自身 HTTP 分享端点 + 平台管理的 Slurm/MAS 计算节点（SSH/BYOC 无） |
| 规模定位 | 单机个人科研智能体（stdlib 零依赖核心） | 多用户生信平台（FastAPI + Celery + Docker Compose + 多队列） |

两仓不是同一重量级的对位产品：OpenAI4S 把"一个人 + 一台机器上的科研闭环"做深；OmicHub 把"多租户生信分析平台"做宽。下述对比中，"OmicHub 缺 X"多数时候是**取舍**而非缺陷，但确实标记了可移植的能力缺口。

---

## A. 远程连接

### A1. 只读会话对外分享

| | OpenAI4S（Share/Relay） | OmicHub（Studio Sharing） |
|---|---|---|
| 入口 | `openai4s/share/tunnel.py` `TunnelClient`、`share/relay.py` `openai4s relay serve` | `src/cygnusx/application/services/studio_sharing.py:27` `create_share()` |
| 通道 | daemon → **出站单条 WSS 隧道** → 公网 relay → 访客（NAT 后机器可发布） | 平台自身 FastAPI **HTTP 快照端点**（`api/v1/studio.py:320-345`，`GET /shared/{token}` / `/artifacts` / `/report`） |
| 认证 | relay 侧 token 指纹认证（takeover/conflict/CAS） | 256-bit token，库存 sha256 hash，可设过期（`studio_sharing.py:27-70`） |
| 内容 | **实时只读投影**（relay 只转发到只读 ShareRouter；帧解析两端共用 `server/ws_frames.py` 的 hardened RFC 6455 codec） | **静态只读快照**（消息列表 + 产物 path/size/mtime 清单；另有 `render_printable_report()` 自包含打印 HTML，`studio_sharing.py:73-146`） |
| 导出引入 | `share/fetch.py`：SSRF-hardened 下载（仅 HTTPS、逐跳重验、私网拒绝、流式上限） | 无对应物（下载走常规产物端点） |

**结论**：功能目标相同（只读分享），架构几乎正交。OpenAI4S 的隧道模型适合"本机 NAT 后向外发布"；OmicHub 的快照模型要求平台本身公网可达但实现简单、无隧道运维负担。OmicHub 侧明确没有出站 WSS 客户端 / relay 代码（全仓 `wss://` 仅出现在入站 WS 端点 docstring）。

### A2. 远程计算（host.compute vs 平台计算节点）

| | OpenAI4S | OmicHub |
|---|---|---|
| 提交面 | cell 内同步 `host.compute(...)`（`sdk/host.py`），`byoc:*` 与 `ssh:*` 双传输（`compute/manager.py:931` `ComputeManager`，`submit`:2029） | 无 SSH/BYOC；agent 不直接持有远程计算 facade |
| 远端类型 | **用户自有机器**（SSH alias 目录 `compute/registry.py` / BYOC provider） | 平台自有资源：MAS Apptainer worker（`infrastructure/mas/apptainer.py:15`，systemd 单元 `deploy/mas/`）、预留的 `RemoteSnakemakeExecutor`（`infrastructure/execution/remote.py:8`，HTTP→Slurm/SGE 头节点，**全仓无 import，未接线**） |
| 远端执行体 | stdlib-only 受限 helper 包 `openai4s_compute_provider/`（两级 secret scrub、凭据走 stdin/fd-3），OS 边界 `security/byoc_confinement.py`（anchor 不成立退出 71） | 容器内 sandbox-agent（`deploy/studio/sandbox_agent.py`，uid 10001、写路径归一化）+ Apptainer `--containall --cleanenv --no-home` |
| job 语义 | 状态机 `compute/states.py`（`unknown` 刻意为 live、终态不可重开）；**job 行先落盘**、幂等键 + UNIQUE 索引、`reconcile()` 只报告绝不重提交；产物 `{path,size,sha256}` manifest 对账（glob 落空 → exit 0 仍判 failed） | Overdrive DAG 任务状态机（`overdrive_execution_service.py`，`TERMINAL_TASK_STATUSES`），幂等 command_id + plan hash 校验；产物只有 path/size/mtime，无 sha256 对账 |
| 调度底座 | 进程内 FIFO coordinator | Celery 多队列（`celery_app/celery.py:64-93`：analysis/phylo_tree/blast_search/mas_apptainer…）+ RocketMQ + arq 混合路由（`task_queue/dispatcher.py:22`） |

**结论**：这是差距最大的一节。OpenAI4S 的 host.compute 是"把用户自己的 GPU/机器接入 agent"；OmicHub 的计算扩展是"平台管理员横向加计算节点"，agent 侧完全没有远程提交 facade。若 OmicHub 想让用户在自有机房/云主机上跑分析，`RemoteSnakemakeExecutor` 是一条现成但未接线的起点；若学习 OpenAI4S，则差距在 sha256 产物对账、幂等提交契约、reconcile-only 语义这三件可直接移植的工程细节。

---

## B. Agent 运行科学代码

### B1. 外循环

| | OpenAI4S | OmicHub |
|---|---|---|
| 循环位置 | `openai4s/agent/engine.py`（CLI 组合 `agent/loop.py`，Web 组合 `server/agent_run.py`） | legacy：`application/services/chat_service.py:2623` `_stream_agent_chat_inner()`（:4189 轮循环，默认 100 轮）；LangGraph 版：`infrastructure/execution/langgraph_runtime.py:35`（图 `llm_call → tool_exec → llm_call`） |
| 每轮动作路由 | **严格三选一**：有序原生 JSON tool 批次 / 唯一 Engine 属 `FinalizeAction` / 一个完整围栏 Python/R Cell（native 优先于 code） | 无动作类型区分：标准 OpenAI `tool_calls` 列表，`tool_exec_node` 内串行逐个执行（`langgraph_nodes.py:181`），结果截断 4000 字符回灌 |
| 代码的地位 | **引擎原生动作**（Cell 不是 tool；shell/科学计算/submit_output 刻意不设为 native tool） | **普通 function tool**（`sandbox_execute` / `chat_sandbox_execute` / `tool_orchestrate`） |
| 完成信号 | 唯一 `finalize_response` 或 cell 内 `host.submit_output(...)`；R cell/散文/取消/轮数耗尽都不算完成 | `ask_user` / `transfer_to_agent` 是工具级中断；轮数触顶注入强制收尾提示词（`langgraph_nodes.py:100-117`） |
| tool calling | provider 原生 JSON Tool（stdlib `urllib` 传输，OpenAI/Anthropic/Gemini 三协议） | provider 原生 JSON（OpenAI 兼容 `infrastructure/ai_provider/openai_compatible.py:241`，另有 LiteLLM/Kimi 适配器）+ MCP 客户端三传输（`infrastructure/mcp/client.py:189`） |

**核心差异**：OpenAI4S 的"Cell 是动作"换来的是：代码不进工具 schema 也不挤占 tool 轮次、Cell 可以携带完成语义（`submit_output`）、notebook 单元天然等于引擎动作。OmicHub 的"代码是 tool"换来的是：工具协议统一、审批/审计复用同一分发点、实现简单；代价是 notebook 单元只能事后从 tool_call 投影（见 C 节），且代码执行与工具竞争同一轮预算。

### B2. 内循环（cell 内同步回调宿主）——两者高度同构，但能力面不对等

OpenAI4S：cell 内 `host.llm/host.delegate/host.compute` → worker 发 `host_call` 帧 → `Kernel`（`kernel/manager.py:238`，`execute`:520）路由给 `HostDispatcher` → 写回 `host_response` → cell 恢复。`worker.py` 的 `_HOST_CALL_LOCK` 保证单帧事务；manager 每次重启 bump generation。

OmicHub 对应物：**PTC（`tool_orchestrate`）**，`application/services/ptc_orchestrator.py:246`：

- 子进程（宿主 Web 进程派生的 `sys.executable -I` 受限进程，:293-305）内注入 `call_tool(name, **args)` 前导代码（:88-174）；
- 向 stdout 写 `\x1e` 前缀 JSON-RPC 帧，父进程按白名单 `PTC_ALLOWED_TOOLS`（:44-61）校验后复用 `execute_studio_tool` 分发，响应写回子进程 stdin，`threading.Event` 阻塞等待（:139）；
- 失败抛 `RuntimeError`（:143）——与 OpenAI4S 的软失败契约 `{"error": msg}` 一一对应。

| 内循环能力 | OpenAI4S | OmicHub PTC |
|---|---|---|
| cell 内调 LLM | ✅ `host.llm` | ❌ 白名单无 LLM 回调 |
| cell 内委派 | ✅ `host.delegate`（并发子 agent，深度 4） | ❌（并行子 agent 是外层 tool `parallel_subagents`，`parallel_subagent_service.py:80`） |
| cell 内远程计算 | ✅ `host.compute` | ❌ |
| 执行环境 | 持久 kernel worker（惰性启动、状态跨 cell 保留） | 一次性子进程，状态不保留（600s 总超时、50 次子调用上限、rlimit、env 清空）；且**跑在宿主上而非容器**，PTC 自述安全边界弱于 Docker（:17-20） |
| R 支持 | Python/R 双 kernel 对称内循环（`r_worker.R` + `r_kernel.py`，fd3/fd4 帧） | PTC 仅 Python；R 只能走无回调的 `sandbox_execute`（language 枚举一值） |

**结论**：机制同构度惊人（同步 RPC、单帧事务、白名单路由、软失败变 RuntimeError），但 OpenAI4S 把内循环做成了**通用宿主通道**（LLM/委派/计算全走它），OmicHub 把它收窄成**平台工具编排通道**。若 OmicHub 想支持"编排代码中途问模型/派子 agent"，PTC 的白名单加一个 LLM handler 即可起步——这是四个方向中性价比最高的移植项。

### B3. 执行进程模型与沙箱

| | OpenAI4S | OmicHub |
|---|---|---|
| 进程 | 每语言一个**持久 worker 子进程**（per-cell `compile(code,"<kernel:N>")`、getrusage、dlopen guard），惰性启动；JSON-per-line 协议；FIFO 执行协调器（`execution/coordinator.py`）串行 Agent/REPL/生命周期写入 | 容器常驻（warm pool / Studio 懒启动+休眠），但**每次执行新起一次性进程**（`python -c <b64>` / `Rscript -` / 临时脚本），Redis busy lease 串行化，**无跨执行内存态**（状态靠文件系统） |
| 隔离 | Seatbelt/bubblewrap `auto|enforce|off`，enforce 失败即拒；strict 子进程 env allowlist | Docker 全硬化：`cap_drop ALL`、`no-new-privileges`、seccomp、read-only rootfs + tmpfs、mem/pids limit（`studio/manager.py:533-605`）；网络三档（none / whitelist + egress proxy `deploy/studio/egress_proxy.py`，拒 IP 字面量/私网/DNS rebinding） |
| 多租户 | 单用户产品，无此问题 | 平台数据只读挂载 + 工作区软链跳转红线（`manager.py:8-11`、`sandbox_agent.py`） |

**结论**：沙箱强度 OmicHub 更系统化（容器 + seccomp + 出站代理白名单是多租户平台应有的水平），OpenAI4S 的 bubblewrap 是单机产品的恰当规模。持久 kernel vs 一次性进程是范式级取舍：前者换来 cell 间状态、热库、执行历史可重放；后者换来实现简单、无泄漏顾虑、天然适配多租户回收。

### B4. 权限/审批/审计 与 子 agent

- **权限路由**：OpenAI4S 统一 `HostDispatcher` 信封（`host_dispatch.py` + `host/` 各服务）；OmicHub 在**工具分发点内联审批闸**（`studio_approval_service.py`，`APPROVAL_REQUIRED_TOOLS` + schema 动态名单，Redis TTL 300s，SSE `approval_request` + BLPOP 等 REST 决议，支持 always_allow 豁免与 PTC 整段一次审批）。OmicHub 的审批 UX（approve/reject/edit/modified_args）比 OpenAI4S 的 unattended-deny 默认值丰富，但拦截点分散在 legacy 循环与 LangGraph 两条路径里。
- **审计**：OpenAI4S 单信封天然单点；OmicHub 三层（`audit_logs` 表 + `infrastructure/studio/audit.py` 结构化日志 + `middleware/audit.py` HTTP 审计 + OTel span `agent.tool_dispatch`），覆盖广但查询需跨源。
- **委派**：OpenAI4S `host.delegate`（cell 内、深度 4、扇出 48）；OmicHub 三种形态——handoff（`agent_handoff_service.py`，会话内换 agent，≤10 跳）、并行子 agent（`parallel_subagents`，深度恒 1，requires_confirm 工具升级为父级审批）、AgentTeams 会诊（`integrations/agentteams/` bridge，HTTP 轮询领 Work Item + 幂等回执 + 只追加审计）。OmicHub 的协作面明显更宽（多智能体会诊室是 OpenAI4S 没有的）。

---

## C. Notebook 前端

### C1. 根本范式差异

- **OpenAI4S**：Notebook UI 是**不可变执行历史的实时投影**。cell 即引擎动作（B1），事件类型化 WS（`notebook_cell_chunk`:1483 / `notebook_cell_finished`:1540 / `producing_cell_id`:1605 / `kernel_status`），每 WS 类型单 handler（`frontend/src/features/notebook/install.ts`），前端按 `producing_cell_id` 只写目标 cell、`_seenChunks` 重放去重、完成态 memoize；`.ipynb` 从执行历史**确定性重导出**（`server/notebook_export.py`，语言元数据 + hash + zip）；可选 Jupyter KernelSpec 桥（`adapters/jupyter/bridge.py`，ZeroMQ 惰性导入，独立于 Web 会话）。
- **OmicHub**：**没有 notebook/cell/kernel 模型**。最小展示单元是 tool_call——每次 `sandbox_execute` 渲染成 `StudioCodeCard.vue` 一张卡（执行单元伪命名 `code_cell.{ext}`，:62-68）。主链路是 **SSE**（`useAgentChatStream.ts`，POST `/api/v1/chat/stream`，单一大 switch `handleStreamEvent()` 路由 ~30 种事件），不是 WS；仅终端与旧聊天用 WS。

### C2. 逐项对照

| 机制 | OpenAI4S | OmicHub |
|---|---|---|
| 框架 | Preact 10 + @preact/signals（TS strict） | Vue 3 + Pinia + naive-ui，CodeMirror 6/monaco、xterm.js、echarts/plotly |
| 输出定向 | `producing_cell_id` **严格**写入目标 cell | `tool_call_id` 精确匹配 + **无 id 回退到"最后一个同名 running 工具"**（`stores/agentHub.ts:2624-2635`）——正确性弱一档 |
| 重放去重 | `_seenChunks` 重放去重 | 无；断线仅"未收到任何内容才重试"（:531-535），否则报错 |
| scroll-follow | 120px 阈值 + reading-delay gate | rAF 合并吸底 + 用户上滑暂停 + 红点 `hasNewWhileAway` + easeOutCubic 回底（`KimiMessageList.vue:127-172`）——**比 OpenAI4S 更精细** |
| 富输出 | live figures、inline tables、traceback 高亮（XSS 有测试，`chrome.ts`） | 图片 base64、CSV 前 50 行 papaparse 预览、diff2html+DOMPurify；**无 traceback 语法高亮**；stdout 靠 Vue 插值天然转义；markdown-it `html:false` + DOMPurify |
| 执行历史 | 不可变历史 = 真相 | 落库 `metadata_json.tool_invocations` + `timeline` 重建工具卡与交错顺序；**流式中间 chunk 不落库**，瞬态审批态靠 Redis 补拉——刷新即丢失过程，只有终态快照 |
| 导出 | `.ipynb` 确定性重导出 | **无任何导出**（无 ipynb/jupyter/kernelspec 概念）；JBrowse 2 是基因组浏览器（iframe 嵌入 `JBrowseViewer.vue`），与 Jupyter 无关 |
| R/Python 同协议 | 是（双 kernel 同 UI 同协议） | 是（`["python","r","bash"]` 语言枚举 + 同卡片 UI），但无 kernel 抽象，三者都是往容器发脚本 |

**结论**：C 节是最不对称的一节。OpenAI4S 把 notebook 做成一等公民（历史即真相、可导出、可投影），OmicHub 把执行展示做成聊天消息的附件。OmicHub 若要补 notebook 能力，不需要先抄 UI——关键是**先有不可变执行历史这个存储语义**，导出与投影才有根基；否则 `_seenChunks`、memoize 这些前端技巧无的放矢。

---

## D. 总结论：各自优势与可移植点

### OmicHub 强于 OpenAI4S 的部分（大多是平台化维度）

1. **多租户沙箱系统化**：seccomp + cap_drop + read-only rootfs + 三档网络隔离 + 出站域名白名单代理（`manager.py:533-605`、`egress_proxy.py`）——OpenAI4S 的单机 bubblewrap 到多用户场景必须重做。
2. **调度底座**：Celery 多队列 + RocketMQ + arq 混合路由 + beat 回收 + 跨进程 Redis 租约，是真平台的任务底座；OpenAI4S 的 FIFO coordinator 是单机正确性设计。
3. **协作面**：handoff + 并行子 agent + AgentTeams 会诊室 + 审批四种决议（含 modified_args）——OpenAI4S 只有 cell 内 delegate。
4. **前端细节**：scroll-follow 交互、产物文件面板（lightbox/CSV 预览/diff）、xterm.js 终端、JBrowse 嵌入，产品完成度高。
5. **专用生信工具链**：`src/cygnusx/tools/`（gsea/deg/enrichments runner）+ pipeline Snakemake 引擎注册表（`execution/registry.py`）。

### OpenAI4S 强于 OmicHub 的部分（大多是科研交互维度）

1. **持久 kernel + Code-as-Action**：cell 间状态、执行历史即真相、代码不占 tool 轮次——这是"agent 当科学家用"与"agent 当客服用"的分水岭。
2. **通用 cell 内 RPC**：`host.llm/delegate/compute` 同步回调（B2），OmicHub 仅有收窄版 PTC。
3. **不可变历史投影 + .ipynb 导出**：可复现、可分享、可审计的科学产物。
4. **host.compute（用户自有机器接入）+ sha256 产物对账 + reconcile-only + 幂等提交契约**（A2）——工程细节可直接移植。
5. **出站分享隧道**（A1）与 SSRF-hardened fetch——NAT 后发布能力。
6. **进程卫生**：job 行先落盘、终态不可重开、`unknown` 刻意为 live、单帧事务锁、generation ABA 防护——一批"正确性优先"的小契约。

### 移植优先级建议（若 OmicHub 要吸收 OpenAI4S 的长处）

| 优先级 | 项 | 理由 | 落点 |
|---|---|---|---|
| P0 | PTC 白名单加 LLM 回调（cell 内问模型） | 机制已同构，增量最小、交互收益最大 | `ptc_orchestrator.py:44` `PTC_ALLOWED_TOOLS` |
| P1 | 执行历史不可变化 + hash 指纹 | notebook/导出/审计的共同根基 | `metadata_json.tool_invocations` 落库层 |
| P1 | 产物 sha256 manifest 对账 | 防"exit 0 但产物缺失"的假成功 | `studio_sharing.py:99-107` 与产物注册处 |
| P2 | .ipynb 确定性导出 | 有 P1 后近乎免费 | 新增 server 服务，参照 `notebook_export.py` 语义 |
| P2 | 输出 chunk 严格定向（去掉 fallback 匹配） | 一行正确性修复 | `agentHub.ts:2624-2635` |
| P3 | 远程执行 facade（接线 `RemoteSnakemakeExecutor`） | 平台级特性，需配合权限模型 | `execution/registry.py` + 新增 agent tool |
| P3 | 出站分享隧道 | 取决于部署形态（平台已公网则不需要） | 新模块 |

### 反向提醒（OpenAI4S 若参考 OmicHub）

OpenAI4S 自评的"过重"项（双循环 host RPC、604 skills、多代 env 治理）在 OmicHub 场景下多数仍然成立；但 OmicHub 的多租户沙箱三档网络隔离、出站白名单代理、审批 modified_args 决议、beat 空闲回收，是 OpenAI4S 走向多用户/服务器部署时绕不开的课程。
