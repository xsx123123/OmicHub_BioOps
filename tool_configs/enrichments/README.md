# CygnusX GO / KEGG 富集（R Docker）

> 工具注册 key 和路由为历史兼容的 `kegg-enrichment`，但实际分析范围为 **GO + KEGG**。
> 工具目录架构、前后端边界和验证要求见 [`framework.md`](./framework.md)；容器运行参数见
> [`KEGG_Docker_契约.md`](./KEGG_Docker_契约.md)。

网页不在 Python 中计算富集。Web 只校验单列 Gene ID 文件、按 `species_id` 读取 YAML、创建
任务目录并投递 Celery；独立计算 Worker 运行 R Docker、解析容器输出的 CSV，并将标准结果行
回写任务。页面按来源分别构建 GO / KEGG Plotly 气泡图和统计表；容器仍保留 PNG/PDF 产物。

## 文件

| 文件 | 用途 |
|---|---|
| `species_config.yaml` | 物种与本地参考文件路径 |
| `go_enricher.r` | RNAFlow 批量差异表 GO 分析脚本，保留原用法 |
| `run_enrichment.R` | 网页富集容器入口：单列 Gene ID → GO/KEGG CSV + 图 |
| `../../deploy/docker/Dockerfile.enrichment` | 构建 `cygnusx-r-enrichment:v1` 的统一部署 Dockerfile |
| `KEGG_Docker_契约.md` | 容器参数、输出和部署契约 |
| `examples/` | 单列 Gene ID 与 GO/KEGG 标准结果的演示 CSV |

## 运行流程

```text
CSV/TSV（仅一列 GeneID）
  → FastAPI 写入 gene_list.txt 并投递 Celery
  → Worker docker run cygnusx-r-enrichment:v1
  → R: GO local OBO + annotation / KEGG enrichKEGG
  → enrichment_result.csv + go/kegg_dotplot.png/pdf
  → Worker 解析 CSV，前端轮询后显示表格与气泡图
```

提交时需要填写项目名称。项目名称会保留在任务历史中，并转换为安全目录名；任务结果目录为：

```text
/data/cygnusx/users/<user_id>/enrichments/<project_slug>/<task_id>/
├── gene_list.txt
├── enrichment_result.csv
├── go_dotplot.png             # GO 有显著结果时生成
├── go_dotplot.pdf
├── kegg_dotplot.png           # KEGG 有显著结果时生成
└── kegg_dotplot.pdf
```

页面可查看当前登录用户最近的富集任务，恢复已完成任务的 GO/KEGG 表格与气泡图，并通过鉴权接口下载容器生成的原始 `enrichment_result.csv`。历史记录不会跨用户展示。

富集气泡图内部标题、坐标轴、颜色条与 hover 字段统一使用英文；页面操作文案保持中文。下载的标准 CSV 可直接上传到“组学绘图工坊 → 富集结果气泡图”，按 ID 或描述多选 pathway/GO term 后重新绘图，并导出筛选后的 CSV、PNG 或 SVG。

## YAML 配置

所有参数只由后端从 `species_config.yaml` 解析，浏览器不能传入任意参考文件路径。

| YAML 字段 | R 容器参数 | 说明 |
|---|---|---|
| `go_obo` | `--go_obo` | 本地 GO OBO 文件 |
| `go_annotation` | `--go_annotation` | 本地 `gene_id<TAB>GO:xxxx` 注释 |
| `kegg_id_map` | `--kegg_id_map` | 本地 `gene_id<TAB>NCBI/KEGG_ID` 映射 |
| `kegg_code` | `--kegg_code` | KEGG 物种代码，例如 `sly` |
| `kegg_key_type` | `--kegg_key_type` | `enrichKEGG` 的 ID 类型，默认 `kegg` |
| `p_value_cutoff` | `--p_value_cutoff` | 物种默认 p-value cutoff；页面可覆盖并随任务提交 |
| `q_value_cutoff` | `--q_value_cutoff` | 物种默认 q-value cutoff；页面可覆盖并随任务提交 |

番茄 ITAG4.1 配置已指向：

```text
/data/cygnusx/cygnusx_data/reference/ITAG4.1/
├── go-basic.obo
├── ITAG4.1_blast2go_annot.annot_deal
└── ITAG4.1.kegg.id
```

GO 完全使用本地 OBO 和注释文件。KEGG 的基因 ID 转换使用本地 `ITAG4.1.kegg.id`，
`clusterProfiler::enrichKEGG` 查询 KEGG 时通过容器网络访问 KEGG REST；如配置代理则使用代理。

## 输入格式

网页仅接受 `.csv` / `.tsv`，每行仅一个 Gene ID；可选首行 `GeneID`：

```text
GeneID
Solyc02g063527.2
Solyc00g500064.1
Solyc02g081340.3
```

后端会去空行、去重，并将输入写为无表头的 `gene_list.txt`。不会读取 Excel，也不会按
`padj`、`log2FoldChange` 等统计列筛选基因；请在提交前准备好目标基因列表。

页面右上角的“COP1/HY5 示例”加载
`examples/cop1_hy5_dependent_1576_gene_list.csv` 与对应真实 R 结果。GO 和 KEGG 在页面中分别显示
气泡图和统计表；示例结果用于核对交互和输出列，重新提交后会按页面设置的 p-value / q-value 阈值运行新任务。

## 构建和部署

```bash
make docker-build-enrichment
make docker-up-worker
docker compose -f deploy/docker/docker-compose.yml restart web
```

第一条命令使用 `deploy/docker/Dockerfile.enrichment` 和 `tool_configs/enrichments` 构建上下文生成 R 镜像；
第二条命令也会自动确保富集镜像已构建，并重建独立 Worker，使其加载 Docker CLI、Docker socket 挂载和最新的 Celery 富集任务；
第三条命令仅在更新 Web API 代码后需要。只有独立计算 Worker 需要 Docker CLI 与 Docker socket；
Web 仅投递和查询任务。默认 R 容器不指定 `--network`，由 Docker 使用本机默认 `bridge` 网络直接访问
KEGG REST，避免依赖可能失效的 Compose / Swarm 网络；如部署 squid 或需要访问内网服务，可设置
`ENRICHMENT_PROXY_URL` 和 `ENRICHMENT_DOCKER_NETWORK`。参考文件和任务目录均通过
`/data/cygnusx:/data/cygnusx` 挂载。
