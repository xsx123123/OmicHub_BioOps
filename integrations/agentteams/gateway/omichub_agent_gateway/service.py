"""Policy enforcement, cost guarding, response sanitization, and audit for consultations."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

import httpx
from pydantic import ValidationError

from .audit import AuditStore
from .client import OmicHubConsultationClient
from .config import GatewaySettings
from .matrix_client import MatrixGatewayClient
from .models import ConsultationError, ConsultationRequest, ScientificInterpretationResponse


class GatewayService:
    def __init__(
        self,
        settings: GatewaySettings,
        client: OmicHubConsultationClient,
        audit: AuditStore,
        matrix_client: MatrixGatewayClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._audit = audit
        self._matrix = matrix_client
        self._case_calls: dict[str, int] = defaultdict(int)
        self._case_tokens: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        self._counter_redis = None
        if settings.state_store_url:
            try:
                from redis.asyncio import from_url

                self._counter_redis = from_url(settings.state_store_url, decode_responses=True)
            except ImportError as exc:  # pragma: no cover - Docker includes redis dependency
                raise RuntimeError("Gateway Redis counter store requires redis package") from exc

    async def consult(
        self, request: ConsultationRequest, actor: str
    ) -> ScientificInterpretationResponse:
        started_at = time.perf_counter()
        policy_error = self._policy_error(request)
        if policy_error:
            return await self._reject(request, actor, started_at, policy_error)
        reservation_error = await self._reserve_call(request.case_id)
        if reservation_error:
            return await self._reject(request, actor, started_at, reservation_error)
        try:
            upstream = await asyncio.wait_for(
                self._client.consult(request), timeout=self._settings.request_timeout_seconds
            )
        except TimeoutError:
            return await self._manual_review(
                request,
                actor,
                started_at,
                "UPSTREAM_TIMEOUT",
                "Professional consultation timed out; manual review is required.",
            )
        except (httpx.HTTPError, ValidationError):
            return await self._manual_review(
                request,
                actor,
                started_at,
                "UPSTREAM_UNAVAILABLE",
                "Professional consultation failed; manual review is required.",
            )
        token_error = await self._consume_tokens(request.case_id, upstream.token_usage)
        if token_error:
            return await self._reject(request, actor, started_at, token_error)
        response = ScientificInterpretationResponse(
            status="completed",
            conclusion=upstream.conclusion,
            recommendations=upstream.recommendations,
            evidence_refs=upstream.evidence_refs,
            risks=upstream.risks,
            agent_id=request.agent_id,
            duration_ms=self._duration_ms(started_at),
            token_usage=upstream.token_usage,
            proposed_submission=upstream.proposed_submission,
            artifacts=upstream.artifacts,
            hard_gate=upstream.hard_gate,
        )
        await self._audit_response(request, actor, response)
        return response

    def _policy_error(self, request: ConsultationRequest) -> ConsultationError | None:
        policy = self._settings.agent_policy_map().get(request.agent_id)
        if policy is None:
            return ConsultationError(
                code="AGENT_NOT_ALLOWED", message="Target agent is not allowlisted."
            )
        capabilities, tools = policy
        if request.capability not in capabilities:
            return ConsultationError(
                code="CAPABILITY_NOT_ALLOWED",
                message="Requested capability is not allowed for this agent.",
            )
        forbidden_tools = sorted(set(request.requested_tools) - tools)
        if forbidden_tools:
            return ConsultationError(
                code="TOOL_NOT_ALLOWED", message="Requested tool is not in the read-only allowlist."
            )
        return None

    async def _reserve_call(self, case_id: str) -> ConsultationError | None:
        if self._counter_redis is not None:
            key = f"{self._settings.state_store_key_prefix}:calls:{case_id}"
            count = await self._counter_redis.incr(key)
            if count == 1:
                await self._counter_redis.expire(key, 86_400)
            if count > self._settings.max_calls_per_case:
                return ConsultationError(
                    code="CASE_CALL_LIMIT_EXCEEDED", message="Per-case consultation limit exceeded."
                )
            return None
        async with self._lock:
            if self._case_calls[case_id] >= self._settings.max_calls_per_case:
                return ConsultationError(
                    code="CASE_CALL_LIMIT_EXCEEDED",
                    message="Per-case consultation limit exceeded.",
                )
            self._case_calls[case_id] += 1
        return None

    async def _consume_tokens(self, case_id: str, token_usage: int) -> ConsultationError | None:
        if self._counter_redis is not None:
            key = f"{self._settings.state_store_key_prefix}:tokens:{case_id}"
            total = await self._counter_redis.incrby(key, max(0, token_usage))
            if total == max(0, token_usage):
                await self._counter_redis.expire(key, 86_400)
            if total > self._settings.max_tokens_per_case:
                return ConsultationError(
                    code="CASE_TOKEN_LIMIT_EXCEEDED", message="Per-case token limit exceeded."
                )
            return None
        async with self._lock:
            if self._case_tokens[case_id] + token_usage > self._settings.max_tokens_per_case:
                return ConsultationError(
                    code="CASE_TOKEN_LIMIT_EXCEEDED",
                    message="Per-case token limit exceeded.",
                )
            self._case_tokens[case_id] += token_usage
        return None

    async def aclose(self) -> None:
        if self._counter_redis is not None:
            await self._counter_redis.aclose()

    async def _reject(
        self,
        request: ConsultationRequest,
        actor: str,
        started_at: float,
        error: ConsultationError,
    ) -> ScientificInterpretationResponse:
        response = ScientificInterpretationResponse(
            status="rejected",
            conclusion="Consultation was not executed.",
            risks=["No automated action is permitted; route this request for manual review."],
            agent_id=request.agent_id,
            duration_ms=self._duration_ms(started_at),
            token_usage=0,
            error=error,
        )
        await self._audit_response(request, actor, response)
        return response

    async def _manual_review(
        self,
        request: ConsultationRequest,
        actor: str,
        started_at: float,
        code: str,
        message: str,
    ) -> ScientificInterpretationResponse:
        response = ScientificInterpretationResponse(
            status="manual_review",
            conclusion="No automated scientific conclusion is available.",
            risks=["Manual review is required before any workflow action."],
            agent_id=request.agent_id,
            duration_ms=self._duration_ms(started_at),
            token_usage=0,
            error=ConsultationError(code=code, message=message),
        )
        await self._audit_response(request, actor, response)
        return response

    async def _audit_response(
        self,
        request: ConsultationRequest,
        actor: str,
        response: ScientificInterpretationResponse,
    ) -> None:
        await self._audit.record(
            case_id=request.case_id,
            actor=actor,
            event_type="agent.consultation",
            payload={
                "target_role": request.agent_id,
                "question_summary": self._question_summary(request.question),
                "schema_version": response.schema_version,
                "status": response.status,
                "duration_ms": response.duration_ms,
                "token_usage": response.token_usage,
                "evidence_refs": response.evidence_refs,
                "error_code": response.error.code if response.error else None,
            },
        )

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return int((time.perf_counter() - started_at) * 1_000)

    @staticmethod
    def _question_summary(question: str) -> str:
        return " ".join(question.split())[:500]

    async def create_room(self, session_id: str, identities: list[str], actor: str):
        from .models import RoomCreateResponse

        matrix = self._require_matrix()
        allowed_identities = self._validated_room_identities(identities)
        room_name = f"omichub-session-{session_id}"
        room_id = await matrix.create_room(room_name, actor, allowed_identities)
        await self._audit.record(
            case_id=session_id,
            actor=actor,
            event_type="matrix.room.created",
            payload={"room_id": room_id, "identities": allowed_identities},
        )
        return RoomCreateResponse(
            room_id=room_id,
            room_name=room_name,
            element_room_url=self._element_room_url(room_id),
        )

    async def post_room_message(self, room_id: str, request, actor: str):
        matrix = self._require_matrix()
        self._validated_room_identities([request.sender_identity])
        event_id = await matrix.send_message(
            room_id,
            request.sender_identity,
            request.content,
            request.sender,
            request.source,
        )
        await self._audit.record(
            case_id=room_id,
            actor=actor,
            event_type="matrix.room.message",
            payload={
                "event_id": event_id,
                "sender_identity": request.sender_identity,
                "source": request.source,
                "content_length": len(request.content),
            },
        )
        return event_id

    async def room_messages(self, room_id: str, since: str | None, limit: int):
        matrix = self._require_matrix()
        events, next_batch = await matrix.messages(room_id, since, limit)
        from .models import RoomMessagesResponse

        return RoomMessagesResponse(events=events, next_batch=next_batch)

    async def room_sync(self, room_id: str, since: str | None):
        matrix = self._require_matrix()
        async for events, next_batch in matrix.stream_sync(room_id, since):
            yield events, next_batch

    def _require_matrix(self):
        if self._matrix is None:
            raise RuntimeError("Matrix Gateway is not configured")
        return self._matrix

    def _validated_room_identities(self, identities: list[str]) -> list[str]:
        normalized = list(
            dict.fromkeys(identity.strip() for identity in identities if identity.strip())
        )
        invalid = [
            identity
            for identity in normalized
            if self._settings.matrix_user_for_identity(identity) is None
        ]
        if invalid:
            raise ValueError(f"Matrix identity is not configured: {', '.join(invalid)}")
        return normalized

    async def ensure_users(self, identities: list[str], actor: str) -> list[str]:
        """Provision AppService-owned Matrix accounts for the given identities.

        幂等：已存在的 Matrix 用户由 ``MatrixGatewayClient.ensure_identities``
        按 M_USER_IN_USE 跳过；返回实际接受的身份列表。
        """
        matrix = self._require_matrix()
        allowed = self._validated_room_identities(identities)
        await matrix.ensure_identities(allowed)
        await self._audit.record(
            case_id="matrix-users",
            actor=actor,
            event_type="matrix.users.ensured",
            payload={"identities": allowed},
        )
        return allowed

    def _element_room_url(self, room_id: str) -> str | None:
        if not self._settings.element_base_url:
            return None
        return f"{self._settings.element_base_url.rstrip('/')}/#/room/{room_id}"
