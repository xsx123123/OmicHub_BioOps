"""F9 离线 eval 闭环首用：Manager 组队质量评测（draft → test → 对照 eval → mean±stddev 报告）。

spec：docs/info/26.8.21/协作室融合ClaudeScience设计理念评估与实施方案.md Part 4 F9。
纯离线工具：只读生产模块（路由/能力目录/路由 prompt），不改任何生产逻辑。

双臂定义：
  A 臂（baseline，路由圈选）：房间关键词路由 ``build_route_decision``，纯规则、确定性、
      不消耗 LLM token；预测专家组 = 路由决策的 participants。
  B 臂（带配置，路由圈候选 + LLM 组队会诊）：沿用 chat_service 生产路由 prompt
      （ROUTER_SYSTEM_PROMPT + summary 层能力目录 + 流程目录，F5 渐进暴露口径），
      用户输入附加 A 臂路由圈候选；LLM 输出 agent_id + consult_agent_ids 作为预测组队。
      LLM 可注入：
        --llm-stub    确定性启发式 stub（离线/CI 默认；输出标注 stub 口径，不代表真实模型质量）
        --llm-live    OpenAI 兼容接口真实调用，凭证从环境变量读取：
                      TEAMING_EVAL_LLM_BASE_URL / TEAMING_EVAL_LLM_API_KEY / TEAMING_EVAL_LLM_MODEL
                      缺凭证显式跳过 B 臂并在报告中标注"待真实运行"，禁止编造结果。
        --llm-replay FILE  回放录制的响应 fixtures（JSON：{sample_id: response_text}）
        --llm-record FILE  配合 --llm-live 录制响应到 fixtures

token 口径：tiktoken cl100k_base，与 W3 scripts/measure_capability_catalog_tokens.py 一致。

用法：
  .venv/bin/python scripts/poc/teaming_eval/run_teaming_eval.py                    # stub 离线闭环
  .venv/bin/python scripts/poc/teaming_eval/run_teaming_eval.py --reps 3
  .venv/bin/python scripts/poc/teaming_eval/run_teaming_eval.py --llm-live --reps 3
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tiktoken
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from cygnusx.application.services.agentteams_capability_registry import (  # noqa: E402
    AgentTeamsCapabilityRegistry,
)
from cygnusx.application.services.agentteams_route_decision import (  # noqa: E402
    build_route_decision,
)
from cygnusx.application.services.chat_service import (  # noqa: E402
    ROUTER_CATALOG_SUMMARY_KEYS,
    ROUTER_SYSTEM_PROMPT,
)

_SAMPLES_PATH = Path(__file__).resolve().parent / "samples.yaml"
_DEFAULT_REPORT = _REPO_ROOT / "docs/info/26.8.21/F9_Manager组队质量评测报告.md"
_EVIDENCE_DIR = _REPO_ROOT / "evidence" / "teaming-eval"

_IGNORED_CHARS = frozenset("-_ \t\r\n")
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _tokens(text: str) -> int:
    """tiktoken cl100k_base 口径（与 W3 measure_capability_catalog_tokens.py 一致）。"""
    return len(tiktoken.get_encoding("cl100k_base").encode(text))


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch not in _IGNORED_CHARS)


# ---------------------------------------------------------------- 样本与指标


@dataclass(frozen=True)
class Sample:
    id: str
    text: str
    gold_experts: frozenset[str]
    needs_clarification: bool
    source: str
    note: str = ""


def load_samples(path: Path = _SAMPLES_PATH) -> list[Sample]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    samples = [
        Sample(
            id=str(item["id"]),
            text=str(item["text"]),
            gold_experts=frozenset(str(a) for a in item.get("gold_experts") or []),
            needs_clarification=bool(item.get("needs_clarification")),
            source=str(item.get("source") or ""),
            note=str(item.get("note") or ""),
        )
        for item in data["samples"]
    ]
    if not 20 <= len(samples) <= 30:
        raise ValueError(f"样本数 {len(samples)} 不在 F9 要求的 20-30 区间")
    return samples


def prf1(gold: frozenset[str], pred: set[str]) -> tuple[float, float, float]:
    """集合级 precision/recall/F1；双空集定义为全对（1,1,1），金标准为空而误派为 (0,0,0)。"""
    if not gold and not pred:
        return 1.0, 1.0, 1.0
    if not gold or not pred:
        return 0.0, 0.0, 0.0
    hit = len(gold & pred)
    precision = hit / len(pred)
    recall = hit / len(gold)
    f1 = 2 * precision * recall / (precision + recall) if hit else 0.0
    return precision, recall, f1


def mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    return statistics.mean(values), statistics.stdev(values)


# ---------------------------------------------------------------- 双臂


@dataclass
class ArmResult:
    predicted: set[str]
    needs_clarification: bool
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    detail: dict[str, Any] = field(default_factory=dict)


def run_arm_a(text: str) -> ArmResult:
    """A 臂 baseline：纯关键词路由圈选（生产 build_route_decision，确定性，零 LLM token）。"""
    start = time.perf_counter()
    decision = build_route_decision(text) or {}
    latency_ms = (time.perf_counter() - start) * 1000
    return ArmResult(
        predicted={str(p) for p in decision.get("participants") or []},
        needs_clarification=decision.get("confidence") == "ambiguous",
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=latency_ms,
        detail={
            "path": decision.get("path"),
            "flow_id": decision.get("flow_id"),
            "confidence": decision.get("confidence"),
            "fallback": bool(decision.get("fallback")),
        },
    )


def build_arm_b_prompt(
    text: str,
    *,
    registry: AgentTeamsCapabilityRegistry,
    arm_a_detail: dict[str, Any],
) -> tuple[str, str]:
    """B 臂 prompt：生产 ROUTER_SYSTEM_PROMPT（summary 层目录）+ 路由圈候选上下文。

    返回 (system_prompt, user_input)；token 统计对象与生产注入一致。
    """
    snapshot = registry.snapshot()
    candidates = list(snapshot.get("chat_router_catalog") or [])
    catalog = json.dumps(
        [{key: entry.get(key) for key in ROUTER_CATALOG_SUMMARY_KEYS} for entry in candidates],
        ensure_ascii=False,
    )
    flow_catalog = json.dumps(snapshot.get("flow_router_catalog") or [], ensure_ascii=False)
    system_prompt = ROUTER_SYSTEM_PROMPT.replace("{catalog}", catalog).replace(
        "{flow_catalog}", flow_catalog
    )
    route_hint = (
        f"命中流程 {arm_a_detail['flow_id']}（confidence={arm_a_detail['confidence']}）"
        if arm_a_detail.get("flow_id")
        else "无流程命中（overdrive/通用路径）"
    )
    user_input = f"{text}\n\n[房间关键词路由圈选候选，仅供参考：{route_hint}]"
    return system_prompt, user_input


def parse_router_decision(response_text: str, valid_ids: set[str]) -> dict[str, Any]:
    """解析 LLM 路由决策 JSON；解析失败返回 None 由调用方记为失败样本。"""
    match = _JSON_RE.search(response_text or "")
    if not match:
        return None  # type: ignore[return-value]
    try:
        decision = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None  # type: ignore[return-value]
    if not isinstance(decision, dict):
        return None  # type: ignore[return-value]
    agent_id = str(decision.get("agent_id") or "")
    consults = [
        str(item)
        for item in decision.get("consult_agent_ids") or []
        if str(item) in valid_ids and str(item) != agent_id
    ]
    return {
        "agent_id": agent_id if agent_id in valid_ids else "",
        "consult_agent_ids": list(dict.fromkeys(consults)),
        "confidence": float(decision.get("confidence") or 0.0),
        "collaboration_intent": str(decision.get("collaboration_intent") or ""),
    }


def run_arm_b(
    text: str,
    *,
    registry: AgentTeamsCapabilityRegistry,
    llm: Callable[[str, str, str], str],
    sample_id: str,
    arm_a_detail: dict[str, Any] | None = None,
) -> ArmResult:
    """B 臂：路由圈候选 + LLM 组队会诊；llm(system_prompt, user_input, sample_id) 可注入。"""
    # 路由圈候选（纯规则，零成本）；evaluate 已跑过 A 臂时直接复用其 detail。
    if arm_a_detail is None:
        arm_a_detail = run_arm_a(text).detail
    system_prompt, user_input = build_arm_b_prompt(
        text, registry=registry, arm_a_detail=arm_a_detail
    )
    prompt_tokens = _tokens(system_prompt) + _tokens(user_input)
    start = time.perf_counter()
    response_text = llm(system_prompt, user_input, sample_id)
    latency_ms = (time.perf_counter() - start) * 1000
    valid_ids = {str(c["agent_id"]) for c in registry.snapshot().get("chat_router_catalog") or []}
    decision = parse_router_decision(response_text, valid_ids)
    if decision is None:
        return ArmResult(
            predicted=set(),
            needs_clarification=True,
            prompt_tokens=prompt_tokens,
            completion_tokens=_tokens(response_text or ""),
            latency_ms=latency_ms,
            detail={"parse_failed": True, "raw_response": (response_text or "")[:500]},
        )
    predicted = {decision["agent_id"], *decision["consult_agent_ids"]} - {""}
    return ArmResult(
        predicted=predicted,
        # 与生产口径一致：confidence < 0.6 表示需要向用户澄清（ROUTER_SYSTEM_PROMPT 规则 11）。
        needs_clarification=decision["confidence"] < 0.6,
        prompt_tokens=prompt_tokens,
        completion_tokens=_tokens(response_text),
        latency_ms=latency_ms,
        detail={
            "collaboration_intent": decision["collaboration_intent"],
            "confidence": decision["confidence"],
        },
    )


# ---------------------------------------------------------------- LLM 注入


def make_stub_llm(registry: AgentTeamsCapabilityRegistry) -> Callable[[str, str, str], str]:
    """确定性启发式 stub：按 summary 层目录关键词命中打分，模拟路由决策输出。

    仅用于离线闭环验证管线；输出标注 stub 口径，不代表任何真实模型质量。
    规则：对目录候选逐条统计 routing_hints/capability_tags/routing_notes/description
    中的词项在归一化需求文本中的命中数，最高分者为 agent_id，次高分（>=最高分一半）
    进 consult_agent_ids（至多 2 个）；无任何命中时选 category=general 候选并给低置信度。
    """
    catalog = list(registry.snapshot().get("chat_router_catalog") or [])

    def _terms(value: Any) -> list[str]:
        """目录字段统一成词项列表：list 直接取；str（如 routing_notes 散文）按标点切成候选词。"""
        if isinstance(value, str):
            return [t for t in re.split(r"[，。、：:；;/\s—]+", value) if t]
        return [str(v) for v in value or []]

    def _score(entry: dict[str, Any], normalized: str) -> int:
        terms = [
            *_terms(entry.get("routing_hints")),
            *_terms(entry.get("capability_tags")),
            *_terms(entry.get("routing_notes")),
            *_terms(entry.get("description")),
        ]
        return sum(
            1
            for term in terms
            if (t := _normalize(term)) and len(t) >= 2 and t in normalized
        )

    def _stub(system_prompt: str, user_input: str, sample_id: str) -> str:
        del system_prompt
        # stub 只看需求原文，不参考路由候选行（避免自证）。
        normalized = _normalize(user_input.split("\n\n[房间关键词路由圈选候选")[0])
        scored = sorted(
            (( _score(entry, normalized), str(entry["agent_id"])) for entry in catalog),
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
        top_score, top_id = scored[0] if scored else (0, "")
        if top_score <= 0:
            general = next(
                (str(e["agent_id"]) for e in catalog if e.get("category") == "general"),
                top_id,
            )
            return json.dumps(
                {
                    "agent_id": general,
                    "reason": "stub: 无关键词命中，回落通用入口",
                    "consult_agent_ids": [],
                    "collaboration_intent": "chat",
                    "confidence": 0.4,
                },
                ensure_ascii=False,
            )
        consults = [
            agent_id
            for score, agent_id in scored[1:]
            if score > 0 and score * 2 >= top_score and agent_id != top_id
        ][:2]
        return json.dumps(
            {
                "agent_id": top_id,
                "reason": f"stub: 关键词命中 {top_score} 项",
                "consult_agent_ids": consults,
                "collaboration_intent": "consult" if consults else "chat",
                "confidence": 0.9,
            },
            ensure_ascii=False,
        )

    return _stub


def make_live_llm(record_sink: dict[str, str] | None = None) -> Callable[[str, str, str], str]:
    """OpenAI 兼容接口真实调用；凭证仅从环境变量读取，缺失时抛 RuntimeError 由调用方跳过。"""
    base_url = os.environ.get("TEAMING_EVAL_LLM_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("TEAMING_EVAL_LLM_API_KEY", "")
    model = os.environ.get("TEAMING_EVAL_LLM_MODEL", "")
    missing = [
        name
        for name, value in (
            ("TEAMING_EVAL_LLM_BASE_URL", base_url),
            ("TEAMING_EVAL_LLM_API_KEY", api_key),
            ("TEAMING_EVAL_LLM_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"缺少真实运行凭证环境变量: {', '.join(missing)}")

    import httpx

    def _live(system_prompt: str, user_input: str, sample_id: str) -> str:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
                "temperature": 0,
                "max_tokens": 200,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        text = str(response.json()["choices"][0]["message"]["content"] or "")
        if record_sink is not None:
            record_sink[sample_id] = text
        return text

    return _live


def make_replay_llm(fixtures_path: Path) -> Callable[[str, str, str], str]:
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))

    def _replay(system_prompt: str, user_input: str, sample_id: str) -> str:
        del system_prompt, user_input
        if sample_id not in fixtures:
            raise KeyError(f"fixtures 缺少样本 {sample_id} 的录制响应")
        return str(fixtures[sample_id])

    return _replay


# ---------------------------------------------------------------- 评测闭环


@dataclass
class SampleEval:
    sample: Sample
    arm_a: ArmResult | None = None
    arm_b_runs: list[ArmResult] = field(default_factory=list)


def evaluate(
    samples: list[Sample],
    *,
    registry: AgentTeamsCapabilityRegistry,
    llm: Callable[[str, str, str], str] | None,
    reps: int,
) -> list[SampleEval]:
    evals: list[SampleEval] = []
    for sample in samples:
        entry = SampleEval(sample=sample)
        # A 臂确定性（纯规则路由），reps=1 即可，多次重复结果相同。
        entry.arm_a = run_arm_a(sample.text)
        if llm is not None:
            for _ in range(max(1, reps)):
                entry.arm_b_runs.append(
                    run_arm_b(
                        sample.text,
                        registry=registry,
                        llm=llm,
                        sample_id=sample.id,
                        arm_a_detail=entry.arm_a.detail,
                    )
                )
        evals.append(entry)
    return evals


def _arm_aggregate(
    rows: list[tuple[Sample, ArmResult]],
) -> dict[str, Any]:
    f1s: list[float] = []
    ps: list[float] = []
    rs: list[float] = []
    clarify_hits = 0
    for sample, result in rows:
        p, r, f1 = prf1(sample.gold_experts, result.predicted)
        ps.append(p)
        rs.append(r)
        f1s.append(f1)
        clarify_hits += int(result.needs_clarification == sample.needs_clarification)
    f1_mean, f1_std = mean_std(f1s)
    p_mean, p_std = mean_std(ps)
    r_mean, r_std = mean_std(rs)
    prompt_mean, prompt_std = mean_std([float(r.prompt_tokens) for _, r in rows])
    completion_mean, completion_std = mean_std([float(r.completion_tokens) for _, r in rows])
    latency_mean, latency_std = mean_std([r.latency_ms for _, r in rows])
    return {
        "n": len(rows),
        "precision": {"mean": p_mean, "std": p_std},
        "recall": {"mean": r_mean, "std": r_std},
        "f1": {"mean": f1_mean, "std": f1_std},
        "clarify_accuracy": clarify_hits / len(rows) if rows else 0.0,
        "prompt_tokens": {"mean": prompt_mean, "std": prompt_std},
        "completion_tokens": {"mean": completion_mean, "std": completion_std},
        "latency_ms": {"mean": latency_mean, "std": latency_std},
    }


def aggregate(evals: list[SampleEval]) -> dict[str, Any]:
    arm_a_rows = [(e.sample, e.arm_a) for e in evals if e.arm_a is not None]
    arm_b_rows = [
        (e.sample, run) for e in evals for run in e.arm_b_runs
    ]
    return {
        "arm_a": _arm_aggregate(arm_a_rows),
        "arm_b": _arm_aggregate(arm_b_rows) if arm_b_rows else None,
    }


# ---------------------------------------------------------------- 报告


def _fmt_team(team: set[str] | frozenset[str]) -> str:
    return ", ".join(sorted(team)) if team else "（空）"


def _fmt_diff(gold: frozenset[str], pred: set[str]) -> str:
    parts = []
    if extra := sorted(pred - gold):
        parts.append("误派: " + ", ".join(extra))
    if missing := sorted(gold - pred):
        parts.append("漏派: " + ", ".join(missing))
    return "；".join(parts) if parts else "-"


def render_report(
    evals: list[SampleEval],
    summary: dict[str, Any],
    *,
    llm_mode: str,
    reps: int,
    results_path: Path,
) -> str:
    a = summary["arm_a"]
    b = summary["arm_b"]
    now = datetime.now(UTC).astimezone()
    lines: list[str] = [
        "# F9 离线 eval 闭环首用：Manager 组队质量评测报告",
        "",
        f"> 生成时间：{now.isoformat(timespec='seconds')}；生成脚本："
        "`scripts/poc/teaming_eval/run_teaming_eval.py`（本报告数字全部来自该脚本真实运行输出）。",
        f"> 原始运行数据：`{results_path.relative_to(_REPO_ROOT)}`。",
        "> spec：docs/info/26.8.21/协作室融合ClaudeScience设计理念评估与实施方案.md Part 4 F9。",
        "",
        "## 1. 评测配置",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 样本数 | {len(evals)}（`scripts/poc/teaming_eval/samples.yaml`，逐条标注来源） |",
        "| A 臂（baseline） | 路由圈选：`build_route_decision` 纯关键词/规则路由，确定性，零 LLM token，reps=1 |",
        f"| B 臂（带配置） | 路由圈候选 + LLM 组队会诊（生产 ROUTER_SYSTEM_PROMPT + summary 层目录），LLM 模式：**{llm_mode}**，reps={reps} |",
        "| token 口径 | tiktoken cl100k_base（与 W3 `scripts/measure_capability_catalog_tokens.py` 一致），统计注入 prompt 的目录/输入文本 |",
        "",
    ]
    if llm_mode == "stub":
        lines += [
            "> ⚠️ **stub 口径声明**：本轮 B 臂由确定性启发式 stub 驱动（关键词命中打分），"
            "用于离线验证评测管线闭环；其数字**不代表任何真实模型质量**，"
            "组队策略权重决策须以 `--llm-live` 或 `--llm-replay` 的真实运行为准。",
            "",
        ]
    if b is None:
        lines += [
            "> ⚠️ B 臂**待真实运行**：未提供 LLM（缺凭证且未指定 stub/replay），本报告仅含 A 臂基线。",
            "",
        ]

    lines += [
        "## 2. 样本集（真实需求提炼，逐条来源）",
        "",
        "| id | 需求文本 | 金标准专家 | 需澄清 | 来源 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in evals:
        s = e.sample
        lines.append(
            f"| {s.id} | {s.text} | {_fmt_team(s.gold_experts)} | "
            f"{'是' if s.needs_clarification else '否'} | {s.source} |"
        )

    lines += [
        "",
        "## 3. 双臂逐样本结果",
        "",
        "| id | A 预测组队 | A F1 | A 差异明细 | B 预测组队 | B F1 | B 差异明细 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in evals:
        s = e.sample
        a_res = e.arm_a
        a_f1 = prf1(s.gold_experts, a_res.predicted)[2] if a_res else 0.0
        a_cell = f"{_fmt_team(a_res.predicted)} | {a_f1:.2f} | {_fmt_diff(s.gold_experts, a_res.predicted)}" if a_res else "— | — | —"
        if e.arm_b_runs:
            # 逐样本取首 rep 展示（stub 确定性各 rep 相同；live 各 rep 明细见原始 JSON）。
            b_res = e.arm_b_runs[0]
            b_f1 = prf1(s.gold_experts, b_res.predicted)[2]
            if b_res.detail.get("parse_failed"):
                b_cell = f"（解析失败） | 0.00 | {_fmt_diff(s.gold_experts, set())}"
            else:
                b_cell = f"{_fmt_team(b_res.predicted)} | {b_f1:.2f} | {_fmt_diff(s.gold_experts, b_res.predicted)}"
        else:
            b_cell = "待真实运行 | — | —"
        lines.append(f"| {s.id} | {a_cell} | {b_cell} |")

    lines += [
        "",
        "## 4. 聚合指标（mean ± stddev）",
        "",
        "A 臂为确定性规则路由（reps=1，stddev 仅反映样本间差异）；"
        f"B 臂统计口径为 样本×reps（n={b['n'] if b else 0}）。",
        "",
        "| 指标 | A 臂（路由圈选） | B 臂（路由+LLM 会诊） |",
        "| --- | --- | --- |",
        f"| 样本/运行数 | {a['n']} | {b['n'] if b else '—'} |",
        f"| Precision | {a['precision']['mean']:.3f} ± {a['precision']['std']:.3f} | "
        + (f"{b['precision']['mean']:.3f} ± {b['precision']['std']:.3f}" if b else "待真实运行")
        + " |",
        f"| Recall | {a['recall']['mean']:.3f} ± {a['recall']['std']:.3f} | "
        + (f"{b['recall']['mean']:.3f} ± {b['recall']['std']:.3f}" if b else "待真实运行")
        + " |",
        f"| **F1** | **{a['f1']['mean']:.3f} ± {a['f1']['std']:.3f}** | "
        + (f"**{b['f1']['mean']:.3f} ± {b['f1']['std']:.3f}**" if b else "**待真实运行**")
        + " |",
        f"| 澄清判定准确率 | {a['clarify_accuracy']:.3f} | "
        + (f"{b['clarify_accuracy']:.3f}" if b else "待真实运行")
        + " |",
        f"| Prompt tokens/次 | {a['prompt_tokens']['mean']:.0f} ± {a['prompt_tokens']['std']:.0f} | "
        + (f"{b['prompt_tokens']['mean']:.0f} ± {b['prompt_tokens']['std']:.0f}" if b else "待真实运行")
        + " |",
        f"| Completion tokens/次 | {a['completion_tokens']['mean']:.0f} ± {a['completion_tokens']['std']:.0f} | "
        + (f"{b['completion_tokens']['mean']:.0f} ± {b['completion_tokens']['std']:.0f}" if b else "待真实运行")
        + " |",
        f"| 耗时 ms/次 | {a['latency_ms']['mean']:.1f} ± {a['latency_ms']['std']:.1f} | "
        + (f"{b['latency_ms']['mean']:.1f} ± {b['latency_ms']['std']:.1f}" if b else "待真实运行")
        + " |",
        "",
        "## 5. 结论与待人工决策项",
        "",
    ]
    if b is not None:
        delta = b["f1"]["mean"] - a["f1"]["mean"]
        lines += [
            f"- F1 差值（B−A）：{delta:+.3f}（A={a['f1']['mean']:.3f}，B={b['f1']['mean']:.3f}）。",
            f"- token 成本：A 臂零 LLM token；B 臂每次组队平均 prompt "
            f"{b['prompt_tokens']['mean']:.0f} tokens + completion {b['completion_tokens']['mean']:.0f} tokens。",
            "",
            "**待人工决策（本报告只出数据，不自动改动任何组队策略权重）：**",
            "",
            "- [ ] 是否调整组队策略权重（路由圈选 vs LLM 会诊的优先级/触发条件）——依据上表 F1 差值与 token 成本由管理员决策。",
            "- [ ] 若本轮为 stub 口径：安排一次 `--llm-live`（或录制回放）真实运行后再决策。",
            "- [ ] 误派/漏派高发样本（见第 3 节明细）是否反馈到能力目录/trigger_hints 修订，走 F7 证据流程。",
        ]
    else:
        lines += [
            "- B 臂待真实运行：配置 `TEAMING_EVAL_LLM_BASE_URL/API_KEY/MODEL` 后 "
            "`--llm-live` 重跑，或录制后 `--llm-replay` 离线复跑。",
            "",
            "**待人工决策：**",
            "",
            "- [ ] B 臂真实运行完成前，不调整任何组队策略权重。",
        ]
    lines += [
        "",
        "## 6. 复现方法",
        "",
        "```bash",
        "# 离线 stub 闭环（CI 可用，无需凭证）",
        ".venv/bin/python scripts/poc/teaming_eval/run_teaming_eval.py --llm-stub --reps 3",
        "# 真实运行（凭证从环境变量读，缺失显式跳过）",
        "export TEAMING_EVAL_LLM_BASE_URL=... TEAMING_EVAL_LLM_API_KEY=... TEAMING_EVAL_LLM_MODEL=...",
        ".venv/bin/python scripts/poc/teaming_eval/run_teaming_eval.py --llm-live --reps 3 \\",
        "    --llm-record scripts/poc/teaming_eval/fixtures/llm_responses.json",
        "# 录制回放（离线复跑真实响应）",
        ".venv/bin/python scripts/poc/teaming_eval/run_teaming_eval.py \\",
        "    --llm-replay scripts/poc/teaming_eval/fixtures/llm_responses.json",
        "```",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--llm-stub", action="store_true", help="确定性 stub（离线/CI 默认）")
    mode.add_argument("--llm-live", action="store_true", help="真实 LLM（读 TEAMING_EVAL_LLM_* 环境变量）")
    mode.add_argument("--llm-replay", type=Path, default=None, help="回放录制 fixtures JSON")
    mode.add_argument("--llm-none", action="store_true", help="跳过 B 臂（仅 A 臂基线）")
    parser.add_argument("--llm-record", type=Path, default=None, help="配合 --llm-live 录制响应")
    parser.add_argument("--reps", type=int, default=3, help="B 臂重复次数（A 臂确定性恒 reps=1）")
    parser.add_argument("--samples", type=Path, default=_SAMPLES_PATH)
    parser.add_argument("--report", type=Path, default=_DEFAULT_REPORT)
    args = parser.parse_args()

    samples = load_samples(args.samples)
    registry = AgentTeamsCapabilityRegistry()

    record_sink: dict[str, str] | None = {} if (args.llm_record and args.llm_live) else None
    if args.llm_record and not args.llm_live:
        print("[忽略] --llm-record 仅配合 --llm-live 使用", file=sys.stderr)
    llm: Callable[[str, str, str], str] | None = None
    if args.llm_live:
        try:
            llm = make_live_llm(record_sink)
            llm_mode = "live"
        except RuntimeError as exc:
            print(f"[跳过 B 臂] {exc} → 标注待真实运行", file=sys.stderr)
            llm_mode = "live（缺凭证，待真实运行）"
    elif args.llm_replay:
        llm = make_replay_llm(args.llm_replay)
        llm_mode = f"replay({args.llm_replay})"
    elif args.llm_none:
        llm_mode = "none（仅 A 臂）"
    else:
        llm = make_stub_llm(registry)
        llm_mode = "stub"

    evals = evaluate(samples, registry=registry, llm=llm, reps=args.reps)
    summary = aggregate(evals)

    if record_sink:
        args.llm_record.parent.mkdir(parents=True, exist_ok=True)
        args.llm_record.write_text(
            json.dumps(record_sink, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    results_path = _EVIDENCE_DIR / f"run_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    results_payload = {
        "llm_mode": llm_mode,
        "reps": args.reps,
        "samples": [
            {
                "id": e.sample.id,
                "text": e.sample.text,
                "gold_experts": sorted(e.sample.gold_experts),
                "needs_clarification": e.sample.needs_clarification,
                "source": e.sample.source,
                "arm_a": e.arm_a and {
                    "predicted": sorted(e.arm_a.predicted),
                    "needs_clarification": e.arm_a.needs_clarification,
                    "latency_ms": e.arm_a.latency_ms,
                    "detail": e.arm_a.detail,
                },
                "arm_b_runs": [
                    {
                        "predicted": sorted(run.predicted),
                        "needs_clarification": run.needs_clarification,
                        "prompt_tokens": run.prompt_tokens,
                        "completion_tokens": run.completion_tokens,
                        "latency_ms": run.latency_ms,
                        "detail": run.detail,
                    }
                    for run in e.arm_b_runs
                ],
            }
            for e in evals
        ],
        "summary": summary,
    }
    results_path.write_text(
        json.dumps(results_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = render_report(evals, summary, llm_mode=llm_mode, reps=args.reps, results_path=results_path)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")

    a = summary["arm_a"]
    print(f"A 臂（路由圈选）: F1={a['f1']['mean']:.3f}±{a['f1']['std']:.3f} (n={a['n']}), prompt_tokens=0")
    if summary["arm_b"]:
        b = summary["arm_b"]
        print(
            f"B 臂（{llm_mode}）: F1={b['f1']['mean']:.3f}±{b['f1']['std']:.3f} (n={b['n']}), "
            f"prompt_tokens={b['prompt_tokens']['mean']:.0f}, "
            f"latency={b['latency_ms']['mean']:.1f}ms"
        )
    else:
        print(f"B 臂：{llm_mode}，待真实运行")
    print(f"报告: {args.report}")
    print(f"原始数据: {results_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
