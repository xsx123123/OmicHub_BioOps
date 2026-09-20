---
name: scrna-pipeline-core
description: 从单细胞基因表达矩阵到注释结果的完整分析流程（标准全流程）
version: 0.9.1
author: Zhang Jian
date: 2026-09-19
osdp_version: CygnusX OSDP v1.0
skill_id: scrna-pipeline-core
---

# scrna-pipeline-core — 单细胞标准分析全流程

从原始基因表达矩阵（10x Genomics / MGI DNBC4）自动执行 QC、降维聚类、自动注释、可视化及多样本整合，生成可用于下游定制分析的 Seurat 对象和完整结果目录。

## 用途

- **标准分析**: QC → 降维聚类 → 自动注释 → 可视化
- **多样本整合**: CCA / Harmony / RPCA / SCVI 多策略支持
- **跨平台**: 10x Genomics + MGI DNBC4 混合样本
- **下游准备**: 输出最终 Seurat RDS 供 recluster, deg-analysis 等技能使用

## 输入要求

### CSV 配置文件 (`scRNA-seq.conf`)

```csv
CellRanger,name,group,library_type
/path/to/sample1/outs/filtered_feature_bc_matrix,Sample1,Control,10x
/path/to/sample2/outs/filtered_feature_bc_matrix,Sample2,Treatment,10x
/path/to/sample3/outs/filtered_feature_bc_matrix,Sample3,Treatment,DNBC4
```

**必需列**:
- `CellRanger`: CellRanger 输出目录路径（含 `matrix.mtx.gz`）
- `name`: 唯一样本 ID
- `group`: 实验分组（用于差异分析）
- `library_type`: `10x` 或 `DNBC4`（不同文库类型必须区分）

### 命令行参数

| 短选项 | 长选项 | 必填 | 默认值 | 说明 |
|--------|--------|------|--------|------|
| `-c` | `--scRNAseqdataframe` | ✅ | - | 配置文件路径 |
| `-o` | `--outputdir` | ✅ | `./output` | 结果输出目录 |
| `-n` | `--projectname` | ✅ | - | 项目名称/ID |
| `-I` | `--origintaxID` | ✅ | - | 物种 TaxID (9606=人，10090=鼠，3702=拟南芥) |
| `-F` | `--scRNAref` | ✅ | - | Marker 数据库 (`Cellmarker`, `PanglaoDB`, `Custom`) |
| `-O` | `--organ` | ✅ | - | 目标组织 (`Blood`, `Leaf`, `Stomach` 等) |
| `-i` | `--intergetmethods` | ❌ | `CCA` | 整合方法 (`CCA`, `Harmony`, `RPCA`, `ALL`) |
| `-r` | `--reduceType` | ❌ | `FALSE` | 是否使用 tSNE |
| `-a` | `--autofiltedcell` | ❌ | `TRUE` | 是否自动过滤细胞 |
| `-t` | `--threads` | ❌ | `20` | 并行线程数 |

## 输出结构

```bash
{outputdir}/
├── annotation/
│   ├── auto-annotation-CellID      # CellID 注释结果
│   ├── auto-annotation-sctype      # ScType 注释结果
│   ├── auto-annotation-SinglR      # SingleR 注释结果
│   ├── proportions-plot            # 细胞比例统计图
│   └── tSNE-annotation-plot-plot   # UMAP/tSNE 注释可视化
├── BatchCheck                      # 批次效应评估
├── cluster/
│   ├── DoHeatmap-plot              # 聚类热图
│   ├── DotPlot-plot                # 标记基因点图
│   ├── marker_gene                 # 各簇标记基因列表
│   ├── tSNE-plot                   # tSNE 图
│   └── UMAP-plot                   # UMAP 图
├── DealPatch                       # 整合中间文件
├── figure/
│   ├── deg                         # 差异表达分析结果
│   └── subset_cell_cluster         # 子集细胞聚类图
├── output/
│   └── {projectname}-final.rds     # 最终 Seurat 对象（下游技能输入）
└── QC/
    ├── Cellranger-result           # 原始比对统计
    ├── doublet                     # Doublet 检测报告
    └── RNAContamination            # 环境 RNA 污染评估
```

## 使用示例

### 本地模式

```bash
Rscript /workspace/.skills/scrna-pipeline-core/scripts/run_pipeline.R \
  --conf ./scRNA-seq.conf \
  --output ./my_project-scRNA-seq-result \
  --project-name my_project \
  --taxid 9606 \
  --marker-db Cellmarker \
  --organ Blood \
  --integration-method Harmony \
  --threads 20
```

### 平台沙盒模式（推荐）

```bash
Rscript ref/scRNAseqMulticommand/scRNAseqMulticommand \
  -c {conf.csv} -o {outputdir} -n {projectname} \
  -I {taxID} -F {Cellmarker|PanglaoDB|Custom} -O {organ} \
  [-i {CCA|Harmony|RPCA|ALL}] [-t {threads}]
```

### 混合文库类型（10x + DNBC4）

```csv
# scRNA-seq.conf
CellRanger,name,group,library_type
/path/to/sample1/outs/filtered_feature_bc_matrix,Sample1,Control,10x
/path/to/sample2/outs/filtered_feature_bc_matrix,Sample2,Treatment,DNBC4
```

```bash
Rscript ... \
  -c scRNA-seq.conf \
  -o output/ \
  -n mixed_library \
  -I 9606 \
  -F Cellmarker \
  -O Blood
```

## 参考数据 Provisioning

管理员需在共享数据卷预置以下内容：

### 必需

- **`ref/scRNAseqMulticommand/`** - 主流程脚本 + report 模板目录
  - 包含：`scRNAseqMulticommand`, `src/`, `report/`, `build_analysis_env/`
  - ⚠️ **位置需可写**：渲染时会写入 `report/data/current` symlink 和 `report/_site/`
  
- **`ref/Celldex/`** - SingleR reference + marker 数据库
  - Human: `HumanPrimaryCellAtla.rds`, `HumanBlueprintEncode.rds`, `HumanDICEImmuneCell.rds`, `HumanMonacoImmune.rds`, `HumanNovershternHematopoietic.rds`, `Cell_marker_Human.txt`, `PanglaoDB_markers_27_Mar_2020.tsv`, `ScTypeDB_full.xlsx`
  - Mouse: `MouseRNA.rds`, `MouseImmGen.rds`, `Cell_marker_Mouse.txt`

### 可选

- **`ref/scvi/`** - scvi-tools conda 环境路径（如 `/home/zj/miniconda3/envs/scvi`）
- **`ref/DEG_Annotation_reference/`** - DEG 注释 gene_info 文件（hg19/mm10）

## 容量建议

| 资源 | 最小配置 | 推荐配置 |
|------|---------|---------|
| 内存 | 32 GB | ≥64 GB (100k+ cells) |
| 磁盘 | 输入体积 ×3 | 输入体积 ×10 |
| 线程 | 8 | 20–40 |
| 运行时间 | 2–4 小时 | 4–12 小时 |

## 错误处理

### 常见错误

| 错误信息 | 原因 | 解决方案 |
|---------|------|----------|
| `library_type column missing` | CSV 缺少必需列 | 检查配置文件 header |
| `Invalid library_type value` | 值为非 `10x/DNBC4` | 仅允许这两个值 |
| `gene sets mismatch between samples` | 不同文库类型的基因集不匹配 | 确保所有样本使用相同文库类型和参考基因组版本 |
| `SCRNA_DEG_REF_DIR not set` | 未设置环境变量 | `export SCRNA_DEG_REF_DIR=/path/to/ref` |
| `quarto render failed` | Quarto CLI 未安装 | 平台预装或本地安装 |

### 退出码

- **0**: 成功
- **1**: 参数/输入校验失败
- **2**: 分析过程失败

## 下游集成

生成的 `{projectname}-final.rds` 可直接用于以下技能：

```bash
# 重聚类
skill run scrna-recluster --input output/{projectname}-final.rds ...

# 差异表达分析
skill run scrna-deg-analysis --input output/{projectname}-final.rds ...

# T 细胞精细注释
skill run scrna-tcell-projectils --input output/{projectname}-final.rds ...

# 生成 HTML 报告
skill run scrna-quarto-report --result-dir output ...
```

## 版本历史

- **v4.1.2-alpha** (当前): MAD 自适应 QC、动态内存管理、容器化支持
- **v4.1.1**: 每样本文库类型支持、全局库类型参数移除
- **v4.1.0**: 核心重构、动态内存分配

## 相关文档

- [主流程 README](../../README.md)
- [OSDP 规范](../../../docs/Skill_design.md)
- [环境依赖](references/environment.md)
- [参考数据 Provisioning](references/provisioning.md)
