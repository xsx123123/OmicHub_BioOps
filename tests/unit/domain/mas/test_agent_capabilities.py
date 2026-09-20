from pathlib import Path

from cygnusx.infrastructure.mas.agent_capabilities import load_agent_capabilities


def test_loads_server_owned_agent_capabilities(tmp_path: Path) -> None:
    # load_agent_capabilities merges hand-registered capabilities with executor keys
    # auto-derived from data/ai/flows/*.yaml by get_flow_registry().
    # The YAML under tmp_path declares agent-rnaseq with two capabilities; the flow
    # registry adds deseq2 (from flows/rnaseq.yaml) and all scrna executor keys
    # (from flows/scrna.yaml) for the respective actors.
    path = tmp_path / "agent_capabilities.yaml"
    path.write_text("agents:\n  agent-rnaseq: [rnaflow, quality-gate]\n")

    caps = load_agent_capabilities(path)

    # Hand-registered capabilities are preserved.
    assert {"rnaflow", "quality-gate"}.issubset(caps["agent-rnaseq"])
    # Flow-derived executor keys are merged in (rnaseq flow adds deseq2).
    assert "deseq2" in caps["agent-rnaseq"]
    # The scrna flow actor also gets its executor capabilities auto-derived.
    assert "agent-scrna" in caps
    assert "scrna-cellranger" in caps["agent-scrna"]

    assert load_agent_capabilities(tmp_path / "missing.yaml") == {}
