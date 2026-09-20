"""自省查询面（F4）测试：scope 限定、denied 词边界与别名绕过、行数上限+聚合截断、
四个预置模板正确性、调用审计事件写入（放行 fail-closed / 拒绝尽力而为）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cygnusx.application.services.agentteams_introspection_service import (
    DENIED_AUDIT_EVENT_TYPE,
    QUERY_AUDIT_EVENT_TYPE,
    AgentTeamsIntrospectionService,
    IntrospectionDeniedError,
    scan_denied,
)
from cygnusx.core.exceptions import BusinessError, ValidationError
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsRoomModel,
    CaseArtifactDependencyModel,
    CaseArtifactVersionModel,
)


class _Result:
    """模拟 AsyncSession.execute 返回值的最小表面。"""

    def __init__(self, *, scalars=(), one=None) -> None:
        self._scalars = scalars
        self._one = one

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def one(self):
        return self._one


def _db(*, scalars=(), execute_results=()) -> SimpleNamespace:
    return SimpleNamespace(
        scalar=AsyncMock(side_effect=list(scalars)),
        execute=AsyncMock(side_effect=list(execute_results)),
    )


def _agentteams() -> SimpleNamespace:
    return SimpleNamespace(
        post_case_evidence=AsyncMock(return_value={"event_id": "audit-1"}),
        get_case=AsyncMock(return_value={"case_id": "case-1"}),
    )


def _service(db, *, agentteams=None, audit_chain=None) -> AgentTeamsIntrospectionService:
    return AgentTeamsIntrospectionService(
        agentteams=agentteams or _agentteams(), audit_chain=audit_chain
    )


def _room(*, room_id="room-1", case_id="case-1", owner_id="user-1", proposal=None):
    return AgentTeamsRoomModel(
        room_id=room_id, owner_id=owner_id, case_id=case_id, proposal=proposal
    )


def _version_row(artifact_id: str, version_no: int, *, case_id: str = "case-1"):
    return CaseArtifactVersionModel(
        case_id=case_id,
        artifact_id=artifact_id,
        version_no=version_no,
        checksum_sha256="a" * 64,
        size_bytes=10,
        content_type="text/markdown",
        storage_uri=f"s3://agentteams/cases/case-1/{artifact_id}",
        environment_snapshot={},
    )


def _event(
    event_id: str,
    event_type: str,
    *,
    recorded_at: str = "2026-08-21T00:00:00+00:00",
    actor: str = "bioops-manager",
    payload=None,
    event_class: str = "business",
):
    return {
        "event_id": event_id,
        "recorded_at": recorded_at,
        "case_id": "case-1",
        "actor": actor,
        "event_type": event_type,
        "source": "case",
        "event_class": event_class,
        "summary": f"{event_type} 摘要",
        "correlation": {},
        "payload": payload or {},
    }


def _chain(events, *, broken_link_count=0):
    return SimpleNamespace(
        get_case_audit_chain_ops=AsyncMock(
            return_value={
                "case_id": "case-1",
                "room_id": "room-1",
                "event_count": len(events),
                "broken_link_count": broken_link_count,
                "broken_links": [],
                "generated_at": datetime.now(UTC).isoformat(),
                "events": events,
            }
        )
    )


def run(coro):
    return asyncio.run(coro)


# ---- denied 词表：词边界与别名绕过 ----


@pytest.mark.parametrize(
    "text_value",
    [
        "SELECT * FROM worker_tokens",  # 表名
        "WHERE reason = 'the worker_token is x'",  # 下划线复合别名（token 词边界被 _ 截断）
        "select api_key",  # 下划线别名
        "select apikey",  # 连写别名
        "select Secret from t",  # 大小写混合
        "select password",  # 密码
        "select credentials",  # 复数凭据
        "select host",  # 宿主
        "where x = '查主机信息'",  # CJK 宿主
        "where x = '这是密钥'",  # CJK 密钥
        "where x = '口令123'",  # CJK 口令
        "select token",  # 裸 token
    ],
)
def test_scan_denied_hits_keywords_and_aliases(text_value: str) -> None:
    assert scan_denied(text_value) is not None


@pytest.mark.parametrize(
    "text_value",
    [
        "SELECT checksum_sha256, artifact_id FROM case_artifact_versions",
        "WHERE verdict = 'fail'",
        "WHERE storage_uri LIKE 's3://agentteams/%'",
        "monkey business",  # 词边界：key 子串不命中
        "WHERE artifact_id = 'exec-01/plot.svg'",
    ],
)
def test_scan_denied_allows_benign_text(text_value: str) -> None:
    assert scan_denied(text_value) is None


def test_denied_sql_rejected_and_audited() -> None:
    db = _db(scalars=[_room()])
    agentteams = _agentteams()
    service = _service(db, agentteams=agentteams)
    with pytest.raises(IntrospectionDeniedError):
        run(
            service.query_case_facts(
                db,
                case_id="case-1",
                caller="manager",
                sql="SELECT * FROM case_artifact_versions WHERE storage_uri = 'worker_token x'",
            )
        )
    call = agentteams.post_case_evidence.await_args
    assert call.kwargs["event_type"] == DENIED_AUDIT_EVENT_TYPE
    assert call.kwargs["payload"]["caller"] == "manager"


def test_denied_param_value_rejected() -> None:
    db = _db(scalars=[_room()])
    agentteams = _agentteams()
    service = _service(db, agentteams=agentteams)
    with pytest.raises(IntrospectionDeniedError):
        run(
            service.query_case_facts(
                db,
                case_id="case-1",
                caller="agent-qc",
                template="artifact_versions",
                params={"artifact_id": "give me the password"},
            )
        )
    assert agentteams.post_case_evidence.await_args.kwargs["event_type"] == DENIED_AUDIT_EVENT_TYPE


# ---- scope 限定 ----


def test_scope_room_case_binding_mismatch_denied() -> None:
    db = _db(scalars=[_room(case_id="case-other")])
    agentteams = _agentteams()
    service = _service(db, agentteams=agentteams)
    with pytest.raises(IntrospectionDeniedError):
        run(
            service.query_case_facts(
                db,
                case_id="case-1",
                room_id="room-1",
                caller="manager",
                template="artifact_versions",
            )
        )
    assert agentteams.post_case_evidence.await_args.kwargs["event_type"] == DENIED_AUDIT_EVENT_TYPE


def test_scope_unknown_room_denied() -> None:
    db = _db(scalars=[None])
    with pytest.raises(IntrospectionDeniedError):
        run(
            _service(db).query_case_facts(
                db,
                case_id="case-1",
                room_id="room-ghost",
                caller="manager",
                template="artifact_versions",
            )
        )


def test_scope_room_namespace_case_id_denied() -> None:
    db = _db()
    with pytest.raises(IntrospectionDeniedError):
        run(
            _service(db).query_case_facts(
                db, case_id="room-room-1", caller="manager", template="artifact_versions"
            )
        )
    db.scalar.assert_not_called()


def test_scope_owner_mismatch_denied_and_falls_back_to_bridge_check() -> None:
    # 房间 owner 不是调用方 → 拒
    db = _db(scalars=[_room(owner_id="user-2")])
    with pytest.raises(IntrospectionDeniedError):
        run(
            _service(db).query_case_facts(
                db,
                case_id="case-1",
                caller="tool:agent-qc",
                template="artifact_versions",
                owner_id="user-1",
            )
        )
    # 无房间绑定的 Case → 回退 Bridge requester 校验
    agentteams = _agentteams()
    db2 = _db(
        scalars=[None, 1],
        execute_results=[_Result(one=(1, 10)), _Result(scalars=[_version_row("a.md", 1)])],
    )
    result = run(
        _service(db2, agentteams=agentteams).query_case_facts(
            db2,
            case_id="case-1",
            caller="tool:manager",
            template="artifact_versions",
            owner_id="user-1",
        )
    )
    agentteams.get_case.assert_awaited_once_with("case-1", "user-1")
    assert result["row_count"] == 1


# ---- 行数上限 + 服务端聚合截断标记 ----


def test_artifact_versions_truncation_reports_total_and_aggregate() -> None:
    rows = [_version_row("exec-01/a.md", index) for index in range(1, 4)]
    db = _db(
        scalars=[_room(), 10],  # scope 房间 + total_count=10（远大于返回行数）
        execute_results=[_Result(one=(2, 1024)), _Result(scalars=rows)],
    )
    result = run(
        _service(db).query_case_facts(
            db, case_id="case-1", caller="manager", template="artifact_versions", limit=3
        )
    )
    assert result["row_count"] == 3
    assert result["total_count"] == 10
    assert result["truncated"] is True
    # 服务端聚合：distinct artifact 数与总字节数不受行截断影响
    assert result["aggregate"] == {"artifact_count": 2, "total_size_bytes": 1024}
    assert result["rows"][0]["version_id"] == str(rows[0].id)
    assert result["rows"][0]["producing_event_id"] is None


def test_limit_clamped_to_maximum() -> None:
    db = _db(
        scalars=[_room(), 0],
        execute_results=[_Result(one=(0, 0)), _Result(scalars=[])],
    )
    result = run(
        _service(db).query_case_facts(
            db, case_id="case-1", caller="manager", template="artifact_versions", limit=99_999
        )
    )
    limit_arg = db.execute.await_args_list[-1].args[0]._limit_clause
    assert int(limit_arg.value) == 200
    assert result["row_count"] == 0


# ---- 模板正确性 ----


def test_artifact_versions_filter_params_applied() -> None:
    db = _db(
        scalars=[_room(), 1],
        execute_results=[_Result(one=(1, 10)), _Result(scalars=[_version_row("exec-01/a.md", 1)])],
    )
    result = run(
        _service(db).query_case_facts(
            db,
            case_id="case-1",
            caller="manager",
            template="artifact_versions",
            params={"artifact_id": "exec-01/a.md", "work_item_id": "exec-01"},
        )
    )
    assert result["template"] == "artifact_versions"
    assert result["rows"][0]["artifact_id"] == "exec-01/a.md"


def test_artifact_lineage_expands_upstream_one_level() -> None:
    version = _version_row("exec-02/plot.svg", 1)
    edge = CaseArtifactDependencyModel(
        case_id="case-1",
        downstream_artifact_id="exec-02/plot.svg",
        upstream_artifact_id="exec-01/counts.tsv",
        relation="input_to",
    )
    db = _db(
        scalars=[_room()],
        execute_results=[_Result(scalars=[version]), _Result(scalars=[edge])],
    )
    result = run(
        _service(db).query_case_facts(
            db, case_id="case-1", caller="agent-qc", template="artifact_lineage"
        )
    )
    assert result["rows"][0]["upstream"] == [
        {"artifact_id": "exec-01/counts.tsv", "relation": "input_to"}
    ]
    assert result["aggregate"]["dependency_count"] == 1
    assert result["truncated"] is False


def test_event_timeline_filters_and_aggregates() -> None:
    events = [
        _event("e1", "case.created"),
        _event("e2", "approval.resolved", payload={"approval_id": "ap-1"}),
        _event("e3", "room.agent_message", recorded_at="2026-08-21T01:00:00+00:00"),
    ]
    db = _db(scalars=[_room(), _room()])
    result = run(
        _service(db, audit_chain=_chain(events, broken_link_count=1)).query_case_facts(
            db, case_id="case-1", caller="manager", template="event_timeline"
        )
    )
    assert result["total_count"] == 3
    assert result["aggregate"]["by_event_class"] == {"business": 3}
    assert result["aggregate"]["broken_link_count"] == 1

    filtered = run(
        _service(db, audit_chain=_chain(events)).query_case_facts(
            db,
            case_id="case-1",
            caller="manager",
            template="event_timeline",
            params={"event_type": "approval."},
        )
    )
    assert [row["event_type"] for row in filtered["rows"]] == ["approval.resolved"]


def test_pending_approvals_collects_unresolved_and_room_proposal() -> None:
    events = [
        _event("e1", "case.created"),
        _event("e2", "approval.requested", payload={"approval_id": "ap-1"}),
        _event(
            "e3",
            "approval.resolved",
            payload={"approval_id": "ap-1"},
            recorded_at="2026-08-21T01:00:00+00:00",
        ),
        _event(
            "e4",
            "approval.requested",
            payload={"approval_id": "ap-2"},
            recorded_at="2026-08-21T02:00:00+00:00",
        ),
        _event(
            "e5",
            "case.state_changed",
            payload={"status": "approval_pending"},
            recorded_at="2026-08-21T03:00:00+00:00",
        ),
    ]
    room = _room(
        proposal={
            "status": "pending",
            "proposal_kind": "followup",
            "objective": "继续分析",
            "created_at": "2026-08-21T04:00:00+00:00",
        }
    )
    db = _db(scalars=[room])
    result = run(
        _service(db, audit_chain=_chain(events)).query_case_facts(
            db, case_id="case-1", caller="manager", template="pending_approvals"
        )
    )
    kinds = [row["kind"] for row in result["rows"]]
    # ap-1 已 resolved 不出现；ap-2 未决 + 状态停在 approval_pending + 房间待确认立项卡
    assert kinds == ["approval_request", "case_approval_pending", "room_proposal"]
    assert result["total_count"] == 3
    assert result["aggregate"]["by_kind"]["approval_request"] == 1

    # 立项卡已消费后不再出现
    room_consumed = _room(proposal={"status": "consumed"})
    db2 = _db(scalars=[room_consumed])
    resolved = run(
        _service(db2, audit_chain=_chain(events[:3])).query_case_facts(
            db2, case_id="case-1", caller="manager", template="pending_approvals"
        )
    )
    assert resolved["rows"] == []


def test_schema_template_returns_document() -> None:
    db = _db(scalars=[_room()])
    result = run(
        _service(db).query_case_facts(db, case_id="case-1", caller="agent-qc", template="schema")
    )
    assert "case_artifact_versions" in result["document"]
    assert "qc_verification_checks" in result["document"]


# ---- 受限 SQL ----


def test_restricted_sql_success_forces_case_scope() -> None:
    row = _version_row("exec-01/a.md", 1)
    db = _db(
        scalars=[_room(), 1],
        execute_results=[_Result(scalars=[row])],
    )
    result = run(
        _service(db).query_case_facts(
            db,
            case_id="case-1",
            caller="manager",
            sql="SELECT artifact_id, version_no FROM case_artifact_versions "
            "WHERE work_item_id = 'exec-01' ORDER BY version_no DESC",
        )
    )
    assert result["row_count"] == 1
    assert result["rows"][0]["artifact_id"] == "exec-01/a.md"
    assert result["sql_sha256"]
    # 强制 case_id 谓词独立注入：最终语句的 whereclause 含两个条件（scope + 用户 where）
    final_stmt = db.execute.await_args_list[-1].args[0]
    assert len(final_stmt.whereclause.clauses) == 2  # type: ignore[union-attr]


def test_restricted_sql_non_whitelisted_table_denied() -> None:
    db = _db(scalars=[_room()])
    agentteams = _agentteams()
    with pytest.raises(IntrospectionDeniedError):
        run(
            _service(db, agentteams=agentteams).query_case_facts(
                db, case_id="case-1", caller="manager", sql="SELECT * FROM chat_sessions"
            )
        )
    assert agentteams.post_case_evidence.await_args.kwargs["event_type"] == DENIED_AUDIT_EVENT_TYPE


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM case_artifact_versions; DROP TABLE x",  # 多语句
        "SELECT count(*) FROM case_artifact_versions",  # 函数/括号
        "SELECT * FROM case_artifact_versions WHERE artifact_id IN (SELECT artifact_id FROM case_artifact_dependencies)",  # 子查询
        "SELECT * FROM case_artifact_versions -- comment",  # 注释
        "SELECT * FROM case_artifact_versions WHERE bogus_column = 'x'",  # 未知列
        "DELETE FROM case_artifact_versions",  # 非 SELECT
    ],
)
def test_restricted_sql_rejects_out_of_grammar(sql: str) -> None:
    db = _db(scalars=[_room()])
    with pytest.raises((ValidationError, IntrospectionDeniedError)):
        run(_service(db).query_case_facts(db, case_id="case-1", caller="manager", sql=sql))


# ---- 调用审计 ----


def test_successful_query_writes_audit_event() -> None:
    db = _db(
        scalars=[_room(), 1],
        execute_results=[_Result(one=(1, 10)), _Result(scalars=[_version_row("exec-01/a.md", 1)])],
    )
    agentteams = _agentteams()
    run(
        _service(db, agentteams=agentteams).query_case_facts(
            db, case_id="case-1", caller="manager", template="artifact_versions"
        )
    )
    call = agentteams.post_case_evidence.await_args
    assert call.args[0] == "case-1"
    assert call.kwargs["event_type"] == QUERY_AUDIT_EVENT_TYPE
    assert call.kwargs["payload"]["caller"] == "manager"
    assert call.kwargs["payload"]["row_count"] == 1
    assert call.kwargs["payload"]["total_count"] == 1
    assert call.kwargs["payload"]["truncated"] is False


def test_query_fail_closed_when_audit_write_fails() -> None:
    db = _db(
        scalars=[_room(), 1],
        execute_results=[_Result(one=(1, 10)), _Result(scalars=[_version_row("exec-01/a.md", 1)])],
    )
    agentteams = _agentteams()
    agentteams.post_case_evidence = AsyncMock(side_effect=RuntimeError("bridge down"))
    with pytest.raises(BusinessError, match="fail-closed"):
        run(
            _service(db, agentteams=agentteams).query_case_facts(
                db, case_id="case-1", caller="manager", template="artifact_versions"
            )
        )


def test_denied_audit_failure_does_not_mask_denial() -> None:
    db = _db(scalars=[_room(case_id="case-other")])
    agentteams = _agentteams()
    agentteams.post_case_evidence = AsyncMock(side_effect=RuntimeError("bridge down"))
    with pytest.raises(IntrospectionDeniedError):
        run(
            _service(db, agentteams=agentteams).query_case_facts(
                db,
                case_id="case-1",
                room_id="room-1",
                caller="manager",
                template="artifact_versions",
            )
        )


def test_unknown_template_denied_and_audited() -> None:
    db = _db(scalars=[_room()])
    agentteams = _agentteams()
    with pytest.raises(IntrospectionDeniedError):
        run(
            _service(db, agentteams=agentteams).query_case_facts(
                db, case_id="case-1", caller="manager", template="everything"
            )
        )
    assert agentteams.post_case_evidence.await_args.kwargs["event_type"] == DENIED_AUDIT_EVENT_TYPE


def test_template_and_sql_are_mutually_exclusive() -> None:
    db = _db()
    with pytest.raises(ValidationError):
        run(
            _service(db).query_case_facts(
                db,
                case_id="case-1",
                caller="manager",
                template="artifact_versions",
                sql="SELECT * FROM case_artifact_versions",
            )
        )
