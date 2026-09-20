# CygnusX GO / KEGG R Docker 契约

## 1. 职责边界

- **Web 后端**：创建 `/data/cygnusx/users/<user_id>/enrichment/<task_id>/`，写
  `gene_list.txt`，创建通用 Task 记录并投递 Celery；不执行容器。
- **Celery Worker**：消费 `analysis` 队列，执行容器，读取 `enrichment_result.csv`，将
  Plotly/表格结果和失败信息回写 Task。
- **R 容器**：使用 `clusterProfiler` 完成 GO 和 KEGG 分析，写 CSV、PNG、PDF；所有已配置分析
  都失败时以非零状态退出。若仅一类分析失败，保留另一类结果并在日志中记录警告。

镜像名由 `ENRICHMENT_DOCKER_IMAGE` 控制，默认 `cygnusx-r-enrichment:v1`。

## 2. 容器命令

Celery Worker 生成的命令形态如下：

```bash
docker run --rm --name cygnusx-enrich-<task> \
  -v /data/cygnusx:/data/cygnusx \
  --memory 2g --cpus 2.0 \
  cygnusx-r-enrichment:v1 \
  Rscript /app/run_enrichment.R \
  --input /data/cygnusx/users/<user>/enrichment/<task>/gene_list.txt \
  --output /data/cygnusx/users/<user>/enrichment/<task>/enrichment_result.csv \
  --go_obo /data/cygnusx/cygnusx_data/reference/ITAG4.1/go-basic.obo \
  --go_annotation /data/cygnusx/cygnusx_data/reference/ITAG4.1/ITAG4.1_blast2go_annot.annot_deal \
  --kegg_id_map /data/cygnusx/cygnusx_data/reference/ITAG4.1/ITAG4.1.kegg.id \
  --kegg_code sly --kegg_key_type kegg \
  --p_value_cutoff 0.05 --q_value_cutoff 0.1
```

默认不传 `--network`，由 Docker 使用本机默认 `bridge` 网络。仅在容器需要访问指定代理或内网服务时，
通过 `ENRICHMENT_DOCKER_NETWORK=<network-name>` 显式加入自定义网络。

GO 参数可单独存在；KEGG 参数 `kegg_id_map + kegg_code` 可单独存在；同时存在时容器合并两类
结果。所有路径都必须位于 `/data/cygnusx`，并在宿主和容器内保持相同绝对路径。

## 3. R 实现

镜像入口是 `run_enrichment.R`：

- GO：读取本地 OBO 和 `gene_id<TAB>GO_ID` 注释，调用
  `clusterProfiler::enricher(TERM2GENE, TERM2NAME)`；
- KEGG：读取本地 `gene_id<TAB>NCBI/KEGG_ID` 映射，调用
  `clusterProfiler::enrichKEGG()`；
- 图：对每类有结果的分析输出 `go_dotplot.*` / `kegg_dotplot.*`；
- ID：自动去除末尾版本号，例如 `Solyc01g000010.3` → `Solyc01g000010`，以兼容不同参考版本。

GO 本地分析不依赖外网。KEGG REST 失败但 GO 成功时，容器保留 GO CSV/图并输出局部失败警告；
若所有已配置分析都失败，Web 会把错误摘要返回给用户。默认通过 Docker bridge 直接访问 KEGG；
设置 `ENRICHMENT_PROXY_URL` 后才会向容器注入代理环境变量。

## 4. 标准 CSV 输出

`--output` 必须始终写出下列列（无显著结果时只写表头）：

```csv
Source,ID,Description,GeneRatio,BgRatio,pvalue,p.adjust,qvalue,geneID,Count
GO,GO:0009507,chloroplast,30/120,87/25582,1.2e-10,3.5e-08,2.1e-08,Solyc01g...,30
KEGG,sly00195,Photosynthesis,12/120,45/31022,2.6e-05,1.9e-03,1.2e-03,101...,12
```

## 5. 镜像构建

```bash
make docker-build-enrichment
docker run --rm cygnusx-r-enrichment:v1 Rscript /app/run_enrichment.R --help
```

`deploy/docker/Dockerfile.enrichment` 使用 `tool_configs/enrichments` 作为构建上下文，基于 Bioconductor R 镜像并预装 `clusterProfiler`、
`enrichplot`、`ontologyIndex` 和 `optparse`。镜像构建阶段可联网安装包；运行阶段 KEGG REST
可直接出网，也可由 `ENRICHMENT_PROXY_URL` 指向部署方的代理。
