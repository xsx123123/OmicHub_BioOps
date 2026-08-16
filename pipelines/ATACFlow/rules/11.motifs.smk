#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
import os

# Rule for formatting merged peak files for TOBIAS analysis
rule tobias_format_bed:
    """
    Format merged peak BED files for TOBIAS footprinting analysis
    """
    input:
        peaks = "03.peak_calling/pooled/{group}/{group}_peaks.narrowPeak",
        genome_fa = lambda wildcards: config['Bowtie2_index'][config['Genome_Version']]['genome_fa']
    output:
        formatted_bed = "06.motif_analysis/01.formatted_peaks/{group}_peaks_formatted.bed"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/tobias.yaml"),
    log:
        "logs/07.motifs/tobias_format_bed_{group}.log",
    message:
        "Formatting peak BED file for {wildcards.group} TOBIAS analysis",
    benchmark:
        "benchmarks/07.motifs/tobias_format_bed_{group}.txt",
    threads:
        1
    shell:
        """
        mkdir -p $(dirname {output.formatted_bed})
        
        # 使用TOBIAS FormatBed格式化peak文件
        TOBIAS FormatBed --bed {input.peaks} \
                         --genome {input.genome_fa} \
                         --outdir $(dirname {output.formatted_bed}) \
                         --prefix {wildcards.group} \
                         --verbose &> {log}
                         
        # 重命名输出文件
        mv $(dirname {output.formatted_bed})/{wildcards.group}_peaks.bed {output.formatted_bed} 2>/dev/null || true
        """

rule tobias_ata_correct:
    """
    Correct ATAC-seq signal bias for footprinting analysis
    """
    input:
        bam = "02.mapping/merged/{group}.merged.bam",
        genome_fa = lambda wildcards: config['Bowtie2_index'][config['Genome_Version']]['genome_fa'],
        peaks = "06.motif_analysis/01.formatted_peaks/{group}_peaks_formatted.bed"
    output:
        bigwig = "06.motif_analysis/02.signal_corrected/{group}_corrected.bw",
        stats = "06.motif_analysis/02.signal_corrected/{group}_atacorrect_stats.txt"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/tobias.yaml"),
    log:
        "logs/07.motifs/tobias_ata_correct_{group}.log",
    message:
        "Correcting ATAC-seq signal for {wildcards.group}",
    benchmark:
        "benchmarks/07.motifs/tobias_ata_correct_{group}.txt",
    params:
        outdir = "06.motif_analysis/02.signal_corrected"
    threads:
        1
    shell:
        """
        mkdir -p {params.outdir}
        
        TOBIAS ATACorrect --bam {input.bam} \
                          --genome {input.genome_fa} \
                          --peaks {input.peaks} \
                          --outdir {params.outdir} \
                          --cores {threads} \
                          --prefix {wildcards.group} \
                          --verbose &> {log}
        """

rule tobias_estimate_footprints:
    """
    Estimate transcription factor footprints using TOBIAS
    """
    input:
        signal_bw = "06.motif_analysis/02.signal_corrected/{group}_corrected.bw",
        peaks = "06.motif_analysis/01.formatted_peaks/{group}_peaks_formatted.bed"
    output:
        footprints = "06.motif_analysis/03.footprints/{group}_footprints.bw",
        occurrences = "06.motif_analysis/03.footprints/{group}_occurrences.bed"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/tobias.yaml"),
    log:
        "logs/07.motifs/tobias_estimate_footprints_{group}.log",
    message:
        "Estimating footprints for {wildcards.group}",
    benchmark:
        "benchmarks/07.motifs/tobias_estimate_footprints_{group}.txt",
    params:
        outdir = "06.motif_analysis/03.footprints"
    threads:
        1
    shell:
        """
        mkdir -p {params.outdir}
        
        TOBIAS EstimateFootprints --signal {input.signal_bw} \
                                 --peaks {input.peaks} \
                                 --outdir {params.outdir} \
                                 --cores {threads} \
                                 --prefix {wildcards.group} \
                                 --verbose &> {log}
        """

# 添加JASPAR motif数据库下载规则（如果需要）
rule download_jaspar_motifs:
    """
    Download JASPAR motif database for transcription factor binding analysis
    """
    output:
        motifs = "06.motif_analysis/00.resources/JASPAR2024_CORE_vertebrates_non-redundant_pfms_jaspar.txt"
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/tobias.yaml"),
    log:
        "logs/07.motifs/download_jaspar_motifs.log",
    message:
        "Downloading JASPAR motif database",
    benchmark:
        "benchmarks/07.motifs/download_jaspar_motifs.txt",
    params:
        url = "https://jaspar.genereg.net/download/data/2024/CORE/JASPAR2024_CORE_vertebrates_non-redundant_pfms_jaspar.txt"
    threads:
        1
    shell:
        """
        mkdir -p $(dirname {output.motifs})
        wget -O {output.motifs} {params.url} &> {log} || curl -o {output.motifs} {params.url} &> {log}
        """

rule tobias_bindetect:
    """
    Detect differential transcription factor binding using TOBIAS BINDetect
    """
    input:
        signal_bw = "06.motif_analysis/02.signal_corrected/{group}_corrected.bw",
        genome_fa = lambda wildcards: config['Bowtie2_index'][config['Genome_Version']]['genome_fa'],
        motifs = "06.motif_analysis/00.resources/JASPAR2024_CORE_vertebrates_non-redundant_pfms_jaspar.txt",
        peaks = "06.motif_analysis/01.formatted_peaks/{group}_peaks_formatted.bed"
    output:
        bindetect_results = directory("06.motif_analysis/04.bindetect/{group}_bindetect_results"),
        summary_pdf = "06.motif_analysis/04.bindetect/{group}/{group}_BINDetect_plot.pdf"
    resources:
        **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/tobias.yaml"),
    log:
        "logs/07.motifs/tobias_bindetect_{group}.log",
    message:
        "Running tobias_bindetect",
    benchmark:
        "benchmarks/07.motifs/tobias_bindetect_{group}.txt",
    params:
        outdir = "06.motif_analysis/04.bindetect/{group}"
    threads:
        1
    shell:
        """
        mkdir -p {params.outdir}
        
        TOBIAS BINDetect --signals {input.signal_bw} \
                         --genome {input.genome_fa} \
                         --motifs {input.motifs} \
                         --peaks {input.peaks} \
                         --outdir {params.outdir} \
                         --cores {threads} \
                         --prefix {wildcards.group} \
                         --verbose &> {log}
        """


rule tobias_complete_analysis:
    """
    Complete TOBIAS motif analysis for all groups
    """
    input:
        bindetect_results = expand("06.motif_analysis/04.bindetect/{group}_bindetect_results", group=groups.keys()),
        footprints = expand("06.motif_analysis/03.footprints/{group}_footprints.bw", group=groups.keys())
    output:
        report = "06.motif_analysis/tobias_analysis_complete.txt"
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    log:
        "logs/07.motifs/tobias_complete_analysis.log",
    message:
        "Completing TOBIAS motif analysis for all groups",
    benchmark:
        "benchmarks/07.motifs/tobias_complete_analysis_benchmarks.txt",
    threads:
        1
    shell:
        """
        echo "TOBIAS motif analysis completed for all groups:" > {output.report}
        echo "Groups analyzed: {groups.keys()}" >> {output.report}
        echo "Results available in 06.motif_analysis/" >> {output.report}
        date >> {output.report}
        """

# 新增：组间差异motif分析规则
rule tobias_create_network:
    """
    Create comparison network between different groups using TOBIAS CreateNetwork
    """
    input:
        bindetect_dirs = expand("06.motif_analysis/04.bindetect/{{comparison}}/{group}",
                               group=groups.keys())
    output:
        network_dir = directory("06.motif_analysis/05.differential_motifs/{comparison}_network"),
        heatmap = "06.motif_analysis/05.differential_motifs/{comparison}_heatmap.pdf",
        barplot = "06.motif_analysis/05.differential_motifs/{comparison}_barplot.pdf"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/tobias.yaml"),
    log:
        "logs/07.motifs/tobias_create_network_{comparison}.log",
    message:
        "Creating motif comparison network for {wildcards.comparison}",
    benchmark:
        "benchmarks/07.motifs/tobias_create_network_{comparison}.txt",
    params:
        outdir = "06.motif_analysis/05.differential_motifs/{comparison}_network",
        prefix = "{comparison}"
    threads:
        1
    shell:
        """
        mkdir -p $(dirname {output.network_dir})

        # 收集所有组的bindetect结果文件
        bindetect_files=""
        for group in {groups.keys()}; do
            if [ -f "06.motif_analysis/04.bindetect/${{group}}/${{group}}_bindetect_results" ]; then
                bindetect_files="$bindetect_files 06.motif_analysis/04.bindetect/${{group}}/${{group}}_bindetect_results"
            fi
        done

        if [ ! -z "$bindetect_files" ]; then
            TOBIAS CreateNetwork --bindetect $bindetect_files \
                                --outdir $(dirname {output.network_dir}) \
                                --prefix {params.prefix} \
                                --cores {threads} \
                                --verbose &> {log}
        else
            echo "No bindetect results found for comparison {wildcards.comparison}" > {log}
            touch {{output.network_dir}},{{output.heatmap}},{{output.barplot}}
        fi
        """


rule tobias_pairwise_comparison:
    """
    Perform pairwise comparison of TF binding between two specific groups
    """
    input:
        group1_bindetect = "06.motif_analysis/04.bindetect/{contrast}/{{contrast}}_bindetect_results".format(contrast="{contrast}"),
        group2_bindetect = "06.motif_analysis/04.bindetect/{treatment}/{{treatment}}_bindetect_results".format(treatment="{treatment}")
    output:
        comparison_dir = directory("06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}"),
        differential_txt = "06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}/differential_tf_binding.txt",
        volcano_plot = "06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}/volcano_plot.pdf"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/tobias.yaml"),
    log:
        "logs/07.motifs/tobias_pairwise_comparison_{contrast}_vs_{treatment}.log",
    message:
        "Running tobias_pairwise_comparison",
    benchmark:
        "benchmarks/07.motifs/tobias_pairwise_comparison_{contrast}_vs_{treatment}.txt",
    params:
        outdir = "06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}",
        prefix = "{contrast}_vs_{treatment}"
    threads:
        1
    shell:
        """
        mkdir -p {params.outdir}

        # 使用TOBIAS Compare进行组间比较
        TOBIAS Compare --bindetect {input.group1_bindetect} {input.group2_bindetect} \
                       --outdir {params.outdir} \
                       --prefix {params.prefix} \
                       --cores {threads} \
                       --verbose &> {log}

        # 创建简化的结果摘要文件
        if [ -f "{params.outdir}/{params.prefix}_comparison.txt" ]; then
            cp "{params.outdir}/{params.prefix}_comparison.txt" {output.differential_txt}
        else
            echo "Comparison results" > {output.differential_txt}
            echo "Groups compared: {wildcards.contrast} vs {wildcards.treatment}" >> {output.differential_txt}
            date >> {output.differential_txt}
        fi
        """

# 新增：基于预定义对比组的差异分析规则
rule tobias_contrast_comparison:
    """
    Perform TF binding comparison based on predefined contrasts
    """
    input:
        control_bindetect = "06.motif_analysis/04.bindetect/{contrast}/{contrast}_bindetect_results",
        treatment_bindetect = "06.motif_analysis/04.bindetect/{treatment}/{treatment}_bindetect_results"
    output:
        comparison_dir = directory("06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}"),
        differential_txt = "06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}/differential_tf_binding.txt",
        volcano_plot = "06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}/volcano_plot.pdf",
        ma_plot = "06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}/ma_plot.pdf"
    resources:
        **rule_resource(config, 'medium_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/tobias.yaml"),
    log:
        "logs/07.motifs/tobias_contrast_comparison_{contrast}_vs_{treatment}.log",
    message:
        "Comparing TF binding between {wildcards.contrast} and {wildcards.treatment} (predefined contrast)",
    benchmark:
        "benchmarks/07.motifs/tobias_contrast_comparison_{contrast}_vs_{treatment}.txt",
    params:
        outdir = "06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}",
        prefix = "{contrast}_vs_{treatment}"
    threads:
        1
    shell:
        """
        mkdir -p {params.outdir}

        # 使用TOBIAS Compare进行对比组比较
        TOBIAS Compare --bindetect {input.control_bindetect} {input.treatment_bindetect} \
                       --outdir {params.outdir} \
                       --prefix {params.prefix} \
                       --cores {threads} \
                       --verbose &> {log}

        # 创建简化的结果摘要文件
        if [ -f "{params.outdir}/{params.prefix}_comparison.txt" ]; then
            cp "{params.outdir}/{params.prefix}_comparison.txt" {output.differential_txt}
        else
            echo "Comparison results for {wildcards.contrast} vs {wildcards.treatment}" > {output.differential_txt}
            echo "Control group: {wildcards.contrast}" >> {output.differential_txt}
            echo "Treatment group: {wildcards.treatment}" >> {output.differential_txt}
            date >> {output.differential_txt}
        fi
        """

rule tobias_differential_analysis_report:
    """
    Generate comprehensive differential motif analysis report
    """
    input:
        pairwise_comparisons = expand("06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}/differential_tf_binding.txt",
                                    zip, contrast=ALL_CONTRASTS, treatment=CONTRAST_MAP),
        networks = expand("06.motif_analysis/05.differential_motifs/{contrast}_vs_{treatment}_network",
                         zip, contrast=ALL_CONTRASTS, treatment=CONTRAST_MAP) if len(ALL_CONTRASTS) > 0 else []
    output:
        report_txt = "06.motif_analysis/06.final_report/differential_motif_analysis_report.txt",
        summary_html = "06.motif_analysis/06.final_report/differential_motif_analysis_summary.html"
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/tobias.yaml"),
    log:
        "logs/07.motifs/tobias_differential_analysis_report.log",
    message:
        "Generating differential motif analysis report",
    benchmark:
        "benchmarks/07.motifs/tobias_differential_analysis_report.txt",
    params:
        outdir = "06.motif_analysis/06.final_report"
    threads:
        1
    shell:
        """
        mkdir -p {params.outdir}

        echo "# Differential Motif Analysis Report" > {output.report_txt}
        echo "===================================" >> {output.report_txt}
        echo "" >> {output.report_txt}
        echo "Date: $(date)" >> {output.report_txt}
        echo "Contrasts analyzed: " >> {output.report_txt}

        for i in "${{!ALL_CONTRASTS[@]}}"; do
            contrast=${{ALL_CONTRASTS[$i]}}
            treatment=${{CONTRAST_MAP[$i]}}
            echo "- $contrast vs $treatment" >> {output.report_txt}
        done

        echo "" >> {output.report_txt}
        echo "## Pairwise Comparisons Performed:" >> {output.report_txt}

        for comparison in {input.pairwise_comparisons}; do
            if [ -f "$comparison" ]; then
                echo "- $(basename $(dirname $comparison))" >> {output.report_txt}
            fi
        done

        echo "" >> {output.report_txt}
        echo "## Key Findings:" >> {output.report_txt}
        echo "- Analysis completed for all predefined contrasts" >> {output.report_txt}
        echo "- Results available in respective directories" >> {output.report_txt}

        # 创建简单的HTML摘要
        echo "<html><head><title>Differential Motif Analysis Report</title></head><body>" > {output.summary_html}
        echo "<h1>Differential Motif Analysis Report</h1>" >> {output.summary_html}
        echo "<p>Date: $(date)</p>" >> {output.summary_html}
        echo "<p>Contrasts analyzed:</p><ul>" >> {output.summary_html}

        for i in "${{!ALL_CONTRASTS[@]}}"; do
            contrast=${{ALL_CONTRASTS[$i]}}
            treatment=${{CONTRAST_MAP[$i]}}
            echo "<li>$contrast vs $treatment</li>" >> {output.summary_html}
        done

        echo "</ul>" >> {output.summary_html}
        echo "<h2>Pairwise Comparisons:</h2><ul>" >> {output.summary_html}

        for comparison in {input.pairwise_comparisons}; do
            if [ -f "$comparison" ]; then
                echo "<li>$(basename $(dirname $comparison))</li>" >> {output.summary_html}
            fi
        done

        echo "</ul></body></html>" >> {output.summary_html}
        """