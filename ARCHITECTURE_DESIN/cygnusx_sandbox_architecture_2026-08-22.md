# CygnusX 沙箱增强架构（安全基线与 Capability 路由）

> **时点说明**：本文件为 2026-09-20 时点的设计/施工快照，所述计划已执行或已演进，部分引用（路径、行号）已失效；当前实现以代码为准。

**版本**：v1.1  
**日期**：2026-09-20
**状态**：阶段 0–2 代码已落地；生产 Docker/egress 真机验收待执行；浏览器/文档工具待后续阶段实现

## 1. 目标与边界

本设计在不替换现有 OmicStudio 编排体系的前提下，强化容器隔离，并引入由平台控制的运行能力（capability）到镜像的映射。它覆盖 Studio 会话沙箱；旧版 `/api/v1/sandbox` 继续保持兼容，不接入新的浏览器/文档能力。

目标：

- 每个 Studio 会话仍只有一个独立 Docker 容器和一个工作区。
- 普通数据分析继续使用代码能力镜像；浏览器和文档能力只能分配到独立镜像。
- 用户请求不能绕过 Agent 授权直接取得浏览器或文档能力。
- 容器默认使用硬 CPU、内存、PID、Linux capability 和只读根文件系统限制。
- 容器控制面仍为宿主经工作区 Unix Socket 连接 sandbox-agent；不对外发布 agent 端口，也不把平台密钥带入容器。

非目标：

- 本阶段不实现 Playwright 浏览器操作、LibreOffice 文档转换、noVNC 或容器内 MCP Server。
- 本阶段不把 Docker 容器宣传为 VM 级强隔离；不可信代码和高敏数据仍需要评估 gVisor、Kata 或 MicroVM。

## 2. 总体架构

```text
Vue Studio UI / Agent Chat
          │ JWT + Studio REST/SSE
          ▼
FastAPI Studio API ─── Agent policy (studio.sandbox_capabilities)
          │                         │
          │ creates session metadata │ rejects unauthorized escalation
          ▼                         ▼
ChatSession.sandbox_meta: {image, sandbox_capabilities}
          │
          ▼
StudioSandboxManager
  ├─ resolve configured image by requested capability set
  ├─ create/rebuild one container per session
  ├─ mount /workspace rw and /data/platform ro (current user only)
  ├─ communicate with sandbox-agent over /workspace/.agent.sock
  └─ keep activity and busy leases in Redis
          │
          ├── code → configured base/bio image
          └── code,browser,document → cygnusx-sandbox-browser-office
```

## 3. Capability 和镜像选择

### 3.1 运行能力

允许值固定为：`code`、`browser`、`document`。

- `code` 是基础能力，所有请求和所有镜像定义都会自动包含它。
- 浏览器或文档请求仅在 Agent 的 `features.studio.sandbox_capabilities` 明确授权时可创建。
- 未授权请求返回业务错误；客户端参数不能提升会话权限。

> 注意：当前代码在 Agent 未配置 `sandbox_capabilities` 时默认放行 `code`/`browser`/`document` 三种能力（`api/v1/studio.py:379-381`），与本节"明确授权才可创建"的设计契约不一致，属待确认的实现偏差。
- `sandbox_meta.sandbox_capabilities` 专门保存运行时沙盒能力，不能和已有的 `sandbox_meta.capabilities` 混用；后者用于 MCP/Skill 的渐进加载状态。

### 3.2 配置

`data/ai/studio.yaml` 的 `studio.images` 定义可部署镜像：

```yaml
images:
  bio:
    image: cygnusx-sandbox-bio:v0.0.2dev
    capabilities: [code]
  browser-office:
    image: cygnusx-sandbox-browser-office:v0.0.2dev
    capabilities: [code, browser, document]
```

创建会话时，代码能力沿用 Agent 配置的 `studio.image` 或默认镜像；请求浏览器/文档能力时，平台选择覆盖请求能力且能力集合最小的已配置镜像。镜像配置缺失时拒绝创建，不回退到普通代码镜像。

## 4. 容器安全基线

`StudioSandboxManager.ensure_running()` 创建容器时设置：

| 控制项 | 当前设置 | 目的 |
| --- | --- | --- |
| CPU | `nano_cpus = cpu × 1_000_000_000` | 使用硬 CPU 上限，不再仅使用相对 `cpu_shares` |
| 内存 | `mem_limit` | 限制每会话内存 |
| PID | `pids_limit`，默认 512 | 限制 fork bomb 和进程滥用 |
| Linux capabilities | `cap_drop=["ALL"]` | 删除容器默认 capability |
| 特权提升 | `security_opt=["no-new-privileges:true"]` | 阻止 setuid/file capability 取得新权限 |
| Seccomp | 配置为 `default` 时 `_seccomp_security_opt("default")` 返回 `None`，不下发显式 `security_opt` 条目（`manager.py:73-86`） | Docker daemon 自动应用内置默认 profile，语义等价于 `seccomp=default`；`docker inspect` 看不到 `seccomp=default` 条目 |
| 运行用户 | `user=10001:10001`，镜像 `USER 10001` | sandbox-agent 和会话进程不以 root 运行 |
| 根文件系统 | 默认 `read_only=true` | 避免镜像层被会话代码篡改 |
| 临时写入 | `/tmp` tmpfs，默认 512 MiB，`nosuid,nodev,noexec` | 为 Chromium、LibreOffice 与临时文件保留受限可写空间 |
| 工作区 | `/workspace` 读写 bind mount | 唯一会话持久化写入面 |
| 平台数据 | `/data/platform` 只读、仅当前用户目录 | 防止跨租户读取和修改 |
| 网络 | 默认 `none`；可选 per-session internal network + egress proxy | 控制面不依赖网络，白名单模式必须由代理强制执行 |
| 工作区配额 | 默认 10 GiB；agent 30 秒统计并保护写操作 | 跨文件系统兜底方案；XFS project quota 可用时升级为硬配额 |

容器复用时会重新校验网络与安全基线。发现旧容器缺少硬 CPU、PID、只读根、`cap_drop=ALL` 或 `no-new-privileges` 时，管理器停止并删除它，然后以当前基线重建，避免旧容器绕过新策略。

### 4.1 统一运行身份与挂载目录授权

沙盒镜像、分析运行时镜像和聊天沙盒统一使用数值身份 `UID=10001`、`GID=10001`，
组名为 `cygnusx-sandbox`。镜像构建阶段负责创建该用户/组，并将镜像内的
`/workspace`、缓存目录和 agent 文件设置为 `10001:10001`；运行时注册表同步记录
`runtime_uid`、`runtime_gid` 和 `runtime_group`，供编排器和验收工具核对。

必须区分镜像层权限与挂载层权限：Docker bind mount、named volume 或 Kubernetes
volume 会覆盖镜像中的目录及属主，镜像 Dockerfile 中的 `chown` 对挂载源无效。因此，
`StudioSandboxManager`、`SandboxPool`、`ScratchVolumeManager` 以及其他运行时编排器在创建容器前都必须预创建并授权
挂载目录。`workspace/output`、日志和临时交付目录至少对 `cygnusx-sandbox` 组可写，
`workspace/input` 按数据策略只读；容器始终以 `10001:10001` 运行，不通过 root 运行时
修复权限。

Kubernetes 部署使用 `runAsUser: 10001`、`runAsGroup: 10001` 和适用的 `fsGroup: 10001`；
Docker host bind mount 则由宿主编排器在启动前执行 `chown 10001:10001` 或等价的组/ACL
授权。启动前写入探针必须检查实际 mount source、owner、group 和 mode，权限不符合时拒绝
执行并给出可定位的审计信息。该规则是防止 `/workspace/output`、`/tmp/chat_output`
出现 root:root、`0755` 导致 uid 10001 无法交付产物的必要基线。

挂载源路径必须同时被 Web 编排进程和 Docker daemon 看见。生产默认使用
`${STORAGE_PATH}/.sandbox-pool`（`SANDBOX_POOL_HOST_DIR`），而不是 Web 容器私有的
`/tmp`。若控制面在容器内创建了 daemon 不可见的 `/tmp/cygnusx-sandbox-*`，Docker 会
自动补建宿主源目录并赋予 `root:root 0755`，即使 sandbox 镜像内的用户和 `chown` 完全
正确，运行时仍会得到 `PermissionError`。

沙盒池收养旧 warm 容器时还必须重新检查 `/tmp/chat_output`、`/workspace/output` 和
`/workspace/input` 的实际 bind mount source。若 source 缺失、不是 `10001:10001` 且不可
组/其他用户写入，容器不得继续复用，必须销毁并按当前挂载契约重建。原因是 bind mount
会遮蔽镜像层目录，单独重建镜像无法修复已经运行容器中的 `root:root 0755` 挂载目录。

镜像构建使用 BuildKit cache mount 保留 conda package cache 和 pip cache；依赖层不应反复
执行 `mamba clean --all` 或关闭 pip cache，否则每次依赖变更都会重新下载大型科学计算包。

## 5. 独立 browser-office 镜像

`deploy/studio/browser-office.Dockerfile` 从生信镜像构建，额外提供 Chromium、Playwright、LibreOffice、`python-docx` 和 `python-pptx`。它只有在 capability 路由选择时才会启动；普通 Studio 会话不承担额外体积和浏览器攻击面。

镜像继续使用现有 sandbox-agent/UDS 启动方式。浏览器进程不得公开调试端口；实施 Playwright 工具时应由 agent 在容器内维护浏览器会话，并通过现有 UDS API 返回受限的文本、截图和产物。

构建命令：

```bash
bash deploy/studio/build.sh
```

该命令按顺序构建 base、bio、browser-office 三个镜像。部署前应将 `studio.images.*.image` 标签与实际推送的镜像标签同步。

## 6. 后续阶段

1. **Browser MVP**：在 sandbox-agent 添加 URL 校验、导航、截图、点击和填写接口；所有调用先由 Studio 工具路由鉴权并写审计日志。
2. **Document MVP**：以 `python-docx`、`openpyxl`、`python-pptx` 生成文档，LibreOffice 仅用于受控 headless 转换；输入和输出必须限制在 `/workspace`。
3. **网络与审计验证**：以集成测试验证 `none` 模式无出站、白名单模式仅经代理访问允许域名，并记录会话、调用者、能力、工具、策略结果、资源峰值和回收原因。
4. **资源与运行时增强**：补充硬磁盘配额、OOM/清理告警、镜像签名/漏洞扫描；高风险场景评估更强隔离运行时。

## 7. 验收清单

- [x] Studio 配置可声明镜像、能力和安全参数。
- [x] capability 请求受 Agent 配置授权，未授权时拒绝。
- [x] 新容器带硬 CPU、内存、PID、cap drop、no-new-privileges、只读根和 `/tmp` tmpfs。
- [x] 不符合新基线的旧容器不会被复用。
- [x] browser-office 使用独立 Dockerfile 和构建目标。
- [x] 生命周期审计事件和 quota_exceeded 事件框架已接入。
- [ ] browser/document UDS 工具和前端面板。
- [ ] Docker 真机和白名单出口集成验证。

## 8. 安全施工版更新（2026-08-22）

本节记录《CygnusX沙箱安全加固实施手册_Codex施工版》的最新落地状态。

### 8.1 阶段 0：容器加固标准件

Studio 容器现在显式设置：

- `security_opt=["no-new-privileges:true"]`；seccomp 配置为 `default` 时 `_seccomp_security_opt("default")` 返回 `None`（`manager.py:73-86`），不下发显式条目，由 Docker daemon 自动应用内置默认 profile（语义等价，`docker inspect` 看不到 `seccomp=default` 条目）。
- `user=10001:10001`；镜像本身的 `USER 10001` 与编排参数双重约束。
- `nano_cpus`、`mem_limit`、`pids_limit`、`cap_drop=["ALL"]`、只读根文件系统和 `/tmp` tmpfs。
- 工作区创建时优先 `chown 10001:10001`，无权限时才退化为目录权限放宽，以保持本地开发环境可用。
- 容器复用时校验 `Config.User`、`HostConfig.SecurityOpt`、`ReadonlyRootfs`、`CapDrop`、`NanoCpus` 和 `PidsLimit`；不符合基线的旧容器会被停止、删除并重建。

**宿主探测结果**：当前执行环境无法访问 `/var/run/docker.sock`（Docker CLI 返回 `permission denied`），因此未能确认生产 daemon 的实际 `Storage Driver`、`SeccompProfile` 或运行中容器 `Config.User`。代码级默认值是显式 `seccomp=default` 与 `10001:10001`，生产验收仍必须执行手册中的 `docker inspect` 检查。

**browser-office 兼容结论**：本阶段不启用浏览器功能。Chromium/Playwright 在 Docker 默认 seccomp 下可能需要 `--no-sandbox` 或经审查的自定义 profile；当前独立镜像仅提供依赖，不代表浏览器工具已上线。后续 Browser MVP 必须单独验证这一点，禁止公开调试端口。

### 8.2 阶段 1：生命周期审计事件

新增 `src/cygnusx/infrastructure/studio/audit.py`，采用结构化 loguru 事件，不引入第二套数据库审计设施，也不让审计写入失败阻断主流程。事件字段通过 `event` 和 `component=studio_sandbox` 供日志采集器检索：

| 事件 | 已接入位置 | 关键字段 |
| --- | --- | --- |
| `sandbox.create` | 新容器创建成功 | 会话、用户、Agent、请求/授予能力、镜像、容器、CPU/内存/PID、网络模式 |
| `sandbox.rebuild` | 旧容器安全基线不符 | 会话、用户、Agent、能力、镜像、旧容器、重建原因 |
| `sandbox.capability_denied` | Studio 创建请求能力授权失败 | 用户、Agent、请求能力、允许能力、拒绝原因 |
| `sandbox.reuse` | 容器安全与网络校验通过 | 会话、容器、网络/CPU/PID/rootfs/capability/seccomp 基线结果 |
| `sandbox.reclaim` | `stop()` 实际删除容器 | 会话、容器名、回收原因、最近活跃时间、资源峰值占位 |
| `sandbox.quota_exceeded` | sandbox-agent 周期探测超过配额 | 当前使用量、配额；结构化 warning，不阻断 watcher |

### 8.3 阶段 2：工作区配额兜底

由于当前宿主 Docker daemon 不可访问，无法确认 `overlay2 + xfs pquota` 是否可用；本次采用跨文件系统可工作的 **方案 B**：

- `studio.sandbox.workspace_quota_bytes` 默认 10 GiB，设为 `0` 可关闭。
- `workspace_quota_check_interval_seconds` 默认 30 秒。
- Manager 将这两个参数注入容器环境变量。
- sandbox-agent 对工作区递归统计普通文件大小，后台 watcher 记录 `sandbox.quota_exceeded`；`write`、`mkdir`、`rename`、`edit` 等文件变更接口在超过配额时返回 HTTP 413 和 `code=quota_exceeded`。
- 删除大文件后下一次检查恢复正常写入。

该方案不能限制用户代码通过 `/exec` 直接写入文件时的瞬时增长，因此它是跨文件系统兜底而非内核硬配额。生产环境若确认 XFS project quota 可用，应优先增加 Docker/宿主硬配额，并保留 agent 检查作为第二层防线。

### 8.4 隔离层升级触发条件

当业务形态变为“接受未认证输入生成任意代码”，或沙箱正式对外开放多租户不可信执行时，启动 gVisor `runsc`（OCI 运行时直接替换）评估；涉及高敏数据、浏览器下载或强对抗租户时，同时评估 Kata Containers/MicroVM。该条件应触发计划内迁移，而不是等到安全事件后应急响应。

### 8.5 当前验收状态

- [x] seccomp、固定非 root、硬 CPU、内存、PID、cap drop、no-new-privileges、只读 rootfs、tmpfs 已进入创建参数。
- [x] 工作区 uid 10001 权限处理已存在并保留。
- [x] 旧容器安全基线漂移检测和重建已接入。
- [x] capability 拒绝、创建、复用、重建、回收事件已接入代码路径。
- [x] 工作区配额配置、agent watcher 和写操作保护已接入。
- [ ] 生产 Docker inspect：daemon seccomp、存储驱动、实际用户和旧容器存量。
- [ ] Docker 真机 egress T1–T7：当前环境无 Docker daemon 权限，尚未执行。
- [ ] XFS project quota 可用性：需在生产宿主执行 `docker info` 与文件系统探测后决定是否升级为方案 A。
