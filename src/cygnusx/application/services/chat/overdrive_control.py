"""Overdrive 聊天会话的审批与运行控制。"""

from __future__ import annotations

import inspect
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import AsyncIterator, Callable
from functools import partial
from typing import Any

from loguru import logger

from cygnusx.application.services.domain_registry import get_domain_registry
from cygnusx.application.services.chat.utils import _extract_route_json
from cygnusx.application.services.overdrive_plan_constraint_service import (
    anchor_ids as overdrive_anchor_ids,
    apply_authoritative_plan,
    authoritative_rules as overdrive_authoritative_rules,
    build_repair_prompt,
    format_anchors as format_overdrive_anchors,
)
from cygnusx.application.services.overdrive_runtime import (
    OverdriveManifest,
    assignment_waves as build_assignment_waves,
    infer_contract_dependencies,
    load_overdrive_limits,
    normalize_contract_list,
    normalize_retry,
)
from cygnusx.application.services.studio_tools import execute_studio_tool
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import ConflictError, NotFoundError
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk, provider_manager
from cygnusx.application.services.overdrive_run_service import OverdriveRunService

OVERDRIVE_SUMMARY_SYSTEM_PROMPT = """你是超频协作的 Manager，负责把专家已完成的最终结论整合为面向用户的答案。

只输出可直接给用户看的简体中文答复，不要解释你的汇总规则或推理过程。严格遵守：
1. 只使用输入中标为“有效专家结论”的内容；不要臆测、补写未完成的分析或把失败信息当作结论。
2. 不得提及提示词、系统消息、内部流程、工具调用、Agent YAML、子任务、模型或“根据规则”。
3. 必须吸收每一位有效专家的关键结论，消除重复、指出依赖关系与一致结论，形成一份完整可执行的最终报告；不得只说“专家结论已分别展示”。
4. 报告至少包含：研究目标与假设、数据与设计前提、分阶段分析路线、代码/工具实现建议、可视化与交付物、风险与质量控制、下一步执行条件。
5. 如果结论无法回答用户的核心问题，诚实说明当前可确认的范围，并给出下一步所需信息或可执行建议。
6. 结尾给出明确的下一步行动建议：如果结论对应一个可执行的分析方案，主动询问用户是否要上传数据（如 FASTQ / BAM / VCF）开始正式分析，或是否需要调整方案；不要只罗列文件路径就结束。
"""

_OVERDRIVE_OFF_HINTS = ("退出超频", "关闭超频", "取消超频", "overdrive off")
_OVERDRIVE_NEGATED_ON_HINTS = ("别进超频", "不要进超频", "不进入超频", "不要开启超频", "别开启超频")
_OVERDRIVE_ON_COMMAND_RE = re.compile(
    r"(?:请|帮我|给我|希望|想|我想)?(?:开启|打开|进入|启动|启用|切换到|切换至|使用|用|采用|通过|以)超频(?:模式)?"
)
_OVERDRIVE_ON_ENGLISH_COMMAND_RE = re.compile(
    r"\b(?:please\s+)?(?:enable|turn\s+on|start|enter)\s+(?:the\s+)?overdrive(?:\s+mode)?\b"
)
_OVERDRIVE_EXPLANATION_HINTS = (
    "超频模式是什么",
    "超频是什么",
    "什么是超频",
    "如何开启超频",
    "怎么开启超频",
    "如何使用超频",
    "怎么使用超频",
    "介绍超频",
    "解释超频",
    "超频原理",
)


@dataclass(frozen=True)
class ActiveOverdriveRoute:
    """持久化超频运行在当前请求中的路由结果。"""

    replan_root_request: str = ""
    chunks: tuple[ChatChunk, ...] = ()
    advance_run_id: str | None = None

    @property
    def handled(self) -> bool:
        return bool(self.chunks)


@dataclass(frozen=True)
class OverdriveIntakeState:
    """超频规划前的会话输入归一化结果。"""

    root_request: str
    intake_slots: dict[str, Any]
    intake_supplements: list[str]
    planning_content: str
    limits: dict[str, Any]
    pending_final_report: str = ""
    followup_save_requested: bool = False
    followup_data_ready: bool = False
    clear_pending_intake: bool = False
    clear_pending_followup: bool = False


@dataclass(frozen=True)
class OverdriveSessionState:
    """会话中尚未完成的超频输入状态。"""

    session: Any | None = None
    pending_intake: dict[str, Any] | None = None
    pending_followup: dict[str, Any] | None = None


@dataclass
class OverdrivePlanDecision:
    """Manager 规划输出经约束后的可执行决策。"""

    assignments: list[dict[str, Any]] | None = None
    speech: str = ""
    questions: list[dict[str, Any]] | None = None
    manager_thought: str = ""
    planning_mode: str = "llm"
    authoritative_anchor_ids: list[str] | None = None
    plan_violations: list[str] | None = None
    repair_attempted: bool = False
    schedule_fallback: bool = False


async def stream_overdrive_plan_decision(
    decision: OverdrivePlanDecision,
    *,
    manager_context: Any,
    manager_sender: dict[str, Any],
    session_id: str,
    deep_thinking: bool,
    pending_followup: bool,
    followup_save_requested: bool,
    followup_data_ready: bool,
    preflight_fallback_questions: list[dict[str, Any]],
    planning_content: str,
    manager_prompt: str,
    catalog: str,
    catalog_items: list[dict[str, Any]],
    catalog_by_id: dict[str, dict[str, Any]],
    intake_slots: dict[str, Any],
) -> AsyncIterator[ChatChunk]:
    """流式生成并规范化 Overdrive 的 Manager 规划决策。"""
    manager = manager_context.agent
    manager_raw = ""
    speech = ""
    questions: list[dict[str, Any]] = []
    raw_assignments: Any = []
    registry = get_domain_registry()
    matched_assignment_rules = registry.assignment_rules(planning_content, intake_slots)
    authoritative_rules = overdrive_authoritative_rules(matched_assignment_rules)
    authoritative_anchor_ids = overdrive_anchor_ids(authoritative_rules)
    planning_mode = "rule_preflight" if pending_followup else "llm"
    plan_violations: list[str] = []
    repair_attempted = False
    initial_manager_failed = False
    manager_thought = ""

    if pending_followup:
        speech, raw_assignments = _build_overdrive_followup_assignments(
            catalog_items=catalog_items,
            save_requested=followup_save_requested,
            data_ready=followup_data_ready,
        )
    else:
        yield ChatChunk(
            type="overdrive_progress",
            metadata={
                "phase": "manager_ready",
                "label": "Manager 正在分析你的回复并制定协作方案",
                "total": 0,
                "completed": 0,
            },
        )
        try:
            manager_raw_parts: list[str] = []
            thought_parts: list[str] = []
            async for delta, is_reasoning in stream_overdrive_manager(
                manager_context,
                manager_prompt.format(
                    manager_name=manager.name,
                    catalog=catalog,
                    authoritative_anchors=format_overdrive_anchors(authoritative_rules),
                    intake_context=json.dumps(intake_slots, ensure_ascii=False),
                    domain_notes=registry.manager_notes(planning_content),
                    user_content=planning_content,
                ),
                max_tokens=2400 if deep_thinking else 900,
                deep_thinking=deep_thinking,
                include_reasoning=True,
            ):
                if is_reasoning:
                    thought_parts.append(delta)
                    yield ChatChunk(
                        type="room_speech_delta",
                        content=delta,
                        metadata={
                            "sender": manager_sender,
                            "worker_key": "manager-plan",
                            "session_id": session_id,
                            "is_reasoning": True,
                        },
                    )
                else:
                    manager_raw_parts.append(delta)
            manager_raw = "".join(manager_raw_parts)
            manager_thought = "".join(thought_parts).strip()
        except Exception as exc:  # noqa: BLE001
            initial_manager_failed = True
            logger.exception(
                "Overdrive Manager planning call failed; neutral fallback required: session={} error={}",
                session_id,
                exc,
            )
        route = _extract_route_json(manager_raw) or {}
        speech = str(route.get("speech") or "我来直接处理这个问题。")
        raw_questions = route.get("questions")
        questions = (
            [
                {
                    "question": str(question.get("question") or "").strip(),
                    "options": [
                        str(option).strip()
                        for option in question.get("options", [])
                        if str(option).strip()
                    ],
                }
                for question in raw_questions
                if isinstance(question, dict)
                and str(question.get("question") or "").strip()
            ][:3]
            if isinstance(raw_questions, list)
            else []
        )
        questions = _filter_overdrive_questions(questions, intake_slots)
        raw_assignments = route.get("assignments")
        if preflight_fallback_questions and not questions:
            logger.warning(
                "Overdrive Manager preflight output lacked valid questions; using safe fallback: session={}",
                session_id,
            )
            speech = "当前无法生成可用的澄清问题。请先补充以下关键信息，我再为你制定可执行的方案。"
            questions = preflight_fallback_questions
            raw_assignments = []
            planning_mode = "rule_preflight"

    assignments = _normalize_overdrive_assignments(raw_assignments, set(catalog_by_id))
    authoritative_assignments = _normalize_overdrive_assignments(
        _default_overdrive_assignments(
            planning_content,
            catalog_items,
            intake_slots,
            authoritative_only=True,
        ),
        set(catalog_by_id),
    )
    settings = get_settings()
    if not questions and not pending_followup:
        repair_plan = partial(
            repair_overdrive_plan,
            manager_context=manager_context,
            authoritative_anchors=format_overdrive_anchors(authoritative_rules),
            catalog_by_id=catalog_by_id,
            session_id=session_id,
            deep_thinking=deep_thinking,
        )
        constrained = await apply_authoritative_plan(
            assignments=assignments,
            speech=speech,
            authoritative_assignments=authoritative_assignments,
            rules=authoritative_rules,
            catalog_by_id=catalog_by_id,
            mode=settings.overdrive_authoritative_mode,
            repair_enabled=settings.overdrive_plan_repair_enabled,
            repair_plan=repair_plan,
            capability_check_enabled=settings.overdrive_capability_check_enabled,
        )
        assignments = constrained.assignments
        speech = constrained.speech
        planning_mode = constrained.planning_mode
        plan_violations = constrained.violations
        repair_attempted = constrained.repair_attempted
        if planning_mode == "rule_merge":
            logger.warning(
                "Overdrive Manager rule merge applied: session={} violations={}",
                session_id,
                plan_violations,
            )
    minimized_assignments = registry.minimize_assignments(
        assignments, catalog_by_id, intake_slots
    )
    if len(minimized_assignments) != len(assignments):
        assignments = minimized_assignments
    schedule_fallback = False
    if not assignments and not questions and not pending_followup:
        assignments = _normalize_overdrive_assignments(
            _default_overdrive_assignments(planning_content, catalog_items, intake_slots),
            set(catalog_by_id),
        )
        if assignments:
            schedule_fallback = True
            planning_mode = "rule_merge"
            if not manager_raw:
                speech = "已为你生成执行计划，请确认任务分工与顺序。"
    if questions:
        assignments = []
    elif initial_manager_failed:
        planning_mode = "rule_merge"
        speech = (
            "已为你生成执行计划，请确认任务分工与顺序。"
            if assignments
            else "Manager 暂时不可用，暂未生成执行计划，请稍后重试。"
        )

    decision.assignments = assignments
    decision.speech = speech
    decision.questions = questions
    decision.manager_thought = manager_thought
    decision.planning_mode = planning_mode
    decision.authoritative_anchor_ids = authoritative_anchor_ids
    decision.plan_violations = plan_violations
    decision.repair_attempted = repair_attempted
    decision.schedule_fallback = schedule_fallback


async def stream_overdrive_manager(
    manager_context: Any,
    prompt: str,
    *,
    max_tokens: int = 1200,
    system_prompt: str = "",
    deep_thinking: bool = False,
    include_reasoning: bool = False,
) -> AsyncIterator[str | tuple[str, bool]]:
    """流式产出 Manager 正文，并将思考 token 与结构化正文隔离。"""
    if manager_context.model_config is None:
        return
    async for chunk in provider_manager.chat_stream(
        config=manager_context.model_config,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=system_prompt,
        temperature=0.2,
        max_tokens=max_tokens,
        tools=None,
        deep_thinking=deep_thinking,
    ):
        if chunk.type != "text":
            continue
        is_reasoning = bool(chunk.metadata.get("is_reasoning"))
        if include_reasoning:
            yield chunk.content, is_reasoning
        elif not is_reasoning:
            yield chunk.content


async def ask_overdrive_manager(
    manager_context: Any,
    prompt: str,
    *,
    max_tokens: int = 1200,
    system_prompt: str = "",
    deep_thinking: bool = False,
) -> str:
    """收集 Manager 的非推理正文，用于后续 JSON 或摘要解析。"""
    answer = ""
    async for delta in stream_overdrive_manager(
        manager_context,
        prompt,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        deep_thinking=deep_thinking,
    ):
        answer += str(delta)
    return answer.strip()


async def repair_overdrive_plan(
    violations: list[str],
    *,
    manager_context: Any,
    authoritative_anchors: str,
    catalog_by_id: dict[str, dict[str, Any]],
    session_id: str,
    deep_thinking: bool,
) -> tuple[str, list[dict[str, Any]]]:
    """请求 Manager 修复违反领域锚点、依赖约束或通用能力匹配的计划。"""
    from cygnusx.application.services.chat.utils import _extract_route_json

    logger.warning(
        "Overdrive Manager plan repair requested: session={} violations={}",
        session_id,
        violations,
    )
    try:
        repair_raw = await ask_overdrive_manager(
            manager_context,
            build_repair_prompt(violations, authoritative_anchors),
            max_tokens=2400 if deep_thinking else 900,
            deep_thinking=deep_thinking,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Overdrive Manager repair call failed; rule merge required: session={} error={}",
            session_id,
            exc,
        )
        return "", []
    repair_decision = _extract_route_json(repair_raw) or {}
    repaired_assignments = _normalize_overdrive_assignments(
        repair_decision.get("assignments"), set(catalog_by_id)
    )
    return str(repair_decision.get("speech") or "").strip(), repaired_assignments


async def emit_overdrive_speech(
    sender: dict[str, Any],
    content: str,
    round_number: int,
    *,
    add_message: Callable[..., Any],
    session_id: str,
    worker_key: str | None = None,
    thought: str = "",
    summary_text: str = "",
    artifacts: dict[str, Any] | None = None,
    task_status: str = "",
    error_summary: str = "",
    planning_metadata: dict[str, Any] | None = None,
) -> ChatChunk:
    """持久化 Overdrive 发言，并返回与历史契约一致的房间事件。"""
    message = await add_message(
        session_id,
        "assistant",
        content,
        metadata={
            "senderAgent": sender,
            "overdriveRound": round_number,
            **({"thought": thought} if thought else {}),
            **({"summary": summary_text} if summary_text else {}),
            **({"artifacts": artifacts} if artifacts else {}),
            **({"taskStatus": task_status} if task_status else {}),
            **({"errorSummary": error_summary} if error_summary else {}),
            **(planning_metadata or {}),
        },
    )
    return ChatChunk(
        type="room_speech",
        content=content,
        metadata={
            "sender": sender,
            "round": round_number,
            "session_id": session_id,
            "message_id": message.message_id,
            **({"thought": thought} if thought else {}),
            **({"summary": summary_text} if summary_text else {}),
            **({"artifacts": artifacts} if artifacts else {}),
            **({"task_status": task_status} if task_status else {}),
            **({"error_summary": error_summary} if error_summary else {}),
            **(planning_metadata or {}),
            **({"worker_key": worker_key} if worker_key else {}),
        },
    )


async def resolve_active_overdrive_route(
    *,
    db: Any,
    user_id: str,
    session_id: str,
    user_content: str,
    replan_lock_id: str | None,
) -> ActiveOverdriveRoute:
    """路由已持久化的超频运行，避免新请求重复进入旧版规划流程。"""
    run_service = OverdriveRunService(db)
    active_run: Any | None = run_service.get_active_for_session(session_id, user_id)
    for _ in range(4):
        if not inspect.isawaitable(active_run):
            break
        active_run = await active_run
    if inspect.isawaitable(active_run):
        if inspect.iscoroutine(active_run):
            active_run.close()
        active_run = None
    if active_run is not None and not isinstance(getattr(active_run, "status", None), str):
        active_run = None
    if active_run is None:
        return ActiveOverdriveRoute()

    if active_run.status == "REPLANNING":
        replan_root_request = str(active_run.root_request or "").strip()
        active_replan_lock = str((active_run.control or {}).get("replan_lock") or "")
        if active_replan_lock and active_replan_lock != replan_lock_id:
            return ActiveOverdriveRoute(
                chunks=(
                    ChatChunk(
                        type="overdrive_progress",
                        metadata={
                            "phase": "replanning",
                            "label": "规划 Agent 正在根据已提交的修改意见生成新版本计划",
                            "run_id": active_run.run_id,
                            "completed": 0,
                            "total": 3,
                        },
                    ),
                ),
            )
        return ActiveOverdriveRoute(replan_root_request=replan_root_request)

    routed = None
    if active_run.status in {
        "RUNNING",
        "WAITING_FOR_RESULTS",
        "AWAITING_USER_INPUT",
        "AWAITING_APPROVAL",
    }:
        routed = await run_service.accept_branch_user_input(
            run_id=active_run.run_id,
            user_id=user_id,
            response=user_content,
        )
    if routed is not None:
        return ActiveOverdriveRoute(
            chunks=(
                ChatChunk(
                    type="overdrive_progress",
                    metadata={
                        "phase": "worker_running",
                        "label": f"已把补充信息交回分支 {routed['task_id']}，其他分支继续运行",
                        "run_id": active_run.run_id,
                        "completed": sum(
                            task.get("status") in {"succeeded", "failed", "skipped"}
                            for task in active_run.tasks
                        ),
                        "total": len(active_run.tasks),
                    },
                ),
            ),
            advance_run_id=active_run.run_id,
        )
    if active_run.status == "AWAITING_PLAN_CONFIRMATION":
        frozen = active_run.plan or {}
        return ActiveOverdriveRoute(
            chunks=(
                ChatChunk(
                    type="ask_request",
                    metadata={
                        "kind": "plan_confirmation",
                        "run_id": active_run.run_id,
                        "plan_path": frozen.get("path"),
                        "plan_version": frozen.get("version"),
                        "plan_hash": frozen.get("hash"),
                        "summary": frozen.get("summary") or {},
                        "actions": ["approve", "revise", "cancel"],
                    },
                ),
            ),
        )
    return ActiveOverdriveRoute(
        chunks=(
            ChatChunk(
                type="overdrive_progress",
                metadata={
                    "phase": active_run.status.lower(),
                    "label": f"超频任务正在后台推进（{active_run.status}）",
                    "completed": sum(
                        task.get("status") in {"succeeded", "failed", "skipped"}
                        for task in active_run.tasks
                    ),
                    "total": len(active_run.tasks),
                    "tasks": active_run.tasks,
                    "run_id": active_run.run_id,
                    "event_cursor": active_run.event_cursor,
                },
            ),
        ),
    )


def prepare_overdrive_intake(
    *,
    user_content: str,
    replan_root_request: str,
    manager_agent_id: str,
    pending_intake: dict[str, Any] | None,
    pending_followup: dict[str, Any] | None,
) -> OverdriveIntakeState:
    """将新请求、重规划和会话补充信息归一化为 Manager 的规划输入。"""
    root_request = replan_root_request or user_content
    intake_slots = _extract_overdrive_intake_slots(root_request)
    intake_supplements: list[str] = []
    planning_content = (
        f"原始请求：\n{root_request}\n\n计划修改意见：\n{user_content.strip()}"
        if replan_root_request
        else user_content
    )
    pending_final_report = ""
    followup_save_requested = False
    followup_data_ready = False
    clear_pending_intake = False
    clear_pending_followup = False

    if pending_intake:
        root_request = str(
            pending_intake.get("root_request")
            or pending_intake.get("original_request")
            or user_content
        ).strip()
        previous_slots = pending_intake.get("slots")
        intake_slots = _extract_overdrive_intake_slots(
            user_content, previous_slots if isinstance(previous_slots, dict) else None
        )
        previous_supplements = pending_intake.get("supplements")
        intake_supplements = (
            [str(item) for item in previous_supplements if str(item).strip()]
            if isinstance(previous_supplements, list)
            else []
        )
        intake_supplements.append(user_content)
        planning_content = (
            f"原始请求：\n{root_request}\n\n"
            f"已确认信息：\n{json.dumps(intake_slots, ensure_ascii=False)}\n\n"
            "用户补充信息：\n" + "\n\n".join(intake_supplements)
        )
        clear_pending_intake = True
    elif pending_followup:
        root_request = str(
            pending_followup.get("root_request")
            or pending_followup.get("original_request")
            or user_content
        ).strip()
        pending_final_report = str(pending_followup.get("final_report") or "").strip()
        followup_save_requested, followup_data_ready = _overdrive_followup_choices(user_content)
        planning_content = (
            f"原始任务：\n{root_request}\n\n"
            f"上轮最终综合报告：\n{pending_final_report}\n\n"
            f"用户对报告保存与数据准备状态的回答：\n{user_content}\n\n"
            "请严格根据用户回答继续：若用户要求保存，安排具备工作区写入能力的 Agent "
            "把综合报告保存到 output/results/ 并更新 output/README.md；若用户确认数据已准备好，"
            "先核验工作区输入文件，再按报告中的顺序安排分析。不要重新生成一份相同计划。"
        )
        clear_pending_followup = True

    return OverdriveIntakeState(
        root_request=root_request,
        intake_slots=intake_slots,
        intake_supplements=intake_supplements,
        planning_content=planning_content,
        limits=load_overdrive_limits(manager_agent_id),
        pending_final_report=pending_final_report,
        followup_save_requested=followup_save_requested,
        followup_data_ready=followup_data_ready,
        clear_pending_intake=clear_pending_intake,
        clear_pending_followup=clear_pending_followup,
    )


async def load_overdrive_session_state(
    *,
    session_loader: Callable[[str, str], Any],
    session_id: str,
    user_id: str,
) -> OverdriveSessionState:
    """安全读取会话中的超频 intake 与后续操作状态。"""
    try:
        session = session_loader(session_id, user_id)
        for _ in range(2):
            if not inspect.isawaitable(session):
                break
            session = await session
        if inspect.isawaitable(session):
            if inspect.iscoroutine(session):
                session.close()
            session = None
        sandbox_meta = getattr(session, "sandbox_meta", None)
        if not isinstance(sandbox_meta, (dict, type(None))) or not hasattr(session, "sandbox_meta"):
            return OverdriveSessionState()
        raw_pending_intake = (sandbox_meta or {}).get("overdrive_intake")
        raw_pending_followup = (sandbox_meta or {}).get("overdrive_followup")
        return OverdriveSessionState(
            session=session,
            pending_intake=(
                raw_pending_intake
                if isinstance(raw_pending_intake, dict)
                and raw_pending_intake.get("status") == "awaiting_input"
                else None
            ),
            pending_followup=(
                raw_pending_followup
                if isinstance(raw_pending_followup, dict)
                and raw_pending_followup.get("status") == "awaiting_input"
                else None
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取超频 intake 状态失败，按新任务处理: {}", exc)
        return OverdriveSessionState()


def build_overdrive_agent_catalog(agents: list[Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """筛选可分派 Agent，并构建 Manager 规划使用的能力目录。"""
    candidates = [
        agent
        for agent in agents
        if not (agent.features or {}).get("router")
        and bool((agent.features or {}).get("subagents_spawnable"))
    ]
    catalog_items = [
        {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "description": agent.description,
            "category": agent.category,
            "avatar": agent.avatar,
            "color": agent.color,
            **_overdrive_capability_profile(
                agent_id=agent.agent_id,
                name=agent.name,
                category=agent.category,
                features=agent.features,
            ),
        }
        for agent in candidates
    ]
    return catalog_items, {item["agent_id"]: item for item in catalog_items}


def _effective_overdrive(request_value: bool | None, session_meta: dict[str, Any]) -> bool:
    """请求显式值优先，否则沿用会话级开关。"""
    return (
        bool(request_value)
        if request_value is not None
        else bool(session_meta.get("overdrive", False))
    )


def _resolve_overdrive_keyword_toggle(text: str, enabled: bool) -> bool | None:
    """仅从明确的会话控制命令切换超频状态，普通问答不得改变会话设置。"""
    normalized = text.lower().replace(" ", "")
    if enabled and any(hint in normalized for hint in _OVERDRIVE_OFF_HINTS):
        return False
    if enabled or any(hint in normalized for hint in _OVERDRIVE_OFF_HINTS):
        return None
    if (
        "?" in normalized
        or "？" in normalized
        or any(hint in normalized for hint in _OVERDRIVE_EXPLANATION_HINTS)
        or any(hint in normalized for hint in _OVERDRIVE_NEGATED_ON_HINTS)
    ):
        return None
    if _OVERDRIVE_ON_COMMAND_RE.search(normalized) or _OVERDRIVE_ON_ENGLISH_COMMAND_RE.search(text.lower()):
        return True
    return None


def _resolve_overdrive_router_toggle(route_info: dict[str, Any] | None, enabled: bool) -> bool | None:
    """Accept an AI Router mode decision only when its intent and confidence are actionable."""
    if not isinstance(route_info, dict):
        return None
    overdrive_intent = str(route_info.get("overdrive_intent") or "none")
    if overdrive_intent == "disable" and enabled:
        return False
    if overdrive_intent != "enable" or enabled:
        return None
    try:
        confidence = float(route_info.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    if confidence < 0.75:
        return None
    return (
        True
        if str(route_info.get("intent")) in {"fanout", "consult", "case", "dag"}
        else None
    )


def _overdrive_answer_requires_user_input(content: str) -> bool:
    """专家已在向用户索取关键输入时，不再由 Manager 重复改写一次。"""
    normalized = content.replace(" ", "")
    return any(
        marker in normalized for marker in ("请补充", "请告诉我", "请回答", "需要明确", "等待你的")
    )


def _overdrive_summary_exposes_internal_instructions(content: str) -> bool:
    """防止模型把 Manager 的汇总约束或自我推理直接展示给用户。"""
    normalized = content.replace(" ", "").replace("\n", "")
    markers = (
        "用户要求只基于",
        "查看专家结果",
        "根据规则",
        "我应该直接输出",
        "提示词",
        "系统消息",
    )
    return any(marker in normalized for marker in markers)


def _is_overdrive_planning_request(content: str) -> bool:
    normalized = content.lower()
    registry = get_domain_registry()
    planning_markers = ("计划", "方案", "研究设计", "研究路线", "挖掘", "新颖发现")
    return (
        any(marker in normalized for marker in planning_markers)
        or registry.has_planning_marker(normalized)
    ) and registry.matches_any(normalized)


def _analysis_intake_questions(user_content: str) -> list[dict[str, Any]]:
    """为会改变组学研究路线的缺失上下文生成最小澄清集。"""
    if not _is_overdrive_planning_request(user_content):
        return []
    return get_domain_registry().intake_questions(user_content)


_OVERDRIVE_OPERATION_MARKERS = (
    "分析", "执行", "运行", "处理", "生成", "构建", "绘制", "画", "计算",
    "比对", "定量", "差异", "富集", "质控", "注释", "批量",
)
_OVERDRIVE_CONCEPT_MARKERS = (
    "介绍", "原理", "教程", "学习", "是什么", "怎么做", "如何做", "方法讨论", "先讲",
)
_OVERDRIVE_INPUT_MARKERS = (
    "已上传", "上传了", "附件", "工作区", "文件", "目录", "路径", "样本表", "元数据",
    "fastq", "fastq.gz", "fq.gz", "fasta", "矩阵", "count", "表达量", "vcf", "bam",
    "h5ad", "treefile", "newick", "结果",
    ".qs", ".rds", ".seurat",  # 单细胞对象格式：Seurat QuickSave, RDS, Seurat 对象
)


def _overdrive_requires_input_clarification(user_content: str) -> bool:
    """Require a domain-agnostic input contract before planning execution work."""
    normalized = user_content.lower().replace(" ", "")
    if any(marker in normalized for marker in _OVERDRIVE_CONCEPT_MARKERS):
        return False
    return any(marker in normalized for marker in _OVERDRIVE_OPERATION_MARKERS) and not any(
        marker in normalized for marker in _OVERDRIVE_INPUT_MARKERS
    )


def _overdrive_preflight_questions(user_content: str) -> list[dict[str, Any]]:
    """生成预检失败时使用的最小安全澄清集。"""
    questions = _analysis_intake_questions(user_content)
    if _overdrive_requires_input_clarification(user_content):
        questions.insert(
            0,
            {
                "question": (
                    "这是要基于真实输入执行任务，还是先讨论方法？当前消息没有可核验的文件、"
                    "工作区、样本表或已有结果；若要执行，请先上传或引用本轮所需输入。"
                ),
                "options": [
                    "我会上传/引用输入后执行（推荐）",
                    "先讨论方法与分析路线",
                    "只解读已有结果",
                ],
            },
        )
    return questions[:3]


def _extract_overdrive_intake_slots(
    user_content: str, existing: dict[str, Any] | None = None
) -> dict[str, Any]:
    """从用户最新回答提取稳定 intake 字段；最新明确回答覆盖旧值。"""
    return get_domain_registry().extract_slots(user_content, existing)


def _filter_overdrive_questions(
    questions: list[dict[str, Any]], slots: dict[str, Any]
) -> list[dict[str, Any]]:
    """移除已回答字段与当前任务分支无关的问题。"""
    return get_domain_registry().filter_questions(questions, slots)


def _normalize_overdrive_assignments(
    raw_assignments: Any, valid_agent_ids: set[str]
) -> list[dict[str, Any]]:
    """归一化 Manager DAG；task_id 唯一，依赖仅保留当前任务集合内引用。"""
    if not isinstance(raw_assignments, list):
        return []
    limits = load_overdrive_limits()
    normalized: list[dict[str, Any]] = []
    used_task_ids: set[str] = set()
    for position, item in enumerate(raw_assignments, start=1):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agent_id") or "").strip()
        task = str(item.get("task") or "").strip()
        if agent_id not in valid_agent_ids or not task:
            continue
        agent_limits = load_overdrive_limits(agent_id)
        requested_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(item.get("task_id") or ""))
        task_id = requested_id.strip("-") or f"task-{position}"
        if task_id in used_task_ids:
            task_id = f"{task_id}-{position}"
        used_task_ids.add(task_id)
        raw_dependencies = item.get("depends_on")
        depends_on = (
            [str(value).strip() for value in raw_dependencies if str(value).strip()]
            if isinstance(raw_dependencies, list)
            else []
        )
        normalized.append(
            {
                "task_id": task_id,
                "agent_id": agent_id,
                "task": task,
                "depends_on": depends_on,
                "workspace_access": bool(item.get("workspace_access")),
                "accepts_inputs": normalize_contract_list(item.get("accepts_inputs")),
                "produces_outputs": normalize_contract_list(item.get("produces_outputs")),
                "retry": normalize_retry(item.get("retry"), agent_limits),
                "timeout_seconds": max(
                    1,
                    int(item.get("timeout_seconds") or agent_limits["default_timeout_seconds"]),
                ),
                "priority": str(item.get("priority") or "normal")
                if str(item.get("priority") or "normal") in {"high", "normal", "low"}
                else "normal",
            }
        )
        if len(normalized) == int(limits["max_tasks_per_session"]):
            break
    valid_task_ids = {item["task_id"] for item in normalized}
    for item in normalized:
        item["depends_on"] = list(
            dict.fromkeys(
                dependency
                for dependency in item["depends_on"]
                if dependency in valid_task_ids and dependency != item["task_id"]
            )
        )
    return infer_contract_dependencies(normalized)


def _overdrive_assignment_waves(
    assignments: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """按 depends_on 生成拓扑波次；循环依赖时按原顺序拆成单任务安全降级。"""
    waves, _ = build_assignment_waves(
        assignments,
        max_parallel=int(load_overdrive_limits()["max_parallel_per_wave"]),
    )
    return waves


def _overdrive_capability_profile(
    *,
    agent_id: str,
    name: str,
    category: str,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """提供给 Manager 的稳定能力边界；YAML 仍是工具与提示词的最终执行约束。"""
    configured = features or {}
    profile = {
        "default_role": str(
            configured.get("default_role") or "仅处理其描述和已挂载工具覆盖的专业任务"
        ),
        "capability_scope": [category or "specialist"],
    }
    capability_scope = configured.get("capability_scope")
    if not isinstance(capability_scope, list) or not capability_scope:
        capability_scope = configured.get("capability_tags")
    if isinstance(capability_scope, list) and capability_scope:
        profile["capability_scope"] = [str(item) for item in capability_scope if str(item)]
    for key in ("accepts_inputs", "produces_outputs"):
        values = configured.get(key)
        if isinstance(values, list) and values:
            profile[key] = [str(item) for item in values if str(item)]
    default_stage = str(configured.get("default_stage") or "").strip()
    if default_stage:
        profile["default_stage"] = default_stage
    return profile


def _default_overdrive_assignments(
    user_content: str,
    catalog_items: list[dict[str, Any]],
    intake_slots: dict[str, Any] | None = None,
    *,
    authoritative_only: bool = False,
) -> list[dict[str, Any]]:
    """Manager 未给出有效分工时，按任务所需的最小专家集合调度。"""
    normalized = user_content.lower()
    slots = intake_slots or {}

    def find(*markers: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in catalog_items
                if any(
                    marker
                    in " ".join(
                        (
                            str(item.get("agent_id") or ""),
                            str(item.get("name") or ""),
                            str(item.get("category") or ""),
                        )
                    ).lower()
                    for marker in markers
                )
            ),
            None,
        )

    registry = get_domain_registry()
    if registry.is_empty:
        return []

    general = find("agent-general", "通用助手")
    code = find("agent-code", "代码助手")
    visualization = find("agent-viz", "可视化助手", "visualization")
    domain_assignments: list[dict[str, Any]] = []
    rules = registry.assignment_rules(user_content, slots)
    if authoritative_only:
        rules = [rule for rule in rules if rule.authoritative]
    for rule in rules:
        candidate = find(*rule.agent_match)
        if candidate is None:
            continue
        assignment = {
            "task_id": rule.task_id,
            "agent_id": candidate["agent_id"],
            "task": rule.task,
            "depends_on": rule.depends_on,
        }
        if rule.workspace_access:
            assignment["workspace_access"] = True
        if rule.accepts_inputs:
            assignment["accepts_inputs"] = rule.accepts_inputs
        if rule.produces_outputs:
            assignment["produces_outputs"] = rule.produces_outputs
        if rule.minimize_to_single:
            return [assignment]
        domain_assignments.append(assignment)
    if domain_assignments:
        return domain_assignments
    if authoritative_only:
        return []

    planning_or_analysis = _is_overdrive_planning_request(user_content) or any(
        marker in normalized for marker in ("分析", "研究", "差异表达", "通路", "富集", "工作流")
    )
    if not planning_or_analysis:
        if code and any(marker in normalized for marker in ("代码", "脚本", "python", " r ")):
            return [
                {
                    "task_id": "code-task",
                    "agent_id": code["agent_id"],
                    "task": "根据用户要求完成代码或脚本任务，并给出可复现的使用说明。",
                    "depends_on": [],
                }
            ]
        if visualization and any(marker in normalized for marker in ("画图", "绘图", "可视化")):
            return [
                {
                    "task_id": "visualization-task",
                    "agent_id": visualization["agent_id"],
                    "task": "根据用户提供的真实数据或结果完成可视化设计；缺少数据时明确请求输入。",
                    "depends_on": [],
                }
            ]
        return []

    if general:
        return [
            {
                "task_id": "research-plan",
                "agent_id": general["agent_id"],
                "task": "完成研究目标拆解、总体分析计划、数据契约、质量控制和交付结果定义。",
                "depends_on": [],
            }
        ]
    return []


def _overdrive_followup_choices(user_content: str) -> tuple[bool, bool]:
    """解析最终报告卡片的两个明确选择，避免把问题文本中的关键词当作答案。"""
    normalized = user_content.replace(" ", "").lower()
    save_requested = not any(
        marker in normalized for marker in ("暂不保存", "不保存", "无需保存")
    ) and any(
        marker in normalized
        for marker in ("保存到output/results", "保存报告", "请保存", "需要保存")
    )
    data_ready = not any(
        marker in normalized for marker in ("尚未准备", "未准备好", "数据没准备")
    ) and any(marker in normalized for marker in ("已准备好", "开始分析", "执行分析", "按计划开始"))
    return save_requested, data_ready


def _build_overdrive_followup_assignments(
    *,
    catalog_items: list[dict[str, Any]],
    save_requested: bool,
    data_ready: bool,
) -> tuple[str, list[dict[str, Any]]]:
    """把用户确认转换为确定性的保存/执行 DAG，而不是再次自由生成研究计划。"""

    def find_candidate(*markers: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in catalog_items
                if any(
                    marker
                    in " ".join(
                        (
                            str(item.get("category") or ""),
                            str(item.get("name") or ""),
                            str(item.get("agent_id") or ""),
                        )
                    ).lower()
                    for marker in markers
                )
            ),
            None,
        )

    code_candidate = find_candidate("code", "代码") or find_candidate("general", "通用")
    visualization_candidate = find_candidate("visualization", "visualisation", "viz", "可视化")
    assignments: list[dict[str, Any]] = []
    if data_ready and code_candidate is not None:
        assignments.append(
            {
                "task_id": "execute-analysis",
                "agent_id": code_candidate["agent_id"],
                "depends_on": [],
                "workspace_access": True,
                "task": (
                    "用户已确认数据准备完成。先使用 workspace_list/workspace_read 核验真实输入文件、"
                    "列名、分组和样本匹配，再严格按照上轮综合报告执行当前可运行的分析阶段。"
                    "必须先用 workspace_write 把完整脚本写入 scripts/，再用 sandbox_execute 运行；"
                    "结果写入 output/results/，并更新 output/README.md。若数据缺失或格式不满足计划，"
                    "列出具体缺失路径与修复要求后停止，禁止伪造分析结果。"
                ),
            }
        )
        if visualization_candidate is not None:
            assignments.append(
                {
                    "task_id": "visualize-results",
                    "agent_id": visualization_candidate["agent_id"],
                    "depends_on": ["execute-analysis"],
                    "workspace_access": True,
                    "task": (
                        "读取代码助手实际生成的结果文件和执行结论，结合上轮综合报告制作最终可视化。"
                        "只使用真实输出数据；绘图脚本写入 scripts/，图表写入 output/figures/，"
                        "并把图表说明和路径更新到 output/README.md。若上游未产生可绘制结果，"
                        "明确说明阻塞原因，不得生成虚构图表。"
                    ),
                }
            )

    if save_requested and data_ready:
        speech = "我会先保存最终综合报告，然后让代码助手核验并执行分析，最后由可视化助手基于真实结果完成图表交付。"
    elif save_requested:
        speech = "我会先把最终综合报告保存到工作目录；数据尚未准备好，本轮不会提前执行分析。"
    elif data_ready:
        speech = "数据已准备好，我会直接让代码助手核验并执行分析，再由可视化助手基于真实结果完成图表交付。"
    else:
        speech = "好的，本轮暂不保存报告，也不启动分析；当前综合计划会保留在会话中。"
    return speech, assignments


async def _save_overdrive_report_to_workspace(
    *,
    session_id: str,
    user_id: str,
    final_report: str,
) -> tuple[bool, str, str]:
    """在用户明确同意后，将报告和索引直接写入当前会话工作区。"""
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_path = f"output/results/overdrive-report-{timestamp}.md"
    report_result = await execute_studio_tool(
        "workspace_write",
        {"path": report_path, "content": final_report},
        session_id,
        user_id=user_id,
    )
    if not report_result.get("success"):
        return False, report_path, str(report_result.get("error") or "报告写入失败")

    readme_result = await execute_studio_tool(
        "workspace_read",
        {"path": "output/README.md"},
        session_id,
        user_id=user_id,
    )
    readme_payload = (readme_result.get("result") or {}).get("llm_payload") or {}
    existing_readme = str(readme_payload.get("content") or "").rstrip()
    entry = f"- [超频协作综合报告 {timestamp}](results/{Path(report_path).name})"
    readme_content = (
        f"{existing_readme}\n\n## 综合报告\n\n{entry}\n"
        if existing_readme
        else f"# CygnusX 分析输出\n\n## 综合报告\n\n{entry}\n"
    )
    readme_write = await execute_studio_tool(
        "workspace_write",
        {"path": "output/README.md", "content": readme_content},
        session_id,
        user_id=user_id,
    )
    if not readme_write.get("success"):
        return False, report_path, "报告已保存，但 output/README.md 更新失败"
    return True, report_path, ""






class OverdriveControl:
    """维护 Overdrive 控制文件和人工审批状态机。"""

    async def create_overdrive_approval(
        self,
        *,
        session: ChatSessionModel,
        run_id: str,
        task_id: str,
        manager_agent_id: str,
        worker_agent_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """在聊天会话中持久化一次待审批的 Worker 工具调用。"""
        now = datetime.now(UTC).isoformat()
        approval = {
            "approval_id": f"overdrive-approval:{uuid.uuid4().hex}",
            "run_id": run_id,
            "task_id": task_id,
            "manager_agent_id": manager_agent_id,
            "worker_agent_id": worker_agent_id,
            "tool_name": tool_name,
            "arguments": dict(arguments),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        metadata = dict(session.sandbox_meta or {})
        approvals = list(metadata.get("overdrive_approvals") or [])[-49:]
        approvals.append(approval)
        session.sandbox_meta = {**metadata, "overdrive_approvals": approvals}
        await self._db.flush()
        return approval

    async def control_overdrive(
        self,
        *,
        session_id: str,
        user_id: str,
        action: str,
        task_id: str = "",
        directive: str = "",
    ) -> dict[str, Any]:
        session = await self.get_session(session_id, user_id)
        if session is None:
            raise ValueError("会话不存在")
        if action == "skip" and not task_id:
            raise ValueError("跳过任务时必须提供 task_id")
        if action == "directive" and not directive.strip():
            raise ValueError("补充指令不能为空")
        runtime_action = "run" if action == "resume" else action
        payload = OverdriveManifest(session_id).write_control(
            runtime_action, task_id=task_id, directive=directive.strip()
        )
        return {"success": True, **payload}

    async def _get_overdrive_approval(
        self, session_id: str, user_id: str, approval_id: str
    ) -> tuple[ChatSessionModel, dict[str, Any], list[dict[str, Any]]]:
        session = await self.get_session(session_id, user_id)
        if session is None:
            raise NotFoundError("会话不存在或无权访问")
        approvals = list((session.sandbox_meta or {}).get("overdrive_approvals") or [])
        approval = next(
            (
                item
                for item in approvals
                if isinstance(item, dict) and item.get("approval_id") == approval_id
            ),
            None,
        )
        if approval is None:
            raise NotFoundError("超频审批记录不存在")
        return session, approval, approvals

    @staticmethod
    def _set_overdrive_task_status(session: ChatSessionModel, task_id: str, status: str) -> None:
        metadata = dict(session.sandbox_meta or {})
        runs = list(metadata.get("overdrive_runs") or [])
        for run in runs:
            if not isinstance(run, dict):
                continue
            for task in run.get("tasks") or []:
                if isinstance(task, dict) and task.get("task_id") == task_id:
                    task["status"] = status
                    task["updated_at"] = datetime.now(UTC).isoformat()
        metadata["overdrive_runs"] = runs
        session.sandbox_meta = metadata

    async def reject_overdrive_approval(
        self, *, session_id: str, user_id: str, approval_id: str, reason: str | None = None
    ) -> dict[str, Any]:
        session, approval, approvals = await self._get_overdrive_approval(
            session_id, user_id, approval_id
        )
        if approval.get("status") != "pending":
            raise ConflictError("该超频审批已被处理")
        approval.update(
            {
                "status": "rejected",
                "reason": (reason or "").strip(),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        self._set_overdrive_task_status(session, str(approval.get("task_id") or ""), "rejected")
        metadata = dict(session.sandbox_meta or {})
        metadata["overdrive_approvals"] = approvals
        session.sandbox_meta = metadata
        await self._db.flush()
        return approval

    async def approve_overdrive_approval(
        self, *, session_id: str, user_id: str, approval_id: str
    ) -> dict[str, Any]:
        """批准后由主会话的可信上下文恢复 Worker 原始工具调用。"""
        from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
        from cygnusx.application.services.tool_bridge_service import get_tool_bridge_service

        session, approval, approvals = await self._get_overdrive_approval(
            session_id, user_id, approval_id
        )
        if approval.get("status") != "pending":
            raise ConflictError("该超频审批已被处理")

        approval["status"] = "executing"
        approval["updated_at"] = datetime.now(UTC).isoformat()
        self._set_overdrive_task_status(session, str(approval.get("task_id") or ""), "running")
        metadata = dict(session.sandbox_meta or {})
        metadata["overdrive_approvals"] = approvals
        session.sandbox_meta = metadata
        await self._db.flush()

        try:
            result = await get_tool_bridge_service().execute(
                user_id=user_id,
                tool_name=str(approval["tool_name"]),
                arguments={**dict(approval.get("arguments") or {}), "_confirmed": True},
                context=ToolInvocationContext(
                    user_id=user_id,
                    agent_id=str(approval.get("manager_agent_id") or session.agent_id or "")
                    or None,
                    session_id=session_id,
                    db=self._db,
                    extra={
                        "overdrive_run_id": approval.get("run_id"),
                        "overdrive_task_id": approval.get("task_id"),
                        "overdrive_worker_agent_id": approval.get("worker_agent_id"),
                        "overdrive_approval_id": approval_id,
                        "approved_by_user": True,
                    },
                ),
            )
            approval["status"] = "completed" if result.get("success") else "failed"
            approval["result"] = result
            if not result.get("success"):
                approval["error"] = str(
                    (result.get("llm_payload") or {}).get("error") or "工具执行失败"
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("超频审批工具执行失败: {}", approval_id)
            approval.update({"status": "failed", "error": str(exc)})

        approval["updated_at"] = datetime.now(UTC).isoformat()
        self._set_overdrive_task_status(
            session,
            str(approval.get("task_id") or ""),
            "completed" if approval.get("status") == "completed" else "failed",
        )
        metadata = dict(session.sandbox_meta or {})
        metadata["overdrive_approvals"] = approvals
        session.sandbox_meta = metadata
        await self._db.flush()
        return approval
