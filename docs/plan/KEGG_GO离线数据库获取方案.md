# 离线 KEGG & GO 数据库获取完整方案

> 目标：为 OmicHub 平台构建支持多物种（生菜、番茄、拟南芥、水稻、Human、Mouse、大鼠、食蟹猴）的离线 KEGG & GO 基因集数据库，实现与 gseapy 的无缝对接

---

## 一、方案概述

### 核心策略

```
KEGG REST API ──→ 下载 pathway-gene 映射 ──→ 转换为 GMT 格式 ──→ gseapy 直接使用
     ↑                                              ↑
  定期更新                                      OmicHub 数据库管理模块
     │                                              │
GO 官网/UniProt ──→ 下载 GAF/GPAD 注释文件 ──→ goatools / 自定义解析
```

### 关键事实

| 项目 | 说明 |
|------|------|
| **KEGG FTP** | 2012年后已关闭免费学术访问，现需商业订阅 |
| **KEGG REST API** | 免费开放，支持学术使用，是离线数据获取的主要途径 |
| **数据更新频率** | KEGG 建议至少每月更新一次；GO 每月发布新版本 |
| **gseapy 兼容性** | 直接支持 GMT 文件格式和 Python dict，完美对接 |

---

## 二、各物种 KEGG Organism Code 汇总

| 物种 | 学名 | KEGG Code | Taxonomy ID | 类别 |
|------|------|-----------|-------------|------|
| **生菜** | Lactuca sativa | `lsv` | 4236 | 植物 (Asterales) |
| **番茄** | Solanum lycopersicum | `sly` | 4081 | 植物 (Solanales) |
| **拟南芥** | Arabidopsis thaliana | `ath` | 3702 | 植物 (Brassicales) |
| **水稻** | Oryza sativa japonica | `osa` | 4530 | 植物 (Poales) |
| **Human** | Homo sapiens | `hsa` | 9606 | 哺乳动物 |
| **Mouse** | Mus musculus | `mmu` | 10090 | 哺乳动物 |
| **大鼠** | Rattus norvegicus | `rno` | 10116 | 哺乳动物 |
| **食蟹猴** | Macaca fascicularis | `mcf` | 9541 | 哺乳动物 |

---

## 三、KEGG 数据库离线获取

### 3.1 KEGG REST API 核心接口

API 基础地址：`https://rest.kegg.jp/`

| 操作 | URL 格式 | 用途 |
|------|----------|------|
| `list` | `/list/pathway/{org}` | 获取某物种所有 pathway 列表 |
| `link` | `/link/{org}/pathway` | 获取 pathway-gene 映射关系 |
| `get` | `/get/{entry}` | 获取特定 entry 详细信息 |
| `conv` | `/conv/ncbi-geneid/{org}` | KEGG ID ↔ NCBI Gene ID 转换 |
| `find` | `/find/genes/{keyword}` | 搜索基因 |

### 3.2 推荐 Python 工具包

```bash
# 方案 A：Biopython（内置 KEGG REST 接口）
pip install biopython

# 方案 B：KEGGRESTpy（更现代的封装）
pip install KEGGRESTpy

# 方案 C：bioservices（统一多数据库接口，含 KEGG）
pip install bioservices
```

### 3.3 批量下载 KEGG 数据的 Python 脚本

```python
#!/usr/bin/env python3
"""
KEGG 离线数据库下载工具
支持多物种 pathway-gene 映射下载，输出 GMT 格式供 gseapy 使用
"""

import requests
import pandas as pd
from pathlib import Path
import time
import json
from datetime import datetime


class KEGGDownloader:
    """KEGG 数据下载器"""
    
    BASE_URL = "https://rest.kegg.jp"
    
    # 支持的物种配置
    ORGANISMS = {
        "lsv": {"name": "Lactuca sativa", "common": "lettuce", "taxid": 4236},
        "sly": {"name": "Solanum lycopersicum", "common": "tomato", "taxid": 4081},
        "ath": {"name": "Arabidopsis thaliana", "common": "arabidopsis", "taxid": 3702},
        "osa": {"name": "Oryza sativa japonica", "common": "rice", "taxid": 4530},
        "hsa": {"name": "Homo sapiens", "common": "human", "taxid": 9606},
        "mmu": {"name": "Mus musculus", "common": "mouse", "taxid": 10090},
        "rno": {"name": "Rattus norvegicus", "common": "rat", "taxid": 10116},
        "mcf": {"name": "Macaca fascicularis", "common": "cynomolgus_monkey", "taxid": 9541},
    }
    
    def __init__(self, output_dir: str = "./kegg_db", delay: float = 0.5):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OmicHub-KEGG-Downloader/1.0 (Academic Use)"
        })
    
    def _get(self, endpoint: str, retries: int = 3) -> str:
        """带重试的 GET 请求"""
        url = f"{self.BASE_URL}/{endpoint}"
        for attempt in range(retries):
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise
                time.sleep(self.delay * (attempt + 1))
        return ""
    
    def download_pathway_list(self, org: str) -> pd.DataFrame:
        """
        下载某物种的所有 pathway 列表
        返回: DataFrame [pathway_id, pathway_name]
        """
        print(f"[+] 下载 {org} 的 pathway 列表...")
        data = self._get(f"list/pathway/{org}")
        
        rows = []
        for line in data.strip().split('\n'):
            if '\t' in line:
                pid, pname = line.split('\t', 1)
                pid = pid.replace("path:", "")
                rows.append({"pathway_id": pid, "pathway_name": pname})
        
        df = pd.DataFrame(rows)
        print(f"    共 {len(df)} 条 pathway")
        return df
    
    def download_pathway2gene(self, org: str) -> pd.DataFrame:
        """
        下载 pathway-gene 映射关系
        返回: DataFrame [gene_id, pathway_id]
        """
        print(f"[+] 下载 {org} 的 pathway-gene 映射...")
        data = self._get(f"link/{org}/pathway")
        
        rows = []
        for line in data.strip().split('\n'):
            if '\t' in line:
                gene, pathway = line.split('\t', 1)
                gene = gene.replace(f"{org}:", "")
                pathway = pathway.replace("path:", "")
                rows.append({"gene_id": gene, "pathway_id": pathway})
        
        df = pd.DataFrame(rows)
        print(f"    共 {len(df)} 条 gene-pathway 映射")
        return df
    
    def convert_to_gmt(self, org: str, output_file: str = None) -> Path:
        """
        下载并转换为 GMT 格式文件
        GMT 格式: pathway_name\tpathway_id\tgene1\tgene2\t...
        """
        info = self.ORGANISMS.get(org, {})
        common_name = info.get("common", org)
        
        if output_file is None:
            output_file = self.output_dir / f"KEGG_{org}_{common_name}.gmt"
        else:
            output_file = Path(output_file)
        
        # 下载数据
        pathways = self.download_pathway_list(org)
        p2g = self.download_pathway2gene(org)
        
        # 构建 pathway_id → pathway_name 映射
        path_names = dict(zip(pathways["pathway_id"], pathways["pathway_name"]))
        
        # 按 pathway 分组聚合基因
        grouped = p2g.groupby("pathway_id")["gene_id"].apply(list).reset_index()
        
        # 写入 GMT 文件
        with open(output_file, 'w') as f:
            for _, row in grouped.iterrows():
                pid = row["pathway_id"]
                pname = path_names.get(pid, pid)
                genes = '\t'.join(row["gene_id"])
                f.write(f"{pname}\t{pid}\t{genes}\n")
        
        print(f"[✓] GMT 文件已保存: {output_file}")
        print(f"    Pathway 数量: {len(grouped)}")
        return output_file
    
    def convert_to_gseapy_dict(self, org: str) -> dict:
        """
        转换为 gseapy 可直接使用的 dict 格式
        返回: {pathway_name: [gene1, gene2, ...], ...}
        """
        pathways = self.download_pathway_list(org)
        p2g = self.download_pathway2gene(org)
        
        path_names = dict(zip(pathways["pathway_id"], pathways["pathway_name"]))
        
        result = {}
        for pid, group in p2g.groupby("pathway_id"):
            pname = path_names.get(pid, pid)
            result[pname] = group["gene_id"].tolist()
        
        return result
    
    def download_all_species(self):
        """批量下载所有配置的物种"""
        metadata = {
            "created_at": datetime.now().isoformat(),
            "source": "KEGG REST API",
            "url": self.BASE_URL,
            "species": {}
        }
        
        for org in self.ORGANISMS:
            print(f"\n{'='*50}")
            print(f"处理物种: {org} ({self.ORGANISMS[org]['name']})")
            print(f"{'='*50}")
            
            try:
                gmt_file = self.convert_to_gmt(org)
                pathways = self.download_pathway_list(org)
                p2g = self.download_pathway2gene(org)
                
                metadata["species"][org] = {
                    "scientific_name": self.ORGANISMS[org]["name"],
                    "common_name": self.ORGANISMS[org]["common"],
                    "pathway_count": len(pathways),
                    "gene_pathway_mapping_count": len(p2g),
                    "gmt_file": str(gmt_file),
                    "download_time": datetime.now().isoformat()
                }
                
                time.sleep(self.delay)
            except Exception as e:
                print(f"[✗] {org} 下载失败: {e}")
                metadata["species"][org] = {"error": str(e)}
        
        # 保存元数据
        meta_file = self.output_dir / "metadata.json"
        with open(meta_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        print(f"\n[✓] 元数据已保存: {meta_file}")
        return metadata


# ============ 使用示例 ============

if __name__ == "__main__":
    downloader = KEGGDownloader(output_dir="./kegg_offline_db")
    
    # 下载单个物种
    # downloader.convert_to_gmt("ath")  # 拟南芥
    
    # 下载全部物种
    downloader.download_all_species()
    
    # 获取 gseapy 可用的 dict 格式
    # gene_sets = downloader.convert_to_gseapy_dict("hsa")
    # gseapy.enrichr(gene_list=genes, gene_sets=gene_sets, ...)
```

### 3.4 使用 Biopython 的简化方案

```python
from Bio.KEGG import REST
import time

def download_kegg_gmt_biopython(org: str, output_file: str):
    """使用 Biopython 下载 KEGG 数据并转为 GMT"""
    
    # 获取 pathway 列表
    pathways = REST.kegg_list("pathway", org).read()
    path_dict = {}
    for line in pathways.strip().split('\n'):
        pid, pname = line.split('\t')
        pid = pid.replace("path:", "")
        path_dict[pid] = pname
    
    # 获取 pathway-gene 映射
    links = REST.kegg_link(org, "pathway").read()
    
    # 构建 GMT
    from collections import defaultdict
    path2genes = defaultdict(list)
    for line in links.strip().split('\n'):
        gene, pathway = line.split('\t')
        gene = gene.replace(f"{org}:", "")
        pathway = pathway.replace("path:", "")
        path2genes[pathway].append(gene)
    
    with open(output_file, 'w') as f:
        for pid, genes in path2genes.items():
            pname = path_dict.get(pid, pid)
            f.write(f"{pname}\t{pid}\t{'\t'.join(genes)}\n")
    
    print(f"Saved: {output_file} ({len(path2genes)} pathways)")

# 使用
download_kegg_gmt_biopython("ath", "KEGG_arabidopsis.gmt")
```

---

## 四、GO 数据库离线获取

### 4.1 GO 注释数据来源

| 来源 | 网址 | 格式 | 适用场景 |
|------|------|------|----------|
| **GO 官网** | http://current.geneontology.org/annotations/ | GAF 2.2 | 官方权威注释 |
| **UniProt GOA** | ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/proteomes/ | GAF | 覆盖 20,000+ 物种 |
| **NCBI gene2go** | ftp://ftp.ncbi.nih.gov/gene/DATA/gene2go.gz | 自定义 | 基于 NCBI Gene ID |
| **QuickGO** | https://www.ebi.ac.uk/QuickGO/ | 多种格式 | 查询、过滤、下载 |

### 4.2 各物种 GO 注释下载地址

#### Human (9606)
```bash
# GO 官网 GAF
wget http://current.geneontology.org/annotations/goa_human.gaf.gz

# NCBI gene2go (包含所有物种，需过滤)
wget ftp://ftp.ncbi.nih.gov/gene/DATA/gene2go.gz
```

#### Mouse (10090)
```bash
wget http://current.geneontology.org/annotations/mgi.gaf.gz
```

#### Rat (10116)
```bash
wget http://current.geneontology.org/annotations/rgd.gaf.gz
```

#### 食蟹猴 (9541)
```bash
# 通过 UniProt GOA 获取
wget ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/proteomes/9541.M_fascicularis.goa.gz
```

#### 拟南芥 (3702)
```bash
wget http://current.geneontology.org/annotations/tair.gaf.gz
```

#### 水稻 (4530)
```bash
wget http://current.geneontology.org/annotations/goa_rice.gaf.gz
# 或
wget ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/proteomes/4530.O_sativa.goa.gz
```

#### 生菜 (4236) & 番茄 (4081)
```bash
# 通过 UniProt GOA 获取
wget ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/proteomes/4236.L_sativa.goa.gz
wget ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/proteomes/4081.S_lycopersicum.goa.gz
```

### 4.3 GO 数据转换为 GMT 格式的 Python 脚本

```python
#!/usr/bin/env python3
"""
GO 注释数据转 GMT 格式工具
支持 GAF 文件解析，输出 BP/MF/CC 三个子集的 GMT 文件
"""

import gzip
import pandas as pd
from pathlib import Path
from collections import defaultdict
import urllib.request


class GODownloader:
    """GO 数据下载与转换工具"""
    
    # 各物种的 GAF 文件下载地址
    GAF_URLS = {
        "human": {
            "url": "http://current.geneontology.org/annotations/goa_human.gaf.gz",
            "id_col": "DB_Object_ID"  # UniProt ID
        },
        "mouse": {
            "url": "http://current.geneontology.org/annotations/mgi.gaf.gz",
            "id_col": "DB_Object_ID"  # MGI ID
        },
        "rat": {
            "url": "http://current.geneontology.org/annotations/rgd.gaf.gz",
            "id_col": "DB_Object_ID"  # RGD ID
        },
        "cynomolgus_monkey": {
            "url": "ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/proteomes/9541.M_fascicularis.goa.gz",
            "id_col": "DB_Object_ID"
        },
        "arabidopsis": {
            "url": "http://current.geneontology.org/annotations/tair.gaf.gz",
            "id_col": "DB_Object_ID"  # TAIR ID
        },
        "rice": {
            "url": "http://current.geneontology.org/annotations/goa_rice.gaf.gz",
            "id_col": "DB_Object_ID"
        },
        "lettuce": {
            "url": "ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/proteomes/4236.L_sativa.goa.gz",
            "id_col": "DB_Object_ID"
        },
        "tomato": {
            "url": "ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/proteomes/4081.S_lycopersicum.goa.gz",
            "id_col": "DB_Object_ID"
        },
    }
    
    # GO 命名空间映射
    NS_MAP = {
        "P": "BP",
        "F": "MF", 
        "C": "CC"
    }
    
    def __init__(self, output_dir: str = "./go_db"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def download_gaf(self, species: str, cache_dir: str = "./gaf_cache") -> Path:
        """下载 GAF 文件（带缓存）"""
        cache = Path(cache_dir)
        cache.mkdir(exist_ok=True)
        
        url = self.GAF_URLS[species]["url"]
        filename = url.split('/')[-1]
        cached_file = cache / filename
        
        if not cached_file.exists():
            print(f"[+] 下载 {species} 的 GAF 文件...")
            urllib.request.urlretrieve(url, cached_file)
            print(f"    已保存: {cached_file}")
        else:
            print(f"[*] 使用缓存: {cached_file}")
        
        return cached_file
    
    def parse_gaf(self, gaf_file: Path) -> pd.DataFrame:
        """解析 GAF 文件"""
        print(f"[+] 解析 GAF: {gaf_file}")
        
        open_func = gzip.open if str(gaf_file).endswith('.gz') else open
        
        rows = []
        with open_func(gaf_file, 'rt') as f:
            for line in f:
                if line.startswith('!'):
                    continue
                cols = line.strip().split('\t')
                if len(cols) < 15:
                    continue
                rows.append({
                    "db": cols[0],
                    "db_object_id": cols[1],
                    "db_object_symbol": cols[2],
                    "qualifier": cols[3],
                    "go_id": cols[4],
                    "reference": cols[5],
                    "evidence_code": cols[6],
                    "with_from": cols[7],
                    "namespace": cols[8],  # P/F/C
                    "db_object_name": cols[9],
                    "db_object_synonym": cols[10],
                    "db_object_type": cols[11],
                    "taxon": cols[12],
                    "date": cols[13],
                    "assigned_by": cols[14],
                })
        
        df = pd.DataFrame(rows)
        print(f"    共 {len(df)} 条注释记录")
        return df
    
    def convert_to_gmt(self, species: str, use_symbol: bool = True) -> dict:
        """
        将 GAF 转换为 BP/MF/CC 三个 GMT 文件
        返回: {"BP": Path, "MF": Path, "CC": Path}
        """
        gaf_file = self.download_gaf(species)
        df = self.parse_gaf(gaf_file)
        
        # 过滤有效的 GO 注释（排除 NOT 限定符）
        df = df[~df["qualifier"].str.contains("NOT", na=False)]
        
        # 获取 GO term 名称（需要 OBO 文件，这里用 ID 代替）
        go_names = self._load_go_names()
        
        results = {}
        
        for ns_code, ns_name in self.NS_MAP.items():
            ns_df = df[df["namespace"] == ns_code]
            
            # 选择基因 ID 列
            if use_symbol and ns_df["db_object_symbol"].notna().any():
                gene_col = "db_object_symbol"
            else:
                gene_col = "db_object_id"
            
            # 按 GO term 分组
            grouped = ns_df.groupby("go_id")[gene_col].apply(
                lambda x: list(set(x.dropna()))
            ).reset_index()
            
            # 添加 GO term 名称
            grouped["go_name"] = grouped["go_id"].map(go_names).fillna(grouped["go_id"])
            
            # 写入 GMT
            output_file = self.output_dir / f"GO_{ns_name}_{species}.gmt"
            with open(output_file, 'w') as f:
                for _, row in grouped.iterrows():
                    go_id = row["go_id"]
                    go_name = row["go_name"]
                    genes = '\t'.join(row[gene_col])
                    f.write(f"{go_name}\t{go_id}\t{genes}\n")
            
            results[ns_name] = output_file
            print(f"[✓] {ns_name}: {len(grouped)} terms -> {output_file}")
        
        return results
    
    def _load_go_names(self) -> dict:
        """加载 GO term 名称（从 OBO 文件）"""
        obo_file = self.output_dir / "go.obo"
        
        if not obo_file.exists():
            print("[+] 下载 GO OBO 文件...")
            urllib.request.urlretrieve(
                "http://current.geneontology.org/ontology/go.obo",
                obo_file
            )
        
        names = {}
        current_id = None
        
        with open(obo_file) as f:
            for line in f:
                if line.startswith("id: GO:"):
                    current_id = line.strip().replace("id: ", "")
                elif line.startswith("name: ") and current_id:
                    names[current_id] = line.strip().replace("name: ", "")
                    current_id = None
        
        return names
    
    def download_all_species(self):
        """批量处理所有物种"""
        for species in self.GAF_URLS:
            print(f"\n{'='*50}")
            print(f"处理物种: {species}")
            print(f"{'='*50}")
            try:
                self.convert_to_gmt(species)
            except Exception as e:
                print(f"[✗] 失败: {e}")


# ============ 使用示例 ============
if __name__ == "__main__":
    go = GODownloader(output_dir="./go_offline_db")
    
    # 处理单个物种
    # go.convert_to_gmt("arabidopsis")
    
    # 批量处理
    go.download_all_species()
```

---

## 五、与 gseapy 的整合使用

### 5.1 使用自定义 KEGG GMT 文件

```python
import gseapy as gp

# 使用离线 KEGG GMT 文件进行 ORA
gp.enrich(
    gene_list=your_gene_list,           # 差异基因列表
    gene_sets="./kegg_db/KEGG_ath_arabidopsis.gmt",
    background=total_genes,              # 背景基因集
    outdir="./enrichment_results"
)

# 使用离线 KEGG 进行 GSEA
ranked_genes = pd.Series(statistics, index=gene_list)  # 排序后的基因
ranked_genes = ranked_genes.sort_values(ascending=False)

gp.prerank(
    rnk=ranked_genes,
    gene_sets="./kegg_db/KEGG_ath_arabidopsis.gmt",
    outdir="./gsea_results"
)
```

### 5.2 使用 dict 格式（不依赖文件）

```python
from kegg_downloader import KEGGDownloader

# 直接从 KEGG API 加载为 dict（首次运行时下载）
downloader = KEGGDownloader()
gene_sets = downloader.convert_to_gseapy_dict("ath")

# 直接使用 dict
gp.enrich(gene_list=genes, gene_sets=gene_sets, ...)
```

### 5.3 使用 goatools 进行 GO 富集（替代方案）

```bash
pip install goatools
```

```python
from goatools.base import download_go_basic_obo
from goatools.associations import read_gaf
from goatools.go_enrichment import GOEnrichmentStudy

# 下载 OBO 文件
obo_file = download_go_basic_obo("go.obo")

# 加载 GAF 注释
assoc = read_gaf("tair.gaf.gz", namespace='BP')  # 仅 BP

# 获取该物种的所有基因作为背景
geneid2gos = assoc.get_geneid2gos()
all_genes = list(geneid2gos.keys())

# 运行富集分析
go = GOEnrichmentStudy(
    all_genes,           # 背景基因
    geneid2gos,          # 基因-GO 映射
    obo_file,            # GO 本体文件
    methods=['fdr_bh']   # 多重检验校正
)

results = go.run_study(your_study_genes)
go.print_results(results)
```

---

## 六、自动化数据库更新方案

### 6.1 建议的目录结构

```
omic_hub_db/
├── kegg/
│   ├── KEGG_lsv_lettuce.gmt
│   ├── KEGG_sly_tomato.gmt
│   ├── KEGG_ath_arabidopsis.gmt
│   ├── KEGG_osa_rice.gmt
│   ├── KEGG_hsa_human.gmt
│   ├── KEGG_mmu_mouse.gmt
│   ├── KEGG_rno_rat.gmt
│   ├── KEGG_mcf_cynomolgus_monkey.gmt
│   └── metadata.json          # 版本记录
├── go/
│   ├── go.obo                 # GO 本体文件（所有物种共用）
│   ├── GO_BP_human.gmt
│   ├── GO_MF_human.gmt
│   ├── GO_CC_human.gmt
│   ├── GO_BP_arabidopsis.gmt
│   └── ...
└── msigdb/
    └── h.all.v2023.1.Hs.symbols.gmt  # MSigDB Hallmark 等
```

### 6.2 定时更新脚本（crontab）

```bash
#!/bin/bash
# update_omic_hub_db.sh - 每月 1 号凌晨 3 点更新

DB_DIR="/data/omichub/db"
LOG_FILE="$DB_DIR/update.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$DATE] 开始更新数据库..." >> $LOG_FILE

# 激活 Python 环境
source /data/omichub/venv/bin/activate

# 更新 KEGG
echo "[$DATE] 更新 KEGG..." >> $LOG_FILE
python /data/omichub/scripts/kegg_downloader.py >> $LOG_FILE 2>&1

# 更新 GO
echo "[$DATE] 更新 GO..." >> $LOG_FILE
python /data/omichub/scripts/go_downloader.py >> $LOG_FILE 2>&1

# 记录版本
DATE=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$DATE] 数据库更新完成" >> $LOG_FILE
```

```bash
# crontab -e
0 3 1 * * /bin/bash /data/omichub/scripts/update_omic_hub_db.sh
```

### 6.3 版本管理

```python
# 在 platform 数据库中记录版本信息
{
    "database_version": {
        "kegg": {
            "last_updated": "2026-07-08",
            "api_version": "REST API 2026-07",
            "species_count": 8
        },
        "go": {
            "last_updated": "2026-07-08", 
            "obo_version": "releases/2026-07-01",
            "annotation_source": "UniProt GOA + GO Consortium"
        }
    }
}
```

---

## 七、工具包对比与选型建议

| 工具 | 用途 | 离线支持 | 与 gseapy 配合 | 推荐场景 |
|------|------|---------|---------------|---------|
| **gseapy** | GSEA/ORA/Prerank/ssGSEA/GSVA | ✅ 支持自定义 GMT | 自身 | 核心分析引擎 |
| **goatools** | GO 富集分析 | ✅ 完全离线 | 互补 | GO 专门分析 |
| **KEGGRESTpy** | KEGG API 访问 | ❌ 需网络 | 数据下载 | KEGG 数据获取 |
| **bioservices** | 多数据库统一接口 | ❌ 需网络 | 数据下载 | 多数据库查询 |
| **Biopython** | KEGG REST 等 | ❌ 需网络 | 数据下载 | 已有 Biopython 环境 |

### 推荐组合

```
OmicHub 平台推荐技术栈:
├── 分析引擎: gseapy (GSEA + ORA + ssGSEA + GSVA)
├── GO 分析: goatools (备选，处理 GO 层级等细节)
├── 数据获取: 自研 KEGGDownloader + GODownloader (基于 requests)
├── 数据格式: GMT (标准格式，gseapy 原生支持)
└── 更新机制: cron 定时任务 + 版本元数据管理
```

---

## 八、常见问题

### Q1: KEGG API 有频率限制吗？
有。建议请求间隔 ≥ 0.5 秒，大批量下载时控制在 1-2 秒/请求。

### Q2: 植物物种在 KEGG 中的注释质量如何？
拟南芥(ath)和水稻(osa)注释较完善。生菜(lsv)和番茄(sly)的 pathway 覆盖可能不如模式生物全面，但足以支持常规富集分析。

### Q3: GO 注释的 ID 类型不统一怎么办？
- GAF 文件中的 `DB_Object_ID` 可能是 UniProt/TAIR/RGD 等不同 ID
- 建议统一转换为 Gene Symbol 后再进行富集分析
- 可在平台中维护各物种的 ID 映射表

### Q4: 如何处理 KEGG API 临时不可用？
- 实现指数退避重试（见脚本中的 `_get` 方法）
- 保留上一次成功下载的数据作为 fallback
- 在平台前端提示用户"使用缓存数据"

### Q5: 食蟹猴(mcf)的基因 ID 用什么？
食蟹猴使用 NCBI Gene ID（数字格式），与人的 Entrez ID 体系一致。如需要与人比较，可通过 ortholog 映射转换。

---

## 九、总结

| 能力 | 方案 | 状态 |
|------|------|------|
| **KEGG 离线数据库** | REST API → Python 脚本 → GMT 格式 | ✅ 完整方案，代码已提供 |
| **GO 离线数据库** | GAF 文件 → Python 解析 → GMT 格式 | ✅ 完整方案，代码已提供 |
| **8 物种全覆盖** | lsv/sly/ath/osa/hsa/mmu/rno/mcf | ✅ 全部确认 |
| **gseapy 兼容** | 直接读取 GMT 或 dict 格式 | ✅ 原生支持 |
| **自动更新** | cron + Python 脚本 + 版本记录 | ✅ 方案已提供 |

**这套方案可以让你彻底摆脱对 ClusterProfiler 的 R 依赖，在纯 Python 环境中完成所有富集分析功能。**
