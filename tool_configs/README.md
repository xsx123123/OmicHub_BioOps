# 生信工具箱配置（tool_configs/）

本目录是**工具箱的集中配置根**，仿 `flows/` 仓库内源码管控。两类配置分治：

| 类型 | 文件 | 用途 |
|------|------|------|
| 前端注册表 | `tool_configs/tools_setting.yaml` | 「哪些工具加载到前端」+ 每张卡片展示元数据（title/description/icon/gradient/route/enabled/order） |
| 工具功能配置 | `<工具名>/*.yaml` | 该工具的后端运行参数（参考基因组、物种列表等） |

> 展示元数据集中在一处（`tool_configs/tools_setting.yaml`），功能配置各自独立成目录，互不耦合。
>
> 目录名使用 `tool_configs/` 而非 `tools/`，是为了与后端代码包 `src/omichub/tools/` 明确区分：
> 前者只放 YAML 配置，后者放工具后端实现。

## 目录结构

```
tool_configs/
├── tools_setting.yaml          # 前端注册表（前端 GET /api/v1/tools 消费）
├── fastq_qc/
│   ├── README.md
│   └── config.yaml             # fastp / MultiQC 镜像、资源、参数与存储策略
├── jbrowse/
│   └── jbrowse_config.yaml     # JBrowse 2 参考基因组 / 预设轨道 / 扫描上传策略
├── enrichments/
│   ├── README.md
│   └── species_config.yaml     # KEGG/GO 富集分析物种列表（KEGG 三字码 / OrgDb / ID 类型）
└── deg/
    ├── README.md               # 引擎口径与 R 容器契约
    ├── deg_config.yaml         # 镜像 / 资源 / 默认参数 / 输入限制（mtime 热重载）
    ├── scripts/                # run_deseq2.r / run_edger.r（打包进 omichub-r-deg:v1）
    └── examples/               # 示例 counts/metadata/pairs/annotation
```

> 仅**有后端配置**的工具才建子目录。纯前端 mock 工具（blast / plot）的展示信息统一在 `tool_configs/tools_setting.yaml`；FASTQ 极速质控已使用 `fastq_qc/config.yaml` 管理 Worker 默认行为。

## 后端入口

工具代码已按「模块化」收口到 `src/omichub/tools/` 包，每个工具自成子包（api/service/schema/config）。路由由 `omichub.tools.register_tool_routers` **自动发现**挂载，新增工具无需改 `api/v1/router.py`。

| 工具 | 代码子包 | 配置项（`core/config.py`） | API |
|------|----------|---------------------------|-----|
| 注册表 | `omichub.tools.registry`（api/schema/config） | `tools_setting_yaml` | `GET /api/v1/tools`、`POST /api/v1/tools/reload` |
| FASTQ 极速质控 | `omichub.tools.fastq_qc`（待接入） | `fastq_qc_config_yaml`（待接入） | `/api/v1/qc/*` |
| JBrowse | `omichub.tools.jbrowse`（api/service/schema/config/tasks） | `jbrowse_config_yaml` | `/api/v1/jbrowse/*` |
| 富集分析 | `omichub.tools.enrichments`（api/service/schema/config/runner） | `enrichment_config_yaml` | `/api/v1/enrichment/*` |
| DEG 差异表达分析 | `omichub.tools.deg`（api/service/schema/config/runner/tasks） | `deg_config_yaml` | `/api/v1/deg/*` |

各工具的配置加载器同模式：单例 + mtime 热重载，文件缺失/解析失败回退默认配置，绝不抛异常。

## 新增工具（模块化流程）

1. **建代码子包**：`src/omichub/tools/<工具名>/`，内含 `api.py`（声明 `router` + `prefix` + `tags`）及 `service.py`/`schema.py`/`config.py` 等；
2. **登记前端展示**：在仓库根 `tool_configs/tools_setting.yaml` 的 `tools` 列表追加一项（key/title/description/icon/gradient/route/order）；
3. **放功能配置**：仓库根 `tool_configs/<工具名>/` 下放 YAML，由子包内 `config.py` 加载器读取，并在 `core/config.py` 加 `xxx_config_yaml` 字段指向它；
4. **前端路由/图标**：`frontend/src/router/index.ts` 加 `tools/<key>` 子路由（前端路由保持 `/tools/*` 不变）；若用新图标在 `ToolsHubView.vue` 的 `ICON_MAP` 登记。

> 第 1 步建好子包后，`register_tool_routers` 会自动发现并挂载其路由 —— **无需改 `api/v1/router.py`**。这是模块化的关键：工具代码自包含，核心路由表零侵入。

## 改完如何生效

**改文件即生效，无需重启**：加载器按文件 mtime 自动热重载。

- `tool_configs/tools_setting.yaml` 改完 → 前端刷新工具箱即可见（或调 `POST /api/v1/tools/reload` 强制）。
- `tool_configs/fastq_qc/config.yaml` → API 与 QC Worker 的配置加载器按 mtime 热重载；已创建任务仍使用各自的 `task.yaml` 快照。
- `tool_configs/jbrowse/jbrowse_config.yaml` → 调 `POST /api/v1/jbrowse/config/reload`（管理员）或等 mtime 热重载。
- `tool_configs/enrichments/species_config.yaml` → 等加载器 mtime 热重载。
- `tool_configs/deg/deg_config.yaml` → 等加载器 mtime 热重载（镜像资源、默认参数、输入限制）。

## 新增工具（旧流程，已自动化）

> 以下为历史流程说明，现已被上方「模块化流程」取代，保留作背景参考。

1. 在 `tool_configs/tools_setting.yaml` 的 `tools` 列表追加一项（填 key/title/description/icon/gradient/route/order）；
2. 若用了**新图标**，须在 `frontend/src/views/BioTools/ToolsHubView.vue` 的 `ICON_MAP` 登记 `@vicons/ionicons5` 组件
   （YAML 不能承载 Vue 组件，字符串 key 须在前端映射；未登记的 key 回退到 `AppsOutline`）；
3. 在 `frontend/src/router/index.ts` 加 `tools/<key>` 子路由，指向工具页组件（前端路由保持 `/tools/*` 不变）；
4. 若该工具有后端配置，新建 `tool_configs/<工具名>/` 目录放 YAML，建对应加载器（仿 `enrichment_config.py`），并在 `tool_configs/tools_setting.yaml` 的 `config_dir` 字段指明目录。

## 部署（重要）

`tool_configs/` 必须**对 web 容器可读**，否则三个加载器静默回退空配置（工具箱空白 / 无参考基因组 / 物种下拉空）：

- **开发**：`deploy/docker/docker-compose.yml` 已挂 `../../tool_configs:/app/tool_configs:ro`（与 `flows/` 同款）。
- **生产**：prod 不挂源码，`Dockerfile` 已 `COPY tool_configs/ ./tool_configs/` 打进镜像（与 `src/` 同款）。
- 改 `tool_configs/` 下文件，dev 经挂载即时可见；prod 需重建镜像。
