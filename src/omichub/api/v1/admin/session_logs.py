"""会话日志排查 — 管理员按聊天会话聚合 AI 助手 / Agent / AI 工作台的可观测日志。

数据来源：
- 会话列表：chat_sessions 表（DB）。
- 事件时间线：loguru 结构化 JSON 日志（omichub.json.log）。会话作用域入口会把
  session_id 注入每条日志的 record.extra.session_id，这里按该字段过滤聚合。

可观测性排查设计（Phase 1）：
- 事件分类：semantic（AI/MCP/技能/Agent/工具箱等业务埋点）/ sql（SQLAlchemy echo）/
  system（中间件、审计等框架日志）。默认只返回 semantic，避免 SQL 噪声淹没语义事件。
- 合规（C1）：sql 类事件的原文（含绑定参数里的用户聊天内容）默认脱敏为「长度+哈希」，
  仅当 reveal_sensitive=true 时返回原文；每次访问都写一条 session_logs.access 审计日志。
- 过滤（C2）：支持按类别、级别过滤与会话内全文搜索。

仅管理员可访问（AdminRequired）。默认只扫描当前活动日志文件；置 include_archives=true
时额外扫描轮转归档（含 .zip），用于排查较旧的会话。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from loguru import logger
from sqlalchemy import Boolean, false, func, literal, or_, select

from omichub.api.deps import CurrentUserId, DbSession
from omichub.core.config import get_settings
from omichub.core.logging import _resolve_log_dir
from omichub.core.span_store import build_trace_tree, read_spans
from omichub.infrastructure.database.models.chat import (
    ChatMessageFeedbackModel,
    ChatMessageModel,
    ChatSessionModel,
)
from omichub.middleware.rbac import AdminRequired

router = APIRouter()

_JSON_LOG_NAME = "omichub.json.log"
# 这些是每条日志都有的标准关联字段，单独提升为顶层；其余 extra 归入 data。
_STANDARD_EXTRA_KEYS = {
    "trace_id",
    "span_id",
    "request_id",
    "session_id",
    "service",
    "event",
}
# 单次请求最多返回的事件数，避免超大会话拖垮接口。
_MAX_EVENTS = 2000

_VALID_CATEGORIES = {"semantic", "sql", "system"}
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_SQL_VERBS = {
    "SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "BEGIN", "COMMIT",
    "ROLLBACK", "CREATE", "ALTER", "DROP", "PRAGMA", "SAVEPOINT",
}


def _has_overdrive_history(
    session: ChatSessionModel,
    *,
    has_overdrive_messages: bool = False,
) -> bool:
    """Return whether this session has ever run through the overdrive runtime.

    ``overdrive`` is the current toggle state, so it can legitimately become
    false after an overdrive turn has finished.  The log explorer instead
    attributes a session by durable execution evidence as well, preventing a
    historical multi-agent run from being shown as a single-assistant chat.
    """
    meta = session.sandbox_meta or {}
    return bool(
        meta.get("overdrive")
        or meta.get("overdrive_used")
        or meta.get("overdrive_runs")
        or meta.get("overdrive_approvals")
        or meta.get("matrix_room_id")
        or has_overdrive_messages
    )


def _has_studio_history(session: ChatSessionModel) -> bool:
    """Return whether a session belongs to the AI workspace.

    ``workspace_id`` is the durable storage binding for Studio sessions.  It
    also lets the diagnostics list recognize older rows whose ``mode`` was
    written before the mode field became authoritative.
    """
    return session.mode == "studio" or bool(session.workspace_id)


def _execution_mode(
    session: ChatSessionModel,
    *,
    has_overdrive_messages: bool = False,
) -> str:
    """Normalize a session into the three user-visible execution modes.

    An overdrive run takes precedence over the workspace shell because it
    describes how the selected task was executed.  Keeping the normalization
    here ensures log search, export, and the admin UI use the same attribution
    rule.
    """
    if _has_overdrive_history(session, has_overdrive_messages=has_overdrive_messages):
        return "overdrive"
    if _has_studio_history(session):
        return "studio"
    return "chat"


def _json_key(col: Any, key: str) -> Any:
    """``col -> 'key'`` 取值表达式。

    SQLAlchemy 2.0.51 会把 ``col["key"]`` 编译成 ``col['key']`` 下标语法，
    PostgreSQL 14 对 json / jsonb 均不支持（PG16+ 才有），直接报
    DatatypeMismatchError。统一走 ``->`` 运算符兼容 PG14。
    """
    return col.op("->")(literal(key))


def _json_text(col: Any, key: str) -> Any:
    """``col ->> 'key'``：按键取文本值。"""
    return col.op("->>")(literal(key))


def _overdrive_history_predicate() -> Any:
    """SQL predicate matching current or historical overdrive execution evidence."""
    metadata = ChatSessionModel.sandbox_meta
    message_evidence = select(ChatMessageModel.message_id).where(
        ChatMessageModel.session_id == ChatSessionModel.session_id,
        ChatMessageModel.role == "assistant",
        _json_key(ChatMessageModel.metadata_json, "senderAgent").is_not(None),
    ).exists()
    return or_(
        func.coalesce(_json_text(metadata, "overdrive").cast(Boolean), false()).is_(True),
        func.coalesce(_json_text(metadata, "overdrive_used").cast(Boolean), false()).is_(True),
        _json_key(metadata, "overdrive_runs").is_not(None),
        _json_key(metadata, "overdrive_approvals").is_not(None),
        _json_key(metadata, "matrix_room_id").is_not(None),
        message_evidence,
    )


def _studio_history_predicate() -> Any:
    """SQL predicate matching the durable Studio mode or workspace binding."""
    return or_(
        ChatSessionModel.mode == "studio",
        ChatSessionModel.workspace_id.is_not(None),
    )


def _iter_json_log_files(log_dir: Path, include_archives: bool) -> list[Path]:
    """返回待扫描的 JSON 日志文件：活动文件优先，归档按修改时间倒序。"""
    files: list[Path] = []
    active = log_dir / _JSON_LOG_NAME
    if active.exists():
        files.append(active)
    if include_archives:
        archives = [
            p
            for p in log_dir.glob(f"{_JSON_LOG_NAME}.*")
            if p.is_file() and p != active
        ]
        archives.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        files.extend(archives)
    return files


def _read_lines(path: Path) -> list[str]:
    """读取日志文件内容行；支持 .zip 归档。损坏文件返回空。"""
    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist() if n.endswith(".log") or "." not in n]
                name = names[0] if names else (zf.namelist()[0] if zf.namelist() else None)
                if not name:
                    return []
                with zf.open(name) as fh:
                    return fh.read().decode("utf-8", errors="replace").splitlines()
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _is_sql(logger_name: str, message: str) -> bool:
    """判断一条日志是否为 SQLAlchemy echo 的 SQL 语句。"""
    if "sqlalchemy" in (logger_name or "").lower():
        return True
    msg = (message or "").strip()
    if not msg:
        return False
    if "[generated in" in msg or "[cached since" in msg or "[raw sql]" in msg:
        return True
    head = msg.split(None, 1)[0].upper().rstrip("(")
    return head in _SQL_VERBS


def _categorize(event: str | None, logger_name: str, message: str) -> str:
    """事件分类：sql（SQL echo）/ semantic（带 event 的业务埋点）/ system（其余框架日志）。"""
    if _is_sql(logger_name, message):
        return "sql"
    if event:
        return "semantic"
    return "system"


def _redact_sql_message(message: str) -> str:
    """把 SQL 原文脱敏为「动词 + 长度 + 短哈希」，避免绑定参数中的聊天内容外泄。"""
    raw = message or ""
    stripped = raw.strip()
    verb = stripped.split(None, 1)[0].upper() if stripped else "SQL"
    digest = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:12]
    return f"[已脱敏] {verb} · 长度 {len(raw)} · sha256:{digest}"


def _record_to_event(record: dict[str, Any], reveal_sensitive: bool) -> dict[str, Any]:
    """把 loguru serialize 记录的 record 段转换为前端时间线事件。"""
    extra = record.get("extra") or {}
    time_info = record.get("time") or {}
    timestamp = time_info.get("repr")
    if not timestamp:
        ts = time_info.get("timestamp")
        timestamp = (
            datetime.fromtimestamp(ts, tz=UTC).isoformat() if isinstance(ts, (int, float)) else ""
        )
    level = (record.get("level") or {}).get("name", "")
    logger_name = record.get("name", "")
    message = record.get("message", "")
    event = extra.get("event")
    category = _categorize(event, logger_name, message)
    data = {k: v for k, v in extra.items() if k not in _STANDARD_EXTRA_KEYS}

    redacted = False
    if category == "sql" and not reveal_sensitive:
        message = _redact_sql_message(message)
        data = {}
        redacted = True

    return {
        "timestamp": timestamp,
        "level": level,
        "category": category,
        "event": event,
        "message": message,
        "logger": logger_name,
        "function": record.get("function", ""),
        "line": record.get("line"),
        "trace_id": extra.get("trace_id", ""),
        "span_id": extra.get("span_id", ""),
        "request_id": extra.get("request_id", ""),
        "redacted": redacted,
        "data": data,
    }


def _parse_set(raw: str | None, upper: bool = False) -> set[str] | None:
    """把逗号分隔字符串解析为集合；空/None 返回 None（表示不过滤）。"""
    if not raw:
        return None
    items = {x.strip().upper() if upper else x.strip() for x in raw.split(",")}
    items.discard("")
    return items or None


def _collect_session_events(
    log_dir: Path,
    session_id: str,
    include_archives: bool,
    limit: int,
    categories: set[str] | None,
    levels: set[str] | None,
    search: str | None,
    reveal_sensitive: bool,
) -> list[dict[str, Any]]:
    """扫描日志文件，收集指定 session_id 的事件（按类别/级别/关键词过滤），时间升序返回。"""
    events: list[dict[str, Any]] = []
    search_l = search.strip().lower() if search else None
    for path in _iter_json_log_files(log_dir, include_archives):
        for line in _read_lines(path):
            line = line.strip()
            if not line or session_id not in line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            record = payload.get("record") or {}
            extra = record.get("extra") or {}
            if extra.get("session_id") != session_id:
                continue
            ev = _record_to_event(record, reveal_sensitive)
            if categories and ev["category"] not in categories:
                continue
            if levels and (ev["level"] or "").upper() not in levels:
                continue
            if search_l:
                haystack = (ev["message"] + " " + json.dumps(ev["data"], ensure_ascii=False)).lower()
                if search_l not in haystack:
                    continue
            events.append(ev)
    events.sort(key=lambda e: e.get("timestamp") or "")
    return events[:limit]


def _summarize_traces(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把扁平 span 列表按 trace_id 聚合为 trace 摘要（供列表展示）。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for s in spans:
        grouped.setdefault(s.get("trace_id") or "", []).append(s)
    summaries: list[dict[str, Any]] = []
    for trace_id, group in grouped.items():
        if not trace_id:
            continue
        group.sort(key=lambda x: x.get("start_ns") or 0)
        root = next((g for g in group if not g.get("parent_span_id")), group[0])
        start_ns = min((g.get("start_ns") or 0) for g in group)
        end_ns = max(
            (g.get("start_ns") or 0) + int((g.get("duration_ms") or 0) * 1_000_000) for g in group
        )
        summaries.append(
            {
                "trace_id": trace_id,
                "session_id": root.get("session_id", ""),
                "root_name": root.get("name", ""),
                "start_time": root.get("start_time", ""),
                "duration_ms": round((end_ns - start_ns) / 1_000_000, 3),
                "span_count": len(group),
                "has_error": any((g.get("status_code") or "") == "ERROR" for g in group),
                "service": root.get("service", ""),
            }
        )
    summaries.sort(key=lambda x: x.get("start_time") or "", reverse=True)
    return summaries


@router.get("/sessions", summary="会话列表（供日志排查选择）")
async def list_sessions(
    _admin: AdminRequired,
    db: DbSession,
    search: Annotated[str | None, Query(description="按 session_id / 标题 / 用户 模糊匹配")] = None,
    mode: Annotated[str | None, Query(description="chat / studio / overdrive")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """按最近活跃倒序列出聊天会话，管理员据此挑选要排查的会话。"""
    stmt = select(ChatSessionModel)
    overdrive_history = _overdrive_history_predicate()
    studio_history = _studio_history_predicate()
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                ChatSessionModel.session_id.ilike(pattern),
                ChatSessionModel.title.ilike(pattern),
                ChatSessionModel.user_id.ilike(pattern),
            )
        )
    if mode == "studio":
        stmt = stmt.where(studio_history, ~overdrive_history)
    elif mode == "overdrive":
        stmt = stmt.where(overdrive_history)
    elif mode == "chat":
        stmt = stmt.where(
            ~studio_history,
            ~overdrive_history,
        )
    elif mode:
        raise HTTPException(status_code=422, detail="mode 仅支持 chat、studio 或 overdrive")
    stmt = stmt.order_by(ChatSessionModel.last_message_at.desc().nullslast()).limit(limit)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # ``senderAgent`` is recorded on every overdrive Manager/Worker response.
    # It is a fallback for sessions created before ``overdrive_used`` existed
    # or whose JSON metadata was later merged by a concurrent feature.
    session_ids = [session.session_id for session in sessions]
    overdrive_message_session_ids: set[str] = set()
    if session_ids:
        overdrive_messages = await db.execute(
            select(ChatMessageModel.session_id)
            .where(
                ChatMessageModel.session_id.in_(session_ids),
                ChatMessageModel.role == "assistant",
                _json_key(ChatMessageModel.metadata_json, "senderAgent").is_not(None),
            )
            .distinct()
        )
        overdrive_message_session_ids = set(overdrive_messages.scalars().all())

    # 批量查用户名（F2：列表展示用户名而非裸 UUID）
    user_names: dict[str, str] = {}
    user_uuids: list[uuid.UUID] = []
    for s in sessions:
        try:
            user_uuids.append(uuid.UUID(s.user_id))
        except (ValueError, AttributeError, TypeError):
            continue
    if user_uuids:
        from omichub.infrastructure.database.models.user import UserModel

        ures = await db.execute(select(UserModel).where(UserModel.id.in_(user_uuids)))
        for u in ures.scalars().all():
            user_names[str(u.id)] = u.nickname or u.username

    return [
        {
            "session_id": s.session_id,
            "user_id": s.user_id,
            "user_name": user_names.get(s.user_id, ""),
            "title": s.title,
            "mode": s.mode,
            "execution_mode": _execution_mode(
                s,
                has_overdrive_messages=s.session_id in overdrive_message_session_ids,
            ),
            "agent_id": s.agent_id,
            "assistant_id": s.assistant_id,
            "status": s.status,
            "message_count": s.message_count,
            "total_tokens": s.total_tokens,
            "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
        }
        for s in sessions
    ]


@router.get("/feedbacks", summary="用户会话反馈列表（点赞 / 点踩）")
async def list_feedbacks(
    _admin: AdminRequired,
    db: DbSession,
    rating: Annotated[str | None, Query(description="like / dislike")] = None,
    search: Annotated[str | None, Query(description="按 session_id / 标题 / 用户 / 备注模糊匹配")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """列出用户对 AI 消息的反馈。点踩记录附带模型 / Agent / 提问与回复摘录快照，
    用于提示词、Agent 与架构的优化分析。"""
    stmt = select(ChatMessageFeedbackModel)
    if rating in ("like", "dislike"):
        stmt = stmt.where(ChatMessageFeedbackModel.rating == rating)
    elif rating:
        raise HTTPException(status_code=422, detail="rating 仅支持 like 或 dislike")

    feedbacks = (
        await db.execute(stmt.order_by(ChatMessageFeedbackModel.created_at.desc()))
    ).scalars().all()

    # 关联会话（标题 / 模式）与用户名
    session_ids = sorted({f.session_id for f in feedbacks})
    sessions: dict[str, ChatSessionModel] = {}
    if session_ids:
        res = await db.execute(
            select(ChatSessionModel).where(ChatSessionModel.session_id.in_(session_ids))
        )
        sessions = {s.session_id: s for s in res.scalars().all()}

    user_names: dict[str, str] = {}
    user_uuids: list[uuid.UUID] = []
    for f in feedbacks:
        try:
            user_uuids.append(uuid.UUID(f.user_id))
        except (ValueError, AttributeError, TypeError):
            continue
    if user_uuids:
        from omichub.infrastructure.database.models.user import UserModel

        ures = await db.execute(select(UserModel).where(UserModel.id.in_(user_uuids)))
        for u in ures.scalars().all():
            user_names[str(u.id)] = u.nickname or u.username

    if search:
        search_l = search.lower()

        def _match(f: ChatMessageFeedbackModel) -> bool:
            session = sessions.get(f.session_id)
            haystack = " ".join(
                [
                    f.session_id,
                    f.user_id,
                    user_names.get(f.user_id, ""),
                    session.title if session else "",
                    f.comment or "",
                ]
            ).lower()
            return search_l in haystack

        feedbacks = [f for f in feedbacks if _match(f)]

    total = len(feedbacks)
    page = feedbacks[offset : offset + limit]
    return {
        "total": total,
        "items": [
            {
                "feedback_id": f.feedback_id,
                "session_id": f.session_id,
                "message_id": f.message_id,
                "user_id": f.user_id,
                "user_name": user_names.get(f.user_id, ""),
                "rating": f.rating,
                "comment": f.comment,
                "status": f.status,
                "context": f.context or {},
                "session_title": sessions[f.session_id].title if f.session_id in sessions else "",
                "execution_mode": _execution_mode(sessions[f.session_id])
                if f.session_id in sessions
                else "chat",
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in page
        ],
    }


@router.get("/{session_id}/events", summary="按会话聚合的日志事件时间线")
async def session_events(
    _admin: AdminRequired,
    admin_id: CurrentUserId,
    session_id: str,
    categories: Annotated[
        str | None,
        Query(description="逗号分隔类别: semantic,sql,system；默认仅 semantic（隐藏 SQL/系统噪声）"),
    ] = None,
    levels: Annotated[
        str | None,
        Query(description="逗号分隔级别: DEBUG,INFO,WARNING,ERROR,CRITICAL；默认全部"),
    ] = None,
    search: Annotated[str | None, Query(description="会话内全文搜索（匹配消息与数据字段）")] = None,
    reveal_sensitive: Annotated[
        bool, Query(description="显示 SQL 敏感原文（含绑定参数）；该动作会被审计记录")
    ] = False,
    include_archives: Annotated[
        bool, Query(description="是否同时扫描轮转归档（含 .zip），排查较旧会话时开启")
    ] = False,
    limit: Annotated[int, Query(ge=1, le=_MAX_EVENTS)] = 500,
) -> dict[str, Any]:
    """返回该会话的可观测事件时间线（默认仅语义事件），支持类别/级别过滤与会话内搜索。"""
    try:
        log_dir = _resolve_log_dir()
    except PermissionError as exc:
        raise HTTPException(status_code=500, detail=f"日志目录不可读: {exc}") from exc

    cat_set = _parse_set(categories) or {"semantic"}
    invalid = cat_set - _VALID_CATEGORIES
    if invalid:
        raise HTTPException(status_code=400, detail=f"非法类别: {', '.join(sorted(invalid))}")
    lvl_set = _parse_set(levels, upper=True)
    if lvl_set is not None:
        invalid_lvl = lvl_set - _VALID_LEVELS
        if invalid_lvl:
            raise HTTPException(status_code=400, detail=f"非法级别: {', '.join(sorted(invalid_lvl))}")

    events = _collect_session_events(
        log_dir,
        session_id,
        include_archives,
        limit,
        cat_set,
        lvl_set,
        search,
        reveal_sensitive,
    )

    # 合规审计：记录谁在何时查看了哪个会话日志、查看了哪些类别、是否揭示敏感原文。
    logger.bind(
        event="session_logs.access",
        admin_user_id=admin_id,
        target_session_id=session_id,
        categories=sorted(cat_set),
        levels=sorted(lvl_set) if lvl_set else None,
        search=search,
        reveal_sensitive=reveal_sensitive,
        count=len(events),
    ).info("session logs accessed")

    return {
        "session_id": session_id,
        "log_dir": str(log_dir),
        "include_archives": include_archives,
        "categories": sorted(cat_set),
        "levels": sorted(lvl_set) if lvl_set else None,
        "reveal_sensitive": reveal_sensitive,
        "count": len(events),
        "events": events,
    }


@router.get("/traces/{trace_id}", summary="单条 Trace 的 span 树（瀑布图数据）")
async def trace_detail(
    _admin: AdminRequired,
    admin_id: CurrentUserId,
    trace_id: str,
    include_archives: Annotated[bool, Query(description="是否同时扫描轮转归档")] = False,
) -> dict[str, Any]:
    """返回该 trace_id 的完整 span 树（含父子关系、耗时、属性、异常事件），供瀑布图渲染。"""
    try:
        log_dir = _resolve_log_dir()
    except PermissionError as exc:
        raise HTTPException(status_code=500, detail=f"日志目录不可读: {exc}") from exc
    spans = read_spans(log_dir, trace_id=trace_id, include_archives=include_archives)
    logger.bind(
        event="session_logs.access",
        admin_user_id=admin_id,
        target_trace_id=trace_id,
        view="trace_detail",
        count=len(spans),
    ).info("trace detail accessed")
    return {
        "trace_id": trace_id,
        "span_count": len(spans),
        "tree": build_trace_tree(spans),
    }


@router.get("/{session_id}/traces", summary="会话的 Trace 列表")
async def session_traces(
    _admin: AdminRequired,
    admin_id: CurrentUserId,
    session_id: str,
    include_archives: Annotated[bool, Query(description="是否同时扫描轮转归档")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """列出该会话产生的所有 trace（按时间倒序），每条含根 span、耗时、span 数、是否出错。"""
    try:
        log_dir = _resolve_log_dir()
    except PermissionError as exc:
        raise HTTPException(status_code=500, detail=f"日志目录不可读: {exc}") from exc
    spans = read_spans(log_dir, session_id=session_id, include_archives=include_archives)
    traces = _summarize_traces(spans)[:limit]
    logger.bind(
        event="session_logs.access",
        admin_user_id=admin_id,
        target_session_id=session_id,
        view="trace_list",
        count=len(traces),
    ).info("session traces accessed")
    return {
        "session_id": session_id,
        "count": len(traces),
        "traces": traces,
    }


def _attr(span: dict[str, Any], *keys: str) -> Any:
    """从 span.attributes 里按候选键取第一个非空值。"""
    attrs = span.get("attributes") or {}
    for k in keys:
        if attrs.get(k) not in (None, ""):
            return attrs[k]
    return None


def _build_session_report(
    session_id: str, spans: list[dict[str, Any]], event_count: int
) -> dict[str, Any]:
    """把一个会话的 span 聚合为运行小结：AI 用量/成本/耗时、工具与技能统计、错误摘要。"""
    rate = float(get_settings().ai_token_cookie_rate)

    trace_ids: set[str] = set()
    ai_calls = 0
    prompt_tokens = completion_tokens = total_tokens = 0
    ai_duration_ms = 0.0
    models: dict[str, dict[str, Any]] = {}
    tool_stats: dict[str, int] = {}
    skill_stats: dict[str, int] = {}
    errors: list[dict[str, Any]] = []
    start_ns: int | None = None
    end_ns: int | None = None

    for s in spans:
        name = s.get("name") or ""
        trace_ids.add(s.get("trace_id") or "")
        s_ns = s.get("start_ns") or 0
        e_ns = s_ns + int((s.get("duration_ms") or 0) * 1_000_000)
        if s_ns:
            start_ns = s_ns if start_ns is None else min(start_ns, s_ns)
            end_ns = e_ns if end_ns is None else max(end_ns, e_ns)

        if (s.get("status_code") or "") == "ERROR":
            errors.append(
                {
                    "name": name,
                    "message": (s.get("status_message") or "")[:300],
                    "time": s.get("start_time", ""),
                }
            )

        if name == "ai.chat":
            ai_calls += 1
            pt = int(_attr(s, "ai.prompt_tokens") or 0)
            ct = int(_attr(s, "ai.completion_tokens") or 0)
            tt = int(_attr(s, "ai.total_tokens") or (pt + ct))
            prompt_tokens += pt
            completion_tokens += ct
            total_tokens += tt
            ai_duration_ms += float(s.get("duration_ms") or 0)
            model = str(_attr(s, "ai.model") or "unknown")
            m = models.setdefault(
                model, {"calls": 0, "tokens": 0, "errors": 0}
            )
            m["calls"] += 1
            m["tokens"] += tt
            if (s.get("status_code") or "") == "ERROR":
                m["errors"] += 1
        elif name.startswith("mcp.") or name == "agent.tool_dispatch":
            tool = str(_attr(s, "tool.name", "tool", "mcp.tool") or name)
            tool_stats[tool] = tool_stats.get(tool, 0) + 1
        elif name == "skill.execute":
            tool = str(_attr(s, "tool_name", "skill_id") or "unknown")
            skill_stats[tool] = skill_stats.get(tool, 0) + 1

    wall_ms = round((end_ns - start_ns) / 1_000_000, 1) if start_ns and end_ns else 0.0
    cost = round(total_tokens / 1000.0 * rate, 4)
    model_list = [
        {"model": k, "calls": v["calls"], "tokens": v["tokens"], "errors": v["errors"]}
        for k, v in sorted(models.items(), key=lambda kv: kv[1]["tokens"], reverse=True)
    ]
    return {
        "session_id": session_id,
        "cookie_rate": rate,
        "summary": {
            "trace_count": len([t for t in trace_ids if t]),
            "span_count": len(spans),
            "log_event_count": event_count,
            "wall_duration_ms": wall_ms,
            "ai_calls": ai_calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_cookie": cost,
            "ai_duration_ms": round(ai_duration_ms, 1),
            "error_count": len(errors),
        },
        "models": model_list,
        "tool_calls": [
            {"tool": k, "count": v} for k, v in sorted(tool_stats.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "skill_calls": [
            {"skill": k, "count": v} for k, v in sorted(skill_stats.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "errors": errors[:50],
    }


@router.get("/{session_id}/report", summary="单会话运行报告")
async def session_report(
    _admin: AdminRequired,
    admin_id: CurrentUserId,
    session_id: str,
    include_archives: Annotated[bool, Query(description="是否同时扫描轮转归档")] = False,
) -> dict[str, Any]:
    """聚合该会话的 span 与日志事件，生成运行小结（token/成本/耗时/工具统计/错误摘要）。"""
    try:
        log_dir = _resolve_log_dir()
    except PermissionError as exc:
        raise HTTPException(status_code=500, detail=f"日志目录不可读: {exc}") from exc
    spans = read_spans(log_dir, session_id=session_id, include_archives=include_archives)
    events = _collect_session_events(
        log_dir, session_id, include_archives, _MAX_EVENTS, None, None, None, False
    )
    logger.bind(
        event="session_logs.access",
        admin_user_id=admin_id,
        target_session_id=session_id,
        view="report",
        count=len(spans),
    ).info("session report accessed")
    return _build_session_report(session_id, spans, len(events))


# 导出列：扁平化事件，data 字段序列化为 JSON 字符串以便 CSV 打开。
_EXPORT_COLUMNS = [
    "timestamp", "level", "category", "event", "message", "logger",
    "trace_id", "span_id", "request_id", "redacted", "data",
]


@router.get("/{session_id}/events/export", summary="导出会话日志（JSON/CSV）")
async def session_events_export(
    _admin: AdminRequired,
    admin_id: CurrentUserId,
    session_id: str,
    format: Annotated[str, Query(description="导出格式: json / csv")] = "json",
    categories: Annotated[str | None, Query(description="逗号分隔类别；默认全部")] = None,
    levels: Annotated[str | None, Query(description="逗号分隔级别")] = None,
    search: Annotated[str | None, Query(description="会话内全文搜索")] = None,
    include_archives: Annotated[bool, Query(description="是否同时扫描轮转归档")] = False,
    limit: Annotated[int, Query(ge=1, le=_MAX_EVENTS)] = _MAX_EVENTS,
) -> Response:
    """把该会话日志事件导出为文件。SQL 原文始终脱敏（导出不提供揭示敏感原文）。"""
    fmt = format.lower()
    if fmt not in {"json", "csv"}:
        raise HTTPException(status_code=400, detail="format 仅支持 json / csv")
    try:
        log_dir = _resolve_log_dir()
    except PermissionError as exc:
        raise HTTPException(status_code=500, detail=f"日志目录不可读: {exc}") from exc

    cat_set = _parse_set(categories)
    if cat_set:
        invalid = cat_set - _VALID_CATEGORIES
        if invalid:
            raise HTTPException(status_code=400, detail=f"非法类别: {', '.join(sorted(invalid))}")
    lvl_set = _parse_set(levels, upper=True)

    events = _collect_session_events(
        log_dir, session_id, include_archives, limit, cat_set, lvl_set, search, False
    )
    logger.bind(
        event="session_logs.access",
        admin_user_id=admin_id,
        target_session_id=session_id,
        view="export",
        format=fmt,
        count=len(events),
    ).info("session logs exported")

    safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "session"
    if fmt == "json":
        body = json.dumps(
            {"session_id": session_id, "count": len(events), "events": events},
            ensure_ascii=False,
            indent=2,
        )
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="session_{safe_id}.json"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_EXPORT_COLUMNS)
    for ev in events:
        writer.writerow(
            [
                ev.get("timestamp", ""),
                ev.get("level", ""),
                ev.get("category", ""),
                ev.get("event", ""),
                ev.get("message", ""),
                ev.get("logger", ""),
                ev.get("trace_id", ""),
                ev.get("span_id", ""),
                ev.get("request_id", ""),
                ev.get("redacted", ""),
                json.dumps(ev.get("data") or {}, ensure_ascii=False),
            ]
        )
    return Response(
        content="\ufeff" + buf.getvalue(),  # BOM 便于 Excel 正确识别 UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="session_{safe_id}.csv"'},
    )
