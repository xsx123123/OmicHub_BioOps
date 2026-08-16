#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
"""
ATACFlow Pipeline - Group-Level Analysis Module (MACS3)

This module handles group-level peak calling and IDR analysis for ATAC-seq data.
It provides two distinct analysis workflows:

1. POOLED ANALYSIS: Merge replicates within each group and call peaks using MACS3
2. IDR ANALYSIS: Identify reproducible peaks across replicates using IDR

Output Structure:
- 03.peak_calling/pooled_macs3/{group}/ - Group-level pooled MACS3 results
- 03.peak_calling/pooled_macs3_HOMER/ - Group-level HOMER annotations
- 03.peak_calling/idr/{group}/ - IDR analysis results
- 03.peak_calling/idr_HOMER/ - IDR peak annotations
- 04.consensus/pooled_macs3/ - Group consensus peaks
"""

import os

rule merge_shifted_bams:
    """
    Merge shifted ATAC-seq BAM files by experimental group.
    
    This rule combines BAM files from all samples belonging to the same
    experimental group, creating a single consolidated BAM file with increased
    sequencing depth for more robust peak calling.
    """
    input:
        lambda wildcards: expand("02.mapping/shifted/{group}.shifted.sorted.bam",group=groups[wildcards.group])
    output:
        bam = "02.mapping/merged/{group}.merged.bam",
        bai = "02.mapping/merged/{group}.merged.bam.bai"
    log:
        "logs/02.mapping/merge_shifted_bams_{group}.log"
    benchmark:
        "benchmarks/02.mapping/merge_shifted_bams_{group}.txt",
    message:
        "Running merge_shifted_bams",
    threads:
        8
    conda:
        workflow.source_path("../envs/samtools.yaml")
    shell:
        """
        echo "Merging group {wildcards.group}..." > {log}
        samtools merge -@ {threads} {output.bam} {input} 2>> {log}
        samtools index -@ {threads} {output.bam} 2>> {log}
        """

rule macs3_pooled_callpeak:
    """
    Identify peaks using MACS3 on merged group BAM files (Pooled Analysis).
    
    This performs peak calling on merged BAM files from each experimental group,
    leveraging increased sequencing depth to identify more robust accessible
    chromatin regions. Input BAMs are already Tn5-shifted, so no further shift
    is applied.
    """
    input:
        bam = "02.mapping/merged/{group}.merged.bam",
        bai = "02.mapping/merged/{group}.merged.bam.bai"
    output:
        bed = temp("03.peak_calling/pooled_macs3/{group}/{group}_clean.bed"),
        narrow_peak = "03.peak_calling/pooled_macs3/{group}/{group}_peaks.narrowPeak",
        xls = "03.peak_calling/pooled_macs3/{group}/{group}_peaks.xls",
        summits = "03.peak_calling/pooled_macs3/{group}/{group}_summits.bed",
        bdg = "03.peak_calling/pooled_macs3/{group}/{group}_treat_pileup.bdg"
    resources:
        **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/macs3.yaml"),
    log:
        "logs/03.peak_calling/pooled_macs3/macs3_pooled_callpeak_{group}.log",
    message:
        "Running pooled MACS3 peak calling for {wildcards.group}",
    benchmark:
        "benchmarks/03.peak_calling/pooled_macs3/macs3_pooled_callpeak_{group}.txt",
    threads:
        config['parameter']['threads']['macs2'],
    params:
        gsize = config['genome_info'][config['Genome_Version']]['effectiveGenomeSize'],
        qvalue = config['parameter']['macs2']['qvalue'],
        outdir = "03.peak_calling/pooled_macs3/{group}",
        tempdir = "03.peak_calling/tmp",
    shell:
        """
        mkdir -p {params.outdir}

        export TMPDIR={params.tempdir}
        mkdir -p $TMPDIR

        # Convert merged BAM to BED
        bedtools bamtobed -i {input.bam} > {output.bed} 2>> {log}

        macs3 callpeak \
            -t {output.bed} \
            -f BED \
            --shift -75 \
            --extsize 150 \
            --nomodel \
            -g {params.gsize} \
            --name {wildcards.group} \
            --outdir {params.outdir} \
            -q {params.qvalue} \
            --keep-dup all \
            --call-summits \
            -B --SPMR 2>> {log}
        """

rule homer_annotate_pooled_peaks_macs3:
    """
    Annotate group-level pooled peaks using HOMER.
    """
    input:
        peak = "03.peak_calling/pooled_macs3/{group}/{group}_peaks.narrowPeak",
    output:
        annotation = "03.peak_calling/pooled_macs3_HOMER/{group}_annotation.txt",
        stats = "03.peak_calling/pooled_macs3_HOMER/{group}_stats.txt"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/homer.yaml"),
    log:
        "logs/03.peak_calling/pooled_macs3/homer_annotate_pooled_peaks_{group}.log",
    message:
        "Running HOMER annotation for {wildcards.group} pooled peaks (MACS3)",
    benchmark:
        "benchmarks/03.peak_calling/pooled_macs3/homer_annotate_pooled_peaks_{group}.txt",
    threads: config['parameter']['threads']['homer']
    params:
        gtf = config['Bowtie2_index'][config['Genome_Version']]['genome_gtf'],
        genome_fasta = config['Bowtie2_index'][config['Genome_Version']]['genome_fa'],
    shell:
        """
        annotatePeaks.pl {input.peak} {params.genome_fasta} \
            -gtf {params.gtf} \
            -annStats {output.stats} \
            -p {threads} > {output.annotation} 2> {log}
        """

rule create_pooled_consensus_peakset_macs3:
    """
    Create consensus peaks from group-level pooled peak calls.
    
    Merges peaks from all experimental groups to create a comprehensive
    consensus peakset for differential accessibility analysis.
    """
    input:
        peaks = expand("03.peak_calling/pooled_macs3/{group}/{group}_peaks.narrowPeak", group=groups.keys())
    output:
        consensus = "04.consensus/pooled_macs3/all_groups_consensus_peaks.bed"
    resources:
        **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/bedtools.yaml"),
    log:
        "logs/04.consensus/pooled_macs3/create_pooled_consensus_peakset.log",
    message:
        "Creating consensus peakset from pooled group peaks (MACS3)",
    benchmark:
        "benchmarks/04.consensus/pooled_macs3/create_pooled_consensus_peakset.txt",
    threads: config['parameter']['threads']['bedtools']
    shell:
        """        
        cat {input.peaks} | \
        sort -k1,1 -k2,2n | \
        bedtools merge -i stdin > {output.consensus} 2> {log}
        """

rule homer_annotate_pooled_consensus_peaks_macs3:
    """
    Annotate pooled consensus peaks using HOMER.
    """
    input:
        consensus = "04.consensus/pooled_macs3/all_groups_consensus_peaks.bed"
    output:
        annotation = "04.consensus/pooled_macs3/consensus_peaks_annotation.txt",
        stats = "04.consensus/pooled_macs3/consensus_peaks_stats.txt"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/homer.yaml"),
    log:
        "logs/04.consensus/pooled_macs3/homer_annotate_pooled_consensus_peaks.log",
    message:
        "Running HOMER annotation for pooled consensus peaks (MACS3)",
    benchmark:
        "benchmarks/04.consensus/pooled_macs3/homer_annotate_pooled_consensus_peaks.txt",
    threads: config['parameter']['threads']['homer']
    params:
        gtf = config['Bowtie2_index'][config['Genome_Version']]['genome_gtf'],
        genome_fasta = config['Bowtie2_index'][config['Genome_Version']]['genome_fa'],
    shell:
        """
        annotatePeaks.pl {input.consensus} {params.genome_fasta} \
            -gtf {params.gtf} \
            -annStats {output.stats} \
            -p {threads} > {output.annotation} 2> {log}
        """

# rule idr_analysis:
#     """
#     Perform Irreproducible Discovery Rate (IDR) analysis on group replicates.
#     
#     Identifies reproducible peaks across biological replicates within a group
#     using the IDR framework. For groups with only one replicate, returns the
#     original peaks as consensus.
#     
#     NOTE: IDR-filtered peaks are used for QC reporting, but differential analysis
#     uses the pooled consensus peaks for sufficient coverage.
#     """
#     input:
#         peaks = lambda wildcards: expand("03.peak_calling/single/{sample}/{sample}_peaks.narrowPeak",
#             sample=groups[wildcards.group]
#         )
#     output:
#         idr_bed = "03.peak_calling/idr/{group}/Final_Consensus_Peaks.bed",
#         idr_log = "03.peak_calling/idr/{group}/idr_pipeline.log",
#     resources:
#         **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
#     message:
#         "Running idr_analysis",
#     conda:
#         workflow.source_path("../envs/idr.yaml"),
#     log:
#         "logs/03.peak_calling/idr/idr_analysis_{group}.log"
#     benchmark:
#         "benchmarks/03.peak_calling/idr/idr_analysis_{group}.txt"
#     threads:
#         config['parameter']['threads'].get('idr', 4)
#     params:
#         script = workflow.source_path(config["parameter"]["idr_scripts"]["path"]),
#         outdir = "03.peak_calling/idr/{group}"
#     shell:
#         """
#         mkdir -p {params.outdir}
# 
#         peak_count=$(echo "{input.peaks}" | wc -w)
# 
#         if [ "$peak_count" -ge 2 ]; then
#             echo "[$(date)] Running IDR for group {wildcards.group} with $peak_count replicates..." > {log}
#             python3 {params.script} \
#                 -i {input.peaks} \
#                 -o {params.outdir} \
#                 -t {threads} >> {log} 2>&1
#         else
#             echo "[$(date)] Group {wildcards.group} has only one replicate. Using original peaks..." >> {log}
#             awk 'BEGIN{{OFS="\\t"}} {{print $1, $2, $3}}' {input.peaks} | \
#             sort -k1,1 -k2,2n | \
#             bedtools merge > {output.idr_bed} 2>> {log}
#         fi
#         """
# 
# rule homer_annotate_idr_peaks:
#     """
#     Annotate IDR-filtered consensus peaks using HOMER.
#     """
#     input:
#         idr_peaks = "03.peak_calling/idr/{group}/Final_Consensus_Peaks.bed",
#     output:
#         annotation = "03.peak_calling/idr_HOMER/{group}_annotation.txt",
#         stats = "03.peak_calling/idr_HOMER/{group}_stats.txt",
#     resources:
#         **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
#     conda:
#         workflow.source_path("../envs/homer.yaml"),
#     log:
#         "logs/03.peak_calling/idr/homer_annotate_idr_peaks_{group}.log",
#     message:
#         "Running HOMER annotation for {wildcards.group} IDR peaks",
#     benchmark:
#         "benchmarks/03.peak_calling/idr/homer_annotate_idr_peaks_{group}.txt",
#     params:
#         gtf = config['Bowtie2_index'][config['Genome_Version']]['genome_gtf'],
#         genome_fasta = config['Bowtie2_index'][config['Genome_Version']]['genome_fa'],
#     threads: 
#         config['parameter']['threads']['homer'],
#     shell:
#         """
#         annotatePeaks.pl {input.idr_peaks} {params.genome_fasta} \
#             -gtf {params.gtf} \
#             -annStats {output.stats} \
#             -p {threads} > {output.annotation} 2> {log}
#         """
# 
rule generate_pooled_count_matrix_macs3:
    """
    Generate count matrix using pooled consensus peaks for differential analysis.
    
    This is the PRIMARY count matrix used for downstream DEG analysis.
    Uses group-level pooled consensus peaks to ensure sufficient coverage
    for statistical analysis.
    """
    input:
        consensus = "04.consensus/pooled_macs3/all_groups_consensus_peaks.bed",
        bams = expand("02.mapping/shifted/{sample}.shifted.sorted.bam", sample=samples.keys())
    output:
        counts_matrix = "04.consensus/pooled_macs3/consensus_counts_matrix.txt",
        counts_clean = "04.consensus/pooled_macs3/consensus_counts_matrix.clean.txt",
        description = "04.consensus/pooled_macs3/matrix_description.txt",
        summary = "04.consensus/pooled_macs3/consensus_counts_matrix.txt.summary",
        saf = temp("04.consensus/pooled_macs3/consensus_peaks.saf")
    message:
        "Running generate_pooled_count_matrix (MACS3)",
    conda:
        workflow.source_path("../envs/subread.yaml"),
    resources:
        **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger),
    log:
        "logs/04.consensus/pooled_macs3/generate_pooled_count_matrix.log"
    benchmark:
        "benchmarks/04.consensus/pooled_macs3/generate_pooled_count_matrix.txt"
    threads: 
        config['parameter']['threads'].get('featurecounts', 16)
    params:
        sample_count = len(samples),
    shell:
        r"""
        echo "Step 1/4: Converting consensus BED to SAF format..." > {log}
        awk 'BEGIN{{OFS="\t"; print "GeneID\tChr\tStart\tEnd\tStrand"}} \
            {{print $1":"$2"-"$3, $1, $2, $3, "+"}}' {input.consensus} > {output.saf}

        echo "Step 2/4: Running featureCounts for ATAC-seq PE fragments..." >> {log}
        featureCounts \
            -p \
            -B \
            -C \
            --largestOverlap \
            --primary \
            -T {threads} \
            -F SAF \
            -a {output.saf} \
            -o {output.counts_matrix} \
            {input.bams} >> {log} 2>&1
            
        echo "Step 3/4: Cleaning up matrix header..." >> {log}
        awk 'NR==1 {{gsub(/02.mapping\/shifted\//,""); gsub(/\.shifted\.sorted\.bam/,""); print}} \
             NR>1 {{print}}' {output.counts_matrix} > {output.counts_clean}

        echo "Step 4/4: Generating description file..." >> {log}
        printf "ATAC-seq Consensus Peak Count Matrix\n" > {output.description}
        printf "Generated: %s\n" "$(date +'%%Y-%%m-%%d %%H:%%M:%%S')" >> {output.description}
        printf "Samples: %d\n" {params.sample_count} >> {output.description}
        printf "Peaks: %d\n" $(wc -l < {input.consensus}) >> {output.description}
        printf "FeatureCounts Version: %s\n" "$(featureCounts -v 2>&1 | head -1)" >> {output.description}
        """

rule generate_pooled_count_matrix_ann_macs3:
    """
    Add gene annotation to the pooled consensus count matrix.
    """
    input:
        annotation = "04.consensus/pooled_macs3/consensus_peaks_annotation.txt",
        counts_matrix = "04.consensus/pooled_macs3/consensus_counts_matrix.txt",
    output:
        counts_matrix_ann = "04.consensus/pooled_macs3/consensus_counts_matrix_ann.txt",
    message:
        "Running generate_pooled_count_matrix_ann (MACS3)",
    conda:
        workflow.source_path("../envs/bedtools.yaml"),
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    log:
        "logs/04.consensus/pooled_macs3/generate_pooled_count_matrix_ann.log",
    benchmark:
        "benchmarks/04.consensus/pooled_macs3/generate_pooled_count_matrix_ann.txt",
    params:
        path = workflow.source_path(config['parameter']['merge_peaks']['path'])
    threads: 
        1
    shell:
        """
        chmod +x {params.path}
        python3 {params.path} \
            -a {input.annotation} \
            -c {input.counts_matrix} \
            -o {output.counts_matrix_ann} &> {log}
        """
