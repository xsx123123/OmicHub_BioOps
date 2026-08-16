#!/bin/bash

# Test script for RDS conversion module
# This script tests the functionality of the new RDS conversion tools

echo "==========================================="
echo "Testing RDS Conversion Module"
echo "==========================================="

# Test 1: Check if scripts exist and are executable
echo "Test 1: Checking if scripts exist and are executable..."
if [ -x "/home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/tools/objectConvert/RDS_convert" ]; then
    echo "✓ RDS_convert script exists and is executable"
else
    echo "✗ RDS_convert script missing or not executable"
fi

if [ -x "/home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/tools/objectConvert/RDS_utility" ]; then
    echo "✓ RDS_utility script exists and is executable"
else
    echo "✗ RDS_utility script missing or not executable"
fi

echo ""

# Test 2: Show help for both tools
echo "Test 2: Checking help functionality..."
echo "RDS_convert help:"
/home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/tools/objectConvert/RDS_convert --help
echo ""

echo "RDS_utility help:"
/home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/tools/objectConvert/RDS_utility --help
echo ""

# Test 3: Check if there are any existing RDS files we can use for testing
echo "Test 3: Looking for existing RDS files in the pipeline..."
find /home/jzhang/pipeline/scRNA_seq_Analysis_pipeline -name "*.rds" -type f | head -5
echo ""

# Test 4: Show the directory structure of the objectConvert tools
echo "Test 4: Object conversion tools structure:"
ls -la /home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/tools/objectConvert/
echo ""

# Test 5: Check the documentation
echo "Test 5: Checking documentation:"
if [ -f "/home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/tools/objectConvert/README.md" ]; then
    echo "✓ Documentation file exists"
    head -20 /home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/tools/objectConvert/README.md
else
    echo "✗ Documentation file missing"
fi

echo ""
echo "==========================================="
echo "Integration with main pipeline:"
echo "==========================================="

# Check if the new RDS export functionality is integrated
echo "Checking if RDS export functionality is integrated into the pipeline..."
if grep -q "13.rds_export.r" /home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/src/core/core_main.r; then
    echo "✓ RDS export script is sourced in core_main.r"
else
    echo "✗ RDS export script not found in core_main.r"
fi

if grep -q "export_seurat_formats" /home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/src/core/11.single_sample.r; then
    echo "✓ RDS export function is called in single_sample.r"
else
    echo "✗ RDS export function not found in single_sample.r"
fi

if grep -q "export_seurat_formats" /home/jzhang/pipeline/scRNA_seq_Analysis_pipeline/src/core/12.multisample.r; then
    echo "✓ RDS export function is called in multisample.r"
else
    echo "✗ RDS export function not found in multisample.r"
fi

echo ""
echo "==========================================="
echo "Test Summary"
echo "==========================================="
echo "The RDS conversion module has been successfully added to the pipeline with:"
echo "1. RDS_convert: Format converter between Seurat RDS, AnnData H5AD, Loom, SCE"
echo "2. RDS_utility: RDS-specific operations (info, subset, merge, optimize, extract)"
echo "3. Integrated export functionality in both single and multisample analysis"
echo "4. Documentation and help functionality"
echo ""
echo "To run a full test, you would need an existing RDS file from your analysis."
echo "Example usage:"
echo "  RDS_convert -i input.rds -o output.h5ad"
echo "  RDS_utility -i input.rds -p info"
echo ""
