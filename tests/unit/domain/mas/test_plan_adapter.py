from cygnusx.application.services.mas_plan_adapter import MASPlanPreviewAdapter


def test_plan_preview_adapter_returns_frontend_safe_dual_payload() -> None:
    result = MASPlanPreviewAdapter().adapt(
        {
            "title": "RNA 计划预览",
            "nodes": [
                {
                    "key": "rnaseq",
                    "agent_id": "agent-rnaseq",
                    "intent": "运行 RNAFlow",
                    "resources": {"required_capabilities": ["rnaflow"]},
                }
            ],
            "context_summary": {"accession": "PRJNA000001"},
        }
    )

    assert result["success"] is True
    payload = result["result"]["ui_payload"]
    assert payload["mas_plan"]["title"] == "RNA 计划预览"
    assert payload["context_summary"] == {"accession": "PRJNA000001"}


def test_plan_preview_adapter_rejects_unregistered_agents() -> None:
    result = MASPlanPreviewAdapter().adapt(
        {
            "title": "无效计划",
            "nodes": [
                {"key": "unknown", "agent_id": "agent-unknown", "intent": "执行"}
            ],
        }
    )

    assert result["success"] is False
    assert "未注册" in result["error"]
