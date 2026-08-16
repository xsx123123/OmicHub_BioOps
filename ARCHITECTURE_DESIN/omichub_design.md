# OmicHub 模块设计与接入指南

> **用途**：本文件是 OmicHub 新增、扩展或重构模块时的项目级设计基线。新增模块先按本文档完成设计，再开始编码；模块级设计文档可在此基础上补充领域细节。
>
> **最后更新**：2026-07-29  
> **适用范围**：平台功能、管理功能、生信工具、分析流程、数据资源、AI/Agent、异步任务与外部服务集成。

---

## 1. 设计原则

| 原则 | 要求 |
|---|---|
| 分层清晰 | HTTP/API、应用服务、领域模型、基础设施各司其职；路由层不承载业务编排。 |
| 前后端契约优先 | 先定义请求/响应 DTO、错误语义与权限，再实现页面；前端不得依赖未声明的隐式字段。 |
| 渐进式接入 | 优先复用现有布局、认证、配置、任务、上传与通知能力；不为单一模块引入平行基础设施。 |
| 配置外置 | 可运营、可调整的内容放入 `tool_configs/` 或系统配置；密钥与环境差异放入环境变量。 |
| 默认安全 | 任何用户数据、文件、任务、管理接口都必须经过认证、授权和所属关系校验。 |
| 可验证 | 每个模块至少有可执行的后端/前端验证命令，并在设计文档中写明验收标准。 |

---

## 2. 当前项目架构基线

```text
Browser (Vue 3 + TypeScript + Naive UI)
  ├─ frontend/src/views/          页面与路由入口
  ├─ frontend/src/components/     可复用展示组件
  ├─ frontend/src/api/            类型化 HTTP 调用
  ├─ frontend/src/types/          前端 DTO / 领域类型
  ├─ frontend/src/stores/         跨页面状态（Pinia）
  └─ frontend/src/composables/    可复用状态与副作用
             │
             ▼
FastAPI (/api/v1)
  ├─ src/omichub/api/v1/          路由与依赖注入
  ├─ src/omichub/application/     DTO、应用服务、用例编排
  ├─ src/omichub/domain/          复杂业务规则与领域对象
  ├─ src/omichub/infrastructure/  数据库、缓存、外部服务、执行器
  └─ src/omichub/tools/           相对独立的生信工具模块
             │
             ▼
PostgreSQL / Redis / Celery / 文件存储 / Snakemake / Docker / 外部 API
```

### 2.1 先选择模块类型

| 模块类型 | 适用场景 | 后端建议位置 | 前端建议位置 |
|---|---|---|---|
| 平台业务模块 | 用户、文件、任务、报告、通知、站点配置等 | `api/v1/` + `application/` + 必要的 `domain/`、`infrastructure/` | `views/`、`components/<module>/`、`api/`、`types/` |
| 管理模块 | 管理员维护资源、配置、账户、定价等 | 复用对应业务服务；新增管理路由 | `views/Admin*` 或 `components/admin/` |
| 生信工具 | 独立工具页或工具后端能力 | `src/omichub/tools/<tool_key>/` | `views/BioTools/`、`components/bio-tools/` |
| 工作流/分析流程 | 提交、调度、监控与报告 | `domain/flow`、`domain/task`、`application/services`、执行基础设施 | `views/Flow*`、`components/task/`、`components/workflow-monitor/` |
| 外部集成 | AI Provider、MCP、下载源、第三方数据库等 | `infrastructure/<provider>/`，由应用服务封装 | 独立 `api/`、`types/`；页面按所属业务模块放置 |

> 生信工具必须同时遵守 `tool_configs/tools_design.md`；本文档解决全项目通用约定，不替代工具页面的紧凑布局和注册表规范。

### 2.2 生信工具强制基线（与 `tools_design.md` 同步）

新增生信工具除遵守本指南外，必须满足以下已落地的专项约束；完整字段、样式和示例以
`tool_configs/tools_design.md` 为唯一详细来源。

1. **注册与分组**：在 `tool_configs/tools_setting.yaml` 登记 `key`、`route`、`icon`、`gradient`、`group`、`enabled`、`order`、`config_dir`；`group` 必须为 `sequence`、`visualization`、`genome`、`function`、`environment` 之一。该字段须沿 YAML → 后端 Pydantic 配置 → `ToolItemDTO` → `GET /api/v1/tools` → 前端 `ToolItem` 完整透传。
2. **工具箱展示**：工具箱按分组顺序和组内 `order` 升序展示，禁用工具不计数；未知分组归入“其他工具”。分组默认展开，折叠状态使用 `localStorage` 键 `omicHub_tools_group_collapsed` 记忆，卡片必须继续复用 `components/bio-tools/ToolCard.vue`。
3. **图形绘制工具**：火山图、散点图、热图、箱线图、柱/折线图等必须形成“导入/粘贴/示例数据 → 自动与手动列映射 → 校验与计算 → 交互式绘图 → 结果表 → PNG/SVG 导出”的闭环。参数至少覆盖数据映射、核心计算、颜色、坐标轴/标题、标签、样式与导出尺寸/DPI。
4. **分组配色（强制）**：最终图形只要有分类分组、系列、处理组、样本组或显著性类别，必须同时使用稳定的离散颜色、图例和 hover 分组名称。2–6 组默认 `color_discrete_friendly`，7 组使用 `colors_discrete_friendly_long`，8–12 组使用 `colors_discrete_friendly_long_2`；超过色板容量必须提示或筛选，禁止静默重复颜色。连续数值使用 `colors_continuous_bluepinkyellow` 等连续色板并显示 colorbar，不能作为分类色板。
5. **图表质量**：处理逻辑放入 `utils/<tool>Processor.ts` 的纯函数；处理 NA/NaN/Infinity/极端值，支持亮暗主题、可解释 hover、受控重绘和页面卸载销毁。PNG 导出至少支持 300/600/1000 DPI 或等效倍率，SVG 用于矢量导出。

---

## 3. 新模块设计文档模板

新增有独立业务价值的模块时，先在 `docs/modules/` 下创建 `<module-key>.md`。复杂方案可以在
`docs/<日期>/<模块名>/` 保留调研、计划或实现细节，但最终约束应回写到模块设计文档和本文件。

```md
# <模块中文名> 设计文档

## 1. 背景与目标
- 要解决的问题：
- 用户角色与使用场景：
- 本期范围：
- 非目标：

## 2. 业务模型与状态
- 核心实体、字段、状态机：
- 所有权、可见范围和生命周期：

## 3. 架构与目录
- 后端文件清单及职责：
- 前端文件清单及职责：
- 配置、数据库、缓存、异步任务与外部依赖：

## 4. API 契约
- Endpoint、方法、认证/权限：
- 请求/响应 DTO、分页、筛选、错误码：

## 5. 前端交互
- 页面入口、路由、加载/空/错误状态：
- 表单校验、权限表现、响应式与主题：

## 6. 数据与安全
- 数据迁移、文件路径、保留/删除策略：
- 鉴权、授权、审计、敏感信息处理：

## 7. 实施步骤与验收
- 可独立合并的开发阶段：
- 自动化验证命令：
- 验收标准与回滚策略：
```

---

## 4. 后端设计与接入

### 4.1 API 与路由

1. 在 `src/omichub/api/v1/` 新建模块路由，使用 `APIRouter()`；按资源命名，例如 `/api/v1/<resource>`。
2. 在 `src/omichub/api/v1/router.py` 统一挂载路由、前缀和 tags；不要在应用入口散落注册。
3. 路由层只负责：参数解析、依赖注入、认证/权限调用、服务调用和 HTTP 状态码映射。
4. 所有对外请求和响应都使用 Pydantic DTO；不要将 SQLAlchemy 模型、内部配置或异常对象直接返回。
5. 列表接口统一明确分页、排序、筛选和空结果语义；写操作明确幂等性与冲突处理。

```python
router = APIRouter()

@router.get("", response_model=ModuleListResponse)
async def list_modules(
    service: ModuleService = Depends(get_module_service),
    current_user: User = Depends(get_current_user),
) -> ModuleListResponse:
    return await service.list_for_user(current_user.id)
```

### 4.2 DTO、应用服务和领域层

| 层 | 目录 | 职责 |
|---|---|---|
| DTO / Schema | `src/omichub/application/schemas/` | 请求校验、响应结构、跨 API 的稳定数据契约。 |
| 应用服务 | `src/omichub/application/services/` | 用例编排、事务边界、权限协作、调用仓储/外部服务。 |
| 领域层 | `src/omichub/domain/<module>/` | 多状态转换、复杂规则、值对象、实体与领域服务。 |
| 基础设施 | `src/omichub/infrastructure/` | ORM、Redis、文件存储、Docker、第三方 API、下载与执行适配器。 |

- 简单 CRUD 不必为形式而创建完整领域对象；但跨实体规则、状态机、账务、配额、任务调度等必须从路由层移出。
- 模块间调用优先依赖应用服务或领域接口，不直接跨模块访问私有 ORM 细节。
- 配置模型使用 Pydantic，读取失败必须有明确降级或可观测错误；避免在请求路径上静默吞掉业务错误。

### 4.3 数据、文件和异步任务

- **数据库**：新增持久化实体时同时新增/更新 ORM、迁移、DTO、索引与所有权字段；迁移必须可升级。
- **文件**：记录逻辑元数据、归属用户/项目和生命周期；任何下载、预览、删除前均校验访问权限。
- **异步任务**：耗时计算、下载、解析、流程运行进入 Celery/执行器；HTTP 接口返回任务标识或可轮询状态，不阻塞请求。
- **实时状态**：需要实时推送时设计 WebSocket/SSE 事件结构、断线重连和初始快照，不能只依赖前端定时猜测状态。
- **外部服务**：设置超时、重试边界、错误映射和必要的限流；密钥只从环境变量或安全配置读取。

### 4.4 权限与错误处理

- 页面级 `requiresAuth` 不等于 API 授权；每个 API 都必须通过 `Depends` 获取并校验当前用户。
- 管理接口必须显式校验管理员角色，不依赖前端隐藏入口。
- 资源接口必须校验 owner、成员关系或公开策略，避免“知道 ID 即可读取”。
- API 错误使用稳定的 HTTP 状态码和可展示的信息；避免暴露堆栈、路径、密钥、SQL 或第三方原始响应。

---

## 5. 前端设计与接入

### 5.1 文件组织与数据流

```text
frontend/src/
├── api/<module>.ts                 # 调用 @/api/client，定义请求函数
├── types/<module>.ts               # 与 API DTO 对齐的 TypeScript 类型
├── views/<Module>View.vue          # 路由页面：组装数据与交互
├── components/<module>/            # 可复用展示/表单子组件
├── composables/use<Module>.ts      # 可复用请求、轮询、WebSocket 等逻辑
├── stores/<module>.ts              # 仅跨页面共享、需缓存或全局同步的状态
└── utils/<module>Processor.ts      # 纯数据转换、格式化、图表配置
```

- HTTP 一律经 `@/api/client`，不在组件中直接创建 axios 实例。
- `views` 负责路由参数、页面状态和组件编排；复杂转换放进 `utils`，跨组件逻辑放进 `composables`。
- 类型必须与后端 DTO 同步；后端新增字段、枚举或状态时同步更新 `frontend/src/types/`。
- 仅当状态需在多个页面共享、跨页面缓存或与全局事件联动时再创建 Pinia store，避免把局部表单状态全局化。

### 5.2 路由、导航和权限表现

1. 在 `frontend/src/router/index.ts` 注册懒加载路由，设置中文 `meta.title` 和 `requiresAuth: true`。
2. 可从侧边栏访问的模块，同时更新 `frontend/src/layouts/DefaultLayout.vue` 的导航数据；管理员入口只在管理员视图展示，但后端仍必须授权。
3. 工具页额外更新 `tool_configs/tools_setting.yaml`、工具注册表 API、`ToolsHubView.vue` 图标映射与分组。
4. 页面必须处理加载、空数据、错误、无权限和提交中状态；不要只假定请求成功。

### 5.3 UI、主题与响应式

- UI 组件统一使用 **Naive UI**，图标统一使用 `@vicons/ionicons5`；新增依赖前先确认现有组件无法满足。
- 颜色、边框、阴影一律优先使用 `frontend/src/styles/global.css` 中的 CSS 变量，例如 `--neutral-bg`、`--neutral-card`、`--neutral-text-1`、`--arco-primary`。
- 同时验证亮色与暗色模式；禁止为单一主题写不可见的透明背景或硬编码文字颜色。
- 保持 `DefaultLayout.vue` 既有桌面/平板/移动端行为；常规页面使用布局提供的 content padding，工具页遵守 `tool_configs/tools_design.md` 的紧凑布局例外。
- 可点击元素必须有 hover/focus/disabled 反馈；异步操作显示 loading 并防止重复提交。

---

## 6. 配置与可运营性

| 内容 | 放置位置 | 规则 |
|---|---|---|
| 工具展示注册表 | `tool_configs/tools_setting.yaml` | 工具的 key、路由、图标、分组、排序与启用状态。 |
| 工具专属 YAML | `tool_configs/<tool>/` | 可运营的参考数据、参数和资源定义；路径写入注册表 `config_dir`。 |
| 应用运行设置 | `src/omichub/core/config.py` + 环境变量 | 数据库、Redis、密钥、开关、外部端点等运行时差异。 |
| 可编辑平台配置 | 对应数据库模型/管理 API | 需要后台维护、审计或即时生效的配置。 |

- YAML 字段改变时，同步更新 Pydantic 配置模型、API DTO、前端类型和相关文档。
- 不将 token、密码、连接串、用户数据或大体积运行产物提交到 YAML/仓库。
- 每个配置加载器明确：默认值、校验失败行为、热重载需求及管理入口。

---

## 7. 标准实施流程

1. **定范围**：写清用户、问题、本期范围、非目标、权限和验收标准。
2. **定契约**：先定义实体/状态、API DTO、错误语义、配置与数据生命周期。
3. **列文件**：在模块设计文档中列出新增与修改文件，并说明每个文件的职责。
4. **实现后端**：先落地 schema、服务、路由、权限、迁移/配置与定向测试。
5. **实现前端**：补 API/types、路由、页面、组件和导航；保持主题与响应式。
6. **接异步/外部能力**：如需任务、WebSocket、Snakemake 或第三方服务，先定义状态与失败路径再接入 UI。
7. **验证收尾**：执行相关测试、静态检查、构建；更新模块设计文档、配置样例和用户说明。

### 7.1 推荐提交拆分

| 阶段 | 可独立验收的内容 |
|---|---|
| 1. 契约与数据 | Schema、模型/迁移、配置模型、服务骨架、接口测试。 |
| 2. API 与权限 | 完整路由、授权、错误处理、异步任务入口。 |
| 3. 前端功能 | Types/API、路由、页面、基础交互与状态展示。 |
| 4. 体验完善 | 导航入口、响应式、主题、空/错/加载态、可访问性。 |
| 5. 文档与验证 | 设计文档、操作说明、测试、构建与部署说明。 |

---

## 8. 验证与验收清单

### 8.1 最低验证命令

```bash
# 后端：按改动范围选择执行
uv run ruff check src tests
uv run pytest <相关测试路径>

# 前端
cd frontend
npm run type-check
npm run build
```

如果模块修改了迁移、Celery、Docker、Snakemake、外部下载或 WebSocket，还必须在模块设计文档中补充对应的定向验证命令与人工验收步骤。

### 8.2 Definition of Done

- [ ] 模块设计文档已说明范围、架构、API、权限、数据与验收。
- [ ] 后端 API 已挂载到 `src/omichub/api/v1/router.py`，请求/响应 DTO 完整且类型稳定。
- [ ] 所有资源操作完成认证、角色与所属关系校验。
- [ ] 前端 API/types、路由、导航（如适用）和加载/空/错误状态完整。
- [ ] 亮/暗主题和移动端/窄屏布局均可用。
- [ ] 生信工具已完成 YAML 注册、`group` 透传、工具箱图标/分组接入；图形工具已满足数据闭环、分组配色与 PNG/SVG 导出要求。
- [ ] 配置、数据库迁移、异步任务和外部依赖已按模块需要更新。
- [ ] 相关单元/集成测试、`ruff`、`vue-tsc` 与前端 build 已通过。
- [ ] 文档、YAML 示例和运营说明与实现一致；未提交密钥或运行产物。

---

## 9. 模块设计评审问题

开始编码前，至少回答以下问题：

1. 该能力属于平台业务、管理功能、生信工具、分析流程还是外部集成？为什么？
2. 谁可以看、创建、修改、删除和执行？资源所有权如何验证？
3. API 输入输出、分页/筛选、错误码和异步状态是什么？
4. 哪些数据需要持久化，哪些放 Redis/文件系统，保留和清理策略是什么？
5. 是否需要 Celery、WebSocket、Snakemake、Docker 或第三方 API？失败、超时和重试怎么处理？
6. 前端入口在哪里，如何在亮/暗主题和移动端呈现？
7. 哪些现有服务、组件、配置或文档能够复用？
8. 如何验证功能、权限、异常路径和回归风险？

---

## 10. 关联文档

- `docs/modules/01_architecture_overview.md`：平台整体架构与基础设施。
- `docs/modules/03_api_design.md`：API 风格与契约设计参考。
- `docs/modules/05_frontend_architecture.md`：前端目录、状态和页面组织参考。
- `tool_configs/tools_design.md`：生信工具页面、工具注册表、分组展示与图形绘制专项规范（含完整标准调色板）。
- `docs/26.7.10/platform_workflow_monitor_template_architecture.md`：复杂跨层模块的完整设计样例。
- `docs/26.7.11/Kimi_Agent_系统发育树工具架构/`：工具模块前后端拆分与实现样例。
- 本文 **附录 A（任务中心体验增强设计）**：在既有任务/工具/报告能力上做“展示补全 + 纯前端导出 + 结果入口按类型分流”的跨模块增强样例，演示如何复用既有契约与组件、用集中映射表达 flow_id 分类约定。

> 新模块若需要突破本指南中的约定，必须在模块设计文档中说明原因、替代方案、兼容性影响和回滚策略。

---

## 附录 A：任务中心体验增强设计（2026-07-29）

> 本节记录一次“在既有模块上做体验补全”的设计落地，作为本指南第 1.3「渐进式接入 / 复用优先」
> 与第 5.1「纯转换进 utils」原则的实例：三处改动均**不引入平行基础设施**、**不改后端契约与数据库**，
> 而是复用既有数据契约与组件，并把跨组件约定收敛到集中的纯函数映射。

### A.1 背景与目标

任务中心（`views/TasksView.vue` + `components/task/TaskTable.vue`）把分析中心流程与工具箱工具产出的
任务混在同一张表里。本期在不改变后端的前提下补齐三项体验：

1. **用户名列**：表格此前缺少提交者列。
2. **导出 Excel**：把当前视图的任务信息一键导出为 `.xlsx`。
3. **工具箱结果分流**：只有分析流程（`rna_seq` / `atac_seq` 等）会生成「报告」（`/reports?taskId=`）；
   工具箱任务**不产出报告**，原「查看报告」按钮对它们是误导（点进去是空报告页）。应改为跳回对应
   工具页并按 `taskId` 直接打开该次分析的结果。

### A.2 设计要点与文件清单

| 关注点 | 决策 | 文件 |
|---|---|---|
| 用户名列 | 后端 `GET /tasks` 列表早已通过 `task_service._attach_usernames` 按 `user_id` 回填 `username`，前端 `Task` 类型与 `TaskTable` 用户列渲染（`username \|\| user_id`）均已具备，仅由 `showUser` prop 控制且默认关闭。**只在前端开启**，零后端改动。 | `views/TasksView.vue`（传 `show-user`） |
| 导出 Excel | 纯前端生成、即时下载；列与状态/流程标签与表格**同口径**；导出对象为**当前筛选视图**。新增依赖 `xlsx`（原仅有 `papaparse`，只能出 CSV，不满足 `.xlsx` 诉求）。转换逻辑放 `utils` 纯函数（§5.1）。 | `utils/taskExport.ts`、`views/TasksView.vue`、`package.json` |
| 工具箱结果分流 | 用**集中映射**表达 `flow_id` 分类：分析流程 → 报告页；工具箱 → 工具页 + `?taskId=` 深链。两项目前会进任务中心的工具箱工具（`kegg-enrichment`、`deg-analysis`；BLAST 走独立 `BlastTaskModel`、不进任务中心）原本**不支持**深链，需在视图补读 query 并复用既有「打开结果」路径，避免重写渲染。 | `utils/toolboxResultRoute.ts`、`components/task/TaskTable.vue`、`views/BioTools/KeggEnrichmentView.vue`、`views/BioTools/DegAnalysisView.vue` |

**契约对齐（§1.2）**：`TaskResponse.username` / 前端 `Task.username?` 已存在并被列表接口回填，前端只做展示开关，不新增隐式字段。

**纯函数与标签一致（§2.2 / §5.1）**：`taskExport.ts` 内状态/流程标签映射与 `TaskTable` 保持一致，
进度按表格同口径归一化（兼容后端 `0–100` 与 `0–1` 混用，规避历史「1000%」问题），时间格式化为
「M月D日 HH:mm」。表头列：`用户 / 任务名称 / 流程 / 状态 / 进度(%) / 提交时间 / 错误信息`，
文件名默认 `omichub-tasks-YYYYMMDD.xlsx`。导出按钮带 `loading` 与空数据禁用 + 文案提示。

**flow_id 分类约定（集中维护）**：

```ts
// utils/toolboxResultRoute.ts —— 仅登记「会写 TaskModel、出现在任务中心」的工具箱工具
const TOOLBOX_RESULT_ROUTE: Record<string, string> = {
  'kegg-enrichment': 'tools-kegg-enrichment',
  'deg-analysis':    'tools-deg-analysis',
}
export const TOOLBOX_RESULT_QUERY = 'taskId' // 工具页深链统一 query 参数名
export function getToolboxResultRoute(flowId, taskId): RouteLocationRaw | null
```

- `TaskTable` 操作列：成功且 `getToolboxResultRoute` 命中 → 文案「查看结果」、跳工具页带 `?taskId=`；
  否则维持「查看报告」→ `/reports?taskId=`。按钮可见性仍为 `status === 'success'`，与原行为等价。
- 工具页深链：`onMounted` 在默认数据就绪后读 `route.query[TOOLBOX_RESULT_QUERY]`，KEGG 经抽出的
  `openTaskById`、DEG 经 `fetchDegTask(id)` + 既有 `openHistoryTask` 打开结果——**复用页面内已验证的渲染路径**，不重复实现图表绘制。
- 顺带在 `TaskTable.flowLabel` 补 `kegg-enrichment`→`GO/KEGG 富集`、`deg-analysis`→`DEG 差异表达`，
  修复表格流程列此前显示原始 id 的问题。

**扩展规约**：新增会产生任务的工具箱工具时，在 `TOOLBOX_RESULT_ROUTE` 登记一行，并在对应视图接住
`TOOLBOX_RESULT_QUERY` 这一个 query 参数即可，无需改 TaskTable 分支逻辑。

### A.3 验证与回滚

- 自动验证（§8.1）：`cd frontend && npm run type-check && npm run build`
  （`vue-tsc -b` + `vite build` 通过；改前删除 `tsconfig*.tsbuildinfo` 规避脏缓存幻影报错）。
- 人工验收：用户名列显示真实用户名；导出 `.xlsx` 可打开且标签为中文、进度无 `1000%`；
  工具箱成功任务点「查看结果」直达对应工具页结果；分析流程成功任务仍为「查看报告」。
- 部署：重建前端后 `docker restart` nginx（`dist` 为 bind mount，重建后旧 inode 需重启才生效）。
- 回滚：用户名列移除 `show-user` 即关；导出与分流为纯前端新增，回退按钮/映射即可；
  **无迁移、无后端契约变更**，回滚不影响数据与接口兼容。`xlsx` 为新增依赖，回滚后可从 `package.json` 移除。
