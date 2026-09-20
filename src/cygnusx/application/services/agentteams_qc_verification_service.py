"""AgentTeams qc 结构化判决落库服务（F2 证据化验收）。

口径（docs/info/26.8.21/协作室融合ClaudeScience设计理念评估与实施方案.md F2）：
- qc 的每条 check 落一行 ``qc_verification_checks``——判决变成可统计的表行，
  qc 质量本身可测量（pass/warn/fail 分布、与后续返工率交叉验证）。
- schema 校验失败的显式降级也落一行 inconclusive（不静默吞），claim_snapshot
  记录降级原因，便于事后统计 qc 输出契约的遵守率。
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.qc_verification import (
    EXTERNAL_LOOKUP_CLAIM_TYPE,
    QcVerificationReport,
)
from cygnusx.infrastructure.database.models.chat import (
    CaseArtifactVersionModel,
    QcVerificationCheckModel,
)

_MAX_REVIEWER_AGENT_LEN = 80
# 血缘清单端点返回的最近判决行上限；counts 为全量聚合不受此限。
_QC_CHECKS_READ_LIMIT = 200


class AgentTeamsQcVerificationService:
    """qc_verification_checks 的写入面与用户态读取面。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record_checks(
        self,
        *,
        case_id: str,
        reviewer_agent: str,
        report: QcVerificationReport,
    ) -> list[QcVerificationCheckModel]:
        """校验通过的判决逐行落库；返回写入的行。"""
        rows: list[QcVerificationCheckModel] = []
        for check in report.checks:
            claim = report.claims[check.claim_index]
            row = QcVerificationCheckModel(
                case_id=case_id,
                claim_hash=claim.claim_hash,
                verdict=check.verdict,
                evidence_event_id=(check.evidence_event_id or "").strip() or None,
                reviewer_agent=reviewer_agent[:_MAX_REVIEWER_AGENT_LEN],
                claim_snapshot={
                    "statement": claim.statement,
                    "location": claim.location,
                    "claim_type": claim.claim_type,
                },
                reason=check.reason,
            )
            self._db.add(row)
            rows.append(row)
        if rows:
            await self._db.flush()
        return rows

    async def enforce_verifiable_evidence(
        self,
        *,
        case_id: str,
        report: QcVerificationReport,
    ) -> list[dict[str, Any]]:
        """证据指针验真：evidence_event_id 必须指向本 Case 已登记的审计事件/血缘 version。

        平台 DB 可查的合法指针集合 = ``case_artifact_versions`` 的 version_id
        ∪ producing_event_id（产物登记时写入的 Bridge 审计事件 id）。qc 编一个
        不存在的 id 从此处拦下，按既有"降级为 fail/inconclusive"惯例处理：
        - ``external_lookup`` 断言 → fail（伪造指针视同绕过编造引用条款）；
        - 其它类型且原判非 fail → inconclusive（证据不可复核，不按 pass/warn 放行）。
        返回降级明细供调用方留痕；本方法只改 report，不落库。
        """
        known_ids = await self._known_evidence_ids(case_id)
        downgrades: list[dict[str, Any]] = []
        for check in report.checks:
            evidence_id = (check.evidence_event_id or "").strip()
            if not evidence_id or evidence_id in known_ids:
                continue
            claim = report.claims[check.claim_index]
            original = check.verdict
            if original == "fail":
                continue
            check.verdict = (
                "fail" if claim.claim_type == EXTERNAL_LOOKUP_CLAIM_TYPE else "inconclusive"
            )
            check.reason = (
                f"证据指针验真失败：{evidence_id} 未指向本 Case 已登记的审计事件或血缘 "
                f"version（原判 {original}）。{check.reason}"
            )[:1_000]
            downgrades.append(
                {
                    "claim_index": check.claim_index,
                    "evidence_event_id": evidence_id,
                    "original_verdict": original,
                    "verdict": check.verdict,
                }
            )
        return downgrades

    async def _known_evidence_ids(self, case_id: str) -> set[str]:
        """本 Case 平台 DB 可验的合法证据指针集合（version_id ∪ producing_event_id）。"""
        result = await self._db.execute(
            select(
                CaseArtifactVersionModel.id,
                CaseArtifactVersionModel.producing_event_id,
            ).where(CaseArtifactVersionModel.case_id == case_id)
        )
        known: set[str] = set()
        for version_id, producing_event_id in result.all():
            if version_id is not None:
                known.add(str(version_id))
            event_id = str(producing_event_id or "").strip()
            if event_id:
                known.add(event_id)
        return known

    async def record_degradation(
        self,
        *,
        case_id: str,
        reviewer_agent: str,
        reason: str,
    ) -> QcVerificationCheckModel:
        """schema 缺失/校验失败的显式降级行：判 inconclusive，原因可查。"""
        row = QcVerificationCheckModel(
            case_id=case_id,
            claim_hash=hashlib.sha256(f"degraded\x00{reason}".encode("utf-8")).hexdigest(),
            verdict="inconclusive",
            evidence_event_id=None,
            reviewer_agent=reviewer_agent[:_MAX_REVIEWER_AGENT_LEN],
            claim_snapshot={
                "statement": "(qc 未输出可解析的结构化判决，平台降级为 inconclusive)",
                "location": "",
                "claim_type": "procedural",
            },
            reason=reason[:1_000],
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def case_verdicts(
        self, case_id: str, *, limit: int = _QC_CHECKS_READ_LIMIT
    ) -> dict[str, Any]:
        """Case 级判决分布（全量聚合）+ 最近判决行（created_at 倒序，上限 limit）。

        counts 始终含 pass/warn/fail 三键；inconclusive 等降级判决按原值并入。
        """
        count_rows = (
            await self._db.execute(
                select(QcVerificationCheckModel.verdict, func.count())
                .where(QcVerificationCheckModel.case_id == case_id)
                .group_by(QcVerificationCheckModel.verdict)
            )
        ).all()
        counts: dict[str, int] = {"pass": 0, "warn": 0, "fail": 0}
        for verdict, count in count_rows:
            counts[str(verdict)] = int(count)
        checks = (
            (
                await self._db.execute(
                    select(QcVerificationCheckModel)
                    .where(QcVerificationCheckModel.case_id == case_id)
                    .order_by(QcVerificationCheckModel.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return {
            "counts": counts,
            "checks": [
                {
                    "verdict": row.verdict,
                    "reason": row.reason,
                    "reviewer_agent": row.reviewer_agent,
                    "claim_hash": row.claim_hash,
                    "evidence_event_id": row.evidence_event_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in checks
            ],
        }


__all__ = ["AgentTeamsQcVerificationService"]
