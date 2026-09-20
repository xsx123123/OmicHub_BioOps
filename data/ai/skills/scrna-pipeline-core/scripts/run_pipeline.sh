#!/bin/bash
# ==============================================================================
# scrna-pipeline-core — CLI wrapper for scRNAseqMulticommand pipeline
# Description: 从单细胞基因表达矩阵到注释结果的完整分析流程
# Usage: run_pipeline.sh [options]
# ==============================================================================

set -e

# Parse arguments
CONF=""
OUTPUTDIR=""
PROJECTNAME=""
TAXID=""
MARKERDB=""
ORGAN=""
INTEGRATION_METHOD="CCA"
REDUCETYPE="FALSE"
AUTOFILTERCELL="TRUE"
THREADS="20"

while [[ $# -gt 0 ]]; do
    case $1 in
        --conf)
            CONF="$2"
            shift 2
            ;;
        --output)
            OUTPUTDIR="$2"
            shift 2
            ;;
        --project-name)
            PROJECTNAME="$2"
            shift 2
            ;;
        --taxid)
            TAXID="$2"
            shift 2
            ;;
        --marker-db)
            MARKERDB="$2"
            shift 2
            ;;
        --organ)
            ORGAN="$2"
            shift 2
            ;;
        --integration-method)
            INTEGRATION_METHOD="$2"
            shift 2
            ;;
        --reduce-type)
            REDUCETYPE="$2"
            shift 2
            ;;
        --auto-filter-cell)
            AUTOFILTERCELL="$2"
            shift 2
            ;;
        --threads)
            THREADS="$2"
            shift 2
            ;;
        --help)
            echo "Usage: run_pipeline.sh [options]"
            echo ""
            echo "Options:"
            echo "  --conf PATH              CSV config file (required)"
            echo "  --output PATH            Output directory (required)"
            echo "  --project-name NAME      Project name (required)"
            echo "  --taxid NUMBER           Taxonomy ID: 9606(Human), 10090(Mouse), 3702(Arabidopsis) (required)"
            echo "  --marker-db TYPE         Marker database: Cellmarker, PanglaoDB, Custom (required)"
            echo "  --organ TEXT             Target organ/tissue (required)"
            echo "  --integration-method METHOD  Integration method: CCA, Harmony, RPCA, ALL (default: CCA)"
            echo "  --reduce-type BOOL       Use tSNE: TRUE/FALSE (default: FALSE)"
            echo "  --auto-filter-cell BOOL  Auto filter cells: TRUE/FALSE (default: TRUE)"
            echo "  --threads NUMBER         Number of threads (default: 20)"
            echo "  --help                   Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate required parameters
if [[ -z "$CONF" || -z "$OUTPUTDIR" || -z "$PROJECTNAME" || -z "$TAXID" || -z "$MARKERDB" || -z "$ORGAN" ]]; then
    echo "[ERROR] Missing required parameters. Use --help for usage."
    exit 1
fi

if [[ ! -f "$CONF" ]]; then
    echo "[ERROR] Config file not found: $CONF"
    exit 1
fi

# Determine pipeline path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_ROOT="$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")"

# Check if running on platform (ref/scRNAseqMulticommand exists)
if [[ -f "$PIPELINE_ROOT/ref/scRNAseqMulticommand/scRNAseqMulticommand" ]]; then
    # Platform mode: use provisioned pipeline
    PIPELINE_CMD="$PIPELINE_ROOT/ref/scRNAseqMulticommand/scRNAseqMulticommand"
    echo "[INFO] Running in platform mode using provisioned pipeline"
elif [[ -f "$PIPELINE_ROOT/scRNAseqMulticommand" ]]; then
    # Local mode: use local pipeline
    PIPELINE_CMD="$PIPELINE_ROOT/scRNAseqMulticommand"
    echo "[INFO] Running in local mode"
else
    echo "[ERROR] Pipeline not found. Please ensure ref/scRNAseqMulticommand/ or scRNAseqMulticommand exists."
    exit 1
fi

# Build command
CMD="$PIPELINE_CMD \
    -c $CONF \
    -o $OUTPUTDIR \
    -n $PROJECTNAME \
    -I $TAXID \
    -F $MARKERDB \
    -O $ORGAN"

if [[ "$INTEGRATION_METHOD" != "CCA" ]]; then
    CMD="$CMD -i $INTEGRATION_METHOD"
fi

if [[ "$REDUCETYPE" == "TRUE" ]]; then
    CMD="$CMD -r TRUE"
fi

if [[ "$AUTOFILTERCELL" == "FALSE" ]]; then
    CMD="$CMD -a FALSE"
fi

if [[ "$THREADS" != "20" ]]; then
    CMD="$CMD -t $THREADS"
fi

echo "[INFO] Executing pipeline command:"
echo "[INFO] $CMD"
echo ""

# Execute
eval $CMD
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
    echo ""
    echo "[SUCCESS] Pipeline completed successfully!"
    echo "[INFO] Results saved to: $OUTPUTDIR"
else
    echo ""
    echo "[ERROR] Pipeline failed with exit code: $EXIT_CODE"
fi

exit $EXIT_CODE
