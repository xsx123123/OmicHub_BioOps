# 工具选择离线评测报告

- 执行时间：2026-08-18T12:44:59.515528+00:00
- 代码版本：`4e93549`
- 评测模式：确定性词法召回（full schema injection）
- Top-1 命中率：**87.50%**（28/32）

| 结果 | Query | 期望工具 | Top-1 |
|---|---|---|---|
| PASS | 帮我看看这些基因富集到什么通路 | cygnusx_run_kegg_enrichment | cygnusx_run_kegg_enrichment |
| PASS | 做 GO 注释 | cygnusx_run_kegg_enrichment | cygnusx_run_kegg_enrichment |
| PASS | KEGG enrichment for these genes | cygnusx_run_kegg_enrichment | cygnusx_run_kegg_enrichment |
| PASS | 画个火山图 | cygnusx_plot_volcano | cygnusx_plot_volcano |
| PASS | visualize DEG log2FC and padj | cygnusx_plot_volcano | cygnusx_plot_volcano |
| PASS | GWAS 曼哈顿图 | cygnusx_plot_manhattan | cygnusx_plot_manhattan |
| PASS | plot QTL association loci | cygnusx_plot_manhattan | cygnusx_plot_manhattan |
| PASS | RNA-seq counts 两组差异分析 | cygnusx_run_deg_analysis | cygnusx_run_deg_analysis |
| PASS | 用 DESeq2 找差异基因 | cygnusx_run_deg_analysis | cygnusx_run_deg_analysis |
| PASS | 构建系统发育树 | cygnusx_build_phylogenetic_tree | cygnusx_build_phylogenetic_tree |
| PASS | NJ tree from aligned FASTA | cygnusx_build_phylogenetic_tree | cygnusx_build_phylogenetic_tree |
| PASS | 找一个做共线性分析的工具 | cygnusx_toolbox_search | cygnusx_toolbox_search |
| PASS | 工具箱里有 GSEA 吗 | cygnusx_toolbox_search | cygnusx_toolbox_search |
| PASS | 帮我打开 DEG 工作台 | cygnusx_run_deg_analysis | cygnusx_run_deg_analysis |
| PASS | 火山图 DEG plot | cygnusx_plot_volcano | cygnusx_plot_volcano |
| PASS | 曼哈顿图 SNP | cygnusx_plot_manhattan | cygnusx_plot_manhattan |
| PASS | 富集气泡图 | cygnusx_run_kegg_enrichment | cygnusx_run_kegg_enrichment |
| PASS | edgeR 分析表达差异 | cygnusx_run_deg_analysis | cygnusx_run_deg_analysis |
| PASS | maximum likelihood phylogeny | cygnusx_build_phylogenetic_tree | cygnusx_build_phylogenetic_tree |
| PASS | GO BP MF CC 富集 | cygnusx_run_kegg_enrichment | cygnusx_run_kegg_enrichment |
| PASS | differential expression plot | cygnusx_plot_volcano | cygnusx_plot_volcano |
| PASS | 有一张 counts matrix | cygnusx_run_deg_analysis | cygnusx_run_deg_analysis |
| PASS | 查看 QTL 显著位点 | cygnusx_plot_manhattan | cygnusx_plot_manhattan |
| PASS | 比较序列亲缘关系 | cygnusx_build_phylogenetic_tree | cygnusx_build_phylogenetic_tree |
| FAIL | 通路分析 | cygnusx_run_kegg_enrichment | cygnusx_prepare_atac_seq_submission |
| PASS | 我有全基因 log2FC 排序，帮我跑 GSEA | cygnusx_run_gsea | cygnusx_run_gsea |
| PASS | 用 GFF3 和 BLASTP 结果画基因组共线性 dot plot | cygnusx_run_synteny | cygnusx_run_synteny |
| PASS | 帮我写一封邮件 | - | - |
| PASS | 今天北京天气如何 | - | - |
| FAIL | 解释一下什么是转录组 | - | cygnusx_run_deg_analysis |
| FAIL | 整理这段会议纪要 | - | cygnusx_open_venn_upset |
| FAIL | 生成项目周报 | - | cygnusx_open_expression_explorer |
