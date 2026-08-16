"""Celery maintenance tasks for MAS event publication."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from uuid import UUID

from celery import shared_task

from omichub.infrastructure.mas.redis_streams import RedisStreamConsumer


@shared_task(name="omichub.infrastructure.celery_app.tasks.mas.publish_outbox")
def publish_outbox() -> dict[str, int]:
    return asyncio.run(_publish_outbox())


async def _publish_outbox() -> dict[str, int]:
    from omichub.application.services.a2a_event_service import A2AEventService
    from omichub.infrastructure.database.session import get_session_factory

    async with get_session_factory()() as session:
        count = await A2AEventService(session).publish_pending()
        await session.commit()
        return {"published": count}


@shared_task(name="omichub.infrastructure.celery_app.tasks.mas.consume_events")
def consume_events() -> dict[str, int]:
    return asyncio.run(_consume_events())


async def _consume_events() -> dict[str, int]:
    from omichub.application.services.mas_event_consumer_service import MASEventConsumerService
    from omichub.infrastructure.database.session import get_session_factory

    consumer = RedisStreamConsumer()
    consumed = 0
    for message_id, event_id in await consumer.read("celery-scheduler"):
        async with get_session_factory()() as session:
            handled = await MASEventConsumerService(session).consume(UUID(event_id))
            await session.commit()
        if handled:
            consumed += 1
        await consumer.acknowledge(message_id)
    return {"consumed": consumed}


@shared_task(name="omichub.infrastructure.celery_app.tasks.mas.run_fake_node")
def run_fake_node(run_id: str, node_key: str) -> dict[str, str]:
    """Execute an explicit fake node for deterministic scheduler integration tests only."""
    return asyncio.run(_run_fake_node(UUID(run_id), node_key))


async def _run_fake_node(run_id: UUID, node_key: str) -> dict[str, str]:
    from omichub.application.services.a2a_event_service import A2AEventService
    from omichub.application.services.artifact_service import ArtifactService
    from omichub.core.config import get_settings
    from omichub.domain.mas.models import (
        A2AEvent,
        A2AEventType,
        AgentRecipient,
        AgentSender,
        ArtifactKind,
        MASArtifact,
        NodeState,
    )
    from omichub.domain.mas.workspace import WorkspaceLayout
    from omichub.infrastructure.database.repositories.mas_repository import MASRepository
    from omichub.infrastructure.database.session import get_session_factory

    async with get_session_factory()() as session:
        repository = MASRepository(session)
        node = await repository.get_node(run_id, node_key)
        if node is None or node.status != NodeState.DISPATCHED.value:
            return {"status": "ignored", "node_key": node_key}
        if not await repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status=NodeState.DISPATCHED.value,
            target_status=NodeState.RUNNING.value,
        ):
            return {"status": "contended", "node_key": node_key}

        state_version = node.version + 1
        events = A2AEventService(session)
        sender = AgentSender(kind="worker", id="mas-fake-agent", attempt_count=node.attempt_count)
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_STARTED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="running",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.started:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )

        workspace = WorkspaceLayout(get_settings().mas_workspace_root)
        output_path = workspace.resolve_container_path(
            run_id, f"/workspace/results/{node_key}.fake.json", require_writable=True
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"executor": "fake", "node_key": node_key, "intent": node.intent}, sort_keys=True
        ).encode()
        output_path.write_bytes(payload)
        artifact = ArtifactService(workspace).validate(
            MASArtifact(
                run_id=run_id,
                node_key=node_key,
                logical_name=f"{node_key}-fake-result",
                kind=ArtifactKind.FILE,
                workspace_path=str(output_path),
                media_type="application/json",
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                summary={"fake": True, "node_key": node_key},
            )
        )
        artifact_model = await repository.save_artifact(artifact)
        await events.record(
            A2AEvent(
                event_type=A2AEventType.ARTIFACT_VALIDATED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="validated",
                intent=node.intent,
                context_pointers={},
                summary={"message": "Fake executor artifact validated", "metrics": {"size_bytes": len(payload)}},
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"artifact.validated:{artifact_model.id}"
                ),
                state_version=state_version,
            )
        )
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_SUCCEEDED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="succeeded",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.succeeded:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )
        await session.commit()
        return {"status": "succeeded", "node_key": node_key}


@shared_task(name="omichub.infrastructure.celery_app.tasks.mas.rnaflow.run_node")
def run_rnaflow_node(run_id: str, node_key: str) -> dict[str, str]:
    """Run a validated RNAFlow node on the dedicated native Apptainer worker queue."""
    return asyncio.run(_run_rnaflow_node(UUID(run_id), node_key))


async def _run_rnaflow_node(run_id: UUID, node_key: str) -> dict[str, str]:
    from omichub.application.services.a2a_event_service import A2AEventService
    from omichub.application.services.artifact_service import ArtifactService
    from omichub.core.config import get_settings
    from omichub.domain.mas.models import (
        A2AEvent,
        A2AEventType,
        AgentRecipient,
        AgentSender,
        ArtifactKind,
        ArtifactPointer,
        MASArtifact,
        NodeState,
    )
    from omichub.domain.mas.workspace import WorkspaceLayout
    from omichub.infrastructure.database.repositories.mas_repository import MASRepository
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.infrastructure.mas.apptainer import build_rnaflow_command
    from omichub.infrastructure.mas.qc_metrics import QCMetricsError, extract_median_mapping_rate
    from omichub.infrastructure.mas.rnaflow import RNAFlowPreflightError, validate_mas_rnaflow_config

    async with get_session_factory()() as session:
        repository = MASRepository(session)
        node = await repository.get_node(run_id, node_key)
        if node is None or node.status != NodeState.DISPATCHED.value:
            return {"status": "ignored", "node_key": node_key}
        if not await repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status=NodeState.DISPATCHED.value,
            target_status=NodeState.RUNNING.value,
        ):
            return {"status": "contended", "node_key": node_key}

        settings = get_settings()
        workspace = WorkspaceLayout(settings.mas_workspace_root)
        state_version = node.version + 1
        sender = AgentSender(kind="worker", id="mas-apptainer-rnaflow", attempt_count=node.attempt_count)
        events = A2AEventService(session)
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_STARTED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="running",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.started:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )

        artifacts = ArtifactService(workspace)
        log_path = workspace.resolve_container_path(
            run_id, f"/workspace/logs/{node_key}.apptainer.log", require_writable=True
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            validate_mas_rnaflow_config(workspace, run_id)
            command = build_rnaflow_command(
                binary=settings.mas_apptainer_binary,
                image=settings.mas_apptainer_image,
                workspace=workspace,
                run_id=run_id,
                pipeline_root=settings.mas_apptainer_pipeline_root,
            )
            result = await asyncio.to_thread(_run_command_to_log, command, log_path)
            if result.returncode != 0:
                log_artifact = await _save_validated_file_artifact(
                    repository,
                    artifacts,
                    run_id,
                    node_key,
                    f"{node_key}-apptainer-log",
                    log_path,
                    "text/plain",
                )
                await _record_node_failure(
                    events,
                    run_id,
                    node,
                    sender,
                    state_version,
                    "RNAFLOW_EXECUTION_FAILED",
                    f"RNAFlow exited with status {result.returncode}; see diagnostic log artifact.",
                    log_artifact.id,
                    f"/workspace/logs/{node_key}.apptainer.log",
                )
                await session.commit()
                return {"status": "failed", "node_key": node_key}
        except (RNAFlowPreflightError, OSError, subprocess.TimeoutExpired) as exc:
            log_path.write_text(str(exc), encoding="utf-8")
            log_artifact = await _save_validated_file_artifact(
                repository,
                artifacts,
                run_id,
                node_key,
                f"{node_key}-apptainer-log",
                log_path,
                "text/plain",
            )
            await _record_node_failure(
                events,
                run_id,
                node,
                sender,
                state_version,
                "RNAFLOW_INPUT_INVALID",
                "RNAFlow preflight failed; provide or correct the requested workflow inputs.",
                log_artifact.id,
                f"/workspace/logs/{node_key}.apptainer.log",
            )
            await session.commit()
            return {"status": "failed", "node_key": node_key}

        manifest_path = workspace.resolve_container_path(run_id, "/workspace/results/delivery_manifest.json")
        if not manifest_path.is_file():
            log_artifact = await _save_validated_file_artifact(
                repository,
                artifacts,
                run_id,
                node_key,
                f"{node_key}-apptainer-log",
                log_path,
                "text/plain",
            )
            await _record_node_failure(
                events,
                run_id,
                node,
                sender,
                state_version,
                "RNAFLOW_DELIVERY_MANIFEST_MISSING",
                "RNAFlow completed without the required delivery_manifest.json artifact.",
                log_artifact.id,
                f"/workspace/logs/{node_key}.apptainer.log",
            )
            await session.commit()
            return {"status": "failed", "node_key": node_key}
        try:
            median_mapping_rate = await asyncio.to_thread(
                extract_median_mapping_rate,
                workspace.resolve_container_path(run_id, "/workspace/results"),
            )
            qc_metrics_path = workspace.resolve_container_path(
                run_id, "/workspace/results/qc_metrics.json", require_writable=True
            )
            qc_metrics_path.write_text(
                json.dumps({"median_mapping_rate": median_mapping_rate}, sort_keys=True), encoding="utf-8"
            )
        except QCMetricsError as exc:
            log_path.write_text(f"{log_path.read_text(encoding='utf-8')}\nQC metrics: {exc}\n", encoding="utf-8")
            log_artifact = await _save_validated_file_artifact(
                repository,
                artifacts,
                run_id,
                node_key,
                f"{node_key}-apptainer-log",
                log_path,
                "text/plain",
            )
            await _record_node_failure(
                events,
                run_id,
                node,
                sender,
                state_version,
                "RNAFLOW_QC_METRICS_MISSING",
                "RNAFlow finished but no usable mapping-rate summary was found.",
                log_artifact.id,
                f"/workspace/logs/{node_key}.apptainer.log",
            )
            await session.commit()
            return {"status": "failed", "node_key": node_key}
        log_artifact = await _save_validated_file_artifact(
            repository,
            artifacts,
            run_id,
            node_key,
            f"{node_key}-apptainer-log",
            log_path,
            "text/plain",
        )
        manifest_artifact = await _save_validated_file_artifact(
            repository,
            artifacts,
            run_id,
            node_key,
            f"{node_key}-delivery-manifest",
            manifest_path,
            "application/json",
        )
        await events.record(
            A2AEvent(
                event_type=A2AEventType.ARTIFACT_VALIDATED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="validated",
                intent=node.intent,
                context_pointers={
                    "delivery_manifest": ArtifactPointer(
                        artifact_id=manifest_artifact.id,
                        container_path="/workspace/results/delivery_manifest.json",
                        media_type="application/json",
                    ),
                    "diagnostic_log": ArtifactPointer(
                        artifact_id=log_artifact.id,
                        container_path=f"/workspace/logs/{node_key}.apptainer.log",
                        media_type="text/plain",
                    ),
                },
                summary={"message": "RNAFlow delivery manifest validated"},
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"artifact.validated:{manifest_artifact.id}"
                ),
                state_version=state_version,
            )
        )
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_SUCCEEDED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="succeeded",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.succeeded:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )
        await session.commit()
        return {"status": "succeeded", "node_key": node_key}


async def _save_validated_file_artifact(
    repository,
    artifacts,
    run_id: UUID,
    node_key: str,
    logical_name: str,
    path,
    media_type: str,
):
    from omichub.domain.mas.models import ArtifactKind, MASArtifact

    payload = path.read_bytes()
    artifact = artifacts.validate(
        MASArtifact(
            run_id=run_id,
            node_key=node_key,
            logical_name=logical_name,
            kind=ArtifactKind.FILE,
            workspace_path=str(path),
            media_type=media_type,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
    )
    return await repository.save_artifact(artifact)


async def _record_node_failure(
    events,
    run_id: UUID,
    node,
    sender,
    state_version: int,
    error_code: str,
    message: str,
    diagnostic_artifact_id,
    diagnostic_container_path: str,
) -> None:
    from omichub.domain.mas.models import A2AEvent, A2AEventType, AgentRecipient, ArtifactPointer

    await events.record(
        A2AEvent(
            event_type=A2AEventType.NODE_FAILED,
            trace_id=f"mas:{run_id}",
            run_id=run_id,
            node_key=node.node_key,
            sender=sender,
            recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
            status="failed",
            intent=node.intent,
            context_pointers={
                "diagnostic_log": ArtifactPointer(
                    artifact_id=diagnostic_artifact_id,
                    container_path=diagnostic_container_path,
                    media_type="text/plain",
                )
            },
            summary={"message": message, "metrics": {"error_code": error_code}},
            dedupe_key=(
                f"{run_id}:{node.node_key}:attempt_{node.attempt_count}:"
                f"node.failed:{error_code}:state_version_{state_version}"
            ),
            state_version=state_version,
        )
    )


@shared_task(name="omichub.infrastructure.celery_app.tasks.mas.volcano.run_node")
def run_volcano_node(run_id: str, node_key: str) -> dict[str, str]:
    """Render a workspace-scoped DEG artifact into PNG and PDF outputs."""
    return asyncio.run(_run_volcano_node(UUID(run_id), node_key))


async def _run_volcano_node(run_id: UUID, node_key: str) -> dict[str, str]:
    from omichub.application.services.a2a_event_service import A2AEventService
    from omichub.application.services.artifact_service import ArtifactService
    from omichub.core.config import get_settings
    from omichub.domain.mas.models import (
        A2AEvent,
        A2AEventType,
        AgentRecipient,
        AgentSender,
        ArtifactPointer,
        NodeState,
    )
    from omichub.domain.mas.workspace import WorkspaceLayout
    from omichub.infrastructure.database.repositories.mas_repository import MASRepository
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.infrastructure.mas.volcano import VolcanoPlotError, render_deg_volcano

    async with get_session_factory()() as session:
        repository = MASRepository(session)
        node = await repository.get_node(run_id, node_key)
        if node is None or node.status != NodeState.DISPATCHED.value:
            return {"status": "ignored", "node_key": node_key}
        if not await repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status=NodeState.DISPATCHED.value,
            target_status=NodeState.RUNNING.value,
        ):
            return {"status": "contended", "node_key": node_key}

        workspace = WorkspaceLayout(get_settings().mas_workspace_root)
        events = A2AEventService(session)
        state_version = node.version + 1
        sender = AgentSender(kind="worker", id="mas-deg-volcano", attempt_count=node.attempt_count)
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_STARTED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="running",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.started:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )
        log_path = workspace.resolve_container_path(
            run_id, f"/workspace/logs/{node_key}.volcano.log", require_writable=True
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        artifacts = ArtifactService(workspace)
        input_path_value = str(node.parameters.get("deg_input_path", "/workspace/results/deg.csv"))
        try:
            if not input_path_value.startswith("/workspace/results/"):
                raise VolcanoPlotError("deg_input_path must be below /workspace/results")
            input_path = workspace.resolve_container_path(run_id, input_path_value)
            result = await asyncio.to_thread(
                render_deg_volcano,
                input_path,
                workspace.resolve_container_path(run_id, "/workspace/plots", require_writable=True),
            )
            log_path.write_text(
                f"Rendered {result.total} DEG rows; up={result.up}; down={result.down}\n", encoding="utf-8"
            )
        except (OSError, VolcanoPlotError) as exc:
            log_path.write_text(str(exc), encoding="utf-8")
            log_artifact = await _save_validated_file_artifact(
                repository, artifacts, run_id, node_key, f"{node_key}-volcano-log", log_path, "text/plain"
            )
            await _record_node_failure(
                events,
                run_id,
                node,
                sender,
                state_version,
                "DEG_SCHEMA_MISSING_REQUIRED_COLUMNS",
                "Unable to render the DEG artifact; review the input schema and retry.",
                log_artifact.id,
                f"/workspace/logs/{node_key}.volcano.log",
            )
            await session.commit()
            return {"status": "failed", "node_key": node_key}

        png_artifact = await _save_validated_file_artifact(
            repository, artifacts, run_id, node_key, f"{node_key}-volcano-png", result.png_path, "image/png"
        )
        pdf_artifact = await _save_validated_file_artifact(
            repository, artifacts, run_id, node_key, f"{node_key}-volcano-pdf", result.pdf_path, "application/pdf"
        )
        await events.record(
            A2AEvent(
                event_type=A2AEventType.ARTIFACT_VALIDATED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="validated",
                intent=node.intent,
                context_pointers={
                    "volcano_png": ArtifactPointer(artifact_id=png_artifact.id, container_path="/workspace/plots/deg-volcano.png", media_type="image/png"),
                    "volcano_pdf": ArtifactPointer(artifact_id=pdf_artifact.id, container_path="/workspace/plots/deg-volcano.pdf", media_type="application/pdf"),
                },
                summary={"message": "Volcano PNG and PDF validated"},
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"artifact.validated:{png_artifact.id}"
                ),
                state_version=state_version,
            )
        )
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_SUCCEEDED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="succeeded",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.succeeded:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )
        await session.commit()
        return {"status": "succeeded", "node_key": node_key}


@shared_task(name="omichub.infrastructure.celery_app.tasks.mas.quality_gate.run_node")
def run_quality_gate_node(run_id: str, node_key: str) -> dict[str, str]:
    """Evaluate a compact QC summary and gate downstream visualization nodes."""
    return asyncio.run(_run_quality_gate_node(UUID(run_id), node_key))


async def _run_quality_gate_node(run_id: UUID, node_key: str) -> dict[str, str]:
    from omichub.application.services.a2a_event_service import A2AEventService
    from omichub.application.services.artifact_service import ArtifactService
    from omichub.core.config import get_settings
    from omichub.domain.mas.models import (
        A2AEvent,
        A2AEventType,
        AgentRecipient,
        AgentSender,
        ArtifactPointer,
        NodeState,
    )
    from omichub.domain.mas.quality_gate import QCOverrideRequest, apply_qc_override, evaluate_mapping_rate
    from omichub.domain.mas.workspace import WorkspaceLayout
    from omichub.infrastructure.database.repositories.mas_repository import MASRepository
    from omichub.infrastructure.database.session import get_session_factory

    async with get_session_factory()() as session:
        repository = MASRepository(session)
        node = await repository.get_node(run_id, node_key)
        if node is None or node.status != NodeState.DISPATCHED.value:
            return {"status": "ignored", "node_key": node_key}
        if not await repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status=NodeState.DISPATCHED.value,
            target_status=NodeState.RUNNING.value,
        ):
            return {"status": "contended", "node_key": node_key}

        workspace = WorkspaceLayout(get_settings().mas_workspace_root)
        events = A2AEventService(session)
        artifacts = ArtifactService(workspace)
        state_version = node.version + 1
        sender = AgentSender(kind="worker", id="mas-quality-gate", attempt_count=node.attempt_count)
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_STARTED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="running",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.started:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )
        log_path = workspace.resolve_container_path(
            run_id, f"/workspace/logs/{node_key}.quality-gate.log", require_writable=True
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            metrics_path_value = str(node.parameters.get("qc_metrics_path", "/workspace/results/qc_metrics.json"))
            if not metrics_path_value.startswith("/workspace/results/"):
                raise ValueError("qc_metrics_path must be below /workspace/results")
            metrics_path = workspace.resolve_container_path(run_id, metrics_path_value)
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            mapping_rate = float(metrics["median_mapping_rate"])
            result = evaluate_mapping_rate(mapping_rate)
            override_reason = node.parameters.get("qc_override_reason")
            if override_reason:
                result = apply_qc_override(result, QCOverrideRequest(reason=str(override_reason)))
            gate_path = workspace.resolve_container_path(
                run_id, "/workspace/results/qc-gate.json", require_writable=True
            )
            gate_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
            log_path.write_text(result.reason, encoding="utf-8")
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            log_path.write_text(str(exc), encoding="utf-8")
            log_artifact = await _save_validated_file_artifact(
                repository, artifacts, run_id, node_key, f"{node_key}-quality-log", log_path, "text/plain"
            )
            await _record_node_failure(
                events,
                run_id,
                node,
                sender,
                state_version,
                "INPUT_NOT_FOUND",
                "QC summary is missing or invalid.",
                log_artifact.id,
                f"/workspace/logs/{node_key}.quality-gate.log",
            )
            await session.commit()
            return {"status": "failed", "node_key": node_key}

        gate_artifact = await _save_validated_file_artifact(
            repository, artifacts, run_id, node_key, f"{node_key}-quality-gate", gate_path, "application/json"
        )
        await events.record(
            A2AEvent(
                event_type=A2AEventType.ARTIFACT_VALIDATED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="validated",
                intent=node.intent,
                context_pointers={
                    "quality_gate": ArtifactPointer(
                        artifact_id=gate_artifact.id,
                        container_path="/workspace/results/qc-gate.json",
                        media_type="application/json",
                    )
                },
                summary={
                    "message": result.reason,
                    "metrics": {"median_mapping_rate": result.observed_value, "qc_status": result.status.value},
                },
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"artifact.validated:{gate_artifact.id}"
                ),
                state_version=state_version,
            )
        )
        if not result.allows_downstream_visualization:
            await _record_node_failure(
                events,
                run_id,
                node,
                sender,
                state_version,
                "QUALITY_GATE_FAILED",
                result.reason,
                gate_artifact.id,
                "/workspace/results/qc-gate.json",
            )
            await session.commit()
            return {"status": "waiting_approval", "node_key": node_key}
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_SUCCEEDED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="succeeded",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.succeeded:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )
        await session.commit()
        return {"status": "succeeded", "node_key": node_key}


@shared_task(name="omichub.infrastructure.celery_app.tasks.mas.ebi_download.run_node")
def run_ebi_download_node(run_id: str, node_key: str) -> dict[str, str]:
    """Download public sequencing data into the current MAS Run staging directory."""
    return asyncio.run(_run_ebi_download_node(UUID(run_id), node_key))


async def _run_ebi_download_node(run_id: UUID, node_key: str) -> dict[str, str]:
    from omichub.application.services.a2a_event_service import A2AEventService
    from omichub.application.services.artifact_service import ArtifactService
    from omichub.core.config import get_settings
    from omichub.domain.mas.models import (
        A2AEvent,
        A2AEventType,
        AgentRecipient,
        AgentSender,
        ArtifactPointer,
        NodeState,
    )
    from omichub.domain.mas.workspace import WorkspaceLayout
    from omichub.infrastructure.database.repositories.mas_repository import MASRepository
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.infrastructure.mas.ebi import EBIDownloadError, build_ebi_download_command, write_download_manifest

    async with get_session_factory()() as session:
        repository = MASRepository(session)
        node = await repository.get_node(run_id, node_key)
        if node is None or node.status != NodeState.DISPATCHED.value:
            return {"status": "ignored", "node_key": node_key}
        if not await repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status=NodeState.DISPATCHED.value,
            target_status=NodeState.RUNNING.value,
        ):
            return {"status": "contended", "node_key": node_key}

        settings = get_settings()
        workspace = WorkspaceLayout(settings.mas_workspace_root)
        events = A2AEventService(session)
        artifacts = ArtifactService(workspace)
        state_version = node.version + 1
        sender = AgentSender(kind="worker", id="mas-ebi-download", attempt_count=node.attempt_count)
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_STARTED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="running",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.started:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )
        staging_path = workspace.resolve_container_path(
            run_id, "/workspace/staging", require_writable=True
        )
        log_path = workspace.resolve_container_path(
            run_id, f"/workspace/logs/{node_key}.ebi-download.log", require_writable=True
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            command = build_ebi_download_command(
                binary=settings.ebi_download_binary,
                yaml_path=settings.ebi_download_yaml,
                accession=str(node.parameters["accession"]),
                output_directory=staging_path,
                method=str(node.parameters.get("download_method", "aws")),
                multithreads=int(node.parameters.get("multithreads", 4)),
                aws_threads=int(node.parameters.get("aws_threads", 8)),
            )
            result = await asyncio.to_thread(_run_command_to_log, command, log_path)
            if result.returncode != 0:
                raise EBIDownloadError(f"EBIDownload exited with status {result.returncode}")
            manifest_path = staging_path / "fastq-manifest.json"
            manifest = await asyncio.to_thread(
                write_download_manifest, staging_path, manifest_path, str(node.parameters["accession"])
            )
        except (EBIDownloadError, KeyError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            if not log_path.exists():
                log_path.write_text(str(exc), encoding="utf-8")
            else:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"\n{exc}\n")
            log_artifact = await _save_validated_file_artifact(
                repository, artifacts, run_id, node_key, f"{node_key}-download-log", log_path, "text/plain"
            )
            await _record_node_failure(
                events,
                run_id,
                node,
                sender,
                state_version,
                "NETWORK_TIMEOUT",
                "EBIDownload failed; the node will retry within its configured budget.",
                log_artifact.id,
                f"/workspace/logs/{node_key}.ebi-download.log",
            )
            await session.commit()
            return {"status": "failed", "node_key": node_key}

        manifest_artifact = await _save_validated_file_artifact(
            repository, artifacts, run_id, node_key, f"{node_key}-fastq-manifest", manifest_path, "application/json"
        )
        await events.record(
            A2AEvent(
                event_type=A2AEventType.ARTIFACT_VALIDATED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="validated",
                intent=node.intent,
                context_pointers={
                    "fastq_manifest": ArtifactPointer(
                        artifact_id=manifest_artifact.id,
                        container_path="/workspace/staging/fastq-manifest.json",
                        media_type="application/json",
                    )
                },
                summary={"message": "EBIDownload manifest validated", "metrics": {"file_count": len(manifest["files"])}},
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"artifact.validated:{manifest_artifact.id}"
                ),
                state_version=state_version,
            )
        )
        await events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_SUCCEEDED,
                trace_id=f"mas:{run_id}",
                run_id=run_id,
                node_key=node_key,
                sender=sender,
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="succeeded",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node_key}:attempt_{node.attempt_count}:"
                    f"node.succeeded:state_version_{state_version}"
                ),
                state_version=state_version,
            )
        )
        await session.commit()
        return {"status": "succeeded", "node_key": node_key}


def _run_command_to_log(command: list[str], log_path) -> subprocess.CompletedProcess[str]:
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(command)}\n\n")
        handle.flush()
        return subprocess.run(
            command,
            check=False,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=86_400,
        )

@shared_task(name="omichub.infrastructure.celery_app.tasks.mas.scanpy_qc.run_node")
def run_scanpy_qc_node(run_id: str, node_key: str) -> dict[str, str]:
    return asyncio.run(_run_scanpy_qc_node(UUID(run_id), node_key))


async def _run_scanpy_qc_node(run_id: UUID, node_key: str) -> dict[str, str]:
    from omichub.application.services.a2a_event_service import A2AEventService
    from omichub.application.services.artifact_service import ArtifactService
    from omichub.core.config import get_settings
    from omichub.domain.mas.models import A2AEvent, A2AEventType, AgentRecipient, AgentSender, ArtifactPointer, NodeState
    from omichub.domain.mas.workspace import WorkspaceLayout
    from omichub.infrastructure.database.repositories.mas_repository import MASRepository
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.infrastructure.mas.scanpy import ScanpyQCError, build_scanpy_qc_command

    async with get_session_factory()() as session:
        repository = MASRepository(session)
        node = await repository.get_node(run_id, node_key)
        if node is None or node.status != NodeState.DISPATCHED.value:
            return {"status": "ignored", "node_key": node_key}
        if not await repository.transition_node(node_id=node.id, expected_version=node.version, current_status=NodeState.DISPATCHED.value, target_status=NodeState.RUNNING.value):
            return {"status": "contended", "node_key": node_key}
        settings = get_settings()
        workspace = WorkspaceLayout(settings.mas_workspace_root)
        events, artifacts = A2AEventService(session), ArtifactService(workspace)
        version = node.version + 1
        sender = AgentSender(kind="worker", id="mas-scanpy-qc", attempt_count=node.attempt_count)
        await events.record(A2AEvent(event_type=A2AEventType.NODE_STARTED, trace_id=f"mas:{run_id}", run_id=run_id, node_key=node_key, sender=sender, recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"), status="running", intent=node.intent, dedupe_key=f"{run_id}:{node_key}:attempt_{node.attempt_count}:node.started:state_version_{version}", state_version=version))
        log_path = workspace.resolve_container_path(run_id, f"/workspace/logs/{node_key}.scanpy.log", require_writable=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            command = build_scanpy_qc_command(workspace, run_id, str(node.parameters.get("input_h5ad_path", "")), int(node.parameters.get("min_genes", 200)), int(node.parameters.get("min_cells", 3)), settings.mas_scrna_docker_image)
            process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            output, _ = await asyncio.wait_for(process.communicate(), timeout=settings.mas_scrna_timeout_seconds)
            log_path.write_bytes(output or b"")
            if process.returncode != 0:
                raise ScanpyQCError(f"scanpy container exited with {process.returncode}")
            h5ad = workspace.resolve_container_path(run_id, "/workspace/results/scrna_qc_filtered.h5ad")
            metrics = workspace.resolve_container_path(run_id, "/workspace/results/scrna_qc_metrics.json")
            if not h5ad.is_file() or not metrics.is_file():
                raise ScanpyQCError("scanpy container did not produce required artifacts")
        except (OSError, ScanpyQCError, TimeoutError, ValueError) as exc:
            log_path.write_text(f"{log_path.read_text(encoding='utf-8') if log_path.exists() else ''}\n{exc}\n", encoding="utf-8")
            log = await _save_validated_file_artifact(repository, artifacts, run_id, node_key, f"{node_key}-scanpy-log", log_path, "text/plain")
            await _record_node_failure(events, run_id, node, sender, version, "SCANPY_QC_FAILED", "Scanpy QC failed; inspect the diagnostic log and retry.", log.id, f"/workspace/logs/{node_key}.scanpy.log")
            await session.commit()
            return {"status": "failed", "node_key": node_key}
        h5ad_artifact = await _save_validated_file_artifact(repository, artifacts, run_id, node_key, f"{node_key}-filtered-h5ad", h5ad, "application/x-hdf5")
        metrics_artifact = await _save_validated_file_artifact(repository, artifacts, run_id, node_key, f"{node_key}-qc-metrics", metrics, "application/json")
        await events.record(A2AEvent(event_type=A2AEventType.ARTIFACT_VALIDATED, trace_id=f"mas:{run_id}", run_id=run_id, node_key=node_key, sender=sender, recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"), status="validated", intent=node.intent, context_pointers={"filtered_h5ad": ArtifactPointer(artifact_id=h5ad_artifact.id, container_path="/workspace/results/scrna_qc_filtered.h5ad", media_type="application/x-hdf5"), "qc_metrics": ArtifactPointer(artifact_id=metrics_artifact.id, container_path="/workspace/results/scrna_qc_metrics.json", media_type="application/json")}, summary={"message": "Scanpy QC artifacts validated"}, dedupe_key=f"{run_id}:{node_key}:attempt_{node.attempt_count}:artifact.validated:{h5ad_artifact.id}", state_version=version))
        await events.record(A2AEvent(event_type=A2AEventType.NODE_SUCCEEDED, trace_id=f"mas:{run_id}", run_id=run_id, node_key=node_key, sender=sender, recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"), status="succeeded", intent=node.intent, dedupe_key=f"{run_id}:{node_key}:attempt_{node.attempt_count}:node.succeeded:state_version_{version}", state_version=version))
        await session.commit()
        return {"status": "succeeded", "node_key": node_key}
