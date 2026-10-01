# SearXNG 生产集成方案

## 1. 架构设计

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    你的平台 (OmicHub/CygnusX)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   API Gateway │  │  Agent 服务  │  │  任务队列    │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                 │               │
│  ┌──────▼─────────────────▼─────────────────▼──────┐       │
│  │         search_provider_service (现有)            │       │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────────────┐    │       │
│  │  │ Tavily  │ │   Exa   │ │  SearXNGProvider │◄───┼───────┤
│  │  │ (付费)  │ │ (付费)  │ │   (新增/改造)    │    │       │
│  │  └─────────┘ └─────────┘ └────────┬────────┘    │       │
│  │                                   │              │       │
│  │  ┌────────────────────────────────▼─────────┐    │       │
│  │  │           WebFetch / Crawler 服务         │    │       │
│  │  │         (现有，负责内容提取)              │    │       │
│  │  └──────────────────────────────────────────┘    │       │
│  └──────────────────────────────────────────────────┘       │
│                           │                                  │
└───────────────────────────┼──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│                  SearXNG 集群 (自托管)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  SearXNG-1   │  │  SearXNG-2   │  │  SearXNG-3   │       │
│  │  (主实例)    │  │  (热备)      │  │  (学术专用)  │       │
│  │  通用引擎    │  │  通用引擎    │  │  arXiv/PubMed│       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                 │               │
│  ┌──────▼─────────────────▼─────────────────▼──────┐       │
│  │              Redis (结果缓存 + 限流)              │       │
│  └──────────────────────────────────────────────────┘       │
│                                                               │
│  监控: /engines 健康检查 + Prometheus metrics                 │
└───────────────────────────────────────────────────────────────┘
```

### 1.2 核心设计决策

| 决策 | 方案 | 理由 |
|------|------|------|
| **部署模式** | 多实例 + 引擎分片 | 避免单点，学术查询走专用实例 |
| **缓存策略** | Redis 两级缓存 | 相同查询 1h 内直接返回，降低成本 |
| **内容提取** | 复用现有 WebFetch | 不引入 AgentSearch，保持链路简洁 |
| **降级策略** | 自动切换付费 API | SearXNG 故障时无缝 fallback |
| **引擎选择** | 动态配置，禁用高风险引擎 | Brave/DDG 当前大面积故障 |

---

## 2. 部署配置

### 2.1 Docker Compose 配置

```yaml
# docker-compose.searxng.yml
version: '3.8'

services:
  # 主实例：通用搜索
  searxng-general:
    image: searxng/searxng:2026.9.12  # 使用最新稳定版
    container_name: searxng-general
    ports:
      - "8081:8080"
    volumes:
      - ./searxng/general:/etc/searxng:ro
    environment:
      - SEARXNG_BASE_URL=http://searxng-general:8080/
      - SEARXNG_REDIS_URL=redis://redis:6379/0
    networks:
      - search-network
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3

  # 学术专用实例
  searxng-academic:
    image: searxng/searxng:2026.9.12
    container_name: searxng-academic
    ports:
      - "8082:8080"
    volumes:
      - ./searxng/academic:/etc/searxng:ro
    environment:
      - SEARXNG_BASE_URL=http://searxng-academic:8080/
      - SEARXNG_REDIS_URL=redis://redis:6379/1
    networks:
      - search-network
    deploy:
      resources:
        limits:
          cpus: '0.3'
          memory: 192M
    restart: unless-stopped

  # Redis 缓存
  redis:
    image: redis:7-alpine
    container_name: searxng-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - search-network
    deploy:
      resources:
        limits:
          memory: 128M
    command: redis-server --maxmemory 100mb --maxmemory-policy allkeys-lru

networks:
  search-network:
    driver: bridge

volumes:
  redis-data:
```

### 2.2 SearXNG 配置（通用实例）

```yaml
# searxng/general/settings.yml
use_default_settings: true

server:
  port: 8080
  bind_address: "0.0.0.0"
  secret_key: "your-secret-key-here-change-in-production"  # 必须修改
  
  # 限制请求来源（你的平台 IP）
  method: "POST"
  default_http_headers:
    X-Robots-Tag: noindex, nofollow
    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY

search:
  safe_search: 0  # 0=关闭, 1=中等, 2=严格
  autocomplete: ""
  default_lang: "zh-CN"
  ban_time_on_fail: 5
  max_ban_time_on_fail: 120

  # 分页设置
  paging: true
  page_size: 20

outgoing:
  # 请求超时
  request_timeout: 3.0
  max_request_timeout: 10.0
  
  # 并发请求数
  pool_connections: 100
  pool_maxsize: 20
  
  # 重试策略
  retries: 1
  
  # 代理设置（如需）
  # proxies:
  #   http:
  #     - http://proxy1:8080
  #   https:
  #     - http://proxy1:8080

  # 启用引擎（基于 2026-09 调研数据，禁用高风险引擎）
  engines:
    # === 通用搜索（当前健康）===
    - name: google
      engine: google
      shortcut: go
      disabled: false
      # 需要处理 CAPTCHA，建议配合 residential 代理
      
    - name: bing
      engine: bing
      shortcut: bi
      disabled: false
      
    # === 谨慎启用（当前大面积故障）===
    - name: brave
      engine: brave
      shortcut: br
      disabled: true  # 25/36 实例错误率≥50%，暂时禁用
      
    - name: duckduckgo
      engine: duckduckgo
      shortcut: ddg
      disabled: true  # 21/40 实例错误率≥50%，暂时禁用
      
    # === 学术/垂直（稳定）===
    - name: wikipedia
      engine: wikipedia
      shortcut: wp
      disabled: false
      
    - name: wikidata
      engine: wikidata
      shortcut: wd
      disabled: false
      
    - name: github
      engine: github
      shortcut: gh
      disabled: false
      
    - name: stackoverflow
      engine: stackoverflow
      shortcut: st
      disabled: false

    # === 新闻（按需启用）===
    - name: bing_news
      engine: bing_news
      shortcut: bin
      disabled: false
      
    # === 禁用高风险/低价值引擎 ===
    - name: startpage
      disabled: true  # 39/40 实例故障
      
    - name: yahoo
      disabled: true  # 常被 block
      
    - name: reddit
      disabled: true  # 需要 API key，且常被限流

# 结果格式
formats:
  - html
  - json  # 必须启用，供 API 调用

# 缓存（使用 Redis）
redis:
  url: redis://redis:6379/0
  # 缓存时间
  ttl:
    search: 3600  # 搜索结果缓存 1 小时

# 限流（防止滥用）
limiter:
  # 每秒最大请求数
  burst: 10
  # 滑动窗口大小
  window: 60

# 日志
logging:
  level: WARNING
  format: json
```

### 2.3 SearXNG 配置（学术专用实例）

```yaml
# searxng/academic/settings.yml
use_default_settings: true

server:
  port: 8080
  bind_address: "0.0.0.0"
  secret_key: "academic-secret-key-different-from-general"

search:
  safe_search: 0
  default_lang: "en"  # 学术搜索以英文为主

outgoing:
  request_timeout: 5.0  # 学术 API 响应较慢
  retries: 2

  engines:
    # === 学术数据库（直连，稳定）===
    - name: arxiv
      engine: arxiv
      shortcut: arx
      disabled: false
      
    - name: crossref
      engine: crossref
      shortcut: cr
      disabled: false
      
    - name: openalex
      engine: openalex
      shortcut: oa
      disabled: false
      
    - name: semantic_scholar
      engine: semantic_scholar
      shortcut: se
      disabled: false
      
    - name: pubmed
      engine: pubmed
      shortcut: pub
      disabled: false
      
    - name: google_scholar
      engine: google_scholar
      shortcut: gsc
      disabled: false
      # 注意：Google Scholar 有反爬，建议低频使用
      
    - name: core
      engine: core
      shortcut: core
      disabled: false
      
    - name: dblp
      engine: dblp
      shortcut: dblp
      disabled: false

    # === 通用引擎（备用）===
    - name: google
      engine: google
      shortcut: go
      disabled: false
      
    - name: bing
      engine: bing
      shortcut: bi
      disabled: false

formats:
  - html
  - json

redis:
  url: redis://redis:6379/1
  ttl:
    search: 86400  # 学术结果缓存 24 小时（变化较慢）

limiter:
  burst: 5  # 学术 API 限流更严格
  window: 60

logging:
  level: INFO
  format: json
```

---

## 3. 代码集成

### 3.1 SearXNG Provider 实现

```python
# search_provider_service/providers/searxng.py
"""
SearXNG 搜索 provider
支持多实例路由、自动降级、结果缓存
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import aiohttp
import redis.asyncio as redis
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .base import BaseSearchProvider, SearchResult, SearchQuery

logger = logging.getLogger(__name__)


class SearXNGInstanceType(str, Enum):
    GENERAL = "general"
    ACADEMIC = "academic"


@dataclass
class SearXNGInstance:
    """SearXNG 实例配置"""
    name: str
    base_url: str
    instance_type: SearXNGInstanceType
    timeout: float = 10.0
    priority: int = 0  # 优先级，数字越小越优先
    enabled: bool = True


class SearXNGProvider(BaseSearchProvider):
    """
    SearXNG 搜索 provider
    
    特性：
    - 多实例自动路由（通用/学术）
    - Redis 结果缓存
    - 自动故障转移
    - 引擎健康度感知
    """
    
    def __init__(
        self,
        instances: List[SearXNGInstance],
        redis_client: redis.Redis,
        cache_ttl: int = 3600,
        enable_cache: bool = True,
    ):
        self.instances = sorted(instances, key=lambda x: x.priority)
        self.redis = redis_client
        self.cache_ttl = cache_ttl
        self.enable_cache = enable_cache
        
        # 实例健康状态
        self._instance_health: Dict[str, bool] = {
            inst.name: True for inst in instances
        }
        
        # 引擎黑名单（动态更新）
        self._engine_blacklist: set = set()
    
    async def search(
        self,
        query: SearchQuery,
        **kwargs
    ) -> List[SearchResult]:
        """
        执行搜索
        
        Args:
            query: 搜索查询
            **kwargs:
                - instance_type: 强制使用特定实例类型
                - engines: 指定引擎列表
                - skip_cache: 跳过缓存
                
        Returns:
            标准化搜索结果列表
        """
        # 1. 确定实例类型
        instance_type = kwargs.get(
            "instance_type",
            self._detect_instance_type(query)
        )
        
        # 2. 尝试缓存
        cache_key = self._make_cache_key(query, instance_type)
        if self.enable_cache and not kwargs.get("skip_cache"):
            cached = await self._get_cache(cache_key)
            if cached:
                logger.debug(f"Cache hit for query: {query.text[:50]}")
                return cached
        
        # 3. 执行搜索（带故障转移）
        results = await self._search_with_failover(
            query=query,
            instance_type=instance_type,
            engines=kwargs.get("engines"),
        )
        
        # 4. 写入缓存
        if self.enable_cache and results:
            await self._set_cache(cache_key, results)
        
        return results
    
    def _detect_instance_type(self, query: SearchQuery) -> SearXNGInstanceType:
        """
        根据查询特征自动选择实例类型
        
        学术查询特征：
        - 包含学术关键词（paper, research, study, arxiv 等）
        - 查询意图为 academic
        - 包含 DOI、arXiv ID 等
        """
        academic_keywords = {
            "paper", "research", "study", "arxiv", "journal",
            "conference", "thesis", "dissertation", "doi",
            "publication", "citation", "peer-reviewed",
        }
        
        query_lower = query.text.lower()
        
        # 检查学术关键词
        if any(kw in query_lower for kw in academic_keywords):
            return SearXNGInstanceType.ACADEMIC
        
        # 检查查询意图
        if query.intent == "academic":
            return SearXNGInstanceType.ACADEMIC
        
        # 检查特定 ID 格式
        if self._is_academic_id(query.text):
            return SearXNGInstanceType.ACADEMIC
        
        return SearXNGInstanceType.GENERAL
    
    def _is_academic_id(self, text: str) -> bool:
        """检测学术 ID（DOI, arXiv ID 等）"""
        import re
        
        patterns = [
            r"10\.\d{4,}/[^\s]+",  # DOI
            r"arXiv:\d{4}\.\d{4,5}",  # arXiv ID
            r"\d{4}\.\d{4,5}(v\d+)?",  # arXiv 新格式
        ]
        
        return any(re.match(p, text) for p in patterns)
    
    async def _search_with_failover(
        self,
        query: SearchQuery,
        instance_type: SearXNGInstanceType,
        engines: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """带故障转移的搜索"""
        # 获取该类型的健康实例
        candidates = [
            inst for inst in self.instances
            if inst.instance_type == instance_type
            and self._instance_health[inst.name]
            and inst.enabled
        ]
        
        if not candidates:
            logger.error(f"No healthy {instance_type} instances available")
            raise AllInstancesUnavailableError(instance_type)
        
        # 按优先级尝试
        last_error = None
        for instance in candidates:
            try:
                results = await self._search_single(
                    instance=instance,
                    query=query,
                    engines=engines,
                )
                
                # 标记实例健康
                self._instance_health[instance.name] = True
                
                # 记录成功指标
                await self._record_metrics(instance, success=True)
                
                return results
                
            except Exception as e:
                logger.warning(
                    f"Instance {instance.name} failed: {e}, "
                    f"trying next..."
                )
                self._instance_health[instance.name] = False
                last_error = e
                await self._record_metrics(instance, success=False, error=e)
        
        # 所有实例都失败
        raise AllInstancesFailedError(instance_type, last_error)
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
    )
    async def _search_single(
        self,
        instance: SearXNGInstance,
        query: SearchQuery,
        engines: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """在单个实例上执行搜索"""
        
        # 构建请求参数
        params = {
            "q": query.text,
            "format": "json",
            "language": query.language or "zh-CN",
            "safesearch": 0,
            "categories": self._map_categories(query),
        }
        
        # 分页
        if query.page > 1:
            params["pageno"] = query.page
        
        # 指定引擎（如果提供）
        if engines:
            # 过滤掉黑名单引擎
            valid_engines = [e for e in engines if e not in self._engine_blacklist]
            if valid_engines:
                params["engines"] = ",".join(valid_engines)
        
        # 发送请求
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=instance.timeout)
        ) as session:
            async with session.get(
                f"{instance.base_url}/search",
                params=params,
            ) as resp:
                
                if resp.status == 429:
                    raise RateLimitError(f"Instance {instance.name} rate limited")
                elif resp.status == 403:
                    raise EngineBlockedError(f"Instance {instance.name} blocked")
                elif resp.status != 200:
                    raise SearXNGError(
                        f"Instance {instance.name} returned {resp.status}"
                    )
                
                data = await resp.json()
        
        # 解析结果
        results = self._parse_results(data, instance)
        
        # 更新引擎健康状态
        await self._update_engine_health(data, instance)
        
        return results
    
    def _parse_results(
        self,
        data: Dict[str, Any],
        instance: SearXNGInstance,
    ) -> List[SearchResult]:
        """解析 SearXNG 响应为标准格式"""
        results = []
        
        for item in data.get("results", []):
            # 跳过黑名单引擎的结果
            engine = item.get("engine", "")
            if engine in self._engine_blacklist:
                continue
            
            result = SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                source=f"searxng_{instance.name}",
                engine=engine,
                score=self._calculate_score(item),
                metadata={
                    "category": item.get("category"),
                    "parsed_url": item.get("parsed_url"),
                    "engines": item.get("engines", []),
                    "positions": item.get("positions", []),
                }
            )
            results.append(result)
        
        # 去重（基于 URL）
        seen_urls = set()
        unique_results = []
        for r in results:
            url_hash = hashlib.md5(r.url.encode()).hexdigest()
            if url_hash not in seen_urls:
                seen_urls.add(url_hash)
                unique_results.append(r)
        
        return unique_results
    
    def _calculate_score(self, item: Dict[str, Any]) -> float:
        """
        计算结果评分
        
        考虑因素：
        - 引擎排名（越靠前越高分）
        - 多引擎共识（多个引擎返回同一结果加分）
        - 内容长度（有实质内容的加分）
        """
        score = 0.0
        
        # 引擎排名分数（0-10）
        positions = item.get("positions", [])
        if positions:
            avg_position = sum(positions) / len(positions)
            score += max(0, 10 - avg_position)
        
        # 多引擎共识（0-5）
        engines = item.get("engines", [])
        score += min(len(engines) * 0.5, 5)
        
        # 内容质量（0-3）
        content = item.get("content", "")
        if len(content) > 100:
            score += 3
        elif len(content) > 50:
            score += 2
        elif len(content) > 0:
            score += 1
        
        return score
    
    def _map_categories(self, query: SearchQuery) -> str:
        """映射查询分类到 SearXNG 分类"""
        category_map = {
            "news": "news",
            "images": "images",
            "videos": "videos",
            "academic": "science",
            "code": "it",
        }
        return category_map.get(query.category, "general")
    
    async def _update_engine_health(
        self,
        data: Dict[str, Any],
        instance: SearXNGInstance,
    ):
        """根据响应更新引擎健康状态"""
        # SearXNG 在响应头或特定字段中返回引擎状态
        unresponsive = data.get("unresponsive_engines", [])
        
        for engine in unresponsive:
            if engine not in self._engine_blacklist:
                logger.warning(
                    f"Engine {engine} unresponsive on {instance.name}, "
                    f"adding to blacklist"
                )
                self._engine_blacklist.add(engine)
                
                # 持久化到 Redis（共享给其他实例）
                await self.redis.sadd(
                    f"searxng:blacklist:{instance.instance_type}",
                    engine
                )
    
    async def _get_cache(self, key: str) -> Optional[List[SearchResult]]:
        """从 Redis 获取缓存"""
        try:
            data = await self.redis.get(f"searxng:cache:{key}")
            if data:
                items = json.loads(data)
                return [SearchResult(**item) for item in items]
        except Exception as e:
            logger.error(f"Cache get error: {e}")
        return None
    
    async def _set_cache(self, key: str, results: List[SearchResult]):
        """写入 Redis 缓存"""
        try:
            data = json.dumps([r.dict() for r in results])
            await self.redis.setex(
                f"searxng:cache:{key}",
                self.cache_ttl,
                data
            )
        except Exception as e:
            logger.error(f"Cache set error: {e}")
    
    def _make_cache_key(
        self,
        query: SearchQuery,
        instance_type: SearXNGInstanceType,
    ) -> str:
        """生成缓存键"""
        raw = f"{query.text}:{query.language}:{query.page}:{instance_type}"
        return hashlib.md5(raw.encode()).hexdigest()
    
    async def _record_metrics(
        self,
        instance: SearXNGInstance,
        success: bool,
        error: Optional[Exception] = None,
    ):
        """记录指标到 Prometheus/Redis"""
        # 实现你的指标记录逻辑
        pass
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查接口"""
        health = {
            "provider": "searxng",
            "instances": {},
            "engine_blacklist": list(self._engine_blacklist),
        }
        
        for instance in self.instances:
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as session:
                    async with session.get(
                        f"{instance.base_url}/healthz"
                    ) as resp:
                        health["instances"][instance.name] = {
                            "status": "healthy" if resp.status == 200 else "unhealthy",
                            "type": instance.instance_type.value,
                            "enabled": instance.enabled,
                        }
            except Exception as e:
                health["instances"][instance.name] = {
                    "status": "unreachable",
                    "error": str(e),
                }
        
        return health


# 自定义异常
class SearXNGError(Exception):
    pass

class RateLimitError(SearXNGError):
    pass

class EngineBlockedError(SearXNGError):
    pass

class AllInstancesUnavailableError(SearXNGError):
    def __init__(self, instance_type: SearXNGInstanceType):
        self.instance_type = instance_type
        super().__init__(f"No available {instance_type} instances")

class AllInstancesFailedError(SearXNGError):
    def __init__(self, instance_type: SearXNGInstanceType, last_error: Exception):
        self.instance_type = instance_type
        self.last_error = last_error
        super().__init__(
            f"All {instance_type} instances failed. Last error: {last_error}"
        )
```

### 3.2 Provider 注册配置

```python
# search_provider_service/config.py
from providers.searxng import SearXNGProvider, SearXNGInstance, SearXNGInstanceType

# SearXNG 实例配置
SEARXNG_INSTANCES = [
    SearXNGInstance(
        name="general-1",
        base_url="http://searxng-general:8080",
        instance_type=SearXNGInstanceType.GENERAL,
        priority=0,
    ),
    # 可添加更多通用实例
    # SearXNGInstance(
    #     name="general-2",
    #     base_url="http://searxng-general-2:8080",
    #     instance_type=SearXNGInstanceType.GENERAL,
    #     priority=1,
    # ),
    SearXNGInstance(
        name="academic-1",
        base_url="http://searxng-academic:8080",
        instance_type=SearXNGInstanceType.ACADEMIC,
        priority=0,
    ),
]

# Provider 注册
SEARCH_PROVIDERS = {
    "tavily": TavilyProvider(...),
    "exa": ExaProvider(...),
    "searxng": SearXNGProvider(
        instances=SEARXNG_INSTANCES,
        redis_client=redis_client,
        cache_ttl=3600,
    ),
    # ... 其他 providers
}
```

### 3.3 智能路由策略

```python
# search_provider_service/router.py
"""
智能搜索路由：根据查询特征和系统状态选择最优 provider
"""

from enum import Enum
from typing import Optional

class ProviderPriority(str, Enum):
    PRIMARY = "primary"      # 首选
    FALLBACK = "fallback"    # 降级
    ACADEMIC = "academic"    # 学术专用


class SmartSearchRouter:
    """
    智能路由策略：
    
    1. 学术查询 → SearXNG academic 实例
    2. 通用查询 → SearXNG general（健康时）
    3. SearXNG 故障 → 自动降级到 Tavily/Exa
    4. 高价值查询 → 付费 API（保证质量）
    """
    
    def __init__(
        self,
        providers: Dict[str, BaseSearchProvider],
        redis_client: redis.Redis,
    ):
        self.providers = providers
        self.redis = redis_client
        
        # 降级阈值：SearXNG 连续失败 N 次后切换
        self.failover_threshold = 3
        self.failover_window = 300  # 5 分钟
    
    async def route(
        self,
        query: SearchQuery,
        context: Optional[Dict] = None,
    ) -> str:
        """
        选择最优 provider
        
        返回 provider 名称
        """
        # 1. 检查是否强制指定 provider
        if context and context.get("force_provider"):
            return context["force_provider"]
        
        # 2. 学术查询 → SearXNG academic
        if self._is_academic_query(query):
            if await self._is_provider_healthy("searxng_academic"):
                return "searxng_academic"
            else:
                return "exa"  # Exa 学术搜索强
        
        # 3. 检查 SearXNG 通用实例健康度
        searxng_healthy = await self._is_provider_healthy("searxng_general")
        
        # 4. 根据查询价值选择
        query_value = self._estimate_query_value(query)
        
        if searxng_healthy:
            if query_value == "high":
                # 高价值查询：付费 API 保证质量
                return "tavily"
            else:
                # 普通查询：免费 SearXNG
                return "searxng_general"
        else:
            # SearXNG 故障，降级到付费 API
            logger.warning("SearXNG unhealthy, falling back to paid API")
            return "tavily"
    
    def _is_academic_query(self, query: SearchQuery) -> bool:
        """判断是否为学术查询"""
        # 复用 SearXNGProvider 中的逻辑
        pass
    
    def _estimate_query_value(self, query: SearchQuery) -> str:
        """
        估算查询价值
        
        高价值特征：
        - 用户付费
        - 实时性要求高
        - 之前的查询反馈好
        """
        # 实现你的价值评估逻辑
        pass
    
    async def _is_provider_healthy(self, provider_name: str) -> bool:
        """检查 provider 健康状态"""
        # 从 Redis 获取最近失败次数
        fail_count = await self.redis.get(
            f"provider:fail_count:{provider_name}"
        )
        
        if fail_count and int(fail_count) >= self.failover_threshold:
            return False
        
        return True
```

---

## 4. 监控与运维

### 4.1 Prometheus 监控配置

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'searxng'
    scrape_interval: 30s
    static_configs:
      - targets: ['searxng-general:8080', 'searxng-academic:8080']
    metrics_path: '/metrics'
```

### 4.2 关键监控指标

```python
# monitoring/searxng_metrics.py
from prometheus_client import Counter, Histogram, Gauge

# 搜索请求计数
searxng_search_total = Counter(
    'searxng_search_total',
    'Total SearXNG search requests',
    ['instance', 'status']  # status: success, error, cache_hit
)

# 搜索延迟
searxng_search_duration = Histogram(
    'searxng_search_duration_seconds',
    'SearXNG search latency',
    ['instance'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

# 引擎健康状态
searxng_engine_health = Gauge(
    'searxng_engine_health',
    'SearXNG engine health status',
    ['instance', 'engine']
)

# 实例可用性
searxng_instance_up = Gauge(
    'searxng_instance_up',
    'SearXNG instance availability',
    ['instance']
)
```

### 4.3 告警规则

```yaml
# alert_rules.yml
groups:
  - name: searxng_alerts
    rules:
      # 实例宕机
      - alert: SearXNGInstanceDown
        expr: searxng_instance_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "SearXNG instance {{ $labels.instance }} is down"
          
      # 高错误率
      - alert: SearXNGHighErrorRate
        expr: |
          rate(searxng_search_total{status="error"}[5m]) 
          / rate(searxng_search_total[5m]) > 0.3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "SearXNG high error rate on {{ $labels.instance }}"
          
      # 高延迟
      - alert: SearXNGHighLatency
        expr: |
          histogram_quantile(0.95, 
            rate(searxng_search_duration_seconds_bucket[5m])
          ) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "SearXNG P95 latency > 5s on {{ $labels.instance }}"
          
      # 引擎大面积故障
      - alert: SearXNGEngineMassFailure
        expr: |
          count(searxng_engine_health == 0) > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Multiple SearXNG engines failing"
```

### 4.4 健康检查端点

```python
# 定期健康检查任务
import asyncio
from datetime import datetime

async def health_check_task():
    """每 30 秒执行一次健康检查"""
    while True:
        for provider_name, provider in SEARCH_PROVIDERS.items():
            try:
                health = await provider.health_check()
                
                # 更新 Prometheus 指标
                for instance_name, status in health.get("instances", {}).items():
                    searxng_instance_up.labels(
                        instance=instance_name
                    ).set(1 if status["status"] == "healthy" else 0)
                
                # 记录到日志
                logger.info(f"Health check {provider_name}: {health}")
                
            except Exception as e:
                logger.error(f"Health check failed for {provider_name}: {e}")
        
        await asyncio.sleep(30)
```

---

## 5. 降级与容灾

### 5.1 自动降级策略

```python
# resiliency/circuit_breaker.py
from enum import Enum
from datetime import datetime, timedelta

class CircuitState(str, Enum):
    CLOSED = "closed"      # 正常
    OPEN = "open"          # 熔断，拒绝请求
    HALF_OPEN = "half_open"  # 试探恢复


class CircuitBreaker:
    """
    熔断器：防止故障扩散
    
    状态转换：
    - CLOSED → OPEN: 连续失败 N 次
    - OPEN → HALF_OPEN: 冷却时间过后
    - HALF_OPEN → CLOSED: 试探成功
    - HALF_OPEN → OPEN: 试探失败
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.half_open_calls = 0
    
    async def call(self, func, *args, **kwargs):
        """执行受保护的调用"""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
            else:
                raise CircuitBreakerOpenError("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """检查是否应该尝试重置"""
        return (
            datetime.now() - self.last_failure_time
        ).total_seconds() >= self.recovery_timeout
    
    def _on_success(self):
        """成功处理"""
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_calls += 1
            if self.half_open_calls >= self.half_open_max_calls:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
        else:
            self.failure_count = 0
    
    def _on_failure(self):
        """失败处理"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN


# 集成到 provider
class ResilientSearXNGProvider(SearXNGProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.circuit_breakers = {
            inst.name: CircuitBreaker()
            for inst in self.instances
        }
    
    async def _search_single(self, instance, query, engines=None):
        breaker = self.circuit_breakers[instance.name]
        return await breaker.call(
            super()._search_single,
            instance, query, engines
        )
```

### 5.2 降级链配置

```python
# resiliency/fallback_chain.py
"""
多级降级链：
1. SearXNG general (免费)
2. Brave API (便宜，$3/千次)
3. Tavily (中等，$8/千次)
4. Exa (贵但质量好)
"""

FALLBACK_CHAINS = {
    "general": [
        {"provider": "searxng_general", "max_latency": 3.0},
        {"provider": "brave", "max_latency": 2.0},
        {"provider": "tavily", "max_latency": 2.0},
    ],
    "academic": [
        {"provider": "searxng_academic", "max_latency": 5.0},
        {"provider": "exa", "max_latency": 3.0},
        {"provider": "tavily", "max_latency": 2.0},
    ],
}


class FallbackSearchService:
    """带降级的搜索服务"""
    
    async def search_with_fallback(
        self,
        query: SearchQuery,
        chain_type: str = "general",
    ) -> Tuple[List[SearchResult], str]:
        """
        执行带降级的搜索
        
        返回: (结果, 实际使用的 provider)
        """
        chain = FALLBACK_CHAINS[chain_type]
        
        for config in chain:
            provider_name = config["provider"]
            max_latency = config["max_latency"]
            
            try:
                provider = SEARCH_PROVIDERS[provider_name]
                
                # 设置超时
                result = await asyncio.wait_for(
                    provider.search(query),
                    timeout=max_latency,
                )
                
                # 检查结果质量
                if self._is_quality_acceptable(result):
                    return result, provider_name
                else:
                    logger.warning(
                        f"Provider {provider_name} returned low quality results, "
                        f"trying next..."
                    )
                    
            except asyncio.TimeoutError:
                logger.warning(f"Provider {provider_name} timeout")
            except Exception as e:
                logger.error(f"Provider {provider_name} failed: {e}")
        
        # 所有 provider 都失败
        raise AllProvidersFailedError(f"Chain {chain_type} exhausted")
    
    def _is_quality_acceptable(self, results: List[SearchResult]) -> bool:
        """检查结果质量是否可接受"""
        if not results:
            return False
        
        # 至少 3 个结果
        if len(results) < 3:
            return False
        
        # 平均评分 > 5
        avg_score = sum(r.score for r in results) / len(results)
        if avg_score < 5:
            return False
        
        return True
```

---

## 6. 部署与运维手册

### 6.1 一键部署脚本

```bash
#!/bin/bash
# deploy_searxng.sh

set -e

echo "=== SearXNG 部署脚本 ==="

# 1. 创建目录结构
mkdir -p searxng/{general,academic}
mkdir -p monitoring

# 2. 生成随机密钥
GENERAL_SECRET=$(openssl rand -hex 32)
ACADEMIC_SECRET=$(openssl rand -hex 32)

# 3. 渲染配置文件
cat > searxng/general/settings.yml <<EOF
# 通用实例配置
server:
  secret_key: "$GENERAL_SECRET"
  # ... 其他配置
EOF

cat > searxng/academic/settings.yml <<EOF
# 学术实例配置
server:
  secret_key: "$ACADEMIC_SECRET"
  # ... 其他配置
EOF

# 4. 启动服务
docker-compose -f docker-compose.searxng.yml up -d

# 5. 等待健康检查
echo "等待服务启动..."
sleep 10

# 6. 验证部署
curl -f http://localhost:8081/healthz || echo "通用实例启动失败"
curl -f http://localhost:8082/healthz || echo "学术实例启动失败"

# 7. 测试搜索
echo "测试搜索..."
curl "http://localhost:8081/search?q=test&format=json" | jq '.results | length'

echo "=== 部署完成 ==="
echo "通用实例: http://localhost:8081"
echo "学术实例: http://localhost:8082"
```

### 6.2 日常运维命令

```bash
# 查看日志
docker logs -f searxng-general

# 重启服务
docker-compose -f docker-compose.searxng.yml restart

# 更新 SearXNG 版本
docker-compose -f docker-compose.searxng.yml pull
docker-compose -f docker-compose.searxng.yml up -d

# 检查引擎状态
curl "http://localhost:8081/engines" | jq '.[] | select(.status != "ok")'

# 清理 Redis 缓存
docker exec -it searxng-redis redis-cli FLUSHDB

# 备份配置
tar -czf searxng-backup-$(date +%Y%m%d).tar.gz searxng/
```

### 6.3 故障排查指南

| 症状 | 可能原因 | 解决方案 |
|------|----------|----------|
| 所有引擎返回空结果 | IP 被封 | 更换出口 IP 或启用代理 |
| Google 引擎 403 | CAPTCHA | 降低请求频率，或禁用 Google |
| 高延迟 | 引擎响应慢 | 调整 `request_timeout`，禁用慢引擎 |
| Redis 连接失败 | Redis 宕机 | 检查 Redis 状态，启用本地缓存降级 |
| 内存溢出 | 缓存过大 | 调整 Redis `maxmemory` 策略 |

---

## 7. 成本效益分析

### 7.1 成本对比（基于你的调研数据）

| 方案 | 月查询量 | 成本 |
|------|----------|------|
| **纯 Tavily** | 100 万 | $8,000 |
| **纯 Exa** | 100 万 | $5,000 |
| **SearXNG + 付费降级** | 100 万（80% 走 SearXNG） | **~$1,600** |
| **纯 SearXNG** | 100 万 | $50（服务器） |

### 7.2 服务器配置建议

| 查询量 | 配置 | 预估成本 |
|--------|------|----------|
| < 10 万/天 | 1 核 2G | $5-10/月 |
| 10-50 万/天 | 2 核 4G | $20-40/月 |
| > 50 万/天 | 4 核 8G + 代理池 | $100+/月 |

---

## 8. 实施路线图

### Phase 1: 试点（1-2 周）
- [ ] 部署单实例 SearXNG（通用）
- [ ] 实现基础 SearXNGProvider
- [ ] 对比 Tavily 结果质量
- [ ] 监控引擎健康度

### Phase 2: 优化（2-4 周）
- [ ] 添加学术专用实例
- [ ] 实现智能路由
- [ ] 添加 Redis 缓存
- [ ] 配置自动降级

### Phase 3: 生产（4-8 周）
- [ ] 多实例部署
- [ ] 完整监控告警
- [ ] 熔断器集成
- [ ] 成本优化调优
