import argparse
import json
import yaml
import os
from pathlib import Path
from datetime import datetime

def update_json_config(client, species, genome, pipeline_version, output_path):
    """更新 data/project_summary.json"""
    default_data = {
        "project_meta": {
            "client": client,
            "species": species,
            "genome_version": genome,
            "pipeline_version": pipeline_version,
            "analysis_date": datetime.now().strftime("%Y-%m-%d")
        },
        "stats": {
            # 这些统计数据通常应该由 upstream pipeline 填充，这里仅作为元数据示例
            # 实际生产中，你可能需要读取 multiqc_data.json 来自动填充这里
            "total_samples": 0, 
            "group_count": 0
        },
        "input_files": {
            "data_dir": "../data/index/",
            "qc_file": "multiqc_qc_general_stats.txt",
            "mapping_file": "multiqc_mapping_general_stats.txt",
            "tpm_file": "merge_rsem_tpm.tsv",
            "sample_file": "sample.csv",
            # 新增 QC 相关目录
            "fastp_report_dir": "../data/fastp_trim_report/multiqc_short_read_trim_report_data",
            "fastp_stats_file": "../data/fastp_trim_report/multiqc_general_stats.txt",
            "fastq_screen_r1_dir": "../data/fastq_screen_report/fastq_screen_multiqc_r1/multiqc_r1_fastq_screen_report_data",
            "fastq_screen_r2_dir": "../data/fastq_screen_report/fastq_screen_multiqc_r2/multiqc_r2_fastq_screen_report_data",
            "qualimap_dir": "../data/QualiMap/multiqc_data/",
            # 新增 Results 相关目录
            "contrasts_file": "../data/index/contrasts.csv",
            "deg_dir": "../data/res/DEG",
            "enrichment_dir": "../data/res/Enrichments"
        }
    }

    # 如果文件存在，读取并更新（保留原有 stats 数据，只更新 meta）
    if os.path.exists(output_path):
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            
            # 深度更新 project_meta
            if "project_meta" not in existing_data:
                existing_data["project_meta"] = {}
            existing_data["project_meta"].update(default_data["project_meta"])
            
            # 更新 input_files (如果不存在则添加)
            if "input_files" not in existing_data:
                existing_data["input_files"] = default_data["input_files"]
            else:
                existing_data["input_files"].update(default_data["input_files"])

            final_data = existing_data
            print(f"✅ 已更新现有配置: {output_path}")
        except json.JSONDecodeError:
            print(f"⚠️  现有文件损坏，覆盖创建: {output_path}")
            final_data = default_data
    else:
        final_data = default_data
        print(f"✅ 创建新配置: {output_path}")

    # 写入
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)

def update_quarto_yaml(title, yaml_path):
    """更新 _quarto.yml 中的标题"""
    if not os.path.exists(yaml_path):
        print(f"❌ 找不到 _quarto.yml: {yaml_path}")
        return

    try:
        # 使用 safe_load 读取
        with open(yaml_path, 'r', encoding='utf-8') as f:
            # 注意：标准 pyyaml 不保留注释。如果需要保留注释，需要使用 ruamel.yaml
            # 这里为了演示简单，假设用户接受重写。如果非常介意注释，建议手动修改或使用高级库。
            # 为了安全起见，我们这里只读取 title，如果 title 变了才重写，尽量避免触碰
            content = f.read()
        
        # 简单的字符串替换策略（比 yaml 解析更安全，能保留注释）
        # 寻找 `title: "..."` 模式
        import re
        new_title_line = f'title: "{title}"'
        
        # 正则替换 title 行
        pattern = re.compile(r'^title:\s*["\'].*["\']', re.MULTILINE)
        
        if pattern.search(content):
            new_content = pattern.sub(new_title_line, content)
            if new_content != content:
                with open(yaml_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"✅ 报告标题已更新为: {title}")
            else:
                print("ℹ️  报告标题未变更")
        else:
            print("⚠️  未在 _quarto.yml 中找到标准 title 字段，跳过更新。")

    except Exception as e:
        print(f"❌ 更新 _quarto.yml 失败: {e}")

def main():
    parser = argparse.ArgumentParser(description="BFP Report Configuration Tool")
    
    # 定义参数
    parser.add_argument("--client", help="客户名称", default="未指定客户")
    parser.add_argument("--species", help="物种名称", default="Unknown")
    parser.add_argument("--genome", help="基因组版本", default="Unknown")
    parser.add_argument("--pipeline", help="流程版本", default="RNAFlow v2.x")
    parser.add_argument("--title", help="报告主标题", default=None)
    
    # 路径参数
    parser.add_argument("--json_out", help="JSON输出路径", default="../data/project_summary.json")
    parser.add_argument("--yaml_out", help="Quarto YAML路径", default="../_quarto.yml")

    args = parser.parse_args()

    # 1. 确定路径 (相对于脚本所在目录)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.abspath(os.path.join(script_dir, args.json_out))
    yaml_path = os.path.abspath(os.path.join(script_dir, args.yaml_out))

    # 2. 更新 JSON
    update_json_config(args.client, args.species, args.genome, args.pipeline, json_path)

    # 3. 更新 YAML (如果提供了 title)
    if args.title:
        update_quarto_yaml(args.title, yaml_path)

if __name__ == "__main__":
    main()
