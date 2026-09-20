"""AI 可观测性指标应用服务 — 按日趋势聚合 + 告警状态评估

数据源为 ai_call_metrics 表（由 core.ai_metrics 后台写入）。成本按平台统一口径
settings.ai_token_cookie_rate（🥫/1K tokens）折算，与"用量统计"页保持一致。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.config import get_settings
from cygnusx.infrastructure.database.models.ai_metric import (
    AiCallMetricModel,
    AiMetricAlertModel,
)


class AiMetricsService:
    """管理端 AI 指标查询与告警评估。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._settings = get_settings()

    @property
    def _cookie_rate(self) -> float:
        return float(self._settings.ai_token_cookie_rate)

    def _tokens_to_cookie(self, tokens: int) -> float:
        return round(tokens / 1000.0 * self._cookie_rate, 4)

    async def daily_trend(
        self,
        days: int = 14,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict:
        """按日聚合调用量/错误率/token/成本/延迟（avg + p95）。"""
        since = datetime.now() - timedelta(days=days)
        m = AiCallMetricModel
        day = func.date(m.created_at).label("day")
        stmt = (
            select(
                day,
                func.count().label("calls"),
                func.count().filter(m.status == "error").label("errors"),
                func.coalesce(func.sum(m.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(m.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(m.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.avg(m.duration_ms), 0).label("avg_duration_ms"),
                func.percentile_cont(0.95).within_group(m.duration_ms).label("p95_duration_ms"),
            )
            .where(m.created_at >= since)
            .group_by(day)
            .order_by(day)
        )
        stmt = self._apply_filters(stmt, model, provider)
        rows = (await self._db.execute(stmt)).all()

        daily = []
        sum_calls = sum_errors = sum_tokens = 0
        for r in rows:
            calls = int(r.calls or 0)
            errors = int(r.errors or 0)
            total_tokens = int(r.total_tokens or 0)
            sum_calls += calls
            sum_errors += errors
            sum_tokens += total_tokens
            daily.append(
                {
                    "date": str(r.day),
                    "calls": calls,
                    "errors": errors,
                    "error_rate": round(errors / calls, 4) if calls else 0.0,
                    "prompt_tokens": int(r.prompt_tokens or 0),
                    "completion_tokens": int(r.completion_tokens or 0),
                    "total_tokens": total_tokens,
                    "cost_cookie": self._tokens_to_cookie(total_tokens),
                    "avg_duration_ms": round(float(r.avg_duration_ms or 0), 1),
                    "p95_duration_ms": round(float(r.p95_duration_ms or 0), 1),
                }
            )
        return {
            "days": days,
            "model": model,
            "provider": provider,
            "cookie_rate": self._cookie_rate,
            "summary": {
                "calls": sum_calls,
                "errors": sum_errors,
                "error_rate": round(sum_errors / sum_calls, 4) if sum_calls else 0.0,
                "total_tokens": sum_tokens,
                "cost_cookie": self._tokens_to_cookie(sum_tokens),
            },
            "daily": daily,
        }

    async def model_breakdown(self, days: int = 14) -> list[dict]:
        """按模型聚合（调用量/token/成本/错误率），降序按 token。"""
        since = datetime.now() - timedelta(days=days)
        m = AiCallMetricModel
        stmt = (
            select(
                m.provider,
                m.model,
                func.count().label("calls"),
                func.count().filter(m.status == "error").label("errors"),
                func.coalesce(func.sum(m.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.avg(m.duration_ms), 0).label("avg_duration_ms"),
            )
            .where(m.created_at >= since)
            .group_by(m.provider, m.model)
            .order_by(func.sum(m.total_tokens).desc())
        )
        rows = (await self._db.execute(stmt)).all()
        result = []
        for r in rows:
            calls = int(r.calls or 0)
            errors = int(r.errors or 0)
            total_tokens = int(r.total_tokens or 0)
            result.append(
                {
                    "provider": r.provider,
                    "model": r.model,
                    "calls": calls,
                    "errors": errors,
                    "error_rate": round(errors / calls, 4) if calls else 0.0,
                    "total_tokens": total_tokens,
                    "cost_cookie": self._tokens_to_cookie(total_tokens),
                    "avg_duration_ms": round(float(r.avg_duration_ms or 0), 1),
                }
            )
        return result

    async def alert_status(self) -> dict:
        """评估 C4 三条规则的当前状态（是否超阈值），供仪表盘展示。"""
        s = self._settings
        error_rate = await self._window_error_rate(s.ai_alert_error_rate_window_minutes)
        p95 = await self._window_p95(s.ai_alert_error_rate_window_minutes)
        today_cost, avg7_cost = await self._cost_vs_7day_avg()

        cost_ratio = (today_cost / avg7_cost) if avg7_cost > 0 else 0.0
        rules = [
            {
                "rule": "error_rate",
                "label": f"错误率 > {s.ai_alert_error_rate:.0%}（近 {s.ai_alert_error_rate_window_minutes} 分钟）",
                "value": error_rate,
                "threshold": s.ai_alert_error_rate,
                "breaching": error_rate > s.ai_alert_error_rate,
                "display": f"{error_rate:.1%}",
            },
            {
                "rule": "p95_latency",
                "label": f"p95 延迟 > {s.ai_alert_p95_latency_ms:.0f}ms（近 {s.ai_alert_error_rate_window_minutes} 分钟）",
                "value": p95,
                "threshold": s.ai_alert_p95_latency_ms,
                "breaching": p95 > s.ai_alert_p95_latency_ms,
                "display": f"{p95:.0f}ms",
            },
            {
                "rule": "daily_cost",
                "label": f"日成本 > 7 日均值 {s.ai_alert_cost_ratio:.0%}",
                "value": cost_ratio,
                "threshold": s.ai_alert_cost_ratio,
                "breaching": avg7_cost > 0 and cost_ratio > s.ai_alert_cost_ratio,
                "display": f"今日 {today_cost:.1f}🥫 / 均值 {avg7_cost:.1f}🥫",
            },
        ]
        return {"enabled": s.ai_alert_enabled, "rules": rules}

    async def alert_history(self, limit: int = 50) -> list[dict]:
        """近期告警历史（倒序）。"""
        stmt = (
            select(AiMetricAlertModel)
            .order_by(AiMetricAlertModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        return [
            {
                "id": str(a.id),
                "rule": a.rule,
                "level": a.level,
                "message": a.message,
                "metric_value": a.metric_value,
                "threshold": a.threshold,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]

    async def check_and_fire_alerts(self) -> list[dict]:
        """评估 C4 规则，对超阈值且过冷却期的规则落一条告警记录。

        返回本次新触发的告警列表（供调用方推送通知）；调用方负责 commit。
        """
        s = self._settings
        if not s.ai_alert_enabled:
            return []
        status = await self.alert_status()
        now = datetime.now()

        fired: list[dict] = []
        for rule in status["rules"]:
            if not rule["breaching"]:
                continue
            cooldown_since = self._alert_cooldown_since(rule["rule"], now)
            recent = (
                await self._db.execute(
                    select(AiMetricAlertModel.id)
                    .where(
                        AiMetricAlertModel.rule == rule["rule"],
                        AiMetricAlertModel.created_at >= cooldown_since,
                    )
                    .limit(1)
                )
            ).first()
            if recent is not None:
                continue  # 冷却期内，抑制重复告警
            message = f"[AI 告警] {rule['label']}，当前 {rule['display']}"
            self._db.add(
                AiMetricAlertModel(
                    rule=rule["rule"],
                    level="error" if rule["rule"] == "error_rate" else "warning",
                    message=message,
                    metric_value=float(rule["value"]),
                    threshold=float(rule["threshold"]),
                )
            )
            fired.append(
                {
                    "rule": rule["rule"],
                    "level": "error" if rule["rule"] == "error_rate" else "warning",
                    "message": message,
                    "value": rule["value"],
                    "threshold": rule["threshold"],
                }
            )
        return fired


    # ---- 内部聚合 ----

    def _alert_cooldown_since(self, rule: str, now: datetime) -> datetime:
        if rule == "daily_cost":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        return now - timedelta(minutes=self._settings.ai_alert_cooldown_minutes)

    def _apply_filters(self, stmt, model: str | None, provider: str | None):
        m = AiCallMetricModel
        if model:
            stmt = stmt.where(m.model == model)
        if provider:
            stmt = stmt.where(m.provider == provider)
        return stmt

    async def _window_error_rate(self, window_minutes: int) -> float:
        since = datetime.now() - timedelta(minutes=window_minutes)
        m = AiCallMetricModel
        stmt = select(
            func.count(),
            func.count().filter(m.status == "error"),
        ).where(m.created_at >= since)
        row = (await self._db.execute(stmt)).one()
        calls = int(row[0] or 0)
        errors = int(row[1] or 0)
        return round(errors / calls, 4) if calls else 0.0

    async def _window_p95(self, window_minutes: int) -> float:
        since = datetime.now() - timedelta(minutes=window_minutes)
        m = AiCallMetricModel
        stmt = select(func.percentile_cont(0.95).within_group(m.duration_ms)).where(
            m.created_at >= since
        )
        value = (await self._db.execute(stmt)).scalar()
        return round(float(value or 0), 1)

    async def _cost_vs_7day_avg(self) -> tuple[float, float]:
        """返回 (今日成本, 近 7 日日均成本)，单位 🥫。"""
        m = AiCallMetricModel
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        today_stmt = select(func.coalesce(func.sum(m.total_tokens), 0)).where(
            m.created_at >= today_start
        )
        today_tokens = int((await self._db.execute(today_stmt)).scalar() or 0)

        week_start = today_start - timedelta(days=7)
        week_stmt = select(
            func.date(m.created_at).label("day"),
            func.coalesce(func.sum(m.total_tokens), 0).label("tokens"),
        ).where(m.created_at >= week_start, m.created_at < today_start).group_by(func.date(m.created_at))
        week_rows = (await self._db.execute(week_stmt)).all()
        avg7_tokens = (sum(int(r.tokens or 0) for r in week_rows) / 7.0) if week_rows else 0.0

        return self._tokens_to_cookie(today_tokens), self._tokens_to_cookie(int(avg7_tokens))
