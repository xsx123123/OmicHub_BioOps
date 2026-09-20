from cygnusx.application.services.agentteams_mention_resolver import resolve_room_mentions


class Registry:
    def role_labels(self):
        return {
            "scrna": {"agent_id": "agent-scrna", "name": "单细胞助手"},
            "rnaseq": {"agent_id": "agent-rnaseq", "name": "RNA助手"},
        }


def test_resolves_manager_typo_and_direct_agent() -> None:
    result = resolve_room_mentions("@mamager 请协调 @单细胞助手 的进度", registry=Registry())

    assert result["dispatch_mode"] == "manager"
    assert result["target_agent_id"] is None
    assert [item["kind"] for item in result["mentions"]] == ["manager", "agent"]


def test_resolves_single_domain_agent() -> None:
    result = resolve_room_mentions("@agent-scrna 请评估这个结果", registry=Registry())

    assert result["dispatch_mode"] == "direct"
    assert result["target_agent_id"] == "agent-scrna"


def test_multiple_agents_fall_back_to_manager_coordination() -> None:
    result = resolve_room_mentions("@agent-scrna @agent-rnaseq 一起看一下", registry=Registry())

    assert result["dispatch_mode"] == "multi_direct"
    assert result["target_agent_id"] is None
    assert result["target_agent_ids"] == ["agent-scrna", "agent-rnaseq"]


def test_realistic_display_names_dispatch_to_multi_direct() -> None:
    result = resolve_room_mentions(
        "@单细胞分析师 @可视化助手 你们两个可以搭配干活吗",
        registry=Registry(),
        role_labels={
            "scrna": {"agent_id": "agent-scrna", "name": "单细胞分析师"},
            "viz": {"agent_id": "agent-viz", "name": "可视化助手"},
        },
    )

    assert result["dispatch_mode"] == "multi_direct"
    assert result["target_agent_id"] is None
    assert result["target_agent_ids"] == ["agent-scrna", "agent-viz"]


def test_space_truncated_display_name_prefix_matches_single_agent() -> None:
    """展示名含空格时 @ 只捕获空格前片段（如 @RNA-seq），按唯一前缀兜底路由。"""
    result = resolve_room_mentions(
        "@RNA-seq 分析师 帮我复述一下经理的回复内容",
        registry=Registry(),
        role_labels={
            "bioops-manager": {"agent_id": "agentteams-manager", "name": "生物信息部门经理"},
            "rnaseq": {"agent_id": "agent-rnaseq", "name": "RNA-seq 分析师"},
            "scrna": {"agent_id": "agent-scrna", "name": "单细胞分析师"},
            "atacseq": {"agent_id": "agent-atacseq", "name": "ATAC-seq 分析师"},
        },
    )

    assert result["dispatch_mode"] == "direct"
    assert result["target_agent_id"] == "agent-rnaseq"
    assert result["unknown_mentions"] == []
    assert result["mentions"][0]["display_name"] == "RNA-seq 分析师"


def test_ambiguous_prefix_stays_unknown() -> None:
    """前缀命中多个 agent（如 @agent）时不猜测派发，保持未知提及走 manager。"""
    result = resolve_room_mentions(
        "@agent 请帮忙看看",
        registry=Registry(),
        role_labels={
            "scrna": {"agent_id": "agent-scrna", "name": "单细胞分析师"},
            "rnaseq": {"agent_id": "agent-rnaseq", "name": "RNA-seq 分析师"},
        },
    )

    assert result["dispatch_mode"] == "manager"
    assert result["target_agent_id"] is None
    assert result["unknown_mentions"] == ["agent"]


def test_manager_chinese_display_name_routes_to_manager_loop() -> None:
    """@生物信息部门经理 / @生物信息经理 都回归 Manager 主回路。"""
    for token in ("生物信息部门经理", "生物信息经理"):
        result = resolve_room_mentions(
            f"@{token} 在吗",
            registry=Registry(),
            role_labels={
                "bioops-manager": {"agent_id": "agentteams-manager", "name": "生物信息部门经理"},
                "scrna": {"agent_id": "agent-scrna", "name": "单细胞分析师"},
            },
        )
        assert result["dispatch_mode"] == "manager"
        assert result["target_agent_id"] is None
        assert [item["kind"] for item in result["mentions"]] == ["manager"]
