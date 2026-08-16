import pandas as pd
import plotly.express as px
import numpy as np
from scipy.stats import zscore
import scipy.cluster.hierarchy as sch
from scipy.spatial.distance import pdist
import os

def draw_interactive_heatmap(
    input_file, 
    metadata_file, 
    top_n=1000, 
    processed=False, 
    do_cluster=True, 
    save_html=None  # 如果想保存网页，传路径给这个参数
):
    """
    读取数据并生成带聚类和高清下载配置的 Plotly 热图对象。
    
    Args:
        input_file (str): 表达量矩阵路径 (CSV/TSV)
        metadata_file (str): 样本信息表路径
        top_n (int): 取变异最大的前 N 个基因
        processed (bool): 数据是否已经预处理过
        do_cluster (bool): 是否进行层级聚类
        save_html (str, optional): 如果需要保存为 HTML 文件，填入路径
        
    Returns:
        plotly.graph_objs._figure.Figure: Plotly 图形对象
    """
    
    # --- 1. 读取数据 ---
    try:
        df = pd.read_csv(input_file, sep=None, engine='python', index_col=0)
        meta_raw = pd.read_csv(metadata_file, sep=None, engine='python')
        
        # 智能列名匹配
        matrix_samples = set(df.columns.astype(str))
        best_col, max_overlap = None, 0
        for col in meta_raw.columns:
            overlap = len(set(meta_raw[col].astype(str)) & matrix_samples)
            if overlap > max_overlap: max_overlap, best_col = overlap, col
                
        if best_col and max_overlap > 0:
            meta = meta_raw.set_index(best_col)
            # print(f"[INFO] Matched Metadata Column: {best_col}")
        else:
            raise ValueError("Metadata mismatch! No common samples found.")
            
    except Exception as e:
        raise ValueError(f"Read Error: {e}")

    # 对齐
    df.columns = df.columns.astype(str)
    meta.index = meta.index.astype(str)
    common = [s for s in df.columns if s in meta.index]
    if not common:
        raise ValueError("No common samples between matrix and metadata.")
        
    df = df[common]
    meta = meta.loc[common]

    # --- 2. 预处理 ---
    if not processed:
        df = df.apply(pd.to_numeric, errors='coerce').dropna()
        # 过滤低表达
        df = df[df.mean(axis=1) > 1]
        # Log2
        df = np.log2(df + 1)
        # 零方差过滤
        df = df[df.var(axis=1) > 0]
        # Top N
        if len(df) > top_n:
            top_genes = df.var(axis=1).sort_values(ascending=False).head(top_n).index
            df = df.loc[top_genes]
    
    # --- 3. Z-Score ---
    z_mat = zscore(df.values, axis=1, nan_policy='omit')
    df_z = pd.DataFrame(z_mat, index=df.index, columns=df.columns).fillna(0)

    # --- 4. 聚类 ---
    if do_cluster and not df_z.empty:
        try:
            # 行聚类 (Correlation)
            d_rows = pdist(df_z.values, metric='correlation')
            row_idx = sch.leaves_list(sch.linkage(d_rows, method='ward'))
            df_z = df_z.iloc[row_idx, :]
            
            # 列聚类 (Euclidean)
            d_cols = pdist(df_z.values.T, metric='euclidean')
            col_idx = sch.leaves_list(sch.linkage(d_cols, method='ward'))
            df_z = df_z.iloc[:, col_idx]
        except Exception as e:
            print(f"[WARN] Clustering skipped due to error: {e}")

    # --- 5. 绘图配置 ---
    title_suffix = "TPM" if "tpm" in input_file.lower() else ("FPKM" if "fpkm" in input_file.lower() else "Exp")
    
    fig = px.imshow(
        df_z,
        labels=dict(x="Sample", y="Gene", color="Z-Score"),
        color_continuous_scale="RdBu_r",
        zmin=-2, zmax=2,
        aspect="auto"
    )

    fig.update_layout(
        title=f"Clustered Heatmap ({title_suffix})",
        xaxis={'side': 'bottom'},
        yaxis={'visible': True if len(df_z) < 100 else False},
        width=1000,  # 给 Quarto 显示设置一个默认宽度
        height=800
    )
    
    # 高清下载配置
    my_config = {
        'toImageButtonOptions': {
            'format': 'png',
            'filename': f'Heatmap_{title_suffix}_Cluster',
            'height': 1200,
            'width': 1600,
            'scale': 4  # 4倍超高清
        },
        'displaylogo': False,
        'modeBarButtonsToRemove': ['lasso2d', 'select2d']
    }
    
    # 将 config 绑定到 fig 对象上 (虽然 fig.show 才会用到，但为了方便 Quarto 调用)
    # 注意：在 Quarto 直接 return fig 时，需要手动在 chunk 里加 fig.show(config=...)
    # 或者我们返回 fig 和 config
    
    if save_html:
        out_path = save_html if save_html.endswith('.html') else f"{save_html}.html"
        fig.write_html(out_path, config=my_config)
        print(f"[INFO] HTML saved to: {out_path}")

    return fig, my_config