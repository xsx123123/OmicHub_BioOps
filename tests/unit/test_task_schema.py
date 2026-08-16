"""任务提交请求模型测试。"""

import pytest
from pydantic import ValidationError

from omichub.application.schemas.task import TaskSubmitRequest


@pytest.mark.unit
@pytest.mark.parametrize("payload", [{"flow_id": "rna_seq"}, {"flow_id": "rna_seq", "name": "   "}])
def test_task_submit_request_requires_non_empty_name(payload: dict[str, str]) -> None:
    """分析任务名称不可缺失或只包含空白字符。"""
    with pytest.raises(ValidationError, match="name"):
        TaskSubmitRequest(**payload)
