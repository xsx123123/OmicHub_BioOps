# OmicHub 参考基因组模块 · 后端搭建指南

> 本文档指导后端搭建「参考基因组」模块，对接已搭好的前端（`/reference-genomes`，当前用 mock 数据）。
> 配置文件：[`reference_genomes.yaml`](./reference_genomes.yaml)
> 前端代码：`frontend/src/views/ReferenceGenomesView.vue`、`ReferenceGenomeDetailView.vue`、`mock/referenceGenomes.ts`
>
> 最后更新：2026-07-06

---

## 一、模块概述

为平台提供预置参考基因组库：浏览基因组卡片、查看详情（染色体统计 / 文件清单）、基因搜索（按 ID / 名称 / 注释）、基因详情（结构 + 注释）、版本间基因 ID 映射。

**首批支持**：生菜 v8、生菜 v11。

**核心能力**：
- 基因组元数据展示（YAML 驱动，热重载）
- 基因搜索（SQLite FTS5 全文索引，毫秒级）
- 基因详情（位置、注释、外显子数）
- 版本映射（v8 ↔ v11，TSV 或数据库表）

---

## 二、架构设计

对齐现有 `src/omichub/tools/` 模块分层（参考 `jbrowse/`、`enrichments/`）：

```
src/omichub/reference_genomes/
├── __init__.py
├── api.py          # FastAPI 路由（APIRouter）
├── service.py      # 业务逻辑（基因组查询、基因搜索、ID 映射）
├── schema.py       # Pydantic 响应模型（与前端 TypeScript 类型对齐）
├── config.py       # YAML 配置加载器（mtime 热重载，单例）
└── indexer.py      # 基因索引构建（GFF3 → SQLite FTS5）

refdata/
├── reference_genomes.yaml   # 配置文件（本目录）
└── README.md                # 本文档
```

### 分层职责

| 层 | 职责 |
|----|------|
| `api.py` | 路由定义、请求校验、调用 service、返回 schema |
| `service.py` | 基因组查询、基因搜索（FTS5）、ID 映射、文件状态检查 |
| `schema.py` | 响应模型，字段与前端 `mock/referenceGenomes.ts` 类型一一对应 |
| `config.py` | 加载 YAML，mtime 热重载，字段缺失回退默认值（绝不抛异常） |
| `indexer.py` | 离线脚本：解析 GFF3，写入 SQLite FTS5 索引 |

### 注册到主路由

`src/omichub/api/v1/router.py` 追加：
```python
from omichub.reference_genomes.api import router as reference_genomes_router
api_router.include_router(reference_genomes_router, prefix="/reference-genomes", tags=["参考基因组"])
```

---

## 三、数据模型

### 3.1 基因组元数据（YAML 配置，非数据库）

由 `reference_genomes.yaml` 的 `genomes` 列表定义，运行时加载到内存。字段见配置文件，与前端 `Genome` 接口对齐。

### 3.2 基因搜索索引（SQLite FTS5）

每个基因组一个 `gene_index.db`，表结构：

```sql
-- 虚拟表：FTS5 全文索引
CREATE VIRTUAL TABLE genes USING fts5(
    gene_id,          -- 基因 ID，如 LsG0001.1
    gene_name,        -- 基因名，如 LsMYB1
    chromosome,       -- 染色体，如 Chr1
    start UNINDEXED,  -- 起始位置（1-based）
    end UNINDEXED,    -- 终止位置
    strand UNINDEXED, -- +/-
    length UNINDEXED, -- 长度 bp
    annotation,       -- 功能注释（可搜索）
    exons UNINDEXED,  -- 外显子数
    tokenize = "unicode61 remove_diacritics 2"
);
```

- `gene_id` / `gene_name` / `annotation` 可搜索（FTS5 索引）
- 其余字段 `UNINDEXED`（仅存储，不索引，用于返回）
- 搜索用 `MATCH` 或 `LIKE`（contains 模式用 LIKE，FTS5 MATCH 更快）

### 3.3 ID 映射

TSV 文件（两列，无表头）：
```
Lsat_v8_0001	LsG0001.1
Lsat_v8_0002	LsG0002.1
...
```

或启用数据库时用表：
```sql
CREATE TABLE gene_id_mapping_v8_v11 (
    source_id VARCHAR(64) PRIMARY KEY,
    target_id VARCHAR(64) NOT NULL,
    INDEX idx_target (target_id)
);
```

---

## 四、API 端点设计

前缀：`/api/v1/reference-genomes`。全部需登录（`Depends(get_current_user)`）。

### 4.1 基因组列表
```
GET /
```
响应：
```json
{
  "data": [
    {
      "id": "lettuce-v11",
      "species_emoji": "🥬",
      "common_name": "生菜",
      "latin_name": "Lactuca sativa",
      "version": "v11",
      "version_full": "Lsat.1.v11",
      "tags": ["最新版", "染色体级"],
      "chromosomes": 9,
      "total_genes": 38678,
      "genome_size": "2.69 Gb",
      "n50": "120 Mb",
      "release_date": "2023-05",
      "is_default": true,
      "gradient": "linear-gradient(90deg, #3b82f6, #7c3aed)"
    }
  ]
}
```

### 4.2 基因组详情
```
GET /{genome_id}
```
响应：列表项全部字段 + `chromosomes`（数组）+ `gene_type_stats`（数组）+ `files`（含 size/indexed 状态）。

### 4.3 染色体列表
```
GET /{genome_id}/chromosomes
```
响应：`[{ "name": "Chr1", "length": 425000000, "color": "#6366f1" }]`

### 4.4 基因类型分布
```
GET /{genome_id}/gene-types
```
响应：`[{ "name": "mRNA", "value": 32104, "color": "#6366f1" }]`

### 4.5 文件清单
```
GET /{genome_id}/files
```
响应：`[{ "name": "genome.fa", "size": "2.1 Gb", "indexed": true, "path": "/data/..." }]`
后端按 `files` 路径 `os.path.exists` 检查，`os.path.getsize` 取大小（人类可读化）。

### 4.6 基因搜索（核心）
```
GET /{genome_id}/genes?field=gene_id&q=MYB&chromosome=Chr1&page=1&page_size=20
```
参数：
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `field` | enum | `gene_id` | 搜索字段：`gene_id` / `gene_name` / `annotation` |
| `q` | string | 必填 | 关键词（contains 模式） |
| `chromosome` | string | 空 | 染色体筛选（空则全部） |
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数（≤100） |

响应：
```json
{
  "data": {
    "total": 5,
    "items": [
      {
        "gene_id": "LsG0001.1",
        "gene_name": "LsMYB1",
        "chromosome": "Chr1",
        "start": 1234567,
        "end": 1235890,
        "strand": "+",
        "length": 1324,
        "annotation": "MYB transcription factor family protein",
        "exons": 3
      }
    ]
  }
}
```

SQL（contains 模式）：
```sql
SELECT gene_id, gene_name, chromosome, start, end, strand, length, annotation, exons
FROM genes
WHERE gene_id LIKE '%MYB%'          -- field + q
  AND chromosome = 'Chr1'           -- 可选
ORDER BY gene_id
LIMIT 20 OFFSET 0;
```

### 4.7 基因详情
```
GET /{genome_id}/genes/{gene_id}
```
响应：单条基因全部字段（同 4.6 items）。若 `exon_source=gff3_parse`，额外返回 `exon_ranges`（`[{start, end}, ...]`）供前端画外显子结构图。

### 4.8 ID 版本映射
```
POST /{genome_id}/map-ids
Content-Type: application/json

{
  "target_genome_id": "lettuce-v11",
  "ids": ["Lsat_v8_0001", "Lsat_v8_0002", "Lsat_v8_9999"]
}
```
响应：
```json
{
  "data": {
    "results": [
      { "input": "Lsat_v8_0001", "output": "LsG0001.1", "status": "success" },
      { "input": "Lsat_v8_9999", "output": null,       "status": "fail" }
    ],
    "success_count": 1,
    "total_count": 3
  }
}
```

### 4.9 设为默认
```
POST /{genome_id}/set-default
```
需管理员权限。更新配置文件 `is_default` 字段（或写 user 偏好表），返回成功。

### 4.10 配置热重载
```
POST /reload
```
需管理员。强制重新加载 YAML。

---

## 五、Schema 设计（schema.py）

与前端 `mock/referenceGenomes.ts` 类型严格对齐（字段名 snake_case ↔ camelCase 用 Pydantic alias 转换）：

```python
from pydantic import BaseModel, Field

class GenomeSummary(BaseModel):
    id: str
    species_emoji: str = Field(alias="speciesEmoji")  # 前端用 camelCase
    common_name: str = Field(alias="commonName")
    latin_name: str = Field(alias="latinName")
    version: str
    version_full: str = Field(alias="versionFull")
    tags: list[str]
    chromosomes: int
    total_genes: int
    genome_size: str
    n50: str
    release_date: str
    is_default: bool
    gradient: str

    model_config = {"populate_by_name": True, "serialize_by_alias": True}
```

> **注意**：前端 `import { MOCK_GENOMES }` 的 `Genome` 用 camelCase（`commonName`、`versionFull`、`isDefault`）。后端要么用 alias 输出 camelCase，要么前端对接时加一层转换。**推荐后端 alias 输出 camelCase**，前端 mock 替换零改动。

---

## 六、基因索引构建（indexer.py）

### 6.1 构建脚本

```python
# src/omichub/reference_genomes/indexer.py
import sqlite3
import re
from pathlib import Path

def build_gene_index(gff3_path: str, db_path: str):
    """解析 GFF3，导入 SQLite FTS5 索引。"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    if Path(db_path).exists():
        Path(db_path).unlink()

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE VIRTUAL TABLE genes USING fts5(
            gene_id, gene_name, chromosome,
            start UNINDEXED, end UNINDEXED, strand UNINDEXED,
            length UNINDEXED, annotation, exons UNINDEXED
        )
    """)

    # 解析 GFF3：提取 gene / mRNA / exon，统计每基因外显子数
    gene_exons = {}  # parent_id -> exon count
    genes = []
    with open(gff3_path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip().split("\t")
            if len(cols) < 9:
                continue
            chrom, _, feature, start, end, _, strand, _, attrs = cols
            attr = dict(re.findall(r'(\w+)=([^;]+)', attrs))
            if feature == "gene":
                gid = attr.get("ID", "")
                name = attr.get("Name", gid)
                ann = attr.get("Note", attr.get("description", "Hypothetical protein"))
                genes.append((gid, name, chrom, int(start), int(end), strand,
                              int(end) - int(start) + 1, ann, 0))
            elif feature == "exon":
                parent = attr.get("Parent", "")
                gene_exons[parent] = gene_exons.get(parent, 0) + 1

    # 补外显子数（mRNA 的 Parent 链回溯到 gene）
    rows = []
    for g in genes:
        gid = g[0]
        exons = gene_exons.get(gid, 0)
        rows.append((*g[:8], exons))

    conn.executemany(
        "INSERT INTO genes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()
    print(f"索引构建完成：{len(rows)} 条基因 → {db_path}")
```

### 6.2 执行构建

```bash
# 在容器内或本地（需能访问 GFF3 文件）
python -m omichub.reference_genomes.indexer build --genome lettuce-v11
python -m omichub.reference_genomes.indexer build --genome lettuce-v8
```

构建命令读取 `reference_genomes.yaml`，按 `files.gff3` 解析，写入 `gene_index`。

### 6.3 索引更新时机
- 首次部署
- GFF3 文件更新后
- 配置新增基因组后

可通过 Celery 任务异步构建（参考 jbrowse 的 index/create 模式），或手动执行。

---

## 七、数据准备

### 7.1 目录结构
```
/data/omichub/reference/
├── lettuce-v11/
│   ├── genome.fa              # FASTA
│   ├── genome.fa.fai          # samtools faidx 生成
│   ├── genes.gff3             # 注释
│   ├── genes.gtf
│   ├── STAR/                  # STAR 比对索引
│   ├── HISAT2/                # HISAT2 比对索引
│   └── gene_index.db          # 后端构建脚本生成
├── lettuce-v8/
│   └── ...（同上）
└── id_mapping/
    ├── lettuce_v8_to_v11.tsv
    └── lettuce_v11_to_v8.tsv
```

### 7.2 索引文件生成
```bash
# FASTA 索引
samtools faidx /data/omichub/reference/lettuce-v11/genome.fa

# STAR 索引（分析流程用，参考基因组模块仅展示）
STAR --runMode genomeGenerate \
     --genomeDir /data/omichub/reference/lettuce-v11/STAR \
     --genomeFastaFiles /data/omichub/reference/lettuce-v11/genome.fa \
     --sjdbGTFfile /data/omichub/reference/lettuce-v11/genes.gtf \
     --runThreadN 16
```

### 7.3 文件大小人类可读化
后端 service 检查文件时，`os.path.getsize` 返回字节数，转成 `2.1 Gb` / `156 Mb` 格式：
```python
def human_size(nbytes):
    for unit in ["b", "Kb", "Mb", "Gb", "Tb"]:
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} Pb"
```

---

## 八、部署

### 8.1 Docker 挂载
`deploy/docker/docker-compose.yml` 的 `omichub-web` 服务追加：
```yaml
volumes:
  - /data/omichub:/data/omichub:ro          # 参考基因组文件（只读）
  - ../../refdata/reference_genomes.yaml:/app/refdata/reference_genomes.yaml:ro
```

### 8.2 配置路径
`src/omichub/core/config.py` 的 Settings 追加：
```python
reference_genomes_yaml: str = "/app/refdata/reference_genomes.yaml"
```

### 8.3 容器内依赖
`omichub-web` 镜像需装 `sqlite3`（Python 自带 `sqlite3` 模块，无需额外装）。GFF3 解析纯 Python，无额外依赖。

---

## 九、与前端对接

### 9.1 替换 mock 为 API

前端当前：`frontend/src/mock/referenceGenomes.ts` 导出静态数据，视图直接 import。

对接后：新建 `frontend/src/api/referenceGenomes.ts`：
```typescript
import apiClient from '@/api/client'
import type { Genome, Gene, Chromosome } from '@/types/referenceGenomes'

export async function fetchGenomes(): Promise<Genome[]> {
  const { data } = await apiClient.get<{ data: Genome[] }>('/reference-genomes')
  return data.data
}

export async function fetchGenomeDetail(id: string): Promise<GenomeDetail> {
  const { data } = await apiClient.get<{ data: GenomeDetail }>(`/reference-genomes/${id}`)
  return data.data
}

export async function searchGenes(
  genomeId: string,
  params: { field: string; q: string; chromosome?: string; page?: number; page_size?: number },
): Promise<{ total: number; items: Gene[] }> {
  const { data } = await apiClient.get(`/reference-genomes/${genomeId}/genes`, { params })
  return data.data
}

export async function mapIds(genomeId: string, targetId: string, ids: string[]) {
  const { data } = await apiClient.post(`/reference-genomes/${genomeId}/map-ids`, {
    target_genome_id: targetId, ids,
  })
  return data.data
}
```

视图层把 `import { MOCK_GENOMES }` 改为 `useApi(fetchGenomes)`，组件结构无需改动。

### 9.2 类型定义
`frontend/src/types/referenceGenomes.ts`：从 `mock/referenceGenomes.ts` 的 interface 提取，与后端 schema 字段对齐（camelCase）。

### 9.3 缓存注意
参考 memory `cached-json-validates-after-cache`：后端若用 `cached_json` 装饰器，确保 dict 字段名与 schema 一致，改完 bump `cache.key_version` 并 `docker restart omichub-web`。

---

## 十、配置加载器实现要点（config.py）

参考 `src/omichub/tools/registry/config.py` 与 `jbrowse/config.py`：

```python
class ReferenceGenomesConfigManager:
    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or get_settings().reference_genomes_yaml
        self._config = None
        self._mtime = 0.0

    def get_config(self) -> ReferenceGenomesConfig:
        path = Path(self.config_path)
        if not path.exists():
            return ReferenceGenomesConfig()  # 空配置，前端降级空列表
        mtime = path.stat().st_mtime
        if self._config is None or mtime > self._mtime:
            raw = yaml.safe_load(path.read_text("utf-8")) or {}
            try:
                self._config = ReferenceGenomesConfig(**raw)
            except Exception:
                self._config = ReferenceGenomesConfig()  # 字段不合法回退默认
            self._mtime = mtime
        return self._config

config_manager = ReferenceGenomesConfigManager()
```

**要点**（对齐现有加载器）：
- 文件缺失 / 解析失败 / 字段不合法 → 回退默认空配置，绝不抛异常（前端降级为空列表，不影响平台其他功能）
- mtime 热重载，无需重启
- 单例 `config_manager`
- `reload()` 方法供管理员 API 调用

参考 memory `tools-dir-must-be-mounted`：配置文件须挂载进容器（dev 挂卷 prod 打镜像），缺失静默回退空配置。

---

## 十一、开发步骤 Checklist

按顺序完成：

- [ ] 1. 创建 `src/omichub/reference_genomes/` 模块目录（`__init__.py`、`api.py`、`service.py`、`schema.py`、`config.py`、`indexer.py`）
- [ ] 2. `schema.py`：定义 `GenomeSummary` / `GenomeDetail` / `Gene` / `Chromosome` / `GeneTypeStat` / `GenomeFile` / `MapResult`，字段用 alias 对齐前端 camelCase
- [ ] 3. `config.py`：实现 `ReferenceGenomesConfigManager`（mtime 热重载 + 缺失回退），配置 Pydantic 模型（`GenomeConfig` / `ReferenceGenomesConfig`）
- [ ] 4. `core/config.py` Settings 加 `reference_genomes_yaml` 路径
- [ ] 5. `indexer.py`：GFF3 → SQLite FTS5 构建脚本，支持 `python -m omichub.reference_genomes.indexer build --genome <id>`
- [ ] 6. `service.py`：实现 `list_genomes` / `get_genome` / `search_genes` / `get_gene` / `list_files` / `map_ids`，基因搜索走 SQLite FTS5
- [ ] 7. `api.py`：定义 APIRouter，实现 §四 全部端点，`Depends(get_current_user)` 鉴权
- [ ] 8. `api/v1/router.py` 注册路由
- [ ] 9. 准备 `/data/omichub/reference/lettuce-v11/` 与 `lettuce-v8/` 数据（FASTA / GFF3 / GTF / 索引）
- [ ] 10. 执行索引构建：`python -m omichub.reference_genomes.indexer build --genome lettuce-v11`
- [ ] 11. docker-compose 挂载 `/data/omichub` 与 `refdata/reference_genomes.yaml`
- [ ] 12. `docker restart omichub-web`
- [ ] 13. 验证：`curl -H "Authorization: Bearer <token>" http://localhost:8888/api/v1/reference-genomes/` 返回 2 个基因组
- [ ] 14. 前端：新建 `api/referenceGenomes.ts`，视图替换 mock 为 API 调用
- [ ] 15. 端到端验证：列表页 → 详情页 → 基因搜索 → 抽屉 → 版本映射

---

## 十二、验收标准

- [ ] `GET /` 返回 2 个基因组（生菜 v8/v11），字段与前端 mock 一致
- [ ] `GET /{id}/genes?q=MYB&field=gene_name` 返回匹配基因，毫秒级响应
- [ ] `GET /{id}/genes/{gene_id}` 返回单基因详情
- [ ] `POST /{id}/map-ids` 双向映射正确，未找到返回 status=fail
- [ ] 文件清单的 `indexed` 状态与磁盘一致（文件存在则 true）
- [ ] 配置文件修改后自动热重载（无需重启）
- [ ] 配置文件缺失时不报错，前端降级空列表
- [ ] 前端从 mock 切换到 API 后，所有交互功能正常

---

## 十三、后续扩展

- **更多物种**：番茄 / 水稻 / 人类，在 YAML `genomes` 追加 + 准备数据
- **JBrowse 联动**：基因详情抽屉「在 JBrowse 中查看」按钮跳转 `/tools/jbrowse` 并定位到该基因坐标
- **LiftOver 集成**：版本映射升级为坐标映射（参考 `docs/26.7.6/omic_tools_sequence_format_prompt.md` 的 LiftOver 工具）
- **权限**：设为默认 / 下载映射表限制管理员
- **缓存**：列表 / 详情接口走 `cached_json`，改配置后 bump key_version

---

*配置文件：[`reference_genomes.yaml`](./reference_genomes.yaml)*
*前端 mock：`frontend/src/mock/referenceGenomes.ts`*
*参考实现：`src/omichub/tools/jbrowse/`、`src/omichub/tools/enrichments/`*
