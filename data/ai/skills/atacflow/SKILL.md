---
name: ATACFlow
description: 使用 CygnusX ATACFlow 完成 Bulk ATAC-seq 从 FASTQ 质控、比对、峰识别、差异可及性、motif/footprinting 到报告交付。正式提交必须走平台预检与确认协议。
skill_id: atacflow
version: 1.0.0
category: workflow
---

# ATACFlow

完整流程通过 CygnusX Pipelines MCP 执行：依次使用 `check_workspace_data`、`atac_seq_prepare`、
用户确认后的 `atac_seq_submit`、`atac_seq_status` 和 `atac_seq_results`。不得绕过平台任务、权限、
计费和审计直接启动主流程。

输入必须明确 paired-end FASTQ、样本与比较表、物种和参考版本、blacklist、organellar 染色体策略
及模块开关。流程覆盖 QC、Bowtie2/Chromap、过滤、MACS2/MACS3、IDR、consensus peaks、
DESeq2 差异可及性、peak annotation、GO/KEGG、motif、TOBIAS 和报告交付。

只依据 `atac_seq_results` 汇报任务 ID、工作流和参考版本、关键参数、QC、峰与差异结果、
motif/footprinting、报告路径及失败或跳过模块，不得编造运行指标。
