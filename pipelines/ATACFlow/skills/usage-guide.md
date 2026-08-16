# ATACFlow Usage Guide

## Overview

This guide helps you use ATACFlow - a complete Snakemake-based ATAC-seq analysis pipeline that takes you from raw FASTQ files to interactive HTML reports with chromatin accessibility analysis.

## Prerequisites

```bash
# Install Snakemake and Mamba
conda install -c conda-forge -c bioconda snakemake mamba

# Optional: Install enhanced logger plugin for monitoring
pip install snakemake_logger_plugin_rich_loguru==0.1.4

# Clone ATACFlow repository
git clone --recurse-submodules git@github.com:xsx123123/ATACFlow.git
cd ATACFlow
```

## Quick Start

Tell your AI agent what you want to do:
- "Run a complete ATAC-seq analysis with ATACFlow on my FASTQ files"
- "Set up ATACFlow for my project with 2 control and 2 treated samples"
- "Use Chromap for fast mapping with ATACFlow"

## Example Prompts

### Starting from Scratch
> "I have raw ATAC-seq FASTQ files for human, help me set up and run ATACFlow"

> "Create a complete ATACFlow configuration for my mouse ATAC-seq experiment"

> "Run ATACFlow with all modules enabled including TOBIAS footprinting"

### Customizing the Analysis
> "Run ATACFlow but use Bowtie2 instead of Chromap for better compatibility"

> "Use ATACFlow in QC-only mode to quickly check my data quality"

> "Configure ATACFlow to use single sample consensus peaks instead of pooled"

### Cluster Execution
> "Configure ATACFlow to run on our Slurm cluster"

> "Set up cluster resource allocation for ATACFlow jobs"

## Input Requirements

| Input | Format | Description | Required |
|-------|--------|-------------|----------|
| FASTQ files | .fastq.gz | Raw sequencing reads (paired-end) | Yes |
| config.yaml | YAML | Project configuration | Yes |
| samples.csv | CSV | Sample metadata (sample, sample_name, group) | Yes |
| contrasts.csv | CSV | DEG contrasts (contrast, treatment) | For diff_peaks |
| Reference genome | FASTA+GTF | Indexed reference | Pre-configured |

## Project Structure

ATACFlow recommends this 3-tier directory structure:

```
Project_Root/
├── 00.raw_data/             # Raw FASTQ files (read-only)
├── 01.workflow/             # Working directory for analysis
│   ├── config.yaml          # Project config
│   ├── samples.csv          # Sample info
│   ├── contrasts.csv        # DEG contrasts
│   ├── 01.qc/              # Intermediate QC files
│   ├── 02.mapping/         # Intermediate mapping files
│   ├── 03.peak_calling/    # Intermediate peak files
│   ├── logs/               # Log files
│   └── benchmarks/         # Resource usage stats
└── 02.data_deliver/        # Final results (auto-generated)
```

## Configuration Options

### Basic Configuration (config.yaml)

```yaml
project_name: 'MyProject'
Genome_Version: "hg38"
species: 'Homo_sapiens'
client: 'MyLab'

raw_data_path:
  - /path/to/00.raw_data
sample_csv: /path/to/01.workflow/samples.csv
paired_csv: /path/to/01.workflow/contrasts.csv
workflow: /path/to/01.workflow
data_deliver: /path/to/02.data_deliver

execution_mode: local
mapping_tools: chromap  # or bowtie2
Library_Types: fr-firststrand
```

### Module Switches

All switches use snake_case naming:

| Module | Default | Description |
|--------|---------|-------------|
| only_qc | false | Only run QC and mapping |
| diff_peaks | true | Differential peak analysis with DESeq2 |
| fastq_screen | true | Contamination detection |
| report | true | Generate HTML report |

### Peak Calling Configuration

```yaml
peak_calling:
  use_pooled_peaks: true  # Use group-pooled peaks (recommended)
```

| Configuration | Description |
|---------------|-------------|
| use_pooled_peaks: true | Merge replicates within groups before peak calling (better sensitivity) |
| use_pooled_peaks: false | Use single sample consensus peaks |

### Mapping Tools

| Mapping Tool | Description |
|--------------|-------------|
| chromap | Fast, optimized for ATAC-seq (default, 2-5x faster) |
| bowtie2 | Classic, well-tested, more parameter control |

## Supported Genomes

ATACFlow comes pre-configured for:

- **Lsat_Salinas_v8/v11** - Lettuce
- **ITAG4.1** - Tomato
- **GRCm39** - Mouse
- **TAIR10.1** - Arabidopsis
- **hg38** - Human

Add new genomes in `config/reference.yaml`.

## Typical Workflow

### 1. Set up Project

```bash
# Create directory structure
mkdir -p MyProject/{00.raw_data,01.workflow,02.data_deliver}

# Link or copy FASTQ files
cp /path/to/your/*.fastq.gz MyProject/00.raw_data/
```

### 2. Create Metadata Files

**samples.csv:**
```csv
sample,sample_name,group
Sample1_R1,Sample1,Control
Sample2_R1,Sample2,Control
Sample3_R1,Sample3,Treatment
Sample4_R1,Sample4,Treatment
```

**contrasts.csv:**
```csv
contrast,treatment
Control,Treatment
```

### 3. Create config.yaml

Copy a template from ATACFlow and customize.

### 4. Dry Run

```bash
cd ATACFlow
snakemake -n --config analysisyaml=/path/to/config.yaml
```

### 5. Run Analysis

```bash
snakemake \
    --cores=60 \
    -p \
    --conda-frontend=mamba \
    --use-conda \
    --rerun-triggers mtime \
    --logger rich-loguru \
    --config analysisyaml=/path/to/config.yaml
```

### 6. View Results

Open the MultiQC reports in `01.qc/` or `05.ATAC_QC/` and the final report in `report/`.

## Choosing Analysis Modules

### Scenario 1: Quick Quality Check

```yaml
only_qc: true
```
- Runs: QC, trimming, mapping, basic filtering
- Skips: Peak calling, differential analysis, etc.
- Use for: Data screening, quality assessment

### Scenario 2: Standard Analysis

```yaml
only_qc: false
diff_peaks: true
fastq_screen: true
report: true
peak_calling:
  use_pooled_peaks: true
```
- Focuses on: Peak calling and differential analysis
- Use for: Routine chromatin accessibility studies

### Scenario 3: Comprehensive Analysis with TOBIAS

```yaml
only_qc: false
diff_peaks: true
fastq_screen: true
report: true
peak_calling:
  use_pooled_peaks: true
```
- Runs: All modules including TOBIAS footprinting
- Use for: Deep chromatin analysis with TF footprinting

## Output Interpretation

### Key Output Files

| Location | Content |
|----------|---------|
| 01_QC/ | MultiQC report, fastp HTMLs |
| 02_Mapping/ | Mapping logs, ataqv reports |
| 03_Peak_Calling/ | MACS2 peaks, IDR results |
| 04_Consensus/ | Consensus peak sets and count matrices |
| 06_DEG_Enrich/ | Differential peaks, volcano plots, GO/KEGG |
| 06_Motif_Analysis/ | TOBIAS footprinting results |
| report/ | Final HTML report |

### Key QC Metrics

| Metric | Good Value | Description |
|--------|------------|-------------|
| Mapping Rate | >70% | Percentage of reads mapped to genome |
| TSS Enrichment | >5 | Enrichment of reads at transcription start sites |
| FRiP | >10% | Fraction of reads in peaks |
| Mitochondrial Reads | <30% (varies by species) | Reads mapping to mitochondria/chloroplasts |

## Tips for Success

1. **Replicates**: Use at least 2 biological replicates per condition (3+ preferred)
2. **Sequencing Depth**: 20-50M reads per sample for standard analysis
3. **Mapping Tool**: Use Chromap for speed, Bowtie2 for compatibility
4. **Peak Strategy**: Use pooled peaks when you have ≥2 replicates/group
5. **Genome Version**: Double-check Genome_Version matches your species
6. **Plant Samples**: ATACFlow automatically filters organellar reads
7. **Storage**: Ensure sufficient space for BAM files (can be large)
8. **Cluster**: For large projects, use cluster execution mode
9. **Monitoring**: Enable Loki + Grafana for real-time monitoring

## Common Issues & Solutions

### Issue: Samples not found
**Solution**: Check that sample names and paths in samples.csv are correct

### Issue: Bowtie2/Chromap index missing
**Solution**: Verify reference_path in config/reference.yaml points to the correct location

### Issue: Low mapping rate
**Solution**: Check that you're using the correct Genome_Version for your species

### Issue: Low TSS enrichment
**Solution**: Check library quality and fragment length distribution

### Issue: High mitochondrial reads
**Solution**: Normal for plant samples - ATACFlow automatically filters these

### Issue: Conda environment errors
**Solution**: Use --conda-frontend mamba for faster, more reliable environment solving

### Issue: Differential peaks not running
**Solution**: Make sure contrasts.csv exists with contrast and treatment columns

### Issue: Out of memory
**Solution**: Adjust cluster_config.yaml or use fewer cores locally
