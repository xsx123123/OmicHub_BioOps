"""配置加载单元测试"""

import pytest

from cygnusx.core.config import get_settings


@pytest.mark.unit
def test_settings_loads_defaults():
    """测试 Settings 能正确加载默认值"""
    settings = get_settings()
    assert settings.app_name == "CygnusX"
    assert settings.app_debug is True
    assert settings.task_queue_backend == "celery"
    assert settings.rocketmq_task_routes == []
    assert settings.overdrive_authoritative_mode == "constraint"
    assert settings.overdrive_plan_repair_enabled is True
