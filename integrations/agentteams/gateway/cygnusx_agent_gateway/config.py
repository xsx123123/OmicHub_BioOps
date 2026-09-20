"""Runtime settings for the isolated Agent Gateway."""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 平台用户动态 Matrix 账号前缀：主后端与 bridge 按同一规则生成
# ``cygnusx-user-<sanitized user_id>``，此处与两侧保持同一字符串。
MATRIX_USER_IDENTITY_PREFIX = "cygnusx-user-"
_MATRIX_LOCALPART_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._=-")


def _is_matrix_localpart(value: str) -> bool:
    return bool(value) and len(value) <= 255 and all(ch in _MATRIX_LOCALPART_CHARS for ch in value)


class GatewaySettings(BaseSettings):
    """Gateway-only configuration; no database, shell, or filesystem credentials are accepted."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="GATEWAY_", extra="ignore")

    environment: str = "development"
    cygnusx_base_url: str = "http://cygnusx-api:8000"
    cygnusx_consultation_path: str = "/api/v1/agent-teams/consultations/scientific-interpretation"
    cygnusx_service_token: str = ""
    cygnusx_api_key: str = ""
    cygnusx_integration_token: str = ""
    identities: str = "bioops-manager:manager-secret"
    matrix_homeserver_url: str = ""
    matrix_service_token: str = ""
    matrix_server_name: str = "localhost"
    # 浏览器/Element 可达的 Matrix C-S 公网地址；未配置时回退 matrix_homeserver_url。
    matrix_public_base_url: str = ""
    matrix_identities: str = (
        "bioops-manager=@bioops-manager:localhost,cygnusx-user=@cygnusx-user:localhost"
    )
    matrix_request_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    matrix_sync_timeout_ms: int = Field(default=25_000, ge=1_000, le=60_000)
    element_base_url: str = ""
    request_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    max_calls_per_case: int = Field(default=5, ge=1, le=100)
    max_tokens_per_case: int = Field(default=200_000, ge=1, le=2_000_000)
    state_store_url: str = ""
    state_store_key_prefix: str = "cygnusx:agentteams:gateway"
    audit_log_path: str = "/tmp/cygnusx-agent-gateway-audit.jsonl"
    agent_policies: str = (
        "agent-rnaseq|interpretation,planning_advice,result_interpretation,qc_advice,workspace_execution|"
        "ensembl.lookup_gene,ensembl.search_genes,task_result_summary,task_file_preview,workspace_file_preview,workspace_read_file,task_compare_metrics,rule_threshold_lookup;"
        "agent-scrna|interpretation,planning_advice,result_interpretation,qc_advice,workspace_execution|"
        "ensembl.lookup_gene,ensembl.search_genes,task_result_summary,task_file_preview,workspace_file_preview,workspace_read_file,task_compare_metrics,rule_threshold_lookup;"
        "agent-viz|interpretation,result_interpretation,qc_advice,workspace_execution|"
        "ensembl.lookup_gene,ensembl.search_genes,task_result_summary,task_file_preview,workspace_file_preview,workspace_read_file,task_compare_metrics,rule_threshold_lookup;"
        "agent-code|interpretation,planning_advice,result_interpretation,qc_advice,workspace_execution|"
        "ensembl.lookup_gene,ensembl.search_genes,task_result_summary,task_file_preview,workspace_file_preview,workspace_read_file,task_compare_metrics,rule_threshold_lookup;"
        "agent-data|project-preflight,workspace_execution|task_result_summary,task_file_preview,workspace_file_preview,workspace_read_file,task_compare_metrics,rule_threshold_lookup;"
        "agent-qc|quality-gate,workspace_execution|task_result_summary,task_file_preview,workspace_file_preview,workspace_read_file,task_compare_metrics,rule_threshold_lookup;"
        "agent-delivery|delivery-pack,workspace_execution|task_result_summary,task_file_preview,workspace_file_preview,workspace_read_file,task_compare_metrics,rule_threshold_lookup"
    )
    discovered_agent_policies: dict[str, tuple[set[str], set[str]]] = Field(
        default_factory=dict, exclude=True
    )

    @model_validator(mode="after")
    def validate_production_secrets(self) -> GatewaySettings:
        if self.environment != "production":
            return self
        if self._is_placeholder(self.cygnusx_integration_token):
            raise ValueError("生产环境必须配置 CygnusX 集成令牌")
        identities = self.identity_secrets()
        if not identities or any(self._is_placeholder(secret) for secret in identities.values()):
            raise ValueError("生产环境必须替换 Gateway 身份凭证")
        if not self.agent_policy_map():
            raise ValueError("生产环境必须配置专业 Agent 白名单")
        if not self.state_store_url:
            raise ValueError("生产环境必须配置 Redis 共享状态存储")
        if bool(self.matrix_homeserver_url) != bool(self.matrix_service_token):
            raise ValueError("Matrix homeserver URL 与服务账号令牌必须同时配置")
        if self.matrix_homeserver_url and self._is_placeholder(self.matrix_service_token):
            raise ValueError("生产环境必须替换 Matrix 服务账号令牌")
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

    def agent_policy_map(self) -> dict[str, tuple[set[str], set[str]]]:
        policies: dict[str, tuple[set[str], set[str]]] = {}
        for entry in self.agent_policies.split(";"):
            agent_id, separator, rules = entry.strip().partition("|")
            capabilities, separator2, tools = rules.partition("|") if separator else ("", "", "")
            if not agent_id or not separator or not separator2:
                continue
            policies[agent_id] = (
                {value.strip() for value in capabilities.split(",") if value.strip()},
                {value.strip() for value in tools.split(",") if value.strip()},
            )
        return {**policies, **self.discovered_agent_policies}

    def apply_capability_snapshot(self, payload: dict) -> None:
        capabilities = payload.get("agent_capabilities")
        if not isinstance(capabilities, dict):
            return
        evidence_tools = {
            "task_result_summary",
            "task_file_preview",
            "workspace_file_preview",
            "workspace_read_file",
            "task_compare_metrics",
            "rule_threshold_lookup",
        }
        discovered: dict[str, tuple[set[str], set[str]]] = {}
        for item in capabilities.values():
            if not isinstance(item, dict) or not item.get("recruitable"):
                continue
            agent_id = str(item.get("agent_id") or "").strip()
            if not agent_id:
                continue
            capability = str(item.get("worker_capability") or "interpretation").strip()
            allowed = {capability}
            if item.get("planner_eligible"):
                allowed.add("planning_advice")
            if item.get("execution_modes") and "workspace_execution" in item["execution_modes"]:
                allowed.add("workspace_execution")
            discovered[agent_id] = (allowed, set(evidence_tools))
        self.discovered_agent_policies = discovered

    @property
    def matrix_enabled(self) -> bool:
        return bool(self.matrix_homeserver_url.strip() and self.matrix_service_token.strip())

    @property
    def matrix_public_url(self) -> str:
        """浏览器侧可达的 Matrix C-S 地址；未单独配置时回退内网 homeserver 地址。"""
        return self.matrix_public_base_url.strip() or self.matrix_homeserver_url.strip()

    def matrix_identity_map(self) -> dict[str, str]:
        entries = (entry.strip() for entry in self.matrix_identities.split(","))
        return {
            identity.strip(): matrix_user.strip()
            for entry in entries
            if "=" in entry
            for identity, matrix_user in [entry.split("=", maxsplit=1)]
            if identity.strip() and matrix_user.strip()
        }

    def matrix_identity_by_user(self) -> dict[str, str]:
        return {
            matrix_user: identity for identity, matrix_user in self.matrix_identity_map().items()
        }

    def matrix_user_for_identity(self, identity: str) -> str | None:
        """Resolve an CygnusX identity to a Matrix user ID.

        Static ``matrix_identities`` mappings win; otherwise per-platform-user
        identities (``cygnusx-user-<slug>``，主后端/bridge 侧同一映射规则生成）
        按 ``@{identity}:{matrix_server_name}`` 动态推导，使平台用户无需逐一
        写入静态配置即可供给 Matrix 账号。
        """
        identity = identity.strip()
        if not identity:
            return None
        static = self.matrix_identity_map().get(identity)
        if static:
            return static
        if (
            identity.startswith(MATRIX_USER_IDENTITY_PREFIX)
            and len(identity) > len(MATRIX_USER_IDENTITY_PREFIX)
            and _is_matrix_localpart(identity)
        ):
            server_name = self.matrix_server_name.strip()
            if server_name:
                return f"@{identity}:{server_name}"
        return None

    def matrix_identity_by_user_dynamic(self, matrix_user: str) -> str | None:
        """Reverse of :meth:`matrix_user_for_identity` for inbound sync events."""
        static = self.matrix_identity_by_user().get(matrix_user)
        if static:
            return static
        localpart, separator, server = matrix_user.removeprefix("@").partition(":")
        if (
            separator
            and server == self.matrix_server_name.strip()
            and localpart.startswith(MATRIX_USER_IDENTITY_PREFIX)
            and _is_matrix_localpart(localpart)
        ):
            return localpart
        return None
