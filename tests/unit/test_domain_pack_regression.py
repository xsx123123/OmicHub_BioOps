"""Domain Pack 重构前后的调度认知层行为回归。"""

import pytest

import omichub.application.services.chat_service as chat_module
from omichub.application.services.chat_service import (
    _analysis_intake_questions,
    _default_overdrive_assignments,
    _extract_overdrive_intake_slots,
    _filter_overdrive_questions,
    _is_overdrive_planning_request,
    _overdrive_capability_profile,
    _overdrive_preflight_questions,
)
from omichub.application.services.domain_registry import DomainRegistry
from omichub.application.services.overdrive_plan_constraint_service import validate_plan

CATALOG = [
    {"agent_id": "agent-general", "name": "通用助手", "category": "general"},
    {"agent_id": "agent-code", "name": "代码助手", "category": "code"},
    {"agent_id": "agent-viz", "name": "可视化助手", "category": "visualization"},
    {"agent_id": "agent-scrna", "name": "单细胞分析师", "category": "omics"},
    {"agent_id": "agent-scrna-upstream", "name": "单细胞上游与样本质控专家", "category": "omics"},
    {"agent_id": "agent-scrna-integration", "name": "单细胞整合与聚类专家", "category": "omics"},
    {"agent_id": "agent-scrna-advanced", "name": "单细胞注释与高级分析专家", "category": "omics"},
    {"agent_id": "agent-rnaseq", "name": "RNA-seq 分析师", "category": "omics"},
]


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("帮我设计一个 TP53 相关的 rna 挖掘方案", True),
        ("给我做个代码审查计划", False),
    ],
)
def test_overdrive_planning_request_regression(content: str, expected: bool) -> None:
    assert _is_overdrive_planning_request(content) is expected


def test_omics_intake_skips_answered_grouping_but_asks_missing_modality_and_samples() -> None:
    questions = _analysis_intake_questions("帮我设计一个 TP53 突变 vs 野生型的 rna 挖掘方案")
    question_texts = [item["question"] for item in questions]

    assert any("模态" in question for question in question_texts)
    assert not any("分组是如何定义" in question for question in question_texts)
    assert any("多少样本或细胞" in question for question in question_texts)


def test_omics_intake_asks_generic_grouping_question() -> None:
    questions = _analysis_intake_questions("设计一个分组研究的组学方案")
    grouping = next(item for item in questions if "分组是如何定义" in item["question"])

    assert "TP53" not in grouping["question"]
    assert grouping["options"] == ["病例 vs 对照", "治疗/干预 vs 对照", "高值 vs 低值", "其他定义"]


def test_omics_intake_uses_tp53_subject_rule() -> None:
    questions = _analysis_intake_questions("设计一个 tp53 分组方案")
    grouping = next(item for item in questions if "分组是如何定义" in item["question"])

    assert "TP53 分组" in grouping["question"]
    assert grouping["options"][0] == "TP53 突变 vs 野生型"


def test_phylo_slots_identify_existing_tree_visualization() -> None:
    slots = _extract_overdrive_intake_slots("请处理/美化已有树")

    assert slots["task_type"] == "tree_visualization"


@pytest.mark.parametrize(
    "content",
    [
        "用ggtree绘制一下 treeplot",
        "帮我绘制系统发育树",
        "帮我画一个树图",
        "用 iqtree 绘制树图",
        "treeplot 帮我画树",
    ],
)
def test_phylo_slots_identify_tree_drawing_phrasings_as_visualization(content: str) -> None:
    slots = _extract_overdrive_intake_slots(content)

    assert slots["task_type"] == "tree_visualization"


def test_tnpd_genome_comparison_is_recognized_as_phylogeny_construction() -> None:
    request = "我要将tnpd序列对比到20个基因组进行进化分析与建树"

    assert _is_overdrive_planning_request(request) is True
    assert _extract_overdrive_intake_slots(request)["task_type"] == "phylogeny_construction"


def test_tnpd_preflight_asks_phylogeny_inputs_not_omics_modality() -> None:
    questions = _overdrive_preflight_questions(
        "我要将tnpd序列对比到20个基因组进行进化分析与建树"
    )
    question_texts = [item["question"] for item in questions]

    assert any("真实输入" in question for question in question_texts)
    assert any("序列类型" in question for question in question_texts)
    assert any("20 个基因组" in question for question in question_texts)
    assert not any("数据属于哪种模态" in question for question in question_texts)


def test_phylo_slots_identify_treefile() -> None:
    slots = _extract_overdrive_intake_slots("我有一个 .treefile 文件")

    assert slots["input_format"] == "treefile"


def test_phylo_filter_hides_tree_construction_questions_for_existing_tree() -> None:
    filtered = _filter_overdrive_questions(
        [
            {"question": "你希望使用哪种建树软件？"},
            {"question": "树上需要展示哪些注释？"},
        ],
        {"task_type": "tree_visualization"},
    )

    assert filtered == [{"question": "树上需要展示哪些注释？"}]


def test_phylo_filter_hides_msa_when_branch_selection_is_pending() -> None:
    filtered = _filter_overdrive_questions(
        [
            {"question": "你的核心需求是从头构建还是处理/美化已有树？"},
            {"question": "你的 MSA 状态如何？"},
        ],
        {},
    )

    assert filtered == [{"question": "你的核心需求是从头构建还是处理/美化已有树？"}]


def test_rnaseq_capability_profile_regression() -> None:
    profile = _overdrive_capability_profile(
        agent_id="agent-rnaseq",
        name="RNA-seq 分析师",
        category="omics",
        features={
            "default_role": "bulk RNA-seq 领域方案与统计分析",
            "capability_scope": ["bulk RNA-seq", "QC", "差异表达", "通路富集", "网络分析"],
        },
    )

    assert profile == {
        "default_role": "bulk RNA-seq 领域方案与统计分析",
        "capability_scope": ["bulk RNA-seq", "QC", "差异表达", "通路富集", "网络分析"],
    }


def test_unknown_agent_capability_profile_regression() -> None:
    profile = _overdrive_capability_profile(
        agent_id="agent-xyz", name="未知专家", category="specialist"
    )

    assert profile == {
        "default_role": "仅处理其描述和已挂载工具覆盖的专业任务",
        "capability_scope": ["specialist"],
    }


def test_default_assignment_uses_viz_for_existing_tree() -> None:
    assignments = _default_overdrive_assignments(
        "处理已有树", CATALOG, {"task_type": "tree_visualization"}
    )

    assert assignments == [
        {
            "task_id": "tree-visualization",
            "agent_id": "agent-viz",
            "task": "处理用户已有的系统发育树文件，先验证 Newick/treefile 可解析性，再完成树注释、美化和 publication-ready 图表交付；不要重新执行序列比对或建树。",
            "depends_on": [],
        }
    ]


def test_default_assignment_builds_tnpd_phylogeny_dag() -> None:
    request = "我要将tnpd序列对比到20个基因组进行进化分析与建树"
    assignments = _default_overdrive_assignments(
        request, CATALOG, _extract_overdrive_intake_slots(request)
    )

    assert [item["task_id"] for item in assignments] == [
        "tnpd-homolog-search",
        "tnpd-phylogeny",
    ]
    assert [item["agent_id"] for item in assignments] == ["agent-code", "agent-viz"]
    assert assignments[1]["depends_on"] == ["tnpd-homolog-search"]
    assert any("候选同源序列 FASTA" in item for item in assignments[0]["produces_outputs"])
    assert any("Newick/treefile" in item for item in assignments[1]["produces_outputs"])


def test_authoritative_assignment_mode_returns_only_declared_domain_anchors() -> None:
    request = "我要将tnpd蛋白序列对比到20个基因组进行进化分析与建树"

    assignments = _default_overdrive_assignments(
        request,
        CATALOG,
        _extract_overdrive_intake_slots(request),
        authoritative_only=True,
    )

    assert [item["task_id"] for item in assignments] == [
        "tnpd-homolog-search",
        "tnpd-phylogeny",
    ]
    scrna_assignments = _default_overdrive_assignments(
        "做个单细胞分析计划", CATALOG, authoritative_only=True
    )
    assert [item["task_id"] for item in scrna_assignments] == [
        "scrna-sample-contract",
        "scrna-integration-clustering",
        "scrna-immune-tolerance",
    ]
    assert _default_overdrive_assignments(
        "做个代码审查计划", CATALOG, authoritative_only=True
    ) == []


def test_default_assignment_uses_scrna_for_single_cell_plan() -> None:
    assignments = _default_overdrive_assignments(
        "帮我创建一下基于tp53的小鼠10个样本的单细胞分析方案，期望发现在肺癌免疫耐受相关的基因和机制",
        CATALOG,
    )

    assert [item["task_id"] for item in assignments] == [
        "scrna-sample-contract",
        "scrna-integration-clustering",
        "scrna-immune-tolerance",
    ]
    assert [item["agent_id"] for item in assignments] == [
        "agent-scrna-upstream",
        "agent-scrna-integration",
        "agent-scrna-advanced",
    ]
    assert assignments[1]["depends_on"] == ["scrna-sample-contract"]
    assert assignments[2]["depends_on"] == ["scrna-integration-clustering"]


def test_default_assignment_uses_code_fallback_for_non_planning_request() -> None:
    assignments = _default_overdrive_assignments("写个 python 脚本", CATALOG)

    assert assignments[0]["agent_id"] == "agent-code"
    assert assignments[0]["task_id"] == "code-task"


def test_empty_domain_registry_safely_degrades(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(chat_module, "get_domain_registry", lambda: DomainRegistry(tmp_path))

    assert _is_overdrive_planning_request("设计一个 RNA-seq 分析方案") is False
    assert _analysis_intake_questions("设计一个 RNA-seq 分析方案") == []
    assert _extract_overdrive_intake_slots("我有一个 .treefile 文件", {"keep": True}) == {
        "keep": True
    }
    questions = [{"question": "是否需要代码？"}]
    assert _filter_overdrive_questions(questions, {}) == questions
    assert _default_overdrive_assignments("写个 python 脚本", CATALOG) == []


GENERAL_CATALOG = [
    {"agent_id": "agent-data", "name": "数据管理员", "category": "data"},
    {"agent_id": "agent-code", "name": "代码助手", "category": "code"},
    {"agent_id": "agent-delivery", "name": "交付助手", "category": "delivery"},
    {"agent_id": "agent-viz", "name": "可视化助手", "category": "visualization"},
    {"agent_id": "agent-general", "name": "通用助手", "category": "general"},
]

GENERAL_ACCEPTANCE_REQUEST = "对里面的基因做文献检索，整理成文档和网页报告"


def test_general_domain_anchors_fire_in_order_for_literature_report_request() -> None:
    slots = _extract_overdrive_intake_slots(GENERAL_ACCEPTANCE_REQUEST)
    assignments = _default_overdrive_assignments(
        GENERAL_ACCEPTANCE_REQUEST, GENERAL_CATALOG, slots, authoritative_only=True
    )

    assert [item["task_id"] for item in assignments] == [
        "general-file-processing",
        "general-literature-search",
        "general-report-generation",
    ]
    assert [item["agent_id"] for item in assignments] == [
        "agent-data",
        "agent-data",
        "agent-delivery",
    ]
    assert assignments[1]["depends_on"] == ["general-file-processing"]
    assert assignments[2]["depends_on"] == ["general-literature-search"]


def test_general_domain_anchors_pass_plan_constraint_validation() -> None:
    registry = chat_module.get_domain_registry()
    slots = _extract_overdrive_intake_slots(GENERAL_ACCEPTANCE_REQUEST)
    rules = [
        rule
        for rule in registry.assignment_rules(GENERAL_ACCEPTANCE_REQUEST, slots)
        if rule.authoritative and rule.required
    ]
    assignments = _default_overdrive_assignments(
        GENERAL_ACCEPTANCE_REQUEST, GENERAL_CATALOG, slots, authoritative_only=True
    )
    catalog_by_id = {item["agent_id"]: item for item in GENERAL_CATALOG}

    assert validate_plan(assignments, rules, catalog_by_id) == []

    reordered = [dict(item, depends_on=[]) for item in reversed(assignments)]
    violations = validate_plan(reordered, rules, catalog_by_id)
    assert any("顺序错误" in item for item in violations)
    assert validate_plan(assignments[1:], rules, catalog_by_id) == ["缺失必需锚点 general-file-processing"]


def test_general_domain_partial_activation_only_emits_requested_anchors() -> None:
    request = "把结果汇总成网页报告"
    slots = _extract_overdrive_intake_slots(request)
    assignments = _default_overdrive_assignments(
        request, GENERAL_CATALOG, slots, authoritative_only=True
    )

    assert [item["task_id"] for item in assignments] == ["general-report-generation"]


def test_phylo_homolog_search_wording_does_not_trigger_general_anchors() -> None:
    request = (
        "我要将 TnpD 蛋白质序列对比到20个基因组进行进化分析与建树；"
        "已上传 query.faa、20个基因组 FASTA/GFF，将用 DIAMOND 检索同源序列。"
    )
    slots = _extract_overdrive_intake_slots(request)
    rules = chat_module.get_domain_registry().assignment_rules(request, slots)

    assert not [rule for rule in rules if rule.task_id.startswith("general-")]
    assert [rule.task_id for rule in rules] == ["tnpd-homolog-search", "tnpd-phylogeny"]
