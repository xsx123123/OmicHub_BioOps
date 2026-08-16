"""MCP Prompts — 预置工作流引导"""

from fastmcp import FastMCP

from client.api_client import OmicHubAPIClient


def register(mcp: FastMCP, api: OmicHubAPIClient) -> None:

    @mcp.prompt()
    def new_analysis(flow_id: str = "rna_seq") -> str:
        """引导完成一次完整的新分析流程"""
        return f"""请帮我完成一次 {flow_id} 分析，按以下步骤操作：

1. 调用 omichub_get_flow_detail(flow_id="{flow_id}") 了解流程参数要求
2. 调用 omichub_list_files() 查看我已有的数据文件
3. 根据我的数据配置参数和样本表
4. 调用 omichub_preview_analysis() 验证参数
5. 调用 omichub_submit_analysis(user_confirmed=True) 提交分析
6. 使用 omichub_get_task_progress() 轮询监控进度直到完成
7. 完成后调用 omichub_get_task_outputs() 查看结果

请在每一步向我确认关键参数后再继续。"""

    @mcp.prompt()
    def interpret_results(task_id: str) -> str:
        """引导解读分析结果"""
        return f"""请帮我解读任务 {task_id} 的分析结果：

1. 调用 omichub_get_task(task_id="{task_id}") 确认任务已完成
2. 调用 omichub_get_task_outputs(task_id="{task_id}") 获取输出路径
3. 使用 omichub_read_file_content() 读取关键结果文件：
   - 差异表达基因表 (DEG table)
   - QC 报告
   - 标准化计数矩阵
4. 总结主要发现：
   - 有多少显著差异基因？
   - 上调/下调比例如何？
   - QC 指标是否合格？
5. 建议下一步分析方向（富集分析、通路分析等）"""

    @mcp.prompt()
    def optimize_in_sandbox(task_id: str) -> str:
        """引导在沙箱中进行结果优化分析"""
        return f"""请帮我在沙箱中对任务 {task_id} 的结果进行深入分析：

1. 调用 omichub_get_task_outputs(task_id="{task_id}") 获取结果路径
2. 创建沙箱会话: omichub_sandbox_create()
3. 在沙箱中加载数据:
   ```python
   import pandas as pd
   import scanpy as sc
   # 读取差异基因结果
   degs = pd.read_csv('/data/platform/tasks/{task_id}/work/.../results/deseq2/all_degs.csv')
   ```
4. 进行自定义分析:
   - 调整筛选阈值 (|log2FC| > 1, padj < 0.05)
   - 绘制火山图 / 热图
   - 运行 GO/KEGG 富集分析
5. 生成发表级别的可视化图表

沙箱环境已预装: scanpy, anndata, pandas, numpy, matplotlib, seaborn, scipy, statsmodels"""

    @mcp.prompt()
    def download_and_analyze(accession: str, flow_id: str = "rna_seq") -> str:
        """引导完成从数据下载到分析的完整流程"""
        return f"""请帮我完成从数据下载到分析的完整流程：

1. 提交下载: omichub_submit_download(source="ebi", accession="{accession}", user_confirmed=True)
2. 监控下载进度: omichub_get_download_progress() 直到完成
3. 查看下载的数据: omichub_list_files(directory="raw_data")
4. 配置 {flow_id} 分析参数（根据下载的样本信息）
5. 提交分析: omichub_submit_analysis(flow_id="{flow_id}", ..., user_confirmed=True)
6. 监控分析进度直到完成
7. 解读分析结果

 accession: {accession}
 目标流程: {flow_id}"""

    @mcp.prompt()
    def troubleshoot_task(task_id: str) -> str:
        """引导排查任务失败原因"""
        return f"""请帮我排查任务 {task_id} 的问题：

1. 调用 omichub_get_task(task_id="{task_id}") 查看状态和错误信息
2. 调用 omichub_get_task_logs(task_id="{task_id}", lines=100) 查看详细日志
3. 如果是运行中卡住，检查 omichub_get_task_progress()
4. 分析错误原因:
   - 内存不足？→ 建议减少样本数或增加资源
   - 参考基因组缺失？→ 检查参数配置
   - 样本表格式错误？→ 检查列名和数据格式
   - Conda 环境构建失败？→ 检查网络或依赖版本
5. 给出修复建议，必要时帮助重新提交任务"""
