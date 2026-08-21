# 工具选择离线评测报告

- 执行时间：2026-08-18T12:45:02.362756+00:00
- 代码版本：`4e93549`
- 评测模式：确定性词法召回（retrieval schema injection）
- Top-1 命中率：**87.50%**（28/32）

| 结果 | Query | 期望工具 | Top-1 |
|---|---|---|---|
| PASS | 帮我看看这些基因富集到什么通路 | omichub_run_kegg_enrichment | omichub_run_kegg_enrichment |
| PASS | 做 GO 注释 | omichub_run_kegg_enrichment | omichub_run_kegg_enrichment |
| PASS | KEGG enrichment for these genes | omichub_run_kegg_enrichment | omichub_run_kegg_enrichment |
| PASS | 画个火山图 | omichub_plot_volcano | omichub_plot_volcano |
| PASS | visualize DEG log2FC and padj | omichub_plot_volcano | omichub_plot_volcano |
| PASS | GWAS 曼哈顿图 | omichub_plot_manhattan | omichub_plot_manhattan |
| PASS | plot QTL association loci | omichub_plot_manhattan | omichub_plot_manhattan |
| PASS | RNA-seq counts 两组差异分析 | omichub_run_deg_analysis | omichub_run_deg_analysis |
| PASS | 用 DESeq2 找差异基因 | omichub_run_deg_analysis | omichub_run_deg_analysis |
| PASS | 构建系统发育树 | omichub_build_phylogenetic_tree | omichub_build_phylogenetic_tree |
| PASS | NJ tree from aligned FASTA | omichub_build_phylogenetic_tree | omichub_build_phylogenetic_tree |
| PASS | 找一个做共线性分析的工具 | omichub_toolbox_search | omichub_toolbox_search |
| PASS | 工具箱里有 GSEA 吗 | omichub_toolbox_search | omichub_toolbox_search |
| PASS | 帮我打开 DEG 工作台 | omichub_run_deg_analysis | omichub_run_deg_analysis |
| PASS | 火山图 DEG plot | omichub_plot_volcano | omichub_plot_volcano |
| PASS | 曼哈顿图 SNP | omichub_plot_manhattan | omichub_plot_manhattan |
| PASS | 富集气泡图 | omichub_run_kegg_enrichment | omichub_run_kegg_enrichment |
| PASS | edgeR 分析表达差异 | omichub_run_deg_analysis | omichub_run_deg_analysis |
| PASS | maximum likelihood phylogeny | omichub_build_phylogenetic_tree | omichub_build_phylogenetic_tree |
| PASS | GO BP MF CC 富集 | omichub_run_kegg_enrichment | omichub_run_kegg_enrichment |
| PASS | differential expression plot | omichub_plot_volcano | omichub_plot_volcano |
| PASS | 有一张 counts matrix | omichub_run_deg_analysis | omichub_run_deg_analysis |
| PASS | 查看 QTL 显著位点 | omichub_plot_manhattan | omichub_plot_manhattan |
| PASS | 比较序列亲缘关系 | omichub_build_phylogenetic_tree | omichub_build_phylogenetic_tree |
| FAIL | 通路分析 | omichub_run_kegg_enrichment | omichub_prepare_atac_seq_submission |
| PASS | 我有全基因 log2FC 排序，帮我跑 GSEA | omichub_run_gsea | omichub_run_gsea |
| PASS | 用 GFF3 和 BLASTP 结果画基因组共线性 dot plot | omichub_run_synteny | omichub_run_synteny |
| PASS | 帮我写一封邮件 | - | - |
| PASS | 今天北京天气如何 | - | - |
| FAIL | 解释一下什么是转录组 | - | omichub_run_deg_analysis |
| FAIL | 整理这段会议纪要 | - | omichub_open_venn_upset |
| FAIL | 生成项目周报 | - | omichub_open_expression_explorer |
