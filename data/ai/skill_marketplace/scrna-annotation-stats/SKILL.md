---
name: 单细胞注释比例统计
description: 当用户需要对已注释 scRNA-seq Seurat 对象做细胞比例统计与可视化（堆叠柱状图）、组间比例显著性检验（Fisher 精确检验 / 样本级 GLM）、多组配对的"DEG 数 × 细胞比例变化"气泡图、或按分组计算基因表达百分比与平均表达时触发。输入为 RDS 对象路径与 meta.data 列名。差异表达基因本身的批量鉴定、基因注释与火山图走 scrna-deg-analysis，本技能只做比例统计与汇总。
skill_id: scrna-annotation-stats
version: 0.9.0
author: "zj"
icon: 📈
category: analysis
---

# 单细胞注释比例统计

对已完成细胞注释的 Seurat 对象做细胞比例层面的统计与可视化：比例堆叠柱状图、组间比例显著性检验（Fisher / 样本级 GLM）、多组配对"DEG 数 × 细胞比例变化"气泡图、基因表达百分比与平均表达汇总。

## 何时使用（Trigger）

- 输入是**已完成注释的 Seurat RDS 对象**（meta.data 中含细胞类型列与分组列）；
- 用户要回答"各组细胞类型比例是多少/有无显著差异/某基因在各细胞类型里表达比例多高"这类**比例统计**问题；
- 五种场景对应五个 `--mode`：
  - `prop`：细胞类型 × 分组的细胞数与比例统计 + 堆叠柱状图；
  - `fisher`：两组间每细胞类型比例差异的 Fisher 精确检验（cell 级，不考虑样本层级）；
  - `glm`：两组间比例差异的样本级 binomial GLM + 卡方 ANOVA（按 orig.ident 计生物学重复，更严谨）；
  - `deg-prop`：多组 treat/control 配对的"上调 DEG 数 × 细胞数 log2FC × 占比"气泡图（内部调 FindMarkers）；
  - `pct-exp`：按分组计算一组基因的表达细胞百分比与平均表达长表。
- **不适用**：细胞类型 × 分组的批量差异表达分析（FindMarkers 列表、基因注释、火山图）→ 走 `scrna-deg-analysis`；细胞注释本身 → 走注释类技能；对象格式转换 → 走 `scrna-object-convert`。

## 输入契约（Input）

公共参数（所有 mode 必填）：

| 参数 | 必填 | 说明 |
|---|---|---|
| `--mode` | 是 | `prop` / `fisher` / `glm` / `deg-prop` / `pct-exp` |
| `--input` | 是 | 已注释 Seurat RDS 路径（用户输入或上游技能产物） |
| `--output` | 是 | 产物目录，脚本负责创建 |
| `--celltype-col` | 否 | 细胞类型列名，默认 `celltype` |
| `--group-col` | 否 | 分组列名，默认 `orig.ident`；prop 模式即堆叠图分组，fisher/glm/deg-prop 为处理/对照分组，pct-exp 为汇总分组 |

各 mode 专属参数：

| mode | 参数 | 必填 | 说明 |
|---|---|---|---|
| prop | `--name` | 否 | 输出文件名前缀，默认 `prop` |
| fisher | `--treat` / `--control` | 是 | 处理组/对照组水平，必须是 `--group-col` 的实际取值 |
| glm | `--treat` / `--control` | 是 | 同上；另要求 orig.ident 能提供生物学重复 |
| deg-prop | `--pair` | 是 | 格式 `Treat:Control`，**可重复**：`--pair LC:N --pair T:N`；取值必须存在于 `--group-col` |
| deg-prop | `--project-id` | 否 | 输出文件名前缀，默认 `deg-prop` |
| pct-exp | `--genes` | 是 | 逗号分隔基因列表，如 `CD3D,CD8A,MS4A1` |

必填项缺失时先简短追问，不要臆测默认值。

## 执行步骤（Workflow）

1. 前置校验：确认 RDS 存在；如用户给了列名/组水平/基因，脚本会自动校验并在缺失时列出实际列名/取值后非 0 退出——把报错原样转告用户。
2. 按场景执行（命令可直接复制，`{}` 为占位符）：

```bash
# prop：比例堆叠柱状图 + 细胞数/比例 CSV
Rscript scripts/annotation_stats.R --mode prop \
  --input {object.rds} --output {outdir} \
  --celltype-col {celltype} --group-col {orig.ident} --name prop

# fisher：两组比例差异 Fisher 精确检验
Rscript scripts/annotation_stats.R --mode fisher \
  --input {object.rds} --output {outdir} \
  --celltype-col {celltype} --group-col {group} \
  --treat {Treate} --control {Control}

# glm：两组比例差异样本级 GLM（有生物学重复时优先）
Rscript scripts/annotation_stats.R --mode glm \
  --input {object.rds} --output {outdir} \
  --celltype-col {celltype} --group-col {group} \
  --treat {Treate} --control {Control}

# deg-prop：多组配对 DEG 数 × 细胞比例变化气泡图
Rscript scripts/annotation_stats.R --mode deg-prop \
  --input {object.rds} --output {outdir} \
  --celltype-col {celltype} --group-col {orig.ident} \
  --pair {LC:N} --pair {T:N} --project-id myproject

# pct-exp：基因表达百分比 + 平均表达
Rscript scripts/annotation_stats.R --mode pct-exp \
  --input {object.rds} --output {outdir} \
  --group-col {celltype} --genes {CD3D,CD8A,MS4A1}
```

3. 结果汇报：只读 `{outdir}/summary.json`，向用户汇报 `stats` 中的关键统计量（细胞类型数、显著条目数等）与 `outputs` 产物清单、`warnings` 警示；不要解析大结果文件。
4. 异常处理：退出码非 0 时读 stderr 与 `{outdir}/summary.json` 的 `error` 字段原样转告；列名错误时把脚本列出的实际列名反馈给用户选择，禁止伪造结果。

## 输出契约（Output）

所有产物写入 `--output` 目录，另含结构化摘要 `{output}/summary.json`（含 tool/version/status/mode/outputs/stats/warnings，失败时含 error 字段且退出码非 0）。

| mode | 产物 |
|---|---|
| prop | `{name}-celltyoe.prop.csv`（细胞数与比例表，文件名拼写为上游原文）、`{name}-prop.pdf/png`（堆叠柱状图） |
| fisher | `fisher-test-result.csv`（celltype/oddsratio/pval_fisher/padj_fisher）、`{Control} vs {Treate}/fisherTest.pdf/png`（log2OR 点图）、`fisher-Test.html`（gt 表，gt 缺失时跳过并记 warnings） |
| glm | `glm-test-result.csv`（celltype/coef_glm/pval_aov/padj_aov） |
| deg-prop | `{project-id}-DrawCellTypePropDEGGene.csv` + 同名 pdf/png 气泡图（x=细胞数 log2(treat/control)，size=占比，color=上调 DEG 数，按 comparison 分面） |
| pct-exp | `pct-avg-exp.csv`（gene/variable/pct_exp/avg_exp 长表） |

## 质控与限制（QC & Constraints）

- **列名规范化策略（上游已知 bug 的 wrapper 规避）**：fisher/glm 的函数内部硬引用字面的 `celltype`、`group` 列，忽略传入的列名参数；deg-prop 内部硬编码 `Celltype` 与 orig.ident。wrapper 会先把 `--celltype-col`/`--group-col` 指定的列复制为上述字面列名（仅内存对象，不改输入 RDS），用户无需手工改对象。
- **Fisher vs GLM 选择**：分组有生物学重复（每组 ≥3 个 orig.ident 样本）时**优先 GLM**——它按样本层级聚合，避免细胞级伪重复导致的假显著；无重复概念或每组样本极少时用 Fisher（并在汇报中注明其局限）。GLM 在某组样本 <2 时会拟合失败（报错退出）。
- **功效警示**：fisher 模式对细胞数 <30 的细胞类型、glm 模式对重复数 <3 的组会写入 warnings，汇报时需转达。
- **被排除的源脚本**：`Robustness_analysis.r`（仅 base R barplot、列名硬引用与默认参数不一致，边际价值低）、`Proplot.r` 1.0v（接口无默认值，功能被 propplot.r 2.0v 覆盖）、`scRNAPropplot.r`（输入非 Seurat 且 source 即执行模拟数据代码）——三者均不入包。
- GLM 库自带的 `data2plot()` 有文件名拼接 bug，wrapper 不调用它，glm 结果图可由用户据 CSV 自绘。
- 脚本只读输入 RDS，所有写入限定在 `--output` 目录；依赖清单见 `references/environment.md`。
