#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
import os
from utils.tools import get_java_opts,get_blacklist_path,get_organelle_names
# --------------- Mapping Rules --------------- #
# if config.get("mapping_tools","chromap") == "chromap":
#    include: "./subrules/mapping/chromap.smk"
#    logger.info("ATAC mapping powered by Chromap") 
# else:
#    include: "./subrules/mapping/bowtie2.smk"
#    logger.info("ATAC mapping powered by bowtie2") 
include: "./subrules/mapping/bowtie2.smk"
# --------------- Mapping Rules --------------- #
rule sorted_bam:
    """
    Convert SAM to sorted BAM format and create index for efficient access.

    This rule converts the SAM format output from the aligner to the compressed BAM format,
    which is the standard binary format for storing aligned sequencing data. The BAM file
    is coordinate-sorted to enable efficient random access by genomic position, and an
    index is generated to support rapid data retrieval for downstream analysis tools.

    Key processing steps:
    - Convert SAM to BAM format using samtools (compression reduces file size)
    - Sort BAM by chromosomal coordinates for indexed access
    - Generate BAM index (.bai) for fast random access to genomic regions

    The sorted BAM and its index serve as the foundation for downstream analyses
    including peak calling, coverage visualization, and quality assessment.
    """
    input:
        bam = '02.mapping/Aligner/{sample}/{sample}.bam',
    output:
        sort_bam = '02.mapping/Aligner/{sample}/{sample}.sorted.bam',
        sort_bam_bai = '02.mapping/Aligner/{sample}/{sample}.sorted.bam.bai',
    resources:
        **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/samtools.yaml"),  # Changed from bwa2.yaml to samtools.yaml
    message:
        "Converting SAM to BAM, sorting and indexing for {wildcards.sample}",
    log:
        "logs/02.mapping/sam_to_sorted_bam_{sample}.log",
    benchmark:
        "benchmarks/02.mapping/{sample}_sam_to_sorted_bam_benchmark.txt",
    threads:
        config['parameter']['threads']['samtools'],
    shell:
        """
        ( samtools sort -@ {threads} -o {output.sort_bam} {input.bam} &&
        samtools index -@ {threads} {output.sort_bam} ) &>{log}
        """

rule bam2cram:
    """
    Convert BAM files to CRAM format for storage efficiency.

    This rule compresses the sorted BAM files into CRAM format, which typically
    achieves 40-60% smaller file sizes compared to BAM while maintaining full
    compatibility with most bioinformatics tools. The CRAM format uses reference-
    based compression, making it ideal for large-scale ATAC-seq projects where
    storage costs are a concern.
    """
    input:
        sort_bam = '02.mapping/Aligner/{sample}/{sample}.sorted.bam',
        sort_bam_bai = '02.mapping/Aligner/{sample}/{sample}.sorted.bam.bai',
    output:
        cram = '02.mapping/cram/{sample}.cram',
        cram_index = '02.mapping/cram/{sample}.cram.crai',
    resources:
        **rule_resource(config, 'medium_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/bwa2.yaml"),
    message:
        "Running bam2cram",
    log:
        "logs/02.mapping/bam2cram_{sample}.log",
    benchmark:
        "benchmarks/02.mapping/bam2cram_{sample}.txt",
    threads:
        config['parameter']['threads']['bam2cram'],
    params:
        reference = config['Bowtie2_index'][config['Genome_Version']]['genome_fa'],
    shell:
        """
        samtools view -@ {threads} -C -T {params.reference} -o {output.cram} {input.sort_bam}
        samtools index  -@ {threads} {output.cram}
        """

rule samtools_flagst:
    """
    Generate flag statistics for BAM files using samtools flagstat.

    This rule produces comprehensive statistics about the alignment flags in the BAM file,
    providing a breakdown of how reads are categorized based on their SAM flag values.
    Flagstat reports essential quality metrics that help assess the success of the
    alignment step and identify potential issues with the sequencing data.

    Key statistics reported include:
    - Total number of reads in the BAM file
    - Number of reads mapped to the reference genome
    - Properly paired reads (reads mapped in correct orientation and distance)
    - Reads mapped as singletons (only one end of pair mapped)
    - Reads mapped to different chromosomes or with unexpected orientations
    - Duplicate reads and supplementary alignments

    These metrics are crucial for quality control, enabling the identification of
    alignment problems such as high unmapped rates, poor pairing efficiency, or
    contamination with adapter dimers. The tab-separated format facilitates downstream
    parsing and integration into quality control reports.
    """
    input:
        bam = '02.mapping/Aligner/{sample}/{sample}.sorted.bam',
        bai = '02.mapping/Aligner/{sample}/{sample}.sorted.bam.bai',
    output:
        samtools_flagstat = '02.mapping/samtools_flagstat/{sample}_bam_flagstat.tsv',
    resources:
        **rule_resource(config, 'medium_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/samtools.yaml"),
    message:
        "Running samtools flagstat for BAM : {input.bam}",
    log:
        "logs/02.mapping/samtools_flagst_{sample}.log",
    benchmark:
        "benchmarks/02.mapping/samtools_flagst_{sample}.txt",
    threads:
        config['parameter']["threads"]["samtools_flagstat"],
    shell:
        """
        samtools flagstat \
                 -@ {threads} \
                 -O tsv \
                 {input.bam} > {output.samtools_flagstat} 2>{log}
        """


rule samtools_stats:
    """
    Generate comprehensive statistics for BAM files using samtools stats.

    This rule produces detailed statistical summaries of the BAM file, including
    alignment quality metrics, coverage statistics, insert size distributions,
    and base composition analyses. The samtools stats tool provides comprehensive
    quality control data that helps assess the overall success of the sequencing
    experiment and identify potential technical issues.

    Key statistics and metrics reported include:
    - Summary statistics: total reads, mapped reads, duplicate rates
    - Quality metrics: average base quality scores, quality distributions
    - Insert size statistics: mean, median, and standard deviation of fragment lengths
    - Coverage statistics: mean coverage, coverage histograms
    - Base composition: nucleotide frequencies and GC content
    - Read length distributions and mapping quality scores
    - Chromosome-specific statistics and coverage summaries

    The reference genome is used to calculate coverage statistics and evaluate
    the quality of alignments against the expected genomic sequence. This detailed
    statistical report is essential for quality control, enabling the assessment
    of library quality, sequencing depth, and the identification of any technical
    artifacts that might affect downstream analyses. The tab-separated output format
    facilitates easy parsing and integration into quality control summaries and
    multi-sample comparison reports.
    """
    input:
        bam = '02.mapping/Aligner/{sample}/{sample}.sorted.bam',
        bai = '02.mapping/Aligner/{sample}/{sample}.sorted.bam.bai',
    output:
        samtools_stats = '02.mapping/samtools_stats/{sample}_bam_stats.tsv',
    resources:
        **rule_resource(config, 'medium_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/samtools.yaml"),
    message:
        "Running samtools stats for BAM : {input.bam}",
    log:
        "logs/02.mapping/samtools_stats_{sample}.log",
    benchmark:
        "benchmarks/02.mapping/samtools_stats_{sample}.txt",
    threads:
        config['parameter']['threads']['samtools_stats'],
    params:
        reference = config['Bowtie2_index'][config['Genome_Version']]['genome_fa'],
    shell:
        """
        samtools stats \
                 -@ {threads} \
                 --reference {params.reference} \
                 {input.bam} > {output.samtools_stats}  2>{log}
        """


rule add_read_groups:
    """
    Add read groups to BAM file using samtools addreplacerg.

    This rule assigns read group (RG) information to each alignment in the BAM file,
    which is essential for downstream GATK tools and other analysis pipelines that
    require read group metadata. Read groups allow tracking of sequencing data
    from different libraries, lanes, or flow cells, enabling proper handling of
    technical artifacts and batch effects.

    Key read group fields assigned:
    - ID: Read group identifier (set to sample name for unique identification)
    - LB: Library identifier (set to "lib1" for tracking library preparation)
    - PL: Platform/technology used (configured via config, typically "illumina")
    - PU: Platform unit/flow cell barcode and lane (set to "unit1")
    - SM: Sample name (derived from wildcards.sample for sample tracking)

    The read group information is crucial for:
    - Distinguishing reads from different sequencing runs or lanes
    - Identifying and correcting batch effects in downstream analyses
    - Enabling duplicate marking algorithms to work correctly across read groups
    - Facilitating variant calling and other analyses that require read group awareness

    The output BAM file maintains all original alignment information while adding
    the structured read group metadata required by GATK and other analysis tools.
    The coordinate sorting and indexing ensure compatibility with downstream
    processing steps including duplicate marking and variant analysis.
    """
    input:
        bam = '02.mapping/Aligner/{sample}/{sample}.sorted.bam',
        sort_bai = '02.mapping/Aligner/{sample}/{sample}.sorted.bam.bai',
    output:
        bam = '02.mapping/gatk/{sample}/{sample}.rg.bam',
        bai = '02.mapping/gatk/{sample}/{sample}.rg.bam.bai',
    message:
        "Running add_read_groups",
    conda:
        workflow.source_path("../envs/samtools.yaml")
    log:
        "logs/02.mapping/add_read_groups_{sample}.log"
    benchmark:
        "benchmarks/02.mapping/add_read_groups_{sample}.txt"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    threads: 
        config['parameter']['threads']['addreplacerg'],
    params:
        PL = config["parameter"]["AddOrReplaceReadGroups"]["PL"],
    shell:
        """
        ( samtools addreplacerg \
            -@ {threads} \
            -r $'@RG\\tID:{wildcards.sample}\\tLB:lib1\\tPL:{params.PL}\\tPU:unit1\\tSM:{wildcards.sample}' \
            -o {output.bam} \
            -O BAM {input.bam} && \
          samtools index -@ {threads} {output.bam} \
        ) 2> {log}
        """

# --------------- mark dup Rules --------------- #
# if config.get("mapping_tools","chromap") == "chromap":
#     include: "./subrules/mapping/chromap_mark_duplicates.smk"
#     logger.info("skiping ATAC mark dup for Chromap") 
# else:
#     include: "./subrules/mapping/bowtie2_mark_duplicates.smk"
#     logger.info("ATAC mark dup for bowtie2") 
include: "./subrules/mapping/bowtie2_mark_duplicates.smk"
# --------------- mark dup Rules --------------- #

rule samtools_flagst_dedup:
    """
    Generate flag statistics for BAM files using samtools flagstat.

    This rule produces comprehensive statistics about the alignment flags in the BAM file,
    providing a breakdown of how reads are categorized based on their SAM flag values.
    Flagstat reports essential quality metrics that help assess the success of the
    alignment step and identify potential issues with the sequencing data.

    Key statistics reported include:
    - Total number of reads in the BAM file
    - Number of reads mapped to the reference genome
    - Properly paired reads (reads mapped in correct orientation and distance)
    - Reads mapped as singletons (only one end of pair mapped)
    - Reads mapped to different chromosomes or with unexpected orientations
    - Duplicate reads and supplementary alignments

    These metrics are crucial for quality control, enabling the identification of
    alignment problems such as high unmapped rates, poor pairing efficiency, or
    contamination with adapter dimers. The tab-separated format facilitates downstream
    parsing and integration into quality control reports.
    """
    input:
        bam = '02.mapping/gatk/{sample}/{sample}.rg.dedup.bam',
        bai = '02.mapping/gatk/{sample}/{sample}.rg.dedup.bai',
    output:
        samtools_flagstat = '02.mapping/samtools_flagstat/{sample}_bam_dedup_flagstat.tsv',
    resources:
        **rule_resource(config, 'medium_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/samtools.yaml"),
    message:
        "Running samtools flagstat for BAM : {input.bam}",
    log:
        "logs/02.mapping/samtools_flagst_dedup_{sample}.log",
    benchmark:
        "benchmarks/02.mapping/samtools_flagst_dedup_{sample}.txt",
    threads:
        config['parameter']["threads"]["samtools_flagstat"],
    shell:
        """
        samtools flagstat \
                 -@ {threads} \
                 -O tsv \
                 {input.bam} > {output.samtools_flagstat} 2>{log}
        """

rule filter_blacklist_and_mito:
    """
    Filter BAM files to remove blacklist regions, organellar reads,
    low mapping quality reads, and unwanted flags
    """
    input:
        bam = '02.mapping/gatk/{sample}/{sample}.rg.dedup.bam',
    output:
        bam = '02.mapping/filtered/{sample}.clean.bam',
        bai = '02.mapping/filtered/{sample}.clean.bam.bai'
    log:
        "logs/02.mapping/filter_blacklist_and_mito_{sample}.log"
    benchmark:
        "benchmarks/02.mapping/filter_blacklist_and_mito_{sample}.txt",
    message:
        "Running filter_blacklist_and_mito",
    conda:
        workflow.source_path("../envs/samtools.yaml")
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    params:
        mapq = config['parameter'].get('filter_bam', {}).get('mapq', 30),
        flag_filter = config['parameter'].get('filter_bam', {}).get('flag_filter', 1548),
        flag_req = config['parameter'].get('filter_bam', {}).get('flag_req', 2),
        blacklist = lambda wildcards: get_blacklist_path(config),
        organelle_filter = lambda wildcards: " && ".join([f'rname != \\"{n}\\"' for n in get_organelle_names(config).split()]) if get_organelle_names(config) else "1"
    threads: 
        4
    shell:
        """
        # 设置 blacklist 过滤命令
        if [ -n "{params.blacklist}" ]; then
            FILTER_CMD="bedtools intersect -v -a stdin -b {params.blacklist}"
            echo "Using blacklist: {params.blacklist}" > {log}
        else
            FILTER_CMD="cat"
            echo "No blacklist used." > {log}
        fi

        # 直接在命令中使用 params.organelle_filter
        echo "Filter expression: {params.organelle_filter}" >> {log}

        (samtools view -@ {threads} -h -b -F {params.flag_filter} -f {params.flag_req} -q {params.mapq} -e "{params.organelle_filter}" {input.bam} | \
         eval "$FILTER_CMD" > {output.bam}) 2>> {log}

        samtools index {output.bam} >> {log} 2>&1
        """

# rule filter_proper_pairs:
#    """
#    Filter for properly paired reads and sort by name then by position.
#
#    This rule processes the filtered BAM files to retain only properly paired reads
#    and performs coordinate-based sorting to prepare the data for downstream analyses.
#    Properly paired reads are those where both ends of the DNA fragment map to the
#    reference genome in the expected orientation and within a reasonable distance
#    from each other.
#
#    Key processing steps:
#    - Sort the input BAM file by read name to group paired reads together
#    - Filter for properly paired reads using specialized filtering tools
#    - Sort the resulting BAM file by genomic coordinates for downstream compatibility
#    - Generate index files for rapid random access to genomic regions
#
#    This filtering step is critical for ATAC-seq analysis as it ensures that only
#    high-quality, properly paired fragments are used for peak calling and other
#    downstream analyses. Removing improperly paired reads improves the accuracy
#    of fragment length estimation, insertion site analysis, and peak detection.
#
#   The coordinate-sorted output is compatible with downstream tools that require
#    position-sorted input, such as peak callers, coverage analysis tools, and
#    visualization software.
#    """
#    input:
#        bam = '02.mapping/filtered/{sample}.clean.bam',
#        bai = '02.mapping/filtered/{sample}.clean.bam.bai'
#    output:
#        sort_name_bam = '02.mapping/filter_pe/{sample}.sort_name.bam',
#        bam = '02.mapping/filter_pe/{sample}.filter_pe.bam',
#        sort_bam = '02.mapping/filter_pe/{sample}.filter_pe.sorted.bam',
#        sort_bam_bai = '02.mapping/filter_pe/{sample}.filter_pe.sorted.bam.bai'
#    log:
#        "logs/02.mapping/filter_proper_pairs_{sample}.log"
#    benchmark:
#        "benchmarks/02.mapping/filter_proper_pairs_{sample}.txt"
#    resources:
#        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
#    conda:
#        workflow.source_path("../envs/samtools.yaml")
#    threads: 10
#    params:
#        filter_pe = workflow.source_path(config['parameter']['filter_pe']['path']),
#    shell:
#        """
#         ( chmod +x {params.filter_pe} && \
#        samtools sort -n -@ {threads} -o {output.sort_name_bam} {input.bam} && \
#        {params.filter_pe} -t {threads} -i {output.sort_name_bam} -o {output.bam} && \
#        samtools sort -@ {threads} {output.bam} -o {output.sort_bam} && \
#        samtools index -@ {threads} {output.sort_bam} ) > {log} 2>&1
#        """

# --------------- tn5 shift Rules --------------- #
# if config.get("mapping_tools","chromap") == "chromap":
#     include: "./subrules/mapping/chromap_shift.smk"
#     logger.info("skiping bam tn5 shift for Chromap") 
# else:
#     include: "./subrules/mapping/bowtie2_shift.smk "
#     logger.info("ATAC bam tn5 shift for bowtie2") 
include: "./subrules/mapping/bowtie2_shift.smk"
# ---------------tn5 shift Rules --------------- #

rule generate_bigwig_coverage:
    """
    Generate normalized BigWig coverage files from BAM
    """
    input:
        shifted_sort_bam = '02.mapping/shifted/{sample}.shifted.sorted.bam',
        shifted_sort_bam_bai = '02.mapping/shifted/{sample}.shifted.sorted.bam.bai'
    output:
        bw = "02.mapping/bamCoverage/{sample}_RPKM.bw",
    resources:
        **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/deeptools.yaml"),
    message:
        "Running bamCoverage (bigwig generation) for {input.shifted_sort_bam}"
    log:
        "logs/02.mapping/generate_bigwig_coverage_{sample}.log",
    benchmark:
        "benchmarks/02.mapping/generate_bigwig_coverage_{sample}.txt",
    threads:
        config['parameter']['threads']['bamCoverage'],
    params:
        binSize = config['parameter']['bamCoverage']['binSize'],
        smoothLength = config['parameter']['bamCoverage']['smoothLength'],
        normalizeUsing = "RPKM",
        effectiveGenomeSize = config['genome_info'][config['Genome_Version']]['effectiveGenomeSize'],
        ignore_chroms = lambda wildcards: get_organelle_names(config)
    shell:
        """
        bamCoverage --bam {input.shifted_sort_bam} -o {output.bw} \
            --binSize {params.binSize} \
            --normalizeUsing {params.normalizeUsing} \
            --effectiveGenomeSize {params.effectiveGenomeSize} \
            --ignoreForNormalization {params.ignore_chroms} \
            -p {threads} &> {log}
        """

rule tss_enrichment_analysis:
    """
    Compute TSS enrichment profile and generate plot
    """
    input:
        bw = "02.mapping/bamCoverage/{sample}_RPKM.bw",
    output:
        matrix = "02.mapping/computeMatrix/{sample}_TSS_matrix.gz",
        plot = "02.mapping/plots/{sample}_TSS_enrichment.png"
    benchmark:
        "benchmarks/02.mapping/tss_enrichment_analysis_{sample}.txt",
    message:
        "Running tss_enrichment_analysis",
    params:
        gene_bed = config['Bowtie2_index'][config['Genome_Version']]['tss_bed'],
        referencePoint = config['parameter']['draw_tss_plot']['referencePoint'],
        range_up_down = config['parameter']['draw_tss_plot']['range'],
    log:
        "logs/02.mapping/tss_enrichment_analysis_{sample}.log"
    conda:
        workflow.source_path("../envs/deeptools.yaml"),
    resources:
        **rule_resource(config, 'high_resource',  skip_queue_on_local=True,logger = logger),
    threads: 
        20
    shell:
        """
        # Compute matrix around TSS
        computeMatrix reference-point --referencePoint {params.referencePoint} \
                      -b {params.range_up_down} -a {params.range_up_down} \
                      -R {params.gene_bed} \
                      -S {input.bw} \
                      --skipZeros \
                      -o {output.matrix} \
                      -p {threads} &> {log}

        # Generate TSS enrichment plot
        plotProfile -m {output.matrix} \
                    -out {output.plot} \
                    --plotTitle "ATAC-seq TSS Enrichment for {wildcards.sample}" \
                    --dpi 1000 \
                    --perGroup >> {log} 2>&1
        """
# ----- end of rules ----- #