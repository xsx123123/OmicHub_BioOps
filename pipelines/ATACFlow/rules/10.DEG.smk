#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
"""
ATACFlow Pipeline - Differential Accessibility Analysis Module

This module performs differential accessibility analysis to identify chromatin regions
that show significant changes in accessibility between different experimental conditions.
Using DESeq2, it provides robust statistical analysis of count data from ATAC-seq
experiments, enabling the identification of regulatory regions associated with
biological processes of interest.

Key Components:
- DEG: Performs differential accessibility analysis using DESeq2 on individual sample peaks
- Enrichments: Performs gene ontology enrichment analysis on differential peaks

This module is essential for understanding the regulatory changes that occur between
experimental conditions, linking differences in chromatin accessibility to potential
changes in gene expression and cellular phenotype.
"""

rule DEG:
    """
    Perform differential accessibility analysis using DESeq2 on the pooled consensus peakset.

    This rule identifies chromatin regions that show statistically significant differences
    in accessibility between experimental conditions using DESeq2, a powerful tool for
    differential analysis of count data. DESeq2 models count data using a negative
    binomial distribution, providing robust statistical inference even with small
    numbers of biological replicates.

    Uses GROUP-LEVEL POOLED consensus peaks to ensure sufficient coverage for
    statistical analysis. IDR-filtered peaks are too sparse for differential analysis.

    Key steps in the differential accessibility analysis:
    - Normalization of read counts across samples
    - Estimation of dispersion parameters
    - Statistical testing for differential accessibility
    - Multiple testing correction using FDR (False Discovery Rate)
    - Generation of visualizations including PCA plots and MA plots

    Important analysis parameters:
    - LFC (log2 fold change) threshold for calling significant differences
    - P-value (adjusted) threshold for statistical significance
    - Sample information from sample_csv for experimental design
    - Contrast information from paired_csv for comparisons of interest

    Outputs from this analysis include:
    - Global PCA plot showing sample relationships and clustering
    - Detailed results tables for each contrast with statistics
    - Summary statistics of differential peaks across all comparisons
    - Various diagnostic plots and visualizations

    The differential accessibility results provide the foundation for understanding
    the regulatory landscape changes between experimental conditions, enabling the
    identification of key regulatory regions and potential target genes associated
    with the biological processes under investigation.
    """
    input:
        counts = "04.consensus/single_macs3/consensus_counts_matrix_ann.txt",
    output:
        output = '06.deg_enrich/DEG/Global_PCA.pdf',
        summary = '06.deg_enrich/DEG/All_Contrast_Differential_Peaks_Statistics.csv',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    message:
        "Running DEG",
    conda:
        workflow.source_path("../envs/deg_deseq2.yaml"),
    log:
        "logs/06.DEG/DEG.log",
    benchmark:
        "benchmarks/06.DEG/DEG.txt",
    params:
        deg_dir = '06.deg_enrich/DEG',
        samples = config['sample_csv'],
        paired = config['paired_csv'],
        PATH = workflow.source_path(config['parameter']['DEG']['PATH']),
        LFC = config['parameter']['DEG']['LFC'],
        PVAL = config['parameter']['DEG']['PVAL'],
    threads: 
        1
    shell:
        """
        chmod +x {params.PATH} && \
        Rscript {params.PATH} -c {input.counts} \
                -m {params.samples} \
                -p {params.paired} \
                -o {params.deg_dir} \
                --lfc={params.LFC} \
                --pval={params.PVAL} \
                --label_co=gene_id &> {log}
        """

rule Enrichments:
    """
    Perform gene ontology enrichment analysis on differentially accessible peaks.

    This rule performs functional enrichment analysis to identify biological processes,
    molecular functions, and cellular components that are significantly associated with
    the genes near differentially accessible chromatin regions. This analysis links
    changes in chromatin accessibility to potential functional consequences at the
    gene and pathway level.

    Key enrichment analysis steps:
    - Assignment of peaks to putative target genes based on proximity
    - Statistical testing for enrichment of gene ontology terms
    - Multiple testing correction to control false discovery rate
    - Generation of enrichment results tables and visualizations

    Important parameters for enrichment analysis:
    - Gene ontology (GO) database (OBO file)
    - GO annotation file for the specific organism
    - Cutoff for statistical significance (default: 0.05)
    - Method for assigning peaks to genes
    - Regular expression pattern for extracting gene identifiers

    The enrichment analysis provides valuable biological context by:
    - Identifying biological processes associated with accessibility changes
    - Revealing potential regulatory pathways affected by the experiment
    - Linking chromatin changes to specific gene functions
    - Generating testable hypotheses about regulatory mechanisms

    The results from this analysis, together with the differential accessibility results,
    provide a comprehensive view of the regulatory changes occurring between experimental
    conditions, enabling deeper biological interpretation of the ATAC-seq data.
    """
    input:
        DEG_info = "06.deg_enrich/DEG/All_Contrast_Differential_Peaks_Statistics.csv",
    output:
        Enrichments_dir = directory("06.deg_enrichs/enrich/"),
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    benchmark:
        "benchmarks/06.DEG/Enrichments.txt",
    message:
        "Running Enrichments",
    conda:
        workflow.source_path("../envs/go_enrich_r.yaml"),
    log:
        "logs/06.DEG/Enrichments.log",
    params:
        obo = config['Bowtie2_index']['GO']['obo'],
        go_annotation = config['Bowtie2_index'][config['Genome_Version']]['go_annotation'],
        gene_col = config['parameter']['Enrichments']['gene_col'],
        r_script = workflow.source_path(config['parameter']['Enrichments']['PATH']),
        wrapper = workflow.source_path(config['parameter']['Enrichments']['PATH_py']),
        gene_regex = config['parameter']['Enrichments']['gene_regex'],
        lib_type = config['parameter']['Enrichments']['lib_type'],
        deg_dir = "06.deg_enrich/DEG",
        cutoff = config['parameter']['Enrichments'].get('cutoff', 0.05)
    threads:
        1
    shell:
        """
        python {params.wrapper} \
            --rscript {params.r_script} \
            --deg_info {input.DEG_info} \
            --deg_dir {params.deg_dir} \
            --lib_type {params.lib_type} \
            -o {params.obo} \
            -a {params.go_annotation} \
            -d {output.Enrichments_dir} \
            --gene_col {params.gene_col} \
            --gene_regex '{params.gene_regex}' \
            --cutoff {params.cutoff} > {log} 2>&1
        """
# ------- rule ------- #