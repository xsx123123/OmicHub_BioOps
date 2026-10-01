# AGENTS.md — OmicHub / CygnusX 工作协议

> 本文件同时适用于 Claude Code（`CLAUDE.md` 以 `@AGENTS.md` 引入）。动代码前**先读** `ARCHITECTURE_DESIN/README.md` 定位对应 as-built 文档——该目录是唯一架构权威库，`docs/` 仅为历史档案，提案/vision 文档不得当作现状依据。

## 0. 协作基线

- 工作语言：提交信息用仓库现行 conventional 风格（`feat(frontend): …` / `fix: …` / `docs: …`），可夹中文术语。
- 提交粒度：一个逻辑变更一个 commit；不提交与本任务无关的脏文件（`git status` 先行检查）。
- 分支模型：主干 `main`，本地领先 origin 常态存在；推送前先 `git log origin/main..HEAD` 自查。
- 子模块（`Protocol/FlowFrame`、`pipelines/*` 共 6 个）：父仓只能记录指针，内部改动须在各自仓库提交；`git status` 里 "modified content" 无法从父仓提交。
- `[待人工确认]` 标记 = 无法从代码 100% 确认的事实，默认按给出的安全推测执行。

## 1. 项目概要与核心定位

CygnusX（仓库名 OmicHub，华中农业大学园艺林学学院）是 AI 驱动的组学/生信分析交付平台：分析管线固化为声明式、版本化流程资产（Flow 家族 + Snakemake 子模块），**AI 只调度、不生成**——Agent 无 shell、无流程 YAML/DB 写权限，仅做需求解析、计划拆解、路由与结果解释。四级用户入口：L1 生信工具箱 / L2 星尘 AI 助手 / L3 AI 工作台 OmicStudio / L4 多 Agent 协作室。

- 后端：Python 3.11（`.python-version` 为 `omichub_3.11`）+ FastAPI + SQLAlchemy(asyncpg) + Alembic + Celery/Redis + LangGraph + litellm + pydantic v2；包管理 **uv**（`uv.lock` 冻结，CI 用 `uv sync --frozen`）。
- 前端：`frontend/`，Vue 3 + TS(strict) + Vite 5 + Pinia + naive-ui；REST 边界 `src/api/*` → axios 统一实例 `baseURL '/api/v1'`（手写，无 OpenAPI 生成）。
- 存储/中间件：PostgreSQL+pgvector（87 表）、Redis、MinIO/S3、RocketMQ、flower；向量检索自研（fastembed + pgvector），**记忆系统无 mem0**（`.env.example` 的 MEM0 残留是配置漂移，勿信）。
- 周边子工程：`mcp-server/`（独立 FastMCP 外部通道）、`integrations/agentteams/{bridge,gateway}/`（各自 pyproject + 独立 CI job）、`scripts/`（cygnusxtools CLI）、`docs/app/`（独立 React 档案站，非主前端）。

## 2. 常用命令与门禁流水线

```bash
uv sync --frozen                       # 后端依赖安装（CI 同款，禁止绕过锁文件）
npm ci                                 # frontend/ 下前端依赖

make dev                               # 后端 dev: uvicorn --reload :8000
make dev-worker / make dev-beat / make dev-flower   # Celery 三件套（flower :5555）
make dev-rocketmq-worker               # RocketMQ worker（需先起 broker）
make test / make test-cov              # pytest（asyncio_mode=auto, --strict-markers）
make lint / make format / make type-check   # ruff check / ruff format+fix / mypy strict
make check-migrations                  # 迁移链静态校验（scripts/check_migrations.py）
make migrate-new m="..." / make migrate / make migrate-merge / make migrate-rollback
make check-alembic-heads               # 检测多 head（>1 告警）
make validate-image-mapping            # 镜像清单 + Studio 运行时契约校验
make docker-dev-refresh                # 容器开发热刷新（秒级 bind mount）；仅依赖变更才 docker-reload

cd frontend && npm run dev / npm test / npm run type-check / npm run build
```

**scripts/ 关键检查脚本**（不在 make 目标里的）：`check_schema_drift.py`（ORM ↔ 实际库对账，容器 entrypoint fail-fast 同款）、`check_custom_agents.py`（上线前只读盘点生产 DB 自建 Agent）、`evaluate_router_20.py`（Router LLM 分类器评估，改路由必跑）、`test_studio_agent_runtime.py`（Agent→Studio 镜像选择契约离线验证）。

**全量门禁（提交前必须全绿，综合 `.github/workflows/ci.yml` 三 job + Makefile）：**

```bash
uv run ruff check src/ tests/ && uv run mypy src/cygnusx/ \
  && uv run python scripts/check_migrations.py \
  && uv run pytest tests/unit tests/e2e -q -m "not quarantine" \
  && (cd integrations/agentteams/bridge && uv run pytest -q) \
  && (cd frontend && npx vitest run && npx vue-tsc --noEmit)
```

**常见盲区（局部全绿仍可能挂 CI / 线上）：**
- CI **不跑 mypy**（strict + pydantic 插件，仅 `make type-check`）也不跑 `tests/integration`（需真实 DB/Redis）——本地必须补跑。
- 前端 `npm test` 过 ≠ `npm run build` 过（build 内含 `vue-tsc -b`）；前端无 eslint/prettier，风格靠 review。
- `-m "not quarantine"` 静默隔离存量失败；改动相关域时翻查 quarantine 是否已有同类用例。
- 改 Agent 提示词/YAML：共享片段（沙盒协议、沟通称呼规范）由 `agent_loader.py` 统一追加，改 `data/ai/prompts/shared/*.md` 而非逐 Agent；且提示词须经**管理端 API 发布**才写入 DB 生效。
- Alembic 并行分支产生多 head：提交前 `make check-migrations`，多人并行改模型 rebase 后必查 `alembic heads`，必要时 `make migrate-merge`。
- 改镜像/Agent 运行时画像：必须跑 `make validate-image-mapping` + `scripts/test_studio_agent_runtime.py`。

## 3. 系统架构与保护边界

**请求主链路**：Vue UI → `/api/v1/chat/stream` (SSE) → `middleware/`（Auth/RBAC/ModuleGate/Cookie/Audit/RateLimit）→ `application/services/`（150+ 用例）→ `AgentContextBuilder` 装配（DB 会话/记忆/知识/计费）→ Chat Runtime（LangGraph 或 Legacy ReAct 受保护轮次）→ 自研 OpenAI-compatible Provider（`infrastructure/ai_provider/`）→ Tool/MCP/Skill 双通道（`llm_payload`/`ui_payload`）→ 事件落库 + SSE 终态。长任务 >600s 走 Celery reconcile-only。

**后端分层**：`api/v1/` 40+ 路由 · `application/` 用例+schemas DTO · `domain/` 限界上下文（ai/flow/mas/team/sandbox/skill/cookie/festival…）· `infrastructure/` 适配器（database/celery_app/cache/sandbox/storage/mcp/skills/web_search/yaml/config）· `core/` 横切（`config.py` Settings 读 `.env`；`data/CygnusX.yaml` 为外置注册中心）· `middleware/` · `tools/` 生信工具注册 + Celery tasks。

**子系统速览**（详情见对应架构文档，勿凭此表改实现）：

| 子系统 | 职责一句话 | 关键代码 |
|---|---|---|
| Chat 执行 | SSE 流式问答，LangGraph/Legacy 双运行时 | `api/v1/chat.py`、`application/services/chat_service.py` |
| Agent 运行时 | 数据驱动装配，4 种闭环形态 | `data/ai/*.yaml`、`infrastructure/config/agent_loader.py` |
| Studio 沙箱 | 一会话一容器，/exec NDJSON | `infrastructure/sandbox/`、`infrastructure/studio/` |
| AgentTeams 协作室 | Room/Case/Manager/Worker | `application/services/agentteams_*`、`integrations/agentteams/` |
| MCP 体系 | 内置 Preset + 外部 Server 双表面 | `infrastructure/mcp/`、`mcp-server/` |
| Flow 家族 | 声明式 catalog + Snakemake 子模块 | `flows/*.yaml`、`pipelines/*`、`Protocol/FlowFrame/` |
| 异步执行 | Celery reconcile-only + RocketMQ | `infrastructure/celery_app/`、`task_queue/` |
| 计费/记忆/知识 | token 计费、pgvector 记忆与检索 | `application/services/` 同名服务、`infrastructure/database/vector` |

**关键资产目录**：`data/ai/`（20 个 Agent YAML + prompts 注册表 + skills 磁盘真相源 + runtime_images/studio 沙箱配置）· `data/MODULE_LOCKED.yaml`（17 模块注册表）· `tool_configs/`（`tools_schema.yaml` LLM 工具 schema + 各工具契约）· `flows/`（声明式流程 catalog）· `deploy/`（compose×7 + runtime-images/studio/sandbox/agentteams Dockerfile + image-mapping）· `mcp-server/` · `pipelines/`（RNAFlow/ATACFlow/scrna/EBIDownload/tools 子模块 + jbrowse2 产物）· `Protocol/`（生效协议）· `evidence/`、`logs/`（运行证据，不入提交）。

**权威文档索引**（改对应域前必读）：总览 `cygnusx_architecture.md` + `platform_architecture_maps.md`（看图入口）；Agent/Chat `agent_execution_framework.md`/`agent_framework_baseline.md`/`agent_architecture.md`；Token 计费 `token_billing_architecture.md`；DB `database_architecture.md`；沙箱 `cygnusx_sandbox_architecture_2026-08-22.md`（唯一规范）；MCP `mcp_architecture.md`；记忆/知识/技能各同名文档；前端 36 章 `frontend.md`；模块设计六原则 `cygnusx_design.md`。

**保护/冻结模块（只许小步渐进修改，禁止盲目重构）：**
- `data/MODULE_LOCKED.yaml` — 模块注册唯一数据源，后端启动硬校验（语法错/key 重复直接拒启），前端路由守卫 + 后端 API 拦截共同消费。
- `deploy/image-mapping.yaml` — 14 镜像清单唯一权威源；tag 变更 6 处同步（清单→config_files→build.sh/Makefile/.env.example/config.py→子镜像重建→`make validate-image-mapping`）；**禁用 `latest`，tag 必带 git SHA 短号**。
- `Protocol/file_protocol.md` v1.3（用户目录协议：`StoragePathFactory.create_project_run_dir()`、禁 UUID 出现在用户可见目录、`ensure_directory_chain()` 登记）；`Protocol/镜像构建国内加速规范_v1.md`（所有 Dockerfile 变更必须遵守）；`Protocol/FlowFrame/`（子模块 = Flow 架构强制规范 v2.0）。
- `mcp-server/` 确认契约：模型永不能自证确认（`_confirmed` 已废弃），确认凭证只能由人类 JWT 端点写入、一次性 + 绑 SHA-256 参数哈希；内外双表面等价由 `tests/unit/test_mcp_dual_surface_parity.py` 守护。
- `data/ai/*.yaml` + `prompts/registry.yaml` — Agent 装配数据源；沙箱 capability 授权源为 Agent YAML `features.studio.sandbox_capabilities`。
- `tool_configs/tools_schema.yaml`（mtime 热重载）、`flows/rna_seq.yaml` v2.3.0/`atac_seq.yaml`、`pipelines/jbrowse2/`（v2.15.1 构建产物，禁改源码）、`ROUTER_MAX_TOKENS=10000`。
- Alembic = schema 唯一事实来源；`scripts/check_schema_drift.py` 在容器 entrypoint 做线上 fail-fast 对账（`RUN_MIGRATIONS=1` 时）。

## 4. 编码规范与雷区

**强约束**：Ruff `line-length=100`、target py311（select E/W/F/I/N/UP/B/SIM/ASYNC，`E501` 被 ignore 但自觉 ≤100；festival 域 per-file 放行 `N815`）；mypy `strict=true` + `pydantic.mypy` 插件 + `disallow_untyped_defs`，新代码全类型注解；pytest 必须打 marker（unit/integration/e2e/quarantine），fixture 挂 `tests/conftest.py` 或域内 conftest；配置一律走 `core/config.py Settings` / `data/*.yaml`，禁散落的魔法常量；错误处理走 `core/exceptions.py` + 统一事件/审计落库，禁裸 `print`；前端 TS strict、`@/*` alias、API 调用集中在 `src/api/`、DOM 测试用 `// @vitest-environment jsdom` 头注释。

**严禁事项（Red Lines）**：禁引入 mem0 / Anthropic SDK / LlamaIndex；禁动 `jieba==0.42.1` 精确锁；禁手改 `uv.lock`/`package-lock.json`；镜像禁 `latest`、容器禁切 root、`/workspace/input` 只读、沙箱 uid 10001 + cap_drop=ALL；Agent 不得获得 shell / 流程 YAML / DB 写权限；禁把 `ARCHITECTURE_DESIN/deprecated/`、`cygnusx_studio_handover_2026-07.md`、任何 `*_plan`/`vision_2026-*` 提案当作现状依据（`agentteams_*` 设计文档已废弃但执行路径仍是现状，以代码 + `agent_execution_framework.md` 为准）。

**排坑指引（Gotchas）**：
1. `data/CygnusX.yaml` 的 `agents.enabled`（19 个）决定加载哪些 Agent YAML——新增 Agent 必须在两处同时登记，否则静默不加载；`tests/unit/test_agent_loader_studio.py` 强制每个 Agent 声明 studio 运行时镜像。
2. Agent 有 4 种执行闭环（Legacy ReAct / LangGraph ReAct / Studio Loop / Worker ReAct），改 Chat 链路先查 `agent_execution_framework.md` 的 execution_path 登记表，改错路径不生效。
3. 长任务 >600s 一律 Celery job reconcile-only，web 进程内不得直接跑；RocketMQ worker（`task_queue/rocketmq_worker.py`）是另一条消费路径。
4. `frontend/` dev proxy 指向 `:8888`（nginx），裸起 uvicorn 是 `:8000`，联调端口错位会 404 [待人工确认：本地 compose 端口映射以 `deploy/docker/` compose 为准]。
5. 改 `data/MODULE_LOCKED.yaml` 后前后端**双双**消费：后端启动硬校验 + 前端路由守卫，任何一边漏同步都会表现为模块 403/消失。
6. Agent 提示词含 `{{runtime_images}}`/`{{bio_packages}}` 占位符，由 `agent_loader._inject_prompt_context` 加载时替换——往 prompt 里写双花括号会被当占位符处理。
7. 双 Skill 体系勿混淆：`.agents/skills/`（561 个 bio-*，Kimi CLI 编码助手用，目录扫描加载）≠ `data/ai/skills/`（平台业务 Agent 用，DB 三表索引）。
8. `frontend/.mypy_cache`（28MB）是误生成的 Python 缓存，可清理，与前端工具链无关。

## 5. 变更验证矩阵

| 改动类型 | 最小验证命令 | 必须触发 E2E/集成 的条件 |
|---|---|---|
| 核心逻辑（domain/application/chat 链路） | `make lint && make type-check && uv run pytest tests/unit -q -m "not quarantine"` | 改 Chat 执行/事件流 → `tests/e2e/chat_golden` + langgraph 沙箱用例 |
| 接口契约（API schema/DB 模型/MCP 工具） | ruff+mypy+单测 + `make check-migrations`（DB 变更须带迁移） | 改 API 响应结构 → `tests/integration`；改 MCP 确认契约 → `test_mcp_dual_surface_parity.py` |
| 前端（组件/store/api） | `npm run type-check && npm test`；动路由/布局/构建再加 `npm run build` | SSE 流式、文件上传、沙箱终端交互需手工 E2E；live E2E 仅 `agentteams-live-e2e.yml` 手动 dispatch（需 secrets） |
| 配置（Agent YAML/prompts/image-mapping/CygnusX.yaml/MODULE_LOCKED） | `make validate-image-mapping` + 单测 + 实际加载验证（`load_agent_configs()`） | 改模块注册须全栈启动验证门禁；镜像按 6 步清单同步并重建子镜像 |
| 子模块（pipelines/FlowFrame） | 子仓自身测试 | 父仓仅提交指针；流程契约变更须 FlowFrame 规范 v2.0 评审 |
| live E2E（跨 docker compose 全栈） | 手动 dispatch `agentteams-live-e2e.yml`（需 secrets 注入 `.env`/`bridge.env`） | 仅改动协作室/桥接层且单元+集成均无法覆盖时触发 |
| 纯文档 | 无需测试 | `ARCHITECTURE_DESIN/` 遵循其 README 治理：活文档不带日期、快照带 `_YYYY-MM`、废弃进 `deprecated/` |
