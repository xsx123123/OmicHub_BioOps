import pandas as pd
import numpy as np
import plotly.express as px

def draw_expression_distribution_plotly(tpm_file, meta_file, 
                                        threshold=1.0, 
                                        group_col=None,
                                        height_num=600, width_num=1000, scale_num=4,
                                        color_map=None):
    """
    [最终修复版] 
    1. 移除了导致变灰的 line_color 强制覆盖代码。
    2. 使用 plotly_white 模板，保证颜色鲜艳。
    """
    
    # print(f"[INFO] 正在读取文件: {tpm_file} ...")
    
    # --- 1. 数据读取与清洗 (保持不变) ---
    try:
        try:
            df = pd.read_csv(tpm_file, index_col=0, sep=None, engine='python')
        except:
            df = pd.read_csv(tpm_file, index_col=0, sep='\t')
        try:
            meta = pd.read_csv(meta_file, sep=None, engine='python')
        except:
            meta = pd.read_csv(meta_file, sep='\t')

        # 样本对齐
        matrix_samples = set(df.columns.astype(str))
        best_id_col, max_overlap = None, 0
        for col in meta.columns:
            overlap = len(set(meta[col].astype(str)) & matrix_samples)
            if overlap > max_overlap: max_overlap, best_id_col = overlap, col
            
        if not best_id_col or max_overlap == 0:
            raise ValueError("Metadata 中找不到对应的样本 ID 列")
            
        meta = meta.set_index(best_id_col)
        df.columns = df.columns.astype(str)
        meta.index = meta.index.astype(str)
        
        common_samples = [s for s in df.columns if s in meta.index]
        if not common_samples:
            raise ValueError("无公共样本")
            
        df = df[common_samples]
        meta = meta.loc[common_samples]
        
        # 确定分组
        if group_col is None:
            possible = ["group", "condition", "type"]
            cols_lower = [c.lower() for c in meta.columns]
            for p in possible:
                if p in cols_lower:
                    group_col = meta.columns[cols_lower.index(p)]
                    break
            if group_col is None: group_col = meta.columns[0]
            
        # print(f"[INFO] 使用分组列: {group_col}")

    except Exception as e:
        print(f"[ERROR] 读取失败: {e}")
        return None, None

    # --- 2. 数据计算 ---
    # 过滤
    mean_expr = df.mean(axis=1)
    df_filtered = df[mean_expr > threshold]
    # print(f"[INFO] 过滤后保留基因数: {len(df_filtered)}")
    
    # Log2 转换
    df_log = np.log2(df_filtered + 1)
    
    # 长宽转换
    df_long = df_log.reset_index().melt(
        id_vars=df_log.index.name if df_log.index.name else 'index', 
        var_name='Sample', 
        value_name='Log2TPM'
    )
    
    # 合并分组 (强制转字符串以防报错)
    sample_to_group = meta[group_col].to_dict()
    df_long['Group'] = df_long['Sample'].map(sample_to_group).astype(str)

    # --- 3. 绘图 (关键修改部分) ---
    
    fig = px.violin(
        df_long,
        x="Sample",
        y="Log2TPM",
        color="Group",       # 这里决定颜色
        box=True,            # 显示箱线图
        points=False,        # 不显示散点
        
        # 优先使用自定义配色字典，否则使用 Bold 序列
        color_discrete_map=color_map if color_map else None,
        color_discrete_sequence=px.colors.qualitative.Bold if not color_map else None,
        
        # 这里的模板改用 plotly_white，比 simple_white 对颜色更友好
        template="plotly_white",
        
        title="Sample TPM Distribution"
    )

    # --- 4. 样式美化 ---
    fig.update_layout(
        width=width_num, 
        height=height_num,
        font=dict(family="Arial", size=14, color="black"),
        
        title=dict(
            text=f"Sample TPM Distribution<br><sup>Filtered for mean expression > {threshold}</sup>",
            x=0.5, xanchor='center'
        ),
        
        xaxis_title="",
        yaxis_title="Log2(TPM + 1)",
        xaxis=dict(tickangle=-90),
        
        margin=dict(t=80, b=100, l=80, r=50),
        
        violinmode='group',
        violingap=0,
        
        # 确保图例标题正确
        legend_title_text=group_col
    )
    
    # [重点修复]: 
    # 只设置不透明度 meanline，绝对不要再设置 line_color='DarkSlateGrey'
    # 否则会覆盖掉 Group 的颜色！
    fig.update_traces(
        meanline_visible=False,
        width=0.8,
        opacity=0.8,  # 设置一点透明度，让重叠部分好看
        # line=dict(width=1) # 只要宽度，不要颜色，让颜色跟随 Group
    )

    # --- 5. 导出配置 ---
    my_config = {
        'toImageButtonOptions': {
            'format': 'png', 'filename': 'TPM_Dist',
            'height': height_num, 'width': width_num, 'scale': scale_num 
        },
        'displaylogo': False
    }

    return fig, my_config