"""把 AgentTeams Case 审计事件投影为超频房间消息。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlparse

from loguru import logger

from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
    get_agentteams_capability_registry,
)


class CaseRoomProjector:
    """纯函数式事件适配器；不持有 DB/Bridge 状态，便于单测与重放。"""

    def __init__(self, registry: AgentTeamsCapabilityRegistry | None = None) -> None:
        self._registry = registry or get_agentteams_capability_registry()

    def project(self, event: dict[str, Any], *, session_id: str, flow_id: str = "") -> list[dict[str, Any]]:
        event_type = str(event.get("event_type") or event.get("type") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        case_id = str(event.get("case_id") or payload.get("case_id") or "")
        event_id = str(event.get("event_id") or "")
        actor = str(event.get("actor") or payload.get("actor") or "bioops-manager")
        sender = self._sender(actor, flow_id=flow_id)
        message_id = f"case-room-{case_id}-{event_id}" if event_id else f"case-room-{case_id}-{event_type}"
        result: list[dict[str, Any]] = []

        speech_type = event_type
        if event_type == "case.state_changed" and payload.get("status") in {
            "remediation_pending",
            "delivery_ready",
        }:
            speech_type = str(payload["status"])
        speech = self._speech(speech_type, payload, sender, session_id, message_id, case_id)
        if speech:
            result.append(speech)
        if event_type.startswith("work_item."):
            task_status = {
                "work_item.assigned": "pending",
                "work_item.claimed": "running",
                "work_item.running": "running",
                "work_item.finished": "succeeded",
                "work_item.failed": "failed",
                "work_item.blocked": "failed",
                "work_item.lease_expired": "pending",
                "work_item.retry_requeued": "pending",
                "work_item.manual_retry": "pending",
                "work_item.timeout": "failed",
                "work_item.skipped": "skipped",
                "work_item.cancelled": "cancelled",
            }.get(event_type, "running")
            result.append(
                {
                    "type": "overdrive_progress",
                    "session_id": session_id,
                    "case_id": case_id,
                    "phase": "worker_running",
                    "label": self._work_item_label(event_type, sender),
                    "completed": 1 if task_status == "succeeded" else 0,
                    "total": 1,
                    "waveMode": "serial",
                    "tasks": [{
                        "taskId": str(payload.get("work_item_id") or event_id),
                        "agentId": sender["agent_id"],
                        "status": task_status,
                    }],
                }
            )
        elif event_type in {"skill.finished", "quality.decision"}:
            task_id = str(payload.get("work_item_id") or event_id)
            artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else []
            result.append(
                {
                    "type": "overdrive_progress",
                    "session_id": session_id,
                    "case_id": case_id,
                    "phase": "worker_finished" if event_type == "skill.finished" else "peer_reviewing",
                    "label": "Case 质控中" if event_type == "skill.finished" else "Case 质控已完成",
                    "completed": 1,
                    "total": 1,
                    "waveMode": "serial",
                    "tasks": [{"taskId": task_id, "agentId": sender["agent_id"], "status": "succeeded"}],
                    "artifacts": [
                        self._artifact_payload(case_id, item)
                        for item in artifacts
                        if isinstance(item, dict) and item.get("path")
                    ],
                }
            )
        elif event_type in {"approval.requested", "approval_pending"} or (
            event_type == "case.state_changed" and payload.get("status") == "approval_pending"
        ):
            result.append(
                {
                    "type": "overdrive_approval_request",
                    "session_id": session_id,
                    "case_id": case_id,
                    "approval": {
                        "approval_id": str(payload.get("approval_id") or event_id),
                        "tool_name": str(payload.get("action") or "submit_task"),
                        "arguments": payload,
                        "status": "pending",
                        "reason": str(payload.get("reason") or "AgentTeams Case 需要你的审批"),
                        "case_id": case_id,
                    },
                    "agentId": sender["agent_id"],
                }
            )
        elif event_type == "case.closed":
            result.append({"type": "mode_changed", "mode": "overdrive", "session_id": session_id, "enabled": False})
        if event_id:
            for index, projected in enumerate(result):
                projected["event_id"] = event_id
                projected["idempotency_key"] = f"{case_id}:{event_id}:{projected['type']}:{index}"
        return result

    @staticmethod
    def _artifact_payload(case_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
        path = str(artifact.get("path") or "")
        download_url = str(artifact.get("download_url") or "") or None
        preview_url = str(artifact.get("preview_url") or "") or None
        s3_uri = str(artifact.get("s3_uri") or "")
        if not download_url and s3_uri.startswith("s3://"):
            parsed = urlparse(s3_uri)
            object_path = parsed.path.lstrip("/")
            prefix = f"{case_id}/"
            if object_path.startswith(prefix):
                key = object_path[len(prefix) :]
                base = f"/api/v1/agent-teams/cases/{quote(case_id)}/artifacts/{quote(key, safe='/')}"
                download_url = f"{base}?download=true"
                if key.lower().endswith((".html", ".htm")):
                    preview_url = preview_url or base
        return {
            "path": path,
            "kind": str(artifact.get("kind") or "file"),
            "status": "ready",
            "source": "agentteams",
            "download_url": download_url,
            "preview_url": preview_url,
        }

    def _sender(self, actor: str, *, flow_id: str) -> dict[str, str]:
        if actor == "bioops-manager":
            return {"agent_id": "agent-general", "name": "Manager", "avatar": "✨", "color": "#4f8ef7", "role": "manager"}
        labels = self._registry.role_labels()
        sender = labels.get(actor)
        if sender is not None:
            return dict(sender)
        if actor == "workflow-operator":
            flow_agent = self._registry.agent_for_flow(flow_id)
            sender = next((item for item in labels.values() if item["agent_id"] == flow_agent), None)
            if sender is not None:
                return dict(sender)
        agent_id = self._registry.resolve_agent(actor)
        if agent_id is None:
            logger.warning("AgentTeams 未命中角色映射，降级为 agent-general: actor={}", actor)
        return {
            "agent_id": agent_id or "agent-general",
            "name": actor or "协作成员",
            "avatar": "💬",
            "color": "#64748b",
            "role": "worker",
        }

    @staticmethod
    def _speech(
        event_type: str,
        payload: dict[str, Any],
        sender: dict[str, str],
        session_id: str,
        message_id: str,
        case_id: str,
    ) -> dict[str, Any] | None:
        queue_reason = str(payload.get("queue_reason") or payload.get("reason") or "")
        queued_scope = "当前用户" if queue_reason == "requester_active_case_quota" else "当前项目"
        labels = {
            "case.created": (
                f"已创建协作 Case「{str(payload.get('intent') or '正式分析任务')[:80]}」，"
                + (
                    f"但{queued_scope}活跃 Case 已达上限，已自动进入队列。"
                    if queue_reason
                    else "开始分派团队工作。"
                )
            ),
            "case.queued": f"{queued_scope}活跃 Case 已达上限，本 Case 正在排队；释放容量后会自动继续。",
            "case.dequeued": "协作容量已经释放，本 Case 已离开队列并开始规划。",
            "case.handoff_proposed": (
                f"已识别领域 Flow「{str(payload.get('flow_id') or '')}」，"
                "正在由专项规划链路生成可确认的执行计划。"
            ),
            "case.handoff_started": (
                f"领域 Flow「{str(payload.get('flow_id') or '')}」已完成确认并真实启动，"
                "后续进度将按工作项持续回传。"
            ),
            "case.handoff_failed": (
                "专项 Flow 暂未交接："
                f"{str(payload.get('reason') or payload.get('summary') or '缺少可用 Worker 或凭证')[:240]}"
                "。可补齐凭证后重试，或改为方案咨询。"
            ),
            "flow.stage_unavailable": (
                f"Flow 阶段「{str(payload.get('stage') or '')}」当前不可用："
                f"{str(payload.get('reason') or '缺少可用 Worker')[:240]}"
            ),
            "planning.revised": (
                f"计划已更新为 v{str(payload.get('plan_version') or '?')}，"
                f"新短码 {str(payload.get('plan_hash') or '')[:8]}；旧版本立即失效，等待重新确认。"
            ),
            "work_item.assigned": str(payload.get("status_line") or "").strip()
            or f"我已领取工作项：{str(payload.get('objective') or payload.get('skill_name') or '开始处理')[:180]}。",
            "work_item.claimed": str(payload.get("status_line") or "").strip()
            or f"已认领工作项 {str(payload.get('work_item_id') or '')}，开始执行。",
            "work_item.running": str(payload.get("status_line") or "").strip()
            or f"工作项 {str(payload.get('work_item_id') or '')} 正在执行。",
            "omic_task.submitted": f"OmicHub 任务 {str(payload.get('omic_task_id') or '')} 已提交，正在等待执行资源。",
            "omic_task.progress": f"任务进度已更新：{str(payload.get('progress') or payload.get('summary') or '处理中')}。",
            "remediation_pending": "失败诊断已完成，修复工作项正在等待执行。",
            "delivery_ready": "质量门已通过，交付文件已经可以核验和下载。",
            "quality.hard_gate": f"硬规则门结论：{str(payload.get('decision') or 'MANUAL_REVIEW')}。{str(payload.get('reason') or '')}",
            "skill.finished": str(payload.get("summary") or "本阶段工作已完成，已提交结果供团队继续处理。"),
            "quality.decision": f"质控结论：{str(payload.get('decision') or '已完成审核')}。{str(payload.get('summary') or '')}",
            "approval.reminder": "Case 已等待审批超过 24 小时，请确认冻结计划；超过 7 天将自动取消。",
            "remediation.requested": f"质控已发起修复请求，由 {str(payload.get('target') or '协作角色')} 处理：{str(payload.get('objective') or '')}",
            "remediation.completed": "修复工作已完成，Case 已重新进入人工审批；批准后将生成新执行版本并再次质控。",
            "manager.review_ready": (
                f"Manager 已验收工作项 {str(payload.get('work_item_id') or '')}："
                f"{str(payload.get('decision') or 'accepted')}。"
                f"{str(payload.get('summary') or '结果可继续流转到下游。')[:300]}"
            ),
            "work_item.retry_scheduled": (
                f"工作项 {str(payload.get('work_item_id') or '')} 执行失败，"
                f"将在 {str(payload.get('delay_seconds') or 0)} 秒后自动重试。"
            ),
            "work_item.retry_exhausted": (
                f"工作项 {str(payload.get('work_item_id') or '')} 已耗尽自动重试次数；"
                "依赖它的下游工作项已跳过，请选择重试、跳过或终止 Case。"
            ),
            "work_item.lease_expired": (
                f"工作项 {str(payload.get('work_item_id') or '')} 的执行 Worker 心跳超时，"
                "任务已回收并将重新派发。"
            ),
            "work_item.retry_requeued": (
                f"工作项 {str(payload.get('work_item_id') or '')} 已到重试时间，"
                "已重新进入待派发队列。"
            ),
            "work_item.timeout": (
                f"工作项 {str(payload.get('work_item_id') or '')} 多次失联，"
                "重试预算已耗尽，判定超时终止。"
            ),
            "work_item.skipped": (
                f"工作项 {str(payload.get('work_item_id') or '')} 因上游 "
                f"{str(payload.get('cause_work_item_id') or '工作项')} 不可恢复而被跳过；"
                "如需继续，请人工重试上游或终止 Case。"
            ),
            "work_item.manual_retry": (
                f"工作项 {str(payload.get('work_item_id') or '')} 已手动重试，"
                "重新进入待派发队列。"
            ),
            "work_item.cancelled": (
                f"工作项 {str(payload.get('work_item_id') or '')} 已被手动终止。"
            ),
            "omic_task.failed": CaseRoomProjector._failure_message(payload),
            "case.execution_failed": CaseRoomProjector._failure_message(payload),
            "case.cancelled": (
                "Case 因等待审批超过 7 天已自动取消。"
                if payload.get("reason") == "approval_timeout_7d"
                else f"Case 已取消：{str(payload.get('reason') or '未提供原因')}"
            ),
            "case.closed": f"Case 已关闭，交付清单已生成：{str(payload.get('manifest_uri') or '')}".rstrip("："),
        }
        content = labels.get(event_type)
        if not content:
            return None
        return {
            "type": "room_speech",
            "content": content,
            "sender": sender,
            "round": 0,
            "session_id": session_id,
            "message_id": message_id,
            "case_id": case_id,
        }

    @staticmethod
    def _failure_message(payload: dict[str, Any]) -> str:
        excerpt = str(payload.get("error_excerpt") or "任务未返回可用错误摘要")[:500]
        recommendation = str(
            payload.get("recommendation")
            or "请检查失败日志与输入；确认后可点击重试，系统会复用冻结计划并生成新提交版本。"
        )[:300]
        return f"执行失败：{excerpt}\n建议：{recommendation}"

    @staticmethod
    def _work_item_label(event_type: str, sender: dict[str, str]) -> str:
        return {
            "work_item.assigned": f"{sender['name']} 已收到工作项",
            "work_item.claimed": f"{sender['name']} 已认领工作项",
            "work_item.running": f"{sender['name']} 正在执行工作项",
            "work_item.finished": f"{sender['name']} 已完成工作项",
            "work_item.failed": f"{sender['name']} 的工作项执行失败",
            "work_item.blocked": f"{sender['name']} 的工作项被阻断",
            "work_item.lease_expired": f"{sender['name']} 心跳超时，工作项已回收重派",
            "work_item.retry_requeued": f"{sender['name']} 的工作项已重新排队",
            "work_item.manual_retry": f"{sender['name']} 的工作项已手动重试",
            "work_item.timeout": f"{sender['name']} 的工作项超时终止",
            "work_item.skipped": f"{sender['name']} 的工作项被级联跳过",
            "work_item.cancelled": f"{sender['name']} 的工作项已终止",
        }.get(event_type, f"{sender['name']} 更新了工作项")


__all__ = ["CaseRoomProjector"]
