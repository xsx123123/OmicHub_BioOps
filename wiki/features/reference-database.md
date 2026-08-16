# 参考基因组与数据库模块

原「参考基因组」模块已升级为「数据库」模块，支持 FA/GFF/GO/KEGG 多类型数据管理。

## 数据模型

```text
Species
  └── GenomeVersions[]
        └── DataFiles[]
              ├── fasta
              ├── gff
              ├── go
              └── kegg
```

Gene 为核心实体，关联 Transcripts、GOAnnotations、KEGGAnnotations、Sequence。

## 离线构建

平台不负责在线转换。管理员使用 `omichubtools refdb build` 离线生成资产：

```bash
pip install -e ./scripts

omichubtools refdb build \
  --species-id Lsat \
  --version-id Lsat_v11 \
  --fasta /data/omichub/omichub_data/db/Lsat/v11/Lsat.1.v11.fa \
  --gff /data/omichub/omichub_data/db/Lsat/v11/Lsat.1.v11.gff3 \
  --out-dir /data/omichub/omichub_data/db/Lsat/v11/build
```

输出：`database.sqlite`、`.fai`、`database_manifest.json`、`jbrowse_assembly_snippet.yaml`、`build_report.json`。

## 注册到平台

1. 将 `jbrowse_assembly_snippet.yaml` 片段合并到 `tool_configs/jbrowse/jbrowse_config.yaml`
2. 调用 `POST /api/v1/jbrowse/config/reload` 热生效
3. 平台只读取已生成文件，不在 Web/Celery 中执行转换

## 页面路由

- `/database`：数据库主页
- `/database/{speciesId}`：物种版本列表
- `/database/{speciesId}/{versionId}`：基因浏览器
- `/database/{speciesId}/{versionId}/gene/{geneId}`：基因详情
- `/database/{speciesId}/mapping`：跨版本映射
