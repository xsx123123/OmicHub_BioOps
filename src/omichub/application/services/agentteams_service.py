"""Authenticated user-facing adapter for the independently deployed AgentTeams Bridge."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeRuntimeConfig,
)
from omichub.application.services.agentteams_capability_registry import (
    get_agentteams_capability_registry,
)
from omichub.application.services.agentteams_intent_router import infer_intent_route
from omichub.application.services.agentteams_room_gateway_service import (
    AgentTeamsRoomGatewayService,
)
from omichub.application.services.agentteams_title import derive_agentteams_case_title
from omichub.core.config import Settings
from omichub.core.exceptions import AuthorizationError, BusinessError
from omichub.infrastructure.cache.redis_client import get_redis
from omichub.infrastructure.database.models.user import UserModel

# Bridge 侧预留的 Case 级证据 work_item_id（bridge record_evidence 对 manager 放行，
# 不要求存在同名 work item）；房间事件不属于任何具体工作项。
CASE_LEVEL_WORK_ITEM_ID = "case"

# 建房时邀请进 Matrix 房间的 Gateway 身份（均为 Gateway 默认 matrix_identities 成员）。
ROOM_MEMBER_IDENTITIES = ["bioops-manager", "omichub-user"]

# 平台用户动态 Matrix 身份前缀：Gateway 按同一前缀把 ``omichub-user-<slug>``
# 映射为 ``@omichub-user-<slug>:{matrix_server_name}``（bridge 侧同规则），
# 三个进程共用这一字符串，改动需同步。
MATRIX_USER_IDENTITY_PREFIX = "omichub-user-"

# 无 flow_id 的聊天式 Case 缺省规划者；意图路由命中时按流程分析师覆盖。
DEFAULT_LEAD_PLANNER = "agent-code"

# 聊天式创建的通用 Case 自动确认集合（Redis set）：API 创建时写入，
# beat 任务消费后移除；Bridge 无 meta 字段且不改 schema，故事实源放在平台侧。
AUTO_CONFIRM_CASES_KEY = "agentteams:auto_confirm_cases"

# Bridge 连接状态缓存：避免每次打开协作室页面都同步探测 Bridge /healthz。
# TTL 10 秒，既减少页面加载延迟，又能在 Bridge 故障时较快感知。
_CONNECTION_STATUS_CACHE_TTL_SECONDS = 10
_CONNECTION_STATUS_CACHE_KEY_PREFIX = "agentteams:connection_status"

_MATRIX_LOCALPART_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._=-")
_MATRIX_USER_SLUG_MAX = 48


def matrix_identity_for_requester(requester_ref: str) -> str:
    """平台用户 → Matrix 身份映射：``omichub-user-<sanitized user_id>``。

    清洗为 Matrix localpart 安全字符（小写字母数字与 ``._=-``），其余字符折为
    ``-``；清洗结果为空时回退共享 ``omichub-user`` 静态身份。
    """
    slug = "".join(
        ch if ch in _MATRIX_LOCALPART_ALLOWED else "-" for ch in requester_ref.strip().lower()
    )
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-.")[:_MATRIX_USER_SLUG_MAX].rstrip("-.")
    if not slug:
        return "omichub-user"
    return f"{MATRIX_USER_IDENTITY_PREFIX}{slug}"


class AgentTeamsService:
    """Uses the Bridge's manager identity internally; browser clients never receive it."""

    # 复用 httpx.AsyncClient 避免每次请求都重新建立 TCP/DNS 连接，显著降低首次 Bridge 调用延迟。
    # 缓存按事件循环隔离：Celery 任务用 asyncio.run() 每次新建 loop，跨 loop 复用客户端
    # 会抛 "Event loop is closed"（httpx 底层流绑定创建时的 loop），loop 变化时重建，
    # 与 infrastructure/cache/redis_client.get_redis 同一模式。
    _bridge_client_cache: dict[str, tuple[httpx.AsyncClient, asyncio.AbstractEventLoop]] = {}

    def __init__(
        self,
        settings: Settings,
        bridge_config: AgentTeamsBridgeRuntimeConfig | None = None,
    ) -> None:
        self._settings = settings
        self._bridge_config = bridge_config or AgentTeamsBridgeRuntimeConfig.from_settings(settings)

    @property
    def available(self) -> bool:
        return bool(self._bridge_config.enabled and self._bridge_config.configured)

    def _bridge_client(self) -> httpx.AsyncClient:
        cache_key = f"{self._bridge_config.bridge_url}:{self._bridge_config.timeout_seconds}"
        loop = asyncio.get_running_loop()
        cached = self._bridge_client_cache.get(cache_key)
        if cached is not None:
            client, client_loop = cached
            if client_loop is loop and not client.is_closed:
                return client
        client = httpx.AsyncClient(
            base_url=self._bridge_config.bridge_url.rstrip("/"),
            timeout=self._bridge_config.timeout_seconds,
        )
        self._bridge_client_cache[cache_key] = (client, loop)
        return client

    async def is_connected(self) -> bool:
        """Return whether the configured Bridge is reachable right now."""
        if not self.available:
            return False
        try:
            health = await self._request("/healthz")
        except BusinessError:
            return False
        return health.get("status") == "ok"

    def _connection_status_cache_key(self) -> str:
        url_hash = hashlib.sha256(self._bridge_config.bridge_url.encode()).hexdigest()[:16]
        return f"{_CONNECTION_STATUS_CACHE_KEY_PREFIX}:{url_hash}"

    async def connection_status(self) -> dict[str, bool | str | None]:
        """Expose configuration and liveness separately for the browser-facing status endpoint.

        对 Bridge 的实时健康探测结果做短期 Redis 缓存，避免协作室页面每次刷新都等待
        /healthz 往返；配置状态（enabled / configured）不做缓存，仍实时返回。
        """
        enabled = self._bridge_config.enabled
        configured = self._bridge_config.configured
        if not enabled or not configured:
            reason = "disabled" if not enabled else "incomplete_configuration"
            return {
                "available": False,
                "enabled": enabled,
                "configured": configured,
                "connected": False,
                "configuration_source": self._bridge_config.source,
                "reason": reason,
            }

        cache_key = self._connection_status_cache_key()
        try:
            redis = get_redis()
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AgentTeams connection status cache read failed: {}", exc)

        connected = await self.is_connected()
        reason = None if connected else "bridge_unreachable"
        result: dict[str, bool | str | None] = {
            "available": connected,
            "enabled": enabled,
            "configured": configured,
            "connected": connected,
            "configuration_source": self._bridge_config.source,
            "reason": reason,
        }
        try:
            redis = get_redis()
            await redis.setex(cache_key, _CONNECTION_STATUS_CACHE_TTL_SECONDS, json.dumps(result))
        except Exception as exc:  # noqa: BLE001
            logger.warning("AgentTeams connection status cache write failed: {}", exc)
        return result

    async def health_check(self) -> dict[str, Any]:
        """Validate Bridge reachability, the four OmicHub credentials, and Worker polls."""
        status = await self.connection_status()
        token_checks = {
            "bioops-manager": self._bridge_config.manager_token,
            "data-steward": self._bridge_config.data_steward_token,
            "approval-authority": self._bridge_config.approval_token,
            "workflow-operator": self._bridge_config.workflow_operator_token,
        }
        identities: list[dict[str, Any]] = []
        for identity, token in token_checks.items():
            valid = False
            if status["connected"] and token:
                try:
                    response = await self._request_as(identity, token, "/v1/health/identity")
                    valid = response.get("status") == "ok" and response.get("identity") == identity
                except BusinessError:
                    valid = False
            identities.append({"identity": identity, "valid": valid})

        bridge_health: dict[str, Any] = {}
        if status["connected"]:
            try:
                bridge_health = await self._request("/v1/health/workers")
            except BusinessError:
                bridge_health = {}
        workers = bridge_health.get("workers") if isinstance(bridge_health.get("workers"), list) else []
        workers = self._merge_worker_heartbeats(workers, self._worker_identity_aliases())
        allowed_flows = bridge_health.get("allowed_flows") if isinstance(bridge_health.get("allowed_flows"), list) else []
        return {
            "connection": status,
            "identities": identities,
            "workers": workers,
            "allowed_flows": allowed_flows,
            "scrna_submit_available": "scrna_seq" in allowed_flows,
        }

    @staticmethod
    def _worker_identity_aliases() -> dict[str, str]:
        """Map alias worker identities (data-steward 等) to their canonical role identity."""
        registry = get_agentteams_capability_registry()
        role_by_agent = {agent_id: role for role, agent_id in registry.role_agent_map().items()}
        return {
            alias: role_by_agent.get(agent_id, agent_id)
            for alias, agent_id in registry.role_alias_map().items()
        }

    @staticmethod
    def _merge_worker_heartbeats(
        workers: list[Any], aliases: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fold alias identities into the canonical role entry to avoid false missing-heartbeat reports."""
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for worker in workers:
            if not isinstance(worker, dict):
                continue
            identity = str(worker.get("identity") or "")
            canonical = aliases.get(identity, identity)
            entry = merged.get(canonical)
            if entry is None:
                merged[canonical] = {**worker, "identity": canonical}
                order.append(canonical)
                continue
            entry["configured"] = bool(entry.get("configured") or worker.get("configured"))
            entry["active"] = bool(entry.get("active") or worker.get("active"))
            age = worker.get("age_seconds")
            if age is not None and (entry.get("age_seconds") is None or age < entry["age_seconds"]):
                entry["age_seconds"] = age
                entry["last_seen_at"] = worker.get("last_seen_at")
        return [merged[identity] for identity in order]

    async def admin_resource_snapshot(self) -> dict[str, Any]:
        """Return the Bridge resources that an OmicHub administrator may operate."""
        health = await self.health_check()
        if not health["connection"].get("connected"):
            return {"health": health, "teams": [], "cases": [], "total_cases": 0}
        response = await self._request("/v1/cases", params={"limit": 100})
        case_items = response.get("items") if isinstance(response.get("items"), list) else []
        cases = [self._public_case(case) for case in case_items if isinstance(case, dict)]
        team_counts: dict[str, int] = {}
        for case in cases:
            team_id = str(case.get("team_id") or "unassigned")
            team_counts[team_id] = team_counts.get(team_id, 0) + 1
        return {
            "health": health,
            "teams": [
                {"team_id": team_id, "case_count": count}
                for team_id, count in sorted(team_counts.items())
            ],
            "cases": cases,
            "total_cases": int(response.get("total") or len(cases)),
        }

    async def admin_metrics(self) -> dict[str, int]:
        """Return the Bridge's event-derived AgentTeams operations metrics."""
        if not self.available:
            return {}
        return {
            str(key): int(value)
            for key, value in (await self._request("/v1/metrics")).items()
            if isinstance(value, int | float)
        }

    async def reconcile_case_as_admin(self, case_id: str) -> dict[str, Any]:
        return self._public_case(
            await self._request(f"/v1/cases/{case_id}/reconcile", method="POST")
        )

    async def admin_issue_worker_token(
        self, *, identity: str, ttl_seconds: int | None = None, note: str = ""
    ) -> dict[str, Any]:
        """Issue a revocable per-worker token on the Bridge; the raw value is returned once."""
        payload: dict[str, Any] = {"identity": identity, "note": note}
        if ttl_seconds is not None:
            payload["ttl_seconds"] = ttl_seconds
        return await self._request("/v1/worker-tokens", method="POST", json=payload)

    async def admin_list_worker_tokens(self) -> list[dict[str, Any]]:
        response = await self._request("/v1/worker-tokens")
        items = response.get("items")
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    async def admin_revoke_worker_token(self, token_id: str) -> dict[str, Any]:
        return await self._request(f"/v1/worker-tokens/{token_id}", method="DELETE")

    async def admin_list_cases_by_status(
        self, case_status: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """以 Bridge manager 身份按状态列 Case；仅供平台内部自动化（如自动确认）使用。"""
        response = await self._request(
            "/v1/cases", params={"status": case_status, "limit": limit}
        )
        items = response.get("items")
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    async def admin_get_case(self, case_id: str) -> dict[str, Any]:
        """以 Bridge manager 身份读取单个 Case；仅供平台内部自动化使用。"""
        return await self._request(f"/v1/cases/{case_id}")

    async def list_cases(
        self,
        requester_ref: str,
        *,
        case_status: str | None = None,
        project_id: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        params = {"requester_ref": requester_ref, "limit": limit}
        if case_status:
            params["status"] = case_status
        if project_id:
            params["project_id"] = project_id
        if cursor:
            params["cursor"] = cursor
        response = await self._request("/v1/cases", params=params)
        response["items"] = [self._public_case(case) for case in response.get("items", [])]
        return response

    async def create_case(
        self,
        *,
        case_id: str,
        project_id: str | None,
        context_refs: list[dict[str, str]] | None = None,
        intent: str,
        requester_ref: str,
        flow_id: str | None,
        sample_sheet: list[dict[str, Any]] | None = None,
        comparisons: list[dict[str, Any]] | None = None,
        origin_consultation_id: str | None = None,
        consultation_summary: str | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        case_payload: dict[str, Any] = {
            "case_id": case_id,
            "intent": intent,
            "requester_ref": requester_ref,
            "execution_mode": "cluster_case",
        }
        if project_id:
            case_payload["project_ref"] = {"kind": "project", "id": project_id}
        if context_refs:
            case_payload["context_refs"] = context_refs
        if flow_id:
            case_payload["flow_id"] = flow_id
        else:
            case_payload["lead_planner"] = self._resolve_chat_lead_planner(intent)
        if origin_consultation_id:
            case_payload["origin_consultation_id"] = origin_consultation_id
        if consultation_summary:
            case_payload["consultation_summary"] = consultation_summary
        case = await self._request(
            "/v1/cases",
            method="POST",
            json=case_payload,
        )
        if db is not None and await self._is_autonomous(db, requester_ref):
            try:
                redis = get_redis()
                await redis.sadd(AUTO_CONFIRM_CASES_KEY, case_id)
            except Exception as exc:  # noqa: BLE001
                logger.bind(case_id=case_id).warning(
                    "AgentTeams auto-confirm marking failed: {}", exc
                )
        return case

    @staticmethod
    def _resolve_chat_lead_planner(intent: str) -> str | None:
        """无 flow_id 的聊天式 Case 不再自动设置 lead_planner。

        早期实现会按意图关键词路由到对应分析流程的规划者，导致用户在协作房间
        里问一个纯咨询问题（如“介绍一下 Manager 能做什么”）时，代码助手立即跑
        planning_advice。现在聊天式 Case 默认只由房间内 Manager 响应链路处理；
        真实执行意图应通过确认执行/绑定 flow_id 等显式路径进入 planning。
        """
        logger.info(
            "AgentTeams 聊天 Case 不自动设置 lead_planner: intent={}",
            intent,
        )
        return None

    @staticmethod
    async def _user_agentteams_preferences(
        db: AsyncSession, requester_ref: str
    ) -> dict[str, Any]:
        """读取用户偏好中的 agentteams 配置段；读取失败返回空字典，避免阻断主流程。"""
        try:
            user_id = UUID(str(requester_ref))
        except (ValueError, TypeError, AttributeError):
            return {}
        try:
            result = await db.execute(
                select(UserModel.preferences).where(UserModel.id == user_id)
            )
            preferences = result.scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001
            logger.bind(requester_ref=requester_ref).warning(
                "AgentTeams user preferences lookup failed: {}", exc
            )
            return {}
        if not isinstance(preferences, dict):
            return {}
        agentteams = preferences.get("agentteams")
        return dict(agentteams) if isinstance(agentteams, dict) else {}

    @classmethod
    async def _is_autonomous(cls, db: AsyncSession, requester_ref: str) -> bool:
        """用户是否授予 AgentTeams 自主执行权限。"""
        preferences = await cls._user_agentteams_preferences(db, requester_ref)
        return preferences.get("autonomy") == "autonomous"

    async def auto_approve_case_if_autonomous(
        self,
        case_id: str,
        requester_ref: str,
        *,
        db: AsyncSession | None = None,
        task_name: str = "auto-approved",
    ) -> dict[str, Any]:
        """若用户为 autonomous 模式，自动批准并提交处于 approval_pending 的 Case。

        通用 Case（无 flow_id）直接调用 general-plans/execute；
        流程 Case 创建 submit work item 后调用 approved-submissions。
        成功后在 Case 上记录「已根据你的授权自动批准」审计事件。
        """
        if db is None:
            return {"status": "skipped_no_db", "case_id": case_id}
        if not await self._is_autonomous(db, requester_ref):
            return {"status": "skipped_not_autonomous", "case_id": case_id}
        case = await self._get_case_for_requester(case_id, requester_ref)
        status_value = str(case.get("status") or "")
        if status_value == "approved":
            return {"status": "idempotent_already_approved", "case_id": case_id}
        if status_value == "executing":
            return {"status": "idempotent_already_executing", "case_id": case_id}
        if status_value != "approval_pending":
            return {"status": "skipped_not_pending", "case_id": case_id, "case_status": status_value}
        result = await self.approve_and_submit_task(
            case_id=case_id,
            requester_ref=requester_ref,
            task_name=task_name,
        )
        await self.post_case_evidence(
            case_id,
            work_item_id=CASE_LEVEL_WORK_ITEM_ID,
            event_type="case.auto_approved",
            summary="已根据你的授权自动批准",
            payload={"reason": "user_autonomy_autonomous"},
        )
        return {"status": "auto_approved", "case_id": case_id, "result": result}

    async def approve_and_submit_task(
        self,
        *,
        case_id: str,
        requester_ref: str,
        task_name: str,
    ) -> dict[str, Any]:
        case = await self._get_case_for_requester(case_id, requester_ref)
        status_value = str(case.get("status") or "")
        if status_value == "approved":
            return {"status": "idempotent_already_approved", "case_id": case_id}
        if status_value == "executing":
            return {"status": "idempotent_already_executing", "case_id": case_id}
        if status_value != "approval_pending":
            raise BusinessError("当前协作 Case 尚未满足人工审批和提交条件")
        if not case.get("flow_id"):
            approval = await self._request_as(
                "approval-authority",
                self._bridge_config.approval_token,
                "/v1/approvals",
                method="POST",
                json={"case_id": case_id, "action": "execute_plan"},
            )
            return await self._request_as(
                "approval-authority",
                self._bridge_config.approval_token,
                "/v1/general-plans/execute",
                method="POST",
                json={"case_id": case_id, "approval_token": approval["token"]},
            )
        snapshot = case.get("preflight_input")
        if not isinstance(snapshot, dict):
            raise BusinessError("当前协作 Case 缺少已通过预检的输入快照")
        flow_id = snapshot.get("flow_id")
        sample_sheet = snapshot.get("sample_sheet")
        comparisons = snapshot.get("comparisons")
        if not isinstance(flow_id, str) or not isinstance(sample_sheet, list):
            raise BusinessError("当前协作 Case 的预检输入快照无效")
        prior_submissions = [
            item
            for item in case.get("work_items", [])
            if item.get("target") == "analysis-worker"
            and str(item.get("work_item_id") or "").startswith("submit-")
        ]
        version = len(prior_submissions) + 1
        work_item_id = f"submit-{version:02d}"
        previous_work_item_id = (
            str(prior_submissions[-1].get("work_item_id")) if prior_submissions else None
        )
        if not any(item.get("work_item_id") == work_item_id for item in case.get("work_items", [])):
            await self._request(
                f"/v1/cases/{case_id}/work-items",
                method="POST",
                json={
                    "work_item_id": work_item_id,
                    "parent_work_item_id": previous_work_item_id,
                    "target": "analysis-worker",
                    "objective": "执行已获人工批准且由 Bridge 固化的分析流程提交，并回写 OmicHub 任务证据。",
                    "skill_name": "workflow-submit",
                    "context_refs": [{"kind": "project", "id": case["project_ref"]["id"]}],
                    "read_only": False,
                    "approval_required": True,
                    "depends_on": [previous_work_item_id] if previous_work_item_id else [],
                },
            )
        approval = await self._request_as(
            "approval-authority",
            self._bridge_config.approval_token,
            "/v1/approvals",
            method="POST",
            json={
                "case_id": case_id,
                "work_item_id": work_item_id,
                "action": "submit_task",
                "flow_id": flow_id,
            },
        )
        frozen_task = case.get("proposed_submission")
        if not isinstance(frozen_task, dict):
            frozen_task = {
                "flow_id": flow_id,
                "name": task_name,
                "sample_sheet": sample_sheet,
                "comparisons": comparisons,
                "execution_mode": "cluster",
            }
        return await self._request_as(
            "approval-authority",
            self._bridge_config.approval_token,
            "/v1/approved-submissions",
            method="POST",
            json={
                "case_id": case_id,
                "work_item_id": work_item_id,
                "idempotency_key": f"{case_id}-submit-v{version}",
                "approval_token": approval["token"],
                "task": frozen_task,
            },
        )

    async def submit_quality_gate(
        self,
        *,
        case_id: str,
        requester_ref: str,
        task_id: str | None,
        decision: str,
        rule_version: str,
        summary: str,
        evidence_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        case = await self._get_case_for_requester(case_id, requester_ref)
        if not task_id:
            omic_task_ids = case.get("omic_task_ids") or []
            task_id = omic_task_ids[-1] if omic_task_ids else None
        if not task_id:
            raise BusinessError("当前协作 Case 没有可提交质量结论的任务")
        token_response = await self.admin_issue_worker_token(
            identity="quality-auditor",
            ttl_seconds=120,
            note="frontend quality gate submission",
        )
        token = str(token_response["token"])
        token_id = str((token_response.get("record") or {}).get("id", ""))
        try:
            return await self._request_as(
                "quality-auditor",
                token,
                f"/v1/tasks/{task_id}/quality-gate",
                method="POST",
                json={
                    "case_id": case_id,
                    "rule_version": rule_version,
                    "decision": decision,
                    "summary": summary,
                    "evidence_refs": evidence_refs,
                },
            )
        finally:
            if token_id:
                try:
                    await self.admin_revoke_worker_token(token_id)
                except BusinessError:
                    pass

    async def start_chat_planning(
        self,
        *,
        case_id: str,
        requester_ref: str,
        objective: str,
        context_refs: list[dict[str, str]],
    ) -> None:
        """聊天式 Case（无 flow_id）命中执行意图时启动 planning。

        先创建 read_only 的 plan-01 规划工作项，再把 Case 推进到 planning_running。
        顺序不可颠倒：Bridge 的 reconcile 会把没有 plan-01 的聊天 Case 从
        planning_running 退回 received（chat_case_skips_auto_planning）。
        失败仅记 warning，绝不影响房间回复主流程。
        """
        refs: list[dict[str, str]] = (
            list(context_refs) if context_refs else [{"kind": "workspace", "id": requester_ref}]
        )
        try:
            await self._request(
                f"/v1/cases/{case_id}/work-items",
                method="POST",
                json={
                    "work_item_id": "plan-01",
                    "target": "agent-code",
                    "objective": objective,
                    "skill_name": "planning_advice",
                    "context_refs": refs,
                    "read_only": True,
                },
            )
            await self._request(
                f"/v1/cases/{case_id}/state",
                method="POST",
                json={"status": "planning_running", "reason": "chat_execution_intent"},
            )
        except Exception as exc:  # noqa: BLE001 - 触发失败不得影响房间回复主流程
            logger.bind(case_id=case_id).warning(
                "AgentTeams chat planning start failed: {}", exc
            )

    async def get_case(self, case_id: str, requester_ref: str) -> dict[str, Any]:
        return self._public_case(await self._get_case_for_requester(case_id, requester_ref))

    async def reject_case(self, case_id: str, requester_ref: str, reason: str) -> dict[str, Any]:
        case = await self._get_case_for_requester(case_id, requester_ref)
        if case.get("status") != "approval_pending":
            raise BusinessError("当前 Case 不处于可拒绝的计划确认阶段")
        cancelled = await self._request(
            f"/v1/cases/{case_id}/cancel",
            method="POST",
            json={"reason": reason},
        )
        return self._public_case(cancelled)

    async def cancel_case(self, case_id: str, requester_ref: str, reason: str) -> dict[str, Any]:
        case = await self._get_case_for_requester(case_id, requester_ref)
        if case.get("status") in {"closed", "cancelled"}:
            raise BusinessError("当前 Case 已结束，无法再次取消")
        cancelled = await self._request(
            f"/v1/cases/{case_id}/cancel",
            method="POST",
            json={"reason": reason},
        )
        return self._public_case(cancelled)

    async def delete_case(self, case_id: str, requester_ref: str) -> dict[str, Any]:
        """删除协作 Case：先校验归属，Bridge 侧取消未结束的 Case 并移除记录与审计事件。"""
        await self._get_case_for_requester(case_id, requester_ref)
        return await self._request(f"/v1/cases/{case_id}", method="DELETE")

    async def revise_case_plan(
        self,
        case_id: str,
        requester_ref: str,
        *,
        expected_plan_hash: str,
        parameters: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        await self._get_case_for_requester(case_id, requester_ref)
        return await self._request(
            f"/v1/cases/{case_id}/plan/revise",
            method="POST",
            json={
                "expected_plan_hash": expected_plan_hash,
                "parameters": parameters,
                "reason": reason,
            },
        )

    async def get_manifest(self, case_id: str, requester_ref: str) -> dict[str, Any]:
        await self._get_case_for_requester(case_id, requester_ref)
        return await self._request(f"/v1/cases/{case_id}/manifest")

    async def refresh_case(self, case_id: str, requester_ref: str) -> dict[str, Any]:
        await self._get_case_for_requester(case_id, requester_ref)
        return self._public_case(
            await self._request(f"/v1/cases/{case_id}/reconcile", method="POST")
        )

    async def retry_case(self, case_id: str, requester_ref: str) -> dict[str, Any]:
        case = await self._get_case_for_requester(case_id, requester_ref)
        if case.get("status") != "execution_failed":
            raise BusinessError("当前 Case 不处于可重试的执行失败状态")
        snapshot = case.get("preflight_input")
        flow_id = snapshot.get("flow_id") if isinstance(snapshot, dict) else None
        if not isinstance(flow_id, str) or not flow_id:
            raise BusinessError("当前 Case 缺少可重试的冻结流程输入")
        approval = await self._request_as(
            "approval-authority",
            self._bridge_config.approval_token,
            "/v1/approvals",
            method="POST",
            json={"case_id": case_id, "action": "submit_task", "flow_id": flow_id},
        )
        return await self._request(
            f"/v1/cases/{case_id}/retry",
            method="POST",
            json={"approval_token": approval["token"]},
        )

    async def _get_case_for_requester(self, case_id: str, requester_ref: str) -> dict[str, Any]:
        case = await self._request(f"/v1/cases/{case_id}")
        if case.get("requester_ref") != requester_ref:
            raise BusinessError("无权查看该协作案例")
        return case

    @staticmethod
    def _public_case(case: dict[str, Any]) -> dict[str, Any]:
        public_case = dict(case)
        public_case.pop("preflight_input", None)
        public_case.pop("task_specs", None)
        public_case.pop("element_room_url", None)
        public_case["display_title"] = derive_agentteams_case_title(
            str(public_case.get("intent") or "")
        )
        return public_case

    async def get_case_events(
        self,
        case_id: str,
        requester_ref: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        await self._get_case_for_requester(case_id, requester_ref)
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request(f"/v1/cases/{case_id}/events", params=params)

    async def provision_case_room(
        self, case_id: str, *, requester_ref: str = ""
    ) -> dict[str, Any] | None:
        """Best-effort Matrix 房间供给；失败仅记录日志，Case 创建不受影响。

        房间标识通过 ``room.created`` Case 证据事件持久化（bridge 审计流即映射存储，
        bridge 侧房间镜像钩子凭它绑定 case_id → room_id）；同时在 Redis 登记
        case→room 绑定供 Matrix 反向同步消费。未启用 Gateway 或建房失败时返回
        None，前端降级为纯事件流模式。
        """
        gateway = AgentTeamsRoomGatewayService()
        if not gateway.available:
            return None
        # 平台用户按映射规则供给独立 Matrix 账号并邀请进房（共享 omichub-user 兜底）。
        identities = list(ROOM_MEMBER_IDENTITIES)
        requester_identity = matrix_identity_for_requester(requester_ref)
        if requester_identity not in identities:
            identities.append(requester_identity)
        try:
            await gateway.ensure_users(identities)
        except Exception:  # noqa: BLE001 - create_room 内部仍会 ensure，账号预热失败不阻断
            logger.warning("agentteams case {} matrix user pre-provision failed", case_id)
        try:
            room = await gateway.create_room(case_id, identities)
        except Exception as exc:  # noqa: BLE001 - 建房失败不得阻断 Case 创建
            logger.warning("agentteams case {} room provisioning failed: {}", case_id, exc)
            return None
        room_id = str(room.get("room_id") or "")
        if not room_id:
            logger.warning("agentteams case {} room provisioning returned no room_id", case_id)
            return None
        try:
            await self.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.created",
                summary="协作房间已创建",
                payload={
                    "provider": "matrix",
                    "room_id": room_id,
                    "room_url": room.get("element_room_url"),
                },
            )
        except BusinessError as exc:
            logger.warning("agentteams case {} room binding evidence failed: {}", case_id, exc)
        from omichub.application.services.agentteams_room_sync_service import (
            record_room_binding,
        )

        await record_room_binding(case_id, room_id, requester_ref)
        return room

    async def post_room_message(
        self,
        case_id: str,
        requester_ref: str,
        content: str,
        *,
        context_refs: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """记录一条用户房间发言（``room.user_message`` 审计事件）。

        无论 Matrix 房间是否存在都记录审计事件（无 Matrix 时房间页经事件流投影显示）；
        已建房时由 bridge 侧镜像钩子发进 Matrix 房间，发送失败不影响事件记录。
        ``context_refs`` 是房间 @ 引用的工作区文件（只读引用），随 payload 落审计。
        """
        case = await self._request(f"/v1/cases/{case_id}")
        if case.get("requester_ref") != requester_ref:
            raise AuthorizationError("无权操作该协作案例")
        payload: dict[str, Any] = {"actor": requester_ref, "content": content.strip()}
        if context_refs:
            payload["context_refs"] = context_refs
        return await self.post_case_evidence(
            case_id,
            work_item_id=CASE_LEVEL_WORK_ITEM_ID,
            event_type="room.user_message",
            summary=content.strip()[:80],
            payload=payload,
        )

    async def post_case_evidence(
        self,
        case_id: str,
        *,
        work_item_id: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an evidence event on a Case with the internal manager identity."""
        return await self._request(
            f"/v1/cases/{case_id}/evidence",
            method="POST",
            json={
                "work_item_id": work_item_id,
                "event_type": event_type,
                "summary": summary[:4_000] or event_type,
                "payload": payload or {},
            },
        )

    async def reconcile_approval_timeouts(self) -> dict[str, int]:
        return await self._request("/v1/maintenance/approval-timeouts", method="POST")

    async def stream_case_events(
        self,
        case_id: str,
        requester_ref: str,
        *,
        cursor: str | None = None,
        watch_seconds: int = 60,
    ) -> AsyncIterator[dict[str, Any]]:
        """Proxy the Bridge's native bounded event stream after ownership verification."""
        await self._get_case_for_requester(case_id, requester_ref)
        if not self.available:
            raise BusinessError("Agent 协作中心尚未接通")
        params: dict[str, Any] = {"watch_seconds": max(1, min(watch_seconds, 60))}
        if cursor:
            params["cursor"] = cursor
        headers = {
            "X-Bridge-Identity": "bioops-manager",
            "X-Bridge-Token": self._bridge_config.manager_token,
        }
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self._bridge_config.bridge_url.rstrip("/"),
                    timeout=self._bridge_config.timeout_seconds + watch_seconds,
                ) as client,
                client.stream(
                    "GET",
                    f"/v1/cases/{case_id}/events/stream",
                    params=params,
                    headers=headers,
                ) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        yield event
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise BusinessError("协作案例不存在") from exc
            raise BusinessError("Agent 协作中心暂时不可用") from exc
        except httpx.HTTPError as exc:
            raise BusinessError("Agent 协作中心暂时不可用") from exc

    async def _request(self, path: str, *, method: str = "GET", **kwargs: Any) -> dict[str, Any]:
        return await self._request_as(
            "bioops-manager",
            self._bridge_config.manager_token,
            path,
            method=method,
            **kwargs,
        )

    async def _request_as(
        self, identity: str, token: str, path: str, *, method: str = "GET", **kwargs: Any
    ) -> dict[str, Any]:
        if not self.available:
            raise BusinessError("Agent 协作中心尚未接通")
        headers = {
            "X-Bridge-Identity": identity,
            "X-Bridge-Token": token,
        }
        try:
            response = await self._bridge_client().request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise BusinessError("协作案例不存在") from exc
            raise BusinessError("Agent 协作中心暂时不可用") from exc
        except httpx.HTTPError as exc:
            raise BusinessError("Agent 协作中心暂时不可用") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise BusinessError("Agent 协作中心返回了无效数据")
        return payload
