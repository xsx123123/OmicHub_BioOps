"""Skill 调用遥测分析器的纯函数回归测试。"""

from __future__ import annotations

from scripts.analyze_skill_invocations import (
    _build_proposal,
    _extract_markers,
    _group_unhit_messages,
)


def test_extract_markers_splits_mixed_content():
    markers = _extract_markers("请把 h5ad 转成 rds 并重聚类")
    assert "h5ad" in markers
    assert "rds" in markers
    assert "转成" in markers
    assert "重聚" in markers or "聚类" in markers
    # 单字应被过滤
    assert "把" not in markers


def test_extract_markers_filters_stopwords():
    markers = _extract_markers("帮我做一个火山图")
    assert "火山" in markers
    assert "山图" in markers
    assert "帮我" not in markers
    assert "一个" not in markers


def test_group_unhit_messages_finds_common_patterns():
    messages = [
        "请把 h5ad 转成 rds",
        "h5ad 怎么转 rds",
        "转 rds 后重聚类",
        "画一个火山图",
        "帮我画火山图",
    ]
    groups = _group_unhit_messages(messages, min_sessions=2)
    assert len(groups) >= 2
    skill_ids = {g["proposal_skill_id"] for g in groups}
    assert any("rds" in sid or "h5ad" in sid for sid in skill_ids)
    assert any("火山" in sid for sid in skill_ids)
    for g in groups:
        assert g["session_count"] >= 2
        assert g["sample_message"]
        assert g["markers"]


def test_group_unhit_messages_respects_min_sessions():
    messages = ["唯一消息", "另一个唯一消息"]
    groups = _group_unhit_messages(messages, min_sessions=3)
    assert groups == []


def test_build_proposal_for_high_volume():
    assert "拆分" in _build_proposal("x", 50)


def test_build_proposal_for_moderate_volume():
    assert "挂载 Agent" in _build_proposal("x", 10)


def test_build_proposal_for_low_volume():
    assert "较低" in _build_proposal("x", 1)
