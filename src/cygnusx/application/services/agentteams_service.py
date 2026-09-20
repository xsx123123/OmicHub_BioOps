"""Authenticated user-facing adapter for the independently deployed AgentTeams Bridge."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import shutil
import tempfile
from collections.abc import AsyncIterator
from math import ceil
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.agentteams_artifact_lineage_service import (
    AgentTeamsArtifactLineageService,
)
from cygnusx.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeRuntimeConfig,
)
from cygnusx.application.services.agentteams_capability_registry import (
    get_agentteams_capability_registry,
)
from cygnusx.application.services.agentteams_context_refs import check_context_refs
from cygnusx.application.services.agentteams_execution_intent import (
    ExecutionIntent,
    classify_execution_intent,
)
from cygnusx.application.services.agentteams_intent_router import infer_intent_route
from cygnusx.application.services.agentteams_room_gateway_service import (
    AgentTeamsRoomGatewayService,
)
from cygnusx.application.services.agentteams_title import derive_agentteams_case_title
from cygnusx.application.services.file_service import ensure_directory_chain
from cygnusx.application.services.flow_registry import get_flow_registry
from cygnusx.application.services.project_service import ProjectService
from cygnusx.core.config import Settings
from cygnusx.core.exceptions import AuthorizationError, BusinessError
from cygnusx.domain.file.entities import DataFile
from cygnusx.domain.file.value_objects import FileType
from cygnusx.infrastructure.cache.redis_client import get_redis
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.repositories.file_repository import FileRepositoryImpl
from cygnusx.infrastructure.storage import get_path_factory
from cygnusx.infrastructure.storage.minio_store import MinioStore

# Bridge 侧预留的 Case 级证据 work_item_id（bridge record_evidence 对 manager 放行，
# 不要求存在同名 work item）；房间事件不属于任何具体工作项。
CASE_LEVEL_WORK_ITEM_ID = "case"

# 房间级事件流的 Bridge 内部命名空间前缀（会话-工单解耦 Part 2 方案 b）：
# 未立项房间的事件流挂在 ``room-<room_id>`` 命名空间记录下，与 Bridge 侧
# models.ROOM_NAMESPACE_ID_PREFIX 保持一致，改动需同步。
ROOM_NAMESPACE_ID_PREFIX = "room-"


def room_namespace_case_id(room_id: str) -> str:
    """协作室房间对应的 Bridge 房间命名空间记录 id。"""
    return f"{ROOM_NAMESPACE_ID_PREFIX}{room_id}"

# 建房时邀请进 Matrix 房间的 Gateway 身份（均为 Gateway 默认 matrix_identities 成员）。
ROOM_MEMBER_IDENTITIES = ["bioops-manager", "cygnusx-user"]

# 平台用户动态 Matrix 身份前缀：Gateway 按同一前缀把 ``cygnusx-user-<slug>``
# 映射为 ``@cygnusx-user-<slug>:{matrix_server_name}``（bridge 侧同规则），
# 三个进程共用这一字符串，改动需同步。
MATRIX_USER_IDENTITY_PREFIX = "cygnusx-user-"

# 无 flow_id 的聊天式 Case 缺省规划者；意图路由命中时按流程分析师覆盖。
DEFAULT_LEAD_PLANNER = "agent-code"

# 历史自动确认集合：仅供 beat 清理旧标记。新的真实计算不再写入该集合，
# 必须由用户在当前 Case 的人工审批卡上显式批准。
AUTO_CONFIRM_CASES_KEY = "agentteams:auto_confirm_cases"

# Bridge 连接状态缓存：避免每次打开协作室页面都同步探测 Bridge /healthz。
# TTL 10 秒，既减少页面加载延迟，又能在 Bridge 故障时较快感知。
_CONNECTION_STATUS_CACHE_TTL_SECONDS = 10
_CONNECTION_STATUS_CACHE_KEY_PREFIX = "agentteams:connection_status"
_BRIDGE_CASE_EVENTS_PAGE_LIMIT = 100
_BRIDGE_CASE_DELETE_TIMEOUT_SECONDS = 60

_MATRIX_LOCALPART_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._=-")
_MATRIX_USER_SLUG_MAX = 48


def matrix_identity_for_requester(requester_ref: str) -> str:
    """平台用户 → Matrix 身份映射：``cygnusx-user-<sanitized user_id>``。

    清洗为 Matrix localpart 安全字符（小写字母数字与 ``._=-``），其余字符折为
    ``-``；清洗结果为空时回退共享 ``cygnusx-user`` 静态身份。
    """
    slug = "".join(
        ch if ch in _MATRIX_LOCALPART_ALLOWED else "-" for ch in requester_ref.strip().lower()
    )
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-.")[:_MATRIX_USER_SLUG_MAX].rstrip("-.")
    if not slug:
        return "cygnusx-user"
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

    async def flow_capability_check(self, flow_id: str) -> dict[str, Any]:
        """Return truthful pre-handoff capability status for every Flow stage."""
        registry = get_flow_registry()
        registered = registry.flows.get(flow_id) or next(
            (item for item in registry.flows.values()
             if item.definition.flow.bridge_workflow == flow_id),
            None,
        )
        if registered is None:
            return {"flow_id": flow_id, "available": False, "reason": "Flow 未注册", "stages": []}
        health = await self._request("/v1/health/workers")
        raw_workers = health.get("workers") if isinstance(health, dict) else []
        workers = self._merge_worker_heartbeats(
            raw_workers if isinstance(raw_workers, list) else [],
            self._worker_identity_aliases(),
        )
        workers_by_identity = {
            str(item.get("identity")): item
            for item in workers
            if isinstance(item, dict) and item.get("identity")
        }
        stages = []
        for stage in registered.definition.stages:
            identity = stage.assistant_agent_id or registered.definition.flow.actor
            worker = workers_by_identity.get(identity, {})
            configured = bool(worker.get("configured"))
            online = bool(worker.get("active"))
            stages.append({
                "stage": stage.key,
                "agent_id": identity,
                "available": configured and online,
                "identity_configured": configured,
                "worker_online": online,
                "execution_mode": "flow",
                "reason": "" if configured and online else (
                    "Bridge 身份未配置" if not configured else "Worker 心跳离线"
                ),
            })
        return {
            "flow_id": registered.definition.flow.id,
            "available": all(item["available"] for item in stages),
            "stages": stages,
        }

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
        """Validate Bridge reachability, the four CygnusX credentials, and Worker polls."""
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
        room_gateway = await AgentTeamsRoomGatewayService().health_check()
        return {
            "connection": status,
            "identities": identities,
            "workers": workers,
            "allowed_flows": allowed_flows,
            "scrna_submit_available": "scrna_seq" in allowed_flows,
            "room_gateway": room_gateway,
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
        """Return the Bridge resources that an CygnusX administrator may operate."""
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
        project_name: str | None = None,
        context_refs: list[dict[str, Any]] | None = None,
        intent: str,
        requester_ref: str,
        flow_id: str | None,
        sample_sheet: list[dict[str, Any]] | None = None,
        comparisons: list[dict[str, Any]] | None = None,
        origin_consultation_id: str | None = None,
        consultation_summary: str | None = None,
        source_case_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        context_refs = await self._normalize_context_refs(
            list(context_refs or []), requester_ref=requester_ref, db=db
        )
        project_name, run_ref = await self._prepare_case_run(
            requester_ref=requester_ref,
            project_id=project_id,
            project_name=project_name,
            context_refs=context_refs,
            db=db,
        )
        if run_ref is not None:
            context_refs.append(run_ref)
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
        resolved_flow_id = flow_id or self._resolve_chat_flow_id(intent, context_refs)
        if resolved_flow_id:
            case_payload["flow_id"] = resolved_flow_id
        else:
            case_payload["lead_planner"] = self._resolve_chat_lead_planner(intent)
        if origin_consultation_id:
            case_payload["origin_consultation_id"] = origin_consultation_id
        if consultation_summary:
            case_payload["consultation_summary"] = consultation_summary
        if source_case_id:
            # 终态后"基于上一 Case 继续"的关联引用（Part 2.4），Bridge 原样落审计。
            case_payload["source_case_id"] = source_case_id
        case = await self._request(
            "/v1/cases",
            method="POST",
            json=case_payload,
        )
        if resolved_flow_id:
            await self._materialize_flow_stage_work_items(
                case_id=case_id,
                flow_id=resolved_flow_id,
                context_refs=context_refs or [],
            )
            if str(case.get("flow_id") or "") == resolved_flow_id:
                await self._record_flow_capability_failure(
                    case_id=case_id,
                    flow_id=resolved_flow_id,
                )
        return case

    async def _normalize_context_refs(
        self,
        refs: list[dict[str, Any]],
        *,
        requester_ref: str,
        db: AsyncSession | None,
    ) -> list[dict[str, Any]]:
        """Prefer protocol paths while retaining UUID refs for legacy audit compatibility."""
        if db is None:
            return refs
        try:
            user_uuid = UUID(requester_ref)
        except ValueError:
            return refs
        factory = get_path_factory()
        files = FileRepositoryImpl(db)
        normalized: list[dict[str, Any]] = []
        for ref in refs:
            item = dict(ref)
            if item.get("kind") in {"file", "workspace"}:
                candidate = str(item.get("location") or item.get("id") or "").strip()
                try:
                    file_uuid = UUID(str(item.get("id")))
                except (TypeError, ValueError):
                    file_uuid = None
                if file_uuid is not None and not candidate.startswith(("projects/", "inbox/")):
                    file_record = await files.get_by_id(user_uuid, file_uuid)
                    if file_record is not None:
                        try:
                            storage_path = Path(file_record.storage_path)
                            if not storage_path.is_absolute():
                                storage_path = factory.data_root / storage_path
                            storage_path = storage_path.resolve()
                            location = storage_path.relative_to(
                                factory.user_root(requester_ref).resolve()
                            ).as_posix()
                            if location.startswith(("projects/", "inbox/")):
                                item["location"] = location
                                item.setdefault("meta", {})["legacy_file_id"] = str(file_uuid)
                        except ValueError:
                            pass
            normalized.append(item)
        return normalized

    async def _prepare_case_run(
        self,
        *,
        requester_ref: str,
        project_id: str | None,
        project_name: str | None,
        context_refs: list[dict[str, Any]],
        db: AsyncSession | None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Create and register the user-visible run directory for a new Case."""
        if db is None or not project_id:
            return project_name, None
        try:
            user_uuid = UUID(requester_ref)
        except ValueError:
            return project_name, None
        project = await ProjectService(db).get_project(user_uuid, UUID(project_id))
        resolved_name = project_name or str(project["name"])
        factory = get_path_factory()
        run_dir = factory.create_project_run_dir(
            requester_ref, resolved_name, analysis_name="agentteams-case"
        )
        relative_run = run_dir.relative_to(factory.user_root(requester_ref)).as_posix()
        await ensure_directory_chain(db, user_uuid, relative_run)
        return resolved_name, {
            "kind": "project",
            "id": project_id,
            "location": relative_run,
            "meta": {"project_name": resolved_name, "run_path": relative_run},
        }

    async def _record_flow_capability_failure(self, *, case_id: str, flow_id: str) -> None:
        """Persist a truthful handoff failure before Manager describes execution."""
        try:
            capability = await self.flow_capability_check(flow_id)
        except Exception as exc:  # noqa: BLE001 - capability failure must be visible, not fatal
            logger.bind(case_id=case_id, flow_id=flow_id).warning(
                "AgentTeams Flow capability check failed: {}", exc
            )
            capability = {
                "flow_id": flow_id,
                "available": False,
                "reason": "能力检查暂不可用，当前不能确认专项 Worker 状态",
                "stages": [],
            }
        if capability.get("available"):
            return
        stage_reasons = [
            f"{item.get('agent_id')}: {item.get('reason')}"
            for item in capability.get("stages", [])
            if isinstance(item, dict) and item.get("reason")
        ]
        reason = "；".join(stage_reasons) or str(
            capability.get("reason") or "专项 Worker 当前不可用"
        )
        try:
            await self.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="case.handoff_failed",
                summary=f"Flow {flow_id} 暂未交接：{reason}"[:200],
                payload={
                    "flow_id": flow_id,
                    "reason": reason,
                    "capability": capability,
                },
            )
        except Exception as exc:  # noqa: BLE001 - evidence failure must not fail Case creation
            logger.bind(case_id=case_id, flow_id=flow_id).warning(
                "AgentTeams Flow capability failure evidence failed: {}", exc
            )

    async def _materialize_flow_stage_work_items(
        self,
        *,
        case_id: str,
        flow_id: str,
        context_refs: list[dict[str, str]],
    ) -> None:
        """把 Flow YAML 阶段投影为可查询的 Case Work Item DAG。"""
        registry = get_flow_registry()
        registered = registry.flows.get(flow_id) or next(
            (
                item
                for item in registry.flows.values()
                if item.definition.flow.bridge_workflow == flow_id
            ),
            None,
        )
        if registered is None:
            return
        previous_id: str | None = None
        for stage in registered.definition.stages:
            work_item_id = f"stage-{stage.key}"
            target = stage.assistant_agent_id or registered.definition.flow.actor
            payload = {
                "work_item_id": work_item_id,
                "parent_work_item_id": previous_id,
                "target": target,
                "objective": stage.title,
                "skill_name": stage.key,
                "context_refs": [*context_refs, {"kind": "flow_stage", "id": stage.key}],
                "declared_inputs": context_refs,
                "declared_outputs": [{"kind": "flow", "id": stage.key}],
                "read_only": True,
                "depends_on": [previous_id] if previous_id else [],
            }
            try:
                await self._request(
                    f"/v1/cases/{case_id}/work-items",
                    method="POST",
                    json=payload,
                )
            except Exception as exc:  # noqa: BLE001 - expose unavailable stage, preserve Case
                logger.bind(case_id=case_id, flow_id=flow_id, stage=stage.key).warning(
                    "AgentTeams Flow stage work item unavailable: {}", exc
                )
                with contextlib.suppress(Exception):
                    await self.post_case_evidence(
                        case_id,
                        work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                        event_type="flow.stage_unavailable",
                        summary=f"Flow 阶段 {stage.key} 暂不可用",
                        payload={"flow_id": flow_id, "stage": stage.key, "target": target, "reason": str(exc)[:500]},
                    )
                continue
            previous_id = work_item_id

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
    def _resolve_chat_flow_id(
        intent: str,
        context_refs: list[dict[str, str]] | None,
    ) -> str | None:
        """仅让带明确输入的正式领域请求在创建时绑定既有 Flow。

        ``workspace`` 是聊天 Case 的只读默认引用，``project`` 是建 Case 时自动注入的
        运行目录，二者都不是用户提供的数据，不能单独视为执行对象；否则"如何进行"
        一类尚无数据的请求会在澄清完成前就误绑流程、向领域 Agent 派出 plan-01。
        真正上传的文件/产物引用，或文本内明确的 FASTQ、Cell Ranger、STARsolo 等
        产物才允许走 Flow。
        """
        execution_refs = [
            ref
            for ref in context_refs or []
            if str(ref.get("kind") or "").strip().lower() not in {"workspace", "project"}
        ]
        if classify_execution_intent(intent, execution_refs) is not ExecutionIntent.EXECUTE:
            return None
        try:
            route = infer_intent_route(intent)
        except Exception as exc:  # noqa: BLE001 - routing failure must preserve generic chat Case
            logger.bind(intent=intent[:160]).warning(
                "AgentTeams chat Case flow routing failed: {}", exc
            )
            return None
        if route is None:
            return None
        logger.bind(flow_id=route.flow_id, lead_planner=route.lead_planner).info(
            "AgentTeams chat Case bound to inferred domain Flow"
        )
        return route.flow_id

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
        """保留旧巡检入口，但真实计算始终要求当前用户显式人工审批。"""
        if db is None:
            return {"status": "skipped_no_db", "case_id": case_id}
        return {
            "status": "skipped_manual_approval_required",
            "case_id": case_id,
            "reason": "真实计算必须由用户在当前 Case 中显式批准",
        }

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
                    "objective": "执行已获人工批准且由 Bridge 固化的分析流程提交，并回写 CygnusX 任务证据。",
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
                with contextlib.suppress(BusinessError):
                    await self.admin_revoke_worker_token(token_id)

    async def start_chat_planning(
        self,
        *,
        case_id: str,
        requester_ref: str,
        objective: str,
        context_refs: list[dict[str, str]],
        target_agent_id: str | None = None,
    ) -> None:
        """聊天式 Case（无 flow_id）命中执行意图时启动 planning。

        先创建 read_only 的 plan-01 规划工作项，再把 Case 推进到 planning_running。
        Bridge reconcile 不会为无 flow_id 的聊天 Case 自动创建 planning 工作项，
        也不会在重复 reconcile 时回退或重复产生 skip 审计事件。
        失败仅记 warning，绝不影响房间回复主流程。
        """
        refs: list[dict[str, str]] = (
            list(context_refs) if context_refs else [{"kind": "workspace", "id": requester_ref}]
        )
        if context_refs:
            workspace_root = get_path_factory().user_root(requester_ref).resolve()
            checks = check_context_refs(
                refs, workspace_root=workspace_root if workspace_root.exists() else None
            )
            unreadable = [item for item in checks if not item.readable]
            if unreadable:
                details = [
                    {"ref": item.ref, "category": item.category, "reason": item.reason}
                    for item in unreadable
                ]
                try:
                    await self.post_case_evidence(
                        case_id,
                        work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                        event_type="work_item.blocked",
                        summary="执行计划已阻断：存在不可读的上下文引用",
                        payload={"reason": "unreadable_context_refs", "references": details},
                    )
                except Exception as exc:  # noqa: BLE001 - blocking evidence is best effort
                    logger.bind(case_id=case_id).warning(
                        "AgentTeams unreadable context evidence failed: {}", exc
                    )
                return
        target = target_agent_id
        if not target:
            try:
                route = infer_intent_route(objective)
                target = route.lead_planner if route else None
            except Exception as exc:  # noqa: BLE001
                logger.bind(case_id=case_id).warning(
                    "AgentTeams chat planning target routing failed: {}", exc
                )
        if not target:
            # P0-1：二次路由仍无命中时兜底 planner 必须可审计、不得静默生效。
            # 房间响应回路已在派发前用领域澄清卡/Manager 会诊拦截无命中请求，
            # 正常路径不会走到这里；走到即视为异常并显式告警。
            logger.bind(case_id=case_id).warning(
                "AgentTeams chat planning target unresolved, audited fallback to {}",
                DEFAULT_LEAD_PLANNER,
            )
        target = target or DEFAULT_LEAD_PLANNER
        try:
            await self._request(
                f"/v1/cases/{case_id}/work-items",
                method="POST",
                json={
                    "work_item_id": "plan-01",
                    "target": target,
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
        return await self._request(
            f"/v1/cases/{case_id}",
            method="DELETE",
            timeout=_BRIDGE_CASE_DELETE_TIMEOUT_SECONDS,
        )

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
        return await self.get_manifest_with_delivery(case_id, requester_ref)

    async def get_manifest_with_delivery(
        self,
        case_id: str,
        requester_ref: str,
        *,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        case = await self._get_case_for_requester(case_id, requester_ref)
        manifest = await self._request(f"/v1/cases/{case_id}/manifest")
        if db is not None:
            await self._materialize_case_delivery(
                case=case,
                manifest=manifest,
                requester_ref=requester_ref,
                db=db,
            )
        return manifest

    async def materialize_case_delivery(
        self,
        case_id: str,
        requester_ref: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """供交付门等内部路径调用：物化交付产物并返回本地落点与 checksum 比对结果。

        与 ``get_manifest_with_delivery`` 共用同一物化实现；返回的本地文件清单
        仅供平台内部（如交付门）使用，不并入 manifest、不向 API 响应暴露。
        """
        case = await self._get_case_for_requester(case_id, requester_ref)
        manifest = await self._request(f"/v1/cases/{case_id}/manifest")
        return await self._materialize_case_delivery(
            case=case,
            manifest=manifest,
            requester_ref=requester_ref,
            db=db,
        )

    async def _materialize_case_delivery(
        self,
        *,
        case: dict[str, Any],
        manifest: dict[str, Any],
        requester_ref: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Project Bridge delivery metadata into the Case's protocol run output directory."""
        empty: dict[str, Any] = {"output_dir": "", "files": [], "checksum_verification": []}
        run_path = ""
        for ref in case.get("context_refs") or []:
            if not isinstance(ref, dict) or ref.get("kind") != "project":
                continue
            meta = ref.get("meta") if isinstance(ref.get("meta"), dict) else {}
            run_path = str(meta.get("run_path") or ref.get("location") or "")
            if "/runs/" in run_path:
                break
        if not run_path or not run_path.startswith("projects/") or "/runs/" not in run_path:
            return empty
        try:
            user_uuid = UUID(requester_ref)
        except ValueError:
            return empty
        factory = get_path_factory()
        output_rel = f"{run_path}/output"
        output_dir = (factory.user_root(requester_ref) / output_rel.removeprefix(""))
        output_dir.mkdir(parents=True, exist_ok=True)
        await ensure_directory_chain(db, user_uuid, output_rel)
        output_refs = case.get("output_refs") or (manifest.get("case") or {}).get("output_refs") or []
        minio = MinioStore(self._settings, probe=False)
        for raw_ref in output_refs:
            if not isinstance(raw_ref, dict):
                continue
            location = str(raw_ref.get("location") or raw_ref.get("id") or "").strip()
            meta = raw_ref.get("meta") if isinstance(raw_ref.get("meta"), dict) else {}
            local_path = str(meta.get("local_path") or "").strip()
            filename = PurePosixPath(local_path or location).name
            if not filename or filename in {".", ".."}:
                continue
            destination = output_dir / filename
            if destination.exists():
                continue
            parsed = urlparse(location)
            try:
                if parsed.scheme == "s3":
                    parts = PurePosixPath(parsed.path.lstrip("/")).parts
                    if parsed.netloc != minio.bucket or len(parts) < 3 or parts[0] != case.get("case_id"):
                        continue
                    minio.fetch_case_object(str(case["case_id"]), "/".join(parts[1:]), destination)
                elif location.startswith(("projects/", "inbox/")):
                    source = (factory.user_root(requester_ref) / location).resolve()
                    source.relative_to(factory.user_root(requester_ref).resolve())
                    if source.is_file():
                        shutil.copyfile(source, destination)
            except (OSError, ValueError, BusinessError) as exc:
                logger.warning("AgentTeams delivery artifact projection skipped {}: {}", location, exc)
        # 产物血缘（F1）：交付 manifest 内嵌权威血缘（平台 DB 版本行 + 依赖 DAG），
        # 甲方报告文末附血缘清单（version_id + checksum + 上游一级展开）。
        lineage: dict[str, Any] = {"versions": [], "dependencies": []}
        lineage_note = ""
        try:
            lineage = await AgentTeamsArtifactLineageService(db).case_lineage(
                str(case.get("case_id") or "")
            )
            manifest["artifact_version_lineage"] = lineage
        except Exception as exc:  # noqa: BLE001 - 血缘查询失败不阻断交付，但必须在报告中显式可见
            lineage_note = f"血缘清单不可用：{type(exc).__name__}"
            logger.bind(case_id=case.get("case_id")).warning(
                "AgentTeams delivery lineage query failed: {}", exc
            )
        # 篡改检测（F1 收尾）：交付前对已登记产物的最新版本重算 sha256 比对登记值，
        # 不一致记 mismatch——结构化留痕（manifest + 审计事件 + 报告小节），不阻断交付。
        checksum_verification: list[dict[str, Any]] = []
        try:
            checksum_verification = await AgentTeamsArtifactLineageService(
                db
            ).verify_case_checksums(
                str(case.get("case_id") or ""),
                self._delivery_content_resolver(str(case.get("case_id") or ""), factory, minio),
            )
        except Exception as exc:  # noqa: BLE001 - 校验执行失败不阻断交付，但必须显式可见
            logger.bind(case_id=case.get("case_id")).warning(
                "AgentTeams delivery checksum verification failed: {}", exc
            )
        manifest["artifact_checksum_verification"] = checksum_verification
        mismatches = [item for item in checksum_verification if item["status"] == "mismatch"]
        if mismatches:
            logger.bind(
                case_id=case.get("case_id"),
                mismatch_count=len(mismatches),
                artifacts=[item["artifact_id"] for item in mismatches],
            ).warning("AgentTeams delivery checksum mismatch detected")
            try:
                await self.post_case_evidence(
                    str(case.get("case_id") or ""),
                    work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                    event_type="artifact.checksum_mismatch",
                    summary=f"交付前 checksum 比对发现 {len(mismatches)} 个产物与登记值不一致",
                    payload={"mismatches": mismatches[:50]},
                )
            except Exception as exc:  # noqa: BLE001 - 事件投影失败不阻断交付
                logger.bind(case_id=case.get("case_id")).warning(
                    "AgentTeams checksum mismatch evidence projection failed: {}", exc
                )
        manifest_path = output_dir / "agentteams-delivery-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = str(manifest.get("remediation_summary") or "").strip()
        task_ids = manifest.get("task_ids") or []
        report = [
            "# AgentTeams Case 交付报告",
            "",
            f"- Case：`{case.get('case_id', '')}`",
            f"- 项目运行目录：`{run_path}`",
            f"- 状态：`{case.get('status', '')}`",
            f"- 任务：{', '.join(map(str, task_ids)) or '无'}",
            "",
            "## 交付说明",
            summary or "交付 Worker 已完成汇总，详细审计与产物校验见同目录 manifest。",
            "",
            "## 产物校验",
            f"manifest 中登记 {len(manifest.get('artifact_checksums') or {})} 个产物校验项。",
            self._checksum_report_line(checksum_verification),
            "",
            *self._lineage_report_lines(lineage, lineage_note),
        ]
        (output_dir / "delivery-summary.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        file_repo = FileRepositoryImpl(db)
        existing = {
            item.path
            for item in await file_repo.list_by_user(user_uuid, status=None)
            if item.source == "agentteams"
        }
        for output_file in sorted(output_dir.iterdir()):
            if not output_file.is_file():
                continue
            storage_path = output_file.relative_to(factory.data_root).as_posix()
            if storage_path in existing:
                continue
            payload = output_file.read_bytes()
            await file_repo.save(
                DataFile(
                    id=uuid4(),
                    user_id=user_uuid,
                    path=storage_path,
                    original_name=output_file.name,
                    size=len(payload),
                    checksum=hashlib.sha256(payload).hexdigest(),
                    file_type=FileType.REPORT if output_file.suffix == ".md" else FileType.OTHER,
                    directory=output_rel,
                    source="agentteams",
                )
            )
        await db.flush()
        return {
            "output_dir": str(output_dir),
            "files": [
                str(path) for path in sorted(output_dir.iterdir()) if path.is_file()
            ],
            "checksum_verification": checksum_verification,
        }

    @staticmethod
    def _checksum_report_line(checksum_verification: list[dict[str, Any]]) -> str:
        """交付报告"产物校验"小节的 checksum 比对汇总行。"""
        if not checksum_verification:
            return "本 Case 无平台登记的产物版本，未做 checksum 比对。"
        counts = {"verified": 0, "mismatch": 0, "unverified": 0}
        for item in checksum_verification:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        line = (
            f"checksum 比对：{counts['verified']} 一致 / "
            f"{counts['mismatch']} 不一致 / {counts['unverified']} 未比对。"
        )
        mismatched = [item["artifact_id"] for item in checksum_verification if item["status"] == "mismatch"]
        if mismatched:
            line += " 不一致产物：" + "、".join(f"`{name}`" for name in mismatched[:10])
        return line

    def _delivery_content_resolver(
        self, case_id: str, factory: Any, minio: MinioStore
    ) -> Any:
        """构造 verify_case_checksums 的内容解析器：本地相对路径直读，s3:// 拉取临时文件。

        任何解析失败都返回 None（调用方记 unverified），不抛异常打断交付。
        """
        data_root = Path(factory.data_root).resolve()

        def local_content(uri: str) -> bytes | None:
            target = (data_root / uri).resolve()
            try:
                target.relative_to(data_root)
            except ValueError:
                return None
            if not target.is_file():
                return None
            return target.read_bytes()

        async def resolve(storage_uri: str) -> bytes | None:
            uri = str(storage_uri or "").strip()
            if not uri:
                return None
            try:
                parsed = urlparse(uri)
                if parsed.scheme == "s3":
                    parts = PurePosixPath(parsed.path.lstrip("/")).parts
                    if parsed.netloc != minio.bucket or len(parts) < 3 or parts[0] != case_id:
                        return None
                    with tempfile.TemporaryDirectory(prefix="cygnusx-checksum-") as tmp:
                        fetched = minio.fetch_case_object(case_id, "/".join(parts[1:]), Path(tmp) / "blob")
                        return fetched.read_bytes()
                return local_content(uri)
            except (OSError, ValueError, BusinessError) as exc:
                logger.bind(case_id=case_id, storage_uri=uri[:200]).warning(
                    "AgentTeams checksum content resolve failed: {}", exc
                )
                return None

        return resolve

    @staticmethod
    def _lineage_report_lines(lineage: dict[str, Any], lineage_note: str) -> list[str]:
        """甲方报告文末的"血缘清单"小节：每个交付物 version_id + checksum + 上游一级展开。"""
        lines = ["## 血缘清单"]
        if lineage_note:
            return [*lines, lineage_note]
        versions = lineage.get("versions") or []
        if not versions:
            declared = lineage.get("dependencies") or []
            return [*lines, "本 Case 无平台登记的产物版本记录。" if not declared else "本 Case 无平台登记的产物版本记录（仅依赖边）。"]
        for row in versions:
            checksum = str(row.get("checksum_sha256") or "")
            lines.append(
                f"- `{row.get('artifact_id', '')}` v{row.get('version_no', '?')}"
                f"（version_id: `{row.get('version_id', '')}`，"
                f"sha256: `{checksum[:16]}…`，"
                f"producing_event: `{row.get('producing_event_id') or '无'}`）"
            )
            upstream = row.get("upstream") or []
            if upstream:
                lines.append(
                    "  - 上游："
                    + "、".join(
                        f"`{ref.get('artifact_id', '')}`（{ref.get('relation', 'input_to')}）"
                        for ref in upstream
                    )
                )
            else:
                lines.append("  - 上游：无（首环产物）")
        return lines

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
        params = {"limit": max(1, min(limit, _BRIDGE_CASE_EVENTS_PAGE_LIMIT))}
        if cursor:
            params["cursor"] = cursor
        return await self._request(f"/v1/cases/{case_id}/events", params=params)

    async def get_room_response_timing_summary(
        self,
        case_id: str,
        requester_ref: str,
        *,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Aggregate persisted Manager response timing events for a Case."""
        event_page = await self.get_case_events(case_id, requester_ref, limit=limit)
        event_items = list(event_page.get("events", []))
        next_cursor = event_page.get("next_cursor")
        while next_cursor and len(event_items) < limit:
            event_page = await self.get_case_events(
                case_id,
                requester_ref,
                cursor=str(next_cursor),
                limit=limit - len(event_items),
            )
            page_items = event_page.get("events", [])
            if not isinstance(page_items, list) or not page_items:
                break
            event_items.extend(page_items)
            next_cursor = event_page.get("next_cursor")
        timings = [
            event.get("payload") or {}
            for event in event_items
            if isinstance(event, dict) and event.get("event_type") == "room.response_timing"
        ]
        durations = [
            max(0, int(item.get("duration_ms") or 0))
            for item in timings
            if isinstance(item, dict) and item.get("duration_ms") is not None
        ]

        def percentile(values: list[int]) -> int:
            if not values:
                return 0
            ordered = sorted(values)
            return ordered[max(0, ceil(len(ordered) * 0.95) - 1)]

        stage_values: dict[str, list[int]] = {}
        for item in timings:
            if not isinstance(item, dict):
                continue
            stage_ms = item.get("stage_ms")
            if not isinstance(stage_ms, dict):
                continue
            for stage, value in stage_ms.items():
                try:
                    stage_values.setdefault(str(stage), []).append(max(0, int(value)))
                except (TypeError, ValueError):
                    continue
        return {
            "case_id": case_id,
            "sample_count": len(durations),
            "p95_duration_ms": percentile(durations),
            "stage_p95_ms": {
                stage: percentile(values) for stage, values in sorted(stage_values.items())
            },
            "latest_duration_ms": durations[-1] if durations else 0,
        }

    async def provision_case_room(
        self, case_id: str, *, requester_ref: str = ""
    ) -> dict[str, Any] | None:
        """Best-effort Matrix 房间供给；失败记录为 Case 证据但不阻断创建。

        房间标识通过 ``room.created`` Case 证据事件持久化（bridge 审计流即映射存储，
        bridge 侧房间镜像钩子凭它绑定 case_id → room_id）；同时在 Redis 登记
        case→room 绑定供 Matrix 反向同步消费。未启用 Gateway 或建房失败时返回
        None，前端降级为纯事件流模式。
        """
        gateway = AgentTeamsRoomGatewayService()
        if not gateway.available:
            return None
        # 平台用户按映射规则供给独立 Matrix 账号并邀请进房（共享 cygnusx-user 兜底）。
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
            await self._record_room_provision_failure(case_id, reason="gateway_request_failed", exc=exc)
            return None
        room_id = str(room.get("room_id") or "")
        if not room_id:
            logger.warning("agentteams case {} room provisioning returned no room_id", case_id)
            await self._record_room_provision_failure(
                case_id,
                reason="gateway_invalid_response",
                detail="Gateway response did not contain room_id",
            )
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
        from cygnusx.application.services.agentteams_room_sync_service import (
            record_room_binding,
        )

        await record_room_binding(case_id, room_id, requester_ref)
        return room

    async def create_element_session(self, identity: str, room_id: str | None = None) -> dict[str, Any]:
        """经 Gateway 为平台用户的 Matrix 身份签发 Element 视图免登录会话。

        as_token 不出 Gateway 进程；本方法只做连通性检查与转发。携带
        ``room_id`` 时 Gateway 会先幂等入房（仅 invited 未 joined 的房间在
        Element 深链下会卡黑屏）。
        """
        gateway = AgentTeamsRoomGatewayService()
        if not gateway.available:
            raise BusinessError("Agent 协作中心尚未接通")
        return await gateway.create_element_session(identity, room_id)

    async def leave_matrix_room(self, identity: str, room_id: str) -> dict[str, Any]:
        """经 Gateway 让平台用户的 Matrix 身份离房（删除协作室时调用）。

        as_token 不出 Gateway 进程；本方法只做连通性检查与转发。
        """
        gateway = AgentTeamsRoomGatewayService()
        if not gateway.available:
            raise BusinessError("Agent 协作中心尚未接通")
        return await gateway.leave_matrix_room(identity, room_id)

    async def _record_room_provision_failure(
        self,
        case_id: str,
        *,
        reason: str,
        exc: Exception | None = None,
        detail: str | None = None,
    ) -> None:
        """Persist a visible fallback event so Matrix degradation is diagnosable from the Case."""
        try:
            await self.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.provisioning_failed",
                summary="协作房间创建失败，已降级为平台事件流",
                payload={
                    "provider": "matrix",
                    "reason": reason,
                    "detail": (detail or str(exc or "unknown failure"))[:1_000],
                    "recovery": "检查 Gateway 配置、网络连通性和 Matrix 服务后重试建房",
                },
            )
        except BusinessError as evidence_exc:
            logger.warning(
                "agentteams case {} room provisioning failure evidence failed: {}",
                case_id,
                evidence_exc,
            )

    async def create_room_namespace(
        self, *, room_id: str, title: str, requester_ref: str
    ) -> dict[str, Any]:
        """在 Bridge 创建房间命名空间记录，承载未立项房间的级事件流。

        命名空间记录（record_kind=room_namespace）复用 Case 事件流/恢复/SSE/镜像
        链路，但不进用户 Case 列表、配额与 GC（Bridge 侧保证）。
        """
        return await self._request(
            "/v1/cases",
            method="POST",
            json={
                "case_id": room_namespace_case_id(room_id),
                "record_kind": "room_namespace",
                "intent": f"协作室房间会话：{title.strip()[:200]}",
                "requester_ref": requester_ref,
            },
        )

    async def bind_case_room(
        self,
        case_id: str,
        *,
        room_id: str,
        matrix_room_id: str | None,
        requester_ref: str,
    ) -> dict[str, Any] | None:
        """立项确认后把既有房间绑定到新 Case。

        房间已有 Matrix 房间时直接复用（把 room.created 证据写到 Case 审计流，
        让 Bridge 房间镜像钩子把 Case 事件镜像进同一房间）；没有则按原逻辑建房。
        """
        if not matrix_room_id:
            return await self.provision_case_room(case_id, requester_ref=requester_ref)
        try:
            await self.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.created",
                summary="协作房间已创建",
                payload={
                    "provider": "matrix",
                    "room_id": matrix_room_id,
                    "reused_from_room_id": room_id,
                },
            )
        except BusinessError as exc:
            logger.warning("agentteams case {} room binding evidence failed: {}", case_id, exc)
        from cygnusx.application.services.agentteams_room_sync_service import (
            record_room_binding,
        )

        await record_room_binding(case_id, matrix_room_id, requester_ref)
        return {"room_id": matrix_room_id}

    async def post_room_message(
        self,
        case_id: str,
        requester_ref: str,
        content: str,
        *,
        actor_user_id: str | None = None,
        context_refs: list[dict[str, str]] | None = None,
        client_message_id: str | None = None,
    ) -> dict[str, Any]:
        """记录一条用户房间发言（``room.user_message`` 审计事件）。

        无论 Matrix 房间是否存在都记录审计事件（无 Matrix 时房间页经事件流投影显示）；
        已建房时由 bridge 侧镜像钩子发进 Matrix 房间，发送失败不影响事件记录。
        ``context_refs`` 是房间 @ 引用的工作区文件（只读引用），随 payload 落审计。
        """
        case = await self._request(f"/v1/cases/{case_id}")
        if case.get("requester_ref") != requester_ref:
            raise AuthorizationError("无权操作该协作案例")
        from cygnusx.application.services.agentteams_mention_resolver import resolve_room_mentions

        registry = get_agentteams_capability_registry()
        role_labels = registry.role_labels()
        participant_targets = {
            str(item.get("target"))
            for item in case.get("work_items", [])
            if isinstance(item, dict) and item.get("target")
        }
        allowed_agent_ids = set(participant_targets)
        allowed_agent_ids.update(
            str(label.get("agent_id"))
            for role, label in role_labels.items()
            if role in participant_targets and label.get("agent_id")
        )
        dispatch = resolve_room_mentions(
            content,
            registry=registry,
            role_labels=role_labels,
            allowed_agent_ids=allowed_agent_ids or None,
        )
        if client_message_id:
            existing = await self.get_case_events(case_id, requester_ref, limit=200)
            existing_events = list(existing.get("events", []))
            next_cursor = existing.get("next_cursor")
            while next_cursor and len(existing_events) < 200:
                existing = await self.get_case_events(
                    case_id,
                    requester_ref,
                    cursor=str(next_cursor),
                    limit=200 - len(existing_events),
                )
                page_events = existing.get("events", [])
                if not isinstance(page_events, list) or not page_events:
                    break
                existing_events.extend(page_events)
                next_cursor = existing.get("next_cursor")
            for event in existing_events:
                if not isinstance(event, dict) or event.get("event_type") != "room.user_message":
                    continue
                event_payload = event.get("payload") or {}
                if not isinstance(event_payload, dict):
                    continue
                nested_payload = event_payload.get("payload")
                if isinstance(nested_payload, dict):
                    event_payload = nested_payload
                if event_payload.get("client_message_id") == client_message_id:
                    return {
                        "event_id": event.get("event_id"),
                        "deduplicated": True,
                        "dispatch": dispatch,
                    }
        payload: dict[str, Any] = {
            "actor": actor_user_id or requester_ref,
            "content": content.strip(),
            "mentions": dispatch["mentions"],
            "target_agent_id": dispatch["target_agent_id"],
            "dispatch_mode": dispatch["dispatch_mode"],
        }
        if dispatch.get("unknown_mentions"):
            payload["mention_resolution_note"] = (
                "以下点名对象不是当前 Case 参与者，已交由生物信息部门经理评估："
                + "、".join(dispatch["unknown_mentions"])
            )
        if client_message_id:
            payload["client_message_id"] = client_message_id
        if context_refs:
            payload["context_refs"] = context_refs
        result = await self.post_case_evidence(
            case_id,
            work_item_id=CASE_LEVEL_WORK_ITEM_ID,
            event_type="room.user_message",
            summary=content.strip()[:80],
            payload=payload,
        )
        return {**result, "dispatch": dispatch}

    async def apply_change_decision(
        self,
        case_id: str,
        requester_ref: str,
        *,
        work_item_ids: list[str],
        decision: str,
        rationale: str = "",
    ) -> dict[str, Any]:
        """Record a user change decision; only cancel mutates execution immediately."""
        if decision not in {"resume", "replan", "branch", "cancel"}:
            raise BusinessError("不支持的变更决策")
        case = await self._get_case_for_requester(case_id, requester_ref)
        requested_ids = {str(item_id) for item_id in work_item_ids if item_id}
        items = [
            item for item in case.get("work_items", [])
            if isinstance(item, dict) and str(item.get("work_item_id")) in requested_ids
        ]
        if not items:
            raise BusinessError("未找到可处理的受影响工作项")
        statuses = {"claimed", "running", "in_progress", "awaiting_approval", "planning_running"}
        active_items = [item for item in items if str(item.get("status") or "").lower() in statuses]
        if not active_items and decision != "resume":
            raise BusinessError("受影响工作项已经离开运行态，无法重复提交该决策")

        changed_items: list[str] = []
        if decision in {"cancel", "replan"}:
            for item in active_items:
                item_id = str(item["work_item_id"])
                await self._request(
                    f"/v1/cases/{case_id}/work-items/{item_id}",
                    method="POST",
                    json={
                        "status": "cancelled",
                        "summary": (
                            rationale.strip()[:4_000]
                            or ("用户确认终止该变更支线" if decision == "cancel" else "重规划前冻结旧工作项")
                        ),
                    },
                )
                changed_items.append(item_id)
                await self.post_case_evidence(
                    case_id,
                    work_item_id=item_id,
                    event_type="work_item.interrupted",
                    summary="工作项已在安全边界停止，等待变更后续编排",
                    payload={
                        "work_item_id": item_id,
                        "stop_level": "queued",
                        "previous_status": item.get("status"),
                        "reusable_artifacts": item.get("output_refs") or [],
                        "resume_hint": "原工作项已保留审计与产物引用",
                        "decision": decision,
                    },
                )

        created_work_item_ids: list[str] = []
        rerouted_targets: dict[str, str] = {}
        if decision in {"replan", "branch"}:
            suffix = uuid4().hex[:8]
            for item in items:
                item_id = str(item["work_item_id"])
                new_id = f"{item_id}-{decision}-{suffix}"
                target = item.get("target")
                if decision == "replan":
                    try:
                        route = infer_intent_route(
                            f"{case.get('intent') or ''}\n{item.get('objective') or ''}"
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve old target on route failure
                        route = None
                        logger.bind(case_id=case_id, work_item_id=item_id).warning(
                            "AgentTeams replan target routing failed: {}", exc
                        )
                    if route is not None:
                        target = route.lead_planner
                if decision == "replan" and target:
                    rerouted_targets[item_id] = str(target)
                await self._request(
                    f"/v1/cases/{case_id}/work-items",
                    method="POST",
                    json={
                        "work_item_id": new_id,
                        "parent_work_item_id": item_id,
                        "target": target,
                        "objective": (
                            f"根据用户变更决策重新规划：{item.get('objective') or ''}"
                            if decision == "replan"
                            else f"并行验证支线：{item.get('objective') or ''}"
                        )[:1_000],
                        "skill_name": item.get("skill_name") or "change-branch",
                        "context_refs": item.get("context_refs") or [],
                        "declared_inputs": item.get("declared_inputs") or [],
                        "declared_outputs": item.get("declared_outputs") or [],
                        "read_only": True,
                        "execution_mode": "readonly_consultation",
                        "depends_on": [],
                        "idempotency_key": f"{case_id}:{new_id}",
                    },
                )
                created_work_item_ids.append(new_id)

        payload = {
            "work_item_ids": [str(item["work_item_id"]) for item in items],
            "decision": decision,
            "rationale": rationale.strip()[:4_000],
            "execution_status": (
                "cancelled" if decision == "cancel" else "recorded_pending_replan"
            ),
            "changed_work_item_ids": changed_items,
            "created_work_item_ids": created_work_item_ids,
            "rerouted_targets": rerouted_targets,
        }
        await self.post_case_evidence(
            case_id,
            work_item_id=CASE_LEVEL_WORK_ITEM_ID,
            event_type="work_item.resume_decision",
            summary=f"用户已提交变更决策：{decision}",
            payload=payload,
        )
        return {"case_id": case_id, **payload}

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

    async def record_room_response_timing(
        self,
        case_id: str,
        *,
        requester_ref: str,
        response_status: str,
        duration_ms: int,
        stage_ms: dict[str, int],
    ) -> dict[str, Any]:
        """Persist response timing as queryable Case evidence for latency baselines."""
        await self._get_case_for_requester(case_id, requester_ref)
        return await self.post_case_evidence(
            case_id,
            work_item_id=CASE_LEVEL_WORK_ITEM_ID,
            event_type="room.response_timing",
            summary=f"生物信息部门经理响应耗时 {duration_ms}ms",
            payload={
                "response_status": response_status,
                "duration_ms": max(0, int(duration_ms)),
                "stage_ms": {
                    str(key): max(0, int(value))
                    for key, value in stage_ms.items()
                },
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
            response_body = exc.response.text[:1000]
            trace_id = exc.response.headers.get("x-request-id") or exc.response.headers.get(
                "x-trace-id"
            )
            response_payload: dict[str, Any] = {}
            try:
                decoded_body = exc.response.json()
                if isinstance(decoded_body, dict):
                    response_payload = decoded_body
            except ValueError:
                pass
            detail = response_payload.get("detail")
            bridge_code = response_payload.get("code")
            if isinstance(detail, dict):
                bridge_code = detail.get("code") or bridge_code
                detail_message = detail.get("message") or detail.get("detail")
            else:
                detail_message = detail
            logger.warning(
                "AgentTeams Bridge request failed: method={} path={} status={} code={} trace_id={} body={}",
                method,
                path,
                exc.response.status_code,
                bridge_code,
                trace_id,
                response_body,
            )
            if exc.response.status_code == 404:
                raise BusinessError("协作案例不存在") from exc
            if bridge_code == "LIMIT_EXCEEDED":
                raise BusinessError(
                    "协作事件查询范围无效，请缩小查询范围",
                    code="LIMIT_EXCEEDED",
                ) from exc
            if bridge_code == "FLOW_NOT_ALLOWED" or detail_message == "Flow is not allowed":
                raise BusinessError(
                    "当前分析流程未在 AgentTeams Bridge 中启用，请联系管理员启用该流程后重试",
                    code="FLOW_NOT_ALLOWED",
                ) from exc
            if isinstance(detail_message, str) and detail_message:
                logger.debug("AgentTeams Bridge error detail: {}", detail_message)
            raise BusinessError("Agent 协作中心暂时不可用", code=bridge_code) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "AgentTeams Bridge request unavailable: method={} path={} error={}",
                method,
                path,
                exc.__class__.__name__,
            )
            raise BusinessError("Agent 协作中心暂时不可用", code="BRIDGE_UNAVAILABLE") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise BusinessError("Agent 协作中心返回了无效数据")
        return payload
