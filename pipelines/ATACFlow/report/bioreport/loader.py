import json
import pandas as pd
import re
from pathlib import Path
from typing import Dict, Any, List

class BaseLoader:
    def __init__(self, result_dir: str):
        self.result_dir = Path(result_dir)
        if not self.result_dir.exists():
            raise FileNotFoundError(f"Result directory not found: {result_dir}")
        self.data = {}

    def load_json_file(self, filename: str) -> Dict:
        path = self.result_dir / filename
        if not path.exists():
            print(f"Warning: {filename} not found.")
            return {}
        with open(path, 'r') as f:
            return json.load(f)

    def load_csv_file(self, filename: str, sep=',') -> pd.DataFrame:
        path = self.result_dir / filename
        if not path.exists():
            print(f"Warning: {filename} not found.")
            return pd.DataFrame()
        return pd.read_csv(path, sep=sep)

class RNALoader(BaseLoader):
    """
    专门用于 RNA-seq 项目的数据提取器
    """
    def extract_context(self) -> Dict[str, Any]:
        """
        主方法：调用各个子方法，汇总所有数据
        """
        # 1. 基础信息 (通常来自一个 meta.json 或手动配置)
        self.data['report_title'] = "RNA-seq Transcriptome Analysis Report"
        self.data['pipeline_version'] = "v3.1.0"
        self.data['date'] = "2025-12-28" # 实际应使用 datetime.now()

        # 2. 提取样本统计 (这里假设有一个汇总的 summary.csv)
        # 实际场景中，你可能需要遍历文件夹去解析每个样本的 log
        self._load_sample_stats()

        # 3. 提取差异表达结果
        self._load_deg_results()

        # 4. 准备 Plotly 数据 (转为 JSON 字符串)
        self._prepare_plots()

        return self.data

    def _load_sample_stats(self):
        # 模拟：从 CSV 读取样本列表
        # 假设文件结构: SampleID, Yield_Mb, Q30, Mapping_Rate
        df = pd.DataFrame({
            "library_id": ["L01", "L02"],
            "sample_name": ["Control_1", "Treat_1"],
            "yield_mb": ["6,000", "6,500"],
            "reads": ["20,000,000", "22,000,000"],
            "q30_pct": ["92.5%", "93.1%"]
        })
        # 转为 list of dicts 供 Jinja2 循环
        self.data['samples'] = df.to_dict(orient='records')
        self.data['filter_stats'] = df.rename(columns={"reads": "raw_reads"}).to_dict(orient='records')

    def _load_deg_results(self):
        # 模拟：读取差异基因统计
        self.data['comparison_name'] = "Treat vs Control"
        self.data['up_count'] = 120
        self.data['down_count'] = 85

    def _prepare_plots(self):
        # 模拟：生成绘图所需的 JSON 数据
        # 在真实场景中，这里会读取 expression_matrix.csv 并计算 PCA
        pca_data = [
            {"PC1": 1.2, "PC2": 0.5, "Group": "Control"},
            {"PC1": 1.1, "PC2": 0.6, "Group": "Control"},
            {"PC1": -2.0, "PC2": -1.0, "Group": "Treat"},
        ]
        
        region_data = [
            {"Sample": "Control_1", "Region": "CDS", "Percentage": 40},
            {"Sample": "Control_1", "Region": "Intron", "Percentage": 60},
        ]
        
        volcano_data = [
             {"log2FC": 2.5, "nlog10p": 5.0, "Significance": "Up"},
             {"log2FC": -1.5, "nlog10p": 3.0, "Significance": "Down"},
             {"log2FC": 0.1, "nlog10p": 0.5, "Significance": "Not Sig"},
        ]

        self.data['region_plot_data'] = json.dumps(region_data)
        self.data['volcano_plot_data'] = json.dumps(volcano_data)
