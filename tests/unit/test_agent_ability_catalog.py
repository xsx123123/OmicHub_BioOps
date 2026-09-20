"""Runtime Agent ability catalog hot-reload contracts."""

from pathlib import Path

from cygnusx.infrastructure.config.agent_ability_catalog import AgentAbilityCatalog


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
    # 本机文件系统 mtime 粒度较粗，连续两次写入可能拿到相同 st_mtime_ns，
    # 导致热重载判定偶发不触发（flaky）；显式推进 mtime 使测试确定。
    import os

    bumped = path.stat().st_mtime_ns + 1_000_000
    os.utime(path, ns=(bumped, bumped))
    assert catalog.get("agent-a")["summary"] == "新摘要"
    assert catalog.get("agent-a")["chat_entry"] is False
