# OmicHub 科研闭环改造 · 现状调查报告

> 版本：v1（2026-09-18）· 执行性质：只查不改（未修改任何代码）
> 代码基线：`/home/zj/zj_code_libarary/OmicHub`（src/cygnusx + frontend + deploy）
> 依据：调查任务书 v1 §3 提示词；交付格式严格按任务书 §3「交付格式」1–6 节。
> 本报告将被追加为任务书 Part 2 逐项核对。

---

## 1. 执行链路图（文字版，每步标注代码位置）

### 1.1 sandbox_execute（Studio 会话沙盒，主力链路）

```
LLM tool_call(JSON, OpenAI 兼容协议)
  → 外循环路由：legacy 手写循环 chat_service.py:4189（默认路径；LangGraph 版存在但 Studio 工具被显式分流，
    chat_service.py:4123-4126 "not studio_mode"，MAS orchestrator 同样排除 :4101-4105）
  → 审批闸（supervised 模式）：chat_service.py:4818-4919
      · 创建审批 → Redis studio:approval:{id}（TTL 300s，studio_approval_service.py:43,176-194）
      → SSE approval_request → BLPOP 等 REST 决议（api/v1/studio.py:711-796）→ record_approval_audit 落 audit_logs
  → 分发 execute_studio_tool（studio_tools.py:1360，sandbox_execute 分支 :1408-1409）
  → 超时判定：>600s 转 Celery 长任务（studio_tools.py:738-758，STUDIO_LONG_TASK_THRESHOLD_SECONDS=600，cap 3600s）
  → StudioSandboxManager.exec（infrastructure/studio/manager.py:931-968）
      · Redis busy lease 获取（manager.py:946，_set_busy :350-362，租约 max(300,min(timeout,3600)+120)s）
      · ensure_running 懒启动/复用容器（manager.py:415-658，一会话一容器，工作区 bind-mount :461-463）
      → UDS + httpx 流式 POST /exec（manager.py:954-957）
  → 容器内 sandbox_agent.py _stream_exec（deploy/studio/sandbox_agent.py:414）
      → asyncio.create_subprocess_shell（:482-490，start_new_session，cwd=/workspace，RLIMIT_CPU=timeout+60 兜底 :569-588）
      → 运行副本+全量日志写 output/logs/exec-{id}.{py|R|sh} / exec-{id}.log（:419-451）
      → NDJSON 行事件回传（流内 stdout/stderr 上限 10KB，溢出写 /workspace/.logs/ :493-541）
  → 产物登记 register_artifact_report（studio_context_service.py:624-641 触发 archive_studio_run 归档）
  → busy lease 释放（manager.py:966-968）
  → 落库：persisted_tool_invocations + timeline 随 AI 消息 metadata_json 落 chat_messages
      （chat_service.py:5220-5247，timeline :5209-5215；载荷超 200KB 替换为 _cygnusx_payload_truncated，
       chat/utils.py:52-66）
  → 前端：tool_output SSE 增量（按 tool_call_id 定向，无 id 回退最后一个同名 running 工具，
      agentHub.ts:2624-2635）→ StudioCodeCard.vue 渲染；tool_result 的 ui_payload 为终态
  → 归档：project_archive_service 写 runs/{分析名}-{时间戳}/{README.md（含产物MD5）, environment.json, AGENTS.md 追加}
      （project_archive_service.py:78-129, 192-244, 252-294）
```

### 1.2 chat_sandbox_execute（聊天轻量沙盒）

```
LLM tool_call → 审批闸（仅会话显式 supervised 才拦，chat_service.py:4944-5027，注释 :4945-4948；
  LangGraph 路径 langgraph_runtime.py:165-169 直接执行 execute_chat_sandbox、无审批、无增量 tool_output——语义不一致）
  → stream_chat_sandbox_tool（chat_sandbox_tools.py:530）→ execute_chat_sandbox（:369）
  → SandboxService.create_session（sandbox_service.py:53，用户级容器亲和：每用户一个容器跨会话复用）
  → SandboxPool.get_or_create_container（pool.py:173，warm 队列取或 _warm_one 新建 :197-237）
  → Docker exec（pool.py:399-412，python -c <b64> / Rscript - / bash -s，:364-378）
  → _timeout_guard 到点 pkill -9（pool.py:429-461）
  → 产物 copy_dir_out：容器 /tmp/chat_output + /workspace/output → 宿主 users/{uid}/workspace/chat-output/{sid}/output
      （chat_sandbox_tools.py:138-224，交付目录每次执行前重置 :81-104 防跨会话串扰）
  → file_records 注册（source=CHAT_SANDBOX）→ ui_payload（stdout/stderr 全量）落库 → ChatCodeCard.vue
```

### 1.3 tool_orchestrate / PTC（编排代码 + 同步回调宿主）

```
LLM tool_call → 审批闸（对 tool_orchestrate 整段一次审批，chat_service.py:4842-4919；子调用不再逐次过闸）
  → run_orchestration（ptc_orchestrator.py:246）
  → 宿主派生子进程 asyncio.create_subprocess_exec(sys.executable, "-I", script)（:293-305，
      cwd=临时目录、env 仅留 UTF-8、rlimit CPU/AS(512MB)/FSIZE(16MB) :177-187、总超时默认 600s 上限 1800s :63-64）
  → 子进程内注入 call_tool()/parallel_calls() 前导代码（:88-174）
  → stdout 写 \x1e 前缀 JSON-RPC 帧 → 父进程 _handle_call（:332-378）
      · 白名单校验 PTC_ALLOWED_TOOLS 13 个工具（:44-61, :414-419）+ 50 次子调用上限（:420-428）
      · 复用 execute_studio_tool 分发（:229-243）
  → 响应写回子进程 stdin，threading.Event 阻塞（:139），失败抛 RuntimeError（:143）
  → llm_payload（用户 print 汇总 :446-462）+ ui_payload（子调用明细）落库
```

### 1.4 会话重建链路（刷新页面）

```
进入会话 → 读 chat_messages（含 metadata_json）
  → tool_invocations 重建工具卡（agentHub.ts:1745-1771）；ask_user 还原澄清卡（:1773-1796）
  → timeline 恢复文本/工具交错顺序（:1798-1809）
  → 审批态从 Redis listPendingApprovals 补拉（:1837-1861）；overdrive run 走 recoverOverdriveRun
    DB 游标重放（agentHub.ts:572-638 + api/v1/chat.py:333-374）
  = 终态快照 + 交错时间线；流式中间 chunk 不可恢复（未落库）
```

---

## 2. 「能力 × 现状」矩阵

### A. 会话与执行模型

| # | 能力 | 现状 | 代码位置 |
|---|---|---|---|
| A1 | 三个执行工具定义与分工 | 已实现。chat=轻量聊天（用户级容器）、studio=工作台（会话级容器+长任务转 Celery）、PTC=编排+回调宿主 | chat_sandbox_tools.py:31；studio_tools.py:160,434,722；ptc_orchestrator.py:246 |
| A2 | warm pool | 已实现（chat：默认 2/最大 10，空闲 300s 回收） | pool.py:102-262；core/config.py:409-420；sandbox_service.py:137-162（每分钟回收） |
| A3 | Studio 懒启动+休眠+回收 | 已实现（一会话一容器；beat 每 5 分钟回收 idle>30min；工作区保留 7 天） | manager.py:415-658, 882-926；tasks/studio.py:25-291 |
| A4 | busy lease 串行化 | 已实现（Redis ZSET 双写进程内字典，回收/休眠/清理均先查 busy；Redis 故障降级进程内） | manager.py:350-390, 884/905/917 |
| A5 | 执行超时/资源限制 | 已实现但三通道口径不一（见 §3 风险表） | pool.py:392,429-461；sandbox_agent.py:60-61,417,569-588；ptc_orchestrator.py:63-68,177-187 |
| A6 | 工作区文件系统持久化 | 已实现（Studio 工作区 bind-mount，容器回收不丢；chat 沙盒无挂载只留 copy-out 产物） | manager.py:461-478, 882-883；chat_sandbox_tools.py:138-224 |
| A7 | 跨执行状态（内存/包环境） | 缺失。两沙盒 pip 包装随容器回收必丢；仅文件系统状态保留 | pool.py:209-229（无 volumes）；manager.py:581（read-only+tmpfs） |

### B. 历史与可复现（调查重点）

| # | 能力 | 现状 | 代码位置 |
|---|---|---|---|
| B1 | tool_invocations 落库 | 已实现（tool_call_id/tool_name/arguments/success/result/ui_payload/checkpoint；result+ui_payload 超 200KB 整体截断为标记） | chat_service.py:5220-5233；langgraph_runtime.py:332-354；chat/utils.py:52-66 |
| B2 | timeline 交错顺序 | 已实现（kind=text/tool 数组，随完成态落库） | chat_service.py:5209-5215, 4261-4273；langgraph_runtime.py:217-222, 372-379 |
| B3 | 流式中间 chunk 落库 | 缺失。tool_output 增量只走 SSE 不落库（证据：chat_sandbox_tools.py:558-566 无 DB 写入；langgraph_runtime.py:165-169 注释明示）；例外：正文 text 每 5 chunk 以 streaming 态刷库 | chat_service.py:4226-4230 |
| B4 | 瞬态状态 | 部分实现。Studio 审批 Redis TTL 300s；另一套 tool_confirmation_service 是进程内内存 TTL 1800s（多进程不可见） | studio_approval_service.py:43,176-194；tool_confirmation_service.py:9,66-68 |
| B5 | 刷新重建 | 已实现，但重建的是**终态快照**非完整过程 | agentHub.ts:1745-1866 |
| B6 | 运行详情落盘（日志/脚本/退出码） | 已实现（Studio：exec-{id}.log+脚本副本；chat：仅 ui_payload 落库+产物 copy-out；pipeline：runs/ 目录） | sandbox_agent.py:419-451；task_service.py:308-322 |
| B7 | 环境快照四件套（conda-explicit/environment.yml/software-versions/pip-freeze） | **未找到平台生成点**。仅存在于提示词契约（要求模型写进 output/）+ 测试固化；非平台强制、无关联键 | sandbox_protocol.md:16,52；test_prompt_config_contract.py:45-46 |
| B8 | 平台环境快照 | 已实现但为"注册表声明级"（镜像名+runtime_images.yaml 声明的 languages/software+平台 git_sha → environment.json），非容器内实测 | project_archive_service.py:78-129；runtime_image_loader.py:158-188 |
| B9 | 项目级调用历史表 | 缺失（无 project_runs/invocation 表）。项目历史=磁盘 runs/ 目录 + AGENTS.md append-only + overdrive_runs/events 两张专用表 | project_archive_service.py:221-244；models/overdrive.py:16-80 |
| B10 | "用历史对话恢复项目"重放链路 | **未找到**。现有恢复=回收站会话状态恢复（deleted→active）+ 重开会话渲染终态快照；工具结果不重新执行；无项目克隆/重建工作区入口 | ProjectDetailView.vue:133-141；api/v1/chat.py:1105-1113 |
| B11 | 分享快照 | 已实现但**不含 metadata_json**（消息只带 role/content，工具卡/timeline/usage 全丢）；产物清单 path/size/mtime（无 sha256） | studio_sharing.py:73-116, 95-107 |
| B12 | 导出 | 部分实现。可打印报告 HTML、产物下载、任务 Excel；**无会话历史导出、无 .ipynb** | studio.py:346,911；TasksView.vue:147 |

### C. 安全、审批与审计

| # | 能力 | 现状 | 代码位置 |
|---|---|---|---|
| C1 | 审批名单 | 已实现。硬编码 6 工具 ∪ tools_schema.yaml requires_confirm 动态 5 工具（读失败安全降级回退硬编码）；仅 supervised 模式拦截 | studio_approval_service.py:30-80；tools_schema.yaml:119,772,786,824,847 |
| C2 | 两条路径审批一致性 | 部分实现。**LangGraph 路径的 chat_sandbox_execute 无审批闸**（直接执行）；Studio 工具因分流永远走 legacy 始终有闸 | langgraph_runtime.py:109-179；chat_service.py:4123-4126 |
| C3 | PTC 整段一次审批 | 已实现 | chat_service.py:4842-4919；ptc_orchestrator.py:229-243 |
| C4 | 审计四层 | 已实现但分散：audit_logs 表（审批+HTTP 写操作）、studio/audit.py 结构化日志（不落库）、middleware/audit.py（POST/PUT/PATCH/DELETE）、OTel agent.tool_dispatch span（仅 LangGraph 节点，legacy 无） | studio_approval_service.py:83-142；audit.py:14-21；middleware/audit.py:22-111；langgraph_nodes.py:218-226 |
| C5 | 单次执行审计计数 | supervised+legacy：audit_logs 最多 2-3 行（REST+决议，超时补记）；auto/plan 无审批时 **audit_logs 为 0 行** | api/v1/studio.py:750-761；chat_service.py:4892-4903 |
| C6 | Studio 容器硬化 | 已实现且严格（cap_drop ALL/no-new-priv/seccomp/read-only+tmpfs noexec/非 root/mem/pids/网络两档+出站白名单代理防 DNS rebinding） | manager.py:73-99, 565-611；egress_proxy.py:28-77 |
| C7 | chat warm pool 硬化 | 部分实现，明显弱化（仅 mem/cpu_shares/network=none；**无** cap_drop/user/no-new-priv/seccomp/read-only/pids） | pool.py:202-230 |
| C8 | PTC 子进程隔离 | 部分实现（-I 隔离、env 清空、rlimit、白名单、宿主临时目录；自述弱于 Docker） | ptc_orchestrator.py:17-20, 177-187, 293-305 |

### D/E. 长任务与路径并存

| # | 能力 | 现状 | 代码位置 |
|---|---|---|---|
| E1 | Studio 长任务 | 已实现（>600s 转 Celery，cap 3600s） | studio_tools.py:738-758；studio_task_service.py:20 |
| E2 | analysis_flow 异步管道 | 已实现（prepare→confirm→submit 返 task_id→轮询；前端 2.5s 轮询卡片） | analysis_flow_tool_service.py:94-175；agentHub.ts:790-860 |
| E3 | Overdrive DAG | 已实现（任务默认 30min、链 45min；Celery advance_run 重入调度） | overdrive_execution_service.py:27-84, 342-402；_overdrive_limits.yaml |
| E4 | MAS Apptainer | 已实现（24h 子进程，但撞 Celery 全局 6h 硬上限） | tasks/mas.py:954-965；celery.py:58-59 |
| E5 | RemoteSnakemakeExecutor | **未接线**。全仓无调用方；注册表只注册 snakemake/binary，未知引擎静默回退本地 | execution/remote.py:8-66；registry.py:10-22；tasks/analysis.py:59-60 |
| E6 | legacy vs LangGraph 并存 | 默认 legacy（chat_runtime_refactor_enabled 默认 False）；**LangGraph 聊天运行时在产线无任何入口**（仅单测设 runtime=langgraph）；官方注释 deprecation 倒计时 | core/config.py:34,167-169；chat_service.py:4106-4108；chat_router_service.py:26-37 |

---

## 3. 风险清单（按严重度分级）

### 3.1 严重度：阻断历史恢复等价性（与本任务第一担忧直接相关）

| # | 风险 | 证据 |
|---|---|---|
| R1 | **载荷 200KB 硬截断**：tool result/ui_payload 超 200KB 整体替换为 `{"_cygnusx_payload_truncated": True}`，被截断的调用在重建/分享/导出中永久丢失内容，且重建时无"已截断"的用户可见提示 | chat/utils.py:52-66；截断只作用 result/ui_payload，arguments 不截断（超长代码参数另有爆库风险） |
| R2 | **流式过程不可恢复**：tool_output 增量不落库，刷新后只剩终态 ui_payload；长执行的中间过程（进度、逐步输出）永久丢失 | chat_sandbox_tools.py:558-566；langgraph_runtime.py:165-169 |
| R3 | **工作区 7 天保留期**：科研迭代跨周的会话，工作区文件被 purge 后，"历史 + 产物清单"还在但产物实体不可下载，归档 README 里的产物 MD5 成死链 | manager.py:893-908；tasks/studio.py:25-86；workspace_retention_days=7（studio_loader.py:33） |
| R4 | **分享快照丢 metadata_json**：被分享方看不到工具卡/timeline，只有纯文本消息+产物清单，"交接"语义弱于"展示" | studio_sharing.py:73-116（messages 仅 role/content/created_at） |
| R5 | **环境快照是契约而非事实**：四件套靠提示词让模型写，平台不校验存在性/完整性；注册表级 environment.json 是声明非实测。若恢复链路假设"环境快照可重建一切"，该假设目前不成立 | sandbox_protocol.md:16,52；project_archive_service.py:78-129 |

### 3.2 严重度：阻断多租户安全

| # | 风险 | 证据 |
|---|---|---|
| R6 | **chat warm pool 硬化缺口**：与 Studio 基线差距显著（无 cap_drop/非 root/seccomp/read-only/pids）；该容器执行模型任意代码且按用户亲和跨会话复用 | pool.py:202-230 vs manager.py:570-594 |
| R7 | **跨会话串扰防护单薄**：chat 容器每用户一个、跨会话复用，隔离仅靠每次执行前重置交付目录（/workspace/input、/tmp/chat_output） | chat_sandbox_tools.py:81-104, 400-413 |

### 3.3 严重度：安全隐患

| # | 风险 | 证据 |
|---|---|---|
| R8 | **LangGraph 路径审批缺失**：chat_runtime_refactor_enabled 一旦打开，chat_sandbox_execute 不再过审批闸，与 legacy 语义分叉 | langgraph_runtime.py:165-169 对比 chat_service.py:4944-5027 |
| R9 | **PTC 在宿主进程派生**：编排代码（模型产出）以宿主 Python 身份运行，虽有 -I/rlimit/白名单，但弱于 Docker 自述明确；加 LLM 回调会放大其数据可达面 | ptc_orchestrator.py:17-20, 293-305 |
| R10 | **tool_confirmation_service 进程内内存**：TTL 1800s 且多进程不可见，analysis_flow 确认态在 worker 拓扑下不可靠 | tool_confirmation_service.py:9,66-68 |
| R11 | **auto/plan 模式零审计行**：无审批的执行在 audit_logs 不留记录，仅有日志/落库 metadata | §C5 证据链 |

### 3.4 严重度：体验不一致

| # | 风险 | 证据 |
|---|---|---|
| R12 | tool_output 无 id 时回退"最后一个同名 running 工具"，并发同名片工具时输出可能写错卡片 | agentHub.ts:2624-2635 |
| R13 | LangGraph 路径不发射增量 tool_output（一次性透出），前端体验与 legacy 分叉 | langgraph_runtime.py:166-168 |
| R14 | MAS 24h 子进程超时设计与 Celery 全局 6h 硬上限矛盾，长任务必死于 Celery 超时 | tasks/mas.py:954-965 vs celery.py:58-59 |

---

## 4. D 节四项目标能力接入就绪度评估

### 4.1 会话状态跨执行保留（工作区文件系统方案，不引入持久 kernel）

- **现有可复用**：Studio 工作区 bind-mount 跨容器回收/休眠/重建全保留（manager.py:461-463, 882-883），预建目录约定（input/ref/scripts/output/{results,figures,logs,tmp}，manager.py:163-196）；busy lease 已保证回收不会打断执行；多租户隔离（一会话一容器一目录、平台数据只读挂 /data/platform）在方案下继续成立。
- **缺口**：chat 沙盒无状态（容器无挂载，状态只 copy-out 产物）；pip 包装环境两沙盒都随容器回收丢失；跨执行"内存态"（Python 变量）按既定原则不做，但需定义"哪些状态靠工作区文件恢复"的 agent 侧约定（类似 sandbox_protocol.md 的协议强化）。
- **冲突点**：与 R3（7 天工作区保留期）直接矛盾——科研闭环会话可能跨周，保留期需按会话活跃度延长或随项目生命周期走；与 R5 叠加：状态文件在、环境不在（包丢失），恢复后首次执行可能缺包。
- **最小侵入落点**：`studio_loader.py:32-33`（idle_ttl/workspace_retention 配置化与会话级覆盖）；`manager.py:163-196`（预建目录加 `state/` 约定）；`sandbox_protocol.md`（协议层写清"跨执行状态必须落工作区文件"）；包环境可在 runtime-images 注册表加 profile 粒度，避免依赖容器可写层。

### 4.2 cell 作为执行一等单元（notebook 式展示与寻址，不改执行器）

- **现有可复用**：timeline 已提供文本/工具交错顺序（chat_service.py:5209-5215）；tool_invocations 已有 arguments+ui_payload（代码与输出俱在）；StudioCodeCard 已是"代码卡"投影；language 枚举 python/r/bash 已是 schema 一值（studio_tools.py:175）。
- **缺口**：无 cell 寻址 id（现在只有 tool_call_id 且可回退匹配，R12）；无"cell 序号/执行计数"（同一工具多次执行的历史折叠依赖 arguments 区分）；流式 chunk 不落库使 cell 的过程态无法回放（R2）。
- **冲突点**：无硬性冲突——展示层升级不改执行语义；但 cell 语义一旦引入，"tool 卡片"与"cell"两套词汇会在 agent 可见 schema 与前端并存，需统一。
- **最小侵入落点**：`chat/utils.py`（落库信封加 `cell_index`/`language` 冗余字段，纯增量）；`agentHub.ts:2624-2635`（去掉 fallback 匹配，强制 tool_call_id）；`StudioCodeCard.vue`（按 cell_index 分组渲染，卡片内部不改）。

### 4.3 PTC 白名单增加 LLM 回调（cell 内问模型）

- **现有可复用**：PTC 的同步 RPC 通道、白名单路由、50 次上限、软失败变 RuntimeError 全部现成（ptc_orchestrator.py:332-378）；宿主侧 LLM 调用能力在 chat_service/langgraph_runtime 均有实现可抽出复用；50 次上限天然约束递归深度。
- **缺口**：LLM handler 无现成组件——PTC 执行时所在会话的模型配置（session.model_id）取用、流式/非流式选择、计费/token 记账、并发与宿主 LLM 限额共享。
- **冲突点（放大 R9）**：PTC 在宿主上运行，cell 内问模型意味着"模型产出的代码可直接驱动宿主发起任意提示词的 LLM 调用"——提示注入面从"平台工具"扩到"任意语义查询"。需在 handler 内做：system 锚定（禁止泄漏宿主上下文）、记录全部进出 PTC 的 LLM 调用审计（补 R11）、纳入审批名单或至少纳入审计。
- **最小侵入落点**：`ptc_orchestrator.py:44-61`（白名单加 `llm_query`）；新增 host 侧 handler（放 application/services/ptc_llm_handler.py 一类，复用 ai_provider 层）；`chat_service.py:4944` 前后复用现有审批/审计拦截模式。

### 4.4 不可变执行历史 + 流式 chunk 落库 + sha256 对账 + .ipynb 导出

- **现有可复用**：落库点集中（仅 chat_service.py:5220-5247 与 langgraph_runtime.py:332-354 两处）；timeline+tool_invocations 字段已覆盖 .ipynb 导出所需的大部分（code=arguments、outputs=ui_payload、language、顺序=timeline）；产物 MD5 已在归档 README 生成（project_archive_service.py:252-294）。
- **缺口**：①无不可变语义——metadata_json 是浅合并可改写（session_service.py:145-165），无版本/hash；②chunk 不落库（R2）；③sha256 无（归档用 MD5 且只针对归档时刻产物，非执行对账语义"glob 落空即失败"）；④导出零基础（B12）。
- **冲突点**：chunk 落库与"恢复等价性"——chunk 落库改变重建语义（从终态快照变过程回放），需保持重建仍可用终态快照（双读：有 chunk 走过程，无 chunk 走快照），否则刷新性能与旧会话兼容受损。不可变化与现有"消息 update 浅合并"写入模式冲突，需改为 append-only 事件列或版本列。
- **最小侵入落点**：新增 `chat_message_events` append-only 表（chunk/事件流，(message_id, seq) 主键）→ 写点挂 stream 产出处（studio_tools.py:1509-1512 等）→ sha256 对账挂产物登记点（studio_context_service.py:624-641 / file_records 注册处，执行完成时 hash 实测）→ .ipynb 导出做成只读投影服务（从 tool_invocations+timeline 重放，参照 OpenAI4S notebook_export 语义但不必引入其内核）。

---

## 5. 演进建议与理由

**路线声明**：以下建议遵循任务书既定原则——吸收契约不吸收架构（不引入持久 kernel、执行器保持容器+一次性进程）。

| 顺序 | 建议 | 性质 | 理由 |
|---|---|---|---|
| 阶段 0（止血） | ① 落库信封加 `truncated` 显式标记并在前端展示"内容已截断"；② 工作区保留期与会话状态/项目生命周期挂钩（活跃会话不 purge）；③ 去掉 tool_output fallback 匹配（强制 tool_call_id） | 平台自有 | 三条都是一行级改动，直接消除 R1/R3/R12 的等价性破坏；不动架构 |
| 阶段 0 | ④ PTC 白名单加 `llm_query`（带 system 锚定+全量审计） | 参考 OpenAI4S 契约 | host.llm 的同步 RPC 是 OpenAI4S 验证过的契约；PTC 通道现成，增量最小、交互收益最大 |
| 阶段 1 | ⑤ append-only 事件列（chunk 落库）+ 落库信封 hash | 参考 OpenAI4S 契约（不可变历史） | 历史即真相是其余一切（回放/导出/审计/交接）的地基；先落库层，UI 仍读终态快照 |
| 阶段 1 | ⑥ 产物 sha256 实测对账挂登记点 | 参考 OpenAI4S 契约 | "exit 0 但产物缺失/被截断"判失败；挂登记点成本最低（产物必经） |
| 阶段 2 | ⑦ cell 语义（cell_index/language 冗余 + 卡片分组 + 历史恢复的双读重建） | 平台自有路线 | 展示与寻址升级，依赖⑤ 的事件流才完整 |
| 阶段 2 | ⑧ .ipynb 只读投影导出 | 参考 OpenAI4S 契约 | ⑤⑦ 之后近乎免费；字段已齐 |
| 阶段 3 | ⑨ chat 沙盒硬化对齐 Studio 基线；⑩ LangGraph 审批闸补齐后再考虑打开 refactor 开关 | 平台自有 | R6/R8 是平台债，与科研闭环无关但会在新会话形态下被放大 |
| 观察 | RemoteSnakemakeExecutor 接线、MAS 与 Celery 6h 上限和解 | 平台自有 | 长任务承接的现实缺口（E4/E5/R14），但非闭环前置依赖 |

**不建议照搬的部分**：持久 kernel 进程与 generation 治理、双循环全量 host facade（delegate/compute）、OpenAI4S 的 604 skills 体系——与任务书原则一致，与容器+一次性进程底座不兼容或收益不成比例。

---

## 6. 「未找到」声明（含已检索路径）

| 任务书假设 | 结论 | 已检索路径 |
|---|---|---|
| 环境快照四件套的平台生成点 | 未找到。仅提示词契约（sandbox_protocol.md）+ 测试固化，平台不生成、不校验 | 全仓 grep `conda-explicit|environment.yml|software-versions|pip-freeze`、`env export|--explicit|pip freeze`：src/cygnusx、deploy/、根目录 |
| "用历史对话恢复项目"的重放/克隆链路 | 未找到。现有恢复仅回收站状态字段 + 终态快照渲染 | frontend/src（restore/恢复/历史）、studio_context_service.py、api/v1/（grep restore/replay/clone） |
| 项目级调用历史 DB 表 | 未找到。历史在磁盘 runs/ 目录 + AGENTS.md + overdrive 两表 | infrastructure/database/models/、repositories/ |
| 会话/.ipynb/notebook 导出 | 未找到 | frontend/src grep `ipynb|jupyter|kernelspec`、src/cygnusx grep `ipynb`（仅归档扩展名白名单命中） |
| legacy 循环的 OTel tool_dispatch span | 未找到（span 仅 LangGraph 节点） | chat_service.py grep `start_as_current_span` |
| chat 沙盒容器的 cap_drop/read_only/user/pids | 未找到（配置不存在） | pool.py:197-237 通读 |
| PTC 子调用级独立审批/审计 | 未找到（整段一次审批，子调用仅内存 records） | ptc_orchestrator.py、studio_approval_service.py |
| `sandbox.capability_denied`/`quota_exceeded` 两个审计事件的 emit 调用点 | 未找到（事件已定义） | manager.py、sandbox_agent.py grep |

---

## 附：对任务书旧判断的修正记录（供 §4 checklist 核对）

1. **任务书 §1 称"环境快照四件套全量落盘"为"现有可复现设计"** —— 证据显示这是提示词协议（sandbox_protocol.md:16,52）而非平台机制：模型可能被要求写、也可能漏写，平台无校验、无关联键。建议任务书改为"环境快照是软协议 + 注册表声明级 environment.json"。
2. **任务书 §1 称"后续重复执行和项目交接可以完全用历史对话恢复"** —— 代码中未找到重放/克隆链路；现有能力上限是"重开会话渲染终态快照 + 工作区文件还在则可下载"。恢复链路的隐含假设实际是"工具结果不重新执行、环境可从镜像声明重建"，而非任务书设想的完整重放。此修正反而**降低**了引入会话状态保留的等价性风险（现状本就不等价于重放，新增状态只需保证"状态可文件化"即可）。
3. **任务书 §3-B2 预设四件套有"生成位置与触发时机"可查** —— 见修正 1，答案是没有。
