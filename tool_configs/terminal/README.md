# 云端沙盒终端

CygnusX 生信工具箱中的即用即毁隔离容器终端，支持用户挂载个人工作目录进行命令行操作。

## 目录结构

```
tool_configs/terminal/
├── README.md                 # 本文档
├── terminal_config.yaml      # 运行时配置（mtime 热重载，改完即生效）
├── terminal_images.yaml      # 可用镜像配置（mtime 热重载，前端镜像选择器数据源）
└── docker/
    ├── Dockerfile            # 沙盒终端镜像（Ubuntu 22.04 + ttyd + zsh/oh-my-zsh/oh-my-posh + 生信工具链）
    ├── bashrc                # 容器内 bash 环境（历史保留，当前默认 shell 为 zsh）
    └── zshrc                 # 容器内 zsh 环境（oh-my-zsh/oh-my-posh、欢迎信息、alias）
```

## 架构概览

```
浏览器 (xterm.js)                FastAPI 后端 (cygnusx-web)            Docker 沙盒容器
┌────────────────┐  WebSocket   ┌──────────────────────┐  aiohttp WS  ┌────────────────┐
│                │  subproto    │                      │  subproto     │                │
│  XTerminal.vue │  "tty"       │   terminal.py        │  "tty"        │   ttyd:7681    │
│  ┌──────────┐  │ ───────────> │   ┌───────────────┐  │ ───────────> │   ┌─────────┐  │
│  │ xterm.js │  │  text/bin    │   │ WebSocket 代理 │  │  ttyd协议    │   │  bash   │  │
│  └──────────┘  │ <─────────── │   │ (协议翻译层)   │  │ <─────────── │   └─────────┘  │
│                │  text/bin    │   └───────────────┘  │  ttyd协议    │                │
└────────────────┘              └──────────────────────┘              └────────────────┘
        │                                │                                      │
        │ GET /environments              │ Docker SDK (docker.sock)             │ bind mount ×3
        │ (镜像列表)                      ▼                                      ▼
        ▼                         ┌──────────────┐                   /home/cygnusx/{workspace,raw_data,temp}
  ImageSelector.vue               │ DockerManager│                            ↕
  (卡片选择器)                     │ (创建/销毁)   │                   /data/cygnusx/users/{uid}/{workspace,raw_data,temp}
  ResourceSettings.vue            └──────────────┘
  (资源设置)
```

### 网络拓扑

```
Docker Host
├── cygnusx-sandbox-net (external bridge)
│   ├── cygnusx-web          (加入此网络，经容器 DNS 直连终端容器)
│   └── cygnusx-term-xxxx    (终端沙盒容器，暴露内部端口 7681)
│
├── cygnusx_net (external bridge)
│   ├── cygnusx-web
│   ├── cygnusx-worker
│   ├── cygnusx-db
│   └── cygnusx-cache
│
├── app_net (internal bridge)
│   ├── cygnusx-web
│   └── cygnusx-nginx
│
└── data_net (internal bridge)
    ├── cygnusx-web
    ├── cygnusx-db
    └── cygnusx-cache
```

**关键设计**：`cygnusx-web` 容器同时加入 `cygnusx-sandbox-net` 和主栈网络，使其 WebSocket 代理可以通过 Docker DNS 解析终端容器名称（`ws://cygnusx-term-xxxx:7681/ws`），而无需经宿主机端口映射。本地开发时回退到 `ws://localhost:{host_port}/ws`。

## WebSocket 数据流详解

### 连接建立

```
1. 浏览器                         2. FastAPI                        3. ttyd
   │                                  │                                │
   │── POST /sessions ──────────────>│                                │
   │<─ {session_id, ws_url} ─────────│── docker run (创建容器) ──────>│
   │                                  │                                │ 容器启动
   │                                  │<─ (container_id, host_port) ──│ ttyd 就绪
   │<─ 201 Created ──────────────────│                                │
   │                                  │                                │
   │── WebSocket /sessions/{id}/ws ─>│                                │
   │   (subprotocol: "tty")           │── ws_connect ───────────────>│
   │                                  │   (protocols: ["tty"])         │ 子协议握手
   │<─ accept(subprotocol="tty") ────│<─ 连接建立 ──────────────────│
   │                                  │                                │
   │                                  │── "{\"columns\":80,\"rows\":24}" ──>│ JSON_DATA 握手
   │                                  │   （裸 JSON，首字节 '{' 即命令）       │ spawn bash
   │                                  │                                │
   │── {type:"resize",cols,rows} ──>│── "1{columns,rows}" ─────────>│ RESIZE_TERMINAL
   │                                  │                                │ PTY 尺寸更新
   │<─ "0<shell output>" ────────────│<─ "0..." ────────────────────│
   │   (去除前缀 "0")                 │                                │ prompt 显示
```

### ttyd 协议翻译

代理层（`terminal.py`）在浏览器和 ttyd 之间进行**协议前缀翻译**，使 xterm.js 无需感知 ttyd 协议细节。

**注意**：容器镜像使用的是 **ttyd 1.7.7**，其协议前缀与 1.6.x 不同，下表为 **ttyd 1.7.x 协议**：

| 方向 | 浏览器消息 | 代理翻译 | ttyd 消息 |
|------|-----------|---------|----------|
| 浏览器→ttyd | `"hello"` (文本) | 添加前缀 `0` | `"0hello"` (stdin 输入) |
| 浏览器→ttyd | `{type:"resize",cols:80,rows:24}` | 转为 ttyd resize 格式 | `"1{\"columns\":80,\"rows\":24}"` |
| 浏览器→ttyd | `{type:"ping"}` | **不转发**（仅维持浏览器→后端心跳） | - |
| 浏览器→ttyd | 初始握手 JSON | **直接发送裸 JSON**（第一个字节 `{` 即 JSON_DATA 命令） | `"{\"columns\":80,\"rows\":24}"` |
| 浏览器→ttyd | `<binary>` | 添加前缀 `\x00` | `\x00<binary>` |
| ttyd→浏览器 | `"0<output>"` (文本) | 去除前缀 `0` | `<output>` |
| ttyd→浏览器 | `"1<title>"` (窗口标题) | **丢弃**（不写入 xterm.js） | - |
| ttyd→浏览器 | `"2<preferences>"` (偏好设置) | **丢弃**（不写入 xterm.js） | - |
| ttyd→浏览器 | `\x00<binary>` (二进制) | 去除前缀 `\x00` | `<binary>` |

**ttyd 1.7.x 消息类型前缀**：

| 前缀 | 方向 | 含义 | 说明 |
|------|------|------|------|
| `0` | 客户端 → 服务端 | INPUT | 终端键盘输入 |
| `1` | 客户端 → 服务端 | RESIZE_TERMINAL | 窗口尺寸变更 |
| `2` | 客户端 → 服务端 | PAUSE | 暂停输出 |
| `3` | 客户端 → 服务端 | RESUME | 恢复输出 |
| `{` (`0x7B`) | 客户端 → 服务端 | JSON_DATA | 初始握手 / 元数据；**ttyd 1.7.x 必需，否则不会 spawn shell** |
| `0` | 服务端 → 客户端 | OUTPUT | 终端输出（唯一需要写入 xterm.js 的消息） |
| `1` | 服务端 → 客户端 | SET_WINDOW_TITLE | 窗口标题，如 `bash (sandbox)` |
| `2` | 服务端 → 客户端 | SET_PREFERENCES | 终端偏好设置，如字体、字号 JSON |

### 前端消息处理

```
xterm.js term.onData()
  │
  ├── 普通按键 ──> send(string) ──> WebSocket.send(text) ──> 代理添加 "0" 前缀 ──> ttyd
  │
  └── 窗口 resize ──> send(JSON{type:"resize"}) ──> 代理翻译 ──> ttyd "1{...}"

WebSocket.onmessage()
  │
  ├── ArrayBuffer ──> new Uint8Array(data) ──> term.write(Uint8Array) ──> xterm.js 渲染
  │
  └── string ──> term.write(string) ──> xterm.js 渲染
```

- **binaryType** 设为 `arraybuffer`，二进制帧转为 `Uint8Array` 直接传给 xterm.js
- **心跳**：每 30 秒发送 `{type: "ping"}`，用于维持浏览器→后端 WebSocket；后端不再转发给 ttyd（ttyd 1.7.x 中 `'3'` 是 RESUME，误发会干扰协议）
- **自动重连**：指数退避（1s → 2s → 4s → 8s → 16s），最多 5 次

## 容器生命周期

### 创建流程

```
用户点击「云端沙盒终端」
  │
  ▼
TerminalView.vue ──> store.fetchImages() 拉取可用镜像列表
  │
  ▼
用户选择镜像（ImageSelector.vue 卡片）
  │
  ▼
用户调整资源（ResourceSettings.vue 滑块：内存 / CPU）
  │
  ▼
TerminalView.vue ──> store.createSession(image_id)
  │
  ▼
POST /api/v1/terminal/sessions  (body 中携带 image_id 与可选 resources)
  │
  ├── JWT 鉴权 (decode_token)
  ├── 配额检查 (max_sessions_per_user)
  ├── 镜像解析：从 terminal_images.yaml 读取对应 image 配置
  │
  ▼
TerminalService.create_session()
  │
  ├── 生成 session_id: "term_" + 8位随机字符
  ├── 创建 TerminalSession 实体 (status: CREATING, image_id: 所选镜像)
  │
  ▼
TerminalDockerManager.create_container(image, registry_prefix, resources)
  │
  ├── 分配随机端口 (port_range: 20000-30000)
  ├── 创建宿主机 workspace / raw_data / temp 目录
  ├── Docker SDK: containers.run()
  │     ├── 镜像: 由 terminal_images.yaml 中 image 字段决定（支持 registry_prefix 前缀）
  │     ├── 容器名: cygnusx-term-{uid[:8]}-{session_id}  (≤63字符 DNS 标签)
  │     ├── 网络: cygnusx-sandbox-net
  │     ├── 用户: 1000:1000 (非 root)
  │     ├── 安全: read_only=True, cap_drop=ALL, no-new-privileges
  │     ├── 资源: 镜像默认资源 / 用户传入资源 / terminal_config.yaml 默认值 三者合并
  │     │        （memory_mb、cpu_cores 会按用户所选或默认值写入 Docker 资源限制）
  │     ├── 环境变量: 镜像自定义 env + USER_ID/SESSION_ID/HOME/ZDOTDIR/XDG_CACHE_HOME/OMP_CACHE_DIR/ZSH_CACHE_DIR
  │     ├── tmpfs: /tmp (noexec), /home/cygnusx/.cache (noexec，承载 shell/oh-my-posh 缓存)
  │     ├── 挂载: workspace → /home/cygnusx/workspace (rw)
  │     │          raw_data → /home/cygnusx/raw_data (rw)
  │     │          temp     → /home/cygnusx/temp (rw)
  │     ├── 端口: 7681/tcp → host_port
  │     ├── auto_remove: True (退出后自动删除)
  │     └── healthcheck: wget --spider localhost:7681
  │
  ├── 返回 (container_id, host_port)
  │
  ▼
更新 TerminalSession (status: RUNNING, host_port, container_id, image_id)
  │
  ▼
返回 {session_id, ws_url, status, image_id, image_name}
```

### 销毁流程

```
用户点击「销毁」/ 空闲超时 / 会话过期
  │
  ▼
DELETE /api/v1/terminal/sessions/{session_id}
  │
  ▼
TerminalService.delete_session()
  │
  ├── DockerManager.destroy_container()
  │     └── container.stop(timeout=5)  →  auto_remove=True  →  容器消失
  ├── 释放端口
  │
  ▼
DomainService.destroy() → status: STOPPED → 删除数据库记录
```

### 自动回收

Celery Beat 定时调用 `TerminalService.recycle_expired()`：
- 扫描 `last_activity` 超过 `idle_timeout`（默认 30 分钟）的会话
- 逐一停止容器并删除数据库记录

### 会话状态机

```
CREATING ──> RUNNING ──> IDLE ──> RUNNING (用户操作)
   │            │          │
   │            │          └──> STOPPING ──> STOPPED (超时回收)
   │            │
   │            └──> STOPPING ──> STOPPED (用户销毁)
   │
   └──> ERROR (容器启动失败)
```

## 管理后台架构

管理员可通过独立后台查看并强制销毁所有活跃沙盒终端会话：

```
浏览器 (管理后台)
┌─────────────────────────────┐
│ AdminTerminalManagementView │
│ (NDataTable + 销毁按钮)      │
└──────────────┬──────────────┘
               │ GET /admin/terminals?include_stats={bool}
               │ DELETE /admin/terminals/{session_id}
               ▼
      FastAPI /api/v1/admin/terminals
               │
               ├── AdminRequired (RBAC 管理员鉴权)
               │
               ▼
      TerminalService.list_all_sessions()
               │
               ├── SQLAlchemy: 查询所有活跃会话
               ├── SQLAlchemy: 批量查询用户名
               ├── TerminalImagesConfig: 解析镜像名称
               ├── DockerManager.get_container_stats() (可选)
               │        └── docker SDK: container.stats(stream=False)
               │
               ▼
      返回 AdminTerminalSessionDTO[]
```

### 管理员列表字段

| 字段 | 来源 | 说明 |
|------|------|------|
| 用户 | `UserModel.username` | 用户名，不存在则回退 `user_id[:8]` |
| 会话 ID | `TerminalSession.session_id` | 前端展示与操作键 |
| 容器名称 | 运行时计算 | `cygnusx-term-{user_id[:8]}-{session_id}` |
| 已使用时长 | 运行时计算 | `now - created_at`（秒） |
| 资源配额 | `terminal_config.yaml` / `default_resources` | CPU 核数 / 内存 MB / PID 限制 |
| 实时占用 | Docker SDK `stats` | CPU%、内存使用率、进程数；默认关闭，通过开关按需拉取 |
| 操作 | 管理员主动触发 | 二次确认后调用 `DELETE /admin/terminals/{session_id}` |

### 管理员强制销毁流程

```
管理员点击「销毁」
  │
  ▼
DELETE /api/v1/admin/terminals/{session_id}
  │
  ▼
TerminalService.admin_delete_session(session_id)
  │
  ├── 跳过用户归属校验（管理员可销毁任意会话）
  ├── DockerManager.destroy_container() → stop + 释放端口
  ├── TerminalDomainService.destroy() → 删除数据库记录
  │
  ▼
返回 {deleted: true}
```

**安全注意**：管理端路由使用 `AdminRequired` 依赖，仅具有管理员角色的 JWT 才能访问；普通用户调用会返回 403。

## 安全策略

| 措施 | 实现方式 | 代码位置 |
|------|---------|---------|
| 根文件系统只读 | `read_only=True`，仅 workspace 和 tmpfs 可写 | `docker_manager.py` |
| 丢弃所有 Linux capabilities | `cap_drop=["ALL"]` | `docker_manager.py` |
| 禁止权限提升 | `security_opt=["no-new-privileges:true"]` | `docker_manager.py` |
| 容器内非 root | `user="1000:1000"` | `docker_manager.py` |
| 内存硬限制 | `mem_limit` + `memswap_limit`（禁止 swap 绕过） | `docker_manager.py` |
| CPU 配额 | `cpu_quota = cpu_cores * 100000`, `cpu_period = 100000` | `docker_manager.py` |
| 进程数限制 | `pids_limit=100`（防 fork bomb） | `docker_manager.py` |
| 目录隔离 | 仅挂载用户个人 `/data/cygnusx/users/{uid}/workspace` / `raw_data` / `temp` | `docker_manager.py` |
| 即用即毁 | `auto_remove=True`，退出后容器自动删除 | `docker_manager.py` |
| JWT 鉴权 | WebSocket 连接须携带有效 access_token | `terminal.py` |
| 会话归属校验 | `session.user_id == token.sub` 防止越权 | `terminal.py` |
| 配额限制 | `max_sessions_per_user` 防止资源滥用 | `terminal_service.py` |
| WebSocket 鉴权 | 无效 token 立即 `close(1008)` | `terminal.py` |

## 配置说明

### 运行时配置

所有参数集中在 `tool_configs/terminal/terminal_config.yaml`，由 `TerminalConfigManager` 按文件 mtime 热重载（无需重启后端）：

| 配置段 | 关键参数 | 默认值 | 说明 |
|--------|---------|--------|------|
| `enabled` | - | `true` | 功能总开关 |
| `image` | `name` / `tag` | `cygnusx-sandbox-terminal:v0.0.2dev` | 容器镜像 |
| `image` | `pull_policy` | `IfNotPresent` | 镜像拉取策略 |
| `default_resources` | `memory_mb` | `512` | 默认内存上限 (MB) |
| `default_resources` | `cpu_cores` | `1.0` | 默认 CPU 核数 |
| `default_resources` | `pid_limit` | `100` | 默认进程数上限 |
| `default_resources` | `tmpfs_size_mb` | `100` | tmpfs 大小 (MB) |
| `max_resources` | `memory_mb` | `4096` | 可申请最大内存 |
| `max_resources` | `cpu_cores` | `4.0` | 可申请最大 CPU |
| `lifecycle` | `idle_timeout` | `1800` (30min) | 空闲超时自动销毁 |
| `lifecycle` | `disconnect_timeout` | `300` (5min) | 断连后保留时间 |
| `lifecycle` | `max_session_duration` | `7200` (2h) | 单会话最大存活时间 |
| `lifecycle` | `max_sessions_per_user` | `2` | 单用户最大并发会话 |
| `security` | `read_only_root` | `true` | 只读根文件系统 |
| `security` | `cap_drop_all` | `true` | 丢弃所有 capabilities |
| `security` | `no_new_privileges` | `true` | 禁止权限提升 |
| `network` | `name` | `cygnusx-sandbox-net` | Docker 隔离网络 |
| `network` | `mode` | `bridge` | 网络模式 |
| `storage` | `workspace_base` | `/data/cygnusx/users` | 用户目录基路径 |
| `port_range` | `base` / `max` | `20000` / `30000` | ttyd 宿主机端口分配范围 |

### 镜像配置

可用沙盒镜像定义在 `tool_configs/terminal/terminal_images.yaml`，同样支持 mtime 热重载：

| 配置段 | 关键参数 | 默认值 | 说明 |
|--------|---------|--------|------|
| `version` | - | `"1.0"` | 配置文件版本 |
| `registry_prefix` | - | `""` | 镜像仓库前缀；设置后非绝对路径镜像自动拼接前缀 |
| `default_image` | - | `"base"` | 用户未选择时的默认镜像 ID |
| `images[].id` | - | - | 镜像唯一标识（前端选择值、落库存储） |
| `images[].name` | - | - | 前端显示名称 |
| `images[].description` | - | - | 前端卡片描述 |
| `images[].image` | - | - | Docker 镜像全名，如 `cygnusx-sandbox-terminal:v0.0.2dev` |
| `images[].tags` | - | `[]` | 前端标签展示 |
| `images[].icon` | - | `"🔧"` | 前端卡片图标 |
| `images[].resources` | `memory_mb` / `cpu_cores` / `pid_limit` | - | 镜像默认资源；创建容器时优先于 `terminal_config.yaml` 的 `default_resources` |
| `images[].env` | - | `[]` | 注入容器的环境变量（`name` / `value`） |
| `images[].enabled` | - | `true` | 是否在前端展示并允许选择 |

配置加载器 (`TerminalConfigManager`) 特性：
- 文件不存在 → 返回内置默认配置（仅含 base 镜像）
- YAML 解析失败 → 回退默认配置
- 字段缺失 → Pydantic `extra="ignore"` 忽略未知字段，缺失字段用默认值
- mtime 变更 → 自动重新解析

### 新增镜像步骤

1. 在 `tool_configs/terminal/docker/` 下新增 `Dockerfile.xxx` 并构建镜像：
   ```bash
   docker build -t cygnusx-sandbox-rnaseq:v0.0.2dev -f tool_configs/terminal/docker/Dockerfile.rnaseq tool_configs/terminal/docker/
   ```
2. 在 `tool_configs/terminal/terminal_images.yaml` 中增加镜像条目并设置 `enabled: true`。
3. 刷新前端页面，`GET /terminal/environments` 会自动返回新镜像，前端镜像选择器即时展示。
4. 无需修改前端代码或重启后端。

## 挂载路径

| 宿主机路径 | 容器内路径 | 权限 | 持久化 |
|-----------|-----------|------|--------|
| `/data/cygnusx/users/{uid}/workspace` | `/home/cygnusx/workspace` | `rw` | 是 |
| `/data/cygnusx/users/{uid}/raw_data` | `/home/cygnusx/raw_data` | `rw` | 是 |
| `/data/cygnusx/users/{uid}/temp` | `/home/cygnusx/temp` | `rw` | 是 |
| - | `/tmp` | `rw,noexec,nosuid` | 否 (tmpfs) |
| - | `/home/cygnusx/.cache` | `rw,noexec,nosuid` | 否 (tmpfs，`XDG_CACHE_HOME` / `OMP_CACHE_DIR`) |

**约定**：三个系统目录由 `FileService.ensure_default_directories()` 懒初始化，物理路径与沙盒挂载路径保持一致；容器启动时也会自动 `mkdir` + `chown`，因此从新建用户到首次开沙盒无需手动创建目录。

## 预装工具

容器镜像内预装（`tool_configs/terminal/docker/Dockerfile`）：

- **基础**: wget, curl, vim, nano, htop, btop, tree, jq, ca-certificates, git, unzip, bash-completion
- **Shell**: zsh + oh-my-zsh + oh-my-posh（默认 shell 为 zsh）
- **生信**: samtools, bcftools, bedtools, fastqc, seqkit
- **Python**: numpy, pandas, biopython, pysam
- **终端**: ttyd 1.7.7 (Web 终端服务，监听 7681 端口)

启动命令：

```dockerfile
CMD ["ttyd", "-p", "7681", "-W", "-t", "fontSize=14", "-t", "fontFamily=JetBrains Mono", "zsh"]
```

## 构建与部署

```bash
# 构建沙盒终端镜像
docker build -t cygnusx-sandbox-terminal:v0.0.2dev tool_configs/terminal/docker/

# 或通过 make 自动化（含清理 + 前端构建 + 服务重启）
make docker-reload
```

`make docker-reload` 执行顺序：
1. `docker-network` — 创建 `cygnusx_net` + `cygnusx-sandbox-net` 外部网络（幂等）
2. 清理残留 `cygnusx-*` 容器（防名称冲突）
3. 构建 `cygnusx-sandbox-terminal:v0.0.2dev` 镜像
4. 构建前端 (`npm run build`)
5. 启动主栈 + Worker 栈
6. 检查 Alembic 迁移状态

### 用途镜像

除基础镜像外，终端提供三种按用途划分的派生镜像。它们均继承
`cygnusx-sandbox-terminal:v0.0.2dev` 的 ttyd、zsh 和非 root 运行环境，并在安装完成后切回 UID 1000。

| ID | Dockerfile | 镜像名 | 默认资源 | 主要工具 |
|---|---|---|---|---|
| `scrna` | `docker/Dockerfile.scrna` | `cygnusx-sandbox-scrna:v0.0.2dev` | 4 GB / 2 核 | scanpy、anndata、leiden、Harmony、Scrublet、scVelo |
| `gatk` | `docker/Dockerfile.gatk` | `cygnusx-sandbox-gatk:v0.0.2dev` | 4 GB / 4 核 | GATK4、PLINK1.9、PLINK2、tabix |
| `ggplot2` | `docker/Dockerfile.ggplot2` | `cygnusx-sandbox-ggplot2:v0.0.2dev` | 1 GB / 1 核 | R、ggplot2、tidyverse、ggrepel、cowplot、plotnine、中文字体 |
| `rnaseq` | `docker/Dockerfile.rnaseq` | `cygnusx-sandbox-rnaseq:v0.0.2dev` | 4 GB / 4 核 | hisat2、salmon、kallisto、featureCounts、DESeq2、tximport |
| `assembly` | `docker/Dockerfile.assembly` | `cygnusx-sandbox-assembly:v0.0.2dev` | 8 GB / 4 核 | SPAdes、flye、QUAST、BUSCO、minimap2 |
| `metagenomics` | `docker/Dockerfile.metagenomics` | `cygnusx-sandbox-metagenomics:v0.0.2dev` | 8 GB / 4 核 | kraken2、bracken、centrifuge、fastp、MultiQC |

构建顺序必须先构建基础镜像：

```bash
docker build -t cygnusx-sandbox-terminal:v0.0.2dev tool_configs/terminal/docker/
docker build -t cygnusx-sandbox-scrna:v0.0.2dev -f tool_configs/terminal/docker/Dockerfile.scrna tool_configs/terminal/docker/
docker build -t cygnusx-sandbox-gatk:v0.0.2dev -f tool_configs/terminal/docker/Dockerfile.gatk tool_configs/terminal/docker/
docker build -t cygnusx-sandbox-ggplot2:v0.0.2dev -f tool_configs/terminal/docker/Dockerfile.ggplot2 tool_configs/terminal/docker/
docker build -t cygnusx-sandbox-rnaseq:v0.0.2dev -f tool_configs/terminal/docker/Dockerfile.rnaseq tool_configs/terminal/docker/
docker build -t cygnusx-sandbox-assembly:v0.0.2dev -f tool_configs/terminal/docker/Dockerfile.assembly tool_configs/terminal/docker/
docker build -t cygnusx-sandbox-metagenomics:v0.0.2dev -f tool_configs/terminal/docker/Dockerfile.metagenomics tool_configs/terminal/docker/
```

每个镜像构建后，使用下列命令验证关键工具与普通用户身份：

```bash
docker run --rm --entrypoint sh cygnusx-sandbox-scrna:v0.0.2dev -lc 'id -u; python3 -c "import scanpy, scvelo"'
docker run --rm --entrypoint sh cygnusx-sandbox-gatk:v0.0.2dev -lc 'id -u; gatk --version; plink --version; plink2 --version'
docker run --rm --entrypoint sh cygnusx-sandbox-ggplot2:v0.0.2dev -lc 'id -u; R --version; R -q -e "library(ggplot2)"; python3 -c "import plotnine"'
docker run --rm --entrypoint sh cygnusx-sandbox-rnaseq:v0.0.2dev -lc 'id -u; hisat2 --version; salmon --version; kallisto version; featureCounts -v; R -q -e "library(DESeq2); library(tximport)"'
docker run --rm --entrypoint sh cygnusx-sandbox-assembly:v0.0.2dev -lc 'id -u; spades.py --version; flye --version; quast.py --version; busco --version; minimap2 --version'
docker run --rm --entrypoint sh cygnusx-sandbox-metagenomics:v0.0.2dev -lc 'id -u; kraken2 --version; bracken -v; centrifuge --version; fastp --version; multiqc --version'
```

`terminal_images.yaml` 已注册上述镜像，配置加载器检测 mtime 后自动热加载；镜像必须先在运行终端服务的 Docker 主机上构建或拉取，再允许用户创建会话。
组装与宏基因组镜像默认申请 8 GB 内存，部署前请确保 `terminal_config.yaml` 的 `max_resources.memory_mb` 不低于 8192（当前配置为 32000）。Kraken2 / Bracken 数据库不会内置到宏基因组镜像中，需放到用户 `workspace` 或 `raw_data` 后在命令中通过 `--db` 指定。

## 后端代码分布

| 层 | 路径 | 作用 |
|----|------|------|
| 配置加载 | `src/cygnusx/tools/terminal/config.py` | YAML ConfigManager（mtime 热重载，Pydantic 模型）；含运行时配置与镜像配置 |
| API 路由 | `src/cygnusx/api/v1/terminal.py` | REST 端点 + WebSocket 双向代理（含 ttyd 协议翻译）；新增 `GET /environments` |
| API 路由 | `src/cygnusx/api/v1/admin/terminals.py` | 管理员查看/销毁所有终端会话 |
| 应用服务 | `src/cygnusx/application/services/terminal_service.py` | 会话编排（创建/销毁/心跳/回收）；按 image_id 选择镜像配置 |
| DTO | `src/cygnusx/application/schemas/terminal.py` | 请求/响应模型；含 `TerminalImageDTO` / `TerminalImagesConfigDTO` |
| 域实体 | `src/cygnusx/domain/terminal/entities.py` | `TerminalSession` 聚合根（新增 `image_id` 字段） |
| 域值对象 | `src/cygnusx/domain/terminal/value_objects.py` | `TerminalStatus` 状态枚举 |
| 域服务 | `src/cygnusx/domain/terminal/services.py` | 会话状态流转 |
| 域仓储接口 | `src/cygnusx/domain/terminal/repositories.py` | `ITerminalSessionRepository` |
| 容器管理 | `src/cygnusx/infrastructure/terminal/docker_manager.py` | Docker SDK 生命周期管理；按镜像配置创建容器 |
| 基础设施入口 | `src/cygnusx/infrastructure/terminal/__init__.py` | `TerminalDockerManager` 单例 |
| DB 模型 | `src/cygnusx/infrastructure/database/models/terminal.py` | `terminal_sessions` 表（新增 `image_id` 列） |
| DB 仓储 | `src/cygnusx/infrastructure/database/repositories/terminal_repository.py` | SQLAlchemy 异步实现 |
| 迁移 | `alembic/versions/3e76881cadbc_add_image_id_to_terminal_sessions.py` | 新增 `image_id` 列的迁移 |

## 前端代码分布

| 路径 | 作用 |
|------|------|
| `frontend/src/views/BioTools/TerminalView.vue` | 终端页面视图（镜像选择 / 创建 / 销毁 / 全屏 / 倒计时） |
| `frontend/src/views/AdminTerminalManagementView.vue` | 管理后台：全量终端列表、实时占用、强制销毁 |
| `frontend/src/components/terminal/ImageSelector.vue` | 镜像卡片选择器（图标、名称、描述、标签、资源） |
| `frontend/src/components/terminal/ResourceSettings.vue` | 资源设置滑块（内存 256–4096 MB / CPU 0.5–4.0 核） |
| `frontend/src/components/terminal/XTerminal.vue` | xterm.js 封装组件（主题、resize 同步、初始尺寸上报） |
| `frontend/src/composables/useTerminalWebSocket.ts` | WebSocket 连接管理（重连、心跳、binary 帧处理） |
| `frontend/src/stores/terminal.ts` | Pinia 状态管理（会话列表、当前会话、镜像列表、选中镜像） |
| `frontend/src/api/terminal.ts` | REST API 封装（CRUD + 镜像列表） |
| `frontend/src/types/terminal.ts` | TypeScript 类型定义（含 `TerminalImage`） |

## Docker Compose 网络配置

`cygnusx-web` 容器加入 4 个网络：

```yaml
networks:
  - app_net              # 内部网络：与 nginx 通信
  - data_net             # 内部网络：与 db / cache 通信
  - cygnusx_net          # 外部跨栈网络：与独立 worker 栈互通
  - cygnusx-sandbox-net  # 外部沙盒网络：经容器 DNS 直连终端容器 ttyd 端口
```

`cygnusx-sandbox-net` 为 external 网络，由 `make docker-network` 在部署前创建：

```makefile
docker-network:
	@docker network create cygnusx_net 2>/dev/null || true
	@docker network create cygnusx-sandbox-net 2>/dev/null || true
```

## 容器命名规则

容器名称格式：`cygnusx-term-{user_id[:8]}-{session_id}`

- `user_id[:8]`：UUID 前 8 位
- `session_id`：`term_` + 8 位随机字符（如 `term_abc12345`）
- 示例：`cygnusx-term-cb79a200-term_abc12345`（35 字符）

**约束**：容器名用于 Docker DNS 解析，DNS 标签最大 63 字符，当前格式 ≤ 40 字符。
