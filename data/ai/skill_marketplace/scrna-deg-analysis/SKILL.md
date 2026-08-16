---
name: 单细胞差异表达分析
skill_id: scrna-deg-analysis
description: 当用户需要对已注释的 scRNA-seq Seurat 对象按"细胞类型 × 分组"做批量差异表达分析（FindMarkers）、基因注释和火山图可视化时触发。输入为 Seurat RDS 对象路径与分组/细胞类型列名。边界：cluster marker 查找（聚类鉴定）由主流程 scrna-pipeline-overview 完成，细胞比例统计走 scrna-annotation-stats，本技能只做"细胞类型内 处理组 vs 对照组"的 DEG。
version: 0.9.0
author: "zj"
icon: 🌋
category: analysis
---

# 单细胞差异表达分析（细胞类型 × 分组批量 DEG）

## 何时使用（Trigger）

- 输入对象已完成细胞注释：Seurat RDS 的 `meta.data` 中同时存在**细胞类型列**（默认 `celltype`）与**分组列**（默认 `group`，须含处理/对照两个水平）；
- 用户意图是"按每个细胞类型分别比较 Treat vs Control 的差异基因"，并要求基因注释（gene_info）与火山图；
- 不适用场景：①cluster marker 查找（cluster-vs-rest 鉴定聚类身份）属于上游主流程，见 `scrna-pipeline-overview`，本技能不含 `multithreadingFindMarkerCluster.r` 等 cluster marker 脚本；②各组细胞比例/组成统计走 `scrna-annotation-stats`；③格式转换走 `scrna-object-convert`。

## 输入契约（Input）

| 参数 | 必填 | 说明 |
|---|---|---|
| `--input` | 是 | Seurat 对象 RDS 路径（只读，不被修改） |
| `--output` | 是 | 产物输出目录（脚本自动创建） |
| `--treat` / `--control` | 是 | 分组列中处理组/对照组水平名；缺失时**先简短追问，不要臆测默认值** |
| `--celltype-col` | 否 | 细胞类型列名，默认 `celltype` |
| `--pair-col` | 否 | 分组列名，默认 `group` |
| `--taxid` | 否 | 物种：9606 人（默认）/ 10090 鼠 |
| `--test` | 否 | FindMarkers 检验方法，默认 `wilcox` |
| `--pval-cutoff` | 否 | p_val_adj 阈值，默认 0.05 |
| `--lfc-cutoff` | 否 | \|avg_log2FC\| 阈值，默认 1 |
| `--pct-1` | 否 | pct.1 过滤阈值，默认 0.25 |
| `--top-gene` | 否 | 火山图上下调各标注 top N 基因，默认 15 |

## 执行步骤（Workflow）

1. **前置校验**（脚本内自动完成，失败即非 0 退出并给出可读错误）：
   - RDS 存在可读；`meta.data` 含 `--celltype-col` / `--pair-col`（缺失时报错并列出实际可用列名）；
   - 分组列含 `--treat` / `--control` 两水平（缺失时列出实际水平）；
   - 每个细胞类型在两组中的细胞数 < 30 时不中断，写入 summary.json 的 `warnings`。
2. **确认注释参考**：环境变量 `SCRNA_DEG_REF_DIR` 指向 gene_info 目录（见"质控与限制"）；未设置时默认相对目录 `DEG_Annotation_reference`。
3. **运行**：

   ```bash
   Rscript scripts/deg_analysis.R \
     --input {seurat.rds}          # 用户输入
     --output {output_dir}         # 用户指定产物目录
     --treat {Treat} --control {Control} \
     [--celltype-col celltype] [--pair-col group] [--taxid 9606]
   ```

4. **汇总计数**（可选但推荐）：合并各细胞类型的上下调基因计数为一张表：

   ```bash
   python3 scripts/merge_deg_infor.py --input {output_dir} --output {output_dir}/merged_DEG_infor.csv
   ```

5. **结果汇报**：只读 `{output_dir}/summary.json` 向用户汇报——`stats.n_celltypes`（完成分析的细胞类型数）、`n_deg_total` / `n_up` / `n_down`、以及 `warnings` 中的小样本预警；不要逐个解析大结果 csv。
6. **异常处理**：退出码非 0 时把 stderr 原样展示给用户，按提示修正列名/组名/参考路径后重跑；**禁止伪造结果**。某细胞类型 FindMarkers 失败时函数库仅记日志跳过，不致命，以 summary.json 与实际目录为准。

## 输出契约（Output）

每个细胞类型一个目录，细胞类型名中的 `/` 会被替换为 `-`：

```
{output}/
├── {Treat}_vs_{Control}-{celltype}/
│   ├── {Treat} vs {Control}{celltype}-DEG.csv        # 全量基因 + log10/log2FC/Group 列
│   ├── ...-DEG-up.csv / ...-DEG-down.csv             # 显著上调/下调子集
│   ├── ...-DEG-infor.csv                             # UP/DOWN 计数（merge_deg_infor.py 的输入）
│   └── ... Volcano Plot-FC-type{1,2,3}.pdf/.png      # 3 种样式火山图
├── summary.json                                      # OSDP §6.3 结构化摘要（必读）
└── merged_DEG_infor.csv                              # 第 4 步可选汇总
```

`summary.json` 结构：`{tool, version, status, outputs:[{path,type}], stats:{n_celltypes,n_deg_total,n_up,n_down}, warnings:[]}`，`outputs.path` 为相对 `--output` 的路径。

## 质控与限制（QC & Constraints）

- **参考数据不进技能包（红线）**：DEG 基因注释依赖 NCBI gene_info（约 47MB），一律走环境变量 `SCRNA_DEG_REF_DIR`（目录内需含 `mm10_Mus_musculus.gene_info` / `hg19_Homo_sapiens.gene_info`）。仓库内参考位于 `tools/DEG/DEG_Annotation_reference/`（另含 `hg38_Homo_sapiens.gene_info`，当前脚本注释用 hg19 版本）；文件缺失时脚本报错"请设置 SCRNA_DEG_REF_DIR 指向 gene_info 目录"，按指引设置后重跑。
- **默认阈值含义**：`pct-1=0.25` 先按表达细胞比例过滤；火山图 DEG 判定用 `p_val_adj < 0.05 且 |avg_log2FC| > 1`；`logfc.threshold=log(2)` 是 FindMarkers 预过滤阈值，函数库内固定，不暴露为 CLI 参数。
- **细胞数 < 30** 的细胞类型仅 warning 不跳过，汇报时须提示用户谨慎解读。
- **被排除的变体脚本**（§6.4，本技能只保留一个权威实现）：`multithreadingFindMarkerCluster.r`（cluster-vs-rest + 多线程旧版）、`findmarker.r`、`FindClusterMarkersDotplot.r` 不进包；`Extert_DEG.PY` 已由 `scripts/merge_deg_infor.py` 重写替代（去掉 /titan3 硬编码）。
- 脚本只读输入 RDS，所有写入限定在 `--output` 目录内；失败时原样返回 stderr。
- 环境依赖见 `references/environment.md`。
