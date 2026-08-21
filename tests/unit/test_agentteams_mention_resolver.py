from types import SimpleNamespace

from omichub.application.services.agentteams_mention_resolver import resolve_room_mentions


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

    assert result["dispatch_mode"] == "manager"
    assert result["target_agent_id"] is None

