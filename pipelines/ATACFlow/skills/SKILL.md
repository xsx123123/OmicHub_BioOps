---
name: bio-workflows-atacflow
description: ATAC-seq analysis using ATACFlow pipeline - complete workflow from raw FASTQ to interactive HTML report. Use whenever user asks for ATAC-seq analysis, chromatin accessibility, open chromatin, transcription factor footprinting, differential peaks, etc. Covers QC, Bowtie2/Chromap mapping, MACS2 peak calling, IDR analysis, TOBIAS footprinting, differential peak analysis with DESeq2, GO/KEGG enrichment, and automated reporting.
tool_type: mixed
primary_tool: Snakemake
workflow: true
depends_on:
  - read-qc/fastp-workflow
  - read-alignment/bowtie2-align
  - peak-calling/macs2
  - differential-peaks/deseq2-atac
  - footprinting/tobias-analysis
  - reporting/quarto-reporting
qc_checkpoints:
  - after_qc: "Q30 >80%, adapter content <5%"
  - after_mapping: "Mapping rate >70%, mitochondrial reads <30%, TSS enrichment >5"
  - after_peak_calling: "FRiP >10%, peaks in expected genomic regions"
  - after_diff: "DESeq2 dispersion fit reasonable, PCA separates conditions"
---

## Version Compatibility

Reference examples tested with: Snakemake 9.9+, Bowtie2 2.5+, Chromap 0.2+, MACS2 2.2+, TOBIAS 0.16+, DESeq2 1.42+, fastp 0.23+, Python 3.10+, R 4.3+

Before using code patterns, verify installed versions match. If versions differ:
- Check ATACFlow version: `grep "ATACFlow" README.md`
- Snakemake: `snakemake --version`
- Conda environments are automatically managed by ATACFlow

If code throws errors, check ATACFlow's config.schema.yaml and reference.yaml for valid configuration options.

# ATACFlow - Complete ATAC-seq Analysis Workflow

**Locating ATACFlow:** First, read the `path_config.yaml` file in this skills directory to find:
- `ATACFLOW_ROOT`: The root directory of the ATACFlow installation (contains snakefile)
- `DEFAULT_ENV_NAME`: Recommended conda environment name
- Configuration templates and default parameters

**"Run full ATAC-seq analysis with ATACFlow from FASTQ to interactive report"** → Orchestrate complete ATAC-seq pipeline using ATACFlow Snakemake workflow with QC, Bowtie2/Chromap mapping, MACS2 peak calling, IDR analysis, TOBIAS footprinting, differential peaks with DESeq2, and HTML reports.

## Workflow Overview

```
Raw FASTQ files
    |
    v
[1. MD5 Check] -----> md5sum validation
    |
    v
[2. QC & Trimming] -> FastQC + fastp + FastQ Screen
    |
    v
[3. Mapping] --------> Bowtie2 or Chromap
    |         |
    |         +-----> Samtools filtering, PCR duplicate removal
    |         +-----> Organellar (mitochondria/chloroplast) read filtering
    |         +-----> Fragment shifting + ataqv QC
    |
    v
[4. Peak Calling] ---> MACS2 (single sample + pooled + IDR)
    |
    v
[5. Consensus Peaks] -> Single sample or pooled consensus
    |
    v
[6. Differential Analysis] -> DESeq2 + GO/KEGG enrichment
    |
    v
[7. Advanced Analysis]
    |
    +---> TOBIAS Footprinting
    +---> Motif Analysis (BINDetect)
    |
    v
[8. Reporting] -------> MultiQC + HTML Report
    |
    v
Final Results & Report
```

## ATACFlow Configuration

### Step 1: Project Structure Setup

```bash
# Create recommended project structure
mkdir -p Project_Root/{00.raw_data,01.workflow,02.data_deliver}

# ATACFlow repository should be cloned separately
git clone --recurse-submodules git@github.com:xsx123123/ATACFlow.git
```

### Step 2: Create Project Config (config.yaml)

```yaml
# === Basic Project Info ===
project_name: 'PRJNA_ATAC_Complete'
Genome_Version: "hg38"
species: 'Homo_sapiens'
client: 'Internal_Test'

# === Data Paths ===
raw_data_path:
  - /path/to/Project_Root/00.raw_data
sample_csv: /path/to/Project_Root/01.workflow/samples.csv
paired_csv: /path/to/Project_Root/01.workflow/contrasts.csv
workflow: /path/to/Project_Root/01.workflow
data_deliver: /path/to/Project_Root/02.data_deliver

# === Execution Parameters ===
execution_mode: local
mapping_tools: chromap  # chromap (fast) or bowtie2 (compatible)
Library_Types: fr-firststrand

# === Analysis Module Switches (snake_case) ===
only_qc: false
diff_peaks: true
fastq_screen: true
report: true

# === Peak Calling Configuration ===
peak_calling:
  use_pooled_peaks: true  # Use group-pooled peaks for DEG

# === Resource Recommendations ===
# Standard Mode: 4-8 cores/sample, 32GB+ RAM
# Complete Mode (TOBIAS): 8+ cores/sample, 64GB+ RAM
# Cluster: Recommended for >10 samples

# === Optional Monitoring ===
loki_url: "http://your-loki-server:3100"
```

### Step 3: Create Sample Metadata (samples.csv)

```csv
sample,sample_name,group
Sample1_R1,Sample1,Control
Sample2_R1,Sample2,Control
Sample3_R1,Sample3,Treatment
Sample4_R1,Sample4,Treatment
```

### Step 4: Create Contrast Table (contrasts.csv)

```csv
contrast,treatment
Control,Treatment
```

### Step 5: Environment Setup and Validation (Recommended)

Use the enhanced startup script for automated conda environment checking:

```bash
# Option 1: Use the enhanced startup script (Recommended)
cd /path/to/ATACFlow/skills
./start_atacflow.sh /path/to/project_config.yaml

# The script will automatically:
# 1. Check if conda is installed
# 2. Verify the ATACFlow conda environment exists
# 3. Check for Snakemake in the environment
# 4. Ask for user confirmation before activating
# 5. Run dry run and ask for final confirmation
```

**Configuring ATACFlow Paths:**
The startup script reads from `path_config.yaml` to locate:
- `ATACFLOW_ROOT`: Path to ATACFlow installation
- `DEFAULT_ENV_NAME`: Conda environment name (default: "atacflow")
- `AUTO_ACTIVATE`: Set to true to skip confirmation prompts

### Step 6: Manual Environment Setup (Alternative)

If not using the startup script, perform these checks manually:

```bash
# 1. Check conda installation
conda --version

# 2. List available environments
conda env list

# 3. Activate your ATACFlow environment (confirm with user first!)
# Ask user: "Do you want to activate environment 'atacflow'?"
conda activate atacflow

# 4. Verify Snakemake
snakemake --version

# 5. Dry Run
cd /path/to/ATACFlow
snakemake -n --config analysisyaml=/path/to/project_config.yaml
```

**QC Checkpoint 1:** Verify all inputs are found and rules are correctly generated.

### Step 7: Run Full Analysis

```bash
# If using startup script, it will proceed automatically after confirmation

# Manual execution:
cd /path/to/ATACFlow

snakemake \
    --cores=60 \
    -p \
    --conda-frontend=mamba \
    --use-conda \
    --rerun-triggers mtime \
    --logger rich-loguru \
    --config analysisyaml=/path/to/project_config.yaml
```

**QC Checkpoint 2:** Monitor logs for:
- Mapping rate >70%
- TSS enrichment score >5
- FRiP (Fraction of Reads in Peaks) >10%

**QC Checkpoint 3:** After differential analysis:
- Check PCA plot in report
- Verify dispersion fit
- No sample outliers

## Supported Genome Versions

ATACFlow includes pre-configured references for:

| Genome Version | Species | Description |
|----------------|---------|-------------|
| Lsat_Salinas_v8 | Lettuce | Lettuce reference v8 |
| Lsat_Salinas_v11 | Lettuce | Lettuce reference v11 |
| ITAG4.1 | Tomato | Tomato reference |
| GRCm39 | Mouse | Mouse reference |
| TAIR10.1 | Arabidopsis | Arabidopsis reference |
| hg38 | Human | Human reference |

Add new genomes in `config/reference.yaml`.

## Analysis Module Configuration

### Complete Analysis (Default)

```yaml
only_qc: false
diff_peaks: true
fastq_screen: true
report: true
peak_calling:
  use_pooled_peaks: true
```

### QC-Only Mode (Fast Screening)

```yaml
only_qc: true
```

### Standard Analysis (Skip Time-Consuming Modules)

```yaml
only_qc: false
diff_peaks: true
fastq_screen: true
report: true
peak_calling:
  use_pooled_peaks: false
```

## Key Mapping Tools in ATACFlow

ATACFlow supports two mapping engines:

### Chromap (Default, Fast)
```yaml
mapping_tools: chromap
```
- Optimized for ATAC-seq data
- 2-5x faster than Bowtie2
- Recommended for large datasets

### Bowtie2 (Compatible)
```yaml
mapping_tools: bowtie2
```
- Classic, well-tested aligner
- More parameter control
- Better compatibility with specialized use cases

## Peak Calling Strategies (v0.0.5+)

ATACFlow supports multiple peak calling strategies:

### Pooled Peaks (Recommended)
```yaml
peak_calling:
  use_pooled_peaks: true
```
- Merge biological replicates within groups
- Higher sensitivity for weak peaks
- Better for experiments with ≥2 replicates/group

### Single Sample Consensus
```yaml
peak_calling:
  use_pooled_peaks: false
```
- Call peaks on each sample individually
- Merge into consensus set
- Better for experiments with few replicates

### IDR Analysis
- Automatically run when ≥2 replicates per group
- Quality control for reproducibility
- Not recommended for DEG (too few peaks)

## Output Directory Structure

```
02.data_deliver/
├── 00_Raw_Data/             # Raw data summary
├── 01_QC/                   # QC reports (MultiQC)
├── 02_Mapping/              # Mapping statistics + ataqv
├── 03_Peak_Calling/         # Peak calling results (single/pooled/IDR)
├── 04_Consensus/            # Consensus peak sets
├── 05_ATAC_QC/              # ATAC-specific QC
├── 06_DEG_Enrich/           # Differential peaks + GO/KEGG
├── 06_Motif_Analysis/       # TOBIAS footprinting results
├── Summary/                  # Project summary statistics
├── report/                   # Final HTML report
└── delivery_manifest.json    # Delivery manifest with MD5 checksums
```

## TOBIAS Footprinting Analysis

ATACFlow integrates TOBIAS for transcription factor footprinting:

### Workflow Steps:
1. **ATACorrect**: Correct for Tn5 insertion bias
2. **EstimateFootprints**: Detect protein-DNA binding footprints
3. **BINDetect**: Identify differential transcription factor binding

### Configuration:
TOBIAS analysis runs automatically when sufficient data is available.

## Troubleshooting Guide

| Issue | Likely Cause | Solution |
|-------|--------------|----------|
| Bowtie2/Chromap index not found | Reference path incorrect | Check `config/reference.yaml` |
| Low mapping rate | Wrong genome version | Verify Genome_Version matches your species |
| High mitochondrial reads | Plant sample with organellar contamination | ATACFlow automatically filters these |
| Low TSS enrichment | Poor quality library | Check fragment length distribution |
| Conda environment errors | Network issue | Check conda channels, try mamba |
| Samples not found | sample_csv format wrong | Verify sample names and paths are correct |
| DEG not running | contrasts.csv missing | Create contrasts.csv with contrast/treatment columns |
| Memory issues | Resources insufficient | Check `config/cluster_config.yaml` |

## Cluster Execution (Slurm)

For cluster environments:

```yaml
# config.yaml
execution_mode: cluster
queue_id: fat_x86
```

```bash
# Install Slurm executor plugin first
conda install snakemake-executor-plugin-slurm

# Run on cluster
snakemake \
    --executor slurm \
    --jobs 100 \
    --use-conda \
    --conda-frontend mamba \
    --config analysisyaml=config.yaml
```

## Monitoring with Loki + Grafana

Enable real-time monitoring:

```yaml
# config.yaml
loki_url: "http://your-loki-server:3100"
```

```bash
# Install logger plugin
pip install snakemake_logger_plugin_rich_loguru==0.1.4

# Run with monitoring
snakemake \
    --cores 60 \
    --use-conda \
    --logger rich-loguru \
    --config analysisyaml=config.yaml
```

View logs in Grafana dashboard.

## Related Skills

- read-qc/fastp-workflow - Detailed fastp QC parameters
- read-alignment/bowtie2-align - Bowtie2 alignment details
- peak-calling/macs2 - MACS2 peak calling
- differential-peaks/deseq2-atac - DESeq2 for ATAC-seq
- footprinting/tobias-analysis - TOBIAS footprinting
- reporting/quarto-reporting - Quarto report generation
- workflow-management/snakemake-workflows - Snakemake best practices
