"""Research-first planning for the overdrive v2 runtime.

The orchestration layer deliberately receives search and model callables instead of
importing ``ChatService``.  This keeps planning read-only, testable, and usable by
both the legacy chat loop and LangGraph-backed agents.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from omichub.application.services.overdrive_run_service import (
    OverdriveRunService,
    validate_plan,
)
from omichub.application.services.research_search_optimizer import ResearchSearchOptimizer
from omichub.core.exceptions import ValidationError
from omichub.infrastructure.database.models.overdrive import OverdriveRunModel

ResearchCallable = Callable[..., Awaitable[Any]]
PlanBuilder = Callable[..., Awaitable[Mapping[str, Any]] | Mapping[str, Any]]
ResearchActivityCallback = Callable[[dict[str, Any]], Awaitable[None]]

SOURCE_TYPES = ("knowledge_base", "web", "model_knowledge")

DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "agent-rnaseq": ("rna-seq", "rnaseq", "bulk rna", "转录组", "差异表达", "deseq"),
    "agent-atacseq": ("atac-seq", "atacseq", "染色质开放", "peak calling", "可及性"),
    "agent-scrna": ("scrna", "单细胞", "single-cell", "细胞注释", "细胞通讯"),
    "agent-viz": ("可视化", "绘图", "图表", "publication-ready"),
    "agent-code": ("代码", "python", "bash", "脚本", "调试"),
    "agent-data": ("数据契约", "元数据", "样本对应", "输入核验"),
}

_BLOCKED_WEB_HOSTS = (
    "siliu.net", "jigao616.com", "mp.weixin.qq.com", "haomeiwen.com",
    "csdn.net", "iikx.com", "shuziyingxiao.net", "8684.com",
    "baijiahao.baidu.com", "sohu.com", "163.com", "zhihu.com",
)
_TRUSTED_WEB_HOSTS = (
    "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov",
    "europepmc.org", "doi.org", "nature.com", "science.org", "cell.com",
    "academic.oup.com", "oup.com", "springer.com", "biomedcentral.com",
    "wiley.com", "frontiersin.org", "plos.org", "sciencedirect.com",
    "mdpi.com", "biorxiv.org", "github.com", "readthedocs.io",
    "iqtree.github.io", "mafft.cbrc.jp", "diamondsearch.org",
    "bioconductor.org", "broadinstitute.org", "satijalab.org", "scanpy.readthedocs.io",
    "docs.python.org", "developer.mozilla.org", "vuejs.org", "pandas.pydata.org",
    "scikit-learn.org", "r-project.org",
    "who.int", "oecd.org", "un.org", "w3.org", "ietf.org",
)
_TRUSTED_WEB_SUFFIXES = (
    ".gov", ".gov.cn", ".edu", ".edu.cn", ".ac.uk", ".ac.cn",
)
_LOW_QUALITY_TEXT_MARKERS = (
    "全部详细技术资料下载", "本发明专利技术", "培训班", "讲习班", "共享仓库下载",
    "-- chatgpt", "产品特点", "本公司", "营销", "专门用的流程",
)
_GENERIC_QUERY_TERMS = (
    "methodology", "best practices", "validation", "benchmark", "reproducible workflow",
    "official documentation", "peer reviewed",
)
_REQUEST_TOKEN_STOPWORDS = {
    "analysis", "analyze", "compare", "comparison", "data", "dataset", "genome",
    "genomes", "help", "method", "plan", "please", "result", "results", "study",
    "using", "want", "with", "workflow",
}


@dataclass(frozen=True)
class ResearchProfileSpec:
    name: str
    markers: tuple[str, ...]
    query_terms: tuple[str, ...]
    relevance_terms: tuple[str, ...]


_RESEARCH_PROFILES = (
    ResearchProfileSpec(
        name="phylogeny",
        markers=("系统发育", "进化树", "进化分析", "建树", "phylogen", "newick"),
        query_terms=(
            "homolog identification", "comparative genomics", "BLASTP", "DIAMOND",
            "MAFFT", "IQ-TREE", "protein phylogeny", "bootstrap",
        ),
        relevance_terms=(
            "homolog", "ortholog", "transposase", "blastp", "diamond", "mafft",
            "muscle", "alignment", "iq-tree", "iqtree", "maximum likelihood",
            "bootstrap", "model selection", "protein family", "同源", "多序列比对",
            "系统发育", "进化树",
        ),
    ),
    ResearchProfileSpec(
        name="bulk_rnaseq",
        markers=("rna-seq", "rnaseq", "bulk rna", "转录组", "差异表达", "count矩阵"),
        query_terms=(
            "RNA-seq", "DESeq2", "edgeR", "differential expression", "batch effect",
            "experimental design", "pathway enrichment",
        ),
        relevance_terms=(
            "rna-seq", "rnaseq", "deseq2", "edger", "limma", "count matrix",
            "differential expression", "batch effect", "normalization", "转录组",
            "差异表达", "批次效应",
        ),
    ),
    ResearchProfileSpec(
        name="single_cell",
        markers=("单细胞", "scrna", "single-cell", "seurat", "scanpy", "细胞通讯"),
        query_terms=(
            "single-cell RNA-seq", "Scanpy", "Seurat", "quality control",
            "cell type annotation", "batch integration", "trajectory analysis",
        ),
        relevance_terms=(
            "single-cell", "scrna", "scanpy", "seurat", "cell annotation",
            "doublet", "batch integration", "trajectory", "单细胞", "细胞注释",
            "细胞通讯",
        ),
    ),
    ResearchProfileSpec(
        name="atacseq",
        markers=("atac-seq", "atacseq", "染色质开放", "peak calling", "可及性"),
        query_terms=(
            "ATAC-seq", "quality control", "peak calling", "TSS enrichment",
            "chromatin accessibility", "differential accessibility",
        ),
        relevance_terms=(
            "atac-seq", "atacseq", "peak calling", "macs2", "tss enrichment",
            "fragment size", "chromatin accessibility", "染色质开放", "可及性",
        ),
    ),
    ResearchProfileSpec(
        name="variant_genomics",
        markers=("变异", "variant", "snp", "vcf", "全基因组", "wgs", "gwas"),
        query_terms=(
            "variant calling", "GATK", "VCF", "quality filtering", "annotation",
            "benchmark", "population genomics",
        ),
        relevance_terms=(
            "variant", "snp", "indel", "vcf", "gatk", "variant calling",
            "genotype", "annotation", "benchmark", "变异", "全基因组",
        ),
    ),
    ResearchProfileSpec(
        name="proteomics",
        markers=("蛋白组", "proteomic", "质谱", "mass spectrometry", "磷酸化"),
        query_terms=(
            "proteomics", "mass spectrometry", "MaxQuant", "quality control",
            "differential abundance", "multiple testing",
        ),
        relevance_terms=(
            "proteomics", "mass spectrometry", "maxquant", "peptide", "fdr",
            "differential abundance", "蛋白组", "质谱", "磷酸化",
        ),
    ),
    ResearchProfileSpec(
        name="software_engineering",
        markers=("python", "javascript", "typescript", "vue", "api", "代码", "脚本", "报错"),
        query_terms=(
            "official documentation", "API reference", "version compatibility",
            "security", "reproducible example", "testing",
        ),
        relevance_terms=(
            "documentation", "api reference", "version", "compatibility", "security",
            "testing", "example", "python", "javascript", "typescript", "vue",
        ),
    ),
    ResearchProfileSpec(
        name="statistics",
        markers=("统计", "回归", "生存分析", "机器学习", "预测模型", "相关性"),
        query_terms=(
            "statistical methodology", "assumptions", "validation", "cross-validation",
            "effect size", "confidence interval", "multiple testing",
        ),
        relevance_terms=(
            "regression", "survival analysis", "cross-validation", "effect size",
            "confidence interval", "multiple testing", "assumption", "统计", "回归",
            "生存分析", "机器学习",
        ),
    ),
)
_GENERIC_RESEARCH_PROFILE = ResearchProfileSpec(
    name="general",
    markers=(),
    query_terms=("methodology", "best practices", "validation", "benchmark"),
    relevance_terms=("methodology", "validation", "benchmark", "best practice", "reproducible"),
)


def select_research_profile(request: str) -> ResearchProfileSpec:
    normalized = request.casefold()
    scored = [
        (sum(marker in normalized for marker in profile.markers), profile)
        for profile in _RESEARCH_PROFILES
    ]
    score, profile = max(scored, key=lambda item: item[0])
    return profile if score else _GENERIC_RESEARCH_PROFILE


def _request_technical_terms(request: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_.+:-]{2,}", request):
        normalized = raw.casefold().strip(".:-")
        if normalized in _REQUEST_TOKEN_STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(raw.strip(".:-"))
    return terms[:8]


def _research_subject_terms(request: str) -> list[str]:
    normalized = request.casefold()
    terms = _request_technical_terms(request)
    concept_terms = (
        (("肺癌", "lung cancer", "lung adenocarcinoma"),),
        (("免疫耐受", "immune tolerance", "immune evasion"),),
        (("髓系", "myeloid cells"),),
        (("tam", "tumor-associated macrophage"),),
        (("巨噬细胞", "macrophage"),),
        (("小鼠", "mouse model"),),
        (("细胞通讯", "cell-cell communication"),),
    )
    for group in concept_terms:
        markers = group[0]
        if any(marker.casefold() in normalized for marker in markers[:1]):
            terms.extend(markers[1:])
    return list(dict.fromkeys(term for term in terms if term))[:12]


def build_research_queries(request: str) -> dict[str, Any]:
    """按领域画像改写方法学检索词，避免自然语言目标直接命中 SEO 内容。"""
    compact = " ".join(request.split())
    profile = select_research_profile(compact)
    subject_terms = _research_subject_terms(compact)
    subject = " ".join(subject_terms) or compact[:120]
    if profile.name == "single_cell":
        web_queries = [
            f"{subject} single-cell RNA-seq tumor microenvironment".strip(),
            f"{subject} tumor-associated macrophage T cell immune evasion".strip(),
            "single-cell RNA-seq best practices quality control batch integration pseudobulk trajectory",
        ]
    else:
        subject = " ".join(dict.fromkeys([compact[:120], subject])).strip()
        focused_methods = " ".join(profile.query_terms[:8])
        web_queries = [
            f"{subject} {focused_methods} official documentation".strip(),
            f"{subject} {profile.name.replace('_', ' ')} methodology best practices official documentation".strip(),
        ]
    web_queries = list(dict.fromkeys(query[:240] for query in web_queries if query.strip()))
    return {
        "profile": profile.name,
        "knowledge_base": f"{compact} {' '.join(profile.query_terms)}"[:600],
        "web": web_queries[0] if web_queries else compact[:240],
        "web_queries": web_queries or [compact[:240]],
    }


def is_planning_only_request(
    request: str, tasks: Sequence[Mapping[str, Any]]
) -> bool:
    normalized = " ".join(request.casefold().split())
    planning_markers = (
        "方案", "研究计划", "分析计划", "方法学", "研究设计", "分析思路",
        "plan", "protocol", "study design",
    )
    execution_markers = (
        "开始分析", "立即分析", "执行分析", "运行流程", "跑流程", "处理这些数据",
        "生成代码", "写代码", "执行代码", "提交任务", "run the analysis", "execute",
    )
    if not any(marker in normalized for marker in planning_markers):
        return False
    # 用户明确只要方案时，以用户意图为权威；不能让 Manager 偶发生成的
    # workspace_access/执行工具把方案请求升级为真实执行。
    return not any(marker in normalized for marker in execution_markers)


@dataclass(frozen=True)
class ResearchBundle:
    """Normalized evidence plus an honest per-source execution ledger."""

    evidence: list[dict[str, Any]]
    sources: dict[str, dict[str, Any]]

    @property
    def statuses(self) -> dict[str, str]:
        return {source: str(record["status"]) for source, record in self.sources.items()}


class ResearchBundleService:
    """Run KB and web IO concurrently, then obtain separate model knowledge."""

    def __init__(
        self,
        *,
        knowledge_search: ResearchCallable,
        web_search: ResearchCallable,
        model_knowledge: ResearchCallable,
        query_refiner: ResearchCallable | None = None,
        literature_search: ResearchCallable | None = None,
        activity_callback: ResearchActivityCallback | None = None,
        source_timeout_seconds: float = 20,
        model_timeout_seconds: float | None = None,
        wall_timeout_seconds: float = 45,
        max_evidence_items_per_source: int = 8,
        search_optimizer: ResearchSearchOptimizer | None = None,
    ) -> None:
        self._knowledge_search = knowledge_search
        self._web_search = web_search
        self._model_knowledge = model_knowledge
        self._query_refiner = query_refiner
        self._literature_search = literature_search
        self._activity_callback = activity_callback
        self._source_timeout = max(0.01, float(source_timeout_seconds))
        # model_knowledge 是一次 LLM 流式归纳,与检索类源共用 20s 预算
        # 在端点稍慢时必超时;未显式配置时回退到检索源预算。
        self._model_timeout = (
            max(0.01, float(model_timeout_seconds))
            if model_timeout_seconds is not None
            else self._source_timeout
        )
        self._wall_timeout = max(self._source_timeout, self._model_timeout, float(wall_timeout_seconds))
        self._max_items = max(1, int(max_evidence_items_per_source))
        self._search_optimizer = search_optimizer or ResearchSearchOptimizer()

    async def collect(
        self,
        query: str,
        *,
        project_id: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> ResearchBundle:
        if not query.strip():
            raise ValidationError("研究问题不能为空")
        started = time.monotonic()
        research_queries = build_research_queries(query)
        await self._notify_activity(
            "source_started",
            source="query_refiner",
            queries=research_queries["web_queries"],
        )
        refinement_record = await self._refine_queries(
            query,
            fallback_queries=research_queries["web_queries"],
            context=context,
        )
        research_queries["web_queries"] = refinement_record["queries"]
        research_queries["web"] = refinement_record["queries"][0]
        await self._notify_activity(
            "query_refinement_completed",
            source="query_refiner",
            status=refinement_record["status"],
            queries=refinement_record["queries"],
            error=refinement_record.get("error"),
        )
        await self._notify_activity(
            "source_started",
            source="knowledge_base",
            queries=[research_queries["knowledge_base"]],
        )
        await self._notify_activity(
            "source_started",
            source="web",
            queries=research_queries["web_queries"],
        )
        if self._literature_search is not None and research_queries["profile"] in {"single_cell", "bulk_rnaseq"}:
            await self._notify_activity(
                "source_started",
                source="literature",
                queries=research_queries["web_queries"],
            )
        kb_task = asyncio.create_task(
            self._call_retrieval(
                "knowledge_base",
                self._knowledge_search,
                research_queries["knowledge_base"],
                project_id=project_id,
            )
        )
        web_task = asyncio.create_task(self._call_web_queries(research_queries["web_queries"]))
        literature_task = (
            asyncio.create_task(self._call_literature_queries(research_queries["web_queries"]))
            if self._literature_search is not None and research_queries["profile"] in {"single_cell", "bulk_rnaseq"}
            else None
        )
        if literature_task is None:
            kb_record, web_record = await asyncio.gather(kb_task, web_task)
            await self._notify_activity("source_completed", source="knowledge_base", **self._activity_record(kb_record))
            await self._notify_activity("source_completed", source="web", **self._activity_record(web_record))
        else:
            kb_record, general_web_record, literature_record = await asyncio.gather(
                kb_task, web_task, literature_task
            )
            await self._notify_activity("source_completed", source="knowledge_base", **self._activity_record(kb_record))
            await self._notify_activity("source_completed", source="web", **self._activity_record(general_web_record))
            await self._notify_activity("source_completed", source="literature", **self._activity_record(literature_record))
            web_record = self._merge_web_channels(general_web_record, literature_record)
        web_items, rejected_web = self._filter_web_items(web_record["items"], query)
        web_items = await self._search_optimizer.rerank(
            query,
            web_items,
            limit=self._max_items,
        )
        web_record["items"] = web_items
        web_record["research_profile"] = research_queries["profile"]
        web_record["accepted_count"] = len(web_items)
        web_record["rejected_count"] = len(rejected_web)
        web_record["quality_gate"] = "authority_and_domain_relevance"
        web_record["query_refinement"] = refinement_record
        if rejected_web:
            web_record["rejected_reasons"] = rejected_web
        if not web_items and rejected_web:
            web_record["quality_status"] = "no_relevant_evidence"

        remaining = max(0.01, self._wall_timeout - (time.monotonic() - started))
        await self._notify_activity("source_started", source="model_knowledge", queries=[])
        model_record = await self._call_model(
            query,
            [*kb_record["items"], *web_record["items"]],
            context={**dict(context or {}), "research_queries": research_queries},
            timeout_seconds=min(self._model_timeout, remaining),
        )
        await self._notify_activity(
            "source_completed", source="model_knowledge", **self._activity_record(model_record)
        )
        sources = {
            "knowledge_base": kb_record,
            "web": web_record,
            "model_knowledge": model_record,
        }
        evidence: list[dict[str, Any]] = []
        next_id = 1
        for source in SOURCE_TYPES:
            record = sources[source]
            for raw_item in record.pop("items"):
                item = self._evidence_item(source, raw_item, next_id)
                if item is None:
                    continue
                evidence.append(item)
                record["evidence_ids"].append(item["evidence_id"])
                next_id += 1
        return ResearchBundle(evidence=evidence, sources=sources)

    async def _notify_activity(self, event: str, **payload: Any) -> None:
        if self._activity_callback is not None:
            await self._activity_callback({"event": event, **payload})

    @staticmethod
    def _activity_record(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "status": record.get("status"),
            "queries": list(record.get("queries") or ([record.get("query")] if record.get("query") else [])),
            "duration_ms": int(record.get("duration_ms") or 0),
            "result_count": len(record.get("items") or []),
            "error": record.get("error") or "; ".join(record.get("errors") or []),
        }

    async def _refine_queries(
        self,
        query: str,
        *,
        fallback_queries: Sequence[str],
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        async def refine(value: str) -> Any:
            if self._query_refiner is None:
                return []
            return await asyncio.wait_for(
                self._invoke(
                    self._query_refiner,
                    value,
                    context=deepcopy(dict(context or {})),
                ),
                timeout=min(self._source_timeout, 10.0),
            )

        return await self._search_optimizer.refine_queries(
            query,
            fallback_queries=fallback_queries,
            refiner=refine if self._query_refiner is not None else None,
        )

    async def _call_literature_queries(self, queries: Sequence[str]) -> dict[str, Any]:
        if self._literature_search is None:
            return self._source_record("skipped", time.monotonic(), items=[])
        records = await asyncio.gather(*(
            self._call_retrieval("literature", self._literature_search, query)
            for query in queries
        ))
        return self._merge_query_records(records, queries, channel="literature")

    async def _call_web_queries(self, queries: Sequence[str]) -> dict[str, Any]:
        records = await asyncio.gather(*(
            self._call_retrieval("web", self._web_search, query) for query in queries
        ))
        return self._merge_query_records(records, queries, channel="general_web")

    def _merge_query_records(
        self,
        records: Sequence[Mapping[str, Any]],
        queries: Sequence[str],
        *,
        channel: str,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for source_record in records:
            for item in source_record.get("items") or []:
                key = (
                    str(item.get("url") or item.get("link") or "").strip().casefold().rstrip("/"),
                    str(item.get("title") or item.get("name") or "").strip().casefold(),
                )
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
        succeeded = [record for record in records if record.get("status") == "succeeded"]
        errors = [str(record.get("error")) for record in records if record.get("error")]
        record = {
            "status": "succeeded" if succeeded else str(records[0].get("status") or "failed"),
            "evidence_ids": [],
            "duration_ms": max((int(record.get("duration_ms") or 0) for record in records), default=0),
            "items": items[: self._max_items * 2],
            "query": str(queries[0]) if queries else "",
            "queries": list(queries),
            "channel": channel,
        }
        if errors:
            record["errors"] = errors
        return record

    def _merge_web_channels(
        self,
        general_web: Mapping[str, Any],
        literature: Mapping[str, Any],
    ) -> dict[str, Any]:
        literature_items = [deepcopy(dict(item)) for item in literature.get("items") or []]
        general_items = [deepcopy(dict(item)) for item in general_web.get("items") or []]
        statuses = {str(general_web.get("status")), str(literature.get("status"))}
        status = "succeeded" if "succeeded" in statuses else next(iter(statuses - {""}), "failed")
        return {
            "status": status,
            "evidence_ids": [],
            "duration_ms": max(
                int(general_web.get("duration_ms") or 0),
                int(literature.get("duration_ms") or 0),
            ),
            "items": [*literature_items, *general_items][: self._max_items * 3],
            "query": str((literature.get("queries") or general_web.get("queries") or [""])[0]),
            "queries": list(literature.get("queries") or general_web.get("queries") or []),
            "channels": {
                "literature": {key: deepcopy(value) for key, value in literature.items() if key != "items"},
                "general_web": {key: deepcopy(value) for key, value in general_web.items() if key != "items"},
            },
        }

    async def _call_retrieval(
        self,
        source: str,
        function: ResearchCallable,
        query: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._invoke(function, query, **kwargs), timeout=self._source_timeout
            )
            items = self._unwrap_items(raw)
            return self._source_record("succeeded", started, items=items, query=query)
        except TimeoutError:
            logger.warning(
                "Research source timed out: source={} timeout={}s query={}",
                source,
                self._source_timeout,
                query[:200],
            )
            return self._source_record(
                "timed_out", started, error=f"{source} research timed out", query=query
            )
        except Exception as exc:  # noqa: BLE001 - one unavailable source must not block planning
            logger.warning(
                "Research source failed: source={} error={}", source, self._safe_error(exc)
            )
            return self._source_record(
                "failed", started, error=self._safe_error(exc), query=query
            )

    async def _call_model(
        self,
        query: str,
        retrieved_evidence: list[dict[str, Any]],
        *,
        context: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._invoke(
                    self._model_knowledge,
                    query,
                    retrieved_evidence=deepcopy(retrieved_evidence),
                    context=deepcopy(dict(context or {})),
                ),
                timeout=timeout_seconds,
            )
            return self._source_record("completed", started, items=self._unwrap_items(raw))
        except TimeoutError:
            logger.warning(
                "Model knowledge synthesis timed out: timeout={}s query={}",
                timeout_seconds,
                query[:200],
            )
            return self._source_record(
                "timed_out", started, error="model knowledge synthesis timed out"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Model knowledge synthesis failed: error={}", self._safe_error(exc))
            return self._source_record("failed", started, error=self._safe_error(exc))

    async def _invoke(self, function: ResearchCallable, query: str, **kwargs: Any) -> Any:
        """Pass only accepted optional kwargs so existing tool adapters plug in directly."""
        try:
            signature = inspect.signature(function)
            accepts_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            accepted = kwargs if accepts_kwargs else {
                key: value for key, value in kwargs.items() if key in signature.parameters
            }
        except (TypeError, ValueError):
            accepted = kwargs
        return await function(query, **accepted)

    def _unwrap_items(self, raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, Mapping) and raw.get("success") is False:
            raise RuntimeError(str(raw.get("error") or "research source returned failure"))
        value = raw
        if isinstance(value, Mapping) and "result" in value:
            value = value["result"]
        if isinstance(value, Mapping):
            value = value.get("results", value.get("items", value.get("evidence", [])))
        if value is None:
            return []
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError("research source did not return an item list")
        return [deepcopy(dict(item)) for item in value[: self._max_items] if isinstance(item, Mapping)]

    @staticmethod
    def _source_record(
        status: str,
        started: float,
        *,
        items: list[dict[str, Any]] | None = None,
        error: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "status": status,
            "evidence_ids": [],
            "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            "items": items or [],
        }
        if error:
            record["error"] = error
        if query:
            record["query"] = query
        return record

    @classmethod
    def _filter_web_items(
        cls,
        items: Sequence[Mapping[str, Any]],
        request: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        accepted: list[dict[str, Any]] = []
        rejected: list[str] = []
        seen: set[tuple[str, str]] = set()
        for raw in items:
            item = deepcopy(dict(raw))
            reason, quality = cls._assess_web_item(item, request)
            if reason:
                rejected.append(reason)
                continue
            item["evidence_quality"] = quality
            locator = str(item.get("url") or item.get("link") or "").strip().casefold()
            title = str(item.get("title") or item.get("name") or "").strip().casefold()
            dedupe_key = (locator.rstrip("/"), re.sub(r"\W+", "", title)[:120])
            if dedupe_key in seen:
                rejected.append("duplicate_result")
                continue
            seen.add(dedupe_key)
            accepted.append(item)
        return accepted, rejected

    @staticmethod
    def _assess_web_item(
        raw: Mapping[str, Any], request: str
    ) -> tuple[str | None, dict[str, Any]]:
        locator = str(raw.get("url") or raw.get("link") or "").strip()
        host = urlparse(locator).netloc.casefold().removeprefix("www.")
        text = " ".join(
            str(raw.get(key) or "")
            for key in ("title", "name", "claim", "excerpt", "snippet", "content", "text")
        ).casefold()
        if not locator or not host:
            return "missing_locator", {}
        if any(blocked in host for blocked in _BLOCKED_WEB_HOSTS):
            return f"blocked_host:{host}", {}
        if any(marker in text for marker in _LOW_QUALITY_TEXT_MARKERS):
            return "low_quality_content", {}
        profile = select_research_profile(request)
        technical_terms = {term.casefold() for term in _research_subject_terms(request)}
        target_hits = {term for term in technical_terms if term in text}
        profile_hits = {term for term in profile.relevance_terms if term in text}
        trusted = ResearchBundleService._is_trusted_web_host(host)
        relevance_score = len(target_hits) * 3 + min(len(profile_hits), 5)
        authority_tier = "trusted" if trusted else "unverified"
        quality = {
            "research_profile": profile.name,
            "authority_tier": authority_tier,
            "relevance_score": relevance_score,
            "matched_terms": sorted({*target_hits, *profile_hits}),
        }
        if profile.name == "general":
            if trusted and (target_hits or profile_hits or not technical_terms):
                return None, quality
            if len(target_hits) >= 2 or (target_hits and profile_hits):
                return None, quality
            return "insufficient_relevance:general", quality
        if trusted and relevance_score >= 2:
            return None, quality
        if relevance_score >= 4:
            return None, quality
        return f"insufficient_relevance:{profile.name}", quality

    @staticmethod
    def _is_trusted_web_host(host: str) -> bool:
        return any(trusted_host in host for trusted_host in _TRUSTED_WEB_HOSTS) or host.endswith(
            _TRUSTED_WEB_SUFFIXES
        )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = re.sub(r"(?i)(api[_-]?key|token|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", str(exc))
        return (message or type(exc).__name__)[:500]

    @staticmethod
    def _evidence_item(
        source: str, raw: Mapping[str, Any], sequence: int
    ) -> dict[str, Any] | None:
        title = str(raw.get("title") or raw.get("name") or "").strip()
        claim = str(
            raw.get("claim")
            or raw.get("excerpt")
            or raw.get("snippet")
            or raw.get("content")
            or raw.get("text")
            or ""
        ).strip()
        if not title and not claim:
            return None
        if source == "model_knowledge":
            locator = ""
            freshness = "not_applicable"
        elif source == "web":
            locator = str(raw.get("url") or raw.get("link") or "").strip()
            freshness = str(raw.get("freshness") or "current")
        else:
            locator = str(raw.get("url") or "").strip()
            if not locator:
                doc_id = str(raw.get("doc_id") or raw.get("id") or "unknown")
                section = str(raw.get("section_path") or "").strip()
                locator = f"kb://{doc_id}" + (f"#{section}" if section else "")
            freshness = str(raw.get("freshness") or "possibly_stale")
        return {
            "evidence_id": f"ev-{sequence:03d}",
            "source_type": source,
            "title": title or claim[:80],
            "locator": locator,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "freshness": freshness,
            "claim": claim,
            "confidence": str(raw.get("confidence") or "medium"),
            "evidence_quality": deepcopy(dict(raw.get("evidence_quality") or {})),
            "used_in_plan_sections": list(raw.get("used_in_plan_sections") or []),
        }


class OverdrivePlanningService:
    """Coordinate research, deterministic Markdown construction, review, and freeze."""

    def __init__(
        self,
        run_service: OverdriveRunService,
        research_service: ResearchBundleService,
        plan_builder: PlanBuilder,
    ) -> None:
        self._runs = run_service
        self._research = research_service
        self._plan_builder = plan_builder

    @staticmethod
    def select_lead_planner(
        request: str, agent_catalog: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        """Choose one smallest capability-matched planner, with general as fallback."""
        if not request.strip():
            raise ValidationError("任务方向不能为空")
        active = [item for item in agent_catalog if item.get("is_active", True)]
        if not active:
            raise ValidationError("没有可用的规划 Agent")
        normalized = request.casefold()
        scored: list[tuple[int, str, Mapping[str, Any], list[str]]] = []
        for candidate in active:
            agent_id = str(candidate.get("agent_id") or "").strip()
            if not agent_id:
                continue
            features = candidate.get("features") or {}
            if not isinstance(features, Mapping):
                features = {}
            terms = [
                *DOMAIN_HINTS.get(agent_id, ()),
                *(str(value) for value in features.get("capability_scope") or []),
                *(str(value) for value in features.get("capability_tags") or []),
            ]
            matches = sorted({term for term in terms if term and term.casefold() in normalized})
            score = len(matches) * 10 - (1 if agent_id == "agent-general" else 0)
            scored.append((score, agent_id, candidate, matches))
        if not scored:
            raise ValidationError("Agent catalog 缺少有效 agent_id")
        matched = [item for item in scored if item[0] > 0]
        if matched:
            score, agent_id, _candidate, matches = max(matched, key=lambda item: (item[0], item[1]))
            reason = f"任务命中规划能力：{', '.join(matches)}"
        else:
            general = next((item for item in scored if item[1] == "agent-general"), None)
            score, agent_id, _candidate, matches = general or max(
                scored, key=lambda item: (item[0], item[1])
            )
            reason = "任务方向未命中特定领域，由通用规划 Agent 完成 intake 与跨域方案"
        return {
            "lead_planner_agent_id": agent_id,
            "advisor_agent_ids": [],
            "reason": reason,
            "matched_capabilities": matches,
            "score": score,
        }

    async def prepare_plan(
        self,
        run: OverdriveRunModel,
        *,
        known_agent_ids: set[str],
        project_id: str | None = None,
        revision_feedback: str = "",
    ) -> dict[str, Any]:
        await self._runs.transition(run, "RESEARCHING")
        research_queries = build_research_queries(run.root_request)
        await self._runs.append_event(
            run.run_id,
            "research_started",
            {
                "research_profile": research_queries["profile"],
                "queries": research_queries["web_queries"],
                "sources": ["knowledge_base", "web", "model_knowledge"],
            },
            dedupe_key=f"research_started:{int((run.plan or {}).get('version') or 0) + 1}",
        )
        bundle = await self._research.collect(
            run.root_request,
            project_id=project_id,
            context={
                "lead_planner_agent_id": run.lead_planner_agent_id,
                "revision_feedback": revision_feedback,
            },
        )
        await self._runs.save_research(
            run,
            bundle.evidence,
            bundle.statuses,
            source_details=bundle.sources,
        )
        await self._runs.transition(run, "PLAN_DRAFTED")
        plan_payload = await self._maybe_await(
            self._plan_builder(
                request=run.root_request,
                lead_planner_agent_id=run.lead_planner_agent_id,
                research=deepcopy(bundle.evidence),
                research_sources=deepcopy(bundle.sources),
                revision_feedback=revision_feedback,
            )
        )
        if not isinstance(plan_payload, Mapping):
            raise ValidationError("规划 Agent 未返回结构化计划")
        tasks = [deepcopy(dict(item)) for item in plan_payload.get("tasks") or []]
        planning_only = self.is_planning_only_request(run.root_request, tasks)
        if planning_only:
            tasks = self.prepare_planning_only_tasks(tasks)
        content = str(plan_payload.get("content") or "").strip()
        if not content or planning_only:
            markdown_plan = deepcopy(dict(plan_payload))
            markdown_plan["_planning_only"] = planning_only
            if planning_only:
                markdown_plan["deliverables"] = markdown_plan.get("deliverables") or ["研究方案（plan.md）"]
                markdown_plan["manager_preflight"] = ["完成证据检索、方法学核验与方案结构化整理"]
                markdown_plan["agent_selection_reasons"] = [
                    f"{run.lead_planner_agent_id}：负责领域研究与方案撰写"
                ]
                markdown_plan["risks"] = ["证据不足处明确标记为待验证推断，不伪造结论"]
                markdown_plan["quality_gates"] = [
                    "方案覆盖研究设计、关键分析节点、验证路径、限制与交付物",
                    "引用证据可追溯；无证据支持的内容明确标记为待验证推断",
                ]
            content = build_plan_markdown(
                request=run.root_request,
                lead_planner_agent_id=str(run.lead_planner_agent_id or ""),
                evidence=bundle.evidence,
                research_sources=bundle.sources,
                tasks=tasks,
                plan=markdown_plan,
                next_version=int((run.plan or {}).get("version") or 0) + 1,
            )
        validate_plan(content, tasks, known_agent_ids, allow_empty_tasks=planning_only)
        await self._runs.transition(run, "PLAN_REVIEWING")
        draft_file = await self._runs.write_plan_draft(run, content)
        next_version = int(draft_file["version"])
        await self._runs.append_event(
            run.run_id,
            "plan_ready",
            {
                "lead_planner_agent_id": run.lead_planner_agent_id,
                "evidence_count": len(bundle.evidence),
                "plan_path": draft_file["path"],
            },
            dedupe_key=f"plan_ready:{next_version}",
        )
        await self._runs.append_event(
            run.run_id,
            "plan_review_passed",
            {
                "plan_version": next_version,
                "review_mode": "contract",
                "reviewed_by": "manager",
            },
            dedupe_key=f"plan_review_passed:{next_version}",
        )
        summary = deepcopy(dict(plan_payload.get("summary") or {}))
        summary.setdefault("evidence_count", len(bundle.evidence))
        summary["planning_only"] = planning_only
        summary["agent_ids"] = sorted({str(task.get("agent_id")) for task in tasks})
        summary["wave_count"] = len(task_waves(tasks))
        summary["deliverables"] = ["plan.md"] if planning_only else sorted(
            {
                str(output)
                for task in tasks
                for output in task.get("produces_outputs") or []
                if str(output).strip()
            }
        )
        return await self._runs.freeze_plan(
            run,
            content=content,
            tasks=tasks,
            known_agent_ids=known_agent_ids,
            summary=summary,
            allow_empty_tasks=planning_only,
        )

    @staticmethod
    def is_planning_only_request(request: str, tasks: Sequence[Mapping[str, Any]]) -> bool:
        return is_planning_only_request(request, tasks)

    @staticmethod
    def prepare_planning_only_tasks(tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """保留方案分解 DAG，但移除计划阶段不应执行的写入和计算能力。"""
        execution_tools = {"workspace_write", "sandbox_execute", "code_execute", "pipeline_submit"}
        prepared: list[dict[str, Any]] = []
        for task in tasks:
            item = deepcopy(dict(task))
            item["workspace_access"] = False
            item["requires_approval"] = False
            item["tools"] = [
                str(tool)
                for tool in item.get("tools") or []
                if str(tool) not in execution_tools
            ] or ["workspace_read"]
            prepared.append(item)
        return prepared

    @staticmethod
    async def _maybe_await(value: Awaitable[Any] | Any) -> Any:
        return await value if inspect.isawaitable(value) else value


def task_waves(tasks: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    """Return deterministic dependency waves; validation reports cycles later."""
    unresolved = {
        str(task.get("task_id") or ""): {str(dep) for dep in task.get("depends_on") or []}
        for task in tasks
    }
    waves: list[list[str]] = []
    while unresolved:
        ready = sorted(task_id for task_id, deps in unresolved.items() if not deps)
        if not ready:
            break
        waves.append(ready)
        ready_set = set(ready)
        unresolved = {
            task_id: dependencies - ready_set
            for task_id, dependencies in unresolved.items()
            if task_id not in ready_set
        }
    return waves


def build_plan_markdown(
    *,
    request: str,
    lead_planner_agent_id: str,
    evidence: Sequence[Mapping[str, Any]],
    research_sources: Mapping[str, Mapping[str, Any]] | None = None,
    tasks: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
    next_version: int,
) -> str:
    """Build the mandatory plan document without inventing missing evidence."""

    def bullets(value: Any, empty: str = "- 无") -> str:
        if isinstance(value, str):
            value = [value] if value.strip() else []
        rows = [f"- {item}" for item in (value or []) if str(item).strip()]
        return "\n".join(rows) or empty

    evidence_groups = {source: [] for source in SOURCE_TYPES}
    for item in evidence:
        evidence_groups.setdefault(str(item.get("source_type") or ""), []).append(item)

    def evidence_lines(source: str) -> str:
        rows = []
        for item in evidence_groups.get(source, []):
            locator = str(item.get("locator") or "")
            suffix = f"（{locator}）" if locator else "（模型通用知识；无检索定位）"
            quality = dict(item.get("evidence_quality") or {})
            quality_suffix = ""
            if quality:
                quality_suffix = (
                    f" [来源：{quality.get('authority_tier', 'unknown')}；"
                    f"相关性：{quality.get('relevance_score', 0)}]"
                )
            rows.append(
                f"- [{item.get('evidence_id')}] {item.get('claim') or item.get('title')} "
                f"{suffix}{quality_suffix}"
            )
        source_record = dict((research_sources or {}).get(source) or {})
        prefix: list[str] = []
        research_profile = str(source_record.get("research_profile") or "").strip()
        if research_profile:
            prefix.append(f"- 研究画像：`{research_profile}`")
        refinement = source_record.get("query_refinement")
        if isinstance(refinement, Mapping):
            mode = str(refinement.get("status") or "fallback")
            query_count = len(refinement.get("queries") or [])
            prefix.append(
                f"- 检索词策略：规划 Agent 已{('精炼' if mode == 'refined' else '回退生成')} "
                f"{query_count} 条联合检索式。"
            )
        channels = source_record.get("channels")
        if isinstance(channels, Mapping):
            channel_labels = {
                "literature": "Europe PMC 专用文献检索",
                "general_web": "默认联网搜索",
            }
            rendered_channels = [
                f"{channel_labels.get(str(name), str(name))}={dict(detail).get('status', 'unknown')}"
                for name, detail in channels.items()
                if isinstance(detail, Mapping)
            ]
            if rendered_channels:
                prefix.append(f"- 检索通道：{'；'.join(rendered_channels)}。")
        search_queries = source_record.get("queries") or [source_record.get("query")]
        for search_query in search_queries:
            if str(search_query or "").strip():
                prefix.append(f"- 实际检索式：`{str(search_query).strip()}`")
        rejected_count = int(source_record.get("rejected_count") or 0)
        if rejected_count:
            prefix.append(f"- 质量门已剔除 {rejected_count} 条低可信、重复或主题不相关结果。")
        if rows:
            return "\n".join([*prefix, *rows])
        empty = (
            "- 本路没有通过相关性与来源质量门的可用证据；详见 evidence.json。"
            if research_sources is not None
            else "- 本路没有可用证据；详见 evidence.json 的状态与失败原因。"
        )
        return "\n".join([*prefix, empty])

    waves = task_waves(tasks)
    planning_only = bool(plan.get("_planning_only"))
    wave_lines = "\n".join(
        f"- 波次 {index}: {', '.join(task_ids)}"
        for index, task_ids in enumerate(waves, start=1)
    ) or ("- 本轮仅交付研究方案，无需启动执行任务" if planning_only else "- 尚无可执行波次")
    task_blocks = []
    for task in tasks:
        task_blocks.append(
            f"### 任务 `{task.get('task_id', '')}`\n\n"
            f"```json\n{json.dumps(dict(task), ensure_ascii=False, indent=2)}\n```"
        )
    task_markdown = "\n\n".join(task_blocks) or (
        "- 本轮无方案分解任务；确认后直接完成方案交付，不进入 Worker 执行。"
        if planning_only else "- 尚无任务"
    )
    return (
        "# 执行计划\n\n"
        f"## 1. 用户目标与最终交付物\n\n{request.strip()}\n\n"
        f"{bullets(plan.get('deliverables'), '- 最终交付物待用户确认')}\n\n"
        f"## 2. 已确认输入\n\n{bullets(plan.get('confirmed_inputs'), '- 暂无已确认输入')}\n\n"
        "## 3. 假设、限制与待确认事项\n\n"
        f"{bullets(plan.get('assumptions'), '- 无额外假设')}\n\n"
        "## 4. 研究与证据摘要\n\n"
        f"### 4.1 平台知识库\n\n{evidence_lines('knowledge_base')}\n\n"
        f"### 4.2 网络资料\n\n{evidence_lines('web')}\n\n"
        "### 4.3 模型通用知识与待验证推断\n\n"
        f"{evidence_lines('model_knowledge')}\n\n"
        "## 5. 主 Agent 串行前置工作\n\n"
        f"{bullets(plan.get('manager_preflight'), '- 核验输入、数据契约与必要 Skill')}\n\n"
        "## 6. Agent 选择与理由\n\n"
        f"- 规划 Agent：`{lead_planner_agent_id}`\n"
        f"{bullets(plan.get('agent_selection_reasons'), '- 执行 Agent 以任务契约为准')}\n\n"
        f"## 7. 执行 DAG 与波次\n\n{wave_lines}\n\n"
        "## 8. 每个任务的输入、输出、工具、超时与重试\n\n"
        f"{task_markdown}\n\n"
        "## 9. 风险、审批点与停止条件\n\n"
        f"{bullets(plan.get('risks'), '- 未识别到额外风险')}\n\n"
        "## 10. 质量门与验收标准\n\n"
        f"{bullets(plan.get('quality_gates'), '- 每个任务满足 completion_criteria')}\n\n"
        f"## 11. 交付目录\n\n{bullets(plan.get('delivery_paths'), '- delivery/')}\n\n"
        "## 12. 计划版本与变更记录\n\n"
        f"- 版本：v{next_version}\n"
        f"{bullets(plan.get('change_log'), '- 初始版本')}\n"
    )
