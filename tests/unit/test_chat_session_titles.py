from cygnusx.application.services.chat_service import ChatService


def test_clean_session_title_removes_wrappers_and_limits_length():
    title = ChatService._clean_session_title('  「RNA-seq\n差异表达分析与可视化工作流优化方案」  ')

    assert title == "RNA-seq差异表达分析与可视化工作流优化方案"
    assert len(title) <= 30


def test_fallback_session_title_truncates_long_message():
    title = ChatService._fallback_session_title("请帮我分析这个项目中的所有RNA测序样本并绘制火山图")

    assert title.endswith("…")
    assert len(title) == 16


def test_clean_session_title_strips_third_person_narration():
    assert (
        ChatService._clean_session_title("用户想要处理VCF文件并询问安装")
        == "处理VCF文件并询问安装"
    )
    assert ChatService._clean_session_title("标题：该用户希望做GO富集") == "做GO富集"
    assert ChatService._clean_session_title("最初询问了火山图怎么画") == "火山图怎么画"
    # 主题式标题不含叙述前缀，保持原样
    assert ChatService._clean_session_title("DESeq2 差异分析与火山图") == "DESeq2 差异分析与火山图"


def test_escape_like_treats_wildcards_as_text():
    assert ChatService._escape_like(r"RNA_100%\done") == r"RNA\_100\%\\done"


def test_search_snippet_centers_keyword_and_marks_truncation():
    content = "前文" * 40 + "差异表达" + "后文" * 40

    snippet = ChatService._build_search_snippet(content, "差异表达")

    assert "差异表达" in snippet
    assert snippet.startswith("…")
    assert snippet.endswith("…")


def test_is_topic_title_rejects_summary_style_output():
    # 摘要式/叙述式产出应被拒（走 fallback）
    assert not ChatService._is_topic_title(
        "用户输入了hi，助手回复了自我介绍和能提供的帮助列表，并询问有什么可以帮忙的。对"
    )
    assert not ChatService._is_topic_title("助手回复了差异分析步骤")
    assert not ChatService._is_topic_title("用户咨询RNA-seq流程。")
    assert not ChatService._is_topic_title("")
    assert not ChatService._is_topic_title("x" * 16)
    # 主题短语式标题放行
    assert ChatService._is_topic_title("DESeq2 差异分析与火山图")
    assert ChatService._is_topic_title("日常问候")
    assert ChatService._is_topic_title("FASTQ 质控报错排查")
