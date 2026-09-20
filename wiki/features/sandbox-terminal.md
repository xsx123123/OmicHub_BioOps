# 云端沙盒终端

CygnusX 提供按会话创建、会话结束后回收的隔离终端。用户在浏览器中使用 xterm.js，平台通过
WebSocket 代理连接到容器内 ttyd；终端容器不直接暴露宿主机端口。

## 当前架构

```text
浏览器终端 → FastAPI WebSocket 代理 → 终端容器 ttyd
                     ↓
                 Docker Manager
                     ↓
用户私有 workspace / raw_data / temp 挂载目录
```

Web 容器和终端容器通过专用沙盒网络通信。平台会为每个会话建立隔离容器，并只挂载当前用户可访问的
目录；其他用户工作区不会挂载到该终端。

## 配置与镜像

| 配置 | 作用 |
| --- | --- |
| `tool_configs/terminal/terminal_config.yaml` | 会话生命周期、资源、网络和存储策略；支持热重载 |
| `tool_configs/terminal/terminal_images.yaml` | 前端可选择的终端镜像清单；支持热重载 |
| `tool_configs/terminal/docker/` | 默认终端镜像、Zsh 和终端环境配置 |

默认镜像提供 Zsh、Oh My Zsh、Oh My Posh 以及常用生信命令行工具。镜像和资源配额应由管理员维护；
用户无法在浏览器中任意指定宿主机路径或 Docker 参数。

## 安全边界

- 非 root 运行、只读根文件系统、能力收缩与资源上限。
- 仅绑定当前用户的 `workspace`、`raw_data` 和 `temp` 目录。
- 会话数、空闲超时、最大生命周期和容器回收由配置控制。
- 终端容器位于专用网络；网络可访问范围按部署策略收紧。
- 管理员应通过日志和审计记录排查异常，不应把交互终端暴露给未认证用户。

## 常见问题

创建失败时，先检查沙盒镜像、Docker Socket 权限、专用网络和用户目录权限；运行中断时，再检查空闲
超时、资源限制和会话生命周期。部署侧排查见 [问题排查](../operations/troubleshooting)。
