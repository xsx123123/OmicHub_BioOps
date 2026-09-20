"""建议追问 Chips 服务端解析（next_step_suggestions）单元测试。

用例与前端 ``frontend/src/utils/nextStepSuggestions.spec.ts`` 对齐，
保证双端解析规则一致。
"""

from cygnusx.application.services.chat.next_step_suggestions import (
    MAX_SUGGESTIONS,
    parse_next_step_suggestions,
    suggestions_metadata,
)

SAMPLE_REPLY = "\n".join(
    [
        "分析已完成，进化树已构建。",
        "",
        "**可选下一步**",
        "",
        "1. 标签精简/分组着色：把叶片名改成短名，并按分组着色",
        "2. 进化枝注释：在关键分支上添加 bootstrap 支持度",
        "3. 版式微调：把树旋转为横向排版并放大字体",
        "4. 提供 .contree 文件路径：我可以基于它叠加更多注释",
    ]
)


def test_parse_standard_section_splits_label_and_prompt() -> None:
    suggestions = parse_next_step_suggestions(SAMPLE_REPLY)
    assert len(suggestions) == 4
    assert suggestions[0] == {
        "label": "标签精简/分组着色",
        "prompt": "标签精简/分组着色：把叶片名改成短名，并按分组着色",
        "action": "send",
    }
    assert suggestions[1]["label"] == "进化枝注释"


def test_prefill_keywords_drive_action() -> None:
    suggestions = parse_next_step_suggestions(SAMPLE_REPLY)
    assert [s["action"] for s in suggestions] == ["send", "send", "send", "prefill"]
    assert parse_next_step_suggestions("可选下一步\n1. 上传参考基因组后继续比对")[0][
        "action"
    ] == "prefill"


def test_variant_headings_are_supported() -> None:
    body = "1. 调整配色：换成蓝紫色系"
    assert parse_next_step_suggestions(f"### 下一步建议\n{body}")[0]["label"] == "调整配色"
    assert len(parse_next_step_suggestions(f"## 可选下一步：\n{body}")) == 1
    assert len(parse_next_step_suggestions(f"**可选的下一步**\n{body}")) == 1


def test_missing_section_returns_empty() -> None:
    assert parse_next_step_suggestions("闲聊回复，没有任何建议。") == []
    assert parse_next_step_suggestions("") == []


def test_section_without_ordered_items_returns_empty() -> None:
    assert parse_next_step_suggestions("可选下一步\n暂无更多建议。") == []
    assert parse_next_step_suggestions("可选下一步\n- 无序列表不算数\n- 也不算") == []


def test_items_are_capped_at_max_suggestions() -> None:
    items = [f"{i + 1}. 建议{i + 1}：继续" for i in range(6)]
    suggestions = parse_next_step_suggestions("\n".join(["可选下一步", *items]))
    assert len(suggestions) == MAX_SUGGESTIONS
    assert suggestions[MAX_SUGGESTIONS - 1]["label"] == "建议4"


def test_label_falls_back_to_truncated_prefix() -> None:
    (suggestion,) = parse_next_step_suggestions(
        "可选下一步\n1. 这是一条没有任何分隔符的超长建议条目文本内容",
    )
    assert suggestion["label"] == "这是一条没有任何分隔符的…"
    assert suggestion["prompt"] == "这是一条没有任何分隔符的超长建议条目文本内容"


def test_dash_separator_and_fullwidth_index_marker() -> None:
    suggestions = parse_next_step_suggestions(
        "可选下一步\n1、支持度叠加 — 在分支上显示 bootstrap 值\n2) 导出图片 - 生成高清 PNG",
    )
    assert len(suggestions) == 2
    assert suggestions[0]["label"] == "支持度叠加"
    assert suggestions[1]["label"] == "导出图片"


def test_collection_stops_at_next_heading_or_paragraph() -> None:
    markdown = "可选下一步\n1. 第一条：继续\n\n## 其他说明\n2. 这条属于别的章节\n3. 也是"
    assert len(parse_next_step_suggestions(markdown)) == 1


def test_inline_markdown_is_stripped_from_items() -> None:
    (suggestion,) = parse_next_step_suggestions(
        "可选下一步\n1. **版式调整**：参考 [样式指南](https://example.com) 微调",
    )
    assert suggestion["label"] == "版式调整"
    assert suggestion["prompt"] == "版式调整：参考 样式指南 微调"


def test_invalid_input_returns_empty_without_raising() -> None:
    assert parse_next_step_suggestions(None) == []


def test_prose_mentioning_section_title_is_not_treated_as_heading() -> None:
    prose = "如果你愿意，我可以给出可选下一步的详细说明，包括更多分析方向供你选择"
    assert parse_next_step_suggestions(f"{prose}\n1. 误命中：不该被解析") == []


def test_suggestions_metadata_omits_field_when_empty() -> None:
    assert suggestions_metadata("闲聊回复，没有任何建议。") == {}
    payload = suggestions_metadata(SAMPLE_REPLY)
    assert len(payload["suggestions"]) == 4
    assert payload["suggestions"][3]["action"] == "prefill"


def test_done_event_end_to_end_serialization_shape() -> None:
    """端到端冒烟（后端半段）：含"可选下一步"的回复 → done 事件挂载 suggestions →
    经 chat.py 出口相同的 {type, content, **metadata} 合并与 JSON 序列化后，
    前端可拿到形状完整的 suggestions（label/prompt/action）。"""
    import json

    from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

    done = ChatChunk(
        type="done",
        metadata={
            "session_id": "s1",
            "message_id": "m1",
            **suggestions_metadata(SAMPLE_REPLY),
        },
    )
    # 与 api/v1/chat.py generate_sse 相同的出口封装
    data = {"type": done.type, "content": done.content}
    data.update(done.metadata)
    frame = f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    decoded = json.loads(frame.removeprefix("data: ").strip())
    assert decoded["type"] == "done"
    suggestions = decoded["suggestions"]
    assert [s["action"] for s in suggestions] == ["send", "send", "send", "prefill"]
    assert all({"label", "prompt", "action"} <= set(s) for s in suggestions)

    # 解析为空时字段不出现（不留空数组占位）
    bare = ChatChunk(
        type="done",
        metadata={"session_id": "s1", **suggestions_metadata("没有建议的回复")},
    )
    bare_data = {"type": bare.type, "content": bare.content}
    bare_data.update(bare.metadata)
    assert "suggestions" not in bare_data
