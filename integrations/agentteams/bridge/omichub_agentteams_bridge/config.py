"""Runtime configuration for the isolated Bridge service."""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BridgeSettings(BaseSettings):
    """Only Bridge-owned configuration is accepted here; no database credentials."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="BRIDGE_", extra="ignore")

    environment: str = "development"
    omichub_base_url: str = "http://omichub-api:8000"
    omichub_service_token: str = ""
    omichub_api_key: str = ""
    omichub_integration_token: str = ""
    gateway_url: str = ""
    gateway_manager_token: str = ""
    role_agent_map: str = ""
    discovered_flow_agent_map: dict[str, str] = Field(default_factory=dict, exclude=True)
    discovered_flow_quality_gate_map: dict[str, bool] = Field(default_factory=dict, exclude=True)
    discovered_role_agent_map: dict[str, str] = Field(default_factory=dict, exclude=True)
    discovered_worker_profiles: dict[str, dict[str, str]] = Field(
        default_factory=dict, exclude=True
    )
    discovered_workspace_execution_identities: set[str] = Field(default_factory=set, exclude=True)
    approval_signing_secret: str = "change-me-before-deployment"
    identities: str = (
        "approval-authority:approval-secret,bioops-manager:manager-secret,data-steward:steward-secret,"
        "workflow-operator:operator-secret,quality-auditor:auditor-secret,"
        "delivery-reporter:reporter-secret,agent-code:code-secret,agent-viz:viz-secret,"
        "agent-scrna:scrna-secret,agent-rnaseq:rnaseq-secret,analysis-worker:analysis-secret"
    )
    allowed_flow_ids: str = "rna_seq,scrna_seq"
    request_timeout_seconds: float = 20.0
    max_request_bytes: int = Field(default=1_048_576, ge=1_024, le=16_777_216)
    max_response_bytes: int = Field(default=1_048_576, ge=1_024, le=16_777_216)
    max_evidence_bytes: int = 16_384
    worker_heartbeat_ttl_seconds: int = Field(default=180, ge=30, le=3_600)
    omic_task_stall_timeout_seconds: int = Field(default=900, ge=30, le=86_400)
    planning_timeout_seconds: int = Field(default=120, ge=10, le=86_400)
    execution_timeout_seconds: int = Field(default=600, ge=60, le=86_400)
    max_active_cases_per_requester: int = Field(default=3, ge=1, le=100)
    max_active_cases_per_project: int = Field(default=5, ge=1, le=100)
    max_active_work_items_per_case: int = Field(default=8, ge=1, le=500)
    case_gc_days: int = Field(default=7, ge=0, le=3650)
    state_store_url: str = ""
    state_store_key_prefix: str = "omichub:agentteams"
    audit_log_path: str = "/tmp/omichub-agentteams-bridge-audit.jsonl"
    case_store_path: str = "/tmp/omichub-agentteams-bridge-cases.json"
    worker_token_store_path: str = "/tmp/omichub-agentteams-bridge-worker-tokens.json"
    manifest_dir: str = "/tmp/omichub-agentteams-bridge-manifests"

    @model_validator(mode="after")
    def validate_production_secrets(self) -> BridgeSettings:
        if self.environment != "production":
            return self
        default_values = {
            "approval_signing_secret": "change-me-before-deployment",
            "identities": (
                "approval-authority:approval-secret,bioops-manager:manager-secret,data-steward:steward-secret,"
                "workflow-operator:operator-secret,quality-auditor:auditor-secret,"
                "delivery-reporter:reporter-secret,agent-code:code-secret,agent-viz:viz-secret,"
                "agent-scrna:scrna-secret,agent-rnaseq:rnaseq-secret,analysis-worker:analysis-secret"
            ),
        }
        configured_upstream_credentials = [
            value
            for value in (self.omichub_service_token, self.omichub_api_key)
            if not self._is_placeholder(value)
        ]
        if not configured_upstream_credentials:
            raise ValueError("生产环境必须设置 OmicHub 受限服务令牌或 API Key")
        if len(configured_upstream_credentials) > 1:
            raise ValueError("生产环境只能配置一种 OmicHub 上游认证方式")
        if self._is_placeholder(self.approval_signing_secret):
            raise ValueError("生产环境必须替换审批签名密钥")
        identity_secrets = self.identity_secrets()
        if (
            self.identities == default_values["identities"]
            or not identity_secrets
            or any(self._is_placeholder(secret) for secret in identity_secrets.values())
        ):
            raise ValueError("生产环境必须替换 Bridge 身份凭证")
        if bool(self.gateway_url) != bool(self.gateway_manager_token):
            raise ValueError("生产环境 Gateway URL 与 Manager token 必须同时配置")
        if self.gateway_url and self._is_placeholder(self.gateway_manager_token):
            raise ValueError("生产环境必须替换 Gateway Manager token")
        if not self.state_store_url:
            raise ValueError("生产环境必须配置 Redis 共享状态存储")
        return self

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        normalized = value.strip().lower()
        return (
            not normalized
            or normalized.startswith("replace-")
            or normalized.startswith("change-me")
        )

    def identity_secrets(self) -> dict[str, str]:
        entries = (entry.strip() for entry in self.identities.split(","))
        return {
            identity.strip(): secret.strip()
            for entry in entries
            if ":" in entry
            for identity, secret in [entry.split(":", maxsplit=1)]
            if identity.strip() and secret.strip()
        }

    def allowed_flows(self) -> set[str]:
        return {flow_id.strip() for flow_id in self.allowed_flow_ids.split(",") if flow_id.strip()}

    def role_agent_mapping(self) -> dict[str, str]:
        configured = {
            role.strip(): agent_id.strip()
            for entry in self.role_agent_map.split(",")
            if ":" in entry
            for role, agent_id in [entry.split(":", maxsplit=1)]
            if role.strip() and agent_id.strip()
        }
        return {**self.discovered_role_agent_map, **configured}

    def apply_capability_snapshot(self, payload: dict) -> None:
        flows = payload.get("allowed_flow_ids")
        flow_agent_map = payload.get("flow_agent_map")
        flow_quality_gate_map = payload.get("flow_quality_gate_map")
        role_map = payload.get("role_agent_map")
        worker_profiles = payload.get("worker_profiles")
        if isinstance(flows, list):
            self.allowed_flow_ids = ",".join(str(item) for item in flows if str(item).strip())
        if isinstance(flow_agent_map, dict):
            self.discovered_flow_agent_map = {
                str(flow_id): str(agent_id)
                for flow_id, agent_id in flow_agent_map.items()
                if str(flow_id).strip() and str(agent_id).strip()
            }
        if isinstance(flow_quality_gate_map, dict):
            self.discovered_flow_quality_gate_map = {
                str(flow_id): bool(required)
                for flow_id, required in flow_quality_gate_map.items()
                if str(flow_id).strip()
            }
        if isinstance(role_map, dict):
            self.discovered_role_agent_map = {
                str(role): str(agent_id)
                for role, agent_id in role_map.items()
                if str(role).strip() and str(agent_id).strip()
            }
        if isinstance(worker_profiles, dict):
            self.discovered_worker_profiles = {
                str(identity): {
                    "identity": str(profile.get("identity") or identity),
                    "agent_id": str(profile.get("agent_id") or ""),
                    "capability": str(profile.get("capability") or ""),
                }
                for identity, profile in worker_profiles.items()
                if isinstance(profile, dict)
                and str(profile.get("agent_id") or "").strip()
                and str(profile.get("capability") or "").strip()
            }
        agent_capabilities = payload.get("agent_capabilities")
        if isinstance(agent_capabilities, dict):
            allowed_agent_ids = {
                str(item.get("agent_id") or "").strip()
                for item in agent_capabilities.values()
                if isinstance(item, dict)
                and "workspace_execution"
                in [str(mode) for mode in (item.get("execution_modes") or [])]
            }
            allowed_agent_ids.discard("")
            # role_agent_map covers canonical roles plus aliases (e.g. data-steward),
            # so alias identities inherit the canonical agent's declaration.
            self.discovered_workspace_execution_identities = {
                identity
                for identity, agent_id in self.discovered_role_agent_map.items()
                if agent_id in allowed_agent_ids
            }

    def quality_gate_for_flow(self, flow_id: str) -> bool:
        return bool(self.discovered_flow_quality_gate_map.get(flow_id, False))
