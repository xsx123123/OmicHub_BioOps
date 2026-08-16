"""管理员维护 AgentTeams Bridge 的运行配置。"""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from omichub.api.deps import AdminRequired, DbSession, require_admin_totp
from omichub.application.schemas.agentteams_bridge import (
    AgentTeamsBridgeConfigDTO,
    AgentTeamsBridgeConfigUpdateDTO,
    AgentTeamsBridgeTokenBundleDTO,
    AgentTeamsWorkerTokenIssueDTO,
)
from omichub.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeSettingsService,
)
from omichub.application.services.agentteams_service import AgentTeamsService
from omichub.core.config import get_settings

router = APIRouter()


async def get_bridge_service(db: DbSession) -> AgentTeamsBridgeSettingsService:
    return AgentTeamsBridgeSettingsService(db, get_settings())


BridgeServiceDep = Annotated[AgentTeamsBridgeSettingsService, Depends(get_bridge_service)]


async def _with_connection_state(
    service: AgentTeamsBridgeSettingsService,
) -> AgentTeamsBridgeConfigDTO:
    config = await service.get_public_config()
    runtime = await service.get_runtime_config()
    config.connected = await AgentTeamsService(get_settings(), runtime).is_connected()
    return config


@router.get("/agentteams-bridge", response_model=AgentTeamsBridgeConfigDTO)
async def get_agentteams_bridge_config(
    _admin: AdminRequired,
    service: BridgeServiceDep,
) -> AgentTeamsBridgeConfigDTO:
    return await _with_connection_state(service)


@router.get("/agentteams-bridge/health", summary="检查 Bridge、身份令牌与外部 Worker 健康状态")
async def get_agentteams_bridge_health(
    _admin: AdminRequired,
    service: BridgeServiceDep,
) -> dict:
    runtime = await service.get_runtime_config()
    return await AgentTeamsService(get_settings(), runtime).health_check()


@router.get("/agentteams-bridge/resources", summary="获取 AgentTeams Worker、Team 与 Case 资源快照")
async def get_agentteams_bridge_resources(
    _admin: AdminRequired,
    service: BridgeServiceDep,
) -> dict:
    runtime = await service.get_runtime_config()
    return await AgentTeamsService(get_settings(), runtime).admin_resource_snapshot()


@router.get("/agentteams-bridge/metrics", summary="获取 AgentTeams Case 与 Work Item 可观测指标")
async def get_agentteams_bridge_metrics(
    _admin: AdminRequired,
    service: BridgeServiceDep,
) -> dict[str, int]:
    runtime = await service.get_runtime_config()
    return await AgentTeamsService(get_settings(), runtime).admin_metrics()


@router.post("/agentteams-bridge/cases/{case_id}/reconcile", summary="以管理员身份重协调协作 Case")
async def reconcile_agentteams_bridge_case(
    case_id: str,
    db: DbSession,
    _admin_id: AdminRequired,
    service: BridgeServiceDep,
    x_totp_code: Annotated[str | None, Header(alias="X-TOTP-Code")] = None,
) -> dict:
    await require_admin_totp(_admin_id, db, x_totp_code)
    runtime = await service.get_runtime_config()
    return await AgentTeamsService(get_settings(), runtime).reconcile_case_as_admin(case_id)


@router.post(
    "/agentteams-bridge/tokens",
    response_model=AgentTeamsBridgeTokenBundleDTO,
    summary="生成一次性 AgentTeams Worker 令牌",
)
async def generate_agentteams_bridge_tokens(
    db: DbSession,
    _admin_id: AdminRequired,
    x_totp_code: Annotated[str | None, Header(alias="X-TOTP-Code")] = None,
) -> AgentTeamsBridgeTokenBundleDTO:
    """Generate credentials for manual deployment without persisting or logging them."""
    await require_admin_totp(_admin_id, db, x_totp_code)
    return AgentTeamsBridgeTokenBundleDTO(
        manager_token=secrets.token_urlsafe(32),
        data_steward_token=secrets.token_urlsafe(32),
        approval_token=secrets.token_urlsafe(32),
        workflow_operator_token=secrets.token_urlsafe(32),
    )


@router.put("/agentteams-bridge", response_model=AgentTeamsBridgeConfigDTO)
async def update_agentteams_bridge_config(
    request: AgentTeamsBridgeConfigUpdateDTO,
    db: DbSession,
    _admin_id: AdminRequired,
    x_totp_code: Annotated[str | None, Header(alias="X-TOTP-Code")] = None,
) -> AgentTeamsBridgeConfigDTO:
    await require_admin_totp(_admin_id, db, x_totp_code)
    service = AgentTeamsBridgeSettingsService(db, get_settings())
    await service.update_config(request)
    return await _with_connection_state(service)


@router.get("/agentteams-bridge/worker-tokens", summary="列出 Bridge 可吊销 Worker 令牌（脱敏）")
async def list_agentteams_worker_tokens(
    _admin: AdminRequired,
    service: BridgeServiceDep,
) -> dict:
    runtime = await service.get_runtime_config()
    items = await AgentTeamsService(get_settings(), runtime).admin_list_worker_tokens()
    return {"items": items}


@router.post("/agentteams-bridge/worker-tokens", summary="签发可吊销的 per-worker Bridge 令牌")
async def issue_agentteams_worker_token(
    request: AgentTeamsWorkerTokenIssueDTO,
    db: DbSession,
    _admin_id: AdminRequired,
    x_totp_code: Annotated[str | None, Header(alias="X-TOTP-Code")] = None,
) -> dict:
    """Proxy token issuance to the Bridge; the raw token is returned exactly once."""
    await require_admin_totp(_admin_id, db, x_totp_code)
    runtime = await AgentTeamsBridgeSettingsService(db, get_settings()).get_runtime_config()
    return await AgentTeamsService(get_settings(), runtime).admin_issue_worker_token(
        identity=request.identity, ttl_seconds=request.ttl_seconds, note=request.note
    )


@router.delete(
    "/agentteams-bridge/worker-tokens/{token_id}", summary="吊销指定 Bridge Worker 令牌"
)
async def revoke_agentteams_worker_token(
    token_id: str,
    db: DbSession,
    _admin_id: AdminRequired,
    x_totp_code: Annotated[str | None, Header(alias="X-TOTP-Code")] = None,
) -> dict:
    await require_admin_totp(_admin_id, db, x_totp_code)
    runtime = await AgentTeamsBridgeSettingsService(db, get_settings()).get_runtime_config()
    return await AgentTeamsService(get_settings(), runtime).admin_revoke_worker_token(token_id)
