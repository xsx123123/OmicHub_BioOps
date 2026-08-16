"""Runtime Agent ability catalog hot-reload contracts."""

from pathlib import Path

from omichub.infrastructure.config.agent_ability_catalog import AgentAbilityCatalog


def test_ability_catalog_normalizes_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "agent_ability.yaml"
    path.write_text(
        "version: 1\nagents:\n  agent-a:\n"
        "    summary: 旧摘要\n"
        "    capabilities: [质控, 质控, '']\n"
        "    not_suitable_for: [执行]\n"
        "    handoff_when: [需要执行]\n"
        "    preferred_inputs: [样本表]\n",
        encoding="utf-8",
    )
    catalog = AgentAbilityCatalog(path)

    assert catalog.get("agent-a")["capabilities"] == ["质控"]
    assert catalog.get("agent-a")["chat_entry"] is True

    path.write_text(
        "version: 1\nagents:\n  agent-a:\n"
        "    summary: 新摘要\n"
        "    chat_entry: false\n"
        "    capabilities: [执行]\n"
        "    not_suitable_for: [无输入]\n"
        "    handoff_when: [缺文件]\n"
        "    preferred_inputs: [FASTQ]\n",
        encoding="utf-8",
    )
    assert catalog.get("agent-a")["summary"] == "新摘要"
    assert catalog.get("agent-a")["chat_entry"] is False
