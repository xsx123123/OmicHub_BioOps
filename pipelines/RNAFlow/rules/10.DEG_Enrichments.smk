#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
"""
RNAFlow Pipeline - Differential Expression Analysis and Functional Enrichment Module

This module performs comprehensive differential gene expression (DEG) analysis using
DESeq2 and subsequent functional enrichment analysis to identify biologically meaningful
patterns in the RNA-seq data.

Key Components:
- gene_dist: Quality control and exploratory analysis of gene expression distributions
- gene_heatmap_tpm/fpkm: Visualization of expression patterns across samples
- DEG: Statistical differential expression analysis using DESeq2
- Enrichments: Gene Ontology (GO) and pathway enrichment analysis

The pipeline enables identification of significantly differentially expressed genes
between experimental conditions and provides biological context through functional
enrichment analysis, helping researchers understand the underlying biological processes,
molecular functions, and cellular components affected by their experimental conditions.
"""

rule gene_dist:
    """
    Generate quality control plots for gene expression distribution analysis.

    This rule creates visualization plots showing the distribution of gene expression
    values across all samples using both TPM and FPKM normalized expression matrices.
    These plots serve as essential quality control metrics to:
    - Assess overall expression distribution patterns
    - Identify potential outliers or batch effects
    - Validate normalization effectiveness
    - Ensure data quality before differential expression analysis

    The output includes both PDF (for publication-quality figures) and PNG (for quick
    inspection) formats of the distribution plots, providing flexibility for different
    use cases.
    """
    input:
        tpm = "03.count/merge_rsem_tpm.tsv",
        fpkm = "03.count/merge_rsem_fpkm.tsv",
    output:
        dist_pdf = '06.DEG/Gene_Expression/Gene_Expression_Distribution.pdf',
        dist_png = '06.DEG/Gene_Expression/Gene_Expression_Distribution.png',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/deg_deseq2.yaml"),
    message:
        "Running Gene Expression Distribution",
    params:
        extension = workflow.source_path(config["parameter"]['Distribution']['path']),
        width = config["parameter"]['Distribution']['width'],
        height = config["parameter"]['Distribution']['height'],
        output = '06.DEG/Gene_Expression/',
        samples = config['sample_csv'],
    log:
        "logs/06.DEG/Gene_Expression_Distribution.log",
    benchmark:
        "benchmarks/Gene_Expression_Distribution.txt",
    threads: 1
    shell:
        """
        chmod +x {params.extension} && \
        {params.extension}  -t {input.tpm} \
                            -f {input.fpkm} \
                            -m {params.samples} \
                            -o {params.output} \
                            --width {params.width} \
                            --height {params.height} &> {log}
        """

rule gene_heatmap_tpm:
    """
    Generate heatmap visualization of top variable genes using TPM expression values.

    This rule creates a clustered heatmap showing the expression patterns of the most
    variable genes across all samples using TPM-normalized data. Heatmaps are powerful
    visual tools for:
    - Identifying sample clustering patterns and potential batch effects
    - Visualizing co-expression patterns among genes
    - Detecting outlier samples that may need further investigation
    - Understanding overall expression relationships between samples

    The heatmap focuses on the most variable genes to highlight the strongest expression
    differences, making it easier to interpret complex expression patterns.
    """
    input:
        tpm = "03.count/merge_rsem_tpm.tsv",
        fpkm = "03.count/merge_rsem_fpkm.tsv",
    output:
        dist_pdf = '06.DEG/Heatmap_tpm/Heatmap_TopVar.pdf',
        dist_png = '06.DEG/Heatmap_tpm/Heatmap_TopVar.png',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/deg_deseq2.yaml"),
    message:
        "Running Gene Heatmap",
    params:
        extension = workflow.source_path(config["parameter"]['Heatmap']['path']),
        output = '06.DEG/Heatmap_tpm/',
        samples = config['sample_csv'],
    log:
        "logs/06.DEG/Gene_Heatmap_tpm.log",
    benchmark:
        "benchmarks/Gene_Heatmap_tpm.txt",
    threads: 1
    shell:
        """
        chmod +x {params.extension} && \
        {params.extension}  -i {input.tpm} \
                            -m {params.samples} \
                            -o {params.output}  &> {log}
        """

rule gene_heatmap_fpkm:
    """
    Generate heatmap visualization of top variable genes using FPKM expression values.

    Similar to the TPM heatmap, this rule creates a clustered heatmap using FPKM-
    normalized expression data. Having both TPM and FPKM heatmaps allows for:
    - Cross-validation of expression patterns between different normalization methods
    - Comparison with legacy datasets that may have used FPKM normalization
    - Robustness assessment of observed clustering patterns

    While TPM is generally preferred for cross-sample comparisons, FPKM heatmaps
    provide additional perspective and can be useful for specific analytical contexts.
    """
    input:
        tpm = "03.count/merge_rsem_tpm.tsv",
        fpkm = "03.count/merge_rsem_fpkm.tsv",
    output:
        dist_pdf = '06.DEG/Heatmap_fpkm/Heatmap_TopVar.pdf',
        dist_png = '06.DEG/Heatmap_fpkm/Heatmap_TopVar.png',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/deg_deseq2.yaml"),
    message:
        "Running Gene Heatmap",
    params:
        extension = workflow.source_path(config["parameter"]['Heatmap']['path']),
        output = '06.DEG/Heatmap_fpkm/',
        samples = config['sample_csv'],
    log:
        "logs/06.DEG/Gene_Heatmap_fpkm.log",
    benchmark:
        "benchmarks/Gene_Heatmap_fpkm.txt",
    threads: 1
    shell:
        """
        chmod +x {params.extension} && \
        {params.extension}  -i {input.fpkm} \
                            -m {params.samples} \
                            -o {params.output}  &> {log}
        """

# ---- DEG engine selection ----------------------------------------------------
# Resolved once at parse time in the snakefile (§3) via rules/utils/deg_method.py:
#   deseq2 -> designs with biological replicates (default, unchanged behavior)
#   edger  -> required when any contrast lacks replicates (1v1). run_edger.r
#             runs replicated contrasts with the QL F-test and 1v1 contrasts
#             with exactTest at a fixed BCV (edgeR User's Guide).
# Output dir (06.DEG/DESEQ2 vs 06.DEG/EDGER), script, conda env and the
# Enrichments/deliver/manifest paths all derive from this single value.
_DEG_METHOD = str(config.get('parameter', {}).get('DEG', {}).get('METHOD_RESOLVED', 'deseq2')).lower()
_DEG_CFG = config['parameter']['DEG']
_DEG_DIRNAME = _DEG_METHOD.upper()
_DEG_SCRIPT = _DEG_CFG['PATH_EDGER'] if _DEG_METHOD == 'edger' else _DEG_CFG['PATH']
_DEG_ENV = "../envs/deg_edger.yaml" if _DEG_METHOD == 'edger' else "../envs/deg_deseq2.yaml"
_DEG_EXTRA_ARGS = f"--bcv={_DEG_CFG.get('BCV', 0.4)}" if _DEG_METHOD == 'edger' else ""

rule DEG:
    """
    Perform statistical differential expression analysis (DESeq2 or edgeR).

    Engine selection (see block above, resolved in the snakefile):
    - deseq2: DESeq2 negative-binomial GLM with dispersion estimated from
      biological replicates. The default for replicated designs.
    - edger:  edgeR. Handles the same replicated designs (estimateDisp +
      QL F-test) AND contrasts without biological replicates (1v1), where
      DESeq2 cannot run: exactTest at a user-supplied BCV
      (parameter.DEG.BCV; 0.4 for human subjects, 0.1 for isogenic model
      organisms/cell lines, 0.01 for technical replicates).

    Both engines share the CLI and output layout, so per-contrast tables
    ({Treat}_vs_{Control}_DEG.csv), volcano plots and the summary
    All_Contrast_DEG_Statistics.csv are identical in structure; the summary
    additionally records the method and dispersion assumption per contrast
    when run under edgeR.

    Parameters:
    - LFC (Log2 Fold Change): Minimum fold change threshold for significance
    - PVAL: P-value threshold for significance
    - paired: Contrast definitions (Treat, Control)

    The output includes comprehensive statistics for all contrasts in the experiment,
    including log2 fold changes, p-values, adjusted p-values, and base means.
    """
    input:
        counts = "03.count/merge_rsem_counts.tsv",
    output:
        output = f'06.DEG/{_DEG_DIRNAME}/All_Contrast_DEG_Statistics.csv',
        deg_dir = directory(f'06.DEG/{_DEG_DIRNAME}'),
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path(_DEG_ENV),
    log:
        f"logs/06.DEG/{_DEG_METHOD}/deg_{_DEG_METHOD}.log",
    benchmark:
        f"benchmarks/06.DEG/deg_{_DEG_METHOD}_benchmark.txt",
    params:
        samples = config['sample_csv'],
        paired = config['paired_csv'],
        PATH = workflow.source_path(_DEG_SCRIPT),
        LFC = _DEG_CFG['LFC'],
        PVAL = _DEG_CFG['PVAL'],
        extra = _DEG_EXTRA_ARGS,
    threads:
        1
    shell:
        """
        chmod +x {params.PATH} && \
        Rscript {params.PATH} -c {input.counts} \
                -m {params.samples} \
                -p {params.paired} \
                -o {output.deg_dir} \
                --lfc={params.LFC} \
                --pval={params.PVAL} \
                {params.extra} &> {log}
        """

rule Enrichments:
    """
    Perform Gene Ontology (GO) and pathway enrichment analysis on differentially expressed genes.

    This rule conducts functional enrichment analysis to identify overrepresented biological
    terms, molecular functions, and cellular components among the differentially expressed
    genes identified by DESeq2. The analysis helps translate statistical results into
    biological insights by answering: "What biological processes are affected by my
    experimental conditions?"

    The enrichment analysis uses:
    - Gene Ontology (GO) database for functional annotation
    - Statistical overrepresentation analysis (hypergeometric test or Fisher's exact test)
    - Multiple testing correction to control false discovery rate
    - Custom gene ID mapping based on reference genome annotation

    Key parameters:
    - gene_col: Column name containing gene identifiers in DEG results
    - gene_regex: Regular expression pattern for extracting gene IDs
    - cutoff: Significance threshold for enriched terms (default: 0.05)
    - obo: GO ontology file for term definitions and relationships
    - go_annotation: Genome-specific GO annotation file

    The output is organized in a dedicated directory containing enrichment results
    for all contrasts, including enriched terms, p-values, gene lists, and visualization
    files for downstream interpretation and reporting.
    """
    input:
        DEG_info = f"06.DEG/{_DEG_DIRNAME}/All_Contrast_DEG_Statistics.csv",
    output:
        Enrichments_dir = directory("07.Enrichments/"),
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/go_enrich_r.yaml"),
    log:
        "logs/07.Enrichments/go_enrich.log",
    params:
        obo = config['STAR_index']['GO']['obo'],
        go_annotation = config['STAR_index'][config['Genome_Version']]['go_annotation'],
        gene_col = config['deg_enrich_wrapper'][config['Genome_Version']]['gene_col'],
        r_script = workflow.source_path(config['parameter']['Enrichments']['PATH']),
        wrapper = workflow.source_path(config['parameter']['Enrichments']['PATH_py']),
        gene_regex = config['parameter']['Enrichments']['gene_regex'],
        deg_dir = f"06.DEG/{_DEG_DIRNAME}",
        cutoff = config['parameter']['Enrichments'].get('cutoff', 0.05)
    shell:
        """
        python {params.wrapper} \
            --rscript {params.r_script} \
            --deg_info {input.DEG_info} \
            --deg_dir {params.deg_dir} \
            -o {params.obo} \
            -a {params.go_annotation} \
            -d {output.Enrichments_dir} \
            --gene_col '{params.gene_col}' \
            --gene_regex '{params.gene_regex}' \
            --cutoff {params.cutoff} > {log} 2>&1
        """