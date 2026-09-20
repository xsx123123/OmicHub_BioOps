"""管理员登录欢迎词服务 —— 预生成 + 顺序轮询。

设计思路（避免运行时调 LLM 的 2~5s 延迟）：
1. **启动补齐**：服务启动时若 ``data/welcome.yaml`` 条数不足阈值，调用默认 AI provider
   （``data/ai/providers.yaml`` 中 ``is_default: true`` 的模型）预生成补齐。失败仅 log，不阻塞启动。
2. **运行时轮询**：登录时仅读盘 + 游标前进，返回下一条；20 条轮完一圈才重复。
   游标独立存 ``data/welcome_state.yaml``，避免污染生成结果；重启不丢。
3. **兜底**：两文件缺失/空列表/解析失败时，返回内置默认文案，保证登录必有弹窗。

读写风格仿 ``site_content_service``（磁盘读）与 ``ai_provider_yaml_loader``（safe_dump 写盘）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.ai_provider_service import AIProviderConfigService
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.ai_provider.litellm_provider import LiteLLMProvider
from cygnusx.infrastructure.config.prompt_loader import get_prompt

# 运行时兜底文案：welcome.yaml 缺失/空/损坏时使用，务必保证登录有弹窗
DEFAULT_WELCOME_TEXT = "晚上好，root 👋 欢迎使用 CygnusX！"

# 预生成用 system prompt —— 元气小助手人设，约束颜文字/语气/字数/随机性
WELCOME_SYSTEM_PROMPT = get_prompt("welcome.admin_system")

# 生成单条文案时的 user message（与 system prompt 配合，system 负责人设与约束）
WELCOME_USER_PROMPT = get_prompt("welcome.admin_user")


class WelcomeService:
    """管理员欢迎词服务：启动补齐 + 运行时顺序轮询。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        s = get_settings()
        self._messages_path = Path(s.welcome_yaml)
        self._state_path = Path(s.welcome_state_yaml)
        self._threshold = s.welcome_seed_threshold

    # ------------------------------------------------------------------ #
    # 启动补齐
    # ------------------------------------------------------------------ #

    async def seed_if_needed(self, threshold: int | None = None) -> int:
        """启动调用：welcome.yaml 条数 < threshold 时调默认 provider 补齐。

        返回补齐后的总条数。任何异常仅 log warning，不抛（不阻塞启动）。
        """
        target = threshold if threshold is not None else self._threshold
        messages = self._read_messages()
        current = len(messages)

        if current >= target:
            logger.debug(f"欢迎词已有 {current} 条 ≥ {target}，无需补齐")
            return current

        need = target - current
        logger.info(f"欢迎词仅 {current} 条，补齐 {need} 条至 {target}（调默认 AI provider）")

        default_config = await self._get_default_provider()
        if default_config is None:
            logger.warning("无可用默认 AI provider，跳过欢迎词补齐（运行时回退兜底文案）")
            return current

        provider = LiteLLMProvider(default_config)
        generated: list[str] = []
        for i in range(need):
            try:
                text = await self._generate_one(provider, default_config.temperature)
                if text:
                    generated.append(text)
            except Exception as e:  # noqa: BLE001
                # 单条失败不中断整体补齐，已生成的照常落盘
                logger.warning(f"第 {i + 1}/{need} 条欢迎词生成失败: {e}")
                break

        if generated:
            messages.extend(generated)
            self._write_messages(messages)
            logger.info(f"欢迎词补齐完成：新增 {len(generated)} 条，共 {len(messages)} 条")
        else:
            logger.warning("本次未生成任何欢迎词，保留现状（运行时回退兜底文案）")
        return len(messages)

    async def _get_default_provider(self):
        """取 is_default=true 且 is_active 的 AI provider 配置（领域实体）。"""
        return await AIProviderConfigService(self._db).get_active_default()

    async def _generate_one(self, provider: LiteLLMProvider, temperature: float) -> str:
        """调 LLM 生成单条欢迎词，返回清洗后的纯文本。"""
        response = await provider.chat(
            messages=[
                {"role": "system", "content": WELCOME_SYSTEM_PROMPT},
                {"role": "user", "content": WELCOME_USER_PROMPT},
            ],
            temperature=temperature,
        )
        return _extract_content(response)

    # ------------------------------------------------------------------ #
    # 运行时顺序轮询
    # ------------------------------------------------------------------ #

    def get_next_welcome(self) -> str:
        """返回下一条欢迎词，游标前进；文件缺失/空时回退兜底文案。

        非异步：运行时只读盘 + 写游标，无 IO 阻塞，开销 < 1ms 量级。

        游标策略：``welcome_state.yaml`` 存单调递增的绝对索引 ``next_index``，
        取模仅在返回时做（``next_index % len``），写入恒为 ``next_index + 1``。
        这样游标单调增长、20 条轮完一圈才重复，且条数变化时仍能正确取模。
        """
        messages = self._read_messages()
        if not messages:
            return DEFAULT_WELCOME_TEXT

        next_index = self._read_next_index()
        current = next_index % len(messages)
        self._write_next_index(next_index + 1)  # 单调递增，取模只在读取处做
        return messages[current]

    # ------------------------------------------------------------------ #
    # 磁盘读写（仿 site_content_service / ai_provider_yaml_loader 风格）
    # ------------------------------------------------------------------ #

    def _read_messages(self) -> list[str]:
        """读 welcome.yaml 的 messages 列表；缺失/损坏/非列表时返回空列表。"""
        if not self._messages_path.exists():
            return []
        try:
            with self._messages_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return []
        if not isinstance(data, dict):
            return []
        msgs = data.get("messages", [])
        return [str(m).strip() for m in msgs if isinstance(m, str) and m.strip()]

    def _write_messages(self, messages: list[str]) -> None:
        """覆盖写 welcome.yaml；ensure_ascii=False 保留颜文字。"""
        self._messages_path.parent.mkdir(parents=True, exist_ok=True)
        with self._messages_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump({"messages": messages}, f, allow_unicode=True, sort_keys=False)

    def _read_next_index(self) -> int:
        """读游标；缺失/损坏时返回 0（从头开始轮询）。"""
        if not self._state_path.exists():
            return 0
        try:
            with self._state_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return 0
        if not isinstance(data, dict):
            return 0
        idx = data.get("next_index", 0)
        return int(idx) if isinstance(idx, int) or (isinstance(idx, str) and idx.isdigit()) else 0

    def _write_next_index(self, next_index: int) -> None:
        """写游标。"""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with self._state_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump({"next_index": int(next_index)}, f, allow_unicode=True, sort_keys=False)


def _extract_content(response: Any) -> str:
    """从 LiteLLM 非流式响应中抽取文本，兼容 dict / ModelResponse。"""
    if not isinstance(response, dict):
        response = response.model_dump() if hasattr(response, "model_dump") else {}
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content", "") or ""
    # 去除模型偶尔自带的引号/换行包裹，保留颜文字
    return content.strip().strip('"').strip("'").strip()
