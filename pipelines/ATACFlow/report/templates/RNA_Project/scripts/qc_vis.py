#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import multiqc
import os
import json
import plotly.graph_objects as go
from IPython.display import display, Markdown
from typing import Optional, List, Dict, Any

def _visualize_from_json(analysis_dir: str, target_modules: Optional[List[str]] = None) -> None:
    """
    Fallback method: Visualize plots directly from multiqc_data.json
    when standard MultiQC log parsing fails (e.g. only aggregated data available).
    """
    json_path = os.path.join(analysis_dir, "multiqc_data.json")
    if not os.path.exists(json_path):
        print(f"❌ Error: No MultiQC modules found via parsing, and no multiqc_data.json found in {analysis_dir}")
        return

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load multiqc_data.json: {e}")
        return

    plot_data = data.get("report_plot_data", {})
    if not plot_data:
        print("⚠️ multiqc_data.json contains no plot data.")
        return

    # Filter plots based on target_modules (case-insensitive substring match in title/id)
    # If target_modules is None, show all.
    plots_to_show = []
    
    for plot_id, plot_info in plot_data.items():
        # Identify module from plot info
        # Usually title is "Module: Chart Name"
        # We try to extract module name or check against targets
        
        should_show = False
        title = ""
        
        # Try to get title from dconfig or pconfig
        if "datasets" in plot_info and len(plot_info["datasets"]) > 0:
            title = plot_info["datasets"][0].get("dconfig", {}).get("title", "")
        
        if not title and "pconfig" in plot_info:
            title = plot_info["pconfig"].get("title", "")

        if not title:
            title = plot_id # Fallback

        if target_modules:
            for mod in target_modules:
                # Check if module name is in the title or ID
                # e.g. mod="QualiMap", title="QualiMap: Coverage"
                if mod.lower() in title.lower() or mod.lower() in plot_id.lower():
                    should_show = True
                    break
        else:
            should_show = True

        if should_show:
            plots_to_show.append((plot_id, title, plot_info))

    if not plots_to_show:
        print(f"⚠️ No plots found matching modules: {target_modules}")
        return

    # Render plots
    for plot_id, title, plot_info in plots_to_show:
        try:
            plot_type = plot_info.get("plot_type")
            fig = go.Figure()
            
            # --- X/Y Line Charts ---
            if plot_type == "x/y line":
                datasets = plot_info.get("datasets", [])
                for dataset in datasets:
                    for line in dataset.get("lines", []):
                        name = line.get("name", "Unknown")
                        pairs = line.get("pairs", [])
                        if not pairs: continue
                        
                        # Unzip pairs
                        x_vals = [p[0] for p in pairs]
                        y_vals = [p[1] for p in pairs]
                        
                        fig.add_trace(go.Scatter(
                            x=x_vals, 
                            y=y_vals, 
                            mode='lines', 
                            name=name
                        ))
                        
            # --- Bar Charts ---
            elif plot_type == "bar plot":
                datasets = plot_info.get("datasets", [])
                for dataset in datasets:
                    cats = dataset.get("cats", []) # Categories/Series
                    samples = dataset.get("samples", []) # X/Y axis labels
                    
                    # Check orientation
                    is_horizontal = False
                    trace_params = dataset.get("trace_params", {})
                    if trace_params.get("orientation") == "h":
                        is_horizontal = True
                        
                    for cat in cats:
                        name = cat.get("name", "Unknown")
                        data_vals = cat.get("data", [])
                        color = cat.get("color")
                        
                        if is_horizontal:
                            fig.add_trace(go.Bar(
                                x=data_vals,
                                y=samples,
                                orientation='h',
                                name=name,
                                marker_color=color
                            ))
                        else:
                            fig.add_trace(go.Bar(
                                x=samples,
                                y=data_vals,
                                name=name,
                                marker_color=color
                            ))
                            
                    # Handle stacking if needed
                    layout_cfg = plot_info.get("layout", {})
                    if layout_cfg.get("barmode") == "stack" or layout_cfg.get("barmode") == "relative":
                        fig.update_layout(barmode='stack') # 'relative' in plotly is usually stack for pos/neg

            else:
                # Unsupported plot type for this simple fallback
                # print(f"Skipping unsupported plot type: {plot_type} for {plot_id}")
                continue

            # --- Common Layout ---
            mqc_layout = plot_info.get("layout", {})
            
            # Extract axis titles
            xaxis_title = mqc_layout.get("xaxis", {}).get("title", {}).get("text", "")
            yaxis_title = mqc_layout.get("yaxis", {}).get("title", {}).get("text", "")
            
            fig.update_layout(
                title=title,
                xaxis_title=xaxis_title,
                yaxis_title=yaxis_title,
                template="simple_white",
                height=500,
                margin=dict(l=50, r=50, t=80, b=50)
            )

            # High-res download config
            my_config = {
                'toImageButtonOptions': {
                    'format': 'png',
                    'filename': f'{plot_id}',
                    'height': 600,
                    'width': 1200,
                    'scale': 4 
                },
                'displaylogo': False
            }

            display(Markdown(f"**{title}** Visualization"))
            fig.show(config=my_config)
            # display(Markdown("\n---\n"))

        except Exception as e:
            print(f"❌ Failed to render plot {plot_id}: {e}")


def visualize_multiqc_logs(analysis_dir: str, target_modules: Optional[List[str]] = None, plot_captions: Optional[Dict[str, str]] = None) -> None:
    """
    解析指定目录的 MultiQC 日志，并交互式展示 Plotly 图表。
    
    Args:
        analysis_dir (str): MultiQC 数据目录路径。
        target_modules (List[str], optional): 指定只展示哪些模块（例如 ['fastp']）。
                                              如果不填，默认展示所有发现的模块。
        plot_captions (Dict[str, str], optional): 图表说明字典，Key 为 plot_id (例如 'fastp_filtered_reads_plot')，
                                                  Value 为 Markdown 格式的说明文本。
    """
    
    # --- 🧹 1. 关键步骤：清除 MultiQC 的旧记忆 ---
    try:
        multiqc.reset()
    except AttributeError:
        if hasattr(multiqc, 'report'):
            multiqc.report.data = {}
            multiqc.report.general_stats_data = []

    # --- 🛡️ 2. 路径检查 ---
    if not os.path.exists(analysis_dir):
        print(f"❌ 错误：找不到数据目录: {analysis_dir}")
        return
        
    # --- 📂 3. 解析日志 ---
    try:
        multiqc.parse_logs(analysis_dir, quiet=True)
    except Exception as e:
        print(f"⚠️ 解析日志时遇到警告: {e}")
    
    # 获取所有发现的模块
    found_modules = multiqc.list_modules()
    all_plots = multiqc.list_plots()
    
    # --- 🔄 4. Fallback Logic ---
    if not found_modules:
        # 如果解析失败，尝试从 multiqc_data.json 直接加载
        # print(f"⚠️ Parsing logs failed to find modules. Attempting to load from multiqc_data.json...")
        _visualize_from_json(analysis_dir, target_modules)
        return

    # --- 🔍 5. 模块过滤 ---
    if target_modules:
        modules_to_visualize = [m for m in found_modules if m in target_modules]
        if not modules_to_visualize:
            # Maybe the user asked for "QualiMap" but it's not found in parsed logs
            # Check JSON fallback as well before giving up? 
            # Often if parse_logs finds SOME modules but not the target, it might be partial parse.
            # But simpler to just warn.
            print(f"⚠️ 警告: 目录中包含 {found_modules}，但没有你指定的 {target_modules}")
            return
    else:
        modules_to_visualize = found_modules

    # --- 🎨 6. 开始绘图 (Standard Method) ---
    for module_name in modules_to_visualize:
        
        modules_plots = all_plots.get(module_name, [])
        if not modules_plots:
            continue

        for item in modules_plots:
            item_name = "Unknown"
            if isinstance(item, str):
                item_name = item
            elif isinstance(item, dict):
                item_name = list(item.keys())[0]
            
            my_config = {
                'toImageButtonOptions': {
                    'format': 'png',
                    'filename': f'{module_name}_{item_name}_plot',
                    'height': 600,
                    'width': 1200,
                    'scale': 4
                },
                'displaylogo': False
            }
            
            try:
                mqc_plot_obj = multiqc.get_plot(module_name, item_name)
                
                if mqc_plot_obj:
                    fig = mqc_plot_obj.get_figure(0)
                    display(Markdown(f"**{module_name}** - **{item_name}** Visualization"))
                    fig.show(config=my_config)
                    
                    # --- 显示图注 (Caption) ---
                    if plot_captions and item_name in plot_captions:
                        display(Markdown(plot_captions[item_name]))
                    
                    # display(Markdown("\n---\n"))
                else:
                    pass
                    
            except Exception as e:
                print(f"❌ 绘制失败 [{module_name} - {item_name}]: {e}")
