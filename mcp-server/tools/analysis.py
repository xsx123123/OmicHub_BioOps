"""分析提交工具"""

from fastmcp import FastMCP

from client.api_client import OmicHubAPIClient, OmicHubAPIError


def register(mcp: FastMCP, api: OmicHubAPIClient) -> None:

    @mcp.tool()
    async def omichub_submit_analysis(
        flow_id: str,
        name: str = "",
        parameters: dict | None = None,
        sample_sheet: list[dict] | None = None,
        comparisons: list[dict] | None = None,
        user_confirmed: bool = False,
    ) -> dict:
        """提交分析任务到平台。需要 user_confirmed=True 确认执行。

        Args:
            flow_id: 流程 ID (如 rna_seq, atac_seq)
            name: 任务名称
            parameters: 流程参数字典
            sample_sheet: 样本表 (list of dicts, 每个 dict 对应一个样本)
            comparisons: 比较组 (如 [{"name": "vs", "control": "ctrl", "treatment": "treat"}])
            user_confirmed: 设为 True 确认提交
        """
        if not user_confirmed:
            return {
                "success": True,
                "needs_confirmation": True,
                "summary": (
                    f"即将提交分析任务:\n"
                    f"  流程: {flow_id}\n"
                    f"  名称: {name or '(自动生成)'}\n"
                    f"  样本数: {len(sample_sheet) if sample_sheet else 0}\n"
                    f"  比较组: {len(comparisons) if comparisons else 0}\n"
                    f"请确认参数无误后设置 user_confirmed=True 重新调用。"
                ),
                "data": {
                    "flow_id": flow_id,
                    "name": name,
                    "parameters": parameters,
                    "sample_sheet": sample_sheet,
                    "comparisons": comparisons,
                },
            }

        payload = {
            "flow_id": flow_id,
            "name": name or f"{flow_id} analysis",
            "parameters": parameters or {},
            "sample_sheet": sample_sheet or [],
        }
        if comparisons:
            payload["comparisons"] = comparisons

        try:
            result = await api.submit_task(payload)
            task_id = result.get("id", "?")
            return {
                "success": True,
                "summary": (
                    f"分析任务已提交!\n"
                    f"  任务 ID: {task_id}\n"
                    f"  状态: {result.get('status', 'queued')}\n"
                    f"使用 omichub_get_task_progress 监控进度。"
                ),
                "data": result,
                "next_steps": [
                    f"调用 omichub_get_task_progress(task_id='{task_id}') 监控进度",
                    "任务完成后调用 omichub_get_task_outputs 查看结果",
                ],
            }
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"提交失败: {e.detail}"}

    @mcp.tool()
    async def omichub_preview_analysis(
        flow_id: str,
        parameters: dict | None = None,
        sample_sheet: list[dict] | None = None,
    ) -> dict:
        """预览/验证分析参数（dry-run）：检查参数是否合法，不实际提交。"""
        try:
            flow = await api.get_flow(flow_id)
            flow_params = flow.get("parameters", [])
            required = [
                p.get("name", p.get("key"))
                for p in flow_params
                if p.get("required", False)
            ]
            provided = set((parameters or {}).keys())
            missing = [r for r in required if r not in provided]

            issues = []
            if missing:
                issues.append(f"缺少必填参数: {', '.join(missing)}")
            if not sample_sheet and flow.get("sample_sheet"):
                issues.append("该流程需要样本表 (sample_sheet)")

            if issues:
                return {
                    "success": False,
                    "summary": "参数验证未通过:\n" + "\n".join(f"- {i}" for i in issues),
                    "data": {"missing_params": missing},
                }
            return {
                "success": True,
                "summary": f"参数验证通过，可以提交 {flow_id} 分析。",
                "data": {"flow_id": flow_id, "valid": True},
            }
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"验证失败: {e.detail}"}
