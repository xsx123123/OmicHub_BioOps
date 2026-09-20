"""F9 离线 eval 闭环（Manager 组队质量评测）单元测试。

覆盖：样本集合法性（20-30 条、来源标注、金标准 agent 在注册表内）、
集合级 P/R/F1 口径、stub 确定性与输出契约、replay fixtures、A 臂离线可跑。
全部离线，不触网、不需要凭证。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "poc" / "teaming_eval"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

import run_teaming_eval as te  # noqa: E402


@pytest.fixture(scope="module")
def samples() -> list[te.Sample]:
    return te.load_samples()


@pytest.fixture(scope="module")
def registry():
    return te.AgentTeamsCapabilityRegistry()


def test_sample_count_within_f9_spec(samples: list[te.Sample]) -> None:
    assert 20 <= len(samples) <= 30


def test_samples_have_source_and_valid_gold(samples: list[te.Sample], registry) -> None:
    valid_ids = set(registry.registered_agent_ids())
    for sample in samples:
        assert sample.text.strip(), sample.id
        assert sample.source.strip(), f"{sample.id} 缺来源标注"
        unknown = sample.gold_experts - valid_ids
        assert not unknown, f"{sample.id} 金标准含未注册 agent: {unknown}"


def test_prf1_edge_cases() -> None:
    assert te.prf1(frozenset(), set()) == (1.0, 1.0, 1.0)
    assert te.prf1(frozenset({"a"}), set()) == (0.0, 0.0, 0.0)
    assert te.prf1(frozenset(), {"a"}) == (0.0, 0.0, 0.0)
    p, r, f1 = te.prf1(frozenset({"a", "b"}), {"a", "c"})
    assert (p, r) == (0.5, 0.5)
    assert f1 == pytest.approx(0.5)


def test_mean_std_single_sample_stddev_zero() -> None:
    assert te.mean_std([0.5]) == (0.5, 0.0)
    mean, std = te.mean_std([0.0, 1.0])
    assert mean == pytest.approx(0.5)
    assert std == pytest.approx(0.7071, abs=1e-3)


def test_arm_a_offline_deterministic(samples: list[te.Sample]) -> None:
    """A 臂纯规则路由：离线可跑、两次运行结果一致、零 LLM token。"""
    sample = samples[0]
    first = te.run_arm_a(sample.text)
    second = te.run_arm_a(sample.text)
    assert first.predicted == second.predicted
    assert first.prompt_tokens == 0 and first.completion_tokens == 0


def test_stub_llm_deterministic_and_valid(registry) -> None:
    stub = te.make_stub_llm(registry)
    valid_ids = {str(c["agent_id"]) for c in registry.snapshot()["chat_router_catalog"]}
    out1 = stub("sys", "我想分析小鼠脑损伤的 RNA-seq 数据", "S05")
    out2 = stub("sys", "我想分析小鼠脑损伤的 RNA-seq 数据", "S05")
    assert out1 == out2
    decision = te.parse_router_decision(out1, valid_ids)
    assert decision is not None
    assert decision["agent_id"] in valid_ids


def test_stub_llm_fallback_on_no_keyword(registry) -> None:
    stub = te.make_stub_llm(registry)
    decision = te.parse_router_decision(
        stub("sys", "hi", "S04"),
        {str(c["agent_id"]) for c in registry.snapshot()["chat_router_catalog"]},
    )
    assert decision is not None
    assert decision["agent_id"]  # 回落通用入口
    assert decision["confidence"] < 0.6  # 低置信度 → 需澄清


def test_parse_router_decision_filters_invalid_ids() -> None:
    decision = te.parse_router_decision(
        '{"agent_id": "agent-rnaseq", "consult_agent_ids": ["agent-fake", "agent-qc"], '
        '"confidence": 0.9, "collaboration_intent": "consult"}',
        {"agent-rnaseq", "agent-qc"},
    )
    assert decision["agent_id"] == "agent-rnaseq"
    assert decision["consult_agent_ids"] == ["agent-qc"]
    assert te.parse_router_decision("非 JSON 输出", {"a"}) is None


def test_replay_llm_fixtures(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps({"S01": '{"agent_id": "agent-scrna", "confidence": 0.9}'}))
    replay = te.make_replay_llm(fixtures)
    assert json.loads(replay("sys", "user", "S01"))["agent_id"] == "agent-scrna"
    with pytest.raises(KeyError):
        replay("sys", "user", "S99")


def test_live_llm_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("TEAMING_EVAL_LLM_BASE_URL", "TEAMING_EVAL_LLM_API_KEY", "TEAMING_EVAL_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError, match="TEAMING_EVAL_LLM"):
        te.make_live_llm()


def test_arm_b_stub_prompt_tokens_measured(samples: list[te.Sample], registry) -> None:
    """B 臂 prompt token 与 W3 口径一致（tiktoken cl100k，summary 层目录注入）。"""
    stub = te.make_stub_llm(registry)
    result = te.run_arm_b(samples[4].text, registry=registry, llm=stub, sample_id="S05")
    assert result.prompt_tokens > 0
    assert result.predicted  # stub 对 RNA-seq 样本应给出非空组队
    assert not result.detail.get("parse_failed")
