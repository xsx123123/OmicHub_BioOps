# 远程连接 + Agent/Notebook 运行机制 — 代码地图（供其他 agent 核查）

> 本文所有路径均相对仓库根 `/home/zj/zj_code_libarary/OpenAI4S/`。
> 行号基于 2026-09-18 的 main（a6955de4），供定位用，以符号名为准。

## A. 远程连接（两条独立通道）

### A1. Share/Relay — 向外发布只读会话（出站 WSS 隧道）

| 文件 | 职责 | 关键锚点 |
|---|---|---|
| `openai4s/share/tunnel.py` | daemon 侧 `TunnelClient`：单条重连 WSS 出站连接、share 注册、credit 流控、分发 relay 转发的请求到只读 handler | class `TunnelClient`（约 373 行文件） |
| `openai4s/share/ws_client.py` | 纯 stdlib WebSocket 客户端：TLS 校验 `wss://`、101-only 握手、client-masked 帧 | — |
| `openai4s/share/protocol.py` | daemon⇄relay 线协议：JSON 控制帧（白名单类型+大小上限）、二进制数据帧（6 字节头分块）、请求头白名单 | — |
| `openai4s/share/relay.py` | 公开侧无状态 relay（`openai4s relay serve`）：token 指纹认证发布者（takeover/conflict/CAS）、按 host label 路由访客、GET/HEAD-only+统一 404 | — |
| `openai4s/share/fetch.py` | `share import` 的 SSRF-hardened 下载（仅 HTTPS、逐跳重校验、私网拒绝、流式大小上限） | — |
| `openai4s/server/share_projection.py` | 不可变只读快照的构建 | — |
| `openai4s/server/ws_frames.py` | 两端共用的 hardened RFC 6455 codec（daemon 会拒的帧 relay 不接受） | — |

核查要点：隧道不出入站端口；relay 只转发到只读 ShareRouter；帧解析两端同源。

### A2. 远程计算 — `host.compute`（BYOC GPU / SSH）

| 文件 | 职责 | 关键锚点 |
|---|---|---|
| `openai4s/sdk/host.py` | agent 在 cell 内调用的 `host.compute(...)` 等 facade | `llm`:548, `delegate`:739, `submit_output`:821, `bash`:896 |
| `openai4s/compute/manager.py` | `ComputeManager`：`byoc:*` 与 `ssh:*` 双传输、并发上限、argv 一处组装 | class:931, `submit`:2029, `result`:2469, `reconcile`:1548 |
| `openai4s/compute/registry.py` | 特化 SSH 能力目录持久化（agent 只能用用户提供的 alias） | — |
| `openai4s/compute/states.py` | job 状态机 + 转移表；`unknown` 刻意为 live；终态不可重开 | — |
| `openai4s/compute/manifest.py` | harvest 产物 `{path,size,sha256}` + 对账（glob 落空 → exit 0 仍判 failed） | — |
| `openai4s_compute_provider/` | 远端运行的 stdlib-only 受限 helper：`__main__.py`（两级 secret scrub，先基线后 provider 前缀，凭据走 stdin/fd-3）、`_resident.py`、`_channel.py` | — |
| `openai4s/security/byoc_confinement.py` | OS 边界包住 helper；helper 内部探测 anchor，不成立退出 71 | — |
| `openai4s/host/remote_science.py` | 解析能力时如实探测远端可用性 | — |

核查要点：job 行先于 submit 落盘；`reconcile()` 只报告绝不重提交；幂等键 + UNIQUE 索引；凭据不进环境变量、confinement 是验证的而非假设的。

## B. Agent 运行科学代码（双循环 → cell 执行历史）

| 文件 | 职责 | 关键锚点 |
|---|---|---|
| `openai4s/agent/engine.py` | 外循环：每轮只路由 tool 批次 / FinalizeAction / 围栏 Cell | — |
| `openai4s/kernel/manager.py` | host 侧 `Kernel`（spawn worker、JSON-per-line 协议、cell 内 host_call→host_response 同步 RPC） | class `Kernel`:238, `execute`:520（"Run one cell; block until the response frame, servicing host_calls"）, host_call 路由:633-634, `_service_host_call`:928, `interrupt`:830, `_spawn`:331 |
| `openai4s/kernel/worker.py` | Python worker 子进程；per-cell `compile(code,"<kernel:N>")`、getrusage、dlopen guard；`_HOST_CALL_LOCK` 单帧事务 | — |
| `openai4s/kernel/r_worker.R` + `r_kernel.py` | R 对称实现：`sh -c 'exec Rscript --vanilla r_worker.R 3>&1 4<&0'`，协议帧走 fd3/fd4 | — |
| `openai4s/kernel/supervisor.py` | worker 身份/生命周期 + ABA 安全 watchdog；绝不读协议帧 | — |
| `openai4s/execution/coordinator.py`（+ `openai4s/server/execution_coordinator.py`） | FIFO 执行协调、依赖模型、watchdog；CLI 与 Web 共用 | — |
| `openai4s/host_dispatch.py` + `openai4s/host/` | 共享权限/审批/审计路由信封；handler 软失败契约 `{"error": msg}` | — |
| `openai4s/security/sandbox.py` | Seatbelt/bubblewrap，`auto|enforce|off`，enforce 失败即拒 | — |

核查要点：cell 内 `host.llm/host.delegate/host.compute` 的同步 RPC 是 tool_use 架构做不到的；manager 每次重启 bump generation；touching kernel 后必跑 `tests/test_kernel.py`。

## C. Notebook 前端（实时投影 + 导出）

| 文件 | 职责 | 关键锚点 |
|---|---|---|
| `frontend/src/features/notebook/cells.ts` | cell merge、`_seenChunks` 重放去重、per-cell 输出 signal（按 `producing_cell_id` 只写目标 cell）、完成态 memoize | — |
| `frontend/src/features/notebook/Notebook.tsx` | CellList / kernel chips / REPL / `renderNotebook` / `cellNode` | — |
| `frontend/src/features/notebook/kernel.ts` | `_kc` 三个失效源（`kernel_status`/`turnDone`/`nbSwitchEnv`）、`notebookOnTurnDone` | — |
| `frontend/src/features/notebook/scroll.ts` | 120px scroll-follow + reading-delay gate | — |
| `frontend/src/features/notebook/chrome.ts` | traceback 高亮（XSS 有测试）、live figures、inline tables | — |
| `frontend/src/features/notebook/install.ts` | WS handler 装配；每个 WS 类型单 handler；`notebook_cell_finished` 同时结算 chat live card | — |
| `openai4s/server/gateway.py` | 类型化 WS 事件：`notebook_cell_chunk`:1483、`notebook_cell_finished`:1540/1546、`producing_cell_id`:1605、`kernel_status`:3766/4829/7563 | — |
| `openai4s/server/notebook_export.py` | 从不可变执行历史确定性导出 `.ipynb`（Python/R 语言元数据、hash、zip） | `_LANGUAGE` 常量表 |
| `openai4s/adapters/jupyter/bridge.py` | 可选 Jupyter KernelSpec 桥：ipykernel/ZeroMQ 仅在真正启动时导入；刻意独立于 Web 会话 | — |

核查要点：R cell 与 Python cell 共用同一套 UI/协议；notebook UI 是历史投影，`.ipynb` 从历史重导出；增量渲染（chunk 只写目标 cell）是性能关键。

## D. 对比结论（与"我的平台"孰优）

本实现的相对优势（可移植的）：增量流式渲染状态机、类型化 WS 事件+单 handler、不可变执行历史=投影、Python/R 同协议、job 先落盘+幂等+如实终态。
本实现相对过重的部分：双循环（cell 内 host RPC）、604 skills、多代 env 治理——若目标平台只是"agent 跑代码 + notebook 展示"，内循环 RPC 与 BYOC helper 可省。
