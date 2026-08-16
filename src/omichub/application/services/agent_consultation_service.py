"""Read-only execution kernel for AgentTeams professional consultations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.agent_service import AgentService
from omichub.application.services.agentteams_capability_registry import (
    get_agentteams_capability_registry,
)
from omichub.application.services.agentteams_consultation_telemetry_service import (
    AgentTeamsConsultationTelemetryService,
)
from omichub.application.services.agentteams_quality_gate_service import (
    AgentTeamsQualityGateService,
)
from omichub.application.services.agentteams_service import AgentTeamsService
from omichub.application.services.agentteams_usage_service import record_consultation_usage
from omichub.application.services.parallel_subagent_service import ParallelSubAgentService
from omichub.application.services.pipeline_result_service import PipelineResultService
from omichub.core.config import get_settings
from omichub.core.exceptions import BusinessError, NotFoundError
from omichub.domain.file.entities import DataFile
from omichub.domain.file.value_objects import FileType, OwnerScope
from omichub.infrastructure.database.repositories.file_repository import FileRepositoryImpl
from omichub.infrastructure.storage.minio_store import MinioStore
from omichub.infrastructure.storage.path_factory import get_path_factory

_JSON_FENCE_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

_TOOL_CALL_EVIDENCE_LIMIT = 200
_ARGS_SUMMARY_MAX_CHARS = 200

_WORKSPACE_EXEC_PROTOCOL_PATH = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "ai"
    / "prompts"
    / "shared"
    / "agentteams_workspace_execution.md"
)


class ConsultationEnvelope(BaseModel):
    conclusion: str = Field(min_length=1, max_length=8_000)
    recommendations: list[str] = Field(default_factory=list, max_length=100)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=100)
    token_usage: int = Field(default=0, ge=0)
    proposed_submission: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    hard_gate: dict[str, Any] | None = None


class _BridgeEvidenceProjector:
    """把子 Agent 运行时事件 fire-and-forget 投影为 Bridge 证据事件（agent.*）。"""

    def __init__(
        self,
        service: AgentTeamsService,
        *,
        case_id: str,
        work_item_id: str,
    ) -> None:
        self._service = service
        self._case_id = case_id
        self._work_item_id = work_item_id
        self._tool_call_counts: dict[int, int] = {}
        self._truncated: set[int] = set()
        self._pending: set[asyncio.Task[None]] = set()

    def __call__(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        index = int(event.get("index") or 0)
        agent_id = str(event.get("agent_id") or "")
        if event_type == "worker_started":
            self._schedule(
                "agent.started",
                f"Agent {agent_id} 开始执行",
                {"work_item_id": self._work_item_id, "agent_id": agent_id},
            )
        elif event_type == "worker_tool_call":
            count = self._tool_call_counts.get(index, 0) + 1
            self._tool_call_counts[index] = count
            tool = str(event.get("tool_name") or "")
            if count <= _TOOL_CALL_EVIDENCE_LIMIT:
                self._schedule(
                    "agent.tool_call",
                    f"Agent {agent_id} 调用工具 {tool}",
                    {
                        "tool": tool,
                        "args_summary": str(event.get("args_summary") or "")[
                            :_ARGS_SUMMARY_MAX_CHARS
                        ],
                        "work_item_id": self._work_item_id,
                        "agent_id": agent_id,
                    },
                )
            elif index not in self._truncated:
                self._truncated.add(index)
                self._schedule(
                    "agent.tool_call_truncated",
                    f"Agent {agent_id} 工具调用超过 {_TOOL_CALL_EVIDENCE_LIMIT} 条，后续合并省略",
                    {
                        "work_item_id": self._work_item_id,
                        "agent_id": agent_id,
                        "limit": _TOOL_CALL_EVIDENCE_LIMIT,
                    },
                )
        elif event_type == "worker_tool_result":
            tool = str(event.get("tool_name") or "")
            success = bool(event.get("success"))
            self._schedule(
                "agent.tool_result",
                f"工具 {tool} 执行{'成功' if success else '失败'}",
                {
                    "tool": tool,
                    "success": success,
                    "duration_ms": int(event.get("duration_ms") or 0),
                    "work_item_id": self._work_item_id,
                    "agent_id": agent_id,
                },
            )
        elif event_type == "worker_finished":
            self._schedule(
                "agent.finished",
                f"Agent {agent_id} 执行结束（{event.get('status') or 'unknown'}）",
                {
                    "status": str(event.get("status") or ""),
                    "tool_call_count": self._tool_call_counts.get(index, 0),
                    "duration_ms": round(float(event.get("elapsed_s") or 0) * 1000),
                    "work_item_id": self._work_item_id,
                    "agent_id": agent_id,
                },
            )

    def _schedule(self, event_type: str, summary: str, payload: dict[str, Any]) -> None:
        task = asyncio.create_task(self._send(event_type, summary, payload))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _send(self, event_type: str, summary: str, payload: dict[str, Any]) -> None:
        try:
            await self._service.post_case_evidence(
                self._case_id,
                work_item_id=self._work_item_id,
                event_type=event_type,
                summary=summary,
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001 — 证据投影失败不得影响会诊主流程
            logger.bind(
                case_id=self._case_id,
                work_item_id=self._work_item_id,
                event_type=event_type,
            ).warning("AgentTeams evidence projection failed: {}", exc)

    async def drain(self) -> None:
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)


class AgentConsultationService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        agent_service: AgentService | None = None,
        parallel_service: ParallelSubAgentService | None = None,
        telemetry_service: AgentTeamsConsultationTelemetryService | None = None,
        minio_store: MinioStore | None = None,
        agentteams_service: AgentTeamsService | None = None,
    ) -> None:
        self._db = db
        self._agent_service = agent_service or AgentService(db)
        self._parallel_service = parallel_service or ParallelSubAgentService()
        self._minio_store = minio_store or MinioStore()
        self._agentteams_service = agentteams_service
        self._telemetry_service = telemetry_service or (
            AgentTeamsConsultationTelemetryService()
            if isinstance(db, AsyncSession) and hasattr(db, "sync_session")
            else None
        )

    async def run_consultation(
        self,
        *,
        case_id: str,
        agent_id: str,
        question: str,
        capability: str,
        evidence_refs: list[str],
        requested_tools: list[str],
        requester_ref: str,
        work_item_id: str | None = None,
        execution_mode: str = "readonly_consultation",
    ) -> ConsultationEnvelope:
        started = time.monotonic()
        registry = get_agentteams_capability_registry()
        if agent_id not in registry.consultation_agents():
            raise NotFoundError(f"Agent {agent_id} 不存在或未启用")
        if execution_mode not in {"readonly_consultation", "workspace_execution"}:
            raise ValueError("Unsupported AgentTeams execution mode")
        if execution_mode == "workspace_execution" and (
            "workspace_execution" not in registry.agent_execution_modes(agent_id)
            or not work_item_id
        ):
            raise ValueError(
                f"Workspace execution requires a work item and a workspace_execution declaration for {agent_id}"
            )
        context = await self._agent_service.assemble_context(agent_id, user_id=requester_ref)
        if context is None or context.model_config is None:
            raise NotFoundError(f"Agent {agent_id} 不存在或未启用")

        hard_gate = await self._evaluate_hard_gate(
            capability=capability,
            evidence_refs=evidence_refs,
            requester_ref=requester_ref,
            case_id=case_id,
        )
        instruction = self._build_instruction(
            question=question,
            capability=capability,
            evidence_refs=evidence_refs,
            requested_tools=requested_tools,
            execution_mode=execution_mode,
            hard_gate=hard_gate,
        )
        workdir_root = (
            Path("/data/omichub") / "output" / "agentteams" / case_id / work_item_id
            if execution_mode == "workspace_execution" and work_item_id
            else None
        )
        projector = (
            _BridgeEvidenceProjector(
                self._agentteams_service, case_id=case_id, work_item_id=work_item_id
            )
            if self._agentteams_service is not None
            and self._agentteams_service.available
            and work_item_id
            else None
        )
        result = await self._parallel_service.run(
            user_id=requester_ref,
            parent_agent_id="agent-general",
            parent_session_id=f"agentteams:{case_id}",
            context_summary=f"AgentTeams Case {case_id} 的受控专业会诊",
            tasks=[
                {
                    "task_id": f"consultation:{case_id}:{work_item_id or agent_id}",
                    "agent_id": agent_id,
                    "task": instruction,
                    "workspace_access": execution_mode == "workspace_execution",
                }
            ],
            db=self._db,
            safe_only=execution_mode == "readonly_consultation",
            runtime_authorized=True,
            workdir_root=workdir_root,
            on_event=projector,
        )
        if projector is not None:
            await projector.drain()
        raw_answer = self._extract_answer(result)
        envelope, parse_success = self._parse_envelope_with_status(raw_answer)
        envelope.evidence_refs = self._verified_evidence_refs(result)
        envelope.hard_gate = hard_gate
        self._enforce_hard_gate(envelope)
        await self._record_telemetry(
            result=result,
            parse_success=parse_success,
            requested_refs=evidence_refs,
            verified_refs=envelope.evidence_refs,
            hard_gate=hard_gate,
            conclusion=envelope.conclusion,
        )
        await self._record_usage(
            result=result,
            envelope=envelope,
            case_id=case_id,
            agent_id=agent_id,
            requester_ref=requester_ref,
            context=context,
        )
        if execution_mode == "workspace_execution" and workdir_root is not None:
            artifacts, errors = await self._register_workspace_artifacts(
                requester_ref, case_id, work_item_id or "", workdir_root
            )
            envelope.artifacts = artifacts
            envelope.risks.extend(errors)
        logger.bind(
            case_id=case_id,
            agent_id=agent_id,
            requester_ref=requester_ref,
            duration_ms=round((time.monotonic() - started) * 1000),
            token_usage=envelope.token_usage,
        ).info("AgentTeams consultation completed")
        return envelope

    @staticmethod
    def _workspace_execution_protocol() -> str:
        """加载工作区执行模式追加契约；文件缺失时返回兜底摘要。"""
        try:
            return _WORKSPACE_EXEC_PROTOCOL_PATH.read_text(encoding="utf-8")
        except OSError:
            return "仅可在分配工作目录内写入；不得修改数据库、任务或工作流。\n"

    @staticmethod
    def _build_instruction(
        *,
        question: str,
        capability: str,
        evidence_refs: list[str],
        requested_tools: list[str],
        execution_mode: str,
        hard_gate: dict[str, Any] | None,
    ) -> str:
        if execution_mode == "workspace_execution":
            mode_clause = f"\n{AgentConsultationService._workspace_execution_protocol()}\n"
            envelope_clause = ""
        else:
            mode_clause = "不得修改文件、数据库、任务或工作流。\n"
            envelope_clause = (
                "最终答复必须只包含一个 ```json 代码块，结构为："
                '{"conclusion":"非空结论","recommendations":[],"evidence_refs":[],"risks":[],'
                '"token_usage":0,"proposed_submission":null,"artifacts":[],"hard_gate":null}。'
                "evidence_refs 只允许填写本回合工具成功读取后产生的已核验引用。规划能力调用时 "
                "proposed_submission 按 Case 类型输出：流程型 Case 输出可校验的 TaskSpec "
                "参数对象；无 flow_id 的通用 Case 输出 "
                '{"name": ..., "parameters": {"work_items": [{"work_item_id", "target", '
                '"objective", "skill_name", "execution_mode": "workspace_execution", '
                '"depends_on": []}]}, "quality_gate_required": bool}，target 限声明了 '
                "workspace_execution 的 worker（如 agent-viz、agent-code）。"
                "quality_gate_required 必须显式填写 true/false；只有 true 才会创建独立质控阶段。"
            )
        hard_gate_clause = (
            f"\n硬规则预判：{json.dumps(hard_gate, ensure_ascii=False)}\n"
            "不得把硬规则 BLOCKED 降级为 WARNING/PASSED，也不得把 WARNING 降级为 PASSED。"
            if hard_gate
            else ""
        )
        return (
            "你正在执行 AgentTeams 受控专业会诊。\n"
            + mode_clause
            + f"\n能力：{capability}\n问题：{question}\n"
            f"待核验引用：{json.dumps(evidence_refs, ensure_ascii=False)}\n"
            f"获准请求的只读工具：{json.dumps(requested_tools, ensure_ascii=False)}\n"
            "凡在结论中引用 task: 或 file:，必须先调用对应只读工具读取；禁止仅凭引用字符串猜测内容。\n"
            + hard_gate_clause
            + envelope_clause
        )

    async def _evaluate_hard_gate(
        self,
        *,
        capability: str,
        evidence_refs: list[str],
        requester_ref: str,
        case_id: str,
    ) -> dict[str, Any] | None:
        if capability != "quality-gate":
            return None
        task_id = next(
            (ref.removeprefix("task:") for ref in evidence_refs if ref.startswith("task:")),
            None,
        )
        if not task_id:
            return None
        try:
            UUID(task_id)
        except ValueError:
            return None
        context = ToolInvocationContext(
            user_id=requester_ref,
            agent_id="agent-qc",
            session_id=f"agentteams:{case_id}:hard-gate",
            db=self._db,
        )
        summary = await PipelineResultService(context).get_task_summary(task_id)
        return AgentTeamsQualityGateService().evaluate(
            str(summary.get("flow_id") or ""), summary.get("metrics") or {}
        )

    @staticmethod
    def _verified_evidence_refs(result: dict[str, Any]) -> list[str]:
        results = (result.get("llm_payload") or {}).get("results") or []
        if not results or not isinstance(results[0], dict):
            return []
        refs = results[0].get("verified_evidence_refs") or []
        return list(dict.fromkeys(str(ref) for ref in refs if str(ref).strip()))[:100]

    @staticmethod
    def _enforce_hard_gate(envelope: ConsultationEnvelope) -> None:
        if not envelope.hard_gate:
            return
        decision = str(envelope.hard_gate.get("decision") or "")
        first_line = envelope.conclusion.splitlines()[0].strip().upper()
        if decision == "BLOCKED" and first_line != "BLOCKED":
            envelope.conclusion = f"BLOCKED\n{envelope.conclusion}"[:8_000]
        elif decision == "WARNING" and first_line == "PASSED":
            envelope.conclusion = f"WARNING\n{envelope.conclusion}"[:8_000]

    async def _register_workspace_artifacts(
        self, requester_ref: str, case_id: str, work_item_id: str, workdir: Path
    ) -> tuple[list[dict[str, Any]], list[str]]:
        try:
            user_id = UUID(str(requester_ref))
        except ValueError:
            return [], ["产物登记失败：requester_ref 不是有效用户 UUID。"]
        if not workdir.exists():
            return [], []

        # 解析 Case 所属团队；失败则回退为个人空间（不影响登记流程）
        owner_scope = OwnerScope.PERSONAL.value
        team_id: UUID | None = None
        case_service = self._agentteams_service
        if case_service is None:
            case_service = AgentTeamsService(get_settings())
        try:
            case = await case_service.get_case(case_id, requester_ref)
            raw_team = case.get("team_id")
            if raw_team and str(raw_team) not in ("", "unassigned"):
                team_id = UUID(str(raw_team))
                owner_scope = OwnerScope.TEAM.value
        except Exception as exc:  # noqa: BLE001
            logger.bind(case_id=case_id, requester_ref=requester_ref).warning(
                "获取 Case 团队信息失败，产物按个人空间登记: {}", exc
            )

        factory = get_path_factory()
        destination = (
            factory.user_root(str(user_id)) / "workspace" / "agentteams" / case_id / work_item_id
        )
        repository = FileRepositoryImpl(self._db)
        artifacts: list[dict[str, Any]] = []
        errors: list[str] = []
        sources = sorted(
            path for path in workdir.rglob("*") if path.is_file() and not path.is_symlink()
        )[:100]
        for source in sources:
            try:
                relative = source.relative_to(workdir)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                digest = hashlib.sha256()
                with source.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                sha256 = digest.hexdigest()
                record = await repository.save(
                    DataFile(
                        id=uuid4(),
                        user_id=user_id,
                        path=factory.relative_to_root(target),
                        original_name=source.name,
                        size=source.stat().st_size,
                        checksum=sha256,
                        file_type=FileType.OTHER,
                        directory=f"workspace/agentteams/{case_id}/{work_item_id}",
                        source="agentteams",
                        owner_scope=owner_scope,
                        team_id=team_id,
                    )
                )
                artifact = {
                    "id": str(record.id),
                    "path": record.path,
                    "kind": "file",
                    "bytes": record.size,
                    "size_bytes": record.size,
                    "sha256": sha256,
                    "download_url": f"/api/v1/files/{record.id}/download",
                }
                try:
                    artifact["s3_uri"] = self._minio_store.put_case_object(
                        case_id, f"{work_item_id}/{relative.as_posix()}", target
                    )
                except (BusinessError, OSError, ValueError) as exc:
                    logger.bind(
                        event_type="artifact.s3_upload_failed",
                        case_id=case_id,
                        work_item_id=work_item_id,
                        local_path=record.path,
                    ).warning("AgentTeams artifact S3 upload failed: {}", exc)
                artifacts.append(artifact)
            except (OSError, ValueError) as exc:
                errors.append(f"产物登记失败（{source.name}）：{exc}")
        return artifacts, errors

    @staticmethod
    def _extract_answer(result: dict[str, Any]) -> str:
        results = (result.get("llm_payload") or {}).get("results") or []
        if results and isinstance(results[0], dict):
            answer = str(results[0].get("answer") or "").strip()
            if answer:
                return answer
            error = str(results[0].get("error") or "").strip()
            if error:
                return error
        return str((result.get("llm_payload") or {}).get("summary") or "会诊未返回内容")

    @staticmethod
    def parse_envelope(raw_answer: str) -> ConsultationEnvelope:
        return AgentConsultationService._parse_envelope_with_status(raw_answer)[0]

    @staticmethod
    def _parse_envelope_with_status(raw_answer: str) -> tuple[ConsultationEnvelope, bool]:
        raw_answer = raw_answer.strip() or "会诊未返回内容"
        match = _JSON_FENCE_RE.search(raw_answer)
        candidate = match.group(1) if match else raw_answer
        try:
            payload = json.loads(candidate)
            if not isinstance(payload, dict):
                raise ValueError("consultation envelope must be an object")
            return ConsultationEnvelope.model_validate(payload), True
        except (json.JSONDecodeError, ValueError):
            return ConsultationEnvelope(
                conclusion=raw_answer[:8_000],
                risks=["信封解析降级：专家答复未满足结构化 JSON 契约。"],
            ), False

    async def _record_usage(
        self,
        *,
        result: dict[str, Any],
        envelope: ConsultationEnvelope,
        case_id: str,
        agent_id: str,
        requester_ref: str,
        context: Any,
    ) -> None:
        """协作室 LLM 用量落库与饼干扣费（best-effort，绝不阻断会诊主流程）。"""
        try:
            await record_consultation_usage(
                self._db,
                case_id=case_id,
                agent_id=agent_id,
                requester_ref=requester_ref,
                usage=result.get("usage"),
                conclusion=envelope.conclusion,
                model_config=context.model_config,
                agentteams_service=self._agentteams_service,
            )
        except Exception as exc:  # noqa: BLE001
            logger.bind(case_id=case_id, agent_id=agent_id).warning(
                "AgentTeams consultation usage record failed: {}", exc
            )

    async def _record_telemetry(
        self,
        *,
        result: dict[str, Any],
        parse_success: bool,
        requested_refs: list[str],
        verified_refs: list[str],
        hard_gate: dict[str, Any] | None,
        conclusion: str,
    ) -> None:
        if self._telemetry_service is None:
            return
        rows = (result.get("llm_payload") or {}).get("results") or []
        first = rows[0] if rows and isinstance(rows[0], dict) else {}
        requested = set(requested_refs)
        verified = set(verified_refs)
        decision = str((hard_gate or {}).get("decision") or "").upper()
        first_line = conclusion.splitlines()[0].strip().upper()
        await self._telemetry_service.record(
            parse_success=parse_success,
            tool_call_count=int(first.get("tool_call_count") or 0),
            evidence_requested=len(requested),
            evidence_verified=len(requested & verified),
            qc_checked=bool(decision),
            qc_consistent=bool(decision and first_line == decision),
        )
