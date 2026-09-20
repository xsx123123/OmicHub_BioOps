# Codex 施工提示词 — AgentTeams v2.2（已归档）

> 用法：把下面「提示词正文」整段粘贴给 Codex。

---

## 提示词正文

你是 CygnusX 仓库（/home/zj/zj_code_libarary/CygnusX）的施工工程师。本次任务：实施 **AgentTeams v2.2 专项**——MinIO agent 间共享存储 + v2.1 遗留收尾 + 并行/通用化增强。

### 第一步：读文档（先读后动，禁止跳读）

1. **施工规格（权威）**：`data/ai/update/AgentTeams_update_v2.1.md` —— 所有施工项、契约、验收标准以此为准。
2. **背景**：`data/ai/update/AgentTeams_update_v2.md` 的 §0（生产实证根因 R1-R6）——理解"为什么做"。
3. **基线原则**：`data/ai/AgentTeams_update.md` —— 状态机/租约/审批/审计原则不得破坏。

规格文档与你的判断冲突时，以规格文档为准；发现规格有错误或遗漏，**先停下来在交付报告里说明，不要擅自改设计**。

### 第二步：核对工作区已起草的改动

2026-08-11 已在工作区起草但未提交、未启动的改动：

- `deploy/docker/docker-compose.yml`：新增 `minio` + `minio-init` 服务
- `.env.example` / `.env`：新增 MINIO_* 配置（.env 密码已生成）

先 `git diff deploy/docker/docker-compose.yml .env.example` 审查，与规格 §1.1 对照；可微调实现细节，但**网络（data_net/cygnusx_net）、端口绑定（127.0.0.1）、bucket 名（agentteams-evidence）、bind mount 路径（_minio）不得改**。

### 施工顺序与范围

严格按规格文档顺序：**P0（MinIO §1.1-1.7）→ P1（v2.1 收尾 §2.1-2.4）→ P2（并行增强 §3.1-3.2）→ P3（通用化收尾 §4.1-4.2）**。

每完成一项：跑该项「验证」步骤 + 相关回归，通过后再做下一项。禁止一次性全做完再统一验证。

### 本项目纪律（违反必返工，逐条遵守）

1. **compose 启动姿势**：主栈必须 `cd deploy/docker && docker compose --env-file ../../.env -p docker up -d <service>`。根 `.env` 的 `COMPOSE_PROJECT_NAME=cygnusx` 会顶掉默认项目名 `docker`，漏了 `-p docker` 会起出一套平行栈。
2. **无热重载**：改后端 Python 代码 → `docker restart cygnusx-web`；改 Celery task → `docker restart cygnusx-worker`；改 builtin 工具/工具预设 → restart cygnusx-web。`docker exec` 看到的是磁盘不是进程内存，改完不重启等于没改。
3. **装 Python 依赖 → 必须重建 web 镜像**（restart 不够）；stdio MCP 命令在容器内执行，PATH 以容器为准。
4. **file_records 是 `/files` 可见性的权威来源**（不扫磁盘）：任何产物链路改造不得绕过 `_register_workspace_artifacts` 的登记逻辑，只能追加不能删除。
5. **业务智能只写 CygnusX 侧**（`src/cygnusx/`）；Bridge/Gateway/Worker（`integrations/agentteams/`）只做编排、搬运与审计。LLM prompt、阈值判断、业务规则禁止进 Bridge。
6. **SQLAlchemy 坑**：ORM 属性名禁用 `metadata`（保留字，改 `meta` 保留列名）；`server_onupdate` 字段 flush 后属性过期，asyncio 下须 `db.refresh()` 再序列化，否则 MissingGreenlet。
7. **降级不阻断**：MinIO 连接失败只 warn 降级为本地模式，绝不能拖垮 chat 主链路或 Case 状态机。
8. **迁移纪律**：如需建表/改表用 alembic，容器内 `/app/.venv/bin/alembic`；若迁移历史多 head 须用 mergepoint 合并。
9. **前端**：改完跑 `vue-tsc -b` + `vite build`；若 vue-tsc 报"找不到名字"幻影错误，删 `frontend/tsconfig*.tsbuildinfo` 再 build。表格注意 fixed 布局列宽陷阱；naive-ui tooltip 的 #trigger slot 根元素禁止带 v-if。
10. **flow_id 规范**：必须下划线（`rna_seq`），禁连字符；前端导航 token 才用连字符。

### 每步验证的最低要求

- P0-1：`minio-init` 退出码 0；`docker exec cygnusx-minio mc ready local` 通过；从 cygnusx_net 网络内能 `mc ls` 到 `agentteams-evidence` bucket 且为私有。
- P0-3/P0-4：跑一个 treeplot 通用 Case 端到端：产物在 MinIO `{case_id}/{work_item_id}/` 可见、`/files` 不回归、下游 artifact_fetch 拉取 sha256 一致、跨 case 访问被拒且有审计。
- P1：前端 vue-tsc + build 通过；建单无二次 LLM（看后端日志）；管理面板指标随会诊变化。
- P2/P3：对应规格的验收用例。
- 每项完成后：Bridge/Gateway/Worker 契约测试（`integrations/agentteams/bridge/tests/`、`gateway/tests/`）+ CygnusX 相关单测回归。

### 禁止事项

- 禁止提交 git commit（只改工作区，由用户审查后自行提交）。
- 禁止删除/重写 v1/v2 文档；规格文档本身如发现错误，在交付报告中提出，不改原文。
- 禁止给 agent 发 MinIO 预签名 URL 直出（统一走 artifact_fetch 服务端鉴权）。
- 禁止做规格之外的"顺手优化"；发现的额外问题记入交付报告「建议后续项」。

### 交付报告格式（最后一轮输出）

按 P0-1…P3-2 逐项给：✅/⚠️/❌ + 改动文件清单 + 验证命令与输出摘要 + 未通过项的原因。结尾给「建议后续项」列表。报告写入 `data/ai/update/AgentTeams_update_v2.2_report.md` 并同步在聊天输出。
