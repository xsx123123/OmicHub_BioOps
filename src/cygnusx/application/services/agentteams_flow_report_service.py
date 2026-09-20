"""Offline HTML flow report export for AgentTeams cases."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.agentteams_artifact_lineage_service import (
    AgentTeamsArtifactLineageService,
)
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError
from cygnusx.infrastructure.database.models.chat import AgentTeamsTurnRecordModel
from cygnusx.infrastructure.storage.minio_store import MinioStore


@dataclass(frozen=True)
class FlowReportArtifact:
    artifact_id: str
    artifact_path: str
    version_id: str
    version_no: int
    checksum_sha256: str
    content_checksum_sha256: str
    size_bytes: int
    storage_uri: str
    generated_at: str


class AgentTeamsFlowReportService:
    """Render a role-trimmed, standalone Case flow report and register its lineage."""

    _TURN_MAX_BYTES = 10 * 1024 * 1024

    def __init__(self, db: AsyncSession, *, minio_store: MinioStore | None = None) -> None:
        self._db = db
        self._minio = minio_store or MinioStore(get_settings())

    async def generate(
        self,
        *,
        case_id: str,
        case: dict[str, Any],
        events: list[dict[str, Any]],
        generated_by: str,
        viewer_role: str,
        publish_evidence: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> FlowReportArtifact:
        records = list(
            await self._db.scalars(
                select(AgentTeamsTurnRecordModel)
                .where(AgentTeamsTurnRecordModel.case_id == case_id)
                .order_by(
                    AgentTeamsTurnRecordModel.work_item_id,
                    AgentTeamsTurnRecordModel.round_number,
                    AgentTeamsTurnRecordModel.call_seq,
                )
            )
        )
        is_member = viewer_role == "invited"
        turns = [await self._load_turn(case_id, row, is_member=is_member) for row in records]
        lineage = await AgentTeamsArtifactLineageService(self._db).case_lineage(case_id)
        generated_at = datetime.now(UTC)
        artifact_path = f"reports/flow-{generated_at:%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.html"
        content_checksum_sha256 = self._content_checksum(
            case=case,
            case_id=case_id,
            events=events,
            turns=turns,
            lineage=lineage,
            generated_at=generated_at,
            generated_by=generated_by,
        )
        report_html = self._render_html(
            case=case,
            case_id=case_id,
            events=events,
            turns=turns,
            lineage=lineage,
            generated_at=generated_at,
            generated_by=generated_by,
            content_checksum_sha256=content_checksum_sha256,
        )
        report_bytes = report_html.encode("utf-8")
        checksum_sha256 = hashlib.sha256(report_bytes).hexdigest()
        storage_uri = await self._put_report(case_id, artifact_path, report_bytes)
        evidence = await publish_evidence(
            {
                "artifact_id": artifact_path,
                "storage_uri": storage_uri,
                "checksum_sha256": checksum_sha256,
                "content_checksum_sha256": content_checksum_sha256,
                "size_bytes": len(report_bytes),
                "viewer_role": viewer_role,
            }
        ) if publish_evidence else {}
        lineage_service = AgentTeamsArtifactLineageService(self._db)
        version = await lineage_service.register_version(
            case_id=case_id,
            artifact_id=artifact_path,
            checksum_sha256=checksum_sha256,
            size_bytes=len(report_bytes),
            content_type="text/html; charset=utf-8",
            storage_uri=storage_uri,
            producing_event_id=str(evidence.get("event_id") or evidence.get("id") or "") or None,
            environment_snapshot={
                "generated_by": generated_by,
                "viewer_role": viewer_role,
                "generated_at": generated_at.isoformat(),
                "turn_count": len(turns),
                "event_count": len(events),
                "content_checksum_sha256": content_checksum_sha256,
            },
        )
        await lineage_service.register_dependencies(
            case_id=case_id,
            downstream_artifact_id=artifact_path,
            source_refs=[
                {"artifact_id": str(item["artifact_id"]), "relation": "derived_from"}
                for item in lineage.get("versions", [])
                if item.get("artifact_id")
            ],
        )
        return FlowReportArtifact(
            artifact_id=artifact_path,
            artifact_path=artifact_path,
            version_id=str(version.id),
            version_no=version.version_no,
            checksum_sha256=checksum_sha256,
            content_checksum_sha256=content_checksum_sha256,
            size_bytes=len(report_bytes),
            storage_uri=storage_uri,
            generated_at=generated_at.isoformat(),
        )

    async def _load_turn(
        self, case_id: str, row: AgentTeamsTurnRecordModel, *, is_member: bool
    ) -> dict[str, Any]:
        prefix = f"s3://{self._minio.bucket}/cases/{case_id}/"
        if not row.s3_uri.startswith(prefix):
            raise BusinessError("过程记录对象地址无效")
        payload = await asyncio.to_thread(
            self._minio.read_turn_record,
            case_id,
            row.s3_uri[len(prefix) :],
            max_bytes=self._TURN_MAX_BYTES,
        )
        turn = json.loads(payload)
        if not isinstance(turn, dict):
            raise BusinessError("过程记录对象格式无效")
        if is_member:
            turn.pop("messages", None)
            turn.pop("reasoning_text", None)
            turn["permission_trimmed"] = True
        return turn

    async def _put_report(self, case_id: str, artifact_path: str, content: bytes) -> str:
        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as handle:
                handle.write(content)
                path = Path(handle.name)
            return await asyncio.to_thread(
                self._minio.put_case_object,
                case_id,
                artifact_path,
                path,
                "text/html; charset=utf-8",
            )
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    @staticmethod
    def _content_checksum(**kwargs: Any) -> str:
        canonical = {
            key: value
            for key, value in kwargs.items()
            if key != "generated_at"
        }
        canonical["generated_at"] = kwargs["generated_at"].isoformat()
        return hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _render_html(
        cls,
        *,
        case: dict[str, Any],
        case_id: str,
        events: list[dict[str, Any]],
        turns: list[dict[str, Any]],
        lineage: dict[str, Any],
        generated_at: datetime,
        generated_by: str,
        content_checksum_sha256: str,
    ) -> str:
        title = str(case.get("display_title") or case.get("intent") or case_id)
        event_items = "".join(cls._event_html(event) for event in events)
        turn_items = "".join(cls._turn_html(turn) for turn in turns)
        artifact_items = "".join(cls._artifact_html(version) for version in lineage.get("versions", []))
        dialogue_items = "".join(cls._dialogue_html(event) for event in events if cls._is_dialogue(event))
        environment_items = cls._environment_html(generated_at, generated_by, len(turns), len(events))
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{cls._escape(title)} · 协作流程报告</title>
<style>
body{{margin:0;background:#f6f8fb;color:#172033;font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:32px 20px 56px}} section{{background:#fff;border:1px solid #dbe3ef;border-radius:12px;margin:16px 0;padding:20px}}
h1{{margin:0 0 8px;font-size:26px}} h2{{margin:0 0 14px;font-size:19px}} h3{{margin:16px 0 8px;font-size:16px}} .meta,.muted{{color:#60708a}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}}
.card{{padding:10px;border-radius:8px;background:#f6f8fb}} .code{{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:#244f9b}} pre{{overflow:auto;white-space:pre-wrap;word-break:break-word;padding:12px;background:#111827;color:#e5eefc;border-radius:8px}}
details{{border-top:1px solid #e4e9f1;padding:10px 0}} summary{{cursor:pointer;font-weight:600}} .trimmed{{color:#9a6700;background:#fff8c5;padding:8px;border-radius:6px}} ul{{padding-left:20px}} footer{{color:#60708a;font-size:12px;padding:8px}} .copy{{margin-left:6px;border:1px solid #b7c5de;border-radius:4px;background:#fff;color:#244f9b;font-size:12px;cursor:pointer}}
</style></head><body><main>
<section><h1>{cls._escape(title)}</h1><p class="meta">Case：<span class="code">{cls._escape(case_id)}</span></p>
<div class="grid"><div class="card">状态：{cls._escape(case.get("status"))}</div><div class="card">LLM 步骤：{len(turns)}</div><div class="card">审计事件：{len(events)}</div><div class="card">产物版本：{len(lineage.get("versions", []))}</div></div></section>
<section><h2>房间对话摘要</h2>{dialogue_items or '<p class="muted">暂无可导出的房间对话摘要。</p>'}</section>
<section><h2>协作时间线</h2><ul>{event_items or '<li class="muted">暂无审计事件。</li>'}</ul></section>
<section><h2>步骤详情</h2>{turn_items or '<p class="muted">暂无过程记录。</p>'}</section>
<section><h2>产物血缘</h2><ul>{artifact_items or '<li class="muted">暂无登记产物。</li>'}</ul></section>
<section><h2>环境快照</h2>{environment_items}</section>
<footer>生成时间：{cls._escape(generated_at.isoformat())} · 生成者：{cls._escape(generated_by)} · 记录总数：{len(turns)} · content_checksum_sha256：<span class="code">{content_checksum_sha256}</span> · 报告文件 SHA-256 以产物血缘登记为准。</footer>
<script>function copyFlowCode(button){{var value=button.dataset.copy||"";if(navigator.clipboard){{navigator.clipboard.writeText(value);}}else{{var input=document.createElement("input");input.value=value;document.body.appendChild(input);input.select();document.execCommand("copy");input.remove();}}button.textContent="已复制";}}</script>
</main></body></html>"""

    @classmethod
    def _turn_html(cls, turn: dict[str, Any]) -> str:
        record_id = str(turn.get("record_id") or "")
        code = f"TRN-{int(turn.get('round_number') or 0):04d}-{int(turn.get('call_seq') or 0):02d}-{record_id[:8]}"
        messages = turn.get("messages")
        if isinstance(messages, list):
            message_html = "".join(
                f"<h3>输入 · {cls._escape(message.get('role'))}</h3><pre>{cls._escape(message.get('content'))}</pre>"
                for message in messages if isinstance(message, dict)
            )
        else:
            message_html = '<p class="trimmed">已按权限裁剪</p>'
        reasoning = turn.get("reasoning_text")
        reasoning_html = (
            f"<h3>思考过程</h3><pre>{cls._escape(reasoning)}</pre>"
            if reasoning is not None
            else ('<p class="trimmed">已按权限裁剪</p>' if turn.get("permission_trimmed") else "")
        )
        tools = turn.get("tool_calls") or []
        return f"""<details><summary>{cls._code_with_copy(code)} · {cls._escape(turn.get("agent_id"))} · {cls._escape(turn.get("model"))}</summary>
<p class="meta">完整记录 ID：<span class="code">{cls._escape(record_id)}</span> · 状态：{cls._escape(turn.get("status"))}</p>{message_html}{reasoning_html}
<h3>输出</h3><pre>{cls._escape(turn.get("output_text"))}</pre><h3>工具调用</h3><pre>{cls._escape(json.dumps(tools, ensure_ascii=False, indent=2, default=str))}</pre></details>"""

    @classmethod
    def _event_html(cls, event: dict[str, Any]) -> str:
        event_id = str(event.get("event_id") or event.get("id") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        summary = payload.get("summary") or event.get("summary") or payload.get("status_line") or "—"
        code = f"EVT-{event_id[:8]}"
        return f"<li>{cls._code_with_copy(code)} · {cls._escape(event.get('event_type') or event.get('type'))} · {cls._escape(summary)}<br><span class=\"meta\">完整事件 ID：<span class=\"code\">{cls._escape(event_id)}</span></span></li>"

    @classmethod
    def _dialogue_html(cls, event: dict[str, Any]) -> str:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        actor = nested.get("actor") or payload.get("actor") or "—"
        content = nested.get("content") or payload.get("summary") or event.get("summary") or "—"
        return f"<p><strong>{cls._escape(actor)}</strong>：{cls._escape(str(content)[:500])}</p>"

    @staticmethod
    def _is_dialogue(event: dict[str, Any]) -> bool:
        event_type = str(event.get("event_type") or event.get("type") or "")
        return event_type in {"room.user_message", "room.manager_message"}

    @classmethod
    def _artifact_html(cls, version: dict[str, Any]) -> str:
        version_id = str(version.get("version_id") or "")
        code = f"ART-{version_id[:8]}"
        return f"<li>{cls._code_with_copy(code)} · {cls._escape(version.get('artifact_id'))} · SHA-256：<span class=\"code\">{cls._escape(version.get('checksum_sha256'))}</span><br><span class=\"meta\">完整版本 ID：<span class=\"code\">{cls._escape(version_id)}</span></span></li>"

    @staticmethod
    def _environment_html(
        generated_at: datetime, generated_by: str, turn_count: int, event_count: int
    ) -> str:
        settings = get_settings()
        values = {
            "应用": settings.app_name,
            "应用版本": settings.app_version,
            "服务": settings.service_name,
            "生成时间": generated_at.isoformat(),
            "生成者": generated_by,
            "步骤数": turn_count,
            "事件数": event_count,
        }
        return "<ul>" + "".join(
            f"<li>{html.escape(key)}：<span class=\"code\">{html.escape(str(value))}</span></li>"
            for key, value in values.items()
        ) + "</ul>"

    @classmethod
    def _code_with_copy(cls, code: str) -> str:
        escaped = cls._escape(code)
        return (
            f'<span class="code">{escaped}</span>'
            f'<button class="copy" type="button" data-copy="{escaped}" '
            'onclick="copyFlowCode(this)">复制</button>'
        )

    @staticmethod
    def _escape(value: Any) -> str:
        return html.escape(str(value if value is not None else "—"), quote=True)
