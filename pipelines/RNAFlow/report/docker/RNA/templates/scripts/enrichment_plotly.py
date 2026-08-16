import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import textwrap  # 📦 引入这个库用于文本折叠

def draw_fancy_dotplot(enrich_file, 
                       top_n=20, 
                       p_cutoff=0.05, 
                       sort_by="p.adjust", 
                       ascending=True, 
                       x_col="GeneRatio", 
                       y_col="Description", 
                       size_col="Count", 
                       color_col="p.adjust",
                       height_num=800, 
                       width_num=900, 
                       scale_num=4,
                       wrap_width=30):
    """
    绘制科研级审美的富集分析气泡图 (支持长文本折行)
    """
    
    # --- 1. 数据读取与预处理 ---
    try:
        if isinstance(enrich_file, str):
            df = pd.read_csv(enrich_file, sep=None, engine='python')
        elif isinstance(enrich_file, pd.DataFrame):
            df = enrich_file.copy()
        else:
            return None, None

        # 阈值过滤
        if p_cutoff is not None and color_col in df.columns:
            df = df[df[color_col] < p_cutoff]
            if len(df) == 0:
                print("⚠️ [WARN] 过滤后无剩余通路。")
                return None, None

        # GeneRatio 计算
        plot_x_col = x_col
        if x_col in df.columns and df[x_col].dtype == 'object' and '/' in str(df[x_col].iloc[0]):
            df['parsed_ratio'] = df[x_col].apply(lambda x: float(x.split('/')[0])/float(x.split('/')[1]) if '/' in str(x) else 0)
            plot_x_col = 'parsed_ratio'
        elif x_col not in df.columns:
             candidates = ['FoldEnrichment', size_col]
             for c in candidates:
                 if c in df.columns:
                     plot_x_col = c
                     break

        # 排序
        if sort_by in df.columns:
            df = df.sort_values(sort_by, ascending=ascending)
        else:
            df = df.sort_values(color_col, ascending=True)
        
        # 截取 Top N 并反转
        if top_n and top_n < len(df):
            df = df.head(top_n)
        df = df.iloc[::-1]

    except Exception as e:
        print(f"❌ [ERROR] {e}")
        return None, None

    # --- 🛠️ 核心修改：文本折行处理 ---
    # 定义折行函数
    def custom_wrap(text, width):
        return "<br>".join(textwrap.wrap(str(text), width=width))
    
    # 创建一个新的列用于绘图（带<br>的），保留原列 y_col 用于悬停显示
    df['wrapped_y'] = df[y_col].apply(lambda x: custom_wrap(x, wrap_width))

    # --- 2. 🎨 绘图 ---

    color_scale = "RdYlBu"  
    
    fig = px.scatter(
        df,
        x=plot_x_col,
        y='wrapped_y', # ✨ 这里使用折行后的列作为 Y 轴
        size=size_col,
        color=color_col,
        color_continuous_scale=color_scale, 
        size_max=25,
        title=f"<b>Top {len(df)} Enriched Pathways</b>",
        # hover_data 中显示原始的长名称 (y_col)
        hover_data={y_col:True, 'wrapped_y':False, size_col:True, color_col:":.2e", plot_x_col:":.3f"}
    )

    # --- 3. 精细化修饰 ---
    fig.update_layout(
        template="simple_white",
        width=width_num, height=height_num,
        font=dict(family="Arial", size=14, color="#333333"),
        
        title=dict(x=0.5, xanchor='center', font=dict(size=18)),

        xaxis=dict(
            title=f"<b>{plot_x_col}</b>",
            showgrid=True,
            gridcolor='#E5E7EB',
            gridwidth=1,
            griddash='dash',
            zeroline=False,
            showline=True, linecolor='black'
        ),

        yaxis=dict(
            title="",
            showgrid=True, gridcolor='#E5E7EB', griddash='dash',
            showline=True, linecolor='black',
            automargin=True, # 自动调整边距
            # ✨ 增加刻度文字间距，防止折行后太密
            tickfont=dict(size=12) 
        ),
        
        # 边距：左边留白交给 automargin，右边留给 Legend
        margin=dict(t=80, b=50, l=20, r=20),
        
        coloraxis_colorbar=dict(
            title="<b>Adj. P-value</b>",
            tickformat=".1e",
            len=0.6,
            thickness=15,
            yanchor="top", y=1,
            xanchor="left", x=1.02
        )
    )
    
    fig.update_traces(
        marker=dict(
            line=dict(width=1.2, color='#4B5563'),
            opacity=0.9
        ),
        # 修改悬停显示的格式，把原本的 wrapped_y 替换为 Description
        hovertemplate = 
            f"<b>%{{customdata[0]}}</b><br>" + # 显示完整的 Description
            f"{plot_x_col}: %{{x:.3f}}<br>" +
            f"{size_col}: %{{marker.size}}<br>" +
            f"{color_col}: %{{marker.color:.2e}}<extra></extra>"
    )
    
    # 这一步是为了让 customdata 对齐 hovertemplate
    # 必须把原始 Description 放到 customdata 里
    fig.update_traces(customdata=df[[y_col]])

    # --- 4. 导出 ---
    config = {
        'toImageButtonOptions': {
            'format': 'png', 'filename': 'Fancy_Enrichment',
            'height': height_num, 'width': width_num, 'scale': scale_num
        },
        'displaylogo': False
    }

    return fig, config