"""DEG 差异表达分析工具测试：配置加载 / 引擎路由 / 输入校验 / 容器命令 / 结果解析。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cygnusx.core.exceptions import ValidationError
from cygnusx.tools.deg.config import DegConfig, DegConfigManager
from cygnusx.tools.deg import service as deg_service_module
from cygnusx.tools.deg.runner import DegDockerRunner, DegRunParams
from cygnusx.tools.deg.service import DegService
from cygnusx.tools.deg.tasks import _parse_results

REPO_ROOT = Path(__file__).resolve().parents[3]
DEG_CONFIG_YAML = REPO_ROOT / "tool_configs" / "deg" / "deg_config.yaml"


def _service() -> DegService:
    return DegService.__new__(DegService)


def _runner() -> DegDockerRunner:
    runner = DegDockerRunner.__new__(DegDockerRunner)
    runner._settings = SimpleNamespace(
        deg_docker_image="cygnusx-r-deg:v1",
        deg_docker_network="cygnusx_app_net",
        deg_data_mount="/data/cygnusx",
        deg_exec_timeout=7200,
    )
    return runner


# ----------------------------------------------------------------------
# 配置加载
# ----------------------------------------------------------------------

def test_config_loads_repo_yaml() -> None:
    cfg = DegConfigManager(DEG_CONFIG_YAML).get_config()
    assert cfg.defaults.method == "auto"
    assert cfg.defaults.bcv == 0.4
    assert cfg.execution.docker_image == "cygnusx-r-deg:v1"
    assert cfg.input_limits.min_samples == 2


def test_config_missing_file_falls_back_to_defaults(tmp_path: Path) -> None:
    cfg = DegConfigManager(tmp_path / "absent.yaml").get_config()
    assert isinstance(cfg, DegConfig)
    assert cfg.defaults.method == "auto"


def test_config_invalid_field_falls_back_to_defaults(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("defaults:\n  pval: 5.0\n", encoding="utf-8")  # pval le=1 违反
    cfg = DegConfigManager(bad).get_config()
    assert cfg.defaults.pval == 0.05  # 回退内置默认，不抛异常


def test_defaults_expose_all_frontend_upload_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DegConfig()
    cfg.input_limits.max_metadata_file_size_mb = 7
    cfg.input_limits.max_pairs_file_size_mb = 9
    cfg.input_limits.max_contrasts = 24
    monkeypatch.setattr(deg_service_module.config_manager, "get_config", lambda: cfg)

    defaults = _service().get_defaults()

    assert defaults.max_counts_file_size_mb == cfg.input_limits.max_counts_file_size_mb
    assert defaults.max_metadata_file_size_mb == 7
    assert defaults.max_pairs_file_size_mb == 9
    assert defaults.max_annotation_file_size_mb == cfg.input_limits.max_annotation_file_size_mb
    assert defaults.min_samples == cfg.input_limits.min_samples
    assert defaults.max_contrasts == 24
    assert defaults.max_genes == cfg.input_limits.max_genes


# ----------------------------------------------------------------------
# 引擎路由（与 RNAFlow rules/utils/deg_method.py 同口径）
# ----------------------------------------------------------------------

GROUP_COUNTS = {"WT": 3, "Treat": 3, "KO": 1, "Rescue": 1}
MIXED_PAIRS = [("Treat", "WT"), ("Rescue", "KO")]


def test_auto_routes_to_edger_when_any_contrast_lacks_replicates() -> None:
    engine, no_rep = _service()._resolve_engine("auto", GROUP_COUNTS, MIXED_PAIRS, 2)
    assert engine == "edger"
    assert no_rep == ["Rescue_vs_KO"]


def test_auto_stays_deseq2_when_all_replicated() -> None:
    engine, no_rep = _service()._resolve_engine("auto", GROUP_COUNTS, [("Treat", "WT")], 2)
    assert engine == "deseq2"
    assert no_rep == []


def test_forced_edger_reports_no_rep_contrasts() -> None:
    engine, no_rep = _service()._resolve_engine("edger", GROUP_COUNTS, MIXED_PAIRS, 2)
    assert engine == "edger"
    assert no_rep == ["Rescue_vs_KO"]


def test_forced_deseq2_with_1v1_is_rejected_early() -> None:
    with pytest.raises(ValidationError, match="DESeq2 无法分析"):
        _service()._resolve_engine("deseq2", GROUP_COUNTS, MIXED_PAIRS, 2)


# ----------------------------------------------------------------------
# 输入校验
# ----------------------------------------------------------------------

def test_parse_table_and_column_detection() -> None:
    svc = _service()
    rows = svc._parse_table(b"sample_name,group\nA,WT\nB,Treat\n", "m.csv", "样本表")
    assert svc._find_column(rows, {"sample", "sample_name"}, "x", "Sample") == "sample_name"
    assert svc._find_column(rows, {"group", "condition"}, "x", "Group") == "group"


def test_parse_table_tsv_and_sniff() -> None:
    svc = _service()
    rows = svc._parse_table("Treat\tControl\nB\tA\n".encode(), "p.tsv", "比较对")
    assert rows[0]["Treat"] == "B"
    rows = svc._parse_table(b"Treat,Control\nB,A\n", "p.txt", "比较对")
    assert rows[0]["Control"] == "A"


def test_missing_required_column_raises() -> None:
    svc = _service()
    rows = svc._parse_table(b"foo,bar\n1,2\n", "m.csv", "样本表")
    with pytest.raises(ValidationError, match="Sample"):
        svc._find_column(rows, {"sample", "sample_name"}, "样本表", "Sample")


def test_counts_header_and_size_limits() -> None:
    svc = _service()
    header = svc._parse_counts_header(b"GeneID,S1,S2\nG1,1,2\n", "c.csv")
    assert header == ["GeneID", "S1", "S2"]
    with pytest.raises(ValidationError, match="至少需要"):
        svc._parse_counts_header(b"GeneID\nG1\n", "c.csv")
    with pytest.raises(ValidationError, match="超过大小上限"):
        svc._check_size("表达矩阵", b"x" * 100, 0)  # 0 MB 上限必然触发（gt=0 仅限 YAML）


# ----------------------------------------------------------------------
# 容器命令构造
# ----------------------------------------------------------------------

def test_runner_command_edger_includes_bcv_and_annotation() -> None:
    params = DegRunParams(
        engine="edger",
        counts_path="/data/cygnusx/u/t/input/counts.csv",
        metadata_path="/data/cygnusx/u/t/input/metadata.csv",
        pairs_path="/data/cygnusx/u/t/input/pairs.csv",
        output_dir="/data/cygnusx/u/t/results",
        lfc=1.0,
        pval=0.05,
        bcv=0.4,
        annotation_path="/data/cygnusx/u/t/input/annotation.csv",
    )
    cmd = _runner().build_command(params, "cygnusx-deg-test")
    joined = " ".join(cmd)
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "cygnusx-r-deg:v1" in cmd
    assert "/opt/deg/run_edger.r" in cmd
    assert "--bcv=0.4" in cmd
    assert "-v" in cmd and "/data/cygnusx:/data/cygnusx" in cmd
    assert "-a" in cmd
    assert cmd[cmd.index("-o") + 1] == params.output_dir
    assert "--lfc=1.0" in joined and "--pval=0.05" in joined


def test_runner_command_deseq2_omits_bcv() -> None:
    params = DegRunParams(
        engine="deseq2",
        counts_path="c",
        metadata_path="m",
        pairs_path="p",
        output_dir="o",
    )
    cmd = _runner().build_command(params, "cygnusx-deg-test2")
    assert "/opt/deg/run_deseq2.r" in cmd
    assert not any("--bcv" in part for part in cmd)
    assert "-a" not in cmd


# ----------------------------------------------------------------------
# 结果解析
# ----------------------------------------------------------------------

def test_parse_results_edgeR_layout(tmp_path: Path) -> None:
    (tmp_path / "All_Contrast_DEG_Statistics.csv").write_text(
        '"Contrast","Control","Treat","Method","Dispersion_Assumption","N_Control","N_Treat","Up_Regulated","Down_Regulated","Total_DEG"\n'
        '"Treat_vs_WT","WT","Treat","edgeR-QLF","trended+tagwise (common BCV=0.321)",3,3,2,6,8\n'
        '"Rescue_vs_KO","KO","Rescue","edgeR-NoRep","fixed BCV=0.40 (dispersion=0.1600)",1,1,8,5,13\n',
        encoding="utf-8",
    )
    (tmp_path / "Treat_vs_WT_DEG.csv").write_text(
        '"ENSEMBL","log2FoldChange","logCPM","pvalue","padj","Symbol"\n'
        '"ENSG1",-2.5,10.0,0.005,0.9,"Gene1"\n'
        '"ENSG2",2.3,9.9,0.009,0.95,"Gene2"\n',
        encoding="utf-8",
    )
    (tmp_path / "Rescue_vs_KO_DEG.csv").write_text(
        '"ENSEMBL","log2FoldChange","logCPM","pvalue","padj","Symbol"\n'
        '"ENSG3",1.8,8.0,0.02,1.0,"Gene3"\n',
        encoding="utf-8",
    )
    for name in (
        "Global_PCA_Combined.png",
        "Treat_vs_WT_Volcano.png",
        "Treat_vs_WT_Volcano_add_gene_id.png",
        "edger.log",
    ):
        (tmp_path / name).write_bytes(b"x")

    result = _parse_results(tmp_path, "edger", "task-123")
    assert result.engine == "edger"
    assert [s.contrast for s in result.statistics] == ["Treat_vs_WT", "Rescue_vs_KO"]
    assert result.statistics[1].method == "edgeR-NoRep"
    assert result.statistics[0].total_deg == 8
    assert result.no_replicate_contrasts == ["Rescue_vs_KO"]
    treat_vs_wt = result.contrasts[0]
    assert treat_vs_wt.total_genes == 2
    assert treat_vs_wt.top_genes[0].ensembl == "ENSG1"
    assert treat_vs_wt.top_genes[0].log_cpm == 10.0
    assert treat_vs_wt.top_genes[0].base_mean is None
    assert treat_vs_wt.volcano_png == "Treat_vs_WT_Volcano.png"
    assert result.pca_png == "Global_PCA_Combined.png"
    assert result.log_file == "edger.log"
    assert "All_Contrast_DEG_Statistics.csv" in result.artifacts


def test_parse_results_deseq2_layout(tmp_path: Path) -> None:
    (tmp_path / "All_Contrast_DEG_Statistics.csv").write_text(
        '"Contrast","Control","Treat","Up_Regulated","Down_Regulated","Total_DEG","LFC_Cutoff","Pvalue_Cutoff"\n'
        '"Treat_vs_WT","WT","Treat",2,6,8,1,0.05\n',
        encoding="utf-8",
    )
    (tmp_path / "Treat_vs_WT_DEG.csv").write_text(
        '"ENSEMBL","baseMean","log2FoldChange","lfcSE","stat","pvalue","padj","Symbol"\n'
        '"ENSG9",120.5,-1.7,0.3,-5.6,0.001,0.4,"Gene9"\n',
        encoding="utf-8",
    )
    result = _parse_results(tmp_path, "deseq2", "task-456")
    row = result.contrasts[0].top_genes[0]
    assert row.base_mean == 120.5
    assert row.log_cpm is None
    assert result.contrasts[0].stat.method == ""
    assert result.no_replicate_contrasts == []
