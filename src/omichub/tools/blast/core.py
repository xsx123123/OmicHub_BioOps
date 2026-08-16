"""BLAST 工具核心逻辑（与队列解耦）。

同时被 Celery task 与同步服务调用；负责序列检测、命令构建、外部二进制执行、
XML 解析与结果格式化。
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from omichub.core.config import get_settings
from omichub.core.exceptions import TaskExecutionError
from omichub.tools.blast.config import config_manager
from omichub.tools.blast.schema import BlastHitDTO, BlastStatisticsDTO

logger = logging.getLogger(__name__)

NUCL_PATTERN = re.compile(r"^[ATCGUatcguNRYMKSWHBVDnrymkswhbvd\-]+$")
PROT_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYacdefghiklmnpqrstvwy\-]+$")


def detect_sequence_type(sequence: str) -> str:
    """根据字符集判断序列类型：nucl / prot / unknown。"""
    cleaned = "".join(sequence.split()).upper()
    if len(cleaned) < 5:
        return "unknown"
    if NUCL_PATTERN.fullmatch(cleaned):
        return "nucl"
    if PROT_PATTERN.fullmatch(cleaned):
        return "prot"
    # 混合字符集时，若仅含氨基酸字母（含 IUPAC 核酸字符子集）按核酸处理
    only_acgt = set("ACGTUNRYMKSWHBVD")
    chars = set(cleaned)
    if chars <= only_acgt:
        return "nucl"
    return "unknown"


def parse_fasta(fasta_text: str) -> tuple[str, str]:
    """解析 FASTA 文本，返回 (title, sequence)。

    若文本无 > 头，则标题使用空字符串，全部内容作为序列。
    """
    lines = [line.strip() for line in fasta_text.strip().splitlines()]
    title = ""
    seq_lines: list[str] = []
    in_header = False
    for line in lines:
        if not line:
            continue
        if line.startswith(">"):
            if not in_header:
                title = line[1:].strip().split()[0]
                in_header = True
            continue
        seq_lines.append(line)
    sequence = "".join(seq_lines)
    return title, sequence


def ensure_fasta(query_sequence: str, query_title: str) -> str:
    """确保查询序列为 FASTA 格式；若不是则自动包装。"""
    text = query_sequence.strip()
    if text.startswith(">"):
        return text
    title = query_title.strip() or "query"
    return f">{title}\n{text}"


def infer_program(query_type: str, db_type: str) -> str:
    """根据查询序列类型和数据库类型推断 BLAST program。"""
    cfg = config_manager.get_config()
    program = cfg.program_for(query_type, db_type)
    if program:
        return program
    # 兜底映射
    mapping = {
        ("nucl", "nucl"): "blastn",
        ("prot", "prot"): "blastp",
        ("nucl", "prot"): "blastx",
        ("prot", "nucl"): "tblastn",
    }
    return mapping.get((query_type, db_type), "blastn")


def _binary_name(program: str) -> str:
    return program


def build_blast_command(
    program: str,
    query_path: Path,
    db_path: str,
    output_path: Path,
    *,
    evalue: float = 1e-5,
    max_target_seqs: int = 10,
    word_size: int | None = None,
    gapopen: int | None = None,
    gapextend: int | None = None,
    outfmt: int = 5,
    num_threads: int = 4,
) -> list[str]:
    """构建 blast 命令列表（本地子进程模式）。"""
    cmd = [
        _binary_name(program),
        "-query",
        str(query_path),
        "-db",
        db_path,
        "-evalue",
        str(evalue),
        "-max_target_seqs",
        str(max_target_seqs),
        "-outfmt",
        str(outfmt),
        "-out",
        str(output_path),
        "-num_threads",
        str(num_threads),
    ]
    if word_size is not None:
        cmd.extend(["-word_size", str(word_size)])
    if gapopen is not None:
        cmd.extend(["-gapopen", str(gapopen)])
    if gapextend is not None:
        cmd.extend(["-gapextend", str(gapextend)])
    return cmd


def build_docker_blast_command(
    program: str,
    query_path: Path,
    db_path: Path,
    output_path: Path,
    *,
    evalue: float = 1e-5,
    max_target_seqs: int = 10,
    word_size: int | None = None,
    gapopen: int | None = None,
    gapextend: int | None = None,
    outfmt: int = 5,
    num_threads: int = 4,
    docker_image: str = "ncbi/blast:latest",
) -> list[str]:
    """构建 docker 模式 blast 命令列表。"""
    # 挂载目录：数据库父目录只读，查询文件目录只读，结果目录可写
    db_dir = Path(db_path).parent
    db_name = Path(db_path).name
    query_dir = query_path.parent
    result_dir = output_path.parent

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{db_dir}:/blast_db:ro",
        "-v",
        f"{query_dir}:/query:ro",
        "-v",
        f"{result_dir}:/results",
        docker_image,
        program,
        "-query",
        f"/query/{query_path.name}",
        "-db",
        f"/blast_db/{db_name}",
        "-evalue",
        str(evalue),
        "-max_target_seqs",
        str(max_target_seqs),
        "-outfmt",
        str(outfmt),
        "-out",
        f"/results/{output_path.name}",
        "-num_threads",
        str(num_threads),
    ]
    if word_size is not None:
        cmd.extend(["-word_size", str(word_size)])
    if gapopen is not None:
        cmd.extend(["-gapopen", str(gapopen)])
    if gapextend is not None:
        cmd.extend(["-gapextend", str(gapextend)])
    return cmd


def run_command(
    cmd: list[str], timeout: int, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """执行外部命令，统一错误处理。"""
    logger.info("执行命令: %s", " ".join(cmd))
    binary = cmd[0]
    if binary != "docker" and shutil.which(binary) is None:
        raise TaskExecutionError(f"找不到 BLAST 二进制: {binary}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "未知错误"
        raise TaskExecutionError(f"BLAST 执行失败: {stderr}")
    return result


def _extract_hit_id(
    hit_def: str,
    hit_accession: str,
    hit_id_raw: str,
) -> tuple[str, str]:
    """从 Hit 节点提取序列 ID 和描述信息。

    策略:
    1. 优先取 Hit_accession（如果非数字且非空）
    2. 其次解析 Hit_id（处理 lcl|Chr1, gnl|BL_ORD_ID|0 格式）
    3. 最后回退 Hit_def 按空格切分
    """
    # 策略 1: Hit_accession 非数字且非空
    if hit_accession and not hit_accession.isdigit():
        return hit_accession.strip(), hit_def.strip()

    # 策略 2: 解析 Hit_id（如 lcl|Chr1, gnl|BL_ORD_ID|0）
    if hit_id_raw and "|" in hit_id_raw:
        parts = hit_id_raw.split("|")
        candidate = parts[-1].strip() if parts else ""
        if candidate and not candidate.isdigit():
            return candidate, hit_def.strip()

    # 策略 3: 从 Hit_def 按空格切分
    if hit_def:
        parts = hit_def.split(" ", 1)
        hit_id = parts[0].strip()
        hit_desc = parts[1].strip() if len(parts) > 1 else ""
        # 如果 hit_id 是纯数字，尝试从描述中提取
        if hit_id.isdigit() and hit_desc:
            sub_parts = hit_desc.split(" ", 1)
            if sub_parts[0] and not sub_parts[0].isdigit():
                hit_id = sub_parts[0]
                hit_desc = sub_parts[1] if len(sub_parts) > 1 else ""
        return hit_id, hit_desc

    return "", ""


def _parse_hsp(hsp: Any) -> dict[str, Any]:
    """解析单个 HSP 元素，返回完整字段字典。"""

    def _text(tag: str, elem: Any = hsp) -> str:
        child = elem.find(tag)
        return child.text or "" if child is not None else ""

    def _int(tag: str, elem: Any = hsp) -> int:
        text = _text(tag, elem)
        return int(text) if text else 0

    def _float(tag: str, elem: Any = hsp) -> float:
        text = _text(tag, elem)
        return float(text) if text else 0.0

    identity = _int("Hsp_identity")
    align_len = _int("Hsp_align-len")
    return {
        "hsp_num": _int("Hsp_num"),
        "bit_score": _float("Hsp_bit-score"),
        "evalue": _float("Hsp_evalue"),
        "query_from": _int("Hsp_query-from"),
        "query_to": _int("Hsp_query-to"),
        "hit_from": _int("Hsp_hit-from"),
        "hit_to": _int("Hsp_hit-to"),
        "identity": identity,
        "align_length": align_len,
        "mismatches": _int("Hsp_mismatches"),
        "gaps": _int("Hsp_gaps"),
        "query_seq": _text("Hsp_qseq"),
        "hit_seq": _text("Hsp_hseq"),
        "midline": _text("Hsp_midline"),
        "identity_percent": round((identity / align_len) * 100, 2) if align_len else 0.0,
    }


def parse_blast_xml(xml_path: Path) -> dict[str, Any]:
    """解析 BLAST XML（outfmt 5），提取命中列表与统计信息。"""
    if not xml_path.exists():
        raise TaskExecutionError(f"结果文件不存在: {xml_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    query_id = ""
    query_def = ""
    query_len = 0
    program = root.findtext(".//BlastOutput_program", "")
    db_name = root.findtext(".//BlastOutput_db", "")

    iteration = root.find(".//Iteration")
    if iteration is not None:
        qid = iteration.find("Iteration_query-ID")
        qdef = iteration.find("Iteration_query-def")
        qlen = iteration.find("Iteration_query-len")
        if qid is not None and qid.text:
            query_id = qid.text
        if qdef is not None and qdef.text:
            query_def = qdef.text
        if qlen is not None and qlen.text:
            query_len = int(qlen.text)

    hits: list[dict[str, Any]] = []
    for hit in root.findall(".//Hit"):
        hit_def_text = hit.findtext("Hit_def", "")
        hit_accession = hit.findtext("Hit_accession", "")
        hit_id_raw = hit.findtext("Hit_id", "")
        hit_id, hit_desc = _extract_hit_id(hit_def_text, hit_accession, hit_id_raw)

        hit_len = int(hit.findtext("Hit_len", "0") or "0")

        hsps = [_parse_hsp(hsp) for hsp in hit.findall(".//Hsp")]
        if not hsps:
            continue

        best_hsp = hsps[0]
        identity_percent = round((best_hsp["identity"] / best_hsp["align_length"]) * 100, 2) if best_hsp["align_length"] else 0.0

        # 从 best_hsp 的 midline 重新计算 mismatches（空格表示错配）
        mismatches = sum(1 for c in best_hsp["midline"] if c == " ") if best_hsp["midline"] else best_hsp["mismatches"]

        hits.append(
            {
                "hit_num": int(hit.findtext("Hit_num", "0") or "0"),
                "hit_id": hit_id,
                "hit_def": hit_desc,
                "hit_accession": hit_accession,
                "hit_len": hit_len,
                "subject_id": hit_id or hit_accession or hit_def_text,
                "identity": identity_percent,
                "identity_percent": identity_percent,
                "align_length": best_hsp["align_length"],
                "mismatches": mismatches,
                "gap_opens": best_hsp["gaps"],
                "q_start": best_hsp["query_from"],
                "q_end": best_hsp["query_to"],
                "s_start": best_hsp["hit_from"],
                "s_end": best_hsp["hit_to"],
                "evalue": best_hsp["evalue"],
                "bit_score": best_hsp["bit_score"],
                "score": int(hit.findtext("Hit_score", "0") or "0"),
                "query_seq": best_hsp["query_seq"],
                "subject_seq": best_hsp["hit_seq"],
                "midline": best_hsp["midline"],
                "query_coverage": round((best_hsp["align_length"] / query_len) * 100, 2) if query_len else 0.0,
                "subject_coverage": round((best_hsp["align_length"] / hit_len) * 100, 2) if hit_len else 0.0,
                "total_score": sum(h["bit_score"] for h in hsps),
                "best_hsp": best_hsp,
                "hsps": [
                    {
                        "query_from": h["query_from"],
                        "query_to": h["query_to"],
                        "hit_from": h["hit_from"],
                        "hit_to": h["hit_to"],
                        "identity_percent": h["identity_percent"],
                        "evalue": h["evalue"],
                        "bit_score": h["bit_score"],
                    }
                    for h in hsps
                ],
            }
        )

    # 保持原有 BlastHitDTO 兼容：将字典转换为 DTO 对象
    hit_dtos: list[BlastHitDTO] = []
    for hit in hits:
        hit_dtos.append(
            BlastHitDTO(
                query_id=query_id or query_def,
                subject_id=hit["subject_id"],
                identity=hit["identity"],
                align_length=hit["align_length"],
                mismatches=hit["mismatches"],
                gap_opens=hit["gap_opens"],
                q_start=hit["q_start"],
                q_end=hit["q_end"],
                s_start=hit["s_start"],
                s_end=hit["s_end"],
                evalue=hit["evalue"],
                bit_score=hit["bit_score"],
                score=hit["score"],
                query_seq=hit["query_seq"],
                subject_seq=hit["subject_seq"],
                midline=hit["midline"],
                query_coverage=hit["query_coverage"],
                subject_coverage=hit["subject_coverage"],
            )
        )

    stats = {
        "hit_count": len(hits),
        "top_hit_identity": hits[0]["identity"] if hits else None,
        "top_hit_evalue": hits[0]["evalue"] if hits else None,
        "query_id": query_id,
        "query_def": query_def,
        "query_len": query_len,
        "program": program,
        "db_name": db_name,
        "hits": hits,
        "hit_dtos": hit_dtos,
    }
    return stats


def convert_blast_archive(archive_path: Path, output_path: Path, outfmt: int) -> None:
    """使用 blast_formatter 将 ASN.1 archive 转换为指定输出格式。"""
    if shutil.which("blast_formatter") is None:
        raise TaskExecutionError("找不到 BLAST 二进制: blast_formatter")
    cmd = [
        "blast_formatter",
        "-archive",
        str(archive_path),
        "-out",
        str(output_path),
        "-outfmt",
        str(outfmt),
    ]
    run_command(cmd, timeout=300)


def run_blast_search(
    *,
    task_id: str,
    user_id: str,
    program: str,
    query_sequence: str,
    query_title: str,
    db_path: str,
    evalue: float,
    max_target_seqs: int,
    word_size: int | None,
    gapopen: int | None,
    gapextend: int | None,
    work_dir: Path,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """执行一次 BLAST 查询，返回结构化结果字典。"""
    settings = get_settings()
    cfg = config_manager.get_config()
    exec_cfg = cfg.execution

    work_dir.mkdir(parents=True, exist_ok=True)
    query_file = work_dir / "query.fasta"
    archive_file = work_dir / "result.asn"
    xml_file = work_dir / "result.xml"
    text_file = work_dir / "result.txt"

    fasta_text = ensure_fasta(query_sequence, query_title)
    query_file.write_text(fasta_text, encoding="utf-8")

    use_docker = exec_cfg.use_docker
    num_threads = exec_cfg.num_threads or settings.blast_num_threads
    timeout = exec_cfg.search_timeout or settings.blast_search_timeout

    if use_docker:
        cmd = build_docker_blast_command(
            program=program,
            query_path=query_file,
            db_path=Path(db_path),
            output_path=archive_file,
            evalue=evalue,
            max_target_seqs=max_target_seqs,
            word_size=word_size,
            gapopen=gapopen,
            gapextend=gapextend,
            outfmt=11,
            num_threads=num_threads,
            docker_image=exec_cfg.docker_image or settings.blast_docker_image,
        )
    else:
        cmd = build_blast_command(
            program=program,
            query_path=query_file,
            db_path=db_path,
            output_path=archive_file,
            evalue=evalue,
            max_target_seqs=max_target_seqs,
            word_size=word_size,
            gapopen=gapopen,
            gapextend=gapextend,
            outfmt=11,
            num_threads=num_threads,
        )

    if progress_callback:
        progress_callback("running", 30, "正在执行 BLAST 比对...")

    run_command(cmd, timeout=timeout)

    if progress_callback:
        progress_callback("running", 70, "正在生成并解析比对结果...")

    convert_blast_archive(archive_file, xml_file, 5)
    stats = parse_blast_xml(xml_file)

    try:
        convert_blast_archive(archive_file, text_file, 0)
    except Exception:
        logger.exception("生成文本格式失败")
        text_file = None  # type: ignore[assignment]

    return {
        "status": "COMPLETED",
        "task_id": task_id,
        "xml_path": str(xml_file),
        "text_path": str(text_file) if text_file and text_file.exists() else None,
        "hit_count": stats["hit_count"],
        "top_hit_identity": stats["top_hit_identity"],
        "top_hit_evalue": stats["top_hit_evalue"],
        "hits": [h.model_dump() for h in stats["hit_dtos"]],
    }


def build_blast_database(
    *,
    db_dir: Path,
    db_key: str,
    db_type: str,
    source_fasta: Path,
    timeout: int = 3600,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """执行 makeblastdb 构建数据库索引。"""
    settings = get_settings()
    cfg = config_manager.get_config()
    exec_cfg = cfg.execution

    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / db_key
    temporary_key = f".{db_key}.building-{uuid.uuid4().hex}"
    temporary_path = db_dir / temporary_key

    use_docker = exec_cfg.use_docker
    docker_image = exec_cfg.docker_image or settings.blast_docker_image

    if use_docker:
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{db_dir}:/work",
            docker_image,
            "makeblastdb",
            "-in",
            f"/work/{source_fasta.name}",
            "-dbtype",
            db_type,
            "-out",
            f"/work/{temporary_key}",
            "-parse_seqids",
            "-hash_index",
        ]
    else:
        if shutil.which("makeblastdb") is None:
            raise TaskExecutionError("找不到 makeblastdb 二进制")
        cmd = [
            "makeblastdb",
            "-in",
            str(source_fasta),
            "-dbtype",
            db_type,
            "-out",
            str(temporary_path),
            "-parse_seqids",
            "-hash_index",
        ]

    if progress_callback:
        progress_callback("building", 30, "正在构建 BLAST 数据库索引...")

    try:
        result = run_command(cmd, timeout=timeout)
    except Exception:
        for temporary_file in db_dir.glob(f"{temporary_key}.*"):
            temporary_file.unlink(missing_ok=True)
        raise

    if progress_callback:
        progress_callback("building", 80, "正在验证索引文件...")

    # 验证索引文件
    suffixes = [".nhr", ".nin", ".nsq"] if db_type == "nucl" else [".phr", ".pin", ".psq"]
    temporary_files = [Path(f"{temporary_path}{suffix}") for suffix in suffixes]
    for expected in temporary_files:
        if not expected.exists():
            for temporary_file in db_dir.glob(f"{temporary_key}.*"):
                temporary_file.unlink(missing_ok=True)
            raise TaskExecutionError(f"缺少索引文件: {expected}")

    for temporary_file in db_dir.glob(f"{temporary_key}.*"):
        final_file = db_dir / temporary_file.name.replace(temporary_key, db_key, 1)
        temporary_file.replace(final_file)

    # 统计序列数量
    seq_count = _count_fasta_sequences(source_fasta)
    total_size = sum(Path(f"{db_path}{suffix}").stat().st_size for suffix in suffixes)

    return {
        "status": "COMPLETED",
        "sequence_count": seq_count,
        "file_size_mb": round(total_size / (1024 * 1024), 2),
        "build_log": result.stdout + "\n" + result.stderr,
    }


def _count_fasta_sequences(fasta_path: Path) -> int:
    """统计 FASTA 文件中的序列条数。"""
    count = 0
    with fasta_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith(">"):
                count += 1
    return count


def make_statistics(
    db_name: str, program: str, query_title: str, stats: dict[str, Any]
) -> BlastStatisticsDTO:
    """构造统计摘要 DTO。"""
    return BlastStatisticsDTO(
        hit_count=stats.get("hit_count", 0),
        top_hit_identity=stats.get("top_hit_identity"),
        top_hit_evalue=stats.get("top_hit_evalue"),
        db_name=db_name,
        program=program,
        query_title=query_title,
    )
