"""AgentTeams 自省查询面（F4）：内部角色"查自己历史"的只读结构化通道。

口径（docs/info/26.8.21/协作室融合ClaudeScience设计理念评估与实施方案.md F4）：

- 四个预置模板覆盖高频自省：``artifact_versions``（本 case 已登记产物及版本）、
  ``event_timeline``（本 case 事件时间线）、``pending_approvals``（本 room 待办审批）、
  ``artifact_lineage``（产物血缘一级展开）；另有 ``schema`` 模板返回表/列说明文档
  （渐进暴露：工具描述常驻一句话索引，正文按需经本模板取）。
- 受限 SQL 是上限能力：单表 SELECT、表白名单（仅三张 case 维度只读表）、
  强制 ``case_id`` 过滤注入（独立 AND 谓词，调用方无法摆脱）、列名/运算符
  白名单分词校验、行数上限。无 SQL 解析器依赖（仓库未引入 sqlparse/sqlglot），
  故语法面刻意收窄：禁括号/分号/注释/引号（除单引号字符串字面量）。
- scope 强制限定当前 case：``room_id`` 与 ``case_id`` 绑定关系在平台 DB
  校验，错配即拒；所有数据查询都以校验后的 case_id 为唯一过滤键。
- denied 纵深防御：密钥/token/宿主基础设施类关键词按词边界匹配（防
  ``worker_token`` 这类下划线别名绕过 ``token`` 的匹配），命中即拒并写审计。
- 所有查询调用（含被拒）写审计事件（``case.introspection_query`` /
  ``case.introspection_denied``，平台 manager 身份写 Case 级事件流），
  验收 V6（Manager 走查询接口而非自由发挥）因此可取证。放行路径审计写入
  失败则查询 fail-closed（无审计不返数据）；拒绝路径审计尽力而为
  （拒绝本身不依赖 Bridge 可用性）。
- 行数上限 + 服务端聚合：``total_count`` 始终为服务端全量计数，
  ``truncated=True`` 时附 ``aggregate`` 摘要，防行数截断造成低估。
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.agentteams_artifact_lineage_service import (
    AgentTeamsArtifactLineageService,
)
from cygnusx.application.services.agentteams_audit_chain_service import (
    AgentTeamsAuditChainService,
)
from cygnusx.application.services.agentteams_service import (
    CASE_LEVEL_WORK_ITEM_ID,
    AgentTeamsService,
)
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError, ValidationError
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsRoomModel,
    CaseArtifactDependencyModel,
    CaseArtifactVersionModel,
    QcVerificationCheckModel,
)

# 行数上限：默认 50，硬顶 200（服务端 total_count 不受截断影响）。
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
# 事件时间线/待办审批模板从审计总线取链的上限（与既有审计链端点默认一致）。
_TIMELINE_MAX_EVENTS = 5_000

QUERY_AUDIT_EVENT_TYPE = "case.introspection_query"
DENIED_AUDIT_EVENT_TYPE = "case.introspection_denied"

TEMPLATES = frozenset(
    {"artifact_versions", "event_timeline", "pending_approvals", "artifact_lineage", "schema"}
)

# 受限 SQL 表白名单：仅 case 维度的只读事实表（均有 case_id 列可强制注入）。
_ALLOWED_SQL_TABLES: dict[str, type] = {
    "case_artifact_versions": CaseArtifactVersionModel,
    "case_artifact_dependencies": CaseArtifactDependencyModel,
    "qc_verification_checks": QcVerificationCheckModel,
}

# denied 清单（F4）：密钥/token/宿主基础设施类。ASCII 词按词边界匹配
# （``(?<![A-Za-z0-9_])`` 前后断言），下划线复合别名（worker_token、api_key）
# 单独列出，避免 ``token`` 的词边界被 ``_`` 截断而绕过；CJK 词按子串匹配。
_DENIED_ASCII_WORDS = (
    "secret",
    "secrets",
    "password",
    "passwd",
    "pwd",
    "credential",
    "credentials",
    "token",
    "tokens",
    "apikey",
    "api_key",
    "api_keys",
    "private_key",
    "access_key",
    "secret_key",
    "session_key",
    "worker_token",
    "worker_tokens",
    "jwt",
    "bearer",
    "key",
    "keys",
    "host",
    "hosts",
    "hostname",
    "kubeconfig",
    "ssh",
    "minio",
    "redis",
    "postgres",
    "postgresql",
    "vault",
)
_DENIED_CJK_WORDS = ("密钥", "密码", "口令", "令牌", "凭据", "凭证", "主机", "宿主", "基础设施")

_DENIED_ASCII_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(_DENIED_ASCII_WORDS) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

# 受限 SQL 语法面：单表 SELECT，禁括号/分号/注释/反引号/双引号/@/反斜杠，
# 从根上去掉子查询、函数调用、多语句与注释绕过。
_SQL_FORBIDDEN_TOKENS = (";", "--", "/*", "*/", "(", ")", "`", '"', "@", "\\")
_SQL_STATEMENT_RE = re.compile(
    r"^\s*SELECT\s+(?P<columns>[A-Za-z0-9_,\s.*]+?)\s+FROM\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+WHERE\s+(?P<where>.+?))?"
    r"(?:\s+ORDER\s+BY\s+(?P<order>[A-Za-z0-9_,\s.]+?))?"
    r"\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SQL_WHERE_TOKEN_RE = re.compile(
    r"\s*(?:'(?:[^']|'')*'|[0-9]+(?:\.[0-9]+)?|[A-Za-z_][A-Za-z0-9_]*|<=|>=|<>|!=|=|<|>)",
    re.DOTALL,
)
_SQL_WHERE_KEYWORDS = frozenset(
    {"AND", "OR", "NOT", "LIKE", "IS", "NULL", "TRUE", "FALSE", "BETWEEN", "IN"}
)
_SQL_ORDER_TERM_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\s+(ASC|DESC))?$", re.IGNORECASE)
# IN/BETWEEN 需要括号或范围字面量，括号已禁；保留关键词占位以便给出明确报错。


class IntrospectionDeniedError(BusinessError):
    """自省查询被拒（越 scope 或命中 denied 清单）；message 对外保持笼统。"""

    def __init__(self, message: str, *, matched: str | None = None) -> None:
        super().__init__(message)
        # 命中的 denied 词只进审计 payload，不进对外报错文案。
        self.matched = matched


def scan_denied(text_value: str) -> str | None:
    """返回命中的 denied 词（无命中返回 None）；供服务与测试共用同一口径。"""
    match = _DENIED_ASCII_RE.search(text_value)
    if match:
        return match.group(0).lower()
    for word in _DENIED_CJK_WORDS:
        if word in text_value:
            return word
    return None


def load_introspection_schema_doc() -> str:
    """读取自省 schema 文档（表/列说明），路径与 prompts registry 同目录约定。"""
    path = Path(get_settings().prompts_registry_yaml).parent / "agentteams_introspection_schema.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("AgentTeams introspection schema doc missing: {}", path)
        return ""


class AgentTeamsIntrospectionService:
    """``query_case_facts`` 的平台侧实现：模板 + 受限 SQL，scope/审计强制。"""

    def __init__(
        self,
        *,
        agentteams: AgentTeamsService | None = None,
        audit_chain: AgentTeamsAuditChainService | None = None,
    ) -> None:
        # 无参构造兼容 tool_bridge 的反射实例化（Phase 1 约定：service 无参构造）。
        self._agentteams = agentteams
        self._audit_chain = audit_chain

    async def query_case_facts(
        self,
        db: AsyncSession,
        *,
        case_id: str,
        caller: str,
        room_id: str | None = None,
        template: str | None = None,
        sql: str | None = None,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        """自省查询主入口。``owner_id`` 非空时追加归属校验（工具调用路径）。"""
        caller = " ".join(str(caller or "").split())[:80]
        if not caller:
            raise ValidationError("caller 不能为空")
        case_id = str(case_id or "").strip()[:80]
        if not case_id:
            raise ValidationError("case_id 不能为空")
        if (template is None) == (sql is None):
            raise ValidationError("template 与 sql 必须且只能提供一个")
        row_limit = _clamp_limit(limit)
        params = params or {}
        query_desc = template if template is not None else f"sql:{_sql_hash(sql or '')}"

        try:
            room = await self._verify_scope(db, case_id, room_id, owner_id=owner_id)
            if sql is not None:
                self._screen_sql(sql)
            self._screen_params(params)
            if template is not None:
                if template not in TEMPLATES:
                    raise IntrospectionDeniedError("自省查询被拒绝：未知模板")
                result = await self._run_template(
                    db, template, case_id=case_id, room=room, params=params, limit=row_limit
                )
            else:
                result = await self._run_restricted_sql(
                    db, str(sql), case_id=case_id, limit=row_limit
                )
        except IntrospectionDeniedError as exc:
            await self._record_denied(
                case_id, caller=caller, query=query_desc, reason=str(exc), matched=exc.matched
            )
            raise

        await self._record_query(
            case_id,
            caller=caller,
            query=query_desc,
            row_count=result["row_count"],
            total_count=result["total_count"],
            truncated=result["truncated"],
        )
        return {
            "case_id": case_id,
            "room_id": room.room_id if room is not None else (room_id or None),
            **result,
        }

    # ---- 工具入口（agentteams_case 工具包，内部角色经 tool_bridge 调用） ----

    async def query_case_facts_tool(
        self,
        *,
        user_id: str,
        case_id: str,
        template: str | None = None,
        sql: str | None = None,
        params: dict[str, Any] | None = None,
        room_id: str | None = None,
        limit: int | None = None,
        context: ToolInvocationContext | None = None,
    ) -> dict[str, Any]:
        if context is None or not context.user_id:
            raise BusinessError("自省查询工具需要受控的会话调用上下文")
        if user_id != context.user_id:
            raise ValidationError("工具调用用户与受控上下文不一致")
        return await self.query_case_facts(
            context.db,
            case_id=case_id,
            caller=f"tool:{context.agent_id or 'internal-role'}",
            room_id=room_id,
            template=template,
            sql=sql,
            params=params,
            limit=limit,
            owner_id=context.user_id,
        )

    # ---- scope 与 denied ----

    async def _verify_scope(
        self,
        db: AsyncSession,
        case_id: str,
        room_id: str | None,
        *,
        owner_id: str | None,
    ) -> AgentTeamsRoomModel | None:
        if case_id.startswith("room-"):
            raise IntrospectionDeniedError(
                "自省查询被拒绝：房间未立项时请使用 room_facts_query 或 room_messages_read"
            )
        if room_id is not None:
            room = await db.scalar(
                select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.room_id == room_id)
            )
            if room is None:
                raise IntrospectionDeniedError("自省查询被拒绝：room 不存在")
            if room.case_id != case_id:
                raise IntrospectionDeniedError(
                    "自省查询被拒绝：room 与 case 绑定不一致（越 scope）"
                )
        else:
            room = await db.scalar(
                select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.case_id == case_id)
            )
        if owner_id is not None:
            if room is not None:
                if room.owner_id != owner_id:
                    raise IntrospectionDeniedError("自省查询被拒绝：case 不属于当前调用方")
            else:
                # 无房间绑定的 Case：回退 Bridge requester 口径校验归属。
                await self._agentteams_service().get_case(case_id, owner_id)
        return room

    def _screen_sql(self, sql: str) -> None:
        matched = scan_denied(sql)
        if matched is not None:
            raise IntrospectionDeniedError("自省查询被拒绝：命中受限关键词", matched=matched)

    @staticmethod
    def _screen_params(params: dict[str, Any]) -> None:
        for value in params.values():
            if isinstance(value, str):
                matched = scan_denied(value)
                if matched is not None:
                    raise IntrospectionDeniedError(
                        "自省查询被拒绝：参数命中受限关键词", matched=matched
                    )

    # ---- 预置模板 ----

    async def _run_template(
        self,
        db: AsyncSession,
        template: str,
        *,
        case_id: str,
        room: AgentTeamsRoomModel | None,
        params: dict[str, Any],
        limit: int,
    ) -> dict[str, Any]:
        if template == "artifact_versions":
            return await self._template_artifact_versions(db, case_id, params, limit)
        if template == "artifact_lineage":
            return await self._template_artifact_lineage(db, case_id, params, limit)
        if template == "event_timeline":
            return await self._template_event_timeline(db, case_id, params, limit)
        if template == "pending_approvals":
            return await self._template_pending_approvals(db, case_id, room, limit)
        return {
            "template": "schema",
            "rows": [],
            "row_count": 0,
            "total_count": 0,
            "truncated": False,
            "aggregate": {},
            "document": load_introspection_schema_doc(),
        }

    async def _template_artifact_versions(
        self, db: AsyncSession, case_id: str, params: dict[str, Any], limit: int
    ) -> dict[str, Any]:
        model = CaseArtifactVersionModel
        filters = [model.case_id == case_id]
        artifact_id = _optional_str(params, "artifact_id", 512)
        if artifact_id:
            filters.append(model.artifact_id == artifact_id)
        work_item_id = _optional_str(params, "work_item_id", 128)
        if work_item_id:
            filters.append(model.work_item_id == work_item_id)
        total = int(await db.scalar(select(func.count()).select_from(model).where(*filters)) or 0)
        aggregate_row = (
            await db.execute(
                select(
                    func.count(func.distinct(model.artifact_id)),
                    func.coalesce(func.sum(model.size_bytes), 0),
                ).where(*filters)
            )
        ).one()
        rows = (
            (
                await db.execute(
                    select(model)
                    .where(*filters)
                    .order_by(model.artifact_id, model.version_no)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return _result_envelope(
            template="artifact_versions",
            rows=[_artifact_version_row(row) for row in rows],
            total_count=total,
            aggregate={
                "artifact_count": int(aggregate_row[0]),
                "total_size_bytes": int(aggregate_row[1]),
            },
        )

    async def _template_artifact_lineage(
        self, db: AsyncSession, case_id: str, params: dict[str, Any], limit: int
    ) -> dict[str, Any]:
        lineage = await AgentTeamsArtifactLineageService(db).case_lineage(case_id)
        versions = list(lineage["versions"])
        artifact_id = _optional_str(params, "artifact_id", 512)
        if artifact_id:
            versions = [row for row in versions if row["artifact_id"] == artifact_id]
        return _result_envelope(
            template="artifact_lineage",
            rows=versions[:limit],
            total_count=len(versions),
            aggregate={
                "artifact_count": len({row["artifact_id"] for row in versions}),
                "dependency_count": len(lineage["dependencies"]),
            },
        )

    async def _template_event_timeline(
        self, db: AsyncSession, case_id: str, params: dict[str, Any], limit: int
    ) -> dict[str, Any]:
        chain = await self._audit_chain_service(db).get_case_audit_chain_ops(
            case_id, max_events=_TIMELINE_MAX_EVENTS
        )
        events = list(chain["events"])
        type_prefix = _optional_str(params, "event_type", 128)
        if type_prefix:
            events = [e for e in events if e["event_type"].startswith(type_prefix)]
        since = _optional_str(params, "since", 64)
        if since:
            events = [e for e in events if e["recorded_at"] >= since]
        rows = [
            {
                "event_id": e["event_id"],
                "recorded_at": e["recorded_at"],
                "event_type": e["event_type"],
                "actor": e["actor"],
                "event_class": e["event_class"],
                "source": e["source"],
                "summary": e["summary"],
            }
            for e in events[:limit]
        ]
        return _result_envelope(
            template="event_timeline",
            rows=rows,
            total_count=len(events),
            aggregate={
                "by_event_class": dict(Counter(e["event_class"] for e in events)),
                "broken_link_count": int(chain["broken_link_count"]),
            },
        )

    async def _template_pending_approvals(
        self, db: AsyncSession, case_id: str, room: AgentTeamsRoomModel | None, limit: int
    ) -> dict[str, Any]:
        """待办审批：审计事件里的未决审批 + 平台 DB 房间行的 pending 立项卡。

        口径：``approval.requested`` 按 approval_id 与 ``approval.resolved`` 对账；
        ``case.state_changed`` 最新状态停在 approval_pending 且其后无 resolved 也算
        待办（Bridge 当前主要以状态迁移表达审批等待）。两类行可能指向同一次审批，
        用 kind 区分，不做跨类去重。
        """
        chain = await self._audit_chain_service(db).get_case_audit_chain_ops(
            case_id, max_events=_TIMELINE_MAX_EVENTS
        )
        events = list(chain["events"])
        pending: list[dict[str, Any]] = []
        resolved_ids = {
            str(e["payload"].get("approval_id") or "")
            for e in events
            if e["event_type"] == "approval.resolved"
        }
        resolved_ids.discard("")
        last_state_index = -1
        last_state = ""
        for index, event in enumerate(events):
            if event["event_type"] == "case.state_changed":
                last_state_index = index
                last_state = str(event["payload"].get("status") or "")
            if event["event_type"] != "approval.requested":
                continue
            approval_id = str(event["payload"].get("approval_id") or event["event_id"])
            if approval_id and approval_id not in resolved_ids:
                pending.append(
                    {
                        "kind": "approval_request",
                        "id": approval_id,
                        "summary": event["summary"],
                        "requested_at": event["recorded_at"],
                        "actor": event["actor"],
                    }
                )
        if last_state == "approval_pending" and not any(
            e["event_type"] == "approval.resolved"
            for e in events[last_state_index + 1 :]  # noqa: E203
        ):
            pending.append(
                {
                    "kind": "case_approval_pending",
                    "id": case_id,
                    "summary": "Case 停在 approval_pending，等待人工审批",
                    "requested_at": events[last_state_index]["recorded_at"],
                    "actor": events[last_state_index]["actor"],
                }
            )
        if room is not None and isinstance(room.proposal, dict):
            proposal = room.proposal
            if proposal.get("status") == "pending":
                pending.append(
                    {
                        "kind": "room_proposal",
                        "id": str(room.room_id),
                        "summary": str(proposal.get("objective") or "")[:200],
                        "requested_at": str(proposal.get("created_at") or ""),
                        "actor": "room",
                        "proposal_kind": str(proposal.get("proposal_kind") or ""),
                    }
                )
        pending.sort(key=lambda row: row["requested_at"])
        return _result_envelope(
            template="pending_approvals",
            rows=pending[:limit],
            total_count=len(pending),
            aggregate={"by_kind": dict(Counter(row["kind"] for row in pending))},
        )

    # ---- 受限 SQL ----

    async def _run_restricted_sql(
        self, db: AsyncSession, sql: str, *, case_id: str, limit: int
    ) -> dict[str, Any]:
        parsed = _parse_restricted_sql(sql)
        model = _ALLOWED_SQL_TABLES[parsed["table"]]
        scope_filter = model.case_id == case_id  # 强制注入：独立谓词，调用方无法摆脱
        user_where = parsed["where"]

        def _with_filters(stmt: Any) -> Any:
            stmt = stmt.where(scope_filter)
            if user_where:
                stmt = stmt.where(text(user_where))
            return stmt

        total = int(await db.scalar(_with_filters(select(func.count()).select_from(model))) or 0)
        statement = _with_filters(select(model))
        for column, descending in parsed["order_by"]:
            order_column = getattr(model, column)
            statement = statement.order_by(order_column.desc() if descending else order_column)
        rows = (await db.execute(statement.limit(limit))).scalars().all()
        return _result_envelope(
            template=None,
            rows=[_model_row(row) for row in rows],
            total_count=total,
            aggregate={"table": parsed["table"]},
            sql_hash=_sql_hash(sql),
        )

    # ---- 审计写入 ----

    async def _record_query(
        self,
        case_id: str,
        *,
        caller: str,
        query: str,
        row_count: int,
        total_count: int,
        truncated: bool,
    ) -> None:
        """放行路径审计：写入失败 fail-closed（无审计不返数据，验收 V6 前提）。"""
        try:
            await self._agentteams_service().post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type=QUERY_AUDIT_EVENT_TYPE,
                summary=f"自省查询 {query}：rows={row_count}/{total_count}",
                payload={
                    "caller": caller,
                    "query": query[:512],
                    "row_count": row_count,
                    "total_count": total_count,
                    "truncated": truncated,
                },
            )
        except Exception as exc:
            raise BusinessError(
                f"自省查询审计写入失败，结果不予返回（fail-closed）: {exc}"
            ) from exc

    async def _record_denied(
        self,
        case_id: str,
        *,
        caller: str,
        query: str,
        reason: str,
        matched: str | None = None,
    ) -> None:
        """拒绝路径审计：尽力而为——拒绝语义本身不依赖 Bridge 可用性。"""
        try:
            await self._agentteams_service().post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type=DENIED_AUDIT_EVENT_TYPE,
                summary=f"自省查询被拒 {query}：{reason[:200]}",
                payload={
                    "caller": caller,
                    "query": query[:512],
                    "reason": reason[:500],
                    "denied_matched": matched or "",
                },
            )
        except Exception:
            logger.bind(case_id=case_id).warning(
                "AgentTeams introspection denied audit failed", exc_info=True
            )

    # ---- 依赖装配 ----

    def _agentteams_service(self) -> AgentTeamsService:
        if self._agentteams is None:
            self._agentteams = AgentTeamsService(get_settings())
        return self._agentteams

    def _audit_chain_service(self, db: AsyncSession) -> AgentTeamsAuditChainService:
        if self._audit_chain is None:
            return AgentTeamsAuditChainService(db, agentteams=self._agentteams_service())
        return self._audit_chain


# ---- 模块级辅助 ----


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return _DEFAULT_LIMIT
    return min(max(int(limit), 1), _MAX_LIMIT)


def _optional_str(params: dict[str, Any], key: str, max_length: int) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"参数 {key} 必须是字符串")
    return value.strip()[:max_length] or None


def _sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()[:16]


def _result_envelope(
    *,
    template: str | None,
    rows: list[dict[str, Any]],
    total_count: int,
    aggregate: dict[str, Any],
    sql_hash: str | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "rows": rows,
        "row_count": len(rows),
        "total_count": total_count,
        "truncated": total_count > len(rows),
        "aggregate": aggregate,
    }
    if template is not None:
        envelope["template"] = template
    if sql_hash is not None:
        envelope["sql_sha256"] = sql_hash
    return envelope


def _artifact_version_row(row: CaseArtifactVersionModel) -> dict[str, Any]:
    return {
        "version_id": str(row.id),
        "artifact_id": row.artifact_id,
        "version_no": row.version_no,
        "checksum_sha256": row.checksum_sha256,
        "size_bytes": row.size_bytes,
        "content_type": row.content_type,
        "storage_uri": row.storage_uri,
        "producing_event_id": row.producing_event_id,
        "work_item_id": row.work_item_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _model_row(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in row.__table__.columns:  # noqa: SLF001 - SQLAlchemy 标准内省接口
        value = getattr(row, column.name)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        result[column.name] = (
            str(value)
            if value is not None and not isinstance(value, (str, int, float, bool, list, dict))
            else value
        )
    return result


def _parse_restricted_sql(sql: str) -> dict[str, Any]:
    """受限 SQL 解析：单表 SELECT，列/关键词白名单，禁括号分号注释。"""
    stripped = sql.strip()
    if len(stripped) > 2_000:
        raise ValidationError("受限 SQL 不能超过 2000 字符")
    for token in _SQL_FORBIDDEN_TOKENS:
        if token in stripped:
            raise ValidationError(f"受限 SQL 不允许出现 {token!r}（禁子查询/函数/多语句/注释）")
    match = _SQL_STATEMENT_RE.match(stripped)
    if match is None:
        raise ValidationError("受限 SQL 只支持单表 SELECT ... FROM ... [WHERE ...] [ORDER BY ...]")
    table = match.group("table").lower()
    model = _ALLOWED_SQL_TABLES.get(table)
    if model is None:
        raise IntrospectionDeniedError("自省查询被拒绝：表不在只读白名单内")
    columns = {column.name for column in model.__table__.columns}  # noqa: SLF001

    select_list = match.group("columns").strip()
    if select_list != "*":
        for item in select_list.split(","):
            name = item.strip().lower()
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", name) or name not in columns:
                raise ValidationError(f"受限 SQL 的列 {item.strip()!r} 不在 {table} 的列白名单内")

    where = match.group("where")
    if where:
        _validate_where_clause(where, columns, table)

    order_by: list[tuple[str, bool]] = []
    raw_order = match.group("order")
    if raw_order:
        for term in raw_order.split(","):
            term_match = _SQL_ORDER_TERM_RE.match(term.strip())
            if term_match is None or term_match.group(1).lower() not in columns:
                raise ValidationError(f"ORDER BY 项 {term.strip()!r} 非法或不在列白名单内")
            order_by.append(
                (term_match.group(1).lower(), (term_match.group(2) or "").upper() == "DESC")
            )
    return {"table": table, "where": where, "order_by": order_by}


def _validate_where_clause(where: str, columns: set[str], table: str) -> None:
    """WHERE 分词校验：只允许列名/白名单关键词/字面量/比较运算符，且全文消耗。"""
    position = 0
    while position < len(where):
        if where[position].isspace():
            position += 1
            continue
        token_match = _SQL_WHERE_TOKEN_RE.match(where, position)
        if token_match is None or token_match.end() == position:
            raise ValidationError("WHERE 子句含不允许的token（仅支持比较/AND/OR/NOT/LIKE/IS NULL）")
        token = where[position : token_match.end()].strip()
        position = token_match.end()
        if not token:
            continue
        if token[0] == "'" or token[0].isdigit():
            continue  # 字面量（字符串/数字）
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            upper = token.upper()
            if upper in _SQL_WHERE_KEYWORDS:
                if upper in {"IN", "BETWEEN"}:
                    raise ValidationError("受限 SQL 不支持 IN/BETWEEN（括号与范围已禁用）")
                continue
            if token.lower() not in columns:
                raise ValidationError(f"WHERE 引用了 {table} 之外的列或未知标识符 {token!r}")
            continue
        # 比较运算符
        if token in {"=", "!=", "<>", "<", "<=", ">", ">="}:
            continue
        raise ValidationError(f"WHERE 子句含不允许的token {token!r}")


__all__ = [
    "AgentTeamsIntrospectionService",
    "DENIED_AUDIT_EVENT_TYPE",
    "IntrospectionDeniedError",
    "QUERY_AUDIT_EVENT_TYPE",
    "TEMPLATES",
    "load_introspection_schema_doc",
    "scan_denied",
]
