---
name: ATACFlow
description: 使用 OmicHub ATACFlow 完成 Bulk ATAC-seq 从 FASTQ 质控、比对、峰识别、差异可及性、motif/footprinting 到报告交付。正式提交必须走平台预检与确认协议。
skill_id: atacflow
version: 1.0.0
category: workflow
---

# ATACFlow

## 何时使用

- 用户明确要求执行 Bulk ATAC-seq 完整流程、重新分析 FASTQ，或查询 ATACFlow 任务结果时使用。
- 只解释原理时先检索 `atacseq` 知识库，不启动流程。
- 单细胞 ATAC-seq、仅生成 TSS BED 或仅构建峰计数矩阵不属于完整 ATACFlow；后两者使用
  `atac-tools`。

## 输入确认

| 输入 | 要求 |
| --- | --- |
| FASTQ | paired-end 配对、样本映射和文件完整性明确。 |
| 样本表 | `sample`、`sample_name`、`group` 可与 FASTQ 对应。 |
| 比较表 | control/treatment 方向和配对关系明确。 |
| 物种/参考 | 基因组版本、注释、blacklist、organellar 染色体命名明确。 |
| 分析模块 | peak calling、IDR、差异峰、motif、TOBIAS、富集和报告按需求启用。 |

## 平台执行协议

1. 调用 `check_workspace_data`，`analysis_type` 必须为 `atac_seq`。
2. 调用 `atac_seq_prepare`，校验样本、参考、参数、资源和费用。
3. 展示预检结果；存在错误时停止，存在警告时解释影响。
4. 只有用户明确确认后调用 `atac_seq_submit`。
5. 使用 `atac_seq_status` 查询状态，完成后用 `atac_seq_results` 获取真实产物。
6. 不直接在聊天沙盒复制并运行 ATACFlow 主流程，不绕过平台任务、权限、计费和审计。

## 流程阶段

1. MD5 与样本映射检查。
2. FastQC/fastp 与污染检查。
3. Bowtie2 或 Chromap 比对，过滤低质量、多重比对、duplicates、organellar reads 和 blacklist。
4. 生成片段分布、TSS enrichment、FRiP、library complexity、ataqv/MultiQC 等 QC。
5. MACS2/MACS3 样本峰、pooled 峰、IDR 与 consensus peaks。
6. 固定峰集合计数和 DESeq2 差异可及性。
7. peak annotation、GO/KEGG、motif enrichment 和 TOBIAS footprinting。
8. 报告、产物清单和 MD5 交付。

## QC 护栏

- Q30、mapping rate、organellar fraction、TSS enrichment、FRiP 和 peak 数量均需结合物种、组织、
  输入量和建库条件判断，不把经验阈值当作绝对标准。
- 插入片段应检查 nucleosome-free、mono-/di-nucleosome 周期性；异常时结合文库复杂度和 TSS QC。
- 差异峰必须基于统一 peak universe、明确设计矩阵和 contrast，并报告效应量与 FDR。

## 输出契约

只依据 `atac_seq_results` 返回内容汇报：任务 ID、工作流版本、参考版本、关键参数、QC、峰与差异
结果摘要、motif/footprinting 结果、报告和产物路径、失败或跳过模块。不得编造任何运行指标。
