---
name: 单细胞分析结果 Quarto HTML 报告
description: 当用户已有 scRNAseqMulticommand 主流程跑完的 *-scRNA-seq-result 结果目录、要求生成或更新可交付的 HTML 分析报告时触发。输入为结果目录路径，输出为 report/_site/ 静态网站（QC/整合/聚类/注释/差异表达/方法学 7 页）。结果目录尚不存在时不适用——需先经 scrna-pipeline-overview 跑主流程。
skill_id: scrna-quarto-report
version: 0.9.0
author: "zj"
icon: 📊
category: analysis
---

# 单细胞分析结果 Quarto HTML 报告

## 何时使用（Trigger）

**触发**：用户已有主流程 `scRNAseqMulticommand` 跑完的 `*-scRNA-seq-result` 结果目录（含 `QC/`、`cluster/`、`annotation/`、`output/` 等子目录），意图是把它渲染成可交付、可浏览的 HTML 报告站，或更新已有报告。

**不适用**：结果目录尚不存在时——先用 `scrna-pipeline-overview` 编排跑主流程；只想补 manifest/summary JSON 而不渲染时也可直接用 `--no-render`（见下）。

## 输入契约（Input）

脚本：`tools/build_quarto_report.R`，Rscript 执行，参数风格 `--key value` 或 `--key=value` 均可。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--result-dir` | 是 | 已存在的 `*-scRNA-seq-result` 结果目录路径 |
| `--report-dir` | 否 | Quarto 模板目录，默认 `<repo>/report` |
| `--project-name` | 否 | 项目名，默认从结果目录名推断 |
| `--species-tax-id` | 否 | 物种 taxID（如 `9606`），写入 summary |
| `--integration-method` | 否 | 整合方法（如 `Harmony`），写入 summary |
| `--pipeline-version` | 否 | 管线版本号，写入 summary |
| `--sample-sheet` | 否 | conf CSV 路径，回填样本信息 |
| `--no-render` | 否 | 只回填 manifest/summary JSON，不调用 Quarto |
| `--skip-empty` | 否 | 空步骤目录不写 summary（否则写并给 warning） |

依赖：R 包 `jsonlite` + 系统 `quarto` CLI。脚本无硬编码路径。

## 执行步骤（Workflow）

1. **前置校验**：确认 `--result-dir` 存在且是主流程结果目录（有 `output/scrna_seq.rds` 等核心产物）；确认 `quarto` CLI 在 PATH 中（`which quarto`）；仅想补 JSON 时跳过 quarto 检查并加 `--no-render`。
2. **执行**（在仓库根目录下）：

```bash
Rscript tools/build_quarto_report.R \
  --result-dir {结果目录} \
  --project-name {项目名} \
  --species-tax-id {9606|10090} \
  --integration-method {Harmony|...}
```

3. **脚本内部逻辑**（排障时需要知道）：
   - source `src/core/99.report_manifest.r` 的 `generate_report_json()`，在结果目录**回填** `manifest.json` 与各步骤 `summary.json`（`--no-render` 时到此为止）；
   - 建 symlink `report/data/current -> 结果目录`；
   - 以环境变量 `SCRNASEQ_REPORT_DATA=data/current` 在 `report/` 下跑 `quarto render`；
   - 渲染完成后建 symlink `report/_site/data/current -> 结果目录`，供页面引用图片/表格。
4. **验收**：确认 `report/_site/index.html` 存在；抽查 01-qc、04-annotation 页面图片能加载；向用户汇报 `_site/` 路径与页面清单。

## 输出契约（Output）

`report/_site/` 静态网站，7 个页面：

- `index.html`：项目总览；
- `01-qc.html`：QC / 双联体 / ambient RNA；
- `02-integration.html`：整合与批次检查；
- `03-clustering.html`：聚类与 marker；
- `04-annotation.html`：细胞注释；
- `05-deg.html`：差异表达；
- `06-methods.html`：方法学。

另在结果目录回填 `manifest.json` 与各步骤 `summary.json`（报告渲染与机器验收共用）。

## 质控与限制（QC & Constraints）

- **quarto CLI 缺失**：脚本会先完成 JSON 回填，再报错 `Quarto executable not found...`，非 0 退出；此时要么安装 Quarto 重跑，要么接受 `--no-render` 的结果，禁止伪造"已渲染"；
- **symlink 已存在**：`report/data/current` 或 `report/_site/data/current` 已存在时按脚本行为处理（重复执行安全），若指向错误目录，先删除旧 symlink 再重跑；
- **`--skip-empty` 与空步骤目录**：默认对空步骤目录也会写 summary 并输出 warning；加 `--skip-empty` 可跳过。warning 不是失败，但应向用户说明哪些步骤缺产物（通常是该步骤被主流程跳过，如单样本无 `BatchCheck/`）；
- 脚本只读结果目录、回填 JSON，渲染产物只写 `report/_site/` 与上述 symlink，不改动结果目录内的分析产物；
- 执行失败时原样转述 stderr（常见：`--result-dir` 不存在、quarto 缺失、`quarto render` 非 0 退出——后者通常是个别 .qmd 引用缺失产物，查具体页面错误信息定位）。
