# scRNA-seq Analysis Skills

单细胞分析技能集，包含 8 个独立技能（OSDP v1.0/CygnusX 规范），可在平台沙盒或本地环境中调用。

## 快速开始

### 环境依赖

**R ≥ 4.2**，推荐环境：`/home/zj/.local/share/mamba/envs/scrna/bin/Rscript` (R 4.3.3)

```bash
# 激活环境
conda activate scrna

# 验证 R 包
Rscript -e 'cat("optparse:", requireNamespace("optparse", quietly=TRUE), "\n")'
```

**必装 R 包**：
- `optparse` - CLI 参数解析（所有 wrapper 脚本必需）
- `Seurat` - 对象读写与核心分析
- `log4r`, `crayon` - 日志系统
- `ggplot2`, `patchwork` - 可视化

**GitHub 独占包**（需管理员预装进镜像，沙盒不可达）：
- `ProjecTILs` - T 细胞功能亚型注释
- `scCustomize` - Percent_Expressing 计算

---

## 技能清单

| 技能 ID | 用途 | 输入 | 输出 | 关键依赖 |
|--------|------|------|------|----------|
| `scrna-pipeline-core` | **标准全流程** | 原始基因表达矩阵 (CSV) | `{projectname}-scRNA-seq-result/`, final.rds | Seurat, SingleR, Harmony, scvi |
| `scrna-object-convert` | RDS 对象转换与工具 | Seurat RDS | 转换后 RDS / 信息报告 | Seurat, data.table |
| `scrna-recluster` | 重聚类分析 | Seurat RDS | `{name}-reclustered.rds`, elbow plots, summary.json | Seurat, ggplot2, patchwork |
| `scrna-annotation-stats` | 注释统计 | Seurat RDS + celltype/group 列 | prop/fisher/deg-prop 模式 CSV/PDF/summary.json | Seurat, scCustomize, tidyverse |
| `scrna-deg-analysis` | 差异表达分析 | Seurat RDS + taxid | `{treat}_vs_{control}-{celltype}/` 目录 + summary.json | Seurat, tidyverse, log4r |
| `scrna-tcell-projectils` | T 细胞精细注释 | 含 T 细胞的 Seurat RDS (已有 UMAP) | functional.cluster 注释 RDS + DotPlot | ProjecTILs (GitHub 独占) |
| `scrna-annotation-ref` | 参考数据检查 | Celldex 目录路径 | 检查报告 (exit=0/1) | Seurat |
| `scrna-pipeline-overview` | 主流程概览 | 无 | 命令行用法说明 | 无 |
| `scrna-quarto-report` | 报告生成 | *-scRNA-seq-result 目录 | _site/ HTML 报告 | Quarto CLI |

---

## 工作流程

### 场景 1: 从头开始的标准分析

```bash
# Step 1: 运行完整流程（从原始数据到最终 Seurat 对象）
skill run scrna-pipeline-core \
  --conf ./scRNA-seq.conf \
  --output ./my_project-scRNA-seq-result \
  --project-name my_project \
  --taxid 9606 \
  --marker-db Cellmarker \
  --organ Blood

# Step 2: 基于结果进行定制分析
skill run scrna-deg-analysis --input my_project-scRNA-seq-result/output/my_project-final.rds ...
skill run scrna-recluster --input my_project-scRNA-seq-result/output/my_project-final.rds ...
```

### 场景 2: 已有 Seurat 对象的定制分析

直接调用定制分析技能（recluster, deg-analysis 等），无需运行完整流程。

## 使用示例

### 1. scrna-recluster (重聚类)

```bash
Rscript /workspace/.skills/scrna-recluster/scripts/recluster.R \
  --file /workspace/.skills/scrna-recluster/scripts/recluster.R \
  --input input.rds \
  --output ./recluster_out \
  --name sample1 \
  --resolution 0.8 \
  --nfeatures 2000
```

**输出**:
- `sample1-reclustered.rds` - 重聚类后的 Seurat 对象
- `sample1-pct-ElbowPlot.png` - PCA 肘部图
- `summary.json` - 结构化摘要

---

### 2. scrna-annotation-stats (注释统计)

三种模式可选：

```bash
# 模式 1: 细胞类型比例统计
Rscript /workspace/.skills/scrna-annotation-stats/scripts/annotation_stats.R \
  --input input.rds \
  --output ./stats_out \
  --name sample1 \
  --mode prop

# 模式 2: Fisher 精确检验
Rscript ... --mode fisher

# 模式 3: 基因表达百分比 + 平均表达
Rscript ... --mode pct-exp
```

**输出**:
- `{name}-celltype.prop.csv` - 细胞类型比例表
- `{name}-prop.pdf/png` - 堆叠柱状图
- `summary.json` - 元数据

---

### 3. scrna-deg-analysis (差异表达分析)

```bash
export SCRNA_DEG_REF_DIR=/path/to/DEG_Annotation_reference

Rscript /workspace/.skills/scrna-deg-analysis/scripts/deg_analysis.R \
  --input input.rds \
  --output ./deg_out \
  --treat treated \
  --control ctrl \
  --taxid 9606 \
  --celltype-col celltype \
  --pair-col group
```

**输出**:
- `treated_vs_ctrl-{CellType}/` - 每个细胞类型的 DEG 结果目录
  - `volcano_plot.png` - 火山图
  - `marker_gene_list.csv` - 标记基因列表
- `summary.json` - 汇总统计

---

### 4. scrna-tcell-projectils (T 细胞精细注释)

```bash
Rscript /workspace/.skills/scrna-tcell-projectils/scripts/projectils_annotate.R \
  --input tcell_rna.rds \
  --output ./projectils_out \
  --name patient1 \
  --ref ref/projectils_ref.rds \
  --cores 20
```

**注意**:
- 输入对象必须已包含 UMAP 降维
- `--ref` 为必填项（平台沙盒约定为共享数据卷预置的 `ref/ProjecTILs/projectils_ref.rds`）
- 需要 ProjecTILs 包（GitHub 独占，需管理员预装）

---

### 5. scrna-annotation-ref (参考数据检查)

```bash
# Human (taxid=9606)
Rscript /workspace/.skills/scrna-annotation-ref/scripts/check_reference.R \
  --ref-dir ./Celldex \
  --taxid 9606

# Mouse (taxid=10090)
Rscript ... --taxid 10090
```

**输出**:
- exit=0: 所有文件存在
- exit=1: 列出缺失文件 + 管理员指引

**必需文件**:
- Human: SingleR 7 个 rds + CellMarker_Human.txt + PanglaoDB + ScTypeDB.xlsx
- Mouse: MouseRNA.rds + MouseImmGen.rds + CellMarker_Mouse.txt

---

### 6. scrna-object-convert (RDS 工具)

```bash
# 查看对象信息
Rscript /workspace/.skills/scrna-object-convert/scripts/RDS_utility \
  -i input.rds \
  -p info

# 子集操作
Rscript ... -i input.rds -o subset.rds -p subset \
  -c celltype -v "T cell" -m group -v "treated"

# 合并多个对象
Rscript ... -i obj1.rds,obj2.rds -o merged.rds -p merge
```

---

### 7. scrna-quarto-report (报告生成)

```bash
Rscript /workspace/.skills/scrna-quarto-report/scripts/build_quarto_report.R \
  --result-dir ./my_project-scRNA-seq-result \
  --report-dir ./report \
  --no-render  # 仅生成 JSON，不执行 quarto render
```

**前置条件**:
- 结果目录符合 pipeline 结构（含 QC/, annotation/, cluster/ 等子目录）
- report/ 模板目录已预置（~3MB，需管理员 provision 到共享卷）

---

## 错误处理

### 常见错误

| 错误信息 | 原因 | 解决方案 |
|---------|------|----------|
| `cannot change value of locked binding for 'logger'` | log4r 全局绑定冲突 | 已修复（所有函数库改用 local_logger 模式） |
| `object 'local_logger' not found` | logger 作用域不一致 | 已修复（check_parameter 等函数显式传入 logger 参数） |
| `R 包 ProjecTILs 未安装` | GitHub 独占包未预装 | 联系管理员按 references/provisioning.md 预装 |
| `DEG 注释参考文件缺失` | SCRNA_DEG_REF_DIR 未设置 | 导出环境变量指向 gene_info 目录 |
| `short option -v repeated` | RDS_utility getopt 重复 | 已修复（metadata-value→-V, version→-e） |

### 退出码约定

- **0**: 成功
- **1**: 参数/输入校验失败
- **2**: 分析过程失败

---

## 平台部署指南

### CygnusX / OmicHub 平台

1. **Skill 安装**:
   ```bash
   # 从 marketplace 安装
   skill install scrna-recluster
   skill install scrna-deg-analysis
   # ... 其他技能
   ```

2. **参考数据 Provisioning**:
   - Celldex: `ref/Celldex/` (7 个 SingleR rds + 4 个 marker 文件)
   - DEG annotation: `ref/DEG_Annotation_reference/` (hg19/mm10 gene_info)
   - ProjecTILs: `ref/ProjecTILs/projectils_ref.rds` (~1-2GB)
   - Pipeline repo: `ref/scRNAseqMulticommand/` (含 report/ 模板)

3. **Agent 配置** (`data/ai/scrna.yaml`):
   ```yaml
   skill_ids:
     - scrna-object-convert
     - scrna-recluster
     - scrna-annotation-stats
     - scrna-deg-analysis
     - scrna-tcell-projectils
     - scrna-annotation-ref
     - scrna-pipeline-overview
     - scrna-quarto-report
   ```

---

## 开发维护

### 代码结构

```
skills/
├── <skill-id>/
│   ├── SKILL.md          # OSDP frontmatter + 使用说明
│   ├── scripts/
│   │   ├── <wrapper>.R   # CLI wrapper (optparse)
│   │   └── <library>.r   # 函数库 (local_logger 模式)
│   └── references/
│       ├── environment.md # 环境依赖清单
│       └── provisioning.md # 参考数据 provision 指南
├── README.md             # 本文件
└── tests/integration/    # 集成测试套件
    └── test_skill_workflow.py
```

### 测试流程

**运行完整集成测试**:
```bash
python3 tests/integration/test_skill_workflow.py
```

**测试覆盖**:
1. ✅ RDS_utility --operation info
2. ✅ recluster.R (完整重聚类流程)
3. ✅ annotation_stats.R --mode prop
4. ✅ deg_analysis.R (带基因注释)
5. ✅ projectils_annotate.R (失败路径正确提示)
6. ✅ merge_deg_infor.py
7. ✅ build_quarto_report.R --no-render

**单个技能冒烟测试**:
```bash
# Recluster
Rscript /workspace/.skills/scrna-recluster/scripts/recluster.R \
  --input test.rds --output ./out --name test --resolution 0.8

# Deg analysis
export SCRNA_DEG_REF_DIR=/path/to/ref
Rscript /workspace/.skills/scrna-deg-analysis/scripts/deg_analysis.R \
  --input test.rds --output ./out --treat treated --control ctrl
```

---

## 版本历史

- **v0.9.1** (当前): 全部技能统一 OSDP v1.0 规范，log4r 作用域 bug 修复
- **v0.9.0**: 初始发布，基于 CygnusX Skill Design Protocol

---

## 联系方式

- **Author**: Zhang Jian
- **Repo**: https://github.com/OmicHub/pipelines/scrna
- **Docs**: `docs/Skill_design.md` (OSDP 规范), `references/environment.md` (依赖清单)
