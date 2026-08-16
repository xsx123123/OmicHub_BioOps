#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bioinformatics Plotting Utilities
---------------------------------
包含常用的生物信息学绘图功能：
1. PCA (静态/交互)
2. 基因表达矩阵表格展示
3. 火山图 (Volcano Plot)
4. 样本相关性分析
5. 数据加载与模拟

Author: Jian Zhang (Optimized by Hajimi)
Date: 2026-01-01
"""

import numpy as np
import pandas as pd
from plotnine import *
from itables import show
import itables.options as opt
import plotly.express as px
import plotly.graph_objects as go
from typing import Optional, List, Union
import os

# --- 全局配置 ---
# 解除 itables 数据大小限制，防止大矩阵报错
opt.maxBytes = 0 
opt.style = "width:100%;" 


def plot_pca_static(
    df: pd.DataFrame, 
    col_x: str, 
    col_y: str, 
    col_group: str, 
    title: str = "PCA Plot"
) -> ggplot:
    """
    使用 plotnine 绘制静态 PCA 散点图 (Publication Ready).
    
    Args:
        df: 包含 PCA 坐标和分组信息的 DataFrame.
        col_x: PC1 列名 (e.g., 'PC1').
        col_y: PC2 列名 (e.g., 'PC2').
        col_group: 用于着色的分组列名 (e.g., 'Group').
        title: 图表标题.

    Returns:
        ggplot 对象.
    """
    plot = (
        ggplot(df, aes(x=col_x, y=col_y, color=col_group))
        + geom_point(size=3, alpha=0.8)
        + theme_bw()
        + labs(title=title, color="Group")
        + theme(
            # 注意：如果 Linux 服务器没有 Arial 字体，这里可能会报警，
            # 可以改为 'DejaVu Sans' 或其他通用字体
            text=element_text(family="Arial"), 
            legend_position='right',
            figure_size=(6, 4)
        )
    )
    return plot


def plot_pca_interactive(
    df: pd.DataFrame, 
    col_x: str, 
    col_y: str, 
    col_group: str, 
    title: str = "PCA Plot"
) -> go.Figure:
    """
    使用 plotly 绘制交互式 PCA 散点图 (HTML Report Ready).
    
    Args:
        df: 输入 DataFrame.
        col_x: X轴列名.
        col_y: Y轴列名.
        col_group: 分组列名.
        title: 标题.

    Returns:
        plotly.graph_objects.Figure 对象.
    """
    fig = px.scatter(
        df,
        x=col_x,
        y=col_y,
        color=col_group,
        title=title,
        width=700,
        height=500,
        template="plotly_white",
        hover_data=[col_group] 
    )
    
    # 统一美化点的样式：增加边框让点更清晰
    fig.update_traces(marker=dict(size=12, line=dict(width=1, color='DarkSlateGrey')))
    
    return fig


def show_gene_table(
    df: pd.DataFrame, 
    caption: str = "Gene Expression Table", 
    precision: int = 4
) -> None:
    """
    封装 itables 用于展示基因表达矩阵，支持导出 (CSV/Excel) 和分页.
    
    Args:
        df: 基因表达矩阵 DataFrame.
        caption: 表格标题.
        precision: 数值保留小数位数 (不影响原始数据，仅用于展示).
    """
    show(
        df.round(precision), 
        caption=caption,
        classes="display nowrap", 
        # 分页设置：每页显示 [10, 25, 50, 全部]
        lengthMenu=[[10, 25, 50, -1], [10, 25, 50, "All"]],
        pageLength=10,
        # 功能按钮：复制、CSV下载、Excel下载
        buttons=["copy", "csv", "excel"],
        # 布局定义：顶部按钮+搜索框，底部信息+分页器
        layout={
            "topStart": "buttons",
            "topEnd": "search",
            "bottomStart": ["info", "pageLength"],
            "bottomEnd": "paging"
        },
        columnDefs=[
            {"className": "dt-center", "targets": "_all"}, # 所有内容居中
            {"width": "100px", "targets": [0]}             # 第一列(通常是ID)固定宽度防止换行
        ]
    )


def plot_volcano_pvalue(
    df: pd.DataFrame, 
    title: str,
    col_logfc: str = 'log2FC',
    col_pval: str = 'Pvalue',      # 核心修改：主要依赖这个列
    col_padj: str = 'Padj',        # 仅作保留，不再用于核心筛选
    col_symbol: str = 'Symbol',
    col_status: str = 'Status',
    fc_cutoff: float = 1.0,
    pval_cutoff: float = 0.05,     # 现在的含义是 P-value < 0.05
    palette: Optional[dict] = None
) -> go.Figure:
    """
    绘制交互式火山图 (使用 Raw P-value 进行筛选).
    """
    
    df = df.copy()

    # --- 1. 列名映射 ---
    col_mappings = {
        'logfc': [col_logfc, 'log2FoldChange', 'logFC', 'Log2FC'],
        'pval': [col_pval, 'pvalue', 'PValue', 'P_Value'],
        'symbol': [col_symbol, 'symbol', 'gene_name', 'Gene']
    }

    resolved_cols = {}
    for key, candidates in col_mappings.items():
        found_col = next((c for c in candidates if c in df.columns), candidates[0])
        resolved_cols[key] = found_col

    c_logfc = resolved_cols['logfc']
    c_pval = resolved_cols['pval']
    c_symbol = resolved_cols['symbol']

    # --- 2. 核心修改：使用 P-value 确定状态 ---
    # 只有当 DataFrame 里没有预先定义好的 Status 列时，才重新计算
    if col_status not in df.columns:
        if c_logfc in df.columns and c_pval in df.columns:
            df[col_status] = 'NS'
            
            # === [修改处] 这里全部改为使用了 c_pval (Raw P-value) ===
            # 上调：LogFC > 阈值 且 Pvalue < 阈值
            df.loc[(df[c_logfc] > fc_cutoff) & (df[c_pval] < pval_cutoff), col_status] = 'Up'
            
            # 下调：LogFC < -阈值 且 Pvalue < 阈值
            df.loc[(df[c_logfc] < -fc_cutoff) & (df[c_pval] < pval_cutoff), col_status] = 'Down'
        else:
            print(f"[Error] 无法计算状态: 缺少 {c_logfc} 或 {c_pval}")
            df[col_status] = 'NS'

    # --- 3. 绘图逻辑 ---
    default_palette = {'Up': '#ef4444', 'Down': '#3b82f6', 'NS': 'lightgrey'}
    if palette:
        default_palette.update(palette)
    colors = default_palette

    fig = go.Figure()
    
    # 按顺序绘制：NS -> Down -> Up (避免显著点被遮挡)
    for status in ['NS', 'Down', 'Up']:
        sub_df = df[df[col_status] == status]
        if sub_df.empty: continue
        
        # 视觉调整：NS 点稍微小一点、透一点
        opacity = 0.5 if status == 'NS' else 0.8
        size = 5 if status == 'NS' else 7
        
        fig.add_trace(go.Scatter(
            x=sub_df[c_logfc], 
            y=-np.log10(sub_df[c_pval] + 1e-300), 
            mode='markers', name=status,
            marker=dict(color=colors.get(status, 'grey'), size=size, opacity=opacity),
            text=sub_df[c_symbol],
            # 悬停显示详细信息
            hovertemplate=(
                "<b>%{text}</b><br>" +
                "LogFC: %{x:.2f}<br>" +
                "P-val: %{y:.2f} (-log10)<br>" +
                "<extra></extra>"
            )
        ))

    # --- 4. 辅助线 ---
    fig.add_vline(x=fc_cutoff, line_dash="dash", line_color="grey", line_width=1)
    fig.add_vline(x=-fc_cutoff, line_dash="dash", line_color="grey", line_width=1)
    # 这里的横线现在完美对应颜色的分界了
    fig.add_hline(y=-np.log10(pval_cutoff), line_dash="dash", line_color="grey", line_width=1)
    
    fig.update_layout(
        title=title,
        xaxis_title=c_logfc,
        yaxis_title=f"-log10({c_pval})",
        template="simple_white",
        width=800, height=600
    )

    return fig

# --- 新增功能 ---

def generate_mock_data(seed, n_genes=2000):
    """生成用于演示的差异表达模拟数据"""
    np.random.seed(seed)
    df = pd.DataFrame({
        'GeneID': [f"ENSG{i:06d}" for i in range(n_genes)],
        'Symbol': [f"Gene_{i}" for i in range(n_genes)],
        'BaseMean': np.random.gamma(2, 100, n_genes),
        'log2FC': np.random.normal(0, 1.5, n_genes),
        'Pvalue': np.random.uniform(0, 1, n_genes),
        'Padj': np.random.uniform(0, 0.05, n_genes)
    })
    
    # 标记显著性
    df['Status'] = 'NS'
    df.loc[(df['log2FC'] > 1) & (df['Padj'] < 0.05), 'Status'] = 'Up'
    df.loc[(df['log2FC'] < -1) & (df['Padj'] < 0.05), 'Status'] = 'Down'
    
    return df

def load_de_results(file_path):
    """
    加载真实的差异表达结果文件。
    支持 CSV/TSV，并自动尝试匹配列名。
    """
    if not os.path.exists(file_path):
        print(f"[Warn] DE file not found: {file_path}. Using Mock Data.")
        return generate_mock_data(seed=42)
    
    try:
        df = pd.read_csv(file_path, sep=None, engine='python')
        # 标准化列名 (示例)
        col_map = {
            'log2FoldChange': 'log2FC',
            'pvalue': 'Pvalue',
            'padj': 'Padj',
            'symbol': 'Symbol',
            'gene_name': 'Symbol'
        }
        df.rename(columns=col_map, inplace=True)
        return df
    except Exception as e:
        print(f"[Error] Failed to load DE file: {e}")
        return generate_mock_data(seed=42)

def plot_sample_correlation(tpm_file, meta_file, width=800, height=700):
    """
    计算样本间 Pearson 相关系数并绘制热图。
    """
    try:
        # 读取 TPM
        df = pd.read_csv(tpm_file, sep=None, engine='python', index_col=0)
        # 过滤低表达
        df = df[df.mean(axis=1) > 1]
        # Log2 转换
        log_df = np.log2(df + 1)
        
        # 计算相关性矩阵
        corr_matrix = log_df.corr(method='pearson')
        
        # 绘图
        fig = px.imshow(
            corr_matrix,
            text_auto=".2f",
            aspect="auto",
            color_continuous_scale="RdBu_r",
            zmin=0.8, zmax=1, # 设定颜色范围，突显差异
            labels=dict(color="Pearson Corr")
        )
        
        fig.update_layout(
            title="Sample Correlation Heatmap",
            width=width, 
            height=height,
            template="simple_white"
        )
        
        # 导出配置
        my_config = {
            'toImageButtonOptions': {
                'format': 'png',
                'filename': 'Sample_Correlation',
                'height': height,
                'width': width,
                'scale': 2
            },
            'displaylogo': False
        }
        
        return fig, my_config
        
    except Exception as e:
        print(f"[Error] Correlation plot failed: {e}")
        return None, None