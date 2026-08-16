#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
"""
ATACFlow Pipeline - Single Sample Peak Calling Module

This module handles individual sample-level peak calling and consensus peak
generation from all samples. It provides the foundational peak calling analysis
for ATAC-seq experiments.

Key Components:
- macs2_callpeak: Single sample peak calling using MACS2
- homer_annotate_peaks: Annotate single sample peaks using HOMER
- create_consensus_peakset: Create consensus peaks from ALL samples

Output Structure:
- 03.peak_calling/single_macs2/{sample}/ - Individual sample MACS2 results
- 03.peak_calling/single_macs2_HOMER/ - Individual sample HOMER annotations
- 04.consensus/single_macs2/ - Consensus peaks from all samples
"""

rule macs2_callpeak:
    """
    Identify open chromatin regions (peaks) using MACS2 on the shifted ATAC-seq BAM file.

    This rule performs peak calling on each individual sample to identify genomic
    regions with significant chromatin accessibility. MACS2 is used with parameters
    optimized for ATAC-seq data to detect regions where Tn5 transposase insertion
    is significantly enriched.

    Key parameters:
    - -f BAMPE: Uses paired-end information for improved peak modeling
    - -g {{genome_size}}: Effective genome size for p-value calculation
    - -q {{qvalue}}: Q-value threshold (FDR control)
    - --keep-dup all: Retains all duplicates (already filtered)
    - -B --SPMR: Generates normalized bedGraph files
    """
    input:
        bam = '02.mapping/shifted/{sample}.shifted.sorted.bam',
        bai = '02.mapping/shifted/{sample}.shifted.sorted.bam.bai'
    output:
        bed = temp("02.mapping/shifted/{sample}/{sample}.macs2.bed"),
        narrow_peak = "03.peak_calling/single_macs2/{sample}/{sample}_peaks.narrowPeak",
        xls = "03.peak_calling/single_macs2/{sample}/{sample}_peaks.xls",
        summits = "03.peak_calling/single_macs2/{sample}/{sample}_summits.bed",
        bdg = "03.peak_calling/single_macs2/{sample}/{sample}_treat_pileup.bdg"
    resources:
        **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/macs2.yaml"),
    log:
        "logs/03.peak_calling/single_macs2/macs2_callpeak_{sample}.log",
    message:
        "Running MACS2 peak calling for {wildcards.sample}",
    benchmark:
        "benchmarks/03.peak_calling/single_macs2/macs2_callpeak_{sample}.txt",
    threads:
        config['parameter']['threads']['macs2'],
    params:
        gsize = config['genome_info'][config['Genome_Version']]['effectiveGenomeSize'],
        qvalue = config['parameter']['macs2']['qvalue'],
        outdir = "03.peak_calling/single_macs2/{sample}",
        tempdir = "03.peak_calling/tmp",
    shell:
        """
        # setting run temp dir
        export TMPDIR={params.tempdir}
        mkdir -p $TMPDIR
        # Convert filtered BAM to BED
        bedtools bamtobed -i {input.bam} > {output.bed} 2>> {log}
        # call peak by macs2
        macs2 callpeak \
            -t {output.bed} \
            -f BED \
            --nomodel \
            -g {params.gsize} \
            --name {wildcards.sample} \
            --outdir {params.outdir} \
            -q {params.qvalue} \
            --keep-dup all \
            --call-summits \
            -B --SPMR 2> {log}
        """

rule genrich_callpeak:
    """
    Identify open chromatin regions (peaks) using Genrich on the shifted ATAC-seq BAM file.

    This rule performs peak calling on each individual sample using Genrich,
    which is designed for ATAC-seq and ChIP-seq data. It first sorts the BAM
    file by read name (required by Genrich) and then calls peaks with parameters
    optimized for ATAC-seq.

    Key parameters:
    - -m 20: Minimum MAPQ score of 20
    - -p 0.01: Maximum p-value threshold
    - -q 0.05: Maximum q-value (FDR) threshold
    - -a 200: Maximum alignment length
    - -l 50: Minimum length of a genomic region
    - -g 100: Maximum distance between reads in the same region
    - -z: Uses the entire fragment for peak calling
    - -v: Verbose output
    """
    input:
        bam = '02.mapping/shifted/{sample}.shifted.sorted.bam'
    output:
        narrow_peak = "03.peak_calling/single_genrich/{sample}/{sample}_peaks.narrowPeak",
        nsort_bam = temp("03.peak_calling/single_genrich/{sample}/{sample}_nsorted.bam")
    resources:
        **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/genrich.yaml"),
    log:
        "logs/03.peak_calling/single_genrich/genrich_callpeak_{sample}.log",
    message:
        "Running Genrich peak calling for {wildcards.sample}",
    benchmark:
        "benchmarks/03.peak_calling/single_genrich/genrich_callpeak_{sample}.txt",
    threads:
        config['parameter']['threads'].get('genrich', 10),
    params:
        min_mapq = 20,
        max_pval = 0.01,
        max_qval = 0.05,
        max_align_len = 200,
        min_region_len = 50,
        max_dist = 100,
        outdir = "03.peak_calling/single_genrich/{sample}"
    shell:
        """
        mkdir -p {params.outdir}

        samtools sort -@ {threads} -n {input.bam} -o {output.nsort_bam} 2> {log}

        Genrich \
            -t {output.nsort_bam} \
            -o {output.narrow_peak} \
            -m {params.min_mapq} \
            -p {params.max_pval} \
            -q {params.max_qval} \
            -a {params.max_align_len} \
            -l {params.min_region_len} \
            -g {params.max_dist} \
            -z -v 2>> {log}
        """

rule homer_annotate_peaks_macs2:
    """
    Annotate peaks relative to gene features using HOMER.
    """
    input:
        peak = "03.peak_calling/single_macs2/{sample}/{sample}_peaks.narrowPeak"
    output:
        annotation = "03.peak_calling/single_macs2_HOMER/{sample}_annotation.txt",
        stats = "03.peak_calling/single_macs2_HOMER/{sample}_stats.txt"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/homer.yaml"),
    log:
        "logs/03.peak_calling/single_macs2/homer_annotate_peaks_{sample}.log",
    message:
        "Running HOMER annotation (MACS2) for {wildcards.sample}",
    benchmark:
        "benchmarks/03.peak_calling/single_macs2/homer_annotate_peaks_{sample}.txt",
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

rule extend_summits_macs2:
    """
    Extend MACS2 summits by ±250bp to create fixed 500bp regions per sample.
    """
    input:
        "03.peak_calling/single_macs2/{sample}/{sample}_summits.bed"
    output:
        "04.consensus/single_macs2/{sample}_summits_extended.bed"
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    log:
        "logs/04.consensus/single_macs2/extend_summits_{sample}.log",
    benchmark:
        "benchmarks/04.consensus/single_macs2/extend_summits_{sample}.txt",
    message:
        "Running extend_summits (MACS2)",
    threads: 1
    shell:
        """
        awk 'BEGIN{{OFS="\t"}} {{
            mid=int(($2+$3)/2);
            start=mid-250;
            if(start<0) start=0;
            end=mid+250;
            print $1, start, end, $4, $5
        }}' {input} > {output} 2> {log}
        """

rule merge_peaks_by_group_macs2:
    """
    Merge extended peaks within each group using HOMER mergePeaks (-d 250).
    """
    input:
        lambda wildcards: expand("04.consensus/single_macs2/{sample}_summits_extended.bed", sample=groups[wildcards.group])
    output:
        "04.consensus/single_macs2/{group}.mergePeaks.bed"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/homer.yaml"),
    log:
        "logs/04.consensus/single_macs2/merge_peaks_by_group_{group}.log",
    message:
        "Merging peaks for group {wildcards.group} (MACS2)",
    benchmark:
        "benchmarks/04.consensus/single_macs2/merge_peaks_by_group_{group}.txt",
    threads: 1
    shell:
        """
        mkdir -p $(dirname {log})
        mergePeaks {input} -d 250 > {output} 2> {log}
        """

rule filter_group_consensus_macs2:
    """
    Filter group-level merged peaks to retain only peaks supported by ≥2 replicates.
    """
    input:
        "04.consensus/single_macs2/{group}.mergePeaks.bed"
    output:
        "04.consensus/single_macs2/{group}.consensus.bed"
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    log:
        "logs/04.consensus/single_macs2/filter_group_consensus_{group}.log",
    benchmark:
        "benchmarks/04.consensus/single_macs2/filter_group_consensus_{group}.txt",
    message:
        "Running filter_group_consensus (MACS2)",
    threads: 
        1
    shell:
        """
        awk 'BEGIN{{OFS="\\t"}} NR==1{{next}} $8>=2 {{print $2,$3,$4,$1,$5,$8}}' {input} > {output} 2> {log}
        """

rule create_all_consensus_peaks_macs2:
    """
    Create final consensus peakset by merging all group-level consensus peaks.
    Converts HOMER mergePeaks output to standard BED4 for downstream compatibility.
    """
    input:
        expand("04.consensus/single_macs2/{group}.consensus.bed", group=groups.keys())
    output:
        "04.consensus/single_macs2/all_samples_consensus_peaks.bed"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    message:
        "Running create_all_consensus_peaks (MACS2)",
    conda:
        workflow.source_path("../envs/homer.yaml"),
    log:
        "logs/04.consensus/single_macs2/create_all_consensus_peaks.log",
    benchmark:
        "benchmarks/04.consensus/single_macs2/create_all_consensus_peaks.txt",
    threads: 1
    shell:
        """
        TMP_PEAKS=$(mktemp /tmp/all_peaks.XXXXXX.bed)
        cat {input} | sort -k1,1 -k2,2n > "$TMP_PEAKS"
        { mergePeaks -d 250 "$TMP_PEAKS" | awk 'BEGIN{{OFS="\t"}} NR==1{{next}} {{print $2,$3,$4,$1,$5,$8}}' > {output}; } 2> {log}
        rm -f "$TMP_PEAKS"
        """


rule homer_annotate_consensus_peaks_macs2:
    """
    Annotate consensus peaks relative to gene features using HOMER.
    """
    input:
        consensus = "04.consensus/single_macs2/all_samples_consensus_peaks.bed"
    output:
        annotation = "04.consensus/single_macs2/all_samples_consensus_peaks_annotation.txt",
        stats = "04.consensus/single_macs2/all_samples_consensus_peaks_stats.txt"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/homer.yaml"),
    log:
        "logs/04.consensus/single_macs2/homer_annotate_consensus_peaks.log",
    message:
        "Running HOMER annotation for consensus peaks (MACS2)",
    benchmark:
        "benchmarks/04.consensus/single_macs2/homer_annotate_consensus_peaks.txt",
    threads: 
        config['parameter']['threads']['homer']
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

rule generate_count_matrix_by_featureCounts_macs2:
    """
    Generate a read count matrix using featureCounts for the consensus peakset.
    """
    input:
        consensus = "04.consensus/single_macs2/all_samples_consensus_peaks.bed",
        bams = expand("02.mapping/shifted/{sample}.shifted.sorted.bam", sample=samples.keys())
    output:
        counts_matrix = "04.consensus/single_macs2/consensus_counts_matrix.txt",
        counts_clean = "04.consensus/single_macs2/consensus_counts_matrix.clean.txt",
        summary = "04.consensus/single_macs2/consensus_counts_matrix.txt.summary",
        saf = temp("04.consensus/single_macs2/consensus_peaks.saf"),
        description = "04.consensus/single_macs2/matrix_description.txt"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/subread.yaml"),
    log:
        "logs/04.consensus/single_macs2/generate_count_matrix_by_featureCounts.log",
    message:
        "Running featureCounts for consensus peaks (MACS2)",
    benchmark:
        "benchmarks/04.consensus/single_macs2/generate_count_matrix_by_featureCounts.txt",
    threads: 
        config['parameter']['threads'].get('featurecounts', 8)  # 添加默认值
    params:
        sample_count = len(samples),  # 新增：样本数
    shell:
        r"""
        echo "Step 1/4: Converting BED to SAF..." > {log}
        awk 'BEGIN{{OFS="\t"; print "GeneID\tChr\tStart\tEnd\tStrand"}} \
            {{print $1"_"$2"_"$3, $1, $2, $3, "+"}}' {input.consensus} > {output.saf}

        echo "Step 2/4: Running featureCounts..." >> {log}
        featureCounts \
            -p -B -C \
            --largestOverlap \
            --primary \
            -T {threads} \
            -F SAF \
            -a {output.saf} \
            -o {output.counts_matrix} \
            {input.bams} >> {log} 2>&1

        echo "Step 3/4: Cleaning header for R..." >> {log}
        awk 'NR==1 {{gsub(/02.mapping\/shifted\//,""); gsub(/\.shifted\.sorted\.bam/,""); print}} \
             NR>1 {{print}}' {output.counts_matrix} > {output.counts_clean}

        echo "Step 4/4: Generating description..." >> {log}
        # 使用printf避免heredoc问题
        printf "ATAC-seq Consensus Peak Count Matrix\n" > {output.description}
        printf "Generated: %s\n" "$(date +'%%Y-%%m-%%d %%H:%%M:%%S')" >> {output.description}
        printf "Samples: %d\n" {params.sample_count} >> {output.description}
        printf "Peaks: %d\n" $(wc -l < {input.consensus}) >> {output.description}
        printf "FeatureCounts Version: %s\n" "$(featureCounts -v 2>&1 | head -1)" >> {output.description}
        """

rule generate_count_matrix_ann_macs2:
    """
    Add gene annotation to the count matrix.
    """
    input:
        annotation = "04.consensus/single_macs2/all_samples_consensus_peaks_annotation.txt",
        counts_matrix = "04.consensus/single_macs2/consensus_counts_matrix.txt",
    output:
        counts_matrix_ann = "04.consensus/single_macs2/consensus_counts_matrix_ann.txt",
    message:
        "Running generate_count_matrix_ann (MACS2)",
    conda:
        workflow.source_path("../envs/bedtools.yaml"),
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    log:
        "logs/04.consensus/single_macs2/generate_count_matrix_ann.log",
    benchmark:
        "benchmarks/04.consensus/single_macs2/generate_count_matrix_ann.txt",
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

rule calculate_frip_score_macs2:
    """
    FRiP (Fraction of Reads in Peaks)
    ATACseq data standards acceptable FRiP is >0.2
    Calculate FRiP (Fraction of Reads in Peaks) score for each sample.
    
    FRiP measures the proportion of reads that fall within called peaks,
    which is a quality metric for peak calling performance.
    """
    input:
        bam = "02.mapping/shifted/{sample}.shifted.sorted.bam",
        peaks = "03.peak_calling/single_macs2/{sample}/{sample}_peaks.narrowPeak"
    output:
        frip = "03.peak_calling/single_macs2/{sample}/{sample}_frip.txt"
    benchmark:
        "benchmarks/03.peak_calling/single_macs2/calculate_frip_score_{sample}.txt",
    message:
        "Running calculate_frip_score (MACS2)",
    conda:
        workflow.source_path("../envs/subread.yaml"),
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    log:
        "logs/03.peak_calling/single_macs2/calculate_frip_score_{sample}.log"
    threads: 4
    shell:
        """
        totalReads=$(samtools view -c -F 4 {input.bam})
        
        awk 'BEGIN{{OFS="\\t"; print "GeneID\\tChr\\tStart\\tEnd\\tStrand"}} {{print "peak_"NR, $1, $2+1, $3, "."}}' {input.peaks} > {output.frip}.saf
        
        featureCounts -p -T {threads} -a {output.frip}.saf -F SAF  -o {output.frip}.counts {input.bam} 2>> {log}
            
        peakReads=$(grep "Assigned" {output.frip}.counts.summary | cut -f2)
        
        frip=$(awk "BEGIN {{printf \\"%.4f\\", $peakReads/$totalReads}}")
        
        echo -e "TotalReads\\t$totalReads" > {output.frip}
        echo -e "PeakReads\\t$peakReads" >> {output.frip}
        echo -e "FRiP\\t$frip" >> {output.frip}
        
        rm -f {output.frip}.saf {output.frip}.counts {output.frip}.counts.summary
        """