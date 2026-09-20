"""任务分析运行时镜像注册表与能力匹配。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cygnusx.core.config import get_settings


class RuntimeResources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu: float = Field(default=1, gt=0)
    memory: str = "2g"
    pids: int = Field(default=512, ge=64)


class RuntimeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    image: str
    family: str
    isolation_class: str
    runtime_uid: int = Field(default=10001, ge=10000)
    runtime_gid: int = Field(default=10001, ge=10000)
    runtime_group: str = "cygnusx-sandbox"
    dockerfile: str
    extends: str | None = None
    executor_compatibility: set[Literal["studio", "toolbox"]] = Field(default_factory=set)
    description: str
    capabilities: set[str] = Field(default_factory=set)
    task_tags: set[str] = Field(default_factory=set)
    languages: dict[str, str] = Field(default_factory=dict)
    software: dict[str, str] = Field(default_factory=dict)
    resources: RuntimeResources = Field(default_factory=RuntimeResources)
    network_policy: Literal["none", "whitelist"] = "none"

    @field_validator(
        "image", "family", "isolation_class", "dockerfile", "runtime_group"
    )
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value.strip()


class RuntimeSelection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    default_profile: str = "analysis-core"
    strategy: Literal["capability_match", "explicit"] = "capability_match"
    reject_unknown_profile: bool = True
    prefer_smallest_satisfying_image: bool = True


class RuntimeImageRegistryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: int = 1
    selection: RuntimeSelection = Field(default_factory=RuntimeSelection)
    profiles: dict[str, RuntimeProfile] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> RuntimeImageRegistryConfig:
        if self.selection.default_profile not in self.profiles:
            raise ValueError("default_profile 必须引用已注册 profile")
        for profile_id, profile in self.profiles.items():
            if profile.extends and profile.extends not in self.profiles:
                raise ValueError(f"{profile_id}.extends 引用了未知 profile")
        return self

    def resolved_profile(self, profile_id: str) -> RuntimeProfile:
        profile = self.profiles[profile_id]
        if not profile.extends:
            return profile
        parent = self.resolved_profile(profile.extends)
        data = parent.model_dump()
        child = profile.model_dump(exclude_unset=True)
        for key in ("capabilities", "task_tags", "executor_compatibility"):
            child[key] = set(data.get(key, set())) | set(child.get(key, set()))
        for key in ("languages", "software"):
            child[key] = {**data.get(key, {}), **child.get(key, {})}
        data.update(child)
        return RuntimeProfile(**data)

    def select(
        self,
        required_capabilities: set[str],
        executor: Literal["studio", "toolbox"],
        preferred_profile: str | None = None,
    ) -> tuple[str, RuntimeProfile]:
        """选择运行时画像。

        ``preferred_profile`` 表示调用方已经明确指定了画像，必须严格校验能力和
        executor，不得静默改选其它 profile。没有 preferred profile 时才走能力匹配，
        并按最小满足集合选择；调用方负责决定这是不是用户显式的能力覆盖。

        这里不负责读取 Agent YAML，也不应把 ``default_profile`` 当成每个 Agent 的
        默认值。若要改变严格校验、能力匹配或兜底语义，先向用户询问，因为这会
        影响 Studio、工具箱以及所有未固定 runtime_profile 的任务。
        """
        if preferred_profile:
            if preferred_profile not in self.profiles:
                raise KeyError(f"未知运行时 profile: {preferred_profile}")
            resolved = self.resolved_profile(preferred_profile)
            if executor not in resolved.executor_compatibility:
                raise ValueError(f"运行时 {preferred_profile} 不支持执行器 {executor}")
            missing = required_capabilities - resolved.capabilities
            if missing:
                raise ValueError(f"运行时 {preferred_profile} 缺少能力: {sorted(missing)}")
            return preferred_profile, resolved
        candidates: list[tuple[str, RuntimeProfile]] = []
        for profile_id in self.profiles:
            resolved = self.resolved_profile(profile_id)
            if executor in resolved.executor_compatibility and required_capabilities <= resolved.capabilities:
                candidates.append((profile_id, resolved))
        if not candidates:
            raise LookupError(f"没有运行时满足能力: {sorted(required_capabilities)}")
        candidates.sort(key=lambda item: (len(item[1].capabilities), item[0]))
        return candidates[0]

    def profile_for_image(self, image: str) -> tuple[str, RuntimeProfile] | None:
        """按实际镜像名反查已注册的解析后运行时 profile。"""
        for profile_id in self.profiles:
            profile = self.resolved_profile(profile_id)
            if profile.image == image:
                return profile_id, profile
        return None


def render_runtime_manifest(profile_id: str, profile: RuntimeProfile) -> str:
    """渲染可注入 Agent 系统提示词的当前运行时软件清单。"""
    languages = ", ".join(
        f"{name} {version}" for name, version in sorted(profile.languages.items())
    ) or "未声明"
    software = ", ".join(
        f"{name} ({version})" if version and version != "installed" else name
        for name, version in sorted(profile.software.items())
    ) or "未声明"
    capabilities = ", ".join(sorted(profile.capabilities)) or "未声明"
    return (
        "## 当前 Studio 运行时（镜像声明）\n"
        f"- Profile：`{profile_id}`\n"
        f"- 镜像：`{profile.image}`\n"
        f"- 语言：{languages}\n"
        f"- 能力：{capabilities}\n"
        f"- 已安装软件：{software}\n"
        "- 使用规则：上述是当前镜像的已声明软件；优先直接使用，不要重复安装。"
        "如果需要未列出的软件或验证实际版本，再在沙箱中检查。"
    )


def render_runtime_catalog(config: RuntimeImageRegistryConfig) -> str:
    """渲染可注入 Agent 提示词的动态运行时目录。"""
    lines = [
        "## 可用 Studio 运行时（由注册表动态注入）",
        "镜像选择以 `data/ai/runtime_images.yaml` 为准；新增 profile 后无需修改 Agent 提示词。",
    ]
    for profile_id in sorted(config.profiles):
        profile = config.resolved_profile(profile_id)
        capabilities = ", ".join(sorted(profile.capabilities)) or "未声明"
        lines.append(
            f"- `{profile_id}`：镜像 `{profile.image}`；能力：{capabilities}；"
            f"执行器：{', '.join(sorted(profile.executor_compatibility)) or '未声明'}"
        )
    return "\n".join(lines)


class RuntimeImageRegistryManager:
    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path or get_settings().runtime_images_yaml)
        self._config: RuntimeImageRegistryConfig | None = None
        self._mtime = -1.0

    def get_config(self) -> RuntimeImageRegistryConfig:
        try:
            mtime = self.config_path.stat().st_mtime
        except OSError as exc:
            raise RuntimeError(f"运行时镜像注册表不存在: {self.config_path}") from exc
        if self._config is not None and mtime <= self._mtime:
            return self._config
        try:
            raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
            self._config = RuntimeImageRegistryConfig(**raw)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            raise RuntimeError(f"运行时镜像注册表无效: {exc}") from exc
        self._mtime = mtime
        return self._config

    def reload(self) -> RuntimeImageRegistryConfig:
        self._config = None
        return self.get_config()


runtime_image_registry = RuntimeImageRegistryManager()


def get_runtime_images() -> RuntimeImageRegistryConfig:
    return runtime_image_registry.get_config()


def resolve_studio_image(studio_config: Mapping[str, Any] | None) -> str | None:
    """Resolve an Agent's declared Studio image without applying the global fallback.

    ``features.studio.image`` is the value persisted by :mod:`agent_loader` and is
    therefore preferred.  Older database rows may contain only
    ``features.studio.runtime_profile``; resolving that profile here keeps those rows
    on their Agent-specific image instead of silently sending them to
    ``selection.default_profile`` (currently ``analysis-core``).

    Returning ``None`` is intentional: it means the Agent has no Studio image
    declaration and lets the caller decide whether a global default is appropriate.
    This helper must not be changed to return ``analysis-core`` because that would
    erase the distinction between an explicit Agent runtime and the deployment-wide
    safety fallback.  Changes to this precedence require asking the user first.
    """
    config = studio_config or {}
    image = str(config.get("image") or "").strip()
    if image:
        return image
    profile_id = str(config.get("runtime_profile") or "").strip()
    if not profile_id:
        return None
    _, profile = get_runtime_images().select(
        set(), "studio", preferred_profile=profile_id
    )
    return profile.image
