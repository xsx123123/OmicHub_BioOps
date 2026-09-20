"""聊天 Runtime 共用的无状态解析和呈现辅助函数。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from loguru import logger


def _invocation_payload_hash(envelope: dict[str, Any]) -> str:
    """对 tool_invocations 信封内容计算 sha256（WP2 信封可校验）。

    hash 字段本身（payload_hash）不参与计算；序列化按 sort_keys 稳定化，
    确保写入方与复算方对同一信封得到同一摘要。
    """
    canonical = {k: v for k, v in envelope.items() if k != "payload_hash"}
    serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


#: 代码执行类工具（WP3-Task1）：这些工具调用的落库信封会带 cell 语义冗余字段
CODE_EXECUTION_TOOL_NAMES = frozenset({"sandbox_execute", "chat_sandbox_execute"})


def _code_cell_envelope_fields(
    tool_name: str, args: dict[str, Any], next_index: int
) -> dict[str, Any]:
    """WP3-Task1：工具调用信封的 cell 语义冗余字段（与 result/ui_payload 平级）。

    cell_index 仅对代码执行类工具（sandbox_execute / chat_sandbox_execute）递增编号，
    非代码工具为 None；language 从工具 arguments.language 取，无则 None。
    调用方负责在代码工具时递增 next_index（按落库顺序编号）。
    """
    language = args.get("language") if isinstance(args, dict) else None
    language = str(language) if language else None
    if tool_name not in CODE_EXECUTION_TOOL_NAMES:
        return {"cell_index": None, "language": language}
    return {"cell_index": next_index, "language": language}


def _max_persisted_cell_index(messages: list[Any]) -> int:
    """从会话已落库消息的 tool_invocations 元数据推导下一个 cell_index 基线。

    纯派生：取历史信封 cell_index 最大值 + 1（历史无字段时从 0 起），
    不重写任何已落库信封，保证会话内编号跨消息单调递增。
    """
    base = 0
    for message in messages or []:
        metadata = getattr(message, "metadata_json", None) or {}
        invocations = metadata.get("tool_invocations")
        if not isinstance(invocations, list):
            continue
        for invocation in invocations:
            if not isinstance(invocation, dict):
                continue
            cell_index = invocation.get("cell_index")
            if not isinstance(cell_index, int) or isinstance(cell_index, bool):
                continue
            base = max(base, cell_index + 1)
    return base


def _extract_route_json(text: str) -> dict[str, Any] | None:
    """从 router LLM 输出中容错提取路由 JSON。

    模型可能在 JSON 前后输出思考过程，甚至多次输出 JSON（先错后对）。
    逐个尝试所有 {...} 片段，取最后一个可解析且含 agent_id 的对象。
    """
    found: tuple[int, dict[str, Any]] | None = None
    manager_found: tuple[int, dict[str, Any]] | None = None
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            data, end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if "speech" in data and "assignments" in data:
            if manager_found is None or match.start() + end > manager_found[0]:
                manager_found = (match.start() + end, data)
        elif data.get("agent_id") and (found is None or match.start() + end > found[0]):
            found = (match.start() + end, data)
    return (manager_found or found or (0, None))[1]


def _studio_risk_hint(tool_name: str, args: dict[str, Any]) -> str:
    """审批卡片上的单行风险提示（supervised 模式，§3.1）。"""
    if tool_name in {"sandbox_execute", "chat_sandbox_execute"}:
        language = str(args.get("language") or "python")
        return f"将在沙盒中执行 {language} 代码"
    if tool_name == "network_request":
        from cygnusx.application.services.network_request_tool import network_request_risk_hint

        return network_request_risk_hint(args)
    if tool_name == "workspace_write":
        return f"将写入工作区文件 {args.get('path') or ''}".strip()
    if tool_name == "workspace_edit":
        return f"将修改工作区文件 {args.get('path') or ''}".strip()
    if tool_name == "artifact_register":
        return f"将把产物 {args.get('path') or ''} 登记到结果报告中心".strip()
    if tool_name == "tool_orchestrate":
        return "将运行一段可多次调用工作区工具的编排代码（内部子调用不再逐次审批）"
    return "该操作需要用户批准"


def _cap_tool_invocation_payload_detail(
    value: Any, limit: int = 200_000
) -> tuple[Any, dict[str, Any]]:
    """tool_invocations 落库护栏（带截断元信息版本）。

    返回 (载荷, 截断元信息)。未截断时元信息为空 dict；截断时元信息含
    payload_truncated / original_bytes / truncation_note，由调用方写入
    tool_invocations 信封（result_truncation / ui_payload_truncation），
    供前端历史重建时显式提示"内容已截断"，而不是无声降级。
    """
    if value is None:
        return None, {}
    original_bytes: int | None = None
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        if len(serialized) <= limit:
            return value, {}
        original_bytes = len(serialized.encode("utf-8"))
    except (TypeError, ValueError):
        pass
    meta: dict[str, Any] = {
        "payload_truncated": True,
        "truncation_note": "工具结果/ui_payload 序列化超过 200KB 落库护栏，已替换为截断标记；完整结果见沙盒产物或归档文件",
    }
    if original_bytes is not None:
        meta["original_bytes"] = original_bytes
    return {"_cygnusx_payload_truncated": True}, meta


def _cap_tool_invocation_payload(value: Any, limit: int = 200_000) -> Any:
    """tool_invocations 落库护栏。

    工具的 result/ui_payload 全量落库供历史重载重建卡片与图表；个别工具
    （如读大文件）载荷可能异常大，序列化超过 limit 时替换为截断标记，
    避免 metadata_json 无限膨胀；前端遇到标记时按"无载荷"降级渲染即可。
    """
    payload, _meta = _cap_tool_invocation_payload_detail(value, limit)
    return payload


def _normalize_ask_questions(args: dict[str, Any]) -> list[dict[str, Any]]:
    """ask_user 参数归一化为问题列表（最多 5 个）。

    优先取 questions[]（多问题分页收集），兼容单问题 question+options；
    模型偶尔把 questions 数组序列化成 JSON 字符串传来，先尝试解析还原；
    字符串还可能裹带前导换行、尾部多余引号等垃圾字符（json.loads 会直接
    失败），此时用 raw_decode 取第一个完整 JSON 值、忽略尾部内容；
    双重编码（解析出来仍是 JSON 字符串）时再解一次；
    模型未给出有效问题时兜底一个空问题，前端据此渲染自由输入，保证用户总能回复。
    """
    questions: list[dict[str, Any]] = []

    def _loose_json_loads(text: str) -> Any:
        """解析模型传来的 JSON 字符串，容忍尾部多余引号/换行（raw_decode 取首个完整值）。"""
        text = (text or "").strip()
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            try:
                value, _ = json.JSONDecoder().raw_decode(text)
                return value
            except (ValueError, TypeError):
                return None

    raw = args.get("questions")
    if isinstance(raw, str):
        parsed: Any = _loose_json_loads(raw)
        # 双重编码（解出来仍是 JSON 字符串）时再解一次，同样容忍尾部垃圾字符
        if isinstance(parsed, str):
            parsed = _loose_json_loads(parsed)
        if isinstance(parsed, list):
            raw = parsed
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question") or "").strip()
            if not q:
                continue
            opts_raw = item.get("options")
            opts = (
                [str(o) for o in opts_raw if str(o).strip()] if isinstance(opts_raw, list) else []
            )
            questions.append({"question": q, "options": opts})
    if not questions:
        single_q = str(args.get("question") or "").strip()
        opts_raw = args.get("options")
        single_opts = (
            [str(o) for o in opts_raw if str(o).strip()] if isinstance(opts_raw, list) else []
        )
        if single_q:
            questions.append({"question": single_q, "options": single_opts})
    if not questions:
        logger.warning("ask_user 调用缺少有效问题，降级为自由输入卡片，args={}", args)
        questions.append({"question": "", "options": []})
    return questions[:5]


def _fanout_ask_request(envelope: dict[str, Any]) -> dict[str, Any] | None:
    """从 fan-out 聚合结果提取首个需要用户处理的子任务问题。"""
    ui_payload = envelope.get("ui_payload") or {}
    progress = ui_payload.get("progress") if isinstance(ui_payload, dict) else None
    if not isinstance(progress, list):
        progress = []
    waiting_indexes = {
        int(item.get("index"))
        for item in progress
        if isinstance(item, dict)
        and str(item.get("status") or "") in {"awaiting_input", "approval_pending"}
        and str(item.get("index") or "").isdigit()
    }
    if not waiting_indexes:
        return None

    llm_payload = envelope.get("llm_payload") or {}
    results = llm_payload.get("results") if isinstance(llm_payload, dict) else None
    if not isinstance(results, list):
        return None
    for result in results:
        if not isinstance(result, dict):
            continue
        try:
            result_index = int(result.get("index") or 0)
        except (TypeError, ValueError):
            continue
        if result_index not in waiting_indexes:
            continue
        packet = result.get("packet") if isinstance(result.get("packet"), dict) else result
        if not isinstance(packet, dict) or not packet.get("needs_user_input"):
            continue
        questions = packet.get("questions")
        if not isinstance(questions, list):
            questions = [
                {"question": str(packet.get("user_request") or "请补充必要信息"), "options": []}
            ]
        normalized = _normalize_ask_questions({"questions": questions})
        first = normalized[0]
        return {
            "questions": normalized,
            "question": first["question"],
            "options": first["options"],
            "agent_id": str(result.get("agent_id") or ""),
            "task_id": str(result.get("task_id") or ""),
            "status": str(result.get("status") or packet.get("status") or "awaiting_input"),
        }
    return None


def _should_show_route_transition(
    previous_agent_id: str | None,
    target_agent_id: str,
    *,
    execution_confirmed: bool = False,
) -> bool:
    """首次路由、目标变化或执行确认时展示；同一目标的连续轮次保持安静。"""
    return execution_confirmed or not previous_agent_id or previous_agent_id != target_agent_id


def _is_route_execution_confirmation(user_text: str) -> bool:
    """判断用户是否明确确认执行已经路由的工作。"""
    normalized = user_text.replace(" ", "").lower()
    if any(
        marker in normalized for marker in ("暂不", "不要开始", "先不执行", "调整参数", "先调整")
    ):
        return False
    return any(
        marker in normalized
        for marker in (
            "开始分析",
            "确认开始",
            "开始执行",
            "确认执行",
            "按上述方案执行",
            "现在开始",
            "确认",
            "可以开始",
            "好的开始",
            "好的执行",
            "继续",
            "开始吧",
            "ok",
            "好开始",
            "进入工作台",
            "切换到工作台",
            "用工作台",
        )
    )
