# ATACFlow Development & Experiment Log

> **Repository**: ATACFlow  
> **Version**: v0.0.5 (Active Development)  
> **Period**: 2026-01 ~ 2026-04  
> **Generated From**: `git log` history with detailed code diffs  

---

## Overview

This document records the complete development history of the ATACFlow ATAC-seq analysis pipeline from January 2026 to April 2026. The log is sorted chronologically by date, with detailed code modifications summarized for each commit.

---

## Chronological Experiment Record

### 2026-01-21

#### `a1dd1e0` - ATACFlow v0.0.1: Initial Analysis Rules

**Scope**: First major commit establishing the foundational pipeline structure.

**Code Changes**:
- `snakefile`: Set up the main Snakemake entry point with basic config loading (`config.yaml`, `config/reference.yaml`, `config/run_parameter.yaml`).
- `rules/01.common.smk`: Established common helper functions and global resource definitions.
- `rules/07.mapping.smk` (369 lines added): First version of the mapping module using Bowtie2 with paired-end read alignment.
- `rules/08.MACS2.smk` (115 lines added): Initial MACS2 peak calling rules with `macs2 callpeak` on BAM files.
- `rules/utils/resource_manager.py`: Added `rule_resource()` helper to standardize CPU/memory allocation across rules.
- `config/reference.yaml`: Populated with initial reference genome paths.
- `schema/config.schema.yaml`: Defined the first JSONSchema for config validation.

**Key Pipeline Logic Introduced**:
```python
# snakefile - early version
configfile: "config.yaml"
configfile: "config/reference.yaml"
configfile: "config/run_parameter.yaml"
workdir: config["workflow"]
```

---

### 2026-01-22

#### `b5a372c` / `35e41f4` - ATACFlow v0.0.1: Env Setup & Analysis Rules

**Code Changes**:
- Added Conda environment definitions:
  - `envs/Preseq.yaml` - Library complexity estimation
  - `envs/bedtools.yaml` - BED manipulation
  - `envs/homer.yaml` - Peak annotation
  - `envs/macs2.yaml` - Peak calling (106 lines, comprehensive dependency list)
  - `envs/samtools.yaml` - BAM processing
- `rules/03.file_convert_md5.smk`: MD5 checksum validation for raw FASTQ files.
- `rules/04.short_read_qc.smk`: FastQC execution for R1/R2 reads.
- `rules/05.Contamination_check.smk`: FastQ-Screen integration to detect cross-species contamination.
- `rules/06.short_read_clean.smk`: fastp-based adapter trimming and quality filtering.
- `rules/07.mapping.smk`: Refined mapping output paths and temp file handling.
- `rules/08.MACS2.smk`: Enhanced with blacklist filtering (`bedtools intersect -v`).
- `rules/utils/reference_update.py`: Added logic to resolve relative reference paths to absolute paths.
- `.gitignore`: Added standard Python/Snakemake ignore patterns.

#### `95b328e` / `83e7aba` - ATACFlow v0.0.1: Fix 07.mapping.smk

**Code Changes**:
- `rules/07.mapping.smk`: Fixed Bowtie2 index path resolution. Changed from hardcoded index prefix to `params.index` dynamically loaded from `config["bowtie2"]["index"]`.
- `config/reference.yaml`: Added `bowtie2` and `bwa_mem2` index configuration sections.
- `config/run_parameter.yaml`: Adjusted default thread counts for mapping rules.

---

### 2026-01-22

#### `07bc6fe` - ATACFlow v0.0.2: Add Group Analysis Logic

**Scope**: Introduced group-based merged BAM analysis and ATAC-seq specific QC.

**Code Changes**:
- `rules/09.MergeMACS2.smk` (160 lines added): Added rules to merge BAM files by `group`, perform pooled peak calling, and generate consensus peak sets across replicates.
- `rules/10.ataqv.smk` (67 lines added): Integrated `ataqv` for ATAC-seq quality metrics (TSS enrichment, insert size distribution).
- `rules/utils/id_convert.py`: Rewrote `load_samples()` and `parse_groups()` to support group-level metadata parsing from `samples.csv`.
- `envs/ataqv.yaml`: New environment for ATAC-seq QC.
- `envs/macs2.yaml`: Added `macs2` dependencies required for pooled peak calling.
- `snakefile`: Added includes for `09.MergeMACS2.smk` and `10.ataqv.smk`.

**Key Function Added**:
```python
def parse_groups(samples):
    """Parse sample grouping information for pooled analysis."""
    groups = {}
    for sample_id, info in samples.items():
        group = info.get("group")
        if group not in groups:
            groups[group] = []
        groups[group].append(sample_id)
    return groups
```

---

### 2026-01-22

#### `e2c2bcb` - ATACFlow v0.0.3: Add Motif Analysis

**Scope**: Added transcription factor motif discovery using HOMER and TOBIAS.

**Code Changes**:
- `rules/11.motifs.smk` (416 lines added): Comprehensive motif analysis module including:
  - `homer_find_motifs_genome`: de novo and known motif discovery
  - `tobias_detect`: TF footprinting detection with TOBIAS
  - `tobias_plot`: Visualization of footprinting scores
- `envs/tobias.yaml`: Added TOBIAS and footprinting dependencies.
- `rules/01.common.smk`: Added motif analysis resource profiles (high memory for TOBIAS).
- `rules/15.deliver.smk`: Updated to include motif result paths in delivery manifest.
- `snakefile`: Included `11.motifs.smk` in the rule chain.

---

### 2026-01-23

#### `80a4a9b` / `ef6bb7d` - ATACFlow v0.0.3: Fix MACS2 & HOMER

**Code Changes**:
- `rules/08.MACS2.smk`: Fixed peak calling output filenames to match MACS2 default naming (`_peaks.narrowPeak`, `_summits.bed`). Added `bedtools sort` and `bedtools merge` for post-processing.
- `rules/09.MergeMACS2.smk`: Fixed consensus peak generation logic. Added `cat` + `sort -k1,1 -k2,2n` + `bedtools merge` pipeline for merging peaks across replicates.
- `rules/01.common.smk`: Simplified resource allocation logic. Removed hardcoded memory values in favor of `rule_resource()` calls.
- `rules/utils/id_convert.py`: Added `load_contrasts()` function to parse differential comparison pairs from `contrasts.csv`.
- `envs/deeptools.yaml` (124 lines refined): Added `deeptools` for coverage visualization and TSS enrichment analysis.
- `config/run_parameter.yaml`: Added `macs2_qvalue` and `macs2_genome_size` parameters.

---

### 2026-01-24

#### `61d2596` / `95692a9` / `e6575f5` - ATACFlow v0.0.3: Update Mapping & Bug Fixes

**Code Changes**:
- `rules/07.mapping.smk`: Added `samtools flagstat` and `samtools stats` generation for alignment QC. Fixed CRAM output path to `02.mapping/cram/{sample}.cram`.
- `rules/08.MACS2.smk`: Added `macs2 callpeak` support for both BAMPE and BAM formats based on config flag.
- `rules/09.MergeMACS2.smk`: Added IDR (Irreproducible Discovery Rate) analysis rule (`idr --samples`) for replicate peak consistency.
- `envs/bedtools.yaml`: Added `bedtools` and `ucsc-bedclip` for peak post-processing.
- `envs/deeptools.yaml`: Added `plotFingerprint`, `computeMatrix`, and `plotProfile` rules for TSS enrichment and FRiP analysis.
- `rules/01.common.smk`: Fixed `get_threads()` helper to respect cluster config overrides.

**Mapping Rule Enhancement**:
```snakemake
rule samtools_stats:
    input: bam="02.mapping/filter_pe/{sample}.filter_pe.sorted.bam"
    output: "02.mapping/samtools_stats/{sample}_bam_stats.tsv"
    shell: "samtools stats {input.bam} > {output}"
```

---

### 2026-01-25

#### `b0bfef7` - ATACFlow v0.0.3: Update DEG & Enrichment

**Scope**: Added differential accessibility analysis and functional enrichment.

**Code Changes**:
- `rules/12.DEG.smk` (71 lines added): Single-contrast differential peak analysis using `DESeq2` on consensus peak count matrix.
- `rules/12.DEG_MERGE.smk` (71 lines added): Multi-contrast merged differential analysis with PCA visualization.
- `envs/bedtools.yaml`: Added `bedtools multicov` for generating raw count matrices over consensus peaks.
- `rules/01.common.smk`: Added `ALL_CONTRASTS` and `CONTRAST_MAP` loading from `paired.csv`.
- `config/run_parameter.yaml`: Added `deg_padj_cutoff` and `deg_lfc_cutoff` parameters.
- `snakefile`: Added includes for `12.DEG.smk` and `12.DEG_MERGE.smk`.

---

### 2026-01-26

#### `54d359d` / `43e86eb` / `4cddeee` - ATACFlow v0.0.3: ATAC-Report & Enrichment Fixes

**Code Changes**:
- `rules/10.ATAC_QC.smk` (renamed from `10.ataqv.smk`): Expanded to include `ataqv`, `mosdepth`, and `preseq` QC metrics. Added MultiQC aggregation for all ATAC-seq specific reports.
- `rules/12.DEG.smk` / `rules/12.DEG_MERGE.smk`: Fixed `DESeq2` script paths. Corrected contrast name parsing from `treatment_vs_control` format.
- `rules/01.common.smk`: Added `report_data` dictionary structure for Quarto report generation.
- `rules/00.log.smk`: Reorganized logging structure to use rule-specific log directories.
- `rules/utils/id_convert.py`: Refactored `load_contrasts()` to handle missing contrast files gracefully.

---

### 2026-01-26

#### `b06f9a4` / `92e6e54` / `7ad7b69` - ATACFlow v0.0.3: README & QC Models

**Code Changes**:
- `README.md`: Added comprehensive usage documentation including:
  - Installation instructions
  - Configuration file explanations
  - Expected output directory structure
  - Troubleshooting guide
- `rules/01.common.smk`: Added `validate_genome_version()` call to ensure selected genome is in `can_use_genome_version` list.
- `rules/09.MergeMACS2.smk`: Fixed consensus peak merging to use `bedtools merge -d 100` (merge peaks within 100bp).
- `.gitignore`: Added `logs/` directory to ignore generated log files.

---

### 2026-03-12

#### `722c383` - ATACFlow v0.0.3: Fix Analysis Logic

**Scope**: Major refactor of the rule orchestration and file delivery logic.

**Code Changes**:
- `rules/utils/datadeliver.py` (334 lines added): **New core module**. Centralized the definition of all pipeline output files. Introduced `DataDeliver()` function that dynamically builds the Snakemake `rule all` input list based on enabled modules.
- `rules/01.common.smk` (223 lines changed): Removed inline data delivery logic. Delegated all target file definitions to `datadeliver.py`.
- `rules/00.log.smk`: Added centralized log directory creation (`logs/{rule_name}/`).
- `rules/03.file_convert_md5.smk` to `rules/16.Report.smk`: All rules updated to use new log paths and standardized output directories.
- `snakefile`: Simplified to:
  ```python
  include: 'rules/01.common.smk'
  # ... includes for all stages ...
  rule all:
      input: DataDeliver(config=config, samples=samples, merge_group=merge_group)
  ```
- `config/config.yaml`: Restructured to use nested module flags (`only_qc`, `mapping`, `peak_calling`, `deg`, etc.).

**Core Function Introduced**:
```python
def DataDeliver(config=None, samples=None, merge_group=False):
    config = config or {}
    samples = samples or {}
    data_deliver = [
        "01.qc/md5_check.tsv",
        os.path.join("00.raw_data", config.get("convert_md5", "md5_check")),
    ]
    if config.get("mapping") is not False:
        data_deliver.extend(expand("02.mapping/cram/{sample}.cram", sample=samples.keys()))
    if config.get("peak_calling") is not False:
        data_deliver.extend(expand("03.peak_calling/MACS2/{sample}/{sample}_peaks.narrowPeak", sample=samples.keys()))
    return data_deliver
```

---

### 2026-03-13

#### `80417ec` - ATACFlow v0.0.3: Add chromap.smk & Fix Pipeline Logic

**Scope**: Introduced Chromap as a second mapping engine alongside Bowtie2.

**Code Changes**:
- `rules/subrules/mapping/bowtie2.smk` (65 lines): Extracted Bowtie2 mapping logic from `06.mapping.smk` into a dedicated subrule file.
- `rules/subrules/mapping/chromap.smk` (57 lines): Added Chromap mapping support:
  ```snakemake
  rule chromap_mapping:
      input: r1="00.raw_data/{sample}_R1.fastq.gz", r2="00.raw_data/{sample}_R2.fastq.gz"
      output: bam="02.mapping/raw/{sample}.bam"
      params: index=config["chromap"]["index"]
      shell: "chromap --preset atac -x {params.index} -r {input.r1} -R {input.r2} -o {output.bam}"
  ```
- `rules/06.mapping.smk`: Refactored to conditionally include either `bowtie2.smk` or `chromap.smk` based on `config["mapping_tool"]`.
- `envs/chromap.yaml` (35 lines): Added Chromap-specific conda environment.
- `rules/utils/common.py` (268 lines added): Extracted shared helper functions (`ReportData`, `get_sample_data_dir`, `judge_bwa_index`, etc.) from `01.common.smk`.
- **File Renumbering**: All rules renamed to sequential numbering:
  - `03.file_convert_md5.smk` -> `02.file_convert_md5.smk`
  - `04.short_read_qc.smk` -> `03.short_read_qc.smk`
  - `05.Contamination_check.smk` -> `04.Contamination_check.smk`
  - ... through `16.Report.smk` -> `15.Report.smk`
- `snakefile`: Updated all `include:` statements to match new numbering.

---

### 2026-03-15

#### `9d43880` / `abc97e9` - ATACFlow v0.0.4: Fix Mapping, MACS2, MergeMACS2 & FeatureCounts

**Code Changes**:
- `rules/06.mapping.smk`: Added `samtools merge` logic for group-level BAM merging. Fixed CRAM conversion to use `samtools view -C -T {ref}`. Added `estimate_library_complexity` rule using Picard.
- `rules/07.MACS2.smk`: Added `homer_annotate_peaks` rule to annotate narrowPeaks with nearest genes. Fixed `macs2 callpeak` to use `-f BAMPE` explicitly for paired-end ATAC-seq.
- `rules/08.MergeMACS2.smk`: Added `featureCounts` integration to count reads in consensus peaks across all samples. Fixed consensus peak merging to handle single-sample groups.
- `rules/subrules/mapping/chromap.smk`: Updated Chromap parameters to use `--trim-adapters` and `--remove-pcr-duplicates`.
- `envs/chromap.yaml`: Trimmed redundant dependencies.
- `rules/04.Contamination_check.smk`: Added `fastq_screen` config parsing for multi-species screening.
- `rules/14.deliver.smk`: Updated delivery paths to match new output structure.
- `config/run_parameter.yaml`: Added `featureCounts` parameter block (`-p -B -C`).

**FeatureCounts Integration**:
```snakemake
rule count_peaks:
    input: bam=expand("02.mapping/filter_pe/{sample}.filter_pe.sorted.bam", sample=samples.keys()),
           peaks="04.consensus/all_samples_consensus_peaks.bed"
    output: "04.consensus/consensus_counts_matrix.txt"
    shell: "featureCounts -a {input.peaks} -o {output} -p -B -C {input.bam}"
```

---

### 2026-03-16

#### `181b56e` - ATACFlow v0.0.4: Fix Various Bugs

**Code Changes**:
- `rules/subrules/mapping/bowtie2.smk` / `chromap.smk`: Fixed index path resolution to use `config["bowtie2"][Genome_Version]["index"]` format.
- `rules/utils/common.py`: Added `ReportData()` function to collect all report-related files.
- `envs/subread.yaml`: New environment for `featureCounts`.
- `config/config.yaml`: Fixed default `workflow` path.
- `config/reference.yaml`: Corrected `STAR_index` and `bwa_mem2` paths for consistency.
- `config/run_parameter.yaml`: Fixed `threads` dictionary nesting.

#### `abe2173` - ATACFlow v0.0.4: Fix estimate_library_complexity Bug

**Code Changes**:
- `rules/06.mapping.smk`: Fixed Picard `EstimateLibraryComplexity` input/output paths. Changed from expecting `.bai` to generating it internally.
  ```diff
  - input: bam="02.mapping/gatk/{sample}/{sample}.rg.dedup.bam", bai="02.mapping/gatk/{sample}/{sample}.rg.dedup.bam.bai"
  + input: bam="02.mapping/gatk/{sample}/{sample}.rg.dedup.bam"
  + output: metrics="02.mapping/picard/{sample}_library_complexity.txt"
  ```

#### `dc1751c` / `9208f49` - ATACFlow v0.0.4: Fix Rule Threads

**Code Changes**:
- `rules/06.mapping.smk`: Fixed thread allocation for `samtools sort` to use `-@ {threads}`.
- `config/run_parameter.yaml`: Adjusted default threads for mapping (20), peak calling (10), and merging (8).

---

### 2026-03-17

#### `51762e4` - ATACFlow v0.0.4: Fix mark_duplicates Rules

**Code Changes**:
- `rules/06.mapping.smk`: Separated `MarkDuplicates` from `AddOrReplaceReadGroups`. Fixed GATK command to use `--CREATE_INDEX true` so `.bai` files are auto-generated.
  ```diff
  shell: "gatk MarkDuplicates -I {input.bam} -O {output.bam} -M {output.metrics} --CREATE_INDEX true"
  ```

#### `ac5da62` / `79375db` / `695712d` / `a2880a6` - ATACFlow v0.0.4: Fix atac_seq_shift & mark_duplicates Error

**Code Changes**:
- `rules/06.mapping.smk`: Iteratively fixed the `atac_seq_shift` rule. The original implementation used `alignmentSieve --ATACshift` but failed due to unsorted intermediate BAMs.
- Added explicit `samtools sort` after `alignmentSieve` and before `samtools index`.
- Fixed input dependencies so `mark_duplicates` correctly waits for `add_read_groups` to complete.
- Corrected intermediate file cleanup to prevent Snakemake from deleting files needed by downstream rules.

---

### 2026-03-19

#### `abf4516` - ATACFlow v0.0.4: Fix atac_seq_shift & mark_duplicates (Subrule Extraction)

**Scope**: Major refactor of mapping post-processing. Extracted shift and mark-duplicates into dedicated subrule files for both Bowtie2 and Chromap.

**Code Changes**:
- `rules/06.mapping.smk` (204 lines removed): Removed inline `atac_seq_shift`, `mark_duplicates`, and `add_read_groups` rules.
- `rules/subrules/mapping/bowtie2_mark_duplicates.smk` (61 lines added):
  ```snakemake
  rule add_read_groups_bowtie2:
      input: bam="02.mapping/raw/{sample}.bam"
      output: bam="02.mapping/gatk/{sample}/{sample}.rg.bam", bai="02.mapping/gatk/{sample}/{sample}.rg.bam.bai"
      shell: "gatk AddOrReplaceReadGroups -I {input.bam} -O {output.bam} -LB {wildcards.sample} -PU unit1 -SM {wildcards.sample} -PL ILLUMINA"
  
  rule mark_duplicates_bowtie2:
      input: bam="02.mapping/gatk/{sample}/{sample}.rg.bam", bai="02.mapping/gatk/{sample}/{sample}.rg.bam.bai"
      output: bam="02.mapping/gatk/{sample}/{sample}.rg.dedup.bam", bai="02.mapping/gatk/{sample}/{sample}.rg.dedup.bam.bai", metrics="02.mapping/gatk/{sample}/{sample}.metrics.txt"
      shell: "gatk MarkDuplicates -I {input.bam} -O {output.bam} -M {output.metrics} --CREATE_INDEX true --MAX_RECORDS_IN_RAM 5000000"
  ```
- `rules/subrules/mapping/bowtie2_shift.smk` (54 lines added):
  ```snakemake
  rule atac_seq_shift_bowtie2:
      input: bam="02.mapping/filter_pe/{sample}.filter_pe.sorted.bam", bai="02.mapping/filter_pe/{sample}.filter_pe.sorted.bam.bai"
      output: shifted_sort_bam="02.mapping/shifted/{sample}.shifted.sorted.bam", shifted_sort_bam_bai="02.mapping/shifted/{sample}.shifted.sorted.bam.bai"
      shell: "alignmentSieve -b {input.bam} -o /dev/stdout --ATACshift -p {threads} | samtools sort -@ {threads} -o {output.shifted_sort_bam} && samtools index {output.shifted_sort_bam}"
  ```
- `rules/subrules/mapping/chromap_mark_duplicates.smk` (56 lines added): Equivalent rules for Chromap.
- `rules/subrules/mapping/chromap_shift.smk` (45 lines added): Equivalent shift rule for Chromap.
- `config/run_parameter.yaml`: Added parameter blocks for `add_read_groups` and `mark_duplicates` Java options.
- `rules/09.ATAC_QC.smk`: Removed duplicate flagstat generation (now handled in mapping module).

#### `9a488d3` / `02fb949` - ATACFlow v0.0.4: Fix add_read_groups

**Code Changes**:
- `rules/06.mapping.smk`: Fixed read group `LB` (library) and `PU` (platform unit) extraction. Changed from hardcoded values to parsing from sample metadata.
- `rules/subrules/mapping/bowtie2_mark_duplicates.smk`: Added `--ASSUME_SORT_ORDER coordinate` to `MarkDuplicates` to prevent coordinate-sort validation errors.

#### `5cf647d` / `228d752` - ATACFlow v0.0.4: Clean Up estimate_library_complexity

**Code Changes**:
- `rules/06.mapping.smk`: Removed 48 lines of duplicate/commented `estimate_library_complexity` rules.
- `rules/09.ATAC_QC.smk`: Fixed MultiQC input paths to point to `05.ATAC_QC/` instead of old `10.ATAC_QC/`.
- `rules/utils/datadeliver.py`: Updated target paths for preseq outputs (later commented out).

---

### 2026-03-20

#### `9f57393` / `de88e5a` - ATACFlow v0.0.5: Fix Add Group Bug & Shift Bug

**Code Changes**:
- `rules/06.mapping.smk`: Fixed group-level BAM merging. The `samtools merge` wildcard expansion was incorrectly using `sample` instead of `group`.
  ```diff
  - input: lambda w: expand("02.mapping/filter_pe/{sample}.filter_pe.sorted.bam", sample=groups[w.sample])
  + input: lambda w: expand("02.mapping/filter_pe/{sample}.filter_pe.sorted.bam", sample=groups[w.group])
  ```
- `rules/07.MACS2.smk`: Fixed peak calling input to use shifted BAMs instead of raw filtered BAMs.
- `rules/08.MergeMACS2.smk`: Fixed consensus peak input paths after directory reorganization.
- `rules/subrules/mapping/chromap_mark_duplicates.smk`: Fixed read group `SM` field to use `wildcards.sample`.
- `config/cluster_config.yaml`: Adjusted memory limits for mapping rules on cluster profiles.
- `config/run_parameter.yaml`: Added `shift_threads` parameter.
- `config/config.yaml`: Fixed default `mapping_tool` value to `"bowtie2"`.

#### `8455e19` - ATACFlow v0.0.5: Fix Resource Manager Modules

**Code Changes**:
- `rules/utils/resource_manager.py`: Added `skip_queue_on_local` parameter support. Fixed local execution mode to bypass cluster queue directives.
  ```python
  def rule_resource(config, profile, skip_queue_on_local=False, logger=None):
      resources = config["cluster_config"][profile].copy()
      if skip_queue_on_local and config.get("execution_mode") == "local":
          resources.pop("queue", None)
      return resources
  ```
- `rules/06.mapping.smk`: Added `skip_queue_on_local=True` to all mapping subrules.
- `config/cluster_config.yaml`: Restructured resource profiles (`low_resource`, `medium_resource`, `high_resource`).

#### `4d8480f` - ATACFlow v0.0.5: Add Resource & Threads

**Code Changes**:
- Applied explicit `threads` and `resources` directives across all pipeline rules:
  - `rules/04.Contamination_check.smk`: `threads: config['parameter']['threads']['fastq_screen']`
  - `rules/06.mapping.smk`: `threads: config['parameter']['threads']['mapping']`
  - `rules/07.MACS2.smk`: `threads: config['parameter']['threads']['macs2']`
  - `rules/08.MergeMACS2.smk`: `threads: 4`
  - `rules/09.ATAC_QC.smk`: `threads: config['parameter']['threads']['atac_qc']`
  - `rules/10.DEG.smk`: `threads: config['parameter']['threads']['deg']`
  - `rules/11.DEG_MERGE.smk`: `threads: config['parameter']['threads']['deg_merge']`
  - `rules/12.motifs.smk`: Added resource profiles for HOMER (medium) and TOBIAS (high).
  - `rules/15.Report.smk`: `threads: 2`
  - `rules/subrules/mapping/bowtie2_shift.smk` / `chromap_shift.smk`: Added `threads: 20`

#### `13dce5a` - ATACFlow v0.0.5: Add validate_species Functions

**Code Changes**:
- `rules/utils/validate.py` (+47 lines): Added `validate_species()` function that cross-references `config["species"]` against a whitelist derived from `config["can_use_species"]`.
  ```python
  def validate_species(config, logger):
      species = config.get("species")
      allowed = config.get("can_use_species", [])
      if species not in allowed:
          raise ValueError(f"Species '{species}' not supported. Allowed: {allowed}")
  ```
- `snakefile`: Added `validate_species(config=config, logger=logger)` call after genome validation.
- `rules/01.common.smk`: Removed old inline species check.
- `rules/07.MACS2.smk` / `08.MergeMACS2.smk`: Removed redundant species validation in individual rules.

#### `24b2427` - ATACFlow v0.0.5: Update src Scripts

**Code Changes**:
- `envs/idr.yaml` (85 lines added): Added IDR (Irreproducible Discovery Rate) environment.
- `rules/08.MergeMACS2.smk`: Added `idr_analysis` rule for replicate peak consistency scoring.
- `rules/utils/validate.py`: Refactored error messages to use `logger.error()` instead of `print()` for consistent logging.
- `config/run_parameter.yaml`: Added `idr_threshold` and `idr_ranking` parameters.
- `src` submodule: Updated to latest commit with fixed R scripts.

#### `a702de6` - ATACFlow v0.0.5: Fix macs2 Call Peaks Logic

**Code Changes**:
- `rules/07.MACS2.smk`: Fixed `macs2 callpeak` input to explicitly require `.bai` index files to prevent race conditions.
- `rules/08.MergeMACS2.smk`: Added pooled peak calling on merged BAMs. Added `homer_annotate_peaks` for pooled peaks. Added `create_consensus_peakset` with automatic fallback to single-sample peaks when replicates are missing.
- `rules/utils/datadeliver.py`: Added delivery targets for pooled peaks and IDR outputs.

#### `a441f47` - ATACFlow v0.0.5: Peak Calling Workflow & Configuration Optimization

**Scope**: Largest refactor of the peak calling architecture.

**Code Changes**:
- `config/config.yaml`: Added `peak_calling.use_pooled_peaks: True` flag.
- `rules/07.MACS2.smk` (175 lines changed): Restructured into single-sample-only peak calling:
  - Output moved to `03.peak_calling/single/{sample}/`
  - Added `create_consensus_peakset` rule to generate `04.consensus/single/all_samples_consensus_peaks.bed`
  - Added FRiP calculation: `bedtools intersect -a {bam} -b {peaks} | wc -l` -> `{sample}_frip.txt`
- `rules/08.MergeMACS2.smk` (511 lines changed): Separated pooled and IDR analyses:
  - `pooled_peak_calling`: `03.peak_calling/pooled/{group}/`
  - `idr_analysis`: `03.peak_calling/idr/{group}/`
  - `create_pooled_consensus`: `04.consensus/pooled/`
- `rules/09.ATAC_QC.smk`: Updated MultiQC inputs to match new `single/` and `pooled/` directory structures.
- `rules/10.DEG.smk` / `11.DEG_MERGE.smk`: Dynamic selection of consensus matrix:
  ```python
  input: counts=lambda w: get_diff_analysis_input(config, merge_group)
  ```
- `rules/12.motifs.smk`: Updated motif input to use pooled consensus when available.
- `rules/utils/datadeliver.py`: Added `get_diff_analysis_input()` and `should_run_pooled_analysis()` helper functions.
- `rules/utils/common.py`: Updated `DataDeliver()` to accept `run_pooled` parameter and route to `merge_group_analysis()`.
- `snakefile`: Added `run_pooled = config['peak_calling']['use_pooled_peaks'] and merge_group` logic.

**New Helper Functions**:
```python
def get_diff_analysis_input(config, merge_group):
    use_pooled = config.get("peak_calling", {}).get("use_pooled_peaks", True)
    if use_pooled and merge_group:
        return "04.consensus/pooled/consensus_counts_matrix_ann.txt"
    return "04.consensus/single/consensus_counts_matrix_ann.txt"

def should_run_pooled_analysis(config, merge_group):
    return config.get("peak_calling", {}).get("use_pooled_peaks", True) and merge_group
```

#### `c547733` - ATACFlow v0.0.5: Update README Configuration Documentation

**Code Changes**:
- `README.md` (+88 lines): Added detailed explanations for:
  - `peak_calling.use_pooled_peaks`
  - `only_qc` mode
  - `mapping_tool` selection (`bowtie2` vs `chromap`)
  - Expected output directory tree

#### `b955996` - ATACFlow v0.0.5: Fix validate_species Bug

**Code Changes**:
- `rules/utils/validate.py`: Fixed `validate_species()` to handle lowercase/uppercase species name normalization. One-line fix: added `.lower()` to comparison.

#### `9676dd5` / `6d812d9` - ATACFlow v0.0.5: Fix run_pooled

**Code Changes**:
- `snakefile`:
  ```diff
  - run_pooled = config['peak_calling']['use_pooled_peaks']
  + run_pooled = config['peak_calling']['use_pooled_peaks'] and merge_group
  ```
- `rules/utils/common.py`: Fixed critical bug where `DataDeliver()` was mutating the global `config` dictionary. Previously, the loop did `config[module] = True`, causing side effects. Refactored to use a local `run_modules` dict.
  ```python
  # Before (buggy):
  for module in basic_modules:
      if config.get(module) is not False:
          config[module] = True  # MUTATES GLOBAL CONFIG
  
  # After (fixed):
  run_modules = {}
  for module in basic_modules:
      run_modules[module] = config.get(module) is not False
  ```
- `snakefile`: Added `config['_merge_group'] = merge_group` and `config['_run_pooled'] = run_pooled` for downstream rule access.

---

### 2026-03-21

#### `7b94148` / `962a026` - ATACFlow v0.0.5: Fix idr_analysis Bug

**Code Changes**:
- `rules/08.MergeMACS2.smk`: Fixed `idr_analysis` rule output declaration. Removed a dynamic `lambda wildcards` output that caused Snakemake DAG resolution failures.
  ```diff
  output:
      idr_bed = "03.peak_calling/idr/{group}/Final_Consensus_Peaks.bed",
      idr_log = "03.peak_calling/idr/{group}/idr_pipeline.log",
  -     idr_peaks = lambda wildcards: expand("03.peak_calling/idr/{group}/{sample}_peaks.idr.narrowPeak", sample=groups[wildcards.group])
  ```
- `snakefile`: Removed redundant `config['idr_analysis'] = True` assignment (was unnecessary since IDR is part of pooled analysis).

---

### 2026-03-22

#### `01193e2` / `a145a38` / `6ce3118` - ATACFlow v0.0.5: README Documentation Improvements

**Code Changes**:
- `README.md` (+226 lines): Added Mermaid workflow diagram showing the complete pipeline:
  ```mermaid
  graph TD
      A[Raw FASTQ] --> B[FastQC]
      B --> C[fastp Trim]
      C --> D[Bowtie2/Chromap Map]
      D --> E[Shift & Mark Duplicates]
      E --> F[MACS2 Peak Calling]
      F --> G[Consensus Peaks]
      G --> H[DESeq2 Differential]
      H --> I[HOMER/TOBIAS Motifs]
      I --> J[Quarto Report]
  ```
- Added Chinese README (`docs/README_CN.md`) in subsequent merge.
- `src` submodule: Updated to latest documentation-compatible version.

#### `d573901` / `332f7b4` / `0211ead` - ATACFlow v0.0.5: Fix Mermaid Diagram Syntax

**Code Changes**:
- `README.md`: Fixed Mermaid syntax errors (missing closing brackets, invalid node labels). Multiple iterations to ensure GitHub rendering compatibility.

---

### 2026-03-23

#### `627b23e` / `da1cf9e` / `d0c7e75` / `210e05d` - ATACFlow: AI Skills & Sample Format Fixes

**Code Changes**:
- `skills/SKILL.md` (415 lines added): Comprehensive skill documentation for AI agents (Kimi/Claude/Codex) covering:
  - ATAC-seq background and biological interpretation
  - Step-by-step ATACFlow usage instructions
  - Expected QC thresholds (TSS enrichment > 6, FRiP > 0.1)
  - Troubleshooting common failures
- `skills/examples/config_complete.yaml`, `config_standard.yaml`, `config_qc_only.yaml`: Added ready-to-use configuration templates.
- `skills/examples/run_atacflow.sh`, `start_atacflow.sh`: Added helper shell scripts.
- `skills/examples/samples.csv`: Fixed CSV format (removed extra whitespace, standardized headers to `sample,sample_name,group`).
- `README.md`: Added "AI Skills" section with installation instructions.
- `config.yaml` / `skills/examples/*.yaml`: Fixed species names to use underscores instead of spaces (`homo_sapiens` instead of `homo sapiens`).

---

### 2026-03-24

#### `97d32ac` - ATACFlow v0.0.5: ADD MCP (Initial)

**Scope**: First introduction of the Model Context Protocol (MCP) server for AI-driven pipeline interaction.

**Code Changes**:
- `mcp/server.py` (413 lines added): Initial FastMCP server with tools:
  - `list_supported_genomes()`
  - `generate_config_file()`
  - `create_sample_csv()`
  - `run_atacflow()` (basic synchronous version)
- `mcp/main.py` (6 lines): Entry point wrapper.
- `mcp/mcp_config.yaml`: Server configuration with conda/snakemake paths.
- `mcp/pyproject.toml`: Project metadata and dependencies (`fastmcp`, `pydantic`, `pyyaml`).
- `mcp/requirements.txt`: Pip-compatible dependency list.
- `mcp/test_mcp.py`: Basic client test script.
- `mcp/uv.lock`: uv lockfile for reproducible installation.
- `mcp/README.md`: Initial MCP documentation.

#### `018cf5f` / `958c7e1` / `6751b05` - RNAFlow v0.1.9 / ATACFlow: Add Lsat_Salinas_v11_wx

**Code Changes**:
- `config/reference.yaml`: Added lettuce genome `Lsat_Salinas_v11_wx` reference paths (genome FASTA, GTF, gene BED, bowtie2 index).
- `schema/config.schema.yaml`: Added `Lsat_Salinas_v11_wx` to allowed genome versions.
- `rules/utils/common.py`: Updated `DataDeliver()` to support additional genome versions (no functional change, just comment).
- Deleted `Reference_README.md` (386 lines removed) in favor of inline README documentation.

#### `ecdbb01` - ATACFlow v0.0.5: Fix UPDATE SRC

**Code Changes**:
- `src` submodule: Bumped to latest commit containing fixed R visualization scripts for DEG results.

#### `cbb784e` - ATACFlow: Add Dual-Mode Support (Local stdio + Remote)

**Code Changes**:
- `mcp/pyproject.toml`: Added `mcp` CLI entry point.
- `mcp/mcp_config.yaml`: Added `mode` setting (`stdio` vs `sse`).
- `mcp/start.sh` (47 lines added): Deployment startup script with environment activation and port configuration.
- `mcp/TEST_AND_DEPLOY.md` (131 lines added): Deployment guide for remote servers.
- `mcp/README.md`: Documented dual-mode architecture and remote deployment options.

#### `b13639a` - ATACFlow: Update README with Complete Documentation

**Code Changes**:
- `mcp/README.md` (+108 lines): Added API reference for all MCP tools, configuration examples, and troubleshooting.

---

### 2026-03-25

#### `5c803a7` / `bc610f9` / `90d7bb5` - ATACFlow v0.0.5: MCP Server Feature Completeness

**Scope**: MCP server matured with monitoring, logging, and database support.

**Code Changes**:
- `mcp/server.py` (981 lines changed): Massive expansion with new tools:
  - `check_system_resources()` - CPU, memory, disk monitoring
  - `list_runs()`, `get_run_details()`, `get_run_statistics()` - SQLite-backed run tracking
  - `check_project_name_conflict()` - Prevents duplicate project names
  - `check_snakemake_status()`, `get_snakemake_log()` - Live pipeline monitoring
- `.gitignore`: Added `mcp/logs/`, `mcp/.db/`, and `mcp/.venv/`.
- `config/reference.yaml`: Added `mcp_genome_version` section for MCP tool usage.
- `mcp/REMOTE_DEPLOYMENT.md` (152 lines): Remote server deployment guide.
- `README.md`: Added MCP server section in root documentation.

#### `4c17636` - ATACFlow v0.0.5: ADD MCP (Docs)

**Code Changes**:
- `docs/README_CN.md` (812 lines added): Complete Chinese translation of the README.

#### `18f0c96` - ATACFlow v0.0.5: ADD MCP (Config Integration)

**Code Changes**:
- `.gitignore`: Added `mcp/*.db` and `mcp/__pycache__/`.
- `config/reference.yaml`: Added `mcp_genome_version` list for genome support in MCP.
- `src` submodule: Updated to latest.

#### `05d1b2e` - ATACFlow: Update mcp/README.md (uv Instructions)

**Code Changes**:
- `mcp/README.md`: Added detailed `uv` installation and usage instructions for server deployment.

#### `b4ad08a` - ATACFlow v0.0.5: Refactor MCP to Modular Architecture

**Scope**: Major architectural refactor of the MCP server from monolithic `server.py` to layered modules.

**Code Changes**:
- `mcp/core/config.py` (41 lines): Centralized path constants (`ATACFLOW_ROOT`, `MCP_CONFIG_FILE`).
- `mcp/core/logger.py` (52 lines): Structured logging with `loguru`, outputting to `mcp/logs/`.
- `mcp/db/database.py` (57 lines): SQLite schema definition for run records.
- `mcp/db/crud.py` (188 lines): Database CRUD operations (`record_run_start`, `update_run_status`, `get_run_info`).
- `mcp/models/schemas.py` (143 lines): Pydantic models for `ProjectConfig`, `SampleRecord`, `RunRecord`.
- `mcp/services/project_mgr.py` (434 lines): Project setup services (`create_project_structure`, `setup_complete_project`, `validate_config`).
- `mcp/services/snakemake.py` (228 lines): Snakemake execution service with async subprocess support.
- `mcp/services/system.py` (317 lines): System monitoring services.
- `mcp/main.py` (554 lines added): Clean entry point registering all tools/resources with `FastMCP`.
- `mcp/docs/`: Archived old files (`server.py.old`, `test_mcp.py`, `requirements.txt`, `REMOTE_DEPLOYMENT.md`, `TEST_AND_DEPLOY.md`).
- `mcp/start.sh`: Updated to point to new `main.py` entry point.

---

### 2026-03-27

#### `6052523` / `aea4f7a` - ATACFlow v0.0.5: ADD Lsat_Salinas_v8_wx Genome

**Code Changes**:
- `config/reference.yaml`: Added `Lsat_Salinas_v8_wx` lettuce genome reference configuration with paths for:
  - Genome FASTA
  - Gene annotation GTF/GFF
  - Bowtie2 index
  - Blacklist BED
  - Effective genome size for MACS2
- `schema/config.schema.yaml`: Added `Lsat_Salinas_v8_wx` to validated genome versions.
- `src` submodule: Updated to include lettuce-specific report templates.

---

### 2026-03-28

#### `a1d00be` - ATACFlow v0.0.5: Add & Fix MCP

**Scope**: Bug fixes and optimizations for the modular MCP architecture.

**Code Changes**:
- `mcp/core/legacy_dispatcher.py` (72 lines added): Added backward-compatibility layer to map legacy tool names to new functions.
- `mcp/core/middleware.py` (70 lines added): Request/response middleware for error handling and logging.
- `mcp/core/response.py` (42 lines added): Standardized JSON response formatting.
- `mcp/db/session.py` (35 lines added): Lazy database initialization to avoid creating DB files on import.
- `mcp/main.py` (656 lines changed):
  - Fixed async bug in backward-compatibility tools
  - Added legacy dispatcher to reduce visible tool count
  - Wrapped blocking operations in `asyncio.get_event_loop().run_in_executor()`
- `mcp/services/snakemake.py` (55 lines changed): Added async safety and 60-second timeout for dry-run validation.
- `mcp/OPTIMIZATION_CHANGES.md` (326 lines): Documented P0/P1 optimizations.
- `mcp/OPTIMIZATION_SUMMARY.md` (361 lines): High-level summary of performance improvements.

**Key Async Safety Fix**:
```python
# Before: blocking call in async tool
@mcp.tool()
async def run_atacflow_tool(...):
    return run_atacflow(...)  # BLOCKS EVENT LOOP

# After: executor isolation
@mcp.tool()
async def run_atacflow_tool(...):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_atacflow, ...)
```

---

### 2026-04-02

#### `b66f320` - ATACFlow v0.0.5: Add container_env

**Code Changes**:
- `.gitmodules`: Added `container_env` submodule pointing to `Flowcontainer` repository.
- `container_env/`: Initialized submodule containing:
  - `Flowcontainer/builder.py` - Dockerfile generation for pipeline dependencies
  - `Flowcontainer/cli.py` - Container build CLI
  - `Flowcontainer/docker_client.py` - Docker/Singularity abstraction layer
  - `Flowcontainer/templates/` - Base container templates for conda/mamba environments
- Enables containerized execution of the ATACFlow pipeline.

---

### 2026-04-13

#### `9745a44` - ATACFlow v0.0.5: Update Bowtie2_mapping Rules

**Scope**: Stability improvements for Bowtie2 mapping output and logging.

**Code Changes**:
- `rules/subrules/mapping/bowtie2.smk`:
  ```diff
  - log: "logs/02.mapping/Bowtie2_{sample}.log"
  + log:
  +     stats = "logs/02.mapping/Bowtie2_{sample}.stats.log",
  +     err = "logs/02.mapping/Bowtie2_{sample}.err.log"
  
  - shell: "( ulimit -n 65535 && bowtie2 -p {threads} ... | samtools view -bS - > {output.bam} ) &> {log}"
  + shell: """
  +     ulimit -n 65535 2>/dev/null || true
  +     bowtie2 -p {threads} -X 2000 --very-sensitive --no-mixed --no-discordant \
  +         -x {params.index} -1 {input.r1} -2 {input.r2} 2> {log.stats} | \
  +     samtools view -b - > {output.bam} 2> {log.err}
  +     """
  ```
  - Split logging into separate `stats` (bowtie2 alignment metrics) and `err` (samtools errors) files.
  - Removed subshell `(...)` in favor of direct pipe execution for better error propagation.
  - Added `ulimit` failure tolerance (`2>/dev/null || true`).
- `src` submodule: Updated to latest commit.

---

### 2026-04-13 (Working Directory / Uncommitted)

#### Chromap Mapping: Real Processing Implementation (WIP)

**Scope**: The Chromap mapping branch was previously using symbolic links as placeholders for `mark_duplicates` and `atac_seq_shift`. This WIP change replaces placeholders with real tool execution, achieving parity with the Bowtie2 branch.

**Code Changes in Working Directory**:

1. **`rules/subrules/mapping/chromap_mark_duplicates.smk`**:
   ```diff
   - resources: **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger)
   + resources: **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger)
   + conda: workflow.source_path("../envs/gatk.yaml")
   - threads: 1
   + threads: 2
   - shell: "ln -s -r {input.bam} {output.bam} && ln -s -r {input.bai} {output.bai}"
   + shell: """
   +     gatk --java-options "{params.java_opts}" MarkDuplicates \
   +         -I {input.bam} -O {output.bam} -M {output.metrics} \
   +         --CREATE_INDEX true --MAX_RECORDS_IN_RAM 5000000 \
   +         --SORTING_COLLECTION_SIZE_RATIO 0.5 2>> {log}
   +     """
   ```

2. **`rules/subrules/mapping/chromap_shift.smk`**:
   ```diff
   + output:
   +     shifted_bam = '02.mapping/shifted/{sample}.shifted.bam',
         shifted_sort_bam = '02.mapping/shifted/{sample}.shifted.sorted.bam',
       shifted_sort_bam_bai = '02.mapping/shifted/{sample}.shifted.sorted.bam.bai'
   - resources: **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger)
   + resources: **rule_resource(config, 'high_resource', skip_queue_on_local=True, logger=logger)
   + conda: workflow.source_path("../envs/deeptools.yaml")
   - threads: 1
   + threads: 20
   - shell: "(ln -s -r {input.bam} {output.shifted_sort_bam} && ln -s -r {input.bai} {output.shifted_sort_bam_bai}) &> {log}"
   + shell: """
   +     alignmentSieve -b {input.bam} -o {output.shifted_bam} --ATACshift -p {threads} 2>> {log}
   +     samtools sort -@ {threads} {output.shifted_bam} -o {output.shifted_sort_bam} 2>> {log}
   +     samtools index {output.shifted_sort_bam} 2>> {log}
   +     """
   ```

**Observation**: This change finalizes the Chromap execution path. Both mapping engines (Bowtie2 and Chromap) now perform identical downstream processing: add read groups -> mark duplicates -> filter -> ATAC shift -> sort -> index.

---

### 2026-04-15 (Current Session)

#### `rules/utils/common.py` - DataDeliver Core Function Refactor

**Scope**: Modernized the pipeline's central orchestrator function `DataDeliver()`.

**Code Changes**:
- Removed global state variable `_qc_warning_logged` in favor of a function attribute (`DataDeliver._qc_warning_logged`) to avoid module-level mutable state.
- Added explicit module dependency validation (`MODULE_DEPENDENCIES`) with auto-enabling of upstream modules:
  ```python
  MODULE_DEPENDENCIES = {
      "peak_calling": ["mapping"],
      "motif_analysis": ["peak_calling"],
      "consensus_peaks": ["peak_calling"],
      "diff_peaks": ["consensus_peaks"],
      "atac_qc": ["mapping"],
  }
  ```
- Unified module function invocation using `functools.partial` to pre-bind `config` and `run_pooled` parameters, eliminating the special-case `if module == "mapping"` branch.
  ```python
  module_functions = {
      "qc_clean": qc_clean,
      "mapping": partial(mapping, config=config),
      "peak_calling": peak_calling,
      "motif_analysis": motif_analysis,
      "consensus_peaks": consensus_peaks,
      "diff_peaks": partial(diff_peaks, run_pooled=run_pooled),
      "atac_qc": partial(atac_qc, run_pooled=run_pooled),
  }
  for module, func in module_functions.items():
      if run_modules.get(module):
          data_deliver = func(samples, data_deliver)
  ```

---

## Long-Unmodified Core Components (Compatibility Risk Alert)

The following files are central to the pipeline but have not been functionally modified since the dates shown. Future changes must ensure backward compatibility:

| File | Last Modified | Role | Risk Factor |
|------|---------------|------|-------------|
| `rules/utils/reference_update.py` | 2026-01-22 | Resolves relative reference paths to absolute paths | Any new genome version must follow the expected YAML nesting |
| `rules/utils/id_convert.py` | 2026-01-26 | Parses `samples.csv` and `contrasts.csv` into Python dicts | Changes to CSV column requirements (e.g., adding `batch`) require updates here |
| `rules/02.file_convert_md5.smk` | 2026-03-13 | Validates raw data integrity via MD5 | Delivery path changes may break the checksum output location |
| `rules/03.short_read_qc.smk` | 2026-03-13 | Runs FastQC on raw reads | New QC parameters (e.g., adapter sequence lists) are not auto-propagated |
| `rules/05.short_read_clean.smk` | 2026-03-13 | fastp trimming and cleaning | Output naming convention is tightly coupled to mapping input expectations |
| `rules/13.Merge_qc.smk` | 2026-03-13 | Aggregates all QC reports with MultiQC | Must be manually updated when new QC stages are added |

---

## Version Timeline

```
2026-01-21  v0.0.1  Initial analysis rules (mapping, MACS2, basic config)
2026-01-22  v0.0.1  Environment setup (conda envs for all tools)
2026-01-22  v0.0.2  Group analysis logic (pooled BAMs, ataqv)
2026-01-22  v0.0.3  Motif analysis (HOMER, TOBIAS)
2026-01-23  v0.0.3  MACS2 & HOMER bug fixes
2026-01-24  v0.0.3  Mapping enhancements (flagstat, CRAM, IDR prep)
2026-01-25  v0.0.3  DEG & enrichment modules (DESeq2)
2026-01-26  v0.0.3  ATAC-report modules & enrichment fixes
2026-03-12  v0.0.3  Analysis logic fix (introduced datadeliver.py)
2026-03-13  v0.0.3  Chromap support & rule renumbering
2026-03-15  v0.0.4  Mapping/MACS2/MergeMACS2 fixes + featureCounts
2026-03-16  v0.0.4  Bug fixes (library complexity, threads)
2026-03-17  v0.0.4  mark_duplicates & atac_seq_shift fixes
2026-03-19  v0.0.4  Extracted mapping subrules (bowtie2/chromap)
2026-03-20  v0.0.5  Group bug fix, species validation, resource manager fixes
2026-03-20  v0.0.5  Peak Calling major refactor (single/pooled/IDR)
2026-03-20  v0.0.5  run_pooled logic fix (prevent config mutation)
2026-03-21  v0.0.5  IDR analysis bug fix (removed lambda output)
2026-03-22  v0.0.5  README & Mermaid documentation
2026-03-23  v0.0.5  AI Skills for agents
2026-03-24  v0.0.5  MCP server initial release
2026-03-25  v0.0.5  MCP modular architecture refactor
2026-03-27  v0.0.5  Lsat_Salinas_v8_wx genome support
2026-03-28  v0.0.5  MCP async safety & optimization fixes
2026-04-02  v0.0.5  Container environment support
2026-04-13  v0.0.5  Bowtie2 logging upgrade / Chromap real processing (WIP)
2026-04-15  v0.0.5  DataDeliver core function refactor
```

---

*Log generated from git history analysis. All code snippets are condensed representations of actual diffs.*
