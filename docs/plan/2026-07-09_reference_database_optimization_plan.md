# 2026-07-09 参考数据库模块优化计划

## 目标

将 `omichubtools refdb build` 生成的物种数据库文件接入平台后端和前端，让 `/database` 页面从 mock 数据切换为真实数据库数据。

## 明天优先事项

### 1. 准备拟南芥测试数据

- 准备 `Arabidopsis thaliana` 的测试目录，建议结构：

```text
/data/omichub/omichub_data/db/Ath/TAIR10/
├── raw/
│   ├── TAIR10.fa
│   ├── TAIR10.gff3
│   ├── gene_go.tsv
│   ├── go_terms.tsv 或 go-basic.obo
│   ├── gene_ko.tsv
│   └── kegg_annotations.tsv
└── build/
```

- 先确认 gene ID 在 GFF、GO、KO、KEGG 文件中是否一致。
- 如果 KEGG 文件只有 `gene_id + Kxxxxx`，需要再准备 `KO -> pathway` 表，或接受第一阶段只展示 KO 不展示 pathway。

### 2. 用 omichubtools 生成测试库

参考命令：

```bash
omichubtools refdb build \
  --species-id Ath \
  --scientific-name "Arabidopsis thaliana" \
  --common-name "拟南芥" \
  --taxonomy-id 3702 \
  --version-id Ath_TAIR10 \
  --version-name TAIR10 \
  --assembly-name TAIR10 \
  --display-name "拟南芥 (TAIR10)" \
  --category plant \
  --fasta /data/omichub/omichub_data/db/Ath/TAIR10/raw/TAIR10.fa \
  --gff /data/omichub/omichub_data/db/Ath/TAIR10/raw/TAIR10.gff3 \
  --go /data/omichub/omichub_data/db/Ath/TAIR10/raw/gene_go.tsv \
  --go-terms /data/omichub/omichub_data/db/Ath/TAIR10/raw/go_terms.tsv \
  --ko /data/omichub/omichub_data/db/Ath/TAIR10/raw/gene_ko.tsv \
  --kegg /data/omichub/omichub_data/db/Ath/TAIR10/raw/kegg_annotations.tsv \
  --out-dir /data/omichub/omichub_data/db/Ath/TAIR10/build \
  --force
```

构建后先检查：

- `build_report.json` 中 gene、GO、KO、KEGG 数量是否合理。
- `database.sqlite` 是否能查询到目标 gene。
- `jbrowse_assembly_snippet.yaml` 中路径是否都在 `/data/omichub` 下。

### 3. 设计后端数据库 API

建议新增独立模块，而不是塞进 JBrowse：

```text
src/omichub/tools/reference_database/
├── api.py
├── config.py
├── schema.py
└── service.py
```

建议第一批 API：

- `GET /api/v1/reference-database/species`
- `GET /api/v1/reference-database/versions/{version_id}`
- `GET /api/v1/reference-database/versions/{version_id}/genes`
- `GET /api/v1/reference-database/versions/{version_id}/genes/{gene_id}`
- `GET /api/v1/reference-database/versions/{version_id}/annotations/go`
- `GET /api/v1/reference-database/versions/{version_id}/annotations/kegg`

第一阶段可以只读 SQLite，不做写入和在线转换。

### 4. 建立平台配置关系

需要明确平台如何找到每个 `database.sqlite`：

- 方案 A：继续复用 `tool_configs/jbrowse/jbrowse_config.yaml` 的 `data_files.*.db_path`。
- 方案 B：新增 `tool_configs/reference_database/databases.yaml`，专门管理数据库模块。

建议优先方案 B。原因是 JBrowse 配置关注浏览器加载，数据库模块需要 gene search、GO、KO、KEGG、版本映射等更多字段，后面会越长越不适合塞进 JBrowse YAML。

### 5. 前端接入真实数据

- 将 `/database` 从 `frontend/src/mock/referenceGenomes.ts` 切到真实 API。
- 保留 mock 作为 fallback 或开发样例。
- 第一阶段实现：
  - 物种列表
  - 版本详情
  - 数据文件状态
  - 基因搜索
  - gene detail drawer
  - GO/KO/KEGG 注释展示

### 6. 测试与验收

最低验收项：

- Ath 测试库能通过 `omichubtools` 构建成功。
- 后端能从 SQLite 查到 genes、GO、KO、KEGG。
- `/database` 页面不再依赖 mock 也能展示 Ath。
- JBrowse 仍能通过 `fasta/fai/gff` 正常打开拟南芥版本。
- 构建过程仍保持离线，不进入 Web API 或 Celery 任务链路。

## 风险点

- GFF gene ID 与 GO/KO/KEGG gene ID 不一致，会导致注释无法关联。
- GO/KEGG 文件只有 ID 时可以先跑通，但前端展示信息会偏少。
- KEGG ID 如果只是 KO，需要额外 KO-pathway 映射才能展示 pathway。
- 大型 GFF/FASTA 构建时间长，应继续保持在平台外离线执行。

## 建议明天先做的最小闭环

1. 用拟南芥测试数据生成 `database.sqlite`。
2. 手动查询 SQLite，确认数据正确。
3. 新增只读后端 service，先实现 species/version/gene detail 三个接口。
4. 前端 `/database` 先接 Ath 一个物种，跑通真实数据链路。

