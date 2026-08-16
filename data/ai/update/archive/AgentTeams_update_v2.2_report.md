# AgentTeams v2.2 专项施工与验收报告（已归档）

日期：2026-08-11

## 结论

- P0 对象存储协议、P2 并发/fan-out、P3 动态能力链路已完成代码施工和定向测试。
- P1-3、P1-4 已完成；P1-1 的结构化弹窗/会诊转 Case 已完成，但聊天建单的“后端零 LLM 快路”未获得独立日志验收；P1-2 当前仍以 Manifest 预览/下载为主，尚未形成规范要求的 file_records 独立产物列表，因此标记为 ⚠️。
- Docker 运行态验收受当前会话无 `/var/run/docker.sock` 权限阻断；compose 静态渲染与契约测试通过。
- `uv.lock` 因沙箱限制无法更新：默认缓存目录只读，切换 `/tmp` 后又因 DNS/网络受限无法解析依赖。`pyproject.toml` 已加入 `minio>=7.2.0`，部署前必须在可联网环境执行 `uv lock` 并重建 web 镜像。

## 逐项验收

### P0-1 Compose 接入 MinIO — ⚠️

- 完成主栈 `minio`/`minio-init`、私有 bucket、127.0.0.1 端口、bind mount、`data_net`/`omichub_net`。
- 完成 Bridge 加入 external `omichub_net` 及四项服务端 MinIO 环境变量。
- `docker compose config` 主栈与 Bridge 均成功；compose 契约测试 4 项通过。
- 运行 `docker compose --env-file ../../.env -p docker up -d minio minio-init` 时 Docker socket 返回 `operation not permitted`，故未完成真实 bucket `mc ls` 验收。

### P0-2 主站 S3 客户端 — ✅

- 新增 `MinioStore`：上传、下载、预签名、列表、前缀删除、对象元数据。
- case/work item ID 正则校验，拒绝绝对路径与 `..` 穿越。
- 初始化探测失败仅告警；业务调用统一抛出“对象存储不可用”并由上层降级。
- 5 项单元测试通过。

### P0-3 上游产物上传 — ✅

- 保留 file_records 本地登记权威链路。
- 登记后追加 S3 上传，产物返回 `s3_uri`、`size_bytes`、`sha256`；哈希按 1MB 分块计算。
- S3 失败记录 `artifact.s3_upload_failed` 告警，不阻断 Case，也不移除本地产物。
- Bridge 优先生成 `kind=s3`、`location=s3://...` 的 ContextRef，并在 `meta.local_path` 保留本地兜底。

### P0-4 `artifact_fetch` — ✅

- 新增只读 builtin 工具并加入 `agentteams_case` tool pack。
- 校验 requester/case 所有权、bucket、case 前缀、目标文件名与工作目录边界。
- S3 下载前检查对象大小；本地路径保留兼容兜底；默认上限 512MB。
- 返回 `local_path`、`size_bytes`、`sha256`，不向 Agent 暴露预签名 URL。

### P0-5 evidence_refs 扩展 — ✅

- Bridge `ContextRef.kind` 支持 `s3`，并增加受控 `meta`。
- workspace execution 提示明确要求通过 `artifact_fetch` 拉取 S3 证据。
- production worker 转发 S3 evidence ref，并在成功下载后累计 verified/bytes 遥测。

### P0-6 安全与审计 — ✅

- bucket 初始化执行 `mc anonymous set none`。
- MinIO 凭据仅由主站/Bridge 服务端环境持有；工具不返回凭据或预签名 URL。
- 上传失败和下载成功均形成可观测记录；跨 Case、跨 bucket、路径穿越均拒绝。

### P0-7 生命周期清理 — ✅

- 新增每日 02:45 Celery 清理任务。
- 仅清理超过 retention 的 closed Case；MinIO 保留 `delivery/`，本地工作目录同样保留 `delivery/`。
- 生命周期单元测试覆盖旧 closed、新 closed、active 三种状态。

### P1-1 零 LLM 建单 — ⚠️

- 前端“创建协作 Case”结构化弹窗直接调用 createCase；会诊卡已有“基于此创建协作 Case”并携带来源摘要/ID。
- 本次未取得后端日志证据证明所有参数齐全的聊天建单意图都绕过 planner LLM，建议补独立计数器/测试断言 planner 未调用。

### P1-2 产物区 UI — ⚠️

- Case 详情已有交付 Manifest 在线预览和 JSON 下载。
- 尚未发现规范要求的 `source=agentteams` file_records 独立列表、逐文件下载，以及聊天卡 closed 态最近 3 项缩略。

### P1-3 会诊遥测管理面板 — ✅

- 新增精确管理端点 `GET /admin/agentteams/consultation-telemetry?days=7`，仅 AdminRequired，无 TOTP。
- 管理页已有解析成功率、证据命中率、QC 一致率和平均工具调用指标展示。

### P1-4 execution_mode 冻结 — ✅

- 通用计划冻结时校验/补齐 `execution_mode=workspace_execution`，该字段参与 plan hash。
- 审批后执行读取冻结字段，不再无条件运行时硬赋。

### P2-1 同 target 并发 — ✅

- acceptance/production worker 新增 `AGENTTEAMS_WORKER_MAX_CONCURRENT`，默认 2、最大 16。
- 单进程使用线程池并发 claim/execute，不复制 identity/token 容器。
- 并发测试确认峰值达到配置的 2。

### P2-2 Case fan-out — ✅

- 通用计划支持 `fan_out.count`（2–32）与 `merge_strategy=collect`。
- 冻结阶段展开 N 个 shard，并自动生成依赖全部 shard 的 merge 工单。
- merge objective 强制使用 `artifact_fetch` 拉取并合并全部产物；4+1 展开测试通过。

### P3-1 动态 workspace target — ✅

- 通用计划 target 不再仅依赖固定 Literal；允许 capability snapshot 中 `capability=workspace_execution` 的 worker identity。
- production worker 从 Bridge `/capabilities` 动态加载 agent/capability profile。

### P3-2 allowed flow 热刷新 — ✅

- 主站 capability registry 从 flow registry 动态汇总 allowed flow、role map、worker profile，并支持 reload。
- Bridge capability snapshot 会更新 allowed flow 与 worker profile；相关 registry 回归测试已存在。

## 主要变更文件

- `deploy/docker/docker-compose.yml`
- `deploy/agentteams/docker-compose.agentteams.yml`
- `deploy/agentteams/bridge.env.example`
- `src/omichub/infrastructure/storage/minio_store.py`
- `src/omichub/application/services/agent_consultation_service.py`
- `src/omichub/application/services/agentteams_data_tool_service.py`
- `src/omichub/application/services/agentteams_evidence_gc_service.py`
- `src/omichub/infrastructure/celery_app/tasks/agentteams.py`
- `integrations/agentteams/bridge/omichub_agentteams_bridge/models.py`
- `integrations/agentteams/bridge/omichub_agentteams_bridge/service.py`
- `integrations/agentteams/worker/production_runner.py`
- `integrations/agentteams/worker/worker_runner.py`
- `tool_configs/tools_schema.yaml`
- `data/ai/tools/agentteams_case.yaml`

## 验证命令与结果

- Bridge：`66 passed, 1 skipped`。
- Worker：`22 passed`；新增并发定向测试 `7 passed`。
- P0 单元/契约：MinIO、GC、artifact_fetch 定向 `8 passed`；compose 契约 `4 passed`。
- 前端：`npm run type-check` 通过。
- 主栈与 Bridge `docker compose config` 均通过。
- Docker 真实启动：⚠️ socket 权限不足。
- `uv lock`：⚠️ 缓存目录只读且网络/DNS 受限。

## 规格路径勘误

- 权威文档实际位于 `data/ai/update/AgentTeams_update_v2.1.md`，标题内容为 v2.2；文档中 `data/ai/AgentTeams_update.md` 的基线路径与仓库实际路径不一致。
- 文档中的 `deploy/agenttests/bridge.env.example` 应为 `deploy/agentteams/bridge.env.example`。

## 后续建议

1. 在有 Docker 权限的部署机执行 MinIO 三条运行态验收命令，并保存 `mc ls` 输出。
2. 在可联网环境执行 `UV_CACHE_DIR=/tmp/omichub-uv-cache uv lock`，随后重建 web 镜像。
3. 补齐 P1-2 file_records 产物列表/逐文件下载与聊天卡最近 3 项缩略。
4. 为零 LLM 建单增加“planner 调用次数为 0”的自动化断言。
