#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
import os
import json
from itables import show
from itables import options
from visualize_utils import plot_software_table,plot_software_table_modern

# ... (keep existing imports and functions)

def get_project_summary_stats(
    data_dir="../data", 
    qc_filename="multiqc_qc_general_stats.txt",
    mapping_filename="multiqc_mapping_general_stats.txt",
    tpm_filename="merge_rsem_tpm.tsv",
    sample_filename="sample.csv"
):
    """
    加载并计算项目总览所需的各项统计指标。
    
    参数:
        data_dir (str): 数据目录路径
        qc_filename (str): QC 统计文件名
        mapping_filename (str): 比对统计文件名
        tpm_filename (str): TPM 表达矩阵文件名
        sample_filename (str): 样本信息表文件名
        
    返回:
        dict: 包含各项统计指标的字典
        pd.DataFrame: 用于展示的样本详情表
    """
    # 构建完整路径
    def resolve_path(d, f):
        if not f: return os.path.join(d, "")
        if os.path.exists(f): return f
        p = os.path.join(d, f)
        if os.path.exists(p): return p
        p_base = os.path.join(d, os.path.basename(f))
        if os.path.exists(p_base): return p_base
        return p

    qc_file = resolve_path(data_dir, qc_filename)
    mapping_file = resolve_path(data_dir, mapping_filename)
    tpm_file = resolve_path(data_dir, tpm_filename)
    sample_file = resolve_path(data_dir, sample_filename)
    
    # 初始化
    df_final = pd.DataFrame()
    stats = {
        'total_samples': 0,
        'total_groups': 0,
        'total_data_gb': 0,
        'avg_q30': 0,
        'mapping_rate': 0,
        'unique_mapping_rate': 0,
        'avg_dup': 0,
        'genes_detected': 0,
        'qc_status': "N/A",
        'mapping_status': "N/A",
        'unique_status': "N/A"
    }

    # 1. 读取样本信息
    if os.path.exists(sample_file):
        try:
            df_sample_info = pd.read_csv(sample_file)
            if 'group' in df_sample_info.columns:
                df_sample_info['group'] = df_sample_info['group'].astype(str)
                stats['total_groups'] = len(df_sample_info['group'].unique())
            stats['total_samples'] = len(df_sample_info)
        except Exception as e:
            print(f"⚠️ 读取样本表失败: {e}")
            df_sample_info = pd.DataFrame()
    else:
        df_sample_info = pd.DataFrame()

    # 2. 读取 QC 统计
    if os.path.exists(qc_file):
        try:
            df_qc = pd.read_csv(qc_file, sep="\t")
            # 过滤 R1/R2
            df_qc = df_qc[~df_qc['Sample'].str.endswith(('_R1', '_R2'))].copy()
            
            if not df_qc.empty:
                target_cols = {
                    'Sample': 'Sample',
                    'fastp-filtering_result_passed_filter_reads': 'Reads_Raw',
                    'fastp-after_filtering_q30_rate': 'Q30_Pct',
                    'fastqc-percent_gc': 'FastQC_GC',
                    'fastp-after_filtering_gc_content': 'Fastp_GC',
                    'fastp-pct_duplication': 'Dup_Pct'
                }
                
                available_cols = [c for c in target_cols.keys() if c in df_qc.columns]
                df_qc_core = df_qc[available_cols].copy()
                df_qc_core.rename(columns=target_cols, inplace=True)
                
                # GC 处理
                if 'FastQC_GC' in df_qc_core.columns and 'Fastp_GC' in df_qc_core.columns:
                    df_qc_core['GC_Pct'] = df_qc_core['FastQC_GC'].fillna(
                        df_qc_core['Fastp_GC'] * 100 if df_qc_core['Fastp_GC'].mean() < 1.0 else df_qc_core['Fastp_GC']
                    )
                elif 'FastQC_GC' in df_qc_core.columns:
                    df_qc_core['GC_Pct'] = df_qc_core['FastQC_GC']
                elif 'Fastp_GC' in df_qc_core.columns:
                    df_qc_core['GC_Pct'] = df_qc_core['Fastp_GC'].apply(lambda x: x * 100 if x < 1.0 else x)
                
                # Reads 单位处理 (M)
                if 'Reads_Raw' in df_qc_core.columns:
                    if df_qc_core['Reads_Raw'].mean() < 1000: # 已经是 M
                         df_qc_core['Reads_M'] = df_qc_core['Reads_Raw']
                    else:
                         df_qc_core['Reads_M'] = df_qc_core['Reads_Raw'] / 1e6
                
                df_final = df_qc_core
        except Exception as e:
            print(f"⚠️ 读取 QC 统计失败: {e}")

    # 3. 读取 Mapping 统计
    if os.path.exists(mapping_file):
        try:
            df_mapping = pd.read_csv(mapping_file, sep="\t")
            if 'star-mapped_percent' in df_mapping.columns:
                df_mapping = df_mapping.dropna(subset=['star-mapped_percent'])
                df_mapping = df_mapping[~df_mapping['Sample'].str.contains('_STARpass1', na=False)]
                
                mapping_cols = {
                    'star-mapped_percent': 'Mapping Rate',
                    'star-uniquely_mapped_percent': 'Unique_Map_Pct',
                    'qualimap_bamqc-avg_gc': 'Mapped_GC_Pct',
                    'qualimap_bamqc-median_insert_size': 'Insert_Size'
                }
                
                existing = [c for c in mapping_cols.keys() if c in df_mapping.columns]
                df_map_sub = df_mapping[['Sample'] + existing].copy()
                df_map_sub.rename(columns=mapping_cols, inplace=True)
                
                if not df_final.empty:
                    df_final = pd.merge(df_final, df_map_sub, on='Sample', how='outer')
                else:
                    df_final = df_map_sub
        except Exception as e:
            print(f"⚠️ 读取 Mapping 统计失败: {e}")

    # 4. 合并分组信息
    if not df_final.empty and not df_sample_info.empty:
        try:
            df_final = pd.merge(df_final, df_sample_info[['sample', 'group']], 
                              left_on='Sample', right_on='sample', how='left')
        except Exception as e:
            print(f"⚠️ 合并分组信息失败: {e}")

    # 5. 计算汇总指标
    if not df_final.empty:
        # 如果 stats['total_samples'] 还没值 (例如没读到 sample.csv), 用 df_final 的行数
        if stats['total_samples'] == 0:
            stats['total_samples'] = len(df_final)
            
        stats['avg_q30'] = df_final['Q30_Pct'].mean() if 'Q30_Pct' in df_final.columns else 0
        stats['mapping_rate'] = df_final['Mapping Rate'].mean() if 'Mapping Rate' in df_final.columns else 0
        stats['unique_mapping_rate'] = df_final['Unique_Map_Pct'].mean() if 'Unique_Map_Pct' in df_final.columns else 0
        stats['avg_dup'] = df_final['Dup_Pct'].mean() if 'Dup_Pct' in df_final.columns else 0
        
        # 数据量 (Gb)
        if 'Reads_M' in df_final.columns:
            stats['total_data_gb'] = df_final['Reads_M'].sum() * 150 / 1000

    # 6. 基因检出数
    if os.path.exists(tpm_file):
        try:
            df_tpm = pd.read_csv(tpm_file, sep="\t", index_col=0)
            stats['genes_detected'] = int((df_tpm > 1).any(axis=1).sum())
        except Exception:
            stats['genes_detected'] = "N/A"

    # 7. 状态评价
    stats['qc_status'] = "数据质量优秀" if stats['avg_q30'] >= 90 else "数据质量良好" if stats['avg_q30'] >= 80 else "数据质量一般"
    stats['mapping_status'] = "比对率正常" if stats['mapping_rate'] >= 70 else "比对率较低"
    stats['unique_status'] = "特异性优秀" if stats['unique_mapping_rate'] >= 80 else "特异性良好" if stats['unique_mapping_rate'] >= 60 else "特异性一般"

    return stats, df_final

    """
    读取 MultiQC 的 fastp 统计文件，清洗数据，
    并展示为带有 MultiQC 风格样式和交互功能的表格。
    
    参数:
        file_path (str): multiqc_general_stats.txt 文件的路径
    """
    
    # 1. 读取数据
    try:
        df = pd.read_csv(file_path, sep="\t")
    except FileNotFoundError:
        return print(f"❌ 错误: 找不到文件 {file_path}")

    # 2. 统一修改列名格式 (去掉 fastp-，下划线变空格，首字母大写)
    df.columns = [c.replace('fastp-', '').replace('_', ' ').title() for c in df.columns]

    # 3. 提取需要的列 (使用清洗后的列名)
    # 这里的列名对应 MultiQC fastp 模块的标准输出
    target_cols_map = {
        'Sample': 'Sample',
        'Pct Duplication': '% Duplication',
        'After Filtering Q30 Rate': '% Q30',
        'After Filtering Q30 Bases': 'Q30 Bases',
        'Before Filtering Read1 Mean Length': 'Read1 Len',
        'Before Filtering Read2 Mean Length': 'Read2 Len',
        'Pct Surviving': '% Surviving',
        'Pct Adapter': '% Adapter'
    }
    
    # 检查列是否存在，防止报错
    existing_cols = [c for c in target_cols_map.keys() if c in df.columns]
    df_clean = df[existing_cols].copy()
    
    # 重命名列
    new_names = [target_cols_map[c] for c in existing_cols]
    df_clean.columns = new_names

    # 4. 数据类型转换 (强制转为数字，处理可能的 NaN)
    numeric_cols = ['% Duplication', '% Q30', '% Surviving', '% Adapter']
    # 只转换存在的列
    cols_to_convert = [c for c in numeric_cols if c in df_clean.columns]
    
    for col in cols_to_convert:
        df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce')
    
    df_clean.fillna(0, inplace=True)

    # 5. 设置全局选项
    options.maxBytes = 0

    # 6. 定义样式 (Pandas Styler)
    # 注意：这里使用了优化过的颜色范围，视觉效果更好
    styler = (
        df_clean.style
        .format(precision=2)
        .hide(axis="index")
        .bar(subset=['% Duplication'], color='#d65f5f', vmin=0, vmax=50) # Duplication > 50% 就满红
        .background_gradient(subset=['% Q30'], cmap='Greens', vmin=90, vmax=100) # Q30 < 90 就偏白
        .background_gradient(subset=['% Surviving'], cmap='Blues', vmin=80, vmax=100)
    )

    # 如果有 % Adapter 列，也可以加个简单的格式化
    if '% Adapter' in df_clean.columns:
        styler = styler.format({'% Adapter': "{:.2f}"})

    # 7. 显示表格 (ITables)
    show(
        styler,
        layout={
            "topStart": "buttons",
            "topEnd": "search",
            "bottomStart": "info",
            "bottomEnd": "paging"
        },
        buttons=[
            "copyHtml5",
            "csvHtml5",
            "excelHtml5",
            "colvis",     # 列可见性控制
            "pageLength", # 每页行数控制
            "pdfHtml5"
        ],
        classes="display nowrap compact stripe hover",
        columnDefs=[
            {"className": "dt-center", "targets": "_all"}
        ],
        # 黑色表头样式
        tags='<style>th { background-color: #444 !important; color: white !important; }</style>',
        allow_html=True
    )

def load_analysis_config(json_path):
    """
    加载分析结果的 JSON 配置文件。
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️ Warning: Configuration file not found at {json_path}")
        return {}
    except json.JSONDecodeError:
        print(f"⚠️ Warning: Failed to decode JSON from {json_path}")
        return {}

def get_file_path(config, file_key, local_base_dir="../data"):
    """
    尝试获取文件的本地路径。
    策略:
    1. 从 config['files'] 中获取 key 对应的原始路径 (remote path)。
    2. 如果 config 中没有，则尝试直接在 local_base_dir 中寻找以 file_key 命名的文件。
    3. 提取文件名 (basename) 并检查 local_base_dir 下是否存在。
    """
    files_map = config.get('files', {})
    remote_path = files_map.get(file_key)
    
    # 如果 config 中有路径
    if remote_path:
        filename = os.path.basename(remote_path)
        local_path = os.path.join(local_base_dir, filename)
        if os.path.exists(local_path):
            return local_path
        return remote_path

    # 如果 config 中没有，尝试直接在本地目录找
    local_path = os.path.join(local_base_dir, file_key)
    if os.path.exists(local_path):
        return local_path
    
    return None

def find_comparisons(config):
    """
    从 config['files'] 中自动推断比较组名称。
    查找规则: 寻找以 '_DEG.csv' 结尾的 key，提取前面的部分作为 comparison_name。
    返回一个列表: ['2_vs_1', 'mutant_vs_wt', ...]
    """
    comparisons = []
    files_map = config.get('files', {})
    for key in files_map.keys():
        if key.endswith('_DEG.csv'):
            comp_name = key.replace('_DEG.csv', '')
            comparisons.append(comp_name)
    return sorted(comparisons)

def get_comparisons_from_csv(csv_path):
    """
    从 contrasts.csv 中提取比较组名称。
    假设 CSV 包含 'Control' 和 'Treat' 列。
    返回列表，如 ['2_vs_1', ...]
    """
    try:
        df = pd.read_csv(csv_path)
        comparisons = []
        for _, row in df.iterrows():
            control = str(row['Control'])
            treat = str(row['Treat'])
            comparisons.append(f"{treat}_vs_{control}")
        return comparisons
    except Exception as e:
        print(f"⚠️ Error reading contrasts CSV: {e}")
        return []

def parse_multiqc_stats(json_path):
    """
    解析 MultiQC 的 JSON 报告 (如 mapping_multiqc_data.json)，
    提取 report_general_stats_data 中的关键指标。
    
    返回: DataFrame (包含 Sample, Total Reads, Mapping Rate, Duplication Rate 等)
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"⚠️ Warning: Failed to load MultiQC JSON from {json_path}: {e}")
        return None

    # MultiQC 的数据结构通常是: data['report_general_stats_data'][0] -> { 'sample_name': { 'metric': value } }
    # 注意: report_general_stats_data 是一个 list，可能包含多个工具的 stats (Star, Qualimap, Fastp 等)
    # 我们需要遍历这个 list，把所有 sample 的数据整合起来。

    general_stats_list = data.get('report_general_stats_data', [])
    if not general_stats_list:
        return None

    combined_stats = {}

    # 修正: 根据用户提供的文件内容，report_general_stats_data 是一个 Dict，Keys 是工具名 (qualimap, STAR, etc.)
    if isinstance(general_stats_list, dict):
         # 格式: {'qualimap': {'s1': {...}}, 'STAR': {'s1': {...}}}
         iterator = general_stats_list.items()
    elif isinstance(general_stats_list, list):
         # 格式: [{'s1': {'var': 1}}, {'s1': {'var2': 2}}] (旧版或特定模块)
         # 但用户给的 JSON 显示是 Dict 结构。我们优先按 Dict 处理，兼顾 List。
         iterator = enumerate(general_stats_list) 
    else:
         iterator = []

    for tool_name, samples_data in iterator:
        if isinstance(samples_data, dict):
            for sample_name, metrics in samples_data.items():
                # 清洗样本名 (去掉 .sort, _raw 等后缀，以便匹配)
                clean_name = sample_name.replace('.sort', '').replace('_raw', '').replace('_R1', '').replace('_R2', '')
                
                if clean_name not in combined_stats:
                    combined_stats[clean_name] = {'Sample': clean_name}
                
                # 将该工具的所有指标合并到该样本中
                # 为了防止列名冲突，可以加上工具前缀，或者根据常用指标重命名
                for metric_key, metric_val in metrics.items():
                    # 挑选一些我们关心的核心指标并标准化命名
                    if metric_key == 'percentage_aligned' or metric_key == 'uniquely_mapped_percent':
                        combined_stats[clean_name]['Mapping Rate'] = metric_val
                    elif metric_key == 'total_reads':
                        combined_stats[clean_name]['Total Reads'] = metric_val
                    elif metric_key == 'duplication_rate':
                        combined_stats[clean_name]['Duplication Rate'] = metric_val
                    elif metric_key == 'mean_coverage':
                        combined_stats[clean_name]['Mean Coverage'] = metric_val
                    # ... 可以根据需要添加更多

    if not combined_stats:
        return None

    return pd.DataFrame(list(combined_stats.values()))

def load_sample_qc_stats(file_path):
    """
    读取 MultiQC 的 general stats 文件，并过滤掉 R1/R2 的行，仅保留样本汇总行。
    通常样本汇总行以 _raw 结尾，且不包含 _R1 或 _R2。
    """
    try:
        df = pd.read_csv(file_path, sep="\t")

        # 过滤逻辑：包含 _raw 但不包含 _R1 和 _R2
        # 如果您的样本命名规则不同，可以调整这里的正则
        mask = df['Sample'].str.contains('_raw') & ~df['Sample'].str.contains('_R1|_R2')
        df_samples = df[mask].copy()
        
        # 清洗样本名，去掉 _raw 后缀方便后续合并
        df_samples['Sample_Clean'] = df_samples['Sample'].str.replace('_raw', '')

        return df_samples

    except Exception as e:
        print(f"⚠️ Error loading QC stats: {e}")
        return pd.DataFrame()

def Sample_Info_table(df_final) -> None:
    if not df_final.empty:
        # 整理显示用的表格
        display_cols = ['Sample']
        col_map = {
            'Sample': 'Sample ID',
            'group': 'Group',
            'Reads_M': 'Clean Reads (M)', 
            'Q30_Pct': 'Q30 (%)',
            'GC_Pct': 'GC (%)',
            'Mapped_GC_Pct': 'Mapped GC (%)',
            'Insert_Size': 'Insert Size (bp)',
            'Mapping Rate': 'Mapping Rate (%)'
        }
        
        # 如果 group 存在，加入显示列表
        if 'group' in df_final.columns:
            display_cols.append('group')
            
        display_cols.extend(['Reads_M', 'Q30_Pct'])
        
        # 按顺序添加其他列（如果存在）
        optional_cols = ['GC_Pct', 'Mapping Rate', 'Mapped_GC_Pct', 'Insert_Size']
        for c in optional_cols:
            if c in df_final.columns:
                display_cols.append(c)
            
        df_display = df_final[display_cols].copy()
        
        # 清洗 Sample 名称 (去掉 _raw 后缀)
        if 'Sample' in df_display.columns:
            df_display['Sample'] = df_display['Sample'].str.replace('_raw', '')
            
        df_display.columns = [col_map.get(c, c) for c in df_display.columns]
        
        # 格式化数字
        from itables import show
        import itables.options as opt
        
        # 忽略关于未文档化参数的警告
        opt.warn_on_undocumented_option = False
        
        # 自定义 CSS (与 plot_software_table 保持一致)
        custom_css = """
        <style>
            /* 第一列 (Sample ID) 字体优化 */
            .dataTable td:first-child {
                font-weight: 600;
                color: #18181b; 
                font-family: 'Space Grotesk', sans-serif;
            }
        </style>
        """
        
        show(
            df_display, 
            classes="display nowrap", 
            paging=True, 
            searching=True,
            # 使用 Bootstrap 类优化布局：按钮在左，搜索在右；信息在左，分页在右
            dom='<"d-flex justify-content-between align-items-center mb-3"Bf>rt<"d-flex justify-content-between align-items-center mt-3"ip>',
            buttons=[
                {'extend': 'copy', 'text': '<i class="bi bi-clipboard"></i>', 'className': 'btn-icon', 'titleAttr': 'Copy'},
                {'extend': 'csv', 'text': '<i class="bi bi-filetype-csv"></i>', 'className': 'btn-icon', 'titleAttr': 'CSV'},
                {'extend': 'excel', 'text': '<i class="bi bi-file-earmark-excel"></i>', 'className': 'btn-icon', 'titleAttr': 'Excel'}
            ],
            columnDefs=[{"className": "dt-center", "targets": "_all"}],
            style="width:100%",
            tags=custom_css, # 注入样式
            allow_html=True
        )
    else:
        print("❌ 未能加载样本统计信息。")


def Sample_Info_table_modern(df_final: pd.DataFrame) -> None:
    """
    Sample Info Table - Notion 风格复刻版
    特点：
    1. Sample ID 左对齐加粗。
    2. Group 列自动变为蓝色系小胶囊 (Badge)。
    3. 数值列使用等宽字体，视觉更整齐。
    4. 整体 UI 与 Software 表格完全统一。
    """
    if df_final.empty:
        print("❌ 未能加载样本统计信息。")
        return

    # ==========================================
    # 1. 数据清洗与列映射 (保持原有逻辑)
    # ==========================================
    display_cols = ['Sample']
    col_map = {
        'Sample': 'Sample ID',
        'group': 'Group',
        'Reads_M': 'Clean Reads (M)', 
        'Q30_Pct': 'Q30 (%)',
        'GC_Pct': 'GC (%)',
        'Mapped_GC_Pct': 'Mapped GC (%)',
        'Insert_Size': 'Insert Size (bp)',
        'Mapping Rate': 'Mapping Rate (%)'
    }
    
    # 动态构建显示列
    if 'group' in df_final.columns:
        display_cols.append('group')
    display_cols.extend(['Reads_M', 'Q30_Pct'])
    
    optional_cols = ['GC_Pct', 'Mapping Rate', 'Mapped_GC_Pct', 'Insert_Size']
    for c in optional_cols:
        if c in df_final.columns:
            display_cols.append(c)
        
    df_display = df_final[display_cols].copy()
    
    # 去掉 _raw 后缀
    if 'Sample' in df_display.columns:
        df_display['Sample'] = df_display['Sample'].str.replace('_raw', '')
        
    # 重命名列
    df_display.columns = [col_map.get(c, c) for c in df_display.columns]

    # ==========================================
    # 2. 样式化：Group 列变胶囊 & 数字格式化
    # ==========================================
    
    # 定义 Group 胶囊样式 (蓝色系，区别于软件表的绿色/红色)
    def group_badge_html(val):
        val_str = str(val)
        style = (
            "display: inline-flex; align-items: center; justify-content: center; "
            "padding: 2px 10px; border-radius: 6px; "
            "font-family: -apple-system, BlinkMacSystemFont, sans-serif; "
            "font-size: 0.85em; font-weight: 500; "
            "background-color: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE;" # 柔和蓝
        )
        return f'<span style="{style}">{val}</span>'

    # 定义数字列的样式 (等宽字体，看起来更专业)
    def number_font_html(val):
        # 简单判断：如果是浮点数，保留2位小数；如果是整数，直接显示
        if isinstance(val, float):
            val_fmt = f"{val:.2f}"
        else:
            val_fmt = str(val)
        
        style = "font-family: 'SF Mono', 'Menlo', 'Consolas', monospace; color: #4B5563;"
        return f'<span style="{style}">{val_fmt}</span>'

    # 应用 Styler
    # 1. 基础 Styler
    styler = df_display.style.hide(axis="index")
    
    # 2. 如果有 Group 列，应用胶囊样式
    if 'Group' in df_display.columns:
        styler = styler.format({'Group': group_badge_html})
        
    # 3. 对所有数字列应用等宽字体样式 (这里简单粗暴地对除了 ID 和 Group 之外的列应用)
    numeric_cols = [c for c in df_display.columns if c not in ['Sample ID', 'Group']]
    # 注意：为了防止 format 报错，这里逐个应用，且仅对数值类型生效会更安全，
    # 但为了简单，我们假设这些列都是数值，统一套用 number_font_html
    format_dict = {c: number_font_html for c in numeric_cols}
    styler = styler.format(format_dict)

    # ==========================================
    # 3. 统一 CSS (直接复用 Software 表格的 CSS)
    # ==========================================
    custom_css = """
    <style>
        /* 全局字体 */
        .itables {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #374151;
        }
        
        /* 强制去除斑马纹，背景全白 */
        table.dataTable tbody tr,
        table.dataTable.display tbody tr.odd,
        table.dataTable.display tbody tr.even {
            background-color: #ffffff !important;
        }

        /* 鼠标悬停高亮 */
        table.dataTable tbody tr:hover {
            background-color: #F9FAFB !important;
        }

        /* 线条风格 */
        table.dataTable.no-footer { border-bottom: 1px solid #E5E7EB !important; }
        table.dataTable td {
            border-bottom: 1px solid #F3F4F6 !important;
            border-right: none !important;
            border-left: none !important;
            padding: 12px 16px !important;
            vertical-align: middle !important;
            font-size: 0.95rem;
        }

        /* 表头风格 */
        .dataTable thead th {
            background-color: #ffffff !important;
            border-bottom: 2px solid #E5E7EB !important;
            color: #6B7280 !important;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 12px 16px !important;
            font-weight: 600;
        }

        /* 第一列 (Sample ID) 强调 */
        .dataTable td:first-child {
            font-weight: 600;
            color: #111827; /* 深黑 */
        }
        
        /* 交互控件美化 */
        .dataTables_wrapper .dataTables_filter input {
            border: 1px solid #D1D5DB;
            border-radius: 6px;
            padding: 4px 8px; 
            margin-left: 8px;
            outline: none;
        }
        .dt-buttons .dt-button {
            background: white !important;
            border: 1px solid #D1D5DB !important;
            border-radius: 6px !important;
            color: #374151 !important;
            padding: 0.4em 1em !important;
            font-size: 0.85rem !important;
        }
        .dt-buttons .dt-button:hover {
            background: #F3F4F6 !important;
            color: #111827 !important;
        }
    </style>
    """

    show(
        styler,
        classes="display",
        # 布局保持一致
        dom='<"d-flex justify-content-between align-items-center mb-4"Bf>rt<"d-flex justify-content-between align-items-center mt-4"ip>',
        
        # 按钮 (稍微简化了 text，如果你喜欢图标可以加回去，但 emoji 在 PDF 导出有时兼容性更好)
        buttons=[
            {'extend': 'copy', 'text': '📋 Copy'}, 
            {'extend': 'csv', 'text': '💾 CSV'},
            {'extend': 'excel', 'text': '📊 Excel'}
        ],
        
        columnDefs=[
            {"width": "20%", "targets": 0}, # Sample ID 列宽
            # 如果有 Group 列 (通常是第2列，target=1)，可以限制一下宽度
            # {"width": "15%", "targets": 1} 
            
            # 对齐方式微调：
            # Sample ID (第0列) 左对齐
            {"className": "dt-left", "targets": 0},
            # 其他列 (数字) 建议居中或右对齐，这里选居中显得比较平衡
            {"className": "dt-center", "targets": "_all"} 
        ],
        style="width:100%; border-collapse: collapse;",
        tags=custom_css,
        allow_html=True # 必须开，否则 Group 胶囊和数字字体都不显示
    )

def software_version_table(df_sw,sw_file) -> None:
    if not df_sw.empty and 'Link' in df_sw.columns:
        # 将软件名包装为链接
        df_sw['Software'] = df_sw.apply(
            lambda x: f'<a href="{x["Link"]}" style="text-decoration: none; color: #2980b9; font-weight: bold;">{x["Software"]}</a>', 
            axis=1
        )
        # 移除 Link 列
        df_display_sw = df_sw.drop(columns=['Link'])
        # plot_software_table(df_display_sw)
        plot_software_table_modern(df_display_sw)
        
        # 准备后续用于替换文本的字典 (软件名 -> 版本)
        # 重新读取原始数据因为 plot_software_table 修改了 df_display_sw 的格式可能不方便直接用
        # 或者直接从原始 df_sw 提取（注意 Software 列已经加了 HTML 标签，最好用原始 YAML 数据）
        import yaml
        with open(sw_file, 'r') as f:
            sw_list = yaml.safe_load(f)
            # 生成映射字典: {'FastQC': 'v0.12.1', 'Fastp': 'v0.23.4', ...}
        sw_ver_map = {item['Software']: item['Version'] for item in sw_list}
    else:
        sw_ver_map = {}

    return sw_ver_map