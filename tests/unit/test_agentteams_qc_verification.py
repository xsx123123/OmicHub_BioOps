"""F2 证据化验收：qc 结构化判决 schema / 聚合 / 落库 / 硬门合并的单测。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cygnusx.application.schemas.qc_verification import (
    QcVerificationReport,
    aggregate_qc_decision,
    enforce_fabrication_clause,
    merge_gate_decision,
    parse_qc_verification,
)
from cygnusx.application.services.agent_consultation_service import (
    AgentConsultationService,
    ConsultationEnvelope,
)
from cygnusx.application.services.agentteams_qc_verification_service import (
    AgentTeamsQcVerificationService,
)

_VALID_PAYLOAD = {
    "claims": [
        {
            "statement": "mapping_rate=0.95 满足阈值 0.70",
            "location": "delivery-01/qc_report.md 第 2 节",
            "claim_type": "metric",
        },
        {"statement": "结论与输入数据一致", "location": "", "claim_type": "factual"},
    ],
    "checks": [
        {
            "claim_index": 0,
            "verdict": "pass",
            "evidence_event_id": "evt-123",
            "reason": "已读取 task 摘要核对数值",
        },
        {"claim_index": 1, "verdict": "pass", "evidence_event_id": None, "reason": "逐项比对一致"},
    ],
}


def _report(payload: dict) -> QcVerificationReport:
    return parse_qc_verification(payload)


def test_parse_valid_report() -> None:
    report = _report(_VALID_PAYLOAD)
    assert len(report.claims) == 2
    assert len(report.checks) == 2
    assert report.claims[0].claim_type == "metric"
    assert len(report.claims[0].claim_hash) == 64


def test_parse_rejects_non_dict() -> None:
    with pytest.raises(ValueError, match="必须是对象"):
        parse_qc_verification(["claims"])
    with pytest.raises(ValueError):
        parse_qc_verification(None)


def test_parse_rejects_missing_required_fields() -> None:
    # check 缺 reason（min_length=1）
    with pytest.raises(ValueError, match="schema 校验失败"):
        parse_qc_verification(
            {
                "claims": [{"statement": "x"}],
                "checks": [{"claim_index": 0, "verdict": "pass"}],
            }
        )
    # verdict 非法
    with pytest.raises(ValueError, match="schema 校验失败"):
        parse_qc_verification(
            {
                "claims": [{"statement": "x"}],
                "checks": [{"claim_index": 0, "verdict": "maybe", "reason": "r"}],
            }
        )
    # claim_index 越界
    with pytest.raises(ValueError, match="超出 claims 范围"):
        parse_qc_verification(
            {
                "claims": [{"statement": "x"}],
                "checks": [{"claim_index": 3, "verdict": "pass", "reason": "r"}],
            }
        )


def test_unknown_claim_type_normalized_to_factual() -> None:
    report = _report(
        {
            "claims": [{"statement": "x", "claim_type": "External_Lookup"}],
            "checks": [],
        }
    )
    assert report.claims[0].claim_type == "external_lookup"
    report2 = _report({"claims": [{"statement": "x", "claim_type": "whatever"}], "checks": []})
    assert report2.claims[0].claim_type == "factual"


def test_aggregate_decision_rules() -> None:
    def check(verdict: str) -> dict:
        return {"claim_index": 0, "verdict": verdict, "reason": "r"}

    base_claim = {"statement": "x"}
    fail = _report({"claims": [base_claim], "checks": [check("fail")]})
    assert aggregate_qc_decision(fail.checks) == "BLOCKED"
    mixed = _report({"claims": [base_claim], "checks": [check("warn"), check("inconclusive")]})
    assert aggregate_qc_decision(mixed.checks) == "MANUAL_REVIEW"
    warn = _report({"claims": [base_claim], "checks": [check("warn"), check("pass")]})
    assert aggregate_qc_decision(warn.checks) == "WARNING"
    passed = _report({"claims": [base_claim], "checks": [check("pass")]})
    assert aggregate_qc_decision(passed.checks) == "PASSED"
    # 无判决 = 没有核查发生，走人工裁决而非默认放行
    assert aggregate_qc_decision([]) == "MANUAL_REVIEW"


def test_fabrication_clause_fails_external_lookup_without_evidence() -> None:
    """编造引用条款样本：声称查了 ClinVar 给出频率，但无证据指针 → fail。"""
    report = _report(
        {
            "claims": [
                {
                    "statement": "已查询 ClinVar，rs123456 频率为 0.003",
                    "location": "delivery-01/report.md 第 3 节",
                    "claim_type": "external_lookup",
                }
            ],
            "checks": [
                {
                    "claim_index": 0,
                    "verdict": "pass",
                    "evidence_event_id": None,
                    "reason": "内容看起来合理",
                }
            ],
        }
    )
    enforce_fabrication_clause(report)
    assert report.checks[0].verdict == "fail"
    assert "编造引用条款" in report.checks[0].reason
    assert aggregate_qc_decision(report.checks) == "BLOCKED"


def test_fabrication_clause_respects_evidence_and_other_types() -> None:
    # 有证据指针的 external_lookup：维持 qc 原判
    report = _report(
        {
            "claims": [{"statement": "查了 ClinVar", "claim_type": "external_lookup"}],
            "checks": [
                {
                    "claim_index": 0,
                    "verdict": "pass",
                    "evidence_event_id": "ver-abc",
                    "reason": "血缘 version 可复核",
                }
            ],
        }
    )
    enforce_fabrication_clause(report)
    assert report.checks[0].verdict == "pass"
    # 非 external_lookup 断言无证据指针：找不到矛盾不定罪，保持 pass
    report2 = _report(
        {
            "claims": [{"statement": "常规事实断言", "claim_type": "factual"}],
            "checks": [
                {"claim_index": 0, "verdict": "pass", "evidence_event_id": None, "reason": "无矛盾"}
            ],
        }
    )
    enforce_fabrication_clause(report2)
    assert report2.checks[0].verdict == "pass"


def test_merge_gate_decision_takes_stricter() -> None:
    assert merge_gate_decision("BLOCKED", "PASSED") == "BLOCKED"
    assert merge_gate_decision("PASSED", "BLOCKED") == "BLOCKED"
    assert merge_gate_decision("WARNING", "MANUAL_REVIEW") == "MANUAL_REVIEW"
    assert merge_gate_decision("", "WARNING") == "WARNING"
    assert merge_gate_decision("PASSED", "") == "PASSED"


def test_record_checks_persists_one_row_per_check() -> None:
    asyncio.run(_test_record_checks_persists_one_row_per_check())


async def _test_record_checks_persists_one_row_per_check() -> None:
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    service = AgentTeamsQcVerificationService(db)
    report = _report(_VALID_PAYLOAD)
    rows = await service.record_checks(case_id="case-1", reviewer_agent="agent-qc", report=report)
    assert len(rows) == 2
    assert db.add.call_count == 2
    db.flush.assert_awaited_once()
    first = rows[0]
    assert first.case_id == "case-1"
    assert first.reviewer_agent == "agent-qc"
    assert first.verdict == "pass"
    assert first.evidence_event_id == "evt-123"
    assert first.claim_hash == report.claims[0].claim_hash
    assert first.claim_snapshot["statement"] == report.claims[0].statement
    # 空证据指针归一为 None
    assert rows[1].evidence_event_id is None


def test_record_degradation_persists_inconclusive_row() -> None:
    asyncio.run(_test_record_degradation_persists_inconclusive_row())


async def _test_record_degradation_persists_inconclusive_row() -> None:
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    service = AgentTeamsQcVerificationService(db)
    row = await service.record_degradation(
        case_id="case-1", reviewer_agent="agent-qc", reason="qc 未输出 verification 结构化判决"
    )
    assert row.verdict == "inconclusive"
    assert row.evidence_event_id is None
    assert "降级" in row.claim_snapshot["statement"]
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


def _make_consultation_service(agentteams_service=None) -> AgentConsultationService:
    return AgentConsultationService(
        SimpleNamespace(add=Mock(), flush=AsyncMock()),
        agent_service=SimpleNamespace(),
        parallel_service=SimpleNamespace(),
        agentteams_service=agentteams_service,
    )


def test_apply_qc_verification_merges_fail_into_blocked_gate() -> None:
    asyncio.run(_test_apply_qc_verification_merges_fail_into_blocked_gate())


async def _test_apply_qc_verification_merges_fail_into_blocked_gate() -> None:
    agentteams = SimpleNamespace(
        available=True, post_case_evidence=AsyncMock(return_value={"event_id": "evt-1"})
    )
    service = _make_consultation_service(agentteams)
    envelope = ConsultationEnvelope(
        conclusion="PASSED\n质量良好",
        hard_gate={"decision": "PASSED", "checks": []},
        verification={
            "claims": [
                {
                    "statement": "已查询 ClinVar，rs123456 频率为 0.003",
                    "location": "delivery-01/report.md",
                    "claim_type": "external_lookup",
                }
            ],
            "checks": [
                {
                    "claim_index": 0,
                    "verdict": "pass",
                    "evidence_event_id": None,
                    "reason": "内容看起来合理",
                }
            ],
        },
    )
    await service._apply_qc_verification(
        envelope, case_id="case-1", agent_id="agent-qc",
        work_item_id="qc-01", causation_event_id="evt-0",
    )
    # 编造引用条款强制 fail → 聚合 BLOCKED → 首行对齐 BLOCKED（禁止静默修复/降级）
    assert envelope.hard_gate["decision"] == "BLOCKED"
    assert envelope.hard_gate["qc_verdict"]["decision"] == "BLOCKED"
    assert envelope.hard_gate["qc_verdict"]["fails"] == 1
    assert envelope.conclusion.splitlines()[0] == "BLOCKED"
    service._db.add.assert_called_once()
    event_types = [c.kwargs["event_type"] for c in agentteams.post_case_evidence.await_args_list]
    assert "consultation.verification_recorded" in event_types


def test_apply_qc_verification_inconclusive_leads_to_manual_review() -> None:
    asyncio.run(_test_apply_qc_verification_inconclusive_leads_to_manual_review())


async def _test_apply_qc_verification_inconclusive_leads_to_manual_review() -> None:
    service = _make_consultation_service()
    envelope = ConsultationEnvelope(
        conclusion="PASSED\n看起来没问题",
        verification={
            "claims": [{"statement": "引用了外部报告", "claim_type": "citation"}],
            "checks": [
                {
                    "claim_index": 0,
                    "verdict": "inconclusive",
                    "evidence_event_id": None,
                    "reason": "已尝试打开来源但 404",
                }
            ],
        },
    )
    await service._apply_qc_verification(
        envelope, case_id="case-1", agent_id="agent-qc",
        work_item_id=None, causation_event_id=None,
    )
    # fail=0 且 inconclusive>0 → MANUAL_REVIEW；三态首行契约对齐为 WARNING
    assert envelope.hard_gate["decision"] == "MANUAL_REVIEW"
    assert envelope.conclusion.splitlines()[0] == "WARNING"
    assert any("人工/甲方裁决" in risk for risk in envelope.risks)


def test_apply_qc_verification_missing_payload_degrades_explicitly() -> None:
    asyncio.run(_test_apply_qc_verification_missing_payload_degrades_explicitly())


async def _test_apply_qc_verification_missing_payload_degrades_explicitly() -> None:
    agentteams = SimpleNamespace(
        available=True, post_case_evidence=AsyncMock(return_value={"event_id": "evt-1"})
    )
    service = _make_consultation_service(agentteams)
    envelope = ConsultationEnvelope(conclusion="PASSED\n通过", verification=None)
    await service._apply_qc_verification(
        envelope, case_id="case-1", agent_id="agent-qc",
        work_item_id=None, causation_event_id=None,
    )
    # 显式降级：inconclusive 落库 + 审计事件 + MANUAL_REVIEW，不静默吞
    assert envelope.hard_gate["decision"] == "MANUAL_REVIEW"
    assert envelope.hard_gate["qc_verdict"]["degraded"] is True
    service._db.add.assert_called_once()
    row = service._db.add.call_args.args[0]
    assert row.verdict == "inconclusive"
    event_types = [c.kwargs["event_type"] for c in agentteams.post_case_evidence.await_args_list]
    assert "consultation.verification_degraded" in event_types


def test_apply_qc_verification_never_weakens_metric_gate() -> None:
    asyncio.run(_test_apply_qc_verification_never_weakens_metric_gate())


async def _test_apply_qc_verification_never_weakens_metric_gate() -> None:
    service = _make_consultation_service()
    envelope = ConsultationEnvelope(
        conclusion="BLOCKED\n指标不达标",
        hard_gate={"decision": "BLOCKED", "checks": [{"metric": "q30", "decision": "BLOCKED"}]},
        verification=_VALID_PAYLOAD,
    )
    await service._apply_qc_verification(
        envelope, case_id="case-1", agent_id="agent-qc",
        work_item_id=None, causation_event_id=None,
    )
    # qc 结构化判决全 pass 也不得把指标门 BLOCKED 降级
    assert envelope.hard_gate["decision"] == "BLOCKED"
    assert envelope.hard_gate["qc_verdict"]["decision"] == "PASSED"
    assert envelope.conclusion.splitlines()[0] == "BLOCKED"


def test_build_instruction_quality_gate_includes_verification_contract() -> None:
    instruction = AgentConsultationService._build_instruction(
        question="审查交付物",
        capability="quality-gate",
        evidence_refs=["task:123"],
        requested_tools=[],
        execution_mode="readonly_consultation",
        hard_gate=None,
    )
    assert '"verification"' in instruction
    assert "claims" in instruction and "checks" in instruction
    assert "external_lookup" in instruction
    # 非质量门会诊不附加该契约
    other = AgentConsultationService._build_instruction(
        question="解释结果",
        capability="result_interpretation",
        evidence_refs=[],
        requested_tools=[],
        execution_mode="readonly_consultation",
        hard_gate=None,
    )
    assert '"verification"' not in other


def _db_with_known_evidence(rows: list[tuple]) -> SimpleNamespace:
    """带 execute 的最小 db：_known_evidence_ids 查询返回给定的 (version_id, producing_event_id) 行。"""
    result = SimpleNamespace(all=lambda: list(rows))
    return SimpleNamespace(
        add=Mock(), flush=AsyncMock(), execute=AsyncMock(return_value=result)
    )


def test_enforce_verifiable_evidence_downgrades_fake_pointers() -> None:
    asyncio.run(_test_enforce_verifiable_evidence_downgrades())


async def _test_enforce_verifiable_evidence_downgrades() -> None:
    known_version_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    db = _db_with_known_evidence([(known_version_id, "evt-real")])
    service = AgentTeamsQcVerificationService(db)
    report = _report(
        {
            "claims": [
                {"statement": "已查询 ClinVar，rs123456 频率 0.003", "claim_type": "external_lookup"},
                {"statement": "常规事实断言", "claim_type": "factual"},
                {"statement": "指标达标", "claim_type": "metric"},
            ],
            "checks": [
                {
                    "claim_index": 0,
                    "verdict": "pass",
                    "evidence_event_id": "evt-fabricated",
                    "reason": "内容看起来合理",
                },
                {
                    "claim_index": 1,
                    "verdict": "pass",
                    "evidence_event_id": "evt-fabricated-2",
                    "reason": "无矛盾",
                },
                {
                    "claim_index": 2,
                    "verdict": "pass",
                    "evidence_event_id": known_version_id,
                    "reason": "血缘 version 可复核",
                },
            ],
        }
    )

    downgrades = await service.enforce_verifiable_evidence(case_id="case-1", report=report)

    assert len(downgrades) == 2
    # external_lookup 伪造指针 → fail（视同绕过编造引用条款）
    assert report.checks[0].verdict == "fail"
    assert "证据指针验真失败" in report.checks[0].reason
    assert "原判 pass" in report.checks[0].reason
    # 其它类型伪造指针 → inconclusive，不按 pass 放行
    assert report.checks[1].verdict == "inconclusive"
    # 指向真实 version_id 的指针维持原判
    assert report.checks[2].verdict == "pass"
    assert aggregate_qc_decision(report.checks) == "BLOCKED"


def test_enforce_verifiable_evidence_accepts_producing_event_id() -> None:
    asyncio.run(_test_enforce_verifiable_evidence_accepts())


async def _test_enforce_verifiable_evidence_accepts() -> None:
    db = _db_with_known_evidence([("ver-1", "evt-real")])
    service = AgentTeamsQcVerificationService(db)
    report = _report(
        {
            "claims": [{"statement": "指标达标", "claim_type": "metric"}],
            "checks": [
                {
                    "claim_index": 0,
                    "verdict": "pass",
                    "evidence_event_id": "evt-real",
                    "reason": "已读取审计事件核对",
                }
            ],
        }
    )

    downgrades = await service.enforce_verifiable_evidence(case_id="case-1", report=report)

    assert downgrades == []
    assert report.checks[0].verdict == "pass"


def test_apply_qc_verification_downgrades_fake_evidence_pointer() -> None:
    asyncio.run(_test_apply_qc_verification_fake_pointer())


async def _test_apply_qc_verification_fake_pointer() -> None:
    """端到端：qc 编造不存在的 evidence_event_id → 验真降级 fail → 聚合 BLOCKED 并留痕。"""
    agentteams = SimpleNamespace(
        available=True, post_case_evidence=AsyncMock(return_value={"event_id": "evt-1"})
    )
    db = _db_with_known_evidence([])  # 本 Case 无任何已登记指针
    service = AgentConsultationService(
        db,
        agent_service=SimpleNamespace(),
        parallel_service=SimpleNamespace(),
        agentteams_service=agentteams,
    )
    envelope = ConsultationEnvelope(
        conclusion="PASSED\n已核查",
        verification={
            "claims": [
                {"statement": "已查询 ClinVar，rs123456 频率 0.003", "claim_type": "external_lookup"}
            ],
            "checks": [
                {
                    "claim_index": 0,
                    "verdict": "pass",
                    "evidence_event_id": "evt-does-not-exist",
                    "reason": "内容看起来合理",
                }
            ],
        },
    )

    await service._apply_qc_verification(
        envelope, case_id="case-1", agent_id="agent-qc",
        work_item_id=None, causation_event_id=None,
    )

    assert envelope.hard_gate["decision"] == "BLOCKED"
    assert envelope.hard_gate["qc_verdict"]["evidence_downgrades"] == 1
    assert envelope.hard_gate["qc_verdict"]["evidence_verify_failed"] is False
    assert envelope.conclusion.splitlines()[0] == "BLOCKED"
    # 落库行携带降级后的 verdict 与验真失败原因（留痕）
    row = db.add.call_args.args[0]
    assert row.verdict == "fail"
    assert "证据指针验真失败" in row.reason
    assert row.evidence_event_id == "evt-does-not-exist"
    event_types = [c.kwargs["event_type"] for c in agentteams.post_case_evidence.await_args_list]
    assert "consultation.verification_recorded" in event_types
    recorded = next(
        c for c in agentteams.post_case_evidence.await_args_list
        if c.kwargs["event_type"] == "consultation.verification_recorded"
    )
    assert recorded.kwargs["payload"]["evidence_downgrade_details"]
