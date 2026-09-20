# CygnusX 沙箱安全加固实施手册（Codex 施工版）

**版本**：v1.0
**日期**：2026-08-23
**上游依据**：《CygnusX 沙箱架构审查报告 —— 与现阶段主流沙箱方案的对比》（2026-08-23）
**施工对象**：《CygnusX 沙箱增强架构（安全基线与 Capability 路由）》v1.0 已落地的 P0 部分

---

## 1. 背景与目标

架构审查结论：现有设计方向正确，安全基线达到业界"加固容器"层标准；差距不在架构方向，而在层内几个标准件未补齐。本手册把审查报告的行动建议落成 Codex 可执行的四个阶段：

- **阶段 0（止血前置包，最先做）**：seccomp 显式启用 + 容器内非 root 运行。两者都是容器创建参数/镜像层面的低成本改动，不依赖任何架构调整，收益最快。
- **阶段 1**：审计事件埋点进框架层（在 browser/document MVP 之前完成，避免工具上线后审计返工）。
- **阶段 2**：工作区磁盘配额（在 document MVP 之前完成，文档转换类负载最容易写爆磁盘）。
- **阶段 3**：egress 白名单真机集成验证（验收清单中唯一挂起的安全验证项，含 DNS 绕过测试）。

**施工纪律**：

- 验收权在你手里，不接受 Codex 自报通过。每阶段按本手册的验收表逐项人工核对。
- 每个阶段的提示词自包含，可独立粘贴；建议一次只贴一个阶段，验收通过后再进下一阶段。
- Codex 若报告"某能力已存在"，让它给出文件路径证据，你核对后从对应阶段删除该项——不重复建设。

## 2. 施工总览

| 阶段 | 内容 | 改动面 | 预估复杂度 | 前置依赖 |
|---|---|---|---|---|
| 0 | seccomp profile + 非 root 运行 + 架构文档补隔离层升级触发条件 | 容器创建参数、Dockerfile、架构文档 | 低 | 无 |
| 1 | 审计事件埋点（capability 校验 / 创建 / 重建 / 拒绝 / 回收） | StudioSandboxManager、能力校验点、日志设施 | 中 | 阶段 0 验收通过 |
| 2 | 工作区磁盘配额 + 超阈值告警 | StudioSandboxManager 或 sandbox-agent、宿主探测 | 中 | 无（可与阶段 1 并行，但建议串行） |
| 3 | egress 白名单真机集成测试（none 无出站 / 白名单仅经代理 / DNS 绕过） | 集成测试套件 | 中 | 白名单代理已实现 |

---

## 3. 阶段 0：容器加固标准件补齐（止血前置包）

### 3.0 提示词（粘贴给 Codex）

````text
你是一名资深后端/基础设施工程师。项目：CygnusX Studio 会话沙箱（FastAPI + Docker SDK
+ 宿主经 UDS 连接容器内 sandbox-agent）。架构设计文档见
《CygnusX 沙箱增强架构（安全基线与 Capability 路由）》v1.0。

任务：在现有 StudioSandboxManager 与镜像构建体系上补齐两个容器加固标准件，并更新
架构文档。先读现有代码再动手，重点阅读：
- StudioSandboxManager.ensure_running() 及其容器创建参数（当前已设置 nano_cpus、
  mem_limit、pids_limit、cap_drop=ALL、no-new-privileges、只读 rootfs、/tmp tmpfs）
- deploy/studio/ 下的 base/bio/browser-office Dockerfile 与 build.sh
- data/ai/studio.yaml 的 studio.images 配置结构

约束：禁止重构无关代码；不改 capability 路由逻辑；不改 UDS 通信协议；所有改动
标注文件路径与位置。若发现以下任何一项已有实现，立即停止该项并报告代码位置，
不要重复建设。

## 改动项 1：显式启用 seccomp

- 在容器创建参数中显式声明 seccomp（Docker SDK 的 security_opt），使用 Docker 默认
  profile 或落一份自定义 profile 文件到 deploy/studio/ 并在配置中可指向它。
- 先确认现状：当前 daemon 默认 profile 是否已生效（docker info / 容器 inspect 的
  SeccompProfile 字段），把确认结果写进交付说明。
- 注意已知坑：browser-office 镜像内 Chromium/Playwright 在 Docker 默认 seccomp 下
  无法启用自身 sandbox，启动参数需要 --no-sandbox（或改用放开 clone/user namespace
  的自定义 profile）。本阶段只要求：代码能力镜像下 seccomp 生效；browser-office 的
  兼容方案给出结论与 TODO 注释即可，不要求本阶段实现浏览器功能。

## 改动项 2：容器内非 root 运行

- 检查三个镜像的 Dockerfile 与 sandbox-agent 启动方式，确认当前容器内进程身份。
- 目标：sandbox-agent 与会话进程以固定 uid 的非 root 用户运行（镜像内 USER 指令或
  创建容器时 user 参数，二选一，给出你选择的理由）。
- 必须处理 /workspace bind mount 的属主问题：宿主侧会话工作区目录的 uid 要与容器内
  运行用户匹配（创建会话目录时 chown，或镜像内 uid 与宿主约定一致），保证非 root
  后工作区仍可写、/data/platform 仍只读可读。
- 容器复用校验逻辑（ensure_running 里的基线漂移检测）同步加入"运行用户非 root"
  一项，旧容器不符合时按现有逻辑重建。

## 改动项 3：架构文档更新

在《CygnusX 沙箱增强架构》文档中：
- 容器安全基线表补两行：seccomp（实际生效的 profile）与容器内运行用户。
- 后续阶段章节补一条："隔离层升级触发条件：当业务形态变为接受未认证输入生成的
  任意代码、或对外多租户开放时，启动 gVisor（runsc，OCI 直接替换）评估；该触发
  条件应使层级切换成为计划内迁移而非安全事件后的应急响应。"

## 验收（我会人工核对，不接受自报通过）

- [ ] 新建容器 inspect 可见 SeccompProfile 生效、Config.User 非空非 root
- [ ] 会话工作区在非 root 下读写正常（容器内向 /workspace 写文件成功，向 / 或
      /data/platform 写失败）
- [ ] 旧 root 容器被基线校验识别并重建
- [ ] 交付说明包含：daemon 现状确认结果、改动文件清单、browser-office Chromium
      兼容方案结论
````

### 3.1 人工验收 checklist

| # | 操作 | 期望现象 | 不通过时的处理 |
|---|---|---|---|
| 0-1 | 创建一个普通 Studio 会话后，`docker inspect <container>` 查看 `HostConfig.SecurityOpt` 与 `Config.User` | 含 seccomp 条目；User 为非空非 root 值 | 让 Codex 对照改动清单指出为何参数未生效（常见于参数名/SDK 字段错误），修复后重建容器再验 |
| 0-2 | 容器内执行 `id` 与 `touch /workspace/_t && rm /workspace/_t` | 非 root uid；工作区可写 | 检查宿主会话目录属主 uid 与容器内用户是否一致，让 Codex 修 chown/uid 约定 |
| 0-3 | 容器内执行 `touch /etc/_t` 与 `touch /data/platform/_t` | 均拒绝（只读） | 回退该次改动，排查只读 rootfs 与挂载参数是否被改动项 2 意外影响 |
| 0-4 | 构造一个带旧基线（root 运行）的容器后触发会话复用 | 管理器停止并删除旧容器、以新基线重建 | 检查基线漂移检测是否覆盖"运行用户"维度，让 Codex 补上 |
| 0-5 | 阅读架构文档 diff | 基线表新增两行、后续阶段新增触发条件条目，无其他章节被改动 | 文档改动走回头评审，不要带进功能改动一起通过 |

---

## 4. 阶段 1：审计事件埋点进框架层

### 4.0 提示词（粘贴给 Codex）

````text
你是一名资深后端工程师。项目：CygnusX Studio 会话沙箱（FastAPI + Docker SDK +
Redis 租约 + 宿主经 UDS 连接容器内 sandbox-agent）。本阶段任务：在沙箱框架层
埋审计事件，为后续 browser/document 工具的审计要求（所有调用鉴权并写审计日志）
打好地基。

先读现有代码再动手：
- StudioSandboxManager.ensure_running()（容器创建 / 复用校验 / 重建路径）
- capability 授权校验点（studio.sandbox_capabilities 与 ChatSession.sandbox_meta
  的写入与校验处）
- 容器回收 / 会话结束路径
- 平台现有日志与审计基础设施（是否已有审计表 / 结构化日志通道 / 事件总线），
  有则复用，禁止另起一套平行设施；若无，用结构化 JSON 日志落地，字段按下表。

约束：不改任何业务行为，只增加事件记录；事件写入失败不得阻断会话主流程
（记录降级日志即可）；所有改动标注文件路径。

## 事件清单（5 个埋点）

| 事件 | 触发点 | 必填字段 |
|---|---|---|
| sandbox.create | 新容器创建成功 | session_id, user_id, agent_id, capabilities_requested, capabilities_granted, image, container_id, limits(cpu/mem/pids), network_mode |
| sandbox.rebuild | 旧容器基线不符被重建 | 同上 + rebuild_reason（缺哪项基线） |
| sandbox.capability_denied | 未授权 capability 请求被拒绝 | session_id, user_id, agent_id, capabilities_requested, policy_result |
| sandbox.reuse | 复用既有容器 | session_id, container_id, baseline_check(passed 项列表) |
| sandbox.reclaim | 容器停止/回收 | session_id, container_id, reclaim_reason(idle/manual/error), last_active_at, resource_peak(可留空，字段先占位) |

## 验收（我会人工核对）

- [ ] 触发一次未授权 browser 能力请求，审计通道出现 capability_denied 事件且字段完整
- [ ] 创建、复用、重建、回收各触发一次，四类事件均出现
- [ ] 人为制造事件写入失败（如临时改坏日志路径），会话主流程不受影响
- [ ] 交付说明给出事件样例（每类一条真实输出）
````

### 4.1 人工验收 checklist

| # | 操作 | 期望现象 | 不通过时的处理 |
|---|---|---|---|
| 1-1 | 以未授权 browser 能力创建会话 | 业务错误返回 + capability_denied 事件落盘，字段含 policy_result | 检查校验点是否只拒不记，让 Codex 在拒绝分支补埋点 |
| 1-2 | 正常创建 → 复用 → 触发重建 → 结束会话 | 四类事件各至少一条，session_id 可串联 | 缺哪类查哪条路径，重点怀疑 rebuild 与 reclaim 两个低频分支 |
| 1-3 | 临时破坏事件写入（改日志路径为只读）再创建会话 | 会话正常创建，降级日志出现 | 事件写入阻断主流程是设计违例，必须修 |
| 1-4 | 对照字段表抽查事件内容 | 无 user_id/agent_id 混用、capabilities 两个字段不混（requested vs granted） | 字段口径问题就地修订，不并入下一阶段 |

---

## 5. 阶段 2：工作区磁盘配额

### 5.0 提示词（粘贴给 Codex）

````text
你是一名资深后端/基础设施工程师。项目：CygnusX Studio 会话沙箱。现状：会话唯一
可写持久面是 /workspace bind mount，无容量上限，单个会话可写满宿主磁盘。
任务：为 /workspace 增加每会话磁盘配额与超阈值行为。

第一步只做探测，不写实现代码：确认部署目标的宿主文件系统与 Docker 存储驱动
（overlay2 + xfs project quota 是否可用 --storage-opt size；ext4 下该选项不可用），
把探测结论先报告给我，然后按下面优先级选一档实现并说明理由：

- 方案 A（优先）：overlay2 + xfs pquota 可用时，用 --storage-opt size=N 实现
  硬配额（配额值进 studio.yaml 安全参数，默认建议 10 GiB，可配）。
- 方案 B（兜底）：宿主不支持时，在 sandbox-agent 增加周期 stat（如每 30s），
  工作区超阈值后拒绝后续写入类调用并上报告警事件（复用阶段 1 的审计通道，
  事件名 sandbox.quota_exceeded）。

约束：不改动既有 bind mount 路径与权限模型；配额参数进配置、有默认值、可关；
所有改动标注文件路径。若已有配额相关实现，立即报告位置，不重复建设。

## 验收（我会人工核对）

- [ ] 报告含宿主探测结论与方案选择理由
- [ ] 容器内向 /workspace 写入超过配额的文件：方案 A 下写入被内核拒绝（No space
      left）；方案 B 下写类调用被拒绝且出现 quota_exceeded 事件
- [ ] 配额参数在 studio.yaml 可配、改配置新建会话生效
- [ ] 未超配额的正常读写无任何行为变化
````

### 5.1 人工验收 checklist

| # | 操作 | 期望现象 | 不通过时的处理 |
|---|---|---|---|
| 2-1 | 阅读探测结论 | 明确给出宿主 fs/存储驱动、所选方案及理由 | 探测结论含糊（"应该支持"类措辞）打回，要求贴 `docker info` 关键输出 |
| 2-2 | 把配额临时调小（如 100 MiB），新建会话，容器内 `dd if=/dev/zero of=/workspace/big bs=1M count=200` | 方案 A：dd 报 No space left；方案 B：写调用被拒 + quota_exceeded 事件 | 区分"配额没生效"与"生效点不对"（如限制落在镜像层而非工作区），让 Codex 定位后修 |
| 2-3 | 超配额后删除大文件再继续写 | 恢复正常可写 | 方案 A 通常自动恢复；方案 B 若不能恢复，要求补解除逻辑 |
| 2-4 | 正常小文件读写回归 | 无行为变化、无性能可感退化 | 方案 B 检查 stat 周期是否过于频繁 |

---

## 6. 阶段 3：egress 白名单真机集成验证

### 6.0 提示词（粘贴给 Codex）

````text
你是一名资深后端/基础设施工程师。项目：CygnusX Studio 会话沙箱。架构设计为
"网络默认 none；可选 per-session internal network + egress proxy，白名单必须由
代理强制执行"。架构文档验收清单中"Docker 真机和白名单出口集成验证"尚未完成。
本阶段只做验证与缺陷修复，不重新设计网络方案。

任务：编写并执行一组真机集成测试（可在专用测试环境执行），逐项验证：

## 测试清单

| # | 场景 | 预期 |
|---|---|---|
| T1 | network=none 会话，容器内 curl 任意外网域名 | 失败（无网络栈） |
| T2 | network=none 会话，容器内访问宿主内网地址（如网关 IP、169.254.169.254 元数据端点） | 失败 |
| T3 | 白名单会话，经代理访问白名单域名 | 成功，代理侧有命中日志 |
| T4 | 白名单会话，经代理访问非白名单域名 | 被代理拒绝，有拒绝日志 |
| T5 | 白名单会话，绕过代理直连外网 IP（curl --noproxy '*' http://<外网IP>） | 失败（证明白名单由网络层强制而非仅靠代理自觉） |
| T6 | 白名单会话，DNS 绕过：dig @8.8.8.8、DoH 请求（curl https://1.1.1.1/dns-query） | 失败或仅解析不影响出站（给出结论） |
| T7 | 白名单会话，代理按会话隔离：会话 A 的代理凭据不能用于会话 B | 失败且有日志 |

T5/T6/T7 是重点——它们验证"白名单由代理强制执行"这条设计声明是否成立。
发现的每个缺陷按"缺陷描述 → 复现命令 → 根因 → 修复 → 复测通过"的格式记录；
修复改动标注文件路径，不改与缺陷无关的代码。

## 交付

- 测试脚本位置与执行方式（可重复跑）
- 七项测试的逐项结果（含原始命令输出）
- 缺陷修复记录（如有）
````

### 6.1 人工验收 checklist

| # | 操作 | 期望现象 | 不通过时的处理 |
|---|---|---|---|
| 3-1 | 亲自重跑测试脚本 | 七项全绿，且输出与 Codex 报告一致 | 结果不可复现 = 不通过，先查环境差异 |
| 3-2 | 重点核对 T5/T6/T7 的原始输出 | 确实失败/拒绝，而非"没跑" | 绕过成功的任一项都是高危缺陷，修复前不进入 browser MVP |
| 3-3 | 检查缺陷修复的 diff | 只动缺陷相关代码，无顺手重构 | 夹带重构的拆出来回退 |
| 3-4 | 更新架构文档验收清单 | "Docker 真机和白名单出口集成验证"勾选 | — |

---

## 7. 风险与回退

| 风险 | 影响 | 应对 |
|---|---|---|
| 非 root 后 /workspace 权限断裂（阶段 0） | 会话无法写工作区，全线受阻 | 阶段 0 单独施工单独验收；保留配置开关可临时回退 root 运行（仅排障用，默认关） |
| Chromium 与 seccomp 冲突（阶段 0 已预告） | browser MVP 启动失败 | 本阶段只要结论与 TODO；Browser MVP 阶段用 --no-sandbox 或自定义 profile 落地 |
| 宿主不支持 xfs pquota（阶段 2） | 方案 A 不可用 | 自动落到方案 B（agent 周期 stat），这正是要求先探测的原因 |
| 白名单被绕过（阶段 3 发现） | 设计声明不成立 | 阻断后续 browser/document MVP，先修网络层；必要时降级为全网 none |
| 审计写入性能（阶段 1） | 高频事件拖慢主流程 | 事件异步入队；本阶段量级极小，暂不引入外部组件 |

## 8. 总验收（全部阶段完成后）

- [ ] 架构文档容器安全基线表与实现一致（seccomp、非 root、磁盘配额三项已补）
- [ ] 五类审计事件在真实会话生命周期中全部可串联
- [ ] 阶段 3 七项测试脚本纳入回归，后续网络相关改动必须重跑
- [ ] 架构文档已写入 gVisor 升级触发条件（阶段 0 改动项 3）
- [ ] 旧容器在新基线下全部完成重建，无存量的 root/无 seccomp 容器在跑
