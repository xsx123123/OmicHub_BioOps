# ATACFlow Skills

This directory contains the bioSkills configuration for ATACFlow - a complete Snakemake-based ATAC-seq analysis pipeline.

## Directory Structure

```
skills/
├── SKILL.md              # Main skill definition for AI agents
├── usage-guide.md        # Detailed usage guide
├── README.md             # This file
├── install_skills.sh     # Generic installation script
├── install_claude_skills.sh # Dedicated Claude Code installer
├── install_codex_skills.sh  # Dedicated Codex installer
├── start_atacflow.sh     # Enhanced startup script
├── path_config.yaml      # Path configuration
└── examples/             # Example configuration files
    ├── config_complete.yaml      # Complete analysis (all modules)
    ├── config_qc_only.yaml       # QC-only mode (fast screening)
    ├── config_standard.yaml      # Standard analysis
    ├── samples.csv               # Example sample metadata
    ├── contrasts.csv             # Example contrast table
    └── run_atacflow.sh           # Helper execution script
```

## What's Included

### SKILL.md
The main skill definition file that teaches AI agents how to use ATACFlow. Includes:
- Complete workflow overview
- Configuration examples
- Module switch documentation
- Troubleshooting guide
- Version compatibility information

### usage-guide.md
A comprehensive guide for users covering:
- Prerequisites and installation
- Quick start instructions
- Example prompts for AI agents
- Input requirements
- Configuration options
- Typical workflow steps

### examples/
Ready-to-use configuration templates:
- **config_complete.yaml**: All modules enabled for deep chromatin analysis
- **config_qc_only.yaml**: Quick QC and data screening
- **config_standard.yaml**: Standard analysis (faster, skips time-consuming modules)
- **samples.csv**: Example sample metadata table
- **contrasts.csv**: Example contrast table for differential peaks
- **run_atacflow.sh**: Helper script to run ATACFlow

## How to Use

### With AI Agents
Load this skill into your AI agent (Claude Code, OpenAI Codex, etc.) and ask questions like:
- "Run a complete ATAC-seq analysis with ATACFlow"
- "Set up ATACFlow for my project"
- "Help me configure ATACFlow for differential peak analysis"

### Direct Usage
Copy the example configuration files and customize for your project:

```bash
# 1. Copy example config
cp skills/examples/config_standard.yaml my_config.yaml

# 2. Edit the config with your paths and settings
nano my_config.yaml

# 3. Create sample metadata
cp skills/examples/samples.csv .
# Edit samples.csv with your sample names and paths

# 4. Create contrasts (for differential peaks)
cp skills/examples/contrasts.csv .
# Edit contrasts.csv with your comparisons

# 5. Run ATACFlow
cd /path/to/ATACFlow
snakemake --cores 60 --use-conda --config analysisyaml=/path/to/my_config.yaml
```

## ATACFlow Features

- **Quality Control**: FastQC + fastp for trimming and adapter removal
- **Contamination Check**: FastQ Screen for species contamination detection
- **Mapping**: Bowtie2 or Chromap (2-5x faster) for sequence alignment
- **Filtering**: PCR duplicate removal, organellar (mitochondria/chloroplast) read filtering
- **Peak Calling**: MACS2 with single sample, pooled, and IDR analysis
- **Differential Analysis**: DESeq2 for differential peak calling with GO/KEGG enrichment
- **Footprinting**: TOBIAS for transcription factor footprinting and motif analysis
- **QC Metrics**: ataqv for ATAC-seq specific quality control
- **Reporting**: MultiQC + interactive HTML reports
- **Plant Optimized**: Special handling for high organellar contamination in plant samples

## Supported Genomes

ATACFlow comes pre-configured for:
- Lettuce (Lsat_Salinas_v8, Lsat_Salinas_v11)
- Tomato (ITAG4.1)
- Mouse (GRCm39)
- Arabidopsis (TAIR10.1)
- Human (hg38)

Add new genomes in `config/reference.yaml`.

## For More Information

- See the main [README.md](../README.md) for complete ATACFlow documentation
- Check [usage-guide.md](./usage-guide.md) for detailed usage instructions
- Look at [SKILL.md](./SKILL.md) for the AI agent skill definition
