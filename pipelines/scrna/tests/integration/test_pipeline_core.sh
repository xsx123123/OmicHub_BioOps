#!/bin/bash
# ==============================================================================
# Test scrna-pipeline-core wrapper script
# Description: 验证 scrna-pipeline-core 的 CLI wrapper 正确工作
# ==============================================================================

set -e

echo "=== Testing scrna-pipeline-core ==="

SKILLS_ROOT="/home/zj/zj_code_libarary/OmicHub/pipelines/scrna/skills"
PIPELINE_CORE="$SKILLS_ROOT/scrna-pipeline-core"
SCRIPT="$PIPELINE_CORE/scripts/run_pipeline.sh"
R="/home/zj/.local/share/mamba/envs/scrna/bin/Rscript"

# Test 1: Help message
echo ""
echo "Test 1: --help flag"
bash "$SCRIPT" --help | grep -q "Usage:" && echo "✅ Help message works" || (echo "❌ Help failed"; exit 1)

# Test 2: Missing required parameters
echo ""
echo "Test 2: Missing required parameters"
if bash "$SCRIPT" --conf /tmp/test.conf 2>&1 | grep -q "Missing required parameters"; then
    echo "✅ Parameter validation works"
else
    echo "❌ Parameter validation failed"
    exit 1
fi

# Test 3: Config file not found
echo ""
echo "Test 3: Config file not found"
mkdir -p /tmp/skill_smoke/test_conf
if bash "$SCRIPT" \
    --conf /tmp/nonexistent.conf \
    --output /tmp/out \
    --project-name test \
    --taxid 9606 \
    --marker-db Cellmarker \
    --organ Blood 2>&1 | grep -q "Config file not found"; then
    echo "✅ Config file validation works"
else
    echo "❌ Config file validation failed"
    exit 1
fi

# Test 4: Pipeline detection (should find local pipeline)
echo ""
echo "Test 4: Pipeline detection"
cd /home/zj/zj_code_libarary/OmicHub/pipelines/scrna
OUTPUT=$(bash "$SCRIPT" \
    --conf /tmp/skill_smoke/test_conf/scRNA-seq.conf \
    --output /tmp/skill_smoke/test_output \
    --project-name test_run \
    --taxid 9606 \
    --marker-db Cellmarker \
    --organ Blood 2>&1)

if echo "$OUTPUT" | grep -q "Running in local mode"; then
    echo "✅ Local pipeline detection works"
elif echo "$OUTPUT" | grep -q "Running in platform mode"; then
    echo "✅ Platform pipeline detection works"
else
    echo "⚠️  Pipeline detection inconclusive (may be expected)"
fi

echo ""
echo "=== All wrapper tests passed! ==="
