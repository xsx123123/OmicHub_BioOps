from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from omichub.application.services.overdrive_planning_service import (
    OverdrivePlanningService,
    ResearchBundleService,
    build_plan_markdown,
    build_research_queries,
)
from omichub.application.services.overdrive_run_service import PLAN_SECTIONS, validate_plan
from omichub.core.exceptions import ValidationError


def _task(task_id: str = "analysis", **overrides: object) -> dict[str, object]:
    task: dict[str, object] = {
        "task_id": task_id,
        "agent_id": "agent-rnaseq",
        "depends_on": [],
        "accepts_inputs": ["research-plan"],
        "produces_outputs": ["analysis-report"],
        "completion_criteria": ["report exists", "evidence is cited"],
        "tools": ["workspace_read"],
        "timeout_seconds": 300,
        "retry": {"max_attempts": 2, "backoff_seconds": 5},
        "requires_approval": False,
    }
    task.update(overrides)
    return task


def _plan_content(tasks: list[dict[str, object]] | None = None) -> str:
    return build_plan_markdown(
        request="分析 RNA-seq 数据",
        lead_planner_agent_id="agent-rnaseq",
        evidence=[],
        tasks=tasks or [_task()],
        plan={},
        next_version=1,
    )


@pytest.mark.asyncio
async def test_retrieval_sources_are_concurrent_and_model_runs_after_both() -> None:
    both_started = asyncio.Event()
    started: set[str] = set()
    model_seen: list[dict[str, object]] = []

    async def retrieval(query: str, *, source: str) -> list[dict[str, object]]:
        started.add(source)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.2)
        return [{"title": source, "url": f"https://example.test/{source}", "claim": query}]

    async def knowledge(query: str, **_: object) -> list[dict[str, object]]:
        return await retrieval(query, source="kb")

    async def web(query: str) -> list[dict[str, object]]:
        return await retrieval(query, source="web")

    async def model(
        query: str,
        *,
        retrieved_evidence: list[dict[str, object]],
        context: dict[str, object],
    ) -> list[dict[str, object]]:
        assert started == {"kb", "web"}
        model_seen.extend(retrieved_evidence)
        return [{"title": "通用知识", "claim": f"候选框架: {query}", "url": "fake://url"}]

    bundle = await ResearchBundleService(
        knowledge_search=knowledge,
        web_search=web,
        model_knowledge=model,
    ).collect("RNA-seq", project_id="project-1")

    assert bundle.statuses == {
        "knowledge_base": "succeeded",
        "web": "succeeded",
        "model_knowledge": "completed",
    }
    assert len(model_seen) == 2
    assert {item["source_type"] for item in bundle.evidence} == {
        "knowledge_base",
        "web",
        "model_knowledge",
    }
    model_item = next(item for item in bundle.evidence if item["source_type"] == "model_knowledge")
    assert model_item["locator"] == ""
    assert model_item["freshness"] == "not_applicable"


@pytest.mark.asyncio
async def test_planner_refines_queries_and_prefers_biomedical_literature() -> None:
    refined_queries = [
        "TP53 AND lung adenocarcinoma AND single-cell RNA-seq",
        "mouse lung cancer AND tumor-associated macrophage AND immune evasion",
    ]
    literature_queries: list[str] = []
    activities: list[dict[str, object]] = []

    async def empty(_query: str, **_: object) -> list[object]:
        return []

    async def refiner(_query: str, **_: object) -> dict[str, object]:
        return {"queries": refined_queries}

    async def literature(query: str, **_: object) -> list[dict[str, str]]:
        literature_queries.append(query)
        return [{
            "title": "Single-cell transcriptomics of mouse lung cancer reveals myeloid populations",
            "url": "https://pubmed.ncbi.nlm.nih.gov/30979687/",
            "snippet": "Mouse lung cancer single-cell RNA-seq identifies tumor-associated macrophage populations.",
            "provider": "europe_pmc",
        }]

    async def activity(event: dict[str, object]) -> None:
        activities.append(event)

    bundle = await ResearchBundleService(
        knowledge_search=empty,
        web_search=empty,
        model_knowledge=empty,
        query_refiner=refiner,
        literature_search=literature,
        activity_callback=activity,
    ).collect("TP53 小鼠肺癌单细胞研究方案与免疫耐受机制")

    assert literature_queries == refined_queries
    assert bundle.sources["web"]["query_refinement"]["status"] == "refined"
    assert bundle.sources["web"]["queries"] == refined_queries
    assert bundle.sources["web"]["channels"]["literature"]["status"] == "succeeded"
    assert any(item["locator"].startswith("https://pubmed.ncbi.nlm.nih.gov/") for item in bundle.evidence)
    assert any(item["event"] == "source_started" and item["source"] == "literature" for item in activities)
    assert any(item["event"] == "source_completed" and item["source"] == "literature" for item in activities)
    content = build_plan_markdown(
        request="TP53 小鼠肺癌单细胞研究方案与免疫耐受机制",
        lead_planner_agent_id="agent-scrna",
        evidence=bundle.evidence,
        research_sources=bundle.sources,
        tasks=[_task(agent_id="agent-scrna")],
        plan={},
        next_version=1,
    )
    assert "规划 Agent 已精炼 2 条联合检索式" in content
    assert "Europe PMC 专用文献检索=succeeded" in content


@pytest.mark.asyncio
async def test_tnpd_research_uses_method_query_and_rejects_irrelevant_web_results() -> None:
    seen_queries: list[str] = []
    model_seen_titles: list[str] = []

    async def empty(_query: str, **_: object) -> list[object]:
        return []

    async def web(query: str) -> list[dict[str, str]]:
        seen_queries.append(query)
        return [
            {
                "title": "MEGA 构建进化树教程 -- chatGPT",
                "url": "https://www.haomeiwen.com/subject/example.html",
                "snippet": "准备一个蛋白序列文件并下载教程安装包",
            },
            {
                "title": "病毒基因组系统进化分析专利",
                "url": "https://www.jigao616.com/example.html",
                "snippet": "本发明专利技术提供病毒分类决定性位点方法",
            },
            {
                "title": "DIAMOND: fast and sensitive protein alignment",
                "url": "https://pubmed.ncbi.nlm.nih.gov/25402007/",
                "snippet": "DIAMOND supports sensitive protein homolog search for comparative genomics.",
            },
            {
                "title": "IQ-TREE documentation: model selection and ultrafast bootstrap",
                "url": "https://iqtree.github.io/doc/Command-Reference",
                "snippet": "Maximum likelihood protein phylogeny with model selection and bootstrap support.",
            },
        ]

    request = "我要将tnpd序列对比到20个基因组进行进化分析与建树"
    async def model(
        _query: str,
        *,
        retrieved_evidence: list[dict[str, str]],
        **_: object,
    ) -> list[object]:
        model_seen_titles.extend(item.get("title", "") for item in retrieved_evidence)
        return []

    bundle = await ResearchBundleService(
        knowledge_search=empty,
        web_search=web,
        model_knowledge=model,
    ).collect(request)

    assert seen_queries == build_research_queries(request)["web_queries"]
    normalized_query = seen_queries[0].casefold()
    assert all(term in normalized_query for term in ("tnpd", "diamond", "mafft", "iq-tree"))
    web_evidence = [item for item in bundle.evidence if item["source_type"] == "web"]
    assert [item["title"] for item in web_evidence] == [
        "DIAMOND: fast and sensitive protein alignment",
        "IQ-TREE documentation: model selection and ultrafast bootstrap",
    ]
    assert bundle.sources["web"]["rejected_count"] == 2
    assert bundle.sources["web"]["quality_gate"] == "authority_and_domain_relevance"
    assert model_seen_titles == [
        "DIAMOND: fast and sensitive protein alignment",
        "IQ-TREE documentation: model selection and ultrafast bootstrap",
    ]


def test_plan_discloses_search_query_and_filtered_result_count() -> None:
    content = build_plan_markdown(
        request="TnpD 建树",
        lead_planner_agent_id="agent-code",
        evidence=[],
        research_sources={
            "web": {
                "research_profile": "phylogeny",
                "query": '\"TnpD\" DIAMOND MAFFT IQ-TREE',
                "rejected_count": 8,
                "quality_status": "no_relevant_evidence",
            }
        },
        tasks=[_task()],
        plan={"deliverables": ["树文件"]},
        next_version=1,
    )

    assert "研究画像：`phylogeny`" in content
    assert '实际检索式：`"TnpD" DIAMOND MAFFT IQ-TREE`' in content
    assert "质量门已剔除 8 条" in content
    assert "没有通过相关性与来源质量门" in content


@pytest.mark.parametrize(
    ("case_text", "expected_profile", "good_result", "bad_result"),
    [
        (
            "请为 TP53 bulk RNA-seq 差异表达设计可靠分析方案",
            "bulk_rnaseq",
            {
                "title": "DESeq2 differential expression workflow",
                "url": "https://bioconductor.org/packages/DESeq2",
                "snippet": "RNA-seq count matrix normalization, differential expression and batch effect design.",
            },
            {
                "title": "转录组分析公司产品介绍",
                "url": "https://qiye.shuziyingxiao.net/rnaseq",
                "snippet": "本公司提供转录组产品特点和营销服务",
            },
        ),
        (
            "Vue 3 API 请求报错，请设计排查与修复方案",
            "software_engineering",
            {
                "title": "Vue official API reference",
                "url": "https://vuejs.org/api/",
                "snippet": "Vue API reference, version compatibility, examples and testing guidance.",
            },
            {
                "title": "Vue 报错解决大全",
                "url": "https://blog.csdn.net/example",
                "snippet": "复制代码即可解决，关注后下载附件",
            },
        ),
        (
            "构建生存分析预测模型并进行交叉验证",
            "statistics",
            {
                "title": "Cross-validation and model evaluation",
                "url": "https://scikit-learn.org/stable/modules/cross_validation.html",
                "snippet": "Cross-validation, model validation, confidence intervals and statistical assumptions.",
            },
            {
                "title": "机器学习培训班开课",
                "url": "https://mp.weixin.qq.com/s/example",
                "snippet": "培训班讲习班课程报名",
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_research_quality_gate_generalizes_across_domains(
    case_text: str,
    expected_profile: str,
    good_result: dict[str, str],
    bad_result: dict[str, str],
) -> None:
    queries: list[str] = []

    async def empty(_query: str, **_: object) -> list[object]:
        return []

    async def web(query: str) -> list[dict[str, str]]:
        queries.append(query)
        return [bad_result, good_result]

    bundle = await ResearchBundleService(
        knowledge_search=empty,
        web_search=web,
        model_knowledge=empty,
    ).collect(case_text)

    assert build_research_queries(case_text)["profile"] == expected_profile
    assert queries == build_research_queries(case_text)["web_queries"]
    assert "methodology best practices" in queries[-1]
    web_evidence = [item for item in bundle.evidence if item["source_type"] == "web"]
    assert [item["title"] for item in web_evidence] == [good_result["title"]]
    assert web_evidence[0]["evidence_quality"]["research_profile"] == expected_profile
    assert web_evidence[0]["evidence_quality"]["authority_tier"] == "trusted"
    assert bundle.sources["web"]["rejected_count"] == 1


@pytest.mark.asyncio
async def test_generic_chinese_research_keeps_original_subject_in_query() -> None:
    case_text = "评估团队知识共享机制并设计改进方案"
    queries: list[str] = []

    async def empty(_query: str, **_: object) -> list[object]:
        return []

    async def web(query: str) -> list[dict[str, str]]:
        queries.append(query)
        return [
            {
                "title": "Knowledge sharing intervention methodology",
                "url": "https://www.nature.com/articles/example",
                "snippet": "A reproducible methodology with validation and benchmark measures.",
            },
            {
                "title": "知识管理培训班",
                "url": "https://mp.weixin.qq.com/s/example",
                "snippet": "培训班课程报名与营销介绍",
            },
        ]

    bundle = await ResearchBundleService(
        knowledge_search=empty,
        web_search=web,
        model_knowledge=empty,
    ).collect(case_text)

    assert build_research_queries(case_text)["profile"] == "general"
    assert case_text in queries[0]
    assert "official documentation" in queries[0]
    assert [
        item["title"] for item in bundle.evidence if item["source_type"] == "web"
    ] == ["Knowledge sharing intervention methodology"]


def test_profile_query_preserves_unregistered_chinese_subject_and_trusts_public_sources() -> None:
    case_text = "设计肝癌转录组差异表达与通路分析方案"
    query = build_research_queries(case_text)

    assert query["profile"] == "bulk_rnaseq"
    assert case_text in query["web"]
    assert ResearchBundleService._is_trusted_web_host("cancer.gov") is True
    assert ResearchBundleService._is_trusted_web_host("example.edu.cn") is True
    assert ResearchBundleService._is_trusted_web_host("who.int") is True


@pytest.mark.asyncio
async def test_failed_and_timed_out_sources_are_recorded_without_fabricated_evidence() -> None:
    async def kb(_query: str) -> object:
        raise RuntimeError("knowledge db unavailable")

    async def web(_query: str) -> object:
        await asyncio.sleep(0.1)
        return [{"title": "too late", "url": "https://example.test"}]

    async def model(_query: str, **_: object) -> object:
        return [{"title": "模型候选", "claim": "这只是待验证推断"}]

    bundle = await ResearchBundleService(
        knowledge_search=kb,
        web_search=web,
        model_knowledge=model,
        source_timeout_seconds=0.01,
        wall_timeout_seconds=0.05,
    ).collect("test")

    assert bundle.sources["knowledge_base"]["status"] == "failed"
    assert "unavailable" in bundle.sources["knowledge_base"]["error"]
    assert bundle.sources["web"]["status"] == "timed_out"
    assert bundle.sources["knowledge_base"]["evidence_ids"] == []
    assert bundle.sources["web"]["evidence_ids"] == []
    assert [item["source_type"] for item in bundle.evidence] == ["model_knowledge"]


@pytest.mark.asyncio
async def test_failure_envelope_is_not_treated_as_a_successful_empty_search() -> None:
    async def failed(_query: str) -> dict[str, object]:
        return {"success": False, "error": "provider missing"}

    async def empty(_query: str, **_: object) -> list[object]:
        return []

    bundle = await ResearchBundleService(
        knowledge_search=failed,
        web_search=empty,
        model_knowledge=empty,
    ).collect("test")

    assert bundle.sources["knowledge_base"]["status"] == "failed"
    assert bundle.sources["knowledge_base"]["error"] == "provider missing"


def test_builder_has_every_required_section_and_honest_empty_source_language() -> None:
    content = _plan_content()

    for index, section in enumerate(PLAN_SECTIONS, start=1):
        assert f"## {index}. {section}" in content
    assert "本路没有可用证据；详见 evidence.json 的状态与失败原因" in content
    validate_plan(content, [_task()], {"agent-rnaseq"})


def test_select_lead_planner_uses_smallest_domain_match_and_general_fallback() -> None:
    catalog = [
        {
            "agent_id": "agent-general",
            "features": {"capability_scope": ["研究设计", "跨专家协调"]},
        },
        {
            "agent_id": "agent-rnaseq",
            "features": {"capability_scope": ["差异表达", "通路富集"]},
        },
        {
            "agent_id": "agent-viz",
            "features": {"capability_scope": ["统计图表"]},
        },
    ]

    selected = OverdrivePlanningService.select_lead_planner(
        "请制定 RNA-seq 差异表达研究计划", catalog
    )
    assert selected["lead_planner_agent_id"] == "agent-rnaseq"
    assert selected["advisor_agent_ids"] == []
    assert "差异表达" in selected["matched_capabilities"]

    fallback = OverdrivePlanningService.select_lead_planner("帮我梳理一个新课题", catalog)
    assert fallback["lead_planner_agent_id"] == "agent-general"


def test_plan_only_request_keeps_research_dag_without_execution_tools() -> None:
    request = "帮我创建基于 TP53 小鼠样本的单细胞研究分析方案"
    tasks = [_task(workspace_access=False)]

    assert OverdrivePlanningService.is_planning_only_request(request, tasks) is True
    prepared = OverdrivePlanningService.prepare_planning_only_tasks(
        [_task(workspace_access=True, tools=["workspace_read", "workspace_write"])]
    )
    assert prepared[0]["workspace_access"] is False
    assert prepared[0]["requires_approval"] is False
    assert prepared[0]["tools"] == ["workspace_read"]
    validate_plan(_plan_content(tasks), tasks, {"agent-rnaseq"})


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"depends_on": ["missing"]}, "未知依赖"),
        ({"agent_id": "agent-unknown"}, "未知 Agent"),
        ({"produces_outputs": []}, "produces_outputs"),
        ({"completion_criteria": None}, "completion_criteria"),
        ({"tools": None}, "tools"),
        ({"requires_approval": None}, "requires_approval"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"retry": {}}, "retry"),
    ],
)
def test_plan_validation_rejects_invalid_task_contracts(
    mutation: dict[str, object], message: str
) -> None:
    task = _task(**mutation)
    with pytest.raises(ValidationError, match=message):
        validate_plan(_plan_content([task]), [task], {"agent-rnaseq"})


def test_plan_validation_rejects_missing_section_and_cycle() -> None:
    content = _plan_content()
    with pytest.raises(ValidationError, match="缺少章节"):
        validate_plan(content.replace("## 10. 质量门与验收标准", "### 质量门"), [_task()], {"agent-rnaseq"})

    tasks = [
        _task("a", depends_on=["b"]),
        _task("b", depends_on=["a"]),
    ]
    with pytest.raises(ValidationError, match="循环依赖"):
        validate_plan(_plan_content(tasks), tasks, {"agent-rnaseq"})


@pytest.mark.asyncio
async def test_planning_service_persists_research_then_freezes_plan() -> None:
    calls: list[object] = []
    run = SimpleNamespace(
        run_id="run-1",
        session_id="session-1",
        root_request="分析 RNA-seq 数据",
        lead_planner_agent_id="agent-rnaseq",
        plan={"version": 0},
    )

    class FakeRunService:
        async def transition(self, _run: object, status: str) -> None:
            calls.append(("transition", status))

        async def save_research(
            self,
            _run: object,
            evidence: list[dict[str, object]],
            statuses: dict[str, str],
            *,
            source_details: dict[str, dict[str, object]],
        ) -> None:
            calls.append(("research", statuses, evidence, source_details))

        async def append_event(self, *args: object, **kwargs: object) -> None:
            calls.append(("event", args[1], args[2]))

        async def write_plan_draft(self, _run: object, content: str) -> dict[str, object]:
            assert "# 执行计划" in content
            calls.append(("write_plan_draft", content))
            return {"version": 1, "path": "output/overdrive/session-1/run-1/plan.md"}

        async def freeze_plan(self, _run: object, **kwargs: object) -> dict[str, object]:
            validate_plan(
                str(kwargs["content"]),
                kwargs["tasks"],  # type: ignore[arg-type]
                kwargs["known_agent_ids"],  # type: ignore[arg-type]
                allow_empty_tasks=bool(kwargs.get("allow_empty_tasks")),
            )
            calls.append(("freeze", kwargs))
            return {"version": 1, "status": "awaiting_confirmation"}

    async def empty(_query: str, **_: object) -> list[object]:
        return []

    task = _task()
    builder = AsyncMock(return_value={"tasks": [task], "deliverables": ["报告"]})
    planner = OverdrivePlanningService(
        FakeRunService(),  # type: ignore[arg-type]
        ResearchBundleService(
            knowledge_search=empty,
            web_search=empty,
            model_knowledge=empty,
        ),
        builder,
    )

    result = await planner.prepare_plan(run, known_agent_ids={"agent-rnaseq"})  # type: ignore[arg-type]

    assert result == {"version": 1, "status": "awaiting_confirmation"}
    assert [call[:2] for call in calls if call[0] == "transition"] == [
        ("transition", "RESEARCHING"),
        ("transition", "PLAN_DRAFTED"),
        ("transition", "PLAN_REVIEWING"),
    ]
    assert next(call for call in calls if call[0] == "write_plan_draft")
    events = [call[1] for call in calls if call[0] == "event"]
    assert events == ["research_started", "plan_ready", "plan_review_passed"]
    plan_ready = next(call[2] for call in calls if call[:2] == ("event", "plan_ready"))
    assert plan_ready["plan_path"] == "output/overdrive/session-1/run-1/plan.md"
    frozen = next(call[1] for call in calls if call[0] == "freeze")
    assert frozen["tasks"] == [task]
    assert frozen["summary"]["wave_count"] == 1


@pytest.mark.asyncio
async def test_plan_only_prepare_flow_freezes_readonly_dag_without_qc() -> None:
    captured: dict[str, object] = {}
    run = SimpleNamespace(
        run_id="run-plan-only",
        session_id="session-1",
        root_request="帮我创建基于 TP53 小鼠10个样本的单细胞研究分析方案",
        lead_planner_agent_id="agent-scrna",
        plan={"version": 0},
    )

    class FakeRunService:
        async def transition(self, _run: object, _status: str) -> None:
            return None

        async def save_research(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def append_event(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def write_plan_draft(self, _run: object, content: str) -> dict[str, object]:
            captured["content"] = content
            return {"version": 1, "path": "output/overdrive/session-1/run-plan-only/plan.md"}

        async def freeze_plan(self, _run: object, **kwargs: object) -> dict[str, object]:
            captured["freeze"] = kwargs
            validate_plan(
                str(kwargs["content"]),
                kwargs["tasks"],  # type: ignore[arg-type]
                kwargs["known_agent_ids"],  # type: ignore[arg-type]
                allow_empty_tasks=bool(kwargs.get("allow_empty_tasks")),
            )
            return {"version": 1, "status": "awaiting_confirmation"}

    async def empty(_query: str, **_: object) -> list[object]:
        return []

    class MemorySearchOptimizer:
        async def refine_queries(
            self, _query: str, *, fallback_queries: object, refiner: object = None
        ) -> dict[str, object]:
            return {
                "status": "fallback",
                "queries": list(fallback_queries),  # type: ignore[arg-type]
                "cache_hit": False,
            }

        async def rerank(
            self, _query: str, items: object, *, limit: int = 8
        ) -> list[object]:
            return list(items)[:limit]  # type: ignore[arg-type]

    planner = OverdrivePlanningService(
        FakeRunService(),  # type: ignore[arg-type]
        ResearchBundleService(
            knowledge_search=empty,
            web_search=empty,
            model_knowledge=empty,
            search_optimizer=MemorySearchOptimizer(),  # type: ignore[arg-type]
        ),
        AsyncMock(return_value={
            "tasks": [
                _task(
                    "scrna-sample-contract",
                    agent_id="agent-scrna",
                    workspace_access=True,
                    tools=["workspace_read", "workspace_write"],
                ),
            ],
            "deliverables": ["研究方案"],
        }),
    )

    await planner.prepare_plan(
        run,  # type: ignore[arg-type]
        known_agent_ids={"agent-scrna", "agent-qc"},
    )

    frozen = captured["freeze"]
    assert isinstance(frozen, dict)
    assert [item["task_id"] for item in frozen["tasks"]] == ["scrna-sample-contract"]
    assert frozen["tasks"][0]["workspace_access"] is False
    assert frozen["tasks"][0]["tools"] == ["workspace_read"]
    assert frozen["allow_empty_tasks"] is True
    assert frozen["summary"]["planning_only"] is True
    assert "independent_qc" not in frozen["summary"]
    assert "波次 1: scrna-sample-contract" in str(captured["content"])
    assert "independent-qc" not in str(captured["content"])


@pytest.mark.asyncio
async def test_save_research_keeps_failure_details_in_evidence_ledger(monkeypatch, tmp_path) -> None:
    from omichub.application.services.overdrive_run_service import OverdriveRunService
    from omichub.infrastructure.config.storage_config import StorageConfig
    from omichub.infrastructure.storage import LocalStorageBackend, reset_storage_backend
    from omichub.infrastructure.storage.path_factory import StoragePathFactory

    monkeypatch.setattr(
        "omichub.application.services.overdrive_run_service.overdrive_run_root",
        lambda _session_id, _run_id: tmp_path,
    )
    factory = StoragePathFactory(StorageConfig(data_root=str(tmp_path), users_subdir="users"))
    monkeypatch.setattr(
        "omichub.application.services.overdrive_run_service.get_path_factory", lambda: factory
    )
    monkeypatch.setattr(
        "omichub.application.services.overdrive_run_service.get_storage_backend",
        lambda: LocalStorageBackend(path_factory=factory),
    )
    reset_storage_backend()
    service = OverdriveRunService(AsyncMock())
    service.append_event = AsyncMock()  # type: ignore[method-assign]
    service._write_snapshot = AsyncMock()  # type: ignore[method-assign]
    run = SimpleNamespace(session_id="session-1", run_id="run-1", research={})

    await service.save_research(
        run,  # type: ignore[arg-type]
        [],
        {"knowledge_base": "failed", "web": "timed_out", "model_knowledge": "completed"},
        source_details={
            "knowledge_base": {"status": "failed", "error": "db unavailable", "items": []},
            "web": {"status": "timed_out", "error": "deadline", "items": []},
            "model_knowledge": {"status": "completed", "items": []},
        },
    )

    ledger = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert ledger["sources"]["knowledge_base"]["error"] == "db unavailable"
    assert run.research["web"]["status"] == "timed_out"
    assert run.research["web"]["error"] == "deadline"
    assert "items" not in run.research["web"]


@pytest.mark.asyncio
async def test_write_plan_draft_makes_plan_ready_path_real(monkeypatch, tmp_path) -> None:
    from omichub.application.services.overdrive_run_service import OverdriveRunService

    monkeypatch.setattr(
        "omichub.application.services.overdrive_run_service.overdrive_run_root",
        lambda _session_id, _run_id: tmp_path,
    )
    service = OverdriveRunService(AsyncMock())
    service._write_snapshot = AsyncMock()  # type: ignore[method-assign]
    run = SimpleNamespace(session_id="session-1", run_id="run-1", plan={"version": 0})

    draft = await service.write_plan_draft(run, "# 执行计划\r\n\r\n草稿   ")  # type: ignore[arg-type]

    assert draft == {
        "path": "output/overdrive/session-1/run-1/plan.md",
        "version": 1,
    }
    assert (tmp_path / "plan.md").read_bytes() == b"# \xe6\x89\xa7\xe8\xa1\x8c\xe8\xae\xa1\xe5\x88\x92\n\n\xe8\x8d\x89\xe7\xa8\xbf\n"
    assert run.plan["status"] == "reviewing"
    assert run.plan["draft_version"] == 1
