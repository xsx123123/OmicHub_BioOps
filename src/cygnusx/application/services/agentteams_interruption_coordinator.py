"""Coordinate safe, auditable change requests for running domain work."""

from __future__ import annotations

from typing import Any

from cygnusx.application.services.agent_consultation_service import AgentConsultationService
from cygnusx.application.services.agentteams_service import CASE_LEVEL_WORK_ITEM_ID, AgentTeamsService

_RUNNING_STATUSES = {"claimed", "running", "in_progress", "awaiting_approval", "planning_running"}


class AgentTeamsInterruptionCoordinator:
    """Phase 2 coordinator; records intent and assessment before execution changes."""

    def __init__(self, agentteams: AgentTeamsService, db: Any) -> None:
        self._agentteams = agentteams
        self._db = db

    async def request_assessment(
        self,
        *,
        case_id: str,
        requester_ref: str,
        agent_id: str,
        content: str,
        causation_event_id: str | None = None,
    ) -> dict[str, Any]:
        case = await self._agentteams.get_case(case_id, requester_ref)
        running_items = [
            item for item in case.get("work_items", [])
            if isinstance(item, dict)
            and item.get("target") == agent_id
            and str(item.get("status") or "").lower() in _RUNNING_STATUSES
        ]
        if not running_items:
            return {"status": "no_running_work", "work_item_ids": []}

        work_item_ids = [str(item.get("work_item_id")) for item in running_items]
        for item in running_items:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=str(item.get("work_item_id")),
                event_type="work_item.interruption_requested",
                summary="收到用户对运行中工作项的变更请求，等待安全点与评估",
                payload={
                    "work_item_id": item.get("work_item_id"),
                    "owner_agent_id": agent_id,
                    "requested_by": requester_ref,
                    "request_content": content[:4_000],
                    "stop_level": "queued",
                    "previous_status": item.get("status"),
                    "decision": "pending",
                },
            )

        question = (
            f"你是 {agent_id}，用户提出了变更请求：{content[:4_000]}\n"
            "请只做只读影响评估，不执行真实计算、不改写计划。\n"
            f"当前 Case：{str(case.get('intent') or '')[:500]}\n"
            f"受影响工作项：{work_item_ids}\n"
            "请说明受影响任务、可复用产物、预计影响、是否需要审批，并推荐："
            "resume、replan、branch 或 cancel。"
        )
        envelope = await AgentConsultationService(
            self._db,
            agentteams_service=self._agentteams,
        ).run_consultation(
            case_id=case_id,
            agent_id=agent_id,
            question=question,
            capability="interpretation",
            evidence_refs=[],
            requested_tools=[],
            requester_ref=requester_ref,
            causation_event_id=causation_event_id,
        )
        assessment = {
            "agent_id": agent_id,
            "work_item_ids": work_item_ids,
            "conclusion": envelope.conclusion,
            "recommendations": envelope.recommendations,
            "risks": envelope.risks,
            "evidence_refs": envelope.evidence_refs,
            "hard_gate": envelope.hard_gate,
            "proposed_submission": envelope.proposed_submission,
            "decision_options": ["resume", "replan", "branch", "cancel"],
            "decision": "pending_user_confirmation",
        }
        await self._agentteams.post_case_evidence(
            case_id,
            work_item_id=CASE_LEVEL_WORK_ITEM_ID,
            event_type="room.change_assessment",
            summary="领域 Agent 已完成变更影响评估，等待用户决策",
            payload=assessment,
        )
        return {"status": "assessment_ready", "work_item_ids": work_item_ids, "assessment": assessment}
