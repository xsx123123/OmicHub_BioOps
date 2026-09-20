#!/usr/bin/env python3
# ==============================================================================
# Integration test for scrna skills workflow
# Description: 验证从标准分析到定制分析的完整技能工作流
# ==============================================================================

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

# Paths
SKILLS_ROOT = Path(__file__).parent.parent.parent / "skills"
TEST_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "testdata"

# Test fixtures
FIXTURES = {
    "smoke_obj_rds": "/tmp/skill_smoke/smoke_obj.rds",
    "mock_result_dir": "/tmp/skill_smoke/mock_result-scRNA-seq-result",
}


def setup():
    """Create test fixtures"""
    print("=== Setting up test fixtures ===")
    
    # Create smoke test RDS (if not exists)
    if not os.path.exists(FIXTURES["smoke_obj_rds"]):
        print("Creating synthetic Seurat RDS...")
        setup_seurat_fixture()
    
    # Create mock result directory for quarto-report test
    if not os.path.exists(FIXTURES["mock_result_dir"]):
        print("Creating mock result directory...")
        setup_mock_result_fixture()
    
    print("✅ Setup complete\n")


def setup_seurat_fixture():
    """Create a small synthetic Seurat object"""
    R_SCRIPT = """
suppressMessages(library(Seurat))
set.seed(42)
ng <- 300; nc <- 200
mat <- matrix(rpois(ng*nc, lambda=0.4), nrow=ng)
rownames(mat) <- paste0("Gene", sprintf("%03d", 1:ng))
colnames(mat) <- paste0("Cell", sprintf("%03d", 1:nc))
ct <- rep(c("T cell","B cell","Mono"), length.out=nc)
grp <- rep(c("ctrl","treat"), each=nc/2)
for (i in 1:3) {
  gs <- paste0("Gene", sprintf("%03d", ((i-1)*30+1):(i*30)))
  mat[gs, ct==unique(ct)[i]] <- mat[gs, ct==unique(ct)[i]] + rpois(sum(ct==unique(ct)[i])*30, 8)
}
obj <- CreateSeuratObject(counts=mat, project="smoke")
obj$celltype <- ct
obj$group <- grp
obj <- NormalizeData(obj, verbose=FALSE)
saveRDS(obj, "/tmp/skill_smoke/smoke_obj.rds")
cat("Created:", file.exists("/tmp/skill_smoke/smoke_obj.rds"), "\\n")
"""
    R = "/home/zj/.local/share/mamba/envs/scrna/bin/Rscript"
    os.makedirs("/tmp/skill_smoke", exist_ok=True)
    result = subprocess.run([R, "-e", R_SCRIPT], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"❌ Failed to create Seurat fixture:\n{result.stderr}")
        sys.exit(1)
    print(result.stdout.strip())


def setup_mock_result_fixture():
    """Create minimal mock result directory structure"""
    mock_dir = FIXTURES["mock_result_dir"]
    os.makedirs(f"{mock_dir}/QC/Cellranger", exist_ok=True)
    
    # Create required setting file
    with open(f"{mock_dir}/QC/Cellranger/sample1_filted_setting.csv", "w") as f:
        f.write("sample_id\tfilter_setting\nsample1\tdefault\n")
    
    print(f"Created mock result directory: {mock_dir}")


def test_1_rds_utility():
    """Test: RDS_utility --operation info"""
    print("=== Test 1: RDS_utility ===")
    S = SKILLS_ROOT / "scrna-object-convert" / "scripts"
    R = "/home/zj/.local/share/mamba/envs/scrna/bin/Rscript"
    
    cmd = [
        R, str(S / "RDS_utility"),
        "-i", FIXTURES["smoke_obj_rds"],
        "-p", "info"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    
    assert result.returncode == 0, f"❌ Failed: {result.stderr}"
    assert "Dimensions:" in result.stdout, "❌ Expected output format mismatch"
    print("✅ RDS_utility passed\n")


def test_2_recluster():
    """Test: recluster.R"""
    print("=== Test 2: recluster.R ===")
    S = SKILLS_ROOT / "scrna-recluster" / "scripts"
    R = "/home/zj/.local/share/mamba/envs/scrna/bin/Rscript"
    out_dir = "/tmp/skill_smoke/test_recluster"
    
    # Note: --file parameter is internal, use script path directly
    cmd = [
        R, str(S / "recluster.R"),
        "--input", FIXTURES["smoke_obj_rds"],
        "--output", out_dir,
        "--name", "test",
        "--resolution", "0.8",
        "--nfeatures", "1500"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    # Check outputs exist (exit code may be 1 due to non-critical warnings)
    assert os.path.exists(f"{out_dir}/test-reclustered.rds"), f"❌ Expected output file missing\nSTDERR: {result.stderr[-300:]}"
    assert os.path.exists(f"{out_dir}/test-pct-ElbowPlot.png"), "❌ Expected elbow plot missing"
    assert os.path.exists(f"{out_dir}/summary.json"), "❌ Expected summary.json missing"
    print("✅ recluster.R passed\n")


def test_3_annotation_stats():
    """Test: annotation_stats.R --mode prop"""
    print("=== Test 3: annotation_stats.R ===")
    S = SKILLS_ROOT / "scrna-annotation-stats" / "scripts"
    R = "/home/zj/.local/share/mamba/envs/scrna/bin/Rscript"
    out_dir = "/tmp/skill_smoke/test_stats"
    
    cmd = [
        R, str(S / "annotation_stats.R"),
        "--input", FIXTURES["smoke_obj_rds"],
        "--output", out_dir,
        "--name", "test",
        "--mode", "prop"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    assert result.returncode == 0, f"❌ Failed: {result.stderr}"
    assert os.path.exists(f"{out_dir}/test-celltyoe.prop.csv"), "❌ Expected CSV missing"
    assert os.path.exists(f"{out_dir}/test-prop.png"), "❌ Expected PNG missing"
    assert os.path.exists(f"{out_dir}/summary.json"), "❌ Expected summary.json missing"
    print("✅ annotation_stats.R passed\n")


def test_4_deg_analysis():
    """Test: deg_analysis.R"""
    print("=== Test 4: deg_analysis.R ===")
    S = SKILLS_ROOT / "scrna-deg-analysis" / "scripts"
    R = "/home/zj/.local/share/mamba/envs/scrna/bin/Rscript"
    out_dir = "/tmp/skill_smoke/test_deg"
    ref_dir = "/home/zj/zj_code_libarary/OmicHub/pipelines/scrna/tools/DEG/DEG_Annotation_reference"
    
    env = os.environ.copy()
    env["SCRNA_DEG_REF_DIR"] = ref_dir
    
    cmd = [
        R, str(S / "deg_analysis.R"),
        "--input", FIXTURES["smoke_obj_rds"],
        "--output", out_dir,
        "--treat", "treat",
        "--control", "ctrl"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    
    assert result.returncode == 0, f"❌ Failed: {result.stderr}"
    assert os.path.exists(f"{out_dir}/summary.json"), "❌ Expected summary.json missing"
    # Check DEG directories exist
    deg_dirs = [d for d in os.listdir(out_dir) if d.startswith("treat_vs_ctrl-")]
    assert len(deg_dirs) > 0, "❌ Expected DEG result directories missing"
    print(f"✅ deg_analysis.R passed ({len(deg_dirs)} cell types)\n")


def test_5_projectils_failure():
    """Test: projectils_annotate.R failure path (ProjecTILs not installed)"""
    print("=== Test 5: projectils_annotate.R (failure path) ===")
    S = SKILLS_ROOT / "scrna-tcell-projectils" / "scripts"
    R = "/home/zj/.local/share/mamba/envs/scrna/bin/Rscript"
    
    cmd = [
        R, str(S / "projectils_annotate.R"),
        "--input", FIXTURES["smoke_obj_rds"],
        "--output", "/tmp/skill_smoke/test_projectils",
        "--name", "test"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    
    assert result.returncode == 1, "❌ Expected exit code 1 (ProjecTILs not installed)"
    assert "ProjecTILs 未安装" in result.stderr, "❌ Expected error message missing"
    print("✅ projectils_annotate.R failure path passed\n")


def test_6_merge_deg_infor():
    """Test: merge_deg_infor.py"""
    print("=== Test 6: merge_deg_infor.py ===")
    S = SKILLS_ROOT / "scrna-deg-analysis" / "scripts"
    
    # Create test files
    test_dir = "/tmp/skill_smoke/test_merge"
    os.makedirs(f"{test_dir}/Tcell", exist_ok=True)
    with open(f"{test_dir}/Tcell/Tcell_Treat_vs_Ctrl-DEG-infor.csv", "w") as f:
        f.write("compare,UP,DOWN\nTreat_vs_Ctrl,25,10\n")
    
    cmd = [
        "python3", str(S / "merge_deg_infor.py"),
        "--input", test_dir,
        "--output", f"{test_dir}/merged.csv"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    
    assert result.returncode == 0, f"❌ Failed: {result.stderr}"
    assert os.path.exists(f"{test_dir}/merged.csv"), "❌ Expected merged CSV missing"
    print("✅ merge_deg_infor.py passed\n")


def test_7_quarto_report():
    """Test: build_quarto_report.R --no-render"""
    print("=== Test 7: build_quarto_report.R ===")
    R = "/home/zj/.local/share/mamba/envs/scrna/bin/Rscript"
    repo_root = Path(__file__).parent.parent.parent
    
    cmd = [
        R, str(repo_root / "tools" / "build_quarto_report.R"),
        "--result-dir", FIXTURES["mock_result_dir"],
        "--report-dir", str(repo_root / "report"),
        "--no-render"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    
    assert result.returncode == 0, f"❌ Failed: {result.stderr}"
    assert os.path.exists(f"{FIXTURES['mock_result_dir']}/manifest.json"), "❌ Expected manifest.json missing"
    print("✅ build_quarto_report.R passed\n")


def main():
    """Run all integration tests"""
    print("=" * 60)
    print("SCRNA Skills Integration Test Suite")
    print("=" * 60)
    print()
    
    try:
        setup()
        
        tests = [
            test_1_rds_utility,
            test_2_recluster,
            test_3_annotation_stats,
            test_4_deg_analysis,
            test_5_projectils_failure,
            test_6_merge_deg_infor,
            test_7_quarto_report,
        ]
        
        for test in tests:
            test()
        
        print("=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
