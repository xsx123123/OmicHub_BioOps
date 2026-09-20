from cygnusx.application.services.agentteams_title import derive_agentteams_case_title


def test_title_removes_request_wrapper() -> None:
    assert derive_agentteams_case_title("创建一个数据质控团队：") == "数据质控团队"


def test_title_removes_workspace_reference_and_particles() -> None:
    assert (
        derive_agentteams_case_title(
            "@workspace/chat-uploads/example.treefile 帮我做一下系统发育树呀"
        )
        == "系统发育树"
    )


def test_title_truncates_long_intent_without_changing_source() -> None:
    intent = "请帮我分析这个项目中的全部转录组样本并生成差异表达与富集分析报告"
    title = derive_agentteams_case_title(intent)

    assert title.endswith("…")
    assert len(title) == 20
    assert intent.startswith("请帮我")
