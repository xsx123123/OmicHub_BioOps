import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

def load_project_metadata(json_path: str, default_client: str = "未指定客户") -> Dict[str, Any]:
    """
    加载项目元数据 JSON 文件。
    如果文件不存在或解析失败，返回带有默认值的字典，确保报告不会报错。
    
    Args:
        json_path (str): JSON 文件的路径
        default_client (str): 默认客户名称
        
    Returns:
        dict: 包含 client, species, genome, software 以及 input_files 的字典
    """
    # 1. 定义默认值 (兜底策略)
    # 基础元数据
    meta_info = {
        "client": default_client,
        "species": "Unknown Species",
        "genome": "Unknown Genome",
        "software": "RNAFlow Pipeline",
        # 默认文件配置 (兜底，防止 JSON 中缺失该字段)
        "input_files": {
            "data_dir": "../data/index/", 
            "qc_file": "multiqc_qc_general_stats.txt",
            "mapping_file": "multiqc_mapping_general_stats.txt",
            "tpm_file": "merge_rsem_tpm.tsv",
            "sample_file": "sample.csv"
        }
    }

    # 2. 检查路径
    file_path = Path(json_path)
    if not file_path.exists():
        print(f"[WARN] Metadata file not found: {json_path}. Using defaults.", file=sys.stderr)
        return meta_info

    # 3. 尝试读取和解析
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # --- 处理 project_meta ---
        source_data = data.get("project_meta", data)
        if isinstance(source_data, dict):
            meta_info["client"] = source_data.get("client", meta_info["client"])
            meta_info["species"] = source_data.get("species", meta_info["species"])
            meta_info["genome"] = source_data.get("genome_version", source_data.get("genome", meta_info["genome"]))
            meta_info["software"] = source_data.get("pipeline_version", source_data.get("software", meta_info["software"]))

        # --- 处理 input_files ---
        if "input_files" in data and isinstance(data["input_files"], dict):
            # 使用 update 进行合并，这样如果 JSON 里只改了 data_dir，其他还是用默认值
            meta_info["input_files"].update(data["input_files"])

    except json.JSONDecodeError:
        print(f"[ERROR] Failed to decode JSON: {json_path}. Using defaults.", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Unexpected error reading metadata: {e}", file=sys.stderr)

    return meta_info
