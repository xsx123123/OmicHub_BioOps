from datetime import datetime
from unittest.mock import MagicMock

from cygnusx.application.services.ai_metrics_service import AiMetricsService


def test_daily_cost_alert_is_deduplicated_for_the_current_calendar_day():
    service = AiMetricsService(MagicMock())
    now = datetime(2026, 8, 3, 16, 30, 0)

    assert service._alert_cooldown_since("daily_cost", now) == datetime(2026, 8, 3)


def test_operational_alerts_keep_the_configured_short_cooldown():
    service = AiMetricsService(MagicMock())
    service._settings = service._settings.model_copy(
        update={"ai_alert_cooldown_minutes": 30}
    )
    now = datetime(2026, 8, 3, 16, 30, 0)

    assert service._alert_cooldown_since("error_rate", now) == datetime(2026, 8, 3, 16)
    assert service._alert_cooldown_since("p95_latency", now) == datetime(2026, 8, 3, 16)
