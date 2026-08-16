"""用户 Agent 个人能力选择的无外部依赖测试。"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from omichub.api.v1.agents import (
    list_user_selectable_mcps,
    reset_user_capabilities,
    update_user_capabilities,
)
from omichub.application.schemas.agent import (
    UserAgentCapabilityDTO,
    UserAgentCapabilityRequest,
    UserSelectableMCPDTO,
)
from omichub.application.services.agent_service import AgentService
from omichub.core.exceptions import BusinessError


@pytest.mark.unit
async def test_user_capability_request_forbids_system_prompt_override() -> None:
    """用户请求只允许模型、MCP 与 Skill 字段。"""
    with pytest.raises(ValidationError, match="system_prompt"):
        UserAgentCapabilityRequest.model_validate({"system_prompt": "attempted override"})


@pytest.mark.unit
async def test_update_user_capabilities_forwards_only_selectable_assets() -> None:
    """用户路由只把资源选择交给服务层，不传递提示词字段。"""
    model_id = uuid4()
    request = UserAgentCapabilityRequest(
        model_id=model_id,
        mcp_ids=[str(uuid4())],
        skill_ids=["skill-rna"],
        features={"enable_web_search": True},
    )
    service = AsyncMock()
    service.update_user_capabilities.return_value = UserAgentCapabilityDTO(
        agent_id="agent-general",
        model_id=model_id,
        mcp_ids=request.mcp_ids,
        skill_ids=request.skill_ids,
        is_customized=True,
    )

    result = await update_user_capabilities("user-1", service, "agent-general", request)

    assert result.is_customized is True
    assert service.update_user_capabilities.await_args.args == (
        "user-1",
        "agent-general",
        request,
    )
    assert not hasattr(request, "system_prompt")


@pytest.mark.unit
def test_user_feature_selection_cannot_exceed_admin_enabled_features() -> None:
    """用户可关闭管理员开放能力，但不能自行启用管理员未开放能力。"""
    admin_features = {
        "enable_web_search": True,
        "enable_file_upload": False,
        "router": True,
    }

    effective = AgentService._effective_user_features(
        admin_features,
        {"enable_web_search": False, "enable_file_upload": True},
    )

    assert effective["enable_web_search"] is False
    assert effective["enable_file_upload"] is False
    with pytest.raises(BusinessError, match="管理员未开放"):
        AgentService._validate_user_feature_selection(
            admin_features,
            {"enable_file_upload": True},
        )


@pytest.mark.unit
async def test_reset_user_capabilities_only_targets_current_user_and_agent() -> None:
    """恢复默认由服务层按当前用户和目标 Agent 删除个人覆盖。"""
    service = AsyncMock()

    response = await reset_user_capabilities("user-1", service, "agent-general")

    assert response.status_code == 204
    assert service.reset_user_capabilities.await_args.args == ("user-1", "agent-general")


@pytest.mark.unit
async def test_user_selectable_mcps_exposes_only_safe_summary_fields() -> None:
    """普通用户能力页只能取得 MCP 摘要，不经由管理员配置接口。"""
    mcp_id = uuid4()
    service = AsyncMock()
    service.list_user_selectable_mcps.return_value = [
        UserSelectableMCPDTO(
            id=mcp_id,
            name="omics-tools",
            description="平台工具集",
            status="online",
            tool_count=3,
        )
    ]

    result = await list_user_selectable_mcps("user-1", service)

    assert result[0].id == mcp_id
    assert result[0].name == "omics-tools"
    assert not hasattr(result[0], "command")
    assert service.list_user_selectable_mcps.await_count == 1
