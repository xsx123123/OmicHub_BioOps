# scrna-pipeline-core 参考数据 Provisioning 指南

管理员需在平台共享数据卷预置以下内容，供技能运行时读取。

## 1. scRNAseqMulticommand 主流程仓库

**路径**: `ref/scRNAseqMulticommand/`

**必需文件**:
```
ref/scRNAseqMulticommand/
├── scRNAseqMulticommand          # 主入口脚本
├── scRNAseqMulticommand.yaml     # YAML 配置
├── src/
│   ├── init/                     # 初始化模块
│   ├── cli/                      # CLI 工具函数
│   └── core/                     # 核心分析逻辑
├── report/                       # Quarto 报告模板 (~3MB)
│   ├── _quarto.yml
│   ├── index.qmd
│   └── data/                     # (运行时创建 symlink)
├── build_analysis_env/           # Dockerfile + conda env
│   ├── multiStage.Dockerfile
│   └── scRNAseqMulticommand_environment.yml
└── Celldex/                      # SingleR reference + marker DB
    ├── HumanPrimaryCellAtla.rds
    ├── HumanBlueprintEncode.rds
    ├── HumanDICEImmuneCell.rds
    ├── HumanMonacoImmune.rds
    ├── HumanNovershternHematopoietic.rds
    ├── MouseRNA.rds
    ├── MouseImmGen.rds
    ├── Cell_marker_Human.txt
    ├── Cell_marker_Mouse.txt
    ├── PanglaoDB_markers_27_Mar_2020.tsv
    └── ScTypeDB_full.xlsx
```

**⚠️ 重要**: 
- **位置需可写**：渲染时会写入 `report/data/current` symlink 和 `report/_site/`
- **Celldex 子目录**：仓库内的 `Celldex/` 必须包含所有 7 个 rds + 4 个 marker 文件
- **版本**: v4.1.2-alpha（当前）

### Provision 命令示例

```bash
# 从 git repo clone
git clone https://github.com/OmicHub/pipelines/scrna.git ref/scRNAseqMulticommand

# 或 rsync 本地副本
rsync -a /path/to/local/scrna/ ref/scRNAseqMulticommand/ --delete
```

### 验证命令

```bash
# 检查关键文件
ls ref/scRNAseqMulticommand/scRNAseqMulticommand
ls ref/scRNAseqMulticommand/Celldex/HumanPrimaryCellAtla.rds
ls ref/scRNAseqMulticommand/report/_quarto.yml

# 检查权限（需可写）
touch ref/scRNAseqMulticommand/report/test_write && rm ref/scRNAseqMulticommand/report/test_write
```

## 2. DEG 注释参考数据

**路径**: `ref/DEG_Annotation_reference/`

**必需文件**:
```
ref/DEG_Annotation_reference/
├── hg19_Homo_sapiens.gene_info   # 人类 gene info (~25MB)
├── mm10_Mus_musculus.gene_info   # 小鼠 gene info (~20MB)
└── hg38_Homo_sapiens.gene_info   # 人类 hg38 版本 (可选)
```

**来源**: NCBI Gene Reference Gene Info (gene_info.gz → tab-separated)

### Provision 命令示例

```bash
# 下载并解压
cd ref/DEG_Annotation_reference
wget https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene_info/gene_info_HUMAN.gz
wget https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene_info/gene_info_MOUSE.gz
gunzip *.gz

# 转换为 tab-separated (如需要)
awk 'BEGIN{FS="\t"; OFS="\t"} {print $3, $4, $5, $6, $7, $8}' hg19_Homo_sapiens.gene_info > hg19_Homo_sapiens.gene_info.tsv
```

### 验证命令

```bash
# 检查文件大小（应 ~20-25MB）
ls -lh ref/DEG_Annotation_reference/*.gene_info

# 检查内容
head -3 ref/DEG_Annotation_reference/hg19_Homo_sapiens.gene_info
```

## 3. SCVI Conda 环境（可选）

如需使用 SCVI 整合方法，需提供单独 conda 环境路径。

**路径**: `/home/zj/miniconda3/envs/scvi` (示例)

**必需包**:
```bash
scvi-tools>=1.0
anndata>=0.8
pytorch>=1.12
```

### Provision 命令示例

```bash
# 创建 scvi 环境
conda create -n scvi python=3.9
conda activate scvi
pip install scvi-tools anndata pytorch
```

### 验证命令

```bash
# 测试导入
python -c "import scvi; print(scvi.__version__)"
```

## 4. Celldex Reference Data（独立 provision）

如果不想将 Celldex 放在 `ref/scRNAseqMulticommand/Celldex/`，可以独立 provision。

**路径**: `ref/Celldex/`

**必需文件**: 同上述 scRNAseqMulticommand/Celldex/ 清单

### Provision 命令示例

```bash
# 从 Bioconductor ExperimentHub 下载
Rscript -e '
library(celldex)
saveRDS(HumanPrimaryCellAtlasData(), "ref/Celldex/HumanPrimaryCellAtla.rds")
saveRDS(BlueprintEncodeData(), "ref/Celldex/HumanBlueprintEncode.rds")
saveRDS(DatabaseImmuneCellExpressionData(), "ref/Celldex/HumanDICEImmuneCell.rds")
saveRDS(MonacoImmuneData(), "ref/Celldex/HumanMonacoImmune.rds")
saveRDS(NovershternHematopoieticData(), "ref/Celldex/HumanNovershternHematopoietic.rds")
saveRDS(MouseRNAseqData(), "ref/Celldex/MouseRNA.rds")
saveRDS(ImmGenData(), "ref/Celldex/MouseImmGen.rds")
'

# 复制 marker 数据库
cp pipelines/scrna/Celldex/{Cell_marker_Human.txt,Cell_marker_Mouse.txt,PanglaoDB_markers_27_Mar_2020.tsv,ScTypeDB_full.xlsx} ref/Celldex/
```

## 完整 Provision 检查清单

运行以下脚本验证所有必需文件存在：

```bash
#!/bin/bash
# check_provision.sh

set -e

echo "=== Checking scrna-pipeline-core provisioning ==="

# 1. scRNAseqMulticommand
if [[ ! -f "ref/scRNAseqMulticommand/scRNAseqMulticommand" ]]; then
    echo "❌ Missing: ref/scRNAseqMulticommand/scRNAseqMulticommand"
    exit 1
fi
echo "✅ ref/scRNAseqMulticommand/scRNAseqMulticommand"

# 2. Celldex
for f in HumanPrimaryCellAtla.rds HumanBlueprintEncode.rds HumanDICEImmuneCell.rds HumanMonacoImmune.rds HumanNovershternHematopoietic.rds MouseRNA.rds MouseImmGen.rds Cell_marker_Human.txt Cell_marker_Mouse.txt PanglaoDB_markers_27_Mar_2020.tsv ScTypeDB_full.xlsx; do
    if [[ ! -f "ref/scRNAseqMulticommand/Celldex/$f" ]]; then
        echo "❌ Missing: ref/scRNAseqMulticommand/Celldex/$f"
        exit 1
    fi
done
echo "✅ ref/scRNAseqMulticommand/Celldex/"

# 3. DEG annotation
for f in hg19_Homo_sapiens.gene_info mm10_Mus_musculus.gene_info; do
    if [[ ! -f "ref/DEG_Annotation_reference/$f" ]]; then
        echo "❌ Missing: ref/DEG_Annotation_reference/$f"
        exit 1
    fi
done
echo "✅ ref/DEG_Annotation_reference/"

# 4. Report template
if [[ ! -f "ref/scRNAseqMulticommand/report/_quarto.yml" ]]; then
    echo "❌ Missing: ref/scRNAseqMulticommand/report/_quarto.yml"
    exit 1
fi
echo "✅ ref/scRNAseqMulticommand/report/"

echo ""
echo "=== All provisioning checks passed! ==="
```

## 容量规划

| 数据项 | 大小 | 说明 |
|--------|------|------|
| scRNAseqMulticommand repo | ~50MB | 含代码、YAML、Dockerfile |
| Celldex rds files | ~500MB | 7 个 SingleR reference |
| Marker databases | ~50MB | CellMarker + PanglaoDB + ScTypeDB |
| DEG gene_info | ~47MB | hg19/mm10/hg38 |
| **总计** | **~650MB** | 不含中间产物 |

建议预留 **2GB** 空间用于未来扩展。
