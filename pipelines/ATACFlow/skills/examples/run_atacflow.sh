#!/bin/bash
# ATACFlow Helper Execution Script
# Usage: ./run_atacflow.sh /path/to/config.yaml [cores]

set -e

# Default values
ATACFLOW_ROOT="/home/zj/pipeline/ATACFlow"
CORES=60

# Check arguments
if [ $# -eq 0 ]; then
    echo "Usage: $0 <path_to_config.yaml> [number_of_cores]"
    echo ""
    echo "Example:"
    echo "  $0 /path/to/my_config.yaml"
    echo "  $0 /path/to/my_config.yaml 80"
    exit 1
fi

CONFIG_FILE="$1"
if [ $# -ge 2 ]; then
    CORES="$2"
fi

# Validate config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: Config file not found: $CONFIG_FILE"
    exit 1
fi

# Validate ATACFlow directory exists
if [ ! -d "$ATACFLOW_ROOT" ]; then
    echo "ERROR: ATACFlow directory not found: $ATACFLOW_ROOT"
    echo "Please edit this script to set the correct ATACFLOW_ROOT"
    exit 1
fi

echo "=========================================="
echo "ATACFlow Analysis Pipeline"
echo "=========================================="
echo "Config File: $CONFIG_FILE"
echo "Cores: $CORES"
echo "ATACFlow Root: $ATACFLOW_ROOT"
echo ""

# Change to ATACFlow directory
cd "$ATACFLOW_ROOT"

# Run ATACFlow
echo "Starting ATACFlow analysis..."
echo ""

snakemake \
    --cores="$CORES" \
    -p \
    --conda-frontend=mamba \
    --use-conda \
    --rerun-triggers mtime \
    --logger rich-loguru \
    --config analysisyaml="$CONFIG_FILE"

echo ""
echo "=========================================="
echo "Analysis complete!"
echo "=========================================="
