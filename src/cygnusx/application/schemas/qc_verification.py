"""F2 证据化验收：agent-qc 结构化判决的权威 schema（claims + checks）。

口径（docs/info/26.8.21/协作室融合ClaudeScience设计理念评估与实施方案.md F2）：
- qc 输出从自由文本改为结构化 JSON：``claims[]``（从交付物抽取的可证伪断言：
  断言原文、位置、类型）+ ``checks[]``（每条 claim 的判决：pass/warn/fail/
  inconclusive + 证据指针 + 理由）。
- 平台侧解析并校验本 schema；校验失败的显式降级（判 inconclusive + 记录）由
  调用方（AgentConsultationService）负责，本模块只负责"合法/非法"的判定。
- 聚合决策写回既有硬门管线：fail>0→BLOCKED；inconclusive>0 且 fail=0→
  MANUAL_REVIEW（人工/甲方裁决路径）；warn>0→WARNING；否则 PASSED。
- 编造引用条款（rubric ③ 的唯一例外开口子）：``claim_type=external_lookup``
  （声称已检索/已计算的可核对标识符）且无证据指针（evidence_event_id）的
  check，一律强制 fail——真实检索必然留下可指向的审计事件或血缘 version_id，
  编造的才没有。
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QcVerdict = Literal["pass", "warn", "fail", "inconclusive"]

QC_VERDICTS = frozenset({"pass", "warn", "fail", "inconclusive"})

CLAIM_TYPES = frozenset(
    {"factual", "metric", "citation", "external_lookup", "computation", "procedural"}
)

#: rubric ③ 的适用类型：声称已检索/已计算的可核对标识符（如声称查了 ClinVar 给出频率）。
EXTERNAL_LOOKUP_CLAIM_TYPE = "external_lookup"

# 依据: 待测（经验初值）— 单份判决的 claim/check 上限，防上下文塞爆与库表膨胀；验证: 统计真实 qc 会诊 claims 数量分布
_MAX_CLAIMS = 50
_MAX_CHECKS = 100

# 总体决策严重度排序：BLOCKED 最严；MANUAL_REVIEW（有 inconclusive 需人工/甲方裁决）
# 严于 WARNING——不确定必须挡在人工复核处，不能与"可披露的告警"同级放行。
_DECISION_SEVERITY = {"PASSED": 0, "WARNING": 1, "MANUAL_REVIEW": 2, "BLOCKED": 3}


class QcClaim(BaseModel):
    """从交付物抽取的一条可证伪断言。"""

    statement: str = Field(min_length=1, max_length=1_000)
    location: str = Field(default="", max_length=512)
    claim_type: str = Field(default="factual", max_length=32)

    @field_validator("claim_type")
    @classmethod
    def _normalize_claim_type(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        # 未知类型宽松归一为 factual（不因此判 schema 失败）；只有
        # external_lookup 触发编造引用条款，类型拼错不会让编造漏网成 pass——
        # 因为归一后按普通事实断言走"找不到矛盾不定罪"，而不是被放行。
        return normalized if normalized in CLAIM_TYPES else "factual"

    @property
    def claim_hash(self) -> str:
        """断言内容指纹：同一份判决重复落库时可按 hash 去重/统计。"""
        material = f"{self.claim_type}\x00{self.location}\x00{self.statement}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


class QcCheck(BaseModel):
    """对一条 claim 的核查判决；evidence_event_id 指向审计事件或血缘 version_id。"""

    claim_index: int = Field(ge=0)
    verdict: QcVerdict
    evidence_event_id: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=1, max_length=1_000)


class QcVerificationReport(BaseModel):
    """agent-qc 一次会诊的完整结构化判决。"""

    claims: list[QcClaim] = Field(default_factory=list, max_length=_MAX_CLAIMS)
    checks: list[QcCheck] = Field(default_factory=list, max_length=_MAX_CHECKS)

    @model_validator(mode="after")
    def _check_indexes_in_range(self) -> QcVerificationReport:
        for check in self.checks:
            if check.claim_index >= len(self.claims):
                raise ValueError(
                    f"check.claim_index={check.claim_index} 超出 claims 范围（{len(self.claims)} 条）"
                )
        return self


def parse_qc_verification(raw: Any) -> QcVerificationReport:
    """解析 qc 输出的 verification 载荷；任何不合法都抛 ValueError（调用方显式降级）。"""
    if not isinstance(raw, dict):
        raise ValueError("verification 必须是对象（含 claims 与 checks）")
    try:
        return QcVerificationReport.model_validate(raw)
    except ValueError as exc:
        raise ValueError(f"verification schema 校验失败: {exc}") from exc


def enforce_fabrication_clause(report: QcVerificationReport) -> QcVerificationReport:
    """编造引用条款（rubric ③）：external_lookup 断言无证据指针一律定罪 fail。

    这是"找不到不定罪"原则的唯一例外，边界划清：只适用于"声称已检索/已计算的
    可核对标识符"，因为真实检索必然留下审计事件或血缘 version_id 可指。
    """
    for check in report.checks:
        claim = report.claims[check.claim_index]
        if claim.claim_type != EXTERNAL_LOOKUP_CLAIM_TYPE:
            continue
        if (check.evidence_event_id or "").strip():
            continue
        if check.verdict == "fail":
            continue
        original = check.verdict
        check.verdict = "fail"
        check.reason = (
            f"编造引用条款：external_lookup 断言未提供证据指针（原判 {original}）。{check.reason}"
        )[:1_000]
    return report


def aggregate_qc_decision(checks: list[QcCheck]) -> str:
    """由逐条判决聚合总体决策：fail>BLOCKED；inconclusive>MANUAL_REVIEW；warn>WARNING。"""
    verdicts = {check.verdict for check in checks}
    if "fail" in verdicts:
        return "BLOCKED"
    if "inconclusive" in verdicts:
        return "MANUAL_REVIEW"
    if "warn" in verdicts:
        return "WARNING"
    if checks:
        return "PASSED"
    # 无任何可统计判决等于没有核查发生，走人工裁决路径而不是默认放行。
    return "MANUAL_REVIEW"


def merge_gate_decision(existing: str, qc_decision: str) -> str:
    """结构化判决与既有指标硬门取较严者——指标门语义不动，qc 判决只能加严不能放水。"""
    existing = (existing or "").upper()
    qc_decision = (qc_decision or "").upper()
    if not existing:
        return qc_decision or "MANUAL_REVIEW"
    if not qc_decision:
        return existing
    if _DECISION_SEVERITY.get(qc_decision, 0) > _DECISION_SEVERITY.get(existing, 0):
        return qc_decision
    return existing


__all__ = [
    "CLAIM_TYPES",
    "EXTERNAL_LOOKUP_CLAIM_TYPE",
    "QC_VERDICTS",
    "QcCheck",
    "QcClaim",
    "QcVerificationReport",
    "QcVerdict",
    "aggregate_qc_decision",
    "enforce_fabrication_clause",
    "merge_gate_decision",
    "parse_qc_verification",
]
