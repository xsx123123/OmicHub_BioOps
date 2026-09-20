# GO / KEGG 富集工具框架

> 本文件是 `kegg-enrichment` 工具的目录级架构说明。它落实
> `tool_configs/tools_design.md` 的工具配置外置要求，并与
> `ARCHITECTURE_DESIN/frontend.md` 的工作台页面、主题和状态反馈规范保持一致。
>
> 路由 key 保持 `kegg-enrichment` 以兼容既有链接；产品名称统一为 **GO / KEGG 富集分析**。

## 1. 工具身份与注册

| 项目 | 值 | 权威位置 |
|---|---|---|
| 工具 key | `kegg-enrichment` | `tool_configs/tools_setting.yaml` |
| 路由 | `/tools/kegg-enrichment` | `frontend/src/router/index.ts` |
| 页面 | `KeggEnrichmentView.vue` | `frontend/src/views/BioTools/` |
| 后端前缀 | `/api/v1/enrichment` | `src/cygnusx/tools/enrichments/api.py` |
| 运行配置目录 | `tool_configs/enrichments` | `tools_setting.yaml#config_dir` |

`tools_setting.yaml` 只保存工具箱卡片元数据；物种、参考库和富集阈值在本目录的
`species_config.yaml` 中维护。容器镜像、网络、资源限制和路径挂载是环境差异，统一由
`src/cygnusx/core/config.py` 的 `ENRICHMENT_*` 设置控制，不写入浏览器可见配置。

## 2. 目录职责

```text
tool_configs/enrichments/
├── framework.md                 # 本工具框架、前后端边界与验收清单
├── README.md                    # 操作说明与部署入口
├── KEGG_Docker_契约.md          # docker run 参数及标准输出约定
├── species_config.yaml          # 物种、GO/KEGG 本地参考与默认阈值
├── run_enrichment.R             # 网页任务入口：单列 Gene ID → CSV + 图
├── go_enricher.r                # RNAFlow 批量 GO 富集脚本，保留原独立用法
├── deg_enrich_wrapper.py        # 既有离线/批处理适配脚本，非网页执行入口
├── examples/                    # 单列 Gene ID 与标准结果 CSV 示例
└── test/                        # 人工验证用基因列表样例；网页上传不读取 Excel

deploy/docker/
└── Dockerfile.enrichment        # clusterProfiler R 运行镜像；统一部署入口
```

网页运行唯一入口是 `run_enrichment.R`。不要让 Web 调用 `go_enricher.r` 或
`deg_enrich_wrapper.py` 处理上传文件，避免两套输出格式和运行语义并存。

## 3. 配置模型与公开边界

### 3.1 `species_config.yaml`

每个 `species_list` 项由后端 `SpeciesConfig` 校验、按 mtime 热重载。字段职责如下：

| 字段 | 是否返回浏览器 | 说明 |
|---|---:|---|
| `id`、`display_name`、`enabled` | 是 | 物种选择框与可用性 |
| `kegg_code`、`id_type`、`analysis_types` | 是 | 仅用于展示可用分析和任务识别 |
| `go_obo`、`go_annotation`、`kegg_id_map` | 否 | 宿主本地参考文件路径，只传给 R 容器 |
| `kegg_key_type`、`p_value_cutoff`、`q_value_cutoff` | 默认值是 | p/q 默认值返回页面，可由用户在合法范围内覆盖；参考路径仍不公开 |

新增物种时必须同步验证：GO OBO、GO 注释和 KEGG 映射均位于
`ENRICHMENT_DATA_MOUNT` 下，且容器内路径与宿主绝对路径一致。

### 3.2 环境配置

以下配置必须通过环境变量或核心 Settings 设置，而非 YAML：

- `ENRICHMENT_DOCKER_IMAGE`：默认 `cygnusx-r-enrichment:v1`；
- `ENRICHMENT_DOCKER_NETWORK`：R 容器加入的 Docker 网络；
- `ENRICHMENT_PROXY_URL`：可选 KEGG REST 出站代理；
- `ENRICHMENT_DATA_MOUNT`：基因列表、结果和参考数据的共享挂载根；
- `ENRICHMENT_EXEC_TIMEOUT`、`ENRICHMENT_MEMORY`、`ENRICHMENT_CPUS`：资源边界。

## 4. 运行数据流

```text
浏览器 CSV/TSV（第一列 Gene ID）
  → POST /enrichment/submit
  → EnrichmentService：校验、去空白/去重、写 gene_list.txt、创建 Task 并投递 Celery
  → Celery Worker：docker run Rscript /app/run_enrichment.R
  → clusterProfiler：本地 GO + 本地映射后的 KEGG
  → enrichment_result.csv、GO/KEGG dotplot PNG/PDF
  → Worker：标准化 CSV → 表格 DTO，回写 Task
  → GET /enrichment/tasks/{task_id} 轮询完成状态
  → KeggEnrichmentView：分别构建 GO / KEGG Plotly 气泡图、数据表和 CSV 导出
```

### 输入约束

- 网页文件输入仅允许 `.csv`、`.tsv`；只读取第一列，允许首行 `GeneID` / `gene_id`；
- 手动输入时每行一个 Gene ID；
- 不解析 Excel、差异表达表或 `padj`/`log2FoldChange` 等统计列；用户先准备目标基因列表；
- R 端会去除基因版本后缀，例如 `Solyc02g063527.2` → `Solyc02g063527`。

### 输出约束

`enrichment_result.csv` 的列恒为：

```text
Source, ID, Description, GeneRatio, BgRatio, pvalue, p.adjust, qvalue, geneID, Count
```

无显著术语时输出表头。若 GO 或 KEGG 其中一类失败，另一类成功结果仍应返回；两类均失败时
容器以非零状态退出，API 返回任务错误摘要。

## 5. 前端工作台契约

页面遵循 `tools_design.md` §6 与 `frontend.md` 的标准工作台模式：

- 根容器单层 `16px` 留白，参数区与结果区使用 `320px 1fr` 的紧凑双栏；
- 使用共享 `PageHeader`，页面级操作仅放在其 `#actions` 插槽；
- 参数区只保留物种和基因列表输入，KEGG code/OrgDB 等内部运行细节不作为可编辑或伪可编辑字段；
- 加载、物种加载失败、无显著结果、任务错误和成功结果均提供明确文字反馈；
- Plotly 使用容器 ref 渲染并在组件卸载时 `purge`，避免路由切换残留；
- 颜色、边框和阴影只使用全局语义令牌；窄屏在 `1024px` 以下切换为单栏；
- 导出 CSV 包含 `Source`，以区分 GO 与 KEGG。
- 页面级“示例数据”操作在浏览器中加载 `examples/` 对应的演示结果，并使用 Plotly 渲染；
  示例绝不提交到 Docker，也不替代真实富集任务。

### Worker 容器边界

Web 不安装 Docker CLI，也不在请求协程中启动 R 容器。独立 `cygnusx-worker` 订阅 `analysis`
队列，具备 Docker CLI 和 Docker socket 访问权，用于编排短生命周期的 R 分析容器。这样 HTTP
提交快速返回，长时间 R 计算、超时和失败都由 Celery 任务状态表达，前端仅轮询并渲染完成结果。

## 6. 验收与维护

每次调整至少完成以下检查：

1. `species_config.yaml` 通过 `EnrichmentConfigManager` / Pydantic 解析；
2. runner 命令包含需要的 GO/KEGG 本地参考参数和 R 入口；
3. CSV/TSV 首列 Gene ID、表头和去重逻辑通过定向单测；
4. `Rscript -e "invisible(parse(file='tool_configs/enrichments/run_enrichment.R'))"` 通过；
5. `npm run type-check` 与 `npm run build` 通过；
6. R 镜像构建成功；至少运行一次本地 GO 容器验证，确认 CSV 和 dotplot 生成；
7. 检查亮/暗主题、窄屏、键盘焦点、加载、错误、空结果和 CSV 导出。

更多 Docker 参数和真实文件路径约束见 [`KEGG_Docker_契约.md`](./KEGG_Docker_契约.md)。
