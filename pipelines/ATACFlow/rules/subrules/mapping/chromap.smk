#!/usr/bin/snakemake
# -*- coding: utf-8 -*-

rule Chromap_mapping:
    """
    Align paired-end ATAC-seq reads to the reference genome using Chromap.

    Chromap is an ultra-fast aligner for chromatin accessibility sequencing data,
    specifically optimized for ATAC-seq. It combines the speed of minimap2 with
    the accuracy of Bowtie2, making it ideal for large-scale ATAC-seq datasets.

    Chromap is configured with parameters specifically optimized for ATAC-seq:
    - -t: Number of threads for parallel processing
    - --preset atac: Preset configuration optimized for ATAC-seq data
    - --min-mapq: Minimum mapping quality threshold

    The alignment process uses the cleaned, adapter-trimmed reads and generates
    an unsorted BAM file as output, which then goes through the same downstream
    processing as Bowtie2 alignments.

    Chromap offers significant advantages for ATAC-seq analysis:
    - 5-10x faster than Bowtie2 with comparable accuracy
    - Lower memory usage
    - Built-in support for ATAC-seq specific alignment parameters
    - Efficient handling of large datasets
    """
    input:
        r1 = "01.qc/short_read_trim/{sample}.R1.trimed.fq.gz",
        r2 = "01.qc/short_read_trim/{sample}.R2.trimed.fq.gz",
    output:
        sam = temp('02.mapping/Aligner/{sample}/{sample}.sam'),
        bam = '02.mapping/Aligner/{sample}/{sample}.bam',
        summary = '02.mapping/Aligner/{sample}/{sample}.summary',
    resources:
        **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../../../envs/chromap.yaml"),
    log:
        "logs/02.mapping/Chromap_{sample}.log",
    message:
        "Running Chromap mapping on {wildcards.sample} R1 and R2",
    benchmark:
        "benchmarks/{sample}_Chromap_benchmark.txt",
    params:
        ref = config['Bowtie2_index'][config['Genome_Version']]['genome_fa'],
        index = config['Bowtie2_index'][config['Genome_Version']]['chromap_index'],
    threads:
        config['parameter'].get('threads', {}).get('chromap', 8),
    shell:
        """
        ( 
        # mapping atac-seq data by chromap
        ulimit -n 65535 && \
          chromap \
            -t {threads} \
            --preset atac \
            -x {params.index} \
            -r {params.ref} \
            -1 {input.r1} \
            -2 {input.r2} \
            --SAM \
            --summary {output.summary} \
            -o {output.sam} 
        # convert sam to bam
        samtools view -@ {threads} -bS {output.sam} > {output.bam} ) &> {log}
        """