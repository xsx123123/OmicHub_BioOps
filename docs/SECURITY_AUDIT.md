# OmicHub 平台安全审计报告

> 审计日期:2026-07-09
> 审计范围:认证/授权、终端沙盒、文件下载、部署配置、注入/SSRF 五个攻击面
> 说明:所有关键结论均已逐条回读源码核实,并纠正了自动化扫描的若干夸大结论。

---

## 概览

| 级别 | 数量 | 编号 | 状态 |
|------|------|------|------|
| 🔴 严重 | 3 | #1 路径穿越、#2 `/tracks/` 无鉴权、#3 密钥默认值 | ✅ 已修复 |
| 🟠 高危 | 5 | #4 Redis、#5 明文密钥、#6 MCP RCE/SSRF、#7 安全头、#8 Flower | ✅ 已修复 |
| 🟡 中危 | 6 | #9–#14 | ✅ 已修复 |

---

## 🔴 严重(需立即处理)

### #1 路径穿越 → 任意文件读取
`src/omichub/application/services/file_service.py:214-216` 的 `_resolve_abs` 直接拼接,**无 `resolve()` 边界校验**:

```python
def _resolve_abs(self, storage_path: str) -> Path:
    return self._storage_root / storage_path   # storage_path=../../etc/passwd → 逃逸
```

`src/omichub/application/services/report_service.py:76 / 95` 更糟:`Path(primary.path)` / `Path(file_model.path)` 直接把 DB 里的**绝对路径**喂给 `read_text()` 和 `FileResponse`,完全无根目录约束。

- **攻击链**:凡是能污染 `file_records.storage_path` / `report_files.path` 的路径(task 产物写入、下载登记),即可读取宿主任意文件。授权检查通过(文件属于该用户)但路径校验缺失。
- **正确范本**:`src/omichub/application/services/docs_service.py:109` 用了 `resolve().relative_to()` 校验,应推广到 file / report。

### #2 nginx `/tracks/` 无鉴权暴露全部用户数据(dev + prod 均存在)
`deploy/docker/nginx/nginx.conf:136` 和 `deploy/docker/nginx/nginx.prod.conf:113`:

```nginx
location ^~ /tracks/ {
    alias /data/omichub/;                    # 直挂全部数据根
    add_header Access-Control-Allow-Origin * always;
    # allow 10.0.0.0/8;  ← IP 白名单被注释掉,未启用
}
```

任何能访问 nginx 的客户端可遍历读取 `/data/omichub/users/*/` 下**所有用户**的原始数据、结果、下载文件。CORS `*` 让恶意网页也能跨域抓取。白名单目前是注释状态,等于没做。

### #3 生产环境密钥默认值可伪造 JWT
`src/omichub/core/config.py`:

```python
app_secret_key = "change-me-in-production"
jwt_secret_key = "change-me-in-production"   # HS256 对称,泄露即可伪造任意用户/admin token
postgres_password = "omichub"
```

`.env` 里也是占位符 `change-me-...`。若上线时忘记覆盖(尤其 `is_production` 未强校验这两个值),攻击者用已知密钥伪造 admin JWT 即可全站接管。**建议在 `is_production` 分支里断言这些值非默认,启动即 fail-fast。**

---

## 🟠 高危

### #4 Redis 无密码 + 端口暴露
`.env` 中 `REDIS_PASSWORD=`(空);`deploy/docker/docker-compose.yml` 暴露 `6379:6379`、`5432:5432` 到宿主。dev 环境任何本机/同网段进程可读写 Celery 队列、结果后端、缓存,注入/篡改任务结果。~~prod compose 已移除端口绑定(好),但 Redis 仍无 auth。~~ **已修复:prod compose 关闭 Redis 端口并统一加 `--requirepass`。**

### #5 AI provider key / TOTP secret 明文落盘
`src/omichub/core/config.py:111` `ai_provider_key_encryption_key = ""` 默认空;`src/omichub/core/security.py` 的 `encrypt_value` 在无密钥时**原样返回明文**。结果:第三方 LLM API key **和 2FA TOTP secret** 明文存 DB。库一旦泄露 → 密钥泄露 + 2FA 绕过。**生产应强制要求配置该密钥。**

### #6 MCP stdio/SSE = admin 后台 RCE + SSRF(已核实为 admin-gated)
`src/omichub/infrastructure/mcp/client.py:118-137`:stdio transport 把 `command`/`args`/`env` 直接交给 `StdioServerParameters` 执行;SSE transport `sse_client(server.url)` 无 URL 校验。

- **已核实所有 MCP 端点都有 `AdminRequired`**(`src/omichub/api/v1/mcp.py`)—— 所以不是未授权 RCE,而是:①恶意/被盗 admin 账号 → 服务器任意命令执行;②SSE URL 可指向 `169.254.169.254`/内网 → SSRF。
- 缺 CSRF 防护叠加:admin 被诱导访问恶意站点即可注册后门 MCP。
- **建议**:SSE URL 加内网/metadata 黑名单,stdio command 加白名单。

### #7 nginx 缺失全部安全响应头
`nginx.conf` 与 `nginx.prod.conf` 都没有 `X-Frame-Options` / `X-Content-Type-Options: nosniff` / `CSP` / `HSTS`。叠加 chat 上传无扩展名/类型校验(`src/omichub/api/v1/files.py:178-200`),存在 MIME sniffing、点击劫持风险。

### #8 Flower 监控 UI 无鉴权(dev)
`deploy/docker/docker-compose.yml` 暴露 `5555`,`nginx.conf:116` 代理 `/flower/` 无认证。可查看/终止所有 Celery 任务(含任务参数、文件路径)。prod nginx 未含此段,但 compose 端口仍开。

---

## 🟡 中危(逐条已核实存在,影响有限)

| # | 问题 | 位置 |
|---|------|------|
| 9 | 云存储 URI 仅校验前缀(`oss://`)不校验 host,可能 SSRF | `src/omichub/infrastructure/celery_app/tasks/download.py:60,86` |
| 10 | `cookie_balance` WebSocket Redis 频道用裸 `user_id` 无命名空间前缀 | `src/omichub/api/v1/cookies.py:74-102` |
| 11 | 登录/2FA 端点仅全局 IP 限流(100/60s),无针对性防爆破 | `src/omichub/api/v1/auth.py:47` |
| 12 | 会话 ID 用 `random`(非 `secrets`)8 位,熵偏低 | `src/omichub/application/services/terminal_service.py:70` |
| 13 | WebSocket 异常 detail 原文回传客户端(信息泄露) | `src/omichub/api/v1/sandbox.py:126`, `terminal.py:221` |
| 14 | AI provider key 可能进异常日志 | `src/omichub/infrastructure/ai_provider/openai_compatible.py:298` |

---

## ✅ 已核实做得对的地方(纠正自动化扫描的误报)

- **终端 WebSocket 认证是安全的**:`src/omichub/api/v1/terminal.py:104-119` 在 `accept()` **之前**校验了 token type=`access` **且** `session.user_id == token.sub`。所谓"未授权 shell"不成立。
- `.env` **未被 git 跟踪**,`.gitignore:56` 正确忽略,仓库无真实密钥泄露。
- prod compose 正确移除 DB 端口、`APP_DEBUG=false`、容器非 root(PUID=1000)。
- `docs_service.py` 路径校验正确,可作为修复 file/report 的范本。
- docker.sock 挂载给 web 容器是终端管理刚需(信任边界大但有意为之)。

---

## 修复优先级建议

1. **立刻**:给 `_resolve_abs` 和 report 路径加 `resolve().relative_to(root)` 校验(#1);启用 `/tracks/` IP 白名单或改走后端鉴权(#2)。
2. **上线前 fail-fast**:`is_production` 时断言 jwt/app secret 非默认值、强制 `ai_provider_key_encryption_key` 非空(#3 / #5)。
3. **配置层**:Redis 加密码、补 nginx 安全头、prod 关闭 Flower 端口(#4 / #7 / #8)。

> 唯一未授权即可利用的严重漏洞是 **#1 路径穿越**,建议最优先修复。

---

## 修复记录

以下问题已在本次迭代中修复,详细改动见 `git log` 与 `README.md`「安全加固清单」。

| 编号 | 修复内容 | 关键文件 |
|---|---|---|
| #1 | `FileService._resolve_abs` / `ReportService._resolve_report_path` 增加 `resolve().relative_to(storage_root)` 校验,禁止 `..` 与绝对路径 | `file_service.py`, `report_service.py` |
| #2 | nginx `/tracks/` 启用 RFC1918 内网 IP 白名单(`allow 10/172/192 + deny all`) | `nginx.conf`, `nginx.prod.conf` |
| #3 | 生产环境(`is_production`)下默认 `app_secret_key`/`jwt_secret_key` 触发启动失败 | `config.py` |
| #4 | Redis 增加 `--requirepass`;生产 compose 关闭 Redis 宿主端口 | `docker-compose.yml`, `docker-compose.prod.yml`, `config.py` |
| #5 | 生产环境强制 `ai_provider_key_encryption_key` 非空,否则启动失败 | `config.py` |
| #6 | MCP SSE URL 禁止 IP/内网/metadata;stdio command 禁止绝对路径与 shell 解释器 | `mcp/client.py`, `mcp_service.py` |
| #7 | nginx 增加 `X-Frame-Options`/`X-Content-Type-Options`/`X-XSS-Protection`/`Referrer-Policy`/`HSTS`;聊天上传增加扩展名白名单 | `nginx.conf`, `nginx.prod.conf`, `files.py` |
| #8 | Flower 开发环境启用 `--basic_auth`;生产环境 `replicas: 0` 关闭 | `docker-compose.yml`, `docker-compose.prod.yml` |
| #9 | 云存储 URI 校验主机名:禁止 IP,显式 endpoint 必须匹配云商域名后缀 | `schemas/download.py` |
| #10 | cookie balance Redis 频道增加应用前缀 `omichub:` | `cookie_pubsub.py` |
| #11 | `/login` 与 `/2fa/login` 增加 IP 级登录失败限流(5 分钟 5 次失败封禁 15 分钟) | `auth.py`, `login_rate_limit.py` |
| #12 | 终端会话 ID 改用 `secrets.token_urlsafe(16)` | `terminal_service.py` |
| #13 | 沙盒 WebSocket 异常不再回传 detail 给客户端,仅记录日志 | `sandbox.py` |
| #14 | LLM 调用异常日志脱敏,隐藏 Bearer token / api_key | `openai_compatible.py` |

### 验证情况

- 新增 `tests/unit/test_security_fixes.py`,16 个用例全部通过。
- `tests/unit/` 全部 53 个用例通过。
- 生产配置 fail-fast 已验证:默认密钥下 `APP_ENV=production` 启动失败。
- 所有修改的 Python 文件均通过 `py_compile`。

> 剩余待办:公网/多租户场景下 `/tracks/` 应进一步实现后端鉴权代理;CSP 策略可根据前端实际情况后续补强。

---

## 第二轮全方面安全审计（2026-07-09）

在首轮 14 项修复基础上，对认证/授权、WebSocket、AI/MCP、文件上传、沙盒/终端、登录限流、JWT 吊销、依赖漏洞等攻击面进行第二轮审计。

### 🔴 严重 / 高危（新增）

| 编号 | 问题 | 位置 | 风险 | 修复 |
|---|---|---|---|---|
| #15 | WebSocket 端点未校验用户状态 | `ai.py` / `terminal.py` / `sandbox.py` / `cookies.py` / `tasks.py` | 用户被禁用/删除后，token 未过期仍可连接 AI/终端/沙盒/饼干/任务日志 WS | accept 前调用 `get_active_user_from_token_payload` 查库确认 active |
| #16 | Chat 附件读取 SSRF | `chat_service.py:785-824` | 附件 URL 可指向内网/metadata，读取任意内部服务 | 非本地上传时校验 URL scheme 与 host，禁止内网/回环/metadata |
| #17 | MCP stdio 路径遍历 + args 未校验 | `mcp/client.py:63-71` | `command="../bin/bash"` 可绕过；`args` 可带 `-c` 执行任意命令 | 禁止 `..`、PATH 白名单、args 禁止 shell 元字符与路径穿越 |
| #18 | AI Tool Call 参数无 schema 校验 | `ai_service.py` / `ai_tools.py` | 模型被 prompt 注入后可越权查询/提交恶意任务 | `submit_task`/`query_status`/`list_samples` 用 Pydantic 校验参数 |

### 🟠 中危（新增）

| 编号 | 问题 | 位置 | 风险 | 修复 |
|---|---|---|---|---|
| #19 | 登录限流 XFF 首个 IP 可伪造 | `login_rate_limit.py:24-32` | 攻击者伪造 XFF 头部绕过限流 | 取 `X-Forwarded-For` 链中最后一个 IP |
| #20 | JWT 无吊销机制 | `security.py` | 改密/禁用/角色变更后旧 token 仍有效 | 引入 `token_version`；关键变更时递增 |
| #21 | 沙盒容器未做网络隔离 | `sandbox/pool.py:100-119` | 用户代码可扫描内网、出站连接 | 默认 `network_mode="none"`，配置项 `SANDBOX_NETWORK_ISOLATED` |
| #22 | 聊天文件上传全局可访问 | `files.py:260-301` | 任意登录用户可下载所有聊天附件 | 目录按 `chat/{user_id}` 隔离；下载校验归属 |
| #23 | TOTP `required` 策略未生效 | `auth_service.py` | 站点开启强制 2FA 后普通用户仍可登录 | `totp_policy=required` 且未开启 2FA 时拒绝登录 |
| #24 | 依赖漏洞（ecdsa） | `pyproject.toml` | `python-jose` 依赖的 `ecdsa` 存在 Minerva 计时攻击 CVE | 用 `PyJWT` 替换 `python-jose[cryptography]`，移除 ecdsa |

### 修复记录（第二轮）

| 编号 | 修复内容 | 关键文件 |
|---|---|---|
| #15 | 所有 WebSocket 端点在 `accept()` 前查库校验用户 active 状态 | `api/v1/ai.py`, `terminal.py`, `sandbox.py`, `cookies.py`, `tasks.py`, `api/deps.py` |
| #16 | Chat 附件非本地上传时禁止内网/回环/metadata URL | `chat_service.py` |
| #17 | MCP stdio 命令 PATH 白名单、args 禁止 shell 元字符与路径穿越 | `mcp/client.py` |
| #18 | AI Tool 参数 Pydantic schema 校验 | `ai_tools.py` |
| #19 | 登录限流取 XFF 最后一个 IP | `login_rate_limit.py` |
| #20 | JWT token_version 吊销机制 + 数据库迁移 | `security.py`, `deps.py`, `user model`, `user_repository.py`, `auth_service.py`, `totp_service.py`, `admin/users.py`, `user_service.py`, `alembic` |
| #21 | 沙盒默认无网络模式 | `sandbox/pool.py`, `config.py` |
| #22 | 聊天文件按用户隔离 | `files.py`, `chat_service.py` |
| #23 | 强制 TOTP required 策略生效 | `auth_service.py` |
| #24 | 依赖替换消除 ecdsa CVE | `pyproject.toml`, `uv.lock`, `security.py` |

### 验证情况（第二轮）

- 新增 `tests/unit/test_security_round2.py`，23 个用例全部通过。
- `tests/unit/` 全部 **76** 个用例通过。
- `pip-audit` 扫描项目依赖：**No known vulnerabilities found**。
- 所有修改的 Python 文件均通过 `py_compile`。
- Alembic 迁移文件 `s7t8u9v0w1x2_add_user_token_version.py` 已创建。

> 第二轮审计后，公网/多租户场景仍需关注：沙盒逃逸纵深防御、终端容器权限最小化、CSP 策略补强。

