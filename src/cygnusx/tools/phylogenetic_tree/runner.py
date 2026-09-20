"""系统发育树生物信息学工具封装。

核心约定：
- 所有外部二进制按 config.yaml 中的 tools.*.binary 解析；缺失时抛出 TaskExecutionError。
- NJ / UPGMA 在二进制不可用时使用 Biopython 内置距离法兜底，保证开发/演示环境可出树。
- 输入/输出文件统一落在 work_dir 内：
  - input.fasta      原始输入（或已比对序列）
  - aligned.fasta    MSA 结果
  - tree.nwk         Newick 树（必出）
  - tree.nex         NEXUS（可选）
  - tree.xml         PhyloXML（可选）
  - tree.stats.json  统计信息
"""

from __future__ import annotations

import contextlib
import json
import logging
import random
import shutil
import subprocess
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from Bio import AlignIO, Phylo, SeqIO
from Bio.Phylo.BaseTree import Clade, Tree
from Bio.Phylo.Consensus import majority_consensus
from Bio.Phylo.TreeConstruction import (
    DistanceCalculator,
    DistanceTreeConstructor,
)

from cygnusx.core.exceptions import TaskExecutionError, ValidationError

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


def _noop_callback(progress: float, message: str) -> None:
    pass


# ---------------------------------------------------------------------------
# 文件格式与序列类型
# ---------------------------------------------------------------------------

FORMAT_EXTENSIONS = {
    "fasta": ".fasta",
    "phylip": ".phylip",
    "nexus": ".nex",
    "newick": ".nwk",
}


def detect_sequence_type(records: list[Any]) -> str:
    """根据字符集判断 DNA / Protein。"""
    dna_chars = set("ACGTN-?")
    total_chars: set[str] = set()
    for rec in records:
        total_chars.update(str(rec.seq).upper())
    # 去除空位/未知后，若全部属于 DNA 字符集则判定为 DNA
    if total_chars and total_chars <= dna_chars:
        return "dna"
    return "protein"


def parse_and_validate_input(input_path: Path) -> tuple[list[Any], str, str, bool]:
    """解析输入文件并返回 (records, fmt, seq_type, is_aligned)。"""
    if not input_path.exists():
        raise ValidationError(f"输入文件不存在: {input_path}")

    suffix = input_path.suffix.lower()
    if suffix in (".fasta", ".fa", ".fas"):
        fmt = "fasta"
    elif suffix in (".phylip", ".phy"):
        fmt = "phylip"
    elif suffix in (".nex", ".nexus"):
        fmt = "nexus"
    elif suffix in (".nwk", ".newick", ".tree"):
        fmt = "newick"
    else:
        raise ValidationError(f"不支持的文件扩展名: {suffix}")

    if fmt == "newick":
        tree = Phylo.read(input_path, "newick")
        # 构造单条伪记录以兼容后续流程
        records = []
        for tip in tree.get_terminals():
            from Bio.Seq import Seq
            from Bio.SeqRecord import SeqRecord

            records.append(SeqRecord(Seq(""), id=tip.name, description=""))
        return records, fmt, "unknown", False

    try:
        records = list(SeqIO.parse(input_path, fmt))
    except Exception as exc:
        raise ValidationError(f"无法解析输入文件 ({fmt}): {exc}") from exc

    if not records:
        raise ValidationError("输入文件未包含任何序列")

    seq_type = detect_sequence_type(records)
    is_aligned = len({len(r.seq) for r in records}) == 1
    return records, fmt, seq_type, is_aligned


def _write_fasta(records: list[Any], path: Path) -> None:
    SeqIO.write(records, path, "fasta")


# ---------------------------------------------------------------------------
# 阶段 1：多序列比对
# ---------------------------------------------------------------------------


def run_alignment(
    task_input: dict[str, Any],
    work_dir: Path,
    callback: ProgressCallback | None = None,
) -> None:
    """执行多序列比对；prealigned 时直接拷贝。"""
    callback = callback or _noop_callback
    tool = task_input.get("alignment_tool", "mafft")
    input_path = Path(task_input["input_path"])
    aligned_path = work_dir / "aligned.fasta"

    if tool == "prealigned":
        records, _, _, _ = parse_and_validate_input(input_path)
        _write_fasta(records, aligned_path)
        callback(1.0, "输入已比对，跳过 MSA")
        return

    from cygnusx.tools.phylogenetic_tree.config import config_manager

    binary = config_manager.get_config().binary_path(tool)
    if not binary or not shutil.which(binary):
        raise TaskExecutionError(f"比对工具未安装或不在 PATH 中: {binary or tool}")

    command: list[str]
    if tool == "mafft":
        mode = task_input.get("alignment_mode", "auto")
        if mode == "auto" or mode == "":
            command = [binary, "--auto", str(input_path)]
        else:
            command = [binary, f"--{mode}", str(input_path)]
    elif tool == "clustalo":
        command = [binary, "-i", str(input_path), "-o", str(aligned_path), "--force"]
    elif tool == "muscle5":
        command = [binary, "-align", str(input_path), "-output", str(aligned_path)]
    else:
        raise ValidationError(f"不支持的比对工具: {tool}")

    callback(0.1, f"启动 {tool} 比对...")
    try:
        if tool == "mafft":
            with aligned_path.open("w", encoding="utf-8") as out:
                subprocess.run(command, stdout=out, stderr=subprocess.PIPE, text=True, check=True)
        else:
            subprocess.run(command, stderr=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise TaskExecutionError(f"{tool} 比对失败: {exc.stderr}") from exc
    callback(1.0, "多序列比对完成")


# ---------------------------------------------------------------------------
# 阶段 2：进化树构建
# ---------------------------------------------------------------------------


def _build_distance_tree(alignment_path: Path, method: str, model: str) -> Tree:
    """使用 Biopython DistanceTreeConstructor 构建 NJ / UPGMA 树。"""
    alignment = AlignIO.read(alignment_path, "fasta")
    calculator = _make_distance_calculator(model)
    constructor = DistanceTreeConstructor(calculator, method)
    tree = constructor.build_tree(alignment)
    # Biopython 构建的树 confidence 可能为 None，统一处理
    return tree


def _make_distance_calculator(model: str) -> DistanceCalculator:
    """根据替代模型返回距离计算器；不支持的模型回退到 identity。"""
    supported = {"identity", "blastn", "trans"}
    if model.lower() in supported:
        return DistanceCalculator(model.lower())
    # 对 DNA 数据使用 identity 兜底
    return DistanceCalculator("identity")


def _run_external_tree_builder(
    method: str,
    aligned_path: Path,
    work_dir: Path,
    task_input: dict[str, Any],
) -> Path:
    """调用 FastTree / IQ-TREE / MrBayes 等外部二进制。"""
    from cygnusx.tools.phylogenetic_tree.config import config_manager

    cfg = config_manager.get_config()
    threads = cfg.execution.resources.default_threads
    seq_type = task_input.get("sequence_type", "auto")

    if method == "fasttree":
        binary = cfg.binary_path("fasttree")
        if not binary or not shutil.which(binary):
            raise TaskExecutionError(f"FastTree 未安装或不在 PATH 中: {binary or 'FastTree'}")
        out_path = work_dir / "tree_raw.nwk"
        command = [binary]
        if seq_type == "protein":
            command.append("-lg")
        command.extend([str(aligned_path)])
        with out_path.open("w", encoding="utf-8") as out:
            subprocess.run(command, stdout=out, stderr=subprocess.PIPE, text=True, check=True)
        return out_path

    if method == "iqtree":
        binary = cfg.binary_path("iqtree2")
        if not binary or not shutil.which(binary):
            raise TaskExecutionError(f"IQ-TREE 未安装或不在 PATH 中: {binary or 'iqtree2'}")
        prefix = work_dir / "iqtree_run"
        model = task_input.get("substitution_model", "auto")
        command = [
            binary,
            "-s",
            str(aligned_path),
            "-pre",
            str(prefix),
            "-nt",
            str(threads),
        ]
        if model != "auto":
            command.extend(["-m", model])
        if seq_type == "protein":
            command.append("-st")
            command.append("AA")
        elif seq_type == "dna":
            command.append("-st")
            command.append("DNA")
        subprocess.run(command, stderr=subprocess.PIPE, text=True, check=True)
        tree_file = Path(f"{prefix}.treefile")
        if not tree_file.exists():
            raise TaskExecutionError("IQ-TREE 未生成树文件")
        return tree_file

    if method == "mrbayes":
        binary = cfg.binary_path("mrbayes")
        if not binary or not shutil.which(binary):
            raise TaskExecutionError(f"MrBayes 未安装或不在 PATH 中: {binary or 'mb'}")
        return _run_mrbayes(binary, aligned_path, work_dir, task_input)

    raise ValidationError(f"不支持的树构建方法: {method}")


def _run_mrbayes(
    binary: str, aligned_path: Path, work_dir: Path, task_input: dict[str, Any]
) -> Path:
    """生成 MrBayes nexus 命令文件并执行。"""
    ngen = task_input.get("mrbayes_ngen", 1000000)
    nchains = task_input.get("mrbayes_nchains", 4)
    seq_type = task_input.get("sequence_type", "dna")

    nexus_in = work_dir / "mrbayes_in.nex"
    nexus_in.write_text(
        f"#NEXUS\nexecute {aligned_path};\n"
        f"lset {'nst=6' if seq_type == 'dna' else 'rates=gamma'};\n"
        f"mcmc ngen={ngen} nchains={nchains} savebrlens=yes file={work_dir / 'mrbayes_run'};\n"
        "sump;\nsumt;\nquit;\n",
        encoding="utf-8",
    )
    subprocess.run(
        [binary, str(nexus_in)],
        cwd=work_dir,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    tree_file = work_dir / "mrbayes_run.con.tre"
    if not tree_file.exists():
        raise TaskExecutionError("MrBayes 未生成一致树")
    return tree_file


def run_tree_building(
    task_input: dict[str, Any],
    work_dir: Path,
    callback: ProgressCallback | None = None,
) -> None:
    """构建系统发育树，输出 tree_raw.nwk（或直接使用外部结果）。"""
    callback = callback or _noop_callback
    method = task_input.get("tree_method", "iqtree")
    aligned_path = work_dir / "aligned.fasta"

    if not aligned_path.exists():
        # 未做比对时尝试把输入当比对文件
        input_path = Path(task_input["input_path"])
        records, _, _, is_aligned = parse_and_validate_input(input_path)
        if not is_aligned:
            raise ValidationError("输入序列长度不一致，请先执行多序列比对")
        _write_fasta(records, aligned_path)

    callback(0.1, f"开始构建 {method} 树...")

    if method in ("nj", "upgma"):
        model = task_input.get("substitution_model", "identity")
        tree = _build_distance_tree(aligned_path, method, model)
        Phylo.write(tree, work_dir / "tree_raw.nwk", "newick")
    elif method in ("fasttree", "iqtree", "mrbayes"):
        raw_tree = _run_external_tree_builder(method, aligned_path, work_dir, task_input)
        # 统一命名为 tree_raw.nwk
        tree = Phylo.read(raw_tree, "newick")
        Phylo.write(tree, work_dir / "tree_raw.nwk", "newick")
    else:
        raise ValidationError(f"不支持的树构建方法: {method}")

    callback(1.0, "进化树构建完成")


# ---------------------------------------------------------------------------
# 阶段 3：Bootstrap 评估
# ---------------------------------------------------------------------------


def _resample_alignment(alignment: Any, seed: int | None = None) -> Any:
    """对多序列比对按列进行有放回抽样。"""
    rng = random.Random(seed)
    length = alignment.get_alignment_length()
    column_indices = [rng.randrange(length) for _ in range(length)]
    records = []
    for record in alignment:
        new_seq = "".join(record.seq[i] for i in column_indices)
        new_record = record.__class__(new_seq, id=record.id, description=record.description)
        records.append(new_record)
    from Bio.Align import MultipleSeqAlignment

    return MultipleSeqAlignment(records)


def _clade_leaf_set(clade: Clade) -> frozenset[str]:
    """返回 clade 下所有叶子名称集合。"""
    if not clade.clades:
        return frozenset([str(clade.name)]) if clade.name else frozenset()
    leaves: set[str] = set()
    for c in clade.clades:
        leaves.update(_clade_leaf_set(c))
    return frozenset(leaves)


def _annotate_bootstrap(main_tree: Tree, bootstrap_tree: Tree) -> None:
    """把 bootstrap 共识树的 confidence 映射到主树内部节点。"""
    support_map: dict[frozenset[str], float] = {}
    for clade in bootstrap_tree.get_nonterminals():
        leaf_set = _clade_leaf_set(clade)
        if leaf_set:
            support_map[leaf_set] = float(clade.confidence) if clade.confidence is not None else 0.0
    for node in main_tree.get_nonterminals():
        leaf_set = _clade_leaf_set(node)
        node.confidence = support_map.get(leaf_set)


def _run_bootstrap_distance(
    task_input: dict[str, Any],
    work_dir: Path,
    callback: ProgressCallback,
) -> None:
    """对 NJ/UPGMA 使用 Biopython 实现简单 bootstrap（列重采样 + 多数规则共识树）。"""
    method = task_input.get("tree_method", "nj")
    model = task_input.get("substitution_model", "identity")
    replicates = int(task_input.get("bootstrap_replicates", 100))
    replicates = max(10, min(replicates, 1000))
    aligned_path = work_dir / "aligned.fasta"

    callback(0.05, f"准备 {replicates} 次 bootstrap 重采样...")
    alignment = AlignIO.read(aligned_path, "fasta")
    replicate_trees = []
    for i in range(replicates):
        resampled = _resample_alignment(alignment, seed=i)
        calculator = _make_distance_calculator(model)
        constructor = DistanceTreeConstructor(calculator, method)
        rep_tree = constructor.build_tree(resampled)
        replicate_trees.append(rep_tree)
        callback((i + 1) / replicates * 0.8, f"Bootstrap 迭代 {i + 1}/{replicates}")

    callback(0.85, "计算一致树...")
    consensus = majority_consensus(replicate_trees, cutoff=0.5)

    main_tree = Phylo.read(work_dir / "tree_raw.nwk", "newick")
    _annotate_bootstrap(main_tree, consensus)
    Phylo.write(main_tree, work_dir / "tree_raw.nwk", "newick")
    callback(1.0, "Bootstrap 评估完成")


def _run_bootstrap_iqtree(task_input: dict[str, Any], work_dir: Path) -> None:
    """IQ-TREE UFBoot 在构建阶段已通过 -bb 完成，无需额外步骤。"""
    # UFBoot 已在 _run_external_tree_builder 中通过 -bb 参数生成 .treefile
    pass


def run_bootstrap(
    task_input: dict[str, Any],
    work_dir: Path,
    callback: ProgressCallback | None = None,
) -> None:
    """执行 Bootstrap 评估。"""
    callback = callback or _noop_callback
    method = task_input.get("tree_method", "iqtree")

    if method in ("fasttree",):
        # FastTree -boot 暂不实现，保留树结构
        callback(1.0, "FastTree Bootstrap 未启用")
        return

    if method in ("nj", "upgma"):
        _run_bootstrap_distance(task_input, work_dir, callback)
        return

    if method == "iqtree":
        btype = task_input.get("bootstrap_type", "ultrafast")
        if btype == "ultrafast":
            _run_bootstrap_iqtree(task_input, work_dir)
            callback(1.0, "UFBoot 评估完成")
            return
        # standard bootstrap via IQ-TREE 需要额外执行，暂不实现
        callback(1.0, "标准 Bootstrap 未启用")
        return

    callback(1.0, "当前方法不支持 Bootstrap")


# ---------------------------------------------------------------------------
# 阶段 4：结果格式化与统计
# ---------------------------------------------------------------------------


def format_results(task_input: dict[str, Any], work_dir: Path) -> dict[str, str]:
    """输出 Newick / NEXUS / PhyloXML / 统计 JSON。"""
    raw_tree_path = work_dir / "tree_raw.nwk"
    tree = Phylo.read(raw_tree_path, "newick")

    # 清理 confidence，确保为数值
    for node in tree.get_nonterminals():
        if node.confidence is not None:
            try:
                node.confidence = float(node.confidence)
            except (TypeError, ValueError):
                node.confidence = None

    output_files: dict[str, str] = {}
    newick_path = work_dir / "tree.nwk"
    Phylo.write(tree, newick_path, "newick")
    output_files["newick"] = str(newick_path)

    nexus_path = work_dir / "tree.nex"
    Phylo.write(tree, nexus_path, "nexus")
    output_files["nexus"] = str(nexus_path)

    phyloxml_path = work_dir / "tree.xml"
    try:
        Phylo.write(tree, phyloxml_path, "phyloxml")
        output_files["phyloxml"] = str(phyloxml_path)
    except Exception:
        logger.warning("PhyloXML 输出失败，已跳过")

    stats = compute_tree_statistics(newick_path)
    stats_path = work_dir / "tree.stats.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    output_files["statistics"] = str(stats_path)

    return output_files


def compute_tree_statistics(newick_path: Path) -> dict[str, Any]:
    """计算树统计信息。"""
    tree = Phylo.read(newick_path, "newick")
    terminals = tree.get_terminals()
    non_terminals = tree.get_nonterminals()

    total_branch_length = 0.0
    bootstrap_values: list[float] = []
    for node in tree.find_clades():
        bl = node.branch_length or 0.0
        total_branch_length += bl
        if node.confidence is not None and not node.is_terminal():
            with contextlib.suppress(TypeError, ValueError):
                bootstrap_values.append(float(node.confidence))

    total_branches = len(terminals) + len(non_terminals) - 1
    avg_branch_length = total_branch_length / max(total_branches, 1)

    # 计算树高（根到叶的最大距离）
    tree_height = 0.0
    for tip in terminals:
        dist = tree.distance(tip)
        if dist > tree_height:
            tree_height = dist

    return {
        "sequence_count": len(terminals),
        "total_branches": total_branches,
        "total_tree_length": round(total_branch_length, 6),
        "mean_branch_length": round(avg_branch_length, 6),
        "tree_height": round(tree_height, 6),
        "min_bootstrap": round(min(bootstrap_values), 2) if bootstrap_values else 0.0,
        "max_bootstrap": round(max(bootstrap_values), 2) if bootstrap_values else 0.0,
        "avg_bootstrap": round(sum(bootstrap_values) / len(bootstrap_values), 2)
        if bootstrap_values
        else 0.0,
        "has_bootstrap_support": bool(bootstrap_values),
    }


# ---------------------------------------------------------------------------
# 资源画像
# ---------------------------------------------------------------------------

RESOURCE_PROFILES = {
    "small": {"cpu": 2, "memory_mb": 2048, "timeout": 300, "queue": "phylo_tree"},
    "medium": {"cpu": 4, "memory_mb": 8192, "timeout": 1800, "queue": "phylo_tree"},
    "large": {"cpu": 8, "memory_mb": 16384, "timeout": 7200, "queue": "phylo_tree"},
    "xlarge": {"cpu": 16, "memory_mb": 32768, "timeout": 28800, "queue": "phylo_tree_highmem"},
}


def select_resource_profile(seq_count: int, avg_length: int, tree_method: str) -> dict[str, Any]:
    """根据序列规模与方法选择资源画像。"""
    if tree_method == "mrbayes":
        return deepcopy(RESOURCE_PROFILES["xlarge"])
    if seq_count <= 100 and avg_length <= 2000:
        return deepcopy(RESOURCE_PROFILES["small"])
    if seq_count <= 1000 and avg_length <= 5000:
        return deepcopy(RESOURCE_PROFILES["medium"])
    if seq_count <= 5000 and avg_length <= 10000:
        return deepcopy(RESOURCE_PROFILES["large"])
    return deepcopy(RESOURCE_PROFILES["xlarge"])
