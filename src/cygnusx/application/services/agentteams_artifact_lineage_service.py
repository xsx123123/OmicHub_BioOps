"""AgentTeams 产物血缘服务（F1：artifact_versions + 依赖 DAG）。

口径（docs/info/26.8.21/协作室融合ClaudeScience设计理念评估与实施方案.md F1）：
- 产物登记时强制写入 ``case_artifact_versions`` 行：checksum + environment_snapshot
  （只记可复现最小事实）+ producing_event_id（指向触发登记的审计事件，复用因果链）。
- ``case_artifact_dependencies`` 记录下游 ← 上游依赖边（relation: input_to /
  derived_from），供"上游变了影响谁"的 DAG 查询与交付血缘清单一级展开。
- 本服务只写平台 DB；Bridge 无平台 DB 访问，其侧血缘事实（Worker 上报的
  source_refs / artifact_hashes）落在该 Case 的 MinIO 审计事件流中。
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.chat import (
    CaseArtifactDependencyModel,
    CaseArtifactVersionModel,
)

VALID_RELATIONS = frozenset({"input_to", "derived_from"})

_MAX_SOURCE_REFS = 100


def normalize_source_refs(raw: Any) -> list[dict[str, str]]:
    """规范化 Worker/调用方上报的 source_refs；非法条目丢弃（调用方负责显式校验）。

    接受两种形态：``{"artifact_id": ..., "relation": ...}`` 字典或纯字符串
    （视为 artifact_id，relation 默认 input_to）。
    """
    refs: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return refs
    for item in raw[:_MAX_SOURCE_REFS]:
        if isinstance(item, str) and item.strip():
            refs.append({"artifact_id": item.strip()[:512], "relation": "input_to"})
            continue
        if not isinstance(item, dict):
            continue
        artifact_id = str(item.get("artifact_id") or "").strip()
        if not artifact_id:
            continue
        relation = str(item.get("relation") or "input_to").strip()
        refs.append(
            {
                "artifact_id": artifact_id[:512],
                "relation": relation if relation in VALID_RELATIONS else "input_to",
            }
        )
    return refs


class AgentTeamsArtifactLineageService:
    """case_artifact_versions / case_artifact_dependencies 的读写面。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def register_version(
        self,
        *,
        case_id: str,
        artifact_id: str,
        checksum_sha256: str,
        size_bytes: int,
        content_type: str,
        storage_uri: str,
        producing_event_id: str | None = None,
        work_item_id: str | None = None,
        environment_snapshot: dict[str, Any] | None = None,
    ) -> CaseArtifactVersionModel:
        """写入一行产物版本；version_no 按 (case_id, artifact_id) 递增。"""
        result = await self._db.execute(
            select(func.max(CaseArtifactVersionModel.version_no)).where(
                CaseArtifactVersionModel.case_id == case_id,
                CaseArtifactVersionModel.artifact_id == artifact_id,
            )
        )
        version_no = int(result.scalar() or 0) + 1
        row = CaseArtifactVersionModel(
            case_id=case_id,
            artifact_id=artifact_id,
            version_no=version_no,
            producing_event_id=producing_event_id,
            work_item_id=work_item_id,
            checksum_sha256=checksum_sha256,
            size_bytes=int(size_bytes),
            content_type=content_type or "",
            storage_uri=storage_uri,
            environment_snapshot=environment_snapshot or {},
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def register_dependencies(
        self,
        *,
        case_id: str,
        downstream_artifact_id: str,
        source_refs: list[dict[str, str]],
    ) -> list[CaseArtifactDependencyModel]:
        """按 source_refs 写入依赖边；同一边（四元组）已存在则跳过。"""
        edges: list[CaseArtifactDependencyModel] = []
        for ref in source_refs:
            upstream = ref["artifact_id"]
            if upstream == downstream_artifact_id:
                continue
            relation = ref.get("relation") or "input_to"
            existing = await self._db.execute(
                select(CaseArtifactDependencyModel.id).where(
                    CaseArtifactDependencyModel.case_id == case_id,
                    CaseArtifactDependencyModel.downstream_artifact_id
                    == downstream_artifact_id,
                    CaseArtifactDependencyModel.upstream_artifact_id == upstream,
                    CaseArtifactDependencyModel.relation == relation,
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue
            edge = CaseArtifactDependencyModel(
                case_id=case_id,
                downstream_artifact_id=downstream_artifact_id,
                upstream_artifact_id=upstream,
                relation=relation,
            )
            self._db.add(edge)
            edges.append(edge)
        if edges:
            await self._db.flush()
        return edges

    async def case_lineage(self, case_id: str) -> dict[str, Any]:
        """Case 全量血缘：版本行 + 依赖边 + 每个版本的上游一级展开。"""
        versions = (
            (
                await self._db.execute(
                    select(CaseArtifactVersionModel)
                    .where(CaseArtifactVersionModel.case_id == case_id)
                    .order_by(
                        CaseArtifactVersionModel.artifact_id,
                        CaseArtifactVersionModel.version_no,
                    )
                )
            )
            .scalars()
            .all()
        )
        dependencies = (
            (
                await self._db.execute(
                    select(CaseArtifactDependencyModel).where(
                        CaseArtifactDependencyModel.case_id == case_id
                    )
                )
            )
            .scalars()
            .all()
        )
        upstream_map: dict[str, list[dict[str, str]]] = {}
        for edge in dependencies:
            upstream_map.setdefault(edge.downstream_artifact_id, []).append(
                {"artifact_id": edge.upstream_artifact_id, "relation": edge.relation}
            )
        return {
            "versions": [
                {
                    "version_id": str(row.id),
                    "artifact_id": row.artifact_id,
                    "version_no": row.version_no,
                    "checksum_sha256": row.checksum_sha256,
                    "size_bytes": row.size_bytes,
                    "content_type": row.content_type,
                    "storage_uri": row.storage_uri,
                    "producing_event_id": row.producing_event_id,
                    "work_item_id": row.work_item_id,
                    "environment_snapshot": row.environment_snapshot,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "upstream": upstream_map.get(row.artifact_id, []),
                }
                for row in versions
            ],
            "dependencies": [
                {
                    "downstream_artifact_id": edge.downstream_artifact_id,
                    "upstream_artifact_id": edge.upstream_artifact_id,
                    "relation": edge.relation,
                }
                for edge in dependencies
            ],
        }

    async def affected_by(self, case_id: str, upstream_artifact_id: str) -> list[str]:
        """沿 DAG 查"上游变了影响谁"：返回受影响的下游 artifact_id 传递闭包。"""
        result = await self._db.execute(
            select(
                CaseArtifactDependencyModel.downstream_artifact_id,
                CaseArtifactDependencyModel.upstream_artifact_id,
            ).where(CaseArtifactDependencyModel.case_id == case_id)
        )
        children: dict[str, set[str]] = {}
        for downstream, upstream in result.all():
            children.setdefault(upstream, set()).add(downstream)
        affected: set[str] = set()
        frontier = [upstream_artifact_id]
        while frontier:
            current = frontier.pop()
            for child in children.get(current, ()):
                if child not in affected:
                    affected.add(child)
                    frontier.append(child)
        return sorted(affected)

    @staticmethod
    def verify_checksum(row: CaseArtifactVersionModel, content: bytes) -> bool:
        """篡改检测：对 storage_uri 指向的内容重算 sha256 与登记值比对。"""
        return hashlib.sha256(content).hexdigest() == row.checksum_sha256

    async def verify_case_checksums(
        self,
        case_id: str,
        content_resolver: Callable[[str], Awaitable[bytes | None]],
    ) -> list[dict[str, Any]]:
        """交付前批量篡改检测：对本 Case 每个产物最新版本重算 sha256 并比对登记值。

        ``content_resolver(storage_uri)`` 返回内容字节；无法解析（对象不存在 /
        读取失败）返回 None，该版本记 ``unverified`` 而非静默跳过。比对不通过记
        ``mismatch``。本方法不抛异常——逐条返回结构化结果，由调用方留痕/告警。
        """
        rows = (
            (
                await self._db.execute(
                    select(CaseArtifactVersionModel)
                    .where(CaseArtifactVersionModel.case_id == case_id)
                    .order_by(
                        CaseArtifactVersionModel.artifact_id,
                        CaseArtifactVersionModel.version_no.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        latest: dict[str, CaseArtifactVersionModel] = {}
        for row in rows:
            latest.setdefault(row.artifact_id, row)
        results: list[dict[str, Any]] = []
        for artifact_id, row in sorted(latest.items()):
            entry: dict[str, Any] = {
                "artifact_id": artifact_id,
                "version_id": str(row.id),
                "version_no": row.version_no,
                "storage_uri": row.storage_uri,
            }
            content = await content_resolver(row.storage_uri)
            if content is None:
                results.append(
                    {**entry, "status": "unverified", "reason": "无法读取登记内容，未做比对"}
                )
                continue
            if self.verify_checksum(row, content):
                results.append({**entry, "status": "verified", "reason": "sha256 与登记值一致"})
            else:
                results.append(
                    {
                        **entry,
                        "status": "mismatch",
                        "reason": "sha256 与登记值不一致，产物可能在登记后被篡改",
                    }
                )
        return results


__all__ = [
    "VALID_RELATIONS",
    "AgentTeamsArtifactLineageService",
    "normalize_source_refs",
]
