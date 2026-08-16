"""
OmicHubCheckpointSaver
=======================
LangGraph 的 PostgreSQL + Redis 持久化检查点实现。

功能:
    - 状态持久化: 每个 superstep 自动保存到 PostgreSQL
    - 断点恢复: 通过 thread_id 恢复任意时刻的状态
    - 历史查询: 列出某 thread 的所有检查点版本
    - Redis 缓存: 热状态缓存，减少 PG 查询

适配 OmicHub:
    - 复用现有 PostgreSQL 连接 (SQLAlchemy asyncpg)
    - 复用现有 Redis 连接 (infrastructure/cache/)
    - Alembic 迁移管理表结构
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
)
from sqlalchemy import select, delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.infrastructure.database.session import async_session_factory
from omichub.infrastructure.cache import redis_client


# ──────────────────────────────
# JSON 序列化器
# ──────────────────────────────

class JsonSerializer(SerializerProtocol):
    """使用 JSON 序列化（兼容 OmicHub 现有基础设施）"""

    def dumps(self, obj: Any) -> bytes:
        return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")

    def loads(self, data: bytes) -> Any:
        return json.loads(data.decode("utf-8"))


# ──────────────────────────────
# PostgreSQL 检查点存储
# ──────────────────────────────

class OmicHubCheckpointSaver(BaseCheckpointSaver):
    """
    LangGraph CheckPointSaver 的 OmicHub 实现。

    使用 PostgreSQL 作为主存储，Redis 作为热缓存。
    支持异步操作，与 OmicHub 的 asyncpg + SQLAlchemy 架构兼容。
    """

    serializer = JsonSerializer()

    def __init__(
        self,
        db_session: Optional[AsyncSession] = None,
        redis_prefix: str = "lg_ckpt",
        cache_ttl: int = 3600,
    ):
        super().__init__()
        self._db = db_session
        self._redis_prefix = redis_prefix
        self._cache_ttl = cache_ttl
        self._owns_session = db_session is None

    # ── 数据库会话管理 ──

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        """获取数据库会话（支持外部传入或自建）"""
        if self._db is not None:
            yield self._db
        else:
            session = async_session_factory()
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    # ── Redis 缓存辅助 ──

    def _cache_key(self, thread_id: str, checkpoint_ns: str = "", checkpoint_id: Optional[str] = None) -> str:
        key = f"{self._redis_prefix}:{thread_id}:{checkpoint_ns}"
        if checkpoint_id:
            key = f"{key}:{checkpoint_id}"
        return key

    async def _cache_get(self, key: str) -> Optional[bytes]:
        """从 Redis 获取缓存"""
        try:
            data = await redis_client.get(key)
            return data if data else None
        except Exception:
            return None

    async def _cache_set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        """写入 Redis 缓存"""
        try:
            await redis_client.setex(key, ttl or self._cache_ttl, value)
        except Exception:
            pass

    async def _cache_delete(self, pattern: str) -> None:
        """删除匹配模式的缓存"""
        try:
            keys = await redis_client.keys(pattern)
            if keys:
                await redis_client.delete(*keys)
        except Exception:
            pass

    # ── 核心 CRUD ──

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """
        获取指定 thread + checkpoint_id 的检查点。
        先查 Redis 缓存，未命中再查 PostgreSQL。
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        # 1. 尝试 Redis 缓存
        cache_key = self._cache_key(thread_id, checkpoint_ns, checkpoint_id)
        cached = await self._cache_get(cache_key)
        if cached:
            data = self.serializer.loads(cached)
            return self._dict_to_tuple(data)

        # 2. 查询 PostgreSQL
        async with self._session() as session:
            query = select(langgraph_checkpoint_table).where(
                langgraph_checkpoint_table.c.thread_id == thread_id,
                langgraph_checkpoint_table.c.checkpoint_ns == checkpoint_ns,
            )
            if checkpoint_id:
                query = query.where(
                    langgraph_checkpoint_table.c.checkpoint_id == checkpoint_id
                )
            else:
                # 未指定 checkpoint_id，取最新的
                query = query.order_by(
                    langgraph_checkpoint_table.c.created_at.desc()
                ).limit(1)

            result = await session.execute(query)
            row = result.mappings().first()

            if not row:
                return None

            # 写入缓存
            data = dict(row)
            cache_key = self._cache_key(thread_id, checkpoint_ns, row["checkpoint_id"])
            await self._cache_set(cache_key, self.serializer.dumps(data))

            return self._dict_to_tuple(data)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """
        列出检查点历史（支持过滤和分页）
        """
        thread_id = config["configurable"]["thread_id"] if config else None
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "") if config else ""

        async with self._session() as session:
            query = select(langgraph_checkpoint_table)

            if thread_id:
                query = query.where(
                    langgraph_checkpoint_table.c.thread_id == thread_id
                )
            if checkpoint_ns:
                query = query.where(
                    langgraph_checkpoint_table.c.checkpoint_ns == checkpoint_ns
                )

            # 过滤条件
            if filter:
                if "user_id" in filter:
                    query = query.where(
                        langgraph_checkpoint_table.c.user_id == filter["user_id"]
                    )
                if "session_id" in filter:
                    query = query.where(
                        langgraph_checkpoint_table.c.session_id == filter["session_id"]
                    )
                if "status" in filter:
                    query = query.where(
                        langgraph_checkpoint_table.c.status == filter["status"]
                    )

            # 时间范围
            if before:
                before_id = before["configurable"].get("checkpoint_id")
                if before_id:
                    # 找到对应时间戳
                    subquery = select(langgraph_checkpoint_table.c.created_at).where(
                        langgraph_checkpoint_table.c.checkpoint_id == before_id
                    )
                    result = await session.execute(subquery)
                    before_row = result.scalar_one_or_none()
                    if before_row:
                        query = query.where(
                            langgraph_checkpoint_table.c.created_at < before_row
                        )

            query = query.order_by(langgraph_checkpoint_table.c.created_at.desc())

            if limit:
                query = query.limit(limit)

            result = await session.execute(query)
            rows = result.mappings().all()

            for row in rows:
                yield self._dict_to_tuple(dict(row))

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """
        保存检查点 —— LangGraph 每个 superstep 自动调用
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        # 序列化
        checkpoint_bytes = self.serializer.dumps(checkpoint)
        metadata_bytes = self.serializer.dumps(metadata)

        # 提取 OmicHub 业务字段（从 checkpoint 的 channel_values 中）
        channel_values = checkpoint.get("channel_values", {})
        agent_state_data = channel_values.get("__root__", {})

        user_id = None
        session_id = None
        status = "running"

        if isinstance(agent_state_data, dict):
            meta = agent_state_data.get("metadata", {})
            user_id = meta.get("user_id")
            session_id = meta.get("session_id")

            # 从状态推断运行状态
            if agent_state_data.get("is_finished"):
                status = "completed" if not agent_state_data.get("error") else "failed"
            elif agent_state_data.get("hitl_status") == "pending":
                status = "hitl_pending"

        async with self._session() as session:
            # UPSERT (PostgreSQL 的 ON CONFLICT)
            stmt = pg_insert(langgraph_checkpoint_table).values(
                id=f"ckpt_{uuid.uuid4().hex[:16]}",
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
                parent_checkpoint_id=parent_checkpoint_id,
                checkpoint=checkpoint_bytes,
                metadata_=metadata_bytes,
                user_id=user_id,
                session_id=session_id,
                status=status,
                created_at=time.time(),
                updated_at=time.time(),
            ).on_conflict_do_update(
                index_elements=["thread_id", "checkpoint_ns", "checkpoint_id"],
                set_={
                    "checkpoint": checkpoint_bytes,
                    "metadata_": metadata_bytes,
                    "user_id": user_id,
                    "session_id": session_id,
                    "status": status,
                    "updated_at": time.time(),
                }
            )

            await session.execute(stmt)

            # 更新 Redis 缓存（最新的检查点）
            cache_key = self._cache_key(thread_id, checkpoint_ns, checkpoint_id)
            data = {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "parent_checkpoint_id": parent_checkpoint_id,
                "checkpoint": json.loads(checkpoint_bytes.decode("utf-8")),
                "metadata": json.loads(metadata_bytes.decode("utf-8")),
                "user_id": user_id,
                "session_id": session_id,
                "status": status,
                "created_at": time.time(),
            }
            await self._cache_set(cache_key, self.serializer.dumps(data))

        # 返回新的 config
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: List[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        保存写入操作（用于并行分支和 Human-in-the-loop）
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        async with self._session() as session:
            for channel, value in writes:
                write_id = f"wrt_{uuid.uuid4().hex[:12]}"
                stmt = pg_insert(langgraph_checkpoint_writes_table).values(
                    id=write_id,
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    task_id=task_id,
                    task_path=task_path,
                    channel=channel,
                    value=self.serializer.dumps(value),
                    created_at=time.time(),
                )
                await session.execute(stmt)

    # ── 辅助方法 ──

    def _dict_to_tuple(self, data: Dict[str, Any]) -> CheckpointTuple:
        """将数据库行转换为 CheckpointTuple"""
        checkpoint = data.get("checkpoint")
        metadata = data.get("metadata_", {})

        # 反序列化
        if isinstance(checkpoint, (bytes, str)):
            checkpoint = self.serializer.loads(
                checkpoint if isinstance(checkpoint, bytes) else checkpoint.encode("utf-8")
            )
        if isinstance(metadata, (bytes, str)):
            metadata = self.serializer.loads(
                metadata if isinstance(metadata, bytes) else metadata.encode("utf-8")
            )

        config = {
            "configurable": {
                "thread_id": data["thread_id"],
                "checkpoint_ns": data.get("checkpoint_ns", ""),
                "checkpoint_id": data["checkpoint_id"],
            }
        }

        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config={
                "configurable": {
                    "thread_id": data["thread_id"],
                    "checkpoint_ns": data.get("checkpoint_ns", ""),
                    "checkpoint_id": data.get("parent_checkpoint_id"),
                }
            } if data.get("parent_checkpoint_id") else None,
            pending_writes=[],  # 简化处理
        )

    # ── OmicHub 业务扩展 ──

    async def get_thread_status(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """获取线程当前状态（OmicHub 业务方法）"""
        async with self._session() as session:
            query = select(
                langgraph_checkpoint_table.c.status,
                langgraph_checkpoint_table.c.user_id,
                langgraph_checkpoint_table.c.session_id,
                langgraph_checkpoint_table.c.updated_at,
            ).where(
                langgraph_checkpoint_table.c.thread_id == thread_id
            ).order_by(
                langgraph_checkpoint_table.c.created_at.desc()
            ).limit(1)

            result = await session.execute(query)
            row = result.mappings().first()
            return dict(row) if row else None

    async def cleanup_old_checkpoints(self, days: int = 7) -> int:
        """清理 N 天前的旧检查点（定时任务调用）"""
        cutoff = time.time() - (days * 86400)
        async with self._session() as session:
            stmt = delete(langgraph_checkpoint_table).where(
                langgraph_checkpoint_table.c.created_at < cutoff,
                langgraph_checkpoint_table.c.status.in_(["completed", "failed"]),
            )
            result = await session.execute(stmt)

            # 清理关联 writes
            stmt_writes = delete(langgraph_checkpoint_writes_table).where(
                langgraph_checkpoint_writes_table.c.created_at < cutoff,
            )
            await session.execute(stmt_writes)

            return result.rowcount


# ──────────────────────────────
# SQLAlchemy 表定义（用于查询）
# ──────────────────────────────

from sqlalchemy import Table, Column, String, LargeBinary, Integer, Float, MetaData, Index

metadata = MetaData()

langgraph_checkpoint_table = Table(
    "langgraph_checkpoints",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("thread_id", String(64), nullable=False),
    Column("checkpoint_ns", String(64), nullable=False, default=""),
    Column("checkpoint_id", String(64), nullable=False),
    Column("parent_checkpoint_id", String(64), nullable=True),
    Column("checkpoint", LargeBinary, nullable=False),
    Column("metadata_", LargeBinary, nullable=True),
    Column("user_id", Integer, nullable=True),
    Column("session_id", String(64), nullable=True),
    Column("status", String(20), nullable=False, default="running"),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    # 唯一约束
    Index("idx_ckpt_thread_checkpoint", "thread_id", "checkpoint_ns", "checkpoint_id", unique=True),
    # 查询索引
    Index("idx_ckpt_user", "user_id", "created_at"),
    Index("idx_ckpt_session", "session_id", "created_at"),
    Index("idx_ckpt_status", "status", "created_at"),
)

langgraph_checkpoint_writes_table = Table(
    "langgraph_checkpoint_writes",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("thread_id", String(64), nullable=False),
    Column("checkpoint_ns", String(64), nullable=False, default=""),
    Column("checkpoint_id", String(64), nullable=False),
    Column("task_id", String(32), nullable=False),
    Column("task_path", String(64), nullable=False, default=""),
    Column("channel", String(64), nullable=False),
    Column("value", LargeBinary, nullable=False),
    Column("created_at", Float, nullable=False),
    Index("idx_ckptwrt_thread_checkpoint", "thread_id", "checkpoint_ns", "checkpoint_id"),
)
