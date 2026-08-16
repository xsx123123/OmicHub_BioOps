"""仪表板统计应用服务 — 个人指标 + 管理员全平台态势。

聚合查询落在仓储层（TaskRepositoryImpl / SqlAlchemyUserRepository），
本服务负责编排、缺日补零、flow_id→name 映射与 Redis 缓存包装。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.services.flow_service import FlowService
from omichub.application.services.cookie_service import CookieService
from omichub.core.config import get_settings
from omichub.domain.task.value_objects import TaskStatus
from omichub.infrastructure.cache.stats_cache import cached_json
from omichub.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel
from omichub.infrastructure.database.models.task import TaskModel
from omichub.infrastructure.database.models.user import UserModel
from omichub.infrastructure.database.repositories.file_repository import (
    SampleRepositoryImpl,
)
from omichub.infrastructure.database.repositories.task_repository import (
    TaskRepositoryImpl,
)
from omichub.infrastructure.database.repositories.user_repository import (
    SqlAlchemyUserRepository,
)

# 各类缓存 TTL（秒）
_TTL_USER = 60  # 个人指标：1 分钟
_TTL_ADMIN = 300  # 管理员全平台指标：5 分钟


class StatsService:
    """仪表板统计服务"""

    def __init__(
        self,
        db: AsyncSession,
        flow_service: FlowService | None = None,
    ):
        self._db = db
        self._task_repo = TaskRepositoryImpl(db)
        self._user_repo = SqlAlchemyUserRepository(db)
        self._sample_repo = SampleRepositoryImpl(db)
        self._flow_service = flow_service or FlowService()

    # ------------------------------------------------------------------
    # 个人指标（当前用户）
    # ------------------------------------------------------------------

    async def user_overview(self, user_id: str) -> dict:
        """状态卡：运行中 / 总任务 / 数据样本数。

        数据样本取「数据管理」登记的样本表（与 /files/samples 同源），
        而非各任务 sample_count 之和——后者会把富集工具的基因数误计为样本。
        """

        async def _compute() -> dict:
            uid = UUID(user_id)
            statuses = await self._status_map(uid)
            total = sum(statuses.values())
            return {
                "running": statuses.get(TaskStatus.RUNNING.value, 0),
                "total": total,
                "samples": await self._sample_repo.count_by_user(uid),
            }

        return await cached_json(f"stats:overview:{user_id}", _TTL_USER, _compute)

    async def user_trend(self, user_id: str, days: int) -> list[dict]:
        """近 N 天每日任务数 + 样本数（缺日补 0）。"""

        async def _compute() -> list[dict]:
            uid = UUID(user_id)
            rows = await self._task_repo.count_trend_by_day(days, uid)
            by_date = {row[0]: (int(row[1]), int(row[2])) for row in rows}
            result: list[dict] = []
            for i in range(days - 1, -1, -1):
                d = date.today() - timedelta(days=i)
                tasks, samples = by_date.get(d, (0, 0))
                result.append({"date": d.strftime("%m/%d"), "tasks": tasks, "samples": samples})
            return result

        return await cached_json(f"stats:trend:{user_id}:{days}", _TTL_USER, _compute)

    async def user_progress(self, user_id: str) -> dict:
        """动态用户引导画像：三步完成状态 + 当前步骤。"""

        async def _compute() -> dict:
            uid = UUID(user_id)
            statuses = await self._status_map(uid)
            total = sum(statuses.values())
            run_like = {
                TaskStatus.RUNNING.value,
                TaskStatus.SUCCESS.value,
                TaskStatus.FAILED.value,
            }
            has_run = any(s in statuses for s in run_like)
            has_success = statuses.get(TaskStatus.SUCCESS.value, 0) > 0
            steps = [
                {"number": 1, "title": "提交首个分析任务", "done": total > 0},
                {"number": 2, "title": "运行分析管线", "done": has_run},
                {"number": 3, "title": "获得分析结果", "done": has_success},
            ]
            current = next((s["number"] for s in steps if not s["done"]), None)
            return {"steps": steps, "current": current}

        return await cached_json(f"stats:progress:{user_id}", _TTL_USER, _compute)

    async def user_studio_usage(self, user_id: str, days: int) -> dict[str, Any]:
        """近 N 天 AI 对话 token、沙盒执行与存储配额汇总。

        覆盖该用户全部会话（普通对话 mode="chat" 与工作台 mode="studio"），
        确保 AI 对话中产生的 token/消息量都能汇总显示；协作室合成会话
        （mode="agentteams"）在此排除，其用量由 token 用量页单独展示。
        """

        async def _compute() -> dict[str, Any]:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            session_result = await self._db.execute(
                select(
                    ChatSessionModel.session_id,
                    ChatSessionModel.created_at,
                ).where(
                    ChatSessionModel.user_id == user_id,
                    ChatSessionModel.created_at >= cutoff,
                    # 协作室合成会话（mode="agentteams"）只进 token 用量页，不计入工作室用量
                    ChatSessionModel.mode != "agentteams",
                )
            )
            message_result = await self._db.execute(
                select(
                    ChatMessageModel.role,
                    ChatMessageModel.metadata_json,
                    ChatMessageModel.created_at,
                )
                .join(
                    ChatSessionModel,
                    ChatSessionModel.session_id == ChatMessageModel.session_id,
                )
                .where(
                    ChatSessionModel.user_id == user_id,
                    ChatMessageModel.created_at >= cutoff,
                    ChatSessionModel.mode != "agentteams",
                )
            )
            task_result = await self._db.execute(
                select(
                    TaskModel.status,
                    TaskModel.started_at,
                    TaskModel.finished_at,
                    TaskModel.created_at,
                ).where(
                    TaskModel.user_id == UUID(user_id),
                    TaskModel.flow_id == "studio_sandbox",
                    TaskModel.created_at >= cutoff,
                )
            )
            user = await self._db.get(UserModel, UUID(user_id))
            return self._aggregate_studio_usage(
                days=days,
                session_rows=list(session_result.all()),
                message_rows=list(message_result.all()),
                task_rows=list(task_result.all()),
                storage_used=int(user.used_storage or 0) if user else 0,
                storage_quota=int(user.storage_quota or 0) if user else 0,
            )

        return await cached_json(f"stats:studio:{user_id}:{days}", _TTL_USER, _compute)

    async def user_ai_token_usage(self, user_id: str, days: int, limit: int = 50) -> dict[str, Any]:
        """近 N 天 AI 对话 token 消耗与饼干折算（用量统计页）。

        记录取自带 usage 的 assistant 消息，饼干按 ai_token_cookie_rate 🥫/1K tokens 折算。
        """

        async def _compute() -> dict[str, Any]:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            result = await self._db.execute(
                select(
                    ChatMessageModel.created_at,
                    ChatMessageModel.metadata_json,
                    ChatSessionModel.session_id,
                    ChatSessionModel.title,
                )
                .join(
                    ChatSessionModel,
                    ChatSessionModel.session_id == ChatMessageModel.session_id,
                )
                .where(
                    ChatSessionModel.user_id == user_id,
                    ChatMessageModel.role == "assistant",
                    ChatMessageModel.created_at >= cutoff,
                )
                .order_by(ChatMessageModel.created_at.desc())
            )
            rows = list(result.all())

            _, rate, _ = await CookieService(self._db).resolve_ai_token_rate()

            def _cookie_cost(tokens: int) -> float:
                return float(
                    (Decimal(tokens) / Decimal(1000) * rate).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                )

            today = datetime.now(UTC).date()
            dates = [today - timedelta(days=index) for index in range(days - 1, -1, -1)]
            daily = {
                d: {"date": d.isoformat(), "messages": 0, "total_tokens": 0, "cookie_cost": 0.0}
                for d in dates
            }

            input_tokens = 0
            output_tokens = 0
            total_tokens = 0
            billed_messages = 0
            session_ids: set[str] = set()
            records: list[dict[str, Any]] = []

            for created_at, metadata, session_id, title in rows:
                usage = (metadata or {}).get("usage") or {}
                prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("input") or 0)
                completion = int(
                    usage.get("completion_tokens")
                    or usage.get("output_tokens")
                    or usage.get("output")
                    or 0
                )
                message_total = int(
                    usage.get("total_tokens") or usage.get("total") or prompt + completion
                )
                if message_total <= 0:
                    continue
                input_tokens += prompt
                output_tokens += completion
                total_tokens += message_total
                billed_messages += 1
                session_ids.add(session_id)
                day = created_at.date() if created_at else None
                if day in daily:
                    daily[day]["messages"] += 1
                    daily[day]["total_tokens"] += message_total
                    daily[day]["cookie_cost"] = round(
                        daily[day]["cookie_cost"] + _cookie_cost(message_total), 2
                    )
                if len(records) < limit:
                    records.append(
                        {
                            "time": created_at.isoformat() if created_at else None,
                            "session_id": session_id,
                            "title": title or "未命名对话",
                            "input_tokens": prompt,
                            "output_tokens": completion,
                            "total_tokens": message_total,
                            "cookie_cost": _cookie_cost(message_total),
                        }
                    )

            return {
                "period_days": days,
                "rate_per_1k_tokens": float(rate),
                "summary": {
                    "messages": billed_messages,
                    "sessions": len(session_ids),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "cookie_cost": _cookie_cost(total_tokens),
                },
                "daily": list(daily.values()),
                "records": records,
            }

        return await cached_json(
            f"stats:ai_usage:{user_id}:{days}:{limit}", _TTL_USER, _compute
        )

    # ------------------------------------------------------------------
    # 管理员全平台指标
    # ------------------------------------------------------------------

    async def admin_status(self) -> dict[str, int]:
        """全平台各状态任务数。"""
        return await cached_json("stats:admin:status", _TTL_ADMIN, self._status_map)

    async def admin_flow_usage(self) -> list[dict]:
        """流程累计调用频次（按 count 降序，flow_id→name 映射）。"""

        async def _compute() -> list[dict]:
            rows = await self._task_repo.count_by_flow(None)
            flow_map = {f.id: f.name for f in self._flow_service.list_flows().items}
            usage = [
                {
                    "flow_id": row[0],
                    "name": flow_map.get(row[0], row[0]),
                    "count": int(row[1]),
                }
                for row in rows
            ]
            usage.sort(key=lambda x: x["count"], reverse=True)
            return usage

        return await cached_json("stats:admin:flows", _TTL_ADMIN, _compute)

    async def admin_user_stats(self) -> dict:
        """全平台注册用户数 + 近 7 天活跃用户数。"""

        async def _compute() -> dict:
            return {
                "total_users": await self._user_repo.count_total(),
                "active_users_7d": await self._task_repo.count_active_users_since(7),
            }

        return await cached_json("stats:admin:users", _TTL_ADMIN, _compute)

    async def admin_recent_failed(self, limit: int = 10) -> list[dict]:
        """近期失败任务（实时，不缓存）。"""
        tasks = await self._task_repo.list_recent_failed(limit, None)
        return [
            {
                "id": str(t.id),
                "name": t.name,
                "flow_id": t.flow_id,
                "user_id": str(t.user_id),
                "error_message": t.error_message,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ]

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _status_map(self, user_id: UUID | None = None) -> dict[str, int]:
        """status -> count 映射。user_id 为 None 时为全平台。"""
        rows = await self._task_repo.count_by_status(user_id)
        return {str(row[0]): int(row[1]) for row in rows}

    @staticmethod
    def _aggregate_studio_usage(
        *,
        days: int,
        session_rows: list[Any],
        message_rows: list[Any],
        task_rows: list[Any],
        storage_used: int,
        storage_quota: int,
    ) -> dict[str, Any]:
        """聚合已持久化的会话（chat + studio）、消息和长任务记录。"""
        today = datetime.now(UTC).date()
        dates = [today - timedelta(days=index) for index in range(days - 1, -1, -1)]
        daily = {
            item: {
                "date": item.isoformat(),
                "sessions": 0,
                "messages": 0,
                "total_tokens": 0,
                "sandbox_runs": 0,
                "sandbox_duration_ms": 0,
            }
            for item in dates
        }

        for row in session_rows:
            created_at = row[1]
            day = created_at.date() if created_at else None
            if day in daily:
                daily[day]["sessions"] += 1

        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        sync_runs = 0
        sync_successes = 0
        sync_duration_ms = 0
        artifact_paths: set[str] = set()

        for row in message_rows:
            role, metadata, created_at = row
            metadata = metadata or {}
            day = created_at.date() if created_at else None
            if day in daily:
                daily[day]["messages"] += 1

            if role == "assistant":
                usage = metadata.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("input") or 0)
                completion_tokens = int(
                    usage.get("completion_tokens")
                    or usage.get("output_tokens")
                    or usage.get("output")
                    or 0
                )
                message_total = int(
                    usage.get("total_tokens")
                    or usage.get("total")
                    or prompt_tokens + completion_tokens
                )
                input_tokens += prompt_tokens
                output_tokens += completion_tokens
                total_tokens += message_total
                if day in daily:
                    daily[day]["total_tokens"] += message_total

            for invocation in metadata.get("tool_invocations") or []:
                if invocation.get("tool_name") != "sandbox_execute":
                    continue
                payload = invocation.get("ui_payload") or {}
                if "duration_ms" not in payload:
                    continue
                duration_ms = max(0, int(payload.get("duration_ms") or 0))
                sync_runs += 1
                sync_duration_ms += duration_ms
                if invocation.get("success") and int(payload.get("exit_code", -1)) == 0:
                    sync_successes += 1
                for artifact in payload.get("artifacts") or []:
                    path = artifact.get("path") if isinstance(artifact, dict) else None
                    if path:
                        artifact_paths.add(str(path))
                if day in daily:
                    daily[day]["sandbox_runs"] += 1
                    daily[day]["sandbox_duration_ms"] += duration_ms

        long_runs = 0
        long_successes = 0
        long_duration_ms = 0
        for row in task_rows:
            status, started_at, finished_at, created_at = row
            duration_ms = 0
            if started_at and finished_at:
                duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
            long_runs += 1
            long_duration_ms += duration_ms
            if status == TaskStatus.SUCCESS.value:
                long_successes += 1
            day = created_at.date() if created_at else None
            if day in daily:
                daily[day]["sandbox_runs"] += 1
                daily[day]["sandbox_duration_ms"] += duration_ms

        sandbox_runs = sync_runs + long_runs
        sandbox_successes = sync_successes + long_successes
        storage_available = max(0, storage_quota - storage_used)
        storage_percent = round(storage_used / storage_quota * 100, 2) if storage_quota else 0.0

        cookie_rate = Decimal(str(get_settings().ai_token_cookie_rate))
        cookie_cost = (Decimal(total_tokens) / Decimal(1000) * cookie_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        return {
            "period_days": days,
            "from": dates[0].isoformat(),
            "to": dates[-1].isoformat(),
            "summary": {
                "sessions": len(session_rows),
                "messages": len(message_rows),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "sandbox_runs": sandbox_runs,
                "sandbox_successes": sandbox_successes,
                "sandbox_failures": sandbox_runs - sandbox_successes,
                "sandbox_success_rate": (
                    round(sandbox_successes / sandbox_runs * 100, 2) if sandbox_runs else 0.0
                ),
                "sandbox_duration_ms": sync_duration_ms + long_duration_ms,
                "long_tasks": long_runs,
                "artifacts": len(artifact_paths),
            },
            "quota": {
                "storage_used": storage_used,
                "storage_quota": storage_quota,
                "storage_available": storage_available,
                "storage_used_percent": storage_percent,
            },
            "cookie": {
                "rate_per_1k_tokens": float(cookie_rate),
                "cost": float(cookie_cost),
            },
            "daily": list(daily.values()),
        }
