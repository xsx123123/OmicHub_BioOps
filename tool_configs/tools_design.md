# OmicHub 生信工具箱 · 前端工具设计规范

> 本文档规定「生信工具箱」(`/tools`)下所有工具页面的架构、布局、样式、交互约定。
> 新增工具**必须遵循本规范**,以保证视觉一致、交互统一、维护成本低。
> 现有参考实现:火山图(`VolcanoPlotView.vue`)为最完整的样板,优先参照;BLAST / FASTQ 质控 / 绘图工坊 / KEGG 为次参照;JBrowse 为**全屏画布工具特例**,其沉浸式布局基线见 §19.7,不作为普通紧凑布局参照。
>
> 最后更新:2026-08-07

---

## 一、设计目标

| 目标 | 含义 |
|------|------|
| **统一** | 所有工具页面的根容器、工具栏、参数面板、卡片、配色、组件选型一致 |
| **紧凑** | 核心工作区(图表/表格/结果)屏幕占比最大化,四周与卡片间留白最小化 |
| **主题适配** | 亮 / 暗模式开箱即用,颜色一律走 CSS 变量,禁止硬编码 |
| **可复用** | 纯前端工具与有后端的工具共用同一套页面壳,差异只在数据来源 |
| **可演进** | 改全局布局规范只需改本文档 + `DefaultLayout.vue`,不动各工具页 |

---

## 二、技术栈(强制)

- **框架**:Vue 3 `<script setup lang="ts">` + Vite + TypeScript(严格模式,`vue-tsc` 必须通过)
- **UI 库**:Naive UI(`naive-ui`)—— 组件一律从 `naive-ui` 具名导入,禁止用其他 UI 库
- **图标**:`@vicons/ionicons5`(仅此一个图标库)
- **科学图表**:Plotly.js(`plotly.js-dist-min`,适合散点/火山/热图等大数据量)
- **通用图表**:ECharts(`vue-echarts`,适合柱/折/箱线等)
- **路由**:Vue Router 4
- **状态**:Pinia(`useThemeStore` 取主题,`useAuthStore` 取鉴权)
- **HTTP**:`@/api/client`(已封装鉴权与错误处理的 axios 实例)

---

## 三、文件与目录组织

```
frontend/src/
├── views/BioTools/
│   ├── ToolsHubView.vue          # 工具箱列表页(唯一,不新增)
│   └── <Tool>View.vue            # 各工具页面(每工具一个 SFC, PascalCase)
├── utils/
│   └── <tool>Processor.ts        # 工具数据处理与图表配置(纯函数,无 Vue 依赖)
├── components/bio-tools/
│   └── ToolCard.vue              # 工具卡片(共用,不新增)
├── api/tools.ts                  # GET /tools 拉取工具列表(共用)
├── types/tools.ts                # ToolItem 类型(共用)
└── router/index.ts               # 注册 tools/<key> 子路由

tool_configs/                            # 仓库根,后端配置目录
├── tools_setting.yaml            # 工具箱前端注册表(卡片元数据)
└── <tool-key>/                   # 工具专属 YAML 配置目录(如 jbrowse/、enrichments/)
```

### 命名约定

| 对象 | 规则 | 示例 |
|------|------|------|
| 视图文件 | `<Tool>View.vue`,PascalCase | `VolcanoPlotView.vue` |
| 处理器文件 | `<tool>Processor.ts`,camelCase | `volcanoProcessor.ts` |
| 路由 key | 小写连字符(kebab-case) | `fastq-qc`、`kegg-enrichment` |
| 根 class | `<key>-page` | `volcano-page`、`blast-page` |
| 布局 class | `<key>-layout` | `volcano-layout` |
| 路由 name | `tools-<key>` | `tools-volcano` |
| 路由 path | `tools/<key>` | `tools/volcano` |

> **key 一致性**:`tools_setting.yaml` 的 `key`、路由 `path` 的最后一段、根 class 前缀、路由 `name` 后缀,四处必须用同一个 kebab-case key。

---

## 四、新工具接入流程(强制 checklist)

新增一个工具,按顺序完成以下 5 步:

1. **后端注册**:在 `tool_configs/tools_setting.yaml` 的 `tools` 列表追加一项，必须指定 `group`（字段与可选值见 §五）。
2. **前端路由**:在 `frontend/src/router/index.ts` 的 `DefaultLayout` children 内,仿照已有工具追加子路由(见 §五)。
3. **图标登记**(仅当用了新图标):在 `ToolsHubView.vue` 的 `ICON_MAP` 登记组件。YAML 的 `icon` 字段是字符串,Vue 组件不能由字符串动态 import,必须在此映射。
4. **后端功能配置**(仅有后端的工具):按 §5.1.1 新建 `tool_configs/<tool-key>/` 目录放 YAML,并在 YAML 的 `config_dir` 指明。纯前端工具(如 plot/volcano)留空；BLAST 和其他高计算量工具必须遵循 §5.1.2。
5. **创建页面**:新建 `frontend/src/views/BioTools/<Tool>View.vue`,按 §六骨架实现;复杂数据逻辑抽到 `frontend/src/utils/<tool>Processor.ts`。

> **图形绘制工具补充要求**：散点图、火山图、热图、箱线图、柱状图等以数据导入和交互式绘图为核心的工具，还必须遵守 §5.6 的参数、功能、导出与验证规范。

---

## 五、路由与注册规范

### 5.1 `tools_setting.yaml` 字段

```yaml
- key: "volcano"                         # 唯一标识,同时是路由 token,kebab-case
  title: "火山图绘制"                    # 卡片标题
  description: "差异表达结果可视化..."   # 卡片描述(一句话)
  icon: "BonfireOutline"                 # 图标字符串 key,须在 ICON_MAP 登记
  gradient: "linear-gradient(135deg, #F53F3F 0%, #FF7D00 100%)"  # 卡片图标渐变
  route: "/tools/volcano"                # 点击跳转路由,与 router path 一致
  group: "visualization"                 # 分组 key,决定工具箱中的展示分区
  enabled: true                          # false 则软下线,不出现在工具箱
  order: 45                              # 卡片排序,升序(10 的步长留间隔)
  config_dir: ""                         # 有后端配置填 "tool_configs/<tool-key>",纯前端留空
```

#### 5.1.1 工具运行配置外置（推荐）

只要工具存在可运营、需按环境/物种/资源调整，或可能由管理员维护的参数，就应将其外置为
`tool_configs/<tool-key>/` 下的 YAML 文件，而不是散落在 Python、Vue 或 TypeScript 常量中。
典型配置包括参考基因组、物种列表、数据库资源、分析默认阈值、容器镜像、可选算法、结果保留策略和功能开关。

```text
tool_configs/
├── tools_setting.yaml                         # 工具箱注册表；只放卡片展示与入口元数据
└── <tool-key>/
    ├── <tool-key>_config.yaml                  # 工具主运行配置（推荐命名）
    ├── resources.yaml                          # 可选：参考资源/数据库/物种等大列表
    └── presets.yaml                            # 可选：用户可选的参数预设
```

| 配置类别 | 放置位置 | 示例 |
|---|---|---|
| 工具卡片元数据 | `tool_configs/tools_setting.yaml` | 标题、图标、路由、分组、排序、`config_dir`。 |
| 工具运行配置 | `tool_configs/<tool-key>/*.yaml` | 默认参数、资源目录、算法开关、可用物种。 |
| 前端纯展示预设 | 优先 `tool_configs/<tool-key>/presets.yaml`；无后端读取需求时可随前端模块维护 | 绘图主题、示例数据说明、表单默认预设。 |
| 密钥与环境差异 | 环境变量 + `src/omichub/core/config.py` | API Key、密码、数据库 DSN、主机地址。 |

实现要求：

1. 后端为每份 YAML 建立对应的 Pydantic 配置模型与加载器，建议放在 `src/omichub/tools/<tool_key>/config.py`；不要把 `dict[str, Any]` 直接传入业务逻辑。
2. 加载器必须明确默认值、必填字段和 YAML 解析失败策略。可热更新的配置应按文件 mtime 缓存/重载；不支持热更新时在文档中说明重启要求。
3. API 只返回前端实际需要且允许公开的配置子集；不得将本地路径、访问令牌、密码或内部基础设施细节直接下发到浏览器。
4. 配置字段改动时，同步更新 Pydantic 模型、调用服务、前端类型/API（如有）、示例 YAML 和模块设计文档。
5. YAML 使用 UTF-8、2 空格缩进与 `snake_case` 字段名；需引用路径时使用相对仓库根的稳定路径，避免写入开发机绝对路径。
6. 每个工具配置至少有解析与模型校验的定向测试/验证样例，确认空配置、非法枚举、资源缺失和默认值行为。

纯前端且没有可运营参数的工具可以保持 `config_dir: ""`；一旦需要让默认阈值、色板、资源列表或预设可独立维护，就应创建对应 YAML 配置，而不是继续扩大组件内硬编码常量。

#### 5.1.2 高计算量工具执行架构（强制，复用 BLAST 模式）

需要运行外部程序、R/Python 工作流、容器镜像、参考数据库检索，或预计会占用较多 CPU、内存、磁盘与执行时间的工具，**必须使用与 BLAST 相同的异步任务架构**。典型工具包括序列检索、比对、组装、注释、富集分析、统计模型和大规模可视化预处理。

```text
浏览器
  └─ POST /<tool>/submit（上传/参数）
       └─ Web API：鉴权、输入校验、创建 TaskModel、保存任务输入
            └─ Celery：投递到 analysis 队列
                 └─ Worker：消费任务、启动对应 Docker/R/命令行容器
                      └─ 任务目录：写入结果表、图片、日志和结果元数据
                 └─ Worker：更新任务状态、进度、错误与结果索引
  └─ GET /<tool>/tasks/{task_id}（轮询任务状态与结果）
       └─ 前端：渲染表格、Plotly/ECharts 图表与可下载产物
```

职责边界：

| 层级 | 必须承担的职责 | 禁止事项 |
|---|---|---|
| 浏览器 | 提交参数/文件、展示排队与进度、轮询任务、渲染结果和下载链接。 | 直接执行分析程序、调用 Docker、等待长请求完成。 |
| Web API | 鉴权与数据归属校验、轻量输入校验、创建任务记录、将任务投递至 Celery、提供状态/结果查询接口。 | 安装 Docker CLI、挂载 Docker Socket、同步运行 R/容器/高耗时子进程。 |
| Celery Worker | 消费 `analysis` 队列、执行任务、控制超时与资源、更新 `TaskModel` 状态。 | 将执行结果只保存在进程内存中，或绕过任务状态记录。 |
| 分析容器 | 在隔离环境中运行 BLAST、R、Python 或其他命令行工具；将约定产物写入挂载任务目录。 | 直接访问 Web 会话、数据库凭据或用户认证令牌。 |

实现要求：

1. 提交接口必须快速返回 `task_id`、初始状态与状态查询地址；不得等待容器分析结束后才响应。
2. Web 进程不得依赖 Docker CLI 或 Docker Socket。只有执行分析的 Worker 具备 Docker CLI、Docker Socket（或等效容器运行权限）和所需的数据卷挂载。
3. 每个任务使用独立的用户归属目录和任务目录；输入、运行日志、结构化结果、图片/PDF/CSV 等产物均写入该目录，并由 `task_id` 关联。
4. Worker 必须在任务开始、进度更新、成功和失败时持久化状态；失败时记录对用户安全的错误摘要，内部日志不得直接泄露到前端。
5. 所有查询、下载和结果展示接口必须校验任务所属用户；前端只能轮询和查看当前用户有权限访问的 `task_id`。
6. 为 Celery 任务和容器运行设置软/硬超时、并发数、CPU/内存限制、文件大小限制及结果保留/清理策略；资源参数应由工具 YAML 或部署配置统一维护。
7. 容器退出后由 Worker 解析约定的结果文件，生成前端可消费的结果 DTO/JSON；图表优先在前端用 Plotly/ECharts 交互式渲染，不要求容器生成静态图。
8. 新增高计算工具时优先复用 BLAST 已有的任务模型、队列、状态字段、目录隔离、进度接口和前端轮询模式，不得重新实现一套同步执行链路。

##### Docker Socket 权限与 GID 规范（强制）

Worker 通过 `/var/run/docker.sock` 启动分析容器时，容器内 Worker 的附加组 GID 必须与宿主机 Docker Socket 的实际 GID 一致。**禁止在 Compose、Dockerfile、`.env` 或部署脚本中固定写死 `DOCKER_GID=987`、`999` 等机器相关数值**；不同 Linux 发行版、Docker 安装方式、CI 节点和服务器上的 Docker 组 GID 可能不同，固定值会导致以下错误：

```text
permission denied while trying to connect to the Docker daemon socket
```

部署实现必须遵循：

1. 统一通过 `scripts/worker-compose.sh` 启动 Worker；该脚本在执行 Compose 前使用 `stat -c '%g' /var/run/docker.sock` 自动读取实际 GID，并导出为 `DOCKER_GID`。
2. `docker-compose.worker.yml` 使用 `group_add: ["${DOCKER_GID}"]` 将 Worker 加入对应附加组，不提供固定数字作为默认值；未检测到 Socket 或 GID 时应明确失败或警告，而不是静默使用猜测值。
3. Docker Socket 必须以只满足执行需求的权限挂载；禁止通过 `chmod 666 /var/run/docker.sock`、特权容器或全局放宽权限规避 GID 配置问题。
4. Docker Socket、Docker CLI 和对应附加组只配置给需要启动分析容器的 Worker；Web 容器不得因为富集、BLAST 等计算任务获得该权限。
5. Worker 重建或迁移节点后必须重新检测 GID；不得复用其他服务器生成的 Compose 环境文件。
6. Worker 入口脚本从 root 降权到 `PUID:PGID` 时必须显式保留 Docker Socket GID。禁止使用会清空附加组的 `gosu "$PUID:$PGID"` 直接启动 Celery；应使用 `setpriv --reuid ... --regid ... --groups "$DOCKER_SOCKET_GID"`，或通过具名用户初始化等效附加组。
7. 权限验收必须检查 Celery PID 及 prefork 子进程的 `/proc/<pid>/status`，确认 `Groups:` 包含 Socket GID。只执行 `docker exec omichub-worker docker version` 会以 root 或独立 exec 用户运行，不能证明实际 Celery 任务具备权限。
8. Worker 健康检查必须同时验证 PID 1 附加组、非 root Docker daemon 连接和 Celery ping；任一失败时将容器标记为 unhealthy，避免任务继续被错误节点消费。

部署验收至少执行：

```bash
stat -c 'host_socket_gid=%g mode=%A' /var/run/docker.sock
docker exec omichub-worker sh -lc 'id; stat -c "worker_socket_gid=%g mode=%A" /var/run/docker.sock'
docker exec omichub-worker sh -lc 'grep -E "^(Uid|Gid|Groups):" /proc/1/status'
docker exec omichub-worker docker version
docker exec omichub-worker docker run --rm alpine:3.20 true
```

宿主机、Worker 和 Celery 进程看到的 Socket GID必须匹配，且实际非 root 运行身份必须能成功执行 `docker version` 和最小测试容器。只验证 Docker CLI 已安装不算通过，因为 CLI 存在并不代表实际 Celery 任务有权连接 Docker daemon。

##### Dockerfile 目录与职责规范（强制）

平台服务、Celery Worker 和高计算量工具运行时的 Dockerfile 必须统一放在 `deploy/` 下，主栈相关镜像优先放在 `deploy/docker/`。`tool_configs/<tool-key>/` 只保存 YAML 配置、运行脚本、示例数据、资源契约和工具说明，禁止继续在工具配置目录中新增 Dockerfile。

目录和命名约定：

```text
deploy/docker/
├── Dockerfile                   # 通用后端：Web / Beat / Flower
├── Dockerfile.frontend          # Vue 构建与 Nginx 静态托管
├── Dockerfile.worker            # 通用 Celery 计算 Worker
├── Dockerfile.phylo             # 系统发育专用 Worker
├── Dockerfile.enrichment        # GO / KEGG clusterProfiler R 运行时
└── README.md                    # 每个 Dockerfile 的职责、上下文和 Make 入口

tool_configs/enrichments/
├── run_enrichment.R             # Docker 构建上下文中的运行脚本
├── species_config.yaml          # 工具运行配置
└── examples/                    # 示例输入输出
```

实现要求：

1. 通用后端可保留名称 `Dockerfile`；其他镜像使用 `Dockerfile.<purpose>`，不得使用含义不明的序号或临时名称。
2. 每个 Dockerfile 文件头和 `deploy/docker/README.md` 必须说明镜像用途、构建上下文、运行角色和推荐 Make target。
3. Dockerfile 位于 `deploy/docker/` 不代表构建上下文也必须是该目录；工具镜像可使用 `docker build -f deploy/docker/Dockerfile.<tool> tool_configs/<tool>/`，避免复制或移动运行脚本。
4. 每个独立工具镜像必须提供稳定的 `make docker-build-<tool>` 入口。项目文档优先引用 Make target，不散落裸 `docker build` 命令。
5. 启动依赖该镜像的 Worker 前，`make docker-up-worker`、`make docker-up-all`、`make docker-start` 和开发重载命令必须自动构建或检查镜像，避免任务提交后才因镜像不存在而失败。
6. 移动或重命名 Dockerfile 时，必须同步更新 Makefile、Compose、README、工具契约、CI/CD 和测试中的路径，并通过 Make dry-run 与 Docker 构建配置验证。

验收标准：提交后 Web 请求立即结束；Worker 可独立完成容器计算；Web 镜像中不存在分析所需 Docker 依赖；任务失败不会导致 Web 进程 500；前端能够明确展示 `queued`、`running`、`completed`、`failed` 状态并在完成后获取结果。

### 5.2 路由注册(`router/index.ts`)

```ts
{
  path: 'tools/<key>',
  name: 'tools-<key>',
  component: () => import('@/views/BioTools/<Tool>View.vue'),
  meta: { title: '<中文标题>', requiresAuth: true },
}
```

- 所有工具路由是 `DefaultLayout` 的 children,path 不带前导 `/`(相对父级 `/`)。
- `requiresAuth: true` 必填。
- **全屏工具**(如 JBrowse,需要占满视口、自带滚动)额外加 `meta: { fullscreen: true }`。全屏工具走 `DefaultLayout` 的 fullscreen 分支(`padding: 0`)，外层不套普通页面边距；内部页头、工具栏和响应式规则仍遵守 §十九，画布区域按 §19.7 沉浸布局基线铺满剩余高度。详见 §十一。

### 5.3 图标登记(`ToolsHubView.vue`)

```ts
import { BonfireOutline, /* ... */ } from '@vicons/ionicons5'

const ICON_MAP: Record<string, Component> = {
  ScanOutline, SearchOutline, ColorPaletteOutline, LayersOutline,
  BarChartOutline, AppsOutline, BonfireOutline, // ← 新图标在此登记
}
```

未登记的 `icon` key 回退到 `AppsOutline`。

### 5.4 工具箱分组展示(`ToolsHubView.vue`)

工具箱列表页按 `group` 分区渲染，而不是将全部工具卡片平铺。分组常量定义在
`frontend/src/views/BioTools/ToolsHubView.vue` 的 `GROUP_MAP`；新增分组时必须同步更新
前端映射、分组图标登记与本文档。

| group key | 展示名称 | 分组图标 | 分组顺序 | 当前工具 |
|---|---|---|---:|---|
| `sequence` | 序列分析 | `CodeSlashOutline` | 1 | FASTQ 极速质控、序列检索 BLAST、序列魔术师、PrimerForge 引物锻造工坊 |
| `visualization` | 数据可视化 | `ColorPaletteOutline` | 2 | 组学绘图工坊、火山图绘制 |
| `analysis` | 表达分析 | `StatsChartOutline` | 3 | DEG 差异表达分析 |
| `genome` | 基因组与进化 | `LayersOutline` | 4 | Web 基因组浏览器、系统发育树构建、格式轻量转换器 |
| `function` | 功能注释 | `BarChartOutline` | 5 | GO / KEGG 富集分析 |
| `environment` | 计算环境 | `TerminalOutline` | 6 | 云端沙盒终端 |

分组与卡片排序规则：

1. `enabled: false` 的工具在后端已过滤，前端仍以 `tool.enabled !== false` 作兼容性过滤；禁用工具不参与分组计数。
2. 分组按上表的 `order` 升序展示；组内工具继续严格按各自 `order` 升序展示，不改变既有排序语义。
3. `group` 缺失或不在 `GROUP_MAP` 内时，前端归入最后的「其他工具」（`AppsOutline`），避免新配置导致卡片丢失。
4. 无可用工具的分组不渲染；首次加载时展示五个标准分组标题，并在每个分组下显示两行骨架卡片。

每个分组标题必须包含分组图标、名称、工具数量和折叠按钮。分组默认展开，用户操作后的
折叠状态以 `localStorage` 键 `omicHub_tools_group_collapsed` 持久化；刷新或再次进入工具箱时恢复。
分组内继续直接复用 `components/bio-tools/ToolCard.vue`，不得修改其卡片渐变、圆角、hover 动效或路由跳转方式。

推荐样式约定：

```css
.tool-group { margin-bottom: 24px; }
.group-header { /* 图标 + 16px/500 标题 + 数量 + 右侧折叠按钮 */ }
.tools-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin: 12px 0;
}
@media (max-width: 768px) {
  .tools-grid { grid-template-columns: 1fr; }
}
```

### 5.5 注册表与 API 字段透传

`group` 是工具注册表元数据的一部分，必须沿以下链路保持同名透传：

```text
tool_configs/tools_setting.yaml
  → src/omichub/tools/registry/config.py::ToolItem
  → src/omichub/tools/registry/schema.py::ToolItemDTO
  → GET /api/v1/tools
  → frontend/src/types/tools.ts::ToolItem
  → ToolsHubView.vue
```

新增或修改 `group` 时，需要同时确认配置模型、API DTO、前端 `ToolItem` 类型与 `GROUP_MAP` 一致；
不要仅修改 YAML，否则接口会因 Pydantic 模型忽略未知字段而无法向前端返回分组信息。

### 5.6 图形绘制工具通用规范（以火山图为基准）

本节适用于火山图、散点图、热图、箱线图、柱状图、富集气泡图等“用户导入表格后在浏览器中配置并生成图形”的工具。
新增图形绘制工具应复用火山图的完整交互闭环，而不是只输出一张不可配置的静态图：

```text
数据导入 → 表头识别与字段映射 → 数据校验与转换 → 参数化绘图
→ 图上交互与结果查询 → 数据表核对 → 图片/矢量导出
```

#### 5.6.1 目录与职责

```text
frontend/src/
├── views/BioTools/<Chart>View.vue       # 页面、表单状态、渲染生命周期、导出按钮
└── utils/<chart>Processor.ts             # 纯函数：解析、列识别、校验、计算、Plotly/ECharts 配置
```

- 页面组件只管理表单、上传文件、响应式状态、图表挂载和用户反馈；不在 Vue 组件内堆积数据算法。
- `Processor` 必须导出明确的输入行、列映射、配置、处理结果和图表构建函数类型；同一输入与配置应得到可预测结果。
- 图表库遵循 §十二：需要缩放、悬浮提示、点选、矢量导出或大规模散点时优先 Plotly；常规统计图可使用 ECharts。
- 绘图工具如是纯前端计算，数据不得上传后端；如果确有服务端计算需求，必须说明文件保留、任务状态、权限与结果清理策略。

#### 5.6.2 必备数据导入与字段映射参数

| 能力 | 最低要求 | 火山图参考实现 |
|---|---|---|
| 文件上传 | 支持 CSV、TSV/TXT；明确大小限制和解析失败提示。 | `NUpload` + `FileReader`。 |
| 直接粘贴 | 支持将表格文本粘贴为数据源，适合少量快速作图。 | 火山图页面已提供粘贴入口。 |
| 示例数据 | 每个工具提供可一键载入的最小有效示例，帮助用户理解字段要求。 | `genSampleData()`。 |
| 分隔符识别 | 自动识别 Tab、逗号和空白分隔；不确定时给出提示或允许人工选择。 | `parseDelimited()`。 |
| 表头与行数反馈 | 上传/粘贴后显示文件名、有效行数、可选列。 | 文件名 + 行数提示。 |
| 自动列识别 | 根据常见别名推测所需列，减少手动操作。 | `autoDetectColumns()` 识别 `padj`、`log2FC`、基因名。 |
| 手动列映射 | 所有核心字段必须可由用户重新选择；不要只依赖列名猜测。 | `NSelect` 映射 padj、log2FC、gene。 |
| 数据校验 | 校验必填列、数值范围、空值、重复/非法值；明确跳过行或中断的规则。 | NA 过滤、`p <= 0` 安全处理。 |

不同图种在模块设计文档中必须列出**输入契约**：必需列、可选列、可接受别名、数值单位、最小行数和示例数据格式。例如：

| 图种 | 常见必需列 | 常见可选列 |
|---|---|---|
| 火山图 | 特征 ID、效应值（如 `log2FC`）、显著性（`padj`/`pvalue`） | 分组、注释、原始 p 值 |
| 散点图 | X、Y | 标签、颜色分组、点大小、形状分组 |
| 箱线图 | 分组、数值 | 子分组、样本 ID、显著性结果 |
| 热图 | 行 ID、列名与数值矩阵 | 行/列注释、聚类结果、分组颜色 |
| 柱/折线图 | 分类/时间轴、数值 | 系列、误差值、标签、置信区间 |

#### 5.6.3 参数面板的最低功能集

参数面板使用 `NCollapse` 分区，默认展开数据、核心阈值/映射和轴设置；复杂参数允许折叠，但不能隐藏核心操作。

| 参数分组 | 必备参数/功能 | 说明 |
|---|---|---|
| 数据与映射 | 数据源、列映射、解析提示、重置/示例数据 | 显示当前数据状态；数据更新后自动重算。 |
| 核心计算 | 图种特有阈值、分组规则、变换方式、统计口径 | 例如火山图的 p-value 与 `|log2FC|` 阈值。 |
| 颜色与图例 | 分组颜色、强调色、图例开关/位置（适用时） | 使用 `NColorPicker`；默认色需符合亮/暗主题。 |
| 坐标轴与标题 | 自动/手动范围、最小/最大值、X/Y 轴标题、主标题、标题换行 | 手动范围须校验 `min < max`；自动模式使用数据驱动的安全边界。 |
| 标签与重点对象 | Top N 标注、自定义 ID/基因列表、高亮开关、标注上限 | 防止大数据量一次标注全部对象；无效 ID 必须提示。 |
| 图表样式 | 点/线/柱尺寸、透明度、网格/阈值线、布局密度 | 参数变化即时重绘，不能破坏数据与筛选状态。 |
| 导出 | PNG、SVG、尺寸跟随容器或自定义宽高、PNG DPI/导出倍率 | PNG 至少提供 300/600/1000 DPI 或等效 `scale` 选项；自定义尺寸要校验合理范围，例如 100–8000 px。 |

图种特有参数必须按语义追加，不能强行套用火山图字段。例如热图需要色阶、聚类和标准化；箱线图需要离群值、抖动点与统计比较；散点图需要回归线、相关系数和点大小映射。

#### 5.6.3.1 分组与配色规范（强制）

**只要最终图形存在分类分组、系列、处理组、样本组、显著性类别或注释类别，就必须用颜色区分。**
不得仅依赖点形状、线型、位置或文字来区分不同组；颜色、图例和 hover 中的分组名称必须同时存在。

1. 分类变量使用**离散色板**，一个类别对应一个稳定颜色；同一类别在筛选、重绘、导出和同工具的不同图中必须保持同色。
2. 连续数值（如表达量、富集比例、时间、相关性）使用**连续渐变色板**，必须显示颜色条及数值范围；禁止把连续渐变逐项分配给离散类别。
3. 默认颜色是数据编码的例外，可使用本节列出的固定十六进制色值；页面背景、文字、边框等 UI 颜色仍须遵守 §八的 CSS 变量要求。
4. `NColorPicker` 仅用于允许用户覆盖默认颜色；重置后必须恢复标准色板。自定义颜色改变后，图例、hover、标注和导出图必须同步更新。
5. 类别数超过当前色板容量时，不得静默循环复用颜色；应提示用户、要求合并/筛选类别，或使用经过设计并在模块文档中登记的扩展色板。

以下色板是 OmicHub 图形绘制工具的标准默认选项。实现时可直接以同名常量放入 `<chart>Processor.ts` 或共用配色工具文件：

```ts
export const PLOT_COLOR_PALETTES = {
  // 优先默认：色觉友好，适合 2–6 个离散组
  color_discrete_friendly: ['#0072B2', '#56B4E9', '#009E73', '#F5C710', '#E69F00', '#D55E00'],
  // 海岸风格，适合不超过 5 个离散组
  colors_discrete_seaside: ['#8ecae6', '#219ebc', '#023047', '#ffb703', '#fb8500'],
  // 色觉友好扩展，适合不超过 7 个离散组
  colors_discrete_friendly_long: ['#CC79A7', '#0072B2', '#56B4E9', '#009E73', '#F5C710', '#E69F00', '#D55E00'],
  // 长离散色板，适合不超过 12 个离散组
  colors_discrete_friendly_long_2: ['#fe65b3', '#CC79A7', '#ffd2d8', '#0072B2', '#007aff', '#56B4E9', '#009E73', '#4cd964', '#F5C710', '#E69F00', '#D55E00', '#ff3b30'],
  // 可选主题色板：按工具设计选用，不能与同图中的默认色板混用
  colors_discrete_apple: ['#ff3b30', '#ff9500', '#ffcc00', '#4cd964', '#5ac8fa', '#007aff', '#5856d6'],
  colors_discrete_ibm: ['#5B8DFE', '#725DEE', '#DD227D', '#FE5F00', '#FFB109'],
  colors_discrete_candy: ['#9b5de5', '#f15bb5', '#fee440', '#00bbf9', '#00f5d4'],
  color_1: ['#ECA669', '#E06681', '#8087E2', '#E2D269'],
  // color_1 的登记扩展版：补充青绿与紫，覆盖 2–6 个离散组；Venn / UpSet 工具的默认色板
  color_1_extended: ['#ECA669', '#E06681', '#8087E2', '#E2D269', '#66B2A0', '#A086C8'],
  // 仅用于有序连续数值；必须配合 colorbar，不可作为分类色板
  colors_continuous_bluepinkyellow: ['#00034D', '#000F9F', '#001CEF', '#241EF5', '#5823F6', '#A033E0', '#E85AB1', '#F1907C', '#F4AF63', '#FCE552', '#FFFB6D'],
} as const
```

默认选择规则：

| 场景 | 默认色板 | 使用规则 |
|---|---|---|
| 2–6 个分类组 | `color_discrete_friendly` | 首选，保证主要生信分组的可读性与色觉友好性。 |
| 7 个分类组 | `colors_discrete_friendly_long` | 按稳定类别顺序取色。 |
| 8–12 个分类组 | `colors_discrete_friendly_long_2` | 必须保留清晰图例；建议同时提供筛选。 |
| 工具明确要求特定视觉主题 | `colors_discrete_seaside` / `colors_discrete_apple` / `colors_discrete_ibm` / `colors_discrete_candy` / `color_1` | 只能选一套作为该图的离散默认色；在模块文档记录选择原因。 |
| Venn / UpSet 集合分析（2–6 个集合） | `color_1_extended` | 默认色板；若用户改选容量不足的色板，须提示并回退到 `colors_discrete_friendly_long`，不得静默循环取色。 |
| 连续数值映射 | `colors_continuous_bluepinkyellow` | 按数值从低到高映射，并展示 colorbar；若数值具有“零/基线”语义，需在模块文档说明中点颜色和范围。 |

建议按原始数据或用户明确的类别顺序建立颜色字典，而不是按当前筛选结果临时排序：

```ts
function buildGroupColorMap(groups: string[], palette: readonly string[]) {
  const uniqueGroups = [...new Set(groups)]
  if (uniqueGroups.length > palette.length) {
    throw new Error('当前分组数超过所选离散色板容量')
  }

  return Object.fromEntries(
    uniqueGroups.map((group, index) => [group, palette[index]]),
  )
}
```

图例中应按该颜色字典输出所有当前可见组；分组标签需使用用户可理解的中文/原始名称，禁止只展示内部编码。

#### 5.6.3.2 富集气泡图颜色与尺寸规范（强制）

GO / KEGG 等同时返回多个知识库来源的富集工具，结果不得混在同一气泡图和同一统计表中。每个来源必须拥有独立标题、空状态、图表、结果数量、表格和导出入口，允许某一来源无结果而另一来源正常展示。

| 设置 | 默认值 | 合法范围与行为 |
|---|---|---|
| GO 主色 | `var(--kimi-chart-3)`（绿色） | 从 `--kimi-chart-1` 至 `--kimi-chart-6` 中选择；同一来源的图、hover 和导出保持一致。 |
| KEGG 主色 | `var(--kimi-chart-1)`（蓝色） | 不得与 GO 默认同色；用户修改后只重绘前端图表。 |
| 图宽 | `960px` | 允许 `640–1600px`；实际渲染宽度不得超过当前容器宽度，窄屏自动收缩。 |
| 图高 | `480px` | 允许 `360–1000px`；GO 与 KEGG 默认保持相同高度。 |
| 展示数量 | Top 20 | 分来源按 `p.adjust` 升序取 Top N，不得先合并来源再截断。 |
| X 轴 | `GeneRatio` | 转换为连续比例；原始比例字符串保留在表格和 hover。 |
| 点大小 | `Count` | 使用受控缩放并设置最大点径，避免大通路遮挡其它结果。 |
| 点颜色 | `-log10(p.adjust)` | 必须使用连续渐变色板并显示 colorbar；来源主色只定义色阶基调，禁止所有气泡使用同一填充色。 |
| Y 轴标签 | 描述文本 | 超长术语/通路名称应自动换行并限制为约两行，超出部分显示省略号；hover 必须保留完整描述。 |
| hover | ID、描述、GeneRatio、Count、p-value、p.adjust、q-value | 小数使用科学计数法，不能遗漏 q-value。 |

颜色、图宽和图高是**前端展示参数**，调整后使用 debounce + `Plotly.react` 局部重绘，不得重新提交计算任务。p-value cutoff 与 q-value cutoff 是**服务端计算参数**，必须分别提供输入框、校验 `0 < cutoff <= 1`，并随任务提交给 R/clusterProfiler；修改计算阈值后必须重新运行任务，不能只在浏览器隐藏结果冒充重新分析。

富集结果页面还必须提供：每个来源独立的 PNG、SVG、CSV 导出入口；PNG 至少支持 300/600/1000 DPI，自定义导出尺寸范围遵循 100–8000 px；结果区提供字段说明卡片，解释 ID、Description、GeneRatio、p-value、p.adjust、q-value、Count 及来源专属操作。图片导出仅消费浏览器中的 Plotly 实例，不得重新提交 Celery 或重新启动 R 容器。

富集任务提交必须包含用户可读的项目 ID，页面字段必须显示明确的必填状态，提交接口不得提供可绕过必填校验的默认项目值。后端对项目 ID 做长度校验和安全目录名转换，结果统一保存到 `{data_mount}/users/{user_id}/enrichments/{project_slug}/{task_id}/`，禁止直接拼接未经清洗的用户输入。项目 ID、物种、基因数量、阈值和结果路径元数据写入通用任务记录；页面提供当前用户的历史任务列表、已完成结果恢复查看和鉴权后的原始 clusterProfiler CSV 下载。历史接口只返回当前 JWT 用户的数据，不接受可伪造的 `user_id` 查询参数。

项目 ID 下方的结果目录说明等帮助文案必须放在对应表单项的正常文档流中，并预留稳定间距；不得通过负外边距、绝对定位或不受控层级将提示文字推入输入框、标签或相邻控件区域。任何屏幕宽度、浏览器缩放比例及输入框显示字数统计时，帮助文案都不能被上方控件遮挡或与其重叠。

气泡图内部可见标注使用英文，包括标题、X/Y 轴、colorbar 和 hover 字段名；页面表单、帮助文案和错误信息继续使用中文。默认标题分别为 `GO Enrichment — Top N`、`KEGG Enrichment — Top N`，避免导出论文图片时混入中文界面文案。

组学绘图工坊必须支持“富集结果气泡图”图种：自动识别 `Source, ID, Description, GeneRatio, pvalue, p.adjust, qvalue, Count` 标准列；未选择条目时按 `p.adjust` 展示 Top 20，用户可按 ID/Description 搜索并多选 pathway/GO term 后局部重绘；当前筛选结果可导出 CSV，图片继续支持 PNG/SVG 和高 DPI。重新绘图仅处理下载结果，不重新运行 R 容器。

#### 5.6.4 数据处理与绘图质量要求

1. **纯函数处理管线**：将原始行转换为渲染行时，依次完成列读取、数值转换、缺失值策略、派生指标、分类/分系列、排序、标签选择和坐标范围计算。
2. **异常值策略明确**：零值、负值、NA、NaN、Infinity、重复 ID、极端值和对数变换的非法输入必须有确定行为；例如火山图把 `p <= 0` 夹到最小正数，避免产生 `Infinity`。
3. **自动范围可读**：自动坐标范围必须留边距，并抑制单个极端值挤压主体数据；用户始终可切换为手动范围。
4. **主题适配**：图表背景、网格、坐标轴、文本、标注框、hover 文本和图例均要随 `useThemeStore()` 的亮/暗主题切换。
5. **可解释 hover**：每个图元的 hover 至少展示主键/标签、关键数值和分组；格式化小数、p 值和科学计数法，禁止直接显示未处理的浮点数。
6. **受控重绘**：参数、数据或主题变化后更新图表；避免重复创建图表实例。页面卸载时调用图表库的销毁方法（如 `Plotly.purge`）。
7. **性能边界**：大数据量默认关闭过多文本标签，限制搜索结果/结果表首屏行数；必要时采用 WebGL trace、抽样或前端分页，并在设计文档说明阈值。
8. **图内标注使用英文**：工具自身生成的图内可见文本——标题、坐标轴标签、图例条目、colorbar 标签、hover 字段名、默认标注——统一使用英文，使导出的 PNG/SVG 可直接作为论文配图；页面表单、帮助文案、错误信息与结果表表头继续使用中文。用户输入的数据（集合名、基因名等）按原样展示，不做翻译；工具提供示例数据时，示例的集合/分组名应使用英文，以展示导出效果。

#### 5.6.5 结果区、交互与可追溯性

每个图形绘制工具至少提供以下能力：

- **图表状态**：未导入数据时展示明确空状态和输入要求；绘制时显示 loading；失败时显示可操作的错误提示。
- **统计摘要**：展示总行数、有效行数及图种关键分组/统计结果。火山图对应总计、上调、下调和非显著数量。
- **搜索与焦点**：可按主键/标签搜索对象；选中对象在图上突出显示或添加引线标注。
- **结果数据表**：可展开查看用于绘图的处理后数据，至少包含主键、关键数值、分组/系列与派生指标；支持合理的排序或筛选。
- **重置与全屏**：提供恢复默认参数/重新绘制操作；复杂图表提供全屏查看，并确保退出后图表尺寸重新计算。
- **可复现信息**：导出或结果区域应能让用户获知数据来源、列映射和关键参数；需要审计的工具可额外导出参数 JSON 或生成分析摘要。

#### 5.6.6 导出规范

```ts
// Plotly 工具的最小导出能力；PNG 的 scale 可按目标 DPI / 96 计算
await Plotly.downloadImage(plotElement, {
  format: 'png', // 同时提供 'svg'
  filename: '<tool_key>_plot',
  width,
  height,
  scale: targetDpi / 96,
})
```

- PNG 用于演示和报告插图，至少可选择 300、600、1000 DPI 或等效倍率；SVG 用于论文排版和后续矢量编辑。两种格式都必须可用。
- 默认导出尺寸跟随当前图表容器；开启自定义尺寸时使用用户输入的宽高，且 SVG 不额外套用 DPI 概念。
- 导出文件名使用稳定的 `<tool_key>_plot` 前缀，可附加日期或用户填写的实验名；不得使用随机临时文件名。
- 导出前验证图表实例和数据有效，避免生成空白图片；导出失败时通过 `useMessage()` 告知用户。

#### 5.6.7 图形绘制工具验收清单

- [ ] 支持上传、粘贴和示例数据，且能显示解析后的表头与有效行数。
- [ ] 具备自动列识别和手动列映射；无效或缺失字段会给出明确提示。
- [ ] 核心计算、颜色、坐标轴、标题、标签、样式和导出参数均可配置。
- [ ] 含分类分组/系列的图表使用离散颜色、图例和 hover 同步展示；相同分组在重绘与导出中保持同色。
- [ ] 连续变量使用连续色板和 colorbar；类别数超过默认色板容量时不会静默重复颜色。
- [ ] 自动与手动坐标范围均正确，手动范围能阻止 `min >= max` 的无效提交。
- [ ] 图表支持 hover、主题切换、搜索/重点对象标注、统计摘要和处理后数据表。
- [ ] 支持 PNG 与 SVG 导出，能选择容器尺寸或自定义尺寸。
- [ ] 大数据量下不会默认渲染无限标签，切换页面后图表实例已正确销毁。
- [ ] 处理器中的解析、列识别、数值转换、核心计算和图表配置具备定向测试或可重复的验证样例。

---

## 六、页面布局规范

### 6.1 标准页面骨架(紧凑布局)

```vue
<template>
  <div class="xxx-page">
    <!-- 1. 纯身份页头:共享 PageHeader，不放主操作 -->
    <PageHeader title="工具标题" subtitle="一句话说明工具用途" back-to="/tools" back-label="返回工具箱" />

    <!-- 2. 主体:左参数 + 中工作区 + 右辅助(可选) -->
    <div class="xxx-layout">
      <aside class="param-panel"><!-- NCollapse 参数 --></aside>
      <main class="work-area"><!-- 图表/结果 --></main>
      <aside class="side-panel"><!-- 统计/列表,可选 --></aside>
    </div>
  </div>
</template>
```

### 6.2 根容器与留白(强制值)

工具页面**不设外层 padding**——`DefaultLayout.vue` 的 `contentStyle` 已对 `/tools` 与 `/tools/*`(非全屏)设 `padding: 0`,由页面根自控单层 padding,避免双层留白。

```css
.xxx-page {
  padding: 40px 24px 24px; /* 桌面端页头与导航留白；DefaultLayout 外层为 0 */
  min-height: 100%;
  box-sizing: border-box;
}
.page-header { margin-bottom: 24px; }
.xxx-layout {
  display: grid;
  grid-template-columns: 300px 1fr 280px;  /* 左参数 / 中工作区 / 右辅助 */
  gap: 16px;              /* 卡片间距统一 16px */
  align-items: start;
}
```

- **两栏工具**(无右侧辅助):`grid-template-columns: 320px 1fr;`
- **单栏工具**(纯结果):`grid-template-columns: 1fr;`
- 左参数面板宽度建议 280–360px,右侧辅助 260–300px。

### 6.3 卡片样式(强制)

所有白色面板(参数面板、结果卡片、辅助面板)统一:

```css
.param-panel,
.work-card,
.side-panel {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 12px;          /* 卡片内边距 12px(参数面板);结果卡片 8–12px */
  max-height: calc(100vh - 120px);  /* 超出滚动,避免整页滚动 */
  overflow-y: auto;
}
```

### 6.4 响应式(强制)

```css
@media (max-width: 1200px) {
  .xxx-layout { grid-template-columns: 1fr; }  /* 三栏/两栏退化为单栏堆叠 */
  .param-panel, .side-panel { max-height: none; }
}
@media (max-width: 768px) {
  .xxx-page { padding: 24px 12px 16px; }
}
```

### 6.5 Plotly 图表容器

```css
.plot-card {
  position: relative;
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 8px;
  min-height: 540px;       /* 图表可视高度 ≥ 540px */
}
.plot-container {
  width: 100%;
  height: 560px;           /* 固定高度,Plotly 需要明确尺寸 */
}
.plot-area.fullscreen .plot-container { height: calc(100vh - 120px); }
```

Plotly layout 的 `margin` 用紧凑值:`{ t: 40, r: 30, b: 60, l: 60 }`。

---

## 七、组件使用规范(Naive UI)

### 7.1 选型约定

| 场景 | 组件 | 关键 props |
|------|------|-----------|
| 参数折叠分组 | `NCollapse` + `NCollapseItem` | `arrow-placement="left"`, `:default-expanded-names="[...]"` |
| 数值输入 | `NInputNumber` | `:show-button="false"`, `size="small"`, `:step` 按字段语义 |
| 文本输入 | `NInput` | `size="small"` |
| 下拉选择 | `NSelect` | `size="small"`, options 形如 `{label, value}` |
| 开关 | `NSwitch` | `size="small"` |
| 单选互斥(模式) | `NRadioGroup` + `NRadioButton` | `size="small"` |
| 颜色 | `NColorPicker` | `:show-alpha="false"`, `size="small"` |
| 文件上传 | `NUpload` | `:default-upload="false"`, `:max="1"`, `accept` |
| 数据表格 | `NDataTable` | `:pagination="{pageSize:20}"`, `size="small"`, `:scroll-x` |
| 空状态 | `NEmpty` | 图表区无数据时占位 |
| 加载 | `NSpin` | 渲染中遮罩 |
| 统计数字 | `NStatistic` | 右侧统计面板 |
| 消息反馈 | `useMessage` | `message.success/error/warning/info` |

### 7.2 按钮层级(强制)

| 层级 | 用法 | 样式 |
|------|------|------|
| 主操作 | 「生成图表」「运行分析」等触发核心计算 | `type="primary"`, `size="small"`, 带 `:loading` |
| 次操作 | 导出 PNG/SVG、重置视图 | `size="tiny"`, `secondary` |
| 文字操作 | 返回工具箱、示例数据 | `text` 或 `quaternary` |

```vue
<NButton size="small" type="primary" :loading="plotting" @click="generate">
  <template #icon><NIcon><BarChartOutline /></NIcon></template>生成图表
</NButton>
<NButton size="tiny" secondary @click="exportImage('png')">PNG</NButton>
<NButton text @click="router.push('/tools')">返回工具箱</NButton>
```

### 7.3 图标导入

```ts
import { NIcon } from 'naive-ui'
import { ArrowBackOutline, BarChartOutline, DownloadOutline, SparklesOutline } from '@vicons/ionicons5'
```

### 7.4 下拉浮层与提示文案防遮挡(强制)

`NSelect`、`NDatePicker`、`NPopselect` 等组件的浮层默认 teleport 到 `<body>`，会覆盖在页面内容之上。参数面板空间窄、控件密，必须遵守：

1. **提示文案放在下拉控件上方，不要放下方**：列映射说明、格式提示（如"状态兼容 1/0、Dead/Alive…"）写在该控件组的**顶部**或 label 行内，禁止紧跟在 `NSelect` 后面——下拉菜单向下展开时会正好盖住它。
2. **连续多个下拉时，提示统一上移到组首**：一组 2 个以上的连续 `NSelect`（如列映射区），共用提示放在第一个控件之前，不要插在某个控件后面。
3. **验证方式**：实现后必须实际点开每个下拉，确认展开态不遮挡任何说明文字、校验 `NAlert` 和其它控件的关键信息；窄屏（≤768px）下也要检查一遍。
4. 浮层被裁剪（而非遮挡）时才考虑 `:to="false"` 挂回父容器；默认保持 teleport 到 body，不要在滚动面板内强行内联浮层。

---

## 八、样式与主题规范

### 8.1 CSS 变量(强制,禁止硬编码颜色)

| 变量 | 用途 | 亮色回退 |
|------|------|---------|
| `var(--neutral-bg)` | 页面灰底 | — |
| `var(--neutral-card)` | 卡片白底 | `#fff` |
| `var(--neutral-border)` | 边框 | `#e5e6eb` |
| `var(--neutral-text-1)` | 主文字 | `#1d2129` |
| `var(--neutral-text-2)` | 次文字 | `#4e5969` |
| `var(--neutral-text-3)` | 辅助文字 | `#86909c` |
| `var(--arco-primary)` | 主色 | `#165DFF` |
| `var(--arco-primary-light)` | 主色浅(选中态) | — |

所有颜色必须用变量并带亮色回退:`color: var(--neutral-text-1, #1d2129);`。

### 8.2 暗黑模式

- **CSS 层**:变量已在全局定义,卡片/文字自动适配;图表内固定色用 `themeStore.isDark` 切换调色板。
- **Plotly/ECharts 层**:监听 `isDark` 重新渲染,切换 `plot_bgcolor`/`paper_bgcolor`/字体颜色:

```ts
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)
watch(isDark, () => renderPlot())
// buildPlotlyFigure(..., isDark.value, ...) 内部按 isDark 选调色板
```

### 8.3 scoped 样式

- 每个工具视图用 `<style scoped>`,避免污染全局。
- 穿透 Naive UI 内部类用 `:deep()`,如 `.param-panel :deep(.n-collapse-item__header) { font-size: 13px; }`。

---

## 九、交互与数据流规范

### 9.1 数据加载

- **onMounted 自动载入示例数据**,让用户进入页面即见图,不要求先上传:

```ts
onMounted(() => { loadSample() })
```

- 文件上传 / 粘贴 / 示例数据三种入口,统一走 `loadTable(headers, rows, fileName)` → `updatePipeline()`。
- 解析失败用 `message.error` 提示,不抛异常打断。

### 9.2 自动更新(debounce)

- 参数变化用 `watch` + 300ms debounce 触发重算,避免拖动滑块时频繁渲染:

```ts
let debounceTimer: ReturnType<typeof setTimeout> | null = null
function schedulePipeline() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(updatePipeline, 300)
}
watch(() => [form.pvalCutoff, form.lfcCutoff, /* ...所有参数 */], schedulePipeline, { deep: false })
```

### 9.3 显式生成按钮(强制)

- 工具栏**必须有一个 `type="primary"` 的主操作按钮**(「生成图表」/「运行分析」),点击立即强制重算(跳过 debounce)。
- 作用:给用户明确控制感;自动渲染失败时的兜底入口。

### 9.4 组件卸载清理

```ts
onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  const el = document.getElementById(PLOT_DIV_ID)
  if (el) Plotly.purge(el)   // Plotly 必须显式释放,否则内存泄漏
})
```

---

## 十、数据处理模块规范(`<tool>Processor.ts`)

复杂工具的数据处理与图表配置**必须抽到独立的处理器文件**,视图只管交互。处理器是**纯函数模块,不持有状态、不依赖 Vue**。

### 10.1 结构约定

```ts
// volcanoProcessor.ts
import * as Plotly from 'plotly.js-dist-min'

// 1. 类型定义
export interface VolcanoConfig { /* 所有可调参数 */ }
export interface VolcanoRow { /* 单行数据 */ }
export interface ProcessedResult { rows: VolcanoRow[]; stats: ...; axisRange: ... }

// 2. 默认值(供视图初始化)
export const DEFAULT_CONFIG: VolcanoConfig = { ... }
export const DEFAULT_COLORS: VolcanoColors = { ... }

// 3. 解析函数(纯)
export function parseDelimited(text: string): ParsedTable { ... }
export function autoDetectColumns(cols: string[]): ColMap { ... }

// 4. 核心处理 pipeline(纯)
export function processVolcanoData(raw, colMap, config): ProcessedResult { ... }

// 5. 图表配置生成(纯,接收 isDark)
export function buildPlotlyFigure(rows, config, axisRange, isDark, focusGene?): PlotlyFigure { ... }

// 6. 辅助
export function formatP(n: number): string { ... }
export function genSampleData(): ParsedTable { ... }
```

### 10.2 视图与处理器的边界

| 职责 | 归属 |
|------|------|
| 响应式状态(form / colMap / processed) | 视图(`<Tool>View.vue`) |
| 数据清洗、统计、坐标轴计算 | 处理器(`processXxx`) |
| Plotly/ECharts 配置对象生成 | 处理器(`buildXxxFigure`) |
| 主题调色板选择 | 处理器(接收 `isDark` 参数) |
| DOM 操作、事件、消息提示 | 视图 |
| 调用 `Plotly.react` / `Plotly.purge` | 视图 |

---

## 十一、作用域隔离与全屏工具排外规则(重要)

### 11.1 紧凑布局的作用域

`DefaultLayout.vue` 的 `contentStyle` 用路由判断控制主内容区 padding,**只对工具箱区域生效**:

```ts
const contentStyle = computed(() => {
  if (route.meta.fullscreen) return 'padding: 0; ...'              // 全屏工具
  const isToolsArea = route.path === '/tools'
    || (route.path.startsWith('/tools/') && route.path !== '/tools/jbrowse')
  if (isToolsArea) return 'padding: 0; ...'                        // 工具箱紧凑
  return 'padding: 24px; ...'                                      // 其他页面不变
})
```

- 非工具页(首页、仪表板、任务、报告等)**保持 24px**,不受影响。
- 工具页(非全屏)外层 `padding: 0`,由页面根统一控制桌面 `40px 24px 24px`、移动端 `24px 12px 16px`。

### 11.2 全屏工具(JBrowse 模式)排外

**「Web 基因组浏览器」(JBrowse)及任何 `fullscreen: true` 的工具,外层仍不受 DefaultLayout 的普通 padding 影响**,但页面内部必须遵守本规范的页头与工具栏层级；画布区域按 §19.7「全屏画布工具沉浸布局基线」铺满剩余高度（flex 链 + 480px 兜底、页面级无纵向滚动、全屏沉浸模式与弹层 teleport 规则）。

技术保证(双重保险):
1. `fullscreen` 分支在 `contentStyle` 中**最先判断**,直接返回 `padding: 0`,不进入工具箱分支。
2. 工具箱分支的 `isToolsArea` 判断中**显式排除 `/tools/jbrowse``,即便 fullscreen meta 被误删也不会被紧凑化。

**新增全屏工具时**:在路由 meta 加 `fullscreen: true` 即可自动走排外分支;若希望它也被排除在工具箱紧凑分支外,在 `isToolsArea` 判断里追加 `&& route.path !== '/tools/<key>'`。

### 11.3 禁止事项

- 禁止在工具页面根容器设 `max-width`(必须流式 `width: 100%`,大屏铺满)。
- 禁止在工具页面外层再套一层带 padding 的 wrapper(会造成双层留白)。
- 禁止硬编码颜色(必须走 §8.1 CSS 变量)。
- 禁止在视图中写超过 ~50 行的数据处理逻辑(抽到 processor)。

---

## 十二、可视化与导出规范

### 12.1 图表渲染

- 用 `Plotly.react(container, figure.data, figure.layout, figure.config)` 增量更新,不用 `newPlot`。
- 大数据量(>5000 点)用 `scattergl` 类型:`const useGL = rows.length > 5000`。
- 容器用固定 `id`,通过 `document.getElementById` 获取(不依赖 ref 时序)。

### 12.2 导出

- **PNG 高 DPI**:用 `Plotly.downloadImage` 的 `scale = dpi / 96`,DPI 选择器默认 1000(可选 300/600/1000)。
- **SVG 矢量**:不设 scale,直接导出。
- **文件名**:`<base>_<YYYYMMDD_HHMMSS>_<dpi>dpi.png`,含时间戳与 DPI。

```ts
const dpi = exportDpi.value
const scale = dpi / 96
Plotly.downloadImage(container, {
  format: 'png',
  filename: `${baseName}_${formatTimestamp()}_${dpi}dpi`,
  width: Math.round(rect.width),
  height: Math.round(rect.height),
  scale,
} as any)  // @types/plotly.js-dist-min 的 DownloadImgopts 缺 scale 字段,用 as any 逃逸
```

> `@types/plotly.js-dist-min` 类型不完整(`DownloadImgopts` 不含 `scale`、要求 `width/height` 必填),实际 Plotly 支持,用 `as any` 逃逸并在注释说明。

---

## 十三、上线检查清单

新增工具提交前,逐项确认:

- [ ] `tools_setting.yaml` 已注册,`key`/`route`/`icon`/`enabled`/`order` 字段完整
- [ ] `router/index.ts` 已加 `tools/<key>` 子路由,`name` 为 `tools-<key>`,`requiresAuth: true`
- [ ] 用了新图标已在 `ToolsHubView.vue` 的 `ICON_MAP` 登记
- [ ] 视图文件命名 `<Tool>View.vue`,根 class `<key>-page`,布局 class `<key>-layout`
- [ ] 根容器桌面 `padding: 40px 24px 24px`、移动端 `24px 12px 16px`,无外层 wrapper、无 `max-width`
- [ ] 页头使用 `PageHeader`:返回按钮 + 标题 + 副标题(纯身份区,至多 1 个弱操作),`margin-bottom: 24px`;主操作不在页头,见 §十八
- [ ] 主体 `gap: 16px`,卡片 `var(--neutral-card)` + 12px 圆角 + 12px padding
- [ ] 响应式:`@media (max-width: 1200px)` 退化为单栏
- [ ] 所有颜色走 CSS 变量,无硬编码
- [ ] 暗黑模式:图表监听 `isDark` 重渲染
- [ ] `onMounted` 载入示例数据,进入即见内容
- [ ] 参数变化 300ms debounce 自动更新
- [ ] 有且仅有 1 个 `type="primary"` 主操作按钮,位于吸底操作栏 `ToolActionBar.vue`(生成/提交/检索);示例/刷新按钮弱化并归位语义卡片
- [ ] `onUnmounted` 清理定时器与 Plotly 实例
- [ ] 复杂逻辑已抽到 `<tool>Processor.ts`(纯函数)
- [ ] `npm run build` 通过(`vue-tsc` 严格类型检查)
- [ ] 构建后 `docker restart omichub-nginx`(bind mount 换 inode 必须重启,否则跑旧产物)
- [ ] 若是全屏工具,路由 meta 加 `fullscreen: true`,并在 `isToolsArea` 排除

---

## 十四、参考实现索引

| 工具 | 视图 | 参考价值 |
|------|------|---------|
| 火山图 | `VolcanoPlotView.vue` + `volcanoProcessor.ts` | **首选样板**:三栏布局、参数折叠、坐标轴配置、高 DPI 导出、Plotly 暗黑模式 |
| Venn / UpSet | `VennUpsetView.vue` + `vennUpsetProcessor.ts` | Plotly shapes 组合绘制韦恩/UpSet 图、图内全英文标注、`color_1_extended` 默认色板、点击选中联动、高 DPI 导出 |
| BLAST | `BlastSearchView.vue` | 两栏(输入 + 结果)、表格结果展示 |
| FASTQ 质控 | `FastqQCView.vue` | 两栏、文件上传、统计卡片 |
| 绘图工坊 | `PlotWorkshopView.vue` | ECharts 集成、多图表类型切换 |
| GO / KEGG 富集 | `KeggEnrichmentView.vue` | 两栏、R Docker、后端配置驱动(`config_dir`) |
| JBrowse | `JBrowseViewer.vue` | **全屏画布工具样板**(§19.7):查看区 flex 铺满 + 480px 兜底、48px 扁平工具条、`PageHeader` compact 变体、全屏沉浸模式(Fullscreen API + fixed 兜底)、弹层 teleport 到页根、同源 iframe 欢迎屏居中注入;不参考普通紧凑布局 |
| 工具箱列表 | `ToolsHubView.vue` | 卡片网格、ICON_MAP、API 拉取 |

---

*本规范由现有工具实现提炼,改动规范请同步更新本文档。*


---

## 十五、AI 助手联动架构

OmicHub 的「AI 助手」页面（Agent 调度中枢）不仅支持通用对话，还能直接调用平台生信工具箱中的工具完成计算、绘图、富集等任务。本章说明工具箱如何与 AI 助手打通，以及新增工具时需要遵守的约定。

### 15.1 总体数据流

```
用户消息/附件
    │
    ▼
Agent 调度中枢 (chat_service.py::stream_agent_chat)
    │ 1. 查 Agent → 组装模型/系统词/MCP server/工具列表
    │ 2. 送 LLM（流式）
    ▼
LLM 决定调用工具（OpenAI function call）
    │
    ▼
MCPClient.call_tool(server, tool_name, arguments)
    │  _builtin transport_ → omichub-tools preset
    ▼
ToolBridgeService.execute(user_id, tool_name, arguments)
    │ 1. 参数校验 + upload:// 解析
    │ 2. 按 invocation_mode 分发执行
    ▼
具体工具实现（service / shim / async / open_page）
    │
    ▼
双通道结果
    ├─ llm_payload：精简摘要，回灌 LLM 用于下一轮对话
    └─ ui_payload：完整图/表/任务信息，透传给前端渲染
```

### 15.2 工具注册：从 tools_schema.yaml 到 LLM function

`tool_configs/tools_schema.yaml` 是 AI 助手工具的唯一注册表。每个工具条目包含：

| 字段 | 作用 |
|------|------|
| `name` | LLM 看到的 function 名，必须以 `omichub_` 开头 |
| `description` | LLM 判断是否调用该工具的依据 |
| `input_schema` | OpenAI functions 参数 schema |
| `invocation_mode` | 执行方式：`backend_sync` / `backend_shim` / `backend_async` / `open_page` |
| `service` + `method` | `backend_sync` 时进程内调用的 service 方法 |
| `shim_module` | `backend_shim` 时调用的轻量 Python 模块 |
| `llm_result_fields` | 回灌 LLM 的字段白名单（建议 ≤3KB） |
| `ui_result_fields` | 透传给前端的字段白名单 |

启动时 `AgentService.assemble_context()` 自动把 `tools_schema.yaml` 中的工具注入为 Agent 可调用的 OpenAI functions，并在系统提示词里追加工具清单（`schema_loader.build_system_hint()`）。

### 15.3 双通道输出规范

工具实现返回的原始 dict 经过 `ToolBridgeService._package()` 后统一为：

```python
{
    "success": True,
    "is_error": False,
    "llm_payload": {...},   # 给 LLM 看
    "ui_payload": {...},    # 给前端看
}
```

#### 15.3.1 llm_payload（回灌 LLM）

- 必须精简，默认不超过 3KB。
- 只放文字摘要、统计、Top 列表、错误说明等 LLM 能读懂的内容。
- 禁止放完整 Plotly JSON、二进制、大表格。

#### 15.3.2 ui_payload（前端渲染）

前端 `KimiMessageItem.vue` 目前识别以下 ui_payload 字段：

| 字段 | 前端行为 |
|------|---------|
| `plotly_figure` | 用 Plotly.js 渲染交互式图表 |
| `table_data` / `tableData` | 用 `NDataTable` 展示表格 |
| `confirm_card` | 显示二次确认卡片 |
| `route` | 显示「前往工具页」引导卡片 |
| `task_id` + `progress_url` / `result_url` | 显示异步任务进度卡片 |

新增可视化工具时，ui_payload 里必须包含 `plotly_figure: {data: [...], layout: {...}}`，前端即可自动出图。

### 15.4 文件上传协议：`upload://file_id`

AI 助手上传的文件保存在 `{data_root}/users/{uid}/workspace/chat-uploads/`。当工具参数需要大段文本（如 `data_text`、`gene_text`）时，LLM 可以传 `upload://file_id` 引用已上传文件，而不是把整个 CSV 塞进参数。

约定：

- 参数 description 里必须写明「也支持 upload://file_id」。
- 系统提示词规则里明确要求 LLM：大文件用 `upload://file_id`，禁止留空。
- `ToolBridgeService._resolve_upload_refs()` 负责把引用解析为文件内容。

示例参数描述：

```yaml
data_text:
  type: string
  description: CSV/TSV 格式的差异表达表文本，含 log2FC 与 p-value 列；也支持 upload://file_id 引用已上传文件
```

### 15.5 前端 SSE 事件消费

Agent 调度中枢通过 `/api/v1/chat/stream` 返回 SSE 事件，前端 `useAgentChatStream.ts` 解析：

| 事件类型 | 含义 | 前端处理 |
|---------|------|---------|
| `text` | LLM 生成的文字 token | 追加到当前 assistant 消息 |
| `tool_call` | LLM 发起工具调用 | 在 assistant 消息的 `toolCalls` 里新增 running 状态卡片 |
| `tool_result` | 工具执行完成 | 匹配 `tool_call_id`，回填 `result` / `uiPayload`，更新状态为 success/error |
| `error` | 服务端/模型错误 | 显示错误态 |
| `done` | 整轮结束 | 结束流式状态 |

`KimiMessageItem.vue` 中：

```ts
const plotlyCharts = computed(() => {
  // 优先从 tool.uiPayload.plotly_figure 取图
  // 兼容 result.ui_payload.plotly_figure / result.plotly_figure
})
```

工具卡片会同时显示：工具名、参数、运行状态、LLM 摘要结果、图表/表格/确认卡/任务进度卡。

### 15.6 新增一个 AI 助手可用工具的步骤

1. **实现工具逻辑**：在 `src/omichub/tools/` 下新增 service 或 shim，返回原始 dict（含 `success` + 可选 `plotly_figure` / `table_data` 等）。
2. **注册 schema**：在 `tool_configs/tools_schema.yaml` 新增条目，写好 description、input_schema、llm_result_fields、ui_result_fields。
3. **选择 invocation_mode**：
   - 轻量快速出图 → `backend_shim`
   - 复用现有 service → `backend_sync`
   - 长时间计算 → `backend_async`（返回 `task_id`）
   - 需要复杂交互 → `open_page`（返回 `route`）
4. **确认 ui_payload 字段**：出图必须含 `plotly_figure`；表格必须含 `table_data`。
5. **测试链路**：
   - `pytest tests/unit/tools/test_tool_bridge.py` 验证 ToolBridge 分发。
   - 在 AI 助手页面发送自然语言请求，确认工具被调用、图表/表格正确渲染。

### 15.7 常见问题排查

| 现象 | 可能原因 | 排查方向 |
|------|---------|---------|
| LLM 不调用工具 | 工具描述不清 / 系统提示词未注入 | 检查 `tools_schema.yaml` description 和 `build_system_hint()` |
| 提示缺少必填参数 | LLM 没传文件内容 | 确认参数 description 写了 `upload://file_id` |
| 工具执行成功但前端没图 | `ui_payload` 里没有 `plotly_figure` / 字段名不对 | 检查 `ui_result_fields` 和工具返回值 |
| 工具结果没关联到工具卡片 | `tool_call_id` 为空或前后端不匹配 | 检查 LLM provider 是否返回 tool_call id |
| 图表渲染报错 | Plotly figure 结构非法 | 用 `python -m omichub.tools.shims.xxx` 单独测试返回值 |

---

## 十六、Apple Design 交互与动效规范(工具箱)

> 自 2026-07-17 起,工具箱列表页(`ToolsHubView.vue`)与工具卡片(`ToolCard.vue`)按 Apple
> 「流体界面」(Fluid Interfaces, WWDC 2018)原则设计。新增/修改工具箱 UI 时必须遵守本节约定,
> 保持全站动效语言一致。

### 16.1 核心原则

| 原则 | 要求 |
|------|------|
| **响应即时** | 按下(pointer-down)立刻给出反馈,不等松手;按压态过渡时长固定 `100ms` |
| **弹簧缓动** | 所有交互过渡统一用 `cubic-bezier(0.16, 1, 0.3, 1)`(模拟临界阻尼弹簧,无过冲);禁止 `transition: all` 和默认 `ease` |
| **动量才弹** | 无手势动量的 UI(卡片、面板、模态)一律临界阻尼不回弹;回弹只允许出现在拖拽/甩动之后 |
| **方向暗示** | 中间帧要预示结果:可导航卡片的箭头在悬停时向「前进」方向位移(`translateX(3px)`) |
| **空间一致** | 展开/收起等可逆动作使用同一元素的连续运动(如箭头旋转 90°),禁止两个图标瞬时替换 |
| **材质纵深** | 彩色图标块加顶部内高光 `inset 0 1px 0 rgba(255,255,255,0.28)`;浮起阴影用「大面积柔光 + 近身接触影」双层结构 |
| **反馈有度** | 不可交互的表面不做悬停位移;反馈只出现在可操作的元素上 |

### 16.2 标准参数(直接复用)

```css
/* 交互过渡(悬停/聚焦等柔和反馈) */
transition: <prop> 320ms cubic-bezier(0.16, 1, 0.3, 1);

/* 按压反馈(即时) */
:active {
  transform: scale(0.98);
  transition-duration: 100ms;
}

/* 卡片/列表项入场(交错 40ms,仅上浮 + 淡入,无缩放弹跳) */
@keyframes cardIn {
  from { opacity: 0; transform: translate3d(0, 10px, 0); }
  to   { opacity: 1; transform: translate3d(0, 0, 0); }
}
animation: cardIn 420ms cubic-bezier(0.16, 1, 0.3, 1) both;

/* 键盘焦点(必须可见) */
:focus-visible {
  outline: 2px solid var(--arco-primary, #165DFF);
  outline-offset: 2px;
}

/* 减少动态效果:去掉位移/缩放/旋转,保留不透明度变化 */
@media (prefers-reduced-motion: reduce) { /* transition: none; transform: none */ }
```

### 16.3 无障碍基线

- 可点击的非按钮元素(如卡片)必须 `role` + `tabindex="0"` + `@keydown.enter` / `@keydown.space.prevent`,并提供 `:focus-visible` 描边。
- 三个无障碍媒体查询按需响应:`prefers-reduced-motion`(去位移,保留淡入淡出)、`prefers-reduced-transparency`(去毛玻璃改实色)、`prefers-contrast`(边框加实)。
- 排他控件(展开/收起)加 `aria-label`,说明动作而非状态。

### 16.4 字距规则

- 大标题/大数字:负字距(`-0.01em` ~ `-0.02em`),可启用 `font-optical-sizing: auto`。
- 正文(13–16px):字距保持 `0` 或 `-0.01em`,用字重而不是字距建立层级。

### 16.5 本次落地记录(2026-07-17)

| 文件 | 修改内容 |
|------|---------|
| `components/bio-tools/ToolCard.vue` | 缓动改弹簧曲线并限定属性;新增 `:active` 100ms 按压收缩;悬停阴影改双层;箭头悬停右移 3px;图标块加内高光与投影;补 `role="link"`、键盘触发、`:focus-visible`、`prefers-reduced-motion` |
| `views/BioTools/ToolsHubView.vue` | 展开/收起改为单箭头旋转 90°(加 `aria-label`);卡片网格交错入场(40ms 步进);分组标题字重 500→600、字距 -0.01em;补 `prefers-reduced-motion` |

---

*本章节与 `tools_update.md` 互为补充：后者记录落地计划与排期，本文档记录架构规范与实现约定。*

## 十七、工具详情页页头统一规范

所有工具详情页的返回入口必须与工具标题信息保持同一视觉组，避免返回按钮贴在标题上沿：

- 标准工具页统一使用 `frontend/src/components/PageHeader.vue`。
- `PageHeader` 的 `backTo` 通常指向 `/tools`，`backLabel` 使用“返回工具箱”。
- 返回按钮在标题与副标题文本块之间垂直居中，而不是与 `h1` 顶部对齐；共享实现使用 `.page-header-main { align-items: center; }`。
- 页头是纯身份区：只放返回按钮 + 标题 + 副标题，最多保留 1 个弱全局操作（text/ghost），禁止出现主操作按钮与“示例数据/生成/刷新”类按钮；主操作一律进吸底操作栏，见 §十八。
- 图标按钮必须保留 Tooltip 与无障碍名称；窄屏下页头允许换行，但返回按钮仍需保持可见和键盘可达。
- JBrowse、云端沙盒终端等全屏画布工具同样复用共享 `PageHeader`，通过 `compact` 变体压缩空间（见下条与 §19.7），不再自建页头。

`PageHeader` 的 `compact` 变体（可选 prop，默认 `false`，不传则行为与原版完全一致）：

| 行为 | 默认 | `compact` |
| --- | --- | --- |
| 垂直内边距 | 无（仅 `margin-bottom: 24px`） | `padding: 12px 0`、`margin-bottom: 0` |
| 副标题 | 标题下方 14px、`var(--text-secondary)` | 标题右侧内联、`12px` 灰色小字（`var(--text-tertiary)`），超长省略；≤640px 折行到标题下方 |
| 标题与返回按钮 | 字号/字重/配色不变 | 同左（压缩的是空间分配，不是视觉语言） |

`compact` 只允许用于 `fullscreen: true` 的画布类工具页（查看区需要最大化视口占比）；普通工具页继续使用默认页头，保证工具之间页头零抖动。

新增或修改工具时，先检查共享 `PageHeader`，只有在全屏工具确有布局约束时才新增局部页头实现。

## 十八、页头操作区与吸底操作栏规范（强制）

背景：工具页的主操作（生成图表 / 提交分析 / 开始检索）曾放在页头，用户在下方表单填完数据后需滚回页面顶部才能点击；“示例数据 / 刷新”类按钮也堆在页头，与页面身份混在一起。本章统一操作区的归属与样式。

### 18.1 三条归属规则

1. **页头 = 纯身份区**。只放：返回按钮 + 标题 + 副标题。最多保留 1 个弱全局操作（`text`/`ghost`，如 BLAST 的“任务中心”）。页头禁止出现：主操作按钮（`type="primary"`）、示例数据按钮、生成/提交按钮、刷新按钮。
2. **主操作 → 吸底操作栏**。每个有“生成/提交/检索”类主操作的页面，主按钮必须放入共享吸底操作栏 `frontend/src/components/ToolActionBar.vue`，保证在任意滚动位置都可见、可点。**全页全局只允许 1 个 `type="primary"` 按钮**，即吸底栏中的主按钮。
3. **示例数据 / 刷新 → 归位语义卡片**。这两类按钮跟随其作用的数据区域，而不是页头：
   - “示例数据”放进数据输入/上传卡片的标题行，弱化为 `text` 按钮，文案统一为“试试示例数据”（带 ✨ `SparklesOutline` 图标），永远不用主按钮权重。
   - “下载示例数据”改为格式说明旁的文字链接“下载示例文件（.csv）”。
   - “刷新物种”放进物种选择卡片（`NFormItem` 的 `#label` 插槽），“刷新历史”放进历史卡片（`NCollapseItem` 的 `#header-extra` 插槽）。均为 icon-only ghost 小按钮（⟳ `RefreshOutline` 16px），带 hover Tooltip，加载时图标旋转。

### 18.2 吸底操作栏组件契约（`ToolActionBar.vue`）

Props：

| Prop | 类型 | 说明 |
| --- | --- | --- |
| `ready` | `boolean` | 表单是否满足提交条件，决定状态点颜色与主按钮可用性 |
| `readyText` | `string` | 就绪时状态文案，如“参数已就绪” |
| `notReadyText` | `string` | 未就绪时状态文案，如“待上传数据文件” |
| `notReadyTip` | `string` | 未就绪时悬停主按钮的 Tooltip，说明缺什么 |
| `primaryLabel` | `string` | 主按钮文案（生成图表 / 提交分析 / 开始检索） |
| `primaryIcon` | `Component` | 主按钮图标（可选） |
| `loading` | `boolean` | 主按钮 loading 态 |

Emit：`action`（点击主按钮或按 ⌘/Ctrl+Enter 时触发）。

### 18.3 视觉与交互规范

- **定位**：`position: sticky; bottom: 0`（组件内实际 `bottom: 12px` 悬浮胶囊形态），`z-index` 高于内容卡片，滚动时始终悬浮在视口底部。
- **玻璃拟态**：半透明白 + `backdrop-filter: blur(12px)`（站点既有玻璃配方为 `rgba(255,255,255,0.72)` + `blur(20-24px) saturate(170%)`，暗黑模式 `rgba(17,22,34,0.62)`，通过 `:root[data-theme="dark"]` 覆盖）；顶部 1px 高亮边（白色 `rgba` 0.6~0.8），向上投影。
- **左侧 = 表单校验状态**：状态点（●）+ 文案。未就绪为灰色，文案如“待上传数据文件”；就绪为绿色（`#00b42a`），文案如“参数已就绪”。状态文案应具体指出还缺什么，而非泛泛的“未就绪”。
- **右侧 = 主按钮**：未就绪时 `disabled`，并用 `NTooltip` 包裹说明缺什么（disabled 按钮不派发鼠标事件，需用 `<span>` 包裹承接 hover）。就绪时高亮可点。
- **快捷键**：⌘+Enter（macOS）/ Ctrl+Enter（其他）触发主操作；按钮内以 `<kbd>⌘↵</kbd>` 提示（窄屏隐藏）。
- **占位**：吸底栏会占据文档流高度，页面内容自然收尾，不需要额外 padding 补偿；但需保证最后一张卡片不被吸底栏视觉遮挡（栏体为悬浮胶囊，与内容保留间距）。
- **动效**：遵循 §十六 Apple 动效规范，使用 `cubic-bezier(0.16, 1, 0.3, 1)`；状态点颜色变化、按钮 hover/`:active`（100ms）均需过渡；`prefers-reduced-motion` 下关闭动效。

### 18.4 移动端规范（≤640px）

- 吸底栏贴底通栏：`bottom: 0`、左右负 margin 撑满、去圆角；`padding-bottom: calc(12px + env(safe-area-inset-bottom))` 兼容全面屏 Home 指示条。
- 主按钮 `min-height: 44px` 且 `flex: 1` 占满宽度，保证触控目标 ≥44px。
- 隐藏 `⌘↵` 快捷键提示。
- 375px 宽度下内容不被吸底栏遮挡，无需横向滚动。

### 18.5 各页面落地映射

| 页面 | 移出页头的按钮 | 落地位置 |
| --- | --- | --- |
| 韦恩图 / UpSet（`VennUpsetView`） | 示例数据、生成图表 | 示例→集合列表输入卡片标题行；生成图表→吸底栏 |
| 组学绘图工坊（`PlotWorkshopView`） | 加载示例、下载示例数据 | 加载示例→数据上传卡片标题行（试试示例数据）；下载→格式说明旁文字链接；自动绘图，无吸底栏 |
| 湿实验计算器（`WetLabCalculatorsView`） | 示例数据 | 每个计算器面板输入区顶部各放一个“试试示例数据”；反应式计算，无吸底栏 |
| GO/KEGG 富集（`KeggEnrichmentView`） | COP1/HY5 示例、刷新物种、刷新历史、提交分析 | 示例→Gene ID 输入卡片；刷新物种→物种卡片；刷新历史→历史卡片；提交分析→吸底栏 |
| 序列检索 BLAST（`BlastSearchView`） | 开始检索 | 开始检索→吸底栏；“任务中心”可弱化为 text 保留在页头 |

### 18.6 验收清单

- [ ] 各工具页页头结构一致（返回 + 标题 + 副标题，至多 1 个弱操作），工具之间页头零抖动。
- [ ] 每页恰好 1 个 `type="primary"` 按钮，位于吸底栏。
- [ ] 吸底栏在任意滚动位置均可见；未就绪时主按钮 disabled + 灰状态点 + 具体缺失文案 + Tooltip。
- [ ] 示例数据 / 刷新按钮位于其语义卡片内，均为弱样式。
- [ ] 375px 移动端无遮挡，触控目标 ≥44px，吸底栏适配 `env(safe-area-inset-bottom)`。
- [ ] ⌘/Ctrl+Enter 可触发主操作。

## 十九、工具页面视觉统一实施基线（2026-07-25，新增工具直接复用）

本节是当前工具页的统一视觉基线，优先级高于本文档中早期的“16px 紧凑页边距”示例。新增工具先复制以下结构，再填充自己的参数和结果内容；不要为每个页面重新发明页头、间距或按钮样式。

### 19.1 页面层级

标准工具页固定为三层：

1. **标准页头**：共享 `frontend/src/components/PageHeader.vue`，只放返回按钮、标题和副标题。标题不添加 emoji；副标题为 `14px`、`var(--text-secondary)`，与标题间距 `8px`。页头与主体间距 `24px`。
2. **工具操作区**：只有确实需要一组全局控件时才使用独立工具栏卡片；不要把选择器、坐标框、上传按钮塞进 `PageHeader` 的 `actions` 插槽。
3. **工作区**：参数面板、图表、表格和结果卡片按工具功能组织，卡片之间统一 `16px` 间距。

标准根容器：

```css
.xxx-page {
  min-height: 100%;
  padding: 40px 24px 24px;
  box-sizing: border-box;
}

@media (max-width: 768px) {
  .xxx-page { padding: 24px 12px 16px; }
}
```

`DefaultLayout.vue` 的工具区域外层保持 `padding: 0`，避免出现双层留白。全屏路由也保持外层 `padding: 0`，但内部页头仍按上述间距设置，画布/终端区域再通过 flex 铺满剩余空间。例外：`fullscreen: true` 的画布类工具改用 §19.7 沉浸布局基线（`PageHeader` compact 变体 + 48px 扁平工具条 + 页面根 `padding: 0 16px 12px`）。

### 19.2 独立工具栏卡片

JBrowse、基因组浏览器、终端控制区等拥有多项全局控件的页面，工具栏使用以下基线：

```css
.tool-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 16px;
  border: 1px solid var(--neutral-border, #e5e7eb);
  border-radius: 12px;
  background: var(--neutral-card, #fff);
}

.tool-toolbar__primary,
.tool-toolbar__actions {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.tool-toolbar__actions { margin-left: auto; }
```

左侧放选择器、输入框和唯一主操作；右侧放上传、文件、帮助等弱操作。控件统一高度 `36px`、圆角 `8px`。窄屏时工具栏纵向堆叠，右侧操作取消 `margin-left: auto`，禁止横向滚动。

### 19.3 控件与按钮

- 唯一主操作使用项目主题蓝和 `type="primary"`，例如“跳转”“运行”“提交”。
- 上传、我的文件、刷新、帮助等次要操作使用白底 outline：`1px solid #d1d5db`、文字 `#374151`，hover 边框加深至 `#9ca3af`。
- 普通控件高度统一 `36px`，圆角统一 `8px`，同一工具栏内间距统一 `12px`。
- 图标统一使用 `@vicons/ionicons5` 线性图标；禁止用 emoji 作为坐标、状态或导航图标。
- 图标按钮必须有 Tooltip 和 `aria-label`；文字按钮必须保证文字不被截断。

### 19.4 选择器、坐标与长文本

- 参考基因组/资源选择器最小宽度 `240px`；选中态第一行显示中文名和版本号，第二行用 `12px` 灰色斜体显示拉丁学名或补充信息。
- 选项使用两行排版，不把完整信息拼成一行再依赖省略号；中文名、版本号不得截断。
- 坐标输入宽度建议 `220px`，placeholder 使用带千分位的示例，例如 `chr1:1,000,000-2,000,000`。
- 展示值可以自动补千分位，但解析必须兼容无逗号、带空格、大小写 `chr` 前缀的输入；格式化只改变展示，不改变业务解析。
- 同一个状态值只保留一个主展示位置。若视图区必须显示当前坐标，使用 `12px` 等宽字体状态条，并避免与工具栏重复渲染。

### 19.5 375px 验收标准

- 页头与导航之间至少 `24px`，标题、副标题、返回按钮不重叠。
- 工具栏控件可以换行或纵向堆叠，文字完整可读，无横向滚动。
- 主按钮和关键次要按钮触控区域不小于 `36px`；吸底主操作遵守 §十八的 `44px` 移动端要求。
- 卡片、弹窗、状态徽标完整显示，不被父级 `overflow: hidden` 或绝对定位裁切。

### 19.6 新增工具最小模板

```vue
<template>
  <div class="xxx-page" role="main" aria-label="工具名称">
    <PageHeader title="工具名称" subtitle="一句话说明" back-to="/tools" back-label="返回工具箱" />
    <section class="tool-toolbar" aria-label="工具控制栏">
      <div class="tool-toolbar__primary"><!-- 选择器、输入、唯一主按钮 --></div>
      <div class="tool-toolbar__actions"><!-- 上传、文件、帮助等 outline 操作 --></div>
    </section>
    <main class="xxx-layout"><!-- 参数 / 工作区 / 结果 --></main>
  </div>
</template>
```

提交前按 §十三检查清单验收，并额外检查桌面 `>=1024px` 与移动 `375px` 两个视口；涉及全屏画布的工具再确认画布仍能占满页头和工具栏以外的剩余高度。

### 19.7 全屏画布工具沉浸布局基线（2026-07-26，JBrowse 落地）

本节是 `fullscreen: true` 的**画布类工具**（嵌入外部渲染器、查看区即产品主体：JBrowse 基因组浏览器、云端沙盒终端等）的空间分配基线，由「Web 基因组浏览器」空间优化落地提炼。与 §19.1–19.3 的关系：

- **§19.2 卡片式工具栏**（border + radius 12 + card 背景）用于普通工具页；
- **本节扁平工具条**（透明背景 + 底部分隔线，约 48px）用于画布类工具——工具条与页头处于同一视觉层级，把全部纵向空间让给画布。

普通参数表单类工具**不要**套用本节，继续使用 §19.1–19.6。

#### 19.7.1 空间分配（强制）

```text
100vh
 ├─ 平台页头 56px（DefaultLayout top-nav，非工具页自有）
 ├─ 标题区 ≈64px（PageHeader compact：12px 垂直 padding + 内容）
 ├─ 工具条 ≈48px（控件 28px + 10px 垂直 padding + 1px 分隔线）
 ├─ 已选轨道条（可选，仅有选中项时出现）
 └─ 查看区 = 剩余全部高度（flex:1，min-height 480px 兜底）
页面左右仅 16px padding，不设 max-width、不做居中限宽
```

根容器与查看区：

```css
.xxx-page {
  height: 100%;            /* 依赖路由 meta.fullscreen 提供的有界 flex 链 */
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;        /* 页面级永不出现纵向滚动条 */
  padding: 0 16px 12px;    /* 左右 16px，垂直空间让给 PageHeader compact */
}

.xxx-canvas {
  flex: 1 1 auto;          /* 铺满剩余高度，禁止固定 px / auto 高度 */
  min-height: 480px;       /* 兜底：极端矮视口下查看区不被压缩到不可用 */
  position: relative;
  overflow: hidden;        /* 滚动交给画布内部（如 JBrowse iframe） */
}

@media (max-width: 768px) {
  .xxx-page { padding: 0 12px 12px; }
  .xxx-canvas { min-height: 360px; }
}
```

验收数值：打开会话后画布高度 ≥ 视口高度的 **70%**（720p 下约 75%，1080p 下约 84%）；1280px 与 1920px 宽度下页面无纵向滚动条，无双重滚动条。

#### 19.7.2 页头与工具条压缩合并

- 页头使用共享 `PageHeader` 的 `compact` 变体（见 §十七）：垂直 padding 12px、副标题内联为标题旁 12px 灰色小字。压缩的是空间分配，**标题字号/字重/配色/返回按钮样式与平台其他工具页一致**。
- 工具条去除卡片式大圆角大留白，改为与页头同层级的紧凑横条：

```css
.xxx-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;          /* 窄屏折行，禁止横向滚动 */
  box-sizing: border-box;
  min-height: 48px;
  padding: 10px 0;
  gap: 10px;
  border-bottom: 1px solid var(--neutral-border, #e5e6eb);
  background: transparent;  /* 与页头同一视觉层级，不用 card 背景 */
}
.xxx-toolbar :deep(.n-button),
.xxx-toolbar :deep(.n-base-selection),
.xxx-toolbar :deep(.n-input) { height: 28px; border-radius: 8px; }
```

- 控件排布沿用 §19.2/§19.4：左侧选择器（≥240px）+ 坐标输入（220px）+ 唯一主操作，右侧上传/我的文件等 outline 弱操作；选择器、输入、按钮的样式规则不变。

#### 19.7.3 全屏沉浸模式（画布类工具推荐配置）

工具条右侧放「全屏」图标按钮（`ExpandOutline` / 退出态 `ContractOutline`，Tooltip + `aria-label`）。行为契约：

1. **优先 Fullscreen API**：对页面根元素调用 `requestFullscreen()`，根元素进入浏览器 top layer，平台页头与侧边导航天然被隔离在外，无需手动隐藏；Esc 由浏览器原生退出。
2. **fixed 定位兜底**：API 不可用或请求被拒（旧 Safari、权限策略）时，给根元素加 `position: fixed; inset: 0; z-index: 1500; background: var(--neutral-bg);` 覆盖视口，并自行监听 `keydown` Esc 退出；再次点击按钮也可退出。两条路径用一个 `computed`（`isFullscreen || immersiveFallback`）统一驱动图标与文案。
3. **全屏态工具条保留可操作**：跳转、上传、我的文件等在全屏下必须可用——引出下条弹层规则。
4. **弹层 teleport 规则（强制）**：Fullscreen top layer 会屏蔽 fullscreen 元素之外的一切节点。页面内的 `NModal` / `NDrawer` 默认 teleport 到 `body`，全屏下会**不可见**。必须把弹层的 `to` 指向页面根元素（如 `:to="pageRootRef || undefined"`）；封装组件（如 `JbrowseFileDrawer`）需透传可选 `to` prop。非全屏时弹层行为不变（`to` 为空走默认 body）。
5. **卸载清理**：`onUnmounted` 中移除 `fullscreenchange` / `keydown` 监听；若离开页面时仍处于原生全屏，主动 `exitFullscreen()` 避免残留黑屏。
6. **z-index 分层**：兜底态 `1500` 高于平台 chrome（top-nav 100），低于 naive 弹层（2000+），保证全屏兜底态下弹层仍浮在页面之上。

#### 19.7.4 嵌入式画布的空状态适配（同源 iframe 场景）

当画布是同域嵌入的第三方应用（如 nginx 同域挂载的 `/jbrowse2/` iframe），其自带欢迎页往往顶部对齐，画布撑满后会出现「上半截内容、下半截大段空白」的割裂感。适配方式（**仅展示层，禁止触碰配置生成、数据接口与集成逻辑**）：

1. iframe `load` 后访问同源 `contentDocument`（跨域或不可访问时 `try/catch` 静默忽略）；
2. 按**文案特征**（如 "Start a new session"）定位欢迎屏容器，避免误伤正常工作视图；
3. 对容器祖先链补 `height: 100%`（已有内联高度的节点不动），父级设 flex 纵列，容器 `margin: auto` 吸收剩余空间实现垂直居中；欢迎屏自带的浮动按钮在 flex 上下文中改为绝对定位保持原视觉位置；
4. 用元素 `id` 标记做幂等快路径；因第三方应用可能在用户关闭会话后重新挂载欢迎屏（新节点丢标记），用节流（≥200ms）的 `MutationObserver` 重跑适配，组件卸载时 `disconnect()`。

#### 19.7.5 向后兼容约束

- `PageHeader` 的 `compact`、弹层组件的 `to` 均为**可选参数默认关闭**，其他工具页零变化；共用外壳（`DefaultLayout`）不新增分支。
- 本节改动只作用于画布类工具页自身；新增画布工具时复制本节结构，不修改其他工具页的页头/工具栏实现。

## 二十、BLAST 结果工具页面专项规范（2026-07-27）

BLAST 是工具箱中“参数输入 + 异步任务 + 多层结果可视化”的参考实现。权威页面为
`frontend/src/views/BioTools/BlastSearchView.vue`；Graphic Summary、命中详情和覆盖条分别位于
`frontend/src/components/blast/BlastGraphicSummary.vue`、`BlastHitDetailCard.vue` 和
`BlastAlignmentBar.vue`。新增同类检索工具可复用本节的页面层级和数据展示方式，但不得复制
BLAST 专属业务字段。

### 20.1 页面层级与参数区

1. 使用共享 `PageHeader`、结果保留提示和 `ToolActionBar`；提交、轮询、取消、历史任务跳转与
   XML/JSON/Text 下载均保留原有业务逻辑，视觉改动不得以页面刷新替代局部状态更新。
2. 桌面端使用“左侧参数列 + 右侧工作区”的两列网格：参数列 `320–360px`，工作区
   `min-width: 0`；`900px` 以下切为单列，禁止页面级横向滚动。
3. 参数区合并为两张卡片：
   - **查询设置**：目标数据库、FASTA 输入和上传入口；
   - **比对参数**：算法、E-value、最大匹配数和查询名称。
4. `word_size`、`gapopen`、`gapextend` 属于高级参数，默认折叠；折叠触发器使用
   `button`、`aria-expanded` 和 `200ms` 箭头旋转，必须保留 `focus-visible` 焦点环。
5. 序列实时分析与最近任务卡片按内容高度自适应（`align-self: start` / 不强行拉伸），避免三列
   网格造成卡片底部无意义留白。

### 20.2 Coverage 数据口径（强制）

结果表和命中详情展示的 **Coverage** 是查询覆盖率，不是 Subject 覆盖率：

```text
query_coverage = align_length / query_len * 100
subject_coverage = align_length / hit_len * 100
```

- `query_coverage` 由后端 XML 解析层计算并通过 `BlastHitDTO` 返回；权威实现为
  `src/omichub/tools/blast/core.py`、`src/omichub/tools/blast/schema.py`。
- 结果页与命中详情均消费 `query_coverage`，显示范围夹紧在 `0–100`、保留一位小数。
- 不得用 `hit_len` / `subject_len` 计算查询 Coverage。对于全长命中（`align_length === query_len`），
  Coverage 必须为 `100.0%`；该场景必须在 `tests/unit/tools/test_blast_core.py` 保留回归断言。
- `subject_coverage` 可作为未来 Subject 覆盖率的独立字段保留，但不能替代当前 Coverage 列。

### 20.3 结果摘要与下载入口

1. 已完成任务使用一张结果摘要卡：左侧为状态徽章和查询标题，中部为数据库、算法、Query 长度、
   命中数、最佳 E-value、最佳 Identity 六项统计，右侧为 XML/JSON/Text 下载按钮。
2. 统计项 label 使用 `12px` 次要色，value 使用 `16px/600` 主色；数值必须使用
   `font-variant-numeric: tabular-nums`。
3. 下载按钮保持局部操作，不移动到页面级 `PageHeader`；窄屏时摘要头允许纵向排列，下载入口仍可见。

### 20.4 比对结果表格

BLAST 结果表沿用任务中心表格规范，并额外满足检索结果密度要求：

- 所有列使用固定 `width`，`scroll-x` 等于列宽总和；长文本 Description 唯一左对齐，固定宽度并用
  `ellipsis: { tooltip: true }`。其余短值列（编号、ID、长度、Identity、E-value、分数、长度、Range、
  Coverage）用列级 `align: 'center'` 同时居中表头和表体。
- 表头使用 `--neutral-bg`，行高 `52–56px`，表体与数值列使用 `tabular-nums`，行 hover 使用
  `--neutral-hover`。Length、E-value、Score、Range 与 Coverage 百分比均 `white-space: nowrap`。
- Length 列至少 `140px`，Range 列至少 `110px`，不得把 `30,427,671 bp` 一类数值折行；Identity 使用
  `12px` 圆角胶囊和四档 identity 色。
- Coverage 单元格结构为“可收缩进度条 + 固定宽度百分比”：轨道 `#eef0f2`，填充色按
  identity/coverage 档位使用 `#22c55e / #3b82f6 / #f59e0b / #ef4444`，进度条最小宽度 `64px`，
  数值固定 `48px`、右对齐、单行显示。
- 数据不超过一页时 `pagination=false`，仅保留结果数量语义；超过 10 条时才显示每页 10 条的分页，
  不显示页大小切换器。

### 20.5 Graphic Summary 与命中详情

1. Graphic Summary 使用轻量 SVG，不引入图表依赖。Query 标尺必须按 Query 长度生成 nice-number
   自适应刻度；色条按 Identity 四档着色，Tooltip 至少展示 HSP、Query Range、Identity 和 E-value。
2. Graphic Summary 色条可点击，并用 `scrollIntoView({ behavior: 'smooth', block: 'start' })` 定位到
   对应命中详情卡片；详情卡片 id 使用稳定的 `blast-hit-<hit_num>` 约定。
3. 图例使用 `12px`，卡片 SVG 高度由命中轨道数推导，禁止固定 `min-height` 制造底部空白。
4. 命中详情卡片头部保持 `Hit #`、Subject ID、描述省略、Identity 胶囊和查看对齐按钮的清晰层级；
   统计区使用 `repeat(auto-fit, minmax(140px, 1fr))` 网格，每项为上 label、下 value，value 使用
   `14px/500` 与 `tabular-nums`。
5. Query 覆盖位置条复用同一 identity 色阶、刻度和 Tooltip 语义；点击色条可以展开序列对齐。

### 20.6 BLAST 验收清单

- [ ] 全长 HSP 的 `query_coverage` 为 `100.0%`，结果表和详情值一致，且后端解析单测覆盖该场景。
- [ ] 结果表的长数字、Range、百分比都不折行；Description 省略并有 Tooltip；单页无分页器。
- [ ] Graphic Summary 有可读刻度、12px 图例、Tooltip 和点击详情联动，卡片无大面积底部留白。
- [ ] 参数区为两张卡，高级参数默认折叠，窄屏无新增横向滚动。
- [ ] 结果摘要的六项统计与下载按钮在桌面/窄屏均可读可操作。
- [ ] `npm --prefix frontend run type-check`、`npm --prefix frontend run build` 与
  `uv run pytest tests/unit/tools/test_blast_core.py` 通过。

## 二十一、Agent MCP 可靠性、诊断与降级规范（强制）

本节适用于所有会被 Agent 调用的 builtin、stdio、SSE 和 streamable HTTP MCP。目标是避免
“单台外部 MCP 暂时不可用，导致本可在本地完成的任务整体失败”，同时确保管理端能够定位真实根因。

### 21.1 明确工具归属，禁止按名称猜测 MCP

1. 排查工具失败时，必须从 Agent 本轮绑定的 MCP Server、数据库工具快照和 `tool_call` 事件确认
   工具实际归属，禁止仅凭“生信工具”名称认定它属于 `omichub-tools`。
2. 外部数据库 MCP 与内置生信工具箱是不同故障域。例如 `translate_sequence` 可能由外部 Ensembl
   MCP 提供，但 DNA 翻译本身属于本地可计算任务，不应因为 Ensembl MCP 离线而失败。
3. MCP Server 名称应使用准确、稳定、可搜索的拼写。历史兼容名称可以暂时保留，但新增配置不得再
   引入类似 `ensmbl` 的拼写错误；更名时必须同步 Agent 绑定、健康探针、日志查询和冒烟测试。
4. 工具清单必须按 `tool_name` 去重。静态工具和动态 Flow 编译工具出现同名时，只保留一个权威定义，
   禁止把重复 function schema 发送给模型。

### 21.2 MCP 调用结果判定（强制）

MCP transport 成功不等于工具执行成功。调用结果必须同时满足：

```text
连接/初始化成功
AND call_tool 完成
AND result.isError != true
AND 平台信封 success == true
```

- MCP SDK 返回 `isError: true` 时必须转为平台级失败，提取文本内容作为内部诊断；不得记录为成功，
  不得增加成功率，也不得在冒烟报告中显示绿色。
- 工具 handler 返回 `{success: false}`、`error` 或等价错误信封时，同样视为失败。
- “发现了 N 个工具”只能证明 MCP 能初始化和执行 `list_tools`，不能证明每个工具可调用；健康检查
  必须至少包含一个无副作用的安全探针。
- 冒烟程序中的 `call_ok` 必须依据平台 `success` 和 MCP `isError` 联合判断，不能仅以“没有抛异常”
  作为成功条件。

### 21.3 错误分类与日志保真（强制）

底层异常不得全部折叠为 `MCP Server 连接失败`。内部日志和健康审计至少区分：

| failure_kind | 典型原因 | 首要检查项 |
|---|---|---|
| `command_not_found` | stdio command 不在 PATH、旧镜像缺 node/npx/cmm | 容器内 `command -v <command>` |
| `timeout` | 初始化、工具调用或外部 API 超时 | Server timeout、网络、子进程 stderr |
| `connection_error` | 子进程提前退出、SSE/HTTP 断连、协议初始化失败 | command/args、工作目录、包安装与网络 |
| `tool_error` | MCP 已连接，但工具参数或业务执行失败 | inputSchema、`isError` 内容、上游 API 返回 |
| `validation_error` | URL、stdio command/args 或工作目录未通过安全校验 | 注册配置和安全约束 |

用户界面只展示友好文案，例如“当前外部服务暂时不可用，正在尝试备用计算方式”；真实异常、
`failure_kind`、Server、tool、attempt、latency 和 trace 信息必须保留在结构化日志或 Admin 健康审计中。
不得为了友好提示而丢失根因。

### 21.4 重试、健康状态与熔断语义

1. 仅对可能恢复的外部传输错误进行有限重试；builtin 参数错误、权限错误和确定性业务错误不得重试。
2. 默认最多 3 次尝试，退避间隔为 `1s / 3s / 5s`；不得无限重试或让单个 MCP 长时间阻塞 Agent 回合。
3. 健康状态按 `server_name + tool_name` 记录，至少包含成功数、失败数、连续失败数、成功率、最后失败时间
   和最近延迟。一次工具故障不得污染同 Server 的所有工具。
4. 连续失败 3 次标记为 `degraded`；后续成功应清零连续失败计数，但保留累计统计以便观察抖动。
5. 健康状态属于运行时信号，不得因为一次瞬时错误永久覆盖 MCP 注册配置；需要持久化时应使用独立的
   健康记录或时序指标，而不是修改工具能力定义。

### 21.5 降级路径设计（强制）

每个工具接入前必须判断任务属于哪一类：

| 类型 | 示例 | MCP 失败后的处理 |
|---|---|---|
| 本地确定性计算 | DNA 翻译、反向互补、GC、FASTA 解析 | 自动切换 builtin/local handler |
| 沙箱可计算 | 文件统计、复杂脚本、可安装依赖的分析 | 切换受控 sandbox，保留资源和超时限制 |
| 外部数据依赖 | Ensembl/UniProt/NCBI 实时查询 | 可重试；无等价数据源时明确说明不可核验 |
| 长耗时工作流 | BLAST、RNA-seq、ATAC-seq Pipeline | 转任务系统，不在聊天回合内反复重试 |

- 本地 fallback 必须是平台维护的确定性实现，并有独立单元测试；禁止要求模型临时生成未经验证的代码
  冒充可靠降级。
- fallback 只能替代等价能力。例如本地 DNA 翻译可以替代外部 `translate_sequence`，但不能替代
  Ensembl 基因注释、最新变异或实时数据库查询。
- 执行 fallback 后应在 `tool_result.reliability` 中记录 `fallback_used`、`attempts` 和
  `primary_status`，让前端与审计系统能区分主路径和降级路径。
- 健康审计必须绕过 fallback 检查主 MCP，否则“本地降级成功”会掩盖外部服务已经离线的事实。

### 21.6 stdio MCP 运行环境注意事项

1. stdio MCP 由 Web/Agent 进程所在容器启动，不是在用户浏览器或分析沙箱中启动。所有 command、
   PATH、working directory、Node/Python 环境和包缓存必须在该运行容器内验证。
2. 使用 `node`/`npx` 的 MCP，运行镜像必须显式安装 Node.js/npm；不能依赖开发机已有环境。
3. 生产环境不应让每次调用都依赖 `npx` 临时联网下载包。优先在镜像构建阶段固定版本并预安装，
   或使用受控缓存；必须验证冷启动、无网络和容器重启后的行为。
4. `command`、`args`、`working_dir` 必须分别存储，禁止通过 shell 字符串拼接执行；不得使用 shell
   解释器绕过参数安全校验。
5. 镜像升级后必须重新执行 MCP 工具发现与安全探针。仅修改 Dockerfile 而未重建、重启运行容器，
   不视为修复完成。

### 21.7 全量健康检查与上线门禁

平台需要同时保留两种验证入口：

```text
GET /api/v1/mcp/health
python scripts/skill_mcp_smoke.py --only mcp
```

- Admin 健康接口应枚举数据库中所有启用 MCP，返回 Server、transport、配置状态、工具发现结果、
  工具数、安全探针结果、失败类型和延迟。
- 冒烟脚本必须从当前数据库读取启用 Server，不得只测试代码中写死的预设列表；未知 MCP 至少执行
  `list_tools`，已知 MCP 还应执行无副作用探针。
- builtin MCP 必须校验工具名唯一且每个 schema 都存在对应 handler。
- 外部 MCP 必须在实际 Web 容器中测试，因为宿主机测试成功不能证明容器 PATH、网络和依赖正确。
- 历史报告只能用于趋势和回归参考，不能证明“当前在线”。上线结论必须注明测试的绝对日期、镜像版本
  和运行环境。

### 21.8 MCP 上线检查清单

- [ ] 已确认工具实际归属的 MCP Server，不按工具名称或业务分类猜测。
- [ ] 工具名称在 Agent 本轮工具清单中唯一，静态与动态注册无重复。
- [ ] `list_tools` 成功，且至少一个无副作用安全探针真实调用成功。
- [ ] `isError: true` 和平台 `{success: false}` 均会被识别为失败。
- [ ] 内部日志保留 `failure_kind` 和真实异常，用户界面不直接暴露底层连接信息。
- [ ] 外部传输采用有限重试，连续失败会进入 `degraded`，成功后可恢复。
- [ ] 本地可计算任务已提供经过测试的 local/builtin fallback。
- [ ] 外部数据依赖任务不会用模型记忆或本地计算伪装成实时查询结果。
- [ ] stdio command 在实际 Web 容器中存在，固定版本依赖已预安装或具备可靠缓存。
- [ ] 已运行 Admin 全量健康审计与 `scripts/skill_mcp_smoke.py --only mcp`。
- [ ] 报告记录了执行日期、镜像版本、Server 数量以及每台 MCP 的结果。

---

## 二十二、Agent 对话路由与输入区展示规范（2026-08-07）

本节用于避免 Agent 对话中出现重复、过大的路由卡片，避免当前 Agent 无法处理时继续勉强回答，
并保证输入框在亮暗主题下保持统一、干净的视觉层级。

### 22.1 路由提示只表达真实状态变化

1. Router 卡片属于“状态变化提示”，不是每轮回答的固定装饰。仅在以下情况显示：
   - 会话首次完成 Agent 路由；
   - 当前目标 Agent 与上一轮目标 Agent 不同；
   - 用户完成高风险执行确认，需要明确提示即将进入执行阶段。
2. 同一会话连续路由到同一个 Agent 时，必须隐藏 Router 卡片，不得仅因 Router 每轮重新计算而重复展示。
3. 后端必须保存最近一次实际路由目标，例如 `last_routed_agent_id`；前端不得通过 Agent 名称、文案或
   消息顺序猜测是否发生切换。
4. `visible` 必须由后端根据真实会话状态生成。前端只负责渲染，不得自行把所有 route 事件默认显示。
5. 流式重连、历史消息恢复和页面刷新后，必须保持原始 `visible` 语义，避免旧路由卡片被重新激活。

### 22.2 Router 组件保持紧凑

1. Router 提示优先使用单行或双行事件条，展示“Router → 目标 Agent”、简短原因和必要的确认状态。
2. 禁止使用占据大部分消息宽度和高度的流程图式卡片重复展示 Router、Active Agent、置信度、匹配依据
   和下一阶段；这些字段仅在调试面板或首次路由确有必要时展开。
3. 路由原因默认单行省略，完整内容可通过 `title`、详情弹层或调试视图查看，不得挤压主要回答内容。
4. 置信度和意图属于辅助信息，应以弱化标签显示；不得让内部路由信息比助手正式回答更醒目。
5. 动效只使用轻量淡入和小幅位移，并遵守 `prefers-reduced-motion`；降低透明度时仍需保持语义边框清晰。

### 22.3 Agent 无法处理时必须有转交通道

1. 面向用户的专业 Agent 应配置 `handoff` 工具包，并通过 `allowed_targets` 明确可转交目标；禁止允许
   任意 Agent 名称绕过白名单。
2. Agent 在澄清需求后确认任务超出能力边界、缺少必要专业工具或无法可靠完成时，应调用
   `transfer_to_agent`，不得继续生成看似完整但未经可靠工具支持的结论。
3. 无法判断目标 Agent 时先调用 `ask_user` 澄清；不得在多个 Agent 之间盲目来回转交。
4. 转交必须限制单会话最大跳数，并记录来源 Agent、目标 Agent、原因、已完成工作、剩余任务和关键产物，
   防止循环转交和上下文丢失。
5. 转交成功后必须更新会话当前 Agent，并向前端发送 handoff 事件；只有目标确实变化时才展示紧凑提示。
6. Router 自身负责逐轮分类时可以不配置 handoff，但普通 Agent 若没有转交通道，必须在上线检查中标记为缺陷。

### 22.4 输入框背景层级

1. 输入组件只能保留一个可见的容器背景。外层 Composer 已提供卡片背景时，内部 textarea、输入包装器和
   UI 库默认容器必须使用 `background: transparent`。
2. 禁止在深色主题中为 textarea 单独硬编码纯黑或近黑背景，否则会形成输入区下方或内部的黑色色块。
3. 输入区边框、聚焦态和禁用态应由外层容器统一表达；内部组件不得叠加第二层边框、阴影或圆角背景。
4. 菜单、弹层和快捷命令面板可以使用独立表面色，但不得复用 textarea 的透明规则导致内容不可读。
5. 修改输入区样式后必须同时检查亮色主题、暗色主题、移动端、聚焦、禁用和多行输入状态。

### 22.5 验收清单

- [ ] 首次路由会显示紧凑 Router 提示。
- [ ] 连续两轮命中同一 Agent 时，第二轮不显示 Router 提示。
- [ ] 目标 Agent 变化或执行确认时，会再次显示正确提示。
- [ ] 页面刷新和历史恢复不会改变路由提示的显示状态。
- [ ] 所有面向用户且需要协作的 Agent 均配置 handoff 白名单和最大跳数。
- [ ] Agent 超出能力边界时能转交，并完整保留任务上下文与审计记录。
- [ ] 输入框内部没有独立黑色背景、重复边框或阴影。
- [ ] 亮暗主题、移动端和减少动效模式均通过视觉验收。
- [ ] 路由状态判断、Router 显隐和 handoff 服务具备针对性自动化测试。
