# 2026-07-08 变更记录

## 今日完成

### 前端入口调整

- 移除主导航中的独立「代码沙盒」入口。
- 保留 `/sandbox` 兼容路由，并重定向到 `/tools/terminal`。
- 将云端沙盒终端作为统一执行环境入口，避免「代码沙盒」和「云端终端」功能重复。

### Makefile 文档

- 新增 Makefile 详细说明文档，记录常用命令、开发/部署/测试入口和使用边界。
- 将 Makefile 的使用说明从口头约定整理为可查阅文档，便于后续部署和协作。

### 日志架构优化

- 使用 loguru 的 rotation、retention、compression 能力限制应用日志体积。
- 为 Celery 单任务日志增加轮转、保留期和压缩策略。
- 为数据库任务日志增加单条 message 截断和最大条数限制，避免长任务日志撑大数据库字段。
- 增加 Docker stdout 日志大小限制，并补充 Nginx/Snakemake 的 logrotate 兜底策略。
- 更新 `LOG_ARCHITECTURE.md`，记录统一日志目录、容量保护、排障方式和本次架构更新。

### 参考数据库离线构建工具

- 新增 `scripts/pyproject.toml`，支持通过 `pip install -e ./scripts` 单独安装 `omichubtools`。
- 新增 `omichubtools` CLI，当前包含：
  - `omichubtools version`
  - `omichubtools refdb build`
  - `omichubtools build-reference-database` 兼容别名
- 复用 gpse 工具模块的设计思路，加入 logo、日志、版本和配置加载工具。
- 清理 `scripts/` 中不再需要的旧脚本，仅保留 Makefile 或部署仍引用的脚本。
- 使用 `rich-argparse` 美化 CLI help 输出，并保留缺依赖时的标准库 formatter 回退。

### FA/GFF/GO/KO/KEGG 离线构建能力

- `omichubtools refdb build` 支持从 FA、GFF、GO、KO、KEGG 原始文件生成：
  - `database.sqlite`
  - FASTA `.fai`
  - `database_manifest.json`
  - `jbrowse_assembly_snippet.yaml`
  - `build_report.json`
- SQLite 当前包含 FASTA 序列索引、GFF feature、gene、transcript、exon、GO、KO、KEGG 等表。
- 构建脚本保持离线执行，不挂到 Web API、Celery Worker 或前端点击链路，避免给平台服务造成压力。

### GO/KEGG 注释补全增强

- 新增 `--go-terms` 参数。
- `--go-terms` 支持 GO term TSV/CSV，也支持 `go-basic.obo`。
- 当 `--go` 只有 `gene_id/go_id` 两列时，可离线补全 `term` 和 `namespace`。
- 新增 `go_terms` SQLite 表，用于保存 GO ID、term、namespace、definition、source。
- 增强 `--kegg` 参数，支持三类输入：
  - `gene_id + kegg_id`
  - `gene_id + pathway_id`
  - `ko_id + pathway_id`
- 当 `kegg_id` 是 `Kxxxxx` 时写入 KO 注释；当存在 KO 到 pathway 映射时自动展开成 gene 到 pathway。

### 数据库模块现状排查

- 确认当前真实运行入口仍是 `tool_configs/jbrowse/jbrowse_config.yaml`。
- JBrowse 运行只强依赖 `fasta + fai`，GFF 需要作为 preset track 配置后才能显示。
- 当前 `/database` 页面仍读取前端 mock 数据，尚未接入真实后端数据库 API。
- 当前后端没有 `/api/database/*`，也没有服务消费 `database.sqlite`。
- 已明确后续方向：用 `omichubtools` 生成每个物种/版本的 SQLite，再新增后端数据库 API 和前端联通。

## 已验证

- `uv run ruff check scripts/omichubtools`
- `python -m compileall scripts/omichubtools`
- `PYTHONPATH=scripts python -m omichubtools --no-logo refdb build --help`
- `python -m pip install -e ./scripts --dry-run`
- 使用临时 FA/GFF/GO/GO-terms/KO/KEGG 样例构建 SQLite，验证：
  - GO term 补全正常
  - `gene_id/kegg_id` 写入 KO 正常
  - `KO -> pathway` 自动展开正常

## 当前边界

- 平台现在只注册和读取构建好的文件路径，不在运行时做 FA/GFF/GO/KO/KEGG 转换。
- `/database` 页面仍是 mock，需要后续改为真实 API。
- `database.sqlite` 已能生成，但平台后端还没有正式查询服务。

# 2026-07-10 变更记录

## 今日完成

### 节日弹窗全屏沉浸式背景动画

- 新增 `frontend/src/components/FestivalBackground.vue` 独立背景动画组件。
- 实现三层核心效果：
  - 暗流涌动的径向渐变背景（中心极暗酒红 #2A0A0A 过渡到纯黑）+ 14s 缓慢呼吸缩放。
  - 26 个重度模糊、琥珀金/琉璃金色调的星火粒子，自下而上漂浮并随机闪烁。
  - 卡片正后方暗金色光晕，80px 模糊 + 6s 缓动呼吸动画。
- 组件固定 `z-index: -1` / `pointer-events: none`，并兼容 `prefers-reduced-motion`。

### 按节日特点定制背景动画

- 春节 / 国庆：红灯笼浮动 + 酒红底。
- 元宵节：水面灯影涟漪 + 暖橙底。
- 端午 / 立春：竹叶飘落 + 墨绿底。
- 七夕：鹊桥弧线 + 流星划过 + 深紫底。
- 中秋 / 冬至：月晕 + 水面涟漪 + 藏蓝底。
- 圣诞 / 元旦：雪花飘落 + 藏蓝底。
- 重阳 / 秋分 / 夏至：枫叶/落叶飘落 + 秋褐底。
- 情人节：爱心上升 + 玫红底。
- 程序员节：绿色代码雨 + 纯黑矩阵底。
- 周年庆：同心轨道旋转 + 星点绕行 + 深紫蓝底。

### 背景动画层级与清晰度修复

- 修复 `z-index: -1` 导致动画被毛玻璃 backdrop 压暗/模糊的问题：
  - `FestivalBackground.vue` 提升为 `z-index: 2`。
  - `FestivalEffect.vue` Canvas 层提升为 `z-index: 3`。
  - 保持 `festival-backdrop` 在 `z-index: 1`，先模糊页面再渲染动画。
- 降低过度模糊：
  - Canvas 层从 `blur(12px)` 降至 `blur(2px)`。
  - 节日专属图形（灯笼、雪花、枫叶、爱心、轨道等）从 1~2px 模糊降至 0~0.5px。
  - 保留光晕/星火粒子的柔和模糊作为氛围。

### 数据管理目录树计数修复

- 修复 `DirectoryTree.vue` 中系统目录（如 `raw_data`、`temp`、`workspace`）显示文件计数徽章的问题。
- 现在仅用户自建目录显示计数，系统目录保持名称整洁。

## 已验证

- `npm run type-check` 通过。
- `npm run build` 通过。

# 2026-07-11 变更记录

## 今日完成

### 实验室知识库快速入门文档重写

- 重写 `docs/knowledge/getting-started.md`，将 Carl Sagan 的引言置于文首。
- 补充 OmicHub 平台理念：让数据回归科学、过程可复现、知识沉淀与共享。
- 详细说明 10 个核心模块的平台理念与使用方法：
  数据管理、分析流程中心、任务中心、AI 聊天助手、实验室知识库、
  云端沙盒终端、饼干积分、富集分析与可视化、JBrowse 2、MCP 工具扩展。
- 增加首次使用四步上手、常见问题排查与获取帮助指引。

### 知识库文件同步机制

- 新增 `scripts/sync_knowledge_from_files.py`：
  - 将 `docs/knowledge/*.md` 按 `meta.yaml` 同步到数据库。
  - 支持 `--auto-admin` 自动选择管理员作为同步者。
  - 使用 Rich 输出彩色同步结果表格，并关闭 SQL echo 日志。
- `Makefile` 新增 `sync-knowledge` 目标，`docker-reload` 执行后自动同步知识库。
- `deploy/docker/docker-compose.yml` 挂载 `scripts` 目录到 web 容器，确保容器内可执行同步脚本。
- 说明：知识库以数据库为权威源，网页端编辑过的文档会入库；直接修改 .md 后需执行同步网页才生效。

### 知识库前端 UI 优化

- 左侧侧边栏：
  - 「新建文档」改为全宽主题蓝 CTA 按钮（无边框、圆角、白字）。
  - 「待审核」改为纯文本 + 图标的菜单项样式。
  - 目录树菜单项统一增加 hover 浅灰背景、圆角与间距。
- 底部讨论区：
  - 增加浅灰分割线与顶部间距，与正文区隔开。
  - 输入框改为 100% 宽度的多行文本域，带浅灰边框、8px 圆角、内边距与占位符。
  - 「发送」按钮移至输入框右下角，使用 Flex 靠右对齐。

### Git 提交整理

- 将工作区变更按功能拆分为 3 个 commit：
  - `feat(knowledge)`：实验室知识库重构与同步机制。
  - `feat(festival)`：节日彩蛋系统与全屏沉浸式背景动画。
  - `feat(workflow-monitor)`：Snakemake 流程监控模块（含旧 `tools/` 目录清理）。
- 剩余未提交：`pipelines/EBIDownload` 子模块仍有本地修改，需单独处理。

## 已验证

- `python -m py_compile scripts/sync_knowledge_from_files.py`
- `cd frontend && npm run type-check`
- `make docker-reload` 可正常完成并自动同步知识库。

## 当前边界

- `pipelines/EBIDownload` 子模块变更未提交。
- 知识库网页端目前缺少文档删除按钮，后续可补充。

# 2026-07-20 变更记录

## 今日完成

### 前端设计规范文档补全（ARCHITECTURE_DESIN/fontend.md）

- 在原有 §1–§12 基础上，新增 §13–§30 共 18 个章节，覆盖此前缺失的前端工程维度：
  - §13 数据可视化规范（ECharts/Plotly 引擎选择、图表配色令牌、Processor 纯函数模式）
  - §14 实时通信与 WebSocket（连接生命周期、心跳重连、组合式函数契约）
  - §15 API 层与数据请求（目录命名、HTTP 错误码→UI 行为对照、数据加载模式）
  - §16 状态管理（Store vs 本地状态边界、Setup Store 规范、组件通信）
  - §17 文件操作（分片上传、下载进度、生信文件格式校验、文件预览）
  - §18 AI 对话与流式界面（流式渲染、输入区交互、工具调用卡片）
  - §19 终端与代码沙箱（等宽字体、DOM 行数限制、Pyodide、沙箱隔离）
  - §20 代码组织与命名（目录结构、命名规则表、组件拆分原则）
  - §21 性能预算与优化（包体积上限、虚拟滚动、网络缓存策略）
  - §22 测试策略（Vitest + Playwright 金字塔、Mock 策略）
  - §23 安全规范（XSS 防护、JWT 处理、输入校验、依赖审计）
  - §24 国际化准备（当前中文规则 + 未来 i18n 迁移预留）
  - §25 浏览器兼容与运行环境（支持矩阵、最小视口）
  - §26 错误边界与全局异常（全局异常 UI、chunk 加载失败、日志监控）
  - §27 路由与权限控制（懒加载、导航守卫、权限 UI）
  - §28 通知与消息系统（消息层级、通知中心、去重规则）
  - §29 打印与导出（print 样式、图表/表格/PDF 导出）
  - §30 长任务与工作流监控（任务状态→UI 映射、进度反馈分级）

### 前端设计规范审计与修复

基于补全后的设计规范，对 `frontend/src` 全量代码进行合规审计，发现并修复 5 类问题：

#### 1. XSS 修复（6 处 v-html 加 DOMPurify）

- `views/TaskDetailView.vue`：SVG DAG 内容使用 `DOMPurify.sanitize(raw, { USE_PROFILES: { svg: true } })`。
- `views/BioTools/SeqManipulatorView.vue`：`colorizeProtein` 输出经 DOMPurify 过滤，防止用户输入序列注入 HTML。
- `components/MarkdownReader.vue`：手写 Markdown 解析器输出增加 DOMPurify 最终过滤。
- `components/studio/StudioArtifactsPanel.vue`：Markdown 预览 `markdown.render()` 输出经 DOMPurify 过滤。
- `components/studio/StudioCodeCard.vue`：diff2html 输出经 DOMPurify 过滤。
- `components/ai-chat/KimiMessageItem.vue`：AI 生成内容 `md.render()` 输出经 DOMPurify 过滤。

#### 2. 硬编码色值替换为语义变量（5 个文件）

- `views/LoginView.vue`：~22 处 hex → `var(--neutral-text-*)`, `var(--arco-primary)`, `var(--arco-danger)` 等。
- `views/RegisterView.vue`：同上模式，移除冗余 dark 覆盖块。
- `views/AboutView.vue`：整页硬编码暗色 → 语义变量（保留装饰性渐变）。
- `components/terminal/ImageSelector.vue`：~14 处 hex → 语义变量。
- `components/blast/BlastSequenceAlignment.vue`：~14 处 hex → 语义变量（含 inline style）。

#### 3. Timer 泄漏修复（16 个文件）

- 为所有未清理的 `setTimeout` 补充 `onUnmounted` / `onBeforeUnmount` 清理：
  FlowSubmitView、StudioCodeCard、RegistrationDisabledModal、JBrowseLinkGenerator、
  LogoAnimation、AgentSandbox、MarkdownRenderer、MessageActionBar、KimiChatInput、
  KimiMessageItem、StudioWorkspaceEditor、StudioArtifactsPanel、LoginView、
  PrimerForgeView、ManhattanPlotView、JBrowseViewer。

#### 4. !important 覆盖移除（8 个文件，~35 处）

- `components/terminal/ResourceSettings.vue`：NSlider `--n-*` 变量改为 wrapper class 继承。
- `components/AnnouncementBanner.vue`：移除 10 处 `!important`。
- `views/ReportsView.vue`：移除 5 处，改用父类 + `:deep()` 提升优先级。
- `views/DashboardView.vue`：移除 3 处。
- `views/HomeView.vue`：改用 `--n-color` / `--n-text-color` 变量。
- `views/SettingsView.vue`：移除 6 处，改用 `--n-*` 变量。
- `views/FlowsView.vue`：移除 4 处，改用 `--n-*` 变量。
- `layouts/DefaultLayout.vue`：移除 7 处（保留 1 处 teleported popover z-index 并注释说明）。

#### 5. PageHeader 复用（6 个页面）

- `views/BioTools/TerminalView.vue`：自定义 `.page-header` → `<PageHeader>`。
- `views/BioTools/JBrowseViewer.vue`：自定义 `.toolbar` → `<PageHeader>`。
- `views/BioTools/YamlGenomeBrowser.vue`：同上。
- `views/ReferenceGenomeDetailView.vue`：自定义 `.page-toolbar` + `.detail-hero` → `<PageHeader>`。
- `views/DownloadsView.vue`：Tailwind h1+p → `<PageHeader>`。
- `views/SharedStudioView.vue`：自定义 `<header>` → `<PageHeader>`。

## 已验证

- `cd frontend && npm run type-check`（vue-tsc --noEmit）通过。
- `cd frontend && npm run build`（vue-tsc -b && vite build）通过，exit code 0。

## 当前边界

- 仍有部分文件存在硬编码色值（PrimerForgeView、TaskDetailView、StudioView、DataTypesWidget、ReportCardMinimal 等），属 MEDIUM 优先级，后续迭代处理。
- `!important` 在 LoginView、RegisterView、KnowledgeView 等认证/特殊页面仍有残留，因涉及 Naive UI 深层主题覆盖，需配合 themeOverrides 整体迁移。
- StudioView 作为全屏工具保留专用 topbar，未强制替换为 PageHeader。
- 前端测试基础设施（Vitest、Playwright）尚未搭建，§22 测试策略为规划性内容。

# 2026-07-22 变更记录

## 今日完成

### 仪表板 OmicStudio 用量卡片

- 修复「近 30 天」活跃度看不全的问题：移除 `daily.slice(-14)` 截断，趋势图完整展示所选周期（7/30 天）。
- 活跃度列表改为固定高度（约 7 行）+ 框内上下滚动，避免 30 天数据把页面撑高。
- Token 数值默认以 K 为单位，新增 K / M 小按钮切换（Token 汇总与每日活跃度同步生效）。
- Token 汇总新增饼干折算行（≈ X 🥫 · 10 🥫/1K tokens），数据来自 `/stats/studio` 新增的 `cookie` 字段。

### AI 对话饼干计费（10 🥫 = 1K tokens）

- 新增配置 `ai_token_cookie_rate`（默认 10.0，🥫/1K tokens）。
- `CookieService.spend_ai_tokens`：按比率扣减饼干，余额不足时按可用余额封顶（不为负），写入 `source_type="ai_chat"` 交易流水并实时推送余额。
- `ChatService`：`stream_chat` / `stream_agent_chat` 入口增加饼干准入闸门，余额为 0 时返回「饼干余额不足」错误事件，饼干耗尽即无法使用 AI 助手；`_apply_usage_to_session` 在累加会话 token 后同步扣减饼干。

### 用量统计页（饼干账户）

- 新增「AI Token 用量」卡片：转换比例横幅（10 🥫 = 1K tokens，饼干耗尽不可用 AI 助手）、近 30 天汇总（Token / 折合饼干 / 消息数 / 会话数）、逐条使用记录表（时间 / 会话 / Token 消耗 / 饼干扣减），同样支持 K / M 切换。
- 新增后端接口 `GET /api/v1/stats/ai-usage`（`StatsService.user_ai_token_usage`），聚合带 usage 的 assistant 消息并按比率折算饼干。

## 已验证

- `python3 -m pytest tests/unit/test_stats_service.py tests/unit/test_cookie_ai_billing.py -q`：15 passed（含 7 条新增计费/聚合用例）。
- `ruff check` 改动文件全部通过。
- `cd frontend && npm run type-check`（vue-tsc --noEmit）通过。

# 2026-07-23 变更记录

## 今日完成

### 仪表板任务提交趋势图形态切换

- 为「任务提交趋势」新增「柱状 / 面积」切换，默认保留任务柱状图与样本折线图，面积模式将两个系列切换为双 Y 轴平滑面积图。
- 图形态切换只更新前端 ECharts option，不重新请求趋势接口；「近 7 天 / 近 30 天」仍按原逻辑重新加载数据。
- 补充窄屏工具栏布局、键盘焦点、`aria-pressed` 和 `prefers-reduced-motion` 适配。

### 平台统一胶囊分段切换器

- 新增全局 `.omichub-segmented-toggle` 样式，统一 Token K/M、柱状/面积等同层级二选一偏好控件。
- 统一使用语义边框、浅色轨道、品牌主色选中态和 `--text-on-primary` 前景色，避免页面局部样式重复和漂移。
- 将仪表板 OmicStudio 用量卡片和饼干账户 Token K/M 控件迁移到共享样式，并补充 `aria-pressed` 状态。
- 在 `ARCHITECTURE_DESIN/fontend.md` 中记录适用边界、视觉参数、无障碍要求、响应式规则及趋势图实现约定，作为 OmicHub 平台统一规范。

## 已验证

- `cd frontend && npm run type-check`（vue-tsc --noEmit）通过。
- `cd frontend && npx vite build` 通过。
- `git diff --check` 通过。

# 2026-08-04 变更记录

## 今日完成

### Agent 记忆系统全面核查（前置调研）

- 以 4 个并行子 Agent + 运行时实测核查平台记忆系统，确认：
  - 短期记忆 = 前端滑窗 20 条 + 后端 200K-token 应急压缩，运行正常。
  - 长期记忆 `agent_memories` 表 schema 完整（含 vector(1024) + HNSW 索引），但**开关全关、0 行数据**，自动摘要唯一触发点是删除会话。
  - 跨 agent 索引为 scope 双轨制：profile/preference 全局共享，project/summary 按 agent 隔离。
- 产出 mem0 适配性评估：与平台技术栈（Python 3.11 / pgvector 0.8.6 / LiteLLM）全面契合，且记忆表零数据、无迁移成本。

### mem0 记忆引擎替换（核心变更，已灰度上线）

- 新增 `src/omichub/infrastructure/memory/mem0_engine.py`：mem0 v2.0.15 引擎封装（进程级单例），
  pgvector 独立 collection `mem0_memories`，不触碰旧 `agent_memories` 表。
- `AgentMemoryService` 八个 public 方法按 `mem0_engine_enabled` 分流，**对外契约零改动**
  （4 个 LLM 工具、用户/管理员 API、前端、prompt 注入格式全部保留）；开关关闭即回滚旧链路。
- 跨 agent 语义保持双轨：共享记忆不带 agent_id，私有记忆 agent_id 存于 metadata，可见性全部客户端过滤。
- 写入前语义查重（阈值 0.95）复刻旧引擎"最新值覆盖"去重行为。
- 新增配置组 `mem0_*`（core/config.py）：引擎开关、抽取模型、embedder 三选一
  （fastembed/ollama/openai）、collection、沉淀频率、检索/查重阈值等。
- `.env` 与 `.env.example` 同步补充完整配置示例与注释。

### 记忆沉淀时机修复（不再只有删会话才沉淀）

- 新增 Celery 任务 `settle_session_memory`：mem0 引擎开启时，把会话最近 30 条消息
  交给 mem0 做 LLM 事实抽取 + 实体合并，写入 `scope=summary` 记忆。
- 触发点扩展为两处：会话消息每累计 `MEM0_SETTLE_EVERY_N_MESSAGES`（默认 20）条异步入库一次；
  删除会话时仍触发（原 `summarize_session` 旧链路保留为回滚位）。

### 结构性小修

- 子 Agent 工具剥离名单补齐 `omichub_update_memory`、`omichub_forget_memory`
  （原先子任务可改写/删除主用户记忆；`omichub_search_memory` 只读予以保留）。
- 记忆注入失败日志 warning→error（主路径 + handoff 路径），不再静默无感。
- `omichub_search_memory` 工具 limit 上限 5→10（底层本就支持）。
- 管理员删除用户时，mem0 引擎开启则同步清理 mem0 存储中的该用户记忆。

### Embedding 方案落地（fastembed 进程内 ONNX）

- 云端 embedding 探针全部出局（阿里云 token-plan 无 embedding 模型、火山 coding key 401）；
  ollama 容器镜像（~4GB）所有 registry 拉取卡死，改走 fastembed。
- 选用 `intfloat/multilingual-e5-large`（1024 维、多语含中文、MIT），
  模型缓存落 `/data/omichub/mem0-cache`（web/worker 共享卷，已预置），
  下载源 `HF_ENDPOINT=https://hf-mirror.com`。
- 按实测分数分布定阈值：检索下限 0.87、查重阈值 0.95
  （e5 无前缀实测：无关≈0.80、跨话题≈0.85、同领域相关≥0.90、同义≥0.96）。

### 部署基础设施修复

- **db 镜像漂移陷阱**：基础 compose 的 db 原为 `postgres:14-alpine`，任何不带 pgvector
  overlay 的 `docker compose up -d` 都会把 db 重建回无 pgvector 镜像（全部向量操作报
  `$libdir/vector`）。已将基础 compose db 镜像改为 `pgvector/pgvector:pg14`。
- pyproject 新增依赖：`mem0ai==2.0.15`、`psycopg[binary,pool]>=3.1`（worker 镜像缺 libpq，
  binary wheel 自带）、`ollama>=0.6.2`、`fastembed>=0.8.0`，镜像重建后依赖固化。
- compose 预留备用 `ollama-embed` 服务（profile `embed-ollama` 隔离，不影响全栈启动），
  模型卷 `omichub_embed` 已预置 bge-m3。

### 记忆引擎管理开关、用户可见性与加密落盘（同日二期）

- **管理员平台设置新增「Agent 长期记忆」运行时开关**：
  - `site_settings.agent_memory_enabled`（新增列 + alembic 迁移 `k5l6m7n8o9p0`，默认 true）；
    管理端「设置 → 平台设置」可视化切换（免 TOTP 功能开关），非敏感字段名单已收录。
  - 三态门控：env `MEM0_ENGINE_ENABLED` 为部署级能力闸门，管理端开关为运行时开关，
    同时为真才启用；管理员关闭时——召回/注入返回空、列表为空、写入明确报
    「平台记忆功能当前已被管理员关闭」、settle 沉淀任务返回 `disabled_by_admin`。
  - 消费点全覆盖：AgentMemoryService 八个入口、chat_service 两处沉淀触发、
    celery settle 任务。
- **用户侧记忆可见性增强**（个人中心「我的记忆」）：
  - 新增 scope 筛选（全部/用户画像/偏好/项目/对话沉淀）；
  - 记忆行展示归属 Agent 友好名（10 个平台 Agent 映射）、来源会话标记（悬停显示会话 ID）、
    更新时间；空态与提示文案改为说明"记忆来自与 AI 助手的对话，自动沉淀"。
- **记忆加密落盘**（`/data/omichub/omichub_data/_mem0/`）：
  - 向量库边界 Fernet 加密：mem0 payload.data 落库即密文，读取解密；mem0 内部
    抽取/去重/实体合并仍见明文（补丁对 insert/search/update/get/list 全覆盖，
    含 pgvector list 的嵌套返回结构与 ndarray→list 适配）。
  - 密钥管理：`MEM0_ENCRYPTION_KEY` 优先；留空自动生成并持久化
    `_mem0/master.key`（0600，web/worker 共享卷）。密钥丢失 = 存量记忆不可恢复。
  - history 审计库（sqlite）从 /tmp 迁入 `_mem0/history/history.db`，
    old/new memory 字段同样写前加密。
  - 解密失败视为历史明文数据原样放行（换钥/迁移兼容）。

### 智能体能力抽屉展示实际应答 Agent（路由会话修复）

- 问题：统一入口（router）会话里，「查看该智能体能力」抽屉按 `session.agent_id`
  取入口 router（无 skill），而实际应答的是路由徽标记录的专家（如通用助手，挂 5 个 skill），
  导致"已挂载的 skill 在能力抽屉里显示 0 个"。
- 修复：agentHub store 新增 `effectiveAgent`（最后一条带 `routed_agent` 徽标的消息
  所指专家优先，回落到会话归属 Agent）；`AgentCapabilityDrawer` 改用它。
  抽屉的 MCP/技能/系统设定现在与实际应答 Agent 一致。
- `vue-tsc` / 构建通过，nginx 已重载。

### 个人中心记忆卡片前置与增强

- 「我的记忆」卡片从页面第 5 位上移至「最近任务」之后（第 2 位），换 ✨ SparklesOutline
  图标，标题旁新增「N 条」计数徽章，首屏即可看到记忆沉淀情况。
- 空态文案明确说明沉淀时机与前置条件：「与 AI 助手对话满约 20 条消息后自动沉淀
  （需要平台 AI 模型密钥有效）」——密钥失效期间不会产出新记忆。

### AI 错误态增加「联系管理员」提示

- 聊天错误卡片（`KimiMessageItem.vue` 错误态）在错误描述与操作按钮之间新增一行引导：
  - 密钥/配置/授权类错误（正则识别 API Key/密钥/过期/401/403 等）→
    「此问题通常由模型密钥或配置失效引起，用户侧无法自行修复，请联系管理员解决。」
  - 其他错误 → 「若重试或切换模型后仍失败，请联系管理员解决。」
- `npm run type-check` / `npm run build` 通过，nginx 已重载。
- 排查截图问题时发现：当日 11:06 起 providers.yaml 四个 Provider（qwen/deepseek/doubao/gpt-5.5）
  密钥均已失效（Invalid API-key），全平台 AI 聊天与 mem0 抽取均不可用，
  需管理员更新 `.env` 中 AL_API_KEY/ARK_API_KEY/COOL_API_KEY 并重启 web（启动时自动重同步入库）。

### audit_logs 缺表修复（历史遗留）

- 现象：web 日志持续出现 `审计日志写入失败: relation "audit_logs" does not exist`
  （ORM 模型早已存在但从未建迁移，与 kb_chunks 同类问题），HTTP 写操作审计全丢，
  个人中心「审计记录」始终为空。
- 修复：新增 alembic 迁移 `l6m7n8o9p0q1_add_audit_logs.py`，按 `AuditLogModel` 建表
  （12 列 + 6 个索引，detail 默认 `'{}'::json`、created_at 默认 now()），已应用。
- 验证：登录探针 POST /api/v1/auth/login 与真实前端 refresh 请求均成功落审计表，
  写入失败告警归零。

### 文档

- 新增 `docs/26.8.4/OmicHub_mem0记忆引擎替换实施方案.md`：架构与设计决策（D1-D8）、
  PoC 验收记录、对外契约附录、分阶段施工计划、灰度部署记录与三大隐形坑、回滚方案。

## 已验证

- PoC（`scripts/poc/mem0_poc.py`）：5 项验收全过，同义事实写入 3 次经 mem0 实体合并仅存 1 条。
- 适配层冒烟（`scripts/poc/mem0_adapter_smoke.py`）：15/15 通过（查重转 update、跨 agent 隔离、
  L1+L2 注入、update/forget/clear）。
- 生产容器金丝雀：web 端 7/7 通过；worker 端 settle 对真实会话（18 条消息）抽出 4 条
  高质量 summary 记忆，scope/agent 归属正确，验证数据已清理。
- 引擎初始化、`mem0_memories` 建表、HNSW 检索在 omichub-db 实测正常。
- 二期验证：加密落盘 SQL 直查为 Fernet 密文（`gAAAAA…`）且明文零泄露；应用侧读回明文正常；
  管理端开关 6 项联动全过（ON 保存/密文/读回，OFF 后 search/list/注入为空、写入被拒、恢复）；
  `master.key`（0600）与 `history/history.db` 确认落盘 `/data/omichub/omichub_data/_mem0/`；
  alembic 迁移 `k5l6m7n8o9p0` 应用成功；前端 `npm run type-check` / `npm run build` 通过。

## 当前边界

- mem0 抽取存在已知边界（均已在引擎层处理）：内容含 `<`/`>` 会破坏抽取（已前置净化为
  "小于/大于"）；传原生 agent_id + assistant 消息会误入 mem0 agent-extraction 分支
  （settle 路径已改为仅经 metadata 传递 agent_id）；fastembed 返回 ndarray 已打转换补丁。
- `use_count`/`confidence` 在 mem0 轨不再维护（返回兼容值），管理端"含归档"审计在 mem0 轨
  仅含活跃记忆（mem0 删除即物理删除）。
- 回滚方式：`.env` 改 `MEM0_ENGINE_ENABLED=false` 并重建 web/worker 容器（restart 不重读
  env_file）。旧 `agent_memories` 链路与全部旧配置项完整保留。
- 阈值基于 e5-large 单模型实测，未来更换 embedder 需重新标定检索/查重阈值。
- 加密密钥治理：`_mem0/master.key` 是当前唯一密钥来源，须纳入备份；多副本部署应显式配置
  同一 `MEM0_ENCRYPTION_KEY`。`client.history()` 接口返回的 old/new memory 为密文，
  平台暂未提供解密展示。
- 管理端开关关闭期间，历史记忆仅隐藏不清除；重新开启即恢复可见。
