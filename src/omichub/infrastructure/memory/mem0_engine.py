"""mem0 v2 记忆引擎封装。

`mem0_engine_enabled=true` 时作为 AgentMemoryService 的存储/检索内核：
- 向量存储：omichub-db 的 pgvector（独立 collection，不动 agent_memories 表）
- 抽取 LLM：从平台 AI Provider 注册表解析凭据（OpenAI 兼容端点）
- Embedder：ollama bge-m3（默认）或 OpenAI 兼容端点
- history 审计：sqlite（mem0_history_dir）

mem0 v2 API 约束（PoC 实测，见实施文档 §4 D8）：
- search/get_all 拒绝顶层 user_id，必须用 filters
- 带 agent_id 过滤时共享条目不可见 → 本封装统一"按 user_id 取全集 + 客户端过滤"
- 服务端 metadata 嵌套过滤不可靠 → scope/agent/project 过滤全部在客户端

记录自描述约定：写入时把 scope/keywords/agent_id/project_id/source_session
放进 mem0 metadata，任何查询路径回来的记录都能还原 DTO 字段。
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlparse

from loguru import logger

from omichub.core.config import get_settings
from omichub.infrastructure.database.models.agent_memory import AgentMemoryModel

os.environ.setdefault("MEM0_TELEMETRY", "false")
os.environ.setdefault("POSTHOG_DISABLED", "1")

EXTRACTION_INSTRUCTIONS = (
    "提取与生物信息学研究相关的长期有价值事实：物种、组织、数据类型、分析方法、工具与参数、"
    "参考基因组、项目进展、用户稳定偏好。每条输出为自包含的中文短句。"
    "忽略问候语、一次性指令与临时性细节。不得输出密钥、密码或 Token。"
)

_engine: "Mem0Engine | None" = None
_engine_lock: asyncio.Lock | None = None


class Mem0EngineError(RuntimeError):
    """mem0 引擎初始化或运行期错误。"""


def _resolve_cipher(settings: Any) -> Any | None:
    """解析记忆静态加密器（Fernet）。

    密钥优先级：env/config `mem0_encryption_key` → `mem0_data_dir/master.key`（自动生成，0600）。
    目录不可写等异常时降级为不加密并告警，避免引擎整体不可用。
    """
    if not settings.mem0_encryption_enabled:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.error("cryptography 未安装，记忆静态加密不可用")
        return None

    key_material = (settings.mem0_encryption_key or "").strip()
    if not key_material:
        from pathlib import Path

        data_dir = Path(settings.mem0_data_dir or "/data/omichub/omichub_data/_mem0")
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            key_file = data_dir / "master.key"
            if key_file.exists():
                key_material = key_file.read_bytes().decode().strip()
            else:
                key_material = Fernet.generate_key().decode()
                key_file.write_text(key_material)
                key_file.chmod(0o600)
                logger.info("已生成 mem0 主密钥: {}", key_file)
        except OSError as exc:
            logger.error("mem0 数据目录不可用（{}），记忆静态加密降级关闭", exc)
            return None
    try:
        return Fernet(key_material.encode())
    except Exception as exc:  # noqa: BLE001
        logger.error("mem0 加密密钥无效，记忆静态加密降级关闭: {}", exc)
        return None


def _patch_vector_store(client: Any, cipher: Any) -> None:
    """vector_store 边界补丁：ndarray→list 适配 + payload.data 静态加密。

    - fastembed 的 embed() 返回 numpy ndarray，psycopg3 无法适配（ollama 返回 list 无此问题）。
    - 加密在向量库边界进行：mem0 内部读回（抽取去重/实体合并）经本补丁解密，始终看到明文；
      落盘的 payload.data 为 Fernet 密文。解密失败视为历史明文数据，原样放行。
    """
    store = getattr(client, "vector_store", None)
    if store is None or getattr(store, "_omichub_patched", False):
        return

    def _to_float_list(vec: Any) -> list[float]:
        if isinstance(vec, list):
            return vec
        return [float(v) for v in vec]

    def _encrypt_payload(payload: Any) -> Any:
        if cipher is None or not isinstance(payload, dict):
            return payload
        data = payload.get("data")
        if not isinstance(data, str) or not data:
            return payload
        return {**payload, "data": cipher.encrypt(data.encode()).decode()}

    def _decrypt_payload(payload: Any) -> Any:
        if cipher is None or not isinstance(payload, dict):
            return payload
        data = payload.get("data")
        if not isinstance(data, str) or not data:
            return payload
        try:
            return {**payload, "data": cipher.decrypt(data.encode()).decode()}
        except Exception:  # noqa: BLE001 明文历史数据或换钥前的旧数据原样放行
            return payload

    orig_insert, orig_search, orig_update = store.insert, store.search, store.update
    orig_get, orig_list = store.get, store.list

    def insert(vectors: Any, payloads: Any = None, ids: Any = None) -> None:
        encrypted = [_encrypt_payload(p) for p in (payloads or [])]
        return orig_insert([_to_float_list(v) for v in vectors], encrypted, ids)

    def search(query: Any, vectors: Any, top_k: Any = 5, filters: Any = None) -> Any:
        results = orig_search(query, _to_float_list(vectors), top_k, filters)
        for item in results:
            item.payload = _decrypt_payload(item.payload)
        return results

    def update(vector_id: Any, vector: Any = None, payload: Any = None) -> None:
        return orig_update(
            vector_id,
            _to_float_list(vector) if vector is not None else None,
            _encrypt_payload(payload),
        )

    def get(vector_id: Any) -> Any:
        item = orig_get(vector_id)
        if item is not None:
            item.payload = _decrypt_payload(item.payload)
        return item

    def list_(filters: Any = None, top_k: Any = 100) -> Any:
        # pgvector 返回嵌套结构 [[OutputData, ...]]
        results = orig_list(filters, top_k)
        for group in results:
            if isinstance(group, list):
                for item in group:
                    item.payload = _decrypt_payload(item.payload)
            elif group is not None and hasattr(group, "payload"):
                group.payload = _decrypt_payload(group.payload)
        return results

    store.insert, store.search, store.update = insert, search, update
    store.get, store.list = get, list_
    store._omichub_patched = True  # type: ignore[attr-defined]


def _patch_history(client: Any, cipher: Any) -> None:
    """history 审计库（sqlite）补丁：old_memory/new_memory 写前加密。

    读取（client.history）返回的将是密文；平台当前不消费该接口，
    如需审计展示须用同一密钥解密。
    """
    db = getattr(client, "db", None)
    if db is None or cipher is None or getattr(db, "_omichub_patched", False):
        return

    def _enc(value: Any) -> Any:
        if not isinstance(value, str) or not value:
            return value
        return cipher.encrypt(value.encode()).decode()

    orig_add = db.add_history
    orig_batch = getattr(db, "batch_add_history", None)

    def add_history(memory_id: Any, old_memory: Any, new_memory: Any, event: Any, **kwargs: Any) -> Any:
        return orig_add(memory_id, _enc(old_memory), _enc(new_memory), event, **kwargs)

    db.add_history = add_history
    if orig_batch is not None:

        def batch_add_history(records: Any) -> Any:
            encrypted = [
                {**r, "old_memory": _enc(r.get("old_memory")), "new_memory": _enc(r.get("new_memory"))}
                for r in records
            ]
            return orig_batch(encrypted)

        db.batch_add_history = batch_add_history
    db._omichub_patched = True  # type: ignore[attr-defined]


def _parse_database_url(url: str) -> dict[str, Any]:
    """从 SQLAlchemy database_url 解析 psycopg 连接参数。"""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise Mem0EngineError(f"无法解析 database_url: {url!r}")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "dbname": (parsed.path or "/").lstrip("/") or "omichub",
    }


async def _resolve_llm_endpoint() -> tuple[str, str, str]:
    """解析抽取 LLM 的 (model, api_key, base_url)。

    优先级：provider 名/模型名精确匹配 → 默认 provider 凭据 + 目标模型名。
    """
    settings = get_settings()
    target = settings.mem0_extraction_model.strip()
    try:
        from omichub.infrastructure.database.repositories.ai_provider_repository import (
            SqlAlchemyAIProviderConfigRepository,
        )
        from omichub.infrastructure.database.session import get_session_factory

        factory = get_session_factory()
        configs = []
        if factory is not None:
            async with factory() as session:
                repo = SqlAlchemyAIProviderConfigRepository(session)
                configs = await repo.list_all(active_only=True)
    except Exception as exc:  # noqa: BLE001
        raise Mem0EngineError(f"读取 AI Provider 注册表失败: {exc}") from exc

    if not configs:
        raise Mem0EngineError("AI Provider 注册表为空，mem0 引擎无法解析抽取 LLM")

    for config in configs:
        if target and target in (config.name, config.model):
            return config.model, config.api_key, config.base_url
    default = next((c for c in configs if c.is_default), configs[0])
    return (target or default.model), default.api_key, default.base_url


class Mem0Engine:
    """进程级单例；经 `await Mem0Engine.get()` 获取。"""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    async def get(cls) -> "Mem0Engine":
        global _engine, _engine_lock
        if _engine is not None:
            return _engine
        if _engine_lock is None:
            _engine_lock = asyncio.Lock()
        async with _engine_lock:
            if _engine is None:
                _engine = await cls._build()
        return _engine

    @classmethod
    async def _build(cls) -> "Mem0Engine":
        settings = get_settings()
        model, api_key, base_url = await _resolve_llm_endpoint()
        if not api_key:
            raise Mem0EngineError(f"抽取 LLM {model} 无 API Key，mem0 引擎不可用")

        pg = _parse_database_url(settings.database_url)
        data_dir = settings.mem0_data_dir.strip() or "/data/omichub/omichub_data/_mem0"
        history_dir = settings.mem0_history_dir.strip() or os.path.join(data_dir, "history")
        os.makedirs(history_dir, exist_ok=True)
        cipher = _resolve_cipher(settings)

        provider = settings.mem0_embedding_provider.strip().lower()
        if provider == "openai":
            embedder = {
                "provider": "openai",
                "config": {
                    "model": settings.mem0_embedding_model.strip(),
                    "embedding_dims": settings.mem0_embedding_dims,
                    "api_key": settings.mem0_openai_api_key,
                    "openai_base_url": settings.mem0_openai_base_url.strip() or None,
                },
            }
        elif provider == "fastembed":
            # 进程内 ONNX 推理（备选方案，免独立容器）；模型缓存走 FASTEMBED_CACHE_PATH
            embedder = {
                "provider": "fastembed",
                "config": {
                    "model": settings.mem0_embedding_model.strip() or "BAAI/bge-m3",
                    "embedding_dims": settings.mem0_embedding_dims,
                },
            }
        else:
            embedder = {
                "provider": "ollama",
                "config": {
                    "model": settings.mem0_embedding_model.strip() or "bge-m3",
                    "embedding_dims": settings.mem0_embedding_dims,
                    "ollama_base_url": settings.mem0_ollama_base_url.strip(),
                },
            }

        config = {
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "dbname": pg["dbname"],
                    "user": pg["user"],
                    "password": pg["password"],
                    "host": pg["host"],
                    "port": pg["port"],
                    "collection_name": settings.mem0_collection.strip() or "mem0_memories",
                    "embedding_model_dims": settings.mem0_embedding_dims,
                    "hnsw": True,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": model,
                    "api_key": api_key,
                    "openai_base_url": base_url or None,
                    "temperature": settings.mem0_llm_temperature,
                    "max_tokens": 1500,
                },
            },
            "embedder": embedder,
            "history_db_path": os.path.join(history_dir, "history.db"),
            "custom_instructions": EXTRACTION_INSTRUCTIONS,
        }

        def _construct() -> Any:
            from mem0 import Memory

            return Memory.from_config(config)

        client = await asyncio.to_thread(_construct)
        _patch_vector_store(client, cipher)
        _patch_history(client, cipher)
        logger.info(
            "mem0 引擎就绪: llm={}, embedder={}/{}, collection={}, encryption={}, data_dir={}",
            model,
            settings.mem0_embedding_provider,
            settings.mem0_embedding_model,
            settings.mem0_collection,
            "on" if cipher is not None else "off",
            data_dir,
        )
        return cls(client)

    # ---------- 写入 ----------

    @staticmethod
    def _build_metadata(
        *,
        scope: str,
        keywords: list[str] | None,
        agent_id: str | None,
        project_id: str | None,
        source_session: str | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {"scope": scope}
        if keywords:
            metadata["keywords"] = list(keywords)
        if agent_id:
            metadata["agent_id"] = agent_id
        if project_id:
            metadata["project_id"] = project_id
        if source_session:
            metadata["source_session"] = source_session
        return metadata

    @staticmethod
    def _sanitize_for_extraction(text: str) -> str:
        """mem0 v2 抽取遇 `<`/`>` 字符会静默产出 0 条事实（PoC 实测）。

        生信对话常含 `padj<0.05`、`QUAL<30` 之类阈值表达式，替换为自然语言读法；
        记忆本身是自然语言事实，语义不受影响。仅用于 infer 抽取路径。
        """
        cleaned = re.sub(r"<\s*", " 小于 ", str(text))
        cleaned = re.sub(r">\s*", " 大于 ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    async def add_inferred(
        self,
        messages: list[dict[str, str]],
        *,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        scope: str = "summary",
        project_id: str | None = None,
        source_session: str | None = None,
    ) -> list[dict[str, Any]]:
        """会话级写入：mem0 走 LLM 抽取 + 实体合并（settle 路径）。"""
        messages = [
            {**m, "content": self._sanitize_for_extraction(m.get("content", ""))}
            for m in messages
        ]
        metadata = self._build_metadata(
            scope=scope,
            keywords=None,
            agent_id=agent_id,
            project_id=project_id,
            source_session=source_session or run_id,
        )
        # 注意：不传原生 agent_id——mem0 v2 检测到 agent_id+assistant 消息会切换到
        # "agent memory extraction" 分支（实测对平台会话产出 0 条事实）。
        # 隔离不依赖原生字段：agent_id 已在 metadata 中，适配层全部客户端过滤。
        result = await asyncio.to_thread(
            self._client.add,
            messages,
            user_id=user_id,
            run_id=run_id,
            metadata=metadata,
        )
        return list(result.get("results", [])) if isinstance(result, dict) else []

    async def add_direct(
        self,
        content: str,
        *,
        user_id: str,
        scope: str,
        keywords: list[str] | None = None,
        agent_id: str | None = None,
        project_id: str | None = None,
        source_session: str | None = None,
    ) -> tuple[str, str]:
        """工具主动写入：infer=False 直存（免二次抽取），写入前语义查重。

        返回 (memory_id, action)，action ∈ {"created", "updated"}。
        """
        threshold = get_settings().mem0_dedup_similarity_threshold
        try:
            hits = await self.search(content, user_id=user_id, top_k=3)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mem0 写入前查重失败，按新建处理: {}", exc)
            hits = []
        for hit in hits:
            score = float(hit.get("score") or 0.0)
            hit_meta = hit.get("metadata") or {}
            hit_agent = hit.get("agent_id") or hit_meta.get("agent_id") or None
            same_bucket = (
                hit_meta.get("scope") == scope
                and hit_agent == agent_id
                and (hit_meta.get("project_id") or None) == project_id
            )
            if score >= threshold and same_bucket:
                memory_id = str(hit.get("id", ""))
                merged = self._build_metadata(
                    scope=scope,
                    keywords=keywords,
                    agent_id=agent_id,
                    project_id=project_id,
                    source_session=source_session,
                )
                await asyncio.to_thread(
                    self._client.update, memory_id, content, merged
                )
                return memory_id, "updated"

        metadata = self._build_metadata(
            scope=scope,
            keywords=keywords,
            agent_id=agent_id,
            project_id=project_id,
            source_session=source_session,
        )
        result = await asyncio.to_thread(
            self._client.add,
            content,
            user_id=user_id,
            agent_id=agent_id,
            run_id=source_session,
            metadata=metadata,
            infer=False,
        )
        results = result.get("results", []) if isinstance(result, dict) else []
        memory_id = str(results[0].get("id", "")) if results else ""
        return memory_id, "created"

    # ---------- 读取 ----------

    async def search(self, query: str, *, user_id: str, top_k: int = 20) -> list[dict[str, Any]]:
        threshold = get_settings().mem0_search_score_threshold
        result = await asyncio.to_thread(
            self._client.search,
            query,
            filters={"user_id": user_id},
            top_k=top_k,
            threshold=threshold,
        )
        return list(result.get("results", [])) if isinstance(result, dict) else []

    async def get_all_user(self, user_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        result = await asyncio.to_thread(
            self._client.get_all, filters={"user_id": user_id}, top_k=limit
        )
        return list(result.get("results", [])) if isinstance(result, dict) else []

    async def find_record(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        """按 id 在用户名下定位记录（兼作所有权校验）。"""
        for record in await self.get_all_user(user_id):
            if str(record.get("id", "")) == memory_id:
                return record
        return None

    # ---------- 变更 ----------

    async def update(
        self, memory_id: str, *, text: str | None = None, metadata: dict[str, Any] | None = None
    ) -> None:
        await asyncio.to_thread(self._client.update, memory_id, text, metadata)

    async def delete(self, memory_id: str) -> None:
        await asyncio.to_thread(self._client.delete, memory_id)

    async def delete_all(self, user_id: str, *, agent_id: str | None = None) -> int:
        """删除用户名下全部（或指定 agent 私有）记忆，返回删除条数。"""
        if agent_id:
            records = await self.get_all_user(user_id)
            targets = [
                r
                for r in records
                if (r.get("agent_id") or (r.get("metadata") or {}).get("agent_id") or None)
                == agent_id
            ]
            for record in targets:
                await self.delete(str(record.get("id", "")))
            return len(targets)
        count = len(await self.get_all_user(user_id))
        await asyncio.to_thread(self._client.delete_all, user_id=user_id)
        return count

    # ---------- 映射 ----------

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None

    @classmethod
    def to_model(cls, record: dict[str, Any], *, user_id: str = "") -> AgentMemoryModel:
        """mem0 record → transient AgentMemoryModel（供 _serialize/端点复用）。

        mem0 v2 会把 user_id/agent_id/run_id 提升为记录顶层字段（identity keys，
        update 不可覆盖）；scope/keywords/project_id/source_session 在 metadata 里。
        """
        metadata = record.get("metadata") or {}
        raw_id = str(record.get("id", ""))
        try:
            parsed_id = uuid.UUID(raw_id)
        except ValueError:
            parsed_id = uuid.uuid5(uuid.NAMESPACE_URL, f"mem0:{raw_id}")
        scope = str(metadata.get("scope") or "profile").lower()
        keywords = metadata.get("keywords") or []
        model = AgentMemoryModel(
            id=parsed_id,
            user_id=str(record.get("user_id") or metadata.get("user_id") or user_id or ""),
            project_id=metadata.get("project_id") or None,
            agent_id=record.get("agent_id") or metadata.get("agent_id") or None,
            scope=scope,
            content=str(record.get("memory") or record.get("text") or ""),
            keywords=[str(k) for k in keywords] if isinstance(keywords, list) else [],
            source_session=metadata.get("source_session") or record.get("run_id") or None,
            confidence=1.0,
            use_count=0,
            last_used_at=None,
            status="active",
        )
        model.created_at = cls._parse_datetime(record.get("created_at"))
        model.updated_at = cls._parse_datetime(record.get("updated_at")) or model.created_at
        return model


async def get_mem0_engine() -> Mem0Engine:
    return await Mem0Engine.get()
