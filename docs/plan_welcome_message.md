# CygnusX 主页动态欢迎词（天气 + LLM）— 执行计划

> 阶段三：主页动态看板开发（天气与 LLM 欢迎词）
> 配套阶段四：视觉 / 性能 / 降级验收。本文档仅覆盖「欢迎词」相关范围。

## 1. 目标

在仪表板（`DashboardView.vue`）现有蓝色渐变 Banner 上，渲染一段**带天气信息与时间段问候的 LLM 欢迎词**，为硬核组学平台注入人文关怀：

- 拉取武汉（和风天气 Location ID `101200101`）实时天气（`text` + `temp`）。
- 将天气 + 时间段（早上好 / 下午好 / 晚上好）注入 Prompt，调 LLM 生成带**生信学术梗**的简短问候。
- 缓存（后端 Redis + 前端 LocalStorage 6h），避免每次刷新都调 LLM。
- 异步渲染，**绝不阻塞**仪表盘核心数据加载；失败静默降级。

## 2. 与现有「管理员登录欢迎词」的关系

仓库已有一套**管理员登录 Toast** 欢迎词，本计划**不复用它、也不替换它**，仅复用其底层基建。

| 维度 | 现有：管理员登录 Toast | 本计划：Dashboard 动态欢迎词 |
|---|---|---|
| 触发 | 管理员登录后弹一次 Notification | 任意用户进仪表板，渲染在 Banner 上 |
| 受众 | 仅 `role === 'admin'` | 所有登录用户 |
| 内容来源 | 预生成池 `welcome.yaml` 顺序轮询（启动补齐） | 实时组装（天气 + 时间段）→ LLM 现生成 + 缓存 |
| 后端入口 | `POST /llm/generate-welcome`（`AdminRequired`） | 新增 `GET /dashboard/welcome`（仅需登录） |
| 前端 | `composables/useAdminWelcome.ts`（Notification） | 新增 `composables/useDashboardWelcome.ts`（Banner 内嵌） |
| 服务 | `application/services/welcome_service.py` | 新增 `dashboard_welcome_service.py` + `weather_service.py` |

**复用点**：`LiteLLMProvider`（LLM 调用）、`AIProviderConfigService.get_active_default()`（取默认 provider）、`infrastructure/cache/redis_client.py` 的 `get_redis()` 与 `cached_json(ttl, key, factory)` 缓存模式、`core/config.py` 的 `Settings` 配置项模式。

## 3. 整体架构

```
DashboardView (onMounted, 异步)
  └─ useDashboardWelcome.fetch()
       ├─ 前端 LocalStorage 命中（6h 内）→ 直接渲染，不发请求
       └─ 未命中 → GET /dashboard/welcome
            ├─ WeatherService.get_wuhan_weather()
            │     └─ Redis 缓存命中 → 返回 {text, temp}
            │     └─ 未命中 → 和风天气 /v7/weather/now → 写 Redis (TTL 20min) → 返回
            ├─ DashboardWelcomeService.generate(time_slot, weather)
            │     └─ Redis 缓存命中 (key=time_slot+weather_text) → 返回文案
            │     └─ 未命中 → 组装 Prompt → LiteLLMProvider.chat → 写 Redis (TTL 6h) → 返回
            └─ 返回 { time_slot, greeting, weather:{text,temp,emoji} }
       └─ 写 LocalStorage (6h) → 渲染到 Banner
       └─ 3s 超时 / 任意异常 → 静默降级静态文案
```

## 4. 阶段拆解

### 阶段 4.1 配置项与和风天气接入

**配置项**（追加到 `src/cygnusx/core/config.py` 的 `Settings`，仿 `welcome_yaml` 段落风格）：

```python
# ===== 主页动态欢迎词（天气 + LLM）=====
dashboard_welcome_enabled: bool = True
qweather_enabled: bool = False           # 未申请到 key 前关闭，降级为无天气
qweather_api_key: str = ""               # 和风天气 API Key（走 .env 注入）
qweather_location: str = "101200101"     # 武汉 Location ID
qweather_base_url: str = "https://devapi.qweather.com"
qweather_cache_ttl: int = 1200           # 天气缓存 20 分钟（秒）
dashboard_welcome_cache_ttl: int = 21600 # 欢迎词缓存 6 小时（秒）
dashboard_welcome_timeout: int = 3       # LLM 调用超时（秒），与前端 3s 对齐
```

**`weather_service.py`**（新增 `src/cygnusx/application/services/weather_service.py`）：

```python
class WeatherService:
    """和风天气实况拉取 + Redis 缓存。城市固定武汉（可配置）。"""
    async def get_wuhan_weather(self) -> dict[str, Any] | None:
        # key = "weather:now:101200101"
        # cached_json(ttl=settings.qweather_cache_ttl, key=..., factory=self._fetch_from_qweather)
        # 失败（key 空 / 网络 / 限流）返回 None，调用方降级为无天气
    async def _fetch_from_qweather(self) -> dict[str, Any] | None:
        # GET {base_url}/v7/weather/now?location={loc}&key={key}
        # 取 now.text（如"多云"）与 now.temp；icon 由 text 映射 emoji（前端做也行）
```

**关键点**：天气是**全平台共享**数据，缓存 key 不含用户维度；`qweather_enabled=False` 或 key 缺失时直接返回 `None`，不抛异常。

### 阶段 4.2 LLM Prompt 组装与调用

**`dashboard_welcome_service.py`**（新增 `src/cygnusx/application/services/dashboard_welcome_service.py`）：

```python
class DashboardWelcomeService:
    """组装天气 + 时间段 → LLM 生成欢迎词，Redis 缓存 6h。"""
    async def generate(self, time_slot: str, weather: dict | None, username: str | None) -> str:
        # cache_key = f"dash_welcome:{time_slot}:{weather_text or 'na'}"
        #   — 不含 username，保证同一时段+天气下全用户复用，省 token
        # 命中则直接返回；未命中调 LLM：
        #   provider = LiteLLMProvider(await AIProviderConfigService(db).get_active_default())
        #   text = await provider.chat(messages=[system, user], temperature=..., max_tokens=...)
        #   清洗 + 写缓存 (ttl=settings.dashboard_welcome_cache_ttl)
```

**System Prompt 模板**（学术梗人设，约束字数与随机性）：

```
你是 CygnusX（多组学分析平台，主打 RNA-seq / ATAC-seq）的欢迎助手。
当前时间段：{time_slot}（早上好/下午好/晚上好）。
当前武汉天气：{weather_text}，{temp}℃（若无天气则忽略天气相关表述）。

请生成一句简短欢迎语，要求：
1. 融入一个生信/组学学术梗（如 DESeq2、比对率、p-value、染色质开放性、FASTQ、batch effect 等），俏皮不生硬。
2. 可呼应天气或时间段（如"下雨天适合跑比对"）。
3. 长度 25-45 字，适合横幅单行展示。
4. 不输出解释、引号、颜文字以外的多余符号。
```

**User Prompt**：`请直接输出欢迎语本身。`

**时间段分桶**（前端计算，作为缓存 key 与 Prompt 变量）：

| 小时 | time_slot | 问候 |
|---|---|---|
| 5–11 | `morning` | 早上好 |
| 12–17 | `afternoon` | 下午好 |
| 18–22 | `evening` | 晚上好 |
| 23–4 | `late_night` | 夜深了 |

**个性化**：username 不进 LLM（保缓存复用），前端在渲染时本地拼接 `「早上好，{username}」` 前缀。

### 阶段 4.3 缓存策略

两层缓存，**后端 Redis 为主、前端 LocalStorage 为辅**：

| 层 | Key | TTL | 作用 |
|---|---|---|---|
| 后端·天气 | `weather:now:101200101` | 20 min | 全平台共享，避免高频调和风 |
| 后端·欢迎词 | `dash_welcome:{time_slot}:{weather_text}` | 6 h | 同时段+同天气全用户复用，省 token |
| 前端 | `cygnusx:dashboardWelcome` | 6 h | 同一用户 6h 内刷新不再请求后端 |

- 后端缓存沿用 `cached_json(ttl, key, factory)` 模式（见 `infrastructure/cache/stats_cache.py`）；`enable_stats_cache=False` 时直查。
- 前端 LocalStorage 存 `{ ts, data }`，读取时校验 `Date.now() - ts < 6h`；过期或格式错则重取。
- 写 LocalStorage 时注意：`localStorage` 在某些隐私模式不可用，try/catch 包裹。

### 阶段 4.4 前端 UI 渲染

**新增 `frontend/src/composables/useDashboardWelcome.ts`**（仿 `useAdminWelcome.ts` 的超时/降级风格）：

```ts
// 状态：greeting, weather, loading, error
// fetch():
//   1. 读 localStorage（6h 内）→ 命中直接 set
//   2. 否则 apiClient.get('/dashboard/welcome', { timeout: 3000 })
//   3. 写 localStorage；任意失败 → 降级静态文案（"欢迎来到 CygnusX"）
// 暴露 timeOfDayGreeting（早上好/...）+ username 拼接
```

**修改 `frontend/src/views/DashboardView.vue`** 的 `announcement-banner`（L262–282）：

- 在 `.banner-text` 内 `.banner-desc` 处，或 Banner 右侧新增一个天气 chip，渲染：
  `「早上好，张三 ☁️ 武汉 多云 25°C — {LLM greeting}」`
- 天气 emoji 由 `weather.text` 映射（晴 ☀️ / 多云 ⛅ / 阴 ☁️ / 雨 🌧️ / 雪 ❄️ …），映射表放前端。
- 初始渲染用占位（骨架/省略），数据到位后淡入；**不阻塞** `healthStatus` / `flowCount` / `stats/overview` 等核心请求（并行 `onMounted`，互不 await）。
- Banner 文案溢出处理：长文本 `text-overflow: ellipsis`，窄屏（`@media max-width:768px`）隐藏天气 chip 只留问候语。

## 5. 接口设计

**`GET /api/v1/dashboard/welcome`**（新增，挂在 `api/v1/router.py`）

- 权限：仅需登录（`Depends(get_current_user)`），**非** admin-only。
- 响应 `DashboardWelcomeDTO`：

```json
{
  "time_slot": "morning",
  "greeting": "早上跑 DESeq2，p 值比咖啡还提神——多云天适合跑比对。",
  "weather": { "text": "多云", "temp": "25", "emoji": "⛅" },
  "username": "zhang_san"
}
```

- `weather` 可为 `null`（未启用 / 拉取失败）。
- 响应头可加 `Cache-Control: private, max-age=21600` 提示前端。

**路由文件**：新增 `src/cygnusx/api/v1/dashboard.py`，在 `router.py` 注册。

## 6. 文件清单

| 类型 | 路径 | 说明 |
|---|---|---|
| 新增 | `src/cygnusx/application/services/weather_service.py` | 和风天气拉取 + Redis 缓存 |
| 新增 | `src/cygnusx/application/services/dashboard_welcome_service.py` | Prompt 组装 + LLM 调用 + 缓存 |
| 新增 | `src/cygnusx/api/v1/dashboard.py` | `GET /dashboard/welcome` |
| 新增 | `src/cygnusx/application/schemas/dashboard.py` | `DashboardWelcomeDTO` |
| 修改 | `src/cygnusx/core/config.py` | 追加 6.1 节配置项 |
| 修改 | `src/cygnusx/api/v1/router.py` | 注册 dashboard 路由 |
| 新增 | `frontend/src/composables/useDashboardWelcome.ts` | 拉取 + LocalStorage + 降级 |
| 修改 | `frontend/src/views/DashboardView.vue` | Banner 渲染欢迎词 + 天气 chip |
| 修改 | `.env` / `deploy/docker/docker-compose.yml` | 注入 `QWEATHER_API_KEY` |

## 7. 验收标准（对应阶段四）

**视觉与交互**
- [ ] 登录后进仪表板，Banner 显示「问候 + 天气 emoji + 温度 + LLM 欢迎词」。
- [ ] 不同分辨率（1920/1440/768/375）下文字不被截断；768px 以下天气 chip 隐藏，仅留问候语。
- [ ] 同一时段 + 同一天气下，不同用户看到的 LLM 文案一致（缓存复用验证）。

**性能**
- [ ] 欢迎词请求与 `/health`、`/flows`、`/stats/overview` 并行，互不阻塞；仪表盘核心数据先于欢迎词展示。
- [ ] 后端 P95 < 300ms（缓存命中）/ < 3s（缓存未命中，LLM 冷调）。
- [ ] 6h 内刷新不触发后端请求（LocalStorage 命中）。

**降级与安全**
- [ ] `QWEATHER_API_KEY` 缺失 → `weather=null`，Banner 隐藏天气部分，问候语仍展示。
- [ ] LLM 超时 / 失败 → 前端 3s 超时后降级静态文案「欢迎来到 CygnusX」。
- [ ] 和风天气限流 / 网络异常 → 后端返回 `weather=null`，不抛 5xx。
- [ ] 未登录访问 `GET /dashboard/welcome` → 401。
- [ ] 构造过期 / 非法 JWT → 401（复用现有鉴权中间件，本计划不涉及 Ed25519 改造）。

## 8. 风险与回退

| 风险 | 应对 |
|---|---|
| 和风天气免费档限流 | 后端 20min 缓存 + 全平台共享，QPS 极低；限流时降级 `weather=null` |
| LLM 生成内容不稳定（超字数 / 跑题） | System Prompt 强约束 + `max_tokens` 限制 + 后端清洗（仿 `_extract_content`） |
| 缓存击穿（6h 整点同时过期） | TTL 加 ±10% 随机抖动（`cached_json` 可扩展） |
| 默认 AI provider 未配置 | `get_active_default()` 返回 None 时降级静态文案，不阻塞 |
| LocalStorage 不可用 | try/catch，降级为每次请求后端（仍有 Redis 兜底） |

**回退开关**：`dashboard_welcome_enabled=False` 时，`GET /dashboard/welcome` 直接返回静态文案 + `weather=null`，前端 Banner 回退为原有「RNA-seq / ATAC-seq 分析已就绪」文案，零影响。

## 9. 不在本计划范围

- Ed25519 鉴权改造（阶段一）：独立推进，本计划的 `/dashboard/welcome` 复用现有 JWT 鉴权即可。
- 全局下拉菜单样式统一（阶段二）：已在前序提交中将 `DownloadsView` 原生 `<select>` 替换为 `NSelect`。
- 管理员登录 Toast（`welcome_service.py`）：保持不动。
