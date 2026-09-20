"""Runtime configuration for the isolated Bridge service."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BridgeSettings(BaseSettings):
    """Only Bridge-owned configuration is accepted here; no database credentials."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="BRIDGE_", extra="ignore")

    environment: str = "development"
    build_sha: str = "unknown"
    build_time: str = "unknown"
    cygnusx_base_url: str = "http://cygnusx-api:8000"
    cygnusx_service_token: str = ""
    cygnusx_api_key: str = ""
    cygnusx_integration_token: str = ""
    gateway_url: str = ""
    gateway_manager_token: str = ""
    role_agent_map: str = ""
    discovered_flow_agent_map: dict[str, str] = Field(default_factory=dict, exclude=True)
    discovered_flow_quality_gate_map: dict[str, bool] = Field(default_factory=dict, exclude=True)
    discovered_flow_standard_work_items: dict[str, dict[str, str]] = Field(
        default_factory=dict, exclude=True
    )
    discovered_role_agent_map: dict[str, str] = Field(default_factory=dict, exclude=True)
    discovered_worker_profiles: dict[str, dict[str, str]] = Field(
        default_factory=dict, exclude=True
    )
    discovered_workspace_execution_identities: set[str] = Field(default_factory=set, exclude=True)
    discovered_agent_personas: dict[str, dict[str, Any]] = Field(default_factory=dict, exclude=True)
    approval_signing_secret: str = "change-me-before-deployment"
    identities: str = (
        "approval-authority:approval-secret,bioops-manager:manager-secret,data-steward:steward-secret,"
        "workflow-operator:operator-secret,quality-auditor:auditor-secret,"
        "delivery-reporter:reporter-secret,agent-code:code-secret,agent-viz:viz-secret,"
        "agent-scrna:scrna-secret,agent-rnaseq:rnaseq-secret,analysis-worker:analysis-secret"
    )
    allowed_flow_ids: str = "rna_seq,scrna_seq"
    # 依据: 待测（经验初值）— Bridge 调用 CygnusX 上游的单次上限；验证: 采集上游响应 P95 后校准
    request_timeout_seconds: float = 20.0
    # 依据: 待测（经验初值）— 1MiB 覆盖立项/计划 JSON 正常体积；验证: 监控超界拒绝日志再调整
    max_request_bytes: int = Field(default=1_048_576, ge=1_024, le=16_777_216)
    # 依据: 待测（经验初值）— 同上，响应侧对称口径
    max_response_bytes: int = Field(default=1_048_576, ge=1_024, le=16_777_216)
    # 依据: 待测（经验初值）— 单条证据摘要上限 16KiB；验证: 统计真实证据字段长度分布
    max_evidence_bytes: int = 16_384
    # 依据: 待测（经验初值）— Worker 失联判定（语义见 docs/configuration/多Agent协作配置指南.md:50）；
    # 验证: 以 Worker inbox 轮询周期 ×3 为基线，观察 sweep 误回收率
    worker_heartbeat_ttl_seconds: int = Field(default=180, ge=30, le=3_600)
    # 依据: 待测（经验初值）— 失联租约清扫节拍，应远小于 heartbeat TTL(180s)；验证: 失联到回收的实测延迟
    work_item_sweep_interval_seconds: int = Field(default=30, ge=0, le=3_600)
    # 依据: 待测（经验初值）— Omic 任务无进展看门狗；验证: evidence/e2e-2026-08-21/E2E-1
    # 曾观测 preflight 卡死 17min+ 未被终止，需复测触发正确性
    omic_task_stall_timeout_seconds: int = Field(default=900, ge=30, le=86_400)
    # 依据: 待测（经验初值）— 验证: E2E-1 规划段（含 3 轮校验自愈）真实耗时可作校准样本
    planning_timeout_seconds: int = Field(default=120, ge=10, le=86_400)
    # 依据: 待测（经验初值）— 单工作项执行上限；验证: 统计真实执行耗时分位数后校准
    execution_timeout_seconds: int = Field(default=600, ge=60, le=86_400)
    # 依据: 待测（经验初值）— 容量护栏，防止单请求者占满 Worker 池；验证: 压测并发 Case 与池容量
    max_active_cases_per_requester: int = Field(default=3, ge=1, le=100)
    # 依据: 待测（经验初值）— 同上，项目维度护栏
    max_active_cases_per_project: int = Field(default=5, ge=1, le=100)
    # 依据: 待测（经验初值）— 单 Case 工作项并发护栏；验证: 压测单 Case 扇出对状态存储的压力
    max_active_work_items_per_case: int = Field(default=8, ge=1, le=500)
    case_gc_days: int = Field(default=7, ge=0, le=3650)  # 依据: 待测（经验初值）— 与平台证据保留 30 天口径的关系待明确；验证: 观察 GC 前是否有审计回放需求
    # 依据: 口径文档 docs/info/26.8.21/协作室房间事件GC与归档口径.md §2 — 建议默认 N=30 天，
    # 以最后一条 business 事件 recorded_at 判定活动（operational/stream 不算）；0=禁用自动归档。
    # 验证: 以 room_events__room-<id> 指标观察房间事件量增长，校准归档窗口
    room_archive_days: int = Field(default=30, ge=0, le=3650)
    state_store_url: str = ""
    state_store_key_prefix: str = "cygnusx:agentteams"
    audit_stream_maxlen: int = Field(default=20_000, ge=1_000, le=10_000_000)
    audit_log_path: str = "/tmp/cygnusx-agentteams-bridge-audit.jsonl"
    case_store_path: str = "/tmp/cygnusx-agentteams-bridge-cases.json"
    # MinIO 持久层（事实源）；未配置时非生产环境回退 Redis/本地文件模式并打 warning。
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "agentteams"
    minio_secure: bool = False
    # 依据: 上游契约 — 设计文档 docs/info/26.8.21/协作室架构升级方案-MinIO持久化与Case解耦及L4前置收尾.md:70
    # 建议 50MB 分卷阈值；minio_store.py 追加为读-改-写尾卷，阈值即单卷整载内存上限
    minio_event_object_max_bytes: int = Field(default=52_428_800, ge=1_048_576)
    worker_token_store_path: str = "/tmp/cygnusx-agentteams-bridge-worker-tokens.json"
    manifest_dir: str = "/tmp/cygnusx-agentteams-bridge-manifests"

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
            for value in (self.cygnusx_service_token, self.cygnusx_api_key)
            if not self._is_placeholder(value)
        ]
        if not configured_upstream_credentials:
            raise ValueError("生产环境必须设置 CygnusX 受限服务令牌或 API Key")
        if len(configured_upstream_credentials) > 1:
            raise ValueError("生产环境只能配置一种 CygnusX 上游认证方式")
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
        if not self.minio_endpoint:
            raise ValueError("生产环境必须配置 MinIO 持久层（BRIDGE_MINIO_ENDPOINT）")
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
        standard_work_items = payload.get("flow_standard_work_items")
        if isinstance(standard_work_items, dict):
            self.discovered_flow_standard_work_items = {
                str(flow_id): {
                    str(kind): str(target)
                    for kind, target in targets.items()
                    if str(kind).strip() and str(target).strip()
                }
                for flow_id, targets in standard_work_items.items()
                if str(flow_id).strip() and isinstance(targets, dict)
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
            # persona 仅作展示用途(状态文案/成员副标题),不参与任何权限判定
            self.discovered_agent_personas = {
                str(item.get("agent_id") or "").strip(): item["persona"]
                for item in agent_capabilities.values()
                if isinstance(item, dict)
                and str(item.get("agent_id") or "").strip()
                and isinstance(item.get("persona"), dict)
            }

    def persona_status_line_for(self, agent_id: str, phase: str) -> str | None:
        """按 agent_id 取该状态阶段的人格播报文案;未配置返回 None。"""
        persona = self.discovered_agent_personas.get(agent_id) or {}
        lines = persona.get("status_lines")
        if not isinstance(lines, dict):
            return None
        candidates = lines.get(phase)
        if isinstance(candidates, str) and candidates.strip():
            return candidates.strip()
        if isinstance(candidates, list):
            for item in candidates:
                if str(item).strip():
                    return str(item).strip()
        return None

    def quality_gate_for_flow(self, flow_id: str) -> bool:
        return bool(self.discovered_flow_quality_gate_map.get(flow_id, False))

    def standard_work_item_target(self, flow_id: str, kind: str) -> str | None:
        """O5:流程 YAML 显式声明的标准工作项 target;未声明返回 None(走缺省)。"""
        targets = self.discovered_flow_standard_work_items.get(flow_id) or {}
        target = str(targets.get(kind) or "").strip()
        return target or None
