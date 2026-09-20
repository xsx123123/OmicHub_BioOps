# CygnusX 科研闭环架构（as-built，2026-09-18）

> **时点说明**：本文记录 2026-09-18 交付的"科研闭环"改造（WP0–WP4）的 as-built 架构。施工依据为
> `docs/info/26.9.18/OmicHub科研闭环-实施手册.md` 与现状调查任务书；全部任务带真实 e2e 验收
> （`scripts/poc/e2e_*.py`，连真实 DB / Docker / Redis / 编排子进程），OpenAI4S 仓库仅只读核对
> 契约语义、零代码移植。验收状态以手册 W0-1 ~ W4-4 人工对照表为准。
>
> 适用范围：Studio / legacy 链路。LangGraph 路径除本文 §8.2 审批闸外不做科研形态扩展。

## 1. 会话工作区生命周期（四层模型）

```
活跃(active) ──dormant 线(90d 无活动)──▶ 休眠打包 ──▶ 平台归档 ──retention(180d)──▶ 到期删除
     │                                        │
     │  project 标 completed/handed_over      │ 用户点击 / 配额超限
     ▼                                        ▼
  解包恢复 ──复用懒启动+终态快照链路──▶ 重新活跃
```

- **配置**（`infrastructure/config/studio_loader.py`，`data/ai/studio.yaml`，mtime 热重载；
  管理页可在线改写 YAML 即时生效）：
  `retention.active_days=14`（活跃豁免窗口+purge 线）、`retention.dormant_days=90`、
  `quota.workspace_gb=500`、`quota.archive_gb=50`、`archive.backend=local|s3(占位)`、
  `archive.retention_days=180`；`workspace_retention_days` 退役为休眠候选线，不再是删除依据。
- **purge 豁免**（`tasks/studio.py _cleanup_expired_workspaces`）：近 active_days 有消息
  （聚合查 `chat_messages`）/ `sandbox_meta.pinned=true` / 绑定项目 / 分享中 —— 满足任一即跳过。
- **打包**（`application/services/workspace_archive_service.py pack_session`）：busy 复核 →
  幂等（`workspace_archives` 部分唯一索引 `uq_workspace_archives_session_active`）→ 归档配额 →
  tar.gz + manifest.json（逐文件 path/size/sha256 流式计算 + 环境四件套存在性校验，缺失记
  `missing_env_snapshot` 不阻断）→ 删本地工作区 → `sandbox_meta.workspace_archive` jsonb_set
  原子标记 → 项目级 AGENTS.md 幂等追加（含包路径 + manifest sha256）→ audit_logs。
- **归档存储**（`infrastructure/studio/archive_storage.py`）：`ArchiveStorageBackend` 接口隔离；
  Local 实现落 `{storage_path}/studio-archive/{user_id}/`（目录 0700/文件 0600，与 `studio/`
  平级的独立顶级目录，**不进任何容器挂载**）；非 UUID session_id 走 sha256[:12] 文件名分支；
  s3 占位（消费时显式 NotImplementedError）。
- **触发链**：beat `hibernate_dormant_workspaces`（04:30，先配额超限清理——按最久未访问依次
  打包——再 dormant 扫描，单轮上限 50）；项目 PATCH `status=completed/handed_over` 后台打包其下
  会话（`project_service._pack_project_sessions`，busy 跳过记日志）；admin 强制休眠。
- **解包恢复**（`unpack_session` + `POST /api/v1/studio/sessions/{id}/restore`）：幂等三态
  （`not_archived` / `idempotent:true` / 正常恢复）；解包前工作区配额校验（409 明确文案）；
  tar 只解 `workspace/` 子树并拒绝 `..` 逃逸；manifest size 校验、sha256 不一致仅告警；
  清标记走 jsonb 减法原子删键；**零容器操作**，恢复完全复用现有懒启动 + 终态快照链路。
- **到期清理**：beat `cleanup_expired_workspace_archives`（05:30），到期删包 + `deleted_at` +
  audit；7 天内到期进 admin overview `expiring_soon`。
- **DTO 契约**：会话列表/详情暴露 `workspace_archive: {package_id, created_at, expires_at} | null`
  （读自 `sandbox_meta.workspace_archive`）。注意与 `chat_sessions.status='archived'` 软删语义区分。
- **管理页**：`AdminWorkspaceArchiveView.vue` + `api/v1/admin/workspace_archive.py`
  （require_admin）：总览/每用户工作区与归档排行/expiring_soon/强制休眠/删包/配额与
  retention 在线修改（行级原子改写 studio.yaml）。
- **新表**：`workspace_archives`（迁移 `e2e0wp1a1b2c`）；`projects.status` 列（同迁移）。

## 2. 不可变执行历史（事件表 + 对账 + 信封 hash）

- **`chat_message_events` 表**（迁移 `f3a4b5c6d7e8`）：(message_id, seq) 联合主键，
  event_type/payload JSONB/created_at；只插不改不删。写点：Studio 流式 `tool_output` 逐 chunk
  （`studio_tools.py stream_studio_tool`）、chat 沙盒链路（`chat_sandbox_tools.py`）；
  正文 text chunk 沿用现有每 5 chunk 刷库机制不落事件表。
- **写入可靠性**（`chat_message_event_service.py`）：攒批 8 条/32KB 先到先刷，独立短生命周期
  session 单事务（与流式主链路事务解耦），失败降级为现状行为（记日志不阻塞）；seq 进程内
  单调计数器 + 撞主键时按 DB max(seq) 重分配一次。
- **信封 hash**：tool 调用完成落库时对信封计算 sha256 存 `payload_hash`（覆盖截断后载荷与
  cell 字段，排除 hash 自身，sort_keys 稳定序列化），可复算、可检出篡改。
- **双读重建**（`session_management.get_messages`）：含 tool_invocations 的消息先批量探查
  事件表，有事件则回放过程态（`metadata_json.tool_output_replay`，含
  `consistent_with_snapshot` 标记）；无事件的旧会话完全回落终态快照，DTO 与旧逻辑逐字节一致。
  截断提示（WP0）与审批态字段随终态快照原样保留。
- **产物 sha256 对账**（`artifact_manifest.py`）：执行完成对所声明产物实测 sha256——chat 沙盒
  每执行 manifest 进执行信封（llm/ui_payload）+ 新建 `file_records` 写 `checksum` 列；
  **声明落空 → `missing_artifacts` 告警**（信封平级字段，不静默假成功）；studio/归档每 run
  旁落 `manifest.json`（`{schema_version, archived_at, files:[{path,size,sha256}]}`），
  归档 README **MD5 保留 + sha256 并存**，environment.json 双摘要。契约借鉴 OpenAI4S
  manifest（仅 verified 条目可兑现声明、流式分块 hash）。

## 3. 声明式环境还原（替代容器快照）

- 触发点：`infrastructure/studio/manager.py ensure_running` 钩子（`_maybe_restore_environment`，
  既有启动逻辑零改动）：检测工作区 `conda-explicit.txt`（优先）/ `environment.yml` →
  容器内一次性 micromamba 安装（yml 先剥离 name/prefix；超时 900–3600s；持 busy 租约）。
- **门控**：仅 `research_mode.enabled=true 且 workspace_protocol="research"` 时执行（§5）；
  WP1 打包 manifest 标 `missing_env_snapshot` 的会话跳过（经打包审计 detail 查询）。
- 每容器生命周期只还原一次（container_id 标记 + 进程内锁）；结果（成功/失败/耗时/跳过原因）
  落 audit_logs（`resource_type='workspace_env_restore'`，200/500/204）。
- **失败不阻断会话**：降级基础环境运行，前端 warning toast 一次（`StudioSessionDetailDTO.env_restore`
  透出，StudioView 按 `sessionId:file:reason` 去重）。
- **已知限制**：生产 `read_only_rootfs=true` 下 micromamba 无法写 /opt/conda，还原会走
  "失败→降级"链路；真正成功需平台级方案（tmpfs overlay 等），列观察项。

## 4. Studio 长任务 job 三契约（>600s 转 Celery 链路）

- **a) job 行先落盘**：幂等键（显式 `command_id` 优先，缺省按 user/session/代码/超时派生，
  ≤128 字符）随 job 行先 commit 再投递队列；`IntegrityError` 并发兜底返回已有行；
  投递失败标记 FAILED；`bind=True` 使 Celery 消息 id == DB task id。
- **b) 终态不可重开**：全局状态机 `FAILED/CANCELLED` 出边清空（域层 `VALID_TRANSITIONS`）；
  重试入口 `retry_studio_sandbox_task` 对终态 409（文案含终态名），存活态 409 "无需重试"。
- **c) reconcile-only**：beat `studio-long-task-reconcile`（600s）只报告/标记状态漂移
  （悬挂 QUEUED→FAILED、backend 已终态按结果恢复、滞留 RUNNING 只报告），**绝不自动重提交**。
- 新列 `tasks.idempotency_key` + UNIQUE 索引（迁移 `g4b5c6d7e8f9a`）。契约借鉴 OpenAI4S
  compute/states.py + compute/manager.py。

## 5. 科研形态（cell 投影 / .ipynb 导出 / 三开关）

- **cell 投影**：落库信封加冗余 `cell_index`（0 起，会话内按代码执行工具落库顺序单调，
  跨流式运行从 `max(cell_index)+1` 续编，纯派生）/ `language`，纳入 `payload_hash` 覆盖；
  前端 `cellTimeline.ts` 连续段归并分组（保时序、投影可逆）+ `StudioCellGroup.vue` 渲染，
  卡片内部实现零改动。
- **.ipynb 导出**：`GET /api/v1/chat/sessions/{id}/notebook`（属主复核，非属主 404）；
  nbformat 4.5，消息文本→markdown cell，截断条目→带说明 markdown + stderr 行（不静默丢弃）；
  **确定性导出**：无时间字段、cell id 由内容 sha256 派生、两次导出字节一致；
  `metadata.cygnusx.content_sha256` 平台注释。借鉴 OpenAI4S notebook_export 的确定性编码/
  语言元数据/安全文件名（未做 KernelSpec 桥）。
- **科研模式三开关**：会话级存 `sandbox_meta.research_mode`（jsonb_set 原子），项目级存
  `projects.settings` JSONB（迁移 `h5i6j7k8l9m0`），新会话创建时从项目继承（显式传入优先）；
  `PUT /api/v1/chat/sessions/{id}/research-mode`（audit_logs `research_mode_change`）。
  子开关：渲染形态（消息流/cell 时间线）、工作区协议（standard/research，科研态给 state/
  目录约定提示）、PTC 白名单（基础集 / +llm_query）。
- **门控**：llm_query 动态白名单（`run_orchestration` 读会话 `research_mode.ptc_llm_query`，
  默认 False→软失败"当前会话未开启 llm_query"，编排不中断）；env restore 门控见 §3。
  **默认全关 = 现状行为不变**；审批语义不变（tool_orchestrate 整段一次审批）。

## 6. PTC llm_query（决策闭环）

- 白名单单工具 `llm_query(prompt, system_hint=None)`；handler
  （`ptc_llm_handler.py`）复用 `infrastructure/ai_provider/`，模型取会话 `model_id`
  （回退链：该配置 is_active → is_default → 软失败）。
- **system 锚定**：强制注入宿主前缀（角色限定 + 禁止索取/复述宿主上下文、密钥、其他会话
  数据），`system_hint` 仅追加不可覆盖；返回截断与 PTC 既有 4000 字符约定一致。
- **审计同窗**：每次调用恰一行 audit_logs（`resource_type='ptc_llm_query'`，关联
  orchestration_id，prompt sha256 不落原文，模型/token/耗时）；计入 50 次子调用上限；
  异常软失败 RuntimeError 回子进程不崩溃编排。契约形态借鉴 OpenAI4S host.llm
  （同步 RPC/软失败/单帧事务，零移植）。

## 7. 平台债修补

- **chat warm pool 硬化**（`infrastructure/sandbox/pool.py`）对齐 Studio 基线：cap_drop
  ALL、no-new-privileges、seccomp（daemon 内置）、read-only rootfs + /tmp tmpfs 512m、
  非 root 10001:10001、pids 512、mem 4g、网络 none。交付/输入目录用 per-container 宿主机
  目录 bind（容器内路径协议不变）——本机 Docker daemon 对 tmpfs 路径 `get_archive` 取不到
  内容（copy-out 依赖 docker cp），bind 是验证可行的唯一可写挂载；`chat_sandbox_tools.py`
  reset 命令 `&&`→`;` 容忍挂载点（R7 每次执行前重置交付目录语义不变）。孤儿容器收养前
  安全基线校验，不符合销毁重建；销毁时容器内清空 bind 内容再回收宿主机目录。
- **LangGraph 审批闸**（ADR `docs/adr/0002-langgraph-chat-sandbox-approval-gate.md`）：
  `chat/runtimes/langgraph_runtime.py` 的 `chat_sandbox_execute` 在 supervised 下走真实
  审批（Redis TTL 300s + approval_request/resolved 事件 + 15s heartbeat + edited/always/
  timeout 分支），语义逐点对齐 legacy（`studio_approval_service.py` 同一套服务）；audit_logs
  留痕。R13（langgraph 缺增量 tool_output）按纪律**只记录不改**。
- **chat 沙盒产物对账**：`execute_chat_sandbox` 支持模型声明 `artifacts` glob，实测 sha256
  落信封 + file_records（见 §2）。

## 8. 安全与分享

- **R1 截断显式化**：落库信封截断时写 `result_truncation`/`ui_payload_truncation`
  （payload_truncated/original_bytes/truncation_note），替换载荷 `{"_cygnusx_payload_truncated":
  true}` 不变；前端代码卡（Studio/Chat 两条路径）显示"内容已截断，完整结果见产物/归档"；
  旧数据无标记不显示不报错。
- **R12 严格定向**：前端 `onToolOutput` 删除"最后一个同名 running 工具"fallback，无
  tool_call_id 丢弃 + console.warn，防并发同名片串卡。
- **分享快照 R4**（`studio_sharing.py`）：分享消息补 `metadata_json`（tool_invocations/
  timeline/usage 白名单键，200KB 护栏二次截断且带 `timeline_truncation` 标记，非白名单键
  不外泄）；产物清单补 sha256（file_records.checksum 按 (original_name, size) 匹配）；
  `render_printable_report` 含工具卡摘要（代码 + 结果摘要行 + sha256 短摘要）。

## 9. 新增配置/表/任务速查

| 类别 | 条目 |
|---|---|
| 配置 | `studio.retention.active_days/dormant_days`、`studio.quota.workspace_gb/archive_gb`、`studio.archive.backend/retention_days`、`sandbox.*` 6 项安全基线（core/config.py） |
| 迁移（单 head `h5i6j7k8l9m0`） | `e2e0wp1a1b2c` workspace_archives+projects.status；`f3a4b5c6d7e8` chat_message_events；`g4b5c6d7e8f9a` tasks.idempotency_key；`h5i6j7k8l9m0` projects.settings |
| beat 任务 | `hibernate_dormant_workspaces` 04:30、`cleanup_expired_workspace_archives` 05:30、`studio-long-task-reconcile` 600s |
| API | `POST /studio/sessions/{id}/restore`、`GET /chat/sessions/{id}/notebook`、`PUT /chat/sessions/{id}/research-mode`、`PATCH /projects/{id}`（status/settings）、`/admin/workspace-archive/*` |

## 10. 已知限制与观察项

1. env restore 在生产只读 rootfs 基线上走降级链路（§3），需平台级 tmpfs overlay 方案。
2. `projects` 表"进行中"语义目前 = project_id 非空（表无历史 status 枚举，WP0 时已回报）。
3. 观察项（本期不施工）：RemoteSnakemakeExecutor 无调用方待立项；MAS 6h 全局上限与 24h
   子任务设计冲突待评估调度方案；SSRF-hardened 分享导入待有需求再做。
4. 存量测试失败 72 项（`test_studio_approval`/`test_studio_platform_tools` 等）经 HEAD
   worktree 对照为本次施工前已存在，与 WP0–WP4 无关。
