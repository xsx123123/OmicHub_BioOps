"""AI Provider YAML 配置加载器

支持从外置 YAML 文件同步 Provider 配置到数据库，便于 Docker / GitOps 部署。
YAML 中可使用 ${ENV_VAR} 或 ${ENV_VAR:-default} 语法引用环境变量。

YAML 为单一事实源：启动同步时未声明的 provider 停用（见 load_and_sync 末尾 prune）。
网页端改完由 AIProviderYamlWriter 回写本文件，形成 yaml↔DB 双向闭环。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.ai_provider_yaml_shared import (
    interpolate_env,
)
from cygnusx.core.config import get_settings
from cygnusx.domain.ai_provider.entities import AIProviderConfig
from cygnusx.domain.ai_provider.value_objects import ProviderType
from cygnusx.infrastructure.database.repositories.ai_provider_repository import (
    SqlAlchemyAIProviderConfigRepository,
)


def _opt_float(value: Any) -> float | None:
    """YAML 字段转可选 float：None 原样保留，否则转 float。"""
    return None if value is None else float(value)


def _load_yaml(path: str) -> dict[str, Any]:
    """读取并解析 YAML，返回 providers 列表"""
    file_path = Path(path)
    if not file_path.exists():
        return {"providers": []}

    with open(file_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return cast(dict[str, Any], interpolate_env(raw))


class AIProviderYamlLoader:
    """将 YAML 中的 Provider 配置同步到数据库"""

    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = SqlAlchemyAIProviderConfigRepository(db)

    async def load_and_sync(self) -> int:
        """加载 YAML 并同步，返回同步的 Provider 数量"""
        settings = get_settings()
        path = settings.ai_provider_config_yaml

        data = _load_yaml(path)
        providers = data.get("providers", [])
        if not providers:
            logger.debug(f"AI Provider YAML 未配置或为空: {path}")
            return 0

        # uvicorn 多 worker 会并发执行启动同步；本函数是"先查再插"的 check-then-act，
        # 并发下会对不存在的 name 重复 INSERT。用 PG 事务级咨询锁串行化：
        # 后到的 worker 等前者提交后再读，看到的即是已同步状态，只更新不新建。
        # 锁随会话上下文退出（commit/rollback）自动释放。
        from sqlalchemy import text

        await self._db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('cygnusx_ai_provider_yaml_sync'))")
        )

        existing = {c.name: c for c in await self._repo.list_all()}
        synced = 0
        default_name: str | None = None

        for item in providers:
            name = item.get("name", "")
            if not name:
                logger.warning("YAML 中存在未命名的 AI Provider，已跳过")
                continue

            is_default = bool(item.get("is_default", False))
            if is_default:
                default_name = name

            provider_type = ProviderType(
                item.get("provider_type", ProviderType.OPENAI_COMPATIBLE.value)
            )

            base = existing.get(name)
            # 统一构造聚合根（已有则保留 id 以触发 update，否则新建），
            # 再经 repo.save 完成实体→ORM 模型转换并持久化。
            config = AIProviderConfig(
                id=base.id if base else uuid4(),
                name=name,
                provider_type=provider_type,
                model=item.get("model", base.model if base else ""),
                base_url=item.get("base_url", base.base_url if base else ""),
                api_key=item.get("api_key") or (base.api_key if base else ""),
                temperature=float(item.get("temperature", base.temperature if base else 0.7)),
                max_tokens=int(item.get("max_tokens", base.max_tokens if base else 2048)),
                top_p=float(item.get("top_p", base.top_p if base else 1.0)),
                timeout=int(item.get("timeout", base.timeout if base else 120)),
                input_price=_opt_float(item.get("input_price", base.input_price if base else None)),
                output_price=_opt_float(item.get("output_price", base.output_price if base else None)),
                input_cache_price=_opt_float(item.get("input_cache_price", base.input_cache_price if base else None)),
                output_cache_price=_opt_float(item.get("output_cache_price", base.output_cache_price if base else None)),
                is_active=bool(item.get("is_active", base.is_active if base else True)),
                is_default=is_default,
                extra_params=item.get("extra_params", base.extra_params if base else {}),
            )
            await self._repo.save(config)
            synced += 1
            logger.info(f"已同步 AI Provider: {name}")

        # 默认配置管理：YAML 声明优先；否则在无任何默认时取首个 active 兜底。
        configs = await self._repo.list_all()
        if default_name:
            target = next((c for c in configs if c.name == default_name), None)
            if target:
                await self._repo.set_default(target.id)
        elif configs and not any(c.is_default for c in configs):
            active = [c for c in configs if c.is_active]
            if active:
                await self._repo.set_default(active[0].id)
                logger.info(f"自动将 {active[0].name} 设为默认 AI Provider")

        # YAML 为单一事实源：YAML 里未声明的 provider 一律停用（不物理删除，避免
        # 会话/Agent 外键级联问题）。被引用的保留行便于历史回溯，不再出现在可选模型。
        declared_names = {item.get("name", "") for item in providers if item.get("name")}
        deactivated = 0
        for c in await self._repo.list_all():
            if c.name not in declared_names and c.is_active:
                c.is_active = False
                c.mark_updated()
                await self._repo.save(c)
                deactivated += 1
                logger.info(f"YAML 未声明，已停用 AI Provider: {c.name}")
        if deactivated:
            logger.info(f"YAML 同步共停用 {deactivated} 个未声明 Provider")

        return synced
