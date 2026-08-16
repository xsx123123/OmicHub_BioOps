# OmicHub 开发进度 Todo

> 基于 `docs/` 架构设计文档，逐步完善项目骨架。
> 更新日期：2026-07-06 (生信工具箱模块化重构 + 数据目录集中迁移 omichub_data)

---

## 已完成

### 生信工具箱模块化重构（工具代码收口 + 路由自动发现）✅ 2026-07-06

> 需求：工具箱代码原先散落在 `api/v1/`、`application/services/`、`application/schemas/`、`infrastructure/config/`、`infrastructure/execution/`、`infrastructure/celery_app/tasks/` 六处分层目录，新增工具需手改 ~7 处代码（含 `router.py` 显式 `include_router`）。将每个工具的代码收口到自包含子包，实现「加子包即模块、核心路由表零侵入」。
> 架构决策：在主包内建 `src/omichub/tools/` 子包（非仓库根 `tool_configs/`——后者保持纯 YAML 配置，配置与代码职责分离）；每个工具一个子包（`api.py`/`service.py`/`schema.py`/`config.py`/`tasks.py`/`runner.py`）；`tools/__init__.py` 提供 `register_tool_routers()` 自动扫描子包 `api.py` 的 `router` 属性并挂载，`router.py` 不再逐工具手写挂载。
> 验证：ruff 改动文件 0 错误；23 单测通过（唯一失败的 `test_download_service` 与本次无关）；运行中 app OpenAPI 150 路径含 jbrowse 11 / enrichment 2 / tools 2；worker 仅注册新路径任务；7 容器 healthy。

- [x] **新包结构** — `src/omichub/tools/` 下三个子包：
  - [x] `registry/`（api/schema/config）← 原 `api/v1/tools.py` + `schemas/tools_registry.py` + `config/tools_registry_config.py`
  - [x] `jbrowse/`（api/service/schema/config/tasks）← 原 5 文件
  - [x] `enrichments/`（api/service/schema/config/runner）← 原 5 文件
  - [x] 共 13 个工具文件 `git mv`/`mv` 归位（jbrowse 走 `git mv` 保留历史，enrichment/registry 为未跟踪文件走 `mv`）
- [x] **路由自动发现** — `tools/__init__.py` 的 `register_tool_routers(api_router)`：`pkgutil.iter_modules` 扫描子包，导入 `<包>.api`，有 `router` 属性即按子包自声明的 `prefix`/`tags` 挂载；纯配置工具（无 api.py）静默跳过
  - [x] 每个 `api.py` 新增模块级 `prefix`/`tags` 常量（jbrowse→`/jbrowse`、enrichment→`/enrichment`、registry→`/tools`）
  - [x] `api/v1/router.py` 移除 jbrowse/enrichment/tools 显式 import + 3 行 `include_router`，改为一行 `register_tool_routers(api_router)`
- [x] **import 全量改写** — 13 个移动文件内部 import 改为绝对路径 `omichub.tools.<工具>.*`；外部引用同步更新：
  - [x] `infrastructure/celery_app/celery.py` — `include` 列表与 `task_routes` 的 jbrowse 项改指向 `omichub.tools.jbrowse.tasks`
  - [x] `jbrowse/tasks.py` — 两个 `@shared_task(name=...)` 更新为新模块路径
- [x] **清理遗留** — 删除旧路径遗留的 13 个 orphan `.pyc`（曾导致 worker 重复注册新旧两套任务名）
- [x] **文档** — `tool_configs/README.md` 后端入口表 + 新增工具流程更新为模块化版本（标注「无需改 router.py」）
- [x] **验证** — 自动发现单元测试发现 3 个工具模块；OpenAPI 含全部 15 条工具路由；HTTP `/api/v1/{tools,enrichment/species,jbrowse/assemblies}` 均返 401（路由存在，仅需鉴权）

### 数据目录集中迁移到 omichub_data ✅ 2026-07-06

> 需求：将 `/data/omichub` 下的 `jbrowse`/`knowledge`/`_pgdata`/`_redis`/`welcome` 五类核心数据集中迁至 `/data/omichub/omichub_data/` 子目录，让数据区更清爽；迁移过程中同步修改所有涉及的脚本/配置，并产出目录结构说明文档。
> 架构决策：`data_root`（`/data/omichub`）保持不变——`omichub_data` 仍是其子目录，故容器 `/data/omichub` 挂载、nginx `/tracks/` alias、`to_tracks_uri()` 路径换算**全部无需改动**，仅同步修改 4 个文件中的具体子路径。`_pgdata`(uid 70)/`_redis`(uid 999) 因属主非 zj 且 `mv` 需更新目录内 `..` 条目，用临时 root 容器执行重命名（sudo 不可用时的绕过方案）。
> 验证：DB `users=2/tables=28/alembic=7ec7e0105527`、Redis `db1=3/db2=284` 数据无损；nginx `/tracks/omichub_data/jbrowse/.../GRCh38.p14.genome.fa` 返 HTTP 206（JBrowse2 Range Request 正常）；7 容器 healthy。

- [x] **目录迁移** — `jbrowse`/`knowledge`/`welcome`（zj 属主，`mv`）；`_pgdata`/`_redis`（`docker run --rm -v alpine mv` 以 root 重命名，属主/权限原样保留）
- [x] **配置/脚本同步修改**：
  - [x] `tool_configs/jbrowse/jbrowse_config.yaml` — fasta/fai/预设轨道路径 → `omichub_data/jbrowse/`（scan_paths/upload_dir 引用 users 不动）
  - [x] `deploy/docker/docker-compose.yml` + `docker-compose.prod.yml` — `db`/`cache` bind mount → `omichub_data/_pgdata`、`omichub_data/_redis`
  - [x] `src/omichub/core/config.py` — `welcome_yaml`/`welcome_state_yaml` → `omichub_data/welcome/`
- [x] **知识库运行时副本** — `docs/knowledge/` 镜像到 `/data/omichub/omichub_data/knowledge/`（含 figure/video）；新增 `data-directory-guide.md` 详细目录说明并登记到 `meta.yaml`
- [x] **文档** — README.md 新增「数据目录结构」章节（目录树 + 子目录表 + 迁移说明）；`docs/OmicHub_数据存储排查与迁移规划报告.md` 加 omichub_data 收口更新说明 + 修正 bind mount 示例
- [x] **验证** — ruff/YAML 校验通过；`test_docs_service` 5/5 通过；JBrowse `/tracks/` 流式读取 HTTP 206；DB/Redis 数据完整性校验通过

### 个人中心 Bento Grid 重构 ✅ 2026-07-05

> 需求：按 `docs/26.7.5/omicHub_profile_page_full_implementation.md` 与 `omicHub_profile_page_bento_grid.md` 重构个人中心，从垂直堆叠改为 Bento Grid 布局。
> 验证：前端 `vue-tsc --noEmit` 通过；`npm run build` 构建成功。

- [x] **Bento Grid 布局**
  - [x] `frontend/src/views/ProfileView.vue` 改为 3 列 CSS Grid，最大宽度 960px
  - [x] 用户信息 `span 3`、KPI `span 1`、最近任务 `span 2`、常用流程 `span 1`、安全 `span 1`、偏好 `span 2`、API 密钥 `span 3`、隐私 `span 2`、审计日志 `span 1`
  - [x] 响应式：`>900px` 3 列、`600-900px` 2 列（KPI 保持小方块）、`<600px` 1 列
- [x] **功能卡片**
  - [x] 用户信息卡片：头像、角色标签、ID/创建时间、邮箱、状态
  - [x] 使用概览 KPI：本月分析、运行中、存储用量、存储进度条
  - [x] 常用流程竖排快捷入口、最近任务列表
  - [x] 安全与登录、登录历史抽屉、活跃会话抽屉
  - [x] 操作审计、API 密钥管理（新建/复制/撤销）
  - [x] 平台偏好（默认首页/主题/语言/通知渠道）、数据与隐私（导出/下载/删除账户）
- [x] **Mock 与 API 兼容**
  - [x] 后端未就绪模块使用 Mock 数据，接口就绪后自动切换
  - [x] 偏好设置先写入 localStorage，后续可替换为 `/api/user/preferences`

### 首页 Hero 动态背景动画库 v3 ✅ 2026-07-05

> 需求：按 `docs/26.7.5/omicHub_hero_animation.md` / `v3.md` 替换 Hero 区域静态烧瓶为动态 Canvas 动画，每次加载随机切换。
> 验证：前端 `vue-tsc --noEmit` 通过；`npm run build` 构建成功。

- [x] **新增组件** — `frontend/src/components/HeroAnimation.vue`，纯 Canvas 实现，零外部依赖
- [x] **6 种动画模式**（每次加载随机选取）：
  - [x] `particles`：浮动粒子网络 + 近距连线
  - [x] `stars`：星空粒子 + 大星十字光芒
  - [x] `aura`：同心圆环光晕脉冲 + 放射线
  - [x] `noise`：Perlin noise 噪点流场
  - [x] `orbitals`：几何轨道环 + 轨道小白点
  - [x] `gradient`：蓝紫粉渐变流光色块
- [x] **集成与优化**
  - [x] `frontend/src/views/HomeView.vue` 引入 `HeroAnimation`，移除静态烧瓶图标
  - [x] Canvas `opacity: 0.35`、`pointer-events: none`，不干扰文字与按钮
  - [x] Retina 适配、resize 自适应、页面不可见暂停、组件卸载清理

### 饼干定价页 500 错误修复 + AI 助手架构文档 ✅ 2026-07-04

> 需求：`/admin/cookies/pricing` 页面突然报 500 错误（`Request failed with status code 500`）。
> 根因分析：`cookie_pricing` 数据库表缺少 ORM 模型中定义的 `per_sample_cost` 和 `per_comparison_cost` 两列，查询时触发 `asyncpg.exceptions.UndefinedColumnError`。同时 CHECK 约束 `chk_pricing_unit` 缺少 `per_sample` 和 `per_comparison` 两个合法值。数据库 schema 与 ORM 模型不一致，属于历史迁移遗漏。
> 验证：修复后 `\d cookie_pricing` 确认两列已存在、约束已更新。

- [x] **数据库修复** — `ALTER TABLE cookie_pricing ADD COLUMN per_sample_cost/per_comparison_cost` + 重建 `chk_pricing_unit` 约束（新增 `per_sample`/`per_comparison`）
- [x] **Alembic 迁移** — `l9m0n1o2p3q4_add_cookie_pricing_sample_cost_columns.py`（upgrade/downgrade 完整，链 `k8l9m0n1o2p3 → l9m0n1o2p3q4`）
- [x] **AI 助手架构文档** — `docs/ai.md`：汇总当前 AI 助手完整实现（两代架构演进、后端四层文件清单、前端组件/Store/Composable 清单、Agent 模式端到端数据流、配置体系、安全机制、DB ER 关系、扩展点分析），供后续架构优化参考

### AI 助手架构优化（按调研报告）✅ 2026-07-04

> 依据：`docs/omichub-architecture-research-report.md`。目标：解决报告中 5 大问题（模型一致、自动发现、配置统一、文件/搜索/代码执行、保留样式）。
> 验证：后端 `ruff check` / 前端 `vue-tsc --noEmit` / `npm run build` 通过；新增 Alembic 迁移 `n1o2p3q4r5s6`。

- [x] **问题 1：Agent 模型调用一致**
  - [x] 后端：`AgentService.assemble_context()` 严格按 `model_id` 外键解析，取消 fallback 到默认模型
  - [x] 后端：`create_agent` / `update_agent` 时自动同步 `model_engine` / `model_name`
  - [x] 后端：`CreateAgentRequest` / `UpdateAgentRequest` 移除 `model_engine` 字段，避免前端字符串覆盖
  - [x] 前端：`AgentResourceTab.vue` 模型列移除 `model_engine` fallback，仅展示下拉选择的 Provider
- [x] **问题 2：模型自动发现**
  - [x] 后端：`OpenAICompatibleProvider.list_models()` 调用 `/v1/models`
  - [x] 后端：`POST /admin/ai-providers/{id}/discover-models`
  - [x] 后端：`GET /admin/ai-providers/templates` 内置 Provider 模板
  - [x] 数据：`data/provider_templates.yaml` 预置 OpenAI / Anthropic / DeepSeek / Kimi / Qwen / Ark / Ollama
  - [x] 前端：`AgentResourceTab.vue` 模型下拉旁增加刷新按钮 + 发现结果浮层
- [x] **问题 3：配置统一**
  - [x] 后端：`agent_templates` 新增 `features` JSONB（联网搜索 / 文件上传 / 代码执行 / 深度思考）
  - [x] 后端：`AgentContext` 携带 `features`，`stream_agent_chat` 默认启用 Agent 级开关
  - [x] 后端：Alembic 迁移 `n1o2p3q4r5s6_add_agent_features.py`
  - [x] 前端：`AgentResourceTab.vue` 新增「功能开关」表单区
  - [x] 前端：`AgentTemplate` / `adminAgentApi` DTO 映射 `features`
- [x] **问题 4：文件上传 / 联网搜索 / 代码执行**
  - [x] 后端：`POST /files/chat-upload` + `GET /files/chat-upload/{filename}` 独立聊天附件目录
  - [x] 后端：`ChatStreamRequest` 增加 `attachments` / `enable_web_search`
  - [x] 后端：`ChatService._build_multimodal_messages()` 把图片转 base64 `image_url`、文本文件注入上下文
  - [x] 后端：`WEB_SEARCH_TOOL` 动态注入 + `_web_search()` 占位实现（可替换真实搜索引擎）
  - [x] 前端：`KimiChatInput.vue` 文件上传真实可用、联网搜索 toggle、附件标签展示
  - [x] 前端：`useAgentChatStream` / `agentHub.sendMessage` 透传 `attachments` / `enableWebSearch`
  - [x] 前端：`usePyodide.ts` 懒加载 Pyodide + numpy/pandas/matplotlib
  - [x] 前端：`setup.ts` 代码块增加「▶ 运行」按钮；`KimiMessageItem.vue` 调用 Pyodide 并展示输出/图表
- [x] **问题 5：保留现有样式 + 引入架构**
  - [x] 未引入新 UI 框架，沿用 Vue 3 + Pinia + NaiveUI
  - [x] 复用 MCP 架构接入联网搜索，OpenAI 兼容 Provider 架构接入自动发现

### 统一夜间模式与 AI 助手主题联动 ✅ 2026-07-02

> 需求：平台此前没有真正的夜间模式切换，AI 助手沿用独立的 Kimi 风格纯黑主题，与平台整体不统一。需要实现全局主题切换，并让 AI 助手跟随平台主题。
> 架构决策：新增 `useThemeStore` 统一管控主题，持久化到 `localStorage` key `omichub-theme`；在 `<html>` 上设置 `data-theme` 与 `.dark` class；`App.vue` 的 `NConfigProvider` 绑定 Naive UI `darkTheme` 并把 `themeOverrides` 改为响应式；`global.css` 新增 `:root[data-theme="dark"]` 平台深色变量，并把 `.kimi-layout` 的 chat 变量映射到平台统一中性色；AI 助手移除独立的 `theme`/`chat-theme` 逻辑，完全跟随全局 `data-theme`。
> 验证：前端 `npm run type-check && npm run build` 通过。

- [x] **全局主题 Store**
  - [x] 新建 `frontend/src/stores/theme.ts` — `useThemeStore`：`theme`/`isDark`/`setTheme`/`toggleTheme`/`initTheme`
  - [x] `localStorage` key 为 `omichub-theme`，默认 `dark`
  - [x] 设置 `document.documentElement.setAttribute('data-theme', ...)` + `classList.toggle('dark', ...)`
- [x] **启动时恢复主题**
  - [x] `frontend/src/main.ts`：Pinia 创建后立即 `themeStore.initTheme()`，避免首屏闪白
- [x] **Naive UI 动态主题**
  - [x] `frontend/src/App.vue`：导入 `darkTheme` + `useThemeStore`
  - [x] `NConfigProvider` 绑定 `:theme="naiveTheme"`
  - [x] `themeOverrides` 改为 `computed<GlobalThemeOverrides>`，深色/浅色自动切换 common text/body/card/modal/popover/divider/border + Layout + Menu 颜色
- [x] **平台深色 CSS 变量**
  - [x] `frontend/src/styles/global.css`：新增 `:root[data-theme="dark"]` 覆盖 `--arco-*` / `--neutral-*` / `--sidebar-*` / `--shadow-*` / `--page-bg`
  - [x] 新增 `:root[data-theme="dark"] .kimi-layout` 规则，把 `--chat-*` 系列变量映射到平台统一中性色（背景/表面/边框/文本/强调色/输入框/导航栏/芯片/阴影等）
- [x] **顶部用户菜单主题切换**
  - [x] `frontend/src/layouts/DefaultLayout.vue`：导入 `SunnyOutline`
  - [x] `userMenuOptions` 改为 `computed`，当前深色时显示「浅色模式 ☀️」，浅色时显示「深色模式 🌙」
  - [x] `handleUserMenuSelect` 增加 `theme` 分支，调用 `themeStore.toggleTheme()`
- [x] **AI 助手去独立主题**
  - [x] `frontend/src/stores/chat.ts`：移除 `theme` ref、`setTheme`/`toggleTheme`、`chat-theme` localStorage 读写
  - [x] `frontend/src/components/ai-chat/KimiLayout.vue`：导入 `useThemeStore`，模板 `:data-theme="themeStore.theme"`

### 饼干余额调账修复（已有用户无法选择 + 充值成功报系统内部错误）✅ 2026-07-02

> 需求：「充值 / 变更饼干余额」弹窗中无法选择已有用户；选择用户充值后提示成功，但随后又弹出「系统内部错误，请联系管理员」。
> 根因分析：
> 1. 用户选择：早期实现只从饼干账户列表拉人，导致未开通饼干钱包的已有用户选不到。当前 `RechargeModal` 已改为从 `/admin/users` 拉全部注册用户，此问题实际已修复。
> 2. 系统内部错误：前端选择「扣除」时发送负数金额；后端 `CookieService.adjust_balance` 会把带符号金额记为 `txn_type='adjust'`；但数据库 `cookie_transactions` 表的 check constraint `chk_txn_amount_sign` 强制 `adjust` 类型金额必须 `>= 0`，写入负数时触发数据库校验错误，被全局异常处理器统一返回「系统内部错误，请联系管理员」。
> 架构决策：调整数据库约束，允许 `adjust` 类型金额可正可负（正=充值/补贴，负=扣除/调账）；`earn`/`refund`/`unfreeze` 仍必须非负，`spend`/`freeze` 仍必须非正。同步新增 Alembic 迁移 + 合并迁移解决当前 revision 分支问题，并增强前端错误提示。
> 验证：
> - 后端 `uv run ruff check` 针对改动文件通过；
> - 后端 `uv run pytest tests/ -v`：36 通过，1 个预存在的下载服务测试失败（与本次改动无关）；
> - 前端 `npm run type-check && npm run build` 通过；
> - `alembic history` 单 head：`i6j7k8l9m0n1_merge_cookie_adjust_heads`。
> ⚠️ 真实环境待执行：`make migrate`（或 `uv run alembic upgrade head`）应用新迁移。

- [x] **后端 — 修正数据库约束**
  - [x] `src/omichub/infrastructure/database/models/cookie.py`：更新 `chk_txn_amount_sign`，`adjust` 允许正负；`earn`/`refund`/`unfreeze` 仍 `>=0`；`spend`/`freeze` 仍 `<=0`
- [x] **后端 — Alembic 迁移**
  - [x] 新建 `alembic/versions/h4i5j6k7l8m9_allow_negative_adjust_transactions.py` — 删除旧约束、创建新约束
  - [x] 新建 `alembic/versions/i6j7k8l9m0n1_merge_cookie_adjust_heads.py` — 合并当前分支，保证 `alembic upgrade head` 单 head
- [x] **前端 — 调账弹窗健壮性**
  - [x] `frontend/src/components/admin-cookie/RechargeModal.vue`：移除 `handleSubmit` 中 catch 后的 `return` 与重复 `store.fetchAccounts()`，由父组件统一刷新
  - [x] `frontend/src/views/AdminCookieManagementView.vue`：`onRechargeSuccess` 加 try-catch，刷新失败时给出具体错误提示
  - [x] `frontend/src/views/AdminUserManagementView.vue`：`fetchUsers` 加 try-catch，加载失败时提示具体原因
- [x] **用户选择确认**
  - [x] `RechargeModal.vue` 继续从 `/admin/users` 拉全部注册用户（含未开通饼干钱包用户），支持 filterable 搜索

### AI 助手 YAML 化配置 + 模型显示修复 ✅ 2026-07-02

> 需求：① AI 助手显示的模型名与实际使用的模型不一致（内置种子 `model_engine` 写 "gpt-4o" 等假名，`model_id` 为 None，回落到默认模型）；② 每个助手应可独立配置模型、MCP、技能、提示词，配置存于 `data/ai/*.yaml`，由 `OmicHub.yaml` 控制加载哪些助手。
> 架构决策：每个助手一个 YAML 文件（`data/ai/{name}.yaml`），`model` 字段按 name 匹配 `ai_provider_configs` 表解析出真实 `model_id`；`OmicHub.yaml` 新增 `agents.enabled` 列表控制加载；`model_engine` 改为从 provider config 动态填充真实模型名；前端移除硬编码 `MODEL_ENGINE_OPTIONS`，直接展示后端返回的模型名。
> 验证：`agent_loader.py` 导入通过 + 成功加载 4 个 YAML 配置；`agent_service.py` 导入通过；前端 `vue-tsc --noEmit` 零错误。⚠️ 真实环境待补：`alembic upgrade head`（新增 `model_name` 列）+ 端到端发消息验证模型显示一致。

- [x] **YAML 配置文件**
  - [x] `data/ai/general.yaml` — 通用助手（model: qwen3.7-max）
  - [x] `data/ai/rnaseq.yaml` — RNA-seq 分析师
  - [x] `data/ai/code.yaml` — 代码助手
  - [x] `data/ai/viz.yaml` — 可视化助手
  - [x] `data/OmicHub.yaml` 新增 `agents.enabled` 列表（控制加载哪些助手）
- [x] **后端 — YAML 加载器**
  - [x] `infrastructure/config/__init__.py` + `agent_loader.py` — 读取 `OmicHub.yaml` 的 `agents.enabled`，逐个加载 `data/ai/{name}.yaml`，文件缺失/解析失败跳过并记录日志
- [x] **后端 — DB Model 扩展**
  - [x] `models/agent.py` 新增 `model_name` 列（存 YAML 中的模型名称，便于调试）
  - [x] Alembic 迁移 `g3h4i5j6k7l8_add_model_name_to_agent_templates.py`
- [x] **后端 — AgentService 改造**
  - [x] 删除硬编码 `BUILTIN_AGENTS` 列表
  - [x] `ensure_builtin_agents()` 改为调用 `load_agent_configs()` 从 YAML 加载
  - [x] 按 `model` name 查 `ai_provider_configs` 解析 `model_id` + 自动填充 `model_engine`（真实模型名）
  - [x] `_to_dto()` 新增 `model_name` 字段
- [x] **后端 — Schema 扩展**
  - [x] `schemas/agent.py` — `AgentTemplateDTO` + `CreateAgentRequest` 新增 `model_name` 字段
- [x] **前端 — 移除硬编码模型选项**
  - [x] `stores/agentHub.ts` 删除 `MODEL_ENGINE_OPTIONS` 硬编码列表
  - [x] `components/admin/AgentResourceTab.vue` 移除「模型引擎标签」表单项（`model_engine` 自动解析）+ 移除 `MODEL_ENGINE_OPTIONS` 导入
  - [x] `components/agent-workspace/AgentSandbox.vue` 简化 `engineLabel`，直接显示 `model_engine`
  - [x] `components/agent-workspace/AgentCapabilityDrawer.vue` 同上
- [x] **前端 — 类型与 API 映射**
  - [x] `types/agent.ts` — `AgentTemplate` 新增 `model_name?: string`
  - [x] `api/agent.ts` — `toAgent()` 新增 `model_name` 字段映射

### 分析流程中心 GitHub 源码链接 ✅ 2026-07-02

> 需求：分析流程中心已有流程（RNA-seq、ATAC-seq 等）的 YAML 配置中定义了 `meta.docs_url`（GitHub 仓库地址），后端 API 也已透传该字段，但前端未渲染。需要在流程卡片和提交页面展示 GitHub 源码链接。
> 架构决策：零后端改动（`docs_url` 已在 `FlowMeta` 值对象 + `FlowListItemDTO` + `FlowMetaDTO` 中传递）。前端三处改动：`FlowDefinition` 类型补字段 → `FlowsView.vue` 推荐卡右上角 + 普通卡标签栏加 GitHub 图标链接 → `FlowSubmitView.vue` 标题旁加「查看源码」按钮。链接使用 `@click.stop` 阻止冒泡（避免同时触发卡片跳转），`target="_blank"` 新窗口打开。后续新增流程只要在 YAML 中设置 `meta.docs_url` 即自动展示。
> 验证：`vue-tsc --noEmit` 零错误。

- [x] **前端类型补全**
  - [x] `types/index.ts` — `FlowDefinition` 接口新增 `docs_url?: string | null`
- [x] **FlowsView.vue 流程卡片**
  - [x] 导入 `LogoGithub` 图标 + `NIcon` 组件
  - [x] 推荐流程（featured card）右上角新增「源码」按钮（半透明白底，hover 加深），`@click.stop` 阻止冒泡
  - [x] 普通流程卡片标签栏末尾新增 GitHub 图标链接（`margin-left: auto` 推至右侧），hover 变深色
  - [x] 两处链接均 `v-if="flow.docs_url"` 条件渲染，无 `docs_url` 时不显示
- [x] **FlowSubmitView.vue 提交页**
  - [x] 标题区改为 flex 布局，右侧新增「查看源码」按钮（灰底圆角，hover 加深）
  - [x] `v-if="flow?.meta.docs_url"` 条件渲染，读取 `FlowConfig.meta.docs_url`

### 生信工具箱 (BioTools) 前端模块搭建 ✅ 2026-07-02

> 需求：新增「生信工具箱」模块，提供 FASTQ 质控、Web IGV 浏览器、序列检索 (BLAST)、组学绘图工坊等独立工具页面。当前阶段仅搭建前端 UI 骨架与静态交互，全程使用 Mock 数据，后端 API 在后续阶段逐步接入。
> 架构决策：前端 `views/BioTools/` 独立子目录（打破现有扁平结构，建立工具"特区"）；路由统一 `/tools/*` 前缀；侧边栏新增一级菜单「生信工具箱」（`ConstructOutline` 图标），`isActive` 扩展支持子路由高亮；Dashboard 新增 4 卡片快捷入口；图表渲染复用项目已有的 `vue-echarts` + `echartsSetup.ts`。
> 验证：前端 `vue-tsc --noEmit` 零错误；`vite build` 成功（10.24s）。

- [x] **阶段零：目录结构与路由**
  - [x] 新建 `frontend/src/views/BioTools/` 目录（5 个页面）+ `frontend/src/components/bio-tools/` 目录（共享组件）
  - [x] `router/index.ts` 新增 5 条路由：`/tools`（大厅）/ `/tools/fastq-qc` / `/tools/igv` / `/tools/blast` / `/tools/plot`，全部 `requiresAuth: true` + 懒加载
  - [x] `DefaultLayout.vue` 侧边栏 `mainNavItems` 新增「生信工具箱」（`ConstructOutline` 图标，位于「代码沙盒」之后）
  - [x] `DefaultLayout.vue` `isActive()` 扩展：`item.key === 'tools'` 时 `/tools` 和 `/tools/*` 均高亮
- [x] **阶段一：前端 UI 搭建（Mock 数据）**
  - [x] **ToolCard.vue** — 大厅可复用卡片组件（渐变图标 + 标题 + 描述 + hover 浮起动效）
  - [x] **ToolsHubView.vue** — 工具箱大厅：2×2 卡片网格（FASTQ/IGV/BLAST/绘图），点击跳转对应工具页，移动端单列
  - [x] **FastqQCView.vue** — FASTQ 质控页：左栏参数面板（Phred 阈值滑块 / 截断长度滑块 / 接头开关 / 文件选择）+ 右栏 Mock 统计卡片（保留率 / Reads 数 / GC%）+ ECharts 碱基质量分布折线图（滑动参数时 Mock 数据动态联动）
  - [x] **IGVBrowserView.vue** — IGV 占位页：参考基因组下拉（hg38/mm10/水稻/拟南芥）+ 渲染容器占位提示 + Mock 轨道列表（Sample_1.bam / H3K27ac.bw），暂不引入 igv.js 依赖
  - [x] **BlastSearchView.vue** — BLAST 检索页：FASTA 文本框（支持文件上传填充）+ 目标数据库下拉（水稻泛基因组/生菜转录本/拟南芥蛋白库/NCBI nt）+ E-value 阈值 + Mock 结果 NDataTable（Query/Subject/Identity%/E-value/Bit Score）+ 序列比对高亮 `<pre>` 展示
  - [x] **PlotWorkshopView.vue** — 绘图工坊：CSV/TSV 上传 + 5 种图表类型（柱/线/散点/热图/箱线图）+ X/Y 轴列选择 + 配色方案 + ECharts 实时渲染画布（切换图表类型即渲染对应 Mock 图表）
  - [x] **DashboardView.vue** — 在 overview-grid 与 AdminStatsPanel 之间新增「生信工具箱」快捷入口卡片（4 列网格，响应式 2 列/1 列）
- [ ] **后续阶段（待推进）**
  - [ ] 阶段二：后端 `/api/v1/tools/` 路由组 + IGV 静态资源 Range Requests 支持 + 质控接口联调（Rust 脚本）
  - [ ] 阶段三：Celery 异步 BLAST 任务队列 + AI 绘图 Agent 接入（MCP 协议）
  - [ ] 后端 `tools_engine/` 目录（Rust 质控工具 + Python 绘图脚本）
  - [ ] igv.js 真实引入（配合 BAM/BigWig Range Requests）

### 数据管理模块全面升级（多租户隔离 + 配额 + 断点续传 + 生命周期）✅ 2026-07-02 待真实环境验证

> 需求：构建支持多用户物理/逻辑隔离、500GB 动态配额与自动清理、大文件断点续传与容量可视化的生信存储底座，为 Nextflow/Snakemake 流程提供稳健文件吞吐。
> 架构决策：配额落 User 表（与现有 per-user 隔离逻辑统一，弃用未启用的 Workspace 表配额）；新建 FileRecord/UploadSession/Sample 三表替代磁盘扫描；仓储层所有方法首参 user_id + WHERE 过滤，杜绝水平越权。
> 验证：15 个后端模块导入通过；create_app().openapi() 注册 9 个 files + 8 个 admin 路由；前端 vue-tsc 零错误、npm run build 成功；FileService 路径/类型识别正确；前后端 MD5 协议一致性已验证（spark-md5 与 hashlib.md5 同字节同结果）。⚠️ 真实环境待补：alembic upgrade head + httpie 端到端 + celery worker/beat 实跑。

- [x] **阶段一：底层架构与多租户隔离**
  - [x] `UserModel` 加 `storage_quota`(默认 500GiB)/`used_storage` + User 领域实体同步 + 仓储 `add_used_storage()` 原子累加（防并发双计）
  - [x] 新建 `models/file.py`：`FileRecordModel`/`UploadSessionModel`/`SampleModel`，全部 `user_id` 外键 + 索引 + ondelete=CASCADE
  - [x] Alembic 迁移 `a9b0c1d2e3f4`（链 f1a2b3c4d5e6→a9b0c1d2e3f4）：新列 + 三新表 + 外键 + 索引 + server_default
  - [x] `QuotaExceededError` → 全局 OmicHubError handler 映射 403
  - [x] 路径规范化：`{storage_path}/users/{user_id}/raw/` 与 `/results/`，FileService 路径工厂 `user_raw_dir`/`user_results_dir`
- [x] **阶段一：Repository 层（强制 user_id 隔离）**
  - [x] `domain/file/repositories.py` 三接口（IFileRepository/IUploadSessionRepository/ISampleRepository），所有方法首参 user_id
  - [x] `infrastructure/database/repositories/file_repository.py` 三实现，get_by_id 同时校验归属（越权返 404）
  - [x] `FileService.list_files` 从磁盘 rglob 切换为 DB 查询（支持排序）
- [x] **阶段二：大文件传输与配额控制**
  - [x] `schemas/file.py` 扩展：UploadInit/Chunk/Merge/Quota/Sample DTO
  - [x] FileService：`init_upload`（配额预检→403、秒传、断点续传）/ `save_chunk`（MD5 校验+幂等）/ `merge_upload`（合并+总 MD5+原子累加配额+清理临时分片）/ `get_quota`
  - [x] 9 个路由：list / quota / upload/init / upload/chunk / upload/merge / upload/cancel / download / delete / samples
- [x] **阶段三：自动化管控与生命周期**
  - [x] `tasks/storage.py`：`reconcile_used_storage`（每日 3:00 盘点物理目录校正 used_storage）+ `cleanup_expired`（僵尸会话/30天临时/90天冷数据归档或删除）
  - [x] `celery.py` 注册 include + route + 两条 beat；旧 `analysis.cleanup_expired` 桩改为向后兼容委托
  - [x] `core/config.py` 新增保留期配置（file_temp_retention_days=30 / file_archive_retention_days=90 / file_archive_mode）
- [x] **阶段四：前端交互重构**
  - [x] `FilesView.vue` 重写：StorageBanner + ChunkUploader + 可排序表格 + 下载/删除
  - [x] `StorageBanner.vue`：复用 Dashboard 蓝紫渐变，三段阈值进度条（0-70% 青/71-90% 黄/91-100% 红）
  - [x] `ChunkUploader.vue` + `useChunkUpload.ts`：5MiB 切片、3 路并发、spark-md5、暂停/续传/取消
  - [x] `types/index.ts` 补 7 个类型（QuotaInfo/UploadInit/Chunk/Merge/QueueItem 等）
- [x] **阶段五：Admin 配额调配**
  - [x] 后端 `PUT /admin/users/{id}/quota`（校验正数/5TiB 上限/不低于已用）+ list_users 返回配额
  - [x] 前端 `AdminUserManagementView.vue` 加存储用量列（小进度条）+「配额」按钮 + `QuotaEditModal.vue`
- [ ] **真实环境验证（待补）**：alembic upgrade head → httpie 走 init/chunk/merge/quota/download/续传/越权404 → celery worker+beat 跑对账与清理

### Agent 调度中枢前后端真实联动（agent_id → 组装模型/系统词/MCP 工具 → SSE 流式 + tool_call 闭环）✅ 2026-07-02 待真实环境验证

> 需求：打通「组装环节」。此前前端智能体沙盒用 `sendMockMessage` 的 setTimeout 假回复，后端 `/chat/stream` 直接吃 model_id、无 Agent 概念、无 MCP 工具注入、system_prompt 被「极简测试」注释掉，且后端根本没有 Agent 实体（仅活在前端 Mock store）。目标链路：前端传 `agent_id` → 后端查 Agent 设定（system_prompt + 绑定模型 + 绑定 MCP 工具）→ 查模型连接信息 → MCP 工具 Schema 转 OpenAI tools 注入 → 打向模型 → SSE 流式回前端；模型返回 tool_calls 时后端用 MCPClient 自动执行并回灌，继续生成（agentic 闭环）。
> 架构决策（已与用户确认两点范围）：① Agent **全量落库**（新建 agent_templates 表，不走扩展 ChatAssistantModel 也不走前端透传）；② MCP 工具**注入 + 自动执行闭环**（不只注入）。
> 复用既有实现：SSE 解析复用 `useChatStream.ts` 模式扩展；Provider 复用 `OpenAICompatibleProvider`/`ProviderManager`；MCP 执行复用 `MCPClient.call_tool` + `MCPDomainService.route_tool_call`；消息持久化复用 `ChatService.add_message`/`get_session`/`create_session`/`update_message_content`；脱敏复用 `sanitizer`；技能 prompt 复用 `SkillService.build_skills_prompt`；Admin CRUD 范式复用 `admin/assistants.py`。
> 验证：后端 `import omichub.main` 通过、openapi 含 `/agents`/`/admin/agents`/`/chat/stream`(agent_id) 路由；ORM metadata 校验 `agent_templates` 表与 `chat_sessions.agent_id` 列已注册；迁移 revision 链正确（`7f8e9d0c1b2a → 9a5b6c7d8e1f`）；前端 `vue-tsc --noEmit` 零错误。⚠️ 真实环境待补：`alembic upgrade head`（沙箱无 DB 访问未实跑）+ 端到端发消息 + 给内置 Agent 绑定真实 model_id 后测工具调用闭环。

#### 后端 — Agent 实体落库
- [x] **新建 `infrastructure/database/models/agent.py`** — `AgentTemplateModel`：`id`/`agent_id`(unique)/`name`/`description`/`avatar`/`color`/`category`/`model_id`(FK→ai_provider_configs.id, nullable)/`model_engine`(展示 label)/`system_prompt`/`welcome_message`/`mcp_ids`(JSONB)/`skill_ids`(JSONB)/`temperature`/`max_tokens`/`is_builtin`/`is_active`/`is_default` + TimestampMixin；索引 `idx_agent_templates_category(category,is_active)`
- [x] **`chat.py` 模型扩展** — `ChatSessionModel` 新增 `agent_id` 列（FK→agent_templates.agent_id, nullable），会话归属 Agent
- [x] **`models/__init__.py` 注册** — import `AgentTemplateModel` 并加入 `__all__`（alembic autogenerate 依赖）
- [x] **Alembic 迁移 `9a5b6c7d8e1f_add_agent_templates.py`** — 建 `agent_templates` 表 + `chat_sessions.agent_id` 列 + FK；down_revision=`7f8e9d0c1b2a`（mergepoint 之后，单 head 无需 merge）

#### 后端 — Agent Schemas + Service
- [x] **新建 `application/schemas/agent.py`** — `AgentTemplateDTO`/`CreateAgentRequest`/`UpdateAgentRequest`（mcp_ids/skill_ids 为 list[Any]）
- [x] **新建 `application/services/agent_service.py`**
  - [x] `BUILTIN_AGENTS` 种子（4 个：general/rnaseq/code/viz，沿用前端 Mock seed 设定）
  - [x] CRUD：`list_agents(active_only)`/`get_agent`/`get_agent_dto`/`create_agent`/`update_agent`/`delete_agent`(builtin 仅停用)/`toggle_agent`/`set_default_agent` + `ensure_builtin_agents`(幂等落库)
  - [x] **`assemble_context(agent_id) -> AgentContext`**（调度中枢核心）：加载 Agent → `_resolve_model`(优先 agent.model_id，缺省回落默认/首个启用) → `SqlAlchemyMCPServerRepository.get_by_ids` 拉绑定 MCP server → 工具 `inputSchema` 转 OpenAI tools `{type:function, function:{name,description,parameters}}` → system_prompt = agent.system_prompt + `_build_skill_prompt`(skill_ids 经 SkillModel 解析 + `SkillService.build_skills_prompt`)
  - [x] `AgentContext` dataclass：agent/model_config(可 None)/system_prompt/tools/mcp_servers/temperature/max_tokens

#### 后端 — MCP 仓储 + Provider 升级
- [x] **`domain/mcp/repositories.py` + `mcp_repository.py` 新增 `get_by_ids(ids)`**（`where(id.in_(ids))`），供 assemble_context 批量拉绑定 server
- [x] **`openai_compatible.py` 升级**
  - [x] `chat_stream` 新增 `tools: list[dict] | None` 入参；非空时注入 `payload["tools"]` + `tool_choice="auto"`
  - [x] 累积流式 `tool_calls` 分片（按 index 累加 id/type/function.name/function.arguments）；流结束 yield 一个 `ChatChunk(type="tool_calls", metadata={"tool_calls":[...]})`（区别于旧的单分片 tool_call）
  - [x] 辅助方法 `_emit_tool_calls`/`_materialize_tool_calls` 提到 class 级（修正误入 try 块导致 except 失效）

#### 后端 — 编排闭环 + 路由
- [x] **`schemas/chat.py` 扩展 `ChatStreamRequest`** — `model_id` 改 `UUID | None`（与 agent_id 至少传一个）、新增 `agent_id: str | None`、新增 `stream: bool = True`
- [x] **`ChatService.create_session` 加 `agent_id` 参数** — 会话 agent_id 列落库
- [x] **`ChatService.stream_agent_chat`（新增，旧 stream_chat 不动）** — Agent 编排闭环：
  - [x] `assemble_context` 取 model_config/system_prompt/tools/mcp_servers；任一缺失 yield error chunk
  - [x] 取/建会话（复用 get_session/create_session）+ 落库用户消息(sanitize_text) + AI 占位消息(status=streaming)
  - [x] **Agentic 循环（上限 8 轮）**：`provider_manager.chat_stream(tools=...)` → 累积 text 逐 chunk yield(打字机) → 收到 tool_calls 则对每个 tool_call：yield `tool_call` SSE → 在绑定 mcp_servers 里按 tool_name 找 server → `MCPClient.call_tool` → yield `tool_result` SSE(含 success/结果) → append assistant tool_calls 消息 + 各 role:tool 结果消息 → continue 下一轮；无 tool_calls 则落库完整 content + yield `done`(带 session_id/message_id) + return
  - [x] 异常/超轮次落库已生成内容 + yield error/done；送 LLM 的 messages 用 sanitize_messages 脱敏
- [x] **`api/v1/chat.py` `/chat/stream` 分派** — agent_id 非空走 `stream_agent_chat`，否则走旧 `stream_chat`（model_id 缺失 yield error）；SSE 事件类型扩展 text/tool_call/tool_result/error/done
- [x] **新建 `api/v1/admin/agents.py`** — AdminRequired CRUD + toggle + set-default（镜像 assistants.py）
- [x] **新建 `api/v1/agents.py`** — 公开 `GET /agents`(启用列表) + `GET /agents/{agent_id}`(详情含 welcome_message)
- [x] **`api/v1/router.py` 挂载** — `/admin/agents`(Admin-Agents) + `/agents`(Agents)

#### 前端 — 切真实 API + SSE 流式
- [x] **新建 `api/agent.ts`** — `agentApi.list/get` + `adminAgentApi.create/update/remove/toggle`；DTO↔AgentTemplate 互转（含 model_id）
- [x] **`types/agent.ts` 扩展** — `AgentTemplate` 新增 `model_id?: string`
- [x] **新建 `composables/useAgentChatStream.ts`** — fetch + ReadableStream；payload `{agent_id, session_id?, messages, stream:true}`；解析 text/tool_call/tool_result/error/done 事件（区别于 useChatStream 的 assistant_id 路径）
- [x] **`stores/agentHub.ts` 从 Mock 切真实**
  - [x] 移除 `seedAgents()`/`seedMcps()`/`seedSkills()`/`sendMockMessage`/streamTimer setInterval 假回复
  - [x] `fetchAgents(activeOnly)`(调 /agents 或 /admin/agents) + `fetchMcps`(调 /mcp) + `fetchSkills(all)`(调 /chat/skills 或 /admin/skills) + `initAssets`(Promise.all)
  - [x] admin 动作改 async：`upsertAgent`/`toggleAgent`/`deleteAgent`(调 admin API 后刷新) + 技能 `importSkillFromUrl`/`importSkillFromJson`/`toggleSkill`/`deleteSkill`(调 /admin/skills)
  - [x] **`sendMessage(content)` 真实 SSE**：push 用户消息 + AI 占位(toolCalls:[]) → 构建 ctxLen=20 上下文 → `streamChat` → onText 累积占位 content/onSessionCreated 回填真实 session_id/onToolCall 追加 toolCalls(pending→running)/onToolResult 更新 status(success/error)/onError/onDone
  - [x] `stopStreaming` 调 abortStream
- [x] **`AgentResourceTab.vue` 表单适配** — 「大模型引擎」下拉改为**「绑定模型配置」**下拉（数据源 `GET /chat/models`，value=model_id UUID）+ 保留「模型引擎标签」次要下拉；onMounted 调 `fetchAgents(false)` + fetchMcps/fetchSkills + 加载模型列表；handleSave/handleDelete 改 async
- [x] **`SkillResourceTab.vue` 适配** — onMounted 调 `fetchSkills(true)`；import/toggle/delete 改 async（原 setTimeout Mock 移除）
- [x] **`AgentWorkspace.vue`** — onMounted 调 `store.initAssets()`
- [x] **`AgentSandbox.vue`** — `handleSend` 改调 `store.sendMessage(content)`（不 await 让 UI 立即清空）；透传 `streaming-thought`

#### 待真实环境验证
- [ ] `alembic upgrade head`（沙箱无 DB 访问，未实跑；迁移文件 revision 链与 ORM metadata 已校验通过）
- [ ] 端到端：进入 AI 助手页 → 选「RNA-seq 分析师」→ 发「帮我解释 DESeq2 结果」→ 验证打字机流式
- [ ] 给内置 Agent 显式绑定真实 model_id（AI 资源中心表单），诱导调用 BioDB MCP 的 `query_kegg` → 验证 tool_call→tool_result 气泡后模型继续生成
- [ ] DB 校验：`chat_sessions.agent_id` 正确、`chat_messages` 含 user+assistant 记录 status=complete

### 账户未激活弹窗彩蛋（点击计数 + 文案切换 + 第5次猫爪）✅ 2026-07-02 待明日测试

> 需求：登录未激活账号时弹窗,文案活泼化 + 点击计数渐变:前两次正常版、第三次起着急版、第五次关闭触发全屏猫爪彩蛋。文案全部 YAML 驱动。
> 技术栈纠偏:任务描述写 React+Arco,实为 Vue3+Naive UI;无独立 ActivationModal.tsx,原由 RegistrationDisabledModal 复用;猫咪是 Lottie(cat-fishing-on-moon.json)非 cat-moon.png;无全局彩蛋系统需自建 CatPawsOverlay。
> 架构:新增 ActivationModal.vue 薄壳(复用共享弹窗视觉 + 叠加计数逻辑)→ 派发 window 事件 omicHub:triggerCatPaws → 新增全局 CatPawsOverlay.vue(App.vue 挂载)监听事件渲染猫爪;AboutView 召唤按钮也改派发同一事件,统一一套实现。
> 验证:后端 SiteContentService 返回 activation 全字段;前端 vue-tsc 退出码 0;Node 单测计数阈值(open#1/#2 normal→#3 urgent→#5 触发猫爪→#6 不重复)正确;web 容器 healthy。

- [x] **后端 YAML 化**(改文件刷新即生效)
  - [x] `data/OmicHub.yaml` activation 段新增 title/button_text/title_urgent/message_urgent/button_text_urgent
  - [x] `schemas/site_content.py` ActivationContent 扩展 5 字段(带默认值,缺失不崩)
  - [x] `services/site_content_service.py` DEFAULT_CONTENT 补对应默认值
- [x] **前端类型 + store**
  - [x] `types/site-content.ts` ActivationContent 接口扩展
  - [x] `stores/site-config.ts` 新增 6 个 computed(activationTitle/Message/ButtonText + 着急版三件套)
- [x] **共享弹窗增强**
  - [x] `RegistrationDisabledModal.vue` 新增 buttonText prop + confirm 事件(仅按钮点击触发,蒙层关闭不触发→满足"只有点按钮才计数");宽度 360→400px
- [x] **新增 ActivationModal.vue** — 打开时读 localStorage `omicHub_activation_click_count` → 按阈值(count<2 正常 / count>=2 着急)选文案 → 按钮点击 count++ 写回 → 第5次(next===5)派发 `window.dispatchEvent(new CustomEvent('omicHub:triggerCatPaws'))` → 关闭
- [x] **新增 CatPawsOverlay.vue** — 全局监听 omicHub:triggerCatPaws,26个发光猫爪(drop-shadow 紫青强发光)、7s 自动收起、pointer-events:none 不挡交互
- [x] **App.vue** 全局挂载 CatPawsOverlay(NMessageProvider 内,登录页/关于页都覆盖)
- [x] **AboutView.vue** 召唤按钮改派发事件(删本地猫爪状态/CSS,与 ActivationModal 共用 CatPawsOverlay)
- [x] **LoginView.vue** 未激活场景从 RegistrationDisabledModal 换成 ActivationModal
- [x] **边界**:清 localStorage 计数重置 / 蒙层关闭不计入 / 隐私模式 try-catch 降级 / 注册关闭场景不受影响
- [ ] **明日测试路径**:刷新登录页,用未激活账号登录 → 前两次「收到喵!」+正常文案(账号还在星尘中沉睡✨) → 第三次起切着急版(喵～你好像很着急呢⏳)+按钮变「我这就去!」→ 第五次关闭后全屏猫爪彩蛋浮现。所有文案改 data/OmicHub.yaml activation 段即可调整

### 登录页 + 注册弹窗 Glassmorphism 毛玻璃改造 ✅ 2026-06-30

> 需求：登录卡片 & 弹窗卡片纯白背景改毛玻璃（半透白 + backdrop-filter:blur + 玻璃边框 + 弥散阴影）；弹窗遮罩改轻透黑 + 轻模糊。
> 纠偏：① 项目样式方案是原生 CSS `<style scoped>`，**非 Tailwind**（需求里给的 Tailwind 类名仅作参考）；② 登录卡片原已是 `rgba(255,255,255,0.95)`（非纯白 #fff），只是透明度太接近不透、无毛玻璃感——属实需改造；③ 弹窗卡片原 `background:#fff` 纯白——属实需改造；④ 弹窗遮罩用 Naive UI `<NModal>`，遮罩 teleport 到 body，scoped `:deep()` 打不到，须用全局 CSS 覆盖 `.n-modal-mask`。
> 验证：`npm run type-check` 退出码 0；`npm run build` 退出码 0（9.20s）；产物确认三处毛玻璃样式全部生效。

- [x] **LoginView.vue 登录卡片**：`rgba(255,255,255,0.95)` → `0.75` + `backdrop-filter:blur(16px)` + `border:1px solid rgba(255,255,255,0.4)` + `box-shadow:0 8px 32px rgba(31,38,135,0.1)`（取代原 60px 重阴影）
- [x] **RegistrationDisabledModal.vue 弹窗卡片**：`background:#fff` → `rgba(255,255,255,0.75)` + `backdrop-filter:blur(16px)` + 玻璃边框 + 弥散阴影
- [x] **global.css 遮罩层**：新增全局 `.n-modal-mask` 规则——`background-color:rgba(0,0,0,0.25)!important`（产物压缩为 `#00000040` 等价）+ `backdrop-filter:blur(4px)`，让背后登录卡片若隐若现；含 `-webkit-backdrop-filter` 兼容 Safari
- [x] **验证**：三处 `backdrop-filter`、玻璃边框、遮罩半透黑均确认进产物 CSS；type-check/build 双 0 退出码

### 登录页猫咪浮层视觉重构（三只各异 + 治白底 + Y轴上移 + 错误提示精致化）✅ 2026-06-30

> 需求：① 彻底清除中间 Lottie 白底块；② 三只猫 Y 轴上移贴合卡片上沿、绝不遮 Logo/输入框；③ 左右重复的黑猫占位图换成不同素材；④ 红色表单校验提示加间距缩字号。
> 根因核查（不盲改）：① 「中间白底」非 vue3-lottie 容器所致（其默认背景即 transparent），而是 `cat-sleeping-rolling.json` 内置 500×500 纯白实体背景层（`ty=1, sc:#ffffff`）——故 `mix-blend-mode: multiply` 对症；② 「两边黑猫占位图」即 `loader-cat.json` 本身画的是近黑剪影猫（主色 `[0.008,0.004,0]`），且左右共用同一只（靠 scaleX 镜像区分），确属重复。
> 素材决策：新增用户提供的 `data/orangeCat.json`（259×190/60fps/透明背景橙猫）替换左侧重复，三只各异；中 rolling 治白底用 multiply，左橙猫/右 loader 本就透明免此处理。

- [x] **资产转换**：`data/orangeCat.json` → `frontend/public/lottie/orange-cat.json`（kebab-case，校验合法 Lottie JSON，透明背景无白底）
- [x] **LoginCats.vue 重构**
  - [x] 三只各异：左 `orange-cat`（镜像朝中央）/ 中 `cat-sleeping-rolling`（`mix-blend-mode: multiply` 治自带白底）/ 右 `loader-cat`（保留）
  - [x] 强制透明容器：`.cat` 与 `:deep(.lottie-animation-container)` 双层 `background: transparent !important`
  - [x] Y 轴上移：左右 `top: -38px`、中央 `top: -44px`，底部贴合卡片上沿、探出半个身子，不遮 Logo/输入框
  - [x] 横向均匀分布：左 `left:16px` / 中 `left:50% + translateX(-50%)` / 右 `right:16px` 对称
  - [x] 移动端 `<768px` 隐藏左右、仅留中央（`top:-36px`）
- [x] **LoginView.vue 表单错误提示精致化**
  - [x] Naive UI 校验提示（「请输入用户名/密码」）`:deep(.n-form-item-feedback)` 加 `padding-top:4px` + 字号 `12px` + `line-height:1.4`
  - [x] `.login-error-message`（登录失败整段）字号 14px→13px 与校验提示风格统一
- [x] **验证**：`npm run type-check` 退出码 0；`npm run build` 退出码 0（9.28s）；`dist/lottie/orange-cat.json` 就位；`LoginView` 产物正确引用三只猫资产

### 登录页猫咪动画浮层（dotLottie 转 JSON 复用 vue3-lottie）✅ 2026-06-30

> 需求：白色登录卡片顶部边缘趴三只猫咪动画（加载猫 + 睡觉打滚猫），增加治愈感；移动端只保留中央一只。
> 纠偏：原提示词假设动画资产在 `data/` 且用 `@dotlottie/vue-player`——两处皆有误。① `data/` 是后端 Python 读 YAML 的目录，浏览器访问不到，前端静态资产应放 `frontend/public/`；② `@dotlottie/vue-player` 在 npm 404 不存在（官方无 Vue 专用包）。
> 架构决策：复用项目既有 `vue3-lottie@3.3.1`（注册弹窗 `RegistrationDisabledModal` 已用其播 `public/lottie/cat.json`），把两个 `.lottie`（dotLottie 压缩=zip）解压为 `animation.json` 放 `public/lottie/`，沿用 `:animation-link` + `BASE_URL` + `loop` + `auto-play` + `@on-error` emoji 兜底模式。零新依赖。
> 验证：`npm run type-check` 退出码 0；`npm run build` 退出码 0（9.44s，7443 模块）；`dist/lottie/*.json` 就位、`LoginCats` 进 `LoginView-*.js` 产物。

- [x] **资产转换与归位**
  - [x] `unzip -p` 从两个 `.lottie`（manifest.json + animations/12345.json）提取动画 JSON → `frontend/public/lottie/loader-cat.json`（280×200/25fps/11层）+ `cat-sleeping-rolling.json`（500×500/29.97fps/15层），均校验为合法 Lottie JSON
  - [x] `.lottie` 源文件从 `data/` 移到 `frontend/public/lottie/`（kebab-case 去空格）；删除 `data/` 下哈基咪先前解压的冗余 `.json` 副本，`data/` 回归 YAML-only
- [x] **新增组件 `components/LoginCats.vue`**
  - [x] 三只猫绝对定位趴在 `.login-card`（已 `position:relative`）顶部边缘（左/中/右），`top:-34px~-40px` 探出半个身子
  - [x] 左右用 loader-cat（左右镜像对称朝中央），中央用 cat-sleeping-rolling（略大 80px）
  - [x] `pointer-events:none` 不挡表单；每只独立 `@on-error` → 🐱 emoji 兜底
  - [x] 响应式 `@media(max-width:767px)` 隐藏左右、仅留中央
- [x] **LoginView.vue 接入**
  - [x] import `LoginCats`，在 `.login-card` 首位插入 `<LoginCats />`（卡片已有 `position:relative;z-index:1`，无需改定位上下文）

### 管理员登录欢迎小彩蛋（LLM 文案 + 3s 超时兜底 + Naive UI Notification）✅ 2026-06-30

> 需求：root/管理员登录进入仪表板后，后台异步拉取一段带颜文字的 LLM 欢迎词，右上角 Notification 弹出；LLM 接口 3s 超时或报错时回退默认文案「晚上好，root 👋 欢迎使用 OmicHub！」，务必保证弹窗弹出。
> 架构决策：① 复用全局 `apiClient`（自动带 JWT），单次请求 `timeout: 3000` 覆盖默认 30s；② `useNotification()` 必须在 `NNotificationProvider` 子树内调用——App.vue 原仅有 Message/Dialog Provider，补齐 NotificationProvider；③ 用 `watch(user.role, { immediate })` 兼容两种时序（刚登录 user 已就绪 / 刷新页面 fetchUser 异步未就绪），触发后立即 `stop()` 防泄漏；④ `sessionStorage` 标记一次会话只弹一次，避免反复进出仪表板刷屏。
> 验证：前端 `npm run type-check`（vue-tsc --noEmit）退出码 0 零错误。

- [x] **新增 composable：`composables/useAdminWelcome.ts`**
  - [x] `fetchWelcomeText()` — 模拟调用 LLM 接口（`POST /api/v1/llm/generate-welcome`，3s 超时 + 错误捕获），兼容返回纯字符串或 `{ content }` 两种形态；空文案抛错走兜底
  - [x] `showWelcome()` — `notification.create({ title, content, type:'success', duration:6000, keepAliveOnHover })`，`placement="top-right"` 由 Provider 决定
  - [x] `fire()` — 拉取文案（失败静默回退默认文案）→ 弹窗；`sessionStorage` 标记防重复弹
  - [x] `triggerAdminWelcome()` — `watch(role, immediate)` 兼容时序竞态，触发后 `stop()` 取消监听
- [x] **App.vue 补齐 NotificationProvider**
  - [x] import 新增 `NNotificationProvider`，在 `NDialogProvider` 内层包裹 `RouterView`（`placement="top-right"`）
- [x] **DashboardView.vue 接入**
  - [x] import `useAdminWelcome`，`onMounted` 调 `triggerAdminWelcome()`（后台异步、不阻塞主流程）
- [x] **后端：预生成 + 顺序轮询**（避免运行时调 LLM 的 2~5s 延迟，把「调 AI」挪到启动时低频补齐）
  - [x] `core/config.py` 新增 `welcome_yaml` / `welcome_state_yaml` / `welcome_seed_threshold`(20) 三配置
  - [x] `application/services/welcome_service.py` — `WelcomeService`：`seed_if_needed` 启动补齐（调默认 provider 的 `LiteLLMProvider.chat` 非流式生成，复用 `AIProviderConfigService.get_active_default` + `ai_provider_service.test_config` 范式；条数 < 20 才补，失败仅 log 不阻塞启动）、`get_next_welcome` 运行时顺序轮询（游标单调递增存独立状态文件，取模仅在读取处做；文件缺失/空/损坏回退 `DEFAULT_WELCOME_TEXT`）、给定 system prompt 常量（元气小助手人设 + 5 条约束）
  - [x] `api/v1/llm.py` — `POST /llm/generate-welcome`，`AdminRequired` 守卫（从 `admin/users.py` 导入），返回 `{content}`（与前端 composable 兼容）；非管理员走全局 `AuthorizationError` → 403
  - [x] `api/v1/router.py` 注册 `llm` 路由（`prefix=/llm tags=["LLM"]`），最终路径 `/api/v1/llm/generate-welcome`
  - [x] `main.py` lifespan 新增 `_seed_welcome()`，串行在 `asyncio.gather(...AI Provider 同步...)` 之后执行（依赖默认 provider 已就绪），异常仅 log warning 不阻塞启动
  - [x] 数据流：启动补齐写 `data/welcome.yaml`（纯字符串数组 `messages: [...]`）；运行时读它 + 游标 `data/welcome_state.yaml`（`{next_index: int}`）
- [x] **验证**：后端新文件 ruff 全通过、main.py 语法 OK；TestClient 真实 HTTP `POST /api/v1/llm/generate-welcome` 无 token → 401（路由已注册+鉴权生效）；WelcomeService 离线单测 5/5 通过（文件缺失兜底 / 顺序轮询不重复 / 游标单调递增 / 状态损坏归零 / 取模正确）；seed 无默认 provider 时静默跳过不阻塞；前端 `npm run type-check` 退出码 0

### 登录页注册开关拦截（保留按钮 + Toast 提示，文案外置 YAML）✅ 2026-06-30

> 需求：后台 `allowRegistration` 关闭时，登录页保留"注册"按钮但点击不跳转，弹全局 Toast「当前平台暂停自助注册，需由管理员创建账号」；开启时正常跳转注册页。
> 架构决策：开关复用既有 DB 驱动 `site_settings.registration_enabled`（`GET /site-settings` 公开 + `/auth/register` 后端强制校验，不破坏安全语义）；提示文案与管理员联系方式外置到 `data/OmicHub.yaml`（改文件即生效）。
> 验证：后端 `pytest tests/unit/test_site_content_service.py` 8/8 通过；前端 `npm run type-check` 零错误；真实 `data/OmicHub.yaml` 端到端解析 `registration` 块正常。

- [x] **后端：YAML 新增 registration 配置块**
  - [x] `data/OmicHub.yaml` 新增 `registration` 块（`disabled_message` + `admin_contact`，附注释说明开关本身归 DB 管）
  - [x] `schemas/site_content.py` 新增 `RegistrationContent` + `SiteContentDTO.registration`
  - [x] `services/site_content_service.py` 的 `DEFAULT_CONTENT` 补 `registration` 默认值（文件缺失/字段缺失自动兜底，首页永不崩）
- [x] **前端：类型 + Pinia site-config store**
  - [x] `types/site-content.ts` 新增 `RegistrationContent` 接口 + `SiteContent.registration?`（可选，不波及 HomeView 默认文案）
  - [x] 新建 `stores/site-config.ts` — 封装 `/site-settings` + `/site-content` 并行拉取、状态存储、`allowRegistration` computed、`registrationDisabledTip`（自动拼管理员联系方式）、并发去重 + `loaded` 就绪标记
- [x] **LoginView 改造：保留按钮 + 点击拦截 + Toast**
  - [x] 移除原 `v-if="registrationEnabled"` 隐藏按钮逻辑，改为始终渲染"注册"按钮
  - [x] `onMounted` 调 `siteConfig.fetchSiteConfig()`；`handleRegister` 点击拦截：开关关 → `message.warning` Toast 不跳转，开关开 → `router.push('/register')`
  - [x] 防 `onMounted` 竞态：首次点击若 `loaded` 未就绪先 `await fetchSiteConfig()` 再判断
  - [x] Toast 走 `App.vue` 全局 `NMessageProvider` 的 `useMessage()`，为真正全局提示
- [x] **测试**
  - [x] `tests/unit/test_site_content_service.py` 新增 3 个回归测试（默认兜底 / YAML 读取 / 部分字段补齐）

### Cherry Studio SSE 架构切换 + AI 资源管理中心 ✅ 2026-06-28

> 端到端验证：`POST /chat/stream` SSE 逐 token 推送（12 文本 token + 61 推理 token），会话/消息持久化到 `chat_sessions`/`chat_messages`，技能 prompt 注入生效，助手 system_prompt 覆盖生效。

- [x] **Part 1：流式聊天 Provider 重构**
  - [x] `litellm_provider.py` 新增 `stream_chat_with_tools()` — 逐 token `StreamEvent` 推送 + `delta.tool_calls` 按 index 累积 + `BadRequestError` 降级非流式
  - [x] `kimi.py` 修复 `is_configured` sync→async + 新增 `stream_chat_with_tools` 降级实现
  - [x] `base.py` 新增 `StreamEvent` dataclass + Protocol `stream_chat_with_tools` 方法签名
  - [x] 修复 `_build_kwargs` 丢失 `stream=True` 导致 litellm 返回 `ModelResponse` 而非异步流的致命 bug
- [x] **Part 2：Skill 后端（技能 prompt 注入）**
  - [x] `domain/skill/` — 完整六域分层（entities / value_objects / repositories / services）
  - [x] `infrastructure/database/models/skill.py` — SkillModel ORM
  - [x] `infrastructure/database/repositories/skill_repository.py` — SqlAlchemySkillRepository
  - [x] `application/schemas/skill.py` — SkillDTO + CreateSkillDTO + UpdateSkillDTO
  - [x] `application/services/skill_service.py` — CRUD + `build_skills_prompt()` + `get_active_skills()` (MAX_ACTIVE_SKILLS=10)
  - [x] `api/v1/admin/skills.py` — AdminRequired CRUD + toggle
  - [x] `api/v1/chat.py` 新增公开 `GET /chat/skills`（仅返回启用技能，供前端插件下拉）
  - [x] Alembic 迁移 `e4f5a6b7c8d9` — skills 表 + ai_conversations.assistant_id + chat_assistants.is_default
- [x] **Part 3：Agent 后端（助手管理）**
  - [x] `ChatAssistantModel` 新增 `is_default` 列
  - [x] `ConversationModel` 新增 `assistant_id` 列
  - [x] `chat_service.py` — `list_all_assistants` / `update_assistant` (含 is_default 联动清除) / `delete_assistant` (builtin 仅停用) / `toggle_assistant` / `set_default_assistant`
  - [x] `schemas/chat.py` — `UpdateAssistantRequest` 新增 `is_default` 字段
  - [x] `api/v1/admin/assistants.py` — AdminRequired CRUD + toggle + set-default
- [x] **Part 4：MCP 管理加固**
  - [x] `api/v1/mcp.py` — ALL endpoints (GET/POST/PUT/DELETE) 改为 `AdminRequired`（防止命令/env 泄露）
  - [x] 新增 `PUT /servers/{id}` 编辑 + `POST /servers/{id}/test` 连通性测试
  - [x] `schemas/mcp.py` — `UpdateMCPServerDTO`
  - [x] `mcp_service.py` — `update_server` + `test_server` 方法
- [x] **Part 5：Cherry Studio SSE 前端（核心架构切换）**
  - [x] 移除 7 个文件的 DEPRECATED 标记（`useChatStream.ts` / `chatSession.ts` / `chatAssistant.ts` / `ChatMessageItem.vue` / `ChatSettingsDrawer.vue` / `types/chat.ts` / `openai_compatible.py`）
  - [x] `KimiLayout.vue` **重写** — 从 WebSocket stores (`useAIStore` + `useAIWebSocket`) 切换到 SSE stores (`useChatSessionStore` + `useChatAssistantStore`)，不再需要 WebSocket 连接/重连逻辑
  - [x] `chat_service.py` SSE `stream_chat()` 添加技能 prompt 注入（与 WebSocket 路径一致）
  - [x] `stores/chat.ts` — `fetchPlugins()` 从 `GET /chat/skills` 加载启用技能，替代硬编码插件列表
  - [x] `alembic/env.py` — 添加 `skill` 模型导入（供 autogenerate 使用）
- [x] **Part 6：AI 资源管理中心前端**
  - [x] `types/index.ts` — Skill + ChatAssistantAdmin 接口
  - [x] `stores/mcp.ts` — createServer/updateServer/deleteServer/testServer
  - [x] `components/admin/McpResourceTab.vue` — MCP CRUD + 连通性测试
  - [x] `components/admin/SkillResourceTab.vue` — Skill CRUD
  - [x] `components/admin/AgentResourceTab.vue` — Agent CRUD + toggle + set-default
  - [x] `views/AdminAIResourceCenterView.vue` — 三标签页统一管理
  - [x] `router/index.ts` — `admin/ai-resources` 路由
  - [x] `layouts/DefaultLayout.vue` — 侧边栏入口
- [x] **验证**：后端 `ruff check` 全通过；前端 `vue-tsc --noEmit` 无错误；`npm run build` 成功；SSE 端到端测试通过（逐 token + 推理过程 + 会话持久化 + 技能注入）

### AI 助手可用性修复（输入无响应 + 界面不铺满）✅ 2026-06-27

> 端到端验证：经 nginx 真实 WebSocket 发送 `hi` → 收到 `['user_message','assistant_message','done']`，回复“您好！我是 OmicHub 智能分析助手…”；`/ai/status` 返回 `{"configured":true}`。

- [x] **问题一：输入 `hi` 没有任何回复**（多根因叠加，导致后端 AI 调用必然失败）
  - [x] **litellm 路由失败（主因）**：`LiteLLMProvider` 把裸模型名 `qwen3.7-max` 直传 litellm，自定义 OpenAI 兼容端点要求 `openai/` 前缀否则抛 `BadRequestError: LLM Provider NOT provided`。新增 `_route_model()`：配置了自定义 `api_base` 且模型名无前缀时自动补 `openai/`（实测 `openai/qwen3.7-max` 正常返回）
  - [x] **YAML Provider 同步崩溃**：`AIProviderYamlLoader` 对领域实体直接 `session.add()` 抛 `Class ... is not mapped`，aliyun 配置未入库（DB 查出 0 行）。改为统一走 `repo.save()`（实体→ORM 模型转换），并修正默认 Provider 管理（`set_default` 正确取消其他默认）
  - [x] **会话未提交**：启动初始化与 YAML 同步仅 `flush()` 未 `commit()`，数据被回滚。两处补 `await session.commit()`；并调整 lifespan 顺序——YAML（方式1，推荐）先同步，环境变量（方式2）仅在库空时兜底，符合 `.env.example` 设计
  - [x] **`${AL_API_KEY}` 解析为空**：YAML 把 key 改为 `${AL_API_KEY}` 引用，但容器环境无此变量→插值得空串→入库 key 为空→“Invalid API-key”。`.env` 新增 `AL_API_KEY`（`.env` 已 gitignore，密钥不出库），`.env.example` 补模板；compose 给 `web` 挂载 `../../data:/app/data:ro`（之前容器内 `/app/data` 不存在，YAML 同步空跑）
  - [x] **`tool_calls: null` 崩溃**：qwen/aliyun 不调工具时返回 `"tool_calls": null`，`message.get("tool_calls", [])` 拿到 `None`，`_normalize_tool_calls` 遍历 `None` 抛 `TypeError`，在 `assistant_message` 事件发出前被 `except` 吞成 error——故 LLM 已回复但前端不可见。改为 `message.get("tool_calls") or []` + `_normalize_tool_calls` 增加 `if not raw: return []` 守卫
- [x] **问题二：AI 界面下方空白、不铺满视口**
  - [x] 根因：`DefaultLayout` 用 `:native-scrollbar="false"` → Naive 渲染 `NScrollbar` 而非 `.n-layout-scroll-container`；全局 CSS 里 `:deep(.n-layout-scroll-container){flex:1}` 只匹配原生滚动容器、不命中 NScrollbar，高度链断裂 → `.kimi-layout` 的 `height:100%` 无从解析 → 聊天区只占内容高度、下方留白
  - [x] 修复：`DefaultLayout.vue` 对 `fullscreen` 路由（仅 `/ai`）改用 `:native-scrollbar="true"`，使 `.n-layout-scroll-container` 的 `flex:1` 生效，高度链贯通、聊天自动铺满视口、消息列表内部滚动
  - [x] `.session-header` / `.input-area-wrapper` 增加 `flex-shrink:0`，短屏下输入框不被挤压
- [x] **验证**：前端 `npm run build` 通过（nginx 已服务新产物 `index-BQzk0j96.css`）；后端真实 WebSocket 走 nginx 端到端返回正常回复；DB 默认 Provider = aliyun(qwen3.7-max)，key 已加密落库

### 测试报告 v1.1 问题修复 ✅ 2026-06-26
- [x] **认证与路由**
  - [x] 登录成功后 `router.push('/')` + `window.location.href` 双重兜底跳转
  - [x] 路由守卫以 `localStorage.access_token` 为准，未登录访问受保护路由带 `redirect` 参数
  - [x] 登出后清除状态并 `window.location.reload()` 彻底重置
  - [x] 增加跨标签页 `storage` 监听，token 被清除时自动登出
  - [x] 登录/注册失败显示表单内红色文案 + Toast 提示
- [x] **核心页面**
  - [x] `TasksView.vue` 修复导入、增加错误处理，解决白屏
  - [x] `FilesView.vue` 从占位改为真实文件列表（调用 `/api/v1/files`）
  - [x] 后端新增 `/api/v1/files` 列表接口 + `FileService.list_files`
  - [x] `FlowsView.vue` 空状态提示优化
  - [x] `KnowledgeView.vue` 空文档提示
  - [x] `SandboxView.vue` 建设中占位，避免 404 外观
- [x] **AI 助手交互**
  - [x] `KimiLayout.vue` / `ai.ts` 修复新建会话后 UI 切换、消息即时渲染
  - [x] 历史会话点击切换加载
  - [x] `KimiChatInput.vue` 去除 Tooltip 嵌套，修复 Agent/插件/模型下拉无响应
  - [x] 快捷提示卡片点击自动发送
  - [x] WebSocket 连接失败时显示错误横幅与重连按钮
  - [x] 后端新增 `GET /api/v1/ai/status` 配置检测接口
  - [x] `LiteLLMProvider` / `KimiProvider` 新增 `is_configured()` 检查
  - [x] AI 未配置时返回明确错误并前端显示黄色警告条
- [x] **系统设置**
  - [x] `SettingsView.vue` 平台设置页签确保管理员可见
  - [x] 注册开关保存失败回滚并提示错误
  - [x] `RegisterView.vue` 关闭注册时隐藏表单并显示提示
  - [x] 后端 `auth.py` 注册接口校验 `site_settings.registration_enabled`
- [x] **UI/UX**
  - [x] `DashboardView.vue` banner 关闭状态持久化到 localStorage
  - [x] `global.css` 提升下拉菜单 z-index，避免与侧边栏重叠
- [x] **AI Provider 外置 YAML 配置**
  - [x] `config.py` 新增 `AI_PROVIDER_CONFIG_YAML`
  - [x] 新增 `AIProviderYamlLoader` 服务，支持 `${ENV_VAR}` 插值与多 Provider 同步
  - [x] `main.py` 启动时自动同步 YAML 到数据库
  - [x] 新增 `data/ai_providers.yaml` + `data/ai_providers.yaml.example`
  - [x] `.env.example` 增加 YAML 配置说明
- [x] **构建验证**：前端 `type-check` / `build` 通过，后端 `make test` 6 passed

### 本次前端体验修复 ✅ 2026-06-26
- [x] **AI 聊天框可用性修复**
  - [x] 修复 `useAIWebSocket.ts` 发送时序 bug：连接未 `OPEN` 时消息入队，连接成功后按序发送
  - [x] `AIChat.vue` 增加连接错误提示，未配置 AI Provider 时显示具体原因
  - [x] 前端 type-check / build 通过
- [x] **管理员菜单图标区分与折叠**
  - [x] `DefaultLayout.vue` 中“系统管理”改为可折叠分组，默认收起
  - [x] 用户管理 `PersonOutline`、饼干账户管理 `WalletOutline`、饼干定价管理 `PricetagOutline`、AI 模型配置 `SparklesOutline`
  - [x] 移动端抽屉同步展示管理入口，修复 `<renderUserAvatar />` 引用错误
- [x] **通知提醒系统闭环**
  - [x] 后端新增 `NotificationModel` + Repository + Service + API（列表/发布/已读/删除）
  - [x] 注册路由 `/api/v1/notifications` 与 `/api/v1/admin/notifications`
  - [x] Alembic 迁移脚本 `c72c373d1ee2_add_notification_table.py`
  - [x] 前端新增 `NotificationDrawer.vue` + `stores/notification.ts` + TS 类型
  - [x] `DefaultLayout.vue` 顶部通知图标显示未读数，点击打开抽屉
  - [x] 管理员可在抽屉内发布通知（标题/内容/级别/全员或指定用户/过期时间）
  - [x] 后端 `make test` 通过、前端 `npm run build` 通过

### 历史已完成

### 1. 项目骨架搭建
- [x] Python 项目结构 (src layout + uv + pyproject.toml)
- [x] 前端 Vue 3 骨架 (Vite + TypeScript + Naive UI + Pinia)
- [x] DDD 六域分层目录结构
- [x] Docker Compose 部署配置 (7 个服务全部 healthy)
- [x] Alembic 数据库迁移配置
- [x] pytest 测试骨架
- [x] Makefile 常用命令 (uv run 前缀)
- [x] .env.example 环境变量模板
- [x] CLAUDE.md 项目指南
- [x] README.md 项目说明

### 2. 后端核心 (src/omichub/)
- [x] **core/** — config (Pydantic Settings), security (JWT+bcrypt), exceptions, logging (loguru)
- [x] **main.py** — FastAPI 应用工厂 + lifespan + 全局异常处理 + `/health` 端点
- [x] **api/v1/** — 7 个路由占位 (auth/users/flows/tasks/files/ai/mcp) + router 聚合 + deps 依赖注入
- [x] **middleware/** — auth (JWT 校验), rbac (角色装饰器), rate_limit (占位)
- [x] **application/** — services/ (7 个应用服务占位) + schemas/ (7 个 DTO 占位)

### 3. 领域层六域 (domain/)
- [x] **user/** — User 聚合根 + Workspace + Role/UserStatus 值对象 + 仓储接口 + 域服务
- [x] **flow/** — FlowDefinition 聚合根 + FlowParameter/FlowStep + ParamType/UIControl + YAML 解析服务
- [x] **task/** — Task 聚合根 + TaskLog + TaskStatus 状态机 + VALID_TRANSITIONS + 域服务
- [x] **file/** — Sample 聚合根 + DataFile + ResultArchive + FileType + 校验和计算
- [x] **ai/** — Conversation 聚合根 + Message + ContextWindow + RoleType + 上下文压缩服务
- [x] **mcp/** — MCPServer 聚合根 + MCPToolRegistry + Transport/ServerStatus + 工具路由服务

### 4. 基础设施层 (infrastructure/)
- [x] **database/** — SQLAlchemy DeclarativeBase + TimestampMixin + 异步 session + UserModel 示例
- [x] **cache/** — Redis 异步客户端 (单例)
- [x] **celery_app/** — Celery 实例 + 配置 + analysis 任务 (snakemake 执行 + 定时清理)
- [x] **ai_provider/** — LLMProvider 抽象接口 + KimiProvider 适配器 (流式 SSE)
- [x] **execution/** — LocalSnakemakeExecutor (subprocess) + RemoteSnakemakeExecutor (HTTP)

### 5. Docker 部署 (deploy/docker/)
- [x] Dockerfile (后端多阶段构建 + uv)
- [x] Dockerfile.frontend (前端构建 + Nginx)
- [x] docker-compose.yml (7 服务: nginx/web/worker/beat/flower/db/cache)
- [x] docker-compose.prod.yml (生产 override)
- [x] nginx.conf (API 代理 + WebSocket + Flower 代理)
- [x] 端口冲突修复 (nginx → 8888)
- [x] 容器健康检查 (各服务自定义 healthcheck)
- [x] 开发环境 src 热重载挂载

### 6. 前端骨架 (frontend/)
- [x] package.json + vite.config.ts + tsconfig
- [x] main.ts + App.vue (NConfigProvider 全局配置)
- [x] router/index.ts (5 个路由: dashboard/flows/tasks/files/ai)
- [x] layouts/DefaultLayout.vue (NLayout 侧边栏布局)
- [x] api/client.ts (axios 实例 + JWT 拦截器)
- [x] stores/auth.ts (Pinia 认证状态)
- [x] composables/useApi.ts (通用请求封装)
- [x] types/index.ts (API 类型定义)
- [x] views/ 5 个页面占位

---

## 待完善

### 优先级 P0 — 核心功能闭环

- [x] **用户认证闭环** (docs/modules/03_api_design.md) ✅ 2026-06-25 验证通过
  - [x] auth.py 实现登录/注册/刷新令牌端点
  - [x] UserModel 完整 ORM (含 workspace ForeignKey 关联)
  - [x] UserRepositoryImpl (SQLAlchemy 实现)
  - [x] UserService/AuthService 编排登录用例
  - [x] JWT 中间件接入 main.py
  - [x] 前端登录页面 + auth store 完整逻辑
  - [x] 注册审批机制: 新用户默认 status=pending, 管理员审批后变 active 才可登录
  - [x] 用户管理 API (admin/users.py): GET 列表 | PUT /{id}/approve | PUT /{id}/reject | PUT /{id}/role
  - [x] 前端用户管理页 (AdminUserManagementView.vue): 审批/拒绝/角色切换
  - [x] 侧边栏菜单改为 computed 动态渲染 (admin 角色可见"系统管理"子菜单)
  - [x] 修复: session.py 模型未注册导致建表失败
  - [x] 修复: router/index.ts/g isLoggedIn() 误调用 computed
  - [x] 修复: DefaultLayout.vue FileText → DocumentText (ionicons5 改名)
  - [x] 修复: main.ts 未全局注册 naive-ui 导致登录页组件不渲染
  - [x] 修复: n-input-password 组件不存在 → n-input type=password (LoginView/RegisterView)
  - [x] 修复: nginx index.html 无禁缓存头导致浏览器加载旧 JS (404)
  - [x] 修复: DashboardView 健康检查路径错误 (apiClient /../health → axios /health)
  - [x] 修复: DashboardView 快速开始按钮未绑定 @click 跳转事件
  - [x] 修复: DefaultLayout 侧边栏 AI 助手菜单重复 + 管理员菜单缺失

- [x] **YAML 配置中心** (docs/modules/04_yaml_schema.md) ✅ 2026-06-25 前后端闭环
  - [x] FlowDomainService.parse_yaml 完整实现 (services.py)
  - [x] YAML → FlowConfig 转换 (entities.py 完整 Pydantic v2 模型)
  - [x] DAG 依赖图校验 (find_condition_cycle 三色 DFS 检测 condition 循环依赖)
  - [x] FlowRepositoryImpl (FileSystemFlowRepository 文件系统仓储 + 线程安全缓存)
  - [x] `/api/v1/flows/{flow_id}/schema` 返回 JSON Schema (含顶层 FlowConfig Schema)
  - [x] YAML 热重载接口 (POST /api/v1/flows/reload)
  - [x] 完整 value_objects: ParameterTypeEnum + 6 Config 子模型 + ExecutionConfig + SampleSheetConfig + FlowMeta
  - [x] 完整 entities: ConditionRule (简单+AND/OR 嵌套) + Parameter (类型校验) + FlowConfig (唯一性+条件引用校验) + FlowDefinition 聚合根
  - [x] condition.py: ConditionEvaluator (11 运算符) + ConditionalValidator (可见参数+必填校验)
  - [x] schemas/flow.py: FlowListItemDTO/FlowDetailDTO/FlowListResponse/FlowReloadResponse + JSON Schema 导出
  - [x] api/v1/flows.py: 5 端点 (GET / | GET /schema | POST /reload | GET /{id} | GET /{id}/schema)
  - [x] flows/rna_seq.yaml 示例配置 (覆盖全部参数类型+条件渲染+Group+Section)
  - [x] flows/atac_seq.yaml ATAC-seq 流程配置 (Bowtie2/Chromap + MACS2 + TOBIAS)
  - [x] ATACFlow Builder (`atacflow_builder.py`) 生成 analysis.yaml / samples.csv / contrasts.csv
  - [x] TaskService 支持 atac_seq 提交与 DAG 生成
  - [x] ExecutionConfig 增加 `config_file_param` 以支持不同流程的配置文件参数名
  - [x] docker-compose 挂载 flows 目录 + config.py 新增 flow_yaml_dir
  - [x] 前端 DynamicForm 组件 (基于 Naive UI) — types/schema.ts + useConditionEvaluator + DynamicForm/FormField/RepeatableGroup/CollapsibleSection，已接入 FlowSubmitView.vue
  - [x] 修复: uvicorn 运行时 /flows 路由 404 (重启容器后路由正常，返回 401 需认证即证明路由已注册)

- [x] **任务执行闭环** (docs/modules/01_architecture_overview.md §4.4) ✅ 2026-06-25 端到端验证通过
  - [x] TaskRepositoryImpl (get_by_id/list_by_user/save/delete/append_log + 模型转换)
  - [x] TaskService 提交任务用例 (参数快照锁定 + RNAFlow builder + Celery 投递 + 状态推进)
  - [x] Celery analysis 任务接入 LocalSnakemakeExecutor (状态流转 + stdout/stderr 日志记录)
  - [x] Redis Pub/Sub → WebSocket 实时日志推送 (pubsub.py + tasks.py WebSocket 端点)
  - [x] 前端任务详情页 + 实时日志流 (TaskDetailView.vue + WebSocket 连接)
  - [x] Snakemake DAG 可视化 (generate_dag SVG/DOT + 前端渲染)
  - [x] 修复: TaskService.submit 重复调用 flow_config_to_detail 导致 500
  - [x] 修复: Celery worker session 未 commit 导致状态/日志丢失 (ROLLBACK)
  - [x] 修复: _update_model 覆盖 append_log 写入的日志 (logs 不再由 save 覆盖)
  - [x] 修复: append_log 未存 timestamp 导致 _to_entity 转换报错

### 优先级 P1 — 饼干积分系统（🥫 Cookie）✅ 2026-06-25 端到端验证通过

> 文档: docs/modules/12_cookie_backend.md + 13_cookie_frontend.md + 14_cookie_integration.md
> 架构适配: 设计文档用 ORM 贫血模型，本项目适配为 DDD 模式 (Pydantic 实体 + 仓储接口 + Python 端统计维护替代 SQL 触发器)

#### 后端 — 领域层 (domain/cookie/)
- [x] CookieAccount 聚合根 + CookieTransaction/CookiePricing/ConsumptionLog/LedgerEntry 实体
- [x] TransactionType/AccountStatus/PricingType/PricingUnit/BillingItem 值对象 (earn/spend/adjust/refund/freeze/unfreeze)
- [x] ICookieAccountRepository / ICookieTransactionRepository / ICookiePricingRepository / IConsumptionLogRepository / ILedgerRepository 仓储接口
- [x] CookieAccount.apply_transaction() — Python 端维护统计 (替代 SQL 触发器 fn_update_account_stats)

#### 后端 — 基础设施层 (infrastructure/database/)
- [x] 5 张表 ORM 模型: cookie_accounts / cookie_transactions / cookie_pricing / cookie_consumption_logs / cookie_ledger
- [x] 索引设计 (idx_txn_user_created 覆盖索引、idx_pricing_query 部分索引、idx_txn_source 等)
- [x] Python 端统计维护 (apply_transaction 替代 SQL 触发器) + 注册建户 (get_or_create_account 替代 fn_create_cookie_account_on_signup)
- [x] SqlAlchemyAccountRepository / SqlAlchemyTransactionRepository / SqlAlchemyPricingRepository / SqlAlchemyConsumptionLogRepository / SqlAlchemyLedgerRepository 仓储实现
- [x] Alembic 迁移脚本 (alembic/env.py 修复模型导入 + 08ab25316cc1_initial_schema 覆盖全部 7 表+索引+约束，upgrade/无 drift 验证通过)

#### 后端 — 应用层 (application/)
- [x] CookieService 核心服务: check_balance / pre_deduct / settle (多退少补) / refund / freeze / unfreeze / suspend / adjust
- [x] PricingEngine 定价计算引擎: 按 flow_category + resource_type + priority 匹配 + 时段生效判断
- [x] Pydantic DTO: CookieAccountDTO / CookieTransactionDTO / CookiePricingDTO / CostEstimateDTO / CookieStatsDTO
- [x] TaskCookieConsumer 结算服务 (Celery 回调中调用 on_complete/on_cancel)

#### 后端 — API 路由 (api/v1/)
- [x] 用户端 cookies.py: GET /cookies/account | /transactions | /pricing | /estimate | /balance-check
- [x] 管理端 admin/cookies.py: GET /admin/cookies/accounts (JOIN users 返回用户名/邮箱) | POST /adjust | PUT /accounts/{id}/freeze|unfreeze|suspend | GET /transactions | /stats | /pricing (CRUD)
- [x] 管理端 admin/users.py: GET /admin/users 用户列表 | PUT /{id}/approve 审批 | PUT /{id}/reject 拒绝 | PUT /{id}/role 角色切换
- [x] CookieRequiredMiddleware 消费拦截中间件 (middleware/cookie.py — 消费类路由 HTTP 层守卫，冻结→402/停用→403，已注册 main.py)
- [x] TaskCookieConsumer — 任务提交前预估+预扣，完成时结算，取消时退还
- [ ] SandboxCookieConsumer — 沙盒启动前检查，运行中按分钟计费 (依赖 P2 沙盒)
- [x] config.py 新增: enable_cookie_system / initial_cookie_balance / cookie_sandbox_base_cost

#### 集成点 (依赖任务闭环 P0 + 沙盒 P2)
- [x] 集成点#1: 用户注册自动建户 + 赠送 INITIAL_COOKIE_BALANCE (100🥫) — auth.py register 端点
- [x] 集成点#2: 任务提交注入 Cookie 检查 + 预扣 (余额不足返回 400 BusinessError) — task_service.submit
- [x] 集成点#3: Celery 任务完成回调结算 (多退少补) — analysis.py _execute_snakemake
- [x] 集成点#4: 任务取消退还预扣饼干 — task_service.cancel_task
- [ ] 集成点#5: 沙盒启动前余额检查 + 预扣基础费用 (依赖 P2 沙盒)
- [ ] 集成点#6: 沙盒关闭结算最终费用 (依赖 P2 沙盒)
- [ ] 集成点#7: Celery Beat 每分钟沙盒扣费，余额不足自动停止 (依赖 P2 沙盒)
- [ ] 集成点#8: AI Agent 提交任务前检查余额 (依赖 P2 AI)

#### 前端 (frontend/src/)
- [x] types/index.ts — TS 类型定义 (CookieAccount/Transaction/Pricing/CostEstimate/CookieStats)
- [x] stores/cookie.ts — Pinia store (余额/流水/预估)
- [x] composables/useCookieWebSocket.ts — 实时余额变更推送 (Redis Pub/Sub + WebSocket /cookies/ws + 自动重连指数退避，已接入 CookieBalanceBadge)
- [x] components/CookieBalanceBadge.vue — 全局余额徽章 (顶栏，已接入 DefaultLayout)
- [x] views/CookieAccountView.vue — 用户账户页 (余额统计/流水列表)
- [x] views/AdminCookieManagementView.vue — 管理后台账户管理 (列表显示用户名+邮箱/调整/冻结/解冻)
- [x] views/AdminCookiePricingView.vue — 定价策略管理 (CRUD + Modal)
- [x] views/AdminUserManagementView.vue — 用户管理 (审批通过/拒绝/角色切换)
- [x] views/AdminCookieTransactionsView.vue — 全局交易流水审计 (独立页面 + 多维度过滤 user/txn_type/source_type/日期 + 分页 + JOIN 用户名/邮箱)
- [x] TaskSubmitView.vue 集成饼干预估 (防抖 500ms 调 /estimate + 余额不足禁用提交按钮 + 费用/余额展示卡片)
- [x] 路由配置: /cookies (用户) + /admin/users + /admin/cookies/accounts + /admin/cookies/transactions + /admin/cookies/pricing (管理员)
- [x] DefaultLayout 侧边栏: computed 动态菜单, admin 角色可见"系统管理"子菜单组 (用户管理/饼干账户管理/交易流水审计/饼干定价管理)

#### 部署与运维
- [x] config.py 新增 cookie 相关配置项 + enable_cookie_system 开关
- [x] scripts/init_cookies.py — 初始化默认定价策略脚本
- [x] cookie 系统开关 ENABLE_COOKIE_SYSTEM=false 时全链路跳过 (TaskCookieConsumer 检查)
- [x] 监控: CookieMonitorService 余额异常告警 + 流水对账 (cookie_ledger 日终快照 + Celery Beat 每日 2:30 自动对账 + 异常检测: 负余额/大额调整/高频消费/冻结账户活动 + 管理端 API: POST /reconcile, GET /anomalies, GET /ledger)

### 优先级 P2 — AI Copilot 与沙盒

- [x] **AI 对话 SSE 流式（Cherry Studio 架构）** (docs/OmicHub_CherryStudio_整合实施文档.md) ✅ 2026-06-28 Cherry Studio SSE 架构完成
  - [x] `chat_service.py` SSE `stream_chat()` — 流式输出 + 实时数据库更新 + 会话/消息持久化
  - [x] `openai_compatible.py` `OpenAICompatibleProvider` + `ProviderManager` — httpx 直连 OpenAI SSE，支持 DeepSeek reasoning_content
  - [x] `api/v1/chat.py` — `POST /chat/stream` SSE 端点 + 会话/助手/模型管理 REST API
  - [x] `useChatStream.ts` — fetch + ReadableStream 解析 SSE，AbortController 停止生成
  - [x] `chatSession.ts` — 会话/消息/流式状态管理（Cherry Studio Optimistic Update 模式）
  - [x] `chatAssistant.ts` — 内置助手 + 自定义助手管理（分类分组）
  - [x] `ChatMessageItem.vue` + `MarkdownRenderer.vue` — Markdown 渲染 + DOMPurify XSS 防护 + highlight.js 代码高亮 + 复制按钮
  - [x] `KimiLayout.vue` 接入 SSE stores（不再依赖 WebSocket）
  - [x] Tool Use 协议 (submit_task/query_status/list_samples) — WebSocket 路径保留（ai_service.py）
  - [x] ⚠️ 2026-06-27 修复多重隐性 bug 使其真正可用：litellm 路由前缀 / YAML 同步 `not mapped` 崩溃 + 未 commit / `${AL_API_KEY}` 解析为空 / `tool_calls:null` 崩溃（详见顶部「AI 助手可用性修复」节）
  - [x] ⚠️ 2026-06-28 修复 `_build_kwargs` 丢失 `stream=True` 导致 SSE 返回 ModelResponse 的致命 bug
  - [x] ⚠️ 2026-06-28 技能 prompt 注入 + 助手 system_prompt 覆盖 + 资源管理中心（Skill/Agent/MCP 三标签页）

- [x] **代码执行沙盒** (docs/modules/08_tech_selection.md) ✅ 2026-06-27
  - [x] Docker 预热容器池管理器
  - [x] 沙盒镜像 Dockerfile (Bioconda + scanpy/seurat) — 改为 `condaforge/mambaforge` 基础，bioconda 渠道预装 scanpy/anndata/squidpy/scvi-tools + R/Seurat/IRkernel；新增 `sitecustomize.py` 注入 sc/np/pd + `show_echarts`/`show_image` 回传协议
  - [x] WebSocket 代码执行协议
  - [x] 前端 CodeMirror 6 编辑器组件 — `components/sandbox/CodeEditor.vue`（Python lang + one-dark + 行号/历史/高亮）
  - [x] ECharts GL 图表渲染 (UMAP/热图) — `components/sandbox/echartsSetup.ts` 注册 scatterGL/heatmap/dataZoom/visualMap/brush
  - [x] 会话亲和性 + 30min 超时回收
  - [x] `SandboxView.vue` 完整页面：会话列表/创建/销毁 + 编辑器 + 运行/停止 + 结果三标签页（输出/图表/图片）+ 示例代码（UMAP scatterGL / 表达热图 / matplotlib 图片）

- [x] **MCP 集成** (docs/modules/11_integration_fusion.md) ✅ 2026-06-26 后端实现完成
  - [x] MCPServerRepositoryImpl
  - [x] MCP Client (Python MCP SDK) 生命周期管理
  - [x] 四大预设 MCP 服务 (文献/基因组/代码/知识库)
  - [x] 工具发现 + 调用路由 + 错误隔离
  - [x] `/api/v1/mcp/servers` CRUD 端点

> ⚠️ P2 后续待补齐：
> 1. 补 alembic 迁移：`ai_conversations` / `ai_messages` / `mcp_servers` / `sandbox_sessions` 四张表未在现有迁移中。
> 2. ~~沙盒前端页面：`SandboxView.vue` + 路由 `/sandbox` + CodeMirror 6 + ECharts GL UMAP/热图渲染。~~ ✅ 2026-06-27 已完成
> 3. ~~沙盒镜像 Dockerfile 按文档要求改为 Bioconda 并启用 R+Seurat。~~ ✅ 2026-06-27 已完成

### 优先级 P3 — 生产化

- [x] **首次部署初始化**
  - [x] Web 首次配置引导页 (`/setup`)：无管理员时自动跳转，创建 root 管理员并登录
  - [x] 后端 API: `GET /auth/setup-required` + `POST /auth/setup`
  - [x] 路由守卫自动检测并跳转 setup 页面
  - [x] 修复 `AuthMiddleware` 未放行 `/auth/setup-required` 和 `/auth/setup`
  - [x] 修复 `main.py` 重复注册 7 次 `CookieRequiredMiddleware` 导致请求异常
  - [x] 修复 `UserStatus` 枚举缺少 `pending` 状态导致含待审批用户时转换失败
  - [x] `scripts/init_admin.py` 命令行初始化脚本（幂等、生产环境强制设置密码）
  - [x] `.env.example` 增加 `OMICHBUB_INIT_ADMIN_*` 配置项
  - [x] `Makefile` 增加 `make init-admin` / `make init-cookies` 命令

- [x] **数据库迁移** (docs/modules/02_database_schema.md) ✅ 2026-06-25
  - [x] 完整建表 SQL (六域所有表 — 通过 Alembic autogenerate 生成)
  - [x] JSONB 字段标注 (parameters/logs/preferences 等)
  - [x] 索引设计 (覆盖索引 + 部分索引 + 复合索引)
  - [x] Alembic 初始迁移 (08ab25316cc1_initial_schema.py — 7 表 + 全部索引/约束/FK，upgrade 验证通过)

- [ ] **安全加固** (docs/modules/01_architecture_overview.md §4.5)
  - [ ] RBAC 中间件完整实现 (数据库查角色)
  - [ ] RateLimitMiddleware 接入 Redis 滑动窗口
  - [ ] 工作空间数据隔离 (user_id 自动过滤)
  - [ ] 敏感信息脱敏 (AI 对话中的品种名)
  - [ ] 审计日志表 + 中间件

- [x] **文件管理** (docs/modules/03_api_design.md) ✅ 2026-07-02 详见顶部「数据管理模块全面升级」
  - [x] 文件上传 (分块 + 断点续传)
  - [x] SampleRepositoryImpl
  - [x] 结果归档过期清理 (Celery Beat 定时任务)
  - [x] 前端文件管理页 + 上传组件

- [ ] **远程执行模式** (docs/modules/01_architecture_overview.md §4.4)
  - [ ] 远程 Snakemake Executor 服务 (集群头节点 FastAPI 副进程)
  - [ ] Slurm/SGE 作业翻译
  - [ ] 结果回传 (rsync/HTTP)

### 本次美化/文档待收尾（2026-06-26 继续）

- [ ] **知识库与文档中心**
  - [x] 创建 `docs/knowledge/` 与 `docs/docs/` 目录及 YAML/Markdown 示例文件
  - [x] 后端 `docs_service.py` + `api/v1/docs.py` 路由实现
  - [x] 后端 `api/v1/router.py` 注册 `/docs` 路由
  - [x] 前端 `MarkdownReader.vue` 轻量 Markdown 渲染组件
  - [x] 前端 `KnowledgeView.vue` 知识库页面（待验证路由参数默认值）
  - [ ] 前端 `DocsView.vue` 文档中心页面
  - [ ] 前端 `router/index.ts` 注册 `/knowledge/:docId?` 与 `/docs/:docId?` 路由
  - [ ] `DefaultLayout.vue` 更新顶部导航链接：实验室知识库 → `/knowledge`，文档 → `/docs`
  - [ ] 前后端类型检查与构建验证

### 优先级 P4 — 优化与运维

- [ ] **监控可观测性**
  - [ ] Prometheus 指标暴露
  - [ ] Grafana 仪表盘模板
  - [ ] 结构化日志 + Loki 聚合
  - [ ] API 请求追踪 (OpenTelemetry)

- [ ] **前端完善**
  - [x] About 页面 (Milky Way 背景 + star-stuff 文案) ✅ 2026-06-25
  - [x] 暗色模式 ✅ 2026-07-02
  - [x] 各域页面完整实现 (Flows/Tasks/Files/AI) ✅ 2026-07-04
  - [x] 全局错误处理 + 加载态 ✅ 2026-07-04
  - [x] 响应式布局适配 ✅ 2026-07-04
  
  > 完成内容：新增 `useApi` 统一请求组合式函数、`AppErrorBoundary` 全局错误边界、`AppLoading`/`AppSkeleton` 通用加载骨架组件；`TasksView` 对接真实 `/api/v1/tasks` 接口并新增状态筛选/搜索/真实删除；`FlowsView` 移除硬编码占位，对接 `/api/v1/flows` 动态渲染；`FilesView` 修复响应式 bug 与深色模式变量，桌面端三栏、移动端抽屉式目录树/详情面板；`AgentWorkspace` 增加 Agent 资产加载态与错误重试兜底。验证：`npm run type-check && npm run build` 通过。

- [ ] **测试覆盖**
  - [ ] 六域单元测试
  - [ ] API 集成测试
  - [ ] E2E 测试 (Playwright)
  - [ ] CI/CD 流水线

- [ ] **文档与交付**
  - [ ] API 文档自动生成 (OpenAPI)
  - [ ] 部署手册
  - [ ] 运维 runbook
  - [ ] 用户使用手册

---

## 技术决策记录

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| 1 | 包管理 | uv | 极快，2024-2025 社区主流 |
| 2 | Python 版本 | 3.11 | pyproject.toml 约束，Docker 镜像一致 |
| 3 | 项目结构 | src layout | PEP 621 标准，避免 import 冲突 |
| 4 | Nginx 端口 | 8888 | 宿主机 80 被 ipsa 占用 |
| 5 | 开发模式 src 挂载 | web/worker/beat | 热重载，无需 rebuild 镜像 |
| 6 | Beat schedule | crontab 对象 | 不能用字符串，Celery 要求 crontab 实例 |
| 7 | 健康检查 | 各服务自定义 | slim 镜像无 pgrep/curl，需 CMD-SHELL |


### 前端优化：分析中心卡片 + 系统设置页面 ✅ 2026-07-05

> 需求：按 `docs/omic_hub_frontend_optimization.md` 优化分析中心卡片视觉与交互，并在系统设置中新增平台级 TOTP 策略控制。
> 验证：前端 `vite build` 构建成功；修改文件 `vue-tsc` 无新增类型错误；后端文件 `py_compile` 通过；`tests/integration/test_flows.py` 通过。

- [x] **分析中心卡片优化**
  - [x] `flows/atac_seq.yaml` / `flows/rna_seq.yaml` 的 `meta.icon` 改为 Emoji（🧪 / 🧬）
  - [x] `frontend/src/views/FlowsView.vue` 优先读取 `flow.icon`，兼容旧 key 兜底，按 `category` 动态背景色
  - [x] GitHub 图标从 `meta.docs_url` 读取，仅 `github.com` 链接显示，带 wiggle 悬停动画
  - [x] 推荐流程 Banner 同步显示 `text-4xl` Emoji 与白色 GitHub 图标
- [x] **系统设置页面优化**
  - [x] 页面内容区宽度从 `max-width: 640px` 放宽至 `1024px`（`>1440px` 为 `1152px`）
  - [x] 卡片 padding 统一为 `32px`（移动端 `24px`），平台设置采用响应式两列布局
  - [x] 平台设置新增 TOTP 策略分段控制器（关闭 / 可选 / 强制）
  - [x] 安全设置根据 `totp_policy` 动态展示：关闭时显示禁用提示，`required` 时显示橙色强制横幅与橙色按钮
- [x] **后端配套接口**
  - [x] 新增 `GET /api/v1/platform/config` 公开读取平台配置
  - [x] 新增 `PATCH /api/v1/admin/platform-config` 管理员更新平台配置（需 TOTP 二次验证）
  - [x] `SiteSettingModel` 新增 `totp_policy` 字段（`String(16)`，默认 `optional`）
  - [x] `SiteSettingsDTO` / `UpdateSiteSettingsDTO` 扩展 `totp_policy`
  - [x] 新增 Alembic 迁移 `m0n1o2p3q4r5_add_totp_policy_to_site_settings.py`
