#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import json
import yaml
import os
import numpy as np
from itables import show
import itables.options as opt
from typing import Optional, Union

# 全局配置
opt.warn_on_undocumented_option = False
opt.maxBytes = 0

def load_software_data(file_path: str, hide_not_installed: bool = False) -> pd.DataFrame:
    """读取软件版本数据，支持 JSON 和 YAML"""
    if not os.path.exists(file_path):
        return pd.DataFrame([{"Error": f"File not found: {file_path}"}])
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_path.endswith(('.yaml', '.yml')):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
                
        df = pd.DataFrame(data)
        if df.empty: return df
        if hide_not_installed:
            df = df[~df['Version'].astype(str).str.contains("Not Installed", case=False)]
        return df
    except Exception as e:
        return pd.DataFrame([{"Error": f"Failed to parse file: {str(e)}"}])

def plot_software_table(df: pd.DataFrame):
    """
    新野兽派 (New Brutalism) 风格软件版本表
    """
    if df.empty:
        print("⚠️ No data available.")
        return

    # ==========================================
    # 1. 定义样式：硬朗、简洁
    # ==========================================
    def style_version_badges(val):
        val_str = str(val)
        
        # 基础样式：直角微圆、高对比度、等宽字体数字
        base_css = (
            "display: inline-block; "
            "padding: 2px 8px; "     
            "border-radius: 4px; "    # 小圆角，更硬朗
            "font-family: 'Space Grotesk', monospace; " # 配合标题字体
            "font-weight: 600; "
            "font-size: 0.85em; "
            "letter-spacing: 0.02em; "
            "min-width: 80px; "
            "text-align: center; "
            "border: 1px solid transparent; "
        )
        
        if "Not Installed" in val_str or "Not Found" in val_str:
            # 浅红背景，深红文字
            return base_css + "background-color: #fee2e2; color: #991b1b;"
        else:
            # 浅绿背景，深绿文字
            return base_css + "background-color: #dcfce7; color: #166534;"

    # ==========================================
    # 2. 构建 Styler
    # ==========================================
    # 确保 Software 列存在，用于自定义 HTML 渲染
    if 'Software' in df.columns:
        # 移除可能存在的默认 HTML 链接样式，由 CSS 控制
        pass 

    styler = (
        df.style
        .hide(axis="index")
        .map(style_version_badges, subset=['Version'])
    )

    # ==========================================
    # 3. 渲染配置
    # ==========================================
    
    # 注入自定义 CSS 以覆盖 DataTables 默认样式，实现更深度的定制
    # 注意：.dataTables_wrapper 是 itables 生成的容器类
    custom_css = """
    <style>
        /* 软件名称列样式 */
        .dataTable td:first-child {
            font-weight: 600;
            color: #18181b; /* Zinc-900 */
            font-family: 'Space Grotesk', sans-serif;
        }
        
        /* 链接去装饰 */
        .dataTable td a {
            color: #18181b !important;
            text-decoration: none;
            border-bottom: 1px solid #d4d4d8; /* 下划线 */
            transition: all 0.2s;
        }
        .dataTable td a:hover {
            background-color: #f4f4f5;
            border-bottom-color: #18181b;
        }

        /* 来源列样式 (如果有) */
        .dataTable td:nth-child(3) {
            color: #71717a; /* Zinc-500 */
            font-size: 0.9em;
        }
    </style>
    """
    
    # 忽略关于未文档化参数的警告
    opt.warn_on_undocumented_option = False

    show(
        styler,
        # caption="🧬 Software Versions & Environment", # 标题可以在 qmd 中写，这里省略更干净
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
        columnDefs=[
            {"className": "dt-center", "targets": "_all"},
            {"width": "30%", "targets": 0}, # 软件名列宽一点
            {"width": "30%", "targets": 1}, # 版本列
        ],
        style="width:100%",
        scrollX=True,
        tags=custom_css, # 注入自定义 CSS
        allow_html=True
    )

def plot_software_table_modern(df: pd.DataFrame):
    """
    极简现代风格 (Modern Minimalist) - V3.2 兼容版
    修复内容：移除已废弃的 opt.css 设置，纯靠 tags 注入样式，完美支持新版 itables。
    """
    if df.empty: return

    # ==========================================
    # 1. 样式化版本号 (HTML 胶囊)
    # ==========================================
    def version_badge_html(val):
        val_str = str(val)
        
        # 基础样式
        base_style = (
            "display: inline-flex; align-items: center; justify-content: center; "
            "padding: 4px 10px; border-radius: 6px; "
            "font-family: 'SF Mono', 'Menlo', 'Consolas', monospace; "
            "font-size: 0.85em; font-weight: 500; letter-spacing: -0.01em; "
            "line-height: 1.2; "
        )
        
        # 配色逻辑
        if "Not" in val_str or pd.isna(val):
            color_style = "background-color: #FEF2F2; color: #B91C1C; border: 1px solid #FCA5A5;" 
        else:
            color_style = "background-color: #F0FDF4; color: #15803D; border: 1px solid #86EFAC;"
            
        return f'<span style="{base_style} {color_style}">{val}</span>'

    # 应用格式化
    styler = df.style.format({'Version': version_badge_html}).hide(axis="index")

    # ==========================================
    # 2. 准备 CSS (不再赋值给 opt.css)
    # ==========================================
    custom_css = """
    <style>
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
        table.dataTable tbody tr:hover,
        table.dataTable.display tbody tr:hover > .sorting_1 {
            background-color: #F9FAFB !important;
        }

        /* 表格线条 */
        table.dataTable.no-footer { border-bottom: 1px solid #E5E7EB !important; }
        table.dataTable td {
            border-bottom: 1px solid #F3F4F6 !important;
            border-right: none !important;
            border-left: none !important;
        }

        /* 单元格布局 */
        .dataTable td {
            padding: 12px 16px !important;
            vertical-align: middle !important;
            font-size: 0.95rem;
        }

        /* 表头设计 */
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

        /* 第一列强调 */
        .dataTable td:first-child {
            font-weight: 600;
            color: #111827;
        }
        
        /* 交互元素美化 */
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
        dom='<"d-flex justify-content-between align-items-center mb-4"Bf>rt<"d-flex justify-content-between align-items-center mt-4"ip>',
        buttons=[{'extend': 'copy', 'text': '📋 Copy'}, {'extend': 'csv', 'text': '💾 CSV'}],
        columnDefs=[
            {"width": "25%", "targets": 0}, 
            {"width": "20%", "targets": 1}, 
            {"className": "dt-left", "targets": "_all"}
        ],
        style="width:100%; border-collapse: collapse;",
        tags=custom_css,
        allow_html=True  
    )

def display_fastp_table(data_path: str):
    """
    读取 MultiQC general_stats.txt，展示 Notion 风格的 Fastp 统计表。
    (不包含 Legend 说明)
    """
    try:
        df = pd.read_csv(data_path, sep='\t')
    except Exception as e:
        print(f"❌ 无法读取文件: {e}")
        return

    # ==========================================
    # 1. 数据清洗与列映射
    # ==========================================
    
    # 目标列映射：根据 MultiQC 输出的列名 -> 最终显示列名
    col_mapping = {
        'fastp-pct_duplication': '% Duplication',
        'fastp-after_filtering_q30_rate': '% Q30',
        'fastp-after_filtering_q30_bases': 'Q30 Bases (M)', 
        'fastp-pct_surviving': '% Surviving',
        'fastp-pct_adapter': '% Adapter',
    }
    
    df_display = pd.DataFrame()
    
    # 1.1 处理 Sample ID (去除后缀)
    if 'Sample' in df.columns:
        # 去除常见的 Fastp/Fastq 后缀，保持 ID 干净
        df_display['Sample'] = df['Sample'].str.replace(r'(_raw|_fastp|\.fastp|\.fq|\.fastq)', '', regex=True)
    else:
        df_display['Sample'] = df.index

    # 1.2 提取列
    for col in df.columns:
        for key, new_name in col_mapping.items():
            if key in col: # 模糊匹配
                df_display[new_name] = df[col]
                break
    
    # 1.3 特殊处理：合并 Read1/2 Length
    r1_col = next((c for c in df.columns if 'read1_mean_length' in c), None)
    r2_col = next((c for c in df.columns if 'read2_mean_length' in c), None)
    
    if r1_col and r2_col:
        # 双端测序：显示 "150/150"
        df_display['Read1/2 Len'] = (
            df[r1_col].astype(int).astype(str) + "/" + 
            df[r2_col].astype(int).astype(str)
        )
    elif r1_col:
        # 单端测序
        df_display['Read Len'] = df[r1_col].astype(int)

    # 1.4 调整列顺序
    # 确保 Sample 在第一列，Read Len 放在 Q30 Bases 后面比较合适
    desired_order = ['Sample', '% Duplication', '% Q30', 'Q30 Bases (M)', 'Read1/2 Len', 'Read Len', '% Surviving', '% Adapter']
    final_cols = [c for c in desired_order if c in df_display.columns]
    df_display = df_display[final_cols]

    # ==========================================
    # 2. 样式化 (HTML 胶囊 & 字体)
    # ==========================================
    
    # 百分比样式
    def style_percent(val):
        if pd.isna(val): return "-"
        val_fmt = f"{val:.2f}"
        style = "font-family: 'SF Mono', 'Consolas', monospace; color: #4B5563;"
        return f'<span style="{style}">{val_fmt}</span>'

    # 大数字样式 (Q30 Bases)
    def style_large_num(val):
        if pd.isna(val): return "-"
        # 假设数据已经是 M 单位 (MultiQC general_stats 通常是 float)，保留2位小数
        val_fmt = f"{val:,.2f}"
        style = "font-family: 'SF Mono', 'Consolas', monospace; color: #111827; font-weight: 500;"
        return f'<span style="{style}">{val_fmt}</span>'

    # 普通文本样式
    def style_text(val):
        style = "font-family: 'SF Mono', 'Consolas', monospace; color: #374151;"
        return f'<span style="{style}">{val}</span>'

    # 应用 Styler
    styler = df_display.style.hide(axis="index")
    
    for col in df_display.columns:
        if col == 'Sample': continue
        
        if '%' in col:
            styler = styler.format({col: style_percent})
        elif 'Q30 Bases' in col:
            styler = styler.format({col: style_large_num})
        else:
            styler = styler.format({col: style_text})

    # ==========================================
    # 3. 统一 CSS (V3.2 兼容版)
    # ==========================================
    custom_css = """
    <style>
        .itables { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #374151; }
        table.dataTable tbody tr { background-color: #ffffff !important; }
        table.dataTable tbody tr:hover { background-color: #F9FAFB !important; }
        table.dataTable.no-footer { border-bottom: 1px solid #E5E7EB !important; }
        table.dataTable td { border-bottom: 1px solid #F3F4F6 !important; padding: 12px 16px !important; vertical-align: middle !important; font-size: 0.9rem; }
        .dataTable thead th { background-color: #ffffff !important; border-bottom: 2px solid #E5E7EB !important; color: #6B7280 !important; font-size: 0.75rem; text-transform: uppercase; padding: 12px 16px !important; font-weight: 600; }
        .dataTable td:first-child { font-weight: 600; color: #111827; }
        .dataTables_wrapper .dataTables_filter input { border: 1px solid #D1D5DB; border-radius: 6px; padding: 4px 8px; outline: none; }
        .dt-buttons .dt-button { background: white !important; border: 1px solid #D1D5DB !important; border-radius: 6px !important; color: #374151 !important; padding: 0.4em 1em !important; }
        .dt-buttons .dt-button:hover { background: #F3F4F6 !important; }
    </style>
    """

    # 展示表格
    show(
        styler,
        classes="display",
        dom='<"d-flex justify-content-between align-items-center mb-4"Bf>rt<"d-flex justify-content-between align-items-center mt-4"ip>',
        buttons=[{'extend': 'copy', 'text': '📋 Copy'}, {'extend': 'csv', 'text': '💾 CSV'}],
        columnDefs=[
            {"className": "dt-left", "targets": 0}, 
            {"className": "dt-center", "targets": "_all"}
        ],
        style="width:100%; border-collapse: collapse;",
        scrollX=True,
        tags=custom_css,
        allow_html=True
    )

def display_fastq_screen_table(r1_path: str, r2_path: str, sample_sheet_path: str,top_number = 3):
    """
    FastQ Screen 表格展示 (V6.0 终极统一版)
    特点：
    1. 风格与 display_fastp_table 100% 统一 (Notion 风)。
    2. 逻辑：保留 Top 15 物种，其余合并为 'Others'，保证信息完整且不爆宽。
    3. 适配：开启横向滚动，固定第一列。
    """
    try:
        df_r1 = pd.read_csv(r1_path, sep='\t')
        df_r2 = pd.read_csv(r2_path, sep='\t')
        df_samples = pd.read_csv(sample_sheet_path)
    except Exception as e:
        print(f"❌ 无法读取文件: {e}")
        return

    # ==========================================
    # 1. 数据清洗与合并 (保持不变)
    # ==========================================
    df_r1['Match_ID'] = df_r1['Sample'].str.replace(r'_R[12]_screen.*', '', regex=True).str.strip()
    df_r2['Match_ID'] = df_r2['Sample'].str.replace(r'_R[12]_screen.*', '', regex=True).str.strip()
    
    species_cols = [c.replace(' counts', '') for c in df_r1.columns if ' counts' in c]
    cols_to_keep = ['Match_ID', 'total_reads'] + [f"{s} counts" for s in species_cols]
    
    valid_cols = [c for c in cols_to_keep if c in df_r1.columns and c in df_r2.columns]
    df_r1_clean = df_r1[valid_cols].set_index('Match_ID')
    df_r2_clean = df_r2[valid_cols].set_index('Match_ID')
    
    common = df_r1_clean.index.intersection(df_r2_clean.index)
    if len(common) == 0: return
    
    df_merged = df_r1_clean.loc[common] + df_r2_clean.loc[common]
    df_merged = df_merged.reset_index()
    
    df_samples['sample'] = df_samples['sample'].astype(str).str.strip()
    df_final = pd.merge(df_samples[['sample', 'sample_name']], df_merged, left_on='sample', right_on='Match_ID')
    
    if df_final.empty: return

    # ==========================================
    # 2. 智能列筛选：Top 15 + Others
    # ==========================================
    
    # 先计算所有物种的百分比
    pct_df = pd.DataFrame()
    for s in species_cols:
        count_col = f"{s} counts"
        if count_col in df_final.columns:
            pct_df[s] = (df_final[count_col] / df_final['total_reads']) * 100

    # 策略：
    # 1. 扔掉所有样本中 max < 0.01% 的列 (噪音)
    valid_cols = [c for c in pct_df.columns if pct_df[c].max() > 0.01]
    pct_df = pct_df[valid_cols]

    # 2. 如果列数 > 15，保留前 15 个，剩下的合并为 "Others"
    final_species = list(pct_df.columns)
    if len(pct_df.columns) > top_number:
        # 按平均丰度排序
        sorted_cols = pct_df.mean().sort_values(ascending=False).index.tolist()
        top_cols = sorted_cols[:top_number]
        other_cols = sorted_cols[top_number:]
        
        # 创建 Others 列
        pct_df['Others'] = pct_df[other_cols].sum(axis=1)
        final_species = top_cols + ['Others']
        print(f"💡 [INFO] 物种较多，已显示 Top {top_number}，其余 {len(other_cols)} 种合并为 'Others'。")

    # 构建最终显示 DF
    df_display = pd.DataFrame()
    df_display['Sample'] = df_final['sample_name']
    for s in final_species:
        df_display[f"{s} (%)"] = pct_df[s]

    # ==========================================
    # 3. 样式复刻 (Notion 风格)
    # ==========================================
    def style_percent(val):
        if pd.isna(val): return "-"
        val_fmt = f"{val:.2f}"
        style = "font-family: 'SF Mono', 'Consolas', monospace; color: #374151;"
        
        if val == 0: style += "color: #D1D5DB;" # 0值变淡
        elif val > 20: style += "color: #B45309; font-weight: 600;" # 高污染(>20%) 橙色警示
        
        return f'<span style="{style}">{val_fmt}</span>'

    styler = df_display.style.hide(axis="index")
    for col in df_display.columns:
        if col != 'Sample':
            styler = styler.format({col: style_percent})

    # ==========================================
    # 4. 统一 CSS (完全复用 fastp 表格样式 + 滚动增强)
    # ==========================================
    custom_css = """
    <style>
        /* 全局字体与颜色 (与 fastp 表格一致) */
        .itables { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #374151; }
        
        /* 表格主体：去斑马纹，纯白背景 */
        table.dataTable tbody tr { background-color: #ffffff !important; }
        table.dataTable tbody tr:hover { background-color: #F9FAFB !important; }
        
        /* 边框风格：Notion 灰线 */
        table.dataTable.no-footer { border-bottom: 1px solid #E5E7EB !important; }
        table.dataTable td { 
            border-bottom: 1px solid #F3F4F6 !important; 
            padding: 12px 16px !important; 
            vertical-align: middle !important; 
            font-size: 0.9rem;
        }
        
        /* 表头：大写、加粗、浅灰底 (或白底) */
        .dataTable thead th { 
            background-color: #ffffff !important; 
            border-bottom: 2px solid #E5E7EB !important; 
            color: #6B7280 !important; 
            font-size: 0.75rem; 
            text-transform: uppercase; 
            padding: 12px 16px !important; 
            font-weight: 600; 
            white-space: nowrap; /* 不换行，配合 scrollX */
        }
        
        /* --- 增强部分：适应 Quarto 的滚动条与固定列 --- */
        
        /* 1. 第一列固定 (Sticky Column) - 效果非常平滑 */
        table.dataTable td:first-child, table.dataTable th:first-child {
            position: sticky !important;
            left: 0 !important;
            background-color: #ffffff !important; /* 必须有背景色防止穿透 */
            z-index: 10 !important;
            border-right: 1px solid #E5E7EB !important; /* 分割线 */
            color: #111827 !important;
            font-weight: 600 !important;
        }

        /* 2. 强制容器适应宽度 (解决 Quarto 溢出) */
        .dataTables_wrapper {
            width: 100%;
            max-width: 100%;
            overflow-x: auto;
        }
    </style>
    """
    show(
        styler,
        classes="display nowrap", 
        scrollX=True,
        autoWidth=False,
        # 布局：按钮左，搜索右
        dom='<"d-flex justify-content-between align-items-center mb-4"Bf>rt<"d-flex justify-content-between align-items-center mt-4"ip>',
        buttons=[{'extend': 'copy', 'text': '📋 Copy'}, {'extend': 'csv', 'text': '💾 CSV'}],
        columnDefs=[
            {"width": "120px", "targets": 0}, # 固定 Sample 列宽
            {"className": "dt-left", "targets": 0},
            {"className": "dt-center", "targets": "_all"}
        ],
        tags=custom_css,
        allow_html=True
    )

def display_gene_expression_table(data: Union[str, pd.DataFrame], top_n: Optional[int] = None):
    """
    展示基因表达量表 (Notion 风格 + 科学计数法优化)
    """
    # ==========================================
    # 1. 数据读取与预处理
    # ==========================================
    if isinstance(data, str):
        try:
            # 自动推断分隔符
            df = pd.read_csv(data, sep=None, engine='python')
        except Exception as e:
            print(f"❌ 无法读取文件: {e}")
            return
    elif isinstance(data, pd.DataFrame):
        df = data.copy()
    else:
        print("❌ 错误：输入数据必须是文件路径或 pd.DataFrame")
        return

    # 如果指定了 top_n，进行切片
    if top_n and len(df) > top_n:
        df_display = df.head(top_n).copy()
    else:
        df_display = df.copy()

    # ==========================================
    # 2. 样式化 (数值与字体)
    # ==========================================

    # 数值样式：等宽字体，处理科学计数法
    def style_expression(val):
        if pd.isna(val): return "-"
        if isinstance(val, (int, float)):
            if val == 0:
                val_fmt = "0"
                color = "#D1D5DB"  # 0值灰色
            elif abs(val) < 0.001 and val != 0:
                val_fmt = f"{val:.2e}"  # 极小值用科学计数法
                color = "#6B7280"
            else:
                val_fmt = f"{val:.2f}"
                color = "#374151"
            
            style = f"font-family: 'SF Mono', 'Consolas', monospace; color: {color};"
            return f'<span style="{style}">{val_fmt}</span>'
        return val

    # ID/Symbol 样式 (加粗强调)
    def style_id(val):
        style = "font-family: 'SF Mono', 'Consolas', monospace; font-weight: 600; color: #111827;"
        return f'<span style="{style}">{val}</span>'

    # 应用 Styler
    styler = df_display.style.hide(axis="index")

    # 智能识别列类型
    numeric_cols = df_display.select_dtypes(include=[np.number]).columns.tolist()
    other_cols = [c for c in df_display.columns if c not in numeric_cols]

    # 格式化数值列
    if numeric_cols:
        styler = styler.format({col: style_expression for col in numeric_cols})
    
    # 格式化文本列 (通常是第一列 ID)
    if other_cols:
        styler = styler.format({col: style_id for col in other_cols})

    # ==========================================
    # 3. 统一 CSS (完全复用 Notion 风格)
    # ==========================================
    custom_css = """
    <style>
        .itables { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #374151; }
        
        /* 表格主体 */
        table.dataTable tbody tr { background-color: #ffffff !important; }
        table.dataTable tbody tr:hover { background-color: #F9FAFB !important; }
        table.dataTable.no-footer { border-bottom: 1px solid #E5E7EB !important; }
        
        /* 单元格 */
        table.dataTable td { 
            border-bottom: 1px solid #F3F4F6 !important; 
            padding: 12px 16px !important; 
            vertical-align: middle !important; 
            font-size: 0.85rem; 
        }
        
        /* 表头 */
        .dataTable thead th { 
            background-color: #ffffff !important; 
            border-bottom: 2px solid #E5E7EB !important; 
            color: #6B7280 !important; 
            font-size: 0.75rem; 
            text-transform: uppercase; 
            padding: 12px 16px !important; 
            font-weight: 600; 
            white-space: nowrap;
        }
        
        /* 固定第一列 (Sticky Column) */
        table.dataTable td:first-child, table.dataTable th:first-child {
            position: sticky !important;
            left: 0 !important;
            background-color: #ffffff !important;
            z-index: 10 !important;
            border-right: 1px solid #E5E7EB !important;
        }

        /* 滚动条容器 */
        .dataTables_wrapper { width: 100%; max-width: 100%; overflow-x: auto; }
        
        /* 搜索框与按钮 */
        .dataTables_wrapper .dataTables_filter input { border: 1px solid #D1D5DB; border-radius: 6px; padding: 4px 8px; outline: none; }
        .dt-buttons .dt-button { background: white !important; border: 1px solid #D1D5DB !important; border-radius: 6px !important; color: #374151 !important; padding: 0.4em 1em !important; }
        .dt-buttons .dt-button:hover { background: #F3F4F6 !important; }
    </style>
    """

    # ==========================================
    # 4. 显示表格
    # ==========================================
    show(
        styler,
        classes="display nowrap",
        scrollX=True,       # 开启横向滚动
        autoWidth=False,    # 关闭自动宽度以支持 Sticky
        dom='<"d-flex justify-content-between align-items-center mb-4"Bf>rt<"d-flex justify-content-between align-items-center mt-4"ip>',
        buttons=[
            {'extend': 'copy', 'text': '📋 Copy'}, 
            {'extend': 'csv', 'text': '💾 CSV'}
        ],
        columnDefs=[
            {"width": "150px", "targets": 0},      # 固定第一列宽度 (基因ID)
            {"className": "dt-left", "targets": 0}, # 第一列左对齐
            {"className": "dt-center", "targets": "_all"} # 其他列居中
        ],
        tags=custom_css,
        allow_html=True
    )