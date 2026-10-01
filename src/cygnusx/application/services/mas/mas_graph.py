"""生物信息部门 Supervisor-Worker MAS 图（手册 2.1–2.4）。

拓扑：START → supervisor →（路由）worker_{agent_id} / plan_review(interrupt, 阶段3) / END
worker → supervisor；轮次熔断 max_orchestration_rounds=8。
图挂 AsyncPostgresSaver（复用 checkpointer 工厂），thread_id = run_id。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from cygnusx.domain.execution.mas_state import FINISH_SENTINEL, MASState
from cygnusx.domain.mas.worker_policy import filter_trace_messages

logger = logging.getLogger(__name__)

MAX_ORCHESTRATION_ROUNDS = 8

# 部门成员名册（MVP）：category=analysis/visualization 的主力生物信息 Agent。
# 名册字段以 agent_templates 为权威；此处只列 agent_id，描述运行时从 DB 补全。
DEFAULT_DEPT_MEMBERS = [
    {"agent_id": "agent-rnaseq"},
    {"agent_id": "agent-atacseq"},
    {"agent_id": "agent-qc"},
    {"agent_id": "agent-scrna"},
    {"agent_id": "agent-data"},
    {"agent_id": "agent-viz"},
]
_SUPERVISOR_DECISION_PROMPT_TEMPLATE = """你是生物信息部门的 Supervisor。根据用户问题与部门成员能力，决策下一步：
1. 自己直接回答（无需专员）→ 输出 JSON：{{"next_worker": "__finish__", "rationale": "…"}}
2. 派给一位专员 → 输出 JSON：{{"next_worker": "<agent_id>", "rationale": "…"}}
3. 需要人工审批的实验/分析计划 → 输出 JSON：{{"plan": {{"steps": ["…"]}}, "need_human_review": true}}

部门成员（agent_id | 能力）：
{members}

最近对话：
{conversation}

只输出一个 JSON 对象，不要输出其它文字。示例：
{{"next_worker": "agent-rnaseq", "rationale": "RNA-seq 质量问题由 RNA-seq 分析师处理"}}"""


def _supervisor_prompt(members_desc: str, conversation: str) -> str:
    return _SUPERVISOR_DECISION_PROMPT_TEMPLATE.format(
        members=members_desc, conversation=conversation
    )


def parse_supervisor_decision(text: str) -> dict[str, Any]:
    """解析 Supervisor 决策 JSON；失败返回 {"__parse_failed__": true}（调用方兜底）。

    模型常在 JSON 前后带推理文本（文本里也可能含 `{`），所以不能简单
    find('{')..rfind('}') 截窗——改为从每个 `{` 位置用 raw_decode 逐个尝试，
    取第一个能解析出完整 dict 的结果。
    """
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[idx:])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"__parse_failed__": True}


def build_mas_graph(
    members: list[dict[str, Any]],
    supervisor_llm: Any,
    worker_executor: Any,
    emit: Any,
    room_service: Any,
    max_rounds: int = MAX_ORCHESTRATION_ROUNDS,
    checkpointer: Any = None,
) -> Any:
    """构建 Supervisor-Worker 图。

    members: [{"agent_id","name","description"}]
    supervisor_llm: async callable(messages) -> str（Supervisor 决策 LLM）
    worker_executor: run_worker_turn(agent_id, user_id, messages, emit, room_id) -> str
    emit: async (room_id, event_dict) -> None
    room_service: MASRoomService-like（add_agent_message 等）
    """

    async def supervisor(state: MASState) -> dict[str, Any]:
        # plan_review resume：人工决议经 Command(resume=...) 回到本节点
        resume_value = state.get("plan_decision")
        if resume_value:
            action = resume_value.get("action")
            await room_service.add_agent_message(
                state.get("room_id", "bioinfo-dept"),
                agent_id=None,
                role="mas_trace",
                content=f"计划已{('批准，按计划派工执行' if action == 'approve' else '修改后执行' if action == 'edit' else '驳回，run 终结')}。",
                run_id=state.get("run_id"),
                meta={"plan_decision": action},
            )
            if action == "reject":
                return {"next_worker": FINISH_SENTINEL}
            plan = resume_value.get("edited_plan") or state.get("pending_plan") or {}
            # 批准/修改：按计划派第一位专员（计划派工简化为顺序派工，阶段 5 扩展）
            steps = plan.get("steps") or []
            await room_service.add_agent_message(
                state.get("room_id", "bioinfo-dept"),
                agent_id=None,
                role="mas_trace",
                content=f"按计划派工：{('；'.join(str(s) for s in steps))[:200]}",
                run_id=state.get("run_id"),
                meta={"plan_execute": True, "steps": steps},
            )
            decision = plan.get("dispatch") or {}
            next_worker = decision.get("next_worker")
            member_ids = {m["agent_id"] for m in members}
            if next_worker and next_worker in member_ids:
                return {"next_worker": next_worker, "plan_decision": None}
            return {"next_worker": FINISH_SENTINEL, "plan_decision": None}

        rounds = state.get("orchestration_rounds", 0) + 1
        messages = state.get("messages", [])
        # 剔除 mas_trace / plan_card 防系统消息污染
        context_messages = filter_trace_messages(messages)

        # 熔断：触顶强制收尾
        if rounds > max_rounds:
            await room_service.add_agent_message(
                state.get("room_id", "bioinfo-dept"),
                agent_id=None,
                role="mas_trace",
                content="已达到最大派工轮次，Supervisor 强制收尾。",
                run_id=state.get("run_id"),
                meta={"rounds": rounds, "circuit_break": True},
            )
            return {"next_worker": FINISH_SENTINEL, "orchestration_rounds": rounds}

        members_desc = "\n".join(
            f"- {m['agent_id']} | {m.get('name', m['agent_id'])}: {m.get('description', '')}"
            for m in members
        )
        conversation = "\n".join(
            f"[{m.get('role')} {m.get('name') or ''}]: {m.get('content', '')[:400]}"
            for m in context_messages[-12:]
        )
        prompt = _supervisor_prompt(members_desc, conversation)
        try:
            raw = await supervisor_llm([*context_messages, {"role": "user", "content": prompt}])
        except Exception as exc:  # noqa: BLE001 - Supervisor 失败不中断 run
            logger.exception("MAS supervisor llm failed run={}", state.get("run_id"))
            await room_service.add_agent_message(
                state.get("room_id", "bioinfo-dept"),
                agent_id=None,
                role="mas_trace",
                content=f"Supervisor 决策失败（{exc}），由部门助手直接回答。",
                run_id=state.get("run_id"),
            )
            return {"next_worker": FINISH_SENTINEL, "orchestration_rounds": rounds}

        decision = parse_supervisor_decision(raw)
        if decision.get("__parse_failed__"):
            # 解析失败静默回落"自己直接回答"（手册 2.2 硬要求）
            await room_service.add_agent_message(
                state.get("room_id", "bioinfo-dept"),
                agent_id=None,
                role="mas_trace",
                content="Supervisor 决策解析失败，回落为部门助手直接回答。",
                run_id=state.get("run_id"),
            )
            return {"next_worker": FINISH_SENTINEL, "orchestration_rounds": rounds}

        if decision.get("need_human_review") and decision.get("plan"):
            # 阶段 3：人工判断点 interrupt（checkpoint 落 Postgres，
            # 人工决议经 POST /mas/runs/{run_id}/plan-decision 写入后 resume）
            plan = dict(decision["plan"])
            plan.setdefault("dispatch", {})
            # interrupt 挂起后 resume 会重放节点，plan_card 副作用查重防重复落库
            run_id = state.get("run_id")
            already_sent = await _has_plan_card(room_service, state.get("room_id", "bioinfo-dept"), run_id)
            if not already_sent:
                await room_service.add_agent_message(
                    state.get("room_id", "bioinfo-dept"),
                    agent_id=None,
                    role="plan_card",
                    content="Supervisor 形成实验/分析计划，等待人工审批。",
                    run_id=run_id,
                    meta={"plan": plan},
                )
            payload = {"kind": "plan_review", "plan": plan, "run_id": state.get("run_id")}
            user_decision = interrupt(payload)
            # resume 后 user_decision = {action: approve|reject|edit, edited_plan?}
            if isinstance(user_decision, dict) and user_decision.get("action"):
                await room_service.add_agent_message(
                    state.get("room_id", "bioinfo-dept"),
                    agent_id=None,
                    role="mas_trace",
                    content=(
                        f"计划已{('批准，按计划派工执行' if user_decision.get('action') == 'approve' else '修改后执行' if user_decision.get('action') == 'edit' else '驳回，run 终结')}。"
                    ),
                    run_id=state.get("run_id"),
                    meta={"plan_decision": user_decision.get("action")},
                )
                if user_decision.get("action") == "reject":
                    return {"next_worker": FINISH_SENTINEL, "orchestration_rounds": rounds}
                effective_plan = user_decision.get("edited_plan") or plan
                steps = effective_plan.get("steps") or []
                await room_service.add_agent_message(
                    state.get("room_id", "bioinfo-dept"),
                    agent_id=None,
                    role="mas_trace",
                    content=f"按计划派工：{('；'.join(str(s) for s in steps))[:200]}",
                    run_id=state.get("run_id"),
                    meta={"plan_execute": True, "steps": steps},
                )
                dispatch = effective_plan.get("dispatch") or {}
                next_worker = dispatch.get("next_worker")
                member_ids = {m["agent_id"] for m in members}
                if next_worker and next_worker in member_ids:
                    return {"next_worker": next_worker, "orchestration_rounds": rounds}
                return {"next_worker": FINISH_SENTINEL, "orchestration_rounds": rounds}
            # resume 值非法：按计划派工兜底（同 approve）
            return {"pending_plan": plan, "next_worker": FINISH_SENTINEL, "orchestration_rounds": rounds}

        next_worker = decision.get("next_worker") or FINISH_SENTINEL
        rationale = decision.get("rationale", "")
        member_ids = {m["agent_id"] for m in members}
        if next_worker != FINISH_SENTINEL and next_worker not in member_ids:
            # 路由到不存在成员：兜底收尾
            next_worker = FINISH_SENTINEL
        await room_service.add_agent_message(
            state.get("room_id", "bioinfo-dept"),
            agent_id=None,
            role="mas_trace",
            content=(
                f"Supervisor 派工：{next_worker}{('（' + rationale + '）') if rationale else ''}"
            ),
            run_id=state.get("run_id"),
            meta={"next_worker": next_worker, "rationale": rationale},
        )
        return {"next_worker": next_worker, "orchestration_rounds": rounds}

    async def worker(state: MASState) -> dict[str, Any]:
        agent_id = state.get("next_worker") or FINISH_SENTINEL
        if agent_id == FINISH_SENTINEL:
            return {}
        messages = state.get("messages", [])
        final_text = await worker_executor(
            agent_id,
            _infer_user_id(messages),
            messages,
            emit,
            state.get("room_id", "bioinfo-dept"),
        )
        # Worker 产出落 mas_room_messages（role=assistant，ui_payload 语义）；
        # token usage 每个 turn 落消息 metadata（阶段 4）
        usage = {}
        try:
            from cygnusx.application.services.mas.mas_worker_executor import last_turn_usage

            usage = last_turn_usage()
        except Exception:  # noqa: BLE001 - usage 记录失败不阻断
            usage = {}
        await room_service.add_agent_message(
            state.get("room_id", "bioinfo-dept"),
            agent_id=agent_id,
            role="assistant",
            content=final_text,
            run_id=state.get("run_id"),
            meta={"worker_turn": True, "usage": usage},
        )
        # Worker 产出回灌（Supervisor 上下文经 filter_trace_messages 可见）
        return {
            "messages": [
                {
                    "role": "assistant",
                    "name": agent_id,
                    "content": final_text,
                }
            ]
        }

    def route_after_supervisor(state: MASState) -> str:
        return END if (state.get("next_worker") or FINISH_SENTINEL) == FINISH_SENTINEL else "worker"

    builder: StateGraph = StateGraph(MASState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("worker", worker)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", route_after_supervisor, [END, "worker"])
    builder.add_edge("worker", "supervisor")
    return builder.compile(checkpointer=checkpointer)


async def _has_plan_card(room_service: Any, room_id: str, run_id: str | None) -> bool:
    """查询本 run 是否已落 plan_card（interrupt 重放查重；失败视为未落，宁可重发）。"""
    try:
        from cygnusx.infrastructure.database.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select

            from cygnusx.infrastructure.database.models.mas_room import MASRoomMessageModel

            stmt = (
                select(MASRoomMessageModel.id)
                .where(
                    MASRoomMessageModel.room_id == room_id,
                    MASRoomMessageModel.role == "plan_card",
                )
                .limit(1)
            )
            if run_id:
                stmt = stmt.where(MASRoomMessageModel.run_id == run_id)
            result = await session.execute(stmt)
            return result.scalars().first() is not None
    except Exception:  # noqa: BLE001 - 查重失败宁可重发
        return False


def _infer_user_id(messages: list[dict[str, Any]]) -> str:
    """从消息 metadata 推断 user_id（落库时写入 user_id 字段）。"""
    for message in reversed(messages):
        meta = message.get("metadata") or {}
        user_id = meta.get("user_id")
        if user_id:
            return str(user_id)
    return "anonymous"
