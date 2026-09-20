"""聊天入口创建 AgentTeams Case 的受控工具服务。"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeSettingsService,
)
from cygnusx.application.services.agentteams_capability_registry import (
    get_agentteams_capability_registry,
)
from cygnusx.application.services.agentteams_service import AgentTeamsService
from cygnusx.application.services.site_settings_service import SiteSettingsService
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError
from cygnusx.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel

_IDEMPOTENCY_WINDOW = timedelta(minutes=5)
_CONFIRMATION_WINDOW = timedelta(minutes=10)


def agentteams_next_actor(status: str) -> str:
    return {
        "queued": "协作资源队列",
        "received": "data-steward",
        "preflight_running": "data-steward",
        "preflight_blocked": "requester",
        "waiting_for_correction": "requester",
        "approval_pending": "approval-authority",
        "approved": "workflow-operator",
        "executing": "workflow-operator",
        "execution_failed": "workflow-operator",
        "quality_running": "quality-auditor",
        "quality_blocked": "workflow-operator",
        "remediation_pending": "workflow-operator",
        "delivery_ready": "requester",
    }.get(status, "协作团队")


class AgentTeamsCaseToolService:
    """创建并绑定聊天会话的 AgentTeams Case。"""

    async def run(
        self,
        *,
        objective: str,
        project_id: str,
        flow_id: str,
        sample_context_refs: list[dict[str, Any]] | None = None,
        origin_consultation_id: str | None = None,
        consultation_summary: str | None = None,
        context: ToolInvocationContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if context is None or not context.user_id or not context.session_id:
            raise BusinessError("协作 Case 工具需要受控的会话调用上下文")

        settings = get_settings()
        site_settings = SiteSettingsService(context.db)
        enabled = (
            settings.agentteams_chat_entry_enabled
            or await site_settings.is_agentteams_chat_entry_enabled()
        )
        if not enabled:
            raise BusinessError("聊天协作 Case 入口尚未启用")

        capability_registry = get_agentteams_capability_registry()
        allowed_flows = self._allowed_flows(settings.agentteams_chat_flow_whitelist)
        allowed_flows.update(capability_registry.allowed_flow_ids())
        if flow_id not in allowed_flows:
            raise BusinessError("该流程不在聊天协作 Case 白名单中")
        if capability_registry.agent_for_flow(flow_id) is None:
            raise BusinessError("该流程没有可用的 active Agent，无法创建协作 Case")

        session = await context.db.scalar(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == context.session_id,
                ChatSessionModel.user_id == context.user_id,
            )
        )
        if session is None:
            raise BusinessError("聊天会话不存在或无权创建协作 Case")
        if not self._session_owns_project(session.sandbox_meta, project_id):
            raise BusinessError("项目未绑定到当前受控会话，无法创建协作 Case")

        normalized_objective = " ".join(objective.split())[:500]
        if len(objective.strip()) > 500:
            raise BusinessError("协作目标不能超过 500 个字符")
        if not normalized_objective:
            raise BusinessError("协作目标不能为空")
        idempotency_key = self._idempotency_key(normalized_objective, project_id, flow_id)
        meta = dict(session.sandbox_meta or {})
        existing = self._get_recent_case(meta, idempotency_key)
        if existing is not None:
            return self._envelope(
                case_id=existing["case_id"],
                title=existing["title"],
                status=existing["status"],
                reused=True,
            )
        confirmation = await self._require_pending_confirmation(context, meta, idempotency_key)
        source = self._consultation_source(
            origin_consultation_id or confirmation.get("origin_consultation_id"),
            consultation_summary or confirmation.get("consultation_summary"),
        )

        runtime = await AgentTeamsBridgeSettingsService(context.db, settings).get_runtime_config()
        agentteams = AgentTeamsService(settings, runtime)
        if not agentteams.available:
            raise BusinessError("AgentTeams Bridge 未配置或未启用")

        safe_refs = self._safe_refs(sample_context_refs or [])
        case_id = f"chat-{uuid.uuid4().hex}"
        case = await agentteams.create_case(
            case_id=case_id,
            project_id=project_id,
            project_name=None,
            intent=normalized_objective,
            requester_ref=context.user_id,
            flow_id=flow_id,
            sample_sheet=[{"context_ref": item} for item in safe_refs]
            or [{"context_ref": {"kind": "project", "id": project_id}}],
            origin_consultation_id=source["origin_consultation_id"],
            consultation_summary=source["consultation_summary"],
            db=context.db,
        )
        status = str(case.get("status") or "received")
        title = normalized_objective[:80]
        self._bind_case(meta, idempotency_key, case_id, title, status)
        session.sandbox_meta = meta
        session.updated_at = datetime.now(UTC)
        await context.db.flush()
        await agentteams.provision_case_room(case_id, requester_ref=context.user_id)
        return self._envelope(case_id=case_id, title=title, status=status, reused=False)

    async def record_confirmation_request(
        self,
        *,
        objective: str,
        project_id: str,
        flow_id: str,
        origin_consultation_id: str | None = None,
        consultation_summary: str | None = None,
        context: ToolInvocationContext | None = None,
    ) -> dict[str, str]:
        """记录已展示的确认卡，禁止模型首次调用伪造 `_confirmed` 直接创建。"""
        if context is None or not context.user_id or not context.session_id:
            raise BusinessError("协作 Case 工具需要受控的会话调用上下文")
        session = await context.db.scalar(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == context.session_id,
                ChatSessionModel.user_id == context.user_id,
            )
        )
        if session is None:
            raise BusinessError("聊天会话不存在或无权创建协作 Case")
        normalized_objective = " ".join(objective.split())[:500]
        if not normalized_objective:
            raise BusinessError("协作目标不能为空")
        key = self._idempotency_key(normalized_objective, project_id, flow_id)
        source = self._consultation_source(origin_consultation_id, consultation_summary)
        meta = dict(session.sandbox_meta or {})
        confirmations = dict(meta.get("agentteams_case_confirmation") or {})
        confirmation = {
            "requested_at": datetime.now(UTC).isoformat(),
            "token": secrets.token_urlsafe(24),
            **source,
        }
        confirmations[key] = confirmation
        meta["agentteams_case_confirmation"] = confirmations
        session.sandbox_meta = meta
        session.updated_at = datetime.now(UTC)
        await context.db.flush()
        return {"key": key, "token": str(confirmation["token"])}

    @staticmethod
    def _session_owns_project(meta: dict[str, Any] | None, project_id: str) -> bool:
        metadata = meta or {}
        candidates: set[str] = set()
        for key in ("project_id", "project_ids", "owned_project_ids"):
            value = metadata.get(key)
            if isinstance(value, str):
                candidates.add(value)
            elif isinstance(value, list):
                candidates.update(str(item) for item in value if isinstance(item, (str, int)))
        project_ref = metadata.get("project_ref")
        if isinstance(project_ref, dict) and project_ref.get("kind") == "project":
            candidates.add(str(project_ref.get("id") or ""))
        return project_id in candidates

    @staticmethod
    def _idempotency_key(objective: str, project_id: str, flow_id: str) -> str:
        payload = f"{project_id}\n{flow_id}\n{objective}".encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _allowed_flows(raw: str) -> set[str]:
        return {item.strip() for item in raw.split(",") if item.strip()}

    @staticmethod
    def _safe_refs(refs: list[dict[str, Any]]) -> list[dict[str, str]]:
        safe: list[dict[str, str]] = []
        for item in refs:
            kind = str(item.get("kind") or "").strip()
            identifier = str(item.get("id") or "").strip()
            if not kind or not identifier:
                raise BusinessError("样本上下文引用必须包含 kind 和 id")
            safe.append({"kind": kind[:80], "id": identifier[:200]})
        return safe

    @staticmethod
    def _get_recent_case(meta: dict[str, Any], key: str) -> dict[str, str] | None:
        item = (meta.get("agentteams_case_idempotency") or {}).get(key)
        if not isinstance(item, dict):
            return None
        try:
            created_at = datetime.fromisoformat(str(item["created_at"]))
        except (KeyError, TypeError, ValueError):
            return None
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - created_at > _IDEMPOTENCY_WINDOW:
            return None
        if not all(
            isinstance(item.get(key_name), str) for key_name in ("case_id", "title", "status")
        ):
            return None
        return {key_name: str(item[key_name]) for key_name in ("case_id", "title", "status")}

    @staticmethod
    async def _require_pending_confirmation(
        context: ToolInvocationContext, meta: dict[str, Any], key: str
    ) -> dict[str, Any]:
        confirmation = (meta.get("agentteams_case_confirmation") or {}).get(key)
        if not isinstance(confirmation, dict):
            raise BusinessError("请先展示并由用户确认协作 Case 创建卡片")
        try:
            requested_at = datetime.fromisoformat(str(confirmation["requested_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise BusinessError("协作 Case 确认状态无效，请重新发起确认") from exc
        if requested_at.tzinfo is None:
            requested_at = requested_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - requested_at > _CONFIRMATION_WINDOW:
            raise BusinessError("协作 Case 确认已过期，请重新发起确认")
        user_confirmation = await context.db.scalar(
            select(ChatMessageModel)
            .where(
                ChatMessageModel.session_id == context.session_id,
                ChatMessageModel.role == "user",
                ChatMessageModel.created_at > requested_at,
            )
            .order_by(ChatMessageModel.created_at.desc())
            .limit(1)
        )
        if not AgentTeamsCaseToolService._is_explicit_confirmation_message(
            user_confirmation, key, confirmation
        ):
            raise BusinessError("请先由用户在确认卡上确认协作 Case 创建")
        return confirmation

    @staticmethod
    def _is_explicit_confirmation_message(
        message: Any, key: str, confirmation: dict[str, Any]
    ) -> bool:
        if message is None:
            return False
        metadata = getattr(message, "metadata_json", None)
        marker = (
            metadata.get("agentteams_case_confirmation") if isinstance(metadata, dict) else None
        )
        if isinstance(marker, dict):
            return (
                marker.get("key") == key
                and marker.get("token") == confirmation.get("token")
                and marker.get("confirmed") is True
            )
        return False

    @staticmethod
    def _consultation_source(
        origin_consultation_id: str | None, consultation_summary: str | None
    ) -> dict[str, str | None]:
        normalized_id = " ".join(str(origin_consultation_id or "").split())[:256] or None
        normalized_summary = " ".join(str(consultation_summary or "").split())[:1800] or None
        return {
            "origin_consultation_id": normalized_id,
            "consultation_summary": normalized_summary,
        }

    @staticmethod
    def _bind_case(meta: dict[str, Any], key: str, case_id: str, title: str, status: str) -> None:
        case_ids = [
            str(item) for item in meta.get("agentteams_case_ids", []) if isinstance(item, str)
        ]
        if case_id not in case_ids:
            case_ids.append(case_id)
        statuses = dict(meta.get("agentteams_case_status") or {})
        statuses[case_id] = status
        notified = dict(meta.get("agentteams_case_notified") or {})
        notified.setdefault(case_id, [])
        idempotency = dict(meta.get("agentteams_case_idempotency") or {})
        idempotency[key] = {
            "case_id": case_id,
            "title": title,
            "status": status,
            "created_at": datetime.now(UTC).isoformat(),
        }
        confirmations = dict(meta.get("agentteams_case_confirmation") or {})
        confirmations.pop(key, None)
        meta["agentteams_case_ids"] = case_ids
        meta["agentteams_case_status"] = statuses
        meta["agentteams_case_notified"] = notified
        meta["agentteams_case_idempotency"] = idempotency
        meta["agentteams_case_confirmation"] = confirmations
        meta["execution_mode"] = "cluster_case"
        meta["execution_routing"] = {
            "mode": "cluster_case",
            "case_id": case_id,
            "reason": "user_confirmed_agentteams_case",
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        meta["active_case_id"] = case_id

    @staticmethod
    def _envelope(*, case_id: str, title: str, status: str, reused: bool) -> dict[str, Any]:
        next_actor = agentteams_next_actor(status)
        summary = (
            f"{'复用已创建的' if reused else '已创建'}协作 Case：{title}（当前状态：{status}）。"
        )
        card = {
            "case_id": case_id,
            "title": title,
            "status": status,
            "next_actor": next_actor,
            "case_url": f"/agent-teams/cases/{case_id}",
        }
        return {
            "success": True,
            "llm_payload": {**card, "summary": summary},
            "ui_payload": {"case_card": card},
        }
