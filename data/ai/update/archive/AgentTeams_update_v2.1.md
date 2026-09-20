# AgentTeams 优化框架 v2.2（MinIO 共享存储 + v2.1 收尾 + 并行/通用化增强，已归档）

> 文档性质：施工规格，供 Codex 直接施工。  
> 编写日期：2026-08-11。  
> 上游文档：v1（`data/ai/AgentTeams_update.md`，编排骨架基线）、v2/v2.1（`data/ai/update/AgentTeams_update_v2.md`，实效与通用化专项）。  
> 本文与 v2.1 的关系：v2.1 的施工代码已 ~85% 落地（2026-08-11 审计），本文 = **v2.1 遗留收尾 + MinIO agent 间沟通基础设施 + 并行/通用化增强**。冲突时以本文为准；未覆盖细节回查 v1/v2.1。  
> 顺序：P0（MinIO）→ P1（v2.1 收尾）→ P2（并行增强）→ P3（通用化收尾）。

---

## 0. 2026-08-11 审计结论（施工前必读）

### 0.1 v2.1 已完成（不要重做）

| 项 | 关键文件 |
|---|---|
| 看门狗双层（Bridge 900s / CygnusX 600s） | `integrations/agentteams/bridge/cygnusx_agentteams_bridge/service.py:257-272`；`src/cygnusx/infrastructure/celery_app/tasks/agentteams.py:188-210` |
| 5 个会诊只读工具 | `tool_configs/tools_schema.yaml:127-220`；`src/cygnusx/application/services/agentteams_data_tool_service.py` |
| 硬规则门 | `src/cygnusx/application/services/agentteams_quality_gate_service.py` |
| retry 幂等升版 | bridge `service.py:1551-1650`；`app.py:271-280` |
| 通用化 Registry（三处硬编码已消除） | `src/cygnusx/application/services/agentteams_capability_registry.py` |
| SSE 重连/审批卡/拒绝理由/roleIdentity/遥测服务 | `frontend/src/stores/agentHub.ts:676-735`；`AgentTeamsCaseCard.vue`；`frontend/src/utils/roleIdentity.ts`；`agentteams_consultation_telemetry_service.py` |
| remediation 闭环、plan diff/replay | bridge `service.py:1337-1434,1932-1967` |

### 0.2 运行时链路现状（MinIO 改造要嵌入的点）

```
Case 创建 → Bridge 规划/分配 work item
  → worker 进程轮询 claim（analysis/quality/delivery/production 各自独立）
  → workspace_execution 实际在【主站侧】执行：
      Bridge → Gateway consult → agent_consultation_service.run_consultation
      → ParallelSubAgentService.run(workspace_access=True)
      → studio builtin 工具（sandbox_execute/workspace_*）在 Docker 沙箱跑 Python/R/Bash
      → 工作目录 /data/cygnusx/output/agentteams/{case_id}/{work_item_id}/
      → _register_workspace_artifacts 复制到用户 workspace/agentteams/{case_id}/{work_item_id}/
        并写 file_records 表（source="agentteams"）
  → 下游 agent 经 evidence_refs（路径字符串）+ workspace_file_preview（20KB 上限）读取
```

**核心痛点**：agent 间传数据只有"路径字符串引用 + 20KB 预览"，无 case 级共享存储、无大文件传递、worker 容器未挂数据卷（跨机部署不可行）。

### 0.3 已起草未提交的改动（Codex 先审查再决定采纳）

2026-08-11 已在工作区起草（**未提交、容器未启动**）：

1. `deploy/docker/docker-compose.yml`：新增 `minio` + `minio-init` 两个服务（完整 YAML 见本文 §1.1，与工作区一致）。
2. `.env.example` / `.env`：新增 `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` / `MINIO_AGENTTEAMS_BUCKET` / `CYGNUSX_MINIO_BIND_HOST` / `CYGNUSX_MINIO_PORT` / `CYGNUSX_MINIO_CONSOLE_PORT`（.env 中密码已生成随机值）。

Codex 施工时先 `git diff deploy/docker/docker-compose.yml .env.example` 审查，可调整但不要与 §1.1 的契约（网络/端口/bucket 名）冲突。

---

## 1. P0 — MinIO 对象存储接入（agent 间沟通基础设施）

> 目标：把 agent 间数据流转从"约定式路径字符串 + 20KB 预览"升级为"显式对象存储协议"。Case 级共享前缀 `agentteams-evidence/{case_id}/`，上游写、下游读，支持大文件与跨机部署。

### 1.1 P0-1 compose 接入 MinIO

**施工**：`deploy/docker/docker-compose.yml` 在 cache 服务后新增（已起草，核对后定稿）：

```yaml
  # ===== MinIO 对象存储（AgentTeams agent 间共享产物 / case 级数据区） =====
  # web 经 data_net 访问；cygnusx_net 供跨栈（agentteams bridge/worker）经服务名 minio 直连
  minio:
    image: minio/minio:latest
    container_name: cygnusx-minio
    restart: unless-stopped
    logging: *default-logging
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:?missing MINIO_ROOT_USER in .env}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:?missing MINIO_ROOT_PASSWORD in .env}
    ports:
      - "${CYGNUSX_MINIO_BIND_HOST:-127.0.0.1}:${CYGNUSX_MINIO_PORT:-9000}:9000"
      - "${CYGNUSX_MINIO_BIND_HOST:-127.0.0.1}:${CYGNUSX_MINIO_CONSOLE_PORT:-9001}:9001"
    volumes:
      - ${CYGNUSX_DATA_ROOT:-/data/cygnusx}/cygnusx_data/_minio:/data
    networks:
      - data_net
      - cygnusx_net
    healthcheck:
      test: ["CMD-SHELL", "mc alias set local http://127.0.0.1:9000 $$MINIO_ROOT_USER $$MINIO_ROOT_PASSWORD >/dev/null 2>&1 && mc ready local"]
      interval: 10s
      timeout: 5s
      retries: 6

  minio-init:
    image: minio/mc:latest
    container_name: cygnusx-minio-init
    logging: *default-logging
    entrypoint: ["/bin/sh", "-c"]
    command:
      - >
        mc alias set cygnusx http://minio:9000 "$${MINIO_ROOT_USER}" "$${MINIO_ROOT_PASSWORD}"
        && mc mb --ignore-existing "cygnusx/$${MINIO_AGENTTEAMS_BUCKET}"
        && mc anonymous set none "cygnusx/$${MINIO_AGENTTEAMS_BUCKET}"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
      MINIO_AGENTTEAMS_BUCKET: ${MINIO_AGENTTEAMS_BUCKET:-agentteams-evidence}
    depends_on:
      minio:
        condition: service_healthy
    networks:
      - data_net
    restart: "no"
```

**设计要点**（不要擅自改动）：
- 端口绑 `127.0.0.1`（与 redis/postgres 同款安全姿势）；容器间走 `data_net`/`cygnusx_net` 服务名直连，不经宿主端口。
- 数据 bind mount 到 `${CYGNUSX_DATA_ROOT}/cygnusx_data/_minio`（与 `_redis` 同款迁移姿势）。
- `cygnusx_net` 是 external 跨栈网络，agentteams 栈的 bridge 加入后即可 `http://minio:9000` 访问。
- bucket 默认私有（`anonymous set none`）。

**同时修改** `deploy/agentteams/docker-compose.agentteams.yml`：
- `cygnusx-agentteams-bridge` 服务的 `networks` 列表追加外部网络 `cygnusx_net`（引用已存在的 external 网络，不新建）。
- bridge 环境变量新增（值从 `deploy/agenttests/bridge.env.example` 同步）：
  ```
  AGENTTEAMS_MINIO_ENDPOINT=http://minio:9000
  AGENTTEAMS_MINIO_BUCKET=${MINIO_AGENTTEAMS_BUCKET:-agentteams-evidence}
  AGENTTEAMS_MINIO_ACCESS_KEY=${MINIO_ROOT_USER}
  AGENTTEAMS_MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD}
  ```

**验证**：
```bash
cd deploy/docker && docker compose --env-file ../../.env -p docker up -d minio minio-init
docker exec cygnusx-minio mc ready local   # 注意：compose 姿势固定 -p docker，根 .env 的 COMPOSE_PROJECT_NAME 会顶掉默认项目名
docker run --rm --network cygnusx_net minio/mc alias set t http://minio:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD && ... ls t/agentteams-evidence
```

### 1.2 P0-2 主站 S3 客户端封装

**施工**：新增 `src/cygnusx/infrastructure/storage/minio_store.py`：

- 依赖：`minio` Python SDK（加入 `pyproject.toml`/`requirements`，重建 web 镜像或在 Dockerfile runtime 安装——注意 web 镜像无热重载，装依赖必须重建镜像）。
- 配置读 `Settings`（`src/cygnusx/core/config.py` 新增，**裸名无前缀**，参照 SKILLS_DIR 先例）：
  ```python
  minio_endpoint: str = "http://minio:9000"
  minio_access_key: str = ""
  minio_secret_key: str = ""
  minio_agentteams_bucket: str = "agentteams-evidence"
  minio_presign_expire_seconds: int = 3600
  ```
- 类 `MinioStore` 提供：
  - `put_case_object(case_id, key, local_path, content_type=None) -> str`：上传到 `{bucket}/{case_id}/{key}`，返回 `s3://{bucket}/{case_id}/{key}`。
  - `presigned_get(case_id, key, expires=None) -> str`：生成预签名 GET URL。
  - `fetch_case_object(case_id, key, dest_path) -> Path`：下载到本地。
  - `list_case_objects(case_id, prefix="") -> list[ObjectMeta]`。
  - `delete_case_prefix(case_id)`：生命周期清理用。
- **key 约束**：`{case_id}/{work_item_id}/{relative_path}`；case_id/work_item_id 校验 `^[a-zA-Z0-9_-]+$` 防穿越；relative_path 拒绝 `..`。
- 连接失败降级：构造时 ping 失败只 warn，不阻断主站启动（MinIO 是增强设施，不能拖垮 chat 主链路）；所有方法抛 `BusinessError("对象存储不可用")` 由调用方兜底。

**验证**：容器内 python REPL 上传/下载/预签名闭环；`docker restart cygnusx-web` 后工具可发现。

### 1.3 P0-3 产物上传改造（上游写）

**施工**：`src/cygnusx/application/services/agent_consultation_service.py` 的 `_register_workspace_artifacts`（当前 154-307 行）：

1. 保持现有本地登记逻辑不变（file_records 表是 `/files` 可见性的权威来源，**不能删**——参照"下载产物需登记才可见"教训）。
2. 每个产物本地登记后，追加 `MinioStore.put_case_object(case_id, f"{work_item_id}/{relpath}", local_path)`。
3. 返回的 artifact 字典增加字段：`s3_uri`、`size_bytes`、`sha256`（流式计算，大文件不全量读内存）。
4. 上传失败：warn + 审计 `artifact.s3_upload_failed`，**不阻断 Case**（降级为本地模式）。

**Bridge 侧**：`integrations/agentteams/bridge/cygnusx_agentteams_bridge/service.py:621-631` 的 `_workspace_artifact_refs`：ContextRef 的 `location` 填 s3_uri（本地路径放 `meta["local_path"]` 兜底）。

**验证**：跑一个 treeplot Case → MinIO 控制台可见 `{case_id}/{work_item_id}/tree.pdf`；`/files` 仍正常显示。

### 1.4 P0-4 下游读取工具（解除 20KB 限制）

**施工**：`tool_configs/tools_schema.yaml` 新增只读工具 + `src/cygnusx/application/services/agentteams_data_tool_service.py` 实现：

```yaml
- name: artifact_fetch
  readOnlyHint: true
  description: 拉取 Case 内上游产物到当前工作目录（大文件走 MinIO，解除 preview 20KB 上限）
  parameters:
    case_id: string, required
    artifact_ref: string, required   # s3://bucket/case_id/work_item_id/path 或 evidence_refs 中的 location
    dest_name: string, optional      # 落盘文件名，默认取 key 末段
```

实现要点：
1. 解析 `artifact_ref`：s3:// 开头走 MinIO 下载；否则回退现有 workspace_file_preview 逻辑。
2. **权限校验**：解析出 case_id 后，校验该 case 的 `requester_ref == context.user_id`（沿用 `_require_context_user` 模式，`agentteams_data_tool_service.py:114-118`），跨 case 访问拒绝。
3. 落盘到当前会话工作目录（`workspace_access=True` 时的 case 工作目录），返回 `{local_path, size_bytes, sha256}`。
4. 大小上限走配置 `agentteams_artifact_fetch_max_mb`（默认 512MB），超限拒绝并提示。
5. `workspace_file_preview` 保留用于小文件快速预览，不动。

**注册**：加入 `data/ai/tools/agentteams_case.yaml` 的 `builtin_tools`，使所有挂 agentteams_case tool_pack 的 agent 可用。改 builtin 预设后 **`docker restart cygnusx-web`**。

**验证**：上游产出 5MB CSV → 下游 agent 调 artifact_fetch 拿到完整文件并正确处理。

### 1.5 P0-5 evidence_refs 协议扩展

**施工**：
1. Bridge `models.py` 的 `ContextRef.kind` 枚举增加 `"s3"`（检查 `integrations/agentteams/gateway/cygnusx_agent_gateway/models.py` 同步）。
2. `agent_consultation_service.py` 的 envelope schema 文档/prompt 更新：`evidence_refs` 允许 `s3://bucket/...` 形式；prompt 增加"引用大文件产物时使用 artifact_fetch 拉取全文，workspace_file_preview 仅用于小文件预览"。
3. 遥测 `agentteams_consultation_telemetry_service.py`：evidence 命中率统计把 s3:// 引用计入 `evidence_verified`（经 artifact_fetch 成功即算 verified）。

**验证**：envelope 含 s3:// 引用不触发解析失败；命中率统计正确。

### 1.6 P0-6 权限隔离与审计

**施工**：
1. **不开放 bucket 级匿名访问**（minio-init 已 `anonymous set none`）。
2. 主站持有 root 凭证做单点鉴权：所有 agent 访问都经 `artifact_fetch` 工具（服务端校验 case 归属），**不给 agent 预签名 URL 直接出网**（避免 URL 外泄绕过审计）。预签名 URL 仅用于将来前端直传/下载场景，本期不开放。
3. 审计事件（写 Bridge 审计流，参照 `quality.hard_gate` 格式）：
   - `artifact.s3_uploaded`：`{case_id, work_item_id, key, size_bytes, sha256}`
   - `artifact.s3_fetched`：`{case_id, fetcher_agent, key, size_bytes}`
   - `artifact.s3_upload_failed` / `artifact.s3_fetch_denied`

**验证**：A 用户的 case 产物，B 用户会话调 artifact_fetch 被拒且有 `s3_fetch_denied` 审计。

### 1.7 P0-7 生命周期管理

**施工**：
1. Bridge `close_case`（`service.py:2030-2057`）：Case 关闭时不动 MinIO（交付期还要下载）。
2. 新增 Celery beat `gc_agentteams_case_artifacts`（日级）：扫描 closed 超过 `agentteams_case_artifact_retention_days`（默认 30 天）的 case，删 MinIO 中 `{case_id}/` 下**非交付**前缀（交付产物 key 约定 `{case_id}/delivery/*` 保留），写审计 `artifact.s3_gc`。
3. 本地 `/data/cygnusx/output/agentteams/{case_id}/` 执行工作目录同期清理（file_records 已复制走的不影响）。

**验证**：构造 closed 31 天的 case → beat 运行后中间产物已删、delivery/ 保留、审计有记录。

---

## 2. P1 — v2.1 遗留收尾

### 2.1 P1-1 一键建 Case：零 LLM 路径补全（v2.1 P1-1 未竟）

**现状**：`POST /api/v1/agent-teams/cases` 端点存在（`src/cygnusx/api/v1/agentteams.py:238-265`），但前端建单仍经 LLM 工具调用（`create_agentteams_case`，`tools_schema.yaml:97` `requires_confirm: true`），不是"信息足够时直接弹确认卡"的零 LLM 路径。会诊卡"基于此创建协作 Case"按钮 UI 缺失（API 已支持 `origin_consultation_id`，`frontend/src/api/agentTeams.ts:18,59,81`）。

**施工**：
1. 后端新增"建单意图识别"轻量分支：chat_service 在建单类请求且参数齐全（flow_id + inputs 或自由文本 objective 明确）时，直接构造 `proposed_submission` 返回确认卡 SSE 事件，**跳过 planner LLM**。参数不全时回退现有 LLM 路径。
2. 前端 `KimiChatInput.vue` "..."菜单改结构化建单弹窗（flow 下拉来自 `/api/v1/agent-teams/capabilities` 的 allowed_flow_ids，inputs 表单按 flow YAML 的 artifacts/inputs 渲染），提交直调 `agentTeamsApi.createCase`。
3. 会诊卡组件（`AgentTeamsConsultationCard` 或同级，自查 frontend/src/components/ai-chat/）加"基于此创建协作 Case"按钮：携带 `origin_consultation_id` + 会诊结论摘要直调 createCase。

**验证**：点击到 `received` ≤ 1 次确认 + 1 次 API 调用；无二次 LLM 往返（后端日志无 planner 调用记录）。

### 2.2 P1-2 产物区 UI（v2.1 P1-5 未竟）

**现状**：artifacts 只经 overdrive_progress 事件和 manifest JSON 展示，无独立产物区组件；omic_task_ids 跳转已有（`AgentTeamsCaseView.vue:513-514`）。

**施工**：
1. `AgentTeamsCaseView.vue` 新增"交付产物"卡片：数据源 = case detail 的 delivery manifest + file_records（source="agentteams"）列表接口；每行：文件名、大小、sha256 短码、下载按钮（复用超频产物区的下载逻辑）、JSON 折叠预览 manifest。
2. `AgentTeamsCaseCard.vue`（聊天内卡片）在 closed 态追加产物区缩略（最近 3 个产物 + "查看全部"跳详情页）。
3. 下载走现有 `/files/{id}/download` 链路（file_records 已登记，不要新造下载端点）。

**验证**：Case 关闭后聊天卡片 1 次点击下载交付文件。

### 2.3 P1-3 会诊遥测管理面板（v2.1 P1-7 未竟）

**现状**：`agentteams_consultation_telemetry_service.py` 已记录 parse_success_rate / evidence_hit_rate / qc_consistency_rate / average_tool_calls 到 Redis（按天聚合），`summary` 方法存在，但无 API 端点、无管理端 UI。

**施工**：
1. 后端：`src/cygnusx/api/v1/admin/` 下新增 `GET /admin/agentteams/consultation-telemetry?days=7`，AdminRequired（仅角色，非 TOTP——参照平台配置条件 TOTP 先例，只读指标免 TOTP）。
2. 前端 `AgentTeamsBridgeTab.vue`（或同级管理页）加指标卡：4 个指标近 7 天趋势（简单折线/数值卡即可，不引新图表库，复用现有 viz 组件）。

**验证**：跑若干会诊后管理页可见命中率数字且随新会诊变化。

### 2.4 P1-4 execution_mode 设置时机对齐（v2.1 P0-4 偏差）

**现状**：文档要求"规划阶段对 agent-code/agent-viz 工单设 workspace_execution"，实际在审批通过后 `execute_general_plan`（bridge `service.py:1296-1335`）才设置。功能等价但与文档不符，且审批卡上用户看不到执行模式。

**施工**：`_accept_plan_result` 通用计划分支冻结 plan 时，把每个 work_item 的 `execution_mode` 一并冻结进 `proposed_submission.parameters.work_items`（planner prompt 已产出该字段则校验、缺省补 `workspace_execution`），审批卡参数明细可见；`execute_general_plan` 改为读取冻结值而非运行时硬赋。

**验证**：审批卡参数明细中每个 work_item 可见 execution_mode 字段；plan_hash 随 execution_mode 变化而变化。

---

## 3. P2 — 多 Agent 并行增强

### 3.1 P2-1 同 target 工单并发认领

**现状**：一个 worker 进程一次 claim 一个 work item，同 target（如两个 agent-code 任务）串行。Case 内无依赖的同 target 工单只能排队。

**施工**：
1. `worker_runner.py` / `production_runner.py` 主循环改为：单轮 claim 最多 `AGENTTEAMS_WORKER_MAX_CONCURRENT`（默认 2）个工单，asyncio.gather 并发执行，各自 complete。
2. Bridge `claim_work_item`（`case_store.py:488-500`）已原子（409 冲突），确认批量 claim 接口或循环单 claim 均可；优先循环单 claim（不改契约）。
3. compose 层面同 identity 多副本是错误姿势（身份 token 竞争），**不做**；并发度只在单进程内开。

**验证**：通用计划含 2 个无依赖 agent-code 工单 → 墙钟时间 ≈ max(两者) 而非 sum。

### 3.2 P2-2 Case 内 fan-out（同角色 N 路并行）

**现状**：对话内有 `parallel_subagents` fan-out（`parallel_subagent_service.py:239-267`），Case 模式没有等价物。

**施工**：planner 通用计划契约扩展：`work_items[]` 允许 `fan_out: {count: N, merge_strategy: "collect"}` 字段——Bridge 冻结时展开为 N 个同 target 工单（objective 带 shard 序号 `{i}/{N}`），并自动生成一个 merge 工单（depends_on = 全部 shard）汇总 output_refs。merge 工单 target 同 shard target，objective 要求调 artifact_fetch 拉取全部 shard 产物后合并。

**验证**："把 4 个 CSV 分别清洗再合并"的 Case → 4 个 shard 并行 + 1 个 merge，产物正确合并。

---

## 4. P3 — 定制分析通用化收尾

### 4.1 P3-1 通用计划 target 白名单动态化

**现状**：`_validate_general_plan`（bridge `service.py:868-889`）硬编码 target 只允许 `agent-code`/`agent-viz`。

**施工**：改从 capability snapshot 读取 `workspace_capable_targets`（CygnusX 侧 `AgentTeamsCapabilityRegistry` 新增方法：凡 agent YAML 的 `capability_scope` 含 workspace 类能力或 tool_packs 含 `workspace` 的 active agent 即入选）。Bridge 启动拉取 + 定时刷新（沿用 capabilities 拉取链路）。

**验证**：给一个测试 agent YAML 加 workspace tool_pack + internal_case_role → 不重启 Bridge（等刷新周期）即成为合法 target。

### 4.2 P3-2 BRIDGE_ALLOWED_FLOW_IDS 热更新

**现状**：新增 flow 需手动改 Bridge 环境变量 `BRIDGE_ALLOWED_FLOW_IDS`（`bridge/config.py:34` 默认 `rna_seq,scrna_seq`）并重启。

**施工**：Bridge 定时（60s）从 CygnusX `/capabilities` 拉 allowed_flow_ids，与 env 白名单取并集（env 为空则全信 Registry）；新增 flow YAML 后最晚 60s 可建单，无需重启。

**验证**：新增 `data/ai/flows/test_general.yaml` → 60s 内 Case 创建成功，Bridge 无重启。

---

## 5. 验收标准

### 5.1 MinIO 闭环
⬜ `docker compose --env-file ../../.env -p docker up -d minio minio-init` 一次拉起，bucket 私有。  
⬜ treeplot Case 产物在 MinIO `{case_id}/{work_item_id}/` 可见，且 `/files` 可见性不回归。  
⬜ 5MB 文件经 artifact_fetch 完整传递（sha256 一致）；跨 case 访问被拒 + 审计。  
⬜ closed 超期 case 中间产物被 GC，delivery/ 保留。

### 5.2 v2.1 收尾
⬜ 建单 ≤1 次确认 + 无二次 LLM；会诊卡一键建单可用。  
⬜ 聊天卡片/详情页产物区 1 次点击下载。  
⬜ 管理面板可见 4 项遥测指标。

### 5.3 并行增强
⬜ 同 target 2 工单并发（墙钟 ≈ max）。  
⬜ fan_out 4 路清洗 + merge Case 端到端通过。

### 5.4 通用化收尾
⬜ 新 workspace agent 免重启成为合法 target。  
⬜ 新 flow 免重启可建单。

### 5.5 不回归（每次施工后必跑）
⬜ Bridge/Gateway/Worker 契约测试 + CygnusX 单测回归。  
⬜ RNA-seq 正式 Case 流程不受影响。

---

## 6. 施工纪律（沿用 v2.1 §7，并补充本项目坑位）

- 顺序严格 P0 → P1 → P2 → P3；每完成一项跑回归 + 重启对应容器。
- **compose 姿势**：主栈必须 `cd deploy/docker && docker compose --env-file ../../.env -p docker up -d`（根 .env 的 COMPOSE_PROJECT_NAME=cygnusx 会顶掉项目名 docker）。
- **改后端代码 → `docker restart cygnusx-web`**（uvicorn --workers 2 无 reload）；改 Celery task → `docker restart cygnusx-worker`；builtin 工具/预设变更 → restart cygnusx-web。
- **装 Python 依赖 → 重建 web 镜像**（restart 不够）。
- file_records 是 `/files` 可见性的权威来源，任何产物链路改造不得绕过登记。
- 业务智能只写 CygnusX 侧；Bridge/Gateway/Worker 只做编排、搬运与审计。
- ORM 属性名禁用 `metadata`（保留列名改 `meta`）；服务端 onupdate 字段 flush 后须 `db.refresh` 再序列化。

---

## 7. 附录：关键契约

### 7.1 MinIO 对象命名

```
bucket: agentteams-evidence
key:    {case_id}/{work_item_id}/{relative_path}     # 中间产物
key:    {case_id}/delivery/{relative_path}           # 交付产物（GC 保留）
约束:   case_id/work_item_id ∈ ^[a-zA-Z0-9_-]+$；relative_path 拒绝 ".."
```

### 7.2 artifact 字典新增字段（_register_workspace_artifacts 返回）

```json
{
  "name": "tree.pdf",
  "local_path": "workspace/agentteams/{case_id}/{work_item_id}/tree.pdf",
  "s3_uri": "s3://agentteams-evidence/{case_id}/{work_item_id}/tree.pdf",
  "size_bytes": 183420,
  "sha256": "9f2c...",
  "file_record_id": 1234
}
```

### 7.3 evidence_refs 扩展

```json
{"kind": "s3", "id": "{case_id}/{work_item_id}/tree.pdf", "location": "s3://agentteams-evidence/{case_id}/{work_item_id}/tree.pdf"}
```

### 7.4 审计事件

```json
{"event_type": "artifact.s3_fetched", "case_id": "...", "fetcher_agent": "agent-viz", "key": ".../tree.pdf", "size_bytes": 183420}
{"event_type": "artifact.s3_fetch_denied", "case_id": "...", "fetcher_user_id": "...", "reason": "case_belongs_to_other_user"}
{"event_type": "artifact.s3_gc", "case_id": "...", "deleted_keys": 12, "retained_prefix": "delivery/"}
```

### 7.5 新增配置项汇总

| 位置 | 配置 | 默认 |
|---|---|---|
| .env | MINIO_ROOT_USER / MINIO_ROOT_PASSWORD / MINIO_AGENTTEAMS_BUCKET | - / - / agentteams-evidence |
| .env | CYGNUSX_MINIO_BIND_HOST / PORT / CONSOLE_PORT | 127.0.0.1 / 9000 / 9001 |
| Settings（裸名） | MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY / MINIO_AGENTTEAMS_BUCKET / MINIO_PRESIGN_EXPIRE_SECONDS | http://minio:9000 / ... |
| Settings | AGENTTEAMS_ARTIFACT_FETCH_MAX_MB | 512 |
| Settings | AGENTTEAMS_CASE_ARTIFACT_RETENTION_DAYS | 30 |
| bridge env | AGENTTEAMS_MINIO_ENDPOINT / BUCKET / ACCESS_KEY / SECRET_KEY | http://minio:9000 / ... |
| worker env | AGENTTEAMS_WORKER_MAX_CONCURRENT | 2 |
